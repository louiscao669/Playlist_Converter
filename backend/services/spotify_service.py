import requests
from backend.utils.logger import get_logger

logger = get_logger(__name__)

class SpotifyService:
    def __init__(self, access_token):
        self.access_token = access_token
        self.base_url = "https://api.spotify.com/v1"

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
        headers = {"Authorization": f"Bearer {self.access_token}"}
        logger.info("Fetching tracks for playlist: %s", playlist_id)
        
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            tracks = []
            for item in response.json().get("items", []):
                track = item.get("track")
                if track:  # safeguard against missing data
                    tracks.append({
                        "name": track["name"],
                        "artist": track["artists"][0]["name"],
                        "album": track["album"]["name"]
                    })
            logger.debug("Fetched %d tracks from playlist %s", len(tracks), playlist_id)
            return tracks
        except Exception as e:
            logger.error("Failed to fetch tracks: %s", e)
            return []
