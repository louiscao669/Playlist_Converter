# Playlist Converter

Convert playlists between Spotify and YouTube/YouTube Music with a Flask API and a React UI.

The React UI can run in two modes:

- **Website** at `http://localhost:3000`.
- **Browser extension panel** injected into `https://open.spotify.com` and `https://music.youtube.com`, similar to the Simplify sidebar/panel pattern.

## Run locally

Install dependencies:

```bash
npm install
pip install -r requirements.txt
```

Start the Flask API:

```bash
python backend/main.py
```

Start the website UI:

```bash
npm start
```

## Build the Spotify / YouTube Music browser extension

Build the unpacked extension:

```bash
npm run build:extension
```

Then load `frontend/build-extension` in Chrome or Edge:

1. Open `chrome://extensions` or `edge://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select `frontend/build-extension`.
5. Open Spotify Web Player or YouTube Music and use the **Convert playlists** floating button.

Clicking the extension toolbar icon also toggles the in-page panel when you are on Spotify or YouTube Music.

## OAuth notes for extension mode

The injected panel still talks to the local Flask API at `http://localhost:8888` by default. Keep the API running while using the extension.

Spotify login cannot safely happen inside an injected iframe, so the extension opens Spotify OAuth in a normal browser tab, watches for the configured redirect URL, exchanges the code with Flask, stores the result in extension storage, and closes the login tab.

For local development, configure Spotify with one of the repo's usual redirect URLs, for example:

- `http://localhost:3000/`
- `http://localhost:8888/`

Set `SPOTIFY_REDIRECT_URI` in your environment to match the exact redirect URI registered in the Spotify Developer Dashboard.

Google / YouTube auth now follows the same browser redirect pattern:

- Add `http://localhost:3000/youtube-callback` to your Google Cloud OAuth client redirect URIs.
- Set `YOUTUBE_REDIRECT_URI=http://localhost:3000/youtube-callback` if you need a custom value.

The app stores Google credentials in `backend/token.pickle` and refreshes them when Google provides a refresh token. YouTube Music browser-header renewal is still available from the panel for accounts where ytmusicapi needs browser cookies.