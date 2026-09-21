"""The maxima probe is read-only and does not approve real motion."""

from __future__ import annotations

import sys

import pytest

from edge_gateway.huayan.adapter import (
    read_joint_max_acceleration, read_joint_max_velocity, read_linear_max_motion,
)
from edge_gateway.huayan.command_codec import decode_reply, encode_read
from edge_gateway.huayan.models import ProtocolError, ReadCommand
from edge_gateway.huayan.motion_limits_probe import main, read_motion_limits
from tests.fakes.huayan_controller import CommandAction, FakeHuayanController
from tests.unit.edge_gateway.test_real_read_only_probe import fake_config


def test_motion_maxima_request_frames_are_exact() -> None:
    assert encode_read(ReadCommand.JOINT_MAX_VELOCITY) == b"ReadJointMaxVel,0,;"
    assert encode_read(ReadCommand.JOINT_MAX_ACCELERATION) == b"ReadJointMaxAcc,0,;"
    assert encode_read(ReadCommand.LINEAR_MAX_MOTION) == b"ReadLinearMaxVel,0,;"


def test_motion_maxima_reply_units_and_invalid_values() -> None:
    velocity = decode_reply(
        b"ReadJointMaxVel,OK,1,2,3,4,5,6,;", expected=ReadCommand.JOINT_MAX_VELOCITY,
    )
    acceleration = decode_reply(
        b"ReadJointMaxAcc,OK,10,20,30,40,50,60,;", expected=ReadCommand.JOINT_MAX_ACCELERATION,
    )
    linear = decode_reply(
        b"ReadLinearMaxVel,OK,2000,2500,5000,;", expected=ReadCommand.LINEAR_MAX_MOTION,
    )
    assert read_joint_max_velocity(velocity) == (1, 2, 3, 4, 5, 6)
    assert read_joint_max_acceleration(acceleration) == (10, 20, 30, 40, 50, 60)
    assert read_linear_max_motion(linear).acceleration_mm_s2 == 2500
    for reply in (
        b"ReadJointMaxVel,OK,1,2,3,4,5,;",
        b"ReadJointMaxVel,OK,1,2,3,4,5,NaN,;",
        b"ReadJointMaxVel,OK,1,2,3,4,5,-1,;",
    ):
        with pytest.raises(ProtocolError):
            read_joint_max_velocity(decode_reply(reply, expected=ReadCommand.JOINT_MAX_VELOCITY))
    with pytest.raises(ProtocolError):
        read_linear_max_motion(decode_reply(
            b"ReadLinearMaxVel,OK,2000,NaN,5000,;", expected=ReadCommand.LINEAR_MAX_MOTION,
        ))


def test_fake_motion_maxima_probe_sends_only_reads() -> None:
    with FakeHuayanController() as fake:
        result = read_motion_limits(fake_config(fake), byte_order="little")
        assert result["device_sn"] == "FAKE-E05-001"
        assert result["joint_max_velocity_deg_s"] == (150, 150, 160, 170, 180, 180)
        assert result["joint_max_acceleration_deg_s2"] == (300, 300, 320, 340, 350, 360)
        assert result["linear_max_velocity_mm_s"] == 2000
        assert result["linear_max_acceleration_mm_s2"] == 2500
        assert result["linear_max_jerk_mm_s3"] == 5000
        assert fake.received_commands[-6:] == [
            b"PackageVersion,;", b"ReadRobotModel,;", b"IsSimulation,;",
            b"ReadJointMaxVel,0,;", b"ReadJointMaxAcc,0,;", b"ReadLinearMaxVel,0,;",
        ]
        assert all(b"WayPoint" not in frame and b"GrpStop" not in frame for frame in fake.received_commands)


def test_changed_identity_stops_before_motion_maxima_reads() -> None:
    with FakeHuayanController(command_actions={
        ReadCommand.PACKAGE_VERSION: [
            CommandAction((b"PackageVersion,OK,6.3.6.20240305,;",)),
            CommandAction((b"PackageVersion,OK,unexpected-version,;",)),
        ],
    }) as fake:
        with pytest.raises(ValueError, match="identity changed"):
            read_motion_limits(fake_config(fake), byte_order="little")
        assert fake.received_commands[-1] == b"PackageVersion,;"
        assert b"ReadJointMaxVel,0,;" not in fake.received_commands


@pytest.mark.parametrize("action", ["--show-requests", "--check-config"])
def test_cli_dry_actions_never_open_a_socket(
    action: str, tmp_path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "real.yaml"
    config_path.write_text("""\
schema_version: '1.0'
allowed_control: observe-only
controller:
  host: 192.168.0.10
  command_port: 10003
  datasheet_port: 10004
  device_sn: CONFIRMED-SN
  asset_id: TEST-ONLY
  model: E05-Pro
  package_versions: ['6.3.6.20240305']
deadlines:
  state_stale_ms: 250
""", encoding="utf-8")
    def forbidden_socket(*_args, **_kwargs):
        raise AssertionError("dry action must not open a socket")
    monkeypatch.setattr("socket.create_connection", forbidden_socket)
    monkeypatch.setattr(sys, "argv", ["read_huayan_motion_limits", "--real-config", str(config_path), action])
    assert main() == 0
    assert "No network connection was opened" in capsys.readouterr().out or action == "--check-config"
    monkeypatch.setattr(sys, "argv", [
        "read_huayan_motion_limits", "--real-config", str(config_path),
        "--connect-real-read-only", "--byte-order", "little",
    ])
    with pytest.raises(SystemExit, match="2"):
        main()
