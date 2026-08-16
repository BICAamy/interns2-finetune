"""Executable entry point for the single-worker simulation service."""

from __future__ import annotations

import os

from .api import create_app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("ROBOT_SIMULATION_HOST", "0.0.0.0"),
        port=int(os.environ.get("ROBOT_SIMULATION_PORT", "8001")),
        log_level=os.environ.get("ROBOT_SIMULATION_LOG_LEVEL", "info"),
        workers=1,
    )


if __name__ == "__main__":
    main()
