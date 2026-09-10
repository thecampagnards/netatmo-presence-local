"""Thin async client for the Netatmo Presence local HTTP API.

The camera exposes an unauthenticated ``/command/ping`` endpoint plus a set of
commands namespaced under a per-device secret (the "vkey"), e.g.::

    http://camera.local/<vkey>/command/floodlight_get_config

The vkey is a secret: it is never logged by this module.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp
from yarl import URL

from .const import (
    ALREADY_IN_STATE_CODE,
    DEFAULT_TIMEOUT,
    FLOODLIGHT_MODES,
    NIGHT_TRIGGERS,
    STREAM_PATHS,
)

_LOGGER = logging.getLogger(__name__)


class NetatmoLocalError(Exception):
    """Base error for the local API."""


class NetatmoLocalConnectionError(NetatmoLocalError):
    """The camera could not be reached."""


class NetatmoLocalAuthError(NetatmoLocalError):
    """The vkey was rejected by the camera."""


class NetatmoLocalNotSupportedError(NetatmoLocalError):
    """The firmware does not implement this command."""


class NetatmoLocalCommandError(NetatmoLocalError):
    """The camera accepted the command but refused to act on it.

    These come back as ``{"error": {"code": .., "message": ..}}``, sometimes
    under a 4xx status -- a rejected command still proves the route exists.
    """

    def __init__(self, message: str, code: int | None = None) -> None:
        """Store the camera's error message and numeric code."""
        super().__init__(message)
        self.code = code

    @property
    def is_already_in_state(self) -> bool:
        """Return True when the camera was already in the requested state.

        Asking a live camera to turn on answers 409 / code 7 "Already on";
        the caller got what it wanted, so this is not a failure.
        """
        return self.code == ALREADY_IN_STATE_CODE or "already" in str(self).lower()


# Openings of the web server's error page, in the forms it has been seen in.
_HTML_MARKERS = (b"<?xml", b"<!doctype", b"<html")


def _redact(url: str | URL, vkey: str) -> str:
    """Return ``url`` with the vkey replaced, for safe logging."""
    text = str(url)
    return text.replace(vkey, "***") if vkey else text


def _is_html(payload: bytes) -> bool:
    """Return True when ``payload`` is a web page rather than an API answer."""
    head = payload[:200].lstrip().lower()
    return head.startswith(_HTML_MARKERS)


