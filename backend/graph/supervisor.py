from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from graph.state import AppGraphState


def _phase_router(state: AppGraphState) -> AppGraphState:
    return {**state, "current_phase": state.get("current_phase", "none")}


def build_supervisor_graph():
    workflow = StateGraph(AppGraphState)
    workflow.add_node("phase_router", _phase_router)
    workflow.add_edge(START, "phase_router")
    workflow.add_edge("phase_router", END)
    return workflow.compile()
