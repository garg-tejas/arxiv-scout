from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from graph.state import AppGraphState


def _survey_placeholder(state: AppGraphState) -> AppGraphState:
    return {
        **state,
        "current_phase": "survey",
        "current_checkpoint": "none",
    }


def build_survey_graph():
    workflow = StateGraph(AppGraphState)
    workflow.add_node("survey_placeholder", _survey_placeholder)
    workflow.add_edge(START, "survey_placeholder")
    workflow.add_edge("survey_placeholder", END)
    return workflow.compile()
