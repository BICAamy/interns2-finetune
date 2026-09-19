"""Provider-neutral telemetry, MJPEG, mirror status and camera proxy."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Callable, Protocol

import httpx
from pydantic import ValidationError

from surgical_contracts import (
    RobotHealth,
    RobotTelemetry,
    SimulationCameraControlRequest,
    SimulationCameraState,
    SimulationHealth,
    SimulationTelemetry,
)


class RobotProxyError(ConnectionError):
    """Stable agent-web boundary for robot observability failures."""


class MJPEGStream(Protocol):
    content_type: str

    def iter_bytes(self) -> AsyncIterator[bytes]: ...
    async def aclose(self) -> None: ...


class _HTTPXMJPEGStream:
    def __init__(self, client: httpx.AsyncClient, response: httpx.Response, content_type: str) -> None:
        self._client = client
        self._response = response
        self.content_type = content_type
        self._closed = False

    async def iter_bytes(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self._response.aiter_raw():
                if chunk:
                    yield chunk
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._response.aclose()
        await self._client.aclose()


class RobotObserver(Protocol):
    def get_health(self) -> SimulationHealth | RobotHealth: ...
    def get_telemetry(self) -> SimulationTelemetry | RobotTelemetry: ...
    def get_mirror_status(self) -> dict[str, Any] | None: ...
    def get_camera_state(self) -> SimulationCameraState: ...
    def control_camera(self, request: SimulationCameraControlRequest) -> SimulationCameraState: ...
    async def open_mjpeg(self) -> MJPEGStream: ...
    def close(self) -> None: ...


class RobotObservabilityHTTPClient:
    """Read provider-neutral state and visualization; exposes no robot commands."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 2.0,
        video_connect_timeout_s: float = 5.0,
        client: Any | None = None,
        async_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        normalized = base_url.rstrip("/")
        if not normalized:
            raise ValueError("robot runtime base URL cannot be empty")
        if timeout_s <= 0 or video_connect_timeout_s <= 0:
            raise ValueError("robot proxy timeouts must be greater than zero")
        self.base_url = normalized
        self.timeout_s = float(timeout_s)
        self.video_connect_timeout_s = float(video_connect_timeout_s)
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout_s,
            headers={"Accept": "application/json"},
            trust_env=False,
        )
        self._async_client_factory = async_client_factory

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _get_json(self, path: str) -> Any:
        response = self._client.get(path)
        response.raise_for_status()
        return response.json()

    def get_health(self) -> SimulationHealth | RobotHealth:
        try:
            payload = self._get_json("/health")
            if payload.get("runtime_mode") == "real":
                return RobotHealth.model_validate(payload)
            return SimulationHealth.model_validate(payload)
        except (httpx.HTTPError, ValueError, ValidationError, AttributeError) as error:
            raise RobotProxyError("无法读取 robot-runtime 健康状态") from error

    def get_telemetry(self) -> SimulationTelemetry | RobotTelemetry:
        try:
            payload = self._get_json("/v1/state")
            if payload.get("runtime_mode") == "real":
                return RobotTelemetry.model_validate(payload)
            return SimulationTelemetry.model_validate(payload)
        except (httpx.HTTPError, ValueError, ValidationError, AttributeError) as error:
            raise RobotProxyError("无法读取 robot-runtime 遥测") from error

    def get_mirror_status(self) -> dict[str, Any] | None:
        try:
            payload = self._get_json("/v1/mirror")
            if not isinstance(payload, dict):
                raise ValueError("mirror status must be an object")
            return payload
        except (httpx.HTTPError, ValueError, ValidationError) as error:
            raise RobotProxyError("无法读取真实机械臂镜像状态") from error

    def get_camera_state(self) -> SimulationCameraState:
        try:
            return SimulationCameraState.model_validate(self._get_json("/v1/camera"))
        except (httpx.HTTPError, ValueError, ValidationError) as error:
            raise RobotProxyError("无法读取 robot-runtime 相机状态") from error

    def control_camera(self, request: SimulationCameraControlRequest) -> SimulationCameraState:
        try:
            response = self._client.put("/v1/camera", json=request.model_dump(mode="json"))
            response.raise_for_status()
            return SimulationCameraState.model_validate(response.json())
        except (httpx.HTTPError, ValueError, ValidationError) as error:
            raise RobotProxyError("无法更新 robot-runtime 相机") from error

    async def open_mjpeg(self) -> MJPEGStream:
        client = self._async_client_factory() if self._async_client_factory is not None else httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(
                connect=self.video_connect_timeout_s,
                read=None,
                write=self.timeout_s,
                pool=self.timeout_s,
            ),
            headers={"Accept": "multipart/x-mixed-replace"},
            trust_env=False,
        )
        try:
            request = client.build_request("GET", "/v1/stream.mjpeg")
            response = await client.send(request, stream=True)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if not content_type.lower().startswith("multipart/x-mixed-replace"):
                raise RobotProxyError("robot-runtime 返回了无效的 MJPEG Content-Type")
            return _HTTPXMJPEGStream(client, response, content_type)
        except Exception as error:
            await client.aclose()
            if isinstance(error, RobotProxyError):
                raise
            raise RobotProxyError("无法连接 robot-runtime 视频流") from error
