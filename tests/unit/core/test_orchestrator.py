from __future__ import annotations

from threading import Event, Thread
import unittest

from agent.core import AgentTaskState, OrchestrationPolicy, SurgicalTaskOrchestrator
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
    EventPhase,
    ParsedCommand,
    Point3D,
    RelativeMotion,
    ToolName,
)


def puncture_command(command_id: str = "cmd-puncture") -> ParsedCommand:
    return ParsedCommand(
        command_id=command_id,
        intent=CommandIntent.PUNCTURE,
        entry_point=Point3D(x=10, y=20, z=30),
        target_point=Point3D(x=10, y=20, z=60),
    )


def relative_command(command_id: str = "cmd-relative", distance: float = 5) -> ParsedCommand:
    return ParsedCommand(
        command_id=command_id,
        intent=CommandIntent.MOVE_RELATIVE,
        relative_motion=RelativeMotion(
            axis=Axis.Z,
            direction=Direction.POSITIVE,
            distance_mm=distance,
        ),
    )


class BlockingRobot(FakeRobotController):
    def __init__(self) -> None:
        super().__init__()
        self.move_started = Event()
        self.release_move = Event()

    def move_to_entry(self, request):
        self.move_started.set()
        if not self.release_move.wait(timeout=3):
            raise TimeoutError("test did not release blocked movement")
        return super().move_to_entry(request)


