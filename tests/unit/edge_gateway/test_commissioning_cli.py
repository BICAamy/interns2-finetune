"""Step 11 preparation must remain local and read-only until Gate C is proven."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from edge_gateway import commissioning_cli as cli
from robot_runtime.real_config import RealRobotConfig


def config(*, speed: float = 5.0, step: float = 1.0) -> RealRobotConfig:
    return RealRobotConfig.model_validate({
        "controller": {
            "host": "192.168.0.10", "command_port": 10003,
            "datasheet_port": 10004, "device_sn": "FAKE-SN", "asset_id": "bench-1",
            "model": "E05_Pro", "package_versions": ["fake-v1"],
        },
        "joint_mapping": {"sign": [1] * 6, "zero_offset_deg": [0] * 6},
        "base_to_sofa": {"translation_mm": [0] * 3, "quaternion_xyzw": [0, 0, 0, 1]},
        "tool": {
            "setup": "flange_only_no_tool", "tcp_name": "TCP",
            "flange_to_tcp": {"translation_mm": [0] * 3, "quaternion_xyzw": [0, 0, 0, 1]},
            "payload_kg": 0, "center_of_gravity_mm": [0] * 3,
            "mount_angle_deg": [0, 0],
        },
        "limits": {
            "joint_soft_limits_deg": [[-180, 180]] * 6, "joint_margin_deg": 5,
            "workspace_low_mm": [0, 0, 0], "workspace_high_mm": [800, 800, 800],
            "max_speed_mm_s": speed, "max_acceleration_mm_s2": 20,
            "max_step_mm": step, "max_rotation_deg": 1,
            "max_absolute_displacement_mm": 1,
        },
        "deadlines": {
            "state_stale_ms": 250, "response_ms": 3000, "startup_ms": 5000,
            "motion_ms": 120000, "stop_delivery_ms": 500, "stop_ack_ms": 3000,
        },
        "arrival": {
            "position_tolerance_mm": 0.5, "orientation_tolerance_deg": 2,
            "stable_samples": 5, "dwell_ms": 500,
        },
    })


class Stream:
    def __init__(self, tty: bool) -> None:
        self.tty = tty

    def isatty(self) -> bool:
        return self.tty


@pytest.mark.parametrize("system,environment,input_tty,output_tty", [
    ("Linux", {}, True, True),
    ("Darwin", {"SSH_CONNECTION": "client server"}, True, True),
    ("Darwin", {}, False, True),
    ("Darwin", {}, True, False),
])
def test_local_terminal_denies_server_ssh_and_pipes(system, environment, input_tty, output_tty):
    with pytest.raises(PermissionError):
        cli.require_local_mac_terminal(
            system=system, environment=environment,
            stdin=Stream(input_tty), stdout=Stream(output_tty),
        )


def test_local_terminal_accepts_interactive_mac():
    cli.require_local_mac_terminal(
        system="Darwin", environment={}, stdin=Stream(True), stdout=Stream(True),
    )


def test_first_motion_caps_are_intersection_with_controller_maxima():
    assert cli.first_motion_config_blockers(config()) == ()
    wide = config(speed=2000, step=1000)
    assert cli.first_motion_config_blockers(wide) == ()
    assert cli.effective_first_motion_caps(wide) == {
        "max_speed_mm_s": 5.0,
        "max_acceleration_mm_s2": 20.0,
        "max_step_mm": 1.0,
        "rotation_deg": 0.0,
    }
    assert cli.effective_first_motion_caps(config(speed=2, step=0.5))["max_step_mm"] == 0.5


def test_check_config_never_opens_a_socket(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_real_config", lambda _path: config())
    monkeypatch.setattr(socket, "create_connection", lambda *_a, **_kw: pytest.fail("network opened"))
    assert cli.main(["--config", "ignored.yaml", "--check-config"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["motion_authorized"] is False
    assert report["no_tool_readback_verified"] is None
    assert report["three_position_enable_verified"] is False
    assert report["read_only_record"] is None


def test_preflight_refuses_without_local_control(monkeypatch):
    monkeypatch.setattr(cli, "load_real_config", lambda _path: config())
    with pytest.raises(SystemExit):
        cli.main([
            "--config", "ignored.yaml", "--preflight-read-only", "--byte-order", "little",
            "--vendor-compatibility-confirmed", "--operator-ready",
        ])


def test_cli_has_no_arm_or_motion_argument(monkeypatch):
    monkeypatch.setattr(cli, "load_real_config", lambda _path: config())
    for forbidden in ("--arm", "--move", "--waypoint", "--speed-mm-s"):
        with pytest.raises(SystemExit):
            cli.main(["--config", "ignored.yaml", "--check-config", forbidden])


def test_preflight_denies_remote_terminal_before_network(monkeypatch):
    monkeypatch.setattr(cli, "load_real_config", lambda _path: config())
    monkeypatch.setattr(cli, "probe_once", lambda *_a, **_kw: pytest.fail("probe opened"))
    monkeypatch.setattr(cli, "require_local_mac_terminal", lambda: (_ for _ in ()).throw(
        PermissionError("SSH is not local")))
    assert cli.main([
        "--config", "ignored.yaml", "--control", "local-only", "--preflight-read-only",
        "--byte-order", "little", "--vendor-compatibility-confirmed", "--operator-ready",
    ]) == 2


def test_preflight_uses_fixed_read_only_probe_and_never_arms(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_real_config", lambda _path: config(speed=2000, step=1000))
    monkeypatch.setattr(cli, "require_local_mac_terminal", lambda: None)
    called = []

    def probe(_config, *, byte_order, scope):
        called.append((byte_order, scope))
        return SimpleNamespace(summary={"no_tool_readback_verified": True})

    monkeypatch.setattr(cli, "probe_once", probe)
    monkeypatch.setattr(cli, "_save_probe_result", lambda _result: Path("read-only-summary.json"))
    assert cli.main([
        "--config", "ignored.yaml", "--control", "local-only", "--preflight-read-only",
        "--byte-order", "little", "--vendor-compatibility-confirmed", "--operator-ready",
    ]) == 0
    report = json.loads(capsys.readouterr().out)
    assert called == [("little", "private-read-only")]
    assert report["motion_authorized"] is False
    assert report["no_tool_readback_verified"] is True
    assert report["effective_first_motion_caps"]["max_step_mm"] == 1.0
    assert report["read_only_record"] == "read-only-summary.json"
