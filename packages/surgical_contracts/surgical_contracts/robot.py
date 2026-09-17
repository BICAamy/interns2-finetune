"""Robot state, command, and result contracts."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, FiniteFloat, model_validator

from .base import SCHEMA_VERSION, ContractModel, SchemaVersion
from .coordinates import CoordinateFrame, DistanceUnit, Point3D
from .errors import ErrorCode


class RuntimeMode(str, Enum):
    SIMULATION = "simulation"
    REAL = "real"


class MotionState(str, Enum):
    IDLE = "idle"
    MOVING = "moving"
    AT_ENTRY = "at_entry"
    STOPPED = "stopped"
    ESTOP = "estop"
    FAILED = "failed"


class ToolStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    REJECTED = "rejected"


class RobotProvider(str, Enum):
    SIMULATION = "simulation"
    HUAYAN_EDGE_GATEWAY = "huayan_edge_gateway"


class LinkState(str, Enum):
    UNKNOWN = "unknown"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"


class SourceFreshness(str, Enum):
    UNKNOWN = "unknown"
    FRESH = "fresh"
    STALE = "stale"
    DISCONNECTED = "disconnected"


class RobotConnectionState(ContractModel):
    """Independent links; omitted fields are unknown, never assumed connected."""

    gateway: LinkState = LinkState.UNKNOWN
    datasheet: LinkState = LinkState.UNKNOWN
    command_socket: LinkState = LinkState.UNKNOWN
    controller_box: LinkState = LinkState.UNKNOWN


class Pose6D(ContractModel):
    """Explicit-frame pose with XYZ millimetres, RPY degrees, and unit xyzw quaternion."""

    translation_mm: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    rotation_rpy_deg: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    quaternion_xyzw: tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat]
    frame: CoordinateFrame
    unit: DistanceUnit

    @model_validator(mode="after")
    def validate_quaternion(self) -> "Pose6D":
        squared_norm = sum(float(value) ** 2 for value in self.quaternion_xyzw)
        if abs(squared_norm - 1.0) > 1e-3:
            raise ValueError("quaternion_xyzw must be a unit quaternion")
        return self


class FaultRecoverability(str, Enum):
    UNKNOWN = "unknown"
    RETRY_AFTER_STATE_CHANGE = "retry_after_state_change"
    OPERATOR_ACTION = "operator_action"
    VENDOR_SUPPORT = "vendor_support"


class ExecutionCertainty(str, Enum):
    UNKNOWN = "unknown"
    NOT_SENT = "not_sent"
    REJECTED = "rejected"
    ACCEPTED = "accepted"
    COMPLETED = "completed"


class VendorFault(ContractModel):
    """Preserve vendor diagnostics without guessing a recovery action."""

    vendor_error_code: int
    vendor_error_message: str | None = Field(default=None, max_length=512)
    vendor_error_axis: int | None = Field(default=None, ge=0, le=6)
    stable_error_code: ErrorCode | None = None
    recoverability: FaultRecoverability = FaultRecoverability.UNKNOWN
    execution_certainty: ExecutionCertainty = ExecutionCertainty.UNKNOWN
    raw_response_digest: str | None = Field(default=None, max_length=128)


class RobotTelemetry(ContractModel):
    """Source-independent snapshot. Unknown real-world safety bits stay None."""

    schema_version: SchemaVersion = SCHEMA_VERSION
    runtime_mode: RuntimeMode
    provider: RobotProvider
    control_mode: Literal["observe-only", "enabled"] | None = None
    sequence: int = Field(ge=0)
    freshness: SourceFreshness = SourceFreshness.UNKNOWN
    connections: RobotConnectionState = Field(default_factory=RobotConnectionState)
    source_timestamp_ms: int | None = Field(default=None, ge=0)
    gateway_received_at_ms: int | None = Field(default=None, ge=0)
    state_age_at_gateway_send_ms: FiniteFloat | None = Field(default=None, ge=0)
    server_received_at_ms: int | None = Field(default=None, ge=0)
    state_age_ms: FiniteFloat | None = Field(default=None, ge=0)
    gateway_session_id: str | None = Field(default=None, min_length=1, max_length=128)
    device_sn: str | None = Field(default=None, min_length=1, max_length=128)
    robot_model: str | None = Field(default=None, min_length=1, max_length=128)
    package_version: str | None = Field(default=None, min_length=1, max_length=128)
    joint_positions_deg: tuple[
        FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat
    ] | None = None
    joint_velocities_deg_s: tuple[
        FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat
    ] | None = None
    actual_pose_robot_base: Pose6D | None = None
    motion_state: MotionState | None = None
    potentially_moving: bool | None = None
    fsm_code: int | None = None
    enabled: bool | None = None
    electrified: bool | None = None
    brakes_released: bool | None = None
    paused: bool | None = None
    moving: bool | None = None
    in_position: bool | None = None
    physical_estop_active: bool | None = None
    emergency_stop_circuit_fault: bool | None = None
    safeguard_active: bool | None = None
    safeguard_circuit_fault: bool | None = None
    reduced_mode: bool | None = None
    auto_mode: bool | None = None
    three_position_enable: bool | None = None
    free_drive_active: bool | None = None
    force_control_active: bool | None = None
    controller_is_simulation: bool | None = None
    validated_tcp_name: str | None = Field(default=None, min_length=1, max_length=128)
    validated_ucs_name: str | None = Field(default=None, min_length=1, max_length=128)
    active_command_id: str | None = Field(default=None, min_length=1, max_length=128)
    controller_waypoint_id: str | None = Field(default=None, min_length=1, max_length=128)
    vendor_fault: VendorFault | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "RobotTelemetry":
        if (self.runtime_mode == RuntimeMode.SIMULATION) != (
            self.provider == RobotProvider.SIMULATION
        ):
            raise ValueError("runtime_mode and provider disagree")
        if (
            self.actual_pose_robot_base is not None
            and self.actual_pose_robot_base.frame != CoordinateFrame.ROBOT_BASE
        ):
            raise ValueError("actual_pose_robot_base must use robot_base frame")
        if self.runtime_mode == RuntimeMode.REAL and self.freshness == SourceFreshness.FRESH:
            if self.joint_positions_deg is None or self.actual_pose_robot_base is None:
                raise ValueError("fresh real telemetry requires actual joints and base pose")
            if self.state_age_ms is None:
                raise ValueError("fresh real telemetry requires state_age_ms")
            if self.controller_is_simulation is True:
                raise ValueError("real telemetry cannot report controller simulation mode")
        return self


class RobotHealth(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    runtime_mode: RuntimeMode
    provider: RobotProvider
    control_mode: Literal["observe-only", "enabled"] | None = None
    status: Literal["healthy", "degraded", "disconnected"]
    freshness: SourceFreshness = SourceFreshness.UNKNOWN
    connections: RobotConnectionState = Field(default_factory=RobotConnectionState)
    ready_for_motion: bool = False
    error: str | None = None

    @model_validator(mode="after")
    def validate_readiness(self) -> "RobotHealth":
        if (self.runtime_mode == RuntimeMode.SIMULATION) != (
            self.provider == RobotProvider.SIMULATION
        ):
            raise ValueError("runtime_mode and provider disagree")
        if self.ready_for_motion:
            if self.runtime_mode == RuntimeMode.REAL:
                raise ValueError("real motion readiness is unavailable before preflight exists")
            if self.status != "healthy" or self.freshness != SourceFreshness.FRESH:
                raise ValueError("ready_for_motion requires fresh healthy state")
        return self


class RobotState(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    mode: RuntimeMode = RuntimeMode.SIMULATION
    tcp: str = Field(default="needle_tip", min_length=1)
    tcp_position: Point3D
    orientation_xyzw: tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat] = (
        0.0,
        0.0,
        0.0,
        1.0,
    )
    motion_state: MotionState = MotionState.IDLE
    estop: bool = False
    active_command_id: str | None = Field(default=None, min_length=1, max_length=128)


class MoveToEntryRequest(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    command_id: str = Field(min_length=1, max_length=128)
    entry_point: Point3D
    tcp: str = Field(default="needle_tip", min_length=1)
    orientation_policy: str = Field(
        default="configured_safe_orientation",
        min_length=1,
    )
    speed_mm_s: FiniteFloat = Field(default=5.0, gt=0)


class MoveToEntryResult(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    command_id: str = Field(min_length=1, max_length=128)
    status: ToolStatus
    reached: bool
    final_tcp_position: Point3D
    position_error_mm: FiniteFloat | None = Field(default=None, ge=0)
    trajectory_id: str | None = Field(default=None, min_length=1, max_length=128)
    message: str = Field(min_length=1)
    error_code: ErrorCode | None = None

    @model_validator(mode="after")
    def validate_status(self) -> "MoveToEntryResult":
        if self.status == ToolStatus.SUCCESS and not self.reached:
            raise ValueError("successful move-to-entry result must have reached=true")
        if self.status == ToolStatus.SUCCESS and self.position_error_mm is None:
            raise ValueError("successful move-to-entry result requires position_error_mm")
        if self.status == ToolStatus.SUCCESS and self.error_code is not None:
            raise ValueError("successful move-to-entry result cannot contain error_code")
        if self.status != ToolStatus.SUCCESS and self.reached:
            raise ValueError("failed move-to-entry result cannot have reached=true")
        if self.status != ToolStatus.SUCCESS and self.error_code is None:
            raise ValueError("non-success move-to-entry result requires error_code")
        return self


class MoveRelativeRequest(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    command_id: str = Field(min_length=1, max_length=128)
    translation_mm: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    frame: CoordinateFrame = CoordinateFrame.ROBOT_BASE
    speed_mm_s: FiniteFloat = Field(default=5.0, gt=0)

    @model_validator(mode="after")
    def validate_translation(self) -> "MoveRelativeRequest":
        if all(float(value) == 0.0 for value in self.translation_mm):
            raise ValueError("translation_mm cannot be the zero vector")
        return self


class MoveRelativeResult(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    command_id: str = Field(min_length=1, max_length=128)
    status: ToolStatus
    completed: bool
    final_tcp_position: Point3D
    trajectory_id: str | None = Field(default=None, min_length=1, max_length=128)
    message: str = Field(min_length=1)
    error_code: ErrorCode | None = None

    @model_validator(mode="after")
    def validate_status(self) -> "MoveRelativeResult":
        if self.status == ToolStatus.SUCCESS and not self.completed:
            raise ValueError("successful relative movement must have completed=true")
        if self.status == ToolStatus.SUCCESS and self.error_code is not None:
            raise ValueError("successful relative movement cannot contain error_code")
        if self.status != ToolStatus.SUCCESS and self.completed:
            raise ValueError("failed relative movement cannot have completed=true")
        if self.status != ToolStatus.SUCCESS and self.error_code is None:
            raise ValueError("non-success relative movement requires error_code")
        return self
