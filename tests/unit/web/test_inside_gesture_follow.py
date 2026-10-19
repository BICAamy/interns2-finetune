from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from surgical_contracts import RuntimeMode
from web_inside.backend.gesture.coordinator import GestureCoordinator
from web_inside.backend.gesture.models import (
    GestureDecision,
    GestureFrameRequest,
    GestureName,
    GestureRecognition,
)
from web_inside.backend.gesture.service import GestureRecognitionError, GestureSettings
from web_inside.backend.manual_control import ManualTransport
from web_inside.backend.sessions import SessionStore


class Recognizer:
    def __init__(self, *results):
        self.results = list(results)

    def recognize(self, _image: str) -> GestureRecognition:
        selected = self.results.pop(0)
        if isinstance(selected, Exception):
            raise selected
        return selected


def recognition(
    gesture: GestureName,
    *,
    confidence: float = 0.96,
    hand_detected: bool = True,
) -> GestureRecognition:
    return GestureRecognition(
        gesture=gesture,
        confidence=confidence,
        hand_detected=hand_detected,
        model="stub-interns2",
        latency_ms=12,
    )


class DirectControl:
    def __init__(self) -> None:
        self.inputs = []
        self.acquired = False
        self.lease = None

    def status(self, _session_id: str) -> dict:
        return {
            "mode": "simulation",
            "moving": bool(self.inputs and self.inputs[-1].kind is not None),
            "reason": "",
        }

    async def acquire(self, session_id: str, *, owner: str) -> dict:
        assert owner == "gesture"
        self.acquired = True
        self.lease = SimpleNamespace(token="gesture-control-token")
        return {"token": self.lease.token}

    async def heartbeat(self, _session_id: str, _token: str) -> dict:
        return {}

    async def input(self, _session_id: str, command) -> dict:
        self.inputs.append(command)
        return {}

    async def release(self, _session_id: str, token: str) -> dict:
        assert token == "gesture-control-token"
        self.acquired = False
        self.lease = None
        return {}

    def default_translation_step(self, _session_id: str) -> float:
        return 15.0


class Runtime:
    def __init__(self) -> None:
        self.store = SessionStore()
        self.session = self.store.create(robot_mode=RuntimeMode.SIMULATION)
        self.manual = DirectControl()
        self.stop_calls = []

    def get_session(self, session_id: str):
        return self.store.snapshot(session_id)

    async def stop(self, session_id: str, *, emergency: bool):
        self.stop_calls.append(emergency)
        return self.store.snapshot(session_id)


def frame() -> GestureFrameRequest:
    return GestureFrameRequest(
        image_data_url="data:image/jpeg;base64," + "A" * 64,
        captured_at_ms=1,
    )


def coordinator(runtime: Runtime, *results) -> GestureCoordinator:
    return GestureCoordinator(
        runtime,
        recognizer=Recognizer(*results),
        settings=GestureSettings(
            minimum_confidence=0.85,
            safety_minimum_confidence=0.8,
            stable_frames=2,
            cooldown_s=10,
            voice_conflict_window_s=10,
        ),
    )


def test_recognized_direction_moves_immediately_without_pending_confirmation():
    async def case():
        runtime = Runtime()
        selected = coordinator(runtime, recognition(GestureName.UP))
        await selected.acquire(runtime.session.session_id)
        response = await selected.submit_frame(runtime.session.session_id, frame())
        command = runtime.manual.inputs[-1]
        assert response.decision == GestureDecision.ACCEPTED
        assert response.mapped_command is not None
        assert response.mapped_command["needs_confirmation"] is False
        assert (command.kind, command.axis, command.direction) == ("translation", 2, 1)
        assert command.amount == 15
        assert command.continuous is True
        snapshot = runtime.get_session(runtime.session.session_id)
        assert snapshot.pending_confirmation is False
        assert snapshot.active_command_id is None

    asyncio.run(case())


