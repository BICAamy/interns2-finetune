"""Deterministic Step 2 orchestrator for robot/planner test doubles."""

from __future__ import annotations

from dataclasses import dataclass

from surgical_contracts import (
    CommandIntent,
    ErrorCode,
    MoveRelativeRequest,
    MoveRelativeResult,
    MoveToEntryRequest,
    MoveToEntryResult,
    ParsedCommand,
    PlanPunctureRequest,
    PlanPunctureResult,
    PlannerStatus,
    ToolStatus,
)

from agent.tools.puncture_planner.interface import PuncturePlannerClient
from agent.tools.robot.interface import RobotController

from .state_machine import AgentTaskState, TaskStateMachine


@dataclass(frozen=True)
class OrchestrationResult:
    command_id: str
    final_state: AgentTaskState
    state_history: tuple[AgentTaskState, ...]
    robot_result: MoveToEntryResult | MoveRelativeResult | None = None
    planner_result: PlanPunctureResult | None = None
    error_code: ErrorCode | None = None
    message: str = ""


class SurgicalTaskOrchestrator:
    """Enforce tool order independently of model output."""

    def __init__(
        self,
        robot: RobotController,
        planner: PuncturePlannerClient,
    ) -> None:
        self.robot = robot
        self.planner = planner

    def execute(self, command: ParsedCommand) -> OrchestrationResult:
        machine = TaskStateMachine()
        machine.transition(AgentTaskState.VALIDATING)

        if command.intent == CommandIntent.CLARIFY:
            machine.transition(AgentTaskState.CLARIFICATION_REQUIRED)
            machine.transition(AgentTaskState.COMPLETED)
            return self._result(machine, command, message="Clarification is required")

        if command.intent == CommandIntent.STOP:
            self.robot.stop()
            machine.transition(AgentTaskState.STOPPED)
            return self._result(machine, command, message="Robot stop requested")

        if command.intent == CommandIntent.EMERGENCY_STOP:
            self.robot.emergency_stop()
            machine.transition(AgentTaskState.ESTOP)
            return self._result(machine, command, message="Robot emergency stop requested")

        if command.intent == CommandIntent.MOVE_RELATIVE:
            return self._execute_relative(command, machine)

        if command.intent in {CommandIntent.MOVE_TO_ENTRY, CommandIntent.PUNCTURE}:
            return self._execute_entry_task(command, machine)

        machine.transition(AgentTaskState.FAILED)
        return self._result(
            machine,
            command,
            error_code=ErrorCode.INVALID_COMMAND_SCHEMA,
            message="Unsupported command intent",
        )

    def _execute_relative(
        self,
        command: ParsedCommand,
        machine: TaskStateMachine,
    ) -> OrchestrationResult:
        assert command.relative_motion is not None
        machine.transition(AgentTaskState.EXECUTING_RELATIVE)
        request = MoveRelativeRequest(
            command_id=command.command_id,
            translation_mm=command.relative_motion.translation_mm(),
            frame=command.relative_motion.frame,
        )
        result = self.robot.move_relative(request)
        if result.status != ToolStatus.SUCCESS or not result.completed:
            machine.transition(AgentTaskState.FAILED)
            return self._result(
                machine,
                command,
                robot_result=result,
                error_code=result.error_code,
                message=result.message,
            )
        machine.transition(AgentTaskState.COMPLETED)
        return self._result(
            machine,
            command,
            robot_result=result,
            message=result.message,
        )

    def _execute_entry_task(
        self,
        command: ParsedCommand,
        machine: TaskStateMachine,
    ) -> OrchestrationResult:
        assert command.entry_point is not None
        machine.transition(AgentTaskState.MOVING_TO_ENTRY)
        move_result = self.robot.move_to_entry(
            MoveToEntryRequest(
                command_id=command.command_id,
                entry_point=command.entry_point,
            )
        )
        if move_result.status != ToolStatus.SUCCESS or not move_result.reached:
            machine.transition(AgentTaskState.FAILED)
            return self._result(
                machine,
                command,
                robot_result=move_result,
                error_code=move_result.error_code or ErrorCode.ENTRY_NOT_REACHED,
                message=move_result.message,
            )

        machine.transition(AgentTaskState.AT_ENTRY)
        if command.intent == CommandIntent.MOVE_TO_ENTRY:
            machine.transition(AgentTaskState.COMPLETED)
            return self._result(
                machine,
                command,
                robot_result=move_result,
                message=move_result.message,
            )

        assert command.target_point is not None
        machine.transition(AgentTaskState.PATH_PLANNING)
        plan_result = self.planner.plan(
            PlanPunctureRequest(
                request_id=command.command_id,
                command_id=command.command_id,
                entry_point=command.entry_point,
                target_point=command.target_point,
            )
        )
        if plan_result.status != PlannerStatus.SUCCESS:
            machine.transition(AgentTaskState.FAILED)
            return self._result(
                machine,
                command,
                robot_result=move_result,
                planner_result=plan_result,
                error_code=plan_result.error_code,
                message=plan_result.message,
            )

        machine.transition(AgentTaskState.PLAN_READY)
        machine.transition(AgentTaskState.COMPLETED)
        return self._result(
            machine,
            command,
            robot_result=move_result,
            planner_result=plan_result,
            message="Entry reached and mock planning result is ready; no puncture executed",
        )

    @staticmethod
    def _result(
        machine: TaskStateMachine,
        command: ParsedCommand,
        *,
        robot_result: MoveToEntryResult | MoveRelativeResult | None = None,
        planner_result: PlanPunctureResult | None = None,
        error_code: ErrorCode | None = None,
        message: str,
    ) -> OrchestrationResult:
        return OrchestrationResult(
            command_id=command.command_id,
            final_state=machine.state,
            state_history=machine.history,
            robot_result=robot_result,
            planner_result=planner_result,
            error_code=error_code,
            message=message,
        )
