from __future__ import annotations

import asyncio
from collections import defaultdict


class StreamBroker:
    def __init__(self, name: str) -> None:
        self.name = name
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._latest: dict[str, object] = {}

    def subscribe(self, key: str, maxsize: int = 1) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subscribers[key].add(queue)

        if key in self._latest:
            self._enqueue(queue, self._latest[key])
        return queue

    def unsubscribe(self, key: str, queue: asyncio.Queue) -> None:
        subscribers = self._subscribers.get(key)
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(key, None)

    def publish(self, key: str, payload: object) -> None:
        self._latest[key] = payload
        for queue in list(self._subscribers.get(key, set())):
            self._enqueue(queue, payload)

    def _enqueue(self, queue: asyncio.Queue, payload: object) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(payload)
