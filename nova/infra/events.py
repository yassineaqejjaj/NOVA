"""Execution event bus.

Events are persisted (``execution_events``, ordered by ``seq``) **and** published on Valkey channel
``nova:exec:{task_id}``. The SSE endpoint replays persisted events then follows the channel, so a
reconnecting client never misses progress and nothing is simulated.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any, Protocol

import redis.asyncio as redis

from nova.config import get_settings

log = logging.getLogger(__name__)


def channel(task_id: str) -> str:
    return f"nova:exec:{task_id}"


class Publisher(Protocol):
    async def publish(self, task_id: str, event: dict[str, Any]) -> None: ...

    def subscribe(self, task_id: str) -> AsyncIterator[dict[str, Any]]: ...


class ValkeyPublisher:
    def __init__(self, url: str) -> None:
        self._client = redis.from_url(url, decode_responses=True)

    async def publish(self, task_id: str, event: dict[str, Any]) -> None:
        try:
            await self._client.publish(channel(task_id), json.dumps(event, default=str))
        except redis.RedisError:
            log.warning("Valkey publish failed (events remain persisted)", exc_info=True)

    async def subscribe(self, task_id: str) -> AsyncIterator[dict[str, Any]]:
        pubsub = self._client.pubsub()
        await pubsub.subscribe(channel(task_id))
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
                if message is None:
                    yield {"type": "heartbeat"}
                    continue
                yield json.loads(message["data"])
        finally:
            await pubsub.unsubscribe(channel(task_id))
            await pubsub.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()


class MemoryPublisher:
    """In-process publisher (tests, eager mode)."""

    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, task_id: str, event: dict[str, Any]) -> None:
        self.published.append((task_id, event))
        for queue in self._queues.get(task_id, []):
            queue.put_nowait(event)

    async def subscribe(self, task_id: str) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue = asyncio.Queue()
        self._queues[task_id].append(queue)
        try:
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield {"type": "heartbeat"}
        finally:
            self._queues[task_id].remove(queue)


_publisher: Publisher | None = None


def get_publisher() -> Publisher:
    global _publisher
    if _publisher is None:
        settings = get_settings()
        _publisher = MemoryPublisher() if settings.env == "test" else ValkeyPublisher(settings.valkey_url)
    return _publisher


def set_publisher(publisher: Publisher | None) -> None:
    global _publisher
    _publisher = publisher
