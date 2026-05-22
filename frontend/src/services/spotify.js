/* global chrome */

export const API_BASE = process.env.REACT_APP_API_BASE || "http://localhost:8888";

function isExtensionRuntime() {
  return (
    typeof chrome !== "undefined" &&
    Boolean(chrome.runtime?.id) &&
    typeof chrome.runtime.sendMessage === "function"
  );
}

function rememberSpotifyAuth(data) {
  if (data?.access_token) {
    localStorage.setItem("spotify_token", data.access_token);
  }
}

function sendExtensionMessage(type, payload = {}) {
  return new Promise((resolve, reject) => {
    if (!isExtensionRuntime()) {
      reject(new Error("Extension runtime is not available."));
      return;
    }

    chrome.runtime.sendMessage({ type, payload }, (response) => {
      const runtimeError = chrome.runtime.lastError;
      if (runtimeError) {
        reject(new Error(runtimeError.message));
        return;
      }
      if (!response?.ok) {
        reject(new Error(response?.error || "Extension request failed."));
        return;
      }
      resolve(response.data);
    });
  });
}

export function isRunningAsExtension() {
  return isExtensionRuntime();
}

export async function getStoredExtensionSpotifyAuth() {
  if (!isExtensionRuntime()) {
    return null;
  }
  const data = await sendExtensionMessage("PC_GET_SPOTIFY_AUTH");
  if (data) {
    rememberSpotifyAuth(data);
  }
  return data || null;
}

/** Must match `SPOTIFY_LIKED_SONGS_PLAYLIST_ID` in backend `spotify_service.py`. */
export const SPOTIFY_LIKED_SONGS_PLAYLIST_ID = "__spotify_liked_songs__";

/** Parse NDJSON body from streaming import/add endpoints. */
async function consumeNdjsonStream(res, onProgress) {
  if (!res.ok) {
    const text = await res.text();
    let msg = text;
    try {
      const j = JSON.parse(text);
      if (j.error) {
        msg = j.details ? `${j.error}: ${j.details}` : j.error;
      }
    } catch (_) {
      /* plain text */
    }
    throw new Error(msg || `Request failed (${res.status})`);
  }
  if (!res.body) {
    throw new Error("No response body (streaming not supported in this browser)");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) {
        continue;
      }
      let evt;
      try {
        evt = JSON.parse(line);
      } catch (_) {
        continue;
      }
      if (evt.type === "progress" && typeof onProgress === "function") {
        onProgress(evt);
      }
      if (evt.type === "error") {
        const err = new Error(evt.error || "Request failed");
        err.details = evt.details;
        err.status = evt.status;
        throw err;
      }
      if (evt.type === "complete") {
        finalResult = evt.result;
      }
    }
  }
  if (buffer.trim()) {
    try {
      const evt = JSON.parse(buffer.trim());
      if (evt.type === "progress" && typeof onProgress === "function") {
        onProgress(evt);
      }
      if (evt.type === "error") {
        throw new Error(evt.error || "Request failed");
      }
      if (evt.type === "complete") {
        finalResult = evt.result;
      }
    } catch (e) {
      if (e instanceof Error && e.message) {
        throw e;
      }
    }
  }
  if (!finalResult) {
    throw new Error("Stream ended without a result");
  }
  return finalResult;
}

export async function startSpotifyAuth() {
  if (isExtensionRuntime()) {
    const data = await sendExtensionMessage("PC_START_SPOTIFY_AUTH", { apiBase: API_BASE });
    rememberSpotifyAuth(data);
    return data;
  }

  const res = await fetch(`${API_BASE}/api/spotify/auth`);
  const data = await res.json();
  window.location.href = data.auth_url;
  return null;
}

