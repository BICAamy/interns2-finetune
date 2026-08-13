"""Robot controller interfaces and test doubles."""

from .fake_controller import FakeRobotController, FakeRobotOutcome
from .interface import RobotController

__all__ = ["FakeRobotController", "FakeRobotOutcome", "RobotController"]
