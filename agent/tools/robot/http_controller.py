"""HTTP RobotController backed by the Step 6 robot-simulation service."""

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
    MoveRelativeRequest,
    MoveRelativeResult,
    MoveToEntryRequest,
    MoveToEntryResult,
    ResetSimulationRequest,
    RobotActionRequest,
    RobotActionResult,
    RobotCommandKind,
    RobotCommandRecord,
    RobotState,
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


class RobotSimulationHTTPController:
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

    def __enter__(self) -> "RobotSimulationHTTPController":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def health(self) -> SimulationHealth:
        health = self._model_request("GET", "/health", SimulationHealth)
        if not health.ready:
            raise RobotSimulationUnavailableError(
                f"robot-simulation is not ready: {health.status} {health.error or ''}".strip()
            )
        return health

    def get_state(self) -> RobotState:
        telemetry = self._model_request("GET", "/v1/state", SimulationTelemetry)
        return telemetry.state

    def move_to_entry(self, request: MoveToEntryRequest) -> MoveToEntryResult:
        record = self._submit_and_wait(
            "/v1/commands/move-to-entry",
            RobotCommandKind.MOVE_TO_ENTRY,
            request,
        )
        if record.status == CommandExecutionStatus.SUCCEEDED:
            return self._result_model(record, MoveToEntryResult)
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
