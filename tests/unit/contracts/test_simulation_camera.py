from __future__ import annotations

from pydantic import ValidationError
import pytest

from surgical_contracts import (
    CameraControlAction,
    CameraPreset,
    SimulationCameraControlRequest,
)


def test_camera_control_contract_accepts_each_view_only_action():
    orbit = SimulationCameraControlRequest(
        action=CameraControlAction.ORBIT,
        yaw_delta_deg=5.0,
        pitch_delta_deg=-2.0,
    )
    zoom = SimulationCameraControlRequest(
        action=CameraControlAction.ZOOM,
        distance_delta_m=0.1,
    )
    pan = SimulationCameraControlRequest(
        action=CameraControlAction.PAN,
        pan_right_delta_m=0.01,
        pan_up_delta_m=-0.02,
    )
    preset = SimulationCameraControlRequest(
        action=CameraControlAction.PRESET,
        preset=CameraPreset.FRONT,
    )

    assert orbit.yaw_delta_deg == 5.0
    assert zoom.distance_delta_m == 0.1
    assert pan.pan_up_delta_m == -0.02
    assert preset.preset == CameraPreset.FRONT


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "orbit"},
        {"action": "zoom", "preset": "front"},
        {"action": "preset", "yaw_delta_deg": 1.0},
        {"action": "orbit", "yaw_delta_deg": 31.0},
    ],
)
def test_camera_control_contract_rejects_missing_mixed_or_unbounded_fields(payload):
    with pytest.raises(ValidationError):
        SimulationCameraControlRequest.model_validate(payload)
