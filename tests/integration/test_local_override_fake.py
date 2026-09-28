"""Mac-local SetOverride with serial 10004 -> 10003 -> 10004 proof."""

from __future__ import annotations

import socket

import pytest

from edge_gateway import commissioning_cli
from edge_gateway.commissioning_runtime import set_override_and_confirm
from tests.fakes.huayan_controller import FakeHuayanController
from tests.unit.edge_gateway.test_real_motion_client import real_shaped_config


def _config(*, confirm_ms: int = 500):
    config = real_shaped_config()
    return config.model_copy(update={
        "controller": config.controller.model_copy(update={"device_sn": "FAKE-E05-001"}),
        "motion": config.motion.model_copy(update={"controller_override": 1.0}),
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


def test_override_is_written_then_confirmed_by_10003_and_new_10004_frame(monkeypatch) -> None:
    with FakeHuayanController(
        accept_fake_motion=True, initial_override=0.01,
    ) as fake:
        _redirect_both_channels(monkeypatch, fake)
        result = set_override_and_confirm(_config(), byte_order="little")

        assert result.initial_command_override == 0.01
        assert result.command_override == 1.0
        assert result.datasheet_override == 1.0
        assert result.write_sent is True
        assert result.datasheet_sequence >= 1
        assert fake.received_commands.count(b"SetOverride,0,1,;") == 1
        first_read = fake.received_commands.index(b"ReadOverride,0,;")
        write = fake.received_commands.index(b"SetOverride,0,1,;")
        second_read = fake.received_commands.index(b"ReadOverride,0,;", first_read + 1)
        assert first_read < write < second_read


def test_matching_override_is_read_and_cross_confirmed_without_write(monkeypatch) -> None:
    with FakeHuayanController(
        accept_fake_motion=True, initial_override=1.0,
    ) as fake:
        _redirect_both_channels(monkeypatch, fake)
        result = set_override_and_confirm(_config(), byte_order="little")

        assert result.initial_command_override == 1.0
        assert result.command_override == 1.0
        assert result.datasheet_override == 1.0
        assert result.write_sent is False
        assert not any(frame.startswith(b"SetOverride,") for frame in fake.received_commands)
        assert fake.received_commands.count(b"ReadOverride,0,;") == 2


def test_override_write_is_blocked_when_robot_is_moving(monkeypatch) -> None:
    with FakeHuayanController(
        accept_fake_motion=True, initial_moving=True, initial_override=0.01,
    ) as fake:
        _redirect_both_channels(monkeypatch, fake)
        with pytest.raises(PermissionError, match="stationary READY 10004"):
            set_override_and_confirm(_config(), byte_order="little")
        assert not any(frame.startswith(b"SetOverride,") for frame in fake.received_commands)


def test_override_ok_without_readback_change_is_rejected(monkeypatch) -> None:
    with FakeHuayanController(
        accept_fake_motion=True, initial_override=0.01,
        apply_group_state_changes=False,
    ) as fake:
        _redirect_both_channels(monkeypatch, fake)
        with pytest.raises(RuntimeError, match="ReadOverride disagrees"):
            set_override_and_confirm(_config(), byte_order="little")
        assert fake.received_commands.count(b"SetOverride,0,1,;") == 1
