"""
One-time Google sign-in for YouTube Data API (writes backend/token.pickle).

If your Google OAuth client is type "Web application" and only allows
http://127.0.0.1:8888/ ... you must either:
  (A) Stop Flask, then run with port 8888:
        cd <project root>
        PYTHONPATH=. YOUTUBE_OAUTH_PORT=8888 python backend/oauth_youtube_once.py

  (B) Or in Google Cloud Console add redirect URI http://127.0.0.1:9090/
     (and optionally http://localhost:9090/) then use default 9090 while Flask runs on 8888.

For new projects, prefer an OAuth client of type "Desktop app" and replace
backend/utils/client_secret.json with the downloaded JSON (it contains "installed").
"""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.auth.youtube_auth import get_youtube_credentials

if __name__ == "__main__":
    print("Starting Google OAuth (check your browser)…")
    get_youtube_credentials()
    print("Saved credentials to backend/token.pickle")
