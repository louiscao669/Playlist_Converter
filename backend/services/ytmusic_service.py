"""
YouTube Music metadata via ytmusicapi (OAuth). Used for YouTube Music → Spotify.
"""
import json
import re
from pathlib import Path
from typing import Any, Optional

from backend.utils import config
from backend.utils.logger import get_logger

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_oauth_json_path() -> Path:
    """Find oauth.json from env or common locations."""
    candidates = []
    raw = getattr(config, "YTMUSIC_OAUTH_JSON", None) or ""
    if raw.strip():
        p = Path(raw.strip())
        candidates.append(p if p.is_absolute() else (_PROJECT_ROOT / p))
    candidates.extend(
        [
            _PROJECT_ROOT / "backend" / "utils" / "oauth.json",
            _PROJECT_ROOT / "backend" / "oauth.json",
            _PROJECT_ROOT / "oauth.json",
            Path.cwd() / "oauth.json",
        ]
    )
    tried = []
    for path in candidates:
        tried.append(str(path))
        if path.is_file():
            return path.resolve()
    raise FileNotFoundError(
        "ytmusic OAuth file (oauth.json) not found. Searched: "
        + "; ".join(tried)
        + ". Run `ytmusicapi oauth` from the project folder, then move oauth.json to "
        "backend/oauth.json, or set YTMUSIC_OAUTH_JSON to its full path."
    )


def _ytm_location():
    return (getattr(config, "YTMUSIC_LOCATION", None) or "").strip()


def _ytm_language():
    return (getattr(config, "YTMUSIC_LANGUAGE", None) or "en").strip() or "en"


def _resolve_browser_headers_path() -> Optional[Path]:
    """
    Path to headers JSON from `ytmusicapi browser` or Playwright capture.

    If YTMUSIC_BROWSER_HEADERS_JSON is set, that path is used (file must exist).
    If unset but backend/browser_headers.json exists, use it so capture/paste works without .env.
    """
    raw = getattr(config, "YTMUSIC_BROWSER_HEADERS_JSON", None) or ""
    if (raw or "").strip():
        p = Path(raw.strip())
        if not p.is_absolute():
            p = _PROJECT_ROOT / p
        if not p.is_file():
            raise FileNotFoundError(
                f"YTMUSIC_BROWSER_HEADERS_JSON file not found: {p.resolve()}"
            )
        return p.resolve()
    default = (_PROJECT_ROOT / "backend" / "browser_headers.json").resolve()
    if default.is_file():
        logger.info(
            "YTMUSIC_BROWSER_HEADERS_JSON unset; loading browser headers from %s",
            default,
        )
        return default
    return None


def _cookie_header_from_browser_headers(headers: dict[str, Any]) -> tuple[str, str]:
    """Return (key_used, cookie_value); normalize to a single 'cookie' key when present."""
    val = ""
    keys_to_drop = []
    for k, v in headers.items():
        if str(k).lower() == "cookie":
            keys_to_drop.append(k)
            if isinstance(v, str) and v.strip():
                val = v
    if keys_to_drop:
        for k in keys_to_drop:
            del headers[k]
        headers["cookie"] = val
    return ("cookie", val)


def _ensure_secure_3papisid_cookie(headers: dict[str, Any]) -> dict[str, Any]:
    """
    ytmusicapi requires __Secure-3PAPISID in the Cookie string. Some DevTools copies
    only include __Secure-1PAPISID; values are usually identical for youtube.com.
    """
    out = dict(headers)
    _, cookie = _cookie_header_from_browser_headers(out)
    if not cookie.strip():
        return out
    if re.search(r"(?:^|;)\s*__Secure-3PAPISID\s*=", cookie, re.I):
        return out
    m = re.search(r"(?:^|;)\s*__Secure-1PAPISID\s*=\s*([^;]+)", cookie, re.I)
    if not m:
        return out
    val = m.group(1).strip()
    sep = "; " if cookie.strip().rstrip(";") else ""
    patched = f"{cookie.rstrip('; ')}{sep}__Secure-3PAPISID={val}"
    out["cookie"] = patched
    logger.info(
        "browser headers: added __Secure-3PAPISID from __Secure-1PAPISID (copy was incomplete)"
    )
    return out


