"""HTTP routes for Step 14 browser-camera gestures."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .coordinator import GestureCoordinator, build_gesture_coordinator
from .models import (
    GestureFrameRequest,
    GestureFrameResponse,
    GestureResetResponse,
    VoiceActivityRequest,
    VoiceActivityResponse,
)
from .service import GestureRecognitionError


router = APIRouter()


def _coordinator(request: Request) -> GestureCoordinator:
    selected = getattr(request.app.state, "gesture_coordinator", None)
    if selected is None:
        selected = build_gesture_coordinator(request.app.state.runtime)
        request.app.state.gesture_coordinator = selected
    return selected


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
def reset_gesture_state(
    session_id: str,
    request: Request,
) -> GestureResetResponse:
    return _coordinator(request).reset(session_id)
