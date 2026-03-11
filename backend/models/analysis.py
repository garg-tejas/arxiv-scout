from __future__ import annotations

from pydantic import BaseModel, Field

from models.enums import AnalysisQuality


class StartAnalysisRequest(BaseModel):
    paper_ids: list[str] = Field(default_factory=list)


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


class MethodComparisonRow(BaseModel):
    paper_id: str
    title: str
    analysis_quality: AnalysisQuality = AnalysisQuality.ABSTRACT_ONLY
    model_type: str | None = None
    core_claim: str | None = None
    methodology_summary: str | None = None
    datasets: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    benchmarks: list[str] = Field(default_factory=list)
    primary_limitation: str | None = None


class AnalysisSummary(BaseModel):
    selected_paper_ids: list[str] = Field(default_factory=list)
    completed: bool = False
    degraded_paper_ids: list[str] = Field(default_factory=list)
    comparison_row_count: int = 0
    retained_context_node_count: int = 0
    lineage_path_count: int = 0
    citation_graph_summary: str | None = None
