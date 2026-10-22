"""Barramento de eventos assíncrono para notificar a interface (WebSocket)."""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from typing import Any

from app.core.db import utcnow


class EventBus:
    def __init__(self, history: int = 200) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self.recent: deque[dict[str, Any]] = deque(maxlen=history)

    async def publish(self, kind: str, data: dict[str, Any] | None = None) -> None:
        event = {"type": kind, "ts": utcnow(), "data": data or {}}
        self.recent.append(event)
        for q in list(self._subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(event)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)
