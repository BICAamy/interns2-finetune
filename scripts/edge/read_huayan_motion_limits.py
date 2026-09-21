"""Thin CLI entry point; set PYTHONPATH to the repo and surgical_contracts."""

from edge_gateway.huayan.motion_limits_probe import main


if __name__ == "__main__":
    raise SystemExit(main())
