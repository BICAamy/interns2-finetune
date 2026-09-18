from __future__ import annotations

import time

import numpy as np
from fastapi.testclient import TestClient

from robot_runtime.api import create_app
from robot_runtime.mirror_worker import RealMirrorWorker
from robot_runtime.providers.huayan_real import HuayanRealStubProvider
from simulation.entry_point_env.config import EntryPointEnvConfig
from simulation.entry_point_env.external_joint_state_controller import ExternalJointStateController
from simulation.server.video_stream import encode_jpeg, mjpeg_chunk
from surgical_contracts import (
    LinkState, RobotConnectionState, RobotHealth, RobotProvider, RuntimeMode,
    SourceFreshness,
)
from tests.simulation.test_external_joint_state import telemetry


class ReplayEnvironment:
    def __init__(self) -> None:
        self.controller = ExternalJointStateController(EntryPointEnvConfig.from_yaml(), stale_ms=250)
        self.closed = False

    def reset(self) -> None:
        pass

    def _frame(self) -> np.ndarray:
        snapshot = self.controller.snapshot
        assert snapshot is not None
        frame = np.full((16, 16, 3), snapshot.source_sequence % 255, dtype=np.uint8)
        if self.controller.freshness != SourceFreshness.FRESH:
            frame[0, :, :] = (255, 0, 0)
        return frame

    def apply_external_joint_state(self, state):
        return self._frame() if self.controller.apply_external_joint_state(state) else None

    def refresh_frozen_frame(self):
        return self._frame() if self.controller.snapshot is not None else None

    def close(self) -> None:
        self.closed = True


class ReplaySessions:
    def __init__(self, current: list) -> None:
        self.current = current

    def telemetry(self):
        return self.current[0]

    def health(self):
        return RobotHealth(
            runtime_mode=RuntimeMode.REAL,
            provider=RobotProvider.HUAYAN_EDGE_GATEWAY,
            control_mode="observe-only",
            status="healthy",
            freshness=SourceFreshness.FRESH,
            connections=RobotConnectionState(gateway=LinkState.CONNECTED),
            ready_for_motion=False,
        )


def wait_for(predicate, *, timeout_s: float = 2.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.01)
    raise AssertionError("mirror replay did not reach expected state")


def test_real_mirror_replays_actual_feedback_and_freezes_without_motion(monkeypatch) -> None:
    current = [telemetry(1)]
    environment = ReplayEnvironment()
    mirror = RealMirrorWorker(
        lambda: current[0],
        stale_ms=250,
        environment_factory=lambda: environment,
        tick_interval_s=0.005,
    )
    provider = HuayanRealStubProvider(ReplaySessions(current), mirror_worker=mirror)
    monkeypatch.setattr(
        "robot_runtime.api.mjpeg_stream",
        lambda _provider: iter([mjpeg_chunk(b"\xff\xd8\xff\xd9")]),
    )
    with TestClient(create_app(provider=provider, mode="real")) as client:
        first = wait_for(lambda: mirror.status().source_sequence == 1 and mirror.status())
        assert first.freshness == SourceFreshness.FRESH
        assert first.calibrated is False
        assert client.get("/v1/state").json()["sequence"] == first.source_sequence
        assert client.get("/v1/mirror").json()["source_sequence"] == 1
        frame_seq, frame = provider.wait_for_frame(-1, timeout_s=1)
        assert frame_seq == first.frame_sequence
        assert encode_jpeg(frame).startswith(b"\xff\xd8")
        assert client.get("/v1/stream.mjpeg").status_code == 200
        assert client.post(
            "/v1/commands/move-relative",
            json={"command_id": "mirror-motion-blocked", "translation_mm": [0, 0, 1]},
        ).status_code == 403

        # A changed command target cannot alter the mirror: only a new source
        # sequence from the actual feedback channel can publish a new pose.
        time.sleep(0.04)
        assert mirror.status().source_sequence == 1
        assert mirror.status().frame_sequence == first.frame_sequence

        current[0] = telemetry(2)
        second = wait_for(lambda: mirror.status().source_sequence == 2 and mirror.status())
        assert second.frame_sequence > first.frame_sequence
        current[0] = telemetry(2, freshness=SourceFreshness.STALE)
        stale = wait_for(lambda: mirror.status().freshness == SourceFreshness.STALE and mirror.status())
        assert stale.source_sequence == 2
        assert stale.frame_sequence > second.frame_sequence
        _, frozen = provider.wait_for_frame(second.frame_sequence, timeout_s=1)
        assert frozen is not None and tuple(frozen[0, 0]) == (255, 0, 0)
        assert environment.controller.snapshot.source_sequence == 2

        current[0] = telemetry(1, session="session-b")
        time.sleep(0.04)
        assert mirror.status().source_sequence == 2
        current[0] = telemetry(2, session="session-b")
        resumed = wait_for(lambda: mirror.status().gateway_session_id == "session-b" and mirror.status())
        assert resumed.source_sequence == 2
        assert resumed.freshness == SourceFreshness.FRESH
    assert environment.closed
