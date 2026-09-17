"""Thin adapter around the existing single-owner SimulationWorker."""

from __future__ import annotations

from typing import Any

from surgical_contracts import (
    RobotCommandKind,
    RobotCommandRecord,
    RuntimeMode,
    SimulationCameraControlRequest,
    SimulationCameraState,
    SimulationEvent,
    SimulationHealth,
    SimulationTelemetry,
)

from simulation.server.simulation_worker import SimulationWorker

from ..provider import ProviderCapabilities


class SimulationProvider:
    mode = RuntimeMode.SIMULATION
    capabilities = ProviderCapabilities(camera=True, events=True, mjpeg=True)

    def __init__(self, worker: SimulationWorker | None = None) -> None:
        self.worker = worker if worker is not None else SimulationWorker()

    def start(self) -> None:
        self.worker.start()

    def shutdown(self) -> None:
        self.worker.shutdown()

    def health(self) -> SimulationHealth:
        return self.worker.health()

    def get_telemetry(self) -> SimulationTelemetry:
        return self.worker.get_telemetry()

    def get_camera_state(self) -> SimulationCameraState:
        return self.worker.get_camera_state()

    def control_camera(
        self, request: SimulationCameraControlRequest
    ) -> SimulationCameraState:
        return self.worker.control_camera(request)

    def submit(
        self, kind: RobotCommandKind, request: Any
    ) -> tuple[RobotCommandRecord, bool]:
        return self.worker.submit(kind, request)

    def get_command(self, command_id: str) -> RobotCommandRecord:
        return self.worker.get_command(command_id)

    def register_client(self) -> None:
        self.worker.register_client()

    def unregister_client(self) -> None:
        self.worker.unregister_client()

    def wait_for_events(
        self, after_sequence: int, *, timeout_s: float = 5.0
    ) -> list[SimulationEvent]:
        return self.worker.wait_for_events(after_sequence, timeout_s=timeout_s)

    def wait_for_frame(
        self, after_sequence: int, *, timeout_s: float = 2.0
    ) -> tuple[int, Any | None]:
        return self.worker.wait_for_frame(after_sequence, timeout_s=timeout_s)
