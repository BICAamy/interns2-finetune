"""Application runtime for preview/confirm web execution."""

from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import replace
from pathlib import Path
import tempfile
from threading import RLock
import time
from typing import Any, Callable, Protocol
from uuid import uuid4

from surgical_contracts import (
    CommandExecutionStatus,
    CommandIntent,
    CoordinateSource,
    ParsedCommand,
    Point3D,
    MoveRelativeRequest,
    MoveToEntryRequest,
    RobotMotionProposal,
    RobotCommandKind,
    RobotTelemetry,
    SetEnabledResult,
    SimulationTelemetry,
    SimulationCameraControlRequest,
    SimulationCameraState,
    ToolEvent,
    RuntimeMode,
)

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
from simulation.runtime_config import load_simulation_motion_policy

from .asr import (
    ASRService,
    ASRSettings,
    ASRStatus,
    SpeechTranscriber,
    TranscriptionResult,
)
from .models import (
    HealthResponse,
    InputSource,
    SessionSnapshot,
    SessionStatus,
    SimulationTelemetryView,
    TextCommandRequest,
)
from .simulation_proxy import (
    MJPEGStream,
    RobotSimulationObservabilityHTTPClient,
    SimulationObserver,
    SimulationProxyError,
)
from .sessions import SessionConflict, SessionStore


