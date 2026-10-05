"""Mac edge gateway for authenticated feedback and explicitly confirmed commands."""

from __future__ import annotations

import argparse
from pathlib import Path
import threading
import time
from typing import Callable

from surgical_contracts import (
    ErrorCode, GatewayCommandKind, LinkState, RobotCommandEnvelope,
    RobotCommandResult, RobotTelemetry, SetEnabledRequest, ToolStatus,
    command_fingerprint,
    load_gateway_secret,
)

from .audit import EdgeAudit
from .cloud_transport import CloudTransport, telemetry_from_sample
from .config import EdgeConfig, RealEdgeConfig
from .huayan.adapter import (
    read_controller_started, read_current_fsm, read_identity_text, read_is_simulation,
    read_emergency_info, read_robot_state,
)
from .huayan.command_client import CommandClient
from .huayan.datasheet_client import DatasheetClient
from .huayan.models import ReadCommand
from .state_machine import EdgeState
from .watchdog import SourceStampWatchdog, StateWatchdog


class EdgeGateway:
    def __init__(
        self,
        config: EdgeConfig | RealEdgeConfig,
        *,
        command_handler: Callable[[RobotCommandEnvelope, str], RobotCommandResult] | None = None,
    ) -> None:
        self.config = config
        self.secret = load_gateway_secret(config.secret_file)
        self.state = EdgeState()
        self.watchdog = StateWatchdog(stale_ms=config.stale_ms)
        self.audit = EdgeAudit(config.audit_path)
        self._stop = threading.Event()
        self._producer: threading.Thread | None = None
        self._real = isinstance(config, RealEdgeConfig)
        self._controller_host = config.controller_host if self._real else "127.0.0.1"
        self._command_port = config.command_port if self._real else config.fake_command_port
        self._datasheet_port = config.datasheet_port if self._real else config.fake_datasheet_port
        self._scope = "private-read-only" if self._real else "loopback"
        self._command = CommandClient( #一问一答，10003
            self._controller_host, self._command_port, timeout_s=0.5, scope=self._scope,
        )
        self._controller_operation = threading.Lock()
        self._controller_operation_active = threading.Event()
        installed_handler = command_handler
        if self._real and installed_handler is None:
            installed_handler = self._execute_real_command
        self._cloud = CloudTransport( # mac与服务器连接（通过websocket）
            config.server_url,
            secret=self.secret,
            gateway_id=config.gateway_id,
            command_handler=installed_handler,
        )
        self.robot_model: str | None = None
        self.package_version: str | None = None
        self.device_sn: str | None = None
        self.controller_is_simulation: bool | None = None
        self.robot_status = None
        self.emergency_status = None
    # 10003 连接处
    def _query_identity(self) -> None:
        self._command.connect()
        try:
            version = read_identity_text(self._command.request(ReadCommand.PACKAGE_VERSION))
            if self._real and version not in self.config.approved_package_versions:
                self.state.fault = True
                raise ValueError("PackageVersion is not approved for this real gateway")
            model = read_identity_text(self._command.request(ReadCommand.ROBOT_MODEL))
            if self._real and model != self.config.expected_robot_model:
                self.state.fault = True
                raise ValueError("robot model changed or disagrees with real config")
            simulation = read_is_simulation(self._command.request(ReadCommand.IS_SIMULATION))
            started = read_controller_started(self._command.request(ReadCommand.CONTROLLER_STATE))
            if simulation or not started:
                self.state.fault = True
                raise ValueError("controller did not report a started hardware state")
            if self._real:
                status = read_robot_state(self._command.request(ReadCommand.ROBOT_STATE))
                emergency = read_emergency_info(self._command.request(ReadCommand.EMERGENCY_INFO))
                self.robot_status = status
                self.emergency_status = emergency
                if (
                    status.moving or status.has_error or status.emergency_stop
                    or status.safeguard or not status.controller_box_connected
                    or emergency.emergency_circuit_fault or emergency.safeguard_circuit_fault
                ):
                    self.state.fault = True
                    raise ValueError("real robot or safety status is abnormal; stop commissioning")
            if self.robot_model is not None and self.robot_model != model:
                self.state.fault = True
                raise ValueError("robot model changed after reconnect")
            if self.package_version is not None and self.package_version != version:
                self.state.fault = True
                raise ValueError("package version changed after reconnect")
            self.robot_model = model
            self.package_version = version
            self.controller_is_simulation = simulation
            self.state.command_connected = True
        except Exception:
            self._command.close()
            self.state.command_connected = False
            raise

    def local_telemetry(self) -> RobotTelemetry:
        """Return the newest Mac-side snapshot for remote motion preflight."""
        session_id = self._cloud.session_id
        record, _events = self.state.snapshot()
        if session_id is None or record is None:
            raise RuntimeError("gateway has no active session or DataSheet sample")
        return telemetry_from_sample(
            record,
            session_id=session_id,
            device_sn=self.device_sn or "",
            robot_model=self.robot_model or "",
            package_version=self.package_version or "",
            controller_is_simulation=bool(self.controller_is_simulation),
            command_connected=self.state.command_connected,
            watchdog=self.watchdog,
            robot_status=self.robot_status,
            emergency_status=self.emergency_status,
        )
    # 10004连接处
    def _poll_datasheet(self) -> None:
        while not self._stop.is_set() and not self.state.fault:
            try:
                with DatasheetClient(
                    self._controller_host,
                    self._datasheet_port,
                    byte_order=self.config.datasheet_byte_order,
                    timeout_s=0.25,
                    max_events=256,
                    scope=self._scope,
                ) as reader:
                    source_stamps = (
                        SourceStampWatchdog(stale_ms=self.watchdog.stale_ms)
                        if self._real else None
                    )
                    self.state.datasheet_connected = True
                    while not self._stop.is_set():
                        reader.poll()
                        for sample in reader.last_batch:
                            # device_sn是设备编号，这里主要是检查设备编号是否与配置文件中规定的编号一致，以确保连接的机械臂是对应的。
                            if not sample.device_sn:
                                raise ValueError("DataSheet DeviceSN is missing")
                            if self._real and sample.device_sn != self.config.expected_device_sn:
                                self.state.fault = True
                                raise ValueError("DataSheet DeviceSN disagrees with real config")
                            if self._real and (sample.error_code or any(sample.axis_error_codes)):
                                self.state.fault = True
                                raise ValueError("DataSheet reports a robot or axis error")
                            if source_stamps is not None:
                                try:
                                    source_stamps.observe(sample)
                                except ValueError:
                                    self.state.fault = True
                                    self.audit.record("source_stamp_invalid")
                                    raise
                            if self.device_sn is None:
                                self.device_sn = sample.device_sn
                            elif sample.device_sn != self.device_sn:
                                self.state.fault = True
                                raise ValueError("DataSheet DeviceSN changed")
                            self.state.observe(sample) # 记录当前机械臂最新真实状态
                        reader.drain_events()  # EdgeState owns the bounded alert queue.
            except (OSError, ConnectionError, ValueError, RuntimeError) as exc:
                self.state.datasheet_connected = False
                self.audit.record("datasheet_lost", reason=type(exc).__name__)
                if self.state.fault:
                    break
                self._stop.wait(0.2)

    def start(self) -> None:
        # 启动 10003 连接
        self._query_identity()
        # 10004 为后台线程，主线程是10003 -> websocket -> 服务器
        self._producer = threading.Thread(target=self._poll_datasheet, daemon=True)
        self._producer.start()

    def _check_command_socket(self) -> None:
        if self._controller_operation_active.is_set():
            return
        try:
            if not self.state.command_connected:
                self._query_identity()
            else:
                read_current_fsm(self._command.request(ReadCommand.CURRENT_FSM))
                self.robot_status = read_robot_state(
                    self._command.request(ReadCommand.ROBOT_STATE)
                )
                self.emergency_status = read_emergency_info(
                    self._command.request(ReadCommand.EMERGENCY_INFO)
                )
        except Exception as exc:
            self._command.close()
            self.state.command_connected = False
            self.audit.record("command_socket_lost", reason=type(exc).__name__)

    def _execute_real_command(
        self, envelope: RobotCommandEnvelope, fingerprint: str,
    ) -> RobotCommandResult:
        """Run one server-dispatched command through the Step 11 local client."""
        if not self._real or not isinstance(self.config, RealEdgeConfig):
            return self._failed_result(envelope, ErrorCode.OPERATION_NOT_ENABLED)
        if command_fingerprint(envelope) != fingerprint:
            return self._failed_result(envelope, ErrorCode.COMMAND_CONFLICT)
        if not self._controller_operation.acquire(blocking=False):
            return self._failed_result(envelope, ErrorCode.COMMAND_CONFLICT)
        self._controller_operation_active.set()
        self._command.close()
        try:
            if envelope.command_kind == GatewayCommandKind.SET_ENABLED:
                return self._execute_set_enabled(envelope)
            if envelope.command_kind in {
                GatewayCommandKind.MOVE_RELATIVE,
                GatewayCommandKind.MOVE_TO_ENTRY,
                GatewayCommandKind.MOVE_SEQUENCE,
            }:
                return self._execute_remote_motion(envelope, fingerprint)
            return self._failed_result(envelope, ErrorCode.OPERATION_NOT_ENABLED)
        except Exception as exc:
            self.audit.record(
                "remote_command_failed",
                command_id=envelope.command_id,
                reason=f"{type(exc).__name__}: {exc}"[:256],
            )
            return self._failed_result(envelope, ErrorCode.INTERNAL_ERROR)
        finally:
            self.state.command_connected = False
            try:
                self._query_identity()
            except Exception as exc:
                self.audit.record("command_socket_reconnect_failed", reason=type(exc).__name__)
            # Keep the health-check path excluded until the command owner has
            # either restored its 10003 session or recorded that reconnect
            # failed.  Clearing this flag earlier lets two threads share and
            # corrupt the same request/reply stream.
            self._controller_operation_active.clear()
            self._controller_operation.release()

    @staticmethod
    def _failed_result(
        envelope: RobotCommandEnvelope, error_code: ErrorCode,
    ) -> RobotCommandResult:
        return RobotCommandResult(
            gateway_session_id=envelope.gateway_session_id,
            command_id=envelope.command_id,
            command_kind=envelope.command_kind,
            status=ToolStatus.FAILED,
            error_code=error_code,
        )

    def _sampler(self):
        gateway = self

        class GatewaySampler:
            watchdog = gateway.watchdog

            @staticmethod
            def snapshot():
                record, _events = gateway.state.snapshot()
                if record is None or not gateway.watchdog.is_fresh(record.sample):
                    raise RuntimeError("gateway DataSheet sample is missing or stale")
                return record

        return GatewaySampler()

    def _execute_set_enabled(
        self, envelope: RobotCommandEnvelope,
    ) -> RobotCommandResult:
        from .huayan.adapter import read_robot_state
        from .huayan.models import ReadCommand
        from .huayan.real_motion_client import LocalRealMotionClient

        payload = envelope.payload
        if not isinstance(payload, SetEnabledRequest):
            return self._failed_result(envelope, ErrorCode.INVALID_COMMAND_SCHEMA)
        config = self.config.robot_config
        if config is None:
            return self._failed_result(envelope, ErrorCode.OPERATION_NOT_ENABLED)
        sampler = self._sampler()
        before = sampler.snapshot()
        if not payload.enabled and (before.sample.moving or not before.sample.in_position):
            return self._failed_result(envelope, ErrorCode.OPERATION_NOT_ENABLED)
        timeout_s = config.deadlines.response_ms / 1000
        deadline = time.monotonic() + config.deadlines.startup_ms / 1000
        with LocalRealMotionClient(
            config, timeout_s=timeout_s, require_local_terminal=False,
        ) as client:
            state = read_robot_state(client.request(ReadCommand.ROBOT_STATE))
            if not payload.enabled and state.moving:
                return self._failed_result(envelope, ErrorCode.OPERATION_NOT_ENABLED)
            if state.enabled is not payload.enabled and not client.set_enabled(
                payload.enabled,
                disable_stationary_confirmed=(not state.moving and not before.sample.moving),
            ):
                return self._failed_result(envelope, ErrorCode.INTERNAL_ERROR)
            while time.monotonic() < deadline:
                state = read_robot_state(client.request(ReadCommand.ROBOT_STATE))
                self.robot_status = state
                if state.moving:
                    return self._failed_result(envelope, ErrorCode.OPERATION_NOT_ENABLED)
                if state.enabled is payload.enabled:
                    break
                time.sleep(0.02)
            else:
                return self._failed_result(envelope, ErrorCode.ROBOT_TIMEOUT)
        while time.monotonic() < deadline:
            current = sampler.snapshot()
            if current.sample.moving:
                return self._failed_result(envelope, ErrorCode.OPERATION_NOT_ENABLED)
            if (
                current.sequence > before.sequence
                and current.sample.enabled is payload.enabled
            ):
                return RobotCommandResult(
                    gateway_session_id=envelope.gateway_session_id,
                    command_id=envelope.command_id,
                    command_kind=envelope.command_kind,
                    status=ToolStatus.SUCCESS,
                    confirmed_enabled=payload.enabled,
                )
            time.sleep(0.02)
        return self._failed_result(envelope, ErrorCode.ROBOT_TIMEOUT)

    def _execute_remote_motion(
        self, envelope: RobotCommandEnvelope, fingerprint: str,
    ) -> RobotCommandResult:
        from .command_journal import CommandJournal
        from .commissioning_runtime import (
            make_approval, make_joint_fk, make_path_ik, read_local_observation,
            read_motion_feedback,
        )
        from .fake_motion import LocalMotionTiming, LocalMotionTrial
        from .huayan.adapter import read_current_fsm, read_robot_state
        from .huayan.models import ReadCommand
        from .huayan.real_motion_client import LocalRealMotionClient
        from .remote_motion import RemoteMotionExecutor

        config = self.config.robot_config
        if config is None:
            return self._failed_result(envelope, ErrorCode.OPERATION_NOT_ENABLED)
        sampler = self._sampler()
        timeout_s = config.deadlines.response_ms / 1000
        expected_override = config.motion.controller_override
        before = sampler.snapshot()
        if (
            before.sample.moving or before.sample.fsm_code != 33
            or not before.sample.enabled or not before.sample.in_position
        ):
            return self._failed_result(envelope, ErrorCode.OPERATION_NOT_ENABLED)

        # SetOverride and its two-channel confirmation are completed before a
        # fresh single-use 10003 connection is opened for WayPoint.
        with LocalRealMotionClient(
            config, timeout_s=timeout_s, require_local_terminal=False,
        ) as override_client:
            state = read_robot_state(override_client.request(ReadCommand.ROBOT_STATE))
            fsm = read_current_fsm(override_client.request(ReadCommand.CURRENT_FSM))
            if state.moving or not state.enabled or not state.in_position or fsm != 33:
                return self._failed_result(envelope, ErrorCode.OPERATION_NOT_ENABLED)
            current_override = override_client.current_override()
            if abs(current_override - expected_override) > 1e-6:
                if not override_client.set_override(
                    expected_override, stationary_confirmed=True,
                ):
                    return self._failed_result(envelope, ErrorCode.INTERNAL_ERROR)
            if abs(override_client.current_override() - expected_override) > 1e-6:
                return self._failed_result(envelope, ErrorCode.INTERNAL_ERROR)
        override_deadline = time.monotonic() + config.deadlines.startup_ms / 1000
        while time.monotonic() < override_deadline:
            confirmed = sampler.snapshot()
            if confirmed.sample.moving:
                return self._failed_result(envelope, ErrorCode.OPERATION_NOT_ENABLED)
            if (
                confirmed.sequence > before.sequence
                and abs(confirmed.sample.override - expected_override) <= 1e-6
            ):
                break
            time.sleep(0.02)
        else:
            return self._failed_result(envelope, ErrorCode.ROBOT_TIMEOUT)

        with LocalRealMotionClient(
            config, timeout_s=timeout_s, require_local_terminal=False,
        ) as motion_client:
            observation_holder = {}

            def snapshot():
                observation = read_local_observation(
                    config, motion_client, sampler,
                    session_id=envelope.gateway_session_id,
                )
                observation_holder["value"] = observation
                self.robot_status = read_robot_state(
                    motion_client.request(ReadCommand.ROBOT_STATE)
                )
                return observation.telemetry

            def readback():
                observation = observation_holder.get("value")
                if observation is None:
                    snapshot()
                    observation = observation_holder["value"]
                return observation.readback

            initial = snapshot()
            approval = make_approval(config, package_version=motion_client.package_version)
            make_path_ik(config, initial)
            make_joint_fk(config, initial)
            timing = LocalMotionTiming(
                response_ms=config.deadlines.response_ms,
                start_ms=config.deadlines.startup_ms,
                motion_ms=config.deadlines.motion_ms,
                stop_confirmation_ms=config.deadlines.stop_ack_ms,
                stable_samples=config.arrival.stable_samples,
                dwell_ms=config.arrival.dwell_ms,
                position_tolerance_mm=config.arrival.position_tolerance_mm,
                orientation_tolerance_deg=config.arrival.orientation_tolerance_deg,
            )
            def feedback():
                result = read_motion_feedback(
                    config, motion_client, sampler,
                    session_id=envelope.gateway_session_id,
                )
                return result.telemetry, (
                    f"moving_10003={result.moving_10003}, "
                    f"moving_10004={result.moving_10004}, "
                    f"fsm_10004={result.fsm_10004}"
                )

            with CommandJournal(
                self.config.audit_path.parent / "commands.journal"
            ) as journal:
                executor = RemoteMotionExecutor(
                    trial_factory=lambda: LocalMotionTrial(
                        client=motion_client,
                        journal=journal,
                        timing=timing,
                        approval=approval,
                        path_ik=make_path_ik(
                            config,
                            observation_holder["value"].telemetry,
                        ),
                        joint_fk=make_joint_fk(
                            config,
                            observation_holder["value"].telemetry,
                        ),
                    ),
                    snapshot=snapshot,
                    readback=readback,
                    feedback=feedback,
                    poll_interval_s=0.02,
                )
                return executor.execute(envelope, fingerprint)

    def _wait_for_identity(self) -> None:
        deadline = time.monotonic() + 3
        while self.device_sn is None and time.monotonic() < deadline:
            if self.state.fault:
                raise RuntimeError("edge state fault before first DataSheet frame")
            time.sleep(0.02)
        if self.device_sn is None:
            raise RuntimeError("fake DataSheet did not provide DeviceSN")

    def run(self, *, max_runtime_s: float | None = None) -> None:
        try:
            self.start() # 连接 10003 与 10004
            self._wait_for_identity()
            started_at = time.monotonic()
            last_command_check = 0.0
            while not self._stop.is_set() and not self.state.fault:
                if max_runtime_s is not None and time.monotonic() - started_at >= max_runtime_s:
                    break
                if time.monotonic() - last_command_check >= 1.0:
                    self._check_command_socket()
                    last_command_check = time.monotonic()
                try:
                    # 连接服务器
                    session_id = self._cloud.connect(
                        device_sn=self.device_sn or "",
                        robot_model=self.robot_model or "",
                        package_version=self.package_version or "",
                    )
                    self.state.start_cloud_session(session_id)
                    self.audit.record("cloud_connected", session_id=session_id, gateway_id=self.config.gateway_id)
                    last_sent = 0
                    last_heartbeat = 0.0
                    while not self._stop.is_set() and not self.state.fault:
                        if max_runtime_s is not None and time.monotonic() - started_at >= max_runtime_s:
                            break
                        if time.monotonic() - last_command_check >= 1.0:
                            self._check_command_socket()
                            last_command_check = time.monotonic()
                        latest, events = self.state.snapshot()
                        candidates = list(events)
                        if latest is not None and (not candidates or latest.sequence > candidates[-1].sequence):
                            candidates.append(latest)
                        sent = False
                        for record in candidates:
                            if record.sequence <= last_sent:
                                continue
                            if not self.watchdog.is_fresh(record.sample):
                                self.audit.record("stale_sample_not_uploaded", sequence=record.sequence)
                                self.state.acknowledged_through(record.sequence)
                                last_sent = record.sequence
                                continue
                            # 将 DatasheetSample -> RobotTelemetry
                            telemetry = telemetry_from_sample(
                                record,
                                session_id=session_id,
                                device_sn=self.device_sn or "",
                                robot_model=self.robot_model or "",
                                package_version=self.package_version or "",
                                controller_is_simulation=bool(self.controller_is_simulation),
                                command_connected=self.state.command_connected,
                                watchdog=self.watchdog,
                                robot_status=self.robot_status,
                                emergency_status=self.emergency_status,
                            )
                            self._cloud.send_state(telemetry)
                            self.state.acknowledged_through(record.sequence)
                            last_sent = record.sequence
                            sent = True
                        if not sent and time.monotonic() - last_heartbeat >= 0.3:
                            # heartbeat 不是完整机器人数据，只是说机械臂没有新状态发送过来了。
                            self._cloud.send_heartbeat(
                                datasheet=(LinkState.CONNECTED if self.state.datasheet_connected else LinkState.DISCONNECTED),
                                command_socket=(LinkState.CONNECTED if self.state.command_connected else LinkState.DISCONNECTED),
                            )
                            last_heartbeat = time.monotonic()
                        self._stop.wait(0.01)
                except Exception as exc:
                    self.audit.record("cloud_lost", reason=type(exc).__name__)
                    self._stop.wait(0.5)
                finally:
                    self._cloud.close()
                    self.state.cloud_lost()
        finally:
            self.close()

    def close(self) -> None:
        self._stop.set()
        self._cloud.close()
        self._command.close()
        if self._producer is not None:
            self._producer.join(timeout=1)
        self.audit.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Authenticated Mac robot gateway")
    parser.add_argument("--fake-command-port", type=int)
    parser.add_argument("--fake-datasheet-port", type=int)
    parser.add_argument("--real-config", type=Path)
    parser.add_argument("--connect-real", action="store_true")
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--secret-file", type=Path, required=True)
    parser.add_argument("--gateway-id", required=True)
    parser.add_argument("--datasheet-byte-order", choices=("little", "big"), required=True)
    parser.add_argument("--audit-path", type=Path, default=Path("logs/edge_gateway.log"))
    args = parser.parse_args()
    if args.real_config is not None:
        if args.fake_command_port is not None or args.fake_datasheet_port is not None:
            parser.error("real mode cannot accept fake controller ports")
        if not args.connect_real:
            parser.error("real gateway requires --connect-real")
        from robot_runtime.real_config import load_real_config

        from .huayan.real_probe import validate_probe_config

        real = load_real_config(args.real_config)
        validate_probe_config(real)
        config = RealEdgeConfig(
            robot_config=real,
            controller_host=real.controller.host,
            command_port=real.controller.command_port,
            datasheet_port=real.controller.datasheet_port,
            expected_device_sn=real.controller.device_sn,
            expected_robot_model=real.controller.model,
            approved_package_versions=tuple(real.controller.package_versions),
            server_url=args.server_url,
            secret_file=args.secret_file,
            gateway_id=args.gateway_id,
            datasheet_byte_order=args.datasheet_byte_order,
            audit_path=args.audit_path,
            stale_ms=real.deadlines.state_stale_ms,
        )
    else:
        if args.connect_real:
            parser.error("real-only options require --real-config")
        if args.fake_command_port is None or args.fake_datasheet_port is None:
            parser.error("fake mode requires both fake ports")
        config = EdgeConfig(
            fake_command_port=args.fake_command_port,
            fake_datasheet_port=args.fake_datasheet_port,
            server_url=args.server_url,
            secret_file=args.secret_file,
            gateway_id=args.gateway_id,
            datasheet_byte_order=args.datasheet_byte_order,
            audit_path=args.audit_path,
        )
    gateway = EdgeGateway(config)
    try:
        gateway.run()
    except KeyboardInterrupt:
        gateway.close()


if __name__ == "__main__":
    main()
