"""Launch the existing gateway with native, platform-correct Python paths."""

from __future__ import annotations

import os
from pathlib import Path
import platform
import runpy
import sys
import tempfile

APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARGUMENTS = (
    "--real-config", "configs/robot-real.local.yaml",
    "--connect-real",
    "--server-url", "ws://127.0.0.1:18001/v1/gateway/connect",
    "--secret-file", "configs/gateway-auth.local",
    "--gateway-id", "mac-huayan-ph590320009",
    "--datasheet-byte-order", "little",
    "--audit-path", "logs/edge_gateway.log",
)


def gateway_arguments(arguments: list[str]) -> list[str]:
    # Preserve the fake-only diagnostic entry point. Real CLI overrides are
    # appended, so argparse uses the explicitly supplied value last.
    if any(arg.startswith("--fake-") for arg in arguments):
        return arguments
    return [*DEFAULT_ARGUMENTS, *arguments]


def configure_imports() -> None:
    roots = [str(APP_ROOT / "packages" / "surgical_contracts"), str(APP_ROOT)]
    sys.path[:0] = roots
    existing = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = os.pathsep.join([*roots, *([existing] if existing else [])])
    os.chdir(APP_ROOT)


def check_installation() -> None:
    """Check imports, config/key, FK and journal ownership; no network I/O."""
    import numpy  # noqa: F401
    import scipy  # noqa: F401
    import websockets  # noqa: F401
    import yaml  # noqa: F401

    from edge_gateway.command_journal import CommandJournal, JournalError
    from robot_runtime.real_config import load_real_config
    from simulation.entry_point_env import E05ProKinematics  # noqa: F401
    from simulation.entry_point_env.config import EntryPointEnvConfig
    from surgical_contracts import load_gateway_secret

    config = load_real_config(APP_ROOT / "configs" / "robot-real.local.yaml")
    if config.blocking_fields():
        raise ValueError("Incomplete real config: " + ", ".join(config.blocking_fields()))
    load_gateway_secret(APP_ROOT / "configs" / "gateway-auth.local")
    EntryPointEnvConfig.from_yaml(APP_ROOT / "configs" / "simulation.yaml")
    with tempfile.TemporaryDirectory(prefix="interns2-gateway-check-") as directory:
        path = Path(directory) / "check.journal"
        with CommandJournal(path) as journal:
            try:
                other = CommandJournal(path)
            except JournalError:
                pass
            else:
                other.close()
                raise RuntimeError("Journal exclusive locking is unavailable")
            journal.prepare(command_id="local-check", fingerprint="check", session_id="check",
                            safety_state_hash="check", start_sequence=0, encoded_frame=b"check-only")
            journal.transition("local-check", "not_sent", evidence="offline dependency check; no controller access")
        with CommandJournal(path) as journal:
            if journal.unresolved():
                raise RuntimeError("Journal persistence check failed")
    print(f"Gateway check OK: {platform.system()}, Python {platform.python_version()}")
    print(f"Python: {sys.executable}")
    print("Dependencies, configuration, key and journal are ready. No robot/server connection was opened.")


def main() -> int:
    configure_imports()
    arguments = sys.argv[1:]
    if arguments == ["--check"]:
        try:
            check_installation()
        except Exception as error:
            print(f"Gateway check failed: {type(error).__name__}: {error}", file=sys.stderr)
            return 1
        return 0
    sys.argv = ["edge_gateway.main", *gateway_arguments(arguments)]
    runpy.run_module("edge_gateway.main", run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