class CommandParser(Protocol):
    def parse_command(
        self,
        prompt: str,
        image_path: str | Path | None = None,
        *,
        input_source: CoordinateSource = CoordinateSource.USER_TEXT,
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
_REAL_CONNECTION_RECOVERY_NOTICE = "真实机械臂连接恢复中"


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
        asr_settings: ASRSettings | None = None,
        speech_transcriber: SpeechTranscriber | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        settings.validate()
        parser_was_provided = parser is not None
        configured_mode = RuntimeMode(settings.runtime_mode)
        fallback_url = settings.robot_simulation_fallback_base_url
        simulation_policy = None
        if configured_mode == RuntimeMode.SIMULATION or fallback_url:
            simulation_policy = load_simulation_motion_policy()
        if configured_mode == RuntimeMode.SIMULATION:
            assert simulation_policy is not None
            settings = replace(
                settings,
                entry_tolerance_mm=simulation_policy.entry_tolerance_mm,
                max_relative_translation_mm=(
                    simulation_policy.max_relative_translation_mm
                ),
                robot_move_speed_mm_s=simulation_policy.move_speed_mm_s,
                max_robot_speed_mm_s=simulation_policy.max_speed_mm_s,
            )
            settings.validate()
        self._configured_mode = configured_mode
        self._real_mode = configured_mode == RuntimeMode.REAL
        self._real_config = None
        self._real_mode_fallback_s: float | None = None
        if self._real_mode:
            from robot_runtime.real_config import load_real_config

            self._real_config = load_real_config(settings.real_config_path)
            fallback_ms = self._real_config.deadlines.real_mode_fallback_ms
            if fallback_ms is None:
                raise ValueError(
                    "real mode requires deadlines.real_mode_fallback_ms"
                )
            self._real_mode_fallback_s = fallback_ms / 1000.0
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
        real = self._real_config
        self.orchestrator = SurgicalTaskOrchestrator(
            self.robot,
            self.planner,
            policy=OrchestrationPolicy(
                entry_tolerance_mm=(
                    real.arrival.position_tolerance_mm or settings.entry_tolerance_mm
                    if real is not None else settings.entry_tolerance_mm
                ),
                max_relative_translation_mm=(
                    real.limits.max_step_mm or settings.max_relative_translation_mm
                    if real is not None else settings.max_relative_translation_mm
                ),
                move_speed_mm_s=(
                    real.motion.speed_mm_s or settings.robot_move_speed_mm_s
                    if real is not None else settings.robot_move_speed_mm_s
                ),
                max_speed_mm_s=(
                    real.limits.max_speed_mm_s or settings.max_robot_speed_mm_s
                    if real is not None else settings.max_robot_speed_mm_s
                ),
                expected_runtime_mode=configured_mode,
                move_tcp_name=(
                    (real.tool.tcp_name or "needle_tip")
                    if real is not None
                    else simulation_policy.tcp_name
                ),
                entry_orientation_policy=(
                    "hold_current_actual_orientation"
                    if real is not None else "configured_safe_orientation"
                ),
            ),
            event_sink=self._on_tool_event,
        )
        self._parsers: dict[RuntimeMode, CommandParser] = {
            configured_mode: self.parser,
        }
        self._robots: dict[RuntimeMode, Any] = {
            configured_mode: self.robot,
        }
        self._observers: dict[RuntimeMode, SimulationObserver] = {
            configured_mode: self.simulation_observer,
        }
        self._orchestrators: dict[RuntimeMode, SurgicalTaskOrchestrator] = {
            configured_mode: self.orchestrator,
        }
        self._secondary_resources: list[Any] = []
        if self._real_mode and fallback_url:
            assert simulation_policy is not None
            simulation_settings = replace(
                settings,
                runtime_mode=RuntimeMode.SIMULATION,
                real_config_path=None,
                robot_simulation_base_url=fallback_url,
                robot_simulation_fallback_base_url=None,
                entry_tolerance_mm=simulation_policy.entry_tolerance_mm,
                max_relative_translation_mm=(
                    simulation_policy.max_relative_translation_mm
                ),
                robot_move_speed_mm_s=simulation_policy.move_speed_mm_s,
                max_robot_speed_mm_s=simulation_policy.max_speed_mm_s,
            )
            simulation_settings.validate()
            simulation_robot = RobotSimulationHTTPController(
                fallback_url,
                http_timeout_s=settings.robot_simulation_http_timeout,
                command_timeout_s=settings.robot_simulation_command_timeout,
                poll_interval_s=settings.robot_simulation_poll_interval,
            )
            simulation_observer = RobotSimulationObservabilityHTTPClient(
                fallback_url,
                timeout_s=min(settings.robot_simulation_http_timeout, 2.0),
            )
            simulation_parser = (
                InternS2Agent(simulation_settings, client=self._model_http)
                if not parser_was_provided
                else parser
            )
            simulation_orchestrator = SurgicalTaskOrchestrator(
                simulation_robot,
                self.planner,
                policy=OrchestrationPolicy(
                    entry_tolerance_mm=simulation_settings.entry_tolerance_mm,
                    max_relative_translation_mm=(
                        simulation_settings.max_relative_translation_mm
                    ),
                    move_speed_mm_s=simulation_settings.robot_move_speed_mm_s,
                    max_speed_mm_s=simulation_settings.max_robot_speed_mm_s,
                    expected_runtime_mode=RuntimeMode.SIMULATION,
                    move_tcp_name=simulation_policy.tcp_name,
                ),
                event_sink=self._on_tool_event,
            )
            self._parsers[RuntimeMode.SIMULATION] = simulation_parser
            self._robots[RuntimeMode.SIMULATION] = simulation_robot
            self._observers[RuntimeMode.SIMULATION] = simulation_observer
            self._orchestrators[RuntimeMode.SIMULATION] = simulation_orchestrator
            self._secondary_resources.extend([simulation_robot, simulation_observer])
        self._default_robot_mode = (
            RuntimeMode.SIMULATION
            if RuntimeMode.SIMULATION in self._robots
            else configured_mode
        )
        self._tasks: set[asyncio.Task[Any]] = set()
        self._motion_origins: dict[str, Point3D] = {}
        self._fps_samples: dict[str, tuple[int, float, float]] = {}
        self._real_feedback_unavailable_since: dict[str, float] = {}
        self._telemetry_lock = RLock()
        self._monotonic_clock = monotonic_clock
        self.telemetry_interval_s = 0.1
        self.asr = ASRService(
            asr_settings or ASRSettings.from_env(),
            transcriber=speech_transcriber,
        )

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
        if self._owns_simulation_observer and self.simulation_observer is not None:
            self.simulation_observer.close()
        for resource in self._secondary_resources:
            resource.close()

    async def create_session(self) -> SessionSnapshot:
        snapshot = self.store.create(robot_mode=self._default_robot_mode)
        try:
            default_robot = self._robots[self._default_robot_mode]
            if self._real_mode and self._default_robot_mode == RuntimeMode.SIMULATION:
                state = await asyncio.to_thread(
                    default_robot.reset_estop,
                    f"web-default-simulation-{uuid4().hex}",
                )
            else:
                state = await asyncio.to_thread(default_robot.get_state)
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

    @property
    def available_robot_modes(self) -> tuple[RuntimeMode, ...]:
        return tuple(self._robots)

    def _session_mode(self, session_id: str) -> RuntimeMode:
        return RuntimeMode(self.store.snapshot(session_id).robot_mode)

    def _resources_for_session(
        self, session_id: str,
    ) -> tuple[RuntimeMode, CommandParser, Any, SimulationObserver, SurgicalTaskOrchestrator]:
        mode = self._session_mode(session_id)
        if mode == self._configured_mode:
            return (
                mode,
                self.parser,
                self.robot,
                self.simulation_observer,
                self.orchestrator,
            )
        return (
            mode,
            self._parsers[mode],
            self._robots[mode],
            self._observers[mode],
            self._orchestrators[mode],
        )

    @staticmethod
    def _real_feedback_issue(telemetry: RobotTelemetry) -> str | None:
        connections = telemetry.connections
        if telemetry.freshness.value != "fresh":
            age = (
                f"，状态年龄 {telemetry.state_age_ms:.0f} ms"
                if telemetry.state_age_ms is not None
                else ""
            )
            return f"真实状态为 {telemetry.freshness.value}{age}"
        for name in ("gateway", "datasheet", "command_socket", "controller_box"):
            if getattr(connections, name).value != "connected":
                return f"{name} 连接为 {getattr(connections, name).value}"
        if telemetry.actual_pose_robot_base is None:
            return "真实状态缺少 Base 坐标系位姿"
        if telemetry.joint_positions_deg is None:
            return "真实状态缺少关节角"
        return None

    @classmethod
    def _real_feedback_available(cls, telemetry: RobotTelemetry) -> bool:
        return cls._real_feedback_issue(telemetry) is None

    def _clear_real_feedback_outage(self, session_id: str) -> bool:
        with self._telemetry_lock:
            return self._real_feedback_unavailable_since.pop(session_id, None) is not None

    def _real_feedback_outage_expired(
        self,
        session_id: str,
        *,
        detail: str,
    ) -> bool:
        fallback_s = self._real_mode_fallback_s
        if fallback_s is None:
            return True
        now = self._monotonic_clock()
        with self._telemetry_lock:
            started_at = self._real_feedback_unavailable_since.get(session_id)
            newly_started = started_at is None
            if started_at is None:
                started_at = now
                self._real_feedback_unavailable_since[session_id] = started_at
            expired = now - started_at >= fallback_s
        if newly_started:
            def mark_recovering(record: Any) -> None:
                if record.robot_mode != RuntimeMode.REAL:
                    return
                record.mode_notice = _REAL_CONNECTION_RECOVERY_NOTICE
                record.message = f"{_REAL_CONNECTION_RECOVERY_NOTICE}：{detail}"

            self.store.mutate(session_id, mark_recovering)
        return expired

    def _mark_real_feedback_recovered(self, session_id: str) -> None:
        if not self._clear_real_feedback_outage(session_id):
            return

        def mark_recovered(record: Any) -> None:
            if (
                record.robot_mode == RuntimeMode.REAL
                and record.mode_notice == _REAL_CONNECTION_RECOVERY_NOTICE
            ):
                record.mode_notice = None
                record.message = "真实机械臂连接已恢复"

        self.store.mutate(session_id, mark_recovered)

    async def set_robot_mode(
        self, session_id: str, *, mode: RuntimeMode,
    ) -> SessionSnapshot:
        session = self.store.snapshot(session_id)
        if session.status in _BUSY_STATUSES or session.pending_confirmation:
            raise SessionConflict("当前任务尚未结束，不能切换机械臂模式")
        if mode not in self._robots:
            raise SessionConflict(f"当前服务没有启动 {mode.value} 运行时")

        if mode == RuntimeMode.REAL:
            try:
                telemetry = await asyncio.to_thread(
                    self._observers[RuntimeMode.REAL].get_telemetry
                )
            except Exception as error:
                return self._fallback_to_simulation(session_id, str(error))
            if (
                not isinstance(telemetry, RobotTelemetry)
                or not self._real_feedback_available(telemetry)
            ):
                return self._fallback_to_simulation(
                    session_id, "未收到完整、新鲜的 10003/10004 真实机械臂状态"
                )
            try:
                await asyncio.to_thread(
                    self._observers[RuntimeMode.REAL].get_mirror_status
                )
            except Exception as error:
                return self._fallback_to_simulation(
                    session_id, f"真实机械臂数字孪生未启动：{error}"
                )
            pose = telemetry.actual_pose_robot_base
            assert pose is not None
            self._clear_real_feedback_outage(session_id)
            return self.store.mutate(
                session_id,
                lambda record: self._apply_mode(
                    record,
                    RuntimeMode.REAL,
                    current_tcp=Point3D(
                        x=pose.translation_mm[0],
                        y=pose.translation_mm[1],
                        z=pose.translation_mm[2],
                        frame=pose.frame,
                        unit=pose.unit,
                    ).model_dump(mode="json"),
                    notice=None,
                ),
            )

        self._clear_real_feedback_outage(session_id)
        # Entering simulation always resets its single environment owner so the
        # browser starts from the configured default simulation pose.
        simulation_robot = self._robots[RuntimeMode.SIMULATION]
        try:
            state = await asyncio.to_thread(
                simulation_robot.reset_estop,
                f"web-mode-simulation-{uuid4().hex}",
            )
        except Exception as error:
            raise SessionConflict(f"无法重置仿真环境：{error}") from error
        return self.store.mutate(
            session_id,
            lambda record: self._apply_mode(
                record,
                RuntimeMode.SIMULATION,
                current_tcp=state.tcp_position.model_dump(mode="json"),
                notice=None,
            ),
        )

    @staticmethod
    def _apply_mode(
        record: Any,
        mode: RuntimeMode,
        *,
        current_tcp: dict[str, Any] | None,
        notice: str | None,
    ) -> None:
        record.robot_mode = mode
        record.mode_notice = notice
        record.current_tcp = current_tcp
        record.status = SessionStatus.READY
        record.pending_command = None
        record.active_command_id = None
        record.raw_model_output = None
        record.normalized_command = None
        record.motion_proposal = None
        record.execution_events = []
        record.live_tool_events = []
        record.orchestration = None
        record.error = None
        record.message = notice or (
            "已切换到真实机械臂" if mode == RuntimeMode.REAL else "已切换到仿真模式"
        )

    def _fallback_to_simulation(
        self, session_id: str, detail: str,
    ) -> SessionSnapshot:
        self._clear_real_feedback_outage(session_id)
        notice = f"未连接机械臂，已自动退回仿真模式：{detail}"
        current_tcp = None
        simulation_robot = self._robots.get(RuntimeMode.SIMULATION)
        if simulation_robot is not None:
            try:
                state = simulation_robot.reset_estop(
                    f"web-auto-fallback-{uuid4().hex}"
                )
                current_tcp = state.tcp_position.model_dump(mode="json")
            except Exception:
                pass
        return self.store.mutate(
            session_id,
            lambda record: self._apply_mode(
                record,
                RuntimeMode.SIMULATION,
                current_tcp=current_tcp,
                notice=notice,
            ),
        )

    async def set_robot_enabled(
        self, session_id: str, *, enabled: bool,
    ) -> SetEnabledResult:
        """Change the physical enable state through the authenticated Mac gateway."""
        mode, _parser, robot, _observer, _orchestrator = self._resources_for_session(
            session_id
        )
        if mode != RuntimeMode.REAL:
            raise SessionConflict("使能/去使能只适用于真实机械臂")
        session = self.store.snapshot(session_id)
        if session.status in _BUSY_STATUSES:
            raise SessionConflict("当前任务正在执行，不能切换使能状态")
        return await asyncio.to_thread(
            robot.set_enabled,
            enabled,
            f"web-{'enable' if enabled else 'disable'}-{uuid4().hex}",
        )

    def get_robot_telemetry(self, session_id: str) -> SimulationTelemetryView:
        mode, _parser, _robot, observer, _orchestrator = self._resources_for_session(
            session_id
        )
        session = self.store.snapshot(session_id)
        telemetry = observer.get_telemetry()
        if isinstance(telemetry, RobotTelemetry):
            issue = self._real_feedback_issue(telemetry)
            if issue is not None:
                if (
                    RuntimeMode.SIMULATION not in self._observers
                    or session.active_command_id is not None
                    or session.status in _BUSY_STATUSES
                ):
                    return self._real_telemetry_view(session, telemetry, observer)
                if self._real_feedback_outage_expired(
                    session_id,
                    detail=issue,
                ):
                    fallback_ms = int((self._real_mode_fallback_s or 0) * 1000)
                    self._fallback_to_simulation(
                        session_id,
                        f"真实连接连续异常超过 {fallback_ms} ms：{issue}",
                    )
                    return self.get_robot_telemetry(session_id)
                session = self.store.snapshot(session_id)
                return self._real_telemetry_view(session, telemetry, observer)
            self._mark_real_feedback_recovered(session_id)
            session = self.store.snapshot(session_id)
            return self._real_telemetry_view(session, telemetry, observer)
        if mode != RuntimeMode.SIMULATION:
            raise SimulationProxyError("真实模式收到了仿真遥测")
        if not isinstance(telemetry, SimulationTelemetry):
            raise SimulationProxyError("robot-runtime 返回了未知遥测类型")
        return self._simulation_telemetry_view(session, telemetry)

    def _real_telemetry_view(
        self,
        session: SessionSnapshot,
        telemetry: RobotTelemetry,
        observer: SimulationObserver,
    ) -> SimulationTelemetryView:
        try:
            mirror = observer.get_mirror_status()
        except SimulationProxyError as error:
            mirror = {"warning": f"SOFA mirror unavailable: {error}"}
        pose = telemetry.actual_pose_robot_base
        current_tcp = (
            Point3D(
                x=pose.translation_mm[0],
                y=pose.translation_mm[1],
                z=pose.translation_mm[2],
                frame=pose.frame,
                unit=pose.unit,
            )
            if pose is not None
            else None
        )
        connections = {
            "server": "connected",
            **{
                key: value.value
                for key, value in telemetry.connections.model_dump(mode="python").items()
            },
        }
        feedback_issue = self._real_feedback_issue(telemetry)
        return SimulationTelemetryView(
            connected=feedback_issue is None,
            runtime_mode="real",
            provider=telemetry.provider.value,
            freshness=telemetry.freshness.value,
            source_age_ms=telemetry.state_age_ms,
            connections=connections,
            sequence=telemetry.sequence,
            received_at_ms=_now_ms(),
            source_updated_at_ms=telemetry.server_received_at_ms,
            state_machine_state=session.status.value,
            motion_state=(telemetry.motion_state.value if telemetry.motion_state else None),
            estop=bool(telemetry.physical_estop_active),
            current_tcp=current_tcp,
            actual_tcp_robot_base=(pose.model_dump(mode="json") if pose else None),
            joint_positions_deg=(
                [float(value) for value in telemetry.joint_positions_deg]
                if telemetry.joint_positions_deg is not None
                else []
            ),
            frame_sequence=int(mirror.get("frame_sequence", 0)) if mirror else 0,
            fsm_code=telemetry.fsm_code,
            enabled=telemetry.enabled,
            electrified=telemetry.electrified,
            moving=telemetry.moving,
            in_position=telemetry.in_position,
            physical_estop_active=telemetry.physical_estop_active,
            emergency_stop_circuit_fault=telemetry.emergency_stop_circuit_fault,
            safeguard_active=telemetry.safeguard_active,
            safeguard_circuit_fault=telemetry.safeguard_circuit_fault,
            vendor_fault=(
                telemetry.vendor_fault.model_dump(mode="json")
                if telemetry.vendor_fault is not None
                else None
            ),
            mirror_calibrated=(bool(mirror.get("calibrated")) if mirror else None),
            mirror_warning=(str(mirror.get("warning")) if mirror else None),
            mirror_reason=(str(mirror.get("reason")) if mirror else None),
            mirror_source_sequence=(
                int(mirror["source_sequence"])
                if mirror and mirror.get("source_sequence") is not None
                else None
            ),
            error=(None if feedback_issue is None else {
                "code": (
                    f"ROBOT_{telemetry.freshness.value.upper()}"
                    if telemetry.freshness.value != "fresh"
                    else "ROBOT_CONNECTION_UNAVAILABLE"
                ),
                "message": f"{_REAL_CONNECTION_RECOVERY_NOTICE}：{feedback_issue}",
            }),
        )

    def _simulation_telemetry_view(
        self,
        session: SessionSnapshot,
        telemetry: SimulationTelemetry,
    ) -> SimulationTelemetryView:
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
        origin = self._motion_origins.get(session.session_id)
        relative = command.get("relative_motion")
        if motion_target is None and origin is not None and isinstance(relative, dict):
            motion_target = _relative_target(origin, relative)
        progress = _motion_progress(origin, motion_target, current_tcp)
        trajectory = [tuple(float(value) for value in point) for point in telemetry.trajectory_mm]
        return SimulationTelemetryView(
            connected=True,
            runtime_mode="simulation",
            provider="simulation",
            freshness="fresh",
            connections={"server": "connected"},
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
                session.session_id,
                telemetry.frame_sequence,
            ),
            error=session.error,
        )

    def get_simulation_telemetry(self, session_id: str) -> SimulationTelemetryView:
        return self.get_robot_telemetry(session_id)

    def robot_telemetry_error(
        self,
        session_id: str,
        error: Exception,
    ) -> SimulationTelemetryView:
        session = self.store.snapshot(session_id)
        selected_mode = RuntimeMode(session.robot_mode)
        if (
            selected_mode == RuntimeMode.REAL
            and RuntimeMode.SIMULATION in self._observers
            and session.active_command_id is None
            and session.status not in _BUSY_STATUSES
        ):
            detail = str(error) or type(error).__name__
            if self._real_feedback_outage_expired(session_id, detail=detail):
                fallback_ms = int((self._real_mode_fallback_s or 0) * 1000)
                self._fallback_to_simulation(
                    session_id,
                    f"真实连接连续异常超过 {fallback_ms} ms：{detail}",
                )
                try:
                    return self.get_robot_telemetry(session_id)
                except Exception as fallback_error:
                    error = fallback_error
                    session = self.store.snapshot(session_id)
                    selected_mode = RuntimeMode.SIMULATION
            else:
                session = self.store.snapshot(session_id)
        command = session.normalized_command or {}
        return SimulationTelemetryView(
            connected=False,
            runtime_mode=selected_mode.value,
            freshness="disconnected",
            connections={"server": "disconnected"},
            sequence=0,
            received_at_ms=_now_ms(),
            state_machine_state=session.status.value,
            current_tool=_CURRENT_TOOLS.get(session.status),
            entry_point=_point_from_payload(command.get("entry_point")),
            target_point=_point_from_payload(command.get("target_point")),
            error={
                "code": (
                    "GATEWAY_DISCONNECTED"
                    if selected_mode == RuntimeMode.REAL
                    else "ROBOT_TELEMETRY_UNAVAILABLE"
                ),
                "message": str(error) or type(error).__name__,
                "details": {},
            },
        )

    def simulation_telemetry_error(
        self, session_id: str, error: Exception
    ) -> SimulationTelemetryView:
        return self.robot_telemetry_error(session_id, error)

    def _verify_session_observer_mode(self, session_id: str) -> SimulationObserver:
        mode = self._session_mode(session_id)
        observer = self._observers[mode]
        telemetry = observer.get_telemetry()
        if mode == RuntimeMode.REAL and not isinstance(telemetry, RobotTelemetry):
            raise SimulationProxyError("robot-runtime 没有运行在 real 模式")
        if mode == RuntimeMode.SIMULATION and not isinstance(telemetry, SimulationTelemetry):
            raise SimulationProxyError("robot-runtime 没有运行在 simulation 模式")
        return observer

    async def open_robot_video(self, session_id: str) -> MJPEGStream:
        self.store.snapshot(session_id)
        observer = await asyncio.to_thread(
            self._verify_session_observer_mode, session_id
        )
        return await observer.open_mjpeg()

    async def open_simulation_video(self, session_id: str) -> MJPEGStream:
        return await self.open_robot_video(session_id)

    def get_robot_camera(self, session_id: str) -> SimulationCameraState:
        self.store.snapshot(session_id)
        observer = self._verify_session_observer_mode(session_id)
        return observer.get_camera_state()

    def get_simulation_camera(self, session_id: str) -> SimulationCameraState:
        return self.get_robot_camera(session_id)

    def control_robot_camera(
        self,
        session_id: str,
        request: SimulationCameraControlRequest,
    ) -> SimulationCameraState:
        self.store.snapshot(session_id)
        observer = self._verify_session_observer_mode(session_id)
        return observer.control_camera(request)

    def control_simulation_camera(
        self, session_id: str, request: SimulationCameraControlRequest
    ) -> SimulationCameraState:
        return self.control_robot_camera(session_id, request)

    def health(self) -> HealthResponse:
        return HealthResponse(
            runtime_mode=RuntimeMode(self.settings.runtime_mode).value,
            default_robot_mode=self._default_robot_mode.value,
            available_robot_modes=[mode.value for mode in self.available_robot_modes],
            puncture_execution_enabled=False,
            sessions=self.store.count,
            downstream={
                "interns2": self.settings.base_url,
                ("robot_runtime" if self._real_mode else "robot_simulation"):
                    self.settings.robot_simulation_base_url,
                **(
                    {
                        "robot_simulation":
                            self.settings.robot_simulation_fallback_base_url
                    }
                    if self.settings.robot_simulation_fallback_base_url
                    else {}
                ),
                "planner_adapter": self.settings.planner_adapter_base_url,
            },
            asr=self.asr.status(),
        )

    def asr_status(self) -> ASRStatus:
        return self.asr.status()

    async def submit_speech(
        self,
        session_id: str,
        audio: bytes,
        *,
        content_type: str,
        duration_ms: int,
    ) -> SessionSnapshot:
        # Reject unknown sessions before spending time on ASR inference.
        self.store.snapshot(session_id)
        request_started = time.monotonic()
        transcription = await asyncio.to_thread(
            self.asr.transcribe,
            audio,
            content_type=content_type,
            reported_duration_ms=duration_ms,
        )
        safety_action = _speech_safety_action(transcription.text)
        if safety_action is not None:
            transcription = transcription.model_copy(
                update={"safety_action": safety_action}
            )
            await self.stop(
                session_id,
                emergency=safety_action == "estop",
            )
            return self.store.mutate(
                session_id,
                lambda record: _record_speech_metadata(
                    record,
                    transcription,
                    request_started,
                ),
            )

        return await self.submit_text(
            session_id,
            TextCommandRequest(prompt=transcription.text),
            input_source=InputSource.VOICE,
            asr_transcription=transcription,
            request_started=request_started,
        )

    async def submit_text(
        self,
        session_id: str,
        request: TextCommandRequest,
        *,
        input_source: InputSource = InputSource.TEXT,
        asr_transcription: TranscriptionResult | None = None,
        request_started: float | None = None,
    ) -> SessionSnapshot:
        selected_mode, parser, robot, _observer, orchestrator = (
            self._resources_for_session(session_id)
        )
        parse_started_ms = time.time_ns() // 1_000_000
        parse_token = uuid4().hex

        def begin(record) -> None:
            if record.status in _BUSY_STATUSES:
                raise SessionConflict("session already has a pending or active command")
            record.status = SessionStatus.PARSING
            record.prompt = request.prompt.strip()
            record.input_source = input_source
            record.image_name = request.image_name
            record.asr_transcription = asr_transcription
            record.pending_command = None
            record.active_command_id = None
            record.raw_model_output = None
            record.normalized_command = None
            record.motion_proposal = None
            record.execution_events = []
            record.live_tool_events = []
            record.orchestration = None
            record.message = "正在解析指令"
            record.error = None
            record.parse_started_ms = parse_started_ms
            record.parse_finished_ms = None
            record.parse_token = parse_token

        self.store.mutate(session_id, begin)
        image_path: Path | None = None
        try:
            if request.image_data_url:
                image_path = self._write_temporary_image(request.image_data_url)
            parsed = await asyncio.to_thread(
                parser.parse_command,
                request.prompt,
                image_path,
                input_source=(
                    CoordinateSource.ASR_TEXT
                    if input_source == InputSource.VOICE
                    else CoordinateSource.USER_TEXT
                ),
            )
        except CommandParsingError as error:
            return self._record_parse_error(
                session_id,
                error.as_dict(),
                parse_token=parse_token,
            )
        except (ValueError, OSError) as error:
            return self._record_parse_error(
                session_id,
                {
                    "code": "INVALID_WEB_INPUT",
                    "message": str(error),
                    "details": {},
                },
                parse_token=parse_token,
            )
        except Exception as error:  # pragma: no cover - defensive service boundary
            return self._record_parse_error(
                session_id,
                {
                    "code": "INTERNAL_ERROR",
                    "message": f"解析失败：{type(error).__name__}",
                    "details": {},
                },
                parse_token=parse_token,
            )
        finally:
            if image_path is not None:
                image_path.unlink(missing_ok=True)

        motion_proposal: RobotMotionProposal | None = None
        if selected_mode == RuntimeMode.REAL and parsed.command.intent != CommandIntent.CLARIFY:
            if parsed.command.intent not in {
                CommandIntent.MOVE_RELATIVE,
                CommandIntent.MOVE_TO_ENTRY,
            }:
                return self._record_parse_error(
                    session_id,
                    {
                        "code": "OPERATION_NOT_ENABLED",
                        "message": "真实模式只开放相对位移和 Base 坐标系绝对 XYZ 运动",
                        "details": {},
                    },
                    parse_token=parse_token,
                )
            if parsed.command.intent == CommandIntent.MOVE_RELATIVE:
                if parsed.command.relative_motion is None:
                    return self._record_parse_error(
                        session_id,
                        {
                            "code": "INVALID_COMMAND_SCHEMA",
                            "message": "相对运动缺少位移参数",
                            "details": {},
                        },
                        parse_token=parse_token,
                    )
                proposal_request = MoveRelativeRequest(
                    command_id=parsed.command.command_id,
                    translation_mm=parsed.command.relative_motion.translation_mm(),
                    frame=parsed.command.relative_motion.frame,
                    speed_mm_s=orchestrator.policy.move_speed_mm_s,
                )
                proposal_method = robot.create_move_relative_proposal
            else:
                if parsed.command.entry_point is None or self._real_config is None:
                    return self._record_parse_error(
                        session_id,
                        {
                            "code": "INVALID_COMMAND_SCHEMA",
                            "message": "绝对运动缺少 Base XYZ 目标",
                            "details": {},
                        },
                        parse_token=parse_token,
                    )
                proposal_request = MoveToEntryRequest(
                    command_id=parsed.command.command_id,
                    entry_point=parsed.command.entry_point,
                    tcp=self._real_config.tool.tcp_name,
                    orientation_policy="hold_current_actual_orientation",
                    speed_mm_s=orchestrator.policy.move_speed_mm_s,
                )
                proposal_method = robot.create_move_to_entry_proposal
            try:
                proposal_record = await asyncio.to_thread(
                    proposal_method,
                    proposal_request,
                )
                if proposal_record.status != CommandExecutionStatus.QUEUED:
                    raise RuntimeError("robot-runtime did not return a queued proposal")
                proposal_payload = (proposal_record.result or {}).get("proposal")
                motion_proposal = RobotMotionProposal.model_validate(proposal_payload)
                if motion_proposal.web_confirmed or motion_proposal.executable:
                    raise RuntimeError("new proposal was unexpectedly executable")
            except Exception as error:
                return self._record_parse_error(
                    session_id,
                    {
                        "code": getattr(getattr(error, "error_code", None), "value", "INTERNAL_ERROR"),
                        "message": f"无法生成真机运动 proposal：{error}",
                        "details": {},
                    },
                    parse_token=parse_token,
                )

        parse_finished_ms = time.time_ns() // 1_000_000

        def finish(record) -> None:
            if record.parse_token != parse_token:
                return
            payload = parsed.as_dict()
            record.raw_model_output = payload.get("raw_model_output")
            record.normalized_command = parsed.command.model_dump(mode="json")
            record.motion_proposal = (
                motion_proposal.model_dump(mode="json")
                if motion_proposal is not None
                else None
            )
            record.parse_finished_ms = parse_finished_ms
            record.parse_token = None
            record.execution_events = [
                event.as_dict()
                for event in build_runtime_events(
                    parse_started_ms=parse_started_ms,
                    parse_finished_ms=parse_finished_ms,
                    orchestration=None,
                )
            ]
            if asr_transcription is not None and request_started is not None:
                record.asr_transcription = asr_transcription.model_copy(
                    update={
                        "end_to_end_latency_ms": round(
                            (time.monotonic() - request_started) * 1000
                        )
                    }
                )
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
                if motion_proposal is not None:
                    record.message = "不可执行 proposal 已生成；核对 fingerprint 后确认一次即可"
                if (
                    asr_transcription is not None
                    and asr_transcription.low_confidence
                ):
                    record.message = (
                        "语音置信度较低，请逐字核对转写与坐标；确认后才会调用机械臂"
                    )

        return self.store.mutate(session_id, finish)

    async def confirm(
        self, session_id: str, *, fingerprint: str | None = None,
    ) -> SessionSnapshot:
        selected_mode, _parser, robot, _observer, orchestrator = (
            self._resources_for_session(session_id)
        )
        selected: dict[str, Any] = {}

        def begin(record) -> None:
            if record.pending_command is None:
                raise SessionConflict("session has no command awaiting confirmation")
            if selected_mode == RuntimeMode.REAL:
                proposal = RobotMotionProposal.model_validate(record.motion_proposal)
                if fingerprint != proposal.fingerprint:
                    raise SessionConflict(
                        "网页确认的 fingerprint 与当前 motion proposal 不一致"
                    )
            command = record.pending_command
            selected["command"] = command
            selected["parse_started_ms"] = record.parse_started_ms
            selected["parse_finished_ms"] = record.parse_finished_ms
            selected["motion_origin"] = record.current_tcp
            selected["motion_proposal"] = record.motion_proposal
            record.pending_command = None
            record.active_command_id = command.command_id
            record.status = SessionStatus.EXECUTING
            record.live_tool_events = []
            record.message = "任务已确认，准备调用机械臂"
            record.error = None

        snapshot = self.store.mutate(session_id, begin)
        command: ParsedCommand = selected["command"]
        if selected_mode == RuntimeMode.REAL:
            try:
                proposal = RobotMotionProposal.model_validate(selected["motion_proposal"])
                confirmed_record = await asyncio.to_thread(
                    robot.confirm_motion_proposal,
                    command.command_id,
                    proposal.fingerprint,
                    RobotCommandKind(proposal.envelope.command_kind.value),
                )
                if confirmed_record.status != CommandExecutionStatus.RUNNING:
                    raise RuntimeError("motion proposal was not accepted for dispatch")
                confirmed_proposal = RobotMotionProposal.model_validate(
                    (confirmed_record.result or {}).get("proposal")
                )
                if (
                    not confirmed_proposal.web_confirmed
                    or confirmed_proposal.fingerprint != proposal.fingerprint
                ):
                    raise RuntimeError("confirmed proposal fingerprint changed")
                snapshot = self.store.mutate(
                    session_id,
                    lambda record: setattr(
                        record,
                        "motion_proposal",
                        confirmed_proposal.model_dump(mode="json"),
                    ),
                )
            except Exception as error:
                return self.store.mutate(
                    session_id,
                    lambda record: self._mark_background_failure(record, error),
                )
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
                orchestrator,
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
        selected_mode, _parser, _robot, _observer, orchestrator = (
            self._resources_for_session(session_id)
        )
        if selected_mode == RuntimeMode.REAL:
            raise SessionConflict(
                "Step 12 真实模式仅开放已确认的 move_relative；"
                "网页不能发送停止或急停，请使用现场物理装置"
            )
        command = ParsedCommand(
            command_id=f"web-{'estop' if emergency else 'stop'}-{uuid4().hex}",
            intent=(
                CommandIntent.EMERGENCY_STOP if emergency else CommandIntent.STOP
            ),
        )

        def begin(record) -> None:
            record.parse_token = None
            record.pending_command = None
            record.active_command_id = command.command_id
            record.status = SessionStatus.ESTOP if emergency else SessionStatus.STOPPING
            record.message = "正在执行急停" if emergency else "正在停止机械臂"

        self.store.mutate(session_id, begin)
        self.store.bind_command(session_id, command.command_id)
        try:
            result = await asyncio.to_thread(orchestrator.execute, command)
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
        selected_mode, _parser, robot, _observer, _orchestrator = (
            self._resources_for_session(session_id)
        )
        if selected_mode == RuntimeMode.REAL:
            raise SessionConflict("Step 12 真实模式禁止远程复位急停")
        # Resolve the session before performing a state-changing tool call.
        self.store.snapshot(session_id)
        command_id = f"web-reset-{uuid4().hex}"
        try:
            state = await asyncio.to_thread(robot.reset_estop, command_id)
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
        orchestrator: SurgicalTaskOrchestrator,
    ) -> None:
        try:
            result = await asyncio.to_thread(orchestrator.execute, command)
            events = [
                event.as_dict()
                for event in build_runtime_events(
                    parse_started_ms=parse_started_ms,
                    parse_finished_ms=parse_finished_ms,
                    orchestration=result,
                )
            ]

            def finish(record) -> None:
                if record.active_command_id != command.command_id:
                    return
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
            def fail_if_active(record) -> None:
                if record.active_command_id == command.command_id:
                    self._mark_background_failure(record, error)

            self.store.mutate(session_id, fail_if_active)
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
        *,
        parse_token: str,
    ) -> SessionSnapshot:
        def operation(record) -> None:
            if record.parse_token != parse_token:
                return
            record.status = SessionStatus.FAILED
            record.pending_command = None
            record.active_command_id = None
            record.message = str(error.get("message") or "解析失败")
            record.error = error
            record.parse_finished_ms = time.time_ns() // 1_000_000
            record.parse_token = None

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


_STOP_SPEECH_PHRASES = {
    "停止",
    "停止机械臂",
    "机械臂停止",
    "停下来",
    "立即停止",
}

_ESTOP_SPEECH_PHRASES = {
    "急停",
    "紧急停止",
    "立即急停",
    "机械臂急停",
}


def _speech_safety_action(text: str) -> str | None:
    normalized = "".join(
        character
        for character in text.strip().lower()
        if character not in " ，。！？、,.!?;；:：\t\r\n"
    )
    if normalized in _ESTOP_SPEECH_PHRASES:
        return "estop"
    if normalized in _STOP_SPEECH_PHRASES:
        return "stop"
    return None


def _record_speech_metadata(
    record: Any,
    transcription: TranscriptionResult,
    request_started: float,
) -> None:
    record.prompt = transcription.text
    record.input_source = InputSource.VOICE
    record.image_name = None
    if transcription.safety_action is not None:
        record.raw_model_output = None
        record.normalized_command = None
    record.asr_transcription = transcription.model_copy(
        update={
            "end_to_end_latency_ms": round(
                (time.monotonic() - request_started) * 1000
            )
        }
    )


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
