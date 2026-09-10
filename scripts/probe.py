#!/usr/bin/env python3
"""Probe a Netatmo Presence's local API and report what the firmware answers.

Only GET requests are made, and only to endpoints that read state -- nothing
here changes the camera's configuration. ``changestatus`` is probed without
its ``status`` parameter precisely so it cannot toggle monitoring.

Usage:
    python3 scripts/probe.py camera-parking.home <device-key>
    python3 scripts/probe.py camera-parking.home <device-key> --extra get_zones
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

# Commands worth trying, beyond the ones the integration already relies on.
# Some only route when their parameters are present -- a bare
# ``get_events_until`` 404s on firmwares that do implement it -- so the query
# string is part of the candidate.
#
# ``changestatus`` is deliberately absent: it only routes with its ``status``
# parameter, and supplying one would switch monitoring. Test it by hand if you
# need to know, with ``status=on``, which never turns a camera off.
CANDIDATE_COMMANDS: tuple[str, ...] = (
    "ping",
    "get_config",
    "get_status",
    "getmodulestatus",
    "floodlight_get_config",
    "get_light_config",
    "get_events_until?offset=1",
    "get_events?offset=1",
    "sd_status",
    "sdcard_status",
    "get_ftp_config",
    "get_timelapse_config",
    "get_zone_config",
    "get_zones",
    "get_notification_config",
    "get_detection_config",
)

CANDIDATE_PATHS: tuple[str, ...] = (
    "live/snapshot_720.jpg",
    "live/index_local.m3u8",
    "live/index.m3u8",
    "live/files/high/index.m3u8",
    "live/files/medium/index.m3u8",
)

PREVIEW_LIMIT = 400


def fetch(url: str, timeout: float) -> tuple[int, bytes, str]:
    """Return ``(status, body, content_type)`` for ``url``."""
    request = urllib.request.Request(url, headers={"User-Agent": "netatmo-probe/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), response.headers.get_content_type()
    except urllib.error.HTTPError as err:
        ctype = err.headers.get_content_type() if err.headers else ""
        return err.code, err.read(), ctype


def describe(status: int, body: bytes, content_type: str, vkey: str = "") -> str:
    """Summarise a response in one line, with the device key blanked out."""
    if status == 404:
        return "not implemented"
    if status >= 400:
        return f"HTTP {status}"

    if content_type.startswith(("image/", "video/", "application/octet-stream")):
        return f"HTTP {status}, {content_type}, {len(body)} bytes"

    text = body.decode("utf-8", errors="replace").strip()
    try:
        parsed = json.loads(text)
    except ValueError:
        preview = text.replace("\n", " ")[:PREVIEW_LIMIT]
        return f"HTTP {status}, {content_type or 'text'}: {redact(preview, vkey)}"
    rendered = json.dumps(parsed, ensure_ascii=False)[:PREVIEW_LIMIT]
    return f"HTTP {status}: {redact(rendered, vkey)}"


def redact(text: str, vkey: str) -> str:
    """Blank out the device key so a report can be shared safely.

    The firmware embeds the key in ``local_url``, so responses leak it unless
    it is stripped here.
    """
    return text.replace(vkey, "<KEY>") if vkey else text


def main() -> int:
    """Probe every candidate endpoint and print a report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="camera hostname or IP, without http://")
    parser.add_argument("vkey", help="the secret path segment of the local API")
    parser.add_argument(
        "--extra",
        nargs="*",
        default=[],
        metavar="COMMAND",
        help="additional command names to try",
    )
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    host = args.host.strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    vkey = args.vkey.strip().strip("/")

    print(f"# Netatmo Presence local API probe -- {host}\n")

    print("## Unauthenticated")
    status, body, ctype = fetch(f"{host}/command/ping", args.timeout)
    print(f"  {'command/ping':<38} {describe(status, body, ctype, vkey)}")
    if status >= 400:
        print(
            "\nThe camera did not answer the unauthenticated ping; check the "
            "address before trusting anything below.",
            file=sys.stderr,
        )

    supported: list[str] = []

    print("\n## Commands")
    for command in (*CANDIDATE_COMMANDS, *args.extra):
        url = f"{host}/{vkey}/command/{command}"
        status, body, ctype = fetch(url, args.timeout)
        print(f"  {'command/' + command:<38} {describe(status, body, ctype, vkey)}")
        if status != 404:
            supported.append(f"command/{command}")

    print("\n## Media paths")
    for path in CANDIDATE_PATHS:
        status, body, ctype = fetch(f"{host}/{vkey}/{path}", args.timeout)
        print(f"  {path:<38} {describe(status, body, ctype, vkey)}")
        if status != 404:
            supported.append(path)

    print(f"\n## Summary\n  {len(supported)} endpoints answered:")
    for endpoint in supported:
        print(f"    - {endpoint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
