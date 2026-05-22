#!/usr/bin/env python3
"""
Load request headers from a text file and write ytmusicapi browser auth JSON.
Avoids pasting megabytes into an interactive terminal.

Usage (from project root):
  python3 scripts/ytmusic_browser_from_file.py path/to/headers.txt backend/browser_headers.json

The input file should look like DevTools "Request headers": one header per line as
  Header-Name: value
The cookie value must be a single line (semicolon-separated).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description="ytmusicapi browser setup from a headers file.")
    p.add_argument("headers_txt", type=Path, help="Plain text file of request headers")
    p.add_argument(
        "out_json",
        type=Path,
        nargs="?",
        default=Path("backend/browser_headers.json"),
        help="Output path (default: backend/browser_headers.json)",
    )
    args = p.parse_args()

    if not args.headers_txt.is_file():
        print(f"Not found: {args.headers_txt}", file=sys.stderr)
        return 1

    raw = args.headers_txt.read_text(encoding="utf-8")
    try:
        from ytmusicapi.auth.browser import setup_browser
    except ImportError:
        print("Install ytmusicapi: pip install ytmusicapi", file=sys.stderr)
        return 1

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    setup_browser(str(args.out_json), raw)
    print(f"Wrote {args.out_json.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
