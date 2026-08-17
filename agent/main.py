"""CLI for InternS2 parsing and Step 8 deterministic mock orchestration."""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from .config import AgentSettings
from .core import AgentTaskState, OrchestrationPolicy, SurgicalTaskOrchestrator
from .parsing import CommandParsingError
from .runtime import InternS2Agent
from .tools.puncture_planner import FakePuncturePlannerClient
from .tools.robot import FakeRobotController


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse text and an optional image into a safe ParsedCommand."
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
    if not args.parse_only and not args.mock_execute:
        raise SystemExit(
            "Choose --parse-only or --mock-execute. Mock execution never connects to a real robot."
        )

    try:
        settings = AgentSettings.from_env(args.env_file)
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

    orchestration = None
    if args.mock_execute:
        if settings.runtime_mode.value != "simulation":
            raise SystemExit("--mock-execute requires RUNTIME_MODE=simulation")
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

    if args.json:
        envelope = parsed.as_dict()
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
