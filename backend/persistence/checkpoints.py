from __future__ import annotations

from datetime import datetime

from persistence.session_store import SessionStore


class GraphCheckpointStore:
    def __init__(self, session_store: SessionStore) -> None:
        self.session_store = session_store

    async def bootstrap_session(self, session_id: str, created_at: datetime) -> None:
        await self.session_store.upsert_graph_checkpoint(
            session_id=session_id,
            phase="none",
            checkpoint_key="bootstrap",
            state={},
            created_at=created_at,
            updated_at=created_at,
        )
