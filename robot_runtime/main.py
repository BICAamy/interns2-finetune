"""Executable entry point for the provider-neutral robot service."""

from __future__ import annotations

import os

from .api import create_app
from .gateway_session import GatewaySessionManager
from .providers.huayan_real import HuayanRealStubProvider
from .real_config import load_real_config
from surgical_contracts import load_gateway_secret


def app_from_environment():
    mode = os.environ.get("ROBOT_MODE", "simulation")
    if mode not in {"simulation", "real"}:
        raise ValueError(f"unsupported ROBOT_MODE: {mode!r}")
    other_mode = os.environ.get("RUNTIME_MODE")
    if other_mode is not None and other_mode != mode:
        raise ValueError("ROBOT_MODE and RUNTIME_MODE disagree")
    config_path = os.environ.get("REAL_CONFIG_PATH")
    secret_path = os.environ.get("GATEWAY_AUTH_SECRET_FILE")
    if mode == "simulation":
        if config_path:
            raise ValueError("simulation mode cannot use REAL_CONFIG_PATH")
        if secret_path:
            raise ValueError("simulation mode cannot use GATEWAY_AUTH_SECRET_FILE")
    else:
        if not config_path:
            raise ValueError("real mode requires REAL_CONFIG_PATH")
        config = load_real_config(config_path)
        expected_digest = os.environ.get("REAL_CONFIG_SHA256")
        if not expected_digest or expected_digest != config.digest():
            raise ValueError("real config digest does not match startup preflight")
        if os.environ.get("ROBOT_CONTROL_MODE") != "observe-only":
            raise ValueError("real runtime must remain observe-only")
        if secret_path:
            expected_gateway_id = os.environ.get("GATEWAY_EXPECTED_ID")
            if (
                not expected_gateway_id
                or not config.controller.device_sn
                or not config.controller.model
                or not config.controller.package_versions
                or not config.deadlines.state_stale_ms
            ):
                raise ValueError("authenticated gateway requires confirmed identity and stale limit")
            sessions = GatewaySessionManager(
                secret=load_gateway_secret(secret_path),
                gateway_id=expected_gateway_id,
                device_sn=config.controller.device_sn,
                robot_model=config.controller.model,
                package_versions=tuple(config.controller.package_versions),
                config_sha256=config.digest(),
                stale_ms=config.deadlines.state_stale_ms,
            )
            return create_app(provider=HuayanRealStubProvider(sessions), mode="real")
    return create_app(mode=mode)


def main() -> None:
    import uvicorn

    app = app_from_environment()
    uvicorn.run(
        app,
        host=os.environ.get(
            "ROBOT_SIMULATION_HOST",
            "127.0.0.1" if os.environ.get("ROBOT_MODE") == "real" else "0.0.0.0",
        ),
        port=int(os.environ.get("ROBOT_SIMULATION_PORT", "8001")),
        log_level=os.environ.get("ROBOT_SIMULATION_LOG_LEVEL", "info"),
        workers=1,
        ws_max_size=64 * 1024,
    )


if __name__ == "__main__":
    main()
