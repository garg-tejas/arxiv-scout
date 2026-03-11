from __future__ import annotations

from pydantic import BaseModel, Field


class Author(BaseModel):
    name: str


class PaperMetadata(BaseModel):
    paper_id: str
    arxiv_id: str | None = None
    title: str
    abstract: str | None = None
    authors: list[Author] = Field(default_factory=list)
    year: int | None = None
    citation_count: int | None = None


class CuratedPaper(PaperMetadata):
    rationale: str | None = None
    score: float | None = None


class MethodExtractionRow(BaseModel):
    paper_id: str
    model_type: str | None = None
    dataset: str | None = None
    metrics: list[str] = Field(default_factory=list)
    benchmarks: list[str] = Field(default_factory=list)
