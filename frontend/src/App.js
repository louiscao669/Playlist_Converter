import React, { useEffect, useRef, useState } from "react";
import {
  startSpotifyAuth,
  handleSpotifyCallback,
  getStoredExtensionSpotifyAuth,
  isRunningAsExtension,
  convertPlaylist,
  fetchYoutubePlaylists,
  fetchYtmusicPlaylists,
  fetchYtmusicBrowserHeadersUploadConfig,
  saveYtmusicBrowserHeadersJson,
  startYtmusicPlaywrightCapture,
  getYtmusicCaptureStatus,
  convertYoutubePlaylistToSpotify,
  SPOTIFY_LIKED_SONGS_PLAYLIST_ID,
} from "./services/spotify";
import "./App.css";

const YTM_HEADERS_UPLOAD_TOKEN_KEY = "pc_ytm_headers_upload_token";

const DIRECTION = {
  SPOTIFY_TO_YOUTUBE: "spotify-youtube",
  YOUTUBE_TO_SPOTIFY: "youtube-spotify",
};

function getInitialDirection() {
  if (typeof window === "undefined") {
    return DIRECTION.SPOTIFY_TO_YOUTUBE;
  }
  const params = new URLSearchParams(window.location.search);
  const host = params.get("host");
  return host === "ytmusic"
    ? DIRECTION.YOUTUBE_TO_SPOTIFY
    : DIRECTION.SPOTIFY_TO_YOUTUBE;
}

