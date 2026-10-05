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
    MoveSequenceRequest,
    MoveSequenceResult,
    MotionStepKind,
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
        post_move_state_offset_mm: tuple[float, float, float] = (0.0, 0.0, 0.0),
        report_requested_entry_on_success: bool = False,
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
        self.post_move_state_offset_mm = post_move_state_offset_mm
        self.report_requested_entry_on_success = report_requested_entry_on_success
        self.move_to_entry_calls: list[MoveToEntryRequest] = []
        self.move_relative_calls: list[MoveRelativeRequest] = []
        self.move_sequence_calls: list[MoveSequenceRequest] = []
        self._joint_positions_deg = [0.0] * 6
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
            requested_position = request.entry_point.model_copy(
                update={"source": CoordinateSource.SIMULATION},
                deep=True,
            )
            self._position = requested_position.translated(self.post_move_state_offset_mm)
            self._motion_state = MotionState.AT_ENTRY
            reported_position = (
                requested_position
                if self.report_requested_entry_on_success
                else self._position
            )
            return MoveToEntryResult(
                command_id=request.command_id,
                status=ToolStatus.SUCCESS,
                reached=True,
                final_tcp_position=reported_position,
                position_error_mm=reported_position.distance_to(request.entry_point),
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

    def move_sequence(self, request: MoveSequenceRequest) -> MoveSequenceResult:
        self.move_sequence_calls.append(request.model_copy(deep=True))
        if self._estop:
            return MoveSequenceResult(
                command_id=request.command_id,
                status=ToolStatus.REJECTED,
                completed=False,
                completed_steps=0,
                total_steps=len(request.steps),
                final_tcp_position=self._position,
                final_joint_positions_deg=tuple(self._joint_positions_deg),
                message="Fake robot rejected sequence because emergency stop is active",
                error_code=ErrorCode.ESTOP_ACTIVE,
            )
        self._motion_state = MotionState.MOVING
        completed_steps = 0
        reported_position: Point3D | None = None
        for step in request.steps:
            if step.kind == MotionStepKind.CARTESIAN_RELATIVE:
                assert step.translation_mm is not None
                if self.move_relative_outcome != FakeRobotOutcome.SUCCESS:
                    return self._sequence_failure(
                        request,
                        completed_steps,
                        self.move_relative_outcome,
                        "Fake robot rejected Cartesian-relative sequence step",
                    )
                self._position = self._position.translated(step.translation_mm)
            elif step.kind == MotionStepKind.CARTESIAN_ABSOLUTE:
                assert step.target_position_mm is not None
                if self.move_to_entry_outcome != FakeRobotOutcome.SUCCESS:
                    return self._sequence_failure(
                        request,
                        completed_steps,
                        self.move_to_entry_outcome,
                        "Fake robot rejected Cartesian-absolute sequence step",
                    )
                requested_position = Point3D(
                    x=step.target_position_mm[0],
                    y=step.target_position_mm[1],
                    z=step.target_position_mm[2],
                    frame=CoordinateFrame.ROBOT_BASE,
                    source=CoordinateSource.SIMULATION,
                )
                self._position = requested_position.translated(
                    self.post_move_state_offset_mm
                )
                reported_position = requested_position
            elif step.kind == MotionStepKind.JOINT_RELATIVE:
                assert step.joint_index is not None and step.rotation_deg is not None
                self._joint_positions_deg[step.joint_index - 1] += float(step.rotation_deg)
            elif step.kind == MotionStepKind.JOINT_ABSOLUTE:
                assert step.joint_index is not None and step.target_angle_deg is not None
                self._joint_positions_deg[step.joint_index - 1] = float(
                    step.target_angle_deg
                )
            completed_steps += 1
        self._motion_state = MotionState.IDLE
        return MoveSequenceResult(
            command_id=request.command_id,
            status=ToolStatus.SUCCESS,
            completed=True,
            completed_steps=len(request.steps),
            total_steps=len(request.steps),
            final_tcp_position=(
                reported_position
                if self.report_requested_entry_on_success
                and reported_position is not None
                else self._position
            ),
            final_joint_positions_deg=tuple(self._joint_positions_deg),
            message="Fake robot completed ordered motion sequence",
        )

    def _sequence_failure(
        self,
        request: MoveSequenceRequest,
        completed_steps: int,
        outcome: FakeRobotOutcome,
        message: str,
    ) -> MoveSequenceResult:
        timed_out = outcome == FakeRobotOutcome.TIMEOUT
        self._motion_state = MotionState.FAILED
        return MoveSequenceResult(
            command_id=request.command_id,
            status=ToolStatus.TIMED_OUT if timed_out else ToolStatus.FAILED,
            completed=False,
            completed_steps=completed_steps,
            total_steps=len(request.steps),
            final_tcp_position=self._position,
            final_joint_positions_deg=tuple(self._joint_positions_deg),
            message=message,
            error_code=(
                ErrorCode.ROBOT_TIMEOUT if timed_out else ErrorCode.OUT_OF_WORKSPACE
            ),
        )

    def stop(self, command_id: str | None = None) -> RobotState:
        del command_id
        self.stop_calls += 1
        self._motion_state = MotionState.STOPPED
        return self._state()

    def emergency_stop(self, command_id: str | None = None) -> RobotState:
        del command_id
        self.emergency_stop_calls += 1
        self._estop = True
        self._motion_state = MotionState.ESTOP
        return self._state()

    def reset_estop(self, command_id: str | None = None) -> RobotState:
        del command_id
        self.reset_estop_calls += 1
        self._estop = False
        self._motion_state = MotionState.IDLE
        return self._state()
