from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from graph.checkpoint import get_sqlite_checkpointer
from graph.commands import GraphCommand
from graph.state import AppGraphState


def _route_command(state: AppGraphState) -> str:
    command = (state.get("command") or "").strip()
    if command == GraphCommand.START_TOPIC.value:
        return "discovery"
    if command in {
        GraphCommand.CONFIRM_TOPIC.value,
        GraphCommand.NUDGE_DISCOVERY.value,
        GraphCommand.UPDATE_APPROVED_PAPERS.value,
    }:
        return "discovery"
    if command == GraphCommand.START_ANALYSIS.value:
        return "analysis"
    if command in {
        GraphCommand.START_SURVEY.value,
        GraphCommand.REVISE_SURVEY.value,
        GraphCommand.APPROVE_SURVEY.value,
    }:
        return "survey"
    return END


def build_supervisor_graph():
    workflow = StateGraph(AppGraphState)
    workflow.add_node("router", lambda state: state)
    workflow.add_conditional_edges(
        "router",
        _route_command,
        {
            "discovery": "discovery",
            "analysis": "analysis",
            "survey": "survey",
            END: END,
        },
    )

    # The actual discovery/analysis/survey graphs are composed and invoked
    # directly in SessionService today. The supervisor graph owns the same
    # checkpointer so it can participate in future orchestration without
    # changing the public API.
    workflow.add_node("discovery", lambda state: state)
    workflow.add_node("analysis", lambda state: state)
    workflow.add_node("survey", lambda state: state)
    workflow.add_edge("discovery", END)
    workflow.add_edge("analysis", END)
    workflow.add_edge("survey", END)

    workflow.add_edge(START, "router")
    return workflow.compile(checkpointer=get_sqlite_checkpointer())
