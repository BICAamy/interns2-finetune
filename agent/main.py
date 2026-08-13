"""Command-line entry point for the InternS2 migration-stage client."""

from __future__ import annotations

import argparse
import json

from .config import AgentSettings
from .runtime import InternS2Agent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send text and an optional image to the InternS2 base model."
    )
    parser.add_argument("--prompt", required=True, help="User request")
    parser.add_argument("--image", default=None, help="Optional path to a local image")
    parser.add_argument("--env-file", default=None, help="Optional path to a .env file")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the answer and model ID as JSON",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = AgentSettings.from_env(args.env_file)
    result = InternS2Agent(settings).run(args.prompt, image_path=args.image)
    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(result.answer)


if __name__ == "__main__":
    main()
