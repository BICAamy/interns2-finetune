"""Validate an operator-owned real-robot configuration without opening a socket.

Step 3 only permits an observe-only, disconnected provider. The canonical
digest is reserved for the later server/Mac gateway handshake.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ControllerConfig(_StrictModel):
    host: str | None = None
    command_port: int | None = Field(default=None, ge=1, le=65535)
    datasheet_port: int | None = Field(default=None, ge=1, le=65535)
    device_sn: str | None = None
    asset_id: str | None = None
    model: str | None = None
    package_versions: list[str] = Field(default_factory=list)


class JointMapping(_StrictModel):
    sign: tuple[int, int, int, int, int, int] | None = None
    zero_offset_deg: tuple[float, float, float, float, float, float] | None = None

    @field_validator("sign")
    @classmethod
    def validate_sign(cls, value: tuple[int, ...] | None) -> tuple[int, ...] | None:
        if value is not None and any(sign not in (-1, 1) for sign in value):
            raise ValueError("joint sign must be +1 or -1")
        return value

    @model_validator(mode="after")
    def validate_complete_pair(self) -> "JointMapping":
        if (self.sign is None) != (self.zero_offset_deg is None):
            raise ValueError("joint sign and zero offset must be set together")
        return self


class RigidTransform(_StrictModel):
    translation_mm: tuple[float, float, float] | None = None
    quaternion_xyzw: tuple[float, float, float, float] | None = None

    @model_validator(mode="after")
    def validate_complete_rigid_transform(self) -> "RigidTransform":
        if (self.translation_mm is None) != (self.quaternion_xyzw is None):
            raise ValueError("translation and quaternion must be set together")
        if self.quaternion_xyzw is not None:
            squared_norm = sum(value * value for value in self.quaternion_xyzw)
            if abs(squared_norm - 1.0) > 1e-3:
                raise ValueError("quaternion_xyzw must be a unit quaternion")
        return self


class ToolConfig(_StrictModel):
    setup: Literal["flange_only_no_tool"] | None = None
    tcp_name: str | None = None
    flange_to_tcp: RigidTransform = Field(default_factory=RigidTransform)
    payload_kg: float | None = Field(default=None, ge=0)
    center_of_gravity_mm: tuple[float, float, float] | None = None
    # GetBaseInstallingAngle returns two angles, not one scalar.
    mount_angle_deg: tuple[float, float] | None = None

    @field_validator("mount_angle_deg")
    @classmethod
    def validate_mount_angles(
        cls, value: tuple[float, float] | None,
    ) -> tuple[float, float] | None:
        if value is not None and any(not -360 <= angle <= 360 for angle in value):
            raise ValueError("base installing angles must be finite and within -360..360 degrees")
        return value

    @model_validator(mode="after")
    def validate_no_tool_setup(self) -> "ToolConfig":
        if self.setup is None:
            return self
        if self.tcp_name is None or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.tcp_name) is None:
            raise ValueError("flange_only_no_tool requires a safe, confirmed TCP name")
        if self.flange_to_tcp.translation_mm != (0.0, 0.0, 0.0):
            raise ValueError("flange_only_no_tool requires zero flange-to-TCP translation")
        if self.flange_to_tcp.quaternion_xyzw != (0.0, 0.0, 0.0, 1.0):
            raise ValueError("flange_only_no_tool requires identity flange-to-TCP rotation")
        if self.payload_kg != 0.0 or self.center_of_gravity_mm != (0.0, 0.0, 0.0):
            raise ValueError("flange_only_no_tool requires zero payload and center of gravity")
        if self.mount_angle_deg is None:
            raise ValueError("flange_only_no_tool requires both measured base installing angles")
        return self


class MotionLimits(_StrictModel):
    joint_soft_limits_deg: tuple[tuple[float, float], ...] | None = None
    joint_margin_deg: float | None = Field(default=None, gt=0)
    workspace_low_mm: tuple[float, float, float] | None = None
    workspace_high_mm: tuple[float, float, float] | None = None
    max_speed_mm_s: float | None = Field(default=None, gt=0)
    max_acceleration_mm_s2: float | None = Field(default=None, gt=0)
    max_step_mm: float | None = Field(default=None, gt=0)
    max_rotation_deg: float | None = Field(default=None, gt=0)
    max_absolute_displacement_mm: float | None = Field(default=None, gt=0)

    @field_validator("joint_soft_limits_deg")
    @classmethod
    def validate_joint_limits(
        cls, value: tuple[tuple[float, float], ...] | None
    ) -> tuple[tuple[float, float], ...] | None:
        if value is not None and (len(value) != 6 or any(low >= high for low, high in value)):
            raise ValueError("joint_soft_limits_deg must contain six increasing pairs")
        return value


class Deadlines(_StrictModel):
    state_stale_ms: int | None = Field(default=None, gt=0)
    response_ms: int | None = Field(default=None, gt=0)
    startup_ms: int | None = Field(default=None, gt=0)
    motion_ms: int | None = Field(default=None, gt=0)
    stop_delivery_ms: int | None = Field(default=None, gt=0)
    stop_ack_ms: int | None = Field(default=None, gt=0)


class ArrivalCriteria(_StrictModel):
    position_tolerance_mm: float | None = Field(default=None, gt=0)
    orientation_tolerance_deg: float | None = Field(default=None, gt=0)
    stable_samples: int | None = Field(default=None, ge=2)
    dwell_ms: int | None = Field(default=None, gt=0)


class RealRobotConfig(_StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    # Keep the Step 0-10 hard stop in the schema itself. Later motion steps
    # must explicitly revise and re-test this cap before accepting enabled.
    allowed_control: Literal["observe-only"] = "observe-only"
    controller: ControllerConfig = Field(default_factory=ControllerConfig)
    joint_mapping: JointMapping = Field(default_factory=JointMapping)
    base_to_sofa: RigidTransform = Field(default_factory=RigidTransform)
    tool: ToolConfig = Field(default_factory=ToolConfig)
    limits: MotionLimits = Field(default_factory=MotionLimits)
    deadlines: Deadlines = Field(default_factory=Deadlines)
    arrival: ArrivalCriteria = Field(default_factory=ArrivalCriteria)

    def blocking_fields(self) -> tuple[str, ...]:
        """Missing calibration/limits prevent any later motion authorization."""
        required = (
            "controller.host", "controller.command_port", "controller.datasheet_port",
            "controller.device_sn", "controller.asset_id", "controller.model",
            "joint_mapping.sign", "joint_mapping.zero_offset_deg",
            "base_to_sofa.translation_mm", "base_to_sofa.quaternion_xyzw",
            "tool.setup", "tool.tcp_name", "tool.flange_to_tcp.translation_mm",
            "tool.flange_to_tcp.quaternion_xyzw", "tool.payload_kg",
            "tool.center_of_gravity_mm", "tool.mount_angle_deg",
            "limits.joint_soft_limits_deg", "limits.joint_margin_deg",
            "limits.workspace_low_mm", "limits.workspace_high_mm",
            "limits.max_speed_mm_s", "limits.max_acceleration_mm_s2",
            "limits.max_step_mm", "limits.max_rotation_deg",
            "limits.max_absolute_displacement_mm", "deadlines.state_stale_ms",
            "deadlines.response_ms", "deadlines.startup_ms",
            "deadlines.motion_ms", "deadlines.stop_delivery_ms",
            "deadlines.stop_ack_ms", "arrival.position_tolerance_mm",
            "arrival.orientation_tolerance_deg", "arrival.stable_samples",
            "arrival.dwell_ms",
        )
        missing = []
        for path in required:
            value: Any = self
            for part in path.split("."):
                value = getattr(value, part)
            if value is None:
                missing.append(path)
        if not self.controller.package_versions:
            missing.append("controller.package_versions")
        return tuple(missing)

    def digest(self) -> str:
        data = self.model_dump(mode="json")
        # Preserve existing observe-only session hashes until a setup is
        # explicitly selected; selecting one intentionally changes the hash.
        if data["tool"]["setup"] is None:
            del data["tool"]["setup"]
        canonical = json.dumps(
            data, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


def load_real_config(path: str | Path) -> RealRobotConfig:
    import yaml

    class UniqueKeyLoader(yaml.SafeLoader):
        pass

    def unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node)
            if not isinstance(key, str):
                raise ValueError("real config keys must be strings")
            if key in result:
                raise ValueError(f"duplicate real config key: {key}")
            result[key] = loader.construct_object(value_node)
        return result

    UniqueKeyLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping
    )

    selected = Path(path).expanduser().resolve(strict=True)
    if not selected.is_file():
        raise ValueError("real config must be a regular file")
    if selected.stat().st_size > 64 * 1024:
        raise ValueError("real config is too large")
    data = yaml.load(selected.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    if not isinstance(data, dict):
        raise ValueError("real config must be a YAML mapping")
    result = RealRobotConfig.model_validate(data)
    # Pydantic accepts non-finite floats in unconstrained tuples; reject them
    # before canonicalization so the same config has one safe digest everywhere.
    def check_finite(value: Any) -> None:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("real config contains a non-finite number")
        if isinstance(value, dict):
            for item in value.values():
                check_finite(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                check_finite(item)

    check_finite(result.model_dump(mode="python"))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate real config without connecting to a robot")
    parser.add_argument("path")
    args = parser.parse_args()
    config = load_real_config(args.path)
    print(f"{config.digest()} {config.allowed_control} {len(config.blocking_fields())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
