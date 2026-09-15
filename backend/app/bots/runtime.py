"""A dedicated asyncio event loop for the bots.

APScheduler's ``BackgroundScheduler`` runs jobs in worker threads.  The
exchange clients are ``async`` (ccxt.async_support / aiohttp) and their
sessions are bound to one event loop, so instead of ``asyncio.run`` per job -
which would rebuild sessions and reload exchange markets every minute - all
bot coroutines are submitted to this single long-lived loop thread.
"""

import asyncio
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


class BotLoop:
    def __init__(self, name: str = "veles-bot-loop") -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._started = threading.Event()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._started.set()
        self._loop.run_forever()

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()
            self._started.wait(timeout=5)

    @property
    def running(self) -> bool:
        return self._thread.is_alive() and self._loop.is_running()

    def run(self, coro: Coroutine[Any, Any, T], timeout: float | None = 300) -> T:
        """Run ``coro`` on the bot loop from any thread and wait for the result."""
        self.start()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            # APScheduler moves on after a timeout - cancel the coroutine so it cannot keep running
            # alongside the next scheduled run (two AIS ingests racing was a real bug on the Pi)
            future.cancel()
            raise

    def submit(self, coro: Coroutine[Any, Any, Any]) -> "asyncio.Future":
        """Fire-and-forget (e.g. a long-lived stream consumer)."""
        self.start()
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self) -> None:
        if self._thread.is_alive():
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)


bot_loop = BotLoop()
