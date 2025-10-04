from googleapiclient.discovery import build
from backend.utils.logger import get_logger

logger = get_logger(__name__)

class YouTubeService:
    def __init__(self, credentials):
        """
        credentials: a google.oauth2.credentials.Credentials object
        (loaded from OAuth2 flow or token.json)
        """
        self.youtube = build("youtube", "v3", credentials=credentials)

    def create_playlist(self, title, description=""):
        logger.info("Creating new YouTube playlist: %s", title)
        try:
            request = self.youtube.playlists().insert(
                part="snippet,status",
                body={
                    "snippet": {"title": title, "description": description},
                    "status": {"privacyStatus": "private"},
                }
            )
            response = request.execute()
            playlist_id = response["id"]
            logger.debug("Created playlist ID: %s", playlist_id)
            return playlist_id
        except Exception as e:
            logger.error("Failed to create playlist: %s", e)
            return None

    def search_video(self, query):
        logger.info("Searching YouTube for: %s", query)
        try:
            request = self.youtube.search().list(
                part="snippet",
                q=query,
                type="video",
                maxResults=1
            )
            response = request.execute()
            if response.get("items"):
                video_id = response["items"][0]["id"]["videoId"]
                logger.debug("Found video ID: %s", video_id)
                return video_id
            return None
        except Exception as e:
            logger.error("Failed to search video: %s", e)
            return None

    def add_video_to_playlist(self, playlist_id, video_id):
        logger.info("Adding video %s to playlist %s", video_id, playlist_id)
        try:
            request = self.youtube.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {
                            "kind": "youtube#video",
                            "videoId": video_id,
                        },
                    }
                },
            )
            response = request.execute()
            logger.debug("Added video: %s", response)
            return response
        except Exception as e:
            logger.error("Failed to add video to playlist: %s", e)
            return None
