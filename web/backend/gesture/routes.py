"""HTTP routes for Step 14 browser-camera gestures."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from web_inside.backend.gesture.coordinator import (
    GestureCoordinator,
    build_gesture_coordinator,
)
from web_inside.backend.gesture.models import (
    GestureControlResponse,
    GestureFrameRequest,
    GestureFrameResponse,
    GestureResetResponse,
    VoiceActivityRequest,
    VoiceActivityResponse,
)
from web_inside.backend.gesture.service import GestureRecognitionError


router = APIRouter()


def _coordinator(request: Request) -> GestureCoordinator:
    selected = getattr(request.app.state, "gesture_coordinator", None)
    if selected is None:
        selected = build_gesture_coordinator(request.app.state.runtime)
        request.app.state.gesture_coordinator = selected
    return selected


@router.get(
    "/api/sessions/{session_id}/gesture",
    response_model=GestureControlResponse,
)
def gesture_status(session_id: str, request: Request) -> GestureControlResponse:
    return _coordinator(request).status(session_id)


@router.post(
    "/api/sessions/{session_id}/gesture/acquire",
    response_model=GestureControlResponse,
)
async def acquire_gesture_control(
    session_id: str,
    request: Request,
) -> GestureControlResponse:
    return await _coordinator(request).acquire(session_id)


@router.post(
    "/api/sessions/{session_id}/gesture/heartbeat",
    response_model=GestureControlResponse,
)
async def heartbeat_gesture_control(
    session_id: str,
    request: Request,
) -> GestureControlResponse:
    return await _coordinator(request).heartbeat(session_id)


@router.post(
    "/api/sessions/{session_id}/commands/gesture",
    response_model=GestureFrameResponse,
)
async def submit_gesture_frame(
    session_id: str,
    frame: GestureFrameRequest,
    request: Request,
):
    try:
        return await _coordinator(request).submit_frame(session_id, frame)
    except GestureRecognitionError as error:
        return JSONResponse(
            status_code=502,
            content={
                "code": "GESTURE_MODEL_UNAVAILABLE",
                "message": str(error),
                "details": {},
            },
        )
    except RuntimeError as error:
        return JSONResponse(
            status_code=409,
            content={
                "code": "GESTURE_CONTROL_INACTIVE",
                "message": str(error),
                "details": {},
            },
        )


@router.put(
    "/api/sessions/{session_id}/gesture/voice-activity",
    response_model=VoiceActivityResponse,
)
def set_voice_activity(
    session_id: str,
    activity: VoiceActivityRequest,
    request: Request,
) -> VoiceActivityResponse:
    return _coordinator(request).set_voice_activity(session_id, activity.active)


@router.post(
    "/api/sessions/{session_id}/gesture/reset",
    response_model=GestureResetResponse,
)
async def reset_gesture_state(
    session_id: str,
    request: Request,
) -> GestureResetResponse:
    return await _coordinator(request).release(session_id)
