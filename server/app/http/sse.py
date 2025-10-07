"""Менеджер событий Server-Sent Events."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator, Dict, Set


class SSEManager:
    """Простой брокер SSE с механизмом широковещательной рассылки."""

    def __init__(self, queue_size: int = 100) -> None:
        self._subscribers: Set[asyncio.Queue[str]] = set()
        self._lock = asyncio.Lock()
        self.queue_size = queue_size

    async def subscribe(self) -> AsyncGenerator[str, None]:
        queue: asyncio.Queue[str] = asyncio.Queue(self.queue_size)
        async with self._lock:
            self._subscribers.add(queue)
        try:
            while True:
                msg = await queue.get()
                yield msg
        finally:
            async with self._lock:
                self._subscribers.discard(queue)

    async def publish(self, event: str, data: Dict) -> None:
        payload = self._format_event(event, data)
        async with self._lock:
            dead: Set[asyncio.Queue[str]] = set()
            for queue in self._subscribers:
                try:
                    queue.put_nowait(payload)
                except asyncio.QueueFull:
                    dead.add(queue)
            for queue in dead:
                self._subscribers.discard(queue)

    @staticmethod
    def _format_event(event: str, data: Dict) -> str:
        body = json.dumps(data, ensure_ascii=False)
        return f"event: {event}\ndata: {body}\n\n"
