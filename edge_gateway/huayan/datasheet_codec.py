"""Incremental, bounded parser for the V6 JSON DataSheet stream.

V6 1.0.19.1 defines LTBR + total length + JSON length, with total length
including the 12-byte header. It does *not* define length byte order, so the
caller must choose it explicitly; no per-frame guessing is permitted.
"""

from __future__ import annotations

import json
import math
import struct
import time
from typing import Any

from .models import DatasheetSample, ProtocolError

MAGIC = b"LTBR"
HEADER_BYTES = 12
MAX_FRAME_BYTES = 1024 * 1024


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError(f"duplicate DataSheet key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ProtocolError(f"non-finite JSON constant: {value}")


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProtocolError(f"{name} must be an object")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ProtocolError(f"{name} must be numeric")
    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise ProtocolError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise ProtocolError(f"{name} must be finite")
    return number


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if type(value) is int:
        number = value
    elif isinstance(value, str) and value.isascii() and value.isdecimal():
        number = int(value)
    else:
        raise ProtocolError(f"{name} must be an integer >= {minimum}")
    if number < minimum:
        raise ProtocolError(f"{name} must be an integer >= {minimum}")
    return number


def _flag(value: Any, name: str) -> bool:
    number = _integer(value, name)
    if number not in (0, 1):
        raise ProtocolError(f"{name} must be 0 or 1")
    return bool(number)


def _vector(value: Any, name: str, length: int) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != length:
        raise ProtocolError(f"{name} must contain exactly {length} values")
    return tuple(_number(item, f"{name}[{index}]") for index, item in enumerate(value))


def parse_datasheet(
    payload: bytes, *, received_wall_ms: int, received_monotonic_ns: int
) -> DatasheetSample:
    try:
        document = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ProtocolError("DataSheet is not valid UTF-8 JSON") from exc
    root = _mapping(document, "DataSheet")
    pos = _mapping(root.get("PosAndVel"), "PosAndVel")
    state = _mapping(root.get("StateAndError"), "StateAndError")
    force = _mapping(root.get("FTData"), "FTData")
    title = _mapping(root.get("MsgTitle"), "MsgTitle")

    actual = pos.get("Actual_Position")
    if not isinstance(actual, list) or len(actual) < 12:
        raise ProtocolError("Actual_Position must contain at least 12 values")
    actual_twelve = _vector(actual[:12], "Actual_Position", 12)
    # Extra values may be added by future controller versions; validate them
    # rather than silently accepting NaN in an unused tail.
    for index, value in enumerate(actual[12:], start=12):
        _number(value, f"Actual_Position[{index}]")
    base_pose = _vector(pos.get("Actual_PCS_Base"), "Actual_PCS_Base", 6)
    tcp_pose = _vector(pos.get("Actual_PCS_TCP"), "Actual_PCS_TCP", 6)
    velocities = _vector(pos.get("Actual_Joint_Velocity"), "Actual_Joint_Velocity", 6)
    accelerations = _vector(
        pos.get("Actual_Joint_Acceleration"), "Actual_Joint_Acceleration", 6
    )
    brakes = state.get("BrakeState")
    axis_errors = state.get("nAxisErrorCode")
    if not isinstance(brakes, list) or len(brakes) != 6:
        raise ProtocolError("BrakeState must contain six values")
    if not isinstance(axis_errors, list) or len(axis_errors) != 6:
        raise ProtocolError("nAxisErrorCode must contain six values")
    brake_states = tuple(int(_flag(value, "BrakeState")) for value in brakes)
    axis_error_codes = tuple(_integer(value, "nAxisErrorCode") for value in axis_errors)
    error_axis = _integer(state.get("Error_AxisID"), "Error_AxisID")
    if error_axis > 6:
        raise ProtocolError("Error_AxisID must be 0..6")

    system = root.get("SystemInfo") or root.get("RobotAuthorization") or {}
    device_sn = _mapping(system, "SystemInfo/RobotAuthorization").get("DeviceSN")
    if device_sn is not None and not isinstance(device_sn, str):
        raise ProtocolError("DeviceSN must be a string")
    if device_sn is not None and len(device_sn) > 128:
        raise ProtocolError("DeviceSN is too long")

    return DatasheetSample(
        source_timestamp_ms=_integer(title.get("Stamp"), "MsgTitle.Stamp"),
        received_wall_ms=received_wall_ms,
        received_monotonic_ns=received_monotonic_ns,
        joint_positions_deg=actual_twelve[:6],
        current_pose=actual_twelve[6:12],
        base_pose=base_pose,
        tcp_pose=tcp_pose,
        joint_velocities_deg_s=velocities,
        joint_accelerations_deg_s2=accelerations,
        override=_number(pos.get("Actual_Override"), "Actual_Override"),
        fsm_code=_integer(state.get("robotState"), "robotState"),
        enabled=_flag(state.get("robotEnabled"), "robotEnabled"),
        moving=_flag(state.get("robotMoving"), "robotMoving"),
        paused=_flag(state.get("robotPaused"), "robotPaused"),
        blending_done=_flag(state.get("robotBlendingDone"), "robotBlendingDone"),
        in_position=_flag(state.get("InPos"), "InPos"),
        error_code=_integer(state.get("Error_Code"), "Error_Code"),
        error_axis=error_axis,
        auto_mode=_flag(state.get("AutoMode"), "AutoMode"),
        reduced_mode=_flag(state.get("IsReduceMode"), "IsReduceMode"),
        free_drive_mode=_flag(state.get("IsFreeDriveMode"), "IsFreeDriveMode"),
        brake_states=brake_states,
        axis_error_codes=axis_error_codes,
        force_control_state=_integer(force.get("FTControlState"), "FTControlState"),
        device_sn=device_sn or None,
    )


class DatasheetFrameDecoder:
    def __init__(
        self,
        *,
        byte_order: str,
        max_frame_bytes: int = MAX_FRAME_BYTES,
        max_resync_bytes: int = 4096,
    ) -> None:
        if byte_order not in ("big", "little"):
            raise ValueError("byte_order must be explicitly big or little")
        if max_frame_bytes < HEADER_BYTES + 2 or max_frame_bytes > MAX_FRAME_BYTES:
            raise ValueError("invalid maximum frame length")
        if max_resync_bytes < 0:
            raise ValueError("invalid resynchronization bound")
        self.byte_order = byte_order
        self.max_frame_bytes = max_frame_bytes
        self.max_resync_bytes = max_resync_bytes
        self._buffer = bytearray()
        self._discarded = 0

    def feed(self, data: bytes) -> list[DatasheetSample]:
        if not isinstance(data, bytes):
            raise TypeError("TCP data must be bytes")
        if len(self._buffer) + len(data) > self.max_frame_bytes * 2:
            raise ProtocolError("DataSheet receive chunk exceeds bounded buffer")
        self._buffer.extend(data)
        result: list[DatasheetSample] = []
        while True:
            start = self._buffer.find(MAGIC)
            if start < 0:
                discard = max(0, len(self._buffer) - len(MAGIC) + 1)
                self._discarded += discard
                del self._buffer[:discard]
                self._check_resync()
                return result
            if start:
                self._discarded += start
                del self._buffer[:start]
                self._check_resync()
            if len(self._buffer) < HEADER_BYTES:
                return result
            fmt = ">II" if self.byte_order == "big" else "<II"
            total, json_length = struct.unpack_from(fmt, self._buffer, 4)
            if total < HEADER_BYTES + 2 or total > self.max_frame_bytes:
                raise ProtocolError("DataSheet total length is out of bounds")
            if json_length != total - HEADER_BYTES:
                raise ProtocolError("DataSheet total/JSON lengths disagree")
            if len(self._buffer) < total:
                return result
            payload = bytes(self._buffer[HEADER_BYTES:total])
            del self._buffer[:total]
            result.append(parse_datasheet(
                payload,
                received_wall_ms=time.time_ns() // 1_000_000,
                received_monotonic_ns=time.monotonic_ns(),
            ))
            self._discarded = 0

    def _check_resync(self) -> None:
        if self._discarded > self.max_resync_bytes:
            raise ProtocolError("DataSheet magic not found within resync bound")
