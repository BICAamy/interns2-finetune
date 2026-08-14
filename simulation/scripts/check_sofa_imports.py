"""Fail-fast validation for the pinned SOFA/SofaPython3 runtime."""

from __future__ import annotations

import importlib
import json
import os
import platform
import sys
import traceback
from pathlib import Path
from types import ModuleType
from typing import Any

# When this file is launched as ``python3 simulation/scripts/...py``, Python
# otherwise places only ``simulation/scripts`` on sys.path. Add the repository
# root before importing the Step 5 simulation package.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


EXPECTED_PYTHON = (3, 10)
EXPECTED_MACHINE = "x86_64"
REQUIRED_MODULES = (
    "Sofa",
    "Sofa.Core",
    "Sofa.Simulation",
    "SofaRuntime",
    "SofaTypes",
    "sofa_env",
    "sofa_env.base",
    "sofa_env.scenes.controllable_object_example.controllable_env",
    "simulation.entry_point_env.environment",
    "simulation.entry_point_env.scene",
)
REQUIRED_PLUGINS = (
    "SofaPython3",
    "Sofa.Component.AnimationLoop",
    "Sofa.Component.StateContainer",
    "Sofa.GL.Component.Rendering3D",
)


def _module_location(module: ModuleType) -> str | None:
    location = getattr(module, "__file__", None)
    return str(Path(location).resolve()) if location else None


def run_checks() -> dict[str, Any]:
    python_version = sys.version_info[:2]
    if python_version != EXPECTED_PYTHON:
        raise RuntimeError(
            f"Python {EXPECTED_PYTHON[0]}.{EXPECTED_PYTHON[1]} is required; "
            f"found {platform.python_version()}"
        )

    machine = platform.machine()
    if machine != EXPECTED_MACHINE:
        raise RuntimeError(f"CPU architecture {EXPECTED_MACHINE} is required; found {machine}")

    sofa_root = Path(os.environ.get("SOFA_ROOT", ""))
    sofa_python_root = Path(os.environ.get("SOFAPYTHON3_ROOT", ""))
    if not sofa_root.is_dir():
        raise RuntimeError(f"SOFA_ROOT does not exist: {sofa_root}")
    if not sofa_python_root.is_dir():
        raise RuntimeError(f"SOFAPYTHON3_ROOT does not exist: {sofa_python_root}")

    e05_model_dir = Path(
        os.environ.get(
            "E05_MODEL_DIR",
            "/opt/huayan-elfin-model/model/485/elfin5",
        )
    )
    source_e05_assets = [e05_model_dir / "elfin_base.STL"] + [
        e05_model_dir / f"elfin_link{index}.STL" for index in range(1, 7)
    ]
    runtime_e05_assets = [path.with_suffix(".stl") for path in source_e05_assets]
    missing_e05_assets = [
        str(path)
        for path in source_e05_assets + runtime_e05_assets
        if not path.is_file()
    ]
    if missing_e05_assets:
        raise RuntimeError(f"E05 model assets are missing: {missing_e05_assets}")

    modules = {name: importlib.import_module(name) for name in REQUIRED_MODULES}
    sofa_runtime = modules["SofaRuntime"]

    loaded_plugins: list[str] = []
    for plugin in REQUIRED_PLUGINS:
        result = sofa_runtime.importPlugin(plugin)
        if result is False:
            raise RuntimeError(f"SOFA plugin could not be loaded: {plugin}")
        loaded_plugins.append(plugin)

    sofa = modules["Sofa"]
    sofa_core = modules["Sofa.Core"]
    sofa_simulation = modules["Sofa.Simulation"]
    root = sofa_core.Node("step4_runtime_check")
    initialized = False
    try:
        root.addObject("DefaultAnimationLoop")
        root.addObject(
            "MechanicalObject",
            name="point",
            template="Vec3d",
            position=[[0.0, 0.0, 0.0]],
        )
        sofa_simulation.init(root)
        initialized = True
        sofa_simulation.animate(root, 0.01)
    finally:
        if initialized:
            sofa_simulation.unload(root)

    return {
        "status": "ok",
        "python": platform.python_version(),
        "machine": machine,
        "sofa_root": str(sofa_root.resolve()),
        "sofa_python_root": str(sofa_python_root.resolve()),
        "sofa_version": getattr(sofa, "__version__", "v24.06.00 (image pin)"),
        "e05_model_dir": str(e05_model_dir.resolve()),
        "e05_model_assets": [path.name for path in source_e05_assets],
        "e05_runtime_mesh_aliases": [path.name for path in runtime_e05_assets],
        "modules": {name: _module_location(module) for name, module in modules.items()},
        "plugins": loaded_plugins,
        "simulation_step": "ok",
        "legacy_splib": "not imported; SOFA v24.06 provides a relocation stub",
    }


def main() -> int:
    try:
        result = run_checks()
    except Exception as error:  # pragma: no cover - exercised inside the image
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(error).__name__,
                    "message": str(error),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        traceback.print_exc()
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
