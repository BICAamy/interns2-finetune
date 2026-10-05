from __future__ import annotations

from dataclasses import replace
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agent.config import AgentSettings
from agent.parsing import CommandParsingError
from agent.runtime import InternS2Agent
from surgical_contracts import (
    Axis,
    CommandIntent,
    CoordinateFrame,
    CoordinateSource,
    Direction,
    DistanceSource,
    ErrorCode,
    RuntimeMode,
)


def make_settings(model: str | None = "interns2-test") -> AgentSettings:
    return AgentSettings(
        base_url="http://localhost:23333/v1",
        api_key="EMPTY",
        model=model,
        timeout=30,
        max_retries=0,
        max_tokens=512,
        temperature=0.0,
        top_p=0.95,
        max_tool_rounds=3,
    )


def base_arguments(intent: str, **updates):
    payload = {
        "intent": intent,
        "entry_point": None,
        "target_point": None,
        "relative_motion": None,
        "missing_fields": [],
        "needs_confirmation": False,
        "confidence": 0.98,
        "summary": "测试解析结果",
    }
    payload.update(updates)
    return payload


def tool_call(arguments, *, name: str = "submit_surgical_task", call_id: str = "call-1"):
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments, ensure_ascii=False)
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


class FakeCompletions:
    def __init__(self, *, calls=None, error: Exception | None = None) -> None:
        self.calls = calls
        self.error = error
        self.requests: list[dict] = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if self.error is not None:
            raise self.error
        message = SimpleNamespace(content=None, tool_calls=self.calls)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeInternS2Client:
    def __init__(self, *, calls=None, error: Exception | None = None) -> None:
        self.chat = SimpleNamespace(
            completions=FakeCompletions(calls=calls, error=error)
        )
        self.models = SimpleNamespace(
            list=lambda: SimpleNamespace(
                data=[SimpleNamespace(id="discovered-interns2")]
            )
        )


def make_agent(arguments, *, settings=None, name="submit_surgical_task"):
    client = FakeInternS2Client(calls=[tool_call(arguments, name=name)])
    agent = InternS2Agent(
        settings or make_settings(),
        client=client,
        command_id_factory=lambda: "cmd-trusted-001",
    )
    return agent, client


