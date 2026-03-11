from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from graph.state import AppGraphState
from models.session import SearchInterpretation


def normalize_topic(topic: str) -> str:
    collapsed = " ".join(topic.split())
    return collapsed.strip()


def generate_search_angles(topic: str) -> list[str]:
    normalized = normalize_topic(topic)
    return [
        normalized,
        f"{normalized} methods and architectures",
        f"{normalized} datasets benchmarks evaluation",
        f"{normalized} recent applications limitations",
    ]


def interpret_topic(topic: str) -> SearchInterpretation:
    normalized = normalize_topic(topic)
    return SearchInterpretation(
        normalized_topic=normalized,
        search_angles=generate_search_angles(normalized),
    )


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
