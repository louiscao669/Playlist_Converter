import json
import os
import sys
import tempfile
import threading
import uuid
from pathlib import Path

# Allow `python3 backend/main.py`: imports are `backend.*`, so the repo root must be on sys.path.
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import requests
from flask import Flask, Response, jsonify, redirect, request, stream_with_context
from backend.services.spotify_service import (
    SPOTIFY_LIKED_SONGS_PLAYLIST_ID,
    SpotifyService,
)
from backend.services.youtube_service import YouTubeService
from backend.services.ytmusic_service import (
    YTMusicService,
    browser_headers_json_write_path,
    normalize_browser_headers_dict,
)
from backend.auth.youtube_auth import (
    YouTubeAuthRequired,
    get_youtube_credentials,
)
import backend.auth.youtube_auth as youtube_auth
import backend.auth.spotify_auth as spotify_auth
from backend.utils import config
from backend.utils.logger import get_logger
from flask_cors import CORS

try:
    from ytmusicapi.exceptions import YTMusicServerError
except ImportError:
    YTMusicServerError = None  # type: ignore

app = Flask(__name__)
CORS(
    app,
    allow_headers=["Content-Type", "Authorization", "X-Ytmusic-Headers-Upload-Token"],
)
logger = get_logger(__name__)

_capture_jobs: dict[str, dict] = {}
_capture_jobs_lock = threading.Lock()


def _atomic_write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix="browser_headers_", suffix=".json", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _spotify_import_events(data):
    """Yield progress / complete / error dicts for Spotify import (NDJSON stream or sync consumer)."""
    title = data.get("title", "Imported from YouTube")
    description = data.get("description", "Imported from YouTube Music")
    raw_tracks = data.get("tracks") or []
    existing_spotify_pid = (data.get("spotify_playlist_id") or "").strip()

    access_token = (data.get("access_token") or "").strip() or None
    if not access_token:
        try:
            access_token = spotify_auth.get_access_token()
        except ValueError:
            yield {"type": "error", "error": "Spotify not connected", "status": 401}
            return

    yield {"type": "progress", "phase": "init", "pct": 2, "message": "Starting…"}
    spotify = SpotifyService(access_token)

    if existing_spotify_pid:
        yield {
            "type": "progress",
            "phase": "create",
            "pct": 6,
            "message": "Adding to your existing Spotify playlist…",
        }
        playlist_id = existing_spotify_pid
    else:
        yield {
            "type": "progress",
            "phase": "create",
            "pct": 6,
            "message": "Creating Spotify playlist…",
        }
        try:
            playlist_id = spotify.create_playlist(name=title, description=description)
        except requests.HTTPError as e:
            detail = ""
            if e.response is not None:
                try:
                    detail = e.response.text[:2000]
                except Exception:
                    pass
            yield {
                "type": "error",
                "error": getattr(e.response, "reason", None) or str(e),
                "status": getattr(e.response, "status_code", None) or 502,
                "details": detail,
            }
            return
        if not playlist_id:
            yield {"type": "error", "error": "Failed to create Spotify playlist", "status": 500}
            return

    total_in = len(raw_tracks)
    logger.info(
        "Spotify import: searching for up to %d tracks (playlist %s)…",
        total_in,
        playlist_id,
    )
    uris = []
    try:
        for i, t in enumerate(raw_tracks, start=1):
            if i == 1 or i % 25 == 0 or i == total_in:
                logger.info(
                    "Spotify import progress: %d / %d searches (uris so far: %d)",
                    i,
                    total_in,
                    len(uris),
                )
            q = f"{t.get('name', '')} {t.get('artist', '')}".strip()
            if total_in:
                pct = 10 + int(78 * i / total_in)
            else:
                pct = 88
            pct = min(88, max(8, pct))
            yield {
                "type": "progress",
                "phase": "search",
                "current": i,
                "total": total_in,
                "matched": len(uris),
                "pct": pct,
                "message": f"Searching Spotify ({i}/{max(total_in, 1)})…",
            }
            if not q:
                continue
            uri = spotify.search_track_uri(q)
            if uri:
                uris.append(uri)
    except requests.HTTPError as e:
        detail = ""
        if e.response is not None:
            try:
                detail = e.response.text[:2000]
            except Exception:
                pass
        logger.exception("Spotify HTTP error during import-tracks")
        yield {
            "type": "error",
            "error": getattr(e.response, "reason", None) or str(e),
            "status": getattr(e.response, "status_code", None) or 502,
            "details": detail,
        }
        return

    deduped = []
    seen_uri = set()
    for u in uris:
        if u not in seen_uri:
            seen_uri.add(u)
            deduped.append(u)

    yield {
        "type": "progress",
        "phase": "add",
        "pct": 92,
        "message": f"Adding {len(deduped)} tracks to Spotify…",
        "matched": len(deduped),
        "total": total_in,
    }
    logger.info(
        "Spotify import: adding %d unique tracks to playlist %s…",
        len(deduped),
        playlist_id,
    )
    try:
        added = spotify.add_tracks_to_playlist(playlist_id, deduped)
    except requests.HTTPError as e:
        detail = ""
        if e.response is not None:
            try:
                detail = e.response.text[:2000]
            except Exception:
                pass
        yield {
            "type": "error",
            "error": getattr(e.response, "reason", None) or str(e),
            "status": getattr(e.response, "status_code", None) or 502,
            "details": detail,
        }
        return

    logger.info("Spotify import: finished (added count=%s)", added)
    yield {
        "type": "complete",
        "result": {
            "spotify_playlist_id": playlist_id,
            "tracks_added": added,
            "tracks_matched": len(deduped),
            "tracks_total": len(raw_tracks),
            "used_existing_playlist": bool(existing_spotify_pid),
        },
    }


