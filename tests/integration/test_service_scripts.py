"""Static and fail-closed checks for the app-local service entry points.

These tests never start the four services or access the robot.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


APP_ROOT = Path(__file__).resolve().parents[2]
SERVICE_SCRIPTS = APP_ROOT / "scripts" / "services"


class ServiceScriptsTest(unittest.TestCase):
    def test_service_logs_are_inside_app(self) -> None:
        expected = 'LOG_DIR="$APP_ROOT/logs/services"'
        for name in ("start_all.sh", "logs.sh"):
            with self.subTest(script=name):
                content = (SERVICE_SCRIPTS / name).read_text(encoding="utf-8")
                self.assertIn(expected, content)
                self.assertNotIn('LOG_DIR="$BUNDLE_ROOT/logs/services"', content)

    def test_real_startup_has_no_removed_config_sha_reference(self) -> None:
        content = (SERVICE_SCRIPTS / "start_all.sh").read_text(encoding="utf-8")
        self.assertNotIn("CONFIG_SHA", content)
        self.assertNotIn("REAL_CONFIG_SHA256", content)

    def test_bash_syntax(self) -> None:
        scripts = (
            "interns2_config.sh",
            "start_all.sh",
            "health_check.sh",
            "status.sh",
            "logs.sh",
        )
        result = subprocess.run(
            ["bash", "-n", *(str(SERVICE_SCRIPTS / name) for name in scripts)],
            cwd=APP_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_robot_mode_is_rejected_before_launch(self) -> None:
        result = subprocess.run(
            [
                "bash",
                str(SERVICE_SCRIPTS / "start_all.sh"),
                "--robot-mode",
                "unsupported",
            ],
            cwd=APP_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be simulation or real", output)
        self.assertNotIn("[1/4] Starting", output)
        self.assertNotIn("unbound variable", output)

    def test_interns2_api_mode_reads_a_secret_file(self) -> None:
        helper = SERVICE_SCRIPTS / "interns2_config.sh"
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "interns2.key"
            key_file.write_text("test-secret\n", encoding="utf-8")
            environment = os.environ.copy()
            environment.update(
                {
                    "INTERNS2_INFERENCE_MODE": "api",
                    "INTERNS2_BASE_URL": "http://127.0.0.1:23333/v1/",
                    "INTERNS2_API_KEY_FILE": str(key_file),
                }
            )
            environment.pop("INTERNS2_API_KEY", None)
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; interns2_configure "$2"; '
                    'printf "%s|%s|%s|%s" "$INTERNS2_INFERENCE_MODE" '
                    '"$INTERNS2_BASE_URL" "${#INTERNS2_API_KEY}" '
                    '"$INTERNS2_MODEL"',
                    "bash",
                    str(helper),
                    str(APP_ROOT),
                ],
                cwd=APP_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "api|http://127.0.0.1:23333/v1|11|interns2-medlora",
        )
        self.assertNotIn("test-secret", result.stdout + result.stderr)

    def test_interns2_api_mode_requires_a_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = os.environ.copy()
            environment.update({"INTERNS2_INFERENCE_MODE": "api"})
            environment.pop("INTERNS2_API_KEY", None)
            environment.pop("INTERNS2_API_KEY_FILE", None)
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; interns2_configure "$2"',
                    "bash",
                    str(SERVICE_SCRIPTS / "interns2_config.sh"),
                    directory,
                ],
                cwd=APP_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing or unreadable", result.stderr)

    def test_interns2_api_mode_also_accepts_a_direct_key(self) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "INTERNS2_INFERENCE_MODE": "api",
                "INTERNS2_API_KEY": "direct-test-secret",
            }
        )
        environment.pop("INTERNS2_API_KEY_FILE", None)
        result = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; interns2_configure "$2"; '
                'printf "%s|%s|%s" "$INTERNS2_BASE_URL" '
                '"$INTERNS2_MODEL" "${#INTERNS2_API_KEY}"',
                "bash",
                str(SERVICE_SCRIPTS / "interns2_config.sh"),
                str(APP_ROOT),
            ],
            cwd=APP_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "http://127.0.0.1:23333/v1|interns2-medlora|18",
        )
        self.assertNotIn("direct-test-secret", result.stdout + result.stderr)

    def test_interns2_local_mode_uses_the_bundled_endpoint(self) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "INTERNS2_INFERENCE_MODE": "local",
                "INTERNS2_BASE_URL": "https://unused.example/v1",
                "INTERNS2_API_KEY": "unused-secret",
            }
        )
        environment.pop("INTERNS2_API_KEY_FILE", None)
        result = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; interns2_configure "$2"; '
                'printf "%s|%s|%s" "$INTERNS2_INFERENCE_MODE" '
                '"$INTERNS2_BASE_URL" "$INTERNS2_API_KEY"',
                "bash",
                str(SERVICE_SCRIPTS / "interns2_config.sh"),
                str(APP_ROOT),
            ],
            cwd=APP_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            "local|http://127.0.0.1:23333/v1|EMPTY",
        )

    def test_agent_web_does_not_override_the_selected_inference_endpoint(self) -> None:
        content = (SERVICE_SCRIPTS / "start_all.sh").read_text(encoding="utf-8")
        self.assertNotIn(
            "export INTERNS2_BASE_URL=http://127.0.0.1:23333/v1",
            content,
        )
        self.assertIn('if [[ "$INTERNS2_INFERENCE_MODE" == local ]]', content)


if __name__ == "__main__":
    unittest.main()
