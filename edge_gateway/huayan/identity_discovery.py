"""Minimal 10003 identity discovery before filling the real-robot config.

This module can only encode four documented read requests. Optional DataSheet
inspection receives bytes without sending any request. No cloud, motion, or
configuration writer is available here.
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import time
from dataclasses import asdict, dataclass
from typing import Literal

from .adapter import read_controller_started, read_identity_text, read_is_simulation
from .command_client import CommandClient, _private_controller_host, _validated_host
from .command_codec import encode_read
from .datasheet_codec import HEADER_BYTES, MAGIC, MAX_FRAME_BYTES, parse_datasheet
from .models import ReadCommand
from .real_probe import _recv_exact, read_one_datasheet_frame


DISCOVERY_COMMANDS = (
    ReadCommand.PACKAGE_VERSION,
    ReadCommand.ROBOT_MODEL,
    ReadCommand.IS_SIMULATION,
    ReadCommand.CONTROLLER_STATE,
)


@dataclass(frozen=True)
class DiscoveredIdentity:
    package_version: str
    robot_model: str
    is_simulation: bool
    controller_started: bool


@dataclass(frozen=True)
class DatasheetIdentity:
    device_sn: str | None
    source_timestamp_ms: int
    joint_positions_deg: tuple[float, ...]
    fsm_code: int
    moving: bool
    error_code: int


def discover_identity(
    host: str, port: int = 10003, *,
    scope: Literal["loopback", "private-read-only"] = "loopback",
) -> DiscoveredIdentity:
    if port != 10003 and scope == "private-read-only":
        raise ValueError("real identity discovery is limited to port 10003")
    with CommandClient(host, port, timeout_s=2.0, scope=scope) as client:
        version = read_identity_text(client.request(ReadCommand.PACKAGE_VERSION))
        model = read_identity_text(client.request(ReadCommand.ROBOT_MODEL))
        simulation = read_is_simulation(client.request(ReadCommand.IS_SIMULATION))
        started = read_controller_started(client.request(ReadCommand.CONTROLLER_STATE))
    return DiscoveredIdentity(version, model, simulation, started)


def inspect_datasheet_header(
    host: str, port: int = 10004, *,
    scope: Literal["loopback", "private-read-only"] = "loopback",
) -> dict[str, object]:
    if scope == "private-read-only" and port != 10004:
        raise ValueError("real DataSheet discovery is limited to port 10004")
    selected = _validated_host(host, scope)
    with socket.create_connection((selected, port), timeout=2.0) as connection:
        connection.settimeout(2.0)
        header = _recv_exact(connection, HEADER_BYTES)
    if header[:4] != MAGIC:
        raise ValueError("DataSheet header does not start with LTBR")
    candidates: dict[str, dict[str, int | bool]] = {}
    for byte_order, fmt in (("little", "<II"), ("big", ">II")):
        total, json_length = struct.unpack(fmt, header[4:])
        candidates[byte_order] = {
            "total_length": total,
            "json_length": json_length,
            "lengths_consistent": HEADER_BYTES + 2 <= total <= MAX_FRAME_BYTES
            and json_length == total - HEADER_BYTES,
        }
    return {"header_hex": header.hex(), "candidates": candidates}


def discover_datasheet_identity(
    host: str, port: int = 10004, *, byte_order: Literal["little", "big"],
    scope: Literal["loopback", "private-read-only"] = "loopback",
) -> DatasheetIdentity:
    if scope == "private-read-only" and port != 10004:
        raise ValueError("real DataSheet discovery is limited to port 10004")
    selected = _validated_host(host, scope)
    raw = read_one_datasheet_frame(selected, port, byte_order=byte_order)
    sample = parse_datasheet(
        raw[HEADER_BYTES:],
        received_wall_ms=time.time_ns() // 1_000_000,
        received_monotonic_ns=time.monotonic_ns(),
    )
    return DatasheetIdentity(
        device_sn=sample.device_sn,
        source_timestamp_ms=sample.source_timestamp_ms,
        joint_positions_deg=sample.joint_positions_deg,
        fsm_code=sample.fsm_code,
        moving=sample.moving,
        error_code=sample.error_code,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only 10003 identity discovery; no server connection")
    parser.add_argument("--host", required=True, help="controller's literal private IPv4 address")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--show-requests", action="store_true", help="print exact read bytes; no network")
    action.add_argument("--discover-real-identity", action="store_true", help="connect and issue four read requests")
    action.add_argument("--inspect-datasheet-header", action="store_true", help="read only the first 12 header bytes")
    action.add_argument("--discover-datasheet-identity", action="store_true", help="read one DataSheet frame")
    parser.add_argument("--operator-ready", action="store_true", help="robot stationary and local safety checks completed")
    parser.add_argument("--byte-order", choices=("little", "big"), help="required for one-frame DataSheet parsing")
    args = parser.parse_args()
    host = _private_controller_host(args.host)
    if args.show_requests:
        for command in DISCOVERY_COMMANDS:
            print(encode_read(command).decode("ascii"))
        print("No network connection was opened")
        return 0
    if not args.operator_ready:
        parser.error("live identity discovery requires --operator-ready")
    if args.discover_real_identity:
        identity = discover_identity(host, scope="private-read-only")
        print(json.dumps(asdict(identity), ensure_ascii=False, indent=2))
        if identity.is_simulation:
            raise SystemExit("STOP: controller reports simulation mode; do not fill the real config")
        if not identity.controller_started:
            raise SystemExit("STOP: controller is not started; do not continue commissioning")
    elif args.inspect_datasheet_header:
        print(json.dumps(inspect_datasheet_header(host, scope="private-read-only"), indent=2))
    else:
        if args.byte_order is None:
            parser.error("--discover-datasheet-identity requires --byte-order")
        identity = discover_datasheet_identity(
            host, byte_order=args.byte_order, scope="private-read-only",
        )
        print(json.dumps(asdict(identity), ensure_ascii=False, indent=2))
        if identity.device_sn is None:
            raise SystemExit("STOP: DataSheet DeviceSN is empty; verify with vendor page/plate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
