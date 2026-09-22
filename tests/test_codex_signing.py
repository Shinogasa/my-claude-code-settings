#!/usr/bin/env python3
"""Codex の Bitwarden SSH agent 設定ヘルパーを検証する。"""
import importlib.util
import io
import os
import stat
import sys
import tempfile
import unittest
import shutil
import subprocess
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "configure_codex_signing.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("configure_codex_signing", SCRIPT)
if spec is None or spec.loader is None:
    raise ImportError(f"failed to load {SCRIPT}")
signing = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = signing
spec.loader.exec_module(signing)


@contextmanager
def bound_unix_socket(path: Path):
    # sandboxではAF_UNIXのbindが禁止されるため、agent検査は個別にmockする。
    path.touch()
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


class CodexSigningTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        # macOSのtempfileが返す`/var` symlinkを安全検査へ混ぜない。
        self.base = Path(self.temporary.name).resolve()
        self.home = self.base / "home"
        self.home.mkdir()
        self.config = self.home / ".codex" / "config.toml"
        self.config.parent.mkdir()
        self.socket_path = self.base / "bitwarden-agent.sock"
        self.bin = self.base / "bin"
        self.bin.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def install_ssh_add(self, exit_code: int = 0):
        ssh_add = self.bin / "ssh-add"
        ssh_add.write_text(
            "#!/bin/sh\n"
            "printf 'agent-output-must-not-leak\n'\n"
            f"exit {exit_code}\n",
            encoding="utf-8",
        )
        ssh_add.chmod(0o755)

    def run_helper(self, *extra_args: str):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.object(signing, "_probe_agent", return_value=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                returncode = signing.main([str(self.config), *extra_args])
        return SimpleNamespace(
            returncode=returncode,
            stdout=stdout.getvalue(),
            stderr=stderr.getvalue(),
        )

    def write_private_config(self, content: str) -> None:
        self.config.write_text(content, encoding="utf-8")
        self.config.chmod(0o600)

    def test_updates_only_target_key_and_preserves_comments_and_unrelated_values(self):
        self.write_private_config(
            'model = "gpt-test"\n'
            '[private]\n'
            'token = "do-not-print-this"\n'
            '[shell_environment_policy]\n'
            'inherit = "core"\n'
            '[shell_environment_policy.set]\n'
            'PATH = "/usr/bin"\n'
            'SSH_AUTH_SOCK = "/tmp/old-agent.sock" # keep this comment\n',
        )
        self.install_ssh_add()

        with bound_unix_socket(self.socket_path):
            result = self.run_helper("--socket", str(self.socket_path))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("agent-output-must-not-leak", result.stdout + result.stderr)
        updated = self.config.read_text(encoding="utf-8")
        self.assertIn('token = "do-not-print-this"', updated)
        self.assertIn('PATH = "/usr/bin"', updated)
        self.assertIn('# keep this comment', updated)
        parsed = signing.tomllib.loads(updated)
        self.assertEqual(
            parsed["shell_environment_policy"]["set"]["SSH_AUTH_SOCK"],
            str(self.socket_path),
        )

    def test_adds_missing_table_and_key(self):
        self.write_private_config('model = "gpt-test"\n')
        self.install_ssh_add()

        with bound_unix_socket(self.socket_path):
            result = self.run_helper("--socket", str(self.socket_path))

        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = signing.tomllib.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual(
            parsed["shell_environment_policy"]["set"]["SSH_AUTH_SOCK"],
            str(self.socket_path),
        )

    def test_preserves_crlf_when_adding_missing_table(self):
        self.config.write_bytes(b'model = "gpt-test"\r\n')
        self.config.chmod(0o600)

        with patch.object(signing, "_probe_agent", return_value=True):
            result = signing.configure(self.config, self.socket_path)

        self.assertEqual(result.kind, "updated")
        updated = self.config.read_bytes()
        self.assertIn(b"model = \"gpt-test\"\r\n", updated)
        self.assertIn(b"[shell_environment_policy.set]\r\n", updated)
        self.assertIn(b"SSH_AUTH_SOCK = ", updated)
        self.assertNotIn(b"\n[shell_environment_policy.set]", updated.replace(b"\r\n", b""))

    def test_second_run_is_byte_and_mtime_idempotent(self):
        self.write_private_config(
            '[shell_environment_policy.set]\n'
            f'SSH_AUTH_SOCK = "{self.socket_path}"\n',
        )
        self.install_ssh_add()

        with bound_unix_socket(self.socket_path):
            first = self.run_helper("--socket", str(self.socket_path))
            first_bytes = self.config.read_bytes()
            first_stat = self.config.stat()
            second = self.run_helper("--socket", str(self.socket_path))
            second_bytes = self.config.read_bytes()
            second_stat = self.config.stat()

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(first_stat.st_mtime_ns, second_stat.st_mtime_ns)
        self.assertEqual(stat.S_IMODE(first_stat.st_mode), stat.S_IMODE(second_stat.st_mode))

    def test_skips_without_agent_identity_and_does_not_mutate_config(self):
        original = '[shell_environment_policy.set]\nSSH_AUTH_SOCK = "/tmp/old.sock"\n'
        self.write_private_config(original)

        with bound_unix_socket(self.socket_path):
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch.object(signing, "_probe_agent", return_value=False):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    returncode = signing.main([str(self.config), "--socket", str(self.socket_path)])
            result = SimpleNamespace(
                returncode=returncode,
                stdout=stdout.getvalue(),
                stderr=stderr.getvalue(),
            )

        self.assertEqual(result.returncode, signing.SKIPPED_EXIT)
        self.assertEqual(self.config.read_text(encoding="utf-8"), original)
        self.assertNotIn("agent-output-must-not-leak", result.stdout + result.stderr)

    def test_rejects_malformed_or_duplicate_target_without_mutation(self):
        fixtures = (
            "[shell_environment_policy.set\nSSH_AUTH_SOCK = \"x\"\n",
            '[shell_environment_policy.set]\n'
            'SSH_AUTH_SOCK = "one"\n'
            '"SSH_AUTH_SOCK" = "two"\n',
        )
        self.install_ssh_add()
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                self.write_private_config(fixture)
                original = self.config.read_bytes()
                with bound_unix_socket(self.socket_path):
                    result = self.run_helper("--socket", str(self.socket_path))
                self.assertEqual(result.returncode, 1)
                self.assertEqual(self.config.read_bytes(), original)

    def test_missing_config_is_a_non_mutating_skip(self):
        self.install_ssh_add()
        with bound_unix_socket(self.socket_path):
            result = self.run_helper("--socket", str(self.socket_path))
        self.assertEqual(result.returncode, signing.SKIPPED_EXIT)
        self.assertFalse(self.config.exists())

    def test_socket_discovery_is_home_based_and_darwin_only(self):
        expected = self.home / "Library/Containers/com.bitwarden.desktop/Data/.bitwarden-ssh-agent.sock"
        self.assertEqual(signing.discover_socket(self.home, system="Darwin"), expected)
        self.assertIsNone(signing.discover_socket(self.home, system="Linux"))

    def test_agent_probe_suppresses_agent_output(self):
        self.install_ssh_add()
        with bound_unix_socket(self.socket_path):
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch.object(Path, "is_socket", return_value=True):
                with patch.dict(
                    os.environ,
                    {"PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"},
                ):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        available = signing._probe_agent(self.socket_path)
        self.assertTrue(available)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_rejects_non_private_config_without_mutation(self):
        original = b'model = "gpt-test"\n'
        self.config.write_bytes(original)
        self.config.chmod(0o640)

        with patch.object(signing, "_probe_agent", return_value=True):
            with self.assertRaises(signing.ConfigurationError):
                signing.configure(self.config, self.socket_path)

        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o640)

    def test_successful_update_preserves_extended_metadata_on_macos(self):
        xattr = shutil.which("xattr")
        chmod = shutil.which("chmod")
        ls = shutil.which("ls")
        if sys.platform != "darwin" or None in {xattr, chmod, ls}:
            self.skipTest("macOSのmetadata保持検査ではない")
        self.write_private_config('model = "gpt-test"\n')
        subprocess.run(
            [xattr, "-w", "com.example.codex-signing-test", "preserve-me", self.config],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [chmod, "+a", "everyone deny write", self.config],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        with patch.object(signing, "_probe_agent", return_value=True):
            outcome = signing.configure(self.config, self.socket_path)

        self.assertEqual(outcome.kind, "updated")
        attribute = subprocess.run(
            [xattr, "-p", "com.example.codex-signing-test", self.config],
            check=True,
            capture_output=True,
            text=True,
        )
        acl = subprocess.run(
            [ls, "-le", self.config],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(attribute.stdout.rstrip("\n"), "preserve-me")
        self.assertIn("deny write", acl.stdout)


if __name__ == "__main__":
    unittest.main()
