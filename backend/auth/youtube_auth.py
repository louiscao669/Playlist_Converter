import pickle
from pathlib import Path

from google_auth_oauthlib.flow import Flow, InstalledAppFlow
from google.auth.transport.requests import Request

from backend.utils import config

# backend/auth → backend
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_CLIENT_SECRET = _BACKEND_DIR / "utils" / "client_secret.json"
# Single stable path so Flask finds the token no matter what cwd you use
_TOKEN_PATH = _BACKEND_DIR / "token.pickle"

# Scopes needed for managing YouTube playlists
SCOPES = ["https://www.googleapis.com/auth/youtube"]


class YouTubeAuthRequired(Exception):
    """Raised when the user needs to complete Google/YouTube OAuth in the browser."""


def _redirect_uri():
    raw = (config.YOUTUBE_REDIRECT_URI or "").strip()
    if raw:
        return raw
    return f"{config.FRONTEND_URL}/youtube-callback"


def _load_credentials():
    if not _TOKEN_PATH.exists():
        return None
    with open(_TOKEN_PATH, "rb") as token:
        return pickle.load(token)


def _save_credentials(creds):
    with open(_TOKEN_PATH, "wb") as token:
        pickle.dump(creds, token)


def _new_flow():
    if not _CLIENT_SECRET.is_file():
        raise FileNotFoundError(f"Missing Google OAuth client file: {_CLIENT_SECRET}")
    return Flow.from_client_secrets_file(
        str(_CLIENT_SECRET),
        scopes=SCOPES,
        redirect_uri=_redirect_uri(),
    )


def get_auth_url():
    flow = _new_flow()
    auth_url, _state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state="youtube",
    )
    return auth_url


def request_tokens(auth_code):
    if not auth_code:
        raise ValueError("Missing authorization code")
    flow = _new_flow()
    flow.fetch_token(code=auth_code)
    creds = flow.credentials
    _save_credentials(creds)
    return creds


def get_youtube_credentials():
    """
    Returns a valid YouTube Credentials object.

    Web/API requests should redirect the user's browser through `/api/youtube/auth`
    when this raises YouTubeAuthRequired; do not open a browser on the Flask host.
    Caches credentials in backend/token.pickle.
    """
    creds = _load_credentials()

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                raise YouTubeAuthRequired("YouTube session expired") from e
        else:
            raise YouTubeAuthRequired("YouTube not connected")

        _save_credentials(creds)

    return creds


def get_youtube_credentials_interactive():
    """
    Local-dev helper for scripts that still want the old server-side browser flow.
    Flask endpoints should use get_youtube_credentials() instead.
    """
    creds = _load_credentials()
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not _CLIENT_SECRET.is_file():
                raise FileNotFoundError(f"Missing Google OAuth client file: {_CLIENT_SECRET}")
            flow = InstalledAppFlow.from_client_secrets_file(str(_CLIENT_SECRET), SCOPES)
            creds = flow.run_local_server(
                port=config.YOUTUBE_OAUTH_PORT,
                host="127.0.0.1",
                open_browser=True,
            )
        _save_credentials(creds)
    return creds
