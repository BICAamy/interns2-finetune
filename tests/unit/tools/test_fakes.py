from __future__ import annotations

import unittest

from agent.tools.puncture_planner import (
    FakePlannerOutcome,
    FakePuncturePlannerClient,
    PuncturePlannerClient,
)
from agent.tools.robot import FakeRobotController, FakeRobotOutcome, RobotController
from surgical_contracts import (
    ErrorCode,
    MoveRelativeRequest,
    MoveToEntryRequest,
    PlanPunctureRequest,
    PlannerStatus,
    Point3D,
    ToolStatus,
    MotionState,
)


class FakeToolTests(unittest.TestCase):
    def test_fakes_implement_runtime_checkable_interfaces(self):
        self.assertIsInstance(FakeRobotController(), RobotController)
        self.assertIsInstance(FakePuncturePlannerClient(), PuncturePlannerClient)

    def test_fake_robot_records_and_applies_movement(self):
        robot = FakeRobotController(initial_position=Point3D(x=0, y=0, z=0))
        entry_result = robot.move_to_entry(
            MoveToEntryRequest(
                command_id="cmd-entry",
                entry_point=Point3D(x=10, y=20, z=30),
            )
        )
        relative_result = robot.move_relative(
            MoveRelativeRequest(
                command_id="cmd-relative",
                translation_mm=(0, 0, 5),
            )
        )

        self.assertTrue(entry_result.reached)
        self.assertTrue(relative_result.completed)
        self.assertEqual(relative_result.final_tcp_position.as_tuple(), (10.0, 20.0, 35.0))
        self.assertEqual(len(robot.move_to_entry_calls), 1)
        self.assertEqual(len(robot.move_relative_calls), 1)

    def test_fake_robot_can_simulate_unreachable_and_timeout(self):
        unreachable = FakeRobotController(
            initial_position=Point3D(x=0, y=0, z=0),
            move_to_entry_outcome=FakeRobotOutcome.UNREACHABLE,
        ).move_to_entry(
            MoveToEntryRequest(
                command_id="cmd-unreachable",
                entry_point=Point3D(x=10, y=20, z=30),
            )
        )
        timed_out = FakeRobotController(
            move_relative_outcome=FakeRobotOutcome.TIMEOUT,
        ).move_relative(
            MoveRelativeRequest(
                command_id="cmd-timeout",
                translation_mm=(0, 0, 5),
            )
        )

        self.assertEqual(unreachable.error_code, ErrorCode.OUT_OF_WORKSPACE)
        self.assertEqual(timed_out.status, ToolStatus.TIMED_OUT)
        self.assertEqual(timed_out.error_code, ErrorCode.ROBOT_TIMEOUT)

    def test_estop_remains_latched_when_movement_is_rejected(self):
        robot = FakeRobotController()
        robot.emergency_stop()

        result = robot.move_relative(
            MoveRelativeRequest(
                command_id="cmd-estop",
                translation_mm=(0, 0, 5),
            )
        )

        self.assertEqual(result.error_code, ErrorCode.ESTOP_ACTIVE)
        self.assertTrue(robot.get_state().estop)
        self.assertEqual(robot.get_state().motion_state, MotionState.ESTOP)

    def test_fake_planner_records_non_executable_preview(self):
        planner = FakePuncturePlannerClient()
        result = planner.plan(
            PlanPunctureRequest(
                request_id="plan-1",
                command_id="cmd-1",
                entry_point=Point3D(x=1, y=2, z=3),
                target_point=Point3D(x=4, y=5, z=6),
            )
        )

        self.assertEqual(planner.call_count, 1)
        self.assertEqual(result.status, PlannerStatus.SUCCESS)
        self.assertFalse(result.executable)

    def test_fake_planner_can_simulate_timeout(self):
        planner = FakePuncturePlannerClient(outcome=FakePlannerOutcome.TIMEOUT)
        result = planner.plan(
            PlanPunctureRequest(
                request_id="plan-timeout",
                command_id="cmd-timeout",
                entry_point=Point3D(x=1, y=2, z=3),
                target_point=Point3D(x=4, y=5, z=6),
            )
        )

        self.assertEqual(result.status, PlannerStatus.TIMED_OUT)
        self.assertEqual(result.error_code, ErrorCode.PLANNER_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
