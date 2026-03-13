from __future__ import annotations

from typing import Any, TypedDict

from models.analysis import MethodComparisonRow, PaperAnalysis
from models.citation import CitationGraph
from models.discovery import SteeringPreferences
from models.papers import CuratedPaper, MethodExtractionRow, PaperMetadata
from models.session import PendingInterrupt, SearchInterpretation
from models.survey import (
    SurveyBrief,
    SurveyDocument,
    SurveySection,
    SurveySummary,
    ThemeCluster,
)
from models.enums import AllowedAction


class AppGraphState(TypedDict, total=False):
    # ── identity / routing ──────────────────────────────────────────────
    session_id: str
    command: str

    # ── lifecycle ───────────────────────────────────────────────────────
    current_phase: str
    current_checkpoint: str
    status: str
    pending_interrupt: PendingInterrupt
    allowed_actions: list[AllowedAction]

    # ── discovery ───────────────────────────────────────────────────────
    topic: str
    search_interpretation: SearchInterpretation
    steering_preferences: SteeringPreferences
    nudge_text: str
    candidate_papers: list[PaperMetadata]
    latest_shortlist: list[CuratedPaper]
    preliminary_method_table: list[MethodExtractionRow]
    approved_papers: list[str]
    approved_paper_details: list[CuratedPaper]

    # ── analysis ────────────────────────────────────────────────────────
    selected_papers: list[CuratedPaper]
    paper_analyses: list[PaperAnalysis]
    degraded_paper_ids: list[str]
    citation_graph: CitationGraph
    method_comparison_table: list[MethodComparisonRow]

    # ── survey ──────────────────────────────────────────────────────────
    snapshot: dict[str, Any]
    survey_brief: SurveyBrief
    theme_clusters: list[ThemeCluster]
    survey_sections: list[SurveySection]
    section_queue: list[str]
    revision_feedback_map: dict[str, str]
    revision_count_map: dict[str, int]
    final_survey_document: SurveyDocument
    survey_summary: SurveySummary
