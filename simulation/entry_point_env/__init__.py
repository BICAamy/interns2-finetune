"""Continuous entry-point positioning environment.

The deterministic controller and configuration types are importable without a
SOFA installation. ``EntryPointReachEnv`` is loaded lazily because SofaPython3
is only available inside the simulation image.
"""

from .camera_controller import OrbitCameraController, camera_pose, camera_position

from .config import (
    DEFAULT_CONFIG_PATH,
    E05ProRobotConfig,
    EntryPointEnvConfig,
    ToolTransformConfig,
    WorkspaceBounds,
)
from .controller import (
    ContinuousTrajectoryController,
    InvalidMotionCommand,
    SimulationStep,
    UnreachableTargetError,
    WorkspaceViolationError,
)
from .kinematics import E05ProKinematics, InverseKinematicsError

__all__ = [
    "OrbitCameraController",
    "camera_pose",
    "camera_position",
    "DEFAULT_CONFIG_PATH",
    "ContinuousTrajectoryController",
    "E05ProKinematics",
    "E05ProRobotConfig",
    "EntryPointEnvConfig",
    "EntryPointReachEnv",
    "InverseKinematicsError",
    "InvalidMotionCommand",
    "SimulationStep",
    "ToolTransformConfig",
    "UnreachableTargetError",
    "WorkspaceBounds",
    "WorkspaceViolationError",
]


def __getattr__(name: str):
    if name == "EntryPointReachEnv":
        from .environment import EntryPointReachEnv

        return EntryPointReachEnv
    raise AttributeError(name)
