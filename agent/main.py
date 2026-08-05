"""Command-line entry point for the InternS2 navigation agent."""

from __future__ import annotations

import argparse
import json

from .config import AgentSettings
from .runtime import InternS2NavigationAgent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send an image and navigation request to InternS2 with NavGPT enabled."
    )
    parser.add_argument("--image", required=True, help="Path to a local image")
    parser.add_argument("--prompt", required=True, help="Navigation request")
    parser.add_argument("--env-file", default=None, help="Optional path to a .env file")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the final answer and tool trace as JSON",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = AgentSettings.from_env(args.env_file)
    result = InternS2NavigationAgent(settings).run(args.image, args.prompt)
    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(result.answer)


if __name__ == "__main__":
    main()
