"""CLI for testing the DeepSeek-backed NavGPT tool without loading InternS2."""

from __future__ import annotations

import argparse
import json

from .nav_tool import NavGPTTool


def main() -> None:
    parser = argparse.ArgumentParser(description="Call the standalone NavGPT navigation tool")
    parser.add_argument("--instruction", required=True)
    parser.add_argument("--observation", required=True)
    parser.add_argument(
        "--candidates-json",
        default="[]",
        help='JSON array such as [{"id":"left-door","direction":"left"}]',
    )
    parser.add_argument("--history", default="")
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args()

    candidates = json.loads(args.candidates_json)
    result = NavGPTTool.from_env(args.env_file).navigate(
        instruction=args.instruction,
        observation=args.observation,
        navigable_viewpoints=candidates,
        history=args.history,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