class NetatmoPresenceLocalApi:
    """Talk to a Netatmo Presence over the local network."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        vkey: str,
        *,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialise the client for ``host`` using the device secret ``vkey``."""
        self._session = session
        self._host = host.rstrip("/")
        self._vkey = vkey.strip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    # -- URL helpers ---------------------------------------------------------

    @property
    def host(self) -> str:
        """Return the configured host, without scheme."""
        return self._host

    @property
    def base_url(self) -> str:
        """Return the camera root URL."""
        if self._host.startswith(("http://", "https://")):
            return self._host
        return f"http://{self._host}"

    def path_url(self, path: str) -> str:
        """Return the absolute, vkey-scoped URL for ``path``."""
        return f"{self.base_url}/{self._vkey}/{path.lstrip('/')}"

    @property
    def snapshot_url(self) -> str:
        """Return the still-image URL."""
        return self.path_url("live/snapshot_720.jpg")

    def stream_url(self, path: str = STREAM_PATHS[0]) -> str:
        """Return the HLS playlist URL for a discovered playlist ``path``."""
        return self.path_url(path)

    # -- Transport -----------------------------------------------------------

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        scoped: bool = True,
        raw: bool = False,
    ) -> Any:
        """Perform a GET and return decoded JSON, or raw bytes when ``raw``."""
        url = self.path_url(path) if scoped else f"{self.base_url}/{path.lstrip('/')}"
        try:
            async with self._session.get(
                url, params=params, timeout=self._timeout
            ) as resp:
                if resp.status in (401, 403):
                    raise NetatmoLocalAuthError(
                        f"Camera rejected the vkey ({resp.status})"
                    )
                if resp.status == 404:
                    raise NetatmoLocalNotSupportedError(
                        f"{_redact(url, self._vkey)} not implemented (404)"
                    )
                status = resp.status
                payload = await resp.read()
        except TimeoutError as err:
            raise NetatmoLocalConnectionError(
                f"Timeout talking to {self._host}"
            ) from err
        except aiohttp.ClientError as err:
            raise NetatmoLocalConnectionError(
                f"Cannot reach {self._host}: {err}"
            ) from err

        if raw:
            return payload

        # Unknown routes are answered with the web server's HTML error page,
        # and not always under a 4xx status. Treat any HTML body on a command
        # as proof the command does not exist.
        if _is_html(payload):
            raise NetatmoLocalNotSupportedError(
                f"{_redact(url, self._vkey)} returned an HTML error page"
            )

        try:
            data = json.loads(payload)
        except ValueError as err:
            if status >= 400:
                raise NetatmoLocalError(
                    f"{_redact(url, self._vkey)} returned HTTP {status}"
                ) from err
            raise NetatmoLocalError(
                f"Malformed response from {_redact(url, self._vkey)}"
            ) from err

        # Command errors come back in-band, under HTTP 200 or a 4xx alike.
        if isinstance(data, dict) and "error" in data:
            error = data["error"]
            if isinstance(error, dict):
                raise NetatmoLocalCommandError(
                    f"Camera error: {error.get('message')}", error.get("code")
                )
            raise NetatmoLocalCommandError(f"Camera error: {error}")

        if status >= 400:
            raise NetatmoLocalError(
                f"{_redact(url, self._vkey)} returned HTTP {status}"
            )
        return data

    async def probe(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        read_body: bool = True,
    ) -> bool:
        """Return True when ``path`` exists on this firmware.

        A missing route -- a 404, or the web server's HTML error page -- counts
        as unsupported; an in-band error still proves the command is there.

        Media paths are probed with ``read_body=False``: a snapshot is a
        quarter of a megabyte, and only the status code matters here.
        """
        if not read_body:
            return await self._probe_status(path, params)

        try:
            await self._get(path, params)
        except NetatmoLocalNotSupportedError:
            return False
        except (NetatmoLocalConnectionError, NetatmoLocalAuthError):
            raise
        except NetatmoLocalError:
            return True
        return True

    async def _probe_status(
        self, path: str, params: dict[str, Any] | None = None
    ) -> bool:
        """Return True when ``path`` answers, without downloading its body."""
        url = self.path_url(path)
        try:
            async with self._session.get(
                url, params=params, timeout=self._timeout
            ) as resp:
                if resp.status in (401, 403):
                    raise NetatmoLocalAuthError(
                        f"Camera rejected the vkey ({resp.status})"
                    )
                return resp.status < 400
        except TimeoutError as err:
            raise NetatmoLocalConnectionError(
                f"Timeout talking to {self._host}"
            ) from err
        except aiohttp.ClientError as err:
            raise NetatmoLocalConnectionError(
                f"Cannot reach {self._host}: {err}"
            ) from err

    # -- Commands ------------------------------------------------------------

    async def async_ping(self) -> dict[str, Any]:
        """Return the unauthenticated identity payload of the camera."""
        return await self._get("command/ping", scoped=False)

    async def async_ping_scoped(self) -> dict[str, Any]:
        """Ping through the vkey-scoped route, to validate the secret."""
        return await self._get("command/ping")

    async def async_get_config(self) -> dict[str, Any]:
        """Return the full module configuration."""
        return await self._get("command/get_config")

    async def async_get_floodlight_config(self) -> dict[str, Any]:
        """Return ``{intensity, mode, night: {...}}``."""
        return await self._get("command/floodlight_get_config")

    async def async_set_floodlight_config(self, config: dict[str, Any]) -> Any:
        """Push a floodlight configuration object."""
        mode = config.get("mode")
        if mode is not None and mode not in FLOODLIGHT_MODES:
            raise ValueError(f"Unknown floodlight mode: {mode}")
        intensity = config.get("intensity")
        if intensity is not None and not 0 <= int(intensity) <= 100:
            raise ValueError("intensity must be between 0 and 100")
        night = config.get("night")
        if night is not None:
            unknown = set(night) - set(NIGHT_TRIGGERS)
            if unknown:
                raise ValueError(f"Unknown night triggers: {sorted(unknown)}")
        return await self._get(
            "command/floodlight_set_config",
            {"config": json.dumps(config, separators=(",", ":"))},
        )

    async def async_set_monitoring(self, enabled: bool) -> Any:
        """Turn video monitoring on or off.

        The camera rejects a no-op with "Already on"; the requested state is
        nonetheless reached, so that is reported as success.
        """
        try:
            return await self._get(
                "command/changestatus", {"status": "on" if enabled else "off"}
            )
        except NetatmoLocalCommandError as err:
            if err.is_already_in_state:
                return {"status": "ok", "already_in_state": True}
            raise

    async def async_get_events(self, offset: int = 10) -> dict[str, Any]:
        """Return the most recent events stored on the camera."""
        return await self._get("command/get_events_until", {"offset": offset})

    async def async_get_snapshot(self) -> bytes:
        """Return a JPEG still."""
        return await self._get("live/snapshot_720.jpg", raw=True)

    async def async_raw_command(
        self, command: str, params: dict[str, Any] | None = None
    ) -> Any:
        """Call an arbitrary vkey-scoped command (escape hatch)."""
        return await self._get(f"command/{command.lstrip('/')}", params)
