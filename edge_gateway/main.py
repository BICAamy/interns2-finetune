"""Mac observe-only edge process; never contains a motion command path."""

from __future__ import annotations

import argparse
from pathlib import Path
import threading
import time

from surgical_contracts import LinkState, load_gateway_secret

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
    def __init__(self, config: EdgeConfig | RealEdgeConfig) -> None:
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
        self._command = CommandClient(
            self._controller_host, self._command_port, timeout_s=0.5, scope=self._scope,
        )
        self._cloud = CloudTransport(
            config.server_url,
            secret=self.secret,
            gateway_id=config.gateway_id,
            config_sha256=config.config_sha256,
        )
        self.robot_model: str | None = None
        self.package_version: str | None = None
        self.device_sn: str | None = None
        self.controller_is_simulation: bool | None = None
        self.robot_status = None
        self.emergency_status = None

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
                            self.state.observe(sample)
                        reader.drain_events()  # EdgeState owns the bounded alert queue.
            except (OSError, ConnectionError, ValueError, RuntimeError) as exc:
                self.state.datasheet_connected = False
                self.audit.record("datasheet_lost", reason=type(exc).__name__)
                if self.state.fault:
                    break
                self._stop.wait(0.2)

    def start(self) -> None:
        self._query_identity()
        self._producer = threading.Thread(target=self._poll_datasheet, daemon=True)
        self._producer.start()

    def _check_command_socket(self) -> None:
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
            self.start()
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
    parser = argparse.ArgumentParser(description="Observe-only Mac edge gateway")
    parser.add_argument("--fake-command-port", type=int)
    parser.add_argument("--fake-datasheet-port", type=int)
    parser.add_argument("--real-config", type=Path)
    parser.add_argument("--probe-summary", type=Path)
    parser.add_argument("--connect-real-read-only", action="store_true")
    parser.add_argument("--vendor-compatibility-confirmed", action="store_true")
    parser.add_argument("--operator-ready", action="store_true")
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--secret-file", type=Path, required=True)
    parser.add_argument("--gateway-id", required=True)
    parser.add_argument("--config-sha256")
    parser.add_argument("--datasheet-byte-order", choices=("little", "big"), required=True)
    parser.add_argument("--audit-path", type=Path, default=Path("logs/edge_gateway.log"))
    args = parser.parse_args()
    if args.real_config is not None:
        if args.fake_command_port is not None or args.fake_datasheet_port is not None:
            parser.error("real mode cannot accept fake controller ports")
        if not args.connect_real_read_only or not args.vendor_compatibility_confirmed or not args.operator_ready:
            parser.error("real gateway requires explicit read-only, vendor and operator confirmation")
        from robot_runtime.real_config import load_real_config

        from .huayan.real_probe import validate_probe_config, validate_probe_summary

        real = load_real_config(args.real_config)
        validate_probe_config(real)
        if args.probe_summary is None:
            parser.error("real gateway requires a recent successful --probe-summary")
        validate_probe_summary(args.probe_summary, real, byte_order=args.datasheet_byte_order)
        digest = real.digest()
        if args.config_sha256 is not None and args.config_sha256 != digest:
            parser.error("supplied config digest does not match the real config")
        config = RealEdgeConfig(
            controller_host=real.controller.host,
            command_port=real.controller.command_port,
            datasheet_port=real.controller.datasheet_port,
            expected_device_sn=real.controller.device_sn,
            expected_robot_model=real.controller.model,
            approved_package_versions=tuple(real.controller.package_versions),
            server_url=args.server_url,
            secret_file=args.secret_file,
            gateway_id=args.gateway_id,
            config_sha256=digest,
            datasheet_byte_order=args.datasheet_byte_order,
            audit_path=args.audit_path,
            stale_ms=real.deadlines.state_stale_ms,
        )
    else:
        if args.connect_real_read_only or args.vendor_compatibility_confirmed or args.operator_ready or args.probe_summary:
            parser.error("real confirmation flags require --real-config")
        if args.fake_command_port is None or args.fake_datasheet_port is None or args.config_sha256 is None:
            parser.error("fake mode requires both fake ports and --config-sha256")
        config = EdgeConfig(
            fake_command_port=args.fake_command_port,
            fake_datasheet_port=args.fake_datasheet_port,
            server_url=args.server_url,
            secret_file=args.secret_file,
            gateway_id=args.gateway_id,
            config_sha256=args.config_sha256,
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
