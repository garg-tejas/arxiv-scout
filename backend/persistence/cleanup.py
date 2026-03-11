from __future__ import annotations

from datetime import datetime, timedelta, timezone

from persistence.session_store import SessionStore


async def cleanup_expired_sessions(session_store: SessionStore, *, ttl_days: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    return await session_store.delete_expired_sessions(cutoff)
