#!/usr/bin/env python3
"""Fetch the Netatmo brand assets used to illustrate this integration.

HACS looks for brand assets inside the integration folder, at
``custom_components/<domain>/brand/``, and only falls back to
brands.home-assistant.io when they are missing. This script fills that folder
from the brand assets Home Assistant already publishes.

The artwork is Netatmo's, reused to identify the hardware this integration
drives -- the same assets the built-in ``netatmo`` integration uses. This
project is not affiliated with or endorsed by Netatmo.

Usage:
    python3 scripts/fetch_brand_icon.py
    python3 scripts/fetch_brand_icon.py --source netatmo --out some/dir
"""

from __future__ import annotations

import argparse
import pathlib
import struct
import sys
import urllib.error
import urllib.request

BRANDS_URL = "https://brands.home-assistant.io"

# name -> the exact square size brands requires, or None to accept any width.
ASSETS: dict[str, int | None] = {
    "icon.png": 256,
    "icon@2x.png": 512,
    "logo.png": None,
}


def png_header(raw: bytes) -> tuple[int, int, int, int]:
    """Return ``(width, height, bit_depth, colour_type)`` from a PNG's IHDR."""
    if raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
        raise ValueError("not a PNG file")
    return struct.unpack(">IIBB", raw[16:26])


def fetch(url: str, timeout: float) -> bytes:
    """Download ``url`` and return its body."""
    request = urllib.request.Request(
        url, headers={"User-Agent": "netatmo-presence-local/1.0"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def main() -> int:
    """Download every brand asset and check it before writing it out."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="netatmo", help="brand domain to copy")
    parser.add_argument(
        "--out",
        default="custom_components/netatmo_presence_local/brand",
        help="output directory",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    for name, expected in ASSETS.items():
        url = f"{BRANDS_URL}/{args.source}/{name}"
        try:
            raw = fetch(url, args.timeout)
        except (urllib.error.URLError, TimeoutError) as err:
            print(f"error: cannot fetch {url}: {err}", file=sys.stderr)
            return 1

        try:
            width, height, depth, colour = png_header(raw)
        except ValueError as err:
            print(f"error: {url}: {err}", file=sys.stderr)
            return 1

        if colour != 6:
            print(
                f"error: {name} is not RGBA; brands requires an alpha channel",
                file=sys.stderr,
            )
            return 1
        if expected is not None and (width, height) != (expected, expected):
            wanted = f"{expected}x{expected}"
            print(
                f"error: {name} is {width}x{height}, expected {wanted}",
                file=sys.stderr,
            )
            return 1

        (out / name).write_bytes(raw)
        print(f"wrote {out / name} ({width}x{height}, depth {depth}, {len(raw)} bytes)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
