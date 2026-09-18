"""Step 3 mode matrix: config-only checks never start a service or open hardware."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess

import pytest
import yaml

from fastapi.testclient import TestClient

from agent.config import AgentSettings
from surgical_contracts import RuntimeMode
from web.backend.main import create_app
from web.backend.runtime import WebRuntime

APP_ROOT = Path(__file__).resolve().parents[2]
START = APP_ROOT / "scripts" / "services" / "start_all.sh"
EXAMPLE = APP_ROOT / "configs" / "robot-real.example.yaml"


def check(
    *arguments: str,
    extra_env: dict[str, str] | None = None,
    cwd: Path = APP_ROOT,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for name in (
        "RUNTIME_MODE", "ROBOT_MODE", "ROBOT_CONTROL_MODE", "REAL_CONFIG_PATH",
        "REAL_CONFIG_SHA256", "GATEWAY_AUTH_SECRET_FILE", "GATEWAY_EXPECTED_ID",
        "ROBOT_REAL_MIRROR",
    ):
        env.pop(name, None)
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", str(START), *arguments, "--check-config"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


@pytest.mark.parametrize("arguments", [(), ("--robot-mode", "simulation")])
def test_simulation_defaults_and_explicit_mode(arguments: tuple[str, ...]) -> None:
    result = check(*arguments)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "SIMULATION"


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (("--robot-mode", "invalid"), "--robot-mode must be"),
        (("--robot-mode", "simulation", "--real-config", str(EXAMPLE)), "not allowed"),
        (("--robot-mode", "real"), "requires --real-config"),
        (("--real-control", "enabled"), "only valid in real mode"),
        (("--robot-mode", "real", "--real-config", "missing.yaml"), "does not exist"),
    ],
)
def test_invalid_combinations_fail_before_start(arguments: tuple[str, ...], message: str) -> None:
    result = check(*arguments)
    assert result.returncode != 0
    assert message in result.stderr
    assert "[1/4] Starting" not in result.stdout


def test_real_config_is_observe_only_even_when_enabled_requested() -> None:
    for suffix in ((), ("--real-control", "enabled")):
        result = check("--robot-mode", "real", "--real-config", str(EXAMPLE), *suffix)
        assert result.returncode == 0, result.stderr
        assert "REAL / OBSERVE ONLY" in result.stdout
        assert "blocking_fields=" in result.stdout
        assert re.search(r"REAL_CONFIG_SHA256=[0-9a-f]{64}", result.stdout)
        assert "[1/4] Starting" not in result.stdout


def test_gateway_authentication_fails_preflight_without_both_inputs_or_confirmed_identity(
    tmp_path: Path,
) -> None:
    secret = tmp_path / "gateway-auth.local"
    secret.write_bytes(b"x" * 32)
    os.chmod(secret, 0o600)
    arguments = ("--robot-mode", "real", "--real-config", str(EXAMPLE))
    missing_id = check(*arguments, extra_env={"GATEWAY_AUTH_SECRET_FILE": str(secret)})
    assert missing_id.returncode != 0
    assert "requires both" in missing_id.stderr
    unconfirmed = check(*arguments, extra_env={
        "GATEWAY_AUTH_SECRET_FILE": str(secret), "GATEWAY_EXPECTED_ID": "mac-edge-test",
    })
    assert unconfirmed.returncode != 0
    assert "gateway authentication preflight failed" in unconfirmed.stderr
    assert "[1/4] Starting" not in unconfirmed.stdout
    simulation = check(extra_env={"GATEWAY_AUTH_SECRET_FILE": str(secret)})
    assert simulation.returncode != 0
    assert "only valid in real mode" in simulation.stderr


def test_gateway_authentication_preflight_accepts_complete_fake_identity(tmp_path: Path) -> None:
    config_data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    config_data["controller"]["device_sn"] = "FAKE-E05-001"
    config_data["controller"]["package_versions"] = ["6.3.6.20240305"]
    config_data["deadlines"]["state_stale_ms"] = 350
    config_path = tmp_path / "robot-real-fake.yaml"
    config_path.write_text(yaml.safe_dump(config_data), encoding="utf-8")
    secret = tmp_path / "gateway-auth.local"
    secret.write_bytes(b"x" * 32)
    os.chmod(secret, 0o600)
    result = check(
        "--robot-mode", "real", "--real-config", str(config_path),
        extra_env={
            "GATEWAY_AUTH_SECRET_FILE": str(secret),
            "GATEWAY_EXPECTED_ID": "mac-edge-test",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "REAL / OBSERVE ONLY" in result.stdout
    assert "[1/4] Starting" not in result.stdout
    mirror = check(
        "--robot-mode", "real", "--real-config", str(config_path),
        extra_env={
            "GATEWAY_AUTH_SECRET_FILE": str(secret),
            "GATEWAY_EXPECTED_ID": "mac-edge-test",
            "ROBOT_REAL_MIRROR": "1",
        },
    )
    assert mirror.returncode == 0, mirror.stderr


def test_real_mirror_requires_real_mode_and_authenticated_gateway() -> None:
    simulation = check(extra_env={"ROBOT_REAL_MIRROR": "1"})
    assert simulation.returncode != 0
    assert "only valid in real mode" in simulation.stderr
    invalid = check(extra_env={"ROBOT_REAL_MIRROR": "yes"})
    assert invalid.returncode != 0
    assert "must be 0 or 1" in invalid.stderr
    no_secret = check(
        "--robot-mode", "real", "--real-config", str(EXAMPLE),
        extra_env={"ROBOT_REAL_MIRROR": "1"},
    )
    assert no_secret.returncode != 0
    assert "requires authenticated gateway" in no_secret.stderr


def test_relative_config_is_resolved_from_app_not_caller_cwd(tmp_path: Path) -> None:
    result = check(
        "--robot-mode", "real", "--real-config", "configs/robot-real.example.yaml",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert f"REAL_CONFIG_PATH={EXAMPLE}" in result.stdout


@pytest.mark.parametrize(
    "extra_env",
    [
        {"RUNTIME_MODE": "simulation"},
        {"ROBOT_MODE": "simulation"},
        {"ROBOT_CONTROL_MODE": "enabled"},
        {"REAL_CONFIG_PATH": "/tmp/unsolicited.yaml"},
        {"REAL_CONFIG_SHA256": "0" * 64},
    ],
)
def test_cli_environment_conflicts_fail(extra_env: dict[str, str]) -> None:
    result = check("--robot-mode", "real", "--real-config", str(EXAMPLE), extra_env=extra_env)
    assert result.returncode != 0
    assert "conflicts" in result.stderr or "must not override" in result.stderr


def test_config_hash_is_stable_and_unknown_fields_are_rejected(tmp_path: Path) -> None:
    first = check("--robot-mode", "real", "--real-config", str(EXAMPLE))
    second = check("--robot-mode", "real", "--real-config", str(EXAMPLE))
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    bad = tmp_path / "bad.yaml"
    bad.write_text("schema_version: '1.0'\nallowed_control: observe-only\ntoken: secret\n")
    result = check("--robot-mode", "real", "--real-config", str(bad))
    assert result.returncode != 0
    assert "real config validation failed" in result.stderr

    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text("schema_version: '1.0'\nallowed_control: observe-only\nallowed_control: enabled\n")
    assert check("--robot-mode", "real", "--real-config", str(duplicate)).returncode != 0

    nonfinite = tmp_path / "nonfinite.yaml"
    nonfinite.write_text("schema_version: '1.0'\nlimits:\n  max_speed_mm_s: .nan\n")
    assert check("--robot-mode", "real", "--real-config", str(nonfinite)).returncode != 0


def test_enabled_config_is_rejected_before_step11(tmp_path: Path) -> None:
    selected = tmp_path / "enabled.yaml"
    selected.write_text(EXAMPLE.read_text().replace("allowed_control: observe-only", "allowed_control: enabled"))
    result = check("--robot-mode", "real", "--real-config", str(selected), "--real-control", "enabled")
    assert result.returncode != 0
    assert "real config validation failed" in result.stderr


def test_syntax_of_all_service_scripts() -> None:
    scripts = APP_ROOT / "scripts" / "services"
    result = subprocess.run(
        ["bash", "-n", *(str(scripts / name) for name in (
            "start_all.sh", "start_real_mirror_pilot.sh", "test_real_mirror_sofa.sh",
            "health_check.sh", "status.sh", "logs.sh"
        ))],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_real_web_is_explicitly_observe_only_with_no_simulated_pose_or_video() -> None:
    settings = AgentSettings(
        base_url="http://127.0.0.1:23333/v1",
        api_key="EMPTY",
        model="test",
        timeout=5,
        max_retries=0,
        max_tokens=128,
        temperature=0,
        top_p=0.95,
        max_tool_rounds=1,
        runtime_mode=RuntimeMode.REAL,
        robot_control_mode="observe-only",
        real_config_path=str(EXAMPLE),
        real_config_sha256="0" * 64,
    )
    runtime = WebRuntime(settings)
    try:
        with TestClient(create_app(runtime)) as client:
            health = client.get("/health").json()
            assert health["runtime_mode"] == "real"
            assert health["control_mode"] == "observe-only"
            session = client.post("/api/sessions").json()
            assert session["current_tcp"] is None
            base = f"/api/sessions/{session['session_id']}"
            telemetry = client.get(f"{base}/simulation/telemetry").json()
            assert telemetry["connected"] is False
            assert telemetry["current_tcp"] is None
            assert telemetry["joint_positions_deg"] == []
            assert telemetry["error"]["code"] == "GATEWAY_DISCONNECTED"
            assert client.get(f"{base}/simulation/camera").status_code == 502
            assert client.get(f"{base}/simulation/stream.mjpeg").status_code == 502
            for action in ("confirm", "stop", "estop", "reset-estop"):
                assert client.post(f"{base}/{action}").status_code == 409
    finally:
        runtime.close()
