from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
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
    def test_api_key_can_be_read_from_an_untracked_file(self):
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "interns2.key"
            key_file.write_text("test-secret\n", encoding="utf-8")
            with patch.dict(
                "os.environ",
                {"INTERNS2_API_KEY_FILE": str(key_file)},
                clear=True,
            ):
                self.assertEqual(AgentSettings.from_env().api_key, "test-secret")

    def test_api_key_file_conflicts_with_a_direct_key(self):
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "interns2.key"
            key_file.write_text("file-secret", encoding="utf-8")
            with patch.dict(
                "os.environ",
                {
                    "INTERNS2_API_KEY": "direct-secret",
                    "INTERNS2_API_KEY_FILE": str(key_file),
                },
                clear=True,
            ):
                with self.assertRaisesRegex(ValueError, "only one"):
                    AgentSettings.from_env()

    def test_api_key_file_must_exist_and_not_be_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.key"
            with patch.dict(
                "os.environ",
                {"INTERNS2_API_KEY_FILE": str(missing)},
                clear=True,
            ):
                with self.assertRaisesRegex(ValueError, "missing or unreadable"):
                    AgentSettings.from_env()

            empty = Path(directory) / "empty.key"
            empty.write_text("\n", encoding="utf-8")
            with patch.dict(
                "os.environ",
                {"INTERNS2_API_KEY_FILE": str(empty)},
                clear=True,
            ):
                with self.assertRaisesRegex(ValueError, "cannot be empty"):
                    AgentSettings.from_env()

    def test_real_environment_requires_config_without_a_control_mode(self):
        base = {
            "RUNTIME_MODE": "real",
            "ROBOT_MODE": "real",
            "REAL_CONFIG_PATH": "/tmp/robot-real.local.yaml",
        }
        with patch.dict("os.environ", base, clear=True):
            self.assertEqual(AgentSettings.from_env().runtime_mode.value, "real")
        with patch.dict("os.environ", {**base, "REAL_CONFIG_PATH": ""}, clear=True):
            with self.assertRaisesRegex(ValueError, "config path"):
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
        self.assertEqual(value.default_relative_step_mm, 15.0)
        self.assertEqual(value.default_relative_rotation_deg, 15.0)
        self.assertEqual(value.default_rotation_joint_index, 1)
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

    def test_default_rotation_joint_must_be_a_physical_joint(self):
        with self.assertRaisesRegex(ValueError, "from 1 to 6"):
            replace(settings(), default_rotation_joint_index=7).validate()

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
