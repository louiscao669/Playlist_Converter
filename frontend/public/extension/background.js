const AUTH_STORAGE_KEY = "pc_spotify_auth";
const YOUTUBE_AUTH_STORAGE_KEY = "pc_youtube_auth";
const DEFAULT_API_BASE = "http://localhost:8888";
const DEFAULT_REDIRECT_PREFIXES = [
  "http://localhost:3000/",
  "http://127.0.0.1:3000/",
  "http://localhost:8888/",
  "http://127.0.0.1:8888/"
];

function normalizeApiBase(raw) {
  return (raw || DEFAULT_API_BASE).replace(/\/+$/, "");
}

function storageGet(key) {
  return new Promise((resolve) => {
    chrome.storage.local.get(key, (items) => resolve(items?.[key] || null));
  });
}

function storageSet(key, value) {
  return new Promise((resolve) => {
    chrome.storage.local.set({ [key]: value }, resolve);
  });
}

function createTab(url) {
  return new Promise((resolve, reject) => {
    chrome.tabs.create({ url, active: true }, (tab) => {
      const err = chrome.runtime.lastError;
      if (err) {
        reject(new Error(err.message));
      } else {
        resolve(tab);
      }
    });
  });
}

function removeTab(tabId) {
  chrome.tabs.remove(tabId, () => {
    // The user may have already closed the tab.
    chrome.runtime.lastError;
  });
}

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || data.details || `Request failed (${res.status})`);
  }
  return data;
}

async function getRedirectPrefixes(apiBase) {
  const prefixes = new Set([...DEFAULT_REDIRECT_PREFIXES, `${apiBase}/`]);
  try {
    const settings = await fetchJson(`${apiBase}/api/spotify/oauth-settings`);
    if (settings.spotify_redirect_uri) {
      prefixes.add(settings.spotify_redirect_uri);
    }
    if (settings.frontend_url) {
      prefixes.add(`${String(settings.frontend_url).replace(/\/+$/, "")}/`);
    }
  } catch (_) {
    // Defaults still support the repo's local development setup.
  }
  return [...prefixes];
}

async function getYoutubeRedirectPrefixes(apiBase) {
  const prefixes = new Set([
    ...DEFAULT_REDIRECT_PREFIXES,
    `${apiBase}/`,
    "http://localhost:3000/youtube-callback",
    "http://127.0.0.1:3000/youtube-callback"
  ]);
  try {
    const settings = await fetchJson(`${apiBase}/api/youtube/oauth-settings`);
    if (settings.youtube_redirect_uri) {
      prefixes.add(settings.youtube_redirect_uri);
    }
    if (settings.frontend_url) {
      prefixes.add(`${String(settings.frontend_url).replace(/\/+$/, "")}/youtube-callback`);
    }
  } catch (_) {
    // Defaults still support the repo's local development setup.
  }
  return [...prefixes];
}

function isSpotifyRedirect(url, prefixes) {
  if (!url) {
    return false;
  }
  let parsed;
  try {
    parsed = new URL(url);
  } catch (_) {
    return false;
  }
  if (!parsed.searchParams.has("code") && !parsed.searchParams.has("error")) {
    return false;
  }
  return prefixes.some((prefix) => url.startsWith(prefix));
}

function isYoutubeRedirect(url, prefixes) {
  if (!url) {
    return false;
  }
  let parsed;
  try {
    parsed = new URL(url);
  } catch (_) {
    return false;
  }
  if (!parsed.searchParams.has("code") && !parsed.searchParams.has("error")) {
    return false;
  }
  const state = parsed.searchParams.get("state") || "";
  return state.startsWith("youtube") || prefixes.some((prefix) => url.startsWith(prefix));
}

async function exchangeSpotifyCode(apiBase, code) {
  return fetchJson(`${apiBase}/api/spotify/callback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code })
  });
}

async function exchangeYoutubeCode(apiBase, code) {
  return fetchJson(`${apiBase}/api/youtube/callback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code })
  });
}

