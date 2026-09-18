"""Typed interpretation of the V6 read-only replies; no motion API."""

from __future__ import annotations

import math
from dataclasses import dataclass

from surgical_contracts import VendorFault

from .command_codec import validate_identifier
from .error_policy import vendor_fault
from .models import CommandReply, ProtocolError, ReadCommand


class VendorCommandFailure(RuntimeError):
    def __init__(self, fault: VendorFault) -> None:
        self.fault = fault
        super().__init__(f"vendor command failed: {fault.vendor_error_code}")


@dataclass(frozen=True)
class RobotStateRead:
    moving: bool
    enabled: bool
    has_error: bool
    error_code: int
    error_axis: int
    brakes_released: bool
    paused: bool
    emergency_stop: bool
    safeguard: bool
    electrified: bool
    controller_box_connected: bool
    blending_done: bool
    in_position: bool


@dataclass(frozen=True)
class ActualPositionRead:
    joints_deg: tuple[float, ...]
    current_pose: tuple[float, ...]
    configured_tcp: tuple[float, ...]
    configured_ucs: tuple[float, ...]


@dataclass(frozen=True)
class EmergencyInfoRead:
    emergency_circuit_fault: bool
    emergency_stop: bool
    safeguard_circuit_fault: bool
    safeguard: bool


@dataclass(frozen=True)
class AxisErrorRead:
    group_error_code: int
    joint_error_codes: tuple[int, ...]


@dataclass(frozen=True)
class PayloadRead:
    mass_kg: float
    center_of_gravity_mm: tuple[float, float, float]


def _values(reply: CommandReply, command: ReadCommand) -> tuple[str, ...]:
    if reply.command != command:
        raise ProtocolError("wrong command reply type")
    if not reply.ok:
        raise VendorCommandFailure(vendor_fault(reply))
    return reply.values


def _integer(value: str, name: str, *, minimum: int = 0) -> int:
    if not value.isascii() or not value.isdecimal():
        raise ProtocolError(f"{name} is not an integer")
    number = int(value)
    if number < minimum:
        raise ProtocolError(f"{name} is below minimum")
    return number


def _signed_integer(value: str, name: str, *, low: int, high: int) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise ProtocolError(f"{name} is not an integer") from exc
    if str(number) != value or not low <= number <= high:
        raise ProtocolError(f"{name} is out of range")
    return number


def _flag(value: str, name: str) -> bool:
    if value not in ("0", "1"):
        raise ProtocolError(f"{name} must be 0 or 1")
    return value == "1"


