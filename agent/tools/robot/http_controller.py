"""HTTP RobotController backed by the provider-neutral port-8001 service."""

from __future__ import annotations

import time
from typing import Any, Callable
from uuid import uuid4

import httpx
from pydantic import ValidationError

from surgical_contracts import (
    CommandExecutionStatus,
    ErrorCode,
    ErrorResponse,
    MotionState,
    MoveRelativeRequest,
    MoveRelativeResult,
    MoveSequenceRequest,
    MoveSequenceResult,
    MoveToEntryRequest,
    MoveToEntryResult,
    ResetSimulationRequest,
    RobotActionRequest,
    RobotActionResult,
    RobotCommandKind,
    RobotCommandRecord,
    RobotHealth,
    RobotState,
    RobotTelemetry,
    SetEnabledRequest,
    SetEnabledResult,
    Point3D,
    CoordinateSource,
    SimulationHealth,
    SimulationTelemetry,
    ToolStatus,
)


_TERMINAL = {
    CommandExecutionStatus.SUCCEEDED,
    CommandExecutionStatus.FAILED,
    CommandExecutionStatus.REJECTED,
    CommandExecutionStatus.CANCELLED,
}


class RobotSimulationClientError(RuntimeError):
    def __init__(self, error_code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class RobotSimulationUnavailableError(ConnectionError):
    error_code = ErrorCode.INTERNAL_ERROR


class RobotSimulationTimeoutError(TimeoutError):
    error_code = ErrorCode.ROBOT_TIMEOUT


class RobotSimulationProtocolError(RobotSimulationClientError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.INTERNAL_ERROR, message)


class RobotRuntimeHTTPController:
    """Translate synchronous high-level tool calls to the queued HTTP API."""

    def __init__(
        self,
        base_url: str,
        *,
        http_timeout_s: float = 10.0,
        command_timeout_s: float = 120.0,
        poll_interval_s: float = 0.05,
        client: Any | None = None,
        command_id_factory: Callable[[], str] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        normalized = base_url.rstrip("/")
        if not normalized:
            raise ValueError("robot-simulation base_url cannot be empty")
        if http_timeout_s <= 0 or command_timeout_s <= 0:
            raise ValueError("robot-simulation timeouts must be greater than zero")
        if poll_interval_s <= 0:
            raise ValueError("robot-simulation poll interval must be greater than zero")
        self.base_url = normalized
        self.http_timeout_s = float(http_timeout_s)
        self.command_timeout_s = float(command_timeout_s)
        self.poll_interval_s = float(poll_interval_s)
        self._clock = clock
        self._sleep = sleeper
        self._command_id_factory = command_id_factory or (
            lambda: f"robot-action-{uuid4().hex}"
        )
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self.base_url,
            timeout=self.http_timeout_s,
            headers={"Accept": "application/json"},
            trust_env=False,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "RobotRuntimeHTTPController":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def get_runtime_health(self) -> SimulationHealth | RobotHealth:
        payload = self._request_json("GET", "/health")
        model = RobotHealth if "runtime_mode" in payload else SimulationHealth
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise RobotSimulationProtocolError("/health response failed validation") from exc

    def health(self) -> SimulationHealth | RobotHealth:
        health = self.get_runtime_health()
        if isinstance(health, RobotHealth):
            if not health.ready_for_motion:
                raise RobotSimulationUnavailableError(
                    f"robot runtime is not ready for motion: {health.error or health.status}"
                )
            return health
        if not health.ready:
            raise RobotSimulationUnavailableError(
                f"robot-simulation is not ready: {health.status} {health.error or ''}".strip()
            )
        return health

    def get_telemetry(self) -> SimulationTelemetry | RobotTelemetry:
        payload = self._request_json("GET", "/v1/state")
        model = SimulationTelemetry if "state" in payload else RobotTelemetry
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise RobotSimulationProtocolError("/v1/state response failed validation") from exc

    def get_state(self) -> RobotState:
        telemetry = self.get_telemetry()
        if isinstance(telemetry, RobotTelemetry):
            pose = telemetry.actual_pose_robot_base
            if pose is None:
                raise RobotSimulationUnavailableError("real robot actual Base pose is unavailable")
            return RobotState(
                mode=telemetry.runtime_mode,
                tcp=telemetry.validated_tcp_name or "TCP",
                tcp_position=Point3D(
                    x=pose.translation_mm[0],
                    y=pose.translation_mm[1],
                    z=pose.translation_mm[2],
                    frame=pose.frame,
                    unit=pose.unit,
                    source=CoordinateSource.STRUCTURED_DATA,
                ),
                orientation_xyzw=pose.quaternion_xyzw,
                motion_state=telemetry.motion_state or MotionState.IDLE,
                estop=telemetry.physical_estop_active is True,
                active_command_id=telemetry.active_command_id,
            )
        return telemetry.state

    def create_move_relative_proposal(
        self, request: MoveRelativeRequest,
    ) -> RobotCommandRecord:
        record = self._model_request(
            "POST",
            "/v1/commands/move-relative",
            RobotCommandRecord,
            json=request.model_dump(mode="json"),
        )
        self._validate_record(record, request.command_id, RobotCommandKind.MOVE_RELATIVE)
        return record

    def create_move_to_entry_proposal(
        self, request: MoveToEntryRequest,
    ) -> RobotCommandRecord:
        record = self._model_request(
            "POST",
            "/v1/commands/move-to-entry",
            RobotCommandRecord,
            json=request.model_dump(mode="json"),
        )
        self._validate_record(record, request.command_id, RobotCommandKind.MOVE_TO_ENTRY)
        return record

    def create_move_sequence_proposal(
        self, request: MoveSequenceRequest,
    ) -> RobotCommandRecord:
        record = self._model_request(
            "POST",
            "/v1/commands/move-sequence",
            RobotCommandRecord,
            json=request.model_dump(mode="json"),
        )
        self._validate_record(record, request.command_id, RobotCommandKind.MOVE_SEQUENCE)
        return record

    def confirm_motion_proposal(
        self,
        command_id: str,
        fingerprint: str,
        expected_kind: RobotCommandKind | None = None,
    ) -> RobotCommandRecord:
        record = self._model_request(
            "POST",
            f"/v1/commands/{command_id}/confirm",
            RobotCommandRecord,
            json={"fingerprint": fingerprint},
        )
        if expected_kind is None:
            if record.command_id != command_id or record.kind not in {
                RobotCommandKind.MOVE_RELATIVE,
                RobotCommandKind.MOVE_TO_ENTRY,
                RobotCommandKind.MOVE_SEQUENCE,
            }:
                raise RobotSimulationProtocolError(
                    "confirmation response is not a motion command"
                )
        else:
            self._validate_record(record, command_id, expected_kind)
        return record

    def set_enabled(
        self, enabled: bool, command_id: str | None = None,
    ) -> SetEnabledResult:
        request = SetEnabledRequest(
            command_id=command_id or self._command_id_factory(),
            enabled=enabled,
        )
        record = self._submit_and_wait(
            "/v1/commands/set-enabled",
            RobotCommandKind.SET_ENABLED,
            request,
        )
        if record.status != CommandExecutionStatus.SUCCEEDED:
            error_code, message, _status = self._record_failure(record)
            raise RobotSimulationClientError(error_code, message)
        return self._result_model(record, SetEnabledResult)

    def move_to_entry(self, request: MoveToEntryRequest) -> MoveToEntryResult:
        record = self._submit_and_wait(
            "/v1/commands/move-to-entry",
            RobotCommandKind.MOVE_TO_ENTRY,
            request,
        )
        if record.status == CommandExecutionStatus.SUCCEEDED:
            return self._result_model(record, MoveToEntryResult)
        self._reject_unavailable_real_command(record)
        state = self.get_state()
        error_code, message, status = self._record_failure(record)
        position_error = None
        if state.tcp_position.frame == request.entry_point.frame:
            position_error = state.tcp_position.distance_to(request.entry_point)
        return MoveToEntryResult(
            command_id=request.command_id,
            status=status,
            reached=False,
            final_tcp_position=state.tcp_position,
            position_error_mm=position_error,
            message=message,
            error_code=error_code,
        )

    def move_relative(self, request: MoveRelativeRequest) -> MoveRelativeResult:
        record = self._submit_and_wait(
            "/v1/commands/move-relative",
            RobotCommandKind.MOVE_RELATIVE,
            request,
        )
        if record.status == CommandExecutionStatus.SUCCEEDED:
            return self._result_model(record, MoveRelativeResult)
        self._reject_unavailable_real_command(record)
        state = self.get_state()
        error_code, message, status = self._record_failure(record)
        return MoveRelativeResult(
            command_id=request.command_id,
            status=status,
            completed=False,
            final_tcp_position=state.tcp_position,
            message=message,
            error_code=error_code,
        )

    def move_sequence(self, request: MoveSequenceRequest) -> MoveSequenceResult:
        record = self._submit_and_wait(
            "/v1/commands/move-sequence",
            RobotCommandKind.MOVE_SEQUENCE,
            request,
        )
        if record.status == CommandExecutionStatus.SUCCEEDED:
            return self._result_model(record, MoveSequenceResult)
        self._reject_unavailable_real_command(record)
        state = self.get_state()
        telemetry = self.get_telemetry()
        joints = getattr(telemetry, "joint_positions_deg", None) or (
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        )
        error_code, message, status = self._record_failure(record)
        return MoveSequenceResult(
            command_id=request.command_id,
            status=status,
            completed=False,
            completed_steps=0,
            total_steps=len(request.steps),
            final_tcp_position=state.tcp_position,
            final_joint_positions_deg=joints,
            message=message,
            error_code=error_code,
        )

    def stop(self, command_id: str | None = None) -> RobotState:
        return self._action(
            "/v1/commands/stop",
            RobotCommandKind.STOP,
            command_id or self._command_id_factory(),
        )

    def emergency_stop(self, command_id: str | None = None) -> RobotState:
        return self._action(
            "/v1/commands/estop",
            RobotCommandKind.ESTOP,
            command_id or self._command_id_factory(),
        )

    def reset_estop(self, command_id: str | None = None) -> RobotState:
        action_id = command_id or self._command_id_factory()
        request = ResetSimulationRequest(command_id=action_id)
        record = self._submit_and_wait(
            "/v1/reset",
            RobotCommandKind.RESET,
            request,
        )
        return self._action_state(record, RobotCommandKind.RESET)

    def _action(
        self,
        path: str,
        kind: RobotCommandKind,
        command_id: str,
    ) -> RobotState:
        request = RobotActionRequest(command_id=command_id)
        record = self._submit_and_wait(path, kind, request)
        return self._action_state(record, kind)

    def _action_state(
        self,
        record: RobotCommandRecord,
        kind: RobotCommandKind,
    ) -> RobotState:
        if record.status != CommandExecutionStatus.SUCCEEDED:
            error_code, message, _status = self._record_failure(record)
            raise RobotSimulationClientError(error_code, message)
        result = self._result_model(record, RobotActionResult)
        if result.operation != kind:
            raise RobotSimulationProtocolError(
                f"robot action kind mismatch: expected {kind.value}, got {result.operation.value}"
            )
        if result.status != ToolStatus.SUCCESS:
            code = result.error.code if result.error else ErrorCode.INTERNAL_ERROR
            raise RobotSimulationClientError(code, result.message)
        return result.state

    def _submit_and_wait(
        self,
        path: str,
        kind: RobotCommandKind,
        request: Any,
    ) -> RobotCommandRecord:
        record = self._model_request(
            "POST",
            path,
            RobotCommandRecord,
            json=request.model_dump(mode="json"),
        )
        self._validate_record(record, request.command_id, kind)
        deadline = self._clock() + self.command_timeout_s
        while record.status not in _TERMINAL:
            if self._clock() >= deadline:
                self._submit_timeout_stop(request.command_id)
                raise RobotSimulationTimeoutError(
                    f"robot command {request.command_id} exceeded "
                    f"{self.command_timeout_s:.3f}s"
                )
            self._sleep(self.poll_interval_s)
            record = self._model_request(
                "GET",
                f"/v1/commands/{request.command_id}",
                RobotCommandRecord,
            )
            self._validate_record(record, request.command_id, kind)
        return record

    def _submit_timeout_stop(self, timed_out_command_id: str) -> None:
        suffix = timed_out_command_id[-32:]
        stop_id = f"timeout-stop-{suffix}-{uuid4().hex[:12]}"[:128]
        try:
            self._request_json(
                "POST",
                "/v1/commands/stop",
                json=RobotActionRequest(command_id=stop_id).model_dump(mode="json"),
            )
        except Exception:
            # Preserve the original timeout even if the best-effort stop fails.
            pass

    @staticmethod
    def _validate_record(
        record: RobotCommandRecord,
        command_id: str,
        kind: RobotCommandKind,
    ) -> None:
        if record.command_id != command_id or record.kind != kind:
            raise RobotSimulationProtocolError(
                "robot-simulation returned a command record for another request"
            )

    @staticmethod
    def _result_model(record: RobotCommandRecord, model_type: Any):
        if record.result is None:
            raise RobotSimulationProtocolError(
                f"successful robot command {record.command_id} has no result"
            )
        try:
            return model_type.model_validate(record.result)
        except ValidationError as exc:
            raise RobotSimulationProtocolError(
                f"robot result failed {model_type.__name__} validation"
            ) from exc

    @staticmethod
    def _record_failure(
        record: RobotCommandRecord,
    ) -> tuple[ErrorCode, str, ToolStatus]:
        error = record.error
        code = error.code if error else ErrorCode.INTERNAL_ERROR
        message = error.message if error else f"robot command ended as {record.status.value}"
        status = (
            ToolStatus.FAILED
            if record.status == CommandExecutionStatus.FAILED
            else ToolStatus.REJECTED
        )
        return code, message, status

    @staticmethod
    def _reject_unavailable_real_command(record: RobotCommandRecord) -> None:
        if record.error and record.error.code == ErrorCode.OPERATION_NOT_ENABLED:
            raise RobotSimulationClientError(record.error.code, record.error.message)

    def _model_request(self, method: str, path: str, model_type: Any, **kwargs):
        payload = self._request_json(method, path, **kwargs)
        try:
            return model_type.model_validate(payload)
        except ValidationError as exc:
            raise RobotSimulationProtocolError(
                f"{path} response failed {model_type.__name__} validation"
            ) from exc

    def _request_json(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise RobotSimulationTimeoutError(
                f"robot-simulation request timed out: {path}"
            ) from exc
        except httpx.RequestError as exc:
            raise RobotSimulationUnavailableError(
                f"cannot reach robot-simulation at {self.base_url}"
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise RobotSimulationProtocolError(
                f"robot-simulation returned non-JSON data for {path}"
            ) from exc
        if response.status_code >= 400:
            try:
                error = ErrorResponse.model_validate(payload)
            except ValidationError as exc:
                raise RobotSimulationProtocolError(
                    f"robot-simulation HTTP {response.status_code} has an invalid error envelope"
                ) from exc
            raise RobotSimulationClientError(error.code, error.message)
        if not isinstance(payload, dict):
            raise RobotSimulationProtocolError(
                f"robot-simulation returned a non-object JSON response for {path}"
            )
        return payload


# Existing callers and tests keep the old name until the service-mode wiring in Step 3.
RobotSimulationHTTPController = RobotRuntimeHTTPController
RobotRuntimeClientError = RobotSimulationClientError
RobotRuntimeUnavailableError = RobotSimulationUnavailableError
RobotRuntimeTimeoutError = RobotSimulationTimeoutError
RobotRuntimeProtocolError = RobotSimulationProtocolError