def _load_browser_headers_for_ytmusic(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError("browser headers JSON must be an object")
    return _ensure_secure_3papisid_cookie(raw)


def browser_headers_json_write_path() -> Path:
    """
    Target file for pasted browser headers (must match YTMUSIC_BROWSER_HEADERS_JSON when set).
    If unset, defaults to backend/browser_headers.json under the project root.
    """
    raw = (getattr(config, "YTMUSIC_BROWSER_HEADERS_JSON", None) or "").strip()
    if raw:
        p = Path(raw.strip())
        return (p if p.is_absolute() else (_PROJECT_ROOT / p)).resolve()
    return (_PROJECT_ROOT / "backend" / "browser_headers.json").resolve()


def normalize_browser_headers_dict(data: Any) -> dict[str, Any]:
    """
    Validate and normalize headers dict from `ytmusicapi browser` (adds __Secure-3PAPISID if needed).
    """
    if not isinstance(data, dict):
        raise ValueError("Headers must be a JSON object")
    out: dict[str, Any] = {}
    for k, v in data.items():
        if not isinstance(k, str):
            raise ValueError("Header keys must be strings")
        if v is None:
            continue
        if isinstance(v, bool):
            out[k] = "true" if v else "false"
        elif isinstance(v, (int, float)):
            out[k] = str(v)
        elif isinstance(v, str):
            out[k] = v
        else:
            raise ValueError(f"Unsupported JSON type for header {k!r}")
    cookie = ""
    for k, v in out.items():
        if k.lower() == "cookie" and isinstance(v, str):
            cookie = v
            break
    if not cookie.strip():
        raise ValueError(
            "Missing non-empty 'cookie' field — paste the full JSON file from `ytmusicapi browser`."
        )
    return _ensure_secure_3papisid_cookie(dict(out))


class YTMusicService:
    """Thin wrapper around ytmusicapi.YTMusic with playlist listing + track rows for Spotify."""

    def __init__(self):
        try:
            from ytmusicapi import YTMusic, OAuthCredentials
            from ytmusicapi.exceptions import YTMusicServerError
        except ImportError as e:
            raise ImportError("Install ytmusicapi: pip install ytmusicapi") from e

        self._YTMusicServerError = YTMusicServerError

        loc = _ytm_location()
        lang = _ytm_language()

        browser_path = _resolve_browser_headers_path()
        if browser_path:
            logger.info(
                "ytmusicapi using browser headers %s (OAuth skipped; TV client env not required)",
                browser_path,
            )
            hdr = _load_browser_headers_for_ytmusic(browser_path)
            self._client = YTMusic(hdr, language=lang, location=loc)
            return

        oauth_path = _resolve_oauth_json_path()
        cid = config.YTMUSIC_CLIENT_ID
        csec = config.YTMUSIC_CLIENT_SECRET
        if not cid or not csec:
            raise ValueError(
                "Set YTMUSIC_CLIENT_ID and YTMUSIC_CLIENT_SECRET in .env "
                '(Google Cloud OAuth client type "TVs and Limited Input devices"), '
                "or set YTMUSIC_BROWSER_HEADERS_JSON to a file from `ytmusicapi browser`. "
                "TV client id/secret must match what you used for `ytmusicapi oauth`."
            )

        logger.info("ytmusicapi using oauth file %s", oauth_path)
        self._client = YTMusic(
            str(oauth_path),
            oauth_credentials=OAuthCredentials(client_id=cid, client_secret=csec),
            language=lang,
            location=loc,
        )

    def _mobile_then_web(self, label: str, fn_mobile, fn_web):
        """
        ANDROID_MUSIC first (avoids many HTTP 400s on browse), then WEB_REMIX.
        """
        try:
            with self._client.as_mobile():
                return fn_mobile()
        except self._YTMusicServerError as e_m:
            logger.warning("%s: mobile client failed (%s); trying WEB_REMIX", label, e_m)
            try:
                return fn_web()
            except self._YTMusicServerError as e_w:
                logger.warning("%s: web client also failed (%s)", label, e_w)
                raise e_w from e_m

    def list_playlists(self):
        """Library playlists + Liked songs (LM). Shape matches frontend: id, name, tracks.total."""
        ytm = self._client
        out = []
        seen = set()

        def lib_mobile():
            return ytm.get_library_playlists(limit=100)

        def lib_web():
            return ytm.get_library_playlists(limit=100)

        lib = self._mobile_then_web("get_library_playlists", lib_mobile, lib_web)

        for p in lib or []:
            pid = p.get("playlistId")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            try:
                cnt = int(p.get("count") or 0)
            except (TypeError, ValueError):
                cnt = 0
            out.append(
                {
                    "id": pid,
                    "name": p.get("title") or "Untitled",
                    "tracks": {"total": cnt},
                }
            )

        lm_title = "Liked songs"
        lm_total = 0
        try:

            def lm_mobile():
                return ytm.get_playlist("LM", limit=1)

            def lm_web():
                return ytm.get_playlist("LM", limit=1)

            lm = self._mobile_then_web("get_playlist(LM)", lm_mobile, lm_web)
            lm_title = lm.get("title") or lm_title
            lm_total = int(lm.get("trackCount") or 0)
            out.insert(
                0, {"id": "LM", "name": lm_title, "tracks": {"total": lm_total}}
            )
        except self._YTMusicServerError as e:
            logger.warning(
                "Skipping YouTube Music Liked songs (LM): %s. "
                "TV OAuth often gets HTTP 404 for LM; try YTMUSIC_BROWSER_HEADERS_JSON.",
                e,
            )
        except (KeyError, TypeError, ValueError) as e:
            # Web client sometimes returns a sign-in / empty UI (singleColumnBrowseResultsRenderer)
            # instead of playlist markup; ytmusicapi then fails navigation.
            logger.warning(
                "Skipping YouTube Music Liked songs (LM): %s. "
                "Session may not expose the library (re-auth, or use browser headers).",
                e,
            )
        except Exception as e:
            logger.warning("Skipping YouTube Music Liked songs (LM): %s", e)

        return out

    def get_playlist_tracks_for_spotify(self, playlist_id: str):
        """
        Returns [{name, artist}, ...] using YTM catalog fields (title + artists[]).
        """

        def pl_mobile():
            return self._client.get_playlist(playlist_id, limit=None)

        def pl_web():
            return self._client.get_playlist(playlist_id, limit=None)

        pl = self._mobile_then_web(
            f"get_playlist({playlist_id})", pl_mobile, pl_web
        )
        rows = []
        for t in pl.get("tracks") or []:
            if not t:
                continue
            title = t.get("title")
            if title in (None, "", "Deleted video"):
                continue
            artists = t.get("artists") or []
            parts = []
            for a in artists:
                if isinstance(a, dict) and a.get("name"):
                    parts.append(a["name"])
            artist = ", ".join(parts)
            rows.append({"name": title.strip(), "artist": artist.strip()})
        return rows
