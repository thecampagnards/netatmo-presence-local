"""Minimal aiohttp/yarl stand-ins so the API client can be tested offline."""

from __future__ import annotations

import sys
import types
from typing import Any


class ClientError(Exception):
    """Stand-in for aiohttp.ClientError."""


class ClientTimeout:
    """Stand-in for aiohttp.ClientTimeout."""

    def __init__(self, total: float | None = None) -> None:
        self.total = total


class FakeResponse:
    """A single canned HTTP response."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    async def read(self) -> bytes:
        """Return the response body."""
        return self._body

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None


class FakeSession:
    """Records the requests made and replays queued responses."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any] | None]] = []
        self.responses: list[Any] = []

    def queue(self, status: int = 200, body: bytes | str = b"{}") -> None:
        """Queue one response to hand back."""
        if isinstance(body, str):
            body = body.encode()
        self.responses.append(FakeResponse(status, body))

    def queue_exception(self, exc: BaseException) -> None:
        """Queue an exception to raise instead of responding."""
        self.responses.append(exc)

    def get(self, url: str, params: dict[str, Any] | None = None, **_: Any):
        """Return the next queued response for ``url``."""
        self.requests.append((url, params))
        if not self.responses:
            raise AssertionError(f"Unexpected request to {url}")
        nxt = self.responses.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt

    @property
    def last_url(self) -> str:
        """Return the URL of the most recent request."""
        return self.requests[-1][0]

    @property
    def last_params(self) -> dict[str, Any] | None:
        """Return the query parameters of the most recent request."""
        return self.requests[-1][1]


def install() -> None:
    """Register the stub modules under the names api.py imports."""
    if "aiohttp" in sys.modules:
        return
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientError = ClientError
    aiohttp.ClientTimeout = ClientTimeout
    aiohttp.ClientSession = FakeSession
    sys.modules["aiohttp"] = aiohttp

    yarl = types.ModuleType("yarl")
    yarl.URL = str
    sys.modules["yarl"] = yarl
