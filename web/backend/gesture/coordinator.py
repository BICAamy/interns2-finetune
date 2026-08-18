"""Per-session Step 14 gesture arbitration.

The browser is an untrusted perception source: it sends raw camera frames and
voice-activity state, while agent-web owns VLM classification, priority,
cooldown, latching, and conversion to a ParsedCommand.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from threading import RLock
import time
from typing import Any
from uuid import uuid4

from surgical_contracts import CommandIntent

from ..models import InputSource, SessionStatus
from .models import (
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


_BUSY_STATUSES = {
    SessionStatus.PARSING,
    SessionStatus.AWAITING_CONFIRMATION,
    SessionStatus.EXECUTING,
    SessionStatus.MOVING_TO_ENTRY,
    SessionStatus.VERIFYING_ENTRY,
    SessionStatus.MOVING_RELATIVE,
    SessionStatus.PLANNING,
    SessionStatus.STOPPING,
}


@dataclass
class _ArbitrationState:
    voice_active: bool = False
    last_voice_activity_s: float = -1.0
    cooldown_until_s: float = 0.0
    latched_gesture: GestureName | None = None


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
        self.settings = settings or GestureSettings()
        self._lock = RLock()
        self._states: dict[str, _ArbitrationState] = {}

    def _state(self, session_id: str) -> _ArbitrationState:
        with self._lock:
            return self._states.setdefault(session_id, _ArbitrationState())

    def set_voice_activity(self, session_id: str, active: bool) -> VoiceActivityResponse:
        self.runtime.get_session(session_id)
        now = time.monotonic()
        state = self._state(session_id)
        with self._lock:
            state.voice_active = bool(active)
            # Record both the start and end edge. After speech/ASR finishes we
            # preserve the conflict window so a held gesture cannot "catch up".
            state.last_voice_activity_s = now
        return VoiceActivityResponse(
            active=bool(active),
            observed_at_ms=time.time_ns() // 1_000_000,
        )

    def reset(self, session_id: str) -> GestureResetResponse:
        self.runtime.get_session(session_id)
        with self._lock:
            self._states[session_id] = _ArbitrationState()
        return GestureResetResponse()

    def _voice_conflict(self, state: _ArbitrationState, now: float) -> bool:
        return state.voice_active or (
            state.last_voice_activity_s >= 0
            and now - state.last_voice_activity_s
            <= self.settings.voice_conflict_window_s
        )

    def _latch(self, state: _ArbitrationState, gesture: GestureName) -> None:
        state.latched_gesture = gesture
        state.cooldown_until_s = time.monotonic() + self.settings.cooldown_s

    async def submit_frame(
        self,
        session_id: str,
        request: GestureFrameRequest,
    ) -> GestureFrameResponse:
        # Do not compare browser Date.now() with server wall-clock time: the
        # browser and remote laboratory server are separate machines and may
        # legitimately have clock skew. Frames are never queued; hidden pages
        # stop sampling and reset the server latch instead.
        session = self.runtime.get_session(session_id)
        recognition = await asyncio.to_thread(
            self.recognizer.recognize,
            request.image_data_url,
        )
        gesture = recognition.gesture
        state = self._state(session_id)
        now = time.monotonic()

        # A no-hand/uncertain frame is the explicit release condition for the
        # one-shot latch. This prevents a held gesture from repeatedly moving.
        if gesture in {GestureName.NONE, GestureName.UNCERTAIN}:
            with self._lock:
                state.latched_gesture = None
            return GestureFrameResponse(
                recognition=recognition,
                decision=GestureDecision.IGNORED,
                message=(
                    "未检测到协议手势。" if gesture == GestureName.NONE
                    else "手势不明确，未产生任何命令。"
                ),
            )

        safety = gesture in {GestureName.STOP, GestureName.ESTOP}
        threshold = (
            self.settings.safety_minimum_confidence
            if safety
            else self.settings.minimum_confidence
        )
        if recognition.confidence < threshold or not recognition.hand_detected:
            return GestureFrameResponse(
                recognition=recognition,
                decision=GestureDecision.IGNORED,
                message=f"手势置信度不足（阈值 {threshold:.2f}），未产生任何命令。",
            )

        with self._lock:
            if state.latched_gesture == gesture:
                return GestureFrameResponse(
                    recognition=recognition,
                    decision=GestureDecision.SUPPRESSED_LATCHED,
                    message="同一手势仍在保持；必须先松开/离开画面后才能再次触发。",
                )

        # Safety gestures bypass busy/cooldown/voice arbitration, but still use
        # the one-shot latch so a held palm/circle does not spam stop requests.
        if gesture == GestureName.ESTOP:
            snapshot = await self.runtime.stop(session_id, emergency=True)
            with self._lock:
                self._latch(state, gesture)
            return GestureFrameResponse(
                recognition=recognition,
                decision=GestureDecision.SAFETY_ESTOP,
                message="识别到急停手势：五指张开且掌心正对摄像头，已立即执行急停。",
                session_snapshot=snapshot.model_dump(mode="json"),
            )
        if gesture == GestureName.STOP:
            snapshot = await self.runtime.stop(session_id, emergency=False)
            with self._lock:
                self._latch(state, gesture)
            return GestureFrameResponse(
                recognition=recognition,
                decision=GestureDecision.SAFETY_STOP,
                message="识别到停止手势：拇指和食指组成圆圈，已立即停止机械臂。",
                session_snapshot=snapshot.model_dump(mode="json"),
            )

        with self._lock:
            if now < state.cooldown_until_s:
                state.latched_gesture = gesture
                return GestureFrameResponse(
                    recognition=recognition,
                    decision=GestureDecision.SUPPRESSED_COOLDOWN,
                    message="手势仍在冷却时间内，未重复触发。",
                )
            if self._voice_conflict(state, now):
                # Voice wins this occurrence. Latch it so holding the same hand
                # pose cannot execute immediately after speech ends.
                state.latched_gesture = gesture
                return GestureFrameResponse(
                    recognition=recognition,
                    decision=GestureDecision.SUPPRESSED_VOICE,
                    message="检测到语音输入，按优先级规则压制普通手势。",
                )
        if session.status in _BUSY_STATUSES or session.pending_confirmation:
            with self._lock:
                state.latched_gesture = gesture
            return GestureFrameResponse(
                recognition=recognition,
                decision=GestureDecision.SUPPRESSED_BUSY,
                message="当前会话已有待确认或执行中的普通任务，未接受新手势。",
            )

        # Hold the ordinary gesture for the configured voice conflict window.
        # If speech begins during the window, voice wins and no command is made.
        await asyncio.sleep(self.settings.voice_conflict_window_s)
        now = time.monotonic()
        with self._lock:
            if self._voice_conflict(state, now):
                state.latched_gesture = gesture
                return GestureFrameResponse(
                    recognition=recognition,
                    decision=GestureDecision.SUPPRESSED_VOICE,
                    message="冲突窗口内出现语音输入，普通手势已被语音压制。",
                )

        # Re-read after the wait; another request may have changed the session.
        session = self.runtime.get_session(session_id)
        if session.status in _BUSY_STATUSES or session.pending_confirmation:
            with self._lock:
                state.latched_gesture = gesture
            return GestureFrameResponse(
                recognition=recognition,
                decision=GestureDecision.SUPPRESSED_BUSY,
                message="冲突窗口结束前会话状态已变化，手势未进入执行链路。",
            )

        command = gesture_to_command(
            gesture,
            distance_mm=self.runtime.settings.default_relative_step_mm,
            command_id=f"gesture-{uuid4().hex}",
        )
        if command is None or command.intent != CommandIntent.MOVE_RELATIVE:
            return GestureFrameResponse(
                recognition=recognition,
                decision=GestureDecision.IGNORED,
                message="识别结果没有对应的普通相对移动命令。",
            )

        raw_output = {
            "function": "classify_fixed_gesture",
            "arguments": {
                "gesture": recognition.gesture.value,
                "confidence": recognition.confidence,
                "hand_detected": recognition.hand_detected,
            },
            "model": recognition.model,
            "tool_call_id": recognition.tool_call_id,
        }

        def accept(record) -> None:
            if record.status in _BUSY_STATUSES or record.pending_command is not None:
                raise RuntimeError("session became busy during gesture acceptance")
            record.status = SessionStatus.AWAITING_CONFIRMATION
            record.prompt = f"[手势] {gesture.value}"
            record.input_source = InputSource.GESTURE
            record.image_name = None
            record.asr_transcription = None
            record.pending_command = command
            record.active_command_id = None
            record.raw_model_output = raw_output
            record.normalized_command = command.model_dump(mode="json")
            record.execution_events = []
            record.live_tool_events = []
            record.orchestration = None
            record.message = (
                f"已识别手势 {gesture.value}；将沿 robot_base "
                f"{command.relative_motion.axis.value.upper()} 轴"
                f"{'正' if command.relative_motion.direction.value == 'positive' else '负'}方向移动 "
                f"{command.relative_motion.distance_mm:g} mm。请确认后执行。"
            )
            record.error = None

        try:
            snapshot = self.runtime.store.mutate(session_id, accept)
        except RuntimeError:
            with self._lock:
                state.latched_gesture = gesture
            return GestureFrameResponse(
                recognition=recognition,
                decision=GestureDecision.SUPPRESSED_BUSY,
                message="接受手势时会话已被其他输入占用，手势未执行。",
            )

        with self._lock:
            self._latch(state, gesture)
        return GestureFrameResponse(
            recognition=recognition,
            decision=GestureDecision.ACCEPTED,
            message="手势已通过仲裁并形成待确认的相对移动任务。",
            mapped_command=command.model_dump(mode="json"),
            session_snapshot=snapshot.model_dump(mode="json"),
        )


def build_gesture_coordinator(runtime: Any) -> GestureCoordinator:
    parser = getattr(runtime, "parser", None)
    client = getattr(parser, "client", None)
    model = getattr(parser, "model", None)
    if client is None or not isinstance(model, str) or not model:
        raise GestureRecognitionError(
            "gesture recognition requires an InternS2Agent-backed WebRuntime"
        )
    recognizer = InternS2GestureRecognizer(
        runtime.settings,
        client,
        model=model,
    )
    return GestureCoordinator(runtime, recognizer=recognizer)
