from __future__ import annotations

from datetime import timedelta
import re
from uuid import uuid4

from graph.discovery import interpret_topic
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
from models.survey import SurveySummary
from persistence.checkpoints import GraphCheckpointStore
from persistence.session_store import SessionStore
from services.analysis_service import AnalysisService
from services.artifact_service import ArtifactService
from services.discovery_service import DiscoveryService
from services.stream_service import StreamService


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
        discovery_service: DiscoveryService,
        stream_service: StreamService,
        ttl_days: int,
        analysis_paper_cap: int,
    ) -> None:
        self.session_store = session_store
        self.artifact_service = artifact_service
        self.analysis_service = analysis_service
        self.discovery_service = discovery_service
        self.stream_service = stream_service
        self.ttl_days = ttl_days
        self.analysis_paper_cap = analysis_paper_cap
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
        snapshot.analysis_summary = AnalysisSummary()
        snapshot.artifact_status[ArtifactType.SEARCH_INTERPRETATION.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.SHORTLIST.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.PRELIMINARY_METHOD_TABLE.value] = ArtifactStatusValue.PENDING
        snapshot.artifact_status[ArtifactType.PAPER_ANALYSIS.value] = ArtifactStatusValue.PENDING
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

        interpretation = interpret_topic(snapshot.topic)
        snapshot.search_interpretation = interpretation
        snapshot.status = SessionStatus.WAITING_FOR_INPUT
        snapshot.current_checkpoint = CheckpointType.TOPIC_CONFIRMATION
        snapshot.pending_interrupt = PendingInterrupt(
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

        return await self._rerun_discovery_shortlist(
            snapshot,
            reason_message="Curated shortlist is ready for review.",
        )

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
        snapshot.approved_paper_details = self._resolve_approved_paper_details(snapshot, deduped_ids)
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
        snapshot.paper_analyses = []
        snapshot.artifact_status[ArtifactType.PAPER_ANALYSIS.value] = ArtifactStatusValue.PENDING
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

        degraded_ids: list[str] = []
        analyses = []
        try:
            for paper in selected_papers:
                analysis = await self.analysis_service.analyze_paper(paper)
                analyses.append(analysis)
                if analysis.analysis_quality.value != "full_text":
                    degraded_ids.append(analysis.paper_id)
                await self.stream_service.publish(
                    StreamEvent(
                        session_id=session_id,
                        event_type=StreamEventType.ARTIFACT_READY,
                        phase=PhaseType.ANALYSIS,
                        artifact_type=ArtifactType.PAPER_ANALYSIS,
                        message=f"Analysis ready for {paper.title}.",
                        data=analysis.model_dump(mode="json"),
                    )
                )
        except Exception as exc:
            snapshot.status = SessionStatus.ERROR
            snapshot.current_checkpoint = CheckpointType.NONE
            snapshot.pending_interrupt = None
            snapshot.allowed_actions = []
            snapshot.analysis_summary.completed = False
            snapshot.artifact_status[ArtifactType.PAPER_ANALYSIS.value] = ArtifactStatusValue.FAILED
            snapshot.last_updated_at = utc_now()
            await self._persist_snapshot(snapshot)
            await self.stream_service.publish(
                StreamEvent(
                    session_id=session_id,
                    event_type=StreamEventType.ERROR,
                    phase=PhaseType.ANALYSIS,
                    message="Paper analysis failed.",
                    data={"error": str(exc), "selected_paper_ids": selected_ids},
                )
            )
            raise SessionExecutionError("Paper analysis failed.") from exc

        snapshot.paper_analyses = analyses
        snapshot.status = SessionStatus.IDLE
        snapshot.current_phase = PhaseType.ANALYSIS
        snapshot.current_checkpoint = CheckpointType.NONE
        snapshot.pending_interrupt = None
        snapshot.allowed_actions = []
        snapshot.analysis_summary.selected_paper_ids = selected_ids
        snapshot.analysis_summary.completed = True
        snapshot.analysis_summary.degraded_paper_ids = degraded_ids
        snapshot.artifact_status[ArtifactType.PAPER_ANALYSIS.value] = ArtifactStatusValue.READY
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
                event_type=StreamEventType.PHASE_COMPLETED,
                phase=PhaseType.ANALYSIS,
                message="Per-paper analysis completed.",
                data={
                    "selected_paper_ids": selected_ids,
                    "degraded_paper_ids": degraded_ids,
                },
            )
        )
        return snapshot

    async def apply_discovery_nudge(self, session_id: str, text: str) -> SessionSnapshot | None:
        snapshot = await self.session_store.get_session_snapshot(session_id)
        if snapshot is None:
            return None
        self._ensure_shortlist_review_ready(snapshot)
        if snapshot.search_interpretation is None or snapshot.topic is None:
            raise SessionTransitionError("Session is missing discovery context for rerunning the shortlist.")

        delta = self._parse_steering_nudge(text)
        snapshot.steering_preferences = self._merge_steering_preferences(
            snapshot.steering_preferences,
            delta,
        )
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
        return await self._rerun_discovery_shortlist(
            snapshot,
            reason_message="Updated shortlist is ready after applying the steering nudge.",
        )

    async def _persist_snapshot(self, snapshot: SessionSnapshot) -> None:
        expires_at = snapshot.last_updated_at + timedelta(days=self.ttl_days)
        await self.session_store.update_session_snapshot(snapshot, expires_at=expires_at)

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
    def _merge_steering_preferences(
        current: SteeringPreferences,
        delta: SteeringPreferences,
    ) -> SteeringPreferences:
        def merge_values(existing: list[str], new_values: list[str]) -> list[str]:
            merged: list[str] = []
            seen: set[str] = set()
            for value in [*existing, *new_values]:
                normalized = " ".join(value.split()).strip().lower()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                merged.append(normalized)
            return merged

        return SteeringPreferences(
            include=merge_values(current.include, delta.include),
            exclude=merge_values(current.exclude, delta.exclude),
            emphasize=merge_values(current.emphasize, delta.emphasize),
        )

    @staticmethod
    def _parse_steering_nudge(text: str) -> SteeringPreferences:
        normalized = " ".join(text.split()).strip()
        if not normalized:
            raise SessionTransitionError("Nudge text cannot be empty.")

        include = SessionService._extract_nudge_terms(normalized, ("include", "prefer", "look for"))
        exclude = SessionService._extract_nudge_terms(normalized, ("exclude", "avoid", "without", "skip"))
        emphasize = SessionService._extract_nudge_terms(normalized, ("focus on", "emphasize", "prioritize"))

        if not include and not exclude and not emphasize:
            emphasize = [normalized.lower()]

        return SteeringPreferences(
            include=include,
            exclude=exclude,
            emphasize=emphasize,
        )

    @staticmethod
    def _extract_nudge_terms(text: str, prefixes: tuple[str, ...]) -> list[str]:
        lowered = text.lower()
        values: list[str] = []
        for prefix in prefixes:
            pattern = rf"{re.escape(prefix)}\s+([^.;]+)"
            for match in re.finditer(pattern, lowered):
                values.extend(SessionService._split_terms(match.group(1)))
        return values

    @staticmethod
    def _split_terms(text: str) -> list[str]:
        parts = re.split(r",| and | or ", text)
        values: list[str] = []
        for part in parts:
            cleaned = re.sub(r"\b(the|a|an|papers?|work|methods?)\b", "", part).strip(" .")
            if cleaned:
                values.append(cleaned)
        return values

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
