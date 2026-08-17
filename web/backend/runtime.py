"""Application runtime for preview/confirm web execution."""

from __future__ import annotations

import asyncio
import base64
import binascii
from pathlib import Path
import tempfile
from threading import RLock
import time
from typing import Any, Protocol
from uuid import uuid4

from surgical_contracts import CommandIntent, ParsedCommand, Point3D, ToolEvent

from agent.config import AgentSettings
from agent.core import (
    AgentTaskState,
    OrchestrationPolicy,
    SurgicalTaskOrchestrator,
    build_runtime_events,
)
from agent.openai_compat_http import OpenAICompatibleHTTPClient
from agent.parsing import CommandParsingError
from agent.runtime import InternS2Agent, ParsedCommandResponse
from agent.tools.puncture_planner import PlannerAdapterHTTPClient
from agent.tools.robot import RobotSimulationHTTPController

from .models import (
    HealthResponse,
    SessionSnapshot,
    SessionStatus,
    SimulationTelemetryView,
    TextCommandRequest,
)
from .simulation_proxy import (
    MJPEGStream,
    RobotSimulationObservabilityHTTPClient,
    SimulationObserver,
)
from .sessions import SessionConflict, SessionStore


class CommandParser(Protocol):
    def parse_command(
        self,
        prompt: str,
        image_path: str | Path | None = None,
    ) -> ParsedCommandResponse: ...


_BUSY_STATUSES = {
    SessionStatus.PARSING,
    SessionStatus.AWAITING_CONFIRMATION,
    SessionStatus.EXECUTING,
    SessionStatus.MOVING_TO_ENTRY,
    SessionStatus.VERIFYING_ENTRY,
    SessionStatus.MOVING_RELATIVE,
    SessionStatus.PLANNING,
    SessionStatus.STOPPING,
}

_IMAGE_SUFFIXES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

_CURRENT_TOOLS = {
    SessionStatus.MOVING_TO_ENTRY: "robot.move_to_entry",
    SessionStatus.VERIFYING_ENTRY: "robot.get_state",
    SessionStatus.MOVING_RELATIVE: "robot.move_relative",
    SessionStatus.PLANNING: "planner.plan_puncture",
    SessionStatus.STOPPING: "robot.stop",
    SessionStatus.ESTOP: "robot.emergency_stop",
}

_TELEMETRY_TRAJECTORY_LIMIT = 160


