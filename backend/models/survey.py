from __future__ import annotations

from pydantic import BaseModel, Field

from models.enums import ReviewVerdict


class SurveyBrief(BaseModel):
    angle: str | None = None
    audience: str | None = None
    emphasis: list[str] = Field(default_factory=list)
    comparisons: list[str] = Field(default_factory=list)


class ThemeCluster(BaseModel):
    cluster_id: str
    title: str
    description: str
    paper_ids: list[str] = Field(default_factory=list)


class SurveySection(BaseModel):
    section_id: str
    title: str
    content_markdown: str
    paper_ids: list[str] = Field(default_factory=list)
    revision_count: int = 0
    accepted: bool = False


class SectionReviewResult(BaseModel):
    verdict: ReviewVerdict
    feedback: str
    revision_count: int = 0


class SurveyDocument(BaseModel):
    title: str = "ArXiv Literature Scout Survey"
    introduction: str | None = None
    sections: list[SurveySection] = Field(default_factory=list)
    conclusion: str | None = None
    references: list[str] = Field(default_factory=list)
    markdown: str = ""


class SurveySummary(BaseModel):
    section_ids: list[str] = Field(default_factory=list)
    completed: bool = False


class SurveyRevisionRequestItem(BaseModel):
    section_id: str
    feedback: str


class SurveyRevisionRequest(BaseModel):
    revisions: list[SurveyRevisionRequestItem] = Field(default_factory=list)
