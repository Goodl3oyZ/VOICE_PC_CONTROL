"""In-process event broadcast to WebSocket subscribers (§14.2 step 11)."""
from __future__ import annotations

import asyncio
from typing import Any


class Broadcaster:
    def __init__(self, queue_size: int = 100):
        self._subs: set[asyncio.Queue[dict[str, Any]]] = set()
        self._size = queue_size

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(self._size)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subs.discard(q)

    async def publish(self, event: dict[str, Any]) -> None:
        for q in list(self._subs):
            if q.full():  # slow client: drop oldest, it can resync from GET /jobs/{id}
                q.get_nowait()
            q.put_nowait(event)
