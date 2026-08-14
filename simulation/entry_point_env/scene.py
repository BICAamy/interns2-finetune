"""SOFA scene for the articulated E05-Pro force-control robot."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Optional, Sequence, Tuple

import Sofa.Core

from sofa_env.sofa_templates.camera import CAMERA_PLUGIN_LIST, Camera
from sofa_env.sofa_templates.motion_restriction import (
    MOTION_RESTRICTION_PLUGIN_LIST,
    add_bounding_box,
)
from sofa_env.sofa_templates.rigid import (
    RIGID_PLUGIN_LIST,
    ControllableRigidObject,
    RigidObject,
)
from sofa_env.sofa_templates.scene_header import (
    SCENE_HEADER_PLUGIN_LIST,
    VISUAL_STYLES,
    add_scene_header,
)
from sofa_env.sofa_templates.visual import VISUAL_PLUGIN_LIST, add_visual_model


PLUGIN_LIST = list(
    dict.fromkeys(
        ["SofaPython3"]
        + RIGID_PLUGIN_LIST
        + SCENE_HEADER_PLUGIN_LIST
        + CAMERA_PLUGIN_LIST
        + MOTION_RESTRICTION_PLUGIN_LIST
        + VISUAL_PLUGIN_LIST
    )
)

HERE = Path(__file__).resolve().parent
PROJECT_SIMULATION_DIR = HERE.parent
UNIT_CYLINDER_PATH = PROJECT_SIMULATION_DIR / "assets" / "unit_cylinder_z.obj"
UNIT_SPHERE_PATH = (
    PROJECT_SIMULATION_DIR.parent
    / "third_party"
    / "sofa_env"
    / "assets"
    / "meshes"
    / "models"
    / "unit_sphere.stl"
)


def _require_model_assets(model_dir: Path) -> dict[str, Path]:
    assets = {"base": model_dir / "elfin_base.STL"}
    assets.update(
        {f"link{index}": model_dir / f"elfin_link{index}.STL" for index in range(1, 7)}
    )
    missing = [str(path) for path in assets.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "official E05 model assets are missing; rebuild the simulation image: "
            + ", ".join(missing)
        )
    return assets


def createScene(
    root_node: Sofa.Core.Node,
    image_shape: Tuple[Optional[int], Optional[int]] = (600, 600),
    model_dir: str = "/opt/huayan-elfin-model/model/485/elfin5",
    initial_link_poses: Sequence[Sequence[float]] = (),
    initial_flange_pose: Sequence[float] = (0.0, 0.0, 0.0, 0.0, 0.0, 1.0),
    initial_tcp_pose: Sequence[float] = (0.0, 0.0, 0.0, 0.0, 0.0, 1.0),
    workspace_low_m: Sequence[float] = (0.3, -0.25, 0.25),
    workspace_high_m: Sequence[float] = (0.7, 0.25, 0.75),
    needle_length_m: float = 0.15,
    force_link6_scale_z: float = 184.0 / 146.0,
):
    """Create a visual six-axis robot driven by project FK/IK.

    The official meshes and this scene use metres. Public commands remain in
    millimetres and are converted only by ``EntryPointReachEnv``.
    """

    if len(initial_link_poses) != 6:
        raise ValueError("initial_link_poses must contain all six E05-Pro links")
    model_assets = _require_model_assets(Path(model_dir))
    if not UNIT_CYLINDER_PATH.is_file() or not UNIT_SPHERE_PATH.is_file():
        raise FileNotFoundError("project needle or target marker mesh is missing")

    add_scene_header(
        root_node=root_node,
        plugin_list=PLUGIN_LIST,
        visual_style_flags=VISUAL_STYLES["normal"],
        scene_has_collisions=False,
    )

    root_node.addObject(
        "LightManager",
        listening=True,
        ambient=(0.45, 0.45, 0.45, 0.45),
    )
    root_node.addObject("DirectionalLight", direction=(-1.0, 0.5, -1.0))
    root_node.addObject("DirectionalLight", direction=(0.5, -1.0, -0.5))

    camera = Camera(
        root_node=root_node,
        placement_kwargs={
            "position": (1.45, -1.45, 1.15),
            "lookAt": (0.35, 0.0, 0.48),
        },
        z_near=0.05,
        z_far=4.0,
        width_viewport=image_shape[1],
        height_viewport=image_shape[0],
        vertical_field_of_view=42,
    )

    scene_node = root_node.addChild("e05_pro_scene")
    silver_visual = partial(add_visual_model, color=(0.72, 0.75, 0.78))
    dark_visual = partial(add_visual_model, color=(0.20, 0.23, 0.27))

    base = RigidObject(
        parent_node=scene_node,
        name="e05_pro_base",
        pose=(0.0, 0.0, 0.0, 0.0, 0.0, 1.0),
        fixed_position=True,
        fixed_orientation=True,
        visual_mesh_path=model_assets["base"],
        add_visual_model_func=dark_visual,
    )

    links = []
    for index, pose in enumerate(initial_link_poses, start=1):
        scale = (1.0, 1.0, force_link6_scale_z) if index == 6 else 1.0
        link = ControllableRigidObject(
            parent_node=scene_node,
            name=f"e05_pro_link{index}",
            pose=pose,
            visual_mesh_path=model_assets[f"link{index}"],
            scale=scale,
            add_visual_model_func=silver_visual if index % 2 else dark_visual,
        )
        links.append(link)

    needle_visual = partial(add_visual_model, color=(0.10, 0.85, 0.75))
    needle = ControllableRigidObject(
        parent_node=scene_node,
        name="provisional_needle",
        pose=initial_flange_pose,
        visual_mesh_path=UNIT_CYLINDER_PATH,
        scale=(0.002, 0.002, needle_length_m),
        add_visual_model_func=needle_visual,
    )

    tcp_visual = partial(add_visual_model, color=(0.0, 1.0, 0.1))
    tcp_marker = ControllableRigidObject(
        parent_node=scene_node,
        name="needle_tip_marker",
        pose=initial_tcp_pose,
        visual_mesh_path=UNIT_SPHERE_PATH,
        scale=0.008,
        add_visual_model_func=tcp_visual,
    )

    target_visual = partial(add_visual_model, color=(1.0, 0.45, 0.0))
    visual_target = ControllableRigidObject(
        parent_node=scene_node,
        name="entry_point_marker",
        pose=initial_tcp_pose,
        visual_mesh_path=UNIT_SPHERE_PATH,
        scale=0.012,
        add_visual_model_func=target_visual,
    )

    scene_node.addObject(
        "MechanicalObject",
        template="Rigid3d",
        position=(0.0, 0.0, 0.0, 0.0, 0.0, 1.0),
    )
    add_bounding_box(
        scene_node,
        min=workspace_low_m,
        max=workspace_high_m,
        show_bounding_box=True,
        name="cartesian_command_workspace",
    )

    return {
        "camera": camera,
        "interactive_objects": {
            "base": base,
            "links": tuple(links),
            "needle": needle,
            "tcp_marker": tcp_marker,
            "visual_target": visual_target,
        },
        "workspace": {
            "low": tuple(workspace_low_m),
            "high": tuple(workspace_high_m),
        },
        "model": {
            "name": "E05-Pro",
            "force_control_variant": True,
            "visual_terminal_is_scaled_proxy": True,
        },
    }

