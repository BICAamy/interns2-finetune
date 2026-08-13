from __future__ import annotations

import unittest

from agent.core import AgentTaskState, SurgicalTaskOrchestrator
from agent.tools.puncture_planner import (
    FakePlannerOutcome,
    FakePuncturePlannerClient,
)
from agent.tools.robot import FakeRobotController, FakeRobotOutcome
from surgical_contracts import (
    Axis,
    CommandIntent,
    Direction,
    ErrorCode,
    ParsedCommand,
    Point3D,
    RelativeMotion,
)


def puncture_command(command_id: str = "cmd-puncture") -> ParsedCommand:
    return ParsedCommand(
        command_id=command_id,
        intent=CommandIntent.PUNCTURE,
        entry_point=Point3D(x=10, y=20, z=30),
        target_point=Point3D(x=10, y=20, z=60),
    )


class OrchestratorInvariantTests(unittest.TestCase):
    def test_failed_entry_movement_never_calls_planner(self):
        robot = FakeRobotController(
            move_to_entry_outcome=FakeRobotOutcome.UNREACHABLE
        )
        planner = FakePuncturePlannerClient()

        result = SurgicalTaskOrchestrator(robot, planner).execute(puncture_command())

        self.assertEqual(result.final_state, AgentTaskState.FAILED)
        self.assertEqual(result.error_code, ErrorCode.OUT_OF_WORKSPACE)
        self.assertEqual(planner.call_count, 0)

    def test_relative_movement_never_calls_planner(self):
        robot = FakeRobotController()
        planner = FakePuncturePlannerClient()
        command = ParsedCommand(
            command_id="cmd-relative",
            intent=CommandIntent.MOVE_RELATIVE,
            relative_motion=RelativeMotion(
                axis=Axis.Z,
                direction=Direction.POSITIVE,
                distance_mm=5,
            ),
        )

        result = SurgicalTaskOrchestrator(robot, planner).execute(command)

        self.assertEqual(result.final_state, AgentTaskState.COMPLETED)
        self.assertEqual(planner.call_count, 0)
        self.assertEqual(len(robot.move_relative_calls), 1)

    def test_move_to_entry_never_calls_planner(self):
        robot = FakeRobotController()
        planner = FakePuncturePlannerClient()
        command = ParsedCommand(
            command_id="cmd-entry-only",
            intent=CommandIntent.MOVE_TO_ENTRY,
            entry_point=Point3D(x=10, y=20, z=30),
        )

        result = SurgicalTaskOrchestrator(robot, planner).execute(command)

        self.assertEqual(result.final_state, AgentTaskState.COMPLETED)
        self.assertEqual(planner.call_count, 0)
        self.assertEqual(len(robot.move_to_entry_calls), 1)

    def test_successful_puncture_preparation_calls_planner_once(self):
        robot = FakeRobotController()
        planner = FakePuncturePlannerClient()

        result = SurgicalTaskOrchestrator(robot, planner).execute(puncture_command())

        self.assertEqual(result.final_state, AgentTaskState.COMPLETED)
        self.assertEqual(planner.call_count, 1)
        self.assertFalse(result.planner_result.executable)
        self.assertIn(AgentTaskState.AT_ENTRY, result.state_history)
        self.assertIn(AgentTaskState.PATH_PLANNING, result.state_history)

    def test_planner_timeout_is_reported_after_entry_is_reached(self):
        robot = FakeRobotController()
        planner = FakePuncturePlannerClient(outcome=FakePlannerOutcome.TIMEOUT)

        result = SurgicalTaskOrchestrator(robot, planner).execute(puncture_command())

        self.assertEqual(result.final_state, AgentTaskState.FAILED)
        self.assertEqual(result.error_code, ErrorCode.PLANNER_TIMEOUT)
        self.assertEqual(planner.call_count, 1)

    def test_clarification_does_not_call_any_tool(self):
        robot = FakeRobotController()
        planner = FakePuncturePlannerClient()
        command = ParsedCommand(
            command_id="cmd-clarify",
            intent=CommandIntent.CLARIFY,
            entry_point=Point3D(x=10, y=20, z=30),
            missing_fields=["target_point"],
        )

        result = SurgicalTaskOrchestrator(robot, planner).execute(command)

        self.assertEqual(result.final_state, AgentTaskState.COMPLETED)
        self.assertEqual(robot.move_to_entry_calls, [])
        self.assertEqual(robot.move_relative_calls, [])
        self.assertEqual(planner.call_count, 0)

    def test_stop_and_estop_never_call_planner(self):
        robot = FakeRobotController()
        planner = FakePuncturePlannerClient()
        orchestrator = SurgicalTaskOrchestrator(robot, planner)

        stopped = orchestrator.execute(
            ParsedCommand(command_id="cmd-stop", intent=CommandIntent.STOP)
        )
        estopped = orchestrator.execute(
            ParsedCommand(command_id="cmd-estop", intent=CommandIntent.EMERGENCY_STOP)
        )

        self.assertEqual(stopped.final_state, AgentTaskState.STOPPED)
        self.assertEqual(estopped.final_state, AgentTaskState.ESTOP)
        self.assertEqual(robot.stop_calls, 1)
        self.assertEqual(robot.emergency_stop_calls, 1)
        self.assertEqual(planner.call_count, 0)


if __name__ == "__main__":
    unittest.main()