def _youtube_add_events(data):
    """Yield progress / complete / error for adding videos to a YouTube playlist."""
    playlist_id = data.get("playlist_id")
    tracks = data.get("tracks") or []
    if not playlist_id:
        yield {"type": "error", "error": "playlist_id required", "status": 400}
        return

    try:
        creds = get_youtube_credentials()
    except YouTubeAuthRequired:
        try:
            auth_url = youtube_auth.get_auth_url()
        except Exception:
            auth_url = None
        yield {
            "type": "error",
            "error": "YouTube not connected",
            "status": 401,
            "auth_required": True,
            "auth_url": auth_url,
        }
        return
    youtube = YouTubeService(creds)
    n = len(tracks)
    added = []
    try:
        for idx, track in enumerate(tracks, start=1):
            pct = 5 + int(90 * idx / max(n, 1))
            yield {
                "type": "progress",
                "phase": "youtube_add",
                "current": idx,
                "total": n,
                "matched": len(added),
                "pct": min(96, max(4, pct)),
                "message": f"Adding to YouTube ({idx}/{max(n, 1)})…",
            }
            query = f"{track.get('name', '')} {track.get('artist', '')}".strip()
            video_id = youtube.search_video(query)
            if video_id:
                youtube.add_video_to_playlist(playlist_id, video_id)
                added.append(query)
    except Exception as e:
        logger.exception("YouTube add failed")
        yield {"type": "error", "error": str(e), "status": 500}
        return

    yield {"type": "complete", "result": {"added": added}}


@app.route("/")
def spotify_oauth_forward():
    """
    Spotify redirects the *browser* to REDIRECT_URI with ?code=...
    That URL must be your React app (see SPOTIFY_REDIRECT_URI).
    If REDIRECT_URI was set to this API (localhost:8888), this forwards to the UI.
    """
    q = request.query_string.decode()
    base = config.FRONTEND_URL
    return redirect(f"{base}/?{q}" if q else f"{base}/")


@app.route("/callback")
def spotify_oauth_forward_callback():
    q = request.query_string.decode()
    base = config.FRONTEND_URL
    return redirect(f"{base}/?{q}" if q else f"{base}/")


