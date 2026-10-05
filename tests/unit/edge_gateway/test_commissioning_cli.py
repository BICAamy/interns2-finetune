"""Step 11 local writer requires explicit per-command human authorization."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from edge_gateway import commissioning_cli as cli
from robot_runtime.real_config import RealRobotConfig


def config(
    *, speed: float = 5.0, acceleration: float = 20.0,
    step: float = 1.0,
) -> RealRobotConfig:
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
            "max_speed_mm_s": speed, "max_acceleration_mm_s2": acceleration,
            "max_step_mm": step, "max_rotation_deg": 1,
            "max_absolute_displacement_mm": 1,
        },
        "motion": {
            "speed_mm_s": 2.0, "controller_override": 1.0,
            "default_relative_step_mm": 15.0,
            "default_relative_rotation_deg": 15.0,
            "default_rotation_joint_index": 1,
            "joint_speed_deg_s": 15.0,
            "joint_acceleration_deg_s2": 30.0,
        },
        "deadlines": {
            "state_stale_ms": 250, "real_mode_fallback_ms": 5000,
            "response_ms": 3000, "startup_ms": 5000,
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


def test_motion_limits_come_directly_from_yaml_without_hidden_caps():
    assert cli.first_motion_config_blockers(config()) == ()
    wide = config(speed=2000, acceleration=2500, step=1000)
    assert cli.first_motion_config_blockers(wide) == ()
    assert cli.effective_first_motion_caps(wide) == {
        "max_speed_mm_s": 2000.0,
        "max_acceleration_mm_s2": 2500.0,
        "max_step_mm": 1000.0,
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
    assert report["three_position_enable_required"] is False
    assert report["read_only_record"] is None


def test_preflight_refuses_without_local_control(monkeypatch):
    monkeypatch.setattr(cli, "load_real_config", lambda _path: config())
    with pytest.raises(SystemExit):
        cli.main([
            "--config", "ignored.yaml", "--preflight-read-only", "--byte-order", "little",
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
        "--byte-order", "little",
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
        "--byte-order", "little",
    ]) == 0
    report = json.loads(capsys.readouterr().out)
    assert called == [("little", "private-read-only")]
    assert report["motion_authorized"] is False
    assert report["no_tool_readback_verified"] is True
    assert report["effective_first_motion_caps"]["max_step_mm"] == 1000.0
    assert report["read_only_record"] == "read-only-summary.json"


def test_execute_denies_remote_terminal_before_network(monkeypatch):
    monkeypatch.setattr(cli, "load_real_config", lambda _path: config())
    monkeypatch.setattr(cli, "probe_once", lambda *_a, **_kw: pytest.fail("probe opened"))
    monkeypatch.setattr(cli, "require_local_mac_terminal", lambda: (_ for _ in ()).throw(
        PermissionError("SSH is not local")))
    assert cli.main([
        "--config", "ignored.yaml", "--control", "local-only", "--execute-relative",
        "--byte-order", "little",
        "--axis=+X", "--test-id", "trial-1",
    ]) == 2


def test_enable_disable_routes_only_through_explicit_local_cli_action(monkeypatch):
    monkeypatch.setattr(cli, "load_real_config", lambda _path: config())
    calls = []

    def execute(loaded, args):
        calls.append((loaded, args.set_enabled, args.control))
        return 0

    monkeypatch.setattr(cli, "_execute_enabled_state", execute)
    assert cli.main([
        "--config", "ignored.yaml", "--control", "local-only",
        "--set-enabled", "false", "--byte-order", "little",
    ]) == 0
    assert calls == [(config(), "false", "local-only")]


def test_enable_disable_denies_remote_terminal_before_network(monkeypatch):
    monkeypatch.setattr(cli, "load_real_config", lambda _path: config())
    monkeypatch.setattr(cli, "probe_once", lambda *_a, **_kw: pytest.fail("probe opened"))
    monkeypatch.setattr(cli, "require_local_mac_terminal", lambda: (_ for _ in ()).throw(
        PermissionError("SSH is not local")))
    assert cli.main([
        "--config", "ignored.yaml", "--control", "local-only",
        "--set-enabled", "true", "--byte-order", "little",
    ]) == 2


def test_persistent_journal_path_has_no_date_component():
    assert cli._journal_path().parts[-3:] == (
        "real_robot_commissioning", "step11", "commands.journal",
    )


def test_config_change_before_write_is_rejected(monkeypatch):
    monkeypatch.setattr(cli, "load_real_config", lambda _path: config(speed=4))
    with pytest.raises(ValueError, match="changed before controller write"):
        cli._require_unchanged_config(Path("ignored.yaml"), config(speed=5))