class WebRuntime:
    def __init__(
        self,
        settings: AgentSettings,
        *,
        parser: CommandParser | None = None,
        robot: Any | None = None,
        planner: Any | None = None,
        store: SessionStore | None = None,
        simulation_observer: SimulationObserver | None = None,
    ) -> None:
        settings.validate()
        if settings.runtime_mode.value != "simulation":
            raise ValueError("agent-web currently requires RUNTIME_MODE=simulation")
        self.settings = settings
        self.store = store or SessionStore()
        self._model_http: OpenAICompatibleHTTPClient | None = None
        self._owns_robot = robot is None
        self._owns_planner = planner is None
        self._owns_simulation_observer = simulation_observer is None
        if parser is None:
            self._model_http = OpenAICompatibleHTTPClient(settings)
            parser = InternS2Agent(settings, client=self._model_http)
        self.parser = parser
        self.robot = robot or RobotSimulationHTTPController(
            settings.robot_simulation_base_url,
            http_timeout_s=settings.robot_simulation_http_timeout,
            command_timeout_s=settings.robot_simulation_command_timeout,
            poll_interval_s=settings.robot_simulation_poll_interval,
        )
        self.planner = planner or PlannerAdapterHTTPClient(
            settings.planner_adapter_base_url,
            timeout_s=settings.planner_adapter_timeout,
        )
        self.simulation_observer = (
            simulation_observer
            or RobotSimulationObservabilityHTTPClient(
                settings.robot_simulation_base_url,
                timeout_s=min(settings.robot_simulation_http_timeout, 2.0),
            )
        )
        self.orchestrator = SurgicalTaskOrchestrator(
            self.robot,
            self.planner,
            policy=OrchestrationPolicy(
                entry_tolerance_mm=settings.entry_tolerance_mm,
                max_relative_translation_mm=settings.max_relative_translation_mm,
                move_speed_mm_s=settings.robot_move_speed_mm_s,
                max_speed_mm_s=settings.max_robot_speed_mm_s,
                expected_runtime_mode=settings.runtime_mode,
            ),
            event_sink=self._on_tool_event,
        )
        self._tasks: set[asyncio.Task[Any]] = set()
        self._motion_origins: dict[str, Point3D] = {}
        self._fps_samples: dict[str, tuple[int, float, float]] = {}
        self._telemetry_lock = RLock()
        self.telemetry_interval_s = 0.1

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "WebRuntime":
        return cls(AgentSettings.from_env(env_file))

    def close(self) -> None:
        if self._model_http is not None:
            self._model_http.close()
        if self._owns_robot and hasattr(self.robot, "close"):
            self.robot.close()
        if self._owns_planner and hasattr(self.planner, "close"):
            self.planner.close()
        if self._owns_simulation_observer:
            self.simulation_observer.close()

    async def create_session(self) -> SessionSnapshot:
        snapshot = self.store.create()
        try:
            state = await asyncio.to_thread(self.robot.get_state)
        except Exception:
            # A downstream outage must not prevent the doctor from opening the
            # console. Preflight will still reject an execution later.
            return snapshot

        return self.store.mutate(
            snapshot.session_id,
            lambda record: setattr(
                record,
                "current_tcp",
                state.tcp_position.model_dump(mode="json"),
            ),
        )

    def get_session(self, session_id: str) -> SessionSnapshot:
        return self.store.snapshot(session_id)

    def get_simulation_telemetry(self, session_id: str) -> SimulationTelemetryView:
        session = self.store.snapshot(session_id)
        telemetry = self.simulation_observer.get_telemetry()
        command = session.normalized_command or {}
        entry_point = _point_from_payload(command.get("entry_point"))
        target_point = _point_from_payload(command.get("target_point"))
        current_tcp = telemetry.state.tcp_position
        position_error = (
            current_tcp.distance_to(entry_point)
            if entry_point is not None and current_tcp.frame == entry_point.frame
            else None
        )
        motion_target = entry_point
        origin = self._motion_origins.get(session_id)
        relative = command.get("relative_motion")
        if motion_target is None and origin is not None and isinstance(relative, dict):
            motion_target = _relative_target(origin, relative)
        progress = _motion_progress(origin, motion_target, current_tcp)
        trajectory = [tuple(float(value) for value in point) for point in telemetry.trajectory_mm]
        return SimulationTelemetryView(
            connected=True,
            sequence=telemetry.sequence,
            received_at_ms=_now_ms(),
            source_updated_at_ms=telemetry.updated_at_ms,
            state_machine_state=session.status.value,
            current_tool=_CURRENT_TOOLS.get(session.status),
            motion_state=telemetry.state.motion_state.value,
            estop=telemetry.state.estop,
            active_command_id=telemetry.state.active_command_id,
            current_tcp=current_tcp,
            entry_point=entry_point,
            target_point=target_point,
            position_error_mm=(round(position_error, 4) if position_error is not None else None),
            motion_progress_percent=progress,
            joint_positions_deg=[float(value) for value in telemetry.joint_positions_deg],
            trajectory_mm=_downsample_trajectory(
                trajectory,
                _TELEMETRY_TRAJECTORY_LIMIT,
            ),
            trajectory_total_points=len(trajectory),
            frame_sequence=telemetry.frame_sequence,
            simulation_fps=self._update_fps(
                session_id,
                telemetry.frame_sequence,
            ),
            error=session.error,
        )

    def simulation_telemetry_error(
        self,
        session_id: str,
        error: Exception,
    ) -> SimulationTelemetryView:
        session = self.store.snapshot(session_id)
        command = session.normalized_command or {}
        return SimulationTelemetryView(
            connected=False,
            sequence=0,
            received_at_ms=_now_ms(),
            state_machine_state=session.status.value,
            current_tool=_CURRENT_TOOLS.get(session.status),
            entry_point=_point_from_payload(command.get("entry_point")),
            target_point=_point_from_payload(command.get("target_point")),
            error={
                "code": "SIMULATION_TELEMETRY_UNAVAILABLE",
                "message": str(error) or type(error).__name__,
                "details": {},
            },
        )

    async def open_simulation_video(self, session_id: str) -> MJPEGStream:
        self.store.snapshot(session_id)
        return await self.simulation_observer.open_mjpeg()

    def health(self) -> HealthResponse:
        return HealthResponse(
            runtime_mode=self.settings.runtime_mode.value,
            puncture_execution_enabled=False,
            sessions=self.store.count,
            downstream={
                "interns2": self.settings.base_url,
                "robot_simulation": self.settings.robot_simulation_base_url,
                "planner_adapter": self.settings.planner_adapter_base_url,
            },
        )

    async def submit_text(
        self,
        session_id: str,
        request: TextCommandRequest,
    ) -> SessionSnapshot:
        parse_started_ms = time.time_ns() // 1_000_000

        def begin(record) -> None:
            if record.status in _BUSY_STATUSES:
                raise SessionConflict("session already has a pending or active command")
            record.status = SessionStatus.PARSING
            record.prompt = request.prompt.strip()
            record.image_name = request.image_name
            record.pending_command = None
            record.active_command_id = None
            record.raw_model_output = None
            record.normalized_command = None
            record.execution_events = []
            record.live_tool_events = []
            record.orchestration = None
            record.message = "正在解析指令"
            record.error = None
            record.parse_started_ms = parse_started_ms
            record.parse_finished_ms = None

        self.store.mutate(session_id, begin)
        image_path: Path | None = None
        try:
            if request.image_data_url:
                image_path = self._write_temporary_image(request.image_data_url)
            parsed = await asyncio.to_thread(
                self.parser.parse_command,
                request.prompt,
                image_path,
            )
        except CommandParsingError as error:
            return self._record_parse_error(session_id, error.as_dict())
        except (ValueError, OSError) as error:
            return self._record_parse_error(
                session_id,
                {
                    "code": "INVALID_WEB_INPUT",
                    "message": str(error),
                    "details": {},
                },
            )
        except Exception as error:  # pragma: no cover - defensive service boundary
            return self._record_parse_error(
                session_id,
                {
                    "code": "INTERNAL_ERROR",
                    "message": f"解析失败：{type(error).__name__}",
                    "details": {},
                },
            )
        finally:
            if image_path is not None:
                image_path.unlink(missing_ok=True)

        parse_finished_ms = time.time_ns() // 1_000_000

        def finish(record) -> None:
            payload = parsed.as_dict()
            record.raw_model_output = payload.get("raw_model_output")
            record.normalized_command = parsed.command.model_dump(mode="json")
            record.parse_finished_ms = parse_finished_ms
            record.execution_events = [
                event.as_dict()
                for event in build_runtime_events(
                    parse_started_ms=parse_started_ms,
                    parse_finished_ms=parse_finished_ms,
                    orchestration=None,
                )
            ]
            if parsed.command.intent == CommandIntent.CLARIFY:
                record.status = SessionStatus.CLARIFICATION_REQUIRED
                record.pending_command = None
                record.message = parsed.clarification or "需要补充信息"
            else:
                # Web execution always requires an explicit human confirmation,
                # even when the parser considers a relative command unambiguous.
                record.status = SessionStatus.AWAITING_CONFIRMATION
                record.pending_command = parsed.command
                record.message = "请核对结构化任务，确认后才会调用机械臂"

        return self.store.mutate(session_id, finish)

    async def confirm(self, session_id: str) -> SessionSnapshot:
        selected: dict[str, Any] = {}

        def begin(record) -> None:
            if record.pending_command is None:
                raise SessionConflict("session has no command awaiting confirmation")
            command = record.pending_command
            selected["command"] = command
            selected["parse_started_ms"] = record.parse_started_ms
            selected["parse_finished_ms"] = record.parse_finished_ms
            selected["motion_origin"] = record.current_tcp
            record.pending_command = None
            record.active_command_id = command.command_id
            record.status = SessionStatus.EXECUTING
            record.live_tool_events = []
            record.message = "任务已确认，准备调用机械臂"
            record.error = None

        snapshot = self.store.mutate(session_id, begin)
        command: ParsedCommand = selected["command"]
        origin = _point_from_payload(selected.get("motion_origin"))
        if origin is not None:
            self._motion_origins[session_id] = origin
        self.store.bind_command(session_id, command.command_id)
        task = asyncio.create_task(
            self._execute_confirmed(
                session_id,
                command,
                int(selected["parse_started_ms"] or _now_ms()),
                int(selected["parse_finished_ms"] or _now_ms()),
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return snapshot

    async def cancel(self, session_id: str) -> SessionSnapshot:
        def operation(record) -> None:
            if record.pending_command is None:
                raise SessionConflict("only a command awaiting confirmation can be cancelled")
            record.pending_command = None
            record.status = SessionStatus.CANCELLED
            record.message = "待确认任务已取消；未调用任何工具"

        return self.store.mutate(session_id, operation)

    async def stop(self, session_id: str, *, emergency: bool) -> SessionSnapshot:
        command = ParsedCommand(
            command_id=f"web-{'estop' if emergency else 'stop'}-{uuid4().hex}",
            intent=(
                CommandIntent.EMERGENCY_STOP if emergency else CommandIntent.STOP
            ),
        )

        def begin(record) -> None:
            record.pending_command = None
            record.active_command_id = command.command_id
            record.status = SessionStatus.ESTOP if emergency else SessionStatus.STOPPING
            record.message = "正在执行急停" if emergency else "正在停止机械臂"

        self.store.mutate(session_id, begin)
        self.store.bind_command(session_id, command.command_id)
        try:
            result = await asyncio.to_thread(self.orchestrator.execute, command)
        except Exception as error:  # pragma: no cover - defensive service boundary
            return self.store.mutate(
                session_id,
                lambda record: self._mark_background_failure(record, error),
            )
        finally:
            self.store.unbind_command(command.command_id)

        def finish(record) -> None:
            record.active_command_id = None
            record.orchestration = result.as_dict()
            record.current_tcp = (
                result.robot_state.tcp_position.model_dump(mode="json")
                if result.robot_state is not None
                else record.current_tcp
            )
            record.status = (
                SessionStatus.ESTOP
                if result.final_state == AgentTaskState.ESTOP
                else SessionStatus.STOPPED
                if result.final_state == AgentTaskState.STOPPED
                else SessionStatus.FAILED
            )
            record.message = result.message
            record.error = self._orchestration_error(result)

        return self.store.mutate(session_id, finish)

    async def reset_estop(self, session_id: str) -> SessionSnapshot:
        # Resolve the session before performing a state-changing tool call.
        self.store.snapshot(session_id)
        command_id = f"web-reset-{uuid4().hex}"
        try:
            state = await asyncio.to_thread(self.robot.reset_estop, command_id)
        except Exception as error:
            return self.store.mutate(
                session_id,
                lambda record: self._mark_background_failure(record, error),
            )

        def finish(record) -> None:
            record.status = SessionStatus.READY
            record.active_command_id = None
            record.pending_command = None
            record.current_tcp = state.tcp_position.model_dump(mode="json")
            record.message = "急停已复位，仿真环境已重置"
            record.error = None

        return self.store.mutate(session_id, finish)

    async def _execute_confirmed(
        self,
        session_id: str,
        command: ParsedCommand,
        parse_started_ms: int,
        parse_finished_ms: int,
    ) -> None:
        try:
            result = await asyncio.to_thread(self.orchestrator.execute, command)
            events = [
                event.as_dict()
                for event in build_runtime_events(
                    parse_started_ms=parse_started_ms,
                    parse_finished_ms=parse_finished_ms,
                    orchestration=result,
                )
            ]

            def finish(record) -> None:
                record.active_command_id = None
                record.execution_events = events
                record.live_tool_events = []
                record.orchestration = result.as_dict()
                record.status = self._session_status(result.final_state)
                record.message = result.message
                record.error = self._orchestration_error(result)
                point = None
                if result.robot_state is not None:
                    point = result.robot_state.tcp_position
                elif result.robot_result is not None:
                    point = result.robot_result.final_tcp_position
                if point is not None:
                    record.current_tcp = point.model_dump(mode="json")

            self.store.mutate(session_id, finish)
        except Exception as error:  # pragma: no cover - defensive task boundary
            self.store.mutate(
                session_id,
                lambda record: self._mark_background_failure(record, error),
            )
        finally:
            self.store.unbind_command(command.command_id)

    def _on_tool_event(self, event: ToolEvent) -> None:
        self.store.add_tool_event(event)

    def _update_fps(self, session_id: str, frame_sequence: int) -> float:
        now = time.monotonic()
        with self._telemetry_lock:
            previous = self._fps_samples.get(session_id)
            if previous is None:
                fps = 0.0
            else:
                old_sequence, old_time, old_fps = previous
                elapsed = now - old_time
                if frame_sequence > old_sequence and elapsed > 0:
                    instantaneous = (frame_sequence - old_sequence) / elapsed
                    fps = instantaneous if old_fps <= 0 else old_fps * 0.65 + instantaneous * 0.35
                    sample_time = now
                elif elapsed >= 1.0:
                    fps = 0.0
                    sample_time = old_time
                else:
                    fps = old_fps
                    sample_time = old_time
            if previous is None:
                sample_time = now
            fps = round(max(0.0, min(fps, 240.0)), 1)
            self._fps_samples[session_id] = (frame_sequence, sample_time, fps)
            return fps

    def _record_parse_error(
        self,
        session_id: str,
        error: dict[str, Any],
    ) -> SessionSnapshot:
        def operation(record) -> None:
            record.status = SessionStatus.FAILED
            record.pending_command = None
            record.active_command_id = None
            record.message = str(error.get("message") or "解析失败")
            record.error = error
            record.parse_finished_ms = time.time_ns() // 1_000_000

        return self.store.mutate(session_id, operation)

    @staticmethod
    def _session_status(state: AgentTaskState) -> SessionStatus:
        return {
            AgentTaskState.PLAN_READY: SessionStatus.PLAN_READY,
            AgentTaskState.COMPLETED: SessionStatus.COMPLETED,
            AgentTaskState.STOPPED: SessionStatus.STOPPED,
            AgentTaskState.ESTOP: SessionStatus.ESTOP,
            AgentTaskState.CLARIFICATION_REQUIRED: (
                SessionStatus.CLARIFICATION_REQUIRED
            ),
        }.get(state, SessionStatus.FAILED)

    @staticmethod
    def _orchestration_error(result: Any) -> dict[str, Any] | None:
        if result.error_code is None:
            return None
        return {
            "code": result.error_code.value,
            "message": result.message,
            "details": {},
        }

    @staticmethod
    def _mark_background_failure(record: Any, error: Exception) -> None:
        record.active_command_id = None
        record.status = SessionStatus.FAILED
        record.message = f"后台任务失败：{type(error).__name__}"
        record.error = {
            "code": "INTERNAL_ERROR",
            "message": record.message,
            "details": {},
        }

    @staticmethod
    def _write_temporary_image(data_url: str) -> Path:
        if not data_url.startswith("data:") or ";base64," not in data_url:
            raise ValueError("image_data_url must be a base64 data URL")
        header, encoded = data_url.split(",", 1)
        mime_type = header[5:].split(";", 1)[0].lower()
        suffix = _IMAGE_SUFFIXES.get(mime_type)
        if suffix is None:
            raise ValueError("image must be JPEG, PNG, or WebP")
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("image_data_url contains invalid base64 data") from error
        if not payload:
            raise ValueError("image cannot be empty")
        if len(payload) > 10 * 1024 * 1024:
            raise ValueError("image cannot exceed 10 MiB")
        with tempfile.NamedTemporaryFile(
            prefix="interns2-web-",
            suffix=suffix,
            delete=False,
        ) as stream:
            stream.write(payload)
            return Path(stream.name)


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _point_from_payload(value: Any) -> Point3D | None:
    if value is None:
        return None
    if isinstance(value, Point3D):
        return value
    if not isinstance(value, dict):
        return None
    try:
        return Point3D.model_validate(value)
    except Exception:
        return None


def _relative_target(origin: Point3D, relative: dict[str, Any]) -> Point3D | None:
    axis = relative.get("axis")
    direction = relative.get("direction")
    distance = relative.get("distance_mm")
    if axis not in {"x", "y", "z"} or direction not in {"positive", "negative"}:
        return None
    try:
        signed = float(distance) * (1.0 if direction == "positive" else -1.0)
    except (TypeError, ValueError):
        return None
    delta = {
        "x": (signed, 0.0, 0.0),
        "y": (0.0, signed, 0.0),
        "z": (0.0, 0.0, signed),
    }[axis]
    return origin.translated(delta)


def _motion_progress(
    origin: Point3D | None,
    target: Point3D | None,
    current: Point3D,
) -> float | None:
    if origin is None or target is None:
        return None
    if origin.frame != target.frame or current.frame != target.frame:
        return None
    total = origin.distance_to(target)
    if total <= 1e-9:
        return 100.0
    remaining = current.distance_to(target)
    return round(max(0.0, min(100.0, (1.0 - remaining / total) * 100.0)), 1)


def _downsample_trajectory(
    points: list[tuple[float, float, float]],
    limit: int,
) -> list[tuple[float, float, float]]:
    if len(points) <= limit:
        return points
    if limit < 2:
        return [points[-1]]
    last_index = len(points) - 1
    indices = [round(index * last_index / (limit - 1)) for index in range(limit)]
    return [points[index] for index in indices]
