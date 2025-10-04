# main.py
from backend.services.spotify_service import SpotifyService
from backend.services.youtube_service import YouTubeService
from backend.auth.youtube_auth import get_youtube_credentials
import backend.auth.spotify_auth as spotify_auth
from backend.utils.logger import get_logger

logger = get_logger(__name__)

def choose_playlist(playlists):
    """
    Show playlists in terminal and let user pick one.
    """
    print("\nYour Spotify Playlists:")
    for idx, pl in enumerate(playlists, 1):
        print(f"{idx}. {pl['name']} ({pl['tracks']['total']} tracks)")

    choice = int(input("\nEnter the number of the playlist you want to convert: "))
    return playlists[choice - 1]


def main():
    # ===== 1. Setup Spotify =====
    scopes = "playlist-read-private playlist-read-collaborative"
    auth_url = spotify_auth.get_auth_url(scopes)
    print("Please open this URL in your browser and log in:\n", auth_url)
    auth_code = input("Paste the 'code' from the redirect URL here: ").strip()
    spotify_auth.request_tokens(auth_code)
    spotify_access_token = spotify_auth.get_access_token()

    spotify = SpotifyService(spotify_access_token)

    logger.info("Fetching Spotify playlists...")
    playlists = spotify.get_user_playlists()
    if not playlists:
        logger.error("No playlists found on Spotify.")
        return

    # Let user choose
    sp_playlist = choose_playlist(playlists)
    logger.info("Selected Spotify playlist: %s", sp_playlist["name"])

    tracks = spotify.get_playlist_tracks(sp_playlist["id"])
    logger.info("Fetched %d tracks from Spotify", len(tracks))

    # ===== 2. Setup YouTube =====
    creds = get_youtube_credentials()
    youtube = YouTubeService(creds)

    # ===== 3. Create new YouTube playlist =====
    yt_playlist_id = youtube.create_playlist(
        title=f"Converted - {sp_playlist['name']}",
        description="Imported from Spotify"
    )
    if not yt_playlist_id:
        logger.error("Could not create YouTube playlist.")
        return

    # ===== 4. Add tracks to YouTube =====
    for track in tracks:
        search_query = f"{track['name']} {track['artist']}"
        video_id = youtube.search_video(search_query)
        if video_id:
            youtube.add_video_to_playlist(yt_playlist_id, video_id)
            logger.info("Added %s by %s", track['name'], track['artist'])
        else:
            logger.warning("No YouTube result for %s by %s",
                           track['name'], track['artist'])

    logger.info("✅ Playlist transfer complete!")


if __name__ == "__main__":
    main()