@app.route("/youtube-callback")
def youtube_oauth_forward_callback():
    q = request.query_string.decode()
    base = config.FRONTEND_URL
    return redirect(f"{base}/youtube-callback?{q}" if q else f"{base}/")


def _youtube_auth_required_response(status: int = 401):
    try:
        auth_url = youtube_auth.get_auth_url()
    except Exception as e:
        logger.warning("Could not build YouTube auth URL: %s", e)
        return jsonify({"error": "YouTube auth is not configured"}), 500
    return (
        jsonify(
            {
                "error": "YouTube not connected",
                "auth_required": True,
                "auth_url": auth_url,
            }
        ),
        status,
    )


# --- Spotify Auth ---
@app.route("/api/spotify/auth", methods=["GET"])
def spotify_auth_url():
    scopes = (
        "playlist-read-private playlist-read-collaborative "
        "playlist-modify-public playlist-modify-private "
        "user-library-read"
    )
    auth_url = spotify_auth.get_auth_url(scopes)
    # print(auth_url)
    return jsonify({"auth_url": auth_url})


@app.route("/api/spotify/oauth-settings", methods=["GET"])
def spotify_oauth_settings():
    """What Flask uses for Spotify OAuth (must match Spotify Dashboard redirect URIs)."""
    return jsonify(
        {
            "spotify_redirect_uri": config.SPOTIFY_REDIRECT_URI,
            "frontend_url": config.FRONTEND_URL,
            "note": "Add spotify_redirect_uri exactly in Spotify app settings. Open the React app at the same host (localhost vs 127.0.0.1). Restart Flask after editing .env.",
        }
    )


# --- YouTube / Google Auth ---
@app.route("/api/youtube/auth", methods=["GET"])
def youtube_auth_url():
    try:
        return jsonify({"auth_url": youtube_auth.get_auth_url()})
    except Exception as e:
        logger.warning("YouTube auth URL failed: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/youtube/oauth-settings", methods=["GET"])
def youtube_oauth_settings():
    return jsonify(
        {
            "youtube_redirect_uri": config.YOUTUBE_REDIRECT_URI
            or f"{config.FRONTEND_URL}/youtube-callback",
            "frontend_url": config.FRONTEND_URL,
            "note": "Add youtube_redirect_uri exactly in Google Cloud OAuth settings.",
        }
    )


@app.route("/api/youtube/callback", methods=["POST"])
def youtube_callback():
    code = (request.json or {}).get("code")
    try:
        youtube_auth.request_tokens(code)
    except ValueError as e:
        logger.warning("YouTube callback failed: %s", e)
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.exception("YouTube callback failed")
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


# --- Spotify Callback ---
@app.route("/api/spotify/callback", methods=["POST"])
def spotify_callback():
    code = request.json.get("code")
    try:
        spotify_auth.request_tokens(code)
    except ValueError as e:
        logger.warning("Spotify callback failed: %s", e)
        return jsonify({"error": str(e)}), 400
    access_token = spotify_auth.get_access_token()
    spotify = SpotifyService(access_token)
    playlists = spotify.get_user_playlists()
    if not playlists:
        logger.error("No playlists found on Spotify.")
    liked_songs_total = None
    try:
        liked_songs_total = spotify.get_saved_tracks_total()
    except Exception as e:
        logger.info("Liked songs count unavailable (re-auth may be needed): %s", e)
    return jsonify(
        {
            "playlists": playlists,
            "access_token": access_token,
            "liked_songs_total": liked_songs_total,
        }
    )


@app.route("/api/spotify/session", methods=["GET"])
def spotify_session():
    try:
        access_token = spotify_auth.get_access_token()
    except ValueError:
        return jsonify({"error": "Spotify not connected"}), 401
    spotify = SpotifyService(access_token)
    playlists = spotify.get_user_playlists()
    liked_songs_total = None
    try:
        liked_songs_total = spotify.get_saved_tracks_total()
    except Exception as e:
        logger.info("Liked songs count unavailable: %s", e)
    return jsonify(
        {
            "playlists": playlists,
            "access_token": access_token,
            "liked_songs_total": liked_songs_total,
        }
    )


