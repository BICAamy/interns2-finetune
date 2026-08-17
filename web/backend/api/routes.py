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
from ..asr import ASRError, ASRStatus
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


@router.get("/api/asr/status", response_model=ASRStatus)
def asr_status(request: Request) -> ASRStatus:
    return _runtime(request).asr_status()


@router.post(
    "/api/sessions/{session_id}/commands/speech",
    response_model=SessionSnapshot,
)
async def submit_speech(
    session_id: str,
    request: Request,
):
    runtime = _runtime(request)
    runtime.get_session(session_id)
    try:
        duration_ms = _audio_duration_ms(request)
        audio = await _read_bounded_audio(
            request,
            runtime.asr.settings.max_audio_bytes,
        )
        return await runtime.submit_speech(
            session_id,
            audio,
            content_type=request.headers.get("content-type", ""),
            duration_ms=duration_ms,
        )
    except ASRError as error:
        return JSONResponse(
            status_code=error.status_code,
            content=error.as_dict(),
        )


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


def _audio_duration_ms(request: Request) -> int:
    value = request.headers.get("x-audio-duration-ms", "").strip()
    try:
        duration_ms = int(value)
    except ValueError as error:
        raise ASRError(
            "ASR_DURATION_REQUIRED",
            "语音请求缺少有效的 X-Audio-Duration-Ms。",
            status_code=400,
        ) from error
    if duration_ms <= 0:
        raise ASRError(
            "ASR_DURATION_REQUIRED",
            "语音时长必须大于零。",
            status_code=400,
        )
    return duration_ms


async def _read_bounded_audio(request: Request, maximum: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > maximum:
                raise ASRError(
                    "ASR_AUDIO_TOO_LARGE",
                    "录音文件超过大小限制。",
                    status_code=413,
                    details={"max_audio_bytes": maximum},
                )
        except ValueError:
            pass
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > maximum:
            raise ASRError(
                "ASR_AUDIO_TOO_LARGE",
                "录音文件超过大小限制。",
                status_code=413,
                details={"max_audio_bytes": maximum},
            )
        chunks.append(chunk)
    return b"".join(chunks)
