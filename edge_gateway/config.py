"""Separate fake and explicitly approved real read-only Mac settings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .cloud_transport import validate_cloud_url
from .huayan.command_client import _private_controller_host


@dataclass(frozen=True)
class EdgeConfig:
    fake_command_port: int
    fake_datasheet_port: int
    server_url: str
    secret_file: Path
    gateway_id: str
    config_sha256: str
    datasheet_byte_order: str
    audit_path: Path
    stale_ms: int = 250

    def __post_init__(self) -> None:
        for name in ("fake_command_port", "fake_datasheet_port"):
            port = getattr(self, name)
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError(f"{name} must be a TCP port")
        validate_cloud_url(self.server_url)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.gateway_id):
            raise ValueError("invalid gateway_id")
        if not re.fullmatch(r"[0-9a-f]{64}", self.config_sha256):
            raise ValueError("invalid config_sha256")
        if self.datasheet_byte_order not in ("little", "big"):
            raise ValueError("DataSheet byte order must be explicit")
        if not 50 <= self.stale_ms <= 5000:
            raise ValueError("stale_ms must be 50..5000")


@dataclass(frozen=True)
class RealEdgeConfig:
    controller_host: str
    command_port: int
    datasheet_port: int
    expected_device_sn: str
    expected_robot_model: str
    approved_package_versions: tuple[str, ...]
    server_url: str
    secret_file: Path
    gateway_id: str
    config_sha256: str
    datasheet_byte_order: str
    audit_path: Path
    stale_ms: int

    def __post_init__(self) -> None:
        _private_controller_host(self.controller_host)
        if self.command_port != 10003 or self.datasheet_port != 10004:
            raise ValueError("first real read-only gateway requires ports 10003 and 10004")
        if not self.expected_device_sn or not self.expected_robot_model or not self.approved_package_versions:
            raise ValueError("real gateway identity must be complete")
        validate_cloud_url(self.server_url)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.gateway_id):
            raise ValueError("invalid gateway_id")
        if not re.fullmatch(r"[0-9a-f]{64}", self.config_sha256):
            raise ValueError("invalid config_sha256")
        if self.datasheet_byte_order not in ("little", "big"):
            raise ValueError("DataSheet byte order must be explicit")
        if not 50 <= self.stale_ms < 1500:
            raise ValueError("real stale_ms must be 50..1499")