# --- Spotify Tracks ---
@app.route("/api/spotify/tracks", methods=["POST"])
def get_spotify_tracks():
    data = request.json or {}
    try:
        access_token = data.get("access_token") or spotify_auth.get_access_token()
    except ValueError:
        return jsonify({"error": "Spotify not connected"}), 401
    playlist_id = (data.get("playlist_id") or "").strip()
    if not playlist_id:
        return jsonify({"error": "playlist_id is required"}), 400

    spotify = SpotifyService(access_token)
    try:
        if playlist_id == SPOTIFY_LIKED_SONGS_PLAYLIST_ID:
            tracks = spotify.get_saved_tracks()
        else:
            tracks = spotify.get_playlist_tracks(playlist_id)
    except requests.HTTPError as e:
        resp = e.response
        sc = resp.status_code if resp is not None else None
        detail = ""
        try:
            if resp is not None:
                j = resp.json()
                detail = (j.get("error") or {}).get("message") or str(j)
        except (TypeError, ValueError, AttributeError):
            detail = resp.text[:300] if resp is not None else ""
        if playlist_id == SPOTIFY_LIKED_SONGS_PLAYLIST_ID and sc in (401, 403):
            return jsonify(
                {
                    "error": "Spotify would not return your Liked songs. "
                    "Log out of Spotify in this app, connect again, and accept the Library permission.",
                    "details": detail,
                }
            ), 403 if sc == 403 else 401
        return jsonify({"error": "Spotify request failed", "details": detail}), (
            sc if sc in (400, 401, 403, 404) else 502
        )
    return jsonify({"tracks": tracks})


# --- YouTube: list / create playlists ---
@app.route("/api/youtube/playlists", methods=["GET", "POST"])
def youtube_playlists():
    try:
        creds = get_youtube_credentials()
    except YouTubeAuthRequired:
        return _youtube_auth_required_response()
    youtube = YouTubeService(creds)

    if request.method == "GET":
        playlists = youtube.list_my_playlists()
        return jsonify({"playlists": playlists})

    data = request.json or {}
    title = data.get("title", "Converted Playlist")
    desc = data.get("description", "Imported from Spotify")

    playlist_id = youtube.create_playlist(title=title, description=desc)
    return jsonify({"yt_playlist_id": playlist_id})


@app.route("/api/youtube/tracks", methods=["POST"])
def get_youtube_playlist_tracks():
    try:
        creds = get_youtube_credentials()
    except YouTubeAuthRequired:
        return _youtube_auth_required_response()
    youtube = YouTubeService(creds)
    data = request.json or {}
    playlist_id = data["playlist_id"]
    tracks = youtube.get_playlist_tracks(playlist_id)
    return jsonify({"tracks": tracks})


