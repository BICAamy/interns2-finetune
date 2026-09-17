"""Static and fail-closed checks for the app-local service entry points.

These tests never start the four services or access the robot.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
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

    def test_bash_syntax(self) -> None:
        scripts = (
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

    def test_real_mode_without_config_is_rejected_before_launch(self) -> None:
        result = subprocess.run(
            ["bash", str(SERVICE_SCRIPTS / "start_all.sh"), "--robot-mode", "real"],
            cwd=APP_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires --real-config", output)
        self.assertNotIn("[1/4] Starting", output)
        self.assertNotIn("unbound variable", output)


if __name__ == "__main__":
    unittest.main()
