from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from graph.state import AppGraphState
from graph.commands import GraphCommand
from models.discovery import SteeringPreferences
from models.enums import AllowedAction, CheckpointType, PhaseType, SessionStatus
from models.session import PendingInterrupt, SearchInterpretation
from services.discovery_service import DiscoveryService


def normalize_topic(topic: str) -> str:
    collapsed = " ".join(topic.split())
    return collapsed.strip()


def _get_command(state: AppGraphState) -> str:
    return (state.get("command") or "").strip()


def _finalize_interpretation(
    interpretation: SearchInterpretation,
) -> SearchInterpretation:
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
        raise ValueError(
            "LLM topic interpretation did not return 3-4 distinct search angles."
        )

    return SearchInterpretation(
        normalized_topic=normalized_topic,
        search_angles=search_angles,
    )


def _route_command(state: AppGraphState) -> str:
    command = _get_command(state)
    if command == GraphCommand.START_TOPIC.value:
        return "start_topic"
    if command == GraphCommand.CONFIRM_TOPIC.value:
        return "confirm_topic"
    if command == GraphCommand.NUDGE_DISCOVERY.value:
        return "nudge_discovery"
    if command == GraphCommand.UPDATE_APPROVED_PAPERS.value:
        return "update_approved_papers"
    return END


def _default_preferences(state: AppGraphState) -> SteeringPreferences:
    pref = state.get("steering_preferences")
    if isinstance(pref, SteeringPreferences):
        return pref
    return SteeringPreferences()


async def _interpret_topic_node(
    state: AppGraphState, *, discovery_service: DiscoveryService
) -> AppGraphState:
    topic = normalize_topic(state.get("topic") or "")
    interpretation = await discovery_service.interpret_topic(topic)
    interpretation = _finalize_interpretation(interpretation)
    return {
        **state,
        "topic": topic,
        "search_interpretation": interpretation,
    }


def _topic_confirmation_interrupt(state: AppGraphState) -> AppGraphState:
    interpretation = state.get("search_interpretation")
    return {
        **state,
        "current_phase": PhaseType.DISCOVERY.value,
        "current_checkpoint": CheckpointType.TOPIC_CONFIRMATION.value,
        "status": SessionStatus.WAITING_FOR_INPUT.value,
        "pending_interrupt": PendingInterrupt(
            checkpoint=CheckpointType.TOPIC_CONFIRMATION,
            message="Confirm the interpreted topic and search angles before paper fetch.",
            expected_action_types=[AllowedAction.CONFIRM_TOPIC],
        ),
        "allowed_actions": [AllowedAction.CONFIRM_TOPIC],
        "topic": state.get("topic"),
        "search_interpretation": interpretation,
    }


async def _apply_steering_delta(
    state: AppGraphState, *, discovery_service: DiscoveryService
) -> AppGraphState:
    nudge_text = " ".join((state.get("nudge_text") or "").split()).strip()
    merged = await discovery_service.merge_steering_preferences(
        current=_default_preferences(state),
        nudge_text=nudge_text,
    )
    return {
        **state,
        "steering_preferences": merged,
    }


async def _fetch_candidates(
    state: AppGraphState, *, discovery_service: DiscoveryService
) -> AppGraphState:
    interpretation = state.get("search_interpretation")
    if not isinstance(interpretation, SearchInterpretation):
        raise ValueError("Discovery graph is missing search_interpretation.")
    candidates = await discovery_service.fetch_candidates(
        interpretation=interpretation,
        steering_preferences=_default_preferences(state),
    )
    return {
        **state,
        "candidate_papers": candidates,
    }


async def _curate_shortlist(
    state: AppGraphState, *, discovery_service: DiscoveryService
) -> AppGraphState:
    interpretation = state.get("search_interpretation")
    if not isinstance(interpretation, SearchInterpretation):
        raise ValueError("Discovery graph is missing search_interpretation.")
    topic = normalize_topic(state.get("topic") or "")
    candidates = state.get("candidate_papers") or []
    curated, method_table = await discovery_service.curate_shortlist(
        topic=topic,
        interpretation=interpretation,
        papers=candidates,
        steering_preferences=_default_preferences(state),
    )
    shortlist = curated[: discovery_service.shortlist_size]
    row_by_id = {row.paper_id: row for row in method_table}
    ordered_rows = [
        row_by_id[paper.paper_id] for paper in shortlist if paper.paper_id in row_by_id
    ]
    return {
        **state,
        "latest_shortlist": shortlist,
        "preliminary_method_table": ordered_rows,
    }


