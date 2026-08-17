"""Session and command HTTP endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from surgical_contracts import (
    SimulationCameraControlRequest,
    SimulationCameraState,
)

from ..models import (
    HealthResponse,
    SessionSnapshot,
    SimulationTelemetryView,
    TextCommandRequest,
)
from ..runtime import WebRuntime
from ..simulation_proxy import SimulationProxyError


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


@router.get(
    "/api/sessions/{session_id}/simulation/telemetry",
    response_model=SimulationTelemetryView,
)
async def simulation_telemetry(session_id: str, request: Request):
    runtime = _runtime(request)
    try:
        return await asyncio.to_thread(
            runtime.get_simulation_telemetry,
            session_id,
        )
    except SimulationProxyError as error:
        return JSONResponse(
            status_code=502,
            content=runtime.simulation_telemetry_error(
                session_id,
                error,
            ).model_dump(mode="json"),
        )


@router.get(
    "/api/sessions/{session_id}/simulation/camera",
    response_model=SimulationCameraState,
)
async def simulation_camera_state(
    session_id: str,
    request: Request,
) -> SimulationCameraState:
    try:
        return await asyncio.to_thread(
            _runtime(request).get_simulation_camera,
            session_id,
        )
    except SimulationProxyError as error:
        return JSONResponse(
            status_code=502,
            content={
                "code": "SIMULATION_CAMERA_UNAVAILABLE",
                "message": str(error),
                "details": {},
            },
        )


@router.put(
    "/api/sessions/{session_id}/simulation/camera",
    response_model=SimulationCameraState,
)
async def control_simulation_camera(
    session_id: str,
    camera: SimulationCameraControlRequest,
    request: Request,
) -> SimulationCameraState:
    try:
        return await asyncio.to_thread(
            _runtime(request).control_simulation_camera,
            session_id,
            camera,
        )
    except SimulationProxyError as error:
        return JSONResponse(
            status_code=502,
            content={
                "code": "SIMULATION_CAMERA_UNAVAILABLE",
                "message": str(error),
                "details": {},
            },
        )


@router.get("/api/sessions/{session_id}/simulation/stream.mjpeg")
async def simulation_video(session_id: str, request: Request):
    runtime = _runtime(request)
    try:
        upstream = await runtime.open_simulation_video(session_id)
    except SimulationProxyError as error:
        return JSONResponse(
            status_code=502,
            content={
                "code": "SIMULATION_VIDEO_UNAVAILABLE",
                "message": str(error),
                "details": {},
            },
        )

    async def stream_body():
        try:
            async for chunk in upstream.iter_bytes():
                yield chunk
        finally:
            await upstream.aclose()

    return StreamingResponse(
        stream_body(),
        media_type=upstream.content_type,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )
