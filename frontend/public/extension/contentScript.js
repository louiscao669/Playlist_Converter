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
        font-family: Arial, sans-serif;
      }
      .launcher {
        position: fixed;
        right: 18px;
        bottom: 24px;
        z-index: 2147483647;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        border: 0;
        border-radius: 999px;
        padding: 11px 15px;
        background: linear-gradient(135deg, #1db954, #ff0000);
        color: #fff;
        font: 700 13px/1 Arial, sans-serif;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.28);
        cursor: pointer;
      }
      .launcher:hover {
        filter: brightness(1.06);
      }
      .panel {
        position: fixed;
        top: 76px;
        right: 18px;
        z-index: 2147483646;
        width: min(420px, calc(100vw - 36px));
        height: min(720px, calc(100vh - 108px));
        min-height: 460px;
        border-radius: 16px;
        overflow: hidden;
        background: #fff;
        box-shadow: 0 22px 70px rgba(0, 0, 0, 0.34);
        border: 1px solid rgba(15, 23, 42, 0.16);
        display: none;
      }
      .panel.open {
        display: block;
      }
      .frame {
        width: 100%;
        height: 100%;
        border: 0;
        background: #fff;
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
      <iframe class="frame" title="Playlist Converter"></iframe>
    </section>
    <button class="launcher" type="button" aria-expanded="false">
      <span aria-hidden="true">&harr;</span>
      <span>Convert playlists</span>
    </button>
  `;

  const panel = shadow.querySelector(".panel");
  const frame = shadow.querySelector(".frame");
  const launcher = shadow.querySelector(".launcher");

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

  chrome.runtime.onMessage.addListener((message) => {
    if (message?.type === "PC_TOGGLE_PANEL") {
      setOpen(!panel.classList.contains("open"));
    }
  });

  setOpen(readOpenState());
})();
