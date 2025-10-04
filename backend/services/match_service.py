def match_tracks_to_youtube(spotify_tracks, youtube_client):
    """
    spotify_tracks: list of dicts with 'name' and 'artist'
    youtube_client: authenticated YouTube API client
    Returns: list of dicts with spotify track and youtube video ID
    """
    matches = []
    for track in spotify_tracks:
        query = f"{track['name']} {track['artist']} official audio"
        search_result = youtube_client.search().list(
            part="snippet",
            q=query,
            type="video",
            maxResults=1
        ).execute()
        video_id = search_result['items'][0]['id']['videoId']
        matches.append({"spotify_track": track, "youtube_id": video_id})
    return matches
