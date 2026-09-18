from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from robot_runtime.api import create_app, create_provider
from robot_runtime.main import app_from_environment
from robot_runtime.real_config import load_real_config
from robot_runtime.providers import HuayanRealStubProvider, SimulationProvider
from surgical_contracts import RuntimeMode


def test_provider_selection_is_explicit_and_defaults_to_simulation() -> None:
    default = create_provider()
    assert isinstance(default, SimulationProvider)
    assert default.mode == RuntimeMode.SIMULATION
    assert isinstance(create_provider("real"), HuayanRealStubProvider)
    with pytest.raises(ValueError):
        create_provider("not-a-mode")


def test_mismatched_provider_and_simulation_worker_are_rejected() -> None:
    with pytest.raises(ValueError, match="simulation worker"):
        create_provider("real", worker=object())
    with pytest.raises(ValueError, match="does not match"):
        create_app(provider=HuayanRealStubProvider())
    with pytest.raises(ValueError, match="either a provider"):
        create_app(provider=HuayanRealStubProvider(), worker=object(), mode="real")


def test_real_stub_does_not_import_simulation_worker() -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from robot_runtime.api import create_app; "
            "create_app(mode='real'); "
            "assert 'simulation.server.simulation_worker' not in sys.modules; "
            "assert 'simulation.entry_point_env' not in sys.modules",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_real_process_entry_requires_matching_mode_config_and_digest(monkeypatch) -> None:
    example = Path(__file__).resolve().parents[3] / "configs" / "robot-real.example.yaml"
    digest = load_real_config(example).digest()
    monkeypatch.setenv("ROBOT_MODE", "real")
    monkeypatch.setenv("RUNTIME_MODE", "real")
    monkeypatch.setenv("REAL_CONFIG_PATH", str(example))
    monkeypatch.setenv("REAL_CONFIG_SHA256", digest)
    monkeypatch.setenv("ROBOT_CONTROL_MODE", "observe-only")
    with TestClient(app_from_environment()) as client:
        health = client.get("/health").json()
        assert health["control_mode"] == "observe-only"
        assert health["ready_for_motion"] is False

    monkeypatch.setenv("REAL_CONFIG_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="digest"):
        app_from_environment()
    monkeypatch.setenv("REAL_CONFIG_SHA256", digest)
    monkeypatch.setenv("ROBOT_CONTROL_MODE", "enabled")
    with pytest.raises(ValueError, match="observe-only"):
        app_from_environment()
    monkeypatch.setenv("ROBOT_CONTROL_MODE", "observe-only")
    monkeypatch.setenv("RUNTIME_MODE", "simulation")
    with pytest.raises(ValueError, match="disagree"):
        app_from_environment()


def test_real_mirror_is_explicit_and_requires_an_authenticated_gateway(monkeypatch) -> None:
    example = Path(__file__).resolve().parents[3] / "configs" / "robot-real.example.yaml"
    monkeypatch.setenv("ROBOT_REAL_MIRROR", "1")
    with pytest.raises(ValueError, match="simulation mode"):
        app_from_environment()
    monkeypatch.setenv("ROBOT_MODE", "real")
    monkeypatch.setenv("REAL_CONFIG_PATH", str(example))
    monkeypatch.setenv("REAL_CONFIG_SHA256", load_real_config(example).digest())
    monkeypatch.setenv("ROBOT_CONTROL_MODE", "observe-only")
    with pytest.raises(ValueError, match="authenticated gateway"):
        app_from_environment()
    monkeypatch.setenv("ROBOT_REAL_MIRROR", "yes")
    with pytest.raises(ValueError, match="must be 0 or 1"):
        app_from_environment()
