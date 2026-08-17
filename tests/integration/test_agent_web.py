from __future__ import annotations

import base64
from pathlib import Path
import time

from fastapi.testclient import TestClient

from agent.config import AgentSettings
from agent.runtime import ParsedCommandResponse
from agent.tools.puncture_planner import FakePuncturePlannerClient
from agent.tools.robot import FakeRobotController
from surgical_contracts import (
    Axis,
    CommandIntent,
    Direction,
    ParsedCommand,
    Point3D,
    RelativeMotion,
)
from web.backend.main import create_app
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

    def parse_command(self, prompt: str, image_path=None) -> ParsedCommandResponse:
        assert prompt.strip()
        self.calls += 1
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


def make_client(command: ParsedCommand):
    parser = StubParser(command)
    robot = FakeRobotController()
    planner = FakePuncturePlannerClient()
    runtime = WebRuntime(
        settings(),
        parser=parser,
        robot=robot,
        planner=planner,
    )
    return TestClient(create_app(runtime, static_dir="/missing")), parser, robot, planner


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
    client, parser, robot, planner = make_client(puncture_command())
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

        # The web service has no browser-facing planner passthrough.
        blocked = client.post("/api/planner/plan", json={})
        assert blocked.status_code in {404, 405}


def test_relative_motion_cancel_and_image_lifecycle():
    client, parser, robot, planner = make_client(relative_command())
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
    client, _parser, robot, planner = make_client(relative_command("web-relative-2"))
    with client:
        session_id = create_session(client)["session_id"]
        with client.websocket_connect(f"/ws/sessions/{session_id}") as websocket:
            initial = websocket.receive_json()
            assert initial["session_id"] == session_id

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
    client, _parser, robot, _planner = make_client(relative_command())
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
    )
    app = create_app(runtime)
    with TestClient(app) as static_client:
        response = static_client.get("/")
        assert response.status_code == 200
        assert "InternS2 手术导航控制台" in response.text
