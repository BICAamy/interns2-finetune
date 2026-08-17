"""Run the fixed Step 7 corpus against a live InternS2 LMDeploy endpoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent.config import AgentSettings
from agent.parsing import CommandParsingError
from agent.runtime import InternS2Agent


DEFAULT_CASES = Path(__file__).with_name("step7_cases.json")


def _close(actual: tuple[float, float, float], expected: list[float]) -> bool:
    return all(abs(value - float(target)) <= 1e-6 for value, target in zip(actual, expected))


def evaluate(command: Any, expected: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if command.intent.value != expected["intent"]:
        errors.append(f"intent={command.intent.value}, expected={expected['intent']}")
        return errors

    if "entry_point_mm" in expected:
        if command.entry_point is None:
            errors.append("entry_point is missing")
        elif not _close(command.entry_point.as_tuple(), expected["entry_point_mm"]):
            errors.append(f"entry_point={command.entry_point.as_tuple()}")
    if "target_point_mm" in expected:
        if command.target_point is None:
            errors.append("target_point is missing")
        elif not _close(command.target_point.as_tuple(), expected["target_point_mm"]):
            errors.append(f"target_point={command.target_point.as_tuple()}")

    relative = command.relative_motion
    for key in ("axis", "direction", "distance_source"):
        if key in expected:
            actual = getattr(relative, key, None)
            actual = getattr(actual, "value", actual)
            if actual != expected[key]:
                errors.append(f"{key}={actual}, expected={expected[key]}")
    if "distance_mm" in expected:
        actual_distance = None if relative is None else float(relative.distance_mm)
        if actual_distance is None or abs(actual_distance - float(expected["distance_mm"])) > 1e-6:
            errors.append(f"distance_mm={actual_distance}")

    for field in expected.get("missing_contains", []):
        if field not in command.missing_fields:
            errors.append(f"missing_fields does not contain {field!r}")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=None)
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--case", action="append", dest="case_ids")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    selected = [
        case for case in cases if not args.case_ids or case["id"] in args.case_ids
    ]
    unknown = set(args.case_ids or []) - {case["id"] for case in selected}
    if unknown:
        raise SystemExit(f"unknown case IDs: {', '.join(sorted(unknown))}")

    agent = InternS2Agent(AgentSettings.from_env(args.env_file))
    results: list[dict[str, Any]] = []
    passed = 0
    for case in selected:
        try:
            response = agent.parse_command(case["prompt"])
            errors = evaluate(response.command, case["expected"])
            record = {
                "id": case["id"],
                "category": case["category"],
                "passed": not errors,
                "errors": errors,
                "parsed_command": response.command.model_dump(mode="json"),
            }
        except CommandParsingError as error:
            record = {
                "id": case["id"],
                "category": case["category"],
                "passed": False,
                "errors": [f"{error.error_code.value}: {error}"],
                "error": error.as_dict(),
            }
        passed += int(record["passed"])
        results.append(record)

    output = {
        "status": "ok" if passed == len(selected) else "failed",
        "model": agent.model,
        "passed": passed,
        "total": len(selected),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
