from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator
from pathlib import Path
from threading import Event
import time

from fastapi.testclient import TestClient

from agent.config import AgentSettings
from agent.runtime import ParsedCommandResponse
from agent.tools.puncture_planner import FakePuncturePlannerClient
from agent.tools.robot import FakeRobotController
from surgical_contracts import (
    Axis,
    CommandIntent,
    CoordinateSource,
    Direction,
    ParsedCommand,
    Point3D,
    RelativeMotion,
    SimulationCameraControlRequest,
    SimulationCameraState,
    SimulationTelemetry,
)
from web.backend.main import create_app
from web.backend.asr import ASRSettings
from web.backend.asr.service import RawTranscription
from web.backend.models import TextCommandRequest
from web.backend.runtime import WebRuntime


def settings() -> AgentSettings:
    return AgentSettings(
        base_url="http://interns2.test/v1",
        api_key="EMPTY",
        model="test-interns2",
        timeout=5.0,
        max_retries=0,
        max_tokens=256,
        temperature=0.0,
        top_p=0.95,
        max_tool_rounds=1,
    )


def puncture_command(command_id: str = "web-puncture") -> ParsedCommand:
    return ParsedCommand(
        command_id=command_id,
        intent=CommandIntent.PUNCTURE,
        entry_point=Point3D(x=10, y=20, z=30),
        target_point=Point3D(x=10, y=20, z=60),
        needs_confirmation=True,
        summary="准备穿刺任务",
    )


def relative_command(command_id: str = "web-relative") -> ParsedCommand:
    return ParsedCommand(
        command_id=command_id,
        intent=CommandIntent.MOVE_RELATIVE,
        relative_motion=RelativeMotion(
            axis=Axis.Z,
            direction=Direction.POSITIVE,
            distance_mm=8,
        ),
        summary="沿 Z 轴正方向移动 8 mm",
    )


class StubParser:
    def __init__(self, command: ParsedCommand) -> None:
        self.command = command
        self.calls = 0
        self.image_paths: list[Path | None] = []
        self.image_existed_during_parse: list[bool] = []
        self.input_sources: list[CoordinateSource] = []

    def parse_command(
        self,
        prompt: str,
        image_path=None,
        *,
        input_source: CoordinateSource = CoordinateSource.USER_TEXT,
    ) -> ParsedCommandResponse:
        assert prompt.strip()
        self.calls += 1
        self.input_sources.append(input_source)
        selected = Path(image_path) if image_path is not None else None
        self.image_paths.append(selected)
        self.image_existed_during_parse.append(
            selected is not None and selected.is_file()
        )
        return ParsedCommandResponse(
            command=self.command,
            model="test-interns2",
            tool_call_id="tool-call-web-1",
            raw_arguments={
                "intent": self.command.intent.value,
                "entry_point": (
                    self.command.entry_point.model_dump(mode="json")
                    if self.command.entry_point
                    else None
                ),
                "target_point": (
                    self.command.target_point.model_dump(mode="json")
                    if self.command.target_point
                    else None
                ),
            },
        )


class StubMJPEGStream:
    content_type = "multipart/x-mixed-replace; boundary=frame"

    def __init__(self) -> None:
        self.closed = False

    async def iter_bytes(self) -> AsyncIterator[bytes]:
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
        yield b"\xff\xd8step12\xff\xd9\r\n"

    async def aclose(self) -> None:
        self.closed = True


