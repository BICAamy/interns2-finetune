"""SOFA visualizer driven only by actual gateway joint samples."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import gymnasium.spaces as spaces
import numpy as np
from scipy.spatial.transform import Rotation
from sofa_env.base import RenderFramework, RenderMode, SofaEnv

from surgical_contracts import RobotTelemetry, SourceFreshness

from .camera_controller import OrbitCameraController
from .config import DEFAULT_CONFIG_PATH, EntryPointEnvConfig
from .external_joint_state_controller import ExternalJointStateController
from .renderer import TrajectoryRenderer


SCENE_PATH = Path(__file__).resolve().with_name("scene.py")
DEFAULT_MODEL_DIR = Path("/opt/huayan-elfin-model/model/485/elfin5")


class PassiveRealMirrorEnv(SofaEnv):
    """No action API, IK or provisional needle; only the worker calls apply()."""

    def __init__(
        self,
        *,
        stale_ms: int,
        sign: tuple[int, ...] | None = None,
        zero_offset_deg: tuple[float, ...] | None = None,
        config: EntryPointEnvConfig | None = None,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
        model_dir: str | Path | None = None,
        render_mode: RenderMode = RenderMode.HUMAN,
        render_framework: RenderFramework = RenderFramework.PYGLET,
    ) -> None:
        self.config = config or EntryPointEnvConfig.from_yaml(config_path)
        self.controller = ExternalJointStateController(
            self.config, stale_ms=stale_ms, sign=sign, zero_offset_deg=zero_offset_deg
        )
        self.camera_controller = OrbitCameraController()
        self._renderer = TrajectoryRenderer()
        initial = self.controller.kinematics.forward(
            np.deg2rad(self.config.robot.initial_joint_positions_deg)
        )
        flange_pose = self._scene_pose(initial.flange_transform)
        resolved_model_dir = Path(model_dir or os.environ.get("E05_MODEL_DIR", str(DEFAULT_MODEL_DIR)))
        super().__init__(
            scene_path=SCENE_PATH,
            time_step=self.config.time_step_s,
            frame_skip=1,
            render_mode=render_mode,
            render_framework=render_framework,
            create_scene_kwargs={
                "image_shape": self.config.image_shape,
                "model_dir": str(resolved_model_dir),
                "initial_link_poses": tuple(self._scene_pose(item) for item in initial.link_transforms),
                "initial_flange_pose": flange_pose,
                "initial_tcp_pose": flange_pose,
                "force_link6_scale_z": self.config.robot.force_flange_offset_mm / 146.0,
                "show_provisional_tool": False,
                "show_command_workspace": False,
            },
        )
        self.action_space = spaces.Box(low=0.0, high=0.0, shape=(1,), dtype=np.float32)
        self.observation_space = spaces.Box(
            low=0, high=255, shape=self.config.image_shape + (3,), dtype=np.uint8
        )

    @staticmethod
    def _scene_pose(transform_mm: np.ndarray) -> tuple[float, ...]:
        position_m = transform_mm[:3, 3] / 1000.0
        quaternion = Rotation.from_matrix(transform_mm[:3, :3]).as_quat()
        return tuple(float(value) for value in np.concatenate((position_m, quaternion)))

    def _init_sim(self) -> None:
        super()._init_sim()
        self._camera = self.scene_creation_result["camera"]
        interactive = self.scene_creation_result["interactive_objects"]
        self._robot_links = interactive["links"]
        self._flange = interactive["needle"]
        if self._flange is not None or interactive["tcp_marker"] is not None:
            raise RuntimeError("passive real mirror must not display the provisional needle/TCP")
        self._apply_camera_pose()

    def _apply_camera_pose(self) -> None:
        if not self._initialized:
            return
        state = self.camera_controller.state()
        self._camera.set_pose(self.camera_controller.pose)
        self._camera.set_look_at(np.asarray(state.target_m, dtype=np.float64))

    def reset(self, seed: int | None = None, options: dict[str, Any] | None = None) -> None:
        super().reset(seed=seed, options=options)
        self._apply_camera_pose()

    def _do_action(self, _unused_action: Any) -> None:
        # SofaEnv.step advances visuals; it never generates robot motion here.
        return None

    def apply_external_joint_state(self, telemetry: RobotTelemetry) -> np.ndarray | None:
        if not self._initialized:
            raise RuntimeError("reset() must be called before external feedback")
        if not self.controller.apply_external_joint_state(telemetry):
            return None
        snapshot = self.controller.snapshot
        assert snapshot is not None
        if len(snapshot.kinematics.link_transforms) != len(self._robot_links):
            raise RuntimeError("SOFA scene does not contain all six E05-Pro links")
        for link, transform in zip(self._robot_links, snapshot.kinematics.link_transforms):
            link.set_pose(np.asarray(self._scene_pose(transform)))
        raw_frame = super().step(None)
        return self._overlay(raw_frame)

    def refresh_frozen_frame(self) -> np.ndarray | None:
        if self.controller.snapshot is None:
            return None
        return self._overlay(self._maybe_update_rgb_buffer())

    def _overlay(self, frame: np.ndarray | None) -> np.ndarray | None:
        if frame is None:
            return None
        from sofa_env.utils.camera import world_to_pixel_coordinates

        freshness = self.controller.freshness
        warning = "UNCALIBRATED / NOT FOR CONTROL"
        if freshness != SourceFreshness.FRESH:
            warning = f"{freshness.value.upper()} / UNCALIBRATED"
        return self._renderer.render(
            frame,
            # Until Base-to-SOFA is calibrated, do not place the controller's
            # actual TCP path into an assumed SOFA coordinate frame.
            trajectory_scene=(),
            tcp_scene=None,
            entry_scene=None,
            warning=warning,
            project=lambda point: world_to_pixel_coordinates(point, self._camera_object),
        )
