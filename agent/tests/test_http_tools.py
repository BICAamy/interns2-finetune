from __future__ import annotations

import unittest

import httpx

from agent.core import AgentTaskState, SurgicalTaskOrchestrator
from agent.tools.puncture_planner import (
    PlannerAdapterHTTPClient,
    PlannerAdapterProtocolError,
)
from agent.tools.robot import (
    RobotSimulationHTTPController,
    RobotSimulationTimeoutError,
)
from surgical_contracts import (
    CommandExecutionStatus,
    CommandIntent,
    ErrorCode,
    MotionState,
    MoveRelativeRequest,
    MoveRelativeResult,
    MoveToEntryRequest,
    MoveToEntryResult,
    ParsedCommand,
    PlanPunctureRequest,
    PlanPunctureResult,
    PlannerStatus,
    Point3D,
    RobotCommandKind,
    RobotCommandRecord,
    RobotState,
    SimulationTelemetry,
    ToolStatus,
)


def robot_state(
    point: Point3D | None = None,
    *,
    motion_state: MotionState = MotionState.IDLE,
) -> RobotState:
    return RobotState(
        tcp_position=point or Point3D(x=530.7, y=0.0, z=520.7),
        motion_state=motion_state,
    )


def telemetry(state: RobotState) -> dict:
    return SimulationTelemetry(
        state=state,
        sequence=1,
        joint_positions_deg=(0, 0, 0, 0, 0, 0),
        trajectory_mm=[state.tcp_position.as_tuple()],
        frame_sequence=1,
        updated_at_ms=1,
    ).model_dump(mode="json")


def record(
    command_id: str,
    kind: RobotCommandKind,
    status: CommandExecutionStatus,
    request: dict,
    *,
    result: dict | None = None,
) -> dict:
    return RobotCommandRecord(
        command_id=command_id,
        kind=kind,
        status=status,
        submitted_at_ms=1,
        updated_at_ms=2,
        request=request,
        result=result,
    ).model_dump(mode="json")


def successful_plan(request: PlanPunctureRequest) -> dict:
    return PlanPunctureResult(
        request_id=request.request_id,
        status=PlannerStatus.SUCCESS,
        planner_name="mock",
        planner_version="mock-v1",
        output_schema_version="preview-v1",
        control_mode="mock_preview",
        control_payload={
            "preview_points_mm": [
                list(request.entry_point.as_tuple()),
                list(request.target_point.as_tuple()),
            ]
        },
        executable=False,
        message="preview only",
    ).model_dump(mode="json")


