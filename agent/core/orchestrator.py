"""Deterministic state machine and tool orchestration for surgical tasks."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
from math import sqrt
from threading import RLock
import time
from typing import Any, Callable, TypeVar

from surgical_contracts import (
    CommandIntent,
    ErrorCode,
    EventPhase,
    MotionState,
    MoveRelativeRequest,
    MoveRelativeResult,
    MoveToEntryRequest,
    MoveToEntryResult,
    ParsedCommand,
    PlanPunctureRequest,
    PlanPunctureResult,
    PlannerStatus,
    RobotState,
    RuntimeMode,
    ToolEvent,
    ToolName,
    ToolStatus,
)

from agent.tools.puncture_planner.interface import PuncturePlannerClient
from agent.tools.robot.interface import RobotController

from .state_machine import AgentTaskState, StateTransitionEvent, TaskStateMachine


ToolResult = TypeVar("ToolResult")


@dataclass(frozen=True)
class OrchestrationPolicy:
    """Non-model safety policy applied to every command."""

    entry_tolerance_mm: float = 1.0
    max_relative_translation_mm: float = 20.0
    move_speed_mm_s: float = 5.0
    max_speed_mm_s: float = 10.0
    expected_runtime_mode: RuntimeMode = RuntimeMode.SIMULATION

    def __post_init__(self) -> None:
        if self.entry_tolerance_mm <= 0:
            raise ValueError("entry_tolerance_mm must be greater than zero")
        if self.max_relative_translation_mm <= 0:
            raise ValueError("max_relative_translation_mm must be greater than zero")
        if self.move_speed_mm_s <= 0:
            raise ValueError("move_speed_mm_s must be greater than zero")
        if self.max_speed_mm_s <= 0:
            raise ValueError("max_speed_mm_s must be greater than zero")
        if self.move_speed_mm_s > self.max_speed_mm_s:
            raise ValueError("move_speed_mm_s cannot exceed max_speed_mm_s")


@dataclass(frozen=True)
class OrchestrationResult:
    command_id: str
    final_state: AgentTaskState
    state_history: tuple[AgentTaskState, ...]
    state_events: tuple[StateTransitionEvent, ...] = ()
    tool_events: tuple[ToolEvent, ...] = ()
    robot_result: MoveToEntryResult | MoveRelativeResult | None = None
    robot_state: RobotState | None = None
    planner_result: PlanPunctureResult | None = None
    verified_position_error_mm: float | None = None
    error_code: ErrorCode | None = None
    message: str = ""
    deduplicated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "final_state": self.final_state.value,
            "state_history": [state.value for state in self.state_history],
            "state_events": [event.as_dict() for event in self.state_events],
            "tool_events": [event.model_dump(mode="json") for event in self.tool_events],
            "robot_result": _json_value(self.robot_result),
            "robot_state": _json_value(self.robot_state),
            "planner_result": _json_value(self.planner_result),
            "verified_position_error_mm": self.verified_position_error_mm,
            "error_code": self.error_code.value if self.error_code else None,
            "message": self.message,
            "deduplicated": self.deduplicated,
        }


class SurgicalTaskOrchestrator:
    """Enforce tool order independently of InternS2 output.

    This runtime can move to an entry point and request a non-executable path
    preview.  It deliberately has no operation that executes a puncture.
    """

    def __init__(
        self,
        robot: RobotController,
        planner: PuncturePlannerClient,
        *,
        policy: OrchestrationPolicy | None = None,
        clock_ms: Callable[[], int] | None = None,
        event_sink: Callable[[ToolEvent], None] | None = None,
    ) -> None:
        self.robot = robot
        self.planner = planner
        self.policy = policy or OrchestrationPolicy()
        self._lock = RLock()
        self._clock_source_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self._last_timestamp_ms = -1
        self._event_sink = event_sink
        self._active_command_id: str | None = None
        self._interrupts: dict[str, AgentTaskState] = {}
        self._fingerprints: dict[str, str] = {}
        self._completed: dict[str, OrchestrationResult] = {}

    @property
    def active_command_id(self) -> str | None:
        with self._lock:
            return self._active_command_id

    def _clock_ms(self) -> int:
        """Return an auditable millisecond timestamp that is strictly increasing.

        Several state changes can legitimately happen within one wall-clock
        millisecond. Sequence already defines their order, while this logical
        millisecond projection also makes the ordering unambiguous to clients
        that compare only ``timestamp_ms``.
        """

        with self._lock:
            source_timestamp = int(self._clock_source_ms())
            timestamp = max(source_timestamp, self._last_timestamp_ms + 1)
            self._last_timestamp_ms = timestamp
            return timestamp

    def execute(self, command: ParsedCommand) -> OrchestrationResult:
        """Execute one validated command with idempotency and arbitration."""

        fingerprint = self._fingerprint(command)
        is_interrupt = command.intent in {
            CommandIntent.STOP,
            CommandIntent.EMERGENCY_STOP,
        }

        with self._lock:
            if is_interrupt:
                if self._active_command_id is not None:
                    current = self._interrupts.get(self._active_command_id)
                    requested = (
                        AgentTaskState.ESTOP
                        if command.intent == CommandIntent.EMERGENCY_STOP
                        else AgentTaskState.STOPPED
                    )
                    if current != AgentTaskState.ESTOP:
                        self._interrupts[self._active_command_id] = requested
            else:
                cached = self._completed.get(command.command_id)
                if cached is not None:
                    if self._fingerprints[command.command_id] == fingerprint:
                        return replace(cached, deduplicated=True)
                    return self._conflict_result(
                        command,
                        "command_id 已用于其他命令，拒绝执行。",
                    )
                if self._active_command_id is not None:
                    detail = (
                        "该 command_id 正在执行，拒绝重复运动。"
                        if self._active_command_id == command.command_id
                        else f"命令 {self._active_command_id} 正在执行，拒绝并发运动。"
                    )
                    return self._conflict_result(command, detail)
                self._active_command_id = command.command_id

        result: OrchestrationResult
        try:
            result = self._execute_fresh(command)
        except Exception as exc:  # pragma: no cover - last-resort process boundary
            result = self._unexpected_failure(command, exc)

        with self._lock:
            if not is_interrupt:
                self._remember(command.command_id, fingerprint, result)
                if self._active_command_id == command.command_id:
                    self._active_command_id = None
                self._interrupts.pop(command.command_id, None)
        return result

    def _execute_fresh(self, command: ParsedCommand) -> OrchestrationResult:
        machine = TaskStateMachine(clock_ms=self._clock_ms)
        tool_events: list[ToolEvent] = []
        machine.transition(AgentTaskState.PARSING)
        machine.transition(AgentTaskState.VALIDATING)

        if command.intent == CommandIntent.CLARIFY:
            machine.transition(AgentTaskState.CLARIFICATION_REQUIRED)
            return self._result(
                machine,
                command,
                tool_events,
                message=command.summary or "需要用户补充或确认信息，未调用任何工具。",
            )

        if command.intent in {CommandIntent.STOP, CommandIntent.EMERGENCY_STOP}:
            return self._execute_interrupt(command, machine, tool_events)

        interrupted = self._interrupted_result(command, machine, tool_events)
        if interrupted is not None:
            return interrupted

        state_or_result = self._preflight(command, machine, tool_events)
        if isinstance(state_or_result, OrchestrationResult):
            return state_or_result

        # A stop/estop may arrive while get_state is in flight. Re-check at the
        # exact boundary before choosing any motion operation.
        interrupted = self._interrupted_result(command, machine, tool_events)
        if interrupted is not None:
            return interrupted

        if command.intent == CommandIntent.MOVE_RELATIVE:
            return self._execute_relative(command, machine, tool_events)

        if command.intent in {CommandIntent.MOVE_TO_ENTRY, CommandIntent.PUNCTURE}:
            return self._execute_entry_task(command, machine, tool_events)

        machine.transition(AgentTaskState.FAILED)
        return self._result(
            machine,
            command,
            tool_events,
            error_code=ErrorCode.INVALID_COMMAND_SCHEMA,
            message="不支持的命令意图，未调用运动工具。",
        )

    def _execute_interrupt(
        self,
        command: ParsedCommand,
        machine: TaskStateMachine,
        tool_events: list[ToolEvent],
    ) -> OrchestrationResult:
        emergency = command.intent == CommandIntent.EMERGENCY_STOP
        tool = ToolName.ROBOT_EMERGENCY_STOP if emergency else ToolName.ROBOT_STOP
        operation = (
            (lambda: self.robot.emergency_stop(command.command_id))
            if emergency
            else (lambda: self.robot.stop(command.command_id))
        )
        try:
            state = self._call_tool(
                command.command_id,
                tool,
                {},
                operation,
                tool_events,
            )
        except Exception as exc:
            machine.transition(AgentTaskState.FAILED)
            return self._result(
                machine,
                command,
                tool_events,
                error_code=_robot_exception_code(exc),
                message=f"{'急停' if emergency else '停止'}工具调用失败：{type(exc).__name__}",
            )

        if emergency:
            if not state.estop and state.motion_state != MotionState.ESTOP:
                machine.transition(AgentTaskState.FAILED)
                return self._result(
                    machine,
                    command,
                    tool_events,
                    robot_state=state,
                    error_code=ErrorCode.INTERNAL_ERROR,
                    message="急停工具返回后未检测到急停锁定状态。",
                )
            machine.transition(AgentTaskState.ESTOP)
            return self._result(
                machine,
                command,
                tool_events,
                robot_state=state,
                error_code=ErrorCode.ESTOP_ACTIVE,
                message="机械臂急停已锁定；未调用路径规划，未执行穿刺。",
            )

        if state.motion_state != MotionState.STOPPED:
            machine.transition(AgentTaskState.FAILED)
            return self._result(
                machine,
                command,
                tool_events,
                robot_state=state,
                error_code=ErrorCode.INTERNAL_ERROR,
                message="停止工具返回后机械臂未进入 stopped 状态。",
            )
        machine.transition(AgentTaskState.STOPPED)
        return self._result(
            machine,
            command,
            tool_events,
            robot_state=state,
            message="机械臂已停止；未调用路径规划，未执行穿刺。",
        )

    def _preflight(
        self,
        command: ParsedCommand,
        machine: TaskStateMachine,
        tool_events: list[ToolEvent],
    ) -> RobotState | OrchestrationResult:
        try:
            state = self._call_tool(
                command.command_id,
                ToolName.ROBOT_GET_STATE,
                {},
                self.robot.get_state,
                tool_events,
            )
        except Exception as exc:
            machine.transition(AgentTaskState.FAILED)
            return self._result(
                machine,
                command,
                tool_events,
                error_code=_robot_exception_code(exc),
                message=f"读取机械臂状态失败：{type(exc).__name__}",
            )

        if state.estop or state.motion_state == MotionState.ESTOP:
            machine.transition(AgentTaskState.ESTOP)
            return self._result(
                machine,
                command,
                tool_events,
                robot_state=state,
                error_code=ErrorCode.ESTOP_ACTIVE,
                message="机械臂处于急停状态，拒绝运动与路径规划。",
            )
        if state.mode != self.policy.expected_runtime_mode:
            machine.transition(AgentTaskState.FAILED)
            return self._result(
                machine,
                command,
                tool_events,
                robot_state=state,
                error_code=ErrorCode.OPERATION_NOT_ENABLED,
                message=(
                    f"运行模式不匹配：期望 {self.policy.expected_runtime_mode.value}，"
                    f"实际 {state.mode.value}。"
                ),
            )
        if state.motion_state == MotionState.MOVING:
            machine.transition(AgentTaskState.FAILED)
            return self._result(
                machine,
                command,
                tool_events,
                robot_state=state,
                error_code=ErrorCode.COMMAND_CONFLICT,
                message="机械臂已在运动，拒绝启动新的普通命令。",
            )
        if state.active_command_id not in {None, command.command_id}:
            machine.transition(AgentTaskState.FAILED)
            return self._result(
                machine,
                command,
                tool_events,
                robot_state=state,
                error_code=ErrorCode.COMMAND_CONFLICT,
                message=f"机械臂工具仍有活动命令 {state.active_command_id}，拒绝并发运动。",
            )
        return state

    def _execute_relative(
        self,
        command: ParsedCommand,
        machine: TaskStateMachine,
        tool_events: list[ToolEvent],
    ) -> OrchestrationResult:
        assert command.relative_motion is not None
        translation = command.relative_motion.translation_mm()
        magnitude = sqrt(sum(float(value) ** 2 for value in translation))
        if magnitude > self.policy.max_relative_translation_mm:
            machine.transition(AgentTaskState.FAILED)
            return self._result(
                machine,
                command,
                tool_events,
                error_code=ErrorCode.OUT_OF_WORKSPACE,
                message=(
                    f"相对位移 {magnitude:.3f} mm 超过单次安全上限 "
                    f"{self.policy.max_relative_translation_mm:.3f} mm。"
                ),
            )

        machine.transition(AgentTaskState.EXECUTING_RELATIVE)
        request = MoveRelativeRequest(
            command_id=command.command_id,
            translation_mm=translation,
            frame=command.relative_motion.frame,
            speed_mm_s=self.policy.move_speed_mm_s,
        )
        try:
            result = self._call_tool(
                command.command_id,
                ToolName.ROBOT_MOVE_RELATIVE,
                request,
                lambda: self.robot.move_relative(request),
                tool_events,
            )
        except Exception as exc:
            machine.transition(AgentTaskState.FAILED)
            return self._result(
                machine,
                command,
                tool_events,
                error_code=_robot_exception_code(exc),
                message=f"相对运动工具调用失败：{type(exc).__name__}",
            )

        interrupted = self._interrupted_result(
            command,
            machine,
            tool_events,
            robot_result=result,
        )
        if interrupted is not None:
            return interrupted
        if result.command_id != command.command_id:
            machine.transition(AgentTaskState.FAILED)
            return self._result(
                machine,
                command,
                tool_events,
                robot_result=result,
                error_code=ErrorCode.INTERNAL_ERROR,
                message="相对运动工具返回了不匹配的 command_id。",
            )
        if result.status != ToolStatus.SUCCESS or not result.completed:
            machine.transition(AgentTaskState.FAILED)
            return self._result(
                machine,
                command,
                tool_events,
                robot_result=result,
                error_code=result.error_code or ErrorCode.INTERNAL_ERROR,
                message=result.message,
            )
        machine.transition(AgentTaskState.COMPLETED)
        return self._result(
            machine,
            command,
            tool_events,
            robot_result=result,
            message="相对运动已完成；未调用路径规划，未执行穿刺。",
        )

    def _execute_entry_task(
        self,
        command: ParsedCommand,
        machine: TaskStateMachine,
        tool_events: list[ToolEvent],
    ) -> OrchestrationResult:
        assert command.entry_point is not None
        machine.transition(AgentTaskState.MOVING_TO_ENTRY)
        request = MoveToEntryRequest(
            command_id=command.command_id,
            entry_point=command.entry_point,
            speed_mm_s=self.policy.move_speed_mm_s,
        )
        try:
            move_result = self._call_tool(
                command.command_id,
                ToolName.ROBOT_MOVE_TO_ENTRY,
                request,
                lambda: self.robot.move_to_entry(request),
                tool_events,
            )
        except Exception as exc:
            machine.transition(AgentTaskState.FAILED)
            return self._result(
                machine,
                command,
                tool_events,
                error_code=_robot_exception_code(exc),
                message=f"入点运动工具调用失败：{type(exc).__name__}",
            )

        interrupted = self._interrupted_result(
            command,
            machine,
            tool_events,
            robot_result=move_result,
        )
        if interrupted is not None:
            return interrupted
        if move_result.command_id != command.command_id:
            machine.transition(AgentTaskState.FAILED)
            return self._result(
                machine,
                command,
                tool_events,
                robot_result=move_result,
                error_code=ErrorCode.INTERNAL_ERROR,
                message="入点运动工具返回了不匹配的 command_id；未调用路径规划。",
            )
        if move_result.status != ToolStatus.SUCCESS or not move_result.reached:
            machine.transition(AgentTaskState.FAILED)
            return self._result(
                machine,
                command,
                tool_events,
                robot_result=move_result,
                error_code=move_result.error_code or ErrorCode.ENTRY_NOT_REACHED,
                message=move_result.message,
            )

        try:
            verified_state = self._call_tool(
                command.command_id,
                ToolName.ROBOT_GET_STATE,
                {},
                self.robot.get_state,
                tool_events,
            )
        except Exception as exc:
            machine.transition(AgentTaskState.FAILED)
            return self._result(
                machine,
                command,
                tool_events,
                robot_result=move_result,
                error_code=_robot_exception_code(exc),
                message=f"到点后读取 TCP 状态失败：{type(exc).__name__}",
            )

        interrupted = self._interrupted_result(
            command,
            machine,
            tool_events,
            robot_result=move_result,
            robot_state=verified_state,
        )
        if interrupted is not None:
            return interrupted
        if verified_state.estop or verified_state.motion_state == MotionState.ESTOP:
            machine.transition(AgentTaskState.ESTOP)
            return self._result(
                machine,
                command,
                tool_events,
                robot_result=move_result,
                robot_state=verified_state,
                error_code=ErrorCode.ESTOP_ACTIVE,
                message="到点复核时检测到急停；未调用路径规划。",
            )
        if verified_state.tcp_position.frame != command.entry_point.frame:
            machine.transition(AgentTaskState.FAILED)
            return self._result(
                machine,
                command,
                tool_events,
                robot_result=move_result,
                robot_state=verified_state,
                error_code=ErrorCode.INVALID_COORDINATE_FRAME,
                message="到点复核的 TCP 坐标系与入点坐标系不一致。",
            )

        position_error = verified_state.tcp_position.distance_to(command.entry_point)
        if position_error > self.policy.entry_tolerance_mm:
            machine.transition(AgentTaskState.FAILED)
            return self._result(
                machine,
                command,
                tool_events,
                robot_result=move_result,
                robot_state=verified_state,
                verified_position_error_mm=position_error,
                error_code=ErrorCode.POSITION_TOLERANCE_EXCEEDED,
                message=(
                    f"TCP 到入点误差 {position_error:.3f} mm 超过容差 "
                    f"{self.policy.entry_tolerance_mm:.3f} mm；未调用路径规划。"
                ),
            )
        if verified_state.motion_state in {
            MotionState.MOVING,
            MotionState.FAILED,
            MotionState.STOPPED,
        }:
            terminal = (
                AgentTaskState.STOPPED
                if verified_state.motion_state == MotionState.STOPPED
                else AgentTaskState.FAILED
            )
            machine.transition(terminal)
            return self._result(
                machine,
                command,
                tool_events,
                robot_result=move_result,
                robot_state=verified_state,
                verified_position_error_mm=position_error,
                error_code=(
                    None
                    if terminal == AgentTaskState.STOPPED
                    else ErrorCode.ENTRY_NOT_REACHED
                ),
                message="TCP 位置满足容差，但机械臂状态不允许继续路径规划。",
            )

        machine.transition(AgentTaskState.AT_ENTRY)
        if command.intent == CommandIntent.MOVE_TO_ENTRY:
            machine.transition(AgentTaskState.COMPLETED)
            return self._result(
                machine,
                command,
                tool_events,
                robot_result=move_result,
                robot_state=verified_state,
                verified_position_error_mm=position_error,
                message="机械臂已到达入点；未调用路径规划，未执行穿刺。",
            )

        interrupted = self._interrupted_result(
            command,
            machine,
            tool_events,
            robot_result=move_result,
            robot_state=verified_state,
            verified_position_error_mm=position_error,
        )
        if interrupted is not None:
            return interrupted

        assert command.target_point is not None
        machine.transition(AgentTaskState.PATH_PLANNING)
        plan_request = PlanPunctureRequest(
            request_id=command.command_id,
            command_id=command.command_id,
            entry_point=command.entry_point,
            target_point=command.target_point,
        )
        try:
            plan_result = self._call_tool(
                command.command_id,
                ToolName.PLANNER_PLAN_PUNCTURE,
                plan_request,
                lambda: self.planner.plan(plan_request),
                tool_events,
            )
        except Exception as exc:
            exception_code = _planner_exception_code(exc)
            unavailable = (
                isinstance(exc, ConnectionError)
                or exception_code == ErrorCode.PLANNER_UNAVAILABLE
            )
            machine.transition(
                AgentTaskState.PLANNER_UNAVAILABLE
                if unavailable
                else AgentTaskState.PLAN_FAILED
            )
            return self._result(
                machine,
                command,
                tool_events,
                robot_result=move_result,
                robot_state=verified_state,
                verified_position_error_mm=position_error,
                error_code=(
                    ErrorCode.PLANNER_UNAVAILABLE
                    if unavailable
                    else exception_code
                ),
                message=f"路径规划工具调用失败：{type(exc).__name__}；未执行穿刺。",
            )

        interrupted = self._interrupted_result(
            command,
            machine,
            tool_events,
            robot_result=move_result,
            robot_state=verified_state,
            planner_result=plan_result,
            verified_position_error_mm=position_error,
        )
        if interrupted is not None:
            return interrupted
        if plan_result.request_id != command.command_id:
            machine.transition(AgentTaskState.PLAN_FAILED)
            return self._result(
                machine,
                command,
                tool_events,
                robot_result=move_result,
                robot_state=verified_state,
                planner_result=plan_result,
                verified_position_error_mm=position_error,
                error_code=ErrorCode.INVALID_PLANNER_OUTPUT,
                message="路径规划工具返回了不匹配的 request_id；未执行穿刺。",
            )
        if plan_result.status == PlannerStatus.UNAVAILABLE:
            machine.transition(AgentTaskState.PLANNER_UNAVAILABLE)
            return self._result(
                machine,
                command,
                tool_events,
                robot_result=move_result,
                robot_state=verified_state,
                planner_result=plan_result,
                verified_position_error_mm=position_error,
                error_code=plan_result.error_code or ErrorCode.PLANNER_UNAVAILABLE,
                message=f"{plan_result.message}；机械臂已在入点，未执行穿刺。",
            )
        if plan_result.status != PlannerStatus.SUCCESS:
            machine.transition(AgentTaskState.PLAN_FAILED)
            return self._result(
                machine,
                command,
                tool_events,
                robot_result=move_result,
                robot_state=verified_state,
                planner_result=plan_result,
                verified_position_error_mm=position_error,
                error_code=plan_result.error_code or ErrorCode.INVALID_PLANNER_OUTPUT,
                message=f"{plan_result.message}；机械臂已在入点，未执行穿刺。",
            )

        machine.transition(AgentTaskState.PLAN_READY)
        return self._result(
            machine,
            command,
            tool_events,
            robot_result=move_result,
            robot_state=verified_state,
            planner_result=plan_result,
            verified_position_error_mm=position_error,
            message="机械臂已到达入点，路径规划结果已就绪；未执行穿刺。",
        )

    def _interrupted_result(
        self,
        command: ParsedCommand,
        machine: TaskStateMachine,
        tool_events: list[ToolEvent],
        *,
        robot_result: MoveToEntryResult | MoveRelativeResult | None = None,
        robot_state: RobotState | None = None,
        planner_result: PlanPunctureResult | None = None,
        verified_position_error_mm: float | None = None,
    ) -> OrchestrationResult | None:
        with self._lock:
            interrupted_state = self._interrupts.get(command.command_id)
        if interrupted_state is None:
            return None
        machine.transition(interrupted_state)
        emergency = interrupted_state == AgentTaskState.ESTOP
        return self._result(
            machine,
            command,
            tool_events,
            robot_result=robot_result,
            robot_state=robot_state,
            planner_result=planner_result,
            verified_position_error_mm=verified_position_error_mm,
            error_code=ErrorCode.ESTOP_ACTIVE if emergency else None,
            message=(
                "执行期间收到急停命令；后续工具调用已阻断，未执行穿刺。"
                if emergency
                else "执行期间收到停止命令；后续工具调用已阻断，未执行穿刺。"
            ),
        )

    def _call_tool(
        self,
        command_id: str,
        tool: ToolName,
        arguments: Any,
        operation: Callable[[], ToolResult],
        events: list[ToolEvent],
    ) -> ToolResult:
        arguments_dict = _json_value(arguments) or {}
        self._emit_tool_event(
            events,
            ToolEvent(
                event_id=self._event_id(command_id, len(events) + 1),
                command_id=command_id,
                timestamp_ms=self._clock_ms(),
                tool=tool,
                phase=EventPhase.STARTED,
                arguments=arguments_dict,
            ),
        )
        try:
            result = operation()
        except Exception as exc:
            self._emit_tool_event(
                events,
                ToolEvent(
                    event_id=self._event_id(command_id, len(events) + 1),
                    command_id=command_id,
                    timestamp_ms=self._clock_ms(),
                    tool=tool,
                    phase=EventPhase.FAILED,
                    arguments=arguments_dict,
                    result={
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                    },
                ),
            )
            raise

        status = getattr(result, "status", None)
        status_value = status.value if isinstance(status, Enum) else status
        phase = EventPhase.COMPLETED if status_value in {None, "success"} else EventPhase.FAILED
        self._emit_tool_event(
            events,
            ToolEvent(
                event_id=self._event_id(command_id, len(events) + 1),
                command_id=command_id,
                timestamp_ms=self._clock_ms(),
                tool=tool,
                phase=phase,
                arguments=arguments_dict,
                result=_json_value(result),
            ),
        )
        return result

    def _emit_tool_event(self, events: list[ToolEvent], event: ToolEvent) -> None:
        events.append(event)
        if self._event_sink is None:
            return
        try:
            self._event_sink(event)
        except Exception:
            # Observability must never change robot/planner execution semantics.
            return

    def _remember(
        self,
        command_id: str,
        fingerprint: str,
        result: OrchestrationResult,
    ) -> None:
        # Do not evict command IDs: silently forgetting one could allow an old
        # retried request to produce a second physical movement.
        self._fingerprints[command_id] = fingerprint
        self._completed[command_id] = result

    def _conflict_result(
        self,
        command: ParsedCommand,
        message: str,
    ) -> OrchestrationResult:
        machine = TaskStateMachine(clock_ms=self._clock_ms)
        machine.transition(AgentTaskState.PARSING)
        machine.transition(AgentTaskState.VALIDATING)
        machine.transition(AgentTaskState.FAILED)
        return self._result(
            machine,
            command,
            [],
            error_code=ErrorCode.COMMAND_CONFLICT,
            message=message,
        )

    def _unexpected_failure(
        self,
        command: ParsedCommand,
        exc: Exception,
    ) -> OrchestrationResult:
        machine = TaskStateMachine(clock_ms=self._clock_ms)
        machine.transition(AgentTaskState.PARSING)
        machine.transition(AgentTaskState.FAILED)
        return self._result(
            machine,
            command,
            [],
            error_code=ErrorCode.INTERNAL_ERROR,
            message=f"编排器内部错误：{type(exc).__name__}",
        )

    @staticmethod
    def _fingerprint(command: ParsedCommand) -> str:
        payload = json.dumps(
            command.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _event_id(command_id: str, sequence: int) -> str:
        digest = hashlib.sha256(command_id.encode("utf-8")).hexdigest()[:20]
        return f"evt-{digest}-{sequence:04d}"

    @staticmethod
    def _result(
        machine: TaskStateMachine,
        command: ParsedCommand,
        tool_events: list[ToolEvent],
        *,
        robot_result: MoveToEntryResult | MoveRelativeResult | None = None,
        robot_state: RobotState | None = None,
        planner_result: PlanPunctureResult | None = None,
        verified_position_error_mm: float | None = None,
        error_code: ErrorCode | None = None,
        message: str,
    ) -> OrchestrationResult:
        return OrchestrationResult(
            command_id=command.command_id,
            final_state=machine.state,
            state_history=machine.history,
            state_events=machine.events,
            tool_events=tuple(tool_events),
            robot_result=robot_result,
            robot_state=robot_state,
            planner_result=planner_result,
            verified_position_error_mm=verified_position_error_mm,
            error_code=error_code,
            message=message,
        )


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _robot_exception_code(exc: Exception) -> ErrorCode:
    explicit = _explicit_error_code(exc)
    if explicit is not None:
        return explicit
    return ErrorCode.ROBOT_TIMEOUT if isinstance(exc, TimeoutError) else ErrorCode.INTERNAL_ERROR


def _planner_exception_code(exc: Exception) -> ErrorCode:
    explicit = _explicit_error_code(exc)
    if explicit is not None:
        return explicit
    return ErrorCode.PLANNER_TIMEOUT if isinstance(exc, TimeoutError) else ErrorCode.INTERNAL_ERROR


def _explicit_error_code(exc: Exception) -> ErrorCode | None:
    value = getattr(exc, "error_code", None)
    if isinstance(value, ErrorCode):
        return value
    if isinstance(value, str):
        try:
            return ErrorCode(value)
        except ValueError:
            return None
    return None
