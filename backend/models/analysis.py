from __future__ import annotations

from pydantic import BaseModel, Field

from models.enums import AnalysisQuality


class PaperAnalysis(BaseModel):
    paper_id: str
    analysis_quality: AnalysisQuality = AnalysisQuality.ABSTRACT_ONLY
    core_claim: str | None = None
    methodology: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    benchmarks: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    explicit_citations: list[str] = Field(default_factory=list)


class AnalysisSummary(BaseModel):
    selected_paper_ids: list[str] = Field(default_factory=list)
    completed: bool = False