async function startSpotifyAuth(payload = {}) {
  const apiBase = normalizeApiBase(payload.apiBase);
  const [{ auth_url: authUrl }, redirectPrefixes] = await Promise.all([
    fetchJson(`${apiBase}/api/spotify/auth`),
    getRedirectPrefixes(apiBase)
  ]);

  if (!authUrl) {
    throw new Error("Spotify auth URL was not returned by the API.");
  }

  const tab = await createTab(authUrl);
  if (!tab.id) {
    throw new Error("Could not open Spotify login tab.");
  }

  return new Promise((resolve, reject) => {
    let settled = false;
    const timeoutId = setTimeout(() => {
      finish(null, new Error("Spotify login timed out."));
    }, 5 * 60 * 1000);

    function finish(data, error) {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timeoutId);
      chrome.tabs.onUpdated.removeListener(onUpdated);
      if (tab.id) {
        removeTab(tab.id);
      }
      if (error) {
        reject(error);
      } else {
        resolve(data);
      }
    }

    async function onUpdated(tabId, changeInfo, updatedTab) {
      if (tabId !== tab.id) {
        return;
      }
      const url = changeInfo.url || updatedTab?.url;
      if (!isSpotifyRedirect(url, redirectPrefixes)) {
        return;
      }

      try {
        const parsed = new URL(url);
        const spotifyError = parsed.searchParams.get("error");
        if (spotifyError) {
          throw new Error(`Spotify denied login: ${spotifyError}`);
        }
        const code = parsed.searchParams.get("code");
        if (!code) {
          throw new Error("Spotify redirect did not include an authorization code.");
        }
        const data = await exchangeSpotifyCode(apiBase, code);
        await storageSet(AUTH_STORAGE_KEY, data);
        finish(data, null);
      } catch (error) {
        finish(null, error);
      }
    }

    chrome.tabs.onUpdated.addListener(onUpdated);
  });
}

async function startYoutubeAuth(payload = {}) {
  const apiBase = normalizeApiBase(payload.apiBase);
  const [{ auth_url: authUrl }, redirectPrefixes] = await Promise.all([
    fetchJson(`${apiBase}/api/youtube/auth`),
    getYoutubeRedirectPrefixes(apiBase)
  ]);

  if (!authUrl) {
    throw new Error("YouTube auth URL was not returned by the API.");
  }

  const tab = await createTab(authUrl);
  if (!tab.id) {
    throw new Error("Could not open YouTube login tab.");
  }

  return new Promise((resolve, reject) => {
    let settled = false;
    const timeoutId = setTimeout(() => {
      finish(null, new Error("YouTube login timed out."));
    }, 5 * 60 * 1000);

    function finish(data, error) {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timeoutId);
      chrome.tabs.onUpdated.removeListener(onUpdated);
      if (tab.id) {
        removeTab(tab.id);
      }
      if (error) {
        reject(error);
      } else {
        resolve(data);
      }
    }

    async function onUpdated(tabId, changeInfo, updatedTab) {
      if (tabId !== tab.id) {
        return;
      }
      const url = changeInfo.url || updatedTab?.url;
      if (!isYoutubeRedirect(url, redirectPrefixes)) {
        return;
      }

      try {
        const parsed = new URL(url);
        const googleError = parsed.searchParams.get("error");
        if (googleError) {
          throw new Error(`YouTube denied login: ${googleError}`);
        }
        const code = parsed.searchParams.get("code");
        if (!code) {
          throw new Error("YouTube redirect did not include an authorization code.");
        }
        const data = await exchangeYoutubeCode(apiBase, code);
        await storageSet(YOUTUBE_AUTH_STORAGE_KEY, data || { ok: true });
        finish(data || { ok: true }, null);
      } catch (error) {
        finish(null, error);
      }
    }

    chrome.tabs.onUpdated.addListener(onUpdated);
  });
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "PC_START_SPOTIFY_AUTH") {
    startSpotifyAuth(message.payload)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message?.type === "PC_GET_SPOTIFY_AUTH") {
    storageGet(AUTH_STORAGE_KEY)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message?.type === "PC_START_YOUTUBE_AUTH") {
    startYoutubeAuth(message.payload)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  return false;
});

chrome.action.onClicked.addListener((tab) => {
  if (!tab.id) {
    return;
  }
  chrome.tabs.sendMessage(tab.id, { type: "PC_TOGGLE_PANEL" }, () => {
    chrome.runtime.lastError;
  });
});
