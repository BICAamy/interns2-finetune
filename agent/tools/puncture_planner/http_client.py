"""HTTP client for the Step 9 planner-adapter service."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import ValidationError

from surgical_contracts import (
    ErrorCode,
    ErrorResponse,
    PlannerHealth,
    PlannerStatus,
    PlanPunctureRequest,
    PlanPunctureResult,
)


class PlannerAdapterClientError(RuntimeError):
    def __init__(self, error_code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class PlannerAdapterUnavailableError(ConnectionError):
    error_code = ErrorCode.PLANNER_UNAVAILABLE


class PlannerAdapterTimeoutError(TimeoutError):
    error_code = ErrorCode.PLANNER_TIMEOUT


class PlannerAdapterProtocolError(PlannerAdapterClientError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.INVALID_PLANNER_OUTPUT, message)


class PlannerAdapterHTTPClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 15.0,
        client: Any | None = None,
    ) -> None:
        normalized = base_url.rstrip("/")
        if not normalized:
            raise ValueError("planner-adapter base_url cannot be empty")
        if timeout_s <= 0:
            raise ValueError("planner-adapter timeout must be greater than zero")
        self.base_url = normalized
        self.timeout_s = float(timeout_s)
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout_s,
            headers={"Accept": "application/json"},
            trust_env=False,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "PlannerAdapterHTTPClient":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def health(self) -> PlannerHealth:
        payload, _status_code = self._request_json("GET", "/health")
        try:
            health = PlannerHealth.model_validate(payload)
        except ValidationError as exc:
            raise PlannerAdapterProtocolError(
                "planner-adapter health response failed validation"
            ) from exc
        if not health.ready:
            raise PlannerAdapterUnavailableError(health.message)
        return health

    def plan(self, request: PlanPunctureRequest) -> PlanPunctureResult:
        payload, status_code = self._request_json(
            "POST",
            "/v1/plan",
            json=request.model_dump(mode="json"),
            allowed_error_statuses={503},
        )
        try:
            result = PlanPunctureResult.model_validate(payload)
        except ValidationError as exc:
            raise PlannerAdapterProtocolError(
                "planner-adapter planning response failed validation"
            ) from exc
        if result.request_id != request.request_id:
            raise PlannerAdapterProtocolError(
                "planner-adapter returned a mismatched request_id"
            )
        if status_code == 503 and result.status != PlannerStatus.UNAVAILABLE:
            raise PlannerAdapterProtocolError(
                "planner-adapter HTTP 503 did not contain unavailable status"
            )
        return result

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        allowed_error_statuses: set[int] | None = None,
        **kwargs,
    ) -> tuple[dict[str, Any], int]:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise PlannerAdapterTimeoutError(
                f"planner-adapter request timed out: {path}"
            ) from exc
        except httpx.RequestError as exc:
            raise PlannerAdapterUnavailableError(
                f"cannot reach planner-adapter at {self.base_url}"
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise PlannerAdapterProtocolError(
                f"planner-adapter returned non-JSON data for {path}"
            ) from exc
        allowed = allowed_error_statuses or set()
        if response.status_code >= 400 and response.status_code not in allowed:
            if response.status_code >= 500:
                raise PlannerAdapterUnavailableError(
                    f"planner-adapter returned HTTP {response.status_code}"
                )
            try:
                error = ErrorResponse.model_validate(payload)
            except ValidationError as exc:
                raise PlannerAdapterProtocolError(
                    f"planner-adapter HTTP {response.status_code} has an invalid error envelope"
                ) from exc
            raise PlannerAdapterClientError(error.code, error.message)
        if not isinstance(payload, dict):
            raise PlannerAdapterProtocolError(
                f"planner-adapter returned a non-object JSON response for {path}"
            )
        return payload, response.status_code
