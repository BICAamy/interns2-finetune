"""No-tool flange profile is valid data, not permission to move a robot."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from robot_runtime.real_config import RealRobotConfig, load_real_config


def no_tool_data() -> dict:
    return {
        "allowed_control": "observe-only",
        "tool": {
            "setup": "flange_only_no_tool",
            "tcp_name": "Flange_0",
            "flange_to_tcp": {
                "translation_mm": [0, 0, 0],
                "quaternion_xyzw": [0, 0, 0, 1],
            },
            "payload_kg": 0,
            "center_of_gravity_mm": [0, 0, 0],
            "mount_angle_deg": [0, 0],
        },
    }


def test_no_tool_profile_accepts_zero_setup_but_never_enables_control() -> None:
    config = RealRobotConfig.model_validate(no_tool_data())
    assert config.tool.setup == "flange_only_no_tool"
    assert config.tool.flange_to_tcp.translation_mm == (0, 0, 0)
    assert config.tool.mount_angle_deg == (0, 0)
    assert not any(name.startswith("tool.") for name in config.blocking_fields())
    assert config.allowed_control == "observe-only"
    assert "limits.joint_soft_limits_deg" in config.blocking_fields()


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("tool", "tcp_name"), None),
        (("tool", "tcp_name"), "bad,name"),
        (("tool", "flange_to_tcp", "translation_mm"), [0, 0, 1]),
        (("tool", "flange_to_tcp", "quaternion_xyzw"), [0, 0, 1, 0]),
        (("tool", "payload_kg"), 0.1),
        (("tool", "center_of_gravity_mm"), [0, 0, 1]),
        (("tool", "mount_angle_deg"), None),
        (("tool", "mount_angle_deg"), [361, 0]),
    ],
)
def test_no_tool_profile_rejects_inconsistent_values(path: tuple[str, ...], value: object) -> None:
    data = no_tool_data()
    selected = data
    for part in path[:-1]:
        selected = selected[part]
    selected[path[-1]] = value
    with pytest.raises(ValidationError):
        RealRobotConfig.model_validate(data)


def test_unmarked_zero_setup_does_not_complete_motion_fields() -> None:
    data = no_tool_data()
    del data["tool"]["setup"]
    config = RealRobotConfig.model_validate(data)
    assert "tool.setup" in config.blocking_fields()


def test_unknown_setup_and_enabled_control_remain_rejected() -> None:
    data = no_tool_data()
    data["tool"]["setup"] = "needle_tip"
    with pytest.raises(ValidationError):
        RealRobotConfig.model_validate(data)
    data = no_tool_data()
    data["allowed_control"] = "enabled"
    with pytest.raises(ValidationError):
        RealRobotConfig.model_validate(data)


def test_legacy_observe_only_digest_is_unchanged_and_profile_changes_it() -> None:
    from pathlib import Path
    from hashlib import sha256

    example = Path(__file__).resolve().parents[3] / "configs" / "robot-real.example.yaml"
    legacy = load_real_config(example)
    old_shape = legacy.model_dump(mode="json")
    del old_shape["tool"]["setup"]
    old_digest = sha256(json.dumps(
        old_shape, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()
    assert legacy.digest() == old_digest

    data = no_tool_data()
    selected = RealRobotConfig.model_validate(data)
    other = deepcopy(data)
    del other["tool"]["setup"]
    assert selected.digest() != RealRobotConfig.model_validate(other).digest()
