from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from fastapi.responses import StreamingResponse

from app.dependencies import ServiceContainer, get_services
from models.discovery import ConfirmTopicRequest, StartTopicRequest
from models.events import CreateSessionResponse
from models.session import SessionSnapshot
from services.session_service import SessionTransitionError

router = APIRouter(tags=["sessions"])


@router.post(
    "/sessions",
    response_model=CreateSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    services: ServiceContainer = Depends(get_services),
) -> CreateSessionResponse:
    snapshot = await services.session_service.create_session()
    return CreateSessionResponse(session_id=snapshot.session_id)


@router.get("/sessions/{session_id}", response_model=SessionSnapshot)
async def get_session(
    session_id: str,
    services: ServiceContainer = Depends(get_services),
) -> SessionSnapshot:
    snapshot = await services.session_service.get_session_snapshot(session_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return snapshot


@router.get("/sessions/{session_id}/stream")
async def stream_session(
    session_id: str,
    response: Response,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    services: ServiceContainer = Depends(get_services),
) -> StreamingResponse:
    snapshot = await services.session_service.get_session_snapshot(session_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    parsed_last_event_id: int | None = None
    if last_event_id:
        try:
            parsed_last_event_id = int(last_event_id)
        except ValueError:
            parsed_last_event_id = None

    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    response.headers["X-Accel-Buffering"] = "no"

    return StreamingResponse(
        services.stream_service.stream(session_id, parsed_last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sessions/{session_id}/topic", response_model=SessionSnapshot)
async def start_topic_interpretation(
    session_id: str,
    payload: StartTopicRequest,
    services: ServiceContainer = Depends(get_services),
) -> SessionSnapshot:
    try:
        snapshot = await services.session_service.start_topic_interpretation(
            session_id,
            payload.topic,
        )
    except SessionTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return snapshot


@router.post("/sessions/{session_id}/discovery/confirm", response_model=SessionSnapshot)
async def confirm_topic_interpretation(
    session_id: str,
    payload: ConfirmTopicRequest,
    services: ServiceContainer = Depends(get_services),
) -> SessionSnapshot:
    if not payload.confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This endpoint only accepts positive confirmation.",
        )

    try:
        snapshot = await services.session_service.confirm_topic_interpretation(session_id)
    except SessionTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return snapshot
