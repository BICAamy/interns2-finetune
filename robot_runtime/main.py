"""Executable entry point for the provider-neutral robot service."""

from __future__ import annotations

import os

from .api import create_app
from .real_config import load_real_config


def app_from_environment():
    mode = os.environ.get("ROBOT_MODE", "simulation")
    if mode not in {"simulation", "real"}:
        raise ValueError(f"unsupported ROBOT_MODE: {mode!r}")
    other_mode = os.environ.get("RUNTIME_MODE")
    if other_mode is not None and other_mode != mode:
        raise ValueError("ROBOT_MODE and RUNTIME_MODE disagree")
    config_path = os.environ.get("REAL_CONFIG_PATH")
    if mode == "simulation":
        if config_path:
            raise ValueError("simulation mode cannot use REAL_CONFIG_PATH")
    else:
        if not config_path:
            raise ValueError("real mode requires REAL_CONFIG_PATH")
        config = load_real_config(config_path)
        expected_digest = os.environ.get("REAL_CONFIG_SHA256")
        if not expected_digest or expected_digest != config.digest():
            raise ValueError("real config digest does not match startup preflight")
        if os.environ.get("ROBOT_CONTROL_MODE") != "observe-only":
            raise ValueError("Step 3 real runtime must remain observe-only")
    return create_app(mode=mode)


def main() -> None:
    import uvicorn

    uvicorn.run(
        app_from_environment(),
        host=os.environ.get("ROBOT_SIMULATION_HOST", "0.0.0.0"),
        port=int(os.environ.get("ROBOT_SIMULATION_PORT", "8001")),
        log_level=os.environ.get("ROBOT_SIMULATION_LOG_LEVEL", "info"),
        workers=1,
    )


if __name__ == "__main__":
    main()
