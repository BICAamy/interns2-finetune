from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest

from surgical_contracts import Axis, CommandIntent, Direction
from web.backend.gesture.coordinator import GestureCoordinator
from web.backend.gesture.models import (
    GestureDecision,
    GestureFrameRequest,
    GestureName,
    GestureRecognition,
)
from web.backend.gesture.service import GestureSettings, gesture_to_command
from web.backend.models import SessionStatus
from web.backend.sessions import SessionStore


class StubRecognizer:
    def __init__(self, *recognitions: GestureRecognition) -> None:
        self.recognitions = list(recognitions)
        self.calls = 0

    def recognize(self, _image_data_url: str) -> GestureRecognition:
        self.calls += 1
        if not self.recognitions:
            raise AssertionError("no stub gesture recognition remains")
        return self.recognitions.pop(0)


def recognition(
    gesture: GestureName,
    *,
    confidence: float = 0.95,
    hand_detected: bool = True,
) -> GestureRecognition:
    return GestureRecognition(
        gesture=gesture,
        confidence=confidence,
        hand_detected=hand_detected,
        model="stub-interns2",
        latency_ms=12,
    )


class StubRuntime:
    def __init__(self) -> None:
        self.store = SessionStore()
        self.settings = SimpleNamespace(default_relative_step_mm=5.0)
        self.stop_calls: list[bool] = []
        self.session = self.store.create()

    def get_session(self, session_id: str):
        return self.store.snapshot(session_id)

    async def stop(self, session_id: str, *, emergency: bool):
        self.stop_calls.append(emergency)

        def mutate(record) -> None:
            record.pending_command = None
            record.status = SessionStatus.ESTOP if emergency else SessionStatus.STOPPED
            record.message = "estop" if emergency else "stop"

        return self.store.mutate(session_id, mutate)


class GestureMappingTests(unittest.TestCase):
    def test_operator_view_directions_map_to_robot_base(self):
        expected = {
            GestureName.UP: (Axis.Z, Direction.POSITIVE),
            GestureName.DOWN: (Axis.Z, Direction.NEGATIVE),
            GestureName.LEFT: (Axis.X, Direction.NEGATIVE),
            GestureName.RIGHT: (Axis.X, Direction.POSITIVE),
            GestureName.FORWARD: (Axis.Y, Direction.POSITIVE),
            GestureName.BACKWARD: (Axis.Y, Direction.NEGATIVE),
        }
        for gesture, (axis, direction) in expected.items():
            with self.subTest(gesture=gesture):
                command = gesture_to_command(
                    gesture,
                    distance_mm=5.0,
                    command_id=f"test-{gesture.value}",
                )
                self.assertEqual(command.intent, CommandIntent.MOVE_RELATIVE)
                self.assertEqual(command.relative_motion.axis, axis)
                self.assertEqual(command.relative_motion.direction, direction)
                self.assertEqual(command.relative_motion.distance_mm, 5.0)
                self.assertTrue(command.needs_confirmation)

    def test_stop_and_estop_map_to_safety_intents(self):
        stop = gesture_to_command(
            GestureName.STOP,
            distance_mm=5.0,
            command_id="stop",
        )
        estop = gesture_to_command(
            GestureName.ESTOP,
            distance_mm=5.0,
            command_id="estop",
        )
        self.assertEqual(stop.intent, CommandIntent.STOP)
        self.assertEqual(estop.intent, CommandIntent.EMERGENCY_STOP)


class GestureCoordinatorTests(unittest.TestCase):
    def settings(self) -> GestureSettings:
        return GestureSettings(
            minimum_confidence=0.85,
            safety_minimum_confidence=0.80,
            cooldown_s=0.0,
            voice_conflict_window_s=0.01,
            maximum_frame_age_s=10.0,
        )

    @staticmethod
    def frame() -> GestureFrameRequest:
        import time

        return GestureFrameRequest(
            image_data_url="data:image/jpeg;base64," + "A" * 64,
            captured_at_ms=time.time_ns() // 1_000_000,
        )

    def test_normal_gesture_becomes_pending_confirmation(self):
        runtime = StubRuntime()
        recognizer = StubRecognizer(recognition(GestureName.UP))
        coordinator = GestureCoordinator(
            runtime,
            recognizer=recognizer,
            settings=self.settings(),
        )
        response = asyncio.run(
            coordinator.submit_frame(runtime.session.session_id, self.frame())
        )
        snapshot = runtime.get_session(runtime.session.session_id)
        self.assertEqual(response.decision, GestureDecision.ACCEPTED)
        self.assertEqual(snapshot.status, SessionStatus.AWAITING_CONFIRMATION)
        self.assertEqual(snapshot.input_source.value, "gesture")
        self.assertEqual(snapshot.normalized_command["intent"], "move_relative")
        self.assertEqual(snapshot.normalized_command["relative_motion"]["axis"], "z")

    def test_voice_activity_suppresses_normal_gesture(self):
        runtime = StubRuntime()
        recognizer = StubRecognizer(recognition(GestureName.DOWN))
        coordinator = GestureCoordinator(
            runtime,
            recognizer=recognizer,
            settings=self.settings(),
        )
        coordinator.set_voice_activity(runtime.session.session_id, True)
        response = asyncio.run(
            coordinator.submit_frame(runtime.session.session_id, self.frame())
        )
        snapshot = runtime.get_session(runtime.session.session_id)
        self.assertEqual(response.decision, GestureDecision.SUPPRESSED_VOICE)
        self.assertEqual(snapshot.status, SessionStatus.READY)
        self.assertFalse(snapshot.pending_confirmation)

    def test_estop_bypasses_voice_and_calls_fast_path(self):
        runtime = StubRuntime()
        recognizer = StubRecognizer(recognition(GestureName.ESTOP, confidence=0.91))
        coordinator = GestureCoordinator(
            runtime,
            recognizer=recognizer,
            settings=self.settings(),
        )
        coordinator.set_voice_activity(runtime.session.session_id, True)
        response = asyncio.run(
            coordinator.submit_frame(runtime.session.session_id, self.frame())
        )
        self.assertEqual(response.decision, GestureDecision.SAFETY_ESTOP)
        self.assertEqual(runtime.stop_calls, [True])
        self.assertEqual(
            runtime.get_session(runtime.session.session_id).status,
            SessionStatus.ESTOP,
        )

    def test_low_confidence_gesture_is_ignored(self):
        runtime = StubRuntime()
        recognizer = StubRecognizer(recognition(GestureName.LEFT, confidence=0.4))
        coordinator = GestureCoordinator(
            runtime,
            recognizer=recognizer,
            settings=self.settings(),
        )
        response = asyncio.run(
            coordinator.submit_frame(runtime.session.session_id, self.frame())
        )
        self.assertEqual(response.decision, GestureDecision.IGNORED)
        self.assertEqual(
            runtime.get_session(runtime.session.session_id).status,
            SessionStatus.READY,
        )


if __name__ == "__main__":
    unittest.main()
