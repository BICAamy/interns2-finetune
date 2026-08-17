from __future__ import annotations

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from simulation.entry_point_env.camera_controller import OrbitCameraController
from surgical_contracts import SimulationCameraControlRequest


def request(**payload) -> SimulationCameraControlRequest:
    return SimulationCameraControlRequest.model_validate(payload)


def test_default_front_camera_is_upright_and_looks_towards_positive_y():
    controller = OrbitCameraController()
    state = controller.state()
    rotation = Rotation.from_quat(controller.pose[3:])

    assert state.preset == "front"
    assert state.position_m == pytest.approx((0.35, -1.65, 0.42))
    assert rotation.apply((0.0, 0.0, -1.0)) == pytest.approx((0.0, 1.0, 0.0))
    assert rotation.apply((0.0, 1.0, 0.0)) == pytest.approx((0.0, 0.0, 1.0))


def test_five_presets_and_orbit_zoom_limits_are_deterministic():
    controller = OrbitCameraController()
    expected = {
        "front": (0.0, 0.0),
        "left": (-90.0, 0.0),
        "right": (90.0, 0.0),
        "top": (0.0, 82.0),
        "isometric": (38.0, 28.0),
    }
    for preset, angles in expected.items():
        state = controller.apply(request(action="preset", preset=preset))
        assert state.preset == preset
        assert (state.yaw_deg, state.pitch_deg) == angles

    for _ in range(10):
        state = controller.apply(
            request(action="orbit", yaw_delta_deg=30.0, pitch_delta_deg=30.0)
        )
    assert -180.0 <= state.yaw_deg <= 180.0
    assert state.pitch_deg == 85.0

    for _ in range(20):
        state = controller.apply(request(action="zoom", distance_delta_m=-0.4))
    assert state.distance_m == 0.75


def test_pan_moves_bounded_orbit_target_in_camera_plane():
    controller = OrbitCameraController()
    initial = np.asarray(controller.state().target_m)
    state = controller.apply(
        request(
            action="pan",
            pan_right_delta_m=0.1,
            pan_up_delta_m=0.1,
        )
    )

    assert state.preset == "custom"
    assert not np.allclose(np.asarray(state.target_m), initial)
    assert state.target_m[0] == pytest.approx(initial[0] + 0.1)
    assert state.target_m[2] == pytest.approx(initial[2] + 0.1)
