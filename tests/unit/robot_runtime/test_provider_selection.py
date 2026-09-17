from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from robot_runtime.api import create_app, create_provider
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


def test_simulation_images_include_the_runtime_package() -> None:
    project_root = Path(__file__).resolve().parents[3]
    for name in ("Dockerfile", "Dockerfile.offline"):
        dockerfile = project_root / "docker" / "simulation" / name
        assert "COPY robot_runtime /workspace/robot_runtime" in dockerfile.read_text()
