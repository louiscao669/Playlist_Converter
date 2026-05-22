# youtube_auth.py
import pickle
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from backend.utils import config

# backend/auth → backend
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_CLIENT_SECRET = _BACKEND_DIR / "utils" / "client_secret.json"
# Single stable path so Flask finds the token no matter what cwd you use
_TOKEN_PATH = _BACKEND_DIR / "token.pickle"

# Scopes needed for managing YouTube playlists
SCOPES = ["https://www.googleapis.com/auth/youtube"]


def get_youtube_credentials():
    """
    Handles OAuth for YouTube and returns a Credentials object.
    Caches credentials in backend/token.pickle.
    """
    creds = None

    if _TOKEN_PATH.exists():
        with open(_TOKEN_PATH, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not _CLIENT_SECRET.is_file():
                raise FileNotFoundError(
                    f"Missing Google OAuth client file: {_CLIENT_SECRET}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(_CLIENT_SECRET), SCOPES
            )
            # Port from YOUTUBE_OAUTH_PORT (.env); must match Google Cloud "redirect URI" for Web clients
            creds = flow.run_local_server(
                port=config.YOUTUBE_OAUTH_PORT,
                host="127.0.0.1",
                open_browser=True,
            )

        with open(_TOKEN_PATH, "wb") as token:
            pickle.dump(creds, token)

    return creds
