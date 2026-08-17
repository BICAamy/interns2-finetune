"""Single-owner worker for all SOFA and OpenGL state."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
import json
import os
from queue import Empty, Queue
from threading import Condition, Event, Lock, Thread
import time
from typing import Any, Protocol

from surgical_contracts import (
    CommandExecutionStatus,
    ErrorCode,
    ErrorResponse,
    MotionState,
    MoveRelativeRequest,
    MoveRelativeResult,
    MoveToEntryRequest,
    MoveToEntryResult,
    ResetSimulationRequest,
    RobotActionResult,
    RobotCommandKind,
    RobotCommandRecord,
    RobotState,
    SimulationEvent,
    SimulationCameraControlRequest,
    SimulationCameraState,
    SimulationHealth,
    SimulationTelemetry,
    ToolStatus,
)

from simulation.entry_point_env import (
    InvalidMotionCommand,
    UnreachableTargetError,
    WorkspaceViolationError,
)

from .command_queue import QueuedCommand, SimulationCommandQueue


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


class SimulationServiceError(RuntimeError):
    error_code = ErrorCode.INTERNAL_ERROR


class CommandConflictError(SimulationServiceError):
    error_code = ErrorCode.COMMAND_CONFLICT


class CommandNotFoundError(SimulationServiceError):
    error_code = ErrorCode.COMMAND_NOT_FOUND


class WorkerUnavailableError(SimulationServiceError):
    error_code = ErrorCode.OPERATION_NOT_ENABLED


class SimulationEnvironment(Protocol):
    config: Any
    controller: Any

    def reset(self, seed: int | None = None, options: dict[str, Any] | None = None) -> Any: ...
    def move_to_entry(self, point: Any, speed_mm_s: float | None = None) -> str: ...
    def move_relative(self, delta_mm: tuple[float, float, float], speed_mm_s: float | None = None) -> str: ...
    def step(self) -> Any: ...
    def get_state(self) -> RobotState: ...
    def stop(self) -> RobotState: ...
    def emergency_stop(self) -> RobotState: ...
    def get_camera_state(self) -> SimulationCameraState: ...
    def control_camera(
        self,
        request: SimulationCameraControlRequest,
    ) -> SimulationCameraState: ...
    def refresh_observation(self) -> Any: ...
    def close(self) -> None: ...


@dataclass
class PendingCameraControl:
    request: SimulationCameraControlRequest
    completed: Event = field(default_factory=Event)
    result: SimulationCameraState | None = None
    error: Exception | None = None


def create_sofa_environment() -> SimulationEnvironment:
    """Import SofaPython3 only inside the dedicated worker thread."""

    from sofa_env.base import RenderMode

    from simulation.entry_point_env.environment import EntryPointReachEnv

    return EntryPointReachEnv(render_mode=RenderMode.HUMAN)


class SimulationWorker:
    """Own one environment and serialize every state-changing operation."""

    def __init__(
        self,
        environment_factory: Callable[[], SimulationEnvironment] = create_sofa_environment,
        *,
        tick_interval_s: float | None = None,
        pause_on_no_clients: bool | None = None,
        event_history_limit: int = 512,
    ) -> None:
        self._environment_factory = environment_factory
        self._configured_tick_interval_s = tick_interval_s
        self._pause_on_no_clients = (
            os.environ.get("SIMULATION_PAUSE_ON_NO_CLIENTS", "0") == "1"
            if pause_on_no_clients is None
            else pause_on_no_clients
        )
        self._queue = SimulationCommandQueue()
        self._camera_queue: Queue[PendingCameraControl] = Queue()
        self._lock = Lock()
        self._event_condition = Condition(self._lock)
        self._frame_condition = Condition(self._lock)
        self._stop_event = Event()
        self._ready_event = Event()
        self._thread: Thread | None = None
        self._environment: SimulationEnvironment | None = None
        self._records: dict[str, RobotCommandRecord] = {}
        self._fingerprints: dict[str, str] = {}
        self._events: deque[SimulationEvent] = deque(maxlen=event_history_limit)
        self._event_sequence = 0
        self._telemetry: SimulationTelemetry | None = None
        self._camera_state: SimulationCameraState | None = None
        self._latest_frame: Any | None = None
        self._frame_sequence = 0
        self._active_command: QueuedCommand | None = None
        self._initialization_error: str | None = None
        self._last_heartbeat_ms: int | None = None
        self._client_count = 0

    def start(self, *, timeout_s: float = 60.0) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._ready_event.clear()
            self._initialization_error = None
            self._thread = Thread(
                target=self._run,
                name="robot-simulation-worker",
                daemon=True,
            )
            self._thread.start()
        if not self._ready_event.wait(timeout_s):
            raise WorkerUnavailableError("simulation worker did not initialize before timeout")
        with self._lock:
            if self._initialization_error is not None:
                raise WorkerUnavailableError(self._initialization_error)

    def shutdown(self, *, timeout_s: float = 10.0) -> None:
        self._stop_event.set()
        with self._lock:
            self._event_condition.notify_all()
            self._frame_condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout_s)

    def _run(self) -> None:
        environment: SimulationEnvironment | None = None
        try:
            environment = self._environment_factory()
            observation = environment.reset(seed=0)
            with self._lock:
                self._environment = environment
                self._camera_state = environment.get_camera_state()
                self._capture_locked(observation)
                self._last_heartbeat_ms = _now_ms()
                self._emit_locked("worker_ready", state=self._telemetry.state)
            self._ready_event.set()

            configured = self._configured_tick_interval_s
            tick_interval = (
                max(0.0, float(configured))
                if configured is not None
                else max(0.001, float(environment.config.time_step_s))
            )
            next_tick = time.monotonic()
            while not self._stop_event.is_set():
                with self._lock:
                    self._last_heartbeat_ms = _now_ms()

                urgent = self._queue.get_urgent_nowait()
                if urgent is not None:
                    self._execute_urgent(environment, urgent)
                    continue

                with self._lock:
                    active = self._active_command
                    paused = self._pause_on_no_clients and self._client_count == 0

                camera_control = self._get_camera_nowait()
                if camera_control is not None:
                    self._execute_camera(
                        environment,
                        camera_control,
                        render_immediately=active is None or paused,
                    )

                if active is None:
                    command = self._queue.get_normal_nowait()
                    if command is not None:
                        self._execute_normal(environment, command)
                        continue
                elif not paused:
                    self._step_active(environment, active)

                next_tick += tick_interval
                delay = next_tick - time.monotonic()
                if delay <= 0.0:
                    next_tick = time.monotonic()
                    delay = 0.001
                self._stop_event.wait(delay)
        except Exception as error:  # pragma: no cover - real SOFA startup path
            with self._lock:
                self._initialization_error = f"{type(error).__name__}: {error}"
                self._emit_locked("worker_failed")
            self._ready_event.set()
        finally:
            if environment is not None:
                try:
                    environment.close()
                except Exception:
                    pass
            with self._lock:
                self._environment = None
                self._event_condition.notify_all()
                self._frame_condition.notify_all()
            self._fail_pending_camera_controls()

    def _get_camera_nowait(self) -> PendingCameraControl | None:
        try:
            return self._camera_queue.get_nowait()
        except Empty:
            return None

    def _execute_camera(
        self,
        environment: SimulationEnvironment,
        pending: PendingCameraControl,
        *,
        render_immediately: bool,
    ) -> None:
        try:
            result = environment.control_camera(pending.request)
            if render_immediately:
                observation = environment.refresh_observation()
                with self._lock:
                    self._capture_locked(observation)
            with self._lock:
                self._camera_state = result
            pending.result = result.model_copy(deep=True)
        except Exception as error:
            pending.error = error
        finally:
            pending.completed.set()

    def _fail_pending_camera_controls(self) -> None:
        while True:
            pending = self._get_camera_nowait()
            if pending is None:
                return
            pending.error = WorkerUnavailableError("simulation worker stopped")
            pending.completed.set()

    def _execute_normal(
        self,
        environment: SimulationEnvironment,
        command: QueuedCommand,
    ) -> None:
        self._mark_running(command)
        try:
            if command.kind == RobotCommandKind.RESET:
                request: ResetSimulationRequest = command.request
                observation = environment.reset(seed=request.seed)
                with self._lock:
                    self._capture_locked(observation)
                result = RobotActionResult(
                    command_id=command.command_id,
                    operation=command.kind,
                    status=ToolStatus.SUCCESS,
                    state=self.get_state(),
                    message="Simulation reset completed",
                )
                self._complete(command, result)
                return

            with self._lock:
                self._active_command = command
            if command.kind == RobotCommandKind.MOVE_TO_ENTRY:
                request = command.request
                if request.tcp != environment.config.tcp_name:
                    raise InvalidMotionCommand(
                        f"unsupported TCP {request.tcp!r}; expected {environment.config.tcp_name!r}"
                    )
                if request.orientation_policy != "configured_safe_orientation":
                    raise InvalidMotionCommand(
                        "only configured_safe_orientation is supported"
                    )
                environment.move_to_entry(request.entry_point, request.speed_mm_s)
            elif command.kind == RobotCommandKind.MOVE_RELATIVE:
                request = command.request
                if request.frame != environment.config.coordinate_frame:
                    raise InvalidMotionCommand(
                        f"expected coordinate frame {environment.config.coordinate_frame.value}, "
                        f"received {request.frame.value}"
                    )
                environment.move_relative(request.translation_mm, request.speed_mm_s)
            else:
                raise InvalidMotionCommand(f"unsupported normal command: {command.kind}")

            with self._lock:
                self._capture_locked(environment.controller.snapshot())
            if environment.get_state().motion_state != MotionState.MOVING:
                self._finish_active(environment, command, environment.controller.snapshot())
        except Exception as error:
            with self._lock:
                if self._active_command == command:
                    self._active_command = None
            self._fail(command, error)

    def _execute_urgent(
        self,
        environment: SimulationEnvironment,
        command: QueuedCommand,
    ) -> None:
        self._mark_running(command)
        with self._lock:
            active = self._active_command
            self._active_command = None
        if active is not None:
            self._cancel(active, f"Preempted by {command.kind.value}")
        for pending in self._queue.drain_normal():
            self._cancel(pending, f"Cancelled before execution by {command.kind.value}")

        try:
            if command.kind == RobotCommandKind.ESTOP:
                state = environment.emergency_stop()
                message = "Simulation emergency stop latched"
            else:
                state = environment.stop()
                message = "Simulation motion stopped"
            with self._lock:
                self._capture_locked(environment.controller.snapshot())
            result = RobotActionResult(
                command_id=command.command_id,
                operation=command.kind,
                status=ToolStatus.SUCCESS,
                state=self._external_state(state),
                message=message,
            )
            self._complete(command, result)
        except Exception as error:
            self._fail(command, error)

    def _step_active(
        self,
        environment: SimulationEnvironment,
        command: QueuedCommand,
    ) -> None:
        try:
            step = environment.step()
            with self._lock:
                self._capture_locked(step)
            if step.state.motion_state != MotionState.MOVING:
                self._finish_active(environment, command, step)
        except Exception as error:
            with self._lock:
                self._active_command = None
            self._fail(command, error)

    def _finish_active(
        self,
        environment: SimulationEnvironment,
        command: QueuedCommand,
        step: Any,
    ) -> None:
        with self._lock:
            self._active_command = None
        state = self._external_state(environment.get_state())
        if command.kind == RobotCommandKind.MOVE_TO_ENTRY:
            request: MoveToEntryRequest = command.request
            error_mm = state.tcp_position.distance_to(request.entry_point)
            if state.motion_state != MotionState.AT_ENTRY:
                self._fail(command, RuntimeError("entry-point motion did not reach its target"))
                return
            result: Any = MoveToEntryResult(
                command_id=command.command_id,
                status=ToolStatus.SUCCESS,
                reached=True,
                final_tcp_position=state.tcp_position,
                position_error_mm=error_mm,
                trajectory_id=f"simulation-{command.command_id}",
                message="Simulation needle TCP reached the entry point",
            )
        else:
            if state.motion_state not in {MotionState.IDLE, MotionState.AT_ENTRY}:
                self._fail(command, RuntimeError("relative motion did not complete"))
                return
            result = MoveRelativeResult(
                command_id=command.command_id,
                status=ToolStatus.SUCCESS,
                completed=True,
                final_tcp_position=state.tcp_position,
                trajectory_id=f"simulation-{command.command_id}",
                message="Simulation relative movement completed",
            )
        self._complete(command, result)

    def _mark_running(self, command: QueuedCommand) -> None:
        with self._lock:
            record = self._records[command.command_id].model_copy(
                update={
                    "status": CommandExecutionStatus.RUNNING,
                    "updated_at_ms": _now_ms(),
                }
            )
            self._records[command.command_id] = record
            self._emit_locked("command_started", command=record)

    def _complete(self, command: QueuedCommand, result: Any) -> None:
        payload = result.model_dump(mode="json")
        with self._lock:
            record = self._records[command.command_id].model_copy(
                update={
                    "status": CommandExecutionStatus.SUCCEEDED,
                    "updated_at_ms": _now_ms(),
                    "result": payload,
                }
            )
            self._records[command.command_id] = record
            self._emit_locked(
                "command_completed",
                command=record,
                state=self._telemetry.state if self._telemetry else None,
            )

    def _cancel(self, command: QueuedCommand, message: str) -> None:
        error = ErrorResponse(
            code=ErrorCode.COMMAND_CONFLICT,
            command_id=command.command_id,
            message=message,
        )
        with self._lock:
            record = self._records[command.command_id].model_copy(
                update={
                    "status": CommandExecutionStatus.CANCELLED,
                    "updated_at_ms": _now_ms(),
                    "error": error,
                }
            )
            self._records[command.command_id] = record
            self._emit_locked("command_cancelled", command=record)

    def _fail(self, command: QueuedCommand, error: Exception) -> None:
        code, status = self._classify_error(error)
        response = ErrorResponse(
            code=code,
            command_id=command.command_id,
            message=str(error) or type(error).__name__,
        )
        with self._lock:
            record = self._records[command.command_id].model_copy(
                update={
                    "status": status,
                    "updated_at_ms": _now_ms(),
                    "error": response,
                }
            )
            self._records[command.command_id] = record
            self._emit_locked("command_failed", command=record)

    @staticmethod
    def _classify_error(error: Exception) -> tuple[ErrorCode, CommandExecutionStatus]:
        if isinstance(error, WorkspaceViolationError):
            return ErrorCode.OUT_OF_WORKSPACE, CommandExecutionStatus.REJECTED
        if isinstance(error, UnreachableTargetError):
            return ErrorCode.IK_FAILED, CommandExecutionStatus.REJECTED
        if isinstance(error, InvalidMotionCommand):
            if "emergency stop" in str(error).lower():
                return ErrorCode.ESTOP_ACTIVE, CommandExecutionStatus.REJECTED
            return ErrorCode.INVALID_COMMAND_SCHEMA, CommandExecutionStatus.REJECTED
        return ErrorCode.INTERNAL_ERROR, CommandExecutionStatus.FAILED

    def submit(
        self,
        kind: RobotCommandKind,
        request: Any,
    ) -> tuple[RobotCommandRecord, bool]:
        payload = request.model_dump(mode="json")
        fingerprint = json.dumps(
            {"kind": kind.value, "request": payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        command_id = request.command_id
        with self._lock:
            if self._initialization_error is not None:
                raise WorkerUnavailableError(self._initialization_error)
            existing = self._records.get(command_id)
            if existing is not None:
                if self._fingerprints[command_id] != fingerprint:
                    raise CommandConflictError(
                        f"command_id {command_id!r} was already used with different arguments"
                    )
                return existing.model_copy(deep=True), False
            if self._thread is None or not self._thread.is_alive() or not self._ready_event.is_set():
                raise WorkerUnavailableError("simulation worker is not ready")
            timestamp = _now_ms()
            record = RobotCommandRecord(
                command_id=command_id,
                kind=kind,
                status=CommandExecutionStatus.QUEUED,
                submitted_at_ms=timestamp,
                updated_at_ms=timestamp,
                request=payload,
            )
            self._records[command_id] = record
            self._fingerprints[command_id] = fingerprint
            self._emit_locked("command_queued", command=record)
            # Publish the queue item before releasing the submission lock so a
            # concurrently submitted stop/estop cannot overtake a command that
            # exists in the record store but is not visible to the worker yet.
            self._queue.put(
                QueuedCommand(
                    command_id=command_id,
                    kind=kind,
                    request=request,
                    fingerprint=fingerprint,
                )
            )
        return record.model_copy(deep=True), True

    def get_command(self, command_id: str) -> RobotCommandRecord:
        with self._lock:
            record = self._records.get(command_id)
            if record is None:
                raise CommandNotFoundError(f"unknown command_id: {command_id}")
            return record.model_copy(deep=True)

    def wait_for_command(
        self,
        command_id: str,
        *,
        timeout_s: float = 5.0,
    ) -> RobotCommandRecord:
        deadline = time.monotonic() + timeout_s
        terminal = {
            CommandExecutionStatus.SUCCEEDED,
            CommandExecutionStatus.FAILED,
            CommandExecutionStatus.REJECTED,
            CommandExecutionStatus.CANCELLED,
        }
        with self._lock:
            while True:
                record = self._records.get(command_id)
                if record is None:
                    raise CommandNotFoundError(f"unknown command_id: {command_id}")
                if record.status in terminal:
                    return record.model_copy(deep=True)
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return record.model_copy(deep=True)
                self._event_condition.wait(remaining)

    def get_state(self) -> RobotState:
        with self._lock:
            if self._telemetry is None:
                raise WorkerUnavailableError("simulation telemetry is not ready")
            return self._telemetry.state.model_copy(deep=True)

    def get_telemetry(self) -> SimulationTelemetry:
        with self._lock:
            if self._telemetry is None:
                raise WorkerUnavailableError("simulation telemetry is not ready")
            return self._telemetry.model_copy(deep=True)

    def get_camera_state(self) -> SimulationCameraState:
        with self._lock:
            if self._camera_state is None:
                raise WorkerUnavailableError("simulation camera is not ready")
            return self._camera_state.model_copy(deep=True)

    def control_camera(
        self,
        request: SimulationCameraControlRequest,
        *,
        timeout_s: float = 3.0,
    ) -> SimulationCameraState:
        with self._lock:
            if self._initialization_error is not None:
                raise WorkerUnavailableError(self._initialization_error)
            if self._thread is None or not self._thread.is_alive() or not self._ready_event.is_set():
                raise WorkerUnavailableError("simulation worker is not ready")
        pending = PendingCameraControl(request=request)
        self._camera_queue.put(pending)
        if not pending.completed.wait(timeout_s):
            raise WorkerUnavailableError("simulation camera update timed out")
        if pending.error is not None:
            raise pending.error
        if pending.result is None:  # pragma: no cover - defensive boundary
            raise WorkerUnavailableError("simulation camera returned no state")
        return pending.result.model_copy(deep=True)

    def health(self) -> SimulationHealth:
        with self._lock:
            alive = self._thread is not None and self._thread.is_alive()
            initialized = self._telemetry is not None
            ready = alive and initialized and self._initialization_error is None
            if self._initialization_error is not None or (self._thread is not None and not alive):
                status = "unhealthy"
            elif ready:
                status = "healthy"
            else:
                status = "starting"
            return SimulationHealth(
                status=status,
                worker_alive=alive,
                initialized=initialized,
                ready=ready,
                queue_depth=self._queue.depth + self._camera_queue.qsize(),
                active_command_id=(
                    self._active_command.command_id
                    if self._active_command is not None
                    else None
                ),
                last_heartbeat_ms=self._last_heartbeat_ms,
                error=self._initialization_error,
            )

    def register_client(self) -> None:
        with self._lock:
            self._client_count += 1

    def unregister_client(self) -> None:
        with self._lock:
            self._client_count = max(0, self._client_count - 1)

    def wait_for_events(
        self,
        after_sequence: int,
        *,
        timeout_s: float = 5.0,
    ) -> list[SimulationEvent]:
        deadline = time.monotonic() + timeout_s
        with self._lock:
            while True:
                events = [
                    event.model_copy(deep=True)
                    for event in self._events
                    if event.sequence > after_sequence
                ]
                if events or self._stop_event.is_set():
                    return events
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return []
                self._event_condition.wait(remaining)

    def wait_for_frame(
        self,
        after_sequence: int,
        *,
        timeout_s: float = 2.0,
    ) -> tuple[int, Any | None]:
        deadline = time.monotonic() + timeout_s
        with self._lock:
            while self._frame_sequence <= after_sequence and not self._stop_event.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return self._frame_sequence, None
                self._frame_condition.wait(remaining)
            frame = self._latest_frame.copy() if self._latest_frame is not None else None
            return self._frame_sequence, frame

    def _capture_locked(self, snapshot: Any) -> None:
        state = self._external_state(snapshot.state)
        joints = tuple(float(value) for value in snapshot.joint_positions_deg)
        trajectory = [
            tuple(float(component) for component in point)
            for point in self._environment.controller.trajectory_mm
        ]
        frame = getattr(snapshot, "rgb", None)
        if frame is not None:
            self._latest_frame = frame.copy()
            self._frame_sequence += 1
            self._frame_condition.notify_all()
        sequence = 0 if self._telemetry is None else self._telemetry.sequence + 1
        self._telemetry = SimulationTelemetry(
            state=state,
            sequence=sequence,
            joint_positions_deg=joints,
            trajectory_mm=trajectory,
            frame_sequence=self._frame_sequence,
            updated_at_ms=_now_ms(),
        )
        self._emit_locked("state_updated", state=state)

    def _external_state(self, state: RobotState) -> RobotState:
        active_id = self._active_command.command_id if self._active_command else None
        if state.motion_state != MotionState.MOVING:
            active_id = None
        return state.model_copy(update={"active_command_id": active_id}, deep=True)

    def _emit_locked(
        self,
        event_type: str,
        *,
        command: RobotCommandRecord | None = None,
        state: RobotState | None = None,
    ) -> None:
        self._event_sequence += 1
        event = SimulationEvent(
            sequence=self._event_sequence,
            timestamp_ms=_now_ms(),
            event_type=event_type,
            command=command,
            state=state,
        )
        self._events.append(event)
        self._event_condition.notify_all()
