from __future__ import annotations

import json
from datetime import datetime

from models.events import StreamEvent
from models.session import SessionSnapshot
from persistence.database import DatabaseManager


class SessionStore:
    def __init__(self, database: DatabaseManager) -> None:
        self.database = database

    async def create_session(
        self,
        snapshot: SessionSnapshot,
        *,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        await self.database.connection.execute(
            """
            INSERT INTO sessions (session_id, snapshot_json, created_at, updated_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                snapshot.session_id,
                snapshot.model_dump_json(),
                created_at.isoformat(),
                snapshot.last_updated_at.isoformat(),
                expires_at.isoformat(),
            ),
        )
        await self.database.connection.commit()

    async def get_session_snapshot(self, session_id: str) -> SessionSnapshot | None:
        cursor = await self.database.connection.execute(
            "SELECT snapshot_json FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return SessionSnapshot.model_validate_json(row["snapshot_json"])

    async def update_session_snapshot(
        self,
        snapshot: SessionSnapshot,
        *,
        expires_at: datetime,
    ) -> None:
        await self.database.connection.execute(
            """
            UPDATE sessions
            SET snapshot_json = ?, updated_at = ?, expires_at = ?
            WHERE session_id = ?
            """,
            (
                snapshot.model_dump_json(),
                snapshot.last_updated_at.isoformat(),
                expires_at.isoformat(),
                snapshot.session_id,
            ),
        )
        await self.database.connection.commit()

    async def append_event(self, event: StreamEvent) -> StreamEvent:
        cursor = await self.database.connection.execute(
            """
            INSERT INTO session_events (session_id, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                event.session_id,
                event.event_type.value,
                event.model_dump_json(),
                event.occurred_at.isoformat(),
            ),
        )
        await self.database.connection.commit()
        event.id = cursor.lastrowid
        return event

    async def get_events_after(
        self,
        session_id: str,
        last_event_id: int | None,
    ) -> list[StreamEvent]:
        if last_event_id is None:
            query = """
                SELECT id, payload_json
                FROM session_events
                WHERE session_id = ?
                ORDER BY id ASC
            """
            params = (session_id,)
        else:
            query = """
                SELECT id, payload_json
                FROM session_events
                WHERE session_id = ? AND id > ?
                ORDER BY id ASC
            """
            params = (session_id, last_event_id)

        cursor = await self.database.connection.execute(query, params)
        rows = await cursor.fetchall()
        events: list[StreamEvent] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            payload["id"] = row["id"]
            events.append(StreamEvent.model_validate(payload))
        return events

    async def upsert_graph_checkpoint(
        self,
        *,
        session_id: str,
        phase: str,
        checkpoint_key: str,
        state: dict,
        created_at: datetime,
        updated_at: datetime,
    ) -> None:
        await self.database.connection.execute(
            """
            INSERT INTO graph_checkpoints (
                session_id,
                phase,
                checkpoint_key,
                state_json,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id, phase, checkpoint_key)
            DO UPDATE SET
                state_json = excluded.state_json,
                updated_at = excluded.updated_at
            """,
            (
                session_id,
                phase,
                checkpoint_key,
                json.dumps(state),
                created_at.isoformat(),
                updated_at.isoformat(),
            ),
        )
        await self.database.connection.commit()

    async def delete_expired_sessions(self, cutoff: datetime) -> int:
        cursor = await self.database.connection.execute(
            "DELETE FROM sessions WHERE updated_at < ?",
            (cutoff.isoformat(),),
        )
        await self.database.connection.commit()
        return cursor.rowcount or 0
