import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from backend.utils import config
from backend.utils.logger import get_logger

logger = get_logger(__name__)

_yt_pace_lock = threading.Lock()
_yt_last_request_mono = 0.0

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_yt_search_cache_lock = threading.Lock()
_yt_search_cache: dict[str, str] = {}
_yt_search_cache_loaded = False


def _normalize_search_cache_key(q: str) -> str:
    s = (q or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s[:420] if s else ""


def _search_cache_file() -> Path:
    raw = (config.YOUTUBE_SEARCH_CACHE_PATH or "").strip()
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = _BACKEND_DIR / path
        return path
    return _BACKEND_DIR / "data" / "yt_search_cache.json"


def _cache_load_unlocked() -> None:
    global _yt_search_cache_loaded, _yt_search_cache
    if _yt_search_cache_loaded:
        return
    _yt_search_cache_loaded = True
    path = _search_cache_file()
    if not path.is_file():
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            for k, v in raw.items():
                if isinstance(k, str) and isinstance(v, str) and k and v:
                    _yt_search_cache[k] = v
    except Exception as e:
        logger.warning("YouTube search cache read failed: %s", e)


def _cache_prune_unlocked() -> None:
    max_e = max(200, int(config.YOUTUBE_SEARCH_CACHE_MAX_ENTRIES))
    if len(_yt_search_cache) <= max_e:
        return
    target = max(max_e * 3 // 4, max_e - 500)
    while len(_yt_search_cache) > target:
        _yt_search_cache.pop(next(iter(_yt_search_cache)))


def _cache_persist_unlocked() -> None:
    path = _search_cache_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_yt_search_cache, f, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(path)


_QUOTA_REASONS = frozenset(
    ("quotaExceeded", "dailyLimitExceeded", "quotaLimitExceeded")
)


def _classify_youtube_http_error(err: HttpError) -> tuple[bool, bool]:
    """Return (daily_quota_or_project_cap, burst_rate_limited)."""
    quota = False
    rate = False
    try:
        body = json.loads((err.content or b"").decode("utf-8"))
        for sub in body.get("error", {}).get("errors", []) or []:
            r = sub.get("reason") or ""
            if r in _QUOTA_REASONS:
                quota = True
            if r in ("userRateLimitExceeded", "rateLimitExceeded"):
                rate = True
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        raw = (err.content or b"").decode("utf-8", errors="replace")
        if any(x in raw for x in _QUOTA_REASONS):
            quota = True
        if "userRateLimitExceeded" in raw or "rateLimitExceeded" in raw:
            rate = True
    return quota, rate


class YouTubeService:
    def __init__(self, credentials):
        """
        credentials: a google.oauth2.credentials.Credentials object
        (loaded from OAuth2 flow or token.json)
        """
        self.youtube = build("youtube", "v3", credentials=credentials)

    def _pace(self) -> None:
        """Minimum spacing between YouTube Data API calls (process-wide)."""
        gap = max(0.0, float(config.YOUTUBE_API_MIN_INTERVAL_SEC))
        global _yt_last_request_mono
        with _yt_pace_lock:
            now = time.monotonic()
            wait = _yt_last_request_mono + gap - now
            if wait > 0:
                time.sleep(wait)
            _yt_last_request_mono = time.monotonic()

    def _execute_request(
        self,
        request_factory: Callable[[], Any],
        *,
        after_success_sleep: float = 0.0,
    ) -> Any:
        """
        Paced execute() with retries only on burst rate limits.
        Daily quota (quotaExceeded, etc.) is not retried — it does not clear after a short sleep.
        """
        max_r = max(0, int(config.YOUTUBE_API_QUOTA_MAX_RETRIES))
        last_err: HttpError | None = None
        for attempt in range(max_r + 1):
            self._pace()
            try:
                out = request_factory().execute()
                extra = max(0.0, float(after_success_sleep))
                if extra > 0:
                    time.sleep(extra)
                return out
            except HttpError as e:
                last_err = e
                quota, rate = _classify_youtube_http_error(e)
                if quota:
                    logger.error(
                        "YouTube Data API daily quota or project cap exceeded — "
                        "waiting will not fix this until quota resets (usually midnight Pacific) "
                        "or you raise the quota in Google Cloud Console. %s",
                        e,
                    )
                    raise
                if not rate or attempt >= max_r:
                    raise
                wait = max(1.0, float(config.YOUTUBE_API_RATE_RETRY_SLEEP_SEC))
                ra = e.resp.get("Retry-After") if e.resp is not None else None
                if ra is not None:
                    try:
                        wait = max(wait, float(ra))
                    except (TypeError, ValueError):
                        pass
                logger.warning(
                    "YouTube rate limit; sleeping %.0fs then retry (attempt %d of up to %d)",
                    wait,
                    attempt + 1,
                    max_r + 1,
                )
                time.sleep(wait)
        if last_err is not None:
            raise last_err
        raise RuntimeError("YouTube execute_request: unreachable")

    def create_playlist(self, title, description=""):
        logger.info("Creating new YouTube playlist: %s", title)
        try:

            def mk():
                return self.youtube.playlists().insert(
                    part="snippet,status",
                    body={
                        "snippet": {"title": title, "description": description},
                        "status": {"privacyStatus": "private"},
                    },
                )

            response = self._execute_request(mk)
            playlist_id = response["id"]
            logger.debug("Created playlist ID: %s", playlist_id)
            return playlist_id
        except Exception as e:
            logger.error("Failed to create playlist: %s", e)
            return None

    def search_video(self, query):
        key = _normalize_search_cache_key(query)
        if not key:
            return None

        if config.YOUTUBE_SEARCH_CACHE_ENABLED:
            with _yt_search_cache_lock:
                _cache_load_unlocked()
                cached = _yt_search_cache.get(key)
            if cached:
                logger.debug("YouTube search.list skipped (cached): %s", key[:120])
                return cached

        logger.info("Searching YouTube for: %s", query)
        try:

            def mk():
                return self.youtube.search().list(
                    part="snippet",
                    q=query,
                    type="video",
                    maxResults=1,
                )

            response = self._execute_request(
                mk,
                after_success_sleep=float(config.YOUTUBE_API_EXTRA_AFTER_SEARCH_SEC),
            )
            if response.get("items"):
                video_id = response["items"][0]["id"]["videoId"]
                logger.debug("Found video ID: %s", video_id)
                if config.YOUTUBE_SEARCH_CACHE_ENABLED:
                    try:
                        with _yt_search_cache_lock:
                            _cache_load_unlocked()
                            _yt_search_cache[key] = video_id
                            _cache_prune_unlocked()
                            _cache_persist_unlocked()
                    except Exception as e:
                        logger.warning("YouTube search cache persist failed: %s", e)
                return video_id
            return None
        except Exception as e:
            logger.error("Failed to search video: %s", e)
            return None

    def add_video_to_playlist(self, playlist_id, video_id):
        logger.info("Adding video %s to playlist %s", video_id, playlist_id)
        try:

            def mk():
                return self.youtube.playlistItems().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "playlistId": playlist_id,
                            "resourceId": {
                                "kind": "youtube#video",
                                "videoId": video_id,
                            },
                        },
                    },
                )

            response = self._execute_request(mk)
            logger.debug("Added video: %s", response)
            return response
        except Exception as e:
            logger.error("Failed to add video to playlist: %s", e)
            return None

    def _playlist_summary(self, playlist_id):
        """Single playlist id → {id, name, tracks.total} for list UI."""
        try:

            def mk():
                return self.youtube.playlists().list(
                    part="snippet,contentDetails", id=playlist_id, maxResults=1
                )

            response = self._execute_request(mk)
            items = response.get("items") or []
            if not items:
                return None
            item = items[0]
            return {
                "id": item["id"],
                "name": item["snippet"]["title"],
                "tracks": {"total": int(item["contentDetails"].get("itemCount", 0))},
            }
        except Exception as e:
            logger.warning("Could not load playlist %s: %s", playlist_id, e)
            return None

    def _related_system_playlists(self, existing_ids):
        """
        playlists.list(mine=true) often omits system lists. The channel's
        relatedPlaylists.likes is the canonical 'Liked videos' list (often LL),
        which is also where YouTube Music thumbs-up tracks appear for many accounts.
        """
        rows = []
        try:

            def mk_ch():
                return self.youtube.channels().list(mine=True, part="contentDetails")

            ch = self._execute_request(mk_ch)
            items = ch.get("items") or []
            if not items:
                return rows
            related = items[0].get("contentDetails", {}).get("relatedPlaylists") or {}
            likes_id = related.get("likes")
            if likes_id and likes_id not in existing_ids:
                row = self._playlist_summary(likes_id)
                if row:
                    rows.append(row)
        except Exception as e:
            logger.warning("Could not read channel relatedPlaylists: %s", e)
        return rows

    def list_my_playlists(self):
        """Return user's YouTube / YouTube Music playlists (same library)."""
        logger.info("Listing user's YouTube playlists...")
        playlists = []
        page_token = None
        try:
            while True:
                pt = page_token

                def mk(pt=pt):
                    return self.youtube.playlists().list(
                        part="snippet,contentDetails",
                        mine=True,
                        maxResults=50,
                        pageToken=pt,
                    )

                response = self._execute_request(mk)
                for item in response.get("items", []):
                    pid = item["id"]
                    title = item["snippet"]["title"]
                    count = int(item["contentDetails"].get("itemCount", 0))
                    playlists.append(
                        {
                            "id": pid,
                            "name": title,
                            "tracks": {"total": count},
                        }
                    )
                page_token = response.get("nextPageToken")
                if not page_token:
                    break

            seen = {p["id"] for p in playlists}
            system_first = self._related_system_playlists(seen)
            merged = system_first + playlists

            logger.debug("Listed %d playlists (incl. system lists)", len(merged))
            return merged
        except Exception as e:
            logger.error("Failed to list playlists: %s", e)
            return []

    def get_playlist_tracks(self, playlist_id):
        """
        Map playlist items to name/artist for Spotify search.
        Uses video title and channel title (YouTube Music often uses * - Topic channels).
        """
        logger.info("Fetching YouTube playlist items: %s", playlist_id)
        tracks = []
        page_token = None
        try:
            while True:
                pt = page_token

                def mk(pt=pt):
                    return self.youtube.playlistItems().list(
                        part="snippet,contentDetails",
                        playlistId=playlist_id,
                        maxResults=50,
                        pageToken=pt,
                    )

                response = self._execute_request(mk)
                for item in response.get("items", []):
                    sn = item.get("snippet") or {}
                    title = sn.get("title")
                    if title in (None, "Deleted video", "Private video"):
                        continue
                    channel = sn.get("videoOwnerChannelTitle") or ""
                    tracks.append({"name": title, "artist": channel})
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
            logger.debug("Fetched %d items from YouTube playlist", len(tracks))
            return tracks
        except Exception as e:
            logger.error("Failed to fetch YouTube playlist items: %s", e)
            return []
