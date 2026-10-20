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
            "stop_all.sh",
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

    def test_invalid_web_variant_is_rejected_before_launch(self) -> None:
        environment = os.environ.copy()
        environment["INTERNS2_WEB_VARIANT"] = "unsupported"
        result = subprocess.run(
            ["bash", str(SERVICE_SCRIPTS / "start_all.sh"), "--check-config"],
            cwd=APP_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be web, web_inside, or both", output)
        self.assertNotIn("[1/4] Starting", output)

    def test_web_variants_share_one_backend_and_control_plane(self) -> None:
        content = (SERVICE_SCRIPTS / "start_all.sh").read_text(encoding="utf-8")
        self.assertIn('WEB_VARIANT="${INTERNS2_WEB_VARIANT:-web}"', content)
        self.assertIn("web|web_inside|both", content)
        self.assertEqual(content.count("-m web.backend.main"), 1)
        self.assertNotIn("-m web_inside.backend.main", content)
        self.assertIn("http://127.0.0.1:8000/inside/", content)

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

    def test_stop_all_targets_only_the_start_all_supervisor(self) -> None:
        start = (SERVICE_SCRIPTS / "start_all.sh").read_text(encoding="utf-8")
        stop = (SERVICE_SCRIPTS / "stop_all.sh").read_text(encoding="utf-8")

        self.assertIn('SUPERVISOR_PID_FILE="$SERVICE_STATE_DIR/start_all.pid"', start)
        self.assertIn('printf \'%s\\n\' "$$" > "$SUPERVISOR_PID_FILE"', start)
        self.assertIn('printf \'%s\\n\' "$INTERNS2_INFERENCE_MODE"', start)
        self.assertIn('PIDS+=("$INFERENCE_PID")', start)
        self.assertIn('kill -TERM "$SUPERVISOR_PID"', stop)
        self.assertNotIn("pkill", stop)
        self.assertNotIn("INFERENCE_PID", stop)
        self.assertNotIn("23333", stop)

    def test_start_all_runs_under_a_detached_session_supervisor(self) -> None:
        content = (SERVICE_SCRIPTS / "start_all.sh").read_text(encoding="utf-8")

        self.assertIn("nohup setsid env", content)
        self.assertIn("_INTERNS2_START_ALL_SUPERVISOR=1", content)
        self.assertIn('</dev/null >>"$SUPERVISOR_LOG" 2>&1 &', content)
        self.assertIn('write_atomic_file "$SUPERVISOR_STATE_FILE" "ready"', content)
        self.assertIn("Services are running independently of this SSH terminal.", content)
        self.assertNotIn("Keep this terminal open.", content)
        self.assertNotIn("Press Ctrl+C to stop the whole system.", content)

    def test_resolved_real_config_is_exported_only_inside_supervisor(self) -> None:
        content = (SERVICE_SCRIPTS / "start_all.sh").read_text(encoding="utf-8")
        detach_boundary = content.index(
            'if [[ "$INTERNAL_SUPERVISOR" != 1 ]]; then\n'
            "    launch_detached_supervisor"
        )
        resolved_path_export = content.index("    export REAL_CONFIG_PATH\n")

        self.assertGreater(resolved_path_export, detach_boundary)
        self.assertIn(
            'REAL_CONFIG_PATH="$REAL_CONFIG_PATH" \\\n'
            '            PYTHONPATH="$APP_ROOT/packages/surgical_contracts:$APP_ROOT"',
            content,
        )

    def test_stop_all_removes_detached_supervisor_state(self) -> None:
        content = (SERVICE_SCRIPTS / "stop_all.sh").read_text(encoding="utf-8")

        self.assertIn('SUPERVISOR_STATE_FILE="$SERVICE_STATE_DIR/start_all.state"', content)
        self.assertIn('"$SUPERVISOR_STATE_FILE"', content)
        self.assertIn('"$SERVICE_STATE_DIR"/startup.*', content)

    def test_stop_all_api_mode_leaves_external_process_running(self) -> None:
        external = subprocess.Popen(["sleep", "30"])
        supervisor = None
        try:
            supervisor = subprocess.Popen(
                [
                    "bash",
                    "-c",
                    'trap "exit 0" TERM; while :; do sleep 1; done',
                    "scripts/services/start_all.sh",
                ],
                cwd=APP_ROOT,
            )
            with tempfile.TemporaryDirectory() as directory:
                state_dir = Path(directory)
                (state_dir / "start_all.pid").write_text(
                    f"{supervisor.pid}\n",
                    encoding="utf-8",
                )
                (state_dir / "inference_mode").write_text(
                    "api\n",
                    encoding="utf-8",
                )
                (state_dir / "start_all.state").write_text(
                    "ready\n",
                    encoding="utf-8",
                )
                (state_dir / "startup.test").write_text(
                    "ready\n",
                    encoding="utf-8",
                )
                environment = os.environ.copy()
                environment.update({
                    "SERVICE_STATE_DIR": str(state_dir),
                    "STOP_TIMEOUT_SECONDS": "5",
                })
                result = subprocess.run(
                    ["bash", str(SERVICE_SCRIPTS / "stop_all.sh")],
                    cwd=APP_ROOT,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertFalse((state_dir / "start_all.pid").exists())
                self.assertFalse((state_dir / "start_all.state").exists())
                self.assertFalse((state_dir / "startup.test").exists())

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "external InternS2 API/model service is still running",
                result.stdout,
            )
            supervisor.wait(timeout=2)
            self.assertIsNone(external.poll())
        finally:
            if supervisor is not None and supervisor.poll() is None:
                supervisor.terminate()
                supervisor.wait(timeout=2)
            if external.poll() is None:
                external.terminate()
            external.wait(timeout=2)


if __name__ == "__main__":
    unittest.main()
