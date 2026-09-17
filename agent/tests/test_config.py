from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

from agent.config import AgentSettings
from surgical_contracts import CoordinateFrame


def settings() -> AgentSettings:
    return AgentSettings(
        base_url="http://127.0.0.1:23333/v1",
        api_key="EMPTY",
        model="interns2-test",
        timeout=30,
        max_retries=0,
        max_tokens=512,
        temperature=0,
        top_p=0.95,
        max_tool_rounds=3,
    )


class AgentSettingsTests(unittest.TestCase):
    def test_real_environment_is_observe_only_and_requires_config(self):
        base = {
            "RUNTIME_MODE": "real",
            "ROBOT_MODE": "real",
            "ROBOT_CONTROL_MODE": "observe-only",
            "REAL_CONFIG_PATH": "/tmp/robot-real.local.yaml",
            "REAL_CONFIG_SHA256": "a" * 64,
        }
        with patch.dict("os.environ", base, clear=True):
            self.assertEqual(AgentSettings.from_env().runtime_mode.value, "real")
        with patch.dict("os.environ", {**base, "ROBOT_CONTROL_MODE": "enabled"}, clear=True):
            with self.assertRaisesRegex(ValueError, "observe-only"):
                AgentSettings.from_env()
        with patch.dict("os.environ", {**base, "REAL_CONFIG_PATH": ""}, clear=True):
            with self.assertRaisesRegex(ValueError, "config path"):
                AgentSettings.from_env()
        with patch.dict("os.environ", {**base, "REAL_CONFIG_SHA256": "invalid"}, clear=True):
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                AgentSettings.from_env()

    def test_environment_mode_conflict_is_rejected(self):
        with patch.dict(
            "os.environ",
            {"RUNTIME_MODE": "real", "ROBOT_MODE": "simulation"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "disagree"):
                AgentSettings.from_env()

    def test_step7_defaults_are_valid(self):
        value = settings()
        value.validate()
        self.assertEqual(value.default_relative_step_mm, 5.0)
        self.assertEqual(value.default_coordinate_frame, CoordinateFrame.ROBOT_BASE)
        self.assertEqual(value.entry_tolerance_mm, 1.0)
        self.assertEqual(value.max_relative_translation_mm, 20.0)
        self.assertFalse(value.puncture_execution_enabled)

    def test_first_version_rejects_a_non_base_default_frame(self):
        value = replace(
            settings(),
            default_coordinate_frame=CoordinateFrame.SCENE_CAMERA,
        )
        with self.assertRaisesRegex(ValueError, "must be robot_base"):
            value.validate()

    def test_move_speed_cannot_exceed_safety_limit(self):
        value = replace(
            settings(),
            robot_move_speed_mm_s=11.0,
            max_robot_speed_mm_s=10.0,
        )
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            value.validate()

    def test_puncture_execution_cannot_be_enabled(self):
        value = replace(settings(), puncture_execution_enabled=True)
        with self.assertRaisesRegex(ValueError, "must remain false"):
            value.validate()


if __name__ == "__main__":
    unittest.main()
