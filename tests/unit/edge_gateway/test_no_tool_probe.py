"""Read-only evidence for the flange-only profile; no motion socket is used."""

from __future__ import annotations

import json

import pytest

from edge_gateway.huayan.models import ReadCommand
from edge_gateway.huayan.real_probe import probe_once, validate_probe_summary
from robot_runtime.real_config import RealRobotConfig
from tests.fakes.huayan_controller import CommandAction, FakeHuayanController


def no_tool_config(fake: FakeHuayanController) -> RealRobotConfig:
    return RealRobotConfig.model_validate({
        "controller": {
            "host": "127.0.0.1",
            "command_port": fake.command_port,
            "datasheet_port": fake.datasheet_port,
            "device_sn": "FAKE-E05-001",
            "model": "E05-Pro",
            "package_versions": ["6.3.6.20240305"],
        },
        "tool": {
            "setup": "flange_only_no_tool",
            "tcp_name": "FAKE_FLANGE",
            "flange_to_tcp": {
                "translation_mm": [0, 0, 0],
                "quaternion_xyzw": [0, 0, 0, 1],
            },
            "payload_kg": 0,
            "center_of_gravity_mm": [0, 0, 0],
            "mount_angle_deg": [0, 0],
        },
        "deadlines": {"state_stale_ms": 250},
    })


def zero_read_actions() -> dict[ReadCommand, list[CommandAction]]:
    zero6 = b"0,0,0,0,0,0,;"
    return {
        ReadCommand.PAYLOAD: [CommandAction((b"ReadPayload,OK,0,0,0,0,;",))],
        ReadCommand.BASE_INSTALLING_ANGLE: [CommandAction((b"GetBaseInstallingAngle,OK,0,0,;",))],
        ReadCommand.CURRENT_TCP: [CommandAction((b"ReadCurTCP,OK," + zero6,))],
        ReadCommand.TCP_BY_NAME: [CommandAction((b"ReadTCPByName,OK," + zero6,))],
    }


def test_no_tool_probe_reads_current_and_named_zero_values_then_validates_record(tmp_path) -> None:
    with FakeHuayanController(command_actions=zero_read_actions()) as fake:
        config = no_tool_config(fake)
        result = probe_once(config, byte_order="little")
        assert result.summary["no_tool_readback_verified"] is True
        assert result.summary["approved_tcp_name"] == "FAKE_FLANGE"
        assert result.summary["approved_ucs_name"] == "Base"
        assert b"ReadTCPByName,0,FAKE_FLANGE,;" in fake.received_commands
        assert b"ReadUCSByName,0,Base,;" in fake.received_commands
        assert all(b"WayPoint" not in item and b"GrpStop" not in item for item in fake.received_commands)

        record = tmp_path / "probe.json"
        record.write_text(json.dumps(result.summary), encoding="utf-8")
        validate_probe_summary(record, config, byte_order="little")

        changed = dict(result.summary)
        changed["payload"] = {**changed["payload"], "mass_kg": 0.1}
        record.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(ValueError, match="no-tool"):
            validate_probe_summary(record, config, byte_order="little")


@pytest.mark.parametrize("command", [
    ReadCommand.PAYLOAD, ReadCommand.CURRENT_TCP,
    ReadCommand.TCP_BY_NAME, ReadCommand.BASE_INSTALLING_ANGLE,
])
def test_no_tool_probe_rejects_nonzero_controller_readback(command: ReadCommand) -> None:
    changes = {
        ReadCommand.PAYLOAD: b"ReadPayload,OK,0.1,0,0,0,;",
        ReadCommand.CURRENT_TCP: b"ReadCurTCP,OK,1,0,0,0,0,0,;",
        ReadCommand.TCP_BY_NAME: b"ReadTCPByName,OK,1,0,0,0,0,0,;",
        ReadCommand.BASE_INSTALLING_ANGLE: b"GetBaseInstallingAngle,OK,1,0,;",
    }
    actions = zero_read_actions()
    actions[command] = [CommandAction((changes[command],))]
    with FakeHuayanController(command_actions=actions) as fake:
        with pytest.raises(ValueError, match="no-tool"):
            probe_once(no_tool_config(fake), byte_order="little")
        assert all(b"WayPoint" not in item and b"GrpStop" not in item for item in fake.received_commands)


def test_no_tool_probe_rejects_wrong_requested_tcp_name_before_connecting() -> None:
    with FakeHuayanController(command_actions=zero_read_actions()) as fake:
        with pytest.raises(ValueError, match="TCP name"):
            probe_once(no_tool_config(fake), byte_order="little", approved_tcp_name="OTHER")
        assert fake.received_commands == []