@app.route("/api/ytmusic/playlists", methods=["GET"])
def ytmusic_playlists():
    """Prefer ytmusicapi; fall back to YouTube Data API if the Music backend errors or returns no playlists."""
    ytm_err = None
    playlists = None
    try:
        svc = YTMusicService()
        playlists = svc.list_playlists()
    except ImportError as e:
        return jsonify({"error": str(e)}), 501
    except Exception as e:
        ytm_err = str(e)
        if YTMusicServerError is not None and isinstance(e, YTMusicServerError):
            logger.warning("ytmusic playlists: %s", e)
        elif isinstance(e, (FileNotFoundError, ValueError)):
            logger.warning("ytmusic playlists (setup): %s", e)
        else:
            logger.exception("ytmusic playlists failed")

    if playlists:
        return jsonify({"playlists": playlists, "source": "ytmusic"})

    ytm_empty = playlists is not None and len(playlists) == 0
    if ytm_empty:
        logger.warning(
            "ytmusicapi returned 0 playlists (library browse often empty with TV OAuth); "
            "trying YouTube Data API fallback"
        )
        if not ytm_err:
            ytm_err = (
                "ytmusicapi returned an empty playlist list (TV/device OAuth often cannot "
                "browse YouTube Music library)."
            )

    try:
        creds = get_youtube_credentials()
        youtube = YouTubeService(creds)
        fb_playlists = youtube.list_my_playlists()
        if ytm_empty:
            warning = (
                "YouTube Music library listing returned no playlists (common with TV OAuth). "
                "Showing playlists from the YouTube Data API instead (same Google account). "
                "For YouTube Music lists and Liked songs, set YTMUSIC_BROWSER_HEADERS_JSON from "
                "`ytmusicapi browser` and restart Flask."
            )
        else:
            warning = (
                "ytmusicapi failed; using YouTube Data API playlists instead. "
                f"Details: {ytm_err}. "
                "HTTP 400 with OAuth is a known YouTube Music backend issue for many accounts "
                "(ytmusicapi GitHub #813); re-running oauth often does not fix it. "
                "Workaround: run `ytmusicapi browser`, save the headers JSON, set "
                "YTMUSIC_BROWSER_HEADERS_JSON to that path and restart Flask. "
                "Optional: YTMUSIC_LOCATION=US if region errors persist."
            )
        return jsonify(
            {
                "playlists": fb_playlists,
                "source": "youtube_data_api",
                "warning": warning,
            }
        )
    except YouTubeAuthRequired:
        return _youtube_auth_required_response()
    except Exception as fe:
        logger.exception("YouTube playlist fallback failed")
        return jsonify({"error": f"{ytm_err}; fallback: {fe}"}), 502


@app.route("/api/ytmusic/browser-headers-config", methods=["GET"])
def ytmusic_browser_headers_upload_config():
    upload = bool((config.YTMUSIC_HEADERS_UPLOAD_SECRET or "").strip())
    playwright_mod = False
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401

        playwright_mod = True
    except ImportError:
        pass
    return jsonify({"upload_enabled": upload, "playwright_available": playwright_mod})


@app.route("/api/ytmusic/browser-headers", methods=["POST"])
def ytmusic_save_browser_headers():
    """
    Save pasted `ytmusicapi browser` JSON to the file used by YTMUSIC_BROWSER_HEADERS_JSON.
    Requires YTMUSIC_HEADERS_UPLOAD_SECRET and matching X-Ytmusic-Headers-Upload-Token (cookies are secrets).
    """
    secret = (config.YTMUSIC_HEADERS_UPLOAD_SECRET or "").strip()
    if not secret:
        return (
            jsonify(
                {
                    "error": (
                        "Upload disabled. Set YTMUSIC_HEADERS_UPLOAD_SECRET in .env to a long random string, "
                        "restart Flask, then enter the same value below as the upload token."
                    ),
                    "upload_enabled": False,
                }
            ),
            403,
        )
    if (request.headers.get("X-Ytmusic-Headers-Upload-Token") or "").strip() != secret:
        return jsonify({"error": "Invalid or missing upload token."}), 401

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "JSON object required"}), 400
    hdr = body.get("headers") if isinstance(body.get("headers"), dict) else body
    if not isinstance(hdr, dict):
        return jsonify({"error": "Headers must be a JSON object (or { \"headers\": { ... } })"}), 400
    try:
        normalized = normalize_browser_headers_dict(hdr)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    target = browser_headers_json_write_path()
    try:
        _atomic_write_json(target, normalized)
    except OSError as e:
        logger.exception("Failed to write browser headers file")
        return jsonify({"error": f"Could not write file: {e}"}), 500

    try:
        rel = str(target.relative_to(_root))
    except ValueError:
        rel = str(target)
    logger.info("Updated YouTube Music browser headers file at %s", rel)
    note = None
    if not (config.YTMUSIC_BROWSER_HEADERS_JSON or "").strip():
        note = (
            "Set YTMUSIC_BROWSER_HEADERS_JSON=backend/browser_headers.json (or this file's path) "
            "in .env and restart Flask so ytmusicapi loads the new cookies."
        )
    return jsonify({"ok": True, "saved_to": rel, "note": note})


