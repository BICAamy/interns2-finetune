"""Native journal ownership and source-only gateway packaging; no robot I/O."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest

from edge_gateway.command_journal import CommandJournal
from edge_gateway import file_support
from surgical_contracts import gateway_wire

ROOT = Path(__file__).resolve().parents[3]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts/edge" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def environment():
    result = os.environ.copy()
    result["PYTHONPATH"] = os.pathsep.join([str(ROOT / "packages/surgical_contracts"), str(ROOT)])
    result["PYTHONIOENCODING"] = "utf-8"
    return result


def test_native_journal_lock_blocks_another_process_and_releases_after_close(tmp_path):
    path = tmp_path / "space 中文" / "commands.journal"
    child = """from edge_gateway.command_journal import CommandJournal, JournalError
import sys
try:
    journal = CommandJournal(sys.argv[1])
except JournalError:
    sys.exit(3)
else:
    journal.close()
"""
    def probe():
        return subprocess.run([sys.executable, "-c", child, str(path)], env=environment(),
                              capture_output=True, text=True, timeout=10)
    with CommandJournal(path) as journal:
        journal.prepare(command_id="check", fingerprint="fp", session_id="session",
                        safety_state_hash="state", start_sequence=0, encoded_frame=b"not-sent")
        result = probe()
        assert result.returncode == 3, result.stderr
    result = probe()
    assert result.returncode == 0, result.stderr
    with CommandJournal(path) as journal:
        assert journal.record("check")["state"] == "prepared"
        journal.transition("check", "not_sent", evidence="no send-start marker")
    with CommandJournal(path) as journal:
        assert journal.unresolved() == ()


def test_windows_lock_adapter_locks_and_unlocks_the_same_byte(tmp_path, monkeypatch):
    calls = []
    fake = SimpleNamespace(LK_NBLCK=10, LK_UNLCK=20,
                           locking=lambda fd, mode, count: calls.append((os.lseek(fd, 0, os.SEEK_CUR), mode, count)))
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    monkeypatch.setattr(file_support, "WINDOWS", True)
    with (tmp_path / "lock").open("w+b") as lock:
        lock.seek(10)
        file_support.lock_exclusive(lock.fileno())
        lock.seek(30)
        file_support.unlock(lock.fileno())
    assert calls == [(0, 10, 1), (0, 20, 1)]


def test_windows_directory_flush_does_not_open_an_unsupported_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(file_support, "WINDOWS", True)
    monkeypatch.setattr(file_support.os, "open", lambda *_a, **_kw: pytest.fail("opened directory on Windows"))
    file_support.sync_parent_directory(tmp_path / "journal")


def test_windows_secret_load_uses_acl_without_calling_unix_getuid(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway_wire, "_WINDOWS", True)
    monkeypatch.setattr(os, "getuid", lambda: pytest.fail("Unix-only getuid called on Windows"), raising=False)
    path = tmp_path / "key"
    path.write_bytes(b"x" * 48)
    assert gateway_wire.load_gateway_secret(path) == b"x" * 48
    path.write_bytes(b"short")
    with pytest.raises(ValueError, match="32"):
        gateway_wire.load_gateway_secret(path)
    with pytest.raises(ValueError, match="regular"):
        gateway_wire.load_gateway_secret(tmp_path)


def test_light_package_has_no_server_runtime_and_imports_without_source_checkout(tmp_path):
    package = load_script("package_gateway")
    archive_path = package.build_package(ROOT, tmp_path / "gateway.zip")
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        assert not any("gateway-auth.local" in name for name in names)
        assert not any("robot-real.local.yaml" in name for name in names)
        assert not any(any(segment in name.split("/") for segment in ("runtime", "models", "software", "third_party", "logs")) for name in names)
        assert not any(name.endswith((".exe", ".dll", ".so", ".STL", ".stl")) for name in names)
        assert "interns2-edge-gateway/scripts/edge/start_gateway.ps1" in names
        assert archive_path.stat().st_size < 1024 * 1024
        archive.extractall(tmp_path / "extract with 中文 spaces")
    extracted = tmp_path / "extract with 中文 spaces" / "interns2-edge-gateway"
    result = subprocess.run(
        [sys.executable, str(extracted / "scripts/edge/launch_gateway.py"), "--help"],
        cwd=tmp_path, env={**os.environ, "PYTHONPATH": "", "PYTHONIOENCODING": "utf-8"},
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "--real-config" in result.stdout
    # Check all offline-only imports in the extracted package, without any
    # local private config/key or source checkout on sys.path.
    code = """import sys
from pathlib import Path
root=Path(sys.argv[1])
sys.path[:0]=[str(root),str(root/'packages/surgical_contracts')]
from edge_gateway.command_journal import CommandJournal
from edge_gateway.commissioning_runtime import make_joint_fk
from simulation.entry_point_env import E05ProKinematics
from simulation.entry_point_env.config import EntryPointEnvConfig
assert EntryPointEnvConfig.from_yaml(root/'configs/simulation.yaml').robot.force_flange_offset_mm == 184
assert 'Sofa' not in sys.modules
"""
    result = subprocess.run([sys.executable, "-c", code, str(extracted)], cwd=tmp_path,
                            env=environment(), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_real_launcher_overrides_defaults_but_keeps_fake_mode_explicit():
    launch = load_script("launch_gateway")
    actual = launch.gateway_arguments(["--server-url", "ws://127.0.0.1:28001/v1/gateway/connect"])
    assert actual[-2:] == ["--server-url", "ws://127.0.0.1:28001/v1/gateway/connect"]
    assert "--connect-real" in actual
    fake = ["--fake-command-port", "1234", "--fake-datasheet-port", "2345"]
    assert launch.gateway_arguments(fake) == fake
