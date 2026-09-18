"""Explicit fake-only settings for Step 5 Mac development."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .cloud_transport import validate_cloud_url


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
