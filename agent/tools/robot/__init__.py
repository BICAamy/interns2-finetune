"""Robot controller interfaces and test doubles."""

from .fake_controller import FakeRobotController, FakeRobotOutcome
from .http_controller import (
    RobotRuntimeClientError,
    RobotRuntimeHTTPController,
    RobotRuntimeProtocolError,
    RobotRuntimeTimeoutError,
    RobotRuntimeUnavailableError,
    RobotSimulationClientError,
    RobotSimulationHTTPController,
    RobotSimulationProtocolError,
    RobotSimulationTimeoutError,
    RobotSimulationUnavailableError,
)
from .interface import RobotController

__all__ = [
    "FakeRobotController",
    "FakeRobotOutcome",
    "RobotController",
    "RobotRuntimeClientError",
    "RobotRuntimeHTTPController",
    "RobotRuntimeProtocolError",
    "RobotRuntimeTimeoutError",
    "RobotRuntimeUnavailableError",
    "RobotSimulationClientError",
    "RobotSimulationHTTPController",
    "RobotSimulationProtocolError",
    "RobotSimulationTimeoutError",
    "RobotSimulationUnavailableError",
]
