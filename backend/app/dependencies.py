from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.config import Settings
from integrations.arxiv import ArxivClient
from integrations.firecrawl import FirecrawlClient
from integrations.semantic_scholar import SemanticScholarClient
from persistence.database import DatabaseManager
from persistence.session_store import SessionStore
from services.analysis_service import AnalysisService
from services.artifact_service import ArtifactService
from services.discovery_service import DiscoveryService
from services.revision_service import RevisionService
from services.session_service import SessionService
from services.stream_service import StreamService


@dataclass(slots=True)
class ServiceContainer:
    settings: Settings
    database: DatabaseManager
    session_store: SessionStore
    semantic_scholar_client: SemanticScholarClient
    arxiv_client: ArxivClient
    firecrawl_client: FirecrawlClient
    stream_service: StreamService
    analysis_service: AnalysisService
    artifact_service: ArtifactService
    discovery_service: DiscoveryService
    revision_service: RevisionService
    session_service: SessionService
    supervisor_graph: object


def get_services(request: Request) -> ServiceContainer:
    return request.app.state.services
