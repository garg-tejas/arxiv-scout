from __future__ import annotations

from pydantic import BaseModel, Field


class SteeringPreferences(BaseModel):
    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    emphasize: list[str] = Field(default_factory=list)


class StartTopicRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=500)


class ConfirmTopicRequest(BaseModel):
    confirmed: bool = True


class UpdateApprovedPapersRequest(BaseModel):
    paper_ids: list[str] = Field(default_factory=list)


class DiscoveryNudgeRequest(BaseModel):
    text: str = Field(min_length=3, max_length=1000)


class CuratedCandidateAssessment(BaseModel):
    paper_id: str
    score: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=500)
    model_type: str | None = None
    dataset: str | None = None
    metrics: list[str] = Field(default_factory=list)
    benchmarks: list[str] = Field(default_factory=list)


class CurationBatchResult(BaseModel):
    shortlisted_papers: list[CuratedCandidateAssessment] = Field(default_factory=list)
