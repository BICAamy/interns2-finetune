"""Fail-closed command and response shapes for a future Mac edge gateway.

This module contains data only. It opens no sockets and cannot move a robot.
"""

from __future__ import annotations

from enum import Enum
from math import sqrt

from pydantic import Field, FiniteFloat, model_validator

from .base import SCHEMA_VERSION, ContractModel, SchemaVersion
from .coordinates import CoordinateFrame
from .errors import ErrorCode
from .robot import (
    MoveRelativeRequest,
    MoveToEntryRequest,
    Pose6D,
    ToolStatus,
    VendorFault,
)


class GatewayControlMode(str, Enum):
    OBSERVE_ONLY = "observe-only"
    ENABLED = "enabled"


class GatewayHandshake(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    gateway_session_id: str = Field(min_length=1, max_length=128)
    device_sn: str = Field(min_length=1, max_length=128)
    robot_model: str = Field(min_length=1, max_length=128)
    package_version: str = Field(min_length=1, max_length=128)
    safety_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    control_mode: GatewayControlMode = GatewayControlMode.OBSERVE_ONLY


class GatewayCommandKind(str, Enum):
    MOVE_TO_ENTRY = "move_to_entry"
    MOVE_RELATIVE = "move_relative"
    SOFTWARE_STOP_REQUEST = "software_stop_request"


class SoftwareStopRequest(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    command_id: str = Field(min_length=1, max_length=128)


class MotionSafetyLimits(ContractModel):
    max_speed_mm_s: FiniteFloat = Field(gt=0)
    max_step_mm: FiniteFloat = Field(gt=0)


class RobotCommandEnvelope(ContractModel):
    """Typed high-level request; arbitrary vendor commands are not expressible."""

    schema_version: SchemaVersion = SCHEMA_VERSION
    gateway_session_id: str = Field(min_length=1, max_length=128)
    command_id: str = Field(min_length=1, max_length=128)
    command_kind: GatewayCommandKind
    created_at_ms: int = Field(ge=0)
    expires_at_ms: int = Field(ge=0)
    based_on_robot_state_sequence: int = Field(ge=0)
    expected_start_pose_robot_base: Pose6D | None = None
    expected_tcp_name: str | None = Field(default=None, min_length=1, max_length=128)
    expected_ucs_name: str | None = Field(default=None, min_length=1, max_length=128)
    payload: MoveToEntryRequest | MoveRelativeRequest | SoftwareStopRequest
    safety_limits: MotionSafetyLimits | None = None
    operator_confirmation_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_envelope(self) -> "RobotCommandEnvelope":
        if self.expires_at_ms <= self.created_at_ms:
            raise ValueError("expires_at_ms must be later than created_at_ms")
        if self.payload.command_id != self.command_id:
            raise ValueError("payload command_id must match envelope command_id")
        expected_payload = {
            GatewayCommandKind.MOVE_TO_ENTRY: MoveToEntryRequest,
            GatewayCommandKind.MOVE_RELATIVE: MoveRelativeRequest,
            GatewayCommandKind.SOFTWARE_STOP_REQUEST: SoftwareStopRequest,
        }[self.command_kind]
        if not isinstance(self.payload, expected_payload):
            raise ValueError("command_kind does not match typed payload")

        if self.command_kind == GatewayCommandKind.SOFTWARE_STOP_REQUEST:
            if any(
                value is not None
                for value in (
                    self.expected_start_pose_robot_base,
                    self.expected_tcp_name,
                    self.expected_ucs_name,
                    self.safety_limits,
                    self.operator_confirmation_id,
                )
            ):
                raise ValueError("software stop cannot contain motion preflight fields")
        else:
            if self.expected_start_pose_robot_base is None:
                raise ValueError("motion requires expected_start_pose_robot_base")
            if self.expected_start_pose_robot_base.frame != CoordinateFrame.ROBOT_BASE:
                raise ValueError("expected start pose must use robot_base frame")
            if not self.expected_tcp_name or not self.expected_ucs_name:
                raise ValueError("motion requires expected TCP and UCS names")
            if self.safety_limits is None or not self.operator_confirmation_id:
                raise ValueError("motion requires safety limits and confirmation")
            if self.payload.speed_mm_s > self.safety_limits.max_speed_mm_s:
                raise ValueError("requested speed exceeds envelope safety limit")
            if isinstance(self.payload, MoveRelativeRequest):
                if "frame" not in self.payload.model_fields_set:
                    raise ValueError("real relative motion requires explicit frame")
                if self.payload.frame != CoordinateFrame.ROBOT_BASE:
                    raise ValueError("real relative motion currently requires robot_base frame")
                displacement_mm = sqrt(sum(float(v) ** 2 for v in self.payload.translation_mm))
            else:
                if self.payload.tcp != self.expected_tcp_name:
                    raise ValueError("entry payload TCP must match expected TCP")
                if not {"frame", "unit"}.issubset(
                    self.payload.entry_point.model_fields_set
                ):
                    raise ValueError("real entry point requires explicit frame and unit")
                if self.payload.entry_point.frame != CoordinateFrame.ROBOT_BASE:
                    raise ValueError("real entry point currently requires robot_base frame")
                start = self.expected_start_pose_robot_base.translation_mm
                target = self.payload.entry_point.as_tuple()
                displacement_mm = sqrt(
                    sum((float(end) - float(begin)) ** 2 for begin, end in zip(start, target))
                )
            if displacement_mm > self.safety_limits.max_step_mm:
                raise ValueError("requested displacement exceeds envelope safety limit")
        return self


class GatewayAcknowledgementStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class RobotCommandAcknowledgement(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    gateway_session_id: str = Field(min_length=1, max_length=128)
    command_id: str = Field(min_length=1, max_length=128)
    status: GatewayAcknowledgementStatus
    error_code: ErrorCode | None = None

    @model_validator(mode="after")
    def validate_error(self) -> "RobotCommandAcknowledgement":
        if self.status == GatewayAcknowledgementStatus.REJECTED and self.error_code is None:
            raise ValueError("rejected acknowledgement requires error_code")
        if self.status == GatewayAcknowledgementStatus.ACCEPTED and self.error_code is not None:
            raise ValueError("accepted acknowledgement cannot contain error_code")
        return self


class StopDelivery(str, Enum):
    SENT = "sent"
    NOT_SENT = "not_sent"
    UNKNOWN = "unknown"


class MotionStopConfirmation(str, Enum):
    CONFIRMED = "confirmed"
    UNCONFIRMED = "unconfirmed"


class SoftwareStopResult(ContractModel):
    """A TCP stop request is never a physical emergency stop."""

    delivery: StopDelivery
    motion_stop: MotionStopConfirmation


class RobotCommandResult(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    gateway_session_id: str = Field(min_length=1, max_length=128)
    command_id: str = Field(min_length=1, max_length=128)
    command_kind: GatewayCommandKind
    status: ToolStatus
    controller_waypoint_id: str | None = Field(default=None, min_length=1, max_length=128)
    error_code: ErrorCode | None = None
    vendor_fault: VendorFault | None = None
    software_stop: SoftwareStopResult | None = None

    @model_validator(mode="after")
    def validate_result(self) -> "RobotCommandResult":
        if self.command_kind == GatewayCommandKind.SOFTWARE_STOP_REQUEST:
            if self.software_stop is None:
                raise ValueError("software stop result requires delivery and motion_stop")
        elif self.software_stop is not None:
            raise ValueError("motion result cannot contain software stop fields")
        if self.status == ToolStatus.SUCCESS and self.error_code is not None:
            raise ValueError("successful result cannot contain error_code")
        if self.status != ToolStatus.SUCCESS and self.error_code is None:
            raise ValueError("non-success result requires error_code")
        if self.status == ToolStatus.SUCCESS and self.software_stop is not None:
            if (
                self.software_stop.delivery != StopDelivery.SENT
                or self.software_stop.motion_stop != MotionStopConfirmation.CONFIRMED
            ):
                raise ValueError("successful software stop requires sent and confirmed")
        return self
