from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from graph.state import AppGraphState


def _analysis_placeholder(state: AppGraphState) -> AppGraphState:
    return {
        **state,
        "current_phase": "analysis",
        "current_checkpoint": "none",
    }


def build_analysis_graph():
    workflow = StateGraph(AppGraphState)
    workflow.add_node("analysis_placeholder", _analysis_placeholder)
    workflow.add_edge(START, "analysis_placeholder")
    workflow.add_edge("analysis_placeholder", END)
    return workflow.compile()
