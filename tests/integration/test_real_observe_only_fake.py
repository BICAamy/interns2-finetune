from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path
from urllib.request import urlopen
import json

import uvicorn

from edge_gateway.config import EdgeConfig
from edge_gateway.config import RealEdgeConfig
from edge_gateway.main import EdgeGateway
from edge_gateway.huayan.command_client import CommandClient
from robot_runtime.api import create_app
from robot_runtime.gateway_session import GatewaySessionManager
from robot_runtime.providers.huayan_real import HuayanRealStubProvider
from tests.fakes.huayan_controller import FakeHuayanController

SECRET = b"step5-test-only-shared-secret-32-bytes!!"


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _json(url: str) -> dict:
    with urlopen(url, timeout=1) as response:
        return json.load(response)


def test_fake_controller_to_mac_gateway_to_runtime_is_read_only(tmp_path: Path) -> None:
    secret_file = tmp_path / "gateway-auth.local"
    secret_file.write_bytes(SECRET)
    os.chmod(secret_file, 0o600)
    sessions = GatewaySessionManager(
        secret=SECRET,
        gateway_id="mac-edge-test",
        device_sn="FAKE-E05-001",
        robot_model="E05-Pro",
        package_versions=("6.3.6.20240305",),
        config_sha256="a" * 64,
        stale_ms=350,
        transit_budget_ms=20,
    )
    app = create_app(provider=HuayanRealStubProvider(sessions), mode="real")
    server_port = _free_port()
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=server_port, log_level="error",
        ws_max_size=64 * 1024,
    ))
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    errors: list[Exception] = []
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                if _json(f"http://127.0.0.1:{server_port}/health"):
                    break
            except OSError:
                time.sleep(0.02)
        else:
            raise AssertionError("test robot runtime did not start")

        with FakeHuayanController() as fake:
            config = EdgeConfig(
                fake_command_port=fake.command_port,
                fake_datasheet_port=fake.datasheet_port,
                server_url=f"ws://127.0.0.1:{server_port}/v1/gateway/connect",
                secret_file=secret_file,
                gateway_id="mac-edge-test",
                config_sha256="a" * 64,
                datasheet_byte_order="little",
                audit_path=tmp_path / "edge-audit.log",
                stale_ms=350,
            )
            gateway = EdgeGateway(config)

            def run_gateway() -> None:
                try:
                    gateway.run(max_runtime_s=2.0)
                except Exception as exc:
                    errors.append(exc)

            gateway_thread = threading.Thread(target=run_gateway, daemon=True)
            gateway_thread.start()
            deadline = time.monotonic() + 2
            seen = None
            while time.monotonic() < deadline:
                health = _json(f"http://127.0.0.1:{server_port}/health")
                if health["status"] == "healthy":
                    seen = _json(f"http://127.0.0.1:{server_port}/v1/state")
                    if seen["joint_positions_deg"]:
                        break
                time.sleep(0.02)
            assert seen is not None and seen["joint_positions_deg"][2] == 81.099
            assert seen["runtime_mode"] == "real"
            assert seen["control_mode"] == "observe-only"
            assert seen["actual_pose_robot_base"]["frame"] == "robot_base"
            assert health["ready_for_motion"] is False
            first_session_id = seen["gateway_session_id"]
            first_sequence = seen["sequence"]
            time.sleep(0.18)
            next_state = _json(f"http://127.0.0.1:{server_port}/v1/state")
            assert next_state["sequence"] >= first_sequence + 2
            assert fake.received_commands
            assert all(not item.startswith(b"WayPoint") for item in fake.received_commands)

            from urllib.error import HTTPError
            from urllib.request import Request

            body = b'{"command_id":"fake-motion-1","translation_mm":[0,0,1]}'
            request = Request(
                f"http://127.0.0.1:{server_port}/v1/commands/move-relative",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urlopen(request, timeout=1)
                raise AssertionError("real motion was not rejected")
            except HTTPError as exc:
                assert exc.code == 403
                assert json.load(exc)["code"] == "OPERATION_NOT_ENABLED"

            gateway_thread.join(timeout=4)
            assert not gateway_thread.is_alive()
            assert not errors, errors
            assert _json(f"http://127.0.0.1:{server_port}/health")["error"] == "gateway_disconnected"

            # Exercise the real-mode identity checks against the fake, while
            # replacing the physical network endpoint with loopback in this test.
            real_config = RealEdgeConfig(
                controller_host="192.168.0.10",
                command_port=10003,
                datasheet_port=10004,
                expected_device_sn="FAKE-E05-001",
                expected_robot_model="E05-Pro",
                approved_package_versions=("6.3.6.20240305",),
                server_url=config.server_url,
                secret_file=secret_file,
                gateway_id=config.gateway_id,
                config_sha256=config.config_sha256,
                datasheet_byte_order="little",
                audit_path=tmp_path / "real-mode-fake-audit.log",
                stale_ms=350,
            )
            real_mode_gateway = EdgeGateway(real_config)
            real_mode_gateway._controller_host = "127.0.0.1"
            real_mode_gateway._datasheet_port = fake.datasheet_port
            real_mode_gateway._scope = "loopback"
            real_mode_gateway._command = CommandClient("127.0.0.1", fake.command_port)

            def run_real_mode_against_fake() -> None:
                try:
                    real_mode_gateway.run(max_runtime_s=0.8)
                except Exception as exc:
                    errors.append(exc)

            real_mode_thread = threading.Thread(target=run_real_mode_against_fake, daemon=True)
            real_mode_thread.start()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                real_health = _json(f"http://127.0.0.1:{server_port}/health")
                if real_health["status"] == "healthy":
                    break
                time.sleep(0.02)
            else:
                raise AssertionError("real-mode gateway did not publish fake state")
            assert real_health["ready_for_motion"] is False
            assert _json(f"http://127.0.0.1:{server_port}/v1/state")["device_sn"] == "FAKE-E05-001"
            real_mode_thread.join(timeout=3)
            assert not real_mode_thread.is_alive()
            assert not errors, errors

            # Restart only the Mac process while the fake and server stay up.
            # Its old session must not be reused or regain control authority.
            restarted = EdgeGateway(config)

            def run_restarted() -> None:
                try:
                    restarted.run(max_runtime_s=0.8)
                except Exception as exc:
                    errors.append(exc)

            restarted_thread = threading.Thread(target=run_restarted, daemon=True)
            restarted_thread.start()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                restarted_health = _json(f"http://127.0.0.1:{server_port}/health")
                restarted_state = _json(f"http://127.0.0.1:{server_port}/v1/state")
                if restarted_health["status"] == "healthy" and restarted_state["gateway_session_id"] != first_session_id:
                    break
                time.sleep(0.02)
            else:
                raise AssertionError("restarted gateway did not establish a fresh session")
            assert restarted_state["control_mode"] == "observe-only"
            assert restarted_health["ready_for_motion"] is False
            restarted_thread.join(timeout=3)
            assert not restarted_thread.is_alive()
            assert not errors, errors
            assert _json(f"http://127.0.0.1:{server_port}/health")["error"] == "gateway_disconnected"
    finally:
        server.should_exit = True
        server_thread.join(timeout=3)
