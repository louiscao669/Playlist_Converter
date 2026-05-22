# spotify_auth.py
import base64
import json
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

from backend.utils import config

# Load credentials from config or environment
CLIENT_ID = config.SPOTIFY_CLIENT_ID
CLIENT_SECRET = config.SPOTIFY_CLIENT_SECRET


def _redirect_uri():
    """Always read from config so .env changes apply after Flask restart."""
    uri = (config.SPOTIFY_REDIRECT_URI or "").strip()
    if not uri:
        raise ValueError("SPOTIFY_REDIRECT_URI is missing in .env")
    return uri

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_SPOTIFY_TOKEN_FILE = _BACKEND_DIR / "spotify_tokens.json"

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

# Store token state (also persisted so Flask restarts keep the session)
tokens = {
    "access_token": None,
    "refresh_token": None,
    "expires_at": None,
}


def _basic_auth_header():
    raw = f"{CLIENT_ID}:{CLIENT_SECRET}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _load_tokens_from_disk():
    if not _SPOTIFY_TOKEN_FILE.is_file():
        return
    try:
        with open(_SPOTIFY_TOKEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        tokens["access_token"] = data.get("access_token")
        tokens["refresh_token"] = data.get("refresh_token")
        tokens["expires_at"] = data.get("expires_at")
    except (OSError, json.JSONDecodeError, TypeError):
        pass


def _save_tokens_to_disk():
    try:
        with open(_SPOTIFY_TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "access_token": tokens["access_token"],
                    "refresh_token": tokens["refresh_token"],
                    "expires_at": tokens["expires_at"],
                },
                f,
            )
    except OSError:
        pass


_load_tokens_from_disk()


# Step 1: Generate auth URL for user login
def get_auth_url(scopes):
    """
    Build Spotify OAuth2 login URL.
    User visits this link → logs in → redirected back to redirect_uri.
    """
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": _redirect_uri(),
        "scope": scopes  # e.g. "playlist-read-private playlist-modify-public"
    }
    url = AUTH_URL + "?" + urlencode(params)
    return url


# Step 2: Exchange authorization code for tokens
def request_tokens(auth_code):
    """
    Exchange authorization code (from redirect) for access + refresh token.
    Raises ValueError with a readable message if Spotify returns an error.
    """
    if not auth_code:
        raise ValueError("Missing authorization code")

    headers = {"Authorization": _basic_auth_header()}
    data = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": _redirect_uri(),
    }
    response = requests.post(TOKEN_URL, headers=headers, data=data, timeout=30)
    try:
        json_data = response.json()
    except ValueError:
        json_data = {}

    if response.status_code != 200 or "access_token" not in json_data:
        err = (
            json_data.get("error_description")
            or json_data.get("error")
            or (response.text[:500] if response.text else "")
            or f"HTTP {response.status_code}"
        )
        raise ValueError(
            f"Spotify token exchange failed: {err}. "
            "Check SPOTIFY_REDIRECT_URI matches the URL you use in the browser "
            "(e.g. http://localhost:3000/) and the Spotify app settings exactly."
        )

    tokens["access_token"] = json_data["access_token"]
    if json_data.get("refresh_token"):
        tokens["refresh_token"] = json_data["refresh_token"]
    tokens["expires_at"] = time.time() + int(json_data.get("expires_in", 3600))
    _save_tokens_to_disk()

    return tokens


# Step 3: Refresh token if expired
def refresh_access_token():
    """
    Use refresh_token to get a new access token.
    """
    if tokens["refresh_token"] is None:
        raise ValueError("No refresh token available")

    headers = {"Authorization": _basic_auth_header()}
    data = {
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"]
    }
    response = requests.post(TOKEN_URL, headers=headers, data=data, timeout=30)
    try:
        json_data = response.json()
    except ValueError:
        json_data = {}

    if response.status_code != 200 or "access_token" not in json_data:
        err = (
            json_data.get("error_description")
            or json_data.get("error")
            or (response.text[:500] if response.text else "")
            or f"HTTP {response.status_code}"
        )
        raise ValueError(f"Spotify refresh failed: {err}")

    tokens["access_token"] = json_data["access_token"]
    tokens["expires_at"] = time.time() + int(json_data.get("expires_in", 3600))
    if json_data.get("refresh_token"):
        tokens["refresh_token"] = json_data["refresh_token"]
    _save_tokens_to_disk()

    return tokens["access_token"]


# Step 4: Get valid access token
def get_access_token():
    """
    Returns a valid access token, refreshing if necessary.
    """
    if tokens["access_token"] is None:
        _load_tokens_from_disk()
    if tokens["access_token"] is None:
        raise ValueError("User not logged in yet")

    if tokens["expires_at"] is not None and time.time() >= tokens["expires_at"]:
        return refresh_access_token()

    return tokens["access_token"]