class BlockingPreflightRobot(FakeRobotController):
    def __init__(self) -> None:
        super().__init__()
        self.get_state_started = Event()
        self.release_get_state = Event()

    def get_state(self):
        self.get_state_started.set()
        if not self.release_get_state.wait(timeout=3):
            raise TimeoutError("test did not release blocked state query")
        return super().get_state()


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

    def test_independent_tcp_error_check_blocks_planner(self):
        robot = FakeRobotController(
            post_move_state_offset_mm=(0.0, 0.0, 2.0),
            report_requested_entry_on_success=True,
        )
        planner = FakePuncturePlannerClient()
        orchestrator = SurgicalTaskOrchestrator(
            robot,
            planner,
            policy=OrchestrationPolicy(entry_tolerance_mm=1.0),
        )

        result = orchestrator.execute(puncture_command())

        self.assertEqual(result.final_state, AgentTaskState.FAILED)
        self.assertEqual(result.error_code, ErrorCode.POSITION_TOLERANCE_EXCEEDED)
        self.assertEqual(result.robot_result.position_error_mm, 0.0)
        self.assertEqual(result.verified_position_error_mm, 2.0)
        self.assertEqual(planner.call_count, 0)

    def test_relative_movement_never_calls_planner(self):
        robot = FakeRobotController()
        planner = FakePuncturePlannerClient()

        result = SurgicalTaskOrchestrator(robot, planner).execute(relative_command())

        self.assertEqual(result.final_state, AgentTaskState.COMPLETED)
        self.assertEqual(planner.call_count, 0)
        self.assertEqual(len(robot.move_relative_calls), 1)
        self.assertIn("未执行穿刺", result.message)

    def test_relative_motion_over_limit_never_moves(self):
        robot = FakeRobotController()
        planner = FakePuncturePlannerClient()

        result = SurgicalTaskOrchestrator(robot, planner).execute(
            relative_command(distance=20.1)
        )

        self.assertEqual(result.final_state, AgentTaskState.FAILED)
        self.assertEqual(result.error_code, ErrorCode.OUT_OF_WORKSPACE)
        self.assertEqual(robot.move_relative_calls, [])
        self.assertEqual(planner.call_count, 0)

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
        self.assertEqual(result.verified_position_error_mm, 0.0)
        self.assertEqual(planner.call_count, 0)
        self.assertEqual(len(robot.move_to_entry_calls), 1)
        self.assertIn("已到达入点", result.message)

    def test_successful_puncture_preparation_calls_planner_once(self):
        robot = FakeRobotController()
        planner = FakePuncturePlannerClient()

        result = SurgicalTaskOrchestrator(robot, planner).execute(puncture_command())

        self.assertEqual(result.final_state, AgentTaskState.PLAN_READY)
        self.assertEqual(planner.call_count, 1)
        self.assertFalse(result.planner_result.executable)
        self.assertIn(AgentTaskState.AT_ENTRY, result.state_history)
        self.assertIn(AgentTaskState.PATH_PLANNING, result.state_history)
        self.assertNotIn("穿刺完成", result.message)
        self.assertIn("未执行穿刺", result.message)

    def test_planner_timeout_is_a_plan_failure_after_entry(self):
        robot = FakeRobotController()
        planner = FakePuncturePlannerClient(outcome=FakePlannerOutcome.TIMEOUT)

        result = SurgicalTaskOrchestrator(robot, planner).execute(puncture_command())

        self.assertEqual(result.final_state, AgentTaskState.PLAN_FAILED)
        self.assertEqual(result.error_code, ErrorCode.PLANNER_TIMEOUT)
        self.assertEqual(planner.call_count, 1)

    def test_planner_unavailable_has_distinct_state(self):
        robot = FakeRobotController()
        planner = FakePuncturePlannerClient(outcome=FakePlannerOutcome.UNAVAILABLE)

        result = SurgicalTaskOrchestrator(robot, planner).execute(puncture_command())

        self.assertEqual(result.final_state, AgentTaskState.PLANNER_UNAVAILABLE)
        self.assertEqual(result.error_code, ErrorCode.PLANNER_UNAVAILABLE)
        self.assertEqual(planner.call_count, 1)

    def test_clarification_does_not_call_any_tool(self):
        robot = FakeRobotController()
        planner = FakePuncturePlannerClient()
        command = ParsedCommand(
            command_id="cmd-clarify",
            intent=CommandIntent.CLARIFY,
            entry_point=Point3D(x=10, y=20, z=30),
            missing_fields=["target_point"],
            needs_confirmation=True,
            summary="Please provide the target point",
        )

        result = SurgicalTaskOrchestrator(robot, planner).execute(command)

        self.assertEqual(result.final_state, AgentTaskState.CLARIFICATION_REQUIRED)
        self.assertEqual(result.tool_events, ())
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

    def test_estop_state_blocks_subsequent_motion_and_planning(self):
        robot = FakeRobotController()
        planner = FakePuncturePlannerClient()
        orchestrator = SurgicalTaskOrchestrator(robot, planner)
        orchestrator.execute(
            ParsedCommand(command_id="cmd-estop", intent=CommandIntent.EMERGENCY_STOP)
        )

        result = orchestrator.execute(puncture_command())

        self.assertEqual(result.final_state, AgentTaskState.ESTOP)
        self.assertEqual(result.error_code, ErrorCode.ESTOP_ACTIVE)
        self.assertEqual(robot.move_to_entry_calls, [])
        self.assertEqual(planner.call_count, 0)

    def test_duplicate_command_id_returns_cached_result_without_motion(self):
        robot = FakeRobotController()
        planner = FakePuncturePlannerClient()
        orchestrator = SurgicalTaskOrchestrator(robot, planner)
        command = puncture_command()

        first = orchestrator.execute(command)
        second = orchestrator.execute(command)

        self.assertFalse(first.deduplicated)
        self.assertTrue(second.deduplicated)
        self.assertEqual(second.as_dict()["final_state"], "plan_ready")
        self.assertEqual(len(robot.move_to_entry_calls), 1)
        self.assertEqual(planner.call_count, 1)

    def test_reusing_command_id_for_different_payload_is_rejected(self):
        robot = FakeRobotController()
        planner = FakePuncturePlannerClient()
        orchestrator = SurgicalTaskOrchestrator(robot, planner)
        orchestrator.execute(puncture_command("same-id"))
        changed = puncture_command("same-id").model_copy(
            update={"target_point": Point3D(x=11, y=20, z=60)}
        )

        result = orchestrator.execute(changed)

        self.assertEqual(result.final_state, AgentTaskState.FAILED)
        self.assertEqual(result.error_code, ErrorCode.COMMAND_CONFLICT)
        self.assertEqual(len(robot.move_to_entry_calls), 1)
        self.assertEqual(planner.call_count, 1)

    def test_active_command_rejects_normal_command_and_estop_blocks_planner(self):
        robot = BlockingRobot()
        planner = FakePuncturePlannerClient()
        orchestrator = SurgicalTaskOrchestrator(robot, planner)
        holder = {}

        worker = Thread(
            target=lambda: holder.setdefault(
                "result", orchestrator.execute(puncture_command("active"))
            )
        )
        worker.start()
        self.assertTrue(robot.move_started.wait(timeout=1))

        conflict = orchestrator.execute(relative_command("second"))
        estop = orchestrator.execute(
            # Safety commands must not be suppressed even if an upstream caller
            # accidentally reuses the active command ID.
            ParsedCommand(command_id="active", intent=CommandIntent.EMERGENCY_STOP)
        )
        robot.release_move.set()
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(conflict.error_code, ErrorCode.COMMAND_CONFLICT)
        self.assertEqual(robot.move_relative_calls, [])
        self.assertEqual(estop.final_state, AgentTaskState.ESTOP)
        self.assertEqual(holder["result"].final_state, AgentTaskState.ESTOP)
        self.assertEqual(planner.call_count, 0)

    def test_stop_during_preflight_blocks_the_motion_call(self):
        robot = BlockingPreflightRobot()
        planner = FakePuncturePlannerClient()
        orchestrator = SurgicalTaskOrchestrator(robot, planner)
        holder = {}
        worker = Thread(
            target=lambda: holder.setdefault(
                "result", orchestrator.execute(relative_command("active-preflight"))
            )
        )
        worker.start()
        self.assertTrue(robot.get_state_started.wait(timeout=1))

        stop = orchestrator.execute(
            ParsedCommand(command_id="stop-preflight", intent=CommandIntent.STOP)
        )
        robot.release_get_state.set()
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(stop.final_state, AgentTaskState.STOPPED)
        self.assertEqual(holder["result"].final_state, AgentTaskState.STOPPED)
        self.assertEqual(robot.move_relative_calls, [])
        self.assertEqual(planner.call_count, 0)

    def test_state_and_tool_events_are_ordered_and_serializable(self):
        result = SurgicalTaskOrchestrator(
            FakeRobotController(),
            FakePuncturePlannerClient(),
            clock_ms=lambda: 123,
        ).execute(puncture_command())

        self.assertEqual(len(result.state_events), len(result.state_history) - 1)
        self.assertEqual(
            [event.sequence for event in result.state_events],
            list(range(1, len(result.state_events) + 1)),
        )
        self.assertEqual(
            [event.tool for event in result.tool_events[::2]],
            [
                ToolName.ROBOT_GET_STATE,
                ToolName.ROBOT_MOVE_TO_ENTRY,
                ToolName.ROBOT_GET_STATE,
                ToolName.PLANNER_PLAN_PUNCTURE,
            ],
        )
        self.assertTrue(
            all(event.phase == EventPhase.STARTED for event in result.tool_events[::2])
        )
        self.assertTrue(
            all(event.phase == EventPhase.COMPLETED for event in result.tool_events[1::2])
        )
        self.assertEqual(
            len({event.event_id for event in result.tool_events}),
            len(result.tool_events),
        )
        self.assertEqual(result.as_dict()["state_events"][0]["timestamp_ms"], 123)
        combined_timestamps = sorted(
            [event.timestamp_ms for event in result.state_events]
            + [event.timestamp_ms for event in result.tool_events]
        )
        self.assertEqual(
            combined_timestamps,
            list(range(123, 123 + len(combined_timestamps))),
        )


if __name__ == "__main__":
    unittest.main()
