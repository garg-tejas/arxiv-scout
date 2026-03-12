from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from graph.state import AppGraphState
from models.analysis import PaperAnalysis
from models.citation import CitationGraph
from models.enums import ArtifactType, PhaseType, StreamEventType
from models.papers import CuratedPaper
from services.analysis_service import AnalysisService
from services.artifact_service import ArtifactService
from services.citation_graph_service import CitationGraphService
from services.stream_service import StreamService


async def _analyze_selected_papers(
    state: AppGraphState,
    *,
    analysis_service: AnalysisService,
    stream_service: StreamService,
) -> AppGraphState:
    session_id = state.get("session_id") or ""
    selected_papers = [CuratedPaper.model_validate(p) for p in state.get("selected_papers") or []]
    degraded_ids: list[str] = []
    analyses: list[PaperAnalysis] = []

    for paper in selected_papers:
        analysis = await analysis_service.analyze_paper(paper)
        analyses.append(analysis)
        if analysis.analysis_quality.value != "full_text":
            degraded_ids.append(analysis.paper_id)
        await stream_service.publish(
            StreamEvent(
                session_id=session_id,
                event_type=StreamEventType.ARTIFACT_READY,
                phase=PhaseType.ANALYSIS,
                artifact_type=ArtifactType.PAPER_ANALYSIS,
                message=f"Analysis ready for {paper.title}.",
                data=analysis.model_dump(mode="json"),
            )
        )

    return {
        **state,
        "paper_analyses": analyses,
        "degraded_paper_ids": degraded_ids,
    }


async def _build_citation_graph_node(
    state: AppGraphState,
    *,
    citation_graph_service: CitationGraphService,
) -> AppGraphState:
    selected_papers = [CuratedPaper.model_validate(p) for p in state.get("selected_papers") or []]
    analyses = [PaperAnalysis.model_validate(a) for a in state.get("paper_analyses") or []]
    citation_graph: CitationGraph = await citation_graph_service.build_graph(
        seed_papers=selected_papers,
        analyses=analyses,
    )
    return {
        **state,
        "citation_graph": citation_graph,
    }


async def _build_method_comparison_table_node(
    state: AppGraphState,
    *,
    artifact_service: ArtifactService,
) -> AppGraphState:
    selected_papers = [CuratedPaper.model_validate(p) for p in state.get("selected_papers") or []]
    analyses = [PaperAnalysis.model_validate(a) for a in state.get("paper_analyses") or []]
    method_comparison_table = artifact_service.build_method_comparison_table(
        papers=selected_papers,
        analyses=analyses,
    )
    return {
        **state,
        "method_comparison_table": method_comparison_table,
    }


def build_analysis_graph(
    *,
    analysis_service: AnalysisService,
    citation_graph_service: CitationGraphService,
    artifact_service: ArtifactService,
    stream_service: StreamService,
):
    from models.events import StreamEvent  # local import to avoid cycles

    workflow = StateGraph(AppGraphState)

    async def analyze_node(state: AppGraphState) -> AppGraphState:
        return await _analyze_selected_papers(
            state,
            analysis_service=analysis_service,
            stream_service=stream_service,
        )

    async def citation_node(state: AppGraphState) -> AppGraphState:
        return await _build_citation_graph_node(
            state,
            citation_graph_service=citation_graph_service,
        )

    async def method_table_node(state: AppGraphState) -> AppGraphState:
        return await _build_method_comparison_table_node(
            state,
            artifact_service=artifact_service,
        )

    workflow.add_node("analyze_selected_papers", analyze_node)
    workflow.add_node("build_citation_graph", citation_node)
    workflow.add_node("build_method_comparison_table", method_table_node)

    workflow.add_edge(START, "analyze_selected_papers")
    workflow.add_edge("analyze_selected_papers", "build_citation_graph")
    workflow.add_edge("build_citation_graph", "build_method_comparison_table")
    workflow.add_edge("build_method_comparison_table", END)

    return workflow.compile(checkpointer=InMemorySaver())
