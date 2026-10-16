"""Read-only random motion suggestions using the current numerical arm model."""

from dataclasses import replace
from math import ceil, dist
import random
import time

import numpy as np
from scipy.spatial.transform import Rotation

from .config import EntryPointEnvConfig
from .controller import ContinuousTrajectoryController
from .kinematics import InverseKinematicsError


def generate_random_commands(config: EntryPointEnvConfig, joint_positions_deg, *, rng=None):
    rng = rng or random.Random()
    initial = tuple(float(value) for value in joint_positions_deg)
    private_config = replace(config, robot=replace(config.robot, initial_joint_positions_deg=initial))
    model = ContinuousTrajectoryController(private_config).kinematics
    joints = np.deg2rad(initial)
    origin = model.forward(joints).tcp_transform[:3, 3].copy()
    steps, instructions = [], []
    last_axis, last_joint = None, None
    deadline = time.monotonic() + 25

    def position(q):
        return model.forward(q).tcp_transform[:3, 3]

    def translation(q):
        start = position(q)
        orientation = Rotation.from_matrix(model.forward(q).tcp_transform[:3, :3])
        axes = [axis for axis in range(3) if axis != last_axis]
        rng.shuffle(axes)
        for axis in axes:
            signs = [-1, 1]
            rng.shuffle(signs)
            for sign in signs:
                bound = config.workspace.high_mm[axis] - 5 if sign > 0 else config.workspace.low_mm[axis] + 5
                room = (bound - start[axis]) * sign
                maximum = min(room, config.maximum_relative_distance_mm)
                if maximum < 20:
                    continue
                # The configured workspace and existing command limits determine
                # distance. Failed reachability checks may shorten this attempt.
                amount = round(rng.uniform(0.35, 0.95) * maximum / 5) * 5
                for _ in range(5):
                    if amount < 20 or time.monotonic() > deadline:
                        break
                    delta = np.zeros(3)
                    delta[axis] = amount * sign
                    target = start + delta
                    candidate = q.copy()
                    try:
                        for fraction in np.linspace(0, 1, max(2, ceil(amount / 40) + 1))[1:]:
                            candidate = np.asarray(model.inverse(start + delta * fraction, orientation, candidate).joint_positions_rad)
                    except InverseKinematicsError:
                        amount = round(amount / 2 / 5) * 5
                        continue
                    if config.workspace.contains(target):
                        direction = (("后", "前"), ("右", "左"), ("下", "上"))[axis][sign > 0]
                        return candidate, {"kind": "cartesian_relative", "translation_mm": delta.tolist(), "frame": "robot_base", "value_source": "user_provided"}, f"向{direction}移动 {amount:g} 毫米", axis
        return None

    def rotation(q):
        indices = [index for index in range(5) if index != last_joint]
        rng.shuffle(indices)
        for index in indices:
            signs = [-1, 1]
            rng.shuffle(signs)
            for sign in signs:
                lower, upper = config.robot.joint_limits_deg[index]
                current = float(np.rad2deg(q[index]))
                room = upper - current if sign > 0 else current - lower
                maximum = min(room, config.maximum_rotation_deg, 45)
                if maximum < 10:
                    continue
                angle = min(rng.randint(2, 9) * 5, int(maximum / 5) * 5)
                while angle >= 10:
                    target = q.copy()
                    target[index] += np.deg2rad(sign * angle)
                    if all(config.workspace.contains(position(q + (target - q) * fraction)) for fraction in np.linspace(0, 1, ceil(angle) + 1)):
                        direction = "左" if sign > 0 else "右"
                        return target, {"kind": "joint_relative", "joint_index": index + 1, "rotation_deg": sign * angle, "value_source": "user_provided"}, f"第{index + 1}关节向{direction}转 {angle} 度", index
                    angle -= 5
        return None

    kinds = ["translation"] * rng.randint(5, 7) + ["rotation"] * 3
    rng.shuffle(kinds)
    for kind in kinds:
        if time.monotonic() > deadline:
            raise ValueError("当前姿态可用动作较少，请重新生成")
        result = translation(joints) if kind == "translation" else rotation(joints)
        if result is None:
            raise ValueError("当前姿态没有足够的可行空间，请调整位置后重新生成")
        joints, step, text, selected = result
        steps.append(step)
        instructions.append(text)
        if kind == "translation":
            last_axis = selected
        else:
            last_joint = selected
    if dist(position(joints), origin) < 10:
        result = translation(joints)
        if result is None:
            raise ValueError("当前姿态没有合适的随机终点，请重新生成")
        joints, step, text, _ = result
        steps.append(step)
        instructions.append(text)
    return {
        "name": "随机混合运动", "prompt": "，然后".join(instructions) + "。",
        "stepCount": len(steps), "steps": steps,
        "start_joint_positions_deg": list(initial),
        "end_joint_positions_deg": np.rad2deg(joints).tolist(),
        "end_tcp_mm": position(joints).tolist(),
    }
