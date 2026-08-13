"""Deterministic in-memory robot controller used before SOFA is connected."""

from __future__ import annotations

from enum import Enum

from surgical_contracts import (
    CoordinateFrame,
    CoordinateSource,
    ErrorCode,
    MotionState,
    MoveRelativeRequest,
    MoveRelativeResult,
    MoveToEntryRequest,
    MoveToEntryResult,
    Point3D,
    RobotState,
    RuntimeMode,
    ToolStatus,
)


class FakeRobotOutcome(str, Enum):
    SUCCESS = "success"
    UNREACHABLE = "unreachable"
    TIMEOUT = "timeout"


class FakeRobotController:
    """Record requests and simulate controlled robot outcomes without I/O."""

    def __init__(
        self,
        *,
        initial_position: Point3D | None = None,
        move_to_entry_outcome: FakeRobotOutcome = FakeRobotOutcome.SUCCESS,
        move_relative_outcome: FakeRobotOutcome = FakeRobotOutcome.SUCCESS,
    ) -> None:
        self._position = initial_position or Point3D(
            x=0.0,
            y=0.0,
            z=100.0,
            frame=CoordinateFrame.ROBOT_BASE,
            source=CoordinateSource.SIMULATION,
        )
        self._motion_state = MotionState.IDLE
        self._estop = False
        self.move_to_entry_outcome = move_to_entry_outcome
        self.move_relative_outcome = move_relative_outcome
        self.move_to_entry_calls: list[MoveToEntryRequest] = []
        self.move_relative_calls: list[MoveRelativeRequest] = []
        self.stop_calls = 0
        self.emergency_stop_calls = 0
        self.reset_estop_calls = 0
        self._trajectory_sequence = 0

    def _next_trajectory_id(self) -> str:
        self._trajectory_sequence += 1
        return f"fake-traj-{self._trajectory_sequence:04d}"

    def _state(self, *, active_command_id: str | None = None) -> RobotState:
        return RobotState(
            mode=RuntimeMode.SIMULATION,
            tcp="needle_tip",
            tcp_position=self._position.model_copy(deep=True),
            motion_state=self._motion_state,
            estop=self._estop,
            active_command_id=active_command_id,
        )

    def get_state(self) -> RobotState:
        return self._state()

    def move_to_entry(self, request: MoveToEntryRequest) -> MoveToEntryResult:
        self.move_to_entry_calls.append(request.model_copy(deep=True))
        if self._estop:
            self._motion_state = MotionState.ESTOP
            return self._move_to_entry_failure(
                request,
                ToolStatus.REJECTED,
                ErrorCode.ESTOP_ACTIVE,
                "Fake robot rejected movement because emergency stop is active",
                motion_state=MotionState.ESTOP,
            )

        if request.entry_point.frame != self._position.frame:
            return self._move_to_entry_failure(
                request,
                ToolStatus.REJECTED,
                ErrorCode.INVALID_COORDINATE_FRAME,
                "Fake robot does not transform coordinate frames",
            )

        self._motion_state = MotionState.MOVING
        if self.move_to_entry_outcome == FakeRobotOutcome.SUCCESS:
            self._position = request.entry_point.model_copy(
                update={"source": CoordinateSource.SIMULATION},
                deep=True,
            )
            self._motion_state = MotionState.AT_ENTRY
            return MoveToEntryResult(
                command_id=request.command_id,
                status=ToolStatus.SUCCESS,
                reached=True,
                final_tcp_position=self._position,
                position_error_mm=0.0,
                trajectory_id=self._next_trajectory_id(),
                message="Fake robot reached the entry point",
            )

        if self.move_to_entry_outcome == FakeRobotOutcome.TIMEOUT:
            return self._move_to_entry_failure(
                request,
                ToolStatus.TIMED_OUT,
                ErrorCode.ROBOT_TIMEOUT,
                "Fake robot timed out before reaching the entry point",
            )

        return self._move_to_entry_failure(
            request,
            ToolStatus.FAILED,
            ErrorCode.OUT_OF_WORKSPACE,
            "Fake robot rejected an unreachable entry point",
        )

    def _move_to_entry_failure(
        self,
        request: MoveToEntryRequest,
        status: ToolStatus,
        error_code: ErrorCode,
        message: str,
        motion_state: MotionState = MotionState.FAILED,
    ) -> MoveToEntryResult:
        self._motion_state = motion_state
        error = None
        if self._position.frame == request.entry_point.frame:
            error = self._position.distance_to(request.entry_point)
        return MoveToEntryResult(
            command_id=request.command_id,
            status=status,
            reached=False,
            final_tcp_position=self._position,
            position_error_mm=error,
            message=message,
            error_code=error_code,
        )

    def move_relative(self, request: MoveRelativeRequest) -> MoveRelativeResult:
        self.move_relative_calls.append(request.model_copy(deep=True))
        if self._estop:
            self._motion_state = MotionState.ESTOP
            return self._relative_failure(
                request,
                ToolStatus.REJECTED,
                ErrorCode.ESTOP_ACTIVE,
                "Fake robot rejected relative movement because emergency stop is active",
                motion_state=MotionState.ESTOP,
            )

        if request.frame != self._position.frame:
            self._motion_state = MotionState.FAILED
            return self._relative_failure(
                request,
                ToolStatus.REJECTED,
                ErrorCode.INVALID_COORDINATE_FRAME,
                "Fake robot does not transform coordinate frames",
            )

        self._motion_state = MotionState.MOVING
        if self.move_relative_outcome == FakeRobotOutcome.SUCCESS:
            self._position = self._position.translated(request.translation_mm)
            self._motion_state = MotionState.IDLE
            return MoveRelativeResult(
                command_id=request.command_id,
                status=ToolStatus.SUCCESS,
                completed=True,
                final_tcp_position=self._position,
                trajectory_id=self._next_trajectory_id(),
                message="Fake robot completed relative movement",
            )

        if self.move_relative_outcome == FakeRobotOutcome.TIMEOUT:
            return self._relative_failure(
                request,
                ToolStatus.TIMED_OUT,
                ErrorCode.ROBOT_TIMEOUT,
                "Fake robot timed out during relative movement",
            )

        return self._relative_failure(
            request,
            ToolStatus.FAILED,
            ErrorCode.OUT_OF_WORKSPACE,
            "Fake robot rejected relative movement",
        )

    def _relative_failure(
        self,
        request: MoveRelativeRequest,
        status: ToolStatus,
        error_code: ErrorCode,
        message: str,
        motion_state: MotionState = MotionState.FAILED,
    ) -> MoveRelativeResult:
        self._motion_state = motion_state
        return MoveRelativeResult(
            command_id=request.command_id,
            status=status,
            completed=False,
            final_tcp_position=self._position,
            message=message,
            error_code=error_code,
        )

    def stop(self) -> RobotState:
        self.stop_calls += 1
        self._motion_state = MotionState.STOPPED
        return self._state()

    def emergency_stop(self) -> RobotState:
        self.emergency_stop_calls += 1
        self._estop = True
        self._motion_state = MotionState.ESTOP
        return self._state()

    def reset_estop(self) -> RobotState:
        self.reset_estop_calls += 1
        self._estop = False
        self._motion_state = MotionState.IDLE
        return self._state()
