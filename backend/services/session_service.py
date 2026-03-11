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
from models.session import PendingInterrupt, SessionSnapshot, utc_now
from models.survey import SurveySummary
from persistence.checkpoints import GraphCheckpointStore
from persistence.session_store import SessionStore
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
        discovery_service: DiscoveryService,
        stream_service: StreamService,
        ttl_days: int,
    ) -> None:
        self.session_store = session_store
        self.artifact_service = artifact_service
        self.discovery_service = discovery_service
        self.stream_service = stream_service
        self.ttl_days = ttl_days
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
            ],
        )
        snapshot.allowed_actions = [
            AllowedAction.UPDATE_APPROVED_PAPERS,
            AllowedAction.NUDGE_DISCOVERY,
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
