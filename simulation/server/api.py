"""Compatibility entry point for the provider-neutral port-8001 API."""

from __future__ import annotations

from fastapi import FastAPI

from robot_runtime.api import create_app as create_runtime_app

from .simulation_worker import SimulationWorker


def create_app(
    worker: SimulationWorker | None = None,
    *,
    manage_worker: bool = True,
) -> FastAPI:
    """Keep existing simulation callers and the server startup unchanged."""

    return create_runtime_app(worker=worker, manage_provider=manage_worker)