function App() {
  const [isExtensionPanel] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("extension") === "1" || isRunningAsExtension();
  });
  const [direction, setDirection] = useState(getInitialDirection);
  const [spotifyPlaylists, setSpotifyPlaylists] = useState([]);
  /** Integer from `/api/spotify/callback` when `user-library-read` is granted; else null. */
  const [spotifyLikedTotal, setSpotifyLikedTotal] = useState(null);
  const [youtubePlaylists, setYoutubePlaylists] = useState([]);
  const [authDone, setAuthDone] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [convertProgress, setConvertProgress] = useState(null);
  /** Spotify → YouTube: destination */
  const [destYoutubeMode, setDestYoutubeMode] = useState("new");
  const [destYoutubePlaylistId, setDestYoutubePlaylistId] = useState("");
  const [youtubeDestPlaylists, setYoutubeDestPlaylists] = useState([]);
  const [youtubeDestLoading, setYoutubeDestLoading] = useState(false);
  const [youtubeDestError, setYoutubeDestError] = useState("");
  /** YouTube → Spotify: destination */
  const [destSpotifyMode, setDestSpotifyMode] = useState("new");
  const [destSpotifyPlaylistId, setDestSpotifyPlaylistId] = useState("");
  const [ytmHeadersUploadEnabled, setYtmHeadersUploadEnabled] = useState(false);
  const [ytmPlaywrightAvailable, setYtmPlaywrightAvailable] = useState(false);
  const [ytmHeadersPanelOpen, setYtmHeadersPanelOpen] = useState(false);
  const [ytmHeadersJsonText, setYtmHeadersJsonText] = useState("");
  const [ytmHeadersUploadToken, setYtmHeadersUploadToken] = useState(() =>
    typeof sessionStorage !== "undefined"
      ? sessionStorage.getItem(YTM_HEADERS_UPLOAD_TOKEN_KEY) || ""
      : ""
  );
  const [ytmHeadersInlineMsg, setYtmHeadersInlineMsg] = useState("");
  const [ytmHeadersSaving, setYtmHeadersSaving] = useState(false);
  const [ytPlaylistReloadKey, setYtPlaylistReloadKey] = useState(0);
  const capturePollRef = useRef(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");

    if (code) {
      // OAuth codes are single-use. Strip ?code=… immediately so React Strict Mode's
      // second mount cannot POST the same code again (would cause "Invalid authorization code").
      const cleanPath =
        `${window.location.pathname}${window.location.hash}` || "/";
      window.history.replaceState({}, document.title, cleanPath);

      const storedDir = sessionStorage.getItem("pc_direction");
      if (
        storedDir === DIRECTION.SPOTIFY_TO_YOUTUBE ||
        storedDir === DIRECTION.YOUTUBE_TO_SPOTIFY
      ) {
        setDirection(storedDir);
      }
      setLoading(true);
      handleSpotifyCallback(code)
        .then((data) => {
          setSpotifyPlaylists(data.playlists || []);
          setSpotifyLikedTotal(
            typeof data.liked_songs_total === "number"
              ? data.liked_songs_total
              : null
          );
          setAuthDone(true);
          setMessage("Logged in with Spotify successfully.");
          window.history.replaceState({}, document.title, "/");
        })
        .catch((err) => {
          console.error(err);
          setMessage(
            err?.message
              ? `Spotify login failed: ${err.message}`
              : "Failed to complete Spotify login."
          );
        })
        .finally(() => setLoading(false));
    }
  }, []);

  useEffect(() => {
    if (!isRunningAsExtension()) {
      return;
    }
    let cancelled = false;
    getStoredExtensionSpotifyAuth()
      .then((data) => {
        if (cancelled || !data?.playlists) {
          return;
        }
        setSpotifyPlaylists(data.playlists || []);
        setSpotifyLikedTotal(
          typeof data.liked_songs_total === "number"
            ? data.liked_songs_total
            : null
        );
        setAuthDone(true);
        setMessage("Connected to Spotify.");
      })
      .catch(() => {
        // No stored extension auth yet; the login button will start the tab-based flow.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    setDestYoutubeMode("new");
    setDestYoutubePlaylistId("");
    setDestSpotifyMode("new");
    setDestSpotifyPlaylistId("");
  }, [direction]);

  useEffect(() => {
    if (!authDone || direction !== DIRECTION.SPOTIFY_TO_YOUTUBE) {
      return;
    }
    let cancelled = false;
    setYoutubeDestLoading(true);
    setYoutubeDestError("");
    fetchYoutubePlaylists()
      .then((data) => {
        if (!cancelled) {
          setYoutubeDestPlaylists(data.playlists || []);
        }
      })
      .catch((err) => {
        console.error(err);
        if (!cancelled) {
          setYoutubeDestError(
            err?.message ||
              "Could not load your YouTube playlists (Google OAuth on the API server may be missing)."
          );
        }
      })
      .finally(() => {
        if (!cancelled) setYoutubeDestLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [authDone, direction]);

  useEffect(() => {
    if (!authDone || direction !== DIRECTION.YOUTUBE_TO_SPOTIFY) {
      return;
    }
    fetchYtmusicBrowserHeadersUploadConfig().then((d) => {
      setYtmHeadersUploadEnabled(d.uploadEnabled);
      setYtmPlaywrightAvailable(Boolean(d.playwrightAvailable));
    });
  }, [authDone, direction]);

  useEffect(() => {
    return () => {
      if (capturePollRef.current) {
        clearInterval(capturePollRef.current);
        capturePollRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!authDone || direction !== DIRECTION.YOUTUBE_TO_SPOTIFY) {
      return;
    }
    let cancelled = false;
    setLoading(true);
    setMessage("");
    fetchYtmusicPlaylists()
      .then((data) => {
        if (!cancelled) {
          setYoutubePlaylists(data.playlists || []);
          setMessage(
            data.warning ||
              (data.playlists?.length
                ? data.source === "youtube_data_api"
                  ? "Loaded playlists via YouTube Data API (ytmusicapi failed — see message above)."
                  : "Loaded your YouTube Music playlists (ytmusicapi)."
                : "No playlists found in your YouTube Music library.")
          );
        }
      })
      .catch((err) => {
        console.error(err);
        if (!cancelled) {
          setMessage(
            `Could not load YouTube Music playlists. ${err.message || ""} OAuth often hits HTTP 400 upstream (see ytmusicapi #813). Try \`ytmusicapi browser\` and set YTMUSIC_BROWSER_HEADERS_JSON, or fix oauth.json + TV client in .env.`
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [authDone, direction, ytPlaylistReloadKey]);

  const handleLogin = async () => {
    sessionStorage.setItem("pc_direction", direction);
    if (!isRunningAsExtension()) {
      startSpotifyAuth();
      return;
    }

    try {
      setLoading(true);
      setMessage("Opening Spotify login in a new tab…");
      const data = await startSpotifyAuth();
      setSpotifyPlaylists(data.playlists || []);
      setSpotifyLikedTotal(
        typeof data.liked_songs_total === "number"
          ? data.liked_songs_total
          : null
      );
      setAuthDone(true);
      setMessage("Logged in with Spotify successfully.");
    } catch (err) {
      setMessage(
        err?.message
          ? `Spotify login failed: ${err.message}`
          : "Failed to complete Spotify login."
      );
    } finally {
      setLoading(false);
    }
  };

  const handleSaveYtmusicBrowserHeaders = async () => {
    setYtmHeadersInlineMsg("");
    try {
      setYtmHeadersSaving(true);
      sessionStorage.setItem(YTM_HEADERS_UPLOAD_TOKEN_KEY, ytmHeadersUploadToken);
      const out = await saveYtmusicBrowserHeadersJson({
        jsonText: ytmHeadersJsonText,
        uploadToken: ytmHeadersUploadToken,
      });
      const tail = out.note ? ` ${out.note}` : "";
      setYtmHeadersInlineMsg(`Saved to ${out.saved_to}.${tail}`);
      setYtPlaylistReloadKey((k) => k + 1);
      setYtmHeadersJsonText("");
    } catch (e) {
      setYtmHeadersInlineMsg(e?.message || "Save failed.");
    } finally {
      setYtmHeadersSaving(false);
    }
  };

  const handleStartPlaywrightCapture = async () => {
    setYtmHeadersInlineMsg("");
    if (!ytmHeadersUploadToken.trim()) {
      setYtmHeadersInlineMsg("Enter the upload token first.");
      return;
    }
    if (capturePollRef.current) {
      clearInterval(capturePollRef.current);
      capturePollRef.current = null;
    }
    try {
      setYtmHeadersSaving(true);
      sessionStorage.setItem(YTM_HEADERS_UPLOAD_TOKEN_KEY, ytmHeadersUploadToken);
      const start = await startYtmusicPlaywrightCapture({
        uploadToken: ytmHeadersUploadToken,
      });
      const jobId = start.job_id;
      if (!jobId) {
        throw new Error("Server did not return job_id.");
      }
      setYtmHeadersInlineMsg(
        "Chromium should open on the computer running Flask — sign in to YouTube Music there."
      );
      capturePollRef.current = setInterval(async () => {
        try {
          const st = await getYtmusicCaptureStatus(jobId);
          if (st.message) {
            setYtmHeadersInlineMsg(st.message);
          }
          if (st.status === "done") {
            if (capturePollRef.current) {
              clearInterval(capturePollRef.current);
              capturePollRef.current = null;
            }
            const n = st.note ? ` ${st.note}` : "";
            setYtmHeadersInlineMsg(`Captured and saved to ${st.saved_to || "file"}.${n}`);
            setYtPlaylistReloadKey((k) => k + 1);
            setYtmHeadersSaving(false);
          } else if (st.status === "failed") {
            if (capturePollRef.current) {
              clearInterval(capturePollRef.current);
              capturePollRef.current = null;
            }
            setYtmHeadersInlineMsg(st.error || "Capture failed.");
            setYtmHeadersSaving(false);
          }
        } catch (e) {
          if (capturePollRef.current) {
            clearInterval(capturePollRef.current);
            capturePollRef.current = null;
          }
          setYtmHeadersInlineMsg(e?.message || "Status poll failed.");
          setYtmHeadersSaving(false);
        }
      }, 1500);
    } catch (e) {
      setYtmHeadersInlineMsg(e?.message || "Could not start capture.");
      setYtmHeadersSaving(false);
    }
  };

  const spotifyLoginButtonLabel =
    direction === DIRECTION.YOUTUBE_TO_SPOTIFY
      ? "Log in with Spotify · import from YouTube Music"
      : "Log in with Spotify · export to YouTube";

  const spotifyLoginHint =
    direction === DIRECTION.YOUTUBE_TO_SPOTIFY
      ? "After Spotify login we load your YouTube Music library so you can create Spotify playlists from it."
      : "After Spotify login we list your playlists and Liked songs so you can copy them to YouTube.";

  const spotifyExportRows = React.useMemo(() => {
    if (direction !== DIRECTION.SPOTIFY_TO_YOUTUBE) {
      return spotifyPlaylists;
    }
    return [
      {
        id: SPOTIFY_LIKED_SONGS_PLAYLIST_ID,
        name: "Liked songs",
        tracks: {
          total:
            typeof spotifyLikedTotal === "number" ? spotifyLikedTotal : "—",
        },
      },
      ...spotifyPlaylists,
    ];
  }, [direction, spotifyPlaylists, spotifyLikedTotal]);

  const handleConvertSpotifyToYoutube = async (playlist) => {
    if (destYoutubeMode === "existing" && !destYoutubePlaylistId) {
      setMessage(
        'Choose a YouTube playlist to add to, or select "Create a new YouTube playlist".'
      );
      return;
    }
    try {
      setLoading(true);
      setMessage("");
      setConvertProgress({
        pct: 0,
        message: `Converting "${playlist.name}" to YouTube…`,
      });
      const appendYt =
        destYoutubeMode === "existing" ? destYoutubePlaylistId : undefined;
      await convertPlaylist(
        playlist,
        (p) => setConvertProgress((prev) => ({ ...(prev || {}), ...p })),
        { existingYoutubePlaylistId: appendYt }
      );
      setMessage(
        appendYt
          ? `Added tracks from "${playlist.name}" to your selected YouTube playlist.`
          : `Converted "${playlist.name}" to a new YouTube playlist.`
      );
    } catch (err) {
      console.error(err);
      setMessage(
        err?.message
          ? `Failed to convert "${playlist.name}": ${err.message}`
          : `Failed to convert "${playlist.name}".`
      );
    } finally {
      setLoading(false);
      setConvertProgress(null);
    }
  };

  const handleConvertYoutubeToSpotify = async (playlist) => {
    if (destSpotifyMode === "existing" && !destSpotifyPlaylistId) {
      setMessage(
        'Choose a Spotify playlist to add to, or select "Create a new Spotify playlist".'
      );
      return;
    }
    try {
      setLoading(true);
      setMessage("");
      setConvertProgress({
        pct: 0,
        message: `Converting "${playlist.name}" to Spotify…`,
      });
      const appendSp =
        destSpotifyMode === "existing" ? destSpotifyPlaylistId : undefined;
      const result = await convertYoutubePlaylistToSpotify(
        playlist,
        (p) => setConvertProgress((prev) => ({ ...(prev || {}), ...p })),
        { existingSpotifyPlaylistId: appendSp }
      );
      const matched = result.tracks_matched ?? 0;
      const total = result.tracks_total ?? 0;
      const targetName = spotifyPlaylists.find(
        (x) => x.id === destSpotifyPlaylistId
      )?.name;
      setMessage(
        appendSp
          ? `Added ${matched}/${total} matched tracks from "${playlist.name}" to "${targetName || "your playlist"}".`
          : `Created Spotify playlist from "${playlist.name}" (${matched}/${total} tracks matched).`
      );
    } catch (err) {
      console.error(err);
      const detail = err?.message ? ` ${err.message}` : "";
      setMessage(`Failed to convert "${playlist.name}".${detail}`);
    } finally {
      setLoading(false);
      setConvertProgress(null);
    }
  };

  const shellStyle = {
    fontFamily: "Arial, sans-serif",
    padding: isExtensionPanel ? "16px" : "2rem",
    maxWidth: isExtensionPanel ? "100%" : "700px",
    margin: "0 auto",
    boxSizing: "border-box",
  };
  const shellClassName = `pc-app${isExtensionPanel ? " pc-app--extension" : ""}`;

  return (
    <div className={shellClassName} style={shellStyle}>
      <header className="pc-hero">
        <div className="pc-hero__icon" aria-hidden="true">
          ↔
        </div>
        <div>
          <p className="pc-eyebrow">
            {isExtensionPanel ? "Web plugin" : "Playlist utility"}
          </p>
          <h1 style={{ marginTop: isExtensionPanel ? 0 : undefined }}>
            Playlist converter
          </h1>
          <p style={{ color: "#444", marginTop: 0 }}>
            Spotify ↔ YouTube Music (via YouTube playlists and Spotify search).
          </p>
        </div>
      </header>

      <div
        className="pc-card pc-direction-card"
        style={{
          marginBottom: "1.5rem",
          padding: "1rem",
          background: "#f9f9f9",
          borderRadius: "8px",
        }}
      >
        <p style={{ fontWeight: 600, marginTop: 0, marginBottom: "0.5rem" }}>
          Direction
        </p>
        <label style={{ display: "block", marginBottom: "0.35rem" }}>
          <input
            type="radio"
            name="dir"
            checked={direction === DIRECTION.SPOTIFY_TO_YOUTUBE}
            onChange={() => setDirection(DIRECTION.SPOTIFY_TO_YOUTUBE)}
          />{" "}
          Spotify → YouTube
        </label>
        <label style={{ display: "block" }}>
          <input
            type="radio"
            name="dir"
            checked={direction === DIRECTION.YOUTUBE_TO_SPOTIFY}
            onChange={() => setDirection(DIRECTION.YOUTUBE_TO_SPOTIFY)}
          />{" "}
          YouTube → Spotify
        </label>
        {authDone && (
          <p style={{ fontSize: "13px", color: "#666", marginBottom: 0 }}>
            You can switch anytime. YouTube → Spotify still needs Spotify
            login (to create playlists) and Google/YouTube auth on the machine
            running the API.
          </p>
        )}
      </div>

      {convertProgress ? (
        <div
          className="pc-progress-card"
          style={{
            marginBottom: "1rem",
            padding: "1rem 1.1rem",
            borderRadius: "10px",
            background: "#eef6ff",
            border: "1px solid #c8daf5",
          }}
          aria-live="polite"
        >
          <p
            style={{
              margin: "0 0 0.65rem",
              fontSize: "14px",
              color: "#1a365d",
              fontWeight: 600,
            }}
          >
            {convertProgress.message || "Converting…"}
          </p>
          {typeof convertProgress.current === "number" &&
            typeof convertProgress.total === "number" &&
            convertProgress.total > 0 && (
              <p
                style={{
                  margin: "0 0 0.5rem",
                  fontSize: "13px",
                  color: "#2c5282",
                }}
              >
                Step {convertProgress.current} of {convertProgress.total}
                {typeof convertProgress.matched === "number"
                  ? ` · ${convertProgress.matched} matched`
                  : ""}
              </p>
            )}
          <div
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(
              Math.min(100, Math.max(0, convertProgress.pct ?? 0))
            )}
            aria-label="Conversion progress"
            style={{
              height: "10px",
              borderRadius: "999px",
              background: "#dbeafe",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                height: "100%",
                width: `${Math.min(100, Math.max(0, convertProgress.pct ?? 0))}%`,
                borderRadius: "999px",
                background:
                  direction === DIRECTION.YOUTUBE_TO_SPOTIFY
                    ? "linear-gradient(90deg, #1DB954, #169c46)"
                    : "linear-gradient(90deg, #FF0000, #cc0000)",
                transition: "width 0.25s ease-out",
              }}
            />
          </div>
          <p
            style={{
              margin: "0.45rem 0 0",
              fontSize: "12px",
              color: "#4a5568",
              textAlign: "right",
            }}
          >
            {Math.round(Math.min(100, Math.max(0, convertProgress.pct ?? 0)))}%
          </p>
        </div>
      ) : (
        loading && <p className="pc-loading">Loading…</p>
      )}
      {message && (
        <p className="pc-status" aria-live="polite">
          {message}
        </p>
      )}

      {!authDone && spotifyPlaylists.length === 0 ? (
        <div style={{ marginTop: "0.5rem" }}>
          <p
            style={{
              fontSize: "14px",
              color: "#555",
              margin: "0 0 12px",
              maxWidth: "520px",
              lineHeight: 1.45,
            }}
          >
            {spotifyLoginHint}
          </p>
          <button
            type="button"
            onClick={handleLogin}
            aria-label={spotifyLoginButtonLabel}
            style={{
              padding: "12px 22px",
              fontSize: "15px",
              fontWeight: 600,
              borderRadius: "999px",
              cursor: "pointer",
              backgroundColor: "#1DB954",
              color: "white",
              border: "none",
              boxShadow: "0 2px 8px rgba(29, 185, 84, 0.35)",
              maxWidth: "100%",
            }}
          >
            {spotifyLoginButtonLabel}
          </button>
        </div>
      ) : direction === DIRECTION.SPOTIFY_TO_YOUTUBE ? (
        <>
          <div
            style={{
              marginBottom: "1.25rem",
              padding: "1rem",
              background: "#fff8f8",
              borderRadius: "10px",
              border: "1px solid #f5cbcb",
            }}
          >
            <p
              style={{
                fontWeight: 600,
                marginTop: 0,
                marginBottom: "0.65rem",
                color: "#7f1d1d",
              }}
            >
              YouTube destination
            </p>
            <label
              style={{ display: "block", marginBottom: "0.4rem", cursor: "pointer" }}
            >
              <input
                type="radio"
                name="ytDest"
                checked={destYoutubeMode === "new"}
                onChange={() => {
                  setDestYoutubeMode("new");
                  setDestYoutubePlaylistId("");
                }}
              />{" "}
              Create a new YouTube playlist (named{" "}
              <code>Converted - …</code>)
            </label>
            <label
              style={{ display: "block", marginBottom: "0.55rem", cursor: "pointer" }}
            >
              <input
                type="radio"
                name="ytDest"
                checked={destYoutubeMode === "existing"}
                onChange={() => setDestYoutubeMode("existing")}
              />{" "}
              Add songs to an existing YouTube playlist
            </label>
            {destYoutubeMode === "existing" && (
              <>
                {youtubeDestLoading ? (
                  <p style={{ margin: "0.35rem 0 0", fontSize: "13px", color: "#666" }}>
                    Loading your YouTube playlists…
                  </p>
                ) : youtubeDestError ? (
                  <p style={{ margin: "0.35rem 0 0", fontSize: "13px", color: "#b91c1c" }}>
                    {youtubeDestError}
                  </p>
                ) : (
                  <select
                    value={destYoutubePlaylistId}
                    onChange={(e) => setDestYoutubePlaylistId(e.target.value)}
                    style={{
                      width: "100%",
                      maxWidth: "420px",
                      padding: "8px 10px",
                      fontSize: "14px",
                      borderRadius: "6px",
                      border: "1px solid #ccc",
                    }}
                    aria-label="Existing YouTube playlist to add tracks to"
                  >
                    <option value="">Select a playlist…</option>
                    {youtubeDestPlaylists.map((yp) => (
                      <option key={yp.id} value={yp.id}>
                        {yp.name} ({yp.tracks?.total ?? "?"} videos)
                      </option>
                    ))}
                  </select>
                )}
              </>
            )}
          </div>
          <h2>Your Spotify playlists</h2>
          <p
            style={{
              fontSize: "13px",
              color: "#555",
              margin: "0 0 0.75rem",
              maxWidth: "560px",
              lineHeight: 1.45,
            }}
          >
            <strong>Liked songs</strong> is read straight from your Spotify library (no need to
            select tracks in the Spotify app). If conversion is denied, connect Spotify again once
            so the app can request library access.
          </p>
          <ul style={{ listStyle: "none", padding: 0 }}>
            {spotifyExportRows.map((p) => (
              <li
                key={p.id}
                style={{
                  marginBottom: "1rem",
                  padding: "1rem",
                  borderRadius: "10px",
                  background: "#f3f3f3",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <span>
                  <strong>{p.name}</strong> ({p.tracks?.total ?? "?"} tracks)
                </span>
                <button
                  type="button"
                  onClick={() => handleConvertSpotifyToYoutube(p)}
                  disabled={loading}
                  style={{
                    backgroundColor: "#FF0000",
                    color: "white",
                    border: "none",
                    padding: "8px 14px",
                    borderRadius: "6px",
                    cursor: loading ? "not-allowed" : "pointer",
                  }}
                >
                  Convert to YouTube
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <>
          <div
            style={{
              marginBottom: "1.25rem",
              padding: "1rem",
              background: "#f0fdf4",
              borderRadius: "10px",
              border: "1px solid #bbf7d0",
            }}
          >
            <p
              style={{
                fontWeight: 600,
                marginTop: 0,
                marginBottom: "0.65rem",
                color: "#14532d",
              }}
            >
              Spotify destination
            </p>
            <label
              style={{ display: "block", marginBottom: "0.4rem", cursor: "pointer" }}
            >
              <input
                type="radio"
                name="spDest"
                checked={destSpotifyMode === "new"}
                onChange={() => {
                  setDestSpotifyMode("new");
                  setDestSpotifyPlaylistId("");
                }}
              />{" "}
              Create a new Spotify playlist (named{" "}
              <code>Converted — …</code>)
            </label>
            <label
              style={{ display: "block", marginBottom: "0.55rem", cursor: "pointer" }}
            >
              <input
                type="radio"
                name="spDest"
                checked={destSpotifyMode === "existing"}
                onChange={() => setDestSpotifyMode("existing")}
              />{" "}
              Add songs to an existing Spotify playlist
            </label>
            {destSpotifyMode === "existing" && (
              <select
                value={destSpotifyPlaylistId}
                onChange={(e) => setDestSpotifyPlaylistId(e.target.value)}
                style={{
                  width: "100%",
                  maxWidth: "420px",
                  padding: "8px 10px",
                  fontSize: "14px",
                  borderRadius: "6px",
                  border: "1px solid #ccc",
                }}
                aria-label="Existing Spotify playlist to add tracks to"
              >
                <option value="">Select a playlist…</option>
                {spotifyPlaylists.map((sp) => (
                  <option key={sp.id} value={sp.id}>
                    {sp.name} ({sp.tracks?.total ?? "?"} tracks)
                  </option>
                ))}
              </select>
            )}
          </div>
          <div
            style={{
              marginBottom: "1rem",
              padding: "1rem",
              background: "#fffbeb",
              borderRadius: "10px",
              border: "1px solid #fcd34d",
            }}
          >
            <button
              type="button"
              onClick={() => setYtmHeadersPanelOpen((o) => !o)}
              style={{
                width: "100%",
                textAlign: "left",
                fontWeight: 600,
                fontSize: "15px",
                padding: "0.35rem 0",
                border: "none",
                background: "transparent",
                cursor: "pointer",
                color: "#78350f",
              }}
            >
              {ytmHeadersPanelOpen ? "▼" : "▶"} Renew YouTube Music browser headers (when cookies expire)
            </button>
            {ytmHeadersPanelOpen && (
              <div style={{ marginTop: "0.75rem" }}>
                {!ytmHeadersUploadEnabled ? (
                  <p style={{ fontSize: "13px", color: "#92400e", marginBottom: 0 }}>
                    Server upload is off. Add{" "}
                    <code>YTMUSIC_HEADERS_UPLOAD_SECRET</code> to your Flask <code>.env</code>{" "}
                    (any long random string), restart the API, then enter the same value below as
                    the upload token.
                  </p>
                ) : (
                  <>
                    <label
                      style={{
                        display: "block",
                        fontSize: "13px",
                        fontWeight: 600,
                        color: "#422006",
                        marginBottom: "0.35rem",
                      }}
                    >
                      Upload token (matches <code>YTMUSIC_HEADERS_UPLOAD_SECRET</code> on the server)
                    </label>
                    <input
                      type="password"
                      autoComplete="off"
                      value={ytmHeadersUploadToken}
                      onChange={(e) => setYtmHeadersUploadToken(e.target.value)}
                      placeholder="Paste server secret once"
                      style={{
                        width: "100%",
                        maxWidth: "420px",
                        padding: "8px 10px",
                        fontSize: "14px",
                        borderRadius: "6px",
                        border: "1px solid #ccc",
                        marginBottom: "0.65rem",
                      }}
                    />
                    {ytmPlaywrightAvailable ? (
                      <div style={{ marginBottom: "0.85rem" }}>
                        <p
                          style={{
                            fontSize: "13px",
                            color: "#422006",
                            margin: "0 0 0.45rem",
                            lineHeight: 1.45,
                          }}
                        >
                          <strong>Chromium on the Flask computer</strong> (needs a screen): enter the
                          upload token above, then start capture. A browser window opens on the server;
                          log into YouTube Music there — cookies are saved when sign-in is detected.
                        </p>
                        <button
                          type="button"
                          disabled={ytmHeadersSaving}
                          onClick={handleStartPlaywrightCapture}
                          style={{
                            padding: "8px 14px",
                            fontWeight: 600,
                            borderRadius: "6px",
                            border: "none",
                            backgroundColor: ytmHeadersSaving ? "#ccc" : "#0f766e",
                            color: "white",
                            cursor: ytmHeadersSaving ? "not-allowed" : "pointer",
                          }}
                        >
                          {ytmHeadersSaving
                            ? "Capture running…"
                            : "Log in with Chromium on server (auto-save headers)"}
                        </button>
                      </div>
                    ) : (
                      <p
                        style={{
                          fontSize: "12px",
                          color: "#92400e",
                          margin: "0 0 0.75rem",
                          lineHeight: 1.4,
                        }}
                      >
                        Playwright is not available on the API host. Install with:{" "}
                        <code>pip install playwright</code> then <code>playwright install chromium</code>
                        , restart Flask, then reload this page.
                      </p>
                    )}
                    <label
                      style={{
                        display: "block",
                        fontSize: "13px",
                        fontWeight: 600,
                        color: "#422006",
                        marginBottom: "0.25rem",
                      }}
                    >
                      {ytmPlaywrightAvailable ? (
                        <>
                          Manual upload — <code>ytmusicapi browser</code> JSON{" "}
                          <span style={{ fontWeight: 400, color: "#57534e" }}>
                            (skip this if Chromium capture above succeeded)
                          </span>
                        </>
                      ) : (
                        <>
                          Headers JSON (from <code>ytmusicapi browser</code>)
                        </>
                      )}
                    </label>
                    {ytmPlaywrightAvailable && (
                      <p
                        style={{
                          fontSize: "12px",
                          color: "#57534e",
                          margin: "0 0 0.4rem",
                          lineHeight: 1.35,
                        }}
                      >
                        This box is an alternative: use it only when you are not using the green
                        &quot;Chromium&quot; button, or when Playwright is unavailable.
                      </p>
                    )}
                    <textarea
                      value={ytmHeadersJsonText}
                      onChange={(e) => setYtmHeadersJsonText(e.target.value)}
                      rows={8}
                      spellCheck={false}
                      placeholder='{ "cookie": "...", "user-agent": "...", ... }'
                      style={{
                        width: "100%",
                        fontFamily: "monospace",
                        fontSize: "12px",
                        padding: "8px",
                        borderRadius: "6px",
                        border: "1px solid #ccc",
                        boxSizing: "border-box",
                      }}
                    />
                    <button
                      type="button"
                      disabled={ytmHeadersSaving || !ytmHeadersJsonText.trim()}
                      onClick={handleSaveYtmusicBrowserHeaders}
                      style={{
                        marginTop: "0.6rem",
                        padding: "8px 16px",
                        fontWeight: 600,
                        borderRadius: "6px",
                        border: "none",
                        backgroundColor: ytmHeadersSaving ? "#ccc" : "#ca8a04",
                        color: "white",
                        cursor:
                          ytmHeadersSaving || !ytmHeadersJsonText.trim()
                            ? "not-allowed"
                            : "pointer",
                      }}
                    >
                      {ytmHeadersSaving ? "Saving…" : "Save headers on server"}
                    </button>
                    {ytmHeadersInlineMsg && (
                      <p
                        style={{
                          marginTop: "0.55rem",
                          fontSize: "13px",
                          color: ytmHeadersInlineMsg.startsWith("Saved") ? "#166534" : "#b91c1c",
                        }}
                      >
                        {ytmHeadersInlineMsg}
                      </p>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
          <h2>Your YouTube Music playlists</h2>
          <p style={{ fontSize: "14px", color: "#555" }}>
            With <strong>browser headers</strong> (<code>YTMUSIC_BROWSER_HEADERS_JSON</code>), use
            the panel above when cookies expire. Otherwise this app uses{" "}
            <code>backend/oauth.json</code> plus <code>YTMUSIC_CLIENT_ID</code> /{" "}
            <code>YTMUSIC_CLIENT_SECRET</code> in <code>.env</code>. Spotify → YouTube uses the
            Google Data API and <code>backend/token.pickle</code>.
          </p>
          <ul style={{ listStyle: "none", padding: 0 }}>
            {youtubePlaylists.map((p) => (
              <li
                key={p.id}
                style={{
                  marginBottom: "1rem",
                  padding: "1rem",
                  borderRadius: "10px",
                  background: "#f3f3f3",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <span>
                  <strong>{p.name}</strong> ({p.tracks?.total ?? "?"} items)
                </span>
                <button
                  type="button"
                  onClick={() => handleConvertYoutubeToSpotify(p)}
                  disabled={loading}
                  style={{
                    backgroundColor: "#1DB954",
                    color: "white",
                    border: "none",
                    padding: "8px 14px",
                    borderRadius: "6px",
                    cursor: loading ? "not-allowed" : "pointer",
                  }}
                >
                  Convert to Spotify
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

export default App;
