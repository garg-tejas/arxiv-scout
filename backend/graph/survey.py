from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from graph.checkpoint import get_sqlite_checkpointer
from graph.state import AppGraphState
from models.enums import ArtifactType, PhaseType, StreamEventType
from models.papers import CuratedPaper
from models.session import SessionSnapshot
from models.survey import (
    SurveyBrief,
    SurveyDocument,
    SurveySection,
    SurveySummary,
    ThemeCluster,
)
from services.stream_service import StreamService
from models.events import StreamEvent
from services.survey_service import SurveyService


async def _prepare_survey_brief_node(
    state: AppGraphState,
    *,
    survey_service: SurveyService,
) -> AppGraphState:
    snapshot = SessionSnapshot.model_validate(state.get("snapshot") or {})
    brief: SurveyBrief = state.get(
        "survey_brief"
    ) or await survey_service.synthesize_brief(snapshot)
    return {
        **state,
        "survey_brief": brief,
    }


async def _cluster_themes_node(
    state: AppGraphState,
    *,
    survey_service: SurveyService,
) -> AppGraphState:
    brief: SurveyBrief = state.get("survey_brief")
    papers = [
        CuratedPaper.model_validate(p) for p in state.get("selected_papers") or []
    ]
    analyses = [a for a in state.get("paper_analyses") or []]
    comparison_rows = [row for row in state.get("method_comparison_table") or []]
    citation_graph = state.get("citation_graph")
    clusters = await survey_service.cluster_themes(
        brief=brief,
        papers=papers,
        analyses=analyses,
        comparison_rows=comparison_rows,
        citation_graph=citation_graph,
    )
    return {
        **state,
        "theme_clusters": clusters,
    }


async def _draft_current_section_node(
    state: AppGraphState,
    *,
    survey_service: SurveyService,
) -> AppGraphState:
    brief: SurveyBrief = state.get("survey_brief")
    clusters = [
        ThemeCluster.model_validate(c) for c in state.get("theme_clusters") or []
    ]
    sections = [
        SurveySection.model_validate(s) for s in state.get("survey_sections") or []
    ]
    queue: list[str] = list(
        state.get("section_queue") or [cluster.cluster_id for cluster in clusters]
    )
    if not queue:
        return state
    current_id = queue[0]
    cluster_map = {cluster.cluster_id: cluster for cluster in clusters}
    cluster = cluster_map[current_id]
    papers = [
        CuratedPaper.model_validate(p) for p in state.get("selected_papers") or []
    ]
    analyses = [a for a in state.get("paper_analyses") or []]
    comparison_rows = [row for row in state.get("method_comparison_table") or []]
    citation_graph = state.get("citation_graph")
    revision_feedback_map: dict[str, str] = state.get("revision_feedback_map") or {}
    revision_feedback = revision_feedback_map.get(current_id)
    revision_count_map: dict[str, int] = state.get("revision_count_map") or {}
    revision_count = revision_count_map.get(current_id, 0)

    section = await survey_service.draft_section(
        cluster=cluster,
        papers=papers,
        analyses=analyses,
        comparison_rows=comparison_rows,
        brief=brief,
        citation_graph=citation_graph,
        revision_feedback=revision_feedback,
        revision_count=revision_count,
    )
    sections = [s for s in sections if s.section_id != section.section_id] + [section]
    revision_count_map[current_id] = section.revision_count
    return {
        **state,
        "survey_sections": sections,
        "section_queue": queue,
        "revision_count_map": revision_count_map,
    }


