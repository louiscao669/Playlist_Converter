# spotify_auth.py
import requests
import base64
import time
from backend.utils import config
from urllib.parse import urlencode

# Load credentials from config or environment
CLIENT_ID = config.SPOTIFY_CLIENT_ID
CLIENT_SECRET = config.SPOTIFY_CLIENT_SECRET
REDIRECT_URI = config.SPOTIFY_REDIRECT_URI


AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

# Store token state
tokens = {
    "access_token": None,
    "refresh_token": None,
    "expires_at": None
}


# Step 1: Generate auth URL for user login
def get_auth_url(scopes):
    """
    Build Spotify OAuth2 login URL.
    User visits this link → logs in → redirected back to redirect_uri.
    """
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": scopes  # e.g. "playlist-read-private playlist-modify-public"
    }
    url = AUTH_URL + "?" + urlencode(params)
    return url


# Step 2: Exchange authorization code for tokens
def request_tokens(auth_code):
    """
    Exchange authorization code (from redirect) for access + refresh token.
    """
    auth_str = f"{CLIENT_ID}:{CLIENT_SECRET}"
    auth_bytes = auth_str.encode("utf-8")

    headers = {
        "Authorization": "Basic " + base64.b64encode(auth_bytes).decode("utf-8")
    }
    data = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI
    }
    response = requests.post(TOKEN_URL, headers=headers, data=data)
    json_data = response.json()

    tokens["access_token"]  = json_data["access_token"]
    tokens["refresh_token"] = json_data["refresh_token"]
    tokens["expires_at"]    = time.time() + json_data["expires_in"]  # seconds

    return tokens


# Step 3: Refresh token if expired
def refresh_access_token():
    """
    Use refresh_token to get a new access token.
    """
    if tokens["refresh_token"] is None:
        raise ValueError("No refresh token available")

    headers = {
        "Authorization": "Basic " + base64.b64encode(CLIENT_ID + ":" + CLIENT_SECRET)
    }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"]
    }
    response = requests.post(TOKEN_URL, headers=headers, data=data)
    json_data = response.json()

    tokens["access_token"] = json_data["access_token"]
    tokens["expires_at"]   = time.time() + json_data["expires_in"]

    return tokens["access_token"]


# Step 4: Get valid access token
def get_access_token():
    """
    Returns a valid access token, refreshing if necessary.
    """
    if tokens["access_token"] is None:
        raise ValueError("User not logged in yet")

    if time.time() >= tokens["expires_at"]:
        return refresh_access_token()

    return tokens["access_token"]