export async function handleSpotifyCallback(authCode) {
  const code =
    typeof authCode === "string" && authCode
      ? authCode
      : new URLSearchParams(window.location.search).get("code");
  if (!code) {
    throw new Error("Missing Spotify authorization code.");
  }

  const res = await fetch(`${API_BASE}/api/spotify/callback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || `Spotify login failed (${res.status})`);
  }
  rememberSpotifyAuth(data);
  return data;
}

export async function fetchYoutubePlaylists() {
  const res = await fetch(`${API_BASE}/api/youtube/playlists`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || "Failed to load YouTube playlists");
  }
  return res.json();
}

/** YouTube Music → Spotify: lists playlists via ytmusicapi (oauth.json + TV client env). */
export async function fetchYtmusicPlaylists() {
  const res = await fetch(`${API_BASE}/api/ytmusic/playlists`);
  let body = {};
  try {
    body = await res.json();
  } catch (_) {
    body = {};
  }
  if (!res.ok) {
    throw new Error(
      body.error || (await res.text()) || "Failed to load YouTube Music playlists"
    );
  }
  return body;
}

/** Whether POST /api/ytmusic/browser-headers is enabled (requires server env secret). */
export async function fetchYtmusicBrowserHeadersUploadConfig() {
  const res = await fetch(`${API_BASE}/api/ytmusic/browser-headers-config`);
  const body = await res.json().catch(() => ({}));
  return {
    uploadEnabled: Boolean(body.upload_enabled),
    playwrightAvailable: Boolean(body.playwright_available),
  };
}

/** Start headed Chromium on the Flask host; returns { job_id, message }. */
export async function startYtmusicPlaywrightCapture({ uploadToken }) {
  const res = await fetch(`${API_BASE}/api/ytmusic/capture-browser-session`, {
    method: "POST",
    headers: { "X-Ytmusic-Headers-Upload-Token": uploadToken || "" },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(body.error || `Capture failed (${res.status})`);
  }
  return body;
}

export async function getYtmusicCaptureStatus(jobId) {
  const q = encodeURIComponent(jobId);
  const res = await fetch(`${API_BASE}/api/ytmusic/capture-browser-session?job_id=${q}`);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(body.error || `Status failed (${res.status})`);
  }
  return body;
}

/**
 * Save pasted `ytmusicapi browser` JSON to the server headers file.
 * @param {{ jsonText: string, uploadToken: string }} args
 */
export async function saveYtmusicBrowserHeadersJson({ jsonText, uploadToken }) {
  let parsed;
  try {
    parsed = JSON.parse(jsonText);
  } catch {
    throw new Error("That text is not valid JSON.");
  }
  const res = await fetch(`${API_BASE}/api/ytmusic/browser-headers`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Ytmusic-Headers-Upload-Token": uploadToken || "",
    },
    body: JSON.stringify(parsed),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(body.error || `Save failed (${res.status})`);
  }
  return body;
}

/**
 * @param {object} selectedPlaylist
 * @param {(p: { pct: number, phase?: string, message?: string, current?: number, total?: number }) => void} [onProgress]
 * @param {{ existingYoutubePlaylistId?: string }} [options] If set, videos are appended to this playlist (no new playlist).
 */
export async function convertPlaylist(selectedPlaylist, onProgress, options = {}) {
  const existingYt = (options.existingYoutubePlaylistId || "").trim();
  onProgress?.({ pct: 4, phase: "spotify_tracks", message: "Loading Spotify tracks…" });
  const tracksRes = await fetch(`${API_BASE}/api/spotify/tracks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      access_token: localStorage.getItem("spotify_token") || undefined,
      playlist_id: selectedPlaylist.id,
    }),
  });
  if (!tracksRes.ok) {
    const raw = await tracksRes.text();
    let msg = raw;
    try {
      const j = JSON.parse(raw);
      if (j.error) {
        msg = j.details ? `${j.error} (${j.details})` : j.error;
      }
    } catch (_) {
      /* keep raw */
    }
    throw new Error(msg || `Spotify tracks failed (${tracksRes.status})`);
  }
  const { tracks } = await tracksRes.json();

  let yt_playlist_id;
  if (existingYt) {
    yt_playlist_id = existingYt;
    onProgress?.({
      pct: 14,
      phase: "youtube_create",
      message: "Using your existing YouTube playlist…",
    });
  } else {
    onProgress?.({ pct: 14, phase: "youtube_create", message: "Creating YouTube playlist…" });
    const ytRes = await fetch(`${API_BASE}/api/youtube/playlists`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: `Converted - ${selectedPlaylist.name}`,
        description: "Imported from Spotify",
      }),
    });
    if (!ytRes.ok) {
      throw new Error(await ytRes.text());
    }
    const body = await ytRes.json();
    yt_playlist_id = body.yt_playlist_id;
  }

  const addRes = await fetch(`${API_BASE}/api/youtube/add?stream=1`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/x-ndjson",
    },
    body: JSON.stringify({ playlist_id: yt_playlist_id, tracks }),
  });
  await consumeNdjsonStream(addRes, (evt) => {
    const inner = typeof evt.pct === "number" ? evt.pct : 0;
    const pct = 18 + Math.round((inner / 100) * 82);
    onProgress?.({
      pct: Math.min(99, pct),
      phase: evt.phase,
      message: evt.message,
      current: evt.current,
      total: evt.total,
      matched: evt.matched,
    });
  });
  onProgress?.({ pct: 100, phase: "done", message: "Done." });
}

/**
 * @param {object} selectedPlaylist
 * @param {(p: { pct: number, phase?: string, message?: string, current?: number, total?: number }) => void} [onProgress]
 * @param {{ existingSpotifyPlaylistId?: string }} [options] If set, matched tracks are appended to this playlist.
 */
export async function convertYoutubePlaylistToSpotify(selectedPlaylist, onProgress, options = {}) {
  onProgress?.({ pct: 5, phase: "yt_tracks", message: "Loading YouTube / YouTube Music tracks…" });
  const tracksRes = await fetch(`${API_BASE}/api/ytmusic/tracks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ playlist_id: selectedPlaylist.id }),
  });
  let tracksBody = {};
  try {
    tracksBody = await tracksRes.json();
  } catch (_) {
    tracksBody = {};
  }
  if (!tracksRes.ok) {
    throw new Error(tracksBody.error || "Failed to load tracks");
  }
  const { tracks } = tracksBody;

  const existingSp = (options.existingSpotifyPlaylistId || "").trim();
  const imp = await fetch(`${API_BASE}/api/spotify/import-tracks?stream=1`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/x-ndjson",
    },
    body: JSON.stringify({
      title: `Converted — ${selectedPlaylist.name}`,
      description: "Imported from YouTube Music",
      tracks,
      access_token: localStorage.getItem("spotify_token") || undefined,
      ...(existingSp ? { spotify_playlist_id: existingSp } : {}),
    }),
  });

  const result = await consumeNdjsonStream(imp, (evt) => {
    const inner = typeof evt.pct === "number" ? evt.pct : 0;
    const pct = 12 + Math.round((inner / 100) * 87);
    onProgress?.({
      pct: Math.min(99, pct),
      phase: evt.phase,
      message: evt.message,
      current: evt.current,
      total: evt.total,
      matched: evt.matched,
    });
  });
  onProgress?.({ pct: 100, phase: "done", message: "Done." });
  return result;
}