def _ytmusic_capture_worker(job_id: str) -> None:
    from backend.services.ytmusic_playwright_capture import run_playwright_capture

    jid = job_id

    def cb(msg: str) -> None:
        with _capture_jobs_lock:
            if jid in _capture_jobs:
                _capture_jobs[jid]["message"] = msg

    try:
        with _capture_jobs_lock:
            _capture_jobs[jid]["status"] = "running"
        headers = run_playwright_capture(status=cb)
        target = browser_headers_json_write_path()
        _atomic_write_json(target, headers)
        try:
            rel = str(target.relative_to(_root))
        except ValueError:
            rel = str(target)
        logger.info("Playwright capture wrote browser headers to %s", rel)
        with _capture_jobs_lock:
            _capture_jobs[jid].update(
                {"status": "done", "saved_to": rel, "message": "Saved."}
            )
        if not (config.YTMUSIC_BROWSER_HEADERS_JSON or "").strip():
            with _capture_jobs_lock:
                _capture_jobs[jid]["note"] = (
                    "Set YTMUSIC_BROWSER_HEADERS_JSON=backend/browser_headers.json (or this path) "
                    "in .env and restart Flask if ytmusicapi is not already using this file."
                )
    except Exception as e:
        logger.exception("Playwright browser capture failed")
        with _capture_jobs_lock:
            if jid in _capture_jobs:
                _capture_jobs[jid].update({"status": "failed", "error": str(e)})


@app.route("/api/ytmusic/capture-browser-session", methods=["POST"])
def ytmusic_capture_browser_session_start():
    """
    Opens headed Chromium on the Flask host; user signs in at music.youtube.com.
    Poll GET with job_id until status is done or failed. Requires YTMUSIC_HEADERS_UPLOAD_SECRET.
    """
    secret = (config.YTMUSIC_HEADERS_UPLOAD_SECRET or "").strip()
    if not secret:
        return jsonify({"error": "Set YTMUSIC_HEADERS_UPLOAD_SECRET to enable capture."}), 403
    if (request.headers.get("X-Ytmusic-Headers-Upload-Token") or "").strip() != secret:
        return jsonify({"error": "Invalid upload token."}), 401
    with _capture_jobs_lock:
        for j in _capture_jobs.values():
            if j.get("status") in ("pending", "running"):
                return (
                    jsonify(
                        {
                            "error": "A capture is already running on the server. "
                            "Finish or wait for it to time out, then try again."
                        }
                    ),
                    409,
                )
        job_id = str(uuid.uuid4())
        _capture_jobs[job_id] = {"status": "pending", "message": "Starting…"}
    threading.Thread(target=_ytmusic_capture_worker, args=(job_id,), daemon=True).start()
    return jsonify(
        {
            "job_id": job_id,
            "message": "A Chromium window should open on the computer running Flask. "
            "Log in to YouTube Music there; this page will update when cookies are saved.",
        }
    )


@app.route("/api/ytmusic/capture-browser-session", methods=["GET"])
def ytmusic_capture_browser_session_status():
    job_id = (request.args.get("job_id") or "").strip()
    if not job_id:
        return jsonify({"error": "job_id query parameter required"}), 400
    with _capture_jobs_lock:
        job = _capture_jobs.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job_id"}), 404
    out: dict = {"status": job.get("status"), "message": job.get("message", "")}
    if job.get("status") == "done":
        out["saved_to"] = job.get("saved_to")
        if job.get("note"):
            out["note"] = job["note"]
    if job.get("status") == "failed":
        out["error"] = job.get("error", "failed")
    return jsonify(out)


