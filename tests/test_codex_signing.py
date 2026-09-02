#!/usr/bin/env python3
"""Codex の Bitwarden SSH agent 設定ヘルパーを検証する。"""
import importlib.util
import os
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "configure_codex_signing.py"
spec = importlib.util.spec_from_file_location("configure_codex_signing", SCRIPT)
if spec is None or spec.loader is None:
    raise ImportError(f"failed to load {SCRIPT}")
signing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signing)


@contextmanager
def bound_unix_socket(path: Path):
    agent_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    agent_socket.bind(str(path))
    try:
        yield
    finally:
        agent_socket.close()
        path.unlink(missing_ok=True)


class CodexSigningTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
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
        environment = os.environ.copy()
        environment.update(
            {
                "HOME": str(self.home),
                "PATH": f"{self.bin}{os.pathsep}{environment['PATH']}",
            }
        )
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(self.config), *extra_args],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )

    def test_updates_only_target_key_and_preserves_comments_and_unrelated_values(self):
        self.config.write_text(
            'model = "gpt-test"\n'
            '[private]\n'
            'token = "do-not-print-this"\n'
            '[shell_environment_policy]\n'
            'inherit = "core"\n'
            '[shell_environment_policy.set]\n'
            'PATH = "/usr/bin"\n'
            'SSH_AUTH_SOCK = "/tmp/old-agent.sock" # keep this comment\n',
            encoding="utf-8",
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
        self.config.write_text('model = "gpt-test"\n', encoding="utf-8")
        self.install_ssh_add()

        with bound_unix_socket(self.socket_path):
            result = self.run_helper("--socket", str(self.socket_path))

        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = signing.tomllib.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual(
            parsed["shell_environment_policy"]["set"]["SSH_AUTH_SOCK"],
            str(self.socket_path),
        )

    def test_second_run_is_byte_and_mtime_idempotent(self):
        self.config.write_text(
            '[shell_environment_policy.set]\n'
            f'SSH_AUTH_SOCK = "{self.socket_path}"\n',
            encoding="utf-8",
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
        self.config.write_text(original, encoding="utf-8")
        self.install_ssh_add(exit_code=1)

        with bound_unix_socket(self.socket_path):
            result = self.run_helper("--socket", str(self.socket_path))

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
                self.config.write_text(fixture, encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()
