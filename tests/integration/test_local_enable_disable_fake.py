"""Mac-local group enable/disable against both fake controller channels."""

from __future__ import annotations

import socket

import pytest

from edge_gateway import commissioning_cli
from edge_gateway.commissioning_runtime import set_enabled_and_confirm
from edge_gateway.huayan.models import ProtocolError, ReadCommand
from tests.fakes.huayan_controller import (
    CommandAction, FakeHuayanController, datasheet_document, datasheet_frame,
)
from tests.unit.edge_gateway.test_real_motion_client import real_shaped_config


def _config(*, confirm_ms: int = 500):
    config = real_shaped_config()
    return config.model_copy(update={
        "controller": config.controller.model_copy(update={"device_sn": "FAKE-E05-001"}),
        "deadlines": config.deadlines.model_copy(update={"startup_ms": confirm_ms}),
    })


def _redirect_both_channels(monkeypatch, fake: FakeHuayanController) -> None:
    original = socket.create_connection

    def connect(address, timeout=None):
        if address == ("192.168.0.10", 10003):
            return original(("127.0.0.1", fake.command_port), timeout)
        if address == ("192.168.0.10", 10004):
            return original(("127.0.0.1", fake.datasheet_port), timeout)
        raise AssertionError(f"unexpected network target: {address}")

    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr(commissioning_cli, "require_local_mac_terminal", lambda: None)


@pytest.mark.parametrize("target,frame", [
    (True, b"GrpEnable,0,;"),
    (False, b"GrpDisable,0,;"),
])
def test_group_state_write_requires_new_agreeing_10003_and_10004_feedback(
    monkeypatch, target, frame,
) -> None:
    config = _config()
    with FakeHuayanController(
        accept_fake_motion=True, initial_enabled=not target,
    ) as fake:
        _redirect_both_channels(monkeypatch, fake)
        result = set_enabled_and_confirm(
            config, enabled=target, byte_order="little",
        )
        assert result.command_enabled is target
        assert result.datasheet_enabled is target
        assert result.command_moving is False
        assert result.datasheet_moving is False
        assert result.datasheet_sequence >= 1
        assert fake.received_commands.count(frame) == 1
        write_index = fake.received_commands.index(frame)
        assert any(
            command.startswith(b"ReadRobotState,")
            for command in fake.received_commands[write_index + 1:]
        )


def test_disable_is_blocked_before_write_when_either_live_channel_is_moving(monkeypatch) -> None:
    config = _config()
    with FakeHuayanController(
        accept_fake_motion=True, initial_enabled=True, initial_moving=True,
    ) as fake:
        _redirect_both_channels(monkeypatch, fake)
        with pytest.raises(PermissionError, match="stationary"):
            set_enabled_and_confirm(
                config, enabled=False, byte_order="little",
            )
        assert b"GrpDisable,0,;" not in fake.received_commands


def test_ok_reply_without_real_state_change_times_out(monkeypatch) -> None:
    config = _config(confirm_ms=150)
    with FakeHuayanController(
        accept_fake_motion=True,
        initial_enabled=True,
        apply_group_state_changes=False,
    ) as fake:
        _redirect_both_channels(monkeypatch, fake)
        with pytest.raises(TimeoutError, match="confirmation timed out"):
            set_enabled_and_confirm(
                config, enabled=False, byte_order="little",
            )
        assert fake.received_commands.count(b"GrpDisable,0,;") == 1


def test_datasheet_on_command_socket_fails_closed_before_disable_write(monkeypatch) -> None:
    config = _config()
    with FakeHuayanController(
        accept_fake_motion=True,
        initial_enabled=True,
        command_actions={ReadCommand.ROBOT_STATE: [
            CommandAction((datasheet_frame(datasheet_document()),)),
        ]},
    ) as fake:
        _redirect_both_channels(monkeypatch, fake)
        with pytest.raises(ProtocolError, match="DataSheet LTBR.*10003"):
            set_enabled_and_confirm(
                config, enabled=False, byte_order="little",
            )
        assert b"GrpDisable,0,;" not in fake.received_commands


def test_disable_uses_configured_response_deadline_not_old_500ms_cap(monkeypatch) -> None:
    config = _config(confirm_ms=2000)
    with FakeHuayanController(
        accept_fake_motion=True,
        initial_enabled=True,
        motion_actions={
            "GrpDisable": [CommandAction((b"GrpDisable,OK,;",), delay_s=0.6)],
        },
    ) as fake:
        _redirect_both_channels(monkeypatch, fake)
        result = set_enabled_and_confirm(
            config, enabled=False, byte_order="little",
        )
        assert result.command_enabled is False
        assert result.datasheet_enabled is False
        assert fake.received_commands.count(b"GrpDisable,0,;") == 1
