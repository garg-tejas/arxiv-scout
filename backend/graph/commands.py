from __future__ import annotations

from enum import StrEnum


class GraphCommand(StrEnum):
    START_TOPIC = "start_topic"
    CONFIRM_TOPIC = "confirm_topic"
    NUDGE_DISCOVERY = "nudge_discovery"
    UPDATE_APPROVED_PAPERS = "update_approved_papers"
    START_ANALYSIS = "start_analysis"
    START_SURVEY = "start_survey"
    REVISE_SURVEY = "revise_survey"
    APPROVE_SURVEY = "approve_survey"

