import re
import time

import requests
from backend.utils.logger import get_logger

logger = get_logger(__name__)

# Virtual playlist id for Spotify → YouTube: reads `/v1/me/tracks` (requires `user-library-read`).
SPOTIFY_LIKED_SONGS_PLAYLIST_ID = "__spotify_liked_songs__"


class SpotifyService:
    def __init__(self, access_token):
        self.access_token = access_token
        self.base_url = "https://api.spotify.com/v1"
        # Pacing derived from Spotify 429 + Retry-After (no fixed per-track sleep).
        self.adaptive_gap_sec = 0.0

    def _bump_adaptive_gap_from_retry_after(self, retry_after_sec: float) -> None:
        """
        After a 429, Spotify sends Retry-After (seconds). Use a fraction of that
        as extra spacing before subsequent calls; cap so imports stay reasonable.
        """
        sec = max(0.0, float(retry_after_sec))
        tail = max(0.02, min(sec / 5.0, 0.6))
        self.adaptive_gap_sec = min(max(self.adaptive_gap_sec * 1.15, tail), 1.2)

    def _relax_adaptive_gap(self) -> None:
        """Decay pacing after successful responses."""
        g = self.adaptive_gap_sec
        if g <= 0.0:
            return
        g = g * 0.83 - 0.004
        self.adaptive_gap_sec = g if g > 0.012 else 0.0

    @staticmethod
    def _sanitize_playlist_name(name):
        if not name or not str(name).strip():
            return "Imported"
        n = str(name).replace("\u2014", "-").replace("\u2013", "-").strip()
        n = re.sub(r"[\x00-\x1f\x7f]", "", n)
        return (n[:100] if n else "Imported") or "Imported"

    @staticmethod
    def _sanitize_description(desc):
        if not desc:
            return ""
        d = re.sub(r"[\x00-\x1f\x7f]", "", str(desc))
        return d[:300]

    def _spotify_request(self, method, url, *, params=None, json=None):
        """HTTP request with retries: 429 (Retry-After), transient 5xx, adaptive pacing from 429s."""
        headers = {"Authorization": f"Bearer {self.access_token}"}
        if json is not None:
            headers["Content-Type"] = "application/json"
        backoff_429 = 0.35
        transient_sleep = 0.5
        transient_count = 0
        max_transient = 8
        last = None
        for _ in range(60):
            if self.adaptive_gap_sec > 0:
                time.sleep(self.adaptive_gap_sec)
            last = requests.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json,
                timeout=120,
            )
            if last.status_code == 429:
                transient_count = 0
                ra = last.headers.get("Retry-After")
                try:
                    wait = float(ra)
                except (TypeError, ValueError):
                    wait = min(backoff_429, 60)
                    backoff_429 = min(backoff_429 * 1.35, 55)
                self._bump_adaptive_gap_from_retry_after(wait)
                logger.warning("Spotify 429, sleeping %.1fs", wait)
                time.sleep(wait)
                continue
            if last.status_code in (500, 502, 503, 504):
                transient_count += 1
                if transient_count > max_transient:
                    last.raise_for_status()
                logger.warning(
                    "Spotify %s (transient), retry %d/%d in %.1fs — %s %s",
                    last.status_code,
                    transient_count,
                    max_transient,
                    transient_sleep,
                    method,
                    url,
                )
                time.sleep(transient_sleep)
                transient_sleep = min(transient_sleep * 1.65, 25)
                continue
            transient_count = 0
            self._relax_adaptive_gap()
            last.raise_for_status()
            return last
        last.raise_for_status()
        return last

    @staticmethod
    def _track_dict(track):
        """Shape expected by YouTube add/search: name, artist, album. Skips locals and non-tracks."""
        if not track or not isinstance(track, dict):
            return None
        if track.get("is_local"):
            return None
        if track.get("type") and track.get("type") != "track":
            return None
        artists = track.get("artists") or []
        artist_name = (artists[0] or {}).get("name") if artists else ""
        album = track.get("album") or {}
        album_name = album.get("name") or ""
        name = track.get("name") or ""
        if not name and not artist_name:
            return None
        return {"name": name, "artist": artist_name or "", "album": album_name or ""}

    def get_user_playlists(self):
        url = f"{self.base_url}/me/playlists"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        logger.info("Fetching user playlists from Spotify...")
        
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()  # raises error for 4xx/5xx
            playlists = response.json().get("items", [])
            logger.debug("Received %d playlists", len(playlists))
            return playlists
        except Exception as e:
            logger.error("Failed to fetch playlists: %s", e)
            return []

    def get_playlist_tracks(self, playlist_id):
        url = f"{self.base_url}/playlists/{playlist_id}/tracks"
        logger.info("Fetching tracks for playlist: %s", playlist_id)
        tracks: list[dict] = []
        offset = 0
        limit = 100
        try:
            while True:
                response = self._spotify_request(
                    "GET", url, params={"limit": limit, "offset": offset}
                )
                data = response.json()
                items = data.get("items") or []
                for item in items:
                    row = self._track_dict(item.get("track"))
                    if row:
                        tracks.append(row)
                if not items or len(items) < limit:
                    break
                offset += limit
            logger.debug("Fetched %d tracks from playlist %s", len(tracks), playlist_id)
            return tracks
        except Exception as e:
            logger.error("Failed to fetch tracks: %s", e)
            return []

    def get_saved_tracks_total(self) -> int | None:
        """First page of /me/tracks includes `total` (cheap count for UI)."""
        url = f"{self.base_url}/me/tracks"
        r = self._spotify_request("GET", url, params={"limit": 1, "offset": 0})
        data = r.json()
        try:
            return int(data.get("total", 0))
        except (TypeError, ValueError):
            return None

    def get_saved_tracks(self):
        """All liked/saved tracks (`GET /v1/me/tracks`), paginated. Requires `user-library-read`."""
        url = f"{self.base_url}/me/tracks"
        tracks: list[dict] = []
        offset = 0
        limit = 50
        while True:
            r = self._spotify_request("GET", url, params={"limit": limit, "offset": offset})
            data = r.json()
            items = data.get("items") or []
            for item in items:
                row = self._track_dict(item.get("track"))
                if row:
                    tracks.append(row)
            total = data.get("total")
            try:
                total_i = int(total) if total is not None else len(tracks)
            except (TypeError, ValueError):
                total_i = len(tracks)
            offset += limit
            if not items or offset >= total_i:
                break
        logger.info("Fetched %d saved (liked) tracks from Spotify", len(tracks))
        return tracks

    def get_current_user_id(self):
        url = f"{self.base_url}/me"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json().get("id")
        except Exception as e:
            logger.error("Failed to get Spotify user id: %s", e)
            return None

    def create_playlist(self, name=None, title=None, description="", public=False):
        """Create a playlist. Use `name` or `title` (same field; both accepted)."""
        playlist_name = name if name is not None else title
        if playlist_name is None or (
            isinstance(playlist_name, str) and not playlist_name.strip()
        ):
            playlist_name = "Imported"
        user_id = self.get_current_user_id()
        if not user_id:
            return None
        url = f"{self.base_url}/users/{user_id}/playlists"
        body = {
            "name": self._sanitize_playlist_name(playlist_name),
            "description": self._sanitize_description(description),
            "public": public,
        }
        logger.info("Creating Spotify playlist: %s", body["name"])
        try:
            response = self._spotify_request("POST", url, json=body)
            pid = response.json().get("id")
            logger.debug("Created Spotify playlist id: %s", pid)
            return pid
        except Exception as e:
            logger.error("Failed to create Spotify playlist: %s", e)
            return None

    def search_track_uri(self, query):
        url = f"{self.base_url}/search"
        params = {"q": query, "type": "track", "limit": 1}
        try:
            response = self._spotify_request("GET", url, params=params)
            items = response.json().get("tracks", {}).get("items") or []
            if not items:
                return None
            return items[0].get("uri")
        except requests.HTTPError:
            raise
        except Exception as e:
            logger.error("Spotify search failed for %r: %s", query, e)
            return None

    def add_tracks_to_playlist(self, playlist_id, track_uris):
        if not track_uris:
            return 0
        url = f"{self.base_url}/playlists/{playlist_id}/tracks"
        total = 0
        for i in range(0, len(track_uris), 100):
            batch = track_uris[i : i + 100]
            self._spotify_request("POST", url, json={"uris": batch})
            total += len(batch)
        return total
