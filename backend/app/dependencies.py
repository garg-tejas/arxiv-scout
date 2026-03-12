from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.config import Settings
from integrations.arxiv import ArxivClient
from integrations.firecrawl import FirecrawlClient
from integrations.llm import LLMRouter
from integrations.semantic_scholar import SemanticScholarClient
from persistence.database import DatabaseManager
from persistence.session_store import SessionStore
from services.analysis_service import AnalysisService
from services.artifact_service import ArtifactService
from services.citation_graph_service import CitationGraphService
from services.discovery_service import DiscoveryService
from services.revision_service import RevisionService
from services.session_service import SessionService
from services.stream_service import StreamService
from services.survey_service import SurveyService


@dataclass(slots=True)
class ServiceContainer:
    settings: Settings
    database: DatabaseManager
    session_store: SessionStore
    semantic_scholar_client: SemanticScholarClient
    arxiv_client: ArxivClient
    firecrawl_client: FirecrawlClient
    llm_router: LLMRouter
    stream_service: StreamService
    analysis_service: AnalysisService
    citation_graph_service: CitationGraphService
    artifact_service: ArtifactService
    discovery_service: DiscoveryService
    revision_service: RevisionService
    survey_service: SurveyService
    session_service: SessionService
    discovery_graph: object
    analysis_graph: object
    supervisor_graph: object


def get_services(request: Request) -> ServiceContainer:
    return request.app.state.services
