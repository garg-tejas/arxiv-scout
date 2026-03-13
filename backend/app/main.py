from __future__ import annotations

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.dependencies import ServiceContainer
from app.routes import sessions
from graph.analysis import build_analysis_graph
from graph.discovery import build_discovery_graph
from graph.survey import build_survey_graph
from integrations.arxiv import ArxivClient
from integrations.firecrawl import FirecrawlClient
from integrations.llm import GLMChatClient, GeminiChatClient, LLMRouter
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
from services.survey_service import SurveyService


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Optional LangSmith / LangChain tracing
    if settings.langsmith_tracing and settings.langsmith_api_key:
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ.setdefault("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")
        os.environ.setdefault("LANGCHAIN_API_KEY", settings.langsmith_api_key)
        if settings.langsmith_project:
            os.environ.setdefault("LANGCHAIN_PROJECT", settings.langsmith_project)

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
    glm_client = GLMChatClient(
        base_url=settings.glm_base_url,
        api_key=settings.glm_api_key,
        default_model=settings.glm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    gemini_client = GeminiChatClient(
        base_url=settings.gemini_base_url,
        api_key=settings.gemini_api_key,
        default_model=settings.gemini_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    llm_router = LLMRouter(
        glm_client=glm_client,
        gemini_client=gemini_client,
        max_retries=settings.llm_max_retries,
    )
    survey_service = SurveyService(llm_router=llm_router)
    analysis_service = AnalysisService(
        firecrawl_client=firecrawl_client,
        llm_router=llm_router,
    )
    citation_graph_service = CitationGraphService(
        semantic_scholar_client=semantic_scholar_client,
    )
    discovery_service = DiscoveryService(
        semantic_scholar_client=semantic_scholar_client,
        arxiv_client=arxiv_client,
        llm_router=llm_router,
        results_per_angle=settings.discovery_results_per_angle,
        shortlist_size=settings.discovery_shortlist_size,
    )
    stream_service = StreamService(
        session_store=session_store,
        heartbeat_seconds=settings.sse_heartbeat_seconds,
    )
    discovery_graph = build_discovery_graph(discovery_service=discovery_service)
    analysis_graph = build_analysis_graph(
        analysis_service=analysis_service,
        citation_graph_service=citation_graph_service,
        artifact_service=artifact_service,
        stream_service=stream_service,
    )
    survey_graph = build_survey_graph(
        survey_service=survey_service,
        stream_service=stream_service,
    )
    session_service = SessionService(
        session_store=session_store,
        artifact_service=artifact_service,
        analysis_service=analysis_service,
        citation_graph_service=citation_graph_service,
        discovery_service=discovery_service,
        stream_service=stream_service,
        revision_service=revision_service,
        survey_service=survey_service,
        ttl_days=settings.session_ttl_days,
        analysis_paper_cap=settings.analysis_paper_cap,
        discovery_graph=discovery_graph,
        analysis_graph=analysis_graph,
        survey_graph=survey_graph,
    )

    app.state.services = ServiceContainer(
        settings=settings,
        database=database,
        session_store=session_store,
        semantic_scholar_client=semantic_scholar_client,
        arxiv_client=arxiv_client,
        firecrawl_client=firecrawl_client,
        llm_router=llm_router,
        stream_service=stream_service,
        analysis_service=analysis_service,
        citation_graph_service=citation_graph_service,
        artifact_service=artifact_service,
        discovery_service=discovery_service,
        revision_service=revision_service,
        survey_service=survey_service,
        session_service=session_service,
        discovery_graph=discovery_graph,
        analysis_graph=analysis_graph,
        survey_graph=survey_graph,
    )

    yield

    await semantic_scholar_client.aclose()
    await arxiv_client.aclose()
    await firecrawl_client.aclose()
    await database.close()


app = FastAPI(
    title="ArXiv Literature Scout",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(sessions.router)


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
