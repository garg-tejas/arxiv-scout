from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from graph.discovery import interpret_topic
from models.analysis import AnalysisSummary
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
from services.stream_service import StreamService


class SessionTransitionError(Exception):
    """Raised when a requested session transition is not allowed."""


class SessionService:
    def __init__(
        self,
        *,
        session_store: SessionStore,
        artifact_service: ArtifactService,
        stream_service: StreamService,
        ttl_days: int,
    ) -> None:
        self.session_store = session_store
        self.artifact_service = artifact_service
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

        snapshot.status = SessionStatus.IDLE
        snapshot.current_phase = PhaseType.DISCOVERY
        snapshot.current_checkpoint = CheckpointType.NONE
        snapshot.pending_interrupt = None
        snapshot.allowed_actions = []
        snapshot.last_updated_at = utc_now()

        await self._persist_snapshot(snapshot)
        await self.checkpoints.save(
            session_id=session_id,
            phase=PhaseType.DISCOVERY.value,
            checkpoint_key="topic_confirmed",
            state=snapshot.model_dump(mode="json"),
            saved_at=snapshot.last_updated_at,
        )
        await self.stream_service.publish(
            StreamEvent(
                session_id=session_id,
                event_type=StreamEventType.NODE_UPDATE,
                phase=PhaseType.DISCOVERY,
                message="Topic interpretation confirmed. Discovery fetch is ready for the next checkpoint.",
                data={"topic": snapshot.topic},
            )
        )
        return snapshot

    async def _persist_snapshot(self, snapshot: SessionSnapshot) -> None:
        expires_at = snapshot.last_updated_at + timedelta(days=self.ttl_days)
        await self.session_store.update_session_snapshot(snapshot, expires_at=expires_at)
