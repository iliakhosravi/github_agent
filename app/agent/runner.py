"""Bridge between Flask's synchronous request handling and the async agent.

A single background event loop is kept for the process lifetime; each request
submits its coroutine to it and blocks on the result. This is cheaper and safer
than `asyncio.run()` per request (which would tear down httpx transports and
anyio task groups on every call).
"""
from __future__ import annotations

import asyncio
import threading
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, Coroutine

from ..services.errors import UpstreamError


class AsyncRunner:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop

            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=self._run_loop, args=(loop,), name="agent-loop", daemon=True
            )
            thread.start()
            self._loop, self._thread = loop, thread
            return loop

    @staticmethod
    def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def run(self, coro: Coroutine[Any, Any, Any], timeout: float | None = None) -> Any:
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout)
        except FutureTimeout as exc:
            future.cancel()
            raise UpstreamError(
                f"The agent did not finish within {timeout:.0f}s."
            ) from exc

    def shutdown(self) -> None:
        with self._lock:
            if self._loop is not None:
                self._loop.call_soon_threadsafe(self._loop.stop)
            self._loop = None
            self._thread = None


runner = AsyncRunner()
