"""An in-process stand-in for a Netatmo Presence, for integration tests."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

VKEY = "abcdef123456"

# Mirrors the real firmware: ``local_url`` embeds the device key, and a
# Presence reports its module type as its product name.
PING = {
    "local_url": f"http://127.0.0.1/{VKEY}",
    "product_name": "noc",
}

# Unknown routes get the embedded web server's error page, not a JSON error.
ERROR_PAGE = (
    b'<?xml version="1.0" encoding="iso-8859-1"?>\n'
    b'<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"\n'
    b'    "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">\n'
    b'<html xmlns="http://www.w3.org/1999/xhtml"><head>\n'
    b"<title>404 Not Found</title></head><body>\n"
    b"<h1>Not Found</h1></body></html>\n"
)
CONFIG = {
    "id": "70:ee:50:11:22:33",
    "name": "Parking",
    "type": "NOC",
    "status": "on",
    "sd_status": 3,
    "alim_status": 2,
    "firmware": 176,
}
EVENTS = {
    "events": [
        {"id": "e1", "type": "human", "time": 1_757_000_100},
        {"id": "e2", "type": "vehicle", "time": 1_757_000_000},
    ]
}
JPEG = b"\xff\xd8\xff" + b"x" * 512


class FakeCamera:
    """A throwaway HTTP server mimicking the camera's local API."""

    def __init__(self) -> None:
        self.floodlight: dict[str, Any] = {
            "intensity": 100,
            "mode": "auto",
            "night": {
                "always": False,
                "person": True,
                "vehicle": True,
                "animal": False,
                "movement": False,
            },
        }
        self.monitoring = True
        self.stream_paths = {"live/index_local.m3u8"}
        # Some firmwares answer 404 for an unknown route, others serve the
        # error page under 200; both must read as "command absent".
        self.missing_status = 404
        # The observed Presence firmware does not implement get_config.
        self.serves_get_config = False
        self.serves_events = False
        # The observed Presence answers ping only under the device key.
        self.serves_unscoped_ping = False
        self.serves_scoped_ping = True
        self.writes: list[dict[str, Any]] = []
        self._server = HTTPServer(("127.0.0.1", 0), _handler_for(self))
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def host(self) -> str:
        """Return ``host:port`` of the running server."""
        return f"127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self) -> FakeCamera:
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _handler_for(camera: FakeCamera):
    """Build a request handler bound to ``camera``'s state."""

    class Handler(BaseHTTPRequestHandler):
        """Serve the routes the observed Presence firmware serves."""

        def log_message(self, *args: object) -> None:
            """Stay quiet during tests."""

        def _send(self, code: int, body: Any, ctype: str = "application/json") -> None:
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            parsed = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            path = parsed.path

            if path == "/command/ping":
                if not camera.serves_unscoped_ping:
                    return self._send(404, ERROR_PAGE, "text/html")
                return self._send(200, PING)
            if not path.startswith(f"/{VKEY}/"):
                return self._send(403, ERROR_PAGE, "text/html")

            rest = path[len(VKEY) + 2 :]
            if rest == "command/ping":
                if not camera.serves_scoped_ping:
                    return self._send(404, ERROR_PAGE, "text/html")
                return self._send(200, PING)
            if rest == "command/get_config" and camera.serves_get_config:
                status = "on" if camera.monitoring else "off"
                return self._send(200, {**CONFIG, "status": status})
            if rest == "command/floodlight_get_config":
                return self._send(200, camera.floodlight)
            if rest == "command/floodlight_set_config":
                try:
                    config = json.loads(query.get("config", ""))
                except ValueError:
                    return self._send(200, {"error": {"message": "bad config"}})
                camera.writes.append(config)
                camera.floodlight = config
                return self._send(200, {"status": "ok"})
            if rest == "command/changestatus":
                # Without its parameter the route does not match at all, and a
                # no-op is refused with an in-band error under HTTP 409.
                status = query.get("status")
                if status not in ("on", "off"):
                    return self._send(404, ERROR_PAGE, "text/html")
                wanted = status == "on"
                if wanted == camera.monitoring:
                    state = "on" if wanted else "off"
                    return self._send(
                        409,
                        {"error": {"code": 7, "message": f"Already {state}"}},
                        "application/json",
                    )
                camera.monitoring = wanted
                return self._send(200, {"status": "ok"})
            if rest == "command/get_events_until" and camera.serves_events:
                return self._send(200, EVENTS)
            if rest == "live/snapshot_720.jpg":
                return self._send(200, JPEG, "image/jpeg")
            if rest in camera.stream_paths:
                return self._send(200, b"#EXTM3U\n", "application/vnd.apple.mpegurl")
            return self._send(camera.missing_status, ERROR_PAGE, "text/html")

    return Handler
