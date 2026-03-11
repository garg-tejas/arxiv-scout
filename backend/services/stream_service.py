from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator

from models.events import StreamEvent
from persistence.session_store import SessionStore


class StreamService:
    def __init__(self, session_store: SessionStore, *, heartbeat_seconds: int) -> None:
        self.session_store = session_store
        self.heartbeat_seconds = heartbeat_seconds
        self._subscribers: dict[str, set[asyncio.Queue[StreamEvent]]] = defaultdict(set)

    async def publish(self, event: StreamEvent) -> StreamEvent:
        stored_event = await self.session_store.append_event(event)
        for queue in list(self._subscribers[event.session_id]):
            queue.put_nowait(stored_event)
        return stored_event

    async def stream(
        self,
        session_id: str,
        last_event_id: int | None = None,
    ) -> AsyncIterator[bytes]:
        backlog = await self.session_store.get_events_after(session_id, last_event_id)
        for event in backlog:
            yield self._encode_event(event)

        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        self._subscribers[session_id].add(queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=self.heartbeat_seconds)
                    yield self._encode_event(event)
                except TimeoutError:
                    yield b": heartbeat\n\n"
        finally:
            self._subscribers[session_id].discard(queue)
            if not self._subscribers[session_id]:
                self._subscribers.pop(session_id, None)

    @staticmethod
    def _encode_event(event: StreamEvent) -> bytes:
        payload = event.model_dump_json()
        return f"id: {event.id}\nevent: {event.event_type.value}\ndata: {payload}\n\n".encode("utf-8")