class InternS2AgentTests(unittest.TestCase):
    def test_explicit_ordered_motion_uses_deterministic_fast_path(self):
        client = FakeInternS2Client(calls=[])
        agent = InternS2Agent(
            replace(
                make_settings(),
                default_relative_step_mm=15.0,
                default_relative_rotation_deg=15.0,
            ),
            client=client,
            command_id_factory=lambda: "cmd-sequence-fallback",
        )

        result = agent.parse_command(
            "往左52mm之后再往上一点然后再往前74mm，再向右转70度"
        )

        self.assertEqual(result.command.intent, CommandIntent.MOVE_SEQUENCE)
        steps = result.command.motion_sequence.steps
        self.assertEqual(steps[0].translation_mm, (0.0, 52.0, 0.0))
        self.assertEqual(steps[1].translation_mm, (0.0, 0.0, 15.0))
        self.assertEqual(steps[2].translation_mm, (74.0, 0.0, 0.0))
        self.assertEqual(steps[3].joint_index, 1)
        self.assertEqual(steps[3].rotation_deg, -70.0)
        self.assertEqual(client.chat.completions.requests, [])

    def test_no_tool_call_uses_configured_vague_distance_and_rotation(self):
        client = FakeInternS2Client(calls=[])
        agent = InternS2Agent(
            replace(
                make_settings(),
                default_relative_step_mm=15.0,
                default_relative_rotation_deg=15.0,
                default_rotation_joint_index=4,
            ),
            client=client,
            command_id_factory=lambda: "cmd-vague-sequence-fallback",
        )

        command = agent.parse_command("往上一点，然后向右转一点").command

        self.assertEqual(command.motion_sequence.steps[0].translation_mm, (0.0, 0.0, 15.0))
        self.assertEqual(command.motion_sequence.steps[1].joint_index, 4)
        self.assertEqual(command.motion_sequence.steps[1].rotation_deg, -15.0)

    def test_one_motion_sequence_can_contain_all_six_step_kinds(self):
        arguments = base_arguments(
            "move_sequence",
            motion_steps=[
                {
                    "kind": "cartesian_relative", "delta_mm": [1, -2, 3],
                    "value_source": "user_provided",
                },
                {
                    "kind": "cartesian_absolute",
                    "target_position_mm": [500, 10, 300],
                    "value_source": "user_provided",
                },
                {
                    "kind": "joint_relative", "joint_index": 2,
                    "direction": "negative", "rotation_deg": 5,
                    "value_source": "user_provided",
                },
                {
                    "kind": "joint_absolute", "joint_index": 3,
                    "target_angle_deg": 30,
                    "value_source": "user_provided",
                },
                {
                    "kind": "tcp_rotation_relative", "axis": "z",
                    "direction": "positive", "rotation_deg": 10,
                    "value_source": "user_provided",
                },
                {
                    "kind": "tcp_rotation_absolute", "axis": "x",
                    "target_angle_deg": -20,
                    "value_source": "user_provided",
                },
            ],
        )
        command = make_agent(arguments)[0].parse_command("执行统一运动序列").command

        self.assertEqual(command.intent, CommandIntent.MOVE_SEQUENCE)
        steps = command.motion_sequence.steps
        self.assertEqual([step.kind.value for step in steps], [
            "cartesian_relative", "cartesian_absolute", "joint_relative",
            "joint_absolute", "tcp_rotation_relative", "tcp_rotation_absolute",
        ])
        self.assertEqual(steps[0].translation_mm, (1.0, -2.0, 3.0))
        self.assertEqual(steps[1].target_position_mm, (500.0, 10.0, 300.0))
        self.assertEqual(steps[2].rotation_deg, -5.0)
        self.assertEqual(steps[3].target_angle_deg, 30.0)
        self.assertEqual(steps[4].rotation_axis, Axis.Z)
        self.assertEqual(steps[5].target_angle_deg, -20.0)

    def test_tcp_absolute_rotation_without_base_axis_requires_clarification(self):
        client = FakeInternS2Client(calls=[])
        agent = InternS2Agent(
            make_settings(),
            client=client,
            command_id_factory=lambda: "cmd-tcp-axis-clarify",
        )

        command = agent.parse_command("把TCP转到30度").command

        self.assertEqual(command.intent, CommandIntent.CLARIFY)
        self.assertEqual(command.missing_fields, ["motion_sequence.rotation_axis"])

        relative = agent.parse_command("TCP转动10度").command
        self.assertEqual(relative.intent, CommandIntent.CLARIFY)
        self.assertEqual(
            relative.missing_fields,
            ["motion_sequence.rotation_axis"],
        )

    def test_no_tool_call_parses_absolute_joint_and_tcp_rotation(self):
        client = FakeInternS2Client(calls=[])
        agent = InternS2Agent(
            make_settings(),
            client=client,
            command_id_factory=lambda: "cmd-absolute-rotation-fallback",
        )

        command = agent.parse_command(
            "J3关节旋转到30度，然后TCP绕Base Z轴转到20度"
        ).command

        self.assertEqual(command.intent, CommandIntent.MOVE_SEQUENCE)
        self.assertEqual(command.motion_sequence.steps[0].joint_index, 3)
        self.assertEqual(command.motion_sequence.steps[0].target_angle_deg, 30.0)
        self.assertEqual(command.motion_sequence.steps[1].rotation_axis, Axis.Z)
        self.assertEqual(command.motion_sequence.steps[1].target_angle_deg, 20.0)

    def test_no_tool_call_parses_base_absolute_xyz_as_one_step_sequence(self):
        client = FakeInternS2Client(calls=[])
        agent = InternS2Agent(
            make_settings(),
            client=client,
            command_id_factory=lambda: "cmd-absolute-xyz-fallback",
        )

        command = agent.parse_command(
            "机械臂移动到Base坐标系下(X=500,Y=-10,Z=300)毫米"
        ).command

        self.assertEqual(command.intent, CommandIntent.MOVE_SEQUENCE)
        self.assertEqual(
            command.motion_sequence.steps[0].target_position_mm,
            (500.0, -10.0, 300.0),
        )

    def test_no_tool_call_keeps_absolute_xyz_inside_a_mixed_sequence(self):
        client = FakeInternS2Client(calls=[])
        agent = InternS2Agent(
            make_settings(),
            client=client,
            command_id_factory=lambda: "cmd-mixed-absolute-fallback",
        )

        command = agent.parse_command(
            "移动到Base坐标系下X=500,Y=-10,Z=300毫米，然后J3关节增加5度"
        ).command

        self.assertEqual(command.intent, CommandIntent.MOVE_SEQUENCE)
        self.assertEqual(len(command.motion_sequence.steps), 2)
        self.assertEqual(
            command.motion_sequence.steps[0].target_position_mm,
            (500.0, -10.0, 300.0),
        )
        self.assertEqual(command.motion_sequence.steps[1].joint_index, 3)
        self.assertEqual(command.motion_sequence.steps[1].rotation_deg, 5.0)

    def test_explicit_heart_polyline_uses_deterministic_fast_path(self):
        client = FakeInternS2Client(calls=[])
        agent = InternS2Agent(
            make_settings(),
            client=client,
            command_id_factory=lambda: "cmd-heart-polyline-fallback",
        )
        vectors = (
            (-25, 0, 25), (-20, 0, 25), (0, 0, 25), (15, 0, 15),
            (20, 0, 0), (10, 0, -15), (10, 0, 15), (20, 0, 0),
            (15, 0, -15), (0, 0, -25), (-20, 0, -25), (-25, 0, -25),
        )
        prompt = "；".join(
            f"第{index}步：沿Base坐标系组合相对移动"
            f"ΔX={dx},ΔY={dy},ΔZ={dz}毫米"
            for index, (dx, dy, dz) in enumerate(vectors, start=1)
        )

        command = agent.parse_command(prompt).command

        assert command.intent == CommandIntent.MOVE_SEQUENCE
        actual = tuple(
            step.translation_mm for step in command.motion_sequence.steps
        )
        assert actual == tuple(
            tuple(float(value) for value in vector) for vector in vectors
        )
        assert tuple(sum(vector[axis] for vector in actual) for axis in range(3)) == (
            0.0, 0.0, 0.0,
        )
        self.assertEqual(client.chat.completions.requests, [])

    def test_heart_demo_phrases_expand_to_fixed_motion_sequence_without_model(self):
        client = FakeInternS2Client(calls=[])
        agent = InternS2Agent(
            make_settings(),
            client=client,
            command_id_factory=lambda: "cmd-heart-demo-preset",
        )
        expected = (
            (20.0, 0.0, 30.0), (40.0, 0.0, 0.0), (30.0, 0.0, -30.0),
            (0.0, 0.0, -50.0), (-40.0, 0.0, -50.0), (-50.0, 0.0, -50.0),
            (-50.0, 0.0, 50.0), (-40.0, 0.0, 50.0), (0.0, 0.0, 50.0),
            (30.0, 0.0, 30.0), (40.0, 0.0, 0.0), (20.0, 0.0, -30.0),
        )

        for prompt in ("画一个爱心", "请画一个爱心", "请帮我画一颗爱心。"):
            with self.subTest(prompt=prompt):
                command = agent.parse_command(prompt).command
                self.assertEqual(command.intent, CommandIntent.MOVE_SEQUENCE)
                self.assertEqual(
                    tuple(
                        step.translation_mm
                        for step in command.motion_sequence.steps
                    ),
                    expected,
                )
                self.assertTrue(command.needs_confirmation)

        self.assertEqual(client.chat.completions.requests, [])
        result = agent.parse_command("画一个爱心")
        self.assertEqual(
            result.raw_arguments["demo_preset"],
            "heart_180mm_xz",
        )

    def test_puncture_tool_call_is_validated_and_model_id_is_ignored(self):
        arguments = base_arguments(
            "puncture",
            command_id="model-controlled-id",
            entry_point={"x": 20, "y": 35, "z": 80, "unit": "mm", "frame": "robot_base"},
            target_point={"x": 24, "y": 38, "z": 120, "unit": "mm", "frame": "robot_base"},
        )
        agent, client = make_agent(arguments)

        result = agent.parse_command("请准备穿刺")

        self.assertEqual(result.command.command_id, "cmd-trusted-001")
        self.assertEqual(result.command.intent, CommandIntent.PUNCTURE)
        self.assertTrue(result.command.needs_confirmation)
        self.assertEqual(result.command.entry_point.as_tuple(), (20.0, 35.0, 80.0))
        request = client.chat.completions.requests[0]
        self.assertEqual(len(request["tools"]), 1)
        self.assertEqual(
            request["tools"][0]["function"]["name"],
            "submit_surgical_task",
        )
        self.assertNotIn("tool_choice", request)
        self.assertNotIn(
            "command_id",
            request["tools"][0]["function"]["parameters"]["properties"],
        )
        properties = request["tools"][0]["function"]["parameters"]["properties"]
        self.assertIn("motion_steps", properties)
        kinds = properties["motion_steps"]["anyOf"][0]["items"]["properties"]["kind"]["enum"]
        self.assertEqual(kinds, [
            "cartesian_relative", "cartesian_absolute", "joint_relative",
            "joint_absolute", "tcp_rotation_relative", "tcp_rotation_absolute",
        ])
        self.assertNotIn("relative_motion", properties)

    def test_asr_coordinate_provenance_cannot_be_overridden_by_model(self):
        arguments = base_arguments(
            "move_to_entry",
            entry_point={
                "x": 20,
                "y": 35,
                "z": 80,
                "unit": "mm",
                "frame": "robot_base",
                "source": "user_text",
            },
        )
        agent, _client = make_agent(arguments)

        command = agent.parse_command(
            "移动到入点X二十Y三十五Z八十毫米",
            input_source=CoordinateSource.ASR_TEXT,
        ).command

        self.assertEqual(command.intent, CommandIntent.MOVE_SEQUENCE)
        self.assertEqual(
            command.motion_sequence.steps[0].target_position_mm,
            (20.0, 35.0, 80.0),
        )

    def test_lmdeploy_stringified_nested_parameters_are_decoded(self):
        arguments = base_arguments(
            "puncture",
            entry_point=json.dumps(
                {
                    "x": 20,
                    "y": 35,
                    "z": 80,
                    "unit": "mm",
                    "frame": "robot_base",
                }
            ),
            target_point=json.dumps(
                {
                    "x": 24,
                    "y": 38,
                    "z": 120,
                    "unit": "mm",
                    "frame": "robot_base",
                }
            ),
            relative_motion="null",
            missing_fields="[]",
            needs_confirmation="false",
            confidence="0.98",
        )
        agent, _client = make_agent(arguments)

        command = agent.parse_command("请准备穿刺").command

        self.assertEqual(command.intent, CommandIntent.PUNCTURE)
        self.assertEqual(command.entry_point.as_tuple(), (20.0, 35.0, 80.0))
        self.assertEqual(command.target_point.as_tuple(), (24.0, 38.0, 120.0))
        self.assertIsNone(command.relative_motion)
        self.assertEqual(command.confidence, 0.98)
        # The safety normalizer, rather than string truthiness, forces this true.
        self.assertTrue(command.needs_confirmation)

    def test_blank_missing_fields_is_accepted_as_an_empty_array(self):
        arguments = base_arguments(
            "puncture",
            entry_point=json.dumps(
                {
                    "x": 600,
                    "y": 0,
                    "z": 500,
                    "unit": "mm",
                    "frame": "robot_base",
                }
            ),
            target_point=json.dumps(
                {
                    "x": 500,
                    "y": 0,
                    "z": 550,
                    "unit": "mm",
                    "frame": "robot_base",
                }
            ),
            missing_fields="   ",
        )
        agent, _client = make_agent(arguments)

        command = agent.parse_command("请准备穿刺").command

        self.assertEqual(command.intent, CommandIntent.PUNCTURE)
        self.assertEqual(command.missing_fields, [])
        self.assertEqual(command.entry_point.as_tuple(), (600.0, 0.0, 500.0))
        self.assertEqual(command.target_point.as_tuple(), (500.0, 0.0, 550.0))

    def test_blank_embedded_json_is_still_rejected_for_other_fields(self):
        arguments = base_arguments(
            "move_to_entry",
            entry_point="   ",
        )
        agent, _client = make_agent(arguments)

        with self.assertRaises(CommandParsingError) as raised:
            agent.parse_command("移动到入点")

        self.assertEqual(
            raised.exception.error_code,
            ErrorCode.MODEL_INVALID_OUTPUT,
        )
        self.assertIn(
            "entry_point must not be an empty JSON value",
            str(raised.exception),
        )

    def test_lmdeploy_string_false_is_not_treated_as_true(self):
        arguments = base_arguments(
            "move_relative",
            entry_point="null",
            target_point="null",
            relative_motion=json.dumps(
                {"axis": "z", "direction": "positive"}
            ),
            missing_fields="[]",
            needs_confirmation="false",
            confidence="0.9",
        )
        agent, _client = make_agent(arguments)

        command = agent.parse_command("机械臂往上抬一点").command

        self.assertEqual(command.intent, CommandIntent.MOVE_SEQUENCE)
        self.assertTrue(command.needs_confirmation)
        self.assertEqual(
            command.motion_sequence.steps[0].translation_mm,
            (0.0, 0.0, 15.0),
        )

    def test_flattened_explicit_relative_fields_are_repaired(self):
        arguments = base_arguments(
            "move_relative",
            relative_motion="z",
            direction="positive",
            distance_mm=8,
            frame="robot_base",
            distance_source="user_provided",
        )
        agent, _client = make_agent(arguments)

        command = agent.parse_command(
            "机械臂沿基座坐标系Z轴正方向移动8毫米"
        ).command

        self.assertEqual(command.intent, CommandIntent.MOVE_SEQUENCE)
        step = command.motion_sequence.steps[0]
        self.assertEqual(step.translation_mm, (0.0, 0.0, 8.0))
        self.assertEqual(
            step.value_source,
            DistanceSource.USER_PROVIDED,
        )

    def test_model_facing_prefixed_relative_fields_are_assembled(self):
        arguments = base_arguments(
            "move_relative",
            relative_motion=None,
            relative_axis="z",
            relative_direction="positive",
            relative_distance_mm=8,
            relative_frame="robot_base",
            relative_distance_source="user_provided",
        )
        agent, _client = make_agent(arguments)

        command = agent.parse_command("机械臂沿Z轴正方向移动8毫米").command

        self.assertEqual(command.intent, CommandIntent.MOVE_SEQUENCE)
        self.assertEqual(
            command.motion_sequence.steps[0].translation_mm,
            (0.0, 0.0, 8.0),
        )

    def test_model_facing_combined_relative_vector_is_assembled(self):
        arguments = base_arguments(
            "move_relative",
            relative_motion=None,
            relative_delta_mm=[8, -3, 5],
            relative_frame="robot_base",
            relative_distance_source="user_provided",
        )
        agent, _client = make_agent(arguments)

        command = agent.parse_command(
            "机械臂在 Base 坐标系 X 加 8、Y 减 3、Z 加 5 毫米"
        ).command

        self.assertEqual(command.intent, CommandIntent.MOVE_SEQUENCE)
        self.assertEqual(
            command.motion_sequence.steps[0].translation_mm,
            (8.0, -3.0, 5.0),
        )

    def test_flattened_relative_fields_are_rejected_for_other_intents(self):
        arguments = base_arguments("stop", direction="positive")
        agent, _client = make_agent(arguments)

        with self.assertRaises(CommandParsingError) as raised:
            agent.parse_command("停止")

        self.assertEqual(raised.exception.details["fields"], ["direction"])

    def test_conflicting_flattened_relative_fields_are_rejected(self):
        arguments = base_arguments(
            "move_relative",
            relative_motion={"axis": "z", "direction": "negative"},
            direction="positive",
        )
        agent, _client = make_agent(arguments)

        with self.assertRaises(CommandParsingError) as raised:
            agent.parse_command("向上移动")

        self.assertIn("conflicts", str(raised.exception))

    def test_vague_up_motion_uses_runtime_default(self):
        arguments = base_arguments(
            "move_relative",
            relative_motion={"axis": "z", "direction": "positive"},
        )
        agent, _client = make_agent(arguments)

        command = agent.parse_command("机械臂往上抬一点").command

        self.assertEqual(command.intent, CommandIntent.MOVE_SEQUENCE)
        step = command.motion_sequence.steps[0]
        self.assertEqual(step.translation_mm, (0.0, 0.0, 15.0))
        self.assertEqual(
            step.value_source,
            DistanceSource.CONFIGURED_DEFAULT,
        )

    def test_ordered_translation_and_j1_rotation_sequence_is_preserved(self):
        arguments = base_arguments(
            "move_sequence",
            motion_steps=[
                {
                    "kind": "translation", "axis": "y", "direction": "positive",
                    "distance_mm": 52, "value_source": "user_provided",
                },
                {
                    "kind": "translation", "axis": "z", "direction": "positive",
                    "value_source": "configured_default",
                },
                {
                    "kind": "translation", "axis": "x", "direction": "positive",
                    "distance_mm": 74, "value_source": "user_provided",
                },
                {
                    "kind": "joint_rotation", "direction": "negative",
                    "rotation_deg": 70, "joint_index": 1,
                    "value_source": "user_provided",
                },
            ],
        )
        agent, _client = make_agent(arguments)

        command = agent.parse_command(
            "往左52mm之后再往上一点然后再往前74mm，再向右转70度"
        ).command

        self.assertEqual(command.intent, CommandIntent.MOVE_SEQUENCE)
        steps = command.motion_sequence.steps
        self.assertEqual(steps[0].translation_mm, (0.0, 52.0, 0.0))
        self.assertEqual(steps[1].translation_mm, (0.0, 0.0, 15.0))
        self.assertEqual(steps[2].translation_mm, (74.0, 0.0, 0.0))
        self.assertEqual(steps[3].joint_index, 1)
        self.assertEqual(steps[3].rotation_deg, -70.0)

    def test_explicit_relative_distance_is_preserved(self):
        arguments = base_arguments(
            "move_relative",
            relative_motion={
                "axis": "x",
                "direction": "negative",
                "distance_mm": 12,
                "frame": "robot_base",
            },
        )
        agent, _client = make_agent(arguments)

        command = agent.parse_command("沿基座 X 负方向移动12毫米").command

        step = command.motion_sequence.steps[0]
        self.assertEqual(step.translation_mm, (-12.0, 0.0, 0.0))
        self.assertEqual(
            step.value_source,
            DistanceSource.USER_PROVIDED,
        )

    def test_missing_point_unit_and_frame_use_simulation_defaults(self):
        arguments = base_arguments(
            "move_to_entry",
            entry_point={"x": 500, "y": 0, "z": 500},
        )
        agent, _client = make_agent(arguments)

        command = agent.parse_command("移动到入点(500,0,500)").command

        self.assertEqual(command.intent, CommandIntent.MOVE_SEQUENCE)
        step = command.motion_sequence.steps[0]
        self.assertEqual(step.frame, CoordinateFrame.ROBOT_BASE)
        self.assertEqual(step.target_position_mm, (500.0, 0.0, 500.0))

    def test_centimetres_are_normalized_to_millimetres(self):
        arguments = base_arguments(
            "move_to_entry",
            entry_point={
                "x": 50,
                "y": 0,
                "z": 50,
                "unit": "cm",
                "frame": "robot_base",
            },
        )
        agent, _client = make_agent(arguments)

        command = agent.parse_command("移动到基座坐标(50,0,50)厘米").command

        self.assertEqual(
            command.motion_sequence.steps[0].target_position_mm,
            (500.0, 0.0, 500.0),
        )

    def test_real_mode_missing_unit_or_frame_becomes_clarification(self):
        settings = replace(make_settings(), runtime_mode=RuntimeMode.REAL)
        arguments = base_arguments(
            "move_to_entry",
            entry_point={"x": 500, "y": 0, "z": 500},
        )
        agent, _client = make_agent(arguments, settings=settings)

        command = agent.parse_command("移动到入点(500,0,500)").command

        self.assertEqual(command.intent, CommandIntent.CLARIFY)
        self.assertTrue(command.needs_confirmation)
        self.assertIn("entry_point.unit", command.missing_fields)
        self.assertIn("entry_point.frame", command.missing_fields)

    def test_missing_required_target_is_downgraded_to_clarification(self):
        arguments = base_arguments(
            "puncture",
            entry_point={"x": 500, "y": 0, "z": 500, "unit": "mm", "frame": "robot_base"},
        )
        agent, _client = make_agent(arguments)

        command = agent.parse_command("从这个入点开始穿刺").command

        self.assertEqual(command.intent, CommandIntent.CLARIFY)
        self.assertIn("target_point", command.missing_fields)
        self.assertIsNotNone(command.entry_point)
        self.assertIsNone(command.relative_motion)

    def test_explicit_incomplete_puncture_cannot_be_downgraded_to_entry_move(self):
        arguments = base_arguments(
            "move_to_entry",
            entry_point={
                "x": 500,
                "y": 0,
                "z": 500,
                "unit": "mm",
                "frame": "robot_base",
            },
            summary="移动到入点位置",
        )
        agent, _client = make_agent(arguments)

        command = agent.parse_command(
            "从基座坐标系入点(500,0,500)毫米开始穿刺，但我还没有提供靶点。"
        ).command

        self.assertEqual(command.intent, CommandIntent.CLARIFY)
        self.assertEqual(command.missing_fields, ["target_point"])
        self.assertIn("靶点", command.summary)

    def test_explicitly_negated_puncture_can_remain_entry_only(self):
        arguments = base_arguments(
            "move_to_entry",
            entry_point={"x": 500, "y": 0, "z": 500},
        )
        agent, _client = make_agent(arguments)

        command = agent.parse_command("不要穿刺，只移动到入点(500,0,500)。").command

        self.assertEqual(command.intent, CommandIntent.MOVE_SEQUENCE)
        self.assertEqual(
            command.motion_sequence.steps[0].target_position_mm,
            (500.0, 0.0, 500.0),
        )

    def test_non_default_coordinate_frame_cannot_form_executable_motion(self):
        arguments = base_arguments(
            "move_to_entry",
            entry_point={
                "x": 100,
                "y": 200,
                "z": 0,
                "unit": "mm",
                "frame": "scene_camera",
            },
        )
        agent, _client = make_agent(arguments)

        command = agent.parse_command("移动到图像坐标(100,200,0)").command

        self.assertEqual(command.intent, CommandIntent.CLARIFY)
        self.assertIn("entry_point.coordinate_transform", command.missing_fields)

    def test_clarification_summary_is_preserved(self):
        arguments = base_arguments(
            "clarify",
            missing_fields=["coordinate_order"],
            needs_confirmation=True,
            summary="请确认三个数值是否依次为 X、Y、Z。",
        )
        agent, _client = make_agent(arguments)

        result = agent.parse_command("坐标是20、30、40")

        self.assertEqual(result.command.intent, CommandIntent.CLARIFY)
        self.assertEqual(result.clarification, "请确认三个数值是否依次为 X、Y、Z。")

    def test_coordinate_label_alias_is_canonicalized_to_coordinate_order(self):
        arguments = base_arguments(
            "clarify",
            entry_point={"x": 20, "y": 35, "z": 80},
            missing_fields=["entry_point.coordinate_labels"],
            needs_confirmation=True,
            summary="请确认三个数值分别对应哪个坐标轴。",
        )
        agent, _client = make_agent(arguments)

        command = agent.parse_command("入点的三个数是20、35、80").command

        self.assertEqual(command.intent, CommandIntent.CLARIFY)
        self.assertEqual(command.missing_fields, ["coordinate_order"])

    def test_target_point_3d_is_an_allowed_clarification_field(self):
        arguments = base_arguments(
            "clarify",
            missing_fields=["entry_point_3d", "target_point_3d"],
            needs_confirmation=True,
            summary="请标明三维入点和靶点。",
        )
        agent, _client = make_agent(arguments)

        command = agent.parse_command("坐标没有标签").command

        self.assertEqual(command.intent, CommandIntent.CLARIFY)
        self.assertEqual(
            command.missing_fields,
            ["entry_point_3d", "target_point_3d"],
        )

    def test_optional_image_is_encoded_as_a_data_url(self):
        arguments = base_arguments(
            "clarify",
            missing_fields=["entry_point_3d"],
            needs_confirmation=True,
            summary="图片没有可用的三维入点坐标。",
        )
        agent, client = make_agent(arguments)
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "scene.jpg"
            image.write_bytes(b"test-image-bytes")
            agent.parse_command("请从图中寻找入点", image_path=image)

        content = client.chat.completions.requests[0]["messages"][1]["content"]
        self.assertEqual(content[0]["type"], "image_url")
        self.assertTrue(content[0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(content[1], {"type": "text", "text": "请从图中寻找入点"})

    def test_stop_and_emergency_stop_do_not_accept_motion_payloads(self):
        for intent in ("stop", "emergency_stop"):
            with self.subTest(intent=intent):
                agent, _client = make_agent(base_arguments(intent))
                command = agent.parse_command(intent).command
                self.assertEqual(command.intent.value, intent)
                self.assertIsNone(command.entry_point)
                self.assertIsNone(command.relative_motion)

    def test_no_tool_call_has_stable_error(self):
        client = FakeInternS2Client(calls=None)
        agent = InternS2Agent(make_settings(), client=client)

        with self.assertRaises(CommandParsingError) as raised:
            agent.parse_command("无关问题")

        self.assertEqual(raised.exception.error_code, ErrorCode.MODEL_NO_TOOL_CALL)

    def test_invalid_json_has_stable_error(self):
        client = FakeInternS2Client(calls=[tool_call("{not-json")])
        agent = InternS2Agent(make_settings(), client=client)

        with self.assertRaises(CommandParsingError) as raised:
            agent.parse_command("测试")

        self.assertEqual(raised.exception.error_code, ErrorCode.MODEL_INVALID_OUTPUT)
        self.assertIn("line", raised.exception.details)

    def test_invalid_embedded_json_has_stable_error(self):
        arguments = base_arguments(
            "move_to_entry",
            entry_point="{not-json",
        )
        agent, _client = make_agent(arguments)

        with self.assertRaises(CommandParsingError) as raised:
            agent.parse_command("移动到入点")

        self.assertEqual(raised.exception.error_code, ErrorCode.MODEL_INVALID_OUTPUT)
        self.assertEqual(raised.exception.details["field"], "entry_point")

    def test_unknown_or_multiple_tool_calls_are_rejected(self):
        agent, _client = make_agent(base_arguments("stop"), name="move_robot")
        with self.assertRaises(CommandParsingError):
            agent.parse_command("停止")

        calls = [tool_call(base_arguments("stop"), call_id="a"), tool_call(base_arguments("stop"), call_id="b")]
        client = FakeInternS2Client(calls=calls)
        agent = InternS2Agent(make_settings(), client=client)
        with self.assertRaises(CommandParsingError) as raised:
            agent.parse_command("停止")
        self.assertEqual(raised.exception.details["tool_call_count"], 2)

    def test_unknown_argument_field_is_rejected(self):
        arguments = base_arguments("stop", joint_angles=[0, 0, 0, 0, 0, 0])
        agent, _client = make_agent(arguments)

        with self.assertRaises(CommandParsingError) as raised:
            agent.parse_command("停止")

        self.assertEqual(raised.exception.error_code, ErrorCode.MODEL_INVALID_OUTPUT)

    def test_semantically_invalid_command_returns_serializable_validation_details(self):
        point = {"x": 500, "y": 0, "z": 500, "unit": "mm", "frame": "robot_base"}
        agent, _client = make_agent(
            base_arguments(
                "puncture",
                entry_point=point,
                target_point=point,
            )
        )

        with self.assertRaises(CommandParsingError) as raised:
            agent.parse_command("入点和靶点相同")

        payload = raised.exception.as_dict()
        self.assertEqual(payload["code"], ErrorCode.MODEL_INVALID_OUTPUT.value)
        self.assertTrue(payload["details"]["errors"])

    def test_timeout_has_stable_error_and_no_command(self):
        client = FakeInternS2Client(error=TimeoutError("slow"))
        agent = InternS2Agent(make_settings(), client=client)

        with self.assertRaises(CommandParsingError) as raised:
            agent.parse_command("移动")

        self.assertEqual(raised.exception.error_code, ErrorCode.MODEL_TIMEOUT)

    def test_model_is_discovered_when_not_configured(self):
        client = FakeInternS2Client(calls=[tool_call(base_arguments("stop"))])
        agent = InternS2Agent(make_settings(model=None), client=client)

        self.assertEqual(agent.model, "discovered-interns2")

    def test_empty_prompt_is_rejected_without_calling_model(self):
        client = FakeInternS2Client(calls=[tool_call(base_arguments("stop"))])
        agent = InternS2Agent(make_settings(), client=client)

        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            agent.parse_command("   ")

        self.assertEqual(client.chat.completions.requests, [])


if __name__ == "__main__":
    unittest.main()
