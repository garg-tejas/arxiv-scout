from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ArXiv Literature Scout"
    debug: bool = False
    session_ttl_days: int = 7
    sse_heartbeat_seconds: int = 15
    database_path: Path = (
        Path(__file__).resolve().parents[1] / "data" / "arxiv_scout.db"
    )
    semantic_scholar_base_url: str = "https://api.semanticscholar.org/graph/v1"
    semantic_scholar_api_key: str | None = None
    arxiv_api_url: str = "https://export.arxiv.org/api/query"
    firecrawl_base_url: str = "https://api.firecrawl.dev"
    firecrawl_api_key: str | None = None
    discovery_results_per_angle: int = 10
    discovery_shortlist_size: int = 12
    analysis_paper_cap: int = 8
    hf_base_url: str = "https://router.huggingface.co/v1"
    hf_api_key: str | None = None
    hf_primary_model: str = "openai/gpt-oss-120b:novita"
    hf_secondary_model: str = "Qwen/Qwen3.5-9B:together"
    llm_timeout_seconds: float = 45.0
    llm_max_retries: int = 2
    langsmith_tracing: bool = False
    langsmith_api_key: str | None = None
    langsmith_project: str = "arxiv-literature-scout"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    model_config = SettingsConfigDict(
        env_prefix="ARXIV_SCOUT_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
