"""Bounded compatibility workers; all actual IBKR calls use BrokerLoop."""

from concurrent.futures import Future, ThreadPoolExecutor
import threading
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


class DiagnosticWorkers:
    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="diagnostic")
        self._slots = threading.BoundedSemaphore(16)

    def submit(
        self, function: Callable[..., T], *args: Any, **kwargs: Any
    ) -> Future[T]:
        if not self._slots.acquire(blocking=False):
            raise RuntimeError("DIAGNOSTIC_QUEUE_FULL")
        try:
            future = self._pool.submit(function, *args, **kwargs)
        except BaseException:
            self._slots.release()
            raise
        future.add_done_callback(lambda _: self._slots.release())
        return future

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
