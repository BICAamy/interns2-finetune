"""Build a small native-Windows gateway source bundle, without server assets."""

from __future__ import annotations

import argparse
from pathlib import Path
import zipfile

APP_ROOT = Path(__file__).resolve().parents[2]
PREFIX = "interns2-edge-gateway"


def package_files(root: Path, *, include_local_config: bool) -> list[tuple[Path, str]]:
    paths = list((root / "edge_gateway").rglob("*.py"))
    paths += list((root / "packages/surgical_contracts/surgical_contracts").rglob("*.py"))
    # The kinematics package is pure Python/numpy/scipy. No SOFA runtime,
    # simulation server, STL meshes or model weights are needed by the gateway.
    paths += list((root / "simulation/entry_point_env").glob("*.py"))
    paths += [root / name for name in (
        "edge_gateway/requirements.txt", "packages/surgical_contracts/pyproject.toml",
        "robot_runtime/__init__.py", "robot_runtime/real_config.py", "simulation/__init__.py",
        "configs/simulation.yaml", "scripts/edge/launch_gateway.py",
        "scripts/edge/setup_gateway.ps1", "scripts/edge/start_gateway.ps1",
    )]
    if include_local_config:
        paths += [root / "configs/robot-real.local.yaml", root / "configs/gateway-auth.local"]
    files = []
    for path in sorted(set(paths)):
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"missing or non-regular package input: {path.relative_to(root)}")
        files.append((path, path.relative_to(root).as_posix()))
    files.append((root / "docs/Windows网关.md", "README.md"))
    return files


def build_package(root: Path, output: Path, *, include_local_config: bool = False) -> Path:
    if output.exists():
        raise ValueError(f"output already exists: {output}; choose a new filename")
    files = package_files(root, include_local_config=include_local_config)
    output.parent.mkdir(parents=True, exist_ok=True)
    # A personal package may contain the local key; keep it private on POSIX.
    with output.open("xb") as stream:
        output.chmod(0o600)
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, relative in files:
                archive.write(path, f"{PREFIX}/{relative}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=APP_ROOT / "artifacts/gateway/interns2-edge-gateway-windows.zip")
    parser.add_argument("--include-local-config", action="store_true",
                        help="include this computer's real robot YAML and private gateway key")
    args = parser.parse_args()
    output = build_package(APP_ROOT, args.output, include_local_config=args.include_local_config)
    print(f"Gateway package: {output}")
    print(f"Size: {output.stat().st_size / 1024:.0f} KiB; Python and dependencies are installed on Windows.")
    if args.include_local_config:
        print("Contains local robot configuration and gateway key. Copy only to your intended operator computer.")
    else:
        print("Copy configs/robot-real.local.yaml and configs/gateway-auth.local from the existing gateway before setup.")


if __name__ == "__main__":
    main()
