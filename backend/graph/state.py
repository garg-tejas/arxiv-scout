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
