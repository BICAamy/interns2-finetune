"""Single-owner, latest-wins SOFA mirror for authenticated real feedback."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Condition, Event, Lock, Thread
import time
from typing import Any, Protocol

from surgical_contracts import RobotTelemetry, SourceFreshness


class MirrorEnvironment(Protocol):
    controller: Any

    def reset(self) -> None: ...
    def apply_external_joint_state(self, telemetry: RobotTelemetry) -> Any | None: ...
    def refresh_frozen_frame(self) -> Any | None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class MirrorStatus:
    enabled: bool
    worker_alive: bool
    source_sequence: int | None
    gateway_session_id: str | None
    frame_sequence: int
    freshness: SourceFreshness
    calibrated: bool
    warning: str
    reason: str
    error: str | None


def create_sofa_mirror_environment(
    *, stale_ms: int, sign: tuple[int, ...] | None, zero_offset_deg: tuple[float, ...] | None,
) -> MirrorEnvironment:
    """Import SOFA only on the one thread that will own its scene and OpenGL."""
    from simulation.entry_point_env.passive_mirror_env import PassiveRealMirrorEnv

    return PassiveRealMirrorEnv(
        stale_ms=stale_ms, sign=sign, zero_offset_deg=zero_offset_deg
    )


class RealMirrorWorker:
    def __init__(
        self,
        telemetry_source: Callable[[], RobotTelemetry],
        *,
        stale_ms: int,
        sign: tuple[int, ...] | None = None,
        zero_offset_deg: tuple[float, ...] | None = None,
        environment_factory: Callable[[], MirrorEnvironment] | None = None,
        tick_interval_s: float = 0.05,
    ) -> None:
        if tick_interval_s <= 0 or stale_ms <= 0:
            raise ValueError("mirror tick and stale deadline must be positive")
        self._telemetry_source = telemetry_source
        self._environment_factory = environment_factory or (
            lambda: create_sofa_mirror_environment(
                stale_ms=stale_ms, sign=sign, zero_offset_deg=zero_offset_deg
            )
        )
        self._tick_interval_s = tick_interval_s
        self._lock = Lock()
        self._condition = Condition(self._lock)
        self._stop = Event()
        self._ready = Event()
        self._thread: Thread | None = None
        self._error: str | None = None
        self._frame: Any | None = None
        self._frame_sequence = 0
        self._source_sequence: int | None = None
        self._session_id: str | None = None
        self._freshness = SourceFreshness.DISCONNECTED
        self._reason = "no_actual_joint_sample"

    def start(self, *, timeout_s: float = 60.0) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._ready.clear()
            self._error = None
            self._frame = None
            self._frame_sequence = 0
            self._source_sequence = None
            self._session_id = None
            self._freshness = SourceFreshness.DISCONNECTED
            self._reason = "no_actual_joint_sample"
            self._thread = Thread(target=self._run, name="real-sofa-mirror", daemon=True)
            self._thread.start()
        if not self._ready.wait(timeout_s):
            raise RuntimeError("real SOFA mirror did not initialize")
        if self._error is not None:
            raise RuntimeError(self._error)

    def shutdown(self, *, timeout_s: float = 10.0) -> None:
        self._stop.set()
        with self._lock:
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout_s)

    def _publish(self, frame: Any, *, source_sequence: int | None, session_id: str | None) -> None:
        with self._lock:
            self._frame = frame.copy()
            self._frame_sequence += 1
            self._source_sequence = source_sequence
            self._session_id = session_id
            self._condition.notify_all()

    def _run(self) -> None:
        environment: MirrorEnvironment | None = None
        try:
            environment = self._environment_factory()
            environment.reset()
            self._ready.set()
            while not self._stop.is_set():
                telemetry = self._telemetry_source()
                old_freshness = environment.controller.freshness
                frame = environment.apply_external_joint_state(telemetry)
                with self._lock:
                    self._freshness = environment.controller.freshness
                    self._reason = environment.controller.reason
                if frame is not None:
                    snapshot = environment.controller.snapshot
                    assert snapshot is not None
                    self._publish(
                        frame,
                        source_sequence=snapshot.source_sequence,
                        session_id=snapshot.gateway_session_id,
                    )
                elif old_freshness != environment.controller.freshness:
                    frozen = environment.refresh_frozen_frame()
                    if frozen is not None:
                        snapshot = environment.controller.snapshot
                        assert snapshot is not None
                        self._publish(
                            frozen,
                            source_sequence=snapshot.source_sequence,
                            session_id=snapshot.gateway_session_id,
                        )
                self._stop.wait(self._tick_interval_s)
        except Exception as error:
            with self._lock:
                self._error = f"{type(error).__name__}: {error}"
                self._freshness = SourceFreshness.DISCONNECTED
                self._condition.notify_all()
            self._ready.set()
        finally:
            if environment is not None:
                try:
                    environment.close()
                except Exception:
                    pass
            with self._lock:
                self._condition.notify_all()

    def status(self) -> MirrorStatus:
        with self._lock:
            return MirrorStatus(
                enabled=True,
                worker_alive=self._thread is not None and self._thread.is_alive(),
                source_sequence=self._source_sequence,
                gateway_session_id=self._session_id,
                frame_sequence=self._frame_sequence,
                freshness=self._freshness,
                calibrated=False,
                warning="UNCALIBRATED / NOT FOR CONTROL",
                reason=self._reason,
                error=self._error,
            )

    def wait_for_frame(self, after_sequence: int, *, timeout_s: float = 2.0) -> tuple[int, Any | None]:
        deadline = time.monotonic() + timeout_s
        with self._lock:
            while self._frame_sequence <= after_sequence and not self._stop.is_set() and self._error is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return self._frame_sequence, None
                self._condition.wait(remaining)
            return self._frame_sequence, self._frame.copy() if self._frame is not None else None
