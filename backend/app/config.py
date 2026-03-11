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

    model_config = SettingsConfigDict(
        env_prefix="ARXIV_SCOUT_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
