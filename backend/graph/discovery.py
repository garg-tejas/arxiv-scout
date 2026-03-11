from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from graph.state import AppGraphState
from integrations.llm import LLMRouter
from models.enums import LLMRole
from models.session import SearchInterpretation


def normalize_topic(topic: str) -> str:
    collapsed = " ".join(topic.split())
    return collapsed.strip()


async def interpret_topic(topic: str, llm_router: LLMRouter) -> SearchInterpretation:
    normalized_topic = normalize_topic(topic)
    interpretation = await llm_router.generate_structured(
        role=LLMRole.SEARCH,
        system_prompt=(
            "You are the Search Agent for an arXiv literature scout. "
            "Interpret the user's research topic into a normalized topic string and 3 to 4 semantically distinct "
            "search angles. Return JSON only. Keep search angles concise, diverse, and arXiv-paper oriented."
        ),
        user_prompt=(
            f"User topic:\n{normalized_topic}\n\n"
            "Requirements:\n"
            "- normalized_topic should be a cleaned-up restatement of the topic\n"
            "- search_angles must contain 3 or 4 distinct strings\n"
            "- angles should emphasize different retrieval views such as method family, benchmark/evaluation, "
            "application area, or limitations/tradeoffs\n"
            "- do not include numbering or commentary"
        ),
        schema_type=SearchInterpretation,
    )
    return _finalize_interpretation(interpretation)


def _finalize_interpretation(interpretation: SearchInterpretation) -> SearchInterpretation:
    normalized_topic = normalize_topic(interpretation.normalized_topic or "")
    seen: set[str] = set()
    search_angles: list[str] = []
    for angle in interpretation.search_angles:
        cleaned = normalize_topic(angle)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        search_angles.append(cleaned)

    if not normalized_topic or len(search_angles) < 3 or len(search_angles) > 4:
        raise ValueError("LLM topic interpretation did not return 3-4 distinct search angles.")

    return SearchInterpretation(
        normalized_topic=normalized_topic,
        search_angles=search_angles,
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