@app.route("/api/ytmusic/tracks", methods=["POST"])
def ytmusic_playlist_tracks():
    data = request.json or {}
    playlist_id = data.get("playlist_id")
    if not playlist_id:
        return jsonify({"error": "playlist_id required"}), 400

    ytm_err = None
    try:
        svc = YTMusicService()
        tracks = svc.get_playlist_tracks_for_spotify(playlist_id)
        return jsonify({"tracks": tracks, "source": "ytmusic"})
    except ImportError as e:
        return jsonify({"error": str(e)}), 501
    except Exception as e:
        ytm_err = str(e)
        if YTMusicServerError is not None and isinstance(e, YTMusicServerError):
            logger.warning("ytmusic tracks: %s", e)
        elif isinstance(e, (FileNotFoundError, ValueError)):
            logger.warning("ytmusic tracks (setup): %s", e)
        else:
            logger.exception("ytmusic tracks failed")

    try:
        creds = get_youtube_credentials()
        youtube = YouTubeService(creds)
        tracks = youtube.get_playlist_tracks(playlist_id)
        return jsonify(
            {
                "tracks": tracks,
                "source": "youtube_data_api",
                "warning": (
                    f"ytmusicapi failed ({ytm_err}); using YouTube playlist item titles/channels instead. "
                    "If OAuth returns HTTP 400, try YTMUSIC_BROWSER_HEADERS_JSON (see /api/ytmusic/playlists warning text)."
                ),
            }
        )
    except YouTubeAuthRequired:
        return _youtube_auth_required_response()
    except Exception as fe:
        logger.exception("YouTube tracks fallback failed")
        return jsonify({"error": f"{ytm_err}; fallback: {fe}"}), 502


@app.route("/api/spotify/import-tracks", methods=["POST"])
def import_tracks_to_spotify():
    data = request.get_json(silent=True) or {}
    if request.args.get("stream") == "1":

        def generate():
            try:
                for evt in _spotify_import_events(data):
                    yield json.dumps(evt, ensure_ascii=False) + "\n"
            except Exception as e:
                logger.exception("import-tracks stream failed")
                yield json.dumps({"type": "error", "error": str(e), "status": 500}) + "\n"

        return Response(
            stream_with_context(generate()),
            mimetype="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    err_payload = None
    ok_payload = None
    try:
        for evt in _spotify_import_events(data):
            if evt.get("type") == "error":
                err_payload = evt
            elif evt.get("type") == "complete":
                ok_payload = evt.get("result")
    except Exception as e:
        logger.exception("import-tracks failed")
        return jsonify({"error": str(e)}), 500
    if err_payload:
        status = int(err_payload.get("status") or 500)
        body = {"error": err_payload.get("error", "Import failed")}
        if err_payload.get("details"):
            body["details"] = err_payload["details"]
        return jsonify(body), status
    return jsonify(ok_payload or {})


# --- Add YouTube Tracks ---
@app.route("/api/youtube/add", methods=["POST"])
def add_tracks_to_youtube():
    data = request.get_json(silent=True) or {}
    if request.args.get("stream") == "1":

        def generate():
            try:
                for evt in _youtube_add_events(data):
                    yield json.dumps(evt, ensure_ascii=False) + "\n"
            except Exception as e:
                logger.exception("youtube add stream failed")
                yield json.dumps({"type": "error", "error": str(e), "status": 500}) + "\n"

        return Response(
            stream_with_context(generate()),
            mimetype="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    err_payload = None
    ok_payload = None
    try:
        for evt in _youtube_add_events(data):
            if evt.get("type") == "error":
                err_payload = evt
            elif evt.get("type") == "complete":
                ok_payload = evt.get("result")
    except Exception as e:
        logger.exception("youtube add failed")
        return jsonify({"error": str(e)}), 500
    if err_payload:
        return jsonify({"error": err_payload.get("error", "Add failed")}), int(
            err_payload.get("status") or 500
        )
    return jsonify(ok_payload or {"added": []})


if __name__ == "__main__":
    app.run(port=8888, debug=True, host="localhost")
