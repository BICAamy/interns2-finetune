"""Small typed vocabulary for the V6 read-only protocol subset."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProtocolError(ValueError):
    """A received frame is malformed or disagrees with the pending request."""


class ResponseUnknown(RuntimeError):
    """A request may have reached the controller, but its reply was lost.

    Callers must never infer success or automatically replay a request.
    """


class ReadCommand(str, Enum):
    IS_SIMULATION = "IsSimulation"
    CONTROLLER_STATE = "ReadControllerState"
    ROBOT_MODEL = "ReadRobotModel"
    PACKAGE_VERSION = "PackageVersion"
    FAST_COMMAND_PORT = "ReadFastCmdPort"
    ROBOT_STATE = "ReadRobotState"
    CURRENT_FSM = "ReadCurFSM"
    ACTUAL_POSITION = "ReadActPos"
    EMERGENCY_INFO = "ReadEmergencyInfo"
    CURRENT_WAYPOINT_ID = "ReadCurWayPointID"
    AXIS_ERROR_CODE = "ReadAxisErrorCode"
    PAYLOAD = "ReadPayload"
    BASE_INSTALLING_ANGLE = "GetBaseInstallingAngle"
    CURRENT_TCP = "ReadCurTCP"
    CURRENT_UCS = "ReadCurUCS"
    TCP_BY_NAME = "ReadTCPByName"
    UCS_BY_NAME = "ReadUCSByName"


ROBOT_ID_COMMANDS = frozenset({
    ReadCommand.ROBOT_STATE,
    ReadCommand.CURRENT_FSM,
    ReadCommand.ACTUAL_POSITION,
    ReadCommand.EMERGENCY_INFO,
    ReadCommand.CURRENT_WAYPOINT_ID,
    ReadCommand.AXIS_ERROR_CODE,
    ReadCommand.PAYLOAD,
    ReadCommand.BASE_INSTALLING_ANGLE,
    ReadCommand.CURRENT_TCP,
    ReadCommand.CURRENT_UCS,
    ReadCommand.TCP_BY_NAME,
    ReadCommand.UCS_BY_NAME,
})

NAMED_READ_COMMANDS = frozenset({ReadCommand.TCP_BY_NAME, ReadCommand.UCS_BY_NAME})

# Each command here is explicitly marked as fast-port capable in V6 1.0.19.1.
FAST_PORT_COMMANDS = frozenset({
    ReadCommand.IS_SIMULATION,
    ReadCommand.CONTROLLER_STATE,
    ReadCommand.ROBOT_MODEL,
    ReadCommand.PACKAGE_VERSION,
    ReadCommand.ROBOT_STATE,
    ReadCommand.CURRENT_FSM,
    ReadCommand.ACTUAL_POSITION,
    ReadCommand.CURRENT_WAYPOINT_ID,
    ReadCommand.AXIS_ERROR_CODE,
    ReadCommand.PAYLOAD,
    ReadCommand.CURRENT_TCP,
    ReadCommand.CURRENT_UCS,
    ReadCommand.TCP_BY_NAME,
    ReadCommand.UCS_BY_NAME,
})

REPLY_FIELD_COUNTS = {
    ReadCommand.IS_SIMULATION: 1,
    ReadCommand.CONTROLLER_STATE: 1,
    ReadCommand.ROBOT_MODEL: 1,
    ReadCommand.PACKAGE_VERSION: 1,
    ReadCommand.FAST_COMMAND_PORT: 1,
    ReadCommand.ROBOT_STATE: 13,
    ReadCommand.CURRENT_FSM: 1,
    ReadCommand.ACTUAL_POSITION: 24,
    ReadCommand.EMERGENCY_INFO: 4,
    ReadCommand.CURRENT_WAYPOINT_ID: 1,
    ReadCommand.AXIS_ERROR_CODE: 7,
    ReadCommand.PAYLOAD: 4,
    ReadCommand.BASE_INSTALLING_ANGLE: 2,
    ReadCommand.CURRENT_TCP: 6,
    ReadCommand.CURRENT_UCS: 6,
    ReadCommand.TCP_BY_NAME: 6,
    ReadCommand.UCS_BY_NAME: 6,
}


@dataclass(frozen=True)
class CommandReply:
    command: ReadCommand
    values: tuple[str, ...] = ()
    vendor_error_code: int | None = None
    vendor_error_message: str | None = None
    protocol_deviation: bool = False

    @property
    def ok(self) -> bool:
        return self.vendor_error_code is None


@dataclass(frozen=True)
class DatasheetSample:
    source_timestamp_ms: int
    received_wall_ms: int
    received_monotonic_ns: int
    joint_positions_deg: tuple[float, ...]
    current_pose: tuple[float, ...]
    base_pose: tuple[float, ...]
    tcp_pose: tuple[float, ...]
    joint_velocities_deg_s: tuple[float, ...]
    joint_accelerations_deg_s2: tuple[float, ...]
    override: float
    fsm_code: int
    enabled: bool
    moving: bool
    paused: bool
    blending_done: bool
    in_position: bool
    error_code: int
    error_axis: int
    auto_mode: bool
    reduced_mode: bool
    free_drive_mode: bool
    brake_states: tuple[int, ...]
    axis_error_codes: tuple[int, ...]
    force_control_state: int
    device_sn: str | None