def test_lost_gesture_pauses_and_new_gesture_resumes_in_new_direction():
    async def case():
        runtime = Runtime()
        selected = coordinator(
            runtime,
            recognition(GestureName.FORWARD),
            recognition(GestureName.NONE, hand_detected=False),
            recognition(GestureName.RIGHT),
        )
        await selected.acquire(runtime.session.session_id)
        first = await selected.submit_frame(runtime.session.session_id, frame())
        lost = await selected.submit_frame(runtime.session.session_id, frame())
        resumed = await selected.submit_frame(runtime.session.session_id, frame())
        assert first.decision == GestureDecision.ACCEPTED
        assert lost.decision == GestureDecision.PAUSED
        assert resumed.decision == GestureDecision.ACCEPTED
        assert [item.kind for item in runtime.manual.inputs] == ["translation", None, "translation"]
        assert (runtime.manual.inputs[-1].axis, runtime.manual.inputs[-1].direction) == (1, -1)

    asyncio.run(case())


def test_direction_change_stops_old_motion_before_starting_new_motion():
    async def case():
        runtime = Runtime()
        selected = coordinator(
            runtime,
            recognition(GestureName.LEFT),
            recognition(GestureName.DOWN),
        )
        await selected.acquire(runtime.session.session_id)
        await selected.submit_frame(runtime.session.session_id, frame())
        await selected.submit_frame(runtime.session.session_id, frame())
        assert [item.kind for item in runtime.manual.inputs] == ["translation", None, "translation"]
        assert (runtime.manual.inputs[-1].axis, runtime.manual.inputs[-1].direction) == (2, -1)

    asyncio.run(case())


def test_recognition_failure_stops_previous_motion_before_reporting_error():
    async def case():
        runtime = Runtime()
        selected = coordinator(
            runtime,
            recognition(GestureName.BACKWARD),
            GestureRecognitionError("model offline"),
        )
        await selected.acquire(runtime.session.session_id)
        await selected.submit_frame(runtime.session.session_id, frame())
        with pytest.raises(GestureRecognitionError):
            await selected.submit_frame(runtime.session.session_id, frame())
        assert runtime.manual.inputs[-1].kind is None

    asyncio.run(case())


def test_estop_uses_runtime_fast_path_without_waiting_for_normal_stop():
    async def case():
        runtime = Runtime()
        selected = coordinator(
            runtime,
            recognition(GestureName.FORWARD),
            recognition(GestureName.ESTOP),
        )
        await selected.acquire(runtime.session.session_id)
        await selected.submit_frame(runtime.session.session_id, frame())
        response = await selected.submit_frame(runtime.session.session_id, frame())
        assert response.decision == GestureDecision.SAFETY_ESTOP
        assert runtime.stop_calls == [True]
        assert [item.kind for item in runtime.manual.inputs] == ["translation"]
        assert selected.status(runtime.session.session_id).moving is False

    asyncio.run(case())


def test_gesture_release_stops_motion_and_releases_exclusive_control():
    async def case():
        runtime = Runtime()
        selected = coordinator(runtime, recognition(GestureName.LEFT))
        await selected.acquire(runtime.session.session_id)
        await selected.submit_frame(runtime.session.session_id, frame())
        response = await selected.release(runtime.session.session_id)
        assert response.reset is True
        assert runtime.manual.inputs[-1].kind is None
        assert runtime.manual.acquired is False
        assert selected.status(runtime.session.session_id).active is False

    asyncio.run(case())


def test_real_direct_transport_confirms_short_motion_proposal_automatically():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/v1/commands/move-sequence":
            return httpx.Response(202, json={
                "status": "queued",
                "result": {"proposal": {"fingerprint": "abc123"}},
            })
        if request.url.path.endswith("/confirm"):
            return httpx.Response(200, json={"status": "running"})
        raise AssertionError(request.url.path)

    async def case():
        transport = ManualTransport("http://robot.test", confirm_proposals=True)
        await transport.client.aclose()
        transport.client = httpx.AsyncClient(
            base_url="http://robot.test",
            transport=httpx.MockTransport(handler),
        )
        command = SimpleNamespace(
            command_id="gesture-real-1",
            model_dump=lambda **_kwargs: {"command_id": "gesture-real-1"},
        )
        record = await transport.submit(command)
        assert record["status"] == "running"
        assert calls == [
            ("POST", "/v1/commands/move-sequence"),
            ("POST", "/v1/commands/gesture-real-1/confirm"),
        ]
        await transport.close()

    asyncio.run(case())
