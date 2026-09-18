from __future__ import annotations

import math
import os

import numpy as np
import pytest

from simulation.entry_point_env.config import EntryPointEnvConfig
from simulation.entry_point_env.external_joint_state_controller import ExternalJointStateController
from simulation.entry_point_env.renderer import TrajectoryRenderer
from surgical_contracts import (
    CoordinateFrame, DistanceUnit, Pose6D, RobotProvider, RobotTelemetry,
    RuntimeMode, SourceFreshness,
)


CONFIG = EntryPointEnvConfig.from_yaml()


def telemetry(
    sequence: int,
    joints: tuple[float, ...] = (0.0, -13.573, 97.585, 0.918, 57.696, -39.035),
    *,
    session: str = "session-a",
    freshness: SourceFreshness = SourceFreshness.FRESH,
    age_ms: float = 10.0,
) -> RobotTelemetry:
    return RobotTelemetry(
        runtime_mode=RuntimeMode.REAL,
        provider=RobotProvider.HUAYAN_EDGE_GATEWAY,
        control_mode="observe-only",
        sequence=sequence,
        freshness=freshness,
        gateway_session_id=session,
        joint_positions_deg=joints,
        state_age_ms=age_ms,
        controller_is_simulation=False,
        actual_pose_robot_base=Pose6D(
            translation_mm=(500.0 + sequence, 0.0, 500.0),
            rotation_rpy_deg=(0.0, 0.0, 0.0),
            quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
            frame=CoordinateFrame.ROBOT_BASE,
            unit=DistanceUnit.MILLIMETER,
        ),
    )


def test_actual_joint_feedback_only_uses_fk_and_mapping(monkeypatch) -> None:
    controller = ExternalJointStateController(
        CONFIG,
        stale_ms=250,
        sign=(1, -1, 1, 1, 1, 1),
        zero_offset_deg=(0, -10, 0, 0, 0, 0),
    )
    monkeypatch.setattr(
        controller.kinematics, "inverse",
        lambda *_args, **_kwargs: pytest.fail("passive mirror called IK"),
    )
    source = telemetry(1)
    assert controller.apply_external_joint_state(source)
    snapshot = controller.snapshot
    assert snapshot is not None
    assert snapshot.actual_joint_positions_deg == source.joint_positions_deg
    assert snapshot.visual_joint_positions_rad[1] == pytest.approx(math.radians(3.573))
    expected = controller.kinematics.forward(snapshot.visual_joint_positions_rad)
    np.testing.assert_allclose(snapshot.kinematics.flange_transform, expected.flange_transform)
    assert controller.trajectory_mm == ((501.0, 0.0, 500.0),)
    assert not hasattr(controller, "move_relative")
    assert not hasattr(controller, "move_to_entry")


def test_20hz_replay_single_axes_both_directions_and_stationary_no_drift() -> None:
    controller = ExternalJointStateController(CONFIG, stale_ms=250)
    initial = telemetry(1)
    assert controller.apply_external_joint_state(initial)
    starting = controller.snapshot
    assert starting is not None
    sequence = 1
    for axis in range(6):
        for delta in (0.1, -0.1):
            sequence += 1
            joints = list(initial.joint_positions_deg)
            joints[axis] += delta
            assert controller.apply_external_joint_state(telemetry(sequence, tuple(joints)))
            assert controller.snapshot is not None
            assert controller.snapshot.actual_joint_positions_deg[axis] == pytest.approx(joints[axis])
    stationary = controller.snapshot
    assert stationary is not None
    for _ in range(40):  # 2 seconds at 20 Hz, repeated actual pose
        sequence += 1
        assert controller.apply_external_joint_state(telemetry(sequence, stationary.actual_joint_positions_deg))
        np.testing.assert_allclose(
            controller.snapshot.kinematics.flange_transform,
            stationary.kinematics.flange_transform,
        )


def test_stale_bad_vectors_limits_and_order_freeze_last_valid_pose() -> None:
    controller = ExternalJointStateController(CONFIG, stale_ms=250)
    assert controller.apply_external_joint_state(telemetry(10))
    good = controller.snapshot
    assert good is not None
    bad_inputs = (
        telemetry(11, freshness=SourceFreshness.STALE),
        telemetry(11, age_ms=251),
        telemetry(11).model_copy(update={"joint_positions_deg": (1.0, 2.0)}),
        telemetry(11).model_copy(update={"joint_positions_deg": (1.0,) * 7}),
        telemetry(11).model_copy(update={"joint_positions_deg": (float("nan"),) * 6}),
        telemetry(11, joints=(0.0, 200.0, 0.0, 0.0, 0.0, 0.0)),
        telemetry(9),
    )
    for bad in bad_inputs:
        assert not controller.apply_external_joint_state(bad)
        assert controller.snapshot is good
    assert controller.freshness == SourceFreshness.STALE
    assert controller.apply_external_joint_state(telemetry(11))
    assert controller.snapshot.source_sequence == 11
    assert not controller.apply_external_joint_state(telemetry(11))
    assert controller.snapshot.source_sequence == 11


def test_new_gateway_session_freezes_first_sample_then_accepts_next() -> None:
    controller = ExternalJointStateController(CONFIG, stale_ms=250)
    assert controller.apply_external_joint_state(telemetry(100))
    old = controller.snapshot
    assert not controller.apply_external_joint_state(telemetry(1, session="session-b"))
    assert controller.snapshot is old
    assert controller.freshness == SourceFreshness.STALE
    assert not controller.apply_external_joint_state(telemetry(1, session="session-b"))
    assert controller.apply_external_joint_state(telemetry(2, session="session-b"))
    assert controller.snapshot.gateway_session_id == "session-b"
    assert controller.snapshot.source_sequence == 2
    assert controller.trajectory_mm == ((502.0, 0.0, 500.0),)


def test_uncalibrated_overlay_has_no_provisional_tcp_marker() -> None:
    frame = np.zeros((64, 128, 3), dtype=np.uint8)
    rendered = TrajectoryRenderer().render(
        frame,
        trajectory_scene=(),
        tcp_scene=None,
        entry_scene=None,
        warning="UNCALIBRATED",
        project=lambda _point: (40, 40),
    )
    assert tuple(rendered[5, 5]) == (90, 0, 0)
    assert tuple(frame[5, 5]) == (0, 0, 0)


@pytest.mark.skipif(
    os.environ.get("ENTRY_POINT_SOFA_TESTS") != "1",
    reason="requires server SOFA, E05 meshes and Xvfb",
)
def test_passive_sofa_scene_hides_provisional_tool_and_renders_feedback() -> None:
    from sofa_env.base import RenderMode
    from simulation.entry_point_env.passive_mirror_env import PassiveRealMirrorEnv

    env = PassiveRealMirrorEnv(stale_ms=250, render_mode=RenderMode.HUMAN)
    try:
        env.reset()
        assert env.scene_creation_result["interactive_objects"]["needle"] is None
        assert env.scene_creation_result["interactive_objects"]["tcp_marker"] is None
        frame = env.apply_external_joint_state(telemetry(1))
        assert frame is not None
        assert frame.shape == CONFIG.image_shape + (3,)
        before = np.asarray(env._robot_links[0].get_pose()).copy()
        joints = list(telemetry(1).joint_positions_deg)
        joints[0] += 1.0
        env.apply_external_joint_state(telemetry(2, tuple(joints)))
        after = np.asarray(env._robot_links[0].get_pose()).copy()
        assert not np.allclose(before, after)
    finally:
        env.close()