async def _review_current_section_node(
    state: AppGraphState,
    *,
    survey_service: SurveyService,
    stream_service: StreamService,
) -> AppGraphState:
    session_id = state.get("session_id") or ""
    brief: SurveyBrief = state.get("survey_brief")
    clusters = [
        ThemeCluster.model_validate(c) for c in state.get("theme_clusters") or []
    ]
    sections = [
        SurveySection.model_validate(s) for s in state.get("survey_sections") or []
    ]
    queue: list[str] = list(
        state.get("section_queue") or [cluster.cluster_id for cluster in clusters]
    )
    if not queue:
        return state
    current_id = queue[0]
    cluster_map = {cluster.cluster_id: cluster for cluster in clusters}
    cluster = cluster_map[current_id]
    section_map = {section.section_id: section for section in sections}
    section = section_map[current_id]

    review = await survey_service.review_section(
        section=section,
        cluster=cluster,
        brief=brief,
    )
    if review.verdict.value == "ACCEPT" or section.revision_count >= 2:
        section.accepted = True
        await stream_service.publish(
            StreamEvent(
                session_id=session_id,
                event_type=StreamEventType.ARTIFACT_READY,
                phase=PhaseType.SURVEY,
                artifact_type=ArtifactType.SURVEY_SECTION,
                message=f"Survey section ready: {section.title}.",
                data=section.model_dump(mode="json"),
            )
        )
        queue = queue[1:]
        section_map[section.section_id] = section
        sections = list(section_map.values())
        return {
            **state,
            "survey_sections": sections,
            "section_queue": queue,
        }

    await stream_service.publish(
        StreamEvent(
            session_id=session_id,
            event_type=StreamEventType.NODE_UPDATE,
            phase=PhaseType.SURVEY,
            message=f"Section reviewer requested a revision for {section.title}.",
            data={"section_id": section.section_id, "feedback": review.feedback},
        )
    )
    revision_feedback_map: dict[str, str] = state.get("revision_feedback_map") or {}
    revision_count_map: dict[str, int] = state.get("revision_count_map") or {}
    revision_feedback_map[current_id] = review.feedback
    revision_count_map[current_id] = min(section.revision_count + 1, 2)
    return {
        **state,
        "revision_feedback_map": revision_feedback_map,
        "revision_count_map": revision_count_map,
    }


async def _assemble_survey_node(
    state: AppGraphState,
    *,
    survey_service: SurveyService,
) -> AppGraphState:
    brief: SurveyBrief = state.get("survey_brief")
    sections = [
        SurveySection.model_validate(s) for s in state.get("survey_sections") or []
    ]
    papers = [
        CuratedPaper.model_validate(p) for p in state.get("selected_papers") or []
    ]
    comparison_rows = [row for row in state.get("method_comparison_table") or []]
    citation_graph = state.get("citation_graph")
    document: SurveyDocument = await survey_service.assemble_document(
        brief=brief,
        sections=sections,
        comparison_rows=comparison_rows,
        papers=papers,
        citation_graph=citation_graph,
    )
    summary = SurveySummary(
        section_ids=[section.section_id for section in sections],
        completed=True,
        cluster_count=len(state.get("theme_clusters") or []),
        brief_ready=True,
        markdown_ready=True,
    )
    return {
        **state,
        "final_survey_document": document,
        "survey_summary": summary,
    }


def build_survey_graph(
    *,
    survey_service: SurveyService,
    stream_service: StreamService,
):
    workflow = StateGraph(AppGraphState)

    async def prepare_brief_node(state: AppGraphState) -> AppGraphState:
        return await _prepare_survey_brief_node(state, survey_service=survey_service)

    async def cluster_node(state: AppGraphState) -> AppGraphState:
        return await _cluster_themes_node(state, survey_service=survey_service)

    async def draft_node(state: AppGraphState) -> AppGraphState:
        return await _draft_current_section_node(state, survey_service=survey_service)

    async def review_node(state: AppGraphState) -> AppGraphState:
        return await _review_current_section_node(
            state,
            survey_service=survey_service,
            stream_service=stream_service,
        )

    async def assemble_node(state: AppGraphState) -> AppGraphState:
        return await _assemble_survey_node(state, survey_service=survey_service)

    workflow.add_node("prepare_survey_brief", prepare_brief_node)
    workflow.add_node("cluster_themes", cluster_node)
    workflow.add_node("draft_current_section", draft_node)
    workflow.add_node("review_current_section", review_node)
    workflow.add_node("assemble_survey", assemble_node)

    workflow.add_edge(START, "prepare_survey_brief")
    workflow.add_edge("prepare_survey_brief", "cluster_themes")
    workflow.add_edge("cluster_themes", "draft_current_section")
    workflow.add_edge("draft_current_section", "review_current_section")
    workflow.add_conditional_edges(
        "review_current_section",
        lambda state: "assemble_survey"
        if not (state.get("section_queue") or [])
        else "draft_current_section",
        {
            "assemble_survey": "assemble_survey",
            "draft_current_section": "draft_current_section",
        },
    )
    workflow.add_edge("assemble_survey", END)

    return workflow.compile(checkpointer=get_sqlite_checkpointer())
