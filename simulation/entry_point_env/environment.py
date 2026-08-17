"""SOFA-backed E05-Pro environment for moving a needle TCP to an entry point."""

from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
from typing import Any

import gymnasium.spaces as spaces
import numpy as np
from scipy.spatial.transform import Rotation

from sofa_env.base import RenderFramework, RenderMode, SofaEnv

from surgical_contracts import (
    Point3D,
    RobotState,
    SimulationCameraControlRequest,
    SimulationCameraState,
)

from .camera_controller import OrbitCameraController
from .config import DEFAULT_CONFIG_PATH, EntryPointEnvConfig
from .controller import ContinuousTrajectoryController, SimulationStep
from .kinematics import KinematicSnapshot
from .renderer import TrajectoryRenderer


SCENE_PATH = Path(__file__).resolve().with_name("scene.py")
MM_PER_SCENE_UNIT = 1000.0
DEFAULT_MODEL_DIR = Path("/opt/huayan-elfin-model/model/485/elfin5")


@dataclass(frozen=True)
class EntryPointObservation:
    state: RobotState
    entry_point: Point3D | None
    trajectory_mm: tuple[tuple[float, float, float], ...]
    joint_positions_deg: tuple[float, float, float, float, float, float]
    rgb: np.ndarray | None


class EntryPointReachEnv(SofaEnv):
    """Move the E05-Pro ``needle_tip`` through bounded Cartesian trajectories."""

    def __init__(
        self,
        *,
        config: EntryPointEnvConfig | None = None,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
        model_dir: str | Path | None = None,
        render_mode: RenderMode = RenderMode.NONE,
        render_framework: RenderFramework = RenderFramework.PYGLET,
    ) -> None:
        self.config = config or EntryPointEnvConfig.from_yaml(config_path)
        self.controller = ContinuousTrajectoryController(self.config)
        self.camera_controller = OrbitCameraController()
        self._trajectory_renderer = TrajectoryRenderer()
        self._last_step = self.controller.snapshot()
        resolved_model_dir = Path(
            model_dir
            or os.environ.get("E05_MODEL_DIR", str(DEFAULT_MODEL_DIR))
        )

        initial_snapshot = self.controller.kinematic_snapshot
        needle_length_m = (
            float(np.linalg.norm(self.config.robot.tool_transform.translation_mm))
            / MM_PER_SCENE_UNIT
        )
        super().__init__(
            scene_path=SCENE_PATH,
            time_step=self.config.time_step_s,
            frame_skip=1,
            render_mode=render_mode,
            render_framework=render_framework,
            create_scene_kwargs={
                "image_shape": self.config.image_shape,
                "model_dir": str(resolved_model_dir),
                "initial_link_poses": tuple(
                    self._transform_to_scene_pose(transform)
                    for transform in initial_snapshot.link_transforms
                ),
                "initial_flange_pose": self._transform_to_scene_pose(
                    initial_snapshot.flange_transform
                ),
                "initial_tcp_pose": self._transform_to_scene_pose(
                    initial_snapshot.tcp_transform
                ),
                "workspace_low_m": self._mm_to_scene(self.config.workspace.low_mm),
                "workspace_high_m": self._mm_to_scene(self.config.workspace.high_mm),
                "needle_length_m": needle_length_m,
                "force_link6_scale_z": (
                    self.config.robot.force_flange_offset_mm / 146.0
                ),
            },
        )
        self.action_space = spaces.Box(low=0.0, high=0.0, shape=(1,), dtype=np.float32)
        self.observation_space = spaces.Box(
            low=0,
            high=255,
            shape=self.config.image_shape + (3,),
            dtype=np.uint8,
        )

    @staticmethod
    def _mm_to_scene(position_mm: tuple[float, float, float]) -> np.ndarray:
        return np.asarray(position_mm, dtype=np.float64) / MM_PER_SCENE_UNIT

    @staticmethod
    def _scene_to_mm(position_scene: np.ndarray) -> tuple[float, float, float]:
        values = np.asarray(position_scene, dtype=np.float64) * MM_PER_SCENE_UNIT
        return (float(values[0]), float(values[1]), float(values[2]))

    @staticmethod
    def _transform_to_scene_pose(transform_mm: np.ndarray) -> tuple[float, ...]:
        transform = np.asarray(transform_mm, dtype=np.float64)
        position_m = transform[:3, 3] / MM_PER_SCENE_UNIT
        quaternion_xyzw = Rotation.from_matrix(transform[:3, :3]).as_quat()
        return tuple(float(value) for value in np.concatenate((position_m, quaternion_xyzw)))

    def _init_sim(self) -> None:
        super()._init_sim()
        self._camera = self.scene_creation_result["camera"]
        interactive = self.scene_creation_result["interactive_objects"]
        self._robot_links = interactive["links"]
        self._needle = interactive["needle"]
        self._tcp_marker = interactive["tcp_marker"]
        self._visual_entry = interactive["visual_target"]
        self._apply_camera_pose()

    def reset(
        self,
        seed: int | np.random.SeedSequence | None = None,
        options: dict[str, Any] | None = None,
    ) -> EntryPointObservation:
        numeric_seed = None if isinstance(seed, np.random.SeedSequence) else seed
        self.controller.reset(seed=numeric_seed)
        super().reset(seed=seed, options=options)
        self._apply_camera_pose()
        self._apply_controller_pose()
        self._sync_entry_marker()
        self._last_step = self.controller.snapshot()
        base_frame = self._maybe_update_rgb_buffer()
        return self._observation(base_frame)

    def set_entry_point(self, point: Point3D) -> None:
        self.controller.set_entry_point(point)
        self._sync_entry_marker()

    def move_to_entry(self, point: Point3D, speed_mm_s: float | None = None) -> str:
        command_id = self.controller.move_to_entry(point, speed_mm_s)
        self._sync_entry_marker()
        return command_id

    def move_relative(
        self,
        delta_mm: tuple[float, float, float],
        speed_mm_s: float | None = None,
    ) -> str:
        return self.controller.move_relative(delta_mm, speed_mm_s)

    def _do_action(self, _unused_action: Any) -> None:
        self._last_step = self.controller.step()
        try:
            self._apply_controller_pose()
        except Exception:
            self.controller.mark_failed()
            self._last_step = self.controller.snapshot()
            raise

    def _apply_controller_pose(self) -> None:
        snapshot = self.controller.kinematic_snapshot
        if len(snapshot.link_transforms) != len(self._robot_links):
            raise RuntimeError("SOFA scene does not contain all six E05-Pro links")
        for link, transform in zip(self._robot_links, snapshot.link_transforms):
            link.set_pose(np.asarray(self._transform_to_scene_pose(transform)))
        self._needle.set_pose(
            np.asarray(self._transform_to_scene_pose(snapshot.flange_transform))
        )
        self._tcp_marker.set_pose(
            np.asarray(self._transform_to_scene_pose(snapshot.tcp_transform))
        )

    def _sync_entry_marker(self) -> None:
        if not self._initialized or self.controller.entry_point is None:
            return
        current_pose = np.asarray(self._visual_entry.get_pose(), dtype=np.float64).copy()
        current_pose[:3] = self._mm_to_scene(self.controller.entry_point.as_tuple())
        self._visual_entry.set_pose(current_pose)

    def step(self) -> SimulationStep:
        if not self._initialized:
            raise RuntimeError("reset() must be called before step()")
        base_frame = super().step(None)
        return replace(self._last_step, rgb=self._render_overlay(base_frame))

    def get_state(self) -> RobotState:
        return self.controller.get_state()

    def stop(self) -> RobotState:
        return self.controller.stop()

    def emergency_stop(self) -> RobotState:
        return self.controller.emergency_stop()

    def get_camera_state(self) -> SimulationCameraState:
        return self.camera_controller.state()

    def control_camera(
        self,
        request: SimulationCameraControlRequest,
    ) -> SimulationCameraState:
        state = self.camera_controller.apply(request)
        self._apply_camera_pose()
        return state

    def refresh_observation(self) -> EntryPointObservation:
        """Render the changed view without advancing robot simulation time."""

        return self._observation(self._maybe_update_rgb_buffer())

    def _apply_camera_pose(self) -> None:
        if not self._initialized:
            return
        state = self.camera_controller.state()
        self._camera.set_pose(self.camera_controller.pose)
        self._camera.set_look_at(np.asarray(state.target_m, dtype=np.float64))

    def render(self, mode: str | None = None) -> np.ndarray:
        return self._render_overlay(super().render(mode=mode))

    def _render_overlay(self, frame: np.ndarray | None) -> np.ndarray | None:
        if frame is None:
            return None
        from sofa_env.utils.camera import world_to_pixel_coordinates

        trajectory_scene = [self._mm_to_scene(point) for point in self.controller.trajectory_mm]
        tcp_scene = self._mm_to_scene(self.controller.get_state().tcp_position.as_tuple())
        entry = self.controller.entry_point
        entry_scene = self._mm_to_scene(entry.as_tuple()) if entry is not None else None
        return self._trajectory_renderer.render(
            frame,
            trajectory_scene=trajectory_scene,
            tcp_scene=tcp_scene,
            entry_scene=entry_scene,
            project=lambda point: world_to_pixel_coordinates(point, self._camera_object),
        )

    def _observation(self, base_frame: np.ndarray | None) -> EntryPointObservation:
        return EntryPointObservation(
            state=self.get_state(),
            entry_point=self.controller.entry_point,
            trajectory_mm=self.controller.trajectory_mm,
            joint_positions_deg=self.controller.joint_positions_deg,
            rgb=self._render_overlay(base_frame),
        )

    def scene_tcp_position_mm(self) -> tuple[float, float, float]:
        """Return the SOFA-side needle-tip pose for integration telemetry."""

        if not self._initialized:
            raise RuntimeError("reset() must be called before reading the SOFA pose")
        return self._scene_to_mm(np.asarray(self._tcp_marker.get_pose())[:3])

    def scene_kinematic_snapshot(self) -> KinematicSnapshot:
        """Return the controller FK snapshot used to place all SOFA link meshes."""

        return self.controller.kinematic_snapshot
