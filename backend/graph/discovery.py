from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from graph.state import AppGraphState


def _discovery_placeholder(state: AppGraphState) -> AppGraphState:
    return {
        **state,
        "current_phase": "discovery",
        "current_checkpoint": "none",
    }


def build_discovery_graph():
    workflow = StateGraph(AppGraphState)
    workflow.add_node("discovery_placeholder", _discovery_placeholder)
    workflow.add_edge(START, "discovery_placeholder")
    workflow.add_edge("discovery_placeholder", END)
    return workflow.compile()
