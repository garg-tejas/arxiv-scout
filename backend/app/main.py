from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.dependencies import ServiceContainer
from app.routes import sessions
from graph.supervisor import build_supervisor_graph
from persistence.cleanup import cleanup_expired_sessions
from persistence.database import DatabaseManager
from persistence.session_store import SessionStore
from services.artifact_service import ArtifactService
from services.revision_service import RevisionService
from services.session_service import SessionService
from services.stream_service import StreamService


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    database = DatabaseManager(settings.database_path)
    await database.connect()
    await database.initialize()

    session_store = SessionStore(database)
    await cleanup_expired_sessions(session_store, ttl_days=settings.session_ttl_days)

    artifact_service = ArtifactService()
    revision_service = RevisionService()
    stream_service = StreamService(
        session_store=session_store,
        heartbeat_seconds=settings.sse_heartbeat_seconds,
    )
    session_service = SessionService(
        session_store=session_store,
        artifact_service=artifact_service,
        stream_service=stream_service,
        ttl_days=settings.session_ttl_days,
    )

    app.state.services = ServiceContainer(
        settings=settings,
        database=database,
        session_store=session_store,
        stream_service=stream_service,
        artifact_service=artifact_service,
        revision_service=revision_service,
        session_service=session_service,
        supervisor_graph=build_supervisor_graph(),
    )

    yield

    await database.close()


app = FastAPI(
    title="ArXiv Literature Scout",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(sessions.router)


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
