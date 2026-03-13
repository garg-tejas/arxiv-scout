from __future__ import annotations

from pathlib import Path

from langchain_core.runnables.config import RunnableConfig

from app.config import get_settings


def get_graph_db_path() -> Path:
    """Return the path to the LangGraph checkpoint database."""
    settings = get_settings()
    db_path: Path = settings.database_path
    return db_path.with_name(db_path.stem + "_graph.db")


def get_run_config(session_id: str, *, namespace: str) -> RunnableConfig:
    """
    Standard LangGraph run config for this app.

    Carries the session_id as thread identifier so checkpointing and
    tracing stay grouped per session.  The namespace prevents different
    graphs (discovery, analysis, survey) from colliding on the same
    checkpoint thread.
    """
    return {"configurable": {"thread_id": f"{session_id}:{namespace}"}}
