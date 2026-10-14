#!/usr/bin/env python3
"""hooks/guard-agent-profile.py の振る舞いを検証する（ADR 0036の②③）。

個人用のセッションから、会社用の claude / codex を起動するコマンドを止める。
フックの契約（stdin に JSON、exit 0=許可 / 2=ブロック）をそのまま叩く。

実行: python3 tests/test_guard_agent_profile.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "guard-agent-profile.py"
WRAPPER = REPO_ROOT / "hooks" / "guard-dangerous-bash.sh"

ALLOW = 0
BLOCK = 2


class AgentProfileGuardTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="guard-agent-profile-")
        self.home = Path(self._tmp.name)
        self.company = self.home / ".codex"
        self.personal = self.home / ".codex-personal"
        self.company.mkdir()
        self.personal.mkdir(mode=0o700)

    def tearDown(self):
        self._tmp.cleanup()

    def env(self, **values):
        env = {key: value for key, value in os.environ.items()
               if key not in ("CLAUDE_PROFILE", "CODEX_HOME")}
        env["HOME"] = str(self.home)
        env.update({key: str(value) for key, value in values.items() if value is not None})
        return env

    def claude_personal(self, **extra):
        return self.env(CLAUDE_PROFILE="personal", CODEX_HOME=self.personal, **extra)

    def run_hook(self, command, env, script=HOOK):
        payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(self.home)}
        argv = [sys.executable, str(script)] if script.suffix == ".py" else [str(script)]
        return subprocess.run(argv, input=json.dumps(payload), capture_output=True,
                              text=True, env=env, cwd=str(self.home), timeout=30)

    def assertBlocked(self, command, env, hint=None):
        result = self.run_hook(command, env)
        self.assertEqual(result.returncode, BLOCK, f"止まるべき: {command}\n{result.stderr}")
        if hint:
            self.assertIn(hint, result.stderr)

    def assertAllowed(self, command, env):
        result = self.run_hook(command, env)
        self.assertEqual(result.returncode, ALLOW, f"通るべき: {command}\n{result.stderr}")

    # --- 個人用の Claude Code（ccp）セッション ---

    def test_blocks_bare_claude_in_personal_claude_session(self):
        for command in ("claude -p hi", "claude", "true || claude -p x", "rtk proxy claude -p x",
                        "/usr/local/bin/claude -p x", "env FOO=1 claude -p x", "cd /tmp && claude -p x"):
            with self.subTest(command=command):
                self.assertBlocked(command, self.claude_personal(), hint="claude-headless")

    def test_allows_claude_subcommands_that_do_not_call_a_model(self):
        for command in ("claude --version", "claude -v", "claude --help", "claude plugin list",
                        "claude mcp list", "claude auth status", "claude doctor"):
            with self.subTest(command=command):
                self.assertAllowed(command, self.claude_personal())

    def test_allows_profile_aware_launchers(self):
        for command in ("claude-headless -p hi", "ccp -p hi", "cxp exec hi",
                        "CLAUDE_PROFILE=default claude-headless -p hi", "echo 'claude -p x'"):
            with self.subTest(command=command):
                self.assertAllowed(command, self.claude_personal())

    def test_allows_codex_when_codex_home_is_personal(self):
        self.assertAllowed("codex exec hi", self.claude_personal())

    def test_blocks_codex_when_codex_home_is_missing(self):
        # setup.sh の実行忘れ。CODEX_HOME が無いと、codex は会社用の ~/.codex を読む
        self.assertBlocked("codex exec hi", self.env(CLAUDE_PROFILE="personal"), hint="setup.sh")

    def test_blocks_codex_when_codex_home_resolves_to_company(self):
        # setup.sh の後で ~/.codex-personal を会社用への symlink に差し替えた場合（セキュリティレビュー Medium-1）
        self.personal.rmdir()
        self.personal.symlink_to(self.company)
        self.assertBlocked("codex exec hi", self.claude_personal(), hint="cxp")

    def test_blocks_codex_after_env_clears_codex_home(self):
        for command in ("env -i codex exec hi", "env -u CODEX_HOME codex exec hi",
                        "unset CODEX_HOME; codex exec hi"):
            with self.subTest(command=command):
                self.assertBlocked(command, self.claude_personal())

    def test_allows_explicit_company_codex_home(self):
        # ユーザーが会社用を指示したときの書き方。明示した跡がコマンドに残る
        for command in ("CODEX_HOME=~/.codex codex exec hi",
                        "export CODEX_HOME=~/.codex; codex exec hi",
                        "env CODEX_HOME=~/.codex codex exec hi"):
            with self.subTest(command=command):
                self.assertAllowed(command, self.claude_personal())

    def test_allows_codex_version(self):
        self.assertAllowed("codex --version", self.env(CLAUDE_PROFILE="personal"))

    # --- 個人用の Codex（cxp）セッション ---

    def test_blocks_bare_claude_in_personal_codex_session(self):
        # Codex には CLAUDE_PROFILE が無いので、claude-headless は使えない。ccp を案内する
        self.assertBlocked("claude -p hi", self.env(CODEX_HOME=self.personal), hint="ccp")

    def test_allows_codex_in_personal_codex_session(self):
        self.assertAllowed("codex exec hi", self.env(CODEX_HOME=self.personal))

    # --- 会社用のセッションでは何もしない ---

    def test_company_sessions_are_untouched(self):
        for env in (self.env(CLAUDE_PROFILE="default", CODEX_HOME=self.company),
                    self.env(CODEX_HOME=self.company), self.env()):
            for command in ("claude -p hi", "codex exec hi"):
                with self.subTest(env=env.get("CLAUDE_PROFILE"), command=command):
                    self.assertAllowed(command, env)

    # --- 判定できないとき ---

    def test_unparseable_command_mentioning_agents_is_blocked(self):
        self.assertBlocked("claude -p 'unterminated", self.claude_personal())

    def test_unparseable_command_without_agents_is_allowed(self):
        self.assertAllowed("echo 'unterminated", self.claude_personal())

    # --- 両ホストが呼ぶラッパーから届くこと ---

    def test_wrapper_runs_profile_guard(self):
        result = self.run_hook("claude -p hi", self.claude_personal(), script=WRAPPER)
        self.assertEqual(result.returncode, BLOCK, result.stderr)
        self.assertIn("claude-headless", result.stderr)

    def test_wrapper_still_runs_dangerous_guard(self):
        result = self.run_hook("rm -rf /", self.claude_personal(), script=WRAPPER)
        self.assertEqual(result.returncode, BLOCK, result.stderr)


if __name__ == "__main__":
    unittest.main()
