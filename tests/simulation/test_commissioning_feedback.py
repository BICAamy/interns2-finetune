"""The local motion monitor must resolve 10003/10004 disagreements conservatively."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from edge_gateway import commissioning_runtime as runtime
from surgical_contracts import RobotTelemetry
from tests.integration.test_real_motion_fake import readback, telemetry
from tests.unit.edge_gateway.test_commissioning_cli import config


def test_motion_feedback_does_not_hide_a_warning_from_either_channel(monkeypatch):
    state = SimpleNamespace(
        has_error=False, error_code=0, enabled=False, brakes_released=False,
        in_position=False, moving=True,
    )
    axes = SimpleNamespace(group_error_code=0, joint_error_codes=(0,) * 6)
    sample = SimpleNamespace(
        enabled=True, brake_states=(1,) * 6, in_position=True, moving=False,
    )
    sampler = SimpleNamespace(snapshot=lambda: SimpleNamespace(sample=sample), watchdog=object())
    client = SimpleNamespace(request=lambda *_a: None, package_version="test-version")
    config = SimpleNamespace(
        controller=SimpleNamespace(device_sn="test-sn", model="E05_Pro"),
        deadlines=SimpleNamespace(state_stale_ms=250),
    )
    base = RobotTelemetry.model_construct(state_age_ms=0, potentially_moving=False)
    monkeypatch.setattr(runtime, "read_robot_state", lambda _reply: state)
    monkeypatch.setattr(runtime, "read_emergency_info", lambda _reply: object())
    monkeypatch.setattr(runtime, "read_axis_error_code", lambda _reply: axes)
    monkeypatch.setattr(runtime, "telemetry_from_sample", lambda *_a, **_kw: base)

    feedback = runtime.read_motion_feedback(config, client, sampler, session_id="test-session")
    assert feedback.enabled is False
    assert feedback.brakes_released is False
    assert feedback.in_position is False
    assert feedback.moving is True
    assert feedback.potentially_moving is True


def test_stationary_observation_rejects_joint_motion_even_with_fixed_tcp():
    def sample(j1):
        return SimpleNamespace(
            base_pose=(500.0, 20.0, 240.0, 0.0, 0.0, 0.0),
            joint_positions_deg=(j1, 0.0, 90.0, 0.0, 90.0, 0.0),
            auto_mode=False, reduced_mode=False, moving=False, fsm_code=33,
            enabled=True, in_position=True, brake_states=(1,) * 6,
            free_drive_mode=False, force_control_state=0, paused=False,
        )

    samples = iter((sample(0.0), sample(0.2)))
    sampler = SimpleNamespace(snapshot=lambda: SimpleNamespace(sample=next(samples)))
    with pytest.raises(ValueError, match="moved or changed"):
        runtime.observe_stationary(sampler, duration_s=0.1, poll_s=0.0)


def test_final_guard_requires_new_sample_and_unchanged_joints():
    before = runtime.LocalObservation(telemetry(), readback(), None)
    stale = runtime.LocalObservation(telemetry(sequence=10), readback(), None)
    with pytest.raises(ValueError, match="freshness"):
        runtime.validate_final_observation(before, stale, config())

    moved = telemetry(sequence=11).model_copy(update={
        "joint_positions_deg": (0.2, 0, 90, 0, 90, 0),
    })
    with pytest.raises(ValueError, match="joints changed"):
        runtime.validate_final_observation(
            before, runtime.LocalObservation(moved, readback(), None), config(),
        )
