from __future__ import annotations

import os
import unittest
from math import dist

import numpy as np

from simulation.entry_point_env import (
    ContinuousTrajectoryController,
    EntryPointEnvConfig,
    InvalidMotionCommand,
    UnreachableTargetError,
    WorkspaceViolationError,
)
from simulation.entry_point_env.renderer import TrajectoryRenderer
from surgical_contracts import CoordinateFrame, MotionState, Point3D


CONFIG = EntryPointEnvConfig.from_yaml()
RUN_SOFA_INTEGRATION = os.environ.get("ENTRY_POINT_SOFA_TESTS") == "1"


def run_until_settled(
    controller: ContinuousTrajectoryController,
    *,
    maximum_steps: int = 1000,
):
    steps = []
    for _ in range(maximum_steps):
        step = controller.step()
        steps.append(step)
        if step.state.motion_state != MotionState.MOVING:
            return steps
    raise AssertionError("controller did not settle within maximum_steps")


class EntryPointControllerTests(unittest.TestCase):
    def test_reaches_multiple_workspace_points_with_bounded_steps(self):
        controller = ContinuousTrajectoryController(CONFIG)
        maximum_step = CONFIG.maximum_speed_mm_s * CONFIG.time_step_s

        initial_joints = np.asarray(controller.joint_positions_deg)
        joint_samples = [initial_joints]
        for coordinates in (
            (500.0, 0.0, 500.0),
            (450.0, 50.0, 450.0),
            (600.0, -100.0, 450.0),
        ):
            target = Point3D(x=coordinates[0], y=coordinates[1], z=coordinates[2])
            controller.move_to_entry(target, speed_mm_s=CONFIG.maximum_speed_mm_s)
            steps = run_until_settled(controller)
            joint_samples.extend(np.asarray(step.joint_positions_deg) for step in steps)

            state = controller.get_state()
            self.assertEqual(state.motion_state, MotionState.AT_ENTRY)
            self.assertLessEqual(state.tcp_position.distance_to(target), CONFIG.reach_tolerance_mm)

        jumps = [
            dist(start, end)
            for start, end in zip(controller.trajectory_mm, controller.trajectory_mm[1:])
        ]
        self.assertTrue(jumps)
        self.assertLessEqual(max(jumps), maximum_step + 1e-9)
        joint_deltas = np.abs(np.diff(np.asarray(joint_samples), axis=0))
        allowed_joint_step = (
            np.asarray(CONFIG.robot.joint_max_speeds_deg_s) * CONFIG.time_step_s
        )
        self.assertTrue(np.all(joint_deltas <= allowed_joint_step + 1e-7))
        self.assertGreater(
            float(np.linalg.norm(np.asarray(controller.joint_positions_deg) - initial_joints)),
            1.0,
        )

    def test_out_of_workspace_entry_is_rejected_before_motion(self):
        controller = ContinuousTrajectoryController(CONFIG)
        with self.assertRaises(WorkspaceViolationError):
            controller.move_to_entry(Point3D(x=701.0, y=0.0, z=500.0), speed_mm_s=10.0)
        self.assertEqual(controller.get_state().motion_state, MotionState.IDLE)
        self.assertEqual(len(controller.trajectory_mm), 1)

    def test_frame_and_speed_are_validated_before_motion(self):
        controller = ContinuousTrajectoryController(CONFIG)
        with self.assertRaisesRegex(InvalidMotionCommand, "coordinate frame"):
            controller.move_to_entry(
                Point3D(x=0.0, y=0.0, z=0.0, frame=CoordinateFrame.SIMULATION_WORLD),
                speed_mm_s=10.0,
            )
        with self.assertRaisesRegex(InvalidMotionCommand, "cannot exceed"):
            controller.move_to_entry(
                Point3D(x=500.0, y=0.0, z=500.0),
                speed_mm_s=CONFIG.maximum_speed_mm_s + 1.0,
            )

    def test_workspace_point_without_valid_ik_is_rejected_before_motion(self):
        controller = ContinuousTrajectoryController(CONFIG)
        with self.assertRaises(UnreachableTargetError):
            controller.move_to_entry(
                Point3D(x=650.0, y=250.0, z=750.0),
                speed_mm_s=10.0,
            )
        self.assertEqual(controller.get_state().motion_state, MotionState.IDLE)

    def test_fixed_seed_reset_is_reproducible(self):
        controller = ContinuousTrajectoryController(CONFIG)
        target = Point3D(x=500.0, y=0.0, z=500.0)

        controller.reset(seed=1234)
        controller.move_to_entry(target, speed_mm_s=20.0)
        run_until_settled(controller)
        first_trajectory = controller.trajectory_mm

        controller.reset(seed=1234)
        controller.move_to_entry(target, speed_mm_s=20.0)
        run_until_settled(controller)
        self.assertEqual(first_trajectory, controller.trajectory_mm)

    def test_overlay_preserves_rgb_shape_and_draws_markers(self):
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        renderer = TrajectoryRenderer()
        rendered = renderer.render(
            frame,
            trajectory_scene=((0.0, 0.0, 0.0), (1.0, 1.0, 0.0)),
            tcp_scene=(1.0, 1.0, 0.0),
            entry_scene=(2.0, 1.0, 0.0),
            project=lambda point: (int(10 + point[1] * 10), int(10 + point[0] * 10)),
        )

        self.assertEqual(rendered.shape, frame.shape)
        self.assertEqual(rendered.dtype, np.uint8)
        self.assertGreater(int(rendered.max()), 0)
        self.assertEqual(int(frame.max()), 0, "renderer must not mutate its input frame")


@unittest.skipUnless(
    RUN_SOFA_INTEGRATION,
    "set ENTRY_POINT_SOFA_TESTS=1 inside the simulation image",
)
class EntryPointSofaIntegrationTests(unittest.TestCase):
    def test_reaches_entry_and_renders_trajectory(self):
        if not os.environ.get("DISPLAY"):
            self.fail("render integration test requires run-with-xvfb")

        from sofa_env.base import RenderMode

        from simulation.entry_point_env.environment import EntryPointReachEnv

        env = EntryPointReachEnv(config=CONFIG, render_mode=RenderMode.HUMAN)
        try:
            observation = env.reset(seed=7)
            self.assertEqual(observation.rgb.shape, CONFIG.image_shape + (3,))

            initial_joints = np.asarray(observation.joint_positions_deg)
            target = Point3D(x=500.0, y=0.0, z=500.0)
            command_id = env.move_to_entry(target, speed_mm_s=25.0)
            for _ in range(200):
                step = env.step()
                if step.state.motion_state != MotionState.MOVING:
                    break
            else:
                self.fail("SOFA environment did not reach the entry point")

            self.assertEqual(step.command_id, command_id)
            self.assertTrue(step.reached)
            self.assertLessEqual(step.position_error_mm, CONFIG.reach_tolerance_mm)
            np.testing.assert_allclose(
                env.scene_tcp_position_mm(),
                target.as_tuple(),
                atol=CONFIG.reach_tolerance_mm,
            )

            frame = env.render()
            self.assertEqual(frame.shape, CONFIG.image_shape + (3,))
            self.assertEqual(frame.dtype, np.uint8)
            self.assertGreater(int(np.ptp(frame)), 0)
            self.assertGreater(len(env.controller.trajectory_mm), 2)
            self.assertGreater(
                float(
                    np.linalg.norm(
                        np.asarray(step.joint_positions_deg) - initial_joints
                    )
                ),
                1.0,
            )
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()
