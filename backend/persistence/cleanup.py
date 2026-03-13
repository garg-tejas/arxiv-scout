from __future__ import annotations

from datetime import datetime, timezone

from persistence.session_store import SessionStore


async def cleanup_expired_sessions(
    session_store: SessionStore, *, ttl_days: int
) -> int:
    now = datetime.now(timezone.utc)
    return await session_store.delete_expired_sessions(now)
