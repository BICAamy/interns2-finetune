from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from robot_runtime.api import create_app
from robot_runtime.main import app_from_environment
from robot_runtime.providers.huayan_real import HuayanRealStubProvider
from robot_runtime.real_config import load_real_config
from tests.unit.robot_runtime.test_gateway_session import SECRET, hello, manager, state_frame


def test_authenticated_websocket_accepts_state_then_closes_on_duplicate_sequence() -> None:
    sessions = manager([1_000_000_000])
    app = create_app(provider=HuayanRealStubProvider(sessions), mode="real")
    with TestClient(app) as client:
        with client.websocket_connect("/v1/gateway/connect") as ws:
            challenge = ws.receive_json()["challenge"]
            greeting = hello(challenge)
            ws.send_json(greeting.model_dump(mode="json"))
            assert ws.receive_json()["control_mode"] == "observe-only"
            frame = state_frame(greeting.handshake.gateway_session_id)
            ws.send_json(frame.model_dump(mode="json"))
            assert ws.receive_json() == {"type": "ack", "message_sequence": 1}
            assert client.get("/health").json()["status"] == "healthy"
            ws.send_json(frame.model_dump(mode="json"))
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == 1008
        assert client.get("/health").json()["error"] == "gateway_disconnected"


def test_gateway_rejects_wrong_secret_concurrent_socket_and_oversized_frame() -> None:
    sessions = manager([1_000_000_000])
    app = create_app(provider=HuayanRealStubProvider(sessions), mode="real")
    with TestClient(app) as client:
        with client.websocket_connect("/v1/gateway/connect") as bad:
            challenge = bad.receive_json()["challenge"]
            bad.send_json(hello(challenge, secret=b"wrong" * 8).model_dump(mode="json"))
            with pytest.raises(WebSocketDisconnect):
                bad.receive_json()
        with client.websocket_connect("/v1/gateway/connect") as first:
            challenge = first.receive_json()["challenge"]
            greeting = hello(challenge)
            first.send_json(greeting.model_dump(mode="json"))
            assert first.receive_json()["type"] == "accepted"
            with client.websocket_connect("/v1/gateway/connect") as second:
                other_challenge = second.receive_json()["challenge"]
                second.send_json(hello(other_challenge).model_dump(mode="json"))
                with pytest.raises(WebSocketDisconnect):
                    second.receive_json()
            first.send_text("x" * (64 * 1024 + 1))
            with pytest.raises(WebSocketDisconnect):
                first.receive_json()


def test_gateway_endpoint_is_closed_without_configured_secret() -> None:
    with TestClient(create_app(mode="real")) as client:
        with client.websocket_connect("/v1/gateway/connect") as ws:
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == 1008


def test_real_process_environment_loads_authenticated_observe_only_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    example = Path(__file__).resolve().parents[3] / "configs" / "robot-real.example.yaml"
    config_data = yaml.safe_load(example.read_text(encoding="utf-8"))
    config_data["controller"]["device_sn"] = "FAKE-E05-001"
    config_data["controller"]["package_versions"] = ["6.3.6.20240305"]
    config_data["deadlines"]["state_stale_ms"] = 350
    config_path = tmp_path / "robot-real-fake.yaml"
    config_path.write_text(yaml.safe_dump(config_data), encoding="utf-8")
    digest = load_real_config(config_path).digest()
    secret_path = tmp_path / "gateway-auth.local"
    secret_path.write_bytes(SECRET)
    os.chmod(secret_path, 0o600)
    monkeypatch.setenv("ROBOT_MODE", "real")
    monkeypatch.setenv("RUNTIME_MODE", "real")
    monkeypatch.setenv("REAL_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("REAL_CONFIG_SHA256", digest)
    monkeypatch.setenv("ROBOT_CONTROL_MODE", "observe-only")
    monkeypatch.setenv("GATEWAY_AUTH_SECRET_FILE", str(secret_path))
    monkeypatch.setenv("GATEWAY_EXPECTED_ID", "mac-edge-test")

    with TestClient(app_from_environment()) as client:
        health = client.get("/health").json()
        assert health["error"] == "gateway_disconnected"
        assert health["ready_for_motion"] is False
        with client.websocket_connect("/v1/gateway/connect") as ws:
            challenge = ws.receive_json()["challenge"]
            greeting = hello(challenge, config_sha256=digest)
            ws.send_json(greeting.model_dump(mode="json"))
            assert ws.receive_json()["gateway_session_id"] == greeting.handshake.gateway_session_id
            assert client.get("/health").json()["control_mode"] == "observe-only"
