from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from models.enums import ArtifactType, CheckpointType, PhaseType, StreamEventType


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StreamEvent(BaseModel):
    id: int | None = None
    session_id: str
    event_type: StreamEventType
    phase: PhaseType = PhaseType.NONE
    checkpoint: CheckpointType = CheckpointType.NONE
    artifact_type: ArtifactType | None = None
    message: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=utc_now)


class CreateSessionResponse(BaseModel):
    session_id: str
