"""Bounded, single-loop ownership of the IBKR client."""

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import TimeoutError as FutureTimeout
import threading
from typing import Any, TypeVar

T = TypeVar("T")


class BrokerLoop:
    def __init__(self, factory: Callable[[], Any], capacity: int = 32):
        self.factory = factory
        self._slots = threading.BoundedSemaphore(capacity)
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.client: Any = None
        self._startup_error: BaseException | None = None
        self._command_lock: asyncio.Lock | None = None

    def start(self) -> None:
        if self._thread is not None:
            return

        def worker() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._command_lock = asyncio.Lock()
            try:
                self.client = self.factory()
            except BaseException as exc:
                self._startup_error = exc
                self._ready.set()
                loop.close()
                return
            self._ready.set()
            try:
                loop.run_forever()
            finally:
                tasks = asyncio.all_tasks(loop)
                for task in tasks:
                    task.cancel()
                loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
                self.client.disconnect()
                loop.close()

        self._thread = threading.Thread(target=worker, name="ibkr-owner", daemon=True)
        self._thread.start()
        if not self._ready.wait(8):
            raise RuntimeError("BROKER_STARTUP_TIMEOUT")
        if self._startup_error is not None:
            raise RuntimeError("BROKER_STARTUP_FAILED") from self._startup_error

    def run(
        self,
        operation: Callable[[Any], Awaitable[T]],
        *,
        timeout: float = 8,
        cancel_on_timeout: bool = True,
    ) -> T:
        if self._loop is None or self._thread is None or not self._thread.is_alive():
            raise RuntimeError("BROKER_NOT_STARTED")
        if threading.current_thread() is self._thread:
            raise RuntimeError("BROKER_SYNC_CALL_ON_OWNER_LOOP")
        if not self._slots.acquire(blocking=False):
            raise RuntimeError("BROKER_QUEUE_FULL")

        async def invoke() -> T:
            assert self._command_lock is not None
            async with self._command_lock:
                return await operation(self.client)

        try:
            future = asyncio.run_coroutine_threadsafe(invoke(), self._loop)
        except BaseException:
            self._slots.release()
            raise
        future.add_done_callback(lambda _: self._slots.release())
        try:
            return future.result(timeout=timeout)
        except FutureTimeout:
            if cancel_on_timeout:
                future.cancel()
            raise TimeoutError("BROKER_DEADLINE_EXCEEDED") from None

    def close(self) -> None:
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=8)
            if self._thread.is_alive():
                raise RuntimeError("BROKER_SHUTDOWN_TIMEOUT")
