# youtube_auth.py
import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Scopes needed for managing YouTube playlists
SCOPES = ["https://www.googleapis.com/auth/youtube"]

def get_youtube_credentials():
    """
    Handles OAuth flow for YouTube and returns a Credentials object.
    Caches credentials in token.pickle so you don’t have to log in every time.
    """
    creds = None

    # token.pickle stores the user's access + refresh tokens
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)

    # if there are no valid credentials, start the login flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # load the OAuth client secret downloaded from Google Cloud Console
            flow = InstalledAppFlow.from_client_secrets_file(
                "/Users/louiscao/Desktop/PROJECT LIST/playlist_converter/backend/utils/client_secret.json", SCOPES
            )
            creds = flow.run_local_server(port=8888, host="127.0.0.1")

        # save credentials for next time
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

    return creds
