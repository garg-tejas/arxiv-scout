from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import RunnableConfig

from app.config import get_settings


@lru_cache
def get_sqlite_checkpointer() -> SqliteSaver:
    """
    Shared LangGraph SQLite checkpointer for all graphs.

    Uses a sibling file next to the main application database, so it
    stays colocated with the rest of the backend state but does not
    reuse the same tables.
    """
    settings = get_settings()
    db_path: Path = settings.database_path
    graph_db_path = db_path.with_name(db_path.stem + "_graph.db")
    conn = sqlite3.connect(
        graph_db_path,
        check_same_thread=False,
    )
    return SqliteSaver(conn)


def get_run_config(session_id: str) -> RunnableConfig:
    """
    Standard LangGraph run config for this app.

    Carries the session_id as thread identifier so checkpointing and
    tracing stay grouped per session.
    """
    return {"configurable": {"thread_id": session_id}}

