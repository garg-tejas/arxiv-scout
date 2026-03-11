from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from models.analysis import AnalysisSummary
from models.enums import CheckpointType, PhaseType, SessionStatus, StreamEventType
from models.events import StreamEvent
from models.session import SessionSnapshot, utc_now
from models.survey import SurveySummary
from persistence.checkpoints import GraphCheckpointStore
from persistence.session_store import SessionStore
from services.artifact_service import ArtifactService
from services.stream_service import StreamService


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
