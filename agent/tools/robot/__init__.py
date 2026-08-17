"""Robot controller interfaces and test doubles."""

from .fake_controller import FakeRobotController, FakeRobotOutcome
from .http_controller import (
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
    "RobotSimulationClientError",
    "RobotSimulationHTTPController",
    "RobotSimulationProtocolError",
    "RobotSimulationTimeoutError",
    "RobotSimulationUnavailableError",
]
