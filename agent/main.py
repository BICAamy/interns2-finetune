"""CLI for parsing and the Step 10 service-backed minimum execution chain."""

from __future__ import annotations

import argparse
import json
import time
from typing import Sequence

from .config import AgentSettings
from .core import (
    AgentTaskState,
    OrchestrationPolicy,
    SurgicalTaskOrchestrator,
    build_runtime_events,
)
from .parsing import CommandParsingError
from .runtime import InternS2Agent
from .tools.puncture_planner import (
    FakePuncturePlannerClient,
    PlannerAdapterHTTPClient,
)
from .tools.robot import FakeRobotController, RobotSimulationHTTPController


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Parse text and an optional image into a safe ParsedCommand. "
            "Without a mode flag, execute it through the simulation services."
        )
    )
    parser.add_argument("--prompt", required=True, help="User request")
    parser.add_argument("--image", default=None, help="Optional path to a local image")
    parser.add_argument("--env-file", default=None, help="Optional path to a .env file")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--parse-only",
        action="store_true",
        help="Parse only; never invoke robot or planner tools",
    )
    mode.add_argument(
        "--mock-execute",
        action="store_true",
        help="Run the Step 8 state machine with in-memory robot/planner fakes",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable result envelope",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    parse_started_ms = time.time_ns() // 1_000_000
    try:
        settings = AgentSettings.from_env(args.env_file)
        if not args.parse_only and settings.runtime_mode.value != "simulation":
            raise SystemExit(
                "CLI execution requires RUNTIME_MODE=simulation; "
                "real robot control is not implemented"
            )
        parsed = InternS2Agent(settings).parse_command(
            args.prompt,
            image_path=args.image,
        )
    except CommandParsingError as error:
        if args.json:
            print(
                json.dumps(
                    {"status": "error", "error": error.as_dict()},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(f"解析失败 [{error.error_code.value}]：{error}")
        return 2
    parse_finished_ms = time.time_ns() // 1_000_000

    orchestration = None
    if args.mock_execute:
        orchestration = SurgicalTaskOrchestrator(
            FakeRobotController(),
            FakePuncturePlannerClient(),
            policy=OrchestrationPolicy(
                entry_tolerance_mm=settings.entry_tolerance_mm,
                max_relative_translation_mm=settings.max_relative_translation_mm,
                move_speed_mm_s=settings.robot_move_speed_mm_s,
                max_speed_mm_s=settings.max_robot_speed_mm_s,
                expected_runtime_mode=settings.runtime_mode,
            ),
        ).execute(parsed.command)
    elif not args.parse_only:
        with RobotSimulationHTTPController(
            settings.robot_simulation_base_url,
            http_timeout_s=settings.robot_simulation_http_timeout,
            command_timeout_s=settings.robot_simulation_command_timeout,
            poll_interval_s=settings.robot_simulation_poll_interval,
        ) as robot, PlannerAdapterHTTPClient(
            settings.planner_adapter_base_url,
            timeout_s=settings.planner_adapter_timeout,
        ) as planner:
            orchestration = SurgicalTaskOrchestrator(
                robot,
                planner,
                policy=OrchestrationPolicy(
                    entry_tolerance_mm=settings.entry_tolerance_mm,
                    max_relative_translation_mm=(
                        settings.max_relative_translation_mm
                    ),
                    move_speed_mm_s=settings.robot_move_speed_mm_s,
                    max_speed_mm_s=settings.max_robot_speed_mm_s,
                    expected_runtime_mode=settings.runtime_mode,
                ),
            ).execute(parsed.command)

    if args.json:
        envelope = parsed.as_dict()
        envelope["execution_mode"] = (
            "parse_only"
            if args.parse_only
            else "mock"
            if args.mock_execute
            else "services"
        )
        envelope["execution_events"] = [
            event.as_dict()
            for event in build_runtime_events(
                parse_started_ms=parse_started_ms,
                parse_finished_ms=parse_finished_ms,
                orchestration=orchestration,
            )
        ]
        if orchestration is not None:
            envelope["orchestration"] = orchestration.as_dict()
        print(json.dumps(envelope, ensure_ascii=False, indent=2))
    elif orchestration is not None:
        print(orchestration.message)
    elif parsed.clarification:
        print(parsed.clarification)
    else:
        print(parsed.command.summary)

    if orchestration is not None and orchestration.final_state in {
        AgentTaskState.FAILED,
        AgentTaskState.PLAN_FAILED,
        AgentTaskState.PLANNER_UNAVAILABLE,
    }:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
