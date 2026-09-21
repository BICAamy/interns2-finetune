"""Typed V6 frames for *loopback fake-controller tests only*.

The production CommandClient remains read-only. Nothing in this module opens a
socket or grants permission to send a frame to a physical controller.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .command_codec import MAX_REPLY_BYTES, validate_identifier
from .models import ProtocolError

_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def _number(value: float, *, positive: bool = False) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("motion number must be finite")
    if positive and value <= 0:
        raise ValueError("motion number must be positive")
    return format(float(value), ".9g")


@dataclass(frozen=True)
class LinearWaypoint:
    """A single Base-frame MoveL with no blending, seek, or joint target."""

    pose_xyzrpy: tuple[float, float, float, float, float, float]
    tcp_name: str
    ucs_name: str
    speed_mm_s: float
    acceleration_mm_s2: float
    waypoint_id: str

    def encode(self) -> bytes:
        if len(self.pose_xyzrpy) != 6:
            raise ValueError("WayPoint requires XYZ and Rx/Ry/Rz")
        if not _NAME.fullmatch(self.tcp_name) or self.ucs_name != "Base":
            raise ValueError("WayPoint requires an approved TCP and Base UCS")
        fields = [
            "WayPoint", "0", *(_number(value) for value in self.pose_xyzrpy),
            *("0" for _ in range(6)), self.tcp_name, self.ucs_name,
            _number(self.speed_mm_s, positive=True),
            _number(self.acceleration_mm_s2, positive=True),
            "0",  # blend radius
            "1",  # MoveL, never MoveJ
            "0",  # no joint target
            "0", "0", "0",  # no seek or IO trigger
            validate_identifier(self.waypoint_id),
        ]
        frame = (",".join(fields) + ",;").encode("ascii")
        if len(frame) > 512:
            raise ValueError("WayPoint exceeds fake-test frame limit")
        return frame


def encode_software_stop() -> bytes:
    """Ordinary TCP stop request, never a physical emergency stop."""
    return b"GrpStop,0,;"


def decode_write_reply(frame: bytes, *, command: str) -> bool:
    """Return acceptance only. An OK reply is never motion completion."""
    if command not in ("WayPoint", "GrpStop"):
        raise ValueError("unsupported write reply")
    if len(frame) > MAX_REPLY_BYTES or not frame.endswith(b",;"):
        raise ProtocolError("invalid motion reply framing")
    try:
        fields = frame[:-2].decode("ascii").split(",")
    except UnicodeDecodeError as exc:
        raise ProtocolError("motion reply is not ASCII") from exc
    if fields == [command, "OK"]:
        return True
    if len(fields) >= 3 and fields[0] == command and fields[1] == "Fail" and fields[2].isdecimal():
        return False
    raise ProtocolError("unexpected motion reply")
