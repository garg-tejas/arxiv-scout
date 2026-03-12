from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from graph.commands import GraphCommand
from models.analysis import AnalysisSummary
from models.discovery import SteeringPreferences
from models.enums import (
    AllowedAction,
    ArtifactStatusValue,
    ArtifactType,
    CheckpointType,
    PhaseType,
    SessionStatus,
    StreamEventType,
)
from models.events import StreamEvent
from models.papers import CuratedPaper
from models.session import PendingInterrupt, SessionSnapshot, utc_now
from models.survey import SurveyBrief, SurveyRevisionRequest, SurveySummary
from persistence.checkpoints import GraphCheckpointStore
from persistence.session_store import SessionStore
from services.analysis_service import AnalysisService
from services.artifact_service import ArtifactService
from services.citation_graph_service import CitationGraphService
from services.discovery_service import DiscoveryService
from services.revision_service import RevisionService
from services.stream_service import StreamService
from services.survey_service import SurveyService


class SessionTransitionError(Exception):
    """Raised when a requested session transition is not allowed."""


class SessionExecutionError(Exception):
    """Raised when a session operation fails while executing an external step."""


class SessionService:
    def __init__(
        self,
        *,
        session_store: SessionStore,
        artifact_service: ArtifactService,
        analysis_service: AnalysisService,
        citation_graph_service: CitationGraphService,
        discovery_service: DiscoveryService,
        stream_service: StreamService,
        revision_service: RevisionService,
        survey_service: SurveyService,
        ttl_days: int,
        analysis_paper_cap: int,
        discovery_graph: object,
        analysis_graph: object,
    ) -> None:
        self.session_store = session_store
        self.artifact_service = artifact_service
        self.analysis_service = analysis_service
        self.citation_graph_service = citation_graph_service
        self.discovery_service = discovery_service
        self.stream_service = stream_service
        self.revision_service = revision_service
        self.survey_service = survey_service
        self.ttl_days = ttl_days
        self.analysis_paper_cap = analysis_paper_cap
        self.discovery_graph = discovery_graph
        self.analysis_graph = analysis_graph
        self.checkpoints = GraphCheckpointStore(session_store)

    async def create_session(self) -> SessionSnapshot:
        now = utc_now()
        session_id = str(uuid4())
        snapshot = SessionSnapshot(
            session_id=session_id,
            status=SessionStatus.IDLE,
            current_phase=PhaseType.NONE,
            current_checkpoint=CheckpointType.NONE,
            analysis_summary=AnalysisSummary(),
            survey_summary=SurveySummary(),
            artifact_status=self.artifact_service.build_initial_artifact_status(),
            last_updated_at=now,
        )
        expires_at = now + timedelta(days=self.ttl_days)

        await self.session_store.create_session(snapshot, created_at=now, expires_at=expires_at)
        await self.checkpoints.bootstrap_session(session_id, now)
        await self.stream_service.publish(
            StreamEvent(
                session_id=session_id,
                event_type=StreamEventType.NODE_UPDATE,
                message="Session created.",
                data={"status": snapshot.status.value},
            )
        )
        return snapshot

    async def get_session_snapshot(self, session_id: str) -> SessionSnapshot | None:
        snapshot = await self.session_store.get_session_snapshot(session_id)
        if snapshot is None:
            return None

        now = utc_now()
        snapshot.last_updated_at = now
        expires_at = now + timedelta(days=self.ttl_days)
        await self.session_store.update_session_snapshot(snapshot, expires_at=expires_at)
        return snapshot

    async def start_topic_interpretation(self, session_id: str, topic: str) -> SessionSnapshot | None:
        snapshot = await self.session_store.get_session_snapshot(session_id)
        if snapshot is None:
            return None

        normalized_topic = topic.strip()
        if not normalized_topic:
            raise SessionTransitionError("Topic cannot be empty.")

        start_time = utc_now()
        snapshot.status = SessionStatus.RUNNING
        snapshot.current_phase = PhaseType.DISCOVERY
        snapshot.current_checkpoint = CheckpointType.NONE
        snapshot.pending_interrupt = None
        snapshot.allowed_actions = []
        snapshot.topic = normalized_topic
        snapshot.search_interpretation = None
        snapshot.steering_preferences = SteeringPreferences()
        snapshot.approved_papers = []
        snapshot.approved_paper_details = []
        snapshot.latest_shortlist = []
        snapshot.preliminary_method_table = []
        snapshot.paper_analyses = []
        snapshot.method_comparison_table = []
        snapshot.citation_graph = None
        snapshot.analysis_summary = AnalysisSummary()
        self._reset_survey_state(snapshot)
        snapshot.artifact_status[ArtifactType.SEARCH_INTERPRETATION.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.SHORTLIST.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.PRELIMINARY_METHOD_TABLE.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.PAPER_ANALYSIS.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.CITATION_GRAPH.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.METHOD_COMPARISON_TABLE.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.SURVEY_BRIEF.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.THEME_CLUSTERS.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.SURVEY_SECTION.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.FINAL_SURVEY_MARKDOWN.value] = ArtifactStatusValue.PENDING
        snapshot.last_updated_at = start_time
        await self._persist_snapshot(snapshot)

        await self.stream_service.publish(
            StreamEvent(
                session_id=session_id,
                event_type=StreamEventType.PHASE_STARTED,
                phase=PhaseType.DISCOVERY,
                message="Discovery topic interpretation started.",
                data={"topic": snapshot.topic},
            )
        )

        try:
            state = await self.discovery_graph.ainvoke(
                {
                    "session_id": session_id,
                    "command": GraphCommand.START_TOPIC.value,
                    "topic": snapshot.topic,
                },
                config={"configurable": {"thread_id": session_id}},
            )
            interpretation = state.get("search_interpretation")
            pending_interrupt = state.get("pending_interrupt")
        except Exception as exc:
            snapshot.status = SessionStatus.ERROR
            snapshot.current_checkpoint = CheckpointType.NONE
            snapshot.pending_interrupt = None
            snapshot.allowed_actions = []
            snapshot.artifact_status[ArtifactType.SEARCH_INTERPRETATION.value] = ArtifactStatusValue.FAILED
            snapshot.last_updated_at = utc_now()
            await self._persist_snapshot(snapshot)
            await self.stream_service.publish(
                StreamEvent(
                    session_id=session_id,
                    event_type=StreamEventType.ERROR,
                    phase=PhaseType.DISCOVERY,
                    message="Discovery topic interpretation failed.",
                    data={"error": str(exc), "topic": snapshot.topic},
                )
            )
            raise SessionExecutionError("Discovery topic interpretation failed.") from exc

        snapshot.search_interpretation = interpretation
        snapshot.status = SessionStatus.WAITING_FOR_INPUT
        snapshot.current_checkpoint = CheckpointType.TOPIC_CONFIRMATION
        snapshot.pending_interrupt = pending_interrupt or PendingInterrupt(
            checkpoint=CheckpointType.TOPIC_CONFIRMATION,
            message="Confirm the interpreted topic and search angles before paper fetch.",
            expected_action_types=[AllowedAction.CONFIRM_TOPIC],
        )
        snapshot.allowed_actions = [AllowedAction.CONFIRM_TOPIC]
        snapshot.artifact_status[ArtifactType.SEARCH_INTERPRETATION.value] = ArtifactStatusValue.READY
        snapshot.last_updated_at = utc_now()

        await self._persist_snapshot(snapshot)
        await self.checkpoints.save(
            session_id=session_id,
            phase=PhaseType.DISCOVERY.value,
            checkpoint_key=CheckpointType.TOPIC_CONFIRMATION.value,
            state=snapshot.model_dump(mode="json"),
            saved_at=snapshot.last_updated_at,
        )

        await self.stream_service.publish(
            StreamEvent(
                session_id=session_id,
                event_type=StreamEventType.ARTIFACT_READY,
                phase=PhaseType.DISCOVERY,
                checkpoint=CheckpointType.TOPIC_CONFIRMATION,
                artifact_type=ArtifactType.SEARCH_INTERPRETATION,
                message="Search interpretation is ready for confirmation.",
                data=interpretation.model_dump(mode="json"),
            )
        )
        await self.stream_service.publish(
            StreamEvent(
                session_id=session_id,
                event_type=StreamEventType.INTERRUPT,
                phase=PhaseType.DISCOVERY,
                checkpoint=CheckpointType.TOPIC_CONFIRMATION,
                message=snapshot.pending_interrupt.message,
                data=snapshot.pending_interrupt.model_dump(mode="json"),
            )
        )
        return snapshot

    async def confirm_topic_interpretation(self, session_id: str) -> SessionSnapshot | None:
        snapshot = await self.session_store.get_session_snapshot(session_id)
        if snapshot is None:
            return None
        if snapshot.current_checkpoint != CheckpointType.TOPIC_CONFIRMATION:
            raise SessionTransitionError("Session is not waiting for topic confirmation.")
        if snapshot.search_interpretation is None or snapshot.topic is None:
            raise SessionTransitionError("Session is missing the interpreted discovery topic.")

        snapshot.status = SessionStatus.RUNNING
        snapshot.current_phase = PhaseType.DISCOVERY
        snapshot.current_checkpoint = CheckpointType.NONE
        snapshot.pending_interrupt = None
        snapshot.allowed_actions = []
        snapshot.last_updated_at = utc_now()

        await self._persist_snapshot(snapshot)
        await self.stream_service.publish(
            StreamEvent(
                session_id=session_id,
                event_type=StreamEventType.NODE_UPDATE,
                phase=PhaseType.DISCOVERY,
                message="Topic interpretation confirmed. Discovery fetch is running.",
                data={"topic": snapshot.topic},
            )
        )
        try:
            state = await self.discovery_graph.ainvoke(
                {
                    "session_id": session_id,
                    "command": GraphCommand.CONFIRM_TOPIC.value,
                },
                config={"configurable": {"thread_id": session_id}},
            )
        except Exception as exc:
            snapshot.status = SessionStatus.ERROR
            snapshot.current_checkpoint = CheckpointType.NONE
            snapshot.pending_interrupt = None
            snapshot.allowed_actions = []
            snapshot.artifact_status[ArtifactType.SHORTLIST.value] = ArtifactStatusValue.FAILED
            snapshot.artifact_status[ArtifactType.PRELIMINARY_METHOD_TABLE.value] = ArtifactStatusValue.FAILED
            snapshot.last_updated_at = utc_now()
            await self._persist_snapshot(snapshot)
            await self.stream_service.publish(
                StreamEvent(
                    session_id=snapshot.session_id,
                    event_type=StreamEventType.ERROR,
                    phase=PhaseType.DISCOVERY,
                    message="Discovery fetch failed.",
                    data={"error": str(exc)},
                )
            )
            raise SessionExecutionError("Discovery fetch failed.") from exc

        snapshot.latest_shortlist = list(state.get("latest_shortlist") or [])
        snapshot.preliminary_method_table = list(state.get("preliminary_method_table") or [])
        snapshot.status = SessionStatus.WAITING_FOR_INPUT
        snapshot.current_phase = PhaseType.DISCOVERY
        snapshot.current_checkpoint = CheckpointType.SHORTLIST_REVIEW
        snapshot.pending_interrupt = state.get("pending_interrupt") or PendingInterrupt(
            checkpoint=CheckpointType.SHORTLIST_REVIEW,
            message="Review the curated shortlist, replace the approved-paper set, or steer discovery with a nudge.",
            expected_action_types=[
                AllowedAction.UPDATE_APPROVED_PAPERS,
                AllowedAction.NUDGE_DISCOVERY,
                AllowedAction.START_ANALYSIS,
            ],
        )
        snapshot.allowed_actions = [
            AllowedAction.UPDATE_APPROVED_PAPERS,
            AllowedAction.NUDGE_DISCOVERY,
            AllowedAction.START_ANALYSIS,
        ]
        snapshot.artifact_status[ArtifactType.SHORTLIST.value] = ArtifactStatusValue.READY
        snapshot.artifact_status[ArtifactType.PRELIMINARY_METHOD_TABLE.value] = ArtifactStatusValue.READY
        snapshot.last_updated_at = utc_now()

        await self._persist_snapshot(snapshot)
        await self.checkpoints.save(
            session_id=snapshot.session_id,
            phase=PhaseType.DISCOVERY.value,
            checkpoint_key=CheckpointType.SHORTLIST_REVIEW.value,
            state=snapshot.model_dump(mode="json"),
            saved_at=snapshot.last_updated_at,
        )
        await self.stream_service.publish(
            StreamEvent(
                session_id=snapshot.session_id,
                event_type=StreamEventType.ARTIFACT_READY,
                phase=PhaseType.DISCOVERY,
                checkpoint=CheckpointType.SHORTLIST_REVIEW,
                artifact_type=ArtifactType.SHORTLIST,
                message="Curated shortlist is ready for review.",
                data={"papers": [paper.model_dump(mode="json") for paper in snapshot.latest_shortlist]},
            )
        )
        await self.stream_service.publish(
            StreamEvent(
                session_id=snapshot.session_id,
                event_type=StreamEventType.ARTIFACT_READY,
                phase=PhaseType.DISCOVERY,
                checkpoint=CheckpointType.SHORTLIST_REVIEW,
                artifact_type=ArtifactType.PRELIMINARY_METHOD_TABLE,
                message="Preliminary method extraction table is ready.",
                data={"rows": [row.model_dump(mode="json") for row in snapshot.preliminary_method_table]},
            )
        )
        await self.stream_service.publish(
            StreamEvent(
                session_id=snapshot.session_id,
                event_type=StreamEventType.INTERRUPT,
                phase=PhaseType.DISCOVERY,
                checkpoint=CheckpointType.SHORTLIST_REVIEW,
                message=snapshot.pending_interrupt.message,
                data=snapshot.pending_interrupt.model_dump(mode="json"),
            )
        )
        return snapshot

    async def update_approved_papers(
        self,
        session_id: str,
        paper_ids: list[str],
    ) -> SessionSnapshot | None:
        snapshot = await self.session_store.get_session_snapshot(session_id)
        if snapshot is None:
            return None
        self._ensure_shortlist_review_ready(snapshot)

        valid_ids = {paper.paper_id for paper in snapshot.latest_shortlist} | set(snapshot.approved_papers)
        deduped_ids: list[str] = []
        seen: set[str] = set()
        for paper_id in paper_ids:
            normalized = paper_id.strip()
            if not normalized or normalized in seen:
                continue
            if normalized not in valid_ids:
                raise SessionTransitionError(
                    f"Approved paper '{normalized}' is not available in the current shortlist or prior approvals."
                )
            seen.add(normalized)
            deduped_ids.append(normalized)

        snapshot.approved_papers = deduped_ids
        await self.discovery_graph.aupdate_state(
            config={"configurable": {"thread_id": session_id}},
            values={"approved_papers": deduped_ids},
            as_node="store_approved_papers",
        )
        graph_state = await self.discovery_graph.aget_state({"configurable": {"thread_id": session_id}})
        values = graph_state.values if graph_state else {}
        snapshot.approved_papers = list(values.get("approved_papers") or deduped_ids)
        snapshot.approved_paper_details = list(values.get("approved_paper_details") or [])
        snapshot.last_updated_at = utc_now()
        await self._persist_snapshot(snapshot)
        await self.checkpoints.save(
            session_id=session_id,
            phase=PhaseType.DISCOVERY.value,
            checkpoint_key="approved_papers_updated",
            state=snapshot.model_dump(mode="json"),
            saved_at=snapshot.last_updated_at,
        )
        await self.stream_service.publish(
            StreamEvent(
                session_id=session_id,
                event_type=StreamEventType.NODE_UPDATE,
                phase=PhaseType.DISCOVERY,
                checkpoint=CheckpointType.SHORTLIST_REVIEW,
                message="Approved paper list updated.",
                data={"approved_papers": snapshot.approved_papers},
            )
        )
        return snapshot

    async def start_analysis(
        self,
        session_id: str,
        paper_ids: list[str],
    ) -> SessionSnapshot | None:
        snapshot = await self.session_store.get_session_snapshot(session_id)
        if snapshot is None:
            return None

        if not snapshot.approved_papers:
            raise SessionTransitionError("At least one approved paper is required before analysis can start.")

        selected_ids = [paper_id.strip() for paper_id in paper_ids if paper_id.strip()]
        approved_ids = list(snapshot.approved_papers)

        if not selected_ids and len(approved_ids) > self.analysis_paper_cap:
            snapshot.status = SessionStatus.WAITING_FOR_INPUT
            snapshot.current_phase = PhaseType.ANALYSIS
            snapshot.current_checkpoint = CheckpointType.ANALYSIS_SELECTION
            snapshot.pending_interrupt = PendingInterrupt(
                checkpoint=CheckpointType.ANALYSIS_SELECTION,
                message=f"Select up to {self.analysis_paper_cap} approved papers to analyze.",
                expected_action_types=[AllowedAction.SELECT_ANALYSIS_PAPERS],
            )
            snapshot.allowed_actions = [AllowedAction.SELECT_ANALYSIS_PAPERS]
            snapshot.analysis_summary.selected_paper_ids = []
            snapshot.analysis_summary.completed = False
            snapshot.analysis_summary.degraded_paper_ids = []
            snapshot.analysis_summary.comparison_row_count = 0
            snapshot.analysis_summary.retained_context_node_count = 0
            snapshot.analysis_summary.lineage_path_count = 0
            snapshot.analysis_summary.citation_graph_summary = None
            snapshot.last_updated_at = utc_now()
            await self._persist_snapshot(snapshot)
            await self.checkpoints.save(
                session_id=session_id,
                phase=PhaseType.ANALYSIS.value,
                checkpoint_key=CheckpointType.ANALYSIS_SELECTION.value,
                state=snapshot.model_dump(mode="json"),
                saved_at=snapshot.last_updated_at,
            )
            await self.stream_service.publish(
                StreamEvent(
                    session_id=session_id,
                    event_type=StreamEventType.INTERRUPT,
                    phase=PhaseType.ANALYSIS,
                    checkpoint=CheckpointType.ANALYSIS_SELECTION,
                    message=snapshot.pending_interrupt.message,
                    data={
                        **snapshot.pending_interrupt.model_dump(mode="json"),
                        "approved_papers": snapshot.approved_papers,
                    },
                )
            )
            return snapshot

        if not selected_ids:
            selected_ids = approved_ids

        if len(selected_ids) > self.analysis_paper_cap:
            raise SessionTransitionError(
                f"Analysis accepts at most {self.analysis_paper_cap} paper IDs per run."
            )

        invalid_ids = [paper_id for paper_id in selected_ids if paper_id not in approved_ids]
        if invalid_ids:
            raise SessionTransitionError(
                f"Selected paper IDs are not in the approved set: {', '.join(invalid_ids)}"
            )

        selected_papers = self._resolve_approved_paper_details(snapshot, selected_ids)
        if len(selected_papers) != len(selected_ids):
            missing = sorted(set(selected_ids) - {paper.paper_id for paper in selected_papers})
            raise SessionTransitionError(
                f"Missing metadata for approved paper(s): {', '.join(missing)}"
            )

        snapshot.status = SessionStatus.RUNNING
        snapshot.current_phase = PhaseType.ANALYSIS
        snapshot.current_checkpoint = CheckpointType.NONE
        snapshot.pending_interrupt = None
        snapshot.allowed_actions = []
        snapshot.analysis_summary.selected_paper_ids = selected_ids
        snapshot.analysis_summary.completed = False
        snapshot.analysis_summary.degraded_paper_ids = []
        snapshot.analysis_summary.comparison_row_count = 0
        snapshot.analysis_summary.retained_context_node_count = 0
        snapshot.analysis_summary.lineage_path_count = 0
        snapshot.analysis_summary.citation_graph_summary = None
        snapshot.paper_analyses = []
        snapshot.method_comparison_table = []
        snapshot.citation_graph = None
        self._reset_survey_state(snapshot)
        snapshot.artifact_status[ArtifactType.PAPER_ANALYSIS.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.CITATION_GRAPH.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.METHOD_COMPARISON_TABLE.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.SURVEY_BRIEF.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.THEME_CLUSTERS.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.SURVEY_SECTION.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.FINAL_SURVEY_MARKDOWN.value] = ArtifactStatusValue.PENDING
        snapshot.last_updated_at = utc_now()
        await self._persist_snapshot(snapshot)

        await self.stream_service.publish(
            StreamEvent(
                session_id=session_id,
                event_type=StreamEventType.PHASE_STARTED,
                phase=PhaseType.ANALYSIS,
                message="Paper analysis started.",
                data={"paper_ids": selected_ids},
            )
        )

        try:
            state = await self.analysis_graph.ainvoke(
                {
                    "session_id": session_id,
                    "selected_papers": [paper.model_dump(mode="json") for paper in selected_papers],
                },
                config={"configurable": {"thread_id": session_id}},
            )
        except Exception as exc:
            snapshot.status = SessionStatus.ERROR
            snapshot.current_checkpoint = CheckpointType.NONE
            snapshot.pending_interrupt = None
            snapshot.allowed_actions = []
            snapshot.analysis_summary.completed = False
            snapshot.analysis_summary.comparison_row_count = 0
            snapshot.analysis_summary.retained_context_node_count = 0
            snapshot.analysis_summary.lineage_path_count = 0
            snapshot.analysis_summary.citation_graph_summary = None
            snapshot.artifact_status[ArtifactType.PAPER_ANALYSIS.value] = ArtifactStatusValue.FAILED
            snapshot.artifact_status[ArtifactType.CITATION_GRAPH.value] = ArtifactStatusValue.FAILED
            snapshot.artifact_status[ArtifactType.METHOD_COMPARISON_TABLE.value] = ArtifactStatusValue.FAILED
            snapshot.last_updated_at = utc_now()
            await self._persist_snapshot(snapshot)
            await self.stream_service.publish(
                StreamEvent(
                    session_id=session_id,
                    event_type=StreamEventType.ERROR,
                    phase=PhaseType.ANALYSIS,
                    message="Analysis pipeline failed.",
                    data={"error": str(exc), "selected_paper_ids": selected_ids},
                )
            )
            raise SessionExecutionError("Analysis pipeline failed.") from exc

        degraded_ids = list(state.get("degraded_paper_ids") or [])
        analyses = [analysis for analysis in state.get("paper_analyses") or []]
        citation_graph = state.get("citation_graph")
        method_comparison_table = [row for row in state.get("method_comparison_table") or []]

        snapshot.paper_analyses = analyses
        snapshot.method_comparison_table = method_comparison_table
        snapshot.citation_graph = citation_graph
        snapshot.status = SessionStatus.IDLE
        snapshot.current_phase = PhaseType.ANALYSIS
        snapshot.current_checkpoint = CheckpointType.NONE
        snapshot.pending_interrupt = None
        snapshot.allowed_actions = [AllowedAction.START_SURVEY]
        snapshot.analysis_summary.selected_paper_ids = selected_ids
        snapshot.analysis_summary.completed = True
        snapshot.analysis_summary.degraded_paper_ids = degraded_ids
        snapshot.analysis_summary.comparison_row_count = len(method_comparison_table)
        snapshot.analysis_summary.retained_context_node_count = len(citation_graph.context_nodes)
        snapshot.analysis_summary.lineage_path_count = len(citation_graph.lineage_paths)
        snapshot.analysis_summary.citation_graph_summary = citation_graph.narrative_summary
        snapshot.artifact_status[ArtifactType.PAPER_ANALYSIS.value] = ArtifactStatusValue.READY
        snapshot.artifact_status[ArtifactType.CITATION_GRAPH.value] = ArtifactStatusValue.READY
        snapshot.artifact_status[ArtifactType.METHOD_COMPARISON_TABLE.value] = ArtifactStatusValue.READY
        snapshot.last_updated_at = utc_now()
        await self._persist_snapshot(snapshot)
        await self.checkpoints.save(
            session_id=session_id,
            phase=PhaseType.ANALYSIS.value,
            checkpoint_key="analysis_completed",
            state=snapshot.model_dump(mode="json"),
            saved_at=snapshot.last_updated_at,
        )
        await self.stream_service.publish(
            StreamEvent(
                session_id=session_id,
                event_type=StreamEventType.ARTIFACT_READY,
                phase=PhaseType.ANALYSIS,
                artifact_type=ArtifactType.CITATION_GRAPH,
                message="Citation graph and lineage summary are ready.",
                data=citation_graph.model_dump(mode="json"),
            )
        )
        await self.stream_service.publish(
            StreamEvent(
                session_id=session_id,
                event_type=StreamEventType.ARTIFACT_READY,
                phase=PhaseType.ANALYSIS,
                artifact_type=ArtifactType.METHOD_COMPARISON_TABLE,
                message="Method comparison table is ready.",
                data={"rows": [row.model_dump(mode="json") for row in method_comparison_table]},
            )
        )
        await self.stream_service.publish(
            StreamEvent(
                session_id=session_id,
                event_type=StreamEventType.PHASE_COMPLETED,
                phase=PhaseType.ANALYSIS,
                message="Per-paper analysis completed.",
                data={
                    "selected_paper_ids": selected_ids,
                    "degraded_paper_ids": degraded_ids,
                    "comparison_row_count": len(method_comparison_table),
                    "retained_context_node_count": len(citation_graph.context_nodes),
                    "lineage_path_count": len(citation_graph.lineage_paths),
                    "citation_graph_summary": citation_graph.narrative_summary,
                },
            )
        )
        return snapshot

    async def start_survey(
        self,
        session_id: str,
        *,
        brief: SurveyBrief | None,
        skip: bool,
    ) -> SessionSnapshot | None:
        snapshot = await self.session_store.get_session_snapshot(session_id)
        if snapshot is None:
            return None
        if not snapshot.analysis_summary.completed or not snapshot.paper_analyses:
            raise SessionTransitionError("Complete analysis before starting survey generation.")

        if brief is None and not skip:
            snapshot.status = SessionStatus.WAITING_FOR_INPUT
            snapshot.current_phase = PhaseType.SURVEY
            snapshot.current_checkpoint = CheckpointType.SURVEY_BRIEF
            snapshot.pending_interrupt = PendingInterrupt(
                checkpoint=CheckpointType.SURVEY_BRIEF,
                message="Provide a survey brief or skip to synthesize one automatically.",
                expected_action_types=[
                    AllowedAction.SUBMIT_SURVEY_BRIEF,
                    AllowedAction.SKIP_SURVEY_BRIEF,
                ],
            )
            snapshot.allowed_actions = [
                AllowedAction.SUBMIT_SURVEY_BRIEF,
                AllowedAction.SKIP_SURVEY_BRIEF,
            ]
            snapshot.last_updated_at = utc_now()
            await self._persist_snapshot(snapshot)
            await self.checkpoints.save(
                session_id=session_id,
                phase=PhaseType.SURVEY.value,
                checkpoint_key=CheckpointType.SURVEY_BRIEF.value,
                state=snapshot.model_dump(mode="json"),
                saved_at=snapshot.last_updated_at,
            )
            await self.stream_service.publish(
                StreamEvent(
                    session_id=session_id,
                    event_type=StreamEventType.INTERRUPT,
                    phase=PhaseType.SURVEY,
                    checkpoint=CheckpointType.SURVEY_BRIEF,
                    message=snapshot.pending_interrupt.message,
                    data=snapshot.pending_interrupt.model_dump(mode="json"),
                )
            )
            return snapshot

        survey_brief = brief or await self.survey_service.synthesize_brief(snapshot)
        try:
            return await self._run_survey_pipeline(
                snapshot,
                survey_brief=survey_brief,
                phase_message="Survey generation started.",
            )
        except Exception as exc:
            await self._mark_survey_failure(
                snapshot,
                message="Survey generation failed.",
                error=exc,
            )
            raise SessionExecutionError("Survey generation failed.") from exc

    async def revise_survey(
        self,
        session_id: str,
        revision_request: SurveyRevisionRequest,
    ) -> SessionSnapshot | None:
        snapshot = await self.session_store.get_session_snapshot(session_id)
        if snapshot is None:
            return None
        if snapshot.current_checkpoint != CheckpointType.SURVEY_REVIEW or snapshot.final_survey_document is None:
            raise SessionTransitionError("Session is not waiting at final survey review.")
        if snapshot.survey_brief is None:
            raise SessionTransitionError("Survey brief is missing from the current session.")

        try:
            revision_map = self.revision_service.validate_revisions(revision_request)
        except ValueError as exc:
            raise SessionTransitionError(str(exc)) from exc

        cluster_map = {cluster.cluster_id: cluster for cluster in snapshot.theme_clusters}
        section_map = {section.section_id: section for section in snapshot.survey_sections}
        unknown_ids = sorted(set(revision_map) - set(section_map))
        if unknown_ids:
            raise SessionTransitionError(
                f"Unknown survey section IDs: {', '.join(unknown_ids)}"
            )

        snapshot.status = SessionStatus.RUNNING
        snapshot.current_phase = PhaseType.SURVEY
        snapshot.current_checkpoint = CheckpointType.NONE
        snapshot.pending_interrupt = None
        snapshot.allowed_actions = []
        snapshot.artifact_status[ArtifactType.SURVEY_SECTION.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.FINAL_SURVEY_MARKDOWN.value] = ArtifactStatusValue.PENDING
        snapshot.last_updated_at = utc_now()
        await self._persist_snapshot(snapshot)

        await self.stream_service.publish(
            StreamEvent(
                session_id=session_id,
                event_type=StreamEventType.NODE_UPDATE,
                phase=PhaseType.SURVEY,
                message="Targeted survey section revision started.",
                data={"section_ids": list(revision_map)},
            )
        )

        try:
            selected_papers = self._resolve_selected_analysis_papers(snapshot)
            updated_sections = []
            for section in snapshot.survey_sections:
                if section.section_id not in revision_map:
                    updated_sections.append(section)
                    continue
                cluster = cluster_map[section.section_id]
                regenerated = await self._draft_and_review_section(
                    session_id=session_id,
                    snapshot=snapshot,
                    cluster=cluster,
                    papers=selected_papers,
                    revision_feedback=revision_map[section.section_id],
                    revision_count=min(section.revision_count + 1, 2),
                )
                updated_sections.append(regenerated)

            final_document = await self.survey_service.assemble_document(
                brief=snapshot.survey_brief,
                sections=updated_sections,
                comparison_rows=snapshot.method_comparison_table,
                papers=selected_papers,
                citation_graph=snapshot.citation_graph,
            )
            snapshot.survey_sections = updated_sections
            snapshot.final_survey_document = final_document
            snapshot.survey_summary.section_ids = [section.section_id for section in updated_sections]
            snapshot.survey_summary.completed = True
            snapshot.survey_summary.cluster_count = len(snapshot.theme_clusters)
            snapshot.survey_summary.brief_ready = True
            snapshot.survey_summary.markdown_ready = True
            snapshot.status = SessionStatus.WAITING_FOR_INPUT
            snapshot.current_phase = PhaseType.SURVEY
            snapshot.current_checkpoint = CheckpointType.SURVEY_REVIEW
            snapshot.pending_interrupt = PendingInterrupt(
                checkpoint=CheckpointType.SURVEY_REVIEW,
                message="Review the assembled survey or request further targeted revisions.",
                expected_action_types=[
                    AllowedAction.REVISE_SURVEY_SECTIONS,
                    AllowedAction.APPROVE_FINAL_SURVEY,
                ],
            )
            snapshot.allowed_actions = [
                AllowedAction.REVISE_SURVEY_SECTIONS,
                AllowedAction.APPROVE_FINAL_SURVEY,
            ]
            snapshot.artifact_status[ArtifactType.SURVEY_SECTION.value] = ArtifactStatusValue.READY
            snapshot.artifact_status[ArtifactType.FINAL_SURVEY_MARKDOWN.value] = ArtifactStatusValue.READY
            snapshot.last_updated_at = utc_now()
            await self._persist_snapshot(snapshot)
            await self.checkpoints.save(
                session_id=session_id,
                phase=PhaseType.SURVEY.value,
                checkpoint_key=CheckpointType.SURVEY_REVIEW.value,
                state=snapshot.model_dump(mode="json"),
                saved_at=snapshot.last_updated_at,
            )
            await self.stream_service.publish(
                StreamEvent(
                    session_id=session_id,
                    event_type=StreamEventType.ARTIFACT_READY,
                    phase=PhaseType.SURVEY,
                    checkpoint=CheckpointType.SURVEY_REVIEW,
                    artifact_type=ArtifactType.FINAL_SURVEY_MARKDOWN,
                    message="Final survey markdown updated after targeted revisions.",
                    data={"markdown": final_document.markdown},
                )
            )
            await self.stream_service.publish(
                StreamEvent(
                    session_id=session_id,
                    event_type=StreamEventType.INTERRUPT,
                    phase=PhaseType.SURVEY,
                    checkpoint=CheckpointType.SURVEY_REVIEW,
                    message=snapshot.pending_interrupt.message,
                    data=snapshot.pending_interrupt.model_dump(mode="json"),
                )
            )
            return snapshot
        except Exception as exc:
            await self._mark_survey_failure(
                snapshot,
                message="Survey revision failed.",
                error=exc,
            )
            raise SessionExecutionError("Survey revision failed.") from exc

    async def approve_survey(self, session_id: str) -> SessionSnapshot | None:
        snapshot = await self.session_store.get_session_snapshot(session_id)
        if snapshot is None:
            return None
        if snapshot.final_survey_document is None or snapshot.current_checkpoint != CheckpointType.SURVEY_REVIEW:
            raise SessionTransitionError("Session is not waiting for final survey approval.")

        snapshot.status = SessionStatus.COMPLETED
        snapshot.current_phase = PhaseType.SURVEY
        snapshot.current_checkpoint = CheckpointType.NONE
        snapshot.pending_interrupt = None
        snapshot.allowed_actions = [AllowedAction.DOWNLOAD_SURVEY_MARKDOWN]
        snapshot.last_updated_at = utc_now()
        await self._persist_snapshot(snapshot)
        await self.checkpoints.save(
            session_id=session_id,
            phase=PhaseType.SURVEY.value,
            checkpoint_key="survey_approved",
            state=snapshot.model_dump(mode="json"),
            saved_at=snapshot.last_updated_at,
        )
        await self.stream_service.publish(
            StreamEvent(
                session_id=session_id,
                event_type=StreamEventType.PHASE_COMPLETED,
                phase=PhaseType.SURVEY,
                message="Survey approved and finalized.",
                data={"section_ids": snapshot.survey_summary.section_ids},
            )
        )
        return snapshot

    async def get_survey_markdown(self, session_id: str) -> str | None:
        snapshot = await self.session_store.get_session_snapshot(session_id)
        if snapshot is None:
            return None
        if snapshot.final_survey_document is None:
            raise SessionTransitionError("Survey markdown is not ready yet.")
        return self.survey_service.render_markdown(snapshot.final_survey_document)

    async def apply_discovery_nudge(self, session_id: str, text: str) -> SessionSnapshot | None:
        snapshot = await self.session_store.get_session_snapshot(session_id)
        if snapshot is None:
            return None
        self._ensure_shortlist_review_ready(snapshot)
        if snapshot.search_interpretation is None or snapshot.topic is None:
            raise SessionTransitionError("Session is missing discovery context for rerunning the shortlist.")

        try:
            state = await self.discovery_graph.ainvoke(
                {
                    "session_id": session_id,
                    "command": GraphCommand.NUDGE_DISCOVERY.value,
                    "nudge_text": text,
                },
                config={"configurable": {"thread_id": session_id}},
            )
        except Exception as exc:
            raise SessionExecutionError("Discovery steering merge failed.") from exc
        snapshot.steering_preferences = state.get("steering_preferences") or snapshot.steering_preferences
        snapshot.status = SessionStatus.RUNNING
        snapshot.current_phase = PhaseType.DISCOVERY
        snapshot.current_checkpoint = CheckpointType.NONE
        snapshot.pending_interrupt = None
        snapshot.allowed_actions = []
        snapshot.artifact_status[ArtifactType.SHORTLIST.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.PRELIMINARY_METHOD_TABLE.value] = ArtifactStatusValue.PENDING
        snapshot.last_updated_at = utc_now()
        await self._persist_snapshot(snapshot)

        await self.stream_service.publish(
            StreamEvent(
                session_id=session_id,
                event_type=StreamEventType.NODE_UPDATE,
                phase=PhaseType.DISCOVERY,
                message="Discovery steering updated. Regenerating shortlist.",
                data={
                    "nudge_text": text,
                    "steering_preferences": snapshot.steering_preferences.model_dump(mode="json"),
                },
            )
        )
        snapshot.latest_shortlist = list(state.get("latest_shortlist") or [])
        snapshot.preliminary_method_table = list(state.get("preliminary_method_table") or [])
        snapshot.status = SessionStatus.WAITING_FOR_INPUT
        snapshot.current_phase = PhaseType.DISCOVERY
        snapshot.current_checkpoint = CheckpointType.SHORTLIST_REVIEW
        snapshot.pending_interrupt = state.get("pending_interrupt") or PendingInterrupt(
            checkpoint=CheckpointType.SHORTLIST_REVIEW,
            message="Review the curated shortlist, replace the approved-paper set, or steer discovery with a nudge.",
            expected_action_types=[
                AllowedAction.UPDATE_APPROVED_PAPERS,
                AllowedAction.NUDGE_DISCOVERY,
                AllowedAction.START_ANALYSIS,
            ],
        )
        snapshot.allowed_actions = [
            AllowedAction.UPDATE_APPROVED_PAPERS,
            AllowedAction.NUDGE_DISCOVERY,
            AllowedAction.START_ANALYSIS,
        ]
        snapshot.artifact_status[ArtifactType.SHORTLIST.value] = ArtifactStatusValue.READY
        snapshot.artifact_status[ArtifactType.PRELIMINARY_METHOD_TABLE.value] = ArtifactStatusValue.READY
        snapshot.last_updated_at = utc_now()

        await self._persist_snapshot(snapshot)
        await self.checkpoints.save(
            session_id=snapshot.session_id,
            phase=PhaseType.DISCOVERY.value,
            checkpoint_key=CheckpointType.SHORTLIST_REVIEW.value,
            state=snapshot.model_dump(mode="json"),
            saved_at=snapshot.last_updated_at,
        )
        await self.stream_service.publish(
            StreamEvent(
                session_id=snapshot.session_id,
                event_type=StreamEventType.ARTIFACT_READY,
                phase=PhaseType.DISCOVERY,
                checkpoint=CheckpointType.SHORTLIST_REVIEW,
                artifact_type=ArtifactType.SHORTLIST,
                message="Updated shortlist is ready after applying the steering nudge.",
                data={"papers": [paper.model_dump(mode="json") for paper in snapshot.latest_shortlist]},
            )
        )
        await self.stream_service.publish(
            StreamEvent(
                session_id=snapshot.session_id,
                event_type=StreamEventType.ARTIFACT_READY,
                phase=PhaseType.DISCOVERY,
                checkpoint=CheckpointType.SHORTLIST_REVIEW,
                artifact_type=ArtifactType.PRELIMINARY_METHOD_TABLE,
                message="Preliminary method extraction table is ready.",
                data={"rows": [row.model_dump(mode="json") for row in snapshot.preliminary_method_table]},
            )
        )
        await self.stream_service.publish(
            StreamEvent(
                session_id=snapshot.session_id,
                event_type=StreamEventType.INTERRUPT,
                phase=PhaseType.DISCOVERY,
                checkpoint=CheckpointType.SHORTLIST_REVIEW,
                message=snapshot.pending_interrupt.message,
                data=snapshot.pending_interrupt.model_dump(mode="json"),
            )
        )
        return snapshot

    async def _persist_snapshot(self, snapshot: SessionSnapshot) -> None:
        expires_at = snapshot.last_updated_at + timedelta(days=self.ttl_days)
        await self.session_store.update_session_snapshot(snapshot, expires_at=expires_at)

    async def _run_survey_pipeline(
        self,
        snapshot: SessionSnapshot,
        *,
        survey_brief: SurveyBrief,
        phase_message: str,
    ) -> SessionSnapshot:
        selected_papers = self._resolve_selected_analysis_papers(snapshot)
        if not selected_papers:
            raise SessionTransitionError("Selected analysis papers are missing from the session state.")

        snapshot.status = SessionStatus.RUNNING
        snapshot.current_phase = PhaseType.SURVEY
        snapshot.current_checkpoint = CheckpointType.NONE
        snapshot.pending_interrupt = None
        snapshot.allowed_actions = []
        snapshot.survey_brief = survey_brief
        snapshot.theme_clusters = []
        snapshot.survey_sections = []
        snapshot.final_survey_document = None
        snapshot.survey_summary = SurveySummary(
            section_ids=[],
            completed=False,
            cluster_count=0,
            brief_ready=True,
            markdown_ready=False,
        )
        snapshot.artifact_status[ArtifactType.SURVEY_BRIEF.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.THEME_CLUSTERS.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.SURVEY_SECTION.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.FINAL_SURVEY_MARKDOWN.value] = ArtifactStatusValue.PENDING
        snapshot.last_updated_at = utc_now()
        await self._persist_snapshot(snapshot)

        await self.stream_service.publish(
            StreamEvent(
                session_id=snapshot.session_id,
                event_type=StreamEventType.PHASE_STARTED,
                phase=PhaseType.SURVEY,
                message=phase_message,
                data={"paper_ids": snapshot.analysis_summary.selected_paper_ids},
            )
        )

        snapshot.artifact_status[ArtifactType.SURVEY_BRIEF.value] = ArtifactStatusValue.READY
        await self.stream_service.publish(
            StreamEvent(
                session_id=snapshot.session_id,
                event_type=StreamEventType.ARTIFACT_READY,
                phase=PhaseType.SURVEY,
                artifact_type=ArtifactType.SURVEY_BRIEF,
                message="Survey brief is ready.",
                data=survey_brief.model_dump(mode="json"),
            )
        )

        clusters = await self.survey_service.cluster_themes(
            brief=survey_brief,
            papers=selected_papers,
            analyses=snapshot.paper_analyses,
            comparison_rows=snapshot.method_comparison_table,
            citation_graph=snapshot.citation_graph,
        )
        snapshot.theme_clusters = clusters
        snapshot.survey_summary.cluster_count = len(clusters)
        snapshot.artifact_status[ArtifactType.THEME_CLUSTERS.value] = ArtifactStatusValue.READY
        await self.stream_service.publish(
            StreamEvent(
                session_id=snapshot.session_id,
                event_type=StreamEventType.ARTIFACT_READY,
                phase=PhaseType.SURVEY,
                artifact_type=ArtifactType.THEME_CLUSTERS,
                message="Theme clusters are ready.",
                data={"clusters": [cluster.model_dump(mode="json") for cluster in clusters]},
            )
        )

        sections = []
        for cluster in clusters:
            section = await self._draft_and_review_section(
                session_id=snapshot.session_id,
                snapshot=snapshot,
                cluster=cluster,
                papers=selected_papers,
                revision_feedback=None,
                revision_count=0,
            )
            sections.append(section)

        final_document = await self.survey_service.assemble_document(
            brief=survey_brief,
            sections=sections,
            comparison_rows=snapshot.method_comparison_table,
            papers=selected_papers,
            citation_graph=snapshot.citation_graph,
        )
        snapshot.survey_sections = sections
        snapshot.final_survey_document = final_document
        snapshot.survey_summary.section_ids = [section.section_id for section in sections]
        snapshot.survey_summary.completed = True
        snapshot.survey_summary.markdown_ready = True
        snapshot.status = SessionStatus.WAITING_FOR_INPUT
        snapshot.current_phase = PhaseType.SURVEY
        snapshot.current_checkpoint = CheckpointType.SURVEY_REVIEW
        snapshot.pending_interrupt = PendingInterrupt(
            checkpoint=CheckpointType.SURVEY_REVIEW,
            message="Review the assembled survey or request targeted section revisions.",
            expected_action_types=[
                AllowedAction.REVISE_SURVEY_SECTIONS,
                AllowedAction.APPROVE_FINAL_SURVEY,
            ],
        )
        snapshot.allowed_actions = [
            AllowedAction.REVISE_SURVEY_SECTIONS,
            AllowedAction.APPROVE_FINAL_SURVEY,
        ]
        snapshot.artifact_status[ArtifactType.SURVEY_SECTION.value] = ArtifactStatusValue.READY
        snapshot.artifact_status[ArtifactType.FINAL_SURVEY_MARKDOWN.value] = ArtifactStatusValue.READY
        snapshot.last_updated_at = utc_now()
        await self._persist_snapshot(snapshot)
        await self.checkpoints.save(
            session_id=snapshot.session_id,
            phase=PhaseType.SURVEY.value,
            checkpoint_key=CheckpointType.SURVEY_REVIEW.value,
            state=snapshot.model_dump(mode="json"),
            saved_at=snapshot.last_updated_at,
        )
        await self.stream_service.publish(
            StreamEvent(
                session_id=snapshot.session_id,
                event_type=StreamEventType.ARTIFACT_READY,
                phase=PhaseType.SURVEY,
                checkpoint=CheckpointType.SURVEY_REVIEW,
                artifact_type=ArtifactType.FINAL_SURVEY_MARKDOWN,
                message="Final survey markdown is ready for review.",
                data={"markdown": final_document.markdown},
            )
        )
        await self.stream_service.publish(
            StreamEvent(
                session_id=snapshot.session_id,
                event_type=StreamEventType.INTERRUPT,
                phase=PhaseType.SURVEY,
                checkpoint=CheckpointType.SURVEY_REVIEW,
                message=snapshot.pending_interrupt.message,
                data=snapshot.pending_interrupt.model_dump(mode="json"),
            )
        )
        return snapshot

    async def _rerun_discovery_shortlist(
        self,
        snapshot: SessionSnapshot,
        *,
        reason_message: str,
    ) -> SessionSnapshot:
        try:
            shortlist, method_table = await self.discovery_service.build_shortlist(
                topic=snapshot.topic or "",
                interpretation=snapshot.search_interpretation,
                steering_preferences=snapshot.steering_preferences,
            )
        except Exception as exc:
            snapshot.status = SessionStatus.ERROR
            snapshot.current_checkpoint = CheckpointType.NONE
            snapshot.pending_interrupt = None
            snapshot.allowed_actions = []
            snapshot.artifact_status[ArtifactType.SHORTLIST.value] = ArtifactStatusValue.FAILED
            snapshot.artifact_status[ArtifactType.PRELIMINARY_METHOD_TABLE.value] = ArtifactStatusValue.FAILED
            snapshot.last_updated_at = utc_now()
            await self._persist_snapshot(snapshot)
            await self.stream_service.publish(
                StreamEvent(
                    session_id=snapshot.session_id,
                    event_type=StreamEventType.ERROR,
                    phase=PhaseType.DISCOVERY,
                    message="Discovery fetch failed.",
                    data={"error": str(exc)},
                )
            )
            raise SessionExecutionError("Discovery fetch failed.") from exc

        snapshot.latest_shortlist = shortlist
        snapshot.preliminary_method_table = method_table
        snapshot.status = SessionStatus.WAITING_FOR_INPUT
        snapshot.current_phase = PhaseType.DISCOVERY
        snapshot.current_checkpoint = CheckpointType.SHORTLIST_REVIEW
        snapshot.pending_interrupt = PendingInterrupt(
            checkpoint=CheckpointType.SHORTLIST_REVIEW,
            message="Review the curated shortlist, replace the approved-paper set, or steer discovery with a nudge.",
            expected_action_types=[
                AllowedAction.UPDATE_APPROVED_PAPERS,
                AllowedAction.NUDGE_DISCOVERY,
                AllowedAction.START_ANALYSIS,
            ],
        )
        snapshot.allowed_actions = [
            AllowedAction.UPDATE_APPROVED_PAPERS,
            AllowedAction.NUDGE_DISCOVERY,
            AllowedAction.START_ANALYSIS,
        ]
        snapshot.artifact_status[ArtifactType.SHORTLIST.value] = ArtifactStatusValue.READY
        snapshot.artifact_status[ArtifactType.PRELIMINARY_METHOD_TABLE.value] = ArtifactStatusValue.READY
        snapshot.last_updated_at = utc_now()

        await self._persist_snapshot(snapshot)
        await self.checkpoints.save(
            session_id=snapshot.session_id,
            phase=PhaseType.DISCOVERY.value,
            checkpoint_key=CheckpointType.SHORTLIST_REVIEW.value,
            state=snapshot.model_dump(mode="json"),
            saved_at=snapshot.last_updated_at,
        )
        await self.stream_service.publish(
            StreamEvent(
                session_id=snapshot.session_id,
                event_type=StreamEventType.ARTIFACT_READY,
                phase=PhaseType.DISCOVERY,
                checkpoint=CheckpointType.SHORTLIST_REVIEW,
                artifact_type=ArtifactType.SHORTLIST,
                message=reason_message,
                data={"papers": [paper.model_dump(mode="json") for paper in shortlist]},
            )
        )
        await self.stream_service.publish(
            StreamEvent(
                session_id=snapshot.session_id,
                event_type=StreamEventType.ARTIFACT_READY,
                phase=PhaseType.DISCOVERY,
                checkpoint=CheckpointType.SHORTLIST_REVIEW,
                artifact_type=ArtifactType.PRELIMINARY_METHOD_TABLE,
                message="Preliminary method extraction table is ready.",
                data={"rows": [row.model_dump(mode="json") for row in method_table]},
            )
        )
        await self.stream_service.publish(
            StreamEvent(
                session_id=snapshot.session_id,
                event_type=StreamEventType.INTERRUPT,
                phase=PhaseType.DISCOVERY,
                checkpoint=CheckpointType.SHORTLIST_REVIEW,
                message=snapshot.pending_interrupt.message,
                data=snapshot.pending_interrupt.model_dump(mode="json"),
            )
        )
        return snapshot

    @staticmethod
    def _ensure_shortlist_review_ready(snapshot: SessionSnapshot) -> None:
        if snapshot.current_checkpoint != CheckpointType.SHORTLIST_REVIEW:
            raise SessionTransitionError("Session is not waiting at shortlist review.")

    @staticmethod
    def _resolve_approved_paper_details(
        snapshot: SessionSnapshot,
        paper_ids: list[str],
    ) -> list[CuratedPaper]:
        shortlist_map = {paper.paper_id: paper for paper in snapshot.latest_shortlist}
        approved_map = {paper.paper_id: paper for paper in snapshot.approved_paper_details}
        resolved: list[CuratedPaper] = []
        for paper_id in paper_ids:
            paper = shortlist_map.get(paper_id) or approved_map.get(paper_id)
            if paper is not None:
                resolved.append(paper)
        return resolved

    def _resolve_selected_analysis_papers(self, snapshot: SessionSnapshot) -> list[CuratedPaper]:
        selected_ids = snapshot.analysis_summary.selected_paper_ids or snapshot.approved_papers
        return self._resolve_approved_paper_details(snapshot, selected_ids)

    def _reset_survey_state(self, snapshot: SessionSnapshot) -> None:
        snapshot.survey_brief = None
        snapshot.theme_clusters = []
        snapshot.survey_sections = []
        snapshot.final_survey_document = None
        snapshot.survey_summary = SurveySummary()

    async def _mark_survey_failure(
        self,
        snapshot: SessionSnapshot,
        *,
        message: str,
        error: Exception,
    ) -> None:
        snapshot.status = SessionStatus.ERROR
        snapshot.current_phase = PhaseType.SURVEY
        snapshot.current_checkpoint = CheckpointType.NONE
        snapshot.pending_interrupt = None
        snapshot.allowed_actions = []
        snapshot.artifact_status[ArtifactType.SURVEY_SECTION.value] = ArtifactStatusValue.FAILED
        snapshot.artifact_status[ArtifactType.FINAL_SURVEY_MARKDOWN.value] = ArtifactStatusValue.FAILED
        snapshot.last_updated_at = utc_now()
        await self._persist_snapshot(snapshot)
        await self.stream_service.publish(
            StreamEvent(
                session_id=snapshot.session_id,
                event_type=StreamEventType.ERROR,
                phase=PhaseType.SURVEY,
                message=message,
                data={"error": str(error)},
            )
        )

    async def _draft_and_review_section(
        self,
        *,
        session_id: str,
        snapshot: SessionSnapshot,
        cluster,
        papers: list[CuratedPaper],
        revision_feedback: str | None,
        revision_count: int,
    ):
        current_feedback = revision_feedback
        current_revision_count = revision_count
        while True:
            section = await self.survey_service.draft_section(
                cluster=cluster,
                papers=papers,
                analyses=snapshot.paper_analyses,
                comparison_rows=snapshot.method_comparison_table,
                brief=snapshot.survey_brief or await self.survey_service.synthesize_brief(snapshot),
                citation_graph=snapshot.citation_graph,
                revision_feedback=current_feedback,
                revision_count=current_revision_count,
            )
            review = await self.survey_service.review_section(
                section=section,
                cluster=cluster,
                brief=snapshot.survey_brief or await self.survey_service.synthesize_brief(snapshot),
            )
            if review.verdict.value == "ACCEPT" or current_revision_count >= 2:
                section.accepted = True
                await self.stream_service.publish(
                    StreamEvent(
                        session_id=session_id,
                        event_type=StreamEventType.ARTIFACT_READY,
                        phase=PhaseType.SURVEY,
                        artifact_type=ArtifactType.SURVEY_SECTION,
                        message=f"Survey section ready: {section.title}.",
                        data=section.model_dump(mode="json"),
                    )
                )
                return section
            await self.stream_service.publish(
                StreamEvent(
                    session_id=session_id,
                    event_type=StreamEventType.NODE_UPDATE,
                    phase=PhaseType.SURVEY,
                    message=f"Section reviewer requested a revision for {section.title}.",
                    data={"section_id": section.section_id, "feedback": review.feedback},
                )
            )
            current_feedback = review.feedback
            current_revision_count += 1
