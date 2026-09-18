from __future__ import annotations

import sys
import os
import json
import time

import pytest

from edge_gateway.huayan.adapter import (
    read_axis_error_code, read_base_installing_angle, read_coordinate_value,
    read_payload,
)
from edge_gateway.huayan.command_client import CommandClient
from edge_gateway.huayan.command_codec import decode_reply, encode_read
from edge_gateway.huayan.datasheet_client import DatasheetClient
from edge_gateway.huayan.models import ProtocolError, ReadCommand
from edge_gateway.huayan.real_probe import (
    main, probe_once, validate_probe_config, validate_probe_summary,
)
from edge_gateway.config import RealEdgeConfig
from edge_gateway.main import EdgeGateway, main as gateway_main
from robot_runtime.real_config import RealRobotConfig
from tests.fakes.huayan_controller import CommandAction, FakeHuayanController


def fake_config(fake: FakeHuayanController, *, version: str = "6.3.6.20240305") -> RealRobotConfig:
    return RealRobotConfig.model_validate({
        "allowed_control": "observe-only",
        "controller": {
            "host": "127.0.0.1",
            "command_port": fake.command_port,
            "datasheet_port": fake.datasheet_port,
            "device_sn": "FAKE-E05-001",
            "model": "E05-Pro",
            "package_versions": [version],
        },
        "deadlines": {"state_stale_ms": 250},
    })


def test_step6_read_commands_are_exact_and_named_reads_are_validated() -> None:
    assert encode_read(ReadCommand.AXIS_ERROR_CODE) == b"ReadAxisErrorCode,0,;"
    assert encode_read(ReadCommand.PAYLOAD) == b"ReadPayload,0,;"
    assert encode_read(ReadCommand.BASE_INSTALLING_ANGLE) == b"GetBaseInstallingAngle,0,;"
    assert encode_read(ReadCommand.CURRENT_TCP) == b"ReadCurTCP,0,;"
    assert encode_read(ReadCommand.CURRENT_UCS) == b"ReadCurUCS,0,;"
    assert encode_read(ReadCommand.TCP_BY_NAME, name="TCP_1") == b"ReadTCPByName,0,TCP_1,;"
    assert encode_read(ReadCommand.UCS_BY_NAME, name="Point_1") == b"ReadUCSByName,0,Point_1,;"
    with pytest.raises(ValueError):
        encode_read(ReadCommand.TCP_BY_NAME)
    with pytest.raises(ValueError):
        encode_read(ReadCommand.TCP_BY_NAME, name="TCP,1")
    with pytest.raises(ValueError):
        encode_read(ReadCommand.PAYLOAD, name="unexpected")
    with pytest.raises(TypeError):
        encode_read("SetPayload")  # type: ignore[arg-type]


def test_step6_reply_values_are_strictly_typed() -> None:
    axis = read_axis_error_code(decode_reply(
        b"ReadAxisErrorCode,OK,0,0,0,0,0,0,0,;", expected=ReadCommand.AXIS_ERROR_CODE,
    ))
    assert axis.joint_error_codes == (0, 0, 0, 0, 0, 0)
    payload = read_payload(decode_reply(
        b"ReadPayload,OK,1.5,-12,25,39,;", expected=ReadCommand.PAYLOAD,
    ))
    assert payload.mass_kg == 1.5
    assert payload.center_of_gravity_mm[0] == -12
    assert read_base_installing_angle(decode_reply(
        b"GetBaseInstallingAngle,OK,-90,90,;", expected=ReadCommand.BASE_INSTALLING_ANGLE,
    )) == (-90, 90)
    assert len(read_coordinate_value(decode_reply(
        b"ReadCurTCP,OK,60,80,120,50,0,0,;", expected=ReadCommand.CURRENT_TCP,
    ))) == 6
    with pytest.raises(ProtocolError):
        read_payload(decode_reply(
            b"ReadPayload,OK,NaN,0,0,0,;", expected=ReadCommand.PAYLOAD,
        ))
    with pytest.raises(ProtocolError):
        read_base_installing_angle(decode_reply(
            b"GetBaseInstallingAngle,OK,361,0,;", expected=ReadCommand.BASE_INSTALLING_ANGLE,
        ))


def test_real_scope_accepts_only_literal_private_ipv4_and_defaults_stay_loopback() -> None:
    assert CommandClient("192.168.0.10", 10003, scope="private-read-only").host == "192.168.0.10"
    assert DatasheetClient(
        "192.168.0.10", 10004, byte_order="little", scope="private-read-only",
    ).host == "192.168.0.10"
    for host in ("example.com", "8.8.8.8", "127.0.0.1", "::1"):
        with pytest.raises(ValueError):
            CommandClient(host, 10003, scope="private-read-only")
    with pytest.raises(ValueError):
        CommandClient("192.168.0.10", 10003)


def test_real_gateway_requires_private_host_and_confirmed_identity(tmp_path) -> None:
    common = dict(
        command_port=10003, datasheet_port=10004,
        expected_device_sn="CONFIRMED-SN", expected_robot_model="E05-Pro",
        approved_package_versions=("6.3.6.20240305",),
        server_url="ws://127.0.0.1:18001/v1/gateway/connect",
        secret_file=tmp_path / "secret", gateway_id="mac-edge",
        config_sha256="a" * 64, datasheet_byte_order="little",
        audit_path=tmp_path / "audit.log", stale_ms=250,
    )
    assert RealEdgeConfig(controller_host="192.168.0.10", **common).controller_host == "192.168.0.10"
    with pytest.raises(ValueError):
        RealEdgeConfig(controller_host="127.0.0.1", **common)
    with pytest.raises(ValueError):
        RealEdgeConfig(controller_host="192.168.0.10", **{**common, "expected_device_sn": ""})


