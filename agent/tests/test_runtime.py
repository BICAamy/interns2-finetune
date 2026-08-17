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

        self.assertEqual(command.intent, CommandIntent.MOVE_RELATIVE)
        self.assertFalse(command.needs_confirmation)
        self.assertEqual(command.relative_motion.distance_mm, 5.0)

    def test_vague_up_motion_uses_runtime_default(self):
        arguments = base_arguments(
            "move_relative",
            relative_motion={"axis": "z", "direction": "positive"},
        )
        agent, _client = make_agent(arguments)

        command = agent.parse_command("机械臂往上抬一点").command

        self.assertEqual(command.intent, CommandIntent.MOVE_RELATIVE)
        self.assertEqual(command.relative_motion.axis, Axis.Z)
        self.assertEqual(command.relative_motion.direction, Direction.POSITIVE)
        self.assertEqual(command.relative_motion.distance_mm, 5.0)
        self.assertEqual(
            command.relative_motion.distance_source,
            DistanceSource.CONFIGURED_DEFAULT,
        )

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

        self.assertEqual(command.relative_motion.translation_mm(), (-12.0, 0.0, 0.0))
        self.assertEqual(
            command.relative_motion.distance_source,
            DistanceSource.USER_PROVIDED,
        )

    def test_missing_point_unit_and_frame_use_simulation_defaults(self):
        arguments = base_arguments(
            "move_to_entry",
            entry_point={"x": 500, "y": 0, "z": 500},
        )
        agent, _client = make_agent(arguments)

        command = agent.parse_command("移动到入点(500,0,500)").command

        self.assertEqual(command.intent, CommandIntent.MOVE_TO_ENTRY)
        self.assertEqual(command.entry_point.frame, CoordinateFrame.ROBOT_BASE)
        self.assertEqual(command.entry_point.unit.value, "mm")

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

        self.assertEqual(command.entry_point.as_tuple(), (500.0, 0.0, 500.0))

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
