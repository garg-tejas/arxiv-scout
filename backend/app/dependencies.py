from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.config import Settings
from persistence.database import DatabaseManager
from persistence.session_store import SessionStore
from services.artifact_service import ArtifactService
from services.revision_service import RevisionService
from services.session_service import SessionService
from services.stream_service import StreamService


@dataclass(slots=True)
class ServiceContainer:
    settings: Settings
    database: DatabaseManager
    session_store: SessionStore
    stream_service: StreamService
    artifact_service: ArtifactService
    revision_service: RevisionService
    session_service: SessionService
    supervisor_graph: object


def get_services(request: Request) -> ServiceContainer:
    return request.app.state.services
