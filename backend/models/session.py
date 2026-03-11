from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from models.analysis import AnalysisSummary, PaperAnalysis
from models.discovery import SteeringPreferences
from models.enums import AllowedAction, ArtifactStatusValue, CheckpointType, PhaseType, SessionStatus
from models.papers import CuratedPaper, MethodExtractionRow
from models.survey import SurveySummary


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PendingInterrupt(BaseModel):
    checkpoint: CheckpointType
    message: str
    expected_action_types: list[AllowedAction] = Field(default_factory=list)


class SearchInterpretation(BaseModel):
    normalized_topic: str | None = None
    search_angles: list[str] = Field(default_factory=list)


class SessionSnapshot(BaseModel):
    session_id: str
    status: SessionStatus = SessionStatus.IDLE
    current_phase: PhaseType = PhaseType.NONE
    current_checkpoint: CheckpointType = CheckpointType.NONE
    pending_interrupt: PendingInterrupt | None = None
    allowed_actions: list[AllowedAction] = Field(default_factory=list)
    topic: str | None = None
    search_interpretation: SearchInterpretation | None = None
    steering_preferences: SteeringPreferences = Field(default_factory=SteeringPreferences)
    approved_papers: list[str] = Field(default_factory=list)
    approved_paper_details: list[CuratedPaper] = Field(default_factory=list)
    latest_shortlist: list[CuratedPaper] = Field(default_factory=list)
    preliminary_method_table: list[MethodExtractionRow] = Field(default_factory=list)
    paper_analyses: list[PaperAnalysis] = Field(default_factory=list)
    analysis_summary: AnalysisSummary = Field(default_factory=AnalysisSummary)
    survey_summary: SurveySummary = Field(default_factory=SurveySummary)
    artifact_status: dict[str, ArtifactStatusValue] = Field(default_factory=dict)
    last_updated_at: datetime = Field(default_factory=utc_now)
