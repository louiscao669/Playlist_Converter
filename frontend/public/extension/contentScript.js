(() => {
  if (window.__playlistConverterExtensionMounted) {
    return;
  }
  window.__playlistConverterExtensionMounted = true;

  const STORAGE_KEY = "playlist-converter-panel-open";
  const host = document.createElement("div");
  host.id = "playlist-converter-extension-root";
  document.documentElement.appendChild(host);

  const shadow = host.attachShadow({ mode: "open" });
  shadow.innerHTML = `
    <style>
      :host {
        all: initial;
        color-scheme: light;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      .launcher {
        position: fixed;
        right: 18px;
        bottom: 24px;
        z-index: 2147483647;
        display: inline-flex;
        align-items: center;
        gap: 10px;
        border: 0;
        border-radius: 999px;
        padding: 12px 16px;
        background: linear-gradient(135deg, #18c36e 0%, #0ea5e9 45%, #ef4444 100%);
        color: #fff;
        font: 800 13px/1 Arial, sans-serif;
        letter-spacing: -0.01em;
        box-shadow: 0 16px 42px rgba(0, 0, 0, 0.34), inset 0 1px 0 rgba(255, 255, 255, 0.25);
        cursor: pointer;
        transform: translateZ(0);
        transition: transform 160ms ease, filter 160ms ease, box-shadow 160ms ease;
      }
      .launcher:hover {
        filter: brightness(1.06);
        transform: translateY(-2px);
        box-shadow: 0 20px 54px rgba(0, 0, 0, 0.38), inset 0 1px 0 rgba(255, 255, 255, 0.25);
      }
      .launcher:active {
        transform: translateY(0) scale(0.98);
      }
      .launcher-icon {
        display: grid;
        place-items: center;
        width: 22px;
        height: 22px;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.18);
      }
      .panel {
        position: fixed;
        top: 76px;
        right: 18px;
        z-index: 2147483646;
        width: min(440px, calc(100vw - 36px));
        height: min(740px, calc(100vh - 108px));
        min-height: 460px;
        border-radius: 24px;
        overflow: hidden;
        background: rgba(255, 255, 255, 0.96);
        box-shadow: 0 26px 90px rgba(0, 0, 0, 0.4), 0 8px 22px rgba(15, 23, 42, 0.16);
        border: 1px solid rgba(255, 255, 255, 0.58);
        opacity: 0;
        pointer-events: none;
        transform: translateY(14px) scale(0.97);
        visibility: hidden;
        transition: opacity 180ms ease, transform 180ms ease, visibility 180ms ease;
        backdrop-filter: blur(18px);
      }
      .panel.open {
        opacity: 1;
        pointer-events: auto;
        transform: translateY(0) scale(1);
        visibility: visible;
      }
      .chrome {
        display: flex;
        align-items: center;
        gap: 12px;
        height: 58px;
        box-sizing: border-box;
        padding: 12px 14px;
        background:
          radial-gradient(circle at 12% 0%, rgba(29, 185, 84, 0.28), transparent 34%),
          radial-gradient(circle at 92% 10%, rgba(239, 68, 68, 0.2), transparent 28%),
          linear-gradient(135deg, #0f172a, #172033 62%, #221826);
        color: #fff;
      }
      .brand-mark {
        display: grid;
        place-items: center;
        width: 34px;
        height: 34px;
        border-radius: 12px;
        background: rgba(255, 255, 255, 0.13);
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.18);
        font: 800 17px/1 Arial, sans-serif;
      }
      .brand-copy {
        flex: 1;
        min-width: 0;
      }
      .brand-copy strong,
      .brand-copy small {
        display: block;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .brand-copy strong {
        font: 800 14px/1.2 Arial, sans-serif;
        letter-spacing: -0.02em;
      }
      .brand-copy small {
        margin-top: 2px;
        color: rgba(255, 255, 255, 0.68);
        font: 600 11px/1.2 Arial, sans-serif;
      }
      .close {
        display: grid;
        place-items: center;
        width: 32px;
        height: 32px;
        border: 0;
        border-radius: 10px;
        background: rgba(255, 255, 255, 0.1);
        color: rgba(255, 255, 255, 0.88);
        cursor: pointer;
        font: 800 18px/1 Arial, sans-serif;
        transition: background 140ms ease, transform 140ms ease;
      }
      .close:hover {
        background: rgba(255, 255, 255, 0.18);
        transform: scale(1.03);
      }
      .frame {
        width: 100%;
        height: calc(100% - 58px);
        border: 0;
        background: #f8fafc;
      }
      @media (max-width: 520px) {
        .panel {
          inset: 12px;
          width: auto;
          height: auto;
          min-height: 0;
          border-radius: 12px;
        }
        .launcher {
          right: 12px;
          bottom: 12px;
        }
      }
    </style>
    <section class="panel" aria-label="Playlist Converter panel">
      <header class="chrome">
        <div class="brand-mark" aria-hidden="true">&harr;</div>
        <div class="brand-copy">
          <strong>Playlist Converter</strong>
          <small>Spotify ↔ YouTube Music</small>
        </div>
        <button class="close" type="button" aria-label="Close Playlist Converter">×</button>
      </header>
      <iframe class="frame" title="Playlist Converter"></iframe>
    </section>
    <button class="launcher" type="button" aria-expanded="false">
      <span class="launcher-icon" aria-hidden="true">&harr;</span>
      <span>Convert playlists</span>
    </button>
  `;

  const panel = shadow.querySelector(".panel");
  const frame = shadow.querySelector(".frame");
  const launcher = shadow.querySelector(".launcher");
  const closeButton = shadow.querySelector(".close");

  const hostName = location.hostname.includes("spotify") ? "spotify" : "ytmusic";
  frame.src = chrome.runtime.getURL(`index.html?extension=1&host=${hostName}`);

  function readOpenState() {
    try {
      return window.localStorage.getItem(STORAGE_KEY) === "1";
    } catch (_) {
      return false;
    }
  }

  function writeOpenState(isOpen) {
    try {
      window.localStorage.setItem(STORAGE_KEY, isOpen ? "1" : "0");
    } catch (_) {
      // Storage may be blocked; the panel can still toggle for this page load.
    }
  }

  function setOpen(isOpen) {
    panel.classList.toggle("open", isOpen);
    launcher.setAttribute("aria-expanded", isOpen ? "true" : "false");
    launcher.querySelector("span:last-child").textContent = isOpen
      ? "Hide converter"
      : "Convert playlists";
    writeOpenState(isOpen);
  }

  launcher.addEventListener("click", () => {
    setOpen(!panel.classList.contains("open"));
  });

  closeButton.addEventListener("click", () => {
    setOpen(false);
  });

  chrome.runtime.onMessage.addListener((message) => {
    if (message?.type === "PC_TOGGLE_PANEL") {
      setOpen(!panel.classList.contains("open"));
    }
  });

  setOpen(readOpenState());
})();
