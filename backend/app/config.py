from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ArXiv Literature Scout"
    debug: bool = False
    session_ttl_days: int = 7
    sse_heartbeat_seconds: int = 15
    database_path: Path = Path(__file__).resolve().parents[1] / "data" / "arxiv_scout.db"
    semantic_scholar_base_url: str = "https://api.semanticscholar.org/graph/v1"
    semantic_scholar_api_key: str | None = None
    arxiv_api_url: str = "https://export.arxiv.org/api/query"
    discovery_results_per_angle: int = 10
    discovery_shortlist_size: int = 12

    model_config = SettingsConfigDict(
        env_prefix="ARXIV_SCOUT_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
