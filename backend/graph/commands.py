from __future__ import annotations

from enum import StrEnum


class GraphCommand(StrEnum):
    START_TOPIC = "start_topic"
    CONFIRM_TOPIC = "confirm_topic"
    NUDGE_DISCOVERY = "nudge_discovery"
    UPDATE_APPROVED_PAPERS = "update_approved_papers"

