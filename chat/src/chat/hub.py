"""Wakes every open stream on a thread when something happens on it.

In process: one server, as `chat serve` runs it. Every call is on the event loop (the
endpoints that notify are `async`), so an `asyncio.Event` needs no lock. A second server
process would need a shared channel; until then a stream's replay from `after` turns a
missed wake-up into a delay, never a lost message.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager


class Hub:
    def __init__(self) -> None:
        self._waiting: dict[str, set[asyncio.Event]] = defaultdict(set)

    def notify(self, thread_id: str) -> None:
        for event in self._waiting.get(thread_id, ()):
            event.set()

    @contextmanager
    def listen(self, thread_id: str) -> Iterator[asyncio.Event]:
        event = asyncio.Event()
        self._waiting[thread_id].add(event)
        try:
            yield event
        finally:
            self._waiting[thread_id].discard(event)
            if not self._waiting[thread_id]:
                del self._waiting[thread_id]