class HTTPToolClientTests(unittest.TestCase):
    def test_robot_client_submits_polls_and_validates_move_result(self):
        entry = Point3D(x=500, y=0, z=500)
        requests: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append((request.method, request.url.path))
            payload = request.read()
            if request.method == "POST":
                body = MoveToEntryRequest.model_validate_json(payload)
                return httpx.Response(
                    202,
                    json=record(
                        body.command_id,
                        RobotCommandKind.MOVE_TO_ENTRY,
                        CommandExecutionStatus.QUEUED,
                        body.model_dump(mode="json"),
                    ),
                )
            body = MoveToEntryRequest(command_id="cmd-http", entry_point=entry)
            result = MoveToEntryResult(
                command_id=body.command_id,
                status=ToolStatus.SUCCESS,
                reached=True,
                final_tcp_position=entry,
                position_error_mm=0,
                trajectory_id="trajectory-http",
                message="reached",
            )
            return httpx.Response(
                200,
                json=record(
                    body.command_id,
                    RobotCommandKind.MOVE_TO_ENTRY,
                    CommandExecutionStatus.SUCCEEDED,
                    body.model_dump(mode="json"),
                    result=result.model_dump(mode="json"),
                ),
            )

        http_client = httpx.Client(
            base_url="http://robot.test",
            transport=httpx.MockTransport(handler),
        )
        client = RobotSimulationHTTPController(
            "http://robot.test",
            client=http_client,
            sleeper=lambda _seconds: None,
        )

        result = client.move_to_entry(
            MoveToEntryRequest(command_id="cmd-http", entry_point=entry)
        )

        self.assertTrue(result.reached)
        self.assertEqual(result.final_tcp_position, entry)
        self.assertEqual(
            requests,
            [
                ("POST", "/v1/commands/move-to-entry"),
                ("GET", "/v1/commands/cmd-http"),
            ],
        )
        http_client.close()

    def test_robot_timeout_submits_best_effort_stop(self):
        now = [0.0]
        paths: list[str] = []
        submitted: list[MoveRelativeRequest] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            if request.url.path == "/v1/commands/stop":
                return httpx.Response(202, json={})
            if request.method == "POST":
                submitted.append(
                    MoveRelativeRequest.model_validate_json(request.read())
                )
            command = submitted[0]
            return httpx.Response(
                202 if request.method == "POST" else 200,
                json=record(
                    command.command_id,
                    RobotCommandKind.MOVE_RELATIVE,
                    CommandExecutionStatus.RUNNING,
                    command.model_dump(mode="json"),
                ),
            )

        def sleep(seconds: float) -> None:
            now[0] += seconds

        http_client = httpx.Client(
            base_url="http://robot.test",
            transport=httpx.MockTransport(handler),
        )
        client = RobotSimulationHTTPController(
            "http://robot.test",
            client=http_client,
            command_timeout_s=0.1,
            poll_interval_s=0.1,
            clock=lambda: now[0],
            sleeper=sleep,
        )

        with self.assertRaises(RobotSimulationTimeoutError):
            client.move_relative(
                MoveRelativeRequest(
                    command_id="cmd-timeout",
                    translation_mm=(0, 0, 5),
                )
            )

        self.assertIn("/v1/commands/stop", paths)
        http_client.close()

    def test_planner_client_rejects_invalid_success_payload(self):
        http_client = httpx.Client(
            base_url="http://planner.test",
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    json={"request_id": "cmd-plan", "status": "success"},
                )
            ),
        )
        client = PlannerAdapterHTTPClient(
            "http://planner.test",
            client=http_client,
        )
        request = PlanPunctureRequest(
            request_id="cmd-plan",
            command_id="cmd-plan",
            entry_point=Point3D(x=500, y=0, z=500),
            target_point=Point3D(x=500, y=0, z=550),
        )

        with self.assertRaises(PlannerAdapterProtocolError):
            client.plan(request)
        http_client.close()

    def test_planner_client_accepts_versioned_unavailable_response(self):
        request = PlanPunctureRequest(
            request_id="cmd-unavailable",
            command_id="cmd-unavailable",
            entry_point=Point3D(x=500, y=0, z=500),
            target_point=Point3D(x=500, y=0, z=550),
        )
        unavailable = PlanPunctureResult(
            request_id=request.request_id,
            status=PlannerStatus.UNAVAILABLE,
            planner_name="external",
            planner_version="unconfigured",
            output_schema_version="preview-v1",
            executable=False,
            message="provider is unavailable",
            error_code=ErrorCode.PLANNER_UNAVAILABLE,
        )
        http_client = httpx.Client(
            base_url="http://planner.test",
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    503,
                    json=unavailable.model_dump(mode="json"),
                )
            ),
        )

        result = PlannerAdapterHTTPClient(
            "http://planner.test",
            client=http_client,
        ).plan(request)

        self.assertEqual(result.status, PlannerStatus.UNAVAILABLE)
        self.assertFalse(result.executable)
        http_client.close()

    def test_http_clients_run_entry_verification_before_planner(self):
        entry = Point3D(x=500, y=0, z=500)
        target = Point3D(x=500, y=0, z=550)
        order: list[str] = []
        moved = [False]

        def robot_handler(request: httpx.Request) -> httpx.Response:
            order.append(f"robot:{request.method}:{request.url.path}")
            if request.url.path == "/v1/state":
                state = robot_state(
                    entry if moved[0] else None,
                    motion_state=(
                        MotionState.AT_ENTRY if moved[0] else MotionState.IDLE
                    ),
                )
                return httpx.Response(200, json=telemetry(state))
            body = MoveToEntryRequest.model_validate_json(request.read())
            moved[0] = True
            result = MoveToEntryResult(
                command_id=body.command_id,
                status=ToolStatus.SUCCESS,
                reached=True,
                final_tcp_position=entry,
                position_error_mm=0,
                trajectory_id="trajectory-e2e",
                message="reached",
            )
            return httpx.Response(
                202,
                json=record(
                    body.command_id,
                    RobotCommandKind.MOVE_TO_ENTRY,
                    CommandExecutionStatus.SUCCEEDED,
                    body.model_dump(mode="json"),
                    result=result.model_dump(mode="json"),
                ),
            )

        planner_calls = [0]

        def planner_handler(request: httpx.Request) -> httpx.Response:
            order.append(f"planner:{request.method}:{request.url.path}")
            self.assertTrue(moved[0])
            planner_calls[0] += 1
            body = PlanPunctureRequest.model_validate_json(request.read())
            return httpx.Response(200, json=successful_plan(body))

        robot_http = httpx.Client(
            base_url="http://robot.test",
            transport=httpx.MockTransport(robot_handler),
        )
        planner_http = httpx.Client(
            base_url="http://planner.test",
            transport=httpx.MockTransport(planner_handler),
        )
        robot = RobotSimulationHTTPController(
            "http://robot.test",
            client=robot_http,
        )
        planner = PlannerAdapterHTTPClient(
            "http://planner.test",
            client=planner_http,
        )
        command = ParsedCommand(
            command_id="cmd-e2e",
            intent=CommandIntent.PUNCTURE,
            entry_point=entry,
            target_point=target,
        )

        result = SurgicalTaskOrchestrator(robot, planner).execute(command)

        self.assertEqual(result.final_state, AgentTaskState.PLAN_READY)
        self.assertEqual(planner_calls[0], 1)
        self.assertFalse(result.planner_result.executable)
        self.assertEqual(
            order,
            [
                "robot:GET:/v1/state",
                "robot:POST:/v1/commands/move-to-entry",
                "robot:GET:/v1/state",
                "planner:POST:/v1/plan",
            ],
        )
        robot_http.close()
        planner_http.close()

    def test_relative_motion_over_http_never_calls_planner(self):
        initial = Point3D(x=500, y=0, z=500)
        final = Point3D(x=500, y=0, z=508)
        planner_calls = [0]

        def robot_handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/state":
                return httpx.Response(200, json=telemetry(robot_state(initial)))
            body = MoveRelativeRequest.model_validate_json(request.read())
            result = MoveRelativeResult(
                command_id=body.command_id,
                status=ToolStatus.SUCCESS,
                completed=True,
                final_tcp_position=final,
                trajectory_id="trajectory-relative",
                message="completed",
            )
            return httpx.Response(
                202,
                json=record(
                    body.command_id,
                    RobotCommandKind.MOVE_RELATIVE,
                    CommandExecutionStatus.SUCCEEDED,
                    body.model_dump(mode="json"),
                    result=result.model_dump(mode="json"),
                ),
            )

        def planner_handler(_request: httpx.Request) -> httpx.Response:
            planner_calls[0] += 1
            return httpx.Response(500, json={})

        robot_http = httpx.Client(
            base_url="http://robot.test",
            transport=httpx.MockTransport(robot_handler),
        )
        planner_http = httpx.Client(
            base_url="http://planner.test",
            transport=httpx.MockTransport(planner_handler),
        )
        result = SurgicalTaskOrchestrator(
            RobotSimulationHTTPController(
                "http://robot.test",
                client=robot_http,
            ),
            PlannerAdapterHTTPClient(
                "http://planner.test",
                client=planner_http,
            ),
        ).execute(
            ParsedCommand.model_validate(
                {
                    "command_id": "cmd-relative-http",
                    "intent": "move_relative",
                    "relative_motion": {
                        "axis": "z",
                        "direction": "positive",
                        "distance_mm": 8,
                    },
                }
            )
        )

        self.assertEqual(result.final_state, AgentTaskState.COMPLETED)
        self.assertEqual(result.robot_result.final_tcp_position, final)
        self.assertEqual(planner_calls[0], 0)
        robot_http.close()
        planner_http.close()

    def test_robot_connection_failure_is_contained_before_planning(self):
        planner_calls = [0]

        def robot_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("offline", request=request)

        def planner_handler(_request: httpx.Request) -> httpx.Response:
            planner_calls[0] += 1
            return httpx.Response(500, json={})

        robot_http = httpx.Client(
            base_url="http://robot.test",
            transport=httpx.MockTransport(robot_handler),
        )
        planner_http = httpx.Client(
            base_url="http://planner.test",
            transport=httpx.MockTransport(planner_handler),
        )
        command = ParsedCommand(
            command_id="cmd-offline",
            intent=CommandIntent.PUNCTURE,
            entry_point=Point3D(x=500, y=0, z=500),
            target_point=Point3D(x=500, y=0, z=550),
        )

        result = SurgicalTaskOrchestrator(
            RobotSimulationHTTPController(
                "http://robot.test",
                client=robot_http,
            ),
            PlannerAdapterHTTPClient(
                "http://planner.test",
                client=planner_http,
            ),
        ).execute(command)

        self.assertEqual(result.final_state, AgentTaskState.FAILED)
        self.assertEqual(planner_calls[0], 0)
        robot_http.close()
        planner_http.close()


if __name__ == "__main__":
    unittest.main()
