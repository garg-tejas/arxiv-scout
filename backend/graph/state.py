from __future__ import annotations

from typing import TypedDict


class AppGraphState(TypedDict, total=False):
    session_id: str
    command: str

    current_phase: str
    current_checkpoint: str

    topic: str
    search_interpretation: object
    steering_preferences: object

    latest_shortlist: list[object]
    preliminary_method_table: list[object]

    approved_papers: list[str]
    approved_paper_details: list[object]

    selected_papers: list[object]
    paper_analyses: list[object]
    degraded_paper_ids: list[str]
    citation_graph: object
    method_comparison_table: list[object]

    survey_brief: object
    theme_clusters: list[object]
    survey_sections: list[object]
    final_survey_document: object