def _float(value: str, name: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise ProtocolError(f"{name} is not numeric") from exc
    if not math.isfinite(result):
        raise ProtocolError(f"{name} must be finite")
    return result


def read_robot_state(reply: CommandReply) -> RobotStateRead:
    v = _values(reply, ReadCommand.ROBOT_STATE)
    axis = _integer(v[4], "error axis")
    if axis > 6:
        raise ProtocolError("error axis must be 0..6")
    return RobotStateRead(
        moving=_flag(v[0], "moving"),
        enabled=_flag(v[1], "enabled"),
        has_error=_flag(v[2], "error"),
        error_code=_integer(v[3], "error code"),
        error_axis=axis,
        brakes_released=_flag(v[5], "brakes"),
        paused=_flag(v[6], "paused"),
        emergency_stop=_flag(v[7], "emergency stop"),
        safeguard=_flag(v[8], "safeguard"),
        electrified=_flag(v[9], "electrified"),
        controller_box_connected=_flag(v[10], "controller box"),
        blending_done=_flag(v[11], "blending"),
        in_position=_flag(v[12], "in position"),
    )


def read_current_fsm(reply: CommandReply) -> int:
    return _integer(_values(reply, ReadCommand.CURRENT_FSM)[0], "FSM")


def read_actual_position(reply: CommandReply) -> ActualPositionRead:
    values = tuple(_float(v, f"position[{i}]") for i, v in enumerate(
        _values(reply, ReadCommand.ACTUAL_POSITION)
    ))
    return ActualPositionRead(values[:6], values[6:12], values[12:18], values[18:24])


def read_emergency_info(reply: CommandReply) -> EmergencyInfoRead:
    values = _values(reply, ReadCommand.EMERGENCY_INFO)
    return EmergencyInfoRead(*(
        _flag(value, f"emergency[{index}]") for index, value in enumerate(values)
    ))


def read_axis_error_code(reply: CommandReply) -> AxisErrorRead:
    values = _values(reply, ReadCommand.AXIS_ERROR_CODE)
    codes = tuple(_integer(value, f"axis_error[{index}]") for index, value in enumerate(values))
    return AxisErrorRead(codes[0], codes[1:])


def read_payload(reply: CommandReply) -> PayloadRead:
    values = _values(reply, ReadCommand.PAYLOAD)
    numbers = tuple(_float(value, f"payload[{index}]") for index, value in enumerate(values))
    if numbers[0] < 0:
        raise ProtocolError("payload mass cannot be negative")
    return PayloadRead(numbers[0], numbers[1:4])


def read_base_installing_angle(reply: CommandReply) -> tuple[int, int]:
    values = _values(reply, ReadCommand.BASE_INSTALLING_ANGLE)
    return (
        _signed_integer(values[0], "base_angle[0]", low=-360, high=360),
        _signed_integer(values[1], "base_angle[1]", low=-360, high=360),
    )


def read_coordinate_value(reply: CommandReply) -> tuple[float, ...]:
    if reply.command not in (
        ReadCommand.CURRENT_TCP, ReadCommand.CURRENT_UCS,
        ReadCommand.TCP_BY_NAME, ReadCommand.UCS_BY_NAME,
    ):
        raise ProtocolError("not a TCP/UCS read reply")
    return tuple(_float(value, f"coordinate[{index}]") for index, value in enumerate(
        _values(reply, reply.command)
    ))


def read_fast_port(reply: CommandReply) -> int:
    port = _integer(_values(reply, ReadCommand.FAST_COMMAND_PORT)[0], "fast port", minimum=1)
    if port > 65535:
        raise ProtocolError("fast port is out of range")
    return port


def read_is_simulation(reply: CommandReply) -> bool:
    return _flag(_values(reply, ReadCommand.IS_SIMULATION)[0], "simulation mode")


def read_controller_started(reply: CommandReply) -> bool:
    return _flag(_values(reply, ReadCommand.CONTROLLER_STATE)[0], "controller started")


def read_waypoint_id(reply: CommandReply) -> str:
    value = _values(reply, ReadCommand.CURRENT_WAYPOINT_ID)[0]
    try:
        return validate_identifier(value)
    except ValueError as exc:
        raise ProtocolError("invalid current WayPoint ID") from exc


def read_identity_text(reply: CommandReply) -> str:
    if reply.command not in (ReadCommand.ROBOT_MODEL, ReadCommand.PACKAGE_VERSION):
        raise ProtocolError("not an identity reply")
    value = _values(reply, reply.command)[0]
    if not value.isascii() or len(value) > 128:
        raise ProtocolError("invalid identity string")
    return value


def fixed_xyz_quaternion(rotation_rpy_deg: tuple[float, float, float]) -> tuple[float, float, float, float]:
    """XYZ fixed-angle degrees -> xyzw; used only for read-only base pose."""
    rx, ry, rz = (math.radians(value) / 2 for value in rotation_rpy_deg)
    sx, cx = math.sin(rx), math.cos(rx)
    sy, cy = math.sin(ry), math.cos(ry)
    sz, cz = math.sin(rz), math.cos(rz)
    return (
        sx * cy * cz - cx * sy * sz,
        cx * sy * cz + sx * cy * sz,
        cx * cy * sz - sx * sy * cz,
        cx * cy * cz + sx * sy * sz,
    )