class StubSimulationObserver:
    def __init__(self, robot: FakeRobotController) -> None:
        self.robot = robot
        self.sequence = 0
        self.frame_sequence = 0
        self.trajectory: list[tuple[float, float, float]] | None = None
        self.last_stream: StubMJPEGStream | None = None
        self.camera_state = SimulationCameraState(
            preset="front",
            yaw_deg=0.0,
            pitch_deg=0.0,
            distance_m=1.65,
            target_m=(0.35, 0.0, 0.42),
            position_m=(0.35, -1.65, 0.42),
            updated_at_ms=int(time.time() * 1000),
        )
        self.camera_calls: list[SimulationCameraControlRequest] = []
        self.closed = False

    def get_telemetry(self) -> SimulationTelemetry:
        self.sequence += 1
        self.frame_sequence += 1
        state = self.robot.get_state()
        trajectory = self.trajectory or [
            (0.0, 0.0, 100.0),
            state.tcp_position.as_tuple(),
        ]
        return SimulationTelemetry(
            state=state,
            sequence=self.sequence,
            joint_positions_deg=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0),
            trajectory_mm=trajectory,
            frame_sequence=self.frame_sequence,
            updated_at_ms=int(time.time() * 1000),
        )

    async def open_mjpeg(self) -> StubMJPEGStream:
        self.last_stream = StubMJPEGStream()
        return self.last_stream

    def get_camera_state(self) -> SimulationCameraState:
        return self.camera_state.model_copy(deep=True)

    def control_camera(
        self,
        request: SimulationCameraControlRequest,
    ) -> SimulationCameraState:
        self.camera_calls.append(request)
        updates: dict[str, object] = {
            "preset": request.preset or "custom",
            "updated_at_ms": int(time.time() * 1000),
        }
        if request.yaw_delta_deg is not None:
            updates["yaw_deg"] = self.camera_state.yaw_deg + request.yaw_delta_deg
        if request.pitch_delta_deg is not None:
            updates["pitch_deg"] = (
                self.camera_state.pitch_deg + request.pitch_delta_deg
            )
        self.camera_state = self.camera_state.model_copy(update=updates)
        return self.camera_state.model_copy(deep=True)

    def close(self) -> None:
        self.closed = True


class StubSpeechTranscriber:
    def __init__(
        self,
        text: str,
        *,
        confidence: float = 0.92,
        duration_s: float = 1.4,
    ) -> None:
        self.text = text
        self.confidence = confidence
        self.duration_s = duration_s
        self.calls = 0
        self.paths: list[Path] = []
        self.existed_during_call: list[bool] = []

    @property
    def loaded(self) -> bool:
        return True

    def transcribe(self, audio_path: Path) -> RawTranscription:
        self.calls += 1
        self.paths.append(audio_path)
        self.existed_during_call.append(audio_path.is_file())
        return RawTranscription(
            text=self.text,
            language="zh",
            language_probability=0.99,
            confidence=self.confidence,
            duration_s=self.duration_s,
        )


class BlockingParser(StubParser):
    def __init__(self, command: ParsedCommand) -> None:
        super().__init__(command)
        self.started = Event()
        self.release = Event()

    def parse_command(
        self,
        prompt: str,
        image_path=None,
        *,
        input_source: CoordinateSource = CoordinateSource.USER_TEXT,
    ) -> ParsedCommandResponse:
        self.started.set()
        assert self.release.wait(timeout=3)
        return super().parse_command(
            prompt,
            image_path,
            input_source=input_source,
        )


def make_client(command: ParsedCommand):
    parser = StubParser(command)
    robot = FakeRobotController()
    planner = FakePuncturePlannerClient()
    observer = StubSimulationObserver(robot)
    runtime = WebRuntime(
        settings(),
        parser=parser,
        robot=robot,
        planner=planner,
        simulation_observer=observer,
    )
    return (
        TestClient(create_app(runtime, static_dir="/missing")),
        parser,
        robot,
        planner,
        observer,
    )


def make_speech_client(
    command: ParsedCommand,
    text: str,
    *,
    confidence: float = 0.92,
):
    parser = StubParser(command)
    robot = FakeRobotController()
    planner = FakePuncturePlannerClient()
    observer = StubSimulationObserver(robot)
    transcriber = StubSpeechTranscriber(text, confidence=confidence)
    runtime = WebRuntime(
        settings(),
        parser=parser,
        robot=robot,
        planner=planner,
        simulation_observer=observer,
        asr_settings=ASRSettings(max_audio_bytes=1024, max_duration_s=30),
        speech_transcriber=transcriber,
    )
    return (
        TestClient(create_app(runtime, static_dir="/missing")),
        parser,
        robot,
        transcriber,
    )


