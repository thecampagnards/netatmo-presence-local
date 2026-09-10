"""An aiohttp-shaped session backed by urllib, so api.py can hit a real server.

Only the surface api.py uses is implemented: ``get()`` returning an async
context manager exposing ``status`` and ``read()``.
"""

from __future__ import annotations

import asyncio
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class _Response:
    """One HTTP response."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    async def read(self) -> bytes:
        """Return the response body."""
        return self._body

    async def __aenter__(self) -> _Response:
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        return None


class _ResponseContext:
    """Awaitable-free async context manager returned by ``get()``."""

    def __init__(self, url: str, params: dict[str, Any] | None, timeout: float) -> None:
        self._url = url
        self._params = params
        self._timeout = timeout

    async def __aenter__(self) -> _Response:
        url = self._url
        if self._params:
            url = f"{url}?{urllib.parse.urlencode(self._params)}"
        return await asyncio.get_running_loop().run_in_executor(None, self._fetch, url)

    async def __aexit__(self, *exc_info: Any) -> None:
        return None

    def _fetch(self, url: str) -> _Response:
        """Perform the blocking request."""
        try:
            with urllib.request.urlopen(url, timeout=self._timeout) as response:
                return _Response(response.status, response.read())
        except urllib.error.HTTPError as err:
            return _Response(err.code, err.read())


class UrllibSession:
    """Drop-in replacement for aiohttp.ClientSession over urllib."""

    def get(
        self, url: str, params: dict[str, Any] | None = None, timeout: Any = None
    ) -> _ResponseContext:
        """Return an async context manager performing the GET."""
        total = getattr(timeout, "total", None) or 10
        return _ResponseContext(url, params, total)
