"""Low-latency gesture following for the internal operator console.

The camera remains an untrusted perception source. InternS2 classifies each
frame on the server, while this coordinator owns the direct-control lease and
maps a recognized direction to the same short, interruptible motion channel as
the manual panel. There is deliberately no browser confirmation in this mode.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from threading import RLock
import time
from typing import Any
from uuid import uuid4

from ..manual_control import ManualInput
from .models import (
    GestureControlResponse,
    GestureDecision,
    GestureFrameRequest,
    GestureFrameResponse,
    GestureName,
    GestureResetResponse,
    VoiceActivityResponse,
)
from .service import (
    GestureRecognitionError,
    GestureSettings,
    InternS2GestureRecognizer,
    gesture_to_command,
)


_DIRECTIONS: dict[GestureName, tuple[int, int]] = {
    GestureName.FORWARD: (0, 1),
    GestureName.BACKWARD: (0, -1),
    GestureName.LEFT: (1, 1),
    GestureName.RIGHT: (1, -1),
    GestureName.UP: (2, 1),
    GestureName.DOWN: (2, -1),
}


@dataclass
class _ControlState:
    token: str | None = None
    sequence: int = 0
    active_gesture: GestureName | None = None
    safety_latch: GestureName | None = None
    voice_active: bool = False
    operation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class GestureCoordinator:
    def __init__(
        self,
        runtime: Any,
        *,
        recognizer: InternS2GestureRecognizer,
        settings: GestureSettings | None = None,
    ) -> None:
        self.runtime = runtime
        self.recognizer = recognizer
        self.settings = settings or GestureSettings.from_env()
        self._lock = RLock()
        self._states: dict[str, _ControlState] = {}

    def _state(self, session_id: str) -> _ControlState:
        with self._lock:
            return self._states.setdefault(session_id, _ControlState())

    def _response(self, session_id: str) -> GestureControlResponse:
        state = self._state(session_id)
        manual = self.runtime.manual.status(session_id)
        return GestureControlResponse(
            active=state.token is not None,
            mode=manual["mode"],
            moving=state.active_gesture is not None and bool(manual["moving"]),
            gesture=state.active_gesture,
            reason=str(manual["reason"]),
        )

    def status(self, session_id: str) -> GestureControlResponse:
        self.runtime.get_session(session_id)
        return self._response(session_id)

    async def acquire(self, session_id: str) -> GestureControlResponse:
        self.runtime.get_session(session_id)
        state = self._state(session_id)
        async with state.operation_lock:
            if state.token is not None:
                return self._response(session_id)
            lease = await self.runtime.manual.acquire(session_id, owner="gesture")
            state.token = lease["token"]
            state.sequence = 0
            state.active_gesture = None
            state.safety_latch = None
        return self._response(session_id)

    async def heartbeat(self, session_id: str) -> GestureControlResponse:
        state = self._state(session_id)
        token = state.token
        if token is None:
            return self._response(session_id)
        try:
            await self.runtime.manual.heartbeat(session_id, token)
        except Exception:
            lease = self.runtime.manual.lease
            if lease is None or lease.token != token:
                with self._lock:
                    state.token = None
                    state.active_gesture = None
            raise
        return self._response(session_id)

    async def _manual_input(
        self,
        session_id: str,
        state: _ControlState,
        *,
        gesture: GestureName | None,
    ) -> None:
        token = state.token
        if token is None:
            raise RuntimeError("手势控制尚未接管机械臂")
        state.sequence += 1
        if gesture is None:
            command = ManualInput(token=token, sequence=state.sequence)
        else:
            axis, direction = _DIRECTIONS[gesture]
            command = ManualInput(
                token=token,
                sequence=state.sequence,
                kind="translation",
                axis=axis,
                direction=direction,
                amount=self.runtime.manual.default_translation_step(session_id),
                speed_scale=1.0,
                continuous=True,
            )
        await self.runtime.manual.input(session_id, command)

    async def _pause(self, session_id: str, state: _ControlState) -> bool:
        if state.token is None or state.active_gesture is None:
            state.active_gesture = None
            return False
        await self._manual_input(session_id, state, gesture=None)
        state.active_gesture = None
        return True

    async def release(self, session_id: str) -> GestureResetResponse:
        self.runtime.get_session(session_id)
        state = self._state(session_id)
        async with state.operation_lock:
            token = state.token
            if token is not None:
                await self._pause(session_id, state)
                await self.runtime.manual.release(session_id, token)
                state.token = None
                state.sequence = 0
                state.active_gesture = None
                state.safety_latch = None
                state.voice_active = False
        return GestureResetResponse()

    def set_voice_activity(self, session_id: str, active: bool) -> VoiceActivityResponse:
        # Backwards-compatible endpoint. The explicitly opened internal gesture
        # drawer owns the input lease until it is closed.
        self.runtime.get_session(session_id)
        self._state(session_id).voice_active = bool(active)
        return VoiceActivityResponse(
            active=bool(active),
            observed_at_ms=time.time_ns() // 1_000_000,
        )

    async def submit_frame(
        self,
        session_id: str,
        request: GestureFrameRequest,
    ) -> GestureFrameResponse:
        self.runtime.get_session(session_id)
        state = self._state(session_id)
        token_before = state.token
        if token_before is None:
            raise RuntimeError("请先启动手势控制")

        try:
            recognition = await asyncio.to_thread(
                self.recognizer.recognize,
                request.image_data_url,
            )
        except Exception:
            # Classification failure is recognition loss: stop the last
            # direction before surfacing the error to the browser.
            async with state.operation_lock:
                if state.token == token_before:
                    await self._pause(session_id, state)
            raise

        async with state.operation_lock:
            if state.token != token_before:
                raise RuntimeError("手势控制已退出，本帧已丢弃")

            gesture = recognition.gesture
            safety = gesture in {GestureName.STOP, GestureName.ESTOP}
            threshold = (
                self.settings.safety_minimum_confidence
                if safety
                else self.settings.minimum_confidence
            )
            recognized = (
                recognition.hand_detected
                and recognition.confidence >= threshold
                and gesture not in {GestureName.NONE, GestureName.UNCERTAIN}
            )

            if not recognized:
                paused = await self._pause(session_id, state)
                state.safety_latch = None
                return GestureFrameResponse(
                    recognition=recognition,
                    decision=GestureDecision.PAUSED,
                    message=(
                        "未识别到有效手势，机械臂已暂停。"
                        if paused
                        else "未识别到有效手势，机械臂保持暂停。"
                    ),
                )

            if gesture in {GestureName.STOP, GestureName.ESTOP}:
                if state.safety_latch == gesture:
                    return GestureFrameResponse(
                        recognition=recognition,
                        decision=GestureDecision.SUPPRESSED_LATCHED,
                        message="安全手势仍在保持；机械臂保持停止。",
                    )
                # Do not put a normal direct-control stop in front of an
                # emergency stop.  WebRuntime.stop() interrupts the shared
                # manual lease itself, then delivers the requested stop level.
                snapshot = await self.runtime.stop(
                    session_id,
                    emergency=gesture == GestureName.ESTOP,
                )
                state.active_gesture = None
                state.safety_latch = gesture
                return GestureFrameResponse(
                    recognition=recognition,
                    decision=(
                        GestureDecision.SAFETY_ESTOP
                        if gesture == GestureName.ESTOP
                        else GestureDecision.SAFETY_STOP
                    ),
                    message=(
                        "识别到张开手掌，已立即执行急停。"
                        if gesture == GestureName.ESTOP
                        else "识别到停止手势，已立即停止机械臂。"
                    ),
                    session_snapshot=snapshot.model_dump(mode="json"),
                )

            state.safety_latch = None
            if gesture not in _DIRECTIONS:
                paused = await self._pause(session_id, state)
                return GestureFrameResponse(
                    recognition=recognition,
                    decision=GestureDecision.PAUSED,
                    message=("该手势没有运动映射，机械臂已暂停。" if paused else "机械臂保持暂停。"),
                )

            if state.active_gesture not in {None, gesture}:
                await self._pause(session_id, state)
            await self._manual_input(session_id, state, gesture=gesture)
            state.active_gesture = gesture
            mapped = gesture_to_command(
                gesture,
                distance_mm=self.runtime.manual.default_translation_step(session_id),
                command_id=f"gesture-{uuid4().hex}",
            )
            return GestureFrameResponse(
                recognition=recognition,
                decision=GestureDecision.ACCEPTED,
                message=f"已识别 {gesture.value}，机械臂正在同步随动；无需二次确认。",
                mapped_command=(mapped.model_dump(mode="json") if mapped is not None else None),
            )


def build_gesture_coordinator(runtime: Any) -> GestureCoordinator:
    parser = getattr(runtime, "parser", None)
    client = getattr(parser, "client", None)
    model = getattr(parser, "model", None)
    if client is None or not isinstance(model, str) or not model:
        raise GestureRecognitionError(
            "gesture recognition requires an InternS2Agent-backed WebRuntime"
        )
    recognizer = InternS2GestureRecognizer(runtime.settings, client, model=model)
    return GestureCoordinator(
        runtime,
        recognizer=recognizer,
        settings=GestureSettings.from_env(),
    )
