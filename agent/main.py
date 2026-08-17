"""CLI for Step 7 InternS2 structured task parsing."""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from .config import AgentSettings
from .parsing import CommandParsingError
from .runtime import InternS2Agent


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse text and an optional image into a safe ParsedCommand."
    )
    parser.add_argument("--prompt", required=True, help="User request")
    parser.add_argument("--image", default=None, help="Optional path to a local image")
    parser.add_argument("--env-file", default=None, help="Optional path to a .env file")
    parser.add_argument(
        "--parse-only",
        action="store_true",
        help="Parse only; Step 7 never executes robot or planner tools",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable result envelope",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.parse_only:
        raise SystemExit(
            "Step 7 only supports --parse-only; deterministic tool execution is added in Step 8."
        )

    try:
        settings = AgentSettings.from_env(args.env_file)
        result = InternS2Agent(settings).parse_command(
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

    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    elif result.clarification:
        print(result.clarification)
    else:
        print(result.command.summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
