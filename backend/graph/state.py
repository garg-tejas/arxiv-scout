from __future__ import annotations

from typing import TypedDict


class AppGraphState(TypedDict, total=False):
    session_id: str
    current_phase: str
    current_checkpoint: str
    topic: str
