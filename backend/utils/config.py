from pathlib import Path

from dotenv import load_dotenv
import os

# Project root .env first, then backend/utils/.env with override so local edits
# in backend/utils/.env win (avoids "I changed .env but Flask still uses old redirect").
_root = Path(__file__).resolve().parents[2]
load_dotenv(_root / ".env")
load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

# Access environment variables
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")

# Where the React app runs (used if Spotify redirects to Flask by mistake)
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")

YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REDIRECT_URI = os.getenv("YOUTUBE_REDIRECT_URI")

# Loopback port for Google OAuth (must match an "Authorized redirect URI" on a *Web* client,
# or use a "Desktop" OAuth client JSON with an "installed" block instead).
def _int_env(name, default):
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _float_env(name, default):
    raw = os.getenv(name, str(default)).strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


YOUTUBE_OAUTH_PORT = _int_env("YOUTUBE_OAUTH_PORT", 9090)

# YouTube Data API v3: pace calls (especially Spotify→YouTube: search.list is ~100 units each).
YOUTUBE_API_MIN_INTERVAL_SEC = _float_env("YOUTUBE_API_MIN_INTERVAL_SEC", 0.55)
YOUTUBE_API_EXTRA_AFTER_SEARCH_SEC = _float_env("YOUTUBE_API_EXTRA_AFTER_SEARCH_SEC", 1.2)
YOUTUBE_API_RATE_RETRY_SLEEP_SEC = _float_env("YOUTUBE_API_RATE_RETRY_SLEEP_SEC", 12.0)
# Retries only for userRateLimitExceeded / rateLimitExceeded (not daily quotaExceeded).
YOUTUBE_API_QUOTA_MAX_RETRIES = _int_env("YOUTUBE_API_QUOTA_MAX_RETRIES", 2)

# Persist Spotify→YouTube search.query → video_id to skip repeat search.list (~100 quota units each).
def _bool_env_default_true(name: str) -> bool:
    raw = os.getenv(name, "").strip()
    if not raw:
        return True
    return raw.lower() not in ("0", "false", "no", "off")


YOUTUBE_SEARCH_CACHE_ENABLED = _bool_env_default_true("YOUTUBE_SEARCH_CACHE_ENABLED")
YOUTUBE_SEARCH_CACHE_PATH = os.getenv("YOUTUBE_SEARCH_CACHE_PATH", "").strip() or None
YOUTUBE_SEARCH_CACHE_MAX_ENTRIES = _int_env("YOUTUBE_SEARCH_CACHE_MAX_ENTRIES", 8000)

# ytmusicapi: OAuth (TV client) or browser headers — see ytmusic_service / main fallback warnings
YTMUSIC_OAUTH_JSON = os.getenv("YTMUSIC_OAUTH_JSON", "").strip() or None
YTMUSIC_CLIENT_ID = os.getenv("YTMUSIC_CLIENT_ID", "").strip() or None
YTMUSIC_CLIENT_SECRET = os.getenv("YTMUSIC_CLIENT_SECRET", "").strip() or None
YTMUSIC_LOCATION = os.getenv("YTMUSIC_LOCATION", "").strip() or None
# Workaround when OAuth returns HTTP 400 (common since ~2025; see ytmusicapi GitHub #813):
# run `ytmusicapi browser`, then set path to the generated JSON (e.g. backend/browser.json).
YTMUSIC_BROWSER_HEADERS_JSON = os.getenv("YTMUSIC_BROWSER_HEADERS_JSON", "").strip() or None
# If set, POST /api/ytmusic/browser-headers accepts pasted JSON when X-Ytmusic-Headers-Upload-Token matches.
YTMUSIC_HEADERS_UPLOAD_SECRET = os.getenv("YTMUSIC_HEADERS_UPLOAD_SECRET", "").strip() or None
YTMUSIC_LANGUAGE = os.getenv("YTMUSIC_LANGUAGE", "en").strip() or "en"

SECRET_KEY = os.getenv("SECRET_KEY", "defaultsecret")
