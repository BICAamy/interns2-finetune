"""Deterministic Z-up orbit camera for the E05-Pro scene."""

from __future__ import annotations

import time

import numpy as np
from scipy.spatial.transform import Rotation

from surgical_contracts import (
    CameraControlAction,
    CameraPreset,
    SimulationCameraControlRequest,
    SimulationCameraState,
)


DEFAULT_CAMERA_TARGET_M = np.asarray((0.35, 0.0, 0.42), dtype=np.float64)
DEFAULT_CAMERA_DISTANCE_M = 1.65
MIN_CAMERA_DISTANCE_M = 0.75
MAX_CAMERA_DISTANCE_M = 3.5
MIN_CAMERA_PITCH_DEG = -75.0
MAX_CAMERA_PITCH_DEG = 85.0

_TARGET_LOW_M = np.asarray((-0.4, -0.8, -0.2), dtype=np.float64)
_TARGET_HIGH_M = np.asarray((1.1, 0.8, 1.2), dtype=np.float64)

_PRESETS: dict[CameraPreset, tuple[float, float, float]] = {
    CameraPreset.FRONT: (0.0, 0.0, 1.65),
    CameraPreset.LEFT: (-90.0, 0.0, 1.65),
    CameraPreset.RIGHT: (90.0, 0.0, 1.65),
    CameraPreset.TOP: (0.0, 82.0, 1.75),
    CameraPreset.ISOMETRIC: (38.0, 28.0, 1.85),
}


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _wrap_yaw(value: float) -> float:
    wrapped = (float(value) + 180.0) % 360.0 - 180.0
    return 180.0 if wrapped == -180.0 else wrapped


def camera_position(
    target_m: np.ndarray,
    yaw_deg: float,
    pitch_deg: float,
    distance_m: float,
) -> np.ndarray:
    """Return an orbit position; yaw=0 is the upright front view from -Y."""

    yaw = np.deg2rad(yaw_deg)
    pitch = np.deg2rad(pitch_deg)
    offset = np.asarray(
        (
            np.sin(yaw) * np.cos(pitch),
            -np.cos(yaw) * np.cos(pitch),
            np.sin(pitch),
        ),
        dtype=np.float64,
    )
    return np.asarray(target_m, dtype=np.float64) + float(distance_m) * offset


def camera_pose(position_m: np.ndarray, target_m: np.ndarray) -> np.ndarray:
    """Build a SOFA pose whose screen-up direction follows world +Z."""

    position = np.asarray(position_m, dtype=np.float64)
    target = np.asarray(target_m, dtype=np.float64)
    forward = target - position
    norm = float(np.linalg.norm(forward))
    if norm <= 1e-9:
        raise ValueError("camera position and target must be different")
    forward /= norm
    local_z = -forward
    desired_up = np.asarray((0.0, 0.0, 1.0), dtype=np.float64)
    local_y = desired_up - np.dot(desired_up, local_z) * local_z
    if float(np.linalg.norm(local_y)) <= 1e-6:
        local_y = np.asarray((0.0, 1.0, 0.0), dtype=np.float64)
        local_y -= np.dot(local_y, local_z) * local_z
    local_y /= np.linalg.norm(local_y)
    local_x = np.cross(local_y, local_z)
    local_x /= np.linalg.norm(local_x)
    orientation = Rotation.from_matrix(
        np.column_stack((local_x, local_y, local_z))
    ).as_quat()
    return np.concatenate((position, orientation))


class OrbitCameraController:
    """Own bounded orbit coordinates independently from SOFA/OpenGL."""

    def __init__(self) -> None:
        self._target_m = DEFAULT_CAMERA_TARGET_M.copy()
        self._yaw_deg = 0.0
        self._pitch_deg = 0.0
        self._distance_m = DEFAULT_CAMERA_DISTANCE_M
        self._preset: CameraPreset | str = CameraPreset.FRONT
        self._updated_at_ms = _now_ms()

    @property
    def pose(self) -> np.ndarray:
        return camera_pose(self.position_m, self._target_m)

    @property
    def position_m(self) -> np.ndarray:
        return camera_position(
            self._target_m,
            self._yaw_deg,
            self._pitch_deg,
            self._distance_m,
        )

    def state(self) -> SimulationCameraState:
        return SimulationCameraState(
            preset=self._preset,
            yaw_deg=self._yaw_deg,
            pitch_deg=self._pitch_deg,
            distance_m=self._distance_m,
            target_m=tuple(float(value) for value in self._target_m),
            position_m=tuple(float(value) for value in self.position_m),
            updated_at_ms=self._updated_at_ms,
        )

    def apply(
        self,
        request: SimulationCameraControlRequest,
    ) -> SimulationCameraState:
        if request.action == CameraControlAction.PRESET:
            preset = request.preset
            if preset is None:  # guarded by the shared contract
                raise ValueError("preset action requires a preset")
            yaw, pitch, distance = _PRESETS[preset]
            self._target_m = DEFAULT_CAMERA_TARGET_M.copy()
            self._yaw_deg = yaw
            self._pitch_deg = pitch
            self._distance_m = distance
            self._preset = preset
        elif request.action == CameraControlAction.ORBIT:
            self._yaw_deg = _wrap_yaw(
                self._yaw_deg + float(request.yaw_delta_deg or 0.0)
            )
            self._pitch_deg = float(
                np.clip(
                    self._pitch_deg + float(request.pitch_delta_deg or 0.0),
                    MIN_CAMERA_PITCH_DEG,
                    MAX_CAMERA_PITCH_DEG,
                )
            )
            self._preset = "custom"
        elif request.action == CameraControlAction.ZOOM:
            self._distance_m = float(
                np.clip(
                    self._distance_m + float(request.distance_delta_m or 0.0),
                    MIN_CAMERA_DISTANCE_M,
                    MAX_CAMERA_DISTANCE_M,
                )
            )
            self._preset = "custom"
        elif request.action == CameraControlAction.PAN:
            rotation = Rotation.from_quat(self.pose[3:]).as_matrix()
            right = rotation[:, 0]
            up = rotation[:, 1]
            self._target_m = np.clip(
                self._target_m
                + right * float(request.pan_right_delta_m or 0.0)
                + up * float(request.pan_up_delta_m or 0.0),
                _TARGET_LOW_M,
                _TARGET_HIGH_M,
            )
            self._preset = "custom"
        self._updated_at_ms = _now_ms()
        return self.state()
