from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.dependencies import ServiceContainer
from app.routes import sessions
from graph.supervisor import build_supervisor_graph
from integrations.arxiv import ArxivClient
from integrations.firecrawl import FirecrawlClient
from integrations.semantic_scholar import SemanticScholarClient
from persistence.cleanup import cleanup_expired_sessions
from persistence.database import DatabaseManager
from persistence.session_store import SessionStore
from services.analysis_service import AnalysisService
from services.artifact_service import ArtifactService
from services.citation_graph_service import CitationGraphService
from services.discovery_service import DiscoveryService
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
    semantic_scholar_client = SemanticScholarClient(
        base_url=settings.semantic_scholar_base_url,
        api_key=settings.semantic_scholar_api_key,
    )
    arxiv_client = ArxivClient(api_url=settings.arxiv_api_url)
    firecrawl_client = FirecrawlClient(
        base_url=settings.firecrawl_base_url,
        api_key=settings.firecrawl_api_key,
    )
    analysis_service = AnalysisService(firecrawl_client=firecrawl_client)
    citation_graph_service = CitationGraphService(
        semantic_scholar_client=semantic_scholar_client,
    )
    discovery_service = DiscoveryService(
        semantic_scholar_client=semantic_scholar_client,
        arxiv_client=arxiv_client,
        results_per_angle=settings.discovery_results_per_angle,
        shortlist_size=settings.discovery_shortlist_size,
    )
    stream_service = StreamService(
        session_store=session_store,
        heartbeat_seconds=settings.sse_heartbeat_seconds,
    )
    session_service = SessionService(
        session_store=session_store,
        artifact_service=artifact_service,
        analysis_service=analysis_service,
        citation_graph_service=citation_graph_service,
        discovery_service=discovery_service,
        stream_service=stream_service,
        ttl_days=settings.session_ttl_days,
        analysis_paper_cap=settings.analysis_paper_cap,
    )

    app.state.services = ServiceContainer(
        settings=settings,
        database=database,
        session_store=session_store,
        semantic_scholar_client=semantic_scholar_client,
        arxiv_client=arxiv_client,
        firecrawl_client=firecrawl_client,
        stream_service=stream_service,
        analysis_service=analysis_service,
        citation_graph_service=citation_graph_service,
        artifact_service=artifact_service,
        discovery_service=discovery_service,
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