def create_session(client: TestClient) -> dict:
    response = client.post("/api/sessions")
    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["current_tcp"]["z"] == 100.0
    return payload


def wait_for_status(
    client: TestClient,
    session_id: str,
    terminal: set[str],
    timeout_s: float = 3.0,
) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        response = client.get(f"/api/sessions/{session_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in terminal:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"session did not reach {terminal}")


def test_puncture_preview_requires_confirmation_and_never_executes_puncture():
    client, parser, robot, planner, _observer = make_client(puncture_command())
    with client:
        session = create_session(client)
        session_id = session["session_id"]

        preview = client.post(
            f"/api/sessions/{session_id}/commands/text",
            json={"prompt": "入点 10,20,30；靶点 10,20,60"},
        )
        assert preview.status_code == 200
        payload = preview.json()
        assert payload["status"] == "awaiting_confirmation"
        assert payload["pending_confirmation"] is True
        assert payload["raw_model_output"]["tool_call_id"] == "tool-call-web-1"
        assert payload["normalized_command"]["intent"] == "puncture"
        assert robot.move_to_entry_calls == []
        assert planner.call_count == 0

        # A page refresh only reads state; it must never replay execution.
        refreshed = client.get(f"/api/sessions/{session_id}")
        assert refreshed.status_code == 200
        assert refreshed.json()["revision"] == payload["revision"]
        assert robot.move_to_entry_calls == []

        accepted = client.post(f"/api/sessions/{session_id}/confirm")
        assert accepted.status_code == 202
        completed = wait_for_status(client, session_id, {"plan_ready", "failed"})
        assert completed["status"] == "plan_ready"
        assert len(robot.move_to_entry_calls) == 1
        assert planner.call_count == 1
        assert completed["orchestration"]["planner_result"]["executable"] is False
        assert "未执行穿刺" in completed["message"]
        assert "穿刺完成" not in completed["message"]
        assert all(
            "duration_ms" in event
            for event in completed["execution_events"]
            if event["status"] == "completed"
        )
        assert parser.calls == 1
        assert parser.input_sources == [CoordinateSource.USER_TEXT]

        # The web service has no browser-facing planner passthrough.
        blocked = client.post("/api/planner/plan", json={})
        assert blocked.status_code in {404, 405}


def test_relative_motion_cancel_and_image_lifecycle():
    client, parser, robot, planner, _observer = make_client(relative_command())
    with client:
        session_id = create_session(client)["session_id"]
        image = base64.b64encode(b"not-a-decoder-test").decode("ascii")
        response = client.post(
            f"/api/sessions/{session_id}/commands/text",
            json={
                "prompt": "机械臂向上移动 8 毫米",
                "image_name": "frame.png",
                "image_data_url": f"data:image/png;base64,{image}",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "awaiting_confirmation"
        assert parser.image_existed_during_parse == [True]
        assert parser.image_paths[0] is not None
        assert not parser.image_paths[0].exists()

        cancelled = client.post(f"/api/sessions/{session_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert robot.move_relative_calls == []
        assert planner.call_count == 0

        second_confirm = client.post(f"/api/sessions/{session_id}/confirm")
        assert second_confirm.status_code == 409


def test_relative_confirmation_stop_estop_reset_and_websocket():
    client, _parser, robot, planner, _observer = make_client(
        relative_command("web-relative-2")
    )
    with client:
        session_id = create_session(client)["session_id"]
        with client.websocket_connect(f"/ws/sessions/{session_id}") as websocket:
            initial = websocket.receive_json()
            assert initial["session_id"] == session_id
            telemetry = websocket.receive_json()
            assert telemetry["type"] == "telemetry"
            assert telemetry["connected"] is True
            assert telemetry["joint_positions_deg"] == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]

        preview = client.post(
            f"/api/sessions/{session_id}/commands/text",
            json={"prompt": "机械臂向上移动 8 毫米"},
        )
        assert preview.status_code == 200
        assert client.post(f"/api/sessions/{session_id}/confirm").status_code == 202
        completed = wait_for_status(client, session_id, {"completed", "failed"})
        assert completed["status"] == "completed"
        assert completed["current_tcp"]["z"] == 108.0
        assert len(robot.move_relative_calls) == 1
        assert planner.call_count == 0

        stopped = client.post(f"/api/sessions/{session_id}/stop")
        assert stopped.status_code == 200
        assert stopped.json()["status"] == "stopped"
        assert robot.stop_calls == 1

        estopped = client.post(f"/api/sessions/{session_id}/estop")
        assert estopped.status_code == 200
        assert estopped.json()["status"] == "estop"
        assert robot.emergency_stop_calls == 1

        reset = client.post(f"/api/sessions/{session_id}/reset-estop")
        assert reset.status_code == 200
        assert reset.json()["status"] == "ready"
        assert robot.reset_estop_calls == 1


def test_unknown_session_never_calls_reset_tool():
    client, _parser, robot, _planner, _observer = make_client(relative_command())
    with client:
        response = client.post("/api/sessions/unknown/reset-estop")
        assert response.status_code == 404
        assert robot.reset_estop_calls == 0


def test_built_react_application_is_served_from_the_same_origin():
    runtime = WebRuntime(
        settings(),
        parser=StubParser(relative_command()),
        robot=FakeRobotController(),
        planner=FakePuncturePlannerClient(),
        simulation_observer=StubSimulationObserver(FakeRobotController()),
    )
    app = create_app(runtime)
    with TestClient(app) as static_client:
        response = static_client.get("/")
        assert response.status_code == 200
        assert "InternS2 手术导航控制台" in response.text


def test_telemetry_is_enriched_and_trajectory_is_downsampled():
    client, _parser, robot, planner, observer = make_client(puncture_command())
    observer.trajectory = [
        (float(index), 0.0, 100.0 + float(index) / 10.0)
        for index in range(300)
    ]
    with client:
        session_id = create_session(client)["session_id"]
        preview = client.post(
            f"/api/sessions/{session_id}/commands/text",
            json={"prompt": "入点 10,20,30；靶点 10,20,60"},
        )
        assert preview.status_code == 200

        response = client.get(
            f"/api/sessions/{session_id}/simulation/telemetry"
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["type"] == "telemetry"
        assert payload["connected"] is True
        assert payload["entry_point"]["x"] == 10.0
        assert payload["trajectory_total_points"] == 300
        assert len(payload["trajectory_mm"]) == 160
        assert payload["trajectory_mm"][0] == [0.0, 0.0, 100.0]
        assert payload["trajectory_mm"][-1] == [299.0, 0.0, 129.9]

        assert client.post(f"/api/sessions/{session_id}/confirm").status_code == 202
        completed = wait_for_status(client, session_id, {"plan_ready", "failed"})
        assert completed["status"] == "plan_ready"
        assert planner.call_count == 1
        final_telemetry = client.get(
            f"/api/sessions/{session_id}/simulation/telemetry"
        ).json()
        assert final_telemetry["position_error_mm"] == 0.0
        assert final_telemetry["motion_progress_percent"] == 100.0
        assert robot.get_state().tcp_position.as_tuple() == (10.0, 20.0, 30.0)


def test_mjpeg_is_proxied_and_upstream_is_closed_after_browser_disconnect():
    client, _parser, _robot, _planner, observer = make_client(relative_command())
    with client:
        session_id = create_session(client)["session_id"]
        with client.stream(
            "GET",
            f"/api/sessions/{session_id}/simulation/stream.mjpeg",
        ) as response:
            body = b"".join(response.iter_bytes())
            assert response.status_code == 200
            assert response.headers["content-type"].startswith(
                "multipart/x-mixed-replace"
            )
            assert b"\xff\xd8step12\xff\xd9" in body
        assert observer.last_stream is not None
        assert observer.last_stream.closed is True

        missing = client.get(
            "/api/sessions/unknown/simulation/stream.mjpeg"
        )
        assert missing.status_code == 404


def test_camera_state_and_bounded_view_controls_are_proxied_by_session():
    client, _parser, _robot, _planner, observer = make_client(relative_command())
    with client:
        session_id = create_session(client)["session_id"]
        initial = client.get(
            f"/api/sessions/{session_id}/simulation/camera"
        )
        assert initial.status_code == 200
        assert initial.json()["preset"] == "front"

        orbit = client.put(
            f"/api/sessions/{session_id}/simulation/camera",
            json={
                "action": "orbit",
                "yaw_delta_deg": 9.0,
                "pitch_delta_deg": -3.0,
            },
        )
        assert orbit.status_code == 200
        assert orbit.json()["preset"] == "custom"
        assert orbit.json()["yaw_deg"] == 9.0
        assert orbit.json()["pitch_deg"] == -3.0
        assert len(observer.camera_calls) == 1

        invalid = client.put(
            f"/api/sessions/{session_id}/simulation/camera",
            json={"action": "zoom", "distance_delta_m": 99.0},
        )
        assert invalid.status_code == 422
        assert len(observer.camera_calls) == 1

        missing = client.put(
            "/api/sessions/unknown/simulation/camera",
            json={"action": "preset", "preset": "front"},
        )
        assert missing.status_code == 404
        assert len(observer.camera_calls) == 1


def test_speech_is_transcribed_deleted_and_reuses_confirmed_text_chain():
    client, parser, robot, transcriber = make_speech_client(
        relative_command("voice-relative"),
        "机械臂沿基座坐标系Z轴正方向移动8毫米",
    )
    with client:
        session_id = create_session(client)["session_id"]
        status = client.get("/api/asr/status")
        assert status.status_code == 200
        assert status.json()["available"] is True
        assert status.json()["loaded"] is True

        response = client.post(
            f"/api/sessions/{session_id}/commands/speech",
            content=b"stub-webm-opus",
            headers={
                "Content-Type": "audio/webm;codecs=opus",
                "X-Audio-Duration-Ms": "1400",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "awaiting_confirmation"
        assert payload["input_source"] == "voice"
        assert payload["prompt"] == "机械臂沿基座坐标系Z轴正方向移动8毫米"
        assert payload["asr_transcription"]["confidence"] == 0.92
        assert payload["asr_transcription"]["asr_latency_ms"] >= 0
        assert payload["asr_transcription"]["end_to_end_latency_ms"] >= 0
        assert payload["asr_transcription"]["safety_action"] is None
        assert parser.calls == 1
        assert parser.input_sources == [CoordinateSource.ASR_TEXT]
        assert transcriber.calls == 1
        assert transcriber.existed_during_call == [True]
        assert not transcriber.paths[0].exists()
        assert robot.move_relative_calls == []

        accepted = client.post(f"/api/sessions/{session_id}/confirm")
        assert accepted.status_code == 202
        completed = wait_for_status(client, session_id, {"completed", "failed"})
        assert completed["status"] == "completed"
        assert len(robot.move_relative_calls) == 1


def test_low_confidence_speech_never_executes_without_doctor_confirmation():
    client, parser, robot, _transcriber = make_speech_client(
        relative_command("voice-low-confidence"),
        "机械臂向上移动8毫米",
        confidence=0.41,
    )
    with client:
        session_id = create_session(client)["session_id"]
        response = client.post(
            f"/api/sessions/{session_id}/commands/speech",
            content=b"low-confidence-audio",
            headers={
                "Content-Type": "audio/webm",
                "X-Audio-Duration-Ms": "1200",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "awaiting_confirmation"
        assert payload["pending_confirmation"] is True
        assert payload["asr_transcription"]["low_confidence"] is True
        assert "逐字核对" in payload["message"]
        assert parser.calls == 1
        assert robot.move_relative_calls == []


def test_exact_spoken_stop_uses_fast_path_without_interns2():
    client, parser, robot, _transcriber = make_speech_client(
        relative_command("unused-voice-command"),
        "停止机械臂。",
    )
    with client:
        session_id = create_session(client)["session_id"]
        response = client.post(
            f"/api/sessions/{session_id}/commands/speech",
            content=b"spoken-stop",
            headers={
                "Content-Type": "audio/ogg;codecs=opus",
                "X-Audio-Duration-Ms": "900",
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "stopped"
        assert payload["input_source"] == "voice"
        assert payload["asr_transcription"]["safety_action"] == "stop"
        assert parser.calls == 0
        assert robot.stop_calls == 1


def test_speech_upload_validation_happens_before_transcription():
    client, parser, robot, transcriber = make_speech_client(
        relative_command(),
        "机械臂向上移动8毫米",
    )
    with client:
        session_id = create_session(client)["session_id"]
        unsupported = client.post(
            f"/api/sessions/{session_id}/commands/speech",
            content=b"audio",
            headers={
                "Content-Type": "application/octet-stream",
                "X-Audio-Duration-Ms": "1000",
            },
        )
        assert unsupported.status_code == 415
        assert unsupported.json()["code"] == "ASR_UNSUPPORTED_AUDIO_TYPE"

        too_large = client.post(
            f"/api/sessions/{session_id}/commands/speech",
            content=b"x" * 1025,
            headers={
                "Content-Type": "audio/webm",
                "X-Audio-Duration-Ms": "1000",
            },
        )
        assert too_large.status_code == 413
        assert too_large.json()["code"] == "ASR_AUDIO_TOO_LARGE"

        missing_duration = client.post(
            f"/api/sessions/{session_id}/commands/speech",
            content=b"audio",
            headers={"Content-Type": "audio/webm"},
        )
        assert missing_duration.status_code == 400
        assert missing_duration.json()["code"] == "ASR_DURATION_REQUIRED"

        unknown = client.post(
            "/api/sessions/unknown/commands/speech",
            content=b"audio",
            headers={
                "Content-Type": "audio/webm",
                "X-Audio-Duration-Ms": "1000",
            },
        )
        assert unknown.status_code == 404
        assert transcriber.calls == 0
        assert parser.calls == 0
        assert robot.move_relative_calls == []


def test_spoken_stop_preempts_inflight_interns2_parse_without_stale_overwrite():
    parser = BlockingParser(relative_command("stale-parse"))
    robot = FakeRobotController()
    runtime = WebRuntime(
        settings(),
        parser=parser,
        robot=robot,
        planner=FakePuncturePlannerClient(),
        simulation_observer=StubSimulationObserver(robot),
        asr_settings=ASRSettings(),
        speech_transcriber=StubSpeechTranscriber("立即停止"),
    )

    async def scenario():
        session_id = (await runtime.create_session()).session_id
        parsing = asyncio.create_task(
            runtime.submit_text(
                session_id,
                TextCommandRequest(prompt="机械臂向上移动8毫米"),
            )
        )
        assert await asyncio.to_thread(parser.started.wait, 1)
        stopped = await runtime.submit_speech(
            session_id,
            b"spoken-stop",
            content_type="audio/webm",
            duration_ms=900,
        )
        assert stopped.status.value == "stopped"
        parser.release.set()
        stale_result = await parsing
        final = runtime.get_session(session_id)
        assert stale_result.status.value == "stopped"
        assert final.status.value == "stopped"
        assert final.asr_transcription is not None
        assert final.asr_transcription.safety_action == "stop"

    try:
        asyncio.run(scenario())
    finally:
        parser.release.set()
        runtime.close()
    assert robot.stop_calls == 1
