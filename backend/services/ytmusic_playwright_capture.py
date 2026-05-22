"""
Headed Chromium capture for YouTube Music browser headers (cookies + derived auth).

Used when the Flask API runs on the same machine as the user (typical local dev).
Requires: pip install playwright && playwright install chromium
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

import requests
from ytmusicapi.constants import YTM_DOMAIN
from ytmusicapi.helpers import (
    get_authorization,
    get_visitor_id,
    initialize_headers,
    sapisid_from_cookie,
)

from backend.services.ytmusic_service import _ensure_secure_3papisid_cookie
from backend.utils.logger import get_logger

logger = get_logger(__name__)

# WEB_REMIX expects a Chrome-like UA; ytmusicapi's default USER_AGENT is Firefox and can break SAPISID flows.
_CHROME_WEB_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _extract_visitor_data_from_html(html: str) -> str:
    """Same idea as ytmusicapi.helpers.get_visitor_id — VISITOR_DATA from embedded ytcfg."""
    if not html:
        return ""
    for m in re.finditer(r"ytcfg\.set\s*\(\s*({.+?})\s*\)\s*;", html, re.DOTALL):
        try:
            ytcfg = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        vid = ytcfg.get("VISITOR_DATA")
        if vid:
            return str(vid)
    return ""


def _cookies_to_header_string(cookies: list[dict[str, Any]]) -> str:
    """
    Playwright cookie list → single Cookie header value.
    De-duplicates by cookie name (last occurrence wins) — duplicates break http.cookies.SimpleCookie.
    """
    merged: dict[str, str] = {}
    for c in cookies:
        dom = (c.get("domain") or "").lstrip(".")
        if not any(x in dom for x in ("youtube.com", "google.com", "youtu.be")):
            continue
        name, val = c.get("name"), c.get("value")
        if not name or val is None:
            continue
        merged[str(name)] = str(val)
    return "; ".join(f"{k}={v}" for k, v in merged.items())


def _has_logged_in_google_cookies(cookies: list[dict[str, Any]]) -> bool:
    """Require a logged-in Google session cookie (avoid matching pre-login noise)."""
    names = {c.get("name") for c in cookies}
    return "__Secure-3PSID" in names or "__Secure-1PSID" in names


def build_browser_headers_from_session_cookies(
    cookies: list[dict[str, Any]],
    user_agent: str,
    *,
    visitor_data_hint: str = "",
) -> dict[str, Any]:
    """Build the same style of dict as `ytmusicapi browser` / browser_headers.json."""
    cookie_str = _cookies_to_header_string(cookies)
    if not cookie_str.strip():
        raise ValueError("No YouTube/Google cookies were captured.")
    sapisid_from_cookie(cookie_str)

    ua = (user_agent or "").strip() or _CHROME_WEB_UA

    out: dict[str, Any] = {k.lower(): v for k, v in dict(initialize_headers()).items()}
    out.update(
        {
            "cookie": cookie_str,
            "origin": YTM_DOMAIN,
            "referer": YTM_DOMAIN + "/",
            "x-origin": YTM_DOMAIN,
            "x-goog-authuser": "0",
            "user-agent": ua,
            "accept-language": "en-US,en;q=0.9",
            "x-youtube-bootstrap-logged-in": "true",
            "x-youtube-client-name": "67",
        }
    )

    if visitor_data_hint.strip():
        out["x-goog-visitor-id"] = visitor_data_hint.strip()

    sess = requests.Session()
    sess.headers["User-Agent"] = ua
    sess.headers["Cookie"] = cookie_str

    def _get(url: str) -> requests.Response:
        return sess.get(url, timeout=60)

    if not (out.get("x-goog-visitor-id") or "").strip():
        try:
            vid = get_visitor_id(_get)
            for k, v in vid.items():
                if v:
                    out[str(k).lower()] = str(v)
        except Exception as e:
            logger.warning("Could not fetch visitor id via HTTP (continuing): %s", e)

    sap = sapisid_from_cookie(cookie_str)
    out["authorization"] = get_authorization(f"{sap} {YTM_DOMAIN}")

    out["x-youtube-client-version"] = (
        "1." + time.strftime("%Y%m%d", time.gmtime()) + ".01.00"
    )

    return _ensure_secure_3papisid_cookie(out)


def run_playwright_capture(
    *,
    status: Callable[[str], None] | None = None,
    login_timeout_ms: int = 600_000,
) -> dict[str, Any]:
    """
    Opens a visible Chromium window on https://music.youtube.com.
    User signs in; we poll until Google session cookies appear, then build headers dict.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError(
            "Playwright is not installed. Run: pip install playwright && playwright install chromium"
        ) from e

    def s(msg: str) -> None:
        if status:
            status(msg)
        logger.info("ytmusic capture: %s", msg)

    s("Starting Chromium — log in to YouTube Music in the window that opens.")
    cookies: list[dict[str, Any]] = []
    ua = ""
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=False)
        except Exception as e:
            raise RuntimeError(
                "Could not launch Chromium. If this is a headless server, use paste-headers "
                "instead. On macOS/Linux with a display, run: playwright install chromium"
            ) from e
        try:
            visitor_hint = ""
            context = browser.new_context(locale="en-US", user_agent=_CHROME_WEB_UA)
            page = context.new_page()
            page.goto(YTM_DOMAIN, wait_until="domcontentloaded", timeout=120_000)
            deadline = time.monotonic() + login_timeout_ms / 1000.0
            logged_in = False
            while time.monotonic() < deadline:
                if _has_logged_in_google_cookies(context.cookies()):
                    logged_in = True
                    break
                page.wait_for_timeout(2000)
            if not logged_in:
                raise TimeoutError(
                    "Timed out waiting for sign-in (no session cookies). "
                    "Complete Google login in the Chromium window and try again."
                )
            s("Session detected — reloading YouTube Music to sync cookies…")
            try:
                page.goto(YTM_DOMAIN, wait_until="load", timeout=120_000)
            except Exception as e:
                logger.warning("Post-login reload: %s", e)
            page.wait_for_timeout(2500)
            cookies = context.cookies()
            html = page.content()
            visitor_hint = _extract_visitor_data_from_html(html)
            if not visitor_hint:
                logger.warning("Could not parse VISITOR_DATA from page HTML; will try HTTP fallback.")
            try:
                ua = page.evaluate("() => navigator.userAgent") or _CHROME_WEB_UA
            except Exception:
                ua = _CHROME_WEB_UA
        finally:
            browser.close()

    return build_browser_headers_from_session_cookies(
        cookies, ua, visitor_data_hint=visitor_hint
    )
