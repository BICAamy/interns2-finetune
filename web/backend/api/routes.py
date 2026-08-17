"""Session and command HTTP endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request, status

from ..models import HealthResponse, SessionSnapshot, TextCommandRequest
from ..runtime import WebRuntime


router = APIRouter()


def _runtime(request: Request) -> WebRuntime:
    return request.app.state.runtime


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    return _runtime(request).health()


@router.post(
    "/api/sessions",
    response_model=SessionSnapshot,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(request: Request) -> SessionSnapshot:
    return await _runtime(request).create_session()


@router.get("/api/sessions/{session_id}", response_model=SessionSnapshot)
def get_session(session_id: str, request: Request) -> SessionSnapshot:
    return _runtime(request).get_session(session_id)


@router.get("/api/sessions/{session_id}/state", response_model=SessionSnapshot)
def get_session_state(session_id: str, request: Request) -> SessionSnapshot:
    return _runtime(request).get_session(session_id)


@router.post(
    "/api/sessions/{session_id}/commands/text",
    response_model=SessionSnapshot,
)
async def submit_text(
    session_id: str,
    command: TextCommandRequest,
    request: Request,
) -> SessionSnapshot:
    return await _runtime(request).submit_text(session_id, command)


@router.post(
    "/api/sessions/{session_id}/confirm",
    response_model=SessionSnapshot,
    status_code=status.HTTP_202_ACCEPTED,
)
async def confirm(session_id: str, request: Request) -> SessionSnapshot:
    return await _runtime(request).confirm(session_id)


@router.post("/api/sessions/{session_id}/cancel", response_model=SessionSnapshot)
async def cancel(session_id: str, request: Request) -> SessionSnapshot:
    return await _runtime(request).cancel(session_id)


@router.post("/api/sessions/{session_id}/stop", response_model=SessionSnapshot)
async def stop(session_id: str, request: Request) -> SessionSnapshot:
    return await _runtime(request).stop(session_id, emergency=False)


@router.post("/api/sessions/{session_id}/estop", response_model=SessionSnapshot)
async def estop(session_id: str, request: Request) -> SessionSnapshot:
    return await _runtime(request).stop(session_id, emergency=True)


@router.post(
    "/api/sessions/{session_id}/reset-estop",
    response_model=SessionSnapshot,
)
async def reset_estop(session_id: str, request: Request) -> SessionSnapshot:
    return await _runtime(request).reset_estop(session_id)