def _shortlist_review_interrupt(state: AppGraphState) -> AppGraphState:
    return {
        **state,
        "current_phase": PhaseType.DISCOVERY.value,
        "current_checkpoint": CheckpointType.SHORTLIST_REVIEW.value,
        "status": SessionStatus.WAITING_FOR_INPUT.value,
        "pending_interrupt": PendingInterrupt(
            checkpoint=CheckpointType.SHORTLIST_REVIEW,
            message="Review the curated shortlist, replace the approved-paper set, or steer discovery with a nudge.",
            expected_action_types=[
                AllowedAction.UPDATE_APPROVED_PAPERS,
                AllowedAction.NUDGE_DISCOVERY,
                AllowedAction.START_ANALYSIS,
            ],
        ),
        "allowed_actions": [
            AllowedAction.UPDATE_APPROVED_PAPERS,
            AllowedAction.NUDGE_DISCOVERY,
            AllowedAction.START_ANALYSIS,
        ],
    }


def _store_approved_papers(state: AppGraphState) -> AppGraphState:
    paper_ids = [
        paper_id.strip()
        for paper_id in (state.get("approved_papers") or [])
        if paper_id.strip()
    ]
    shortlist = state.get("latest_shortlist") or []
    shortlist_map = {paper.paper_id: paper for paper in shortlist}
    approved_details = [
        shortlist_map[paper_id] for paper_id in paper_ids if paper_id in shortlist_map
    ]
    return {
        **state,
        "approved_papers": paper_ids,
        "approved_paper_details": approved_details,
    }


def build_discovery_graph(*, discovery_service: DiscoveryService, checkpointer):
    workflow = StateGraph(AppGraphState)
    workflow.add_node("command_router", lambda state: state)
    workflow.add_conditional_edges(
        "command_router",
        _route_command,
        {
            "start_topic": "interpret_topic",
            "confirm_topic": "fetch_candidates",
            "nudge_discovery": "apply_steering_delta",
            "update_approved_papers": "store_approved_papers",
            END: END,
        },
    )

    async def interpret_topic_node(state: AppGraphState) -> AppGraphState:
        return await _interpret_topic_node(state, discovery_service=discovery_service)

    async def apply_steering_delta_node(state: AppGraphState) -> AppGraphState:
        return await _apply_steering_delta(state, discovery_service=discovery_service)

    async def fetch_candidates_node(state: AppGraphState) -> AppGraphState:
        return await _fetch_candidates(state, discovery_service=discovery_service)

    async def curate_shortlist_node(state: AppGraphState) -> AppGraphState:
        return await _curate_shortlist(state, discovery_service=discovery_service)

    workflow.add_node("interpret_topic", interpret_topic_node)
    workflow.add_node("topic_confirmation", _topic_confirmation_interrupt)
    workflow.add_edge("interpret_topic", "topic_confirmation")
    workflow.add_edge("topic_confirmation", END)

    workflow.add_node("apply_steering_delta", apply_steering_delta_node)
    workflow.add_node("fetch_candidates", fetch_candidates_node)
    workflow.add_node("curate_shortlist", curate_shortlist_node)
    workflow.add_node("shortlist_review", _shortlist_review_interrupt)

    workflow.add_edge("apply_steering_delta", "fetch_candidates")
    workflow.add_edge("fetch_candidates", "curate_shortlist")
    workflow.add_edge("curate_shortlist", "shortlist_review")
    workflow.add_edge("shortlist_review", END)

    workflow.add_node("store_approved_papers", _store_approved_papers)
    workflow.add_edge("store_approved_papers", END)

    workflow.add_edge(START, "command_router")
    return workflow.compile(checkpointer=checkpointer)
