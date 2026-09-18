from __future__ import annotations

import os

import pytest

from edge_gateway.audit import EdgeAudit
from edge_gateway.cloud_transport import validate_cloud_url
from surgical_contracts import load_gateway_secret, parse_wire_json


@pytest.mark.parametrize("url", [
    "ws://192.168.0.10:8001/v1/gateway/connect",
    "ws://remote.example:8001/v1/gateway/connect",
    "ws://127.0.0.1:8001/v1/gateway/connect?token=secret",
    "wss://remote.example:8001/v1/gateway/connect",
])
def test_plain_gateway_transport_is_loopback_ssh_tunnel_only(url: str) -> None:
    with pytest.raises(ValueError):
        validate_cloud_url(url)
    assert validate_cloud_url("ws://127.0.0.1:18001/v1/gateway/connect")


def test_secret_file_permissions_and_wire_parser_fail_closed(tmp_path) -> None:
    secret = tmp_path / "gateway-auth.local"
    secret.write_bytes(b"x" * 32)
    os.chmod(secret, 0o644)
    with pytest.raises(ValueError, match="0600"):
        load_gateway_secret(secret)
    os.chmod(secret, 0o600)
    assert load_gateway_secret(secret) == b"x" * 32
    with pytest.raises(ValueError, match="duplicate"):
        parse_wire_json('{"type":"state","type":"heartbeat"}')
    with pytest.raises(ValueError, match="non-finite"):
        parse_wire_json('{"age":NaN}')
    with pytest.raises(ValueError, match="maximum"):
        parse_wire_json("x" * (64 * 1024 + 1))


def test_audit_is_rotating_and_refuses_secret_fields(tmp_path) -> None:
    path = tmp_path / "edge.log"
    audit = EdgeAudit(path)
    try:
        audit.record("cloud_connected", gateway_id="mac-test")
        with pytest.raises(ValueError, match="allowlisted"):
            audit.record("bad", token="do-not-log")
    finally:
        audit.close()
    assert "mac-test" in path.read_text()
    assert "do-not-log" not in path.read_text()
