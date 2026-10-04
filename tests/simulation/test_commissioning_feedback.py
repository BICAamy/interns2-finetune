"""The local motion monitor must resolve 10003/10004 disagreements conservatively."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from edge_gateway import commissioning_runtime as runtime
from surgical_contracts import RobotTelemetry
from tests.integration.test_real_motion_fake import readback, telemetry
from tests.unit.edge_gateway.test_commissioning_cli import config


def test_motion_feedback_preserves_raw_sources_and_combines_conservatively(monkeypatch):
    state = SimpleNamespace(
        has_error=False, error_code=0, enabled=False,
        in_position=False, moving=True,
    )
    axes = SimpleNamespace(group_error_code=0, joint_error_codes=(0,) * 6)
    sample = SimpleNamespace(
        enabled=True, in_position=True, moving=False, fsm_code=33, override=1.0,
    )
    sampler = SimpleNamespace(snapshot=lambda: SimpleNamespace(sample=sample), watchdog=object())
    client = SimpleNamespace(request=lambda *_a: None, package_version="test-version")
    config = SimpleNamespace(
        controller=SimpleNamespace(device_sn="test-sn", model="E05_Pro"),
        deadlines=SimpleNamespace(state_stale_ms=250),
        motion=SimpleNamespace(controller_override=1.0),
    )
    base = RobotTelemetry.model_construct(state_age_ms=0, potentially_moving=False)
    monkeypatch.setattr(runtime, "read_robot_state", lambda _reply: state)
    monkeypatch.setattr(runtime, "read_emergency_info", lambda _reply: object())
    monkeypatch.setattr(runtime, "read_axis_error_code", lambda _reply: axes)
    monkeypatch.setattr(runtime, "telemetry_from_sample", lambda *_a, **_kw: base)

    result = runtime.read_motion_feedback(config, client, sampler, session_id="test-session")
    assert result.moving_10003 is True
    assert result.moving_10004 is False
    assert result.fsm_10004 == 33
    assert result.debug_text == "moving_10003=True, moving_10004=False, fsm_10004=33"
    assert result.telemetry.enabled is False
    assert result.telemetry.in_position is False
    assert result.telemetry.moving is True
    assert result.telemetry.potentially_moving is True


def test_final_guard_requires_new_sample_and_yaml_pose_tolerance():
    before = runtime.LocalObservation(telemetry(), readback(), None)
    stale = runtime.LocalObservation(telemetry(sequence=10), readback(), None)
    with pytest.raises(ValueError, match="freshness"):
        runtime.validate_final_observation(before, stale, config())

    moved = telemetry(sequence=11, x=101.0)
    with pytest.raises(ValueError, match="start drifted"):
        runtime.validate_final_observation(
            before, runtime.LocalObservation(moved, readback(), None), config(),
        )

    within_tolerance = telemetry(sequence=11, x=100.1).model_copy(update={
        "joint_positions_deg": (0.2, 0, 90, 0, 90, 0),
    })
    runtime.validate_final_observation(
        before, runtime.LocalObservation(within_tolerance, readback(), None), config(),
    )
