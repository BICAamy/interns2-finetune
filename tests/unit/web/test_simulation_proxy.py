from __future__ import annotations

import asyncio

import httpx
import pytest

from agent.tools.robot import FakeRobotController
from surgical_contracts import (
    SimulationCameraControlRequest,
    SimulationCameraState,
    SimulationTelemetry,
)
from web.backend.simulation_proxy import (
    RobotSimulationObservabilityHTTPClient,
    SimulationProxyError,
)


class OneChunkAsyncStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes) -> None:
        self.content = content

    async def __aiter__(self):
        yield self.content


def telemetry_payload() -> dict:
    telemetry = SimulationTelemetry(
        state=FakeRobotController().get_state(),
        sequence=7,
        joint_positions_deg=(0.0, 1.0, 2.0, 3.0, 4.0, 5.0),
        trajectory_mm=[(0.0, 0.0, 100.0), (1.0, 2.0, 103.0)],
        frame_sequence=4,
        updated_at_ms=12345,
    )
    return telemetry.model_dump(mode="json")


def camera_payload() -> dict:
    return SimulationCameraState(
        preset="front",
        yaw_deg=0.0,
        pitch_deg=0.0,
        distance_m=1.65,
        target_m=(0.35, 0.0, 0.42),
        position_m=(0.35, -1.65, 0.42),
        updated_at_ms=12345,
    ).model_dump(mode="json")


def test_observability_client_validates_telemetry_and_preserves_v1_prefix():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=telemetry_payload())

    http = httpx.Client(
        base_url="http://simulation.test",
        transport=httpx.MockTransport(handler),
    )
    client = RobotSimulationObservabilityHTTPClient(
        "http://simulation.test",
        client=http,
    )
    result = client.get_telemetry()

    assert result.sequence == 7
    assert result.state.tcp == "needle_tip"
    assert requests[0].url.path == "/v1/state"
    client.close()
    assert not http.is_closed
    http.close()


def test_observability_client_gets_and_updates_view_only_camera_endpoint():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = camera_payload()
        if request.method == "PUT":
            payload = {**payload, "preset": "custom", "yaw_deg": 7.0}
        return httpx.Response(200, json=payload)

    http = httpx.Client(
        base_url="http://simulation.test",
        transport=httpx.MockTransport(handler),
    )
    client = RobotSimulationObservabilityHTTPClient(
        "http://simulation.test",
        client=http,
    )

    assert client.get_camera_state().preset == "front"
    result = client.control_camera(
        SimulationCameraControlRequest(
            action="orbit",
            yaw_delta_deg=7.0,
            pitch_delta_deg=0.0,
        )
    )
    assert result.preset == "custom"
    assert result.yaw_deg == 7.0
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/v1/camera"),
        ("PUT", "/v1/camera"),
    ]
    assert requests[1].read()
    client.close()
    http.close()


def test_observability_client_streams_and_closes_mjpeg_connection():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={
                "Content-Type": "multipart/x-mixed-replace; boundary=frame"
            },
            stream=OneChunkAsyncStream(
                b"--frame\r\n\xff\xd8proxy\xff\xd9\r\n"
            ),
        )

    async def scenario() -> None:
        async_http = httpx.AsyncClient(
            base_url="http://simulation.test",
            transport=httpx.MockTransport(handler),
        )
        sync_http = httpx.Client(transport=httpx.MockTransport(handler))
        client = RobotSimulationObservabilityHTTPClient(
            "http://simulation.test",
            client=sync_http,
            async_client_factory=lambda: async_http,
        )
        stream = await client.open_mjpeg()
        body = b"".join([chunk async for chunk in stream.iter_bytes()])
        assert b"\xff\xd8proxy\xff\xd9" in body
        assert async_http.is_closed
        client.close()
        assert not sync_http.is_closed
        sync_http.close()

    asyncio.run(scenario())
    assert requests[0].url.path == "/v1/stream.mjpeg"


def test_observability_client_rejects_invalid_mjpeg_content_type():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": "application/json"})

    async def scenario() -> None:
        async_http = httpx.AsyncClient(
            base_url="http://simulation.test",
            transport=httpx.MockTransport(handler),
        )
        sync_http = httpx.Client(transport=httpx.MockTransport(handler))
        client = RobotSimulationObservabilityHTTPClient(
            "http://simulation.test",
            client=sync_http,
            async_client_factory=lambda: async_http,
        )
        with pytest.raises(SimulationProxyError):
            await client.open_mjpeg()
        assert async_http.is_closed
        client.close()
        assert not sync_http.is_closed
        sync_http.close()

    asyncio.run(scenario())