def test_real_gateway_checks_approved_version_before_other_queries(tmp_path) -> None:
    with FakeHuayanController() as fake:
        secret = tmp_path / "secret"
        secret.write_bytes(b"x" * 32)
        os.chmod(secret, 0o600)
        config = RealEdgeConfig(
            controller_host="192.168.0.10", command_port=10003,
            datasheet_port=10004, expected_device_sn="FAKE-E05-001",
            expected_robot_model="E05-Pro", approved_package_versions=("not-the-fake-version",),
            server_url="ws://127.0.0.1:18001/v1/gateway/connect",
            secret_file=secret, gateway_id="mac-edge", config_sha256="a" * 64,
            datasheet_byte_order="little", audit_path=tmp_path / "audit.log", stale_ms=250,
        )
        gateway = EdgeGateway(config)
        # Replace only the network endpoint with the fake; retain real-mode identity checks.
        gateway._command = CommandClient("127.0.0.1", fake.command_port)
        try:
            with pytest.raises(ValueError, match="PackageVersion"):
                gateway._query_identity()
            assert gateway.state.fault
            assert fake.received_commands == [b"PackageVersion,;"]
        finally:
            gateway.close()


@pytest.mark.parametrize("stamp_every_n_frames,should_fault", [(3, False), (1000, True)])
def test_real_gateway_accepts_repeated_stamps_but_faults_on_source_stall(
    tmp_path, stamp_every_n_frames: int, should_fault: bool,
) -> None:
    with FakeHuayanController(stamp_every_n_frames=stamp_every_n_frames) as fake:
        secret = tmp_path / "secret"
        secret.write_bytes(b"x" * 32)
        os.chmod(secret, 0o600)
        config = RealEdgeConfig(
            controller_host="192.168.0.10", command_port=10003,
            datasheet_port=10004, expected_device_sn="FAKE-E05-001",
            expected_robot_model="E05-Pro", approved_package_versions=("6.3.6.20240305",),
            server_url="ws://127.0.0.1:18001/v1/gateway/connect",
            secret_file=secret, gateway_id="mac-edge", config_sha256="a" * 64,
            datasheet_byte_order="little", audit_path=tmp_path / "audit.log", stale_ms=250,
        )
        gateway = EdgeGateway(config)
        gateway._controller_host = "127.0.0.1"
        gateway._datasheet_port = fake.datasheet_port
        gateway._scope = "loopback"
        gateway._command = CommandClient("127.0.0.1", fake.command_port)
        try:
            gateway.start()
            deadline = time.monotonic() + 1.0
            while should_fault and not gateway.state.fault and time.monotonic() < deadline:
                time.sleep(0.02)
            if not should_fault:
                time.sleep(0.4)
            assert gateway.state.fault is should_fault
            if should_fault:
                assert "source_stamp_invalid" in (tmp_path / "audit.log").read_text()
        finally:
            gateway.close()


def test_fake_probe_reads_only_allowlisted_commands_and_captures_one_frame(tmp_path) -> None:
    with FakeHuayanController() as fake:
        config = fake_config(fake)
        result = probe_once(
            config, byte_order="little",
            approved_tcp_name="TCP_1", approved_ucs_name="Point_1",
        )
        assert result.summary["control_mode"] == "observe-only"
        assert result.summary["device_sn"] == "FAKE-E05-001"
        assert result.summary["joint_positions_deg"][2] == 81.099
        assert result.raw_datasheet_frame.startswith(b"LTBR")
        assert [item.split(b",", 1)[0] for item in fake.received_commands] == [
            b"PackageVersion", b"ReadRobotModel", b"IsSimulation", b"ReadControllerState",
            b"ReadFastCmdPort", b"ReadRobotState", b"ReadCurFSM", b"ReadActPos",
            b"ReadAxisErrorCode", b"ReadEmergencyInfo", b"ReadPayload",
            b"GetBaseInstallingAngle", b"ReadCurTCP", b"ReadCurUCS",
            b"ReadTCPByName", b"ReadUCSByName",
        ]
        summary_file = tmp_path / "summary.json"
        summary_file.write_text(json.dumps(result.summary), encoding="utf-8")
        validate_probe_summary(summary_file, config, byte_order="little")
        with pytest.raises(ValueError, match="disagrees"):
            validate_probe_summary(summary_file, config, byte_order="big")


def test_probe_stops_on_unapproved_version_before_other_queries() -> None:
    with FakeHuayanController(command_actions={
        ReadCommand.PACKAGE_VERSION: [CommandAction((b"PackageVersion,OK,unapproved,;",))],
    }) as fake:
        with pytest.raises(ValueError, match="PackageVersion"):
            probe_once(fake_config(fake), byte_order="little")
        assert fake.received_commands == [b"PackageVersion,;"]


def test_real_probe_cli_requires_explicit_gate_and_check_config_never_connects(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "robot-real.local.yaml"
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
        raise AssertionError("check-config must not open a TCP socket")
    monkeypatch.setattr("socket.create_connection", forbidden_socket)
    monkeypatch.setattr(sys, "argv", [
        "probe", "--real-config", str(config_path), "--check-config",
    ])
    assert main() == 0
    monkeypatch.setattr(sys, "argv", [
        "probe", "--real-config", str(config_path), "--connect-real-read-only",
        "--byte-order", "little",
    ])
    with pytest.raises(SystemExit, match="2"):
        main()

    monkeypatch.setattr(sys, "argv", [
        "gateway", "--real-config", str(config_path),
        "--server-url", "ws://127.0.0.1:18001/v1/gateway/connect",
        "--secret-file", str(tmp_path / "secret"), "--gateway-id", "mac-edge",
        "--datasheet-byte-order", "little",
    ])
    with pytest.raises(SystemExit, match="2"):
        gateway_main()
