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

    def test_wrapper_runs_profile_guard_even_if_dangerous_guard_crashes(self):
        # 1本目が落ちても（exit 1 は Claude Code では「通す」）、2本目の判定は走らせる
        hooks = self.home / "hooks"
        hooks.mkdir()
        (hooks / "guard-dangerous-bash.sh").write_text(WRAPPER.read_text(encoding="utf-8"), encoding="utf-8")
        (hooks / "guard-dangerous-bash.sh").chmod(0o755)
        (hooks / "guard-dangerous-bash.py").write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
        (hooks / "guard-agent-profile.py").write_text(HOOK.read_text(encoding="utf-8"), encoding="utf-8")
        result = self.run_hook("claude -p hi", self.claude_personal(), script=hooks / "guard-dangerous-bash.sh")
        self.assertEqual(result.returncode, BLOCK, result.stderr)

    # --- セキュリティレビュー（2026-10-14）で見つかった抜け道 ---

    def test_blocks_command_substitution(self):
        for command in ('out="$(claude -p x)"', 'echo "$(claude -p x)"', "echo `claude -p x`",
                        "x=$(claude -p x)", 'echo "$(echo "$(claude -p x)")"'):
            with self.subTest(command=command):
                self.assertBlocked(command, self.claude_personal())
        self.assertBlocked('out="$(codex exec x)"', self.env(CLAUDE_PROFILE="personal"))

    def test_single_quoted_substitution_is_data(self):
        self.assertAllowed("echo '$(claude -p x)'", self.claude_personal())

    def test_blocks_agent_on_heredoc_line(self):
        self.assertBlocked("cat <<'EOF' | claude -p\nbody\nEOF", self.claude_personal())
        self.assertBlocked("claude -p <<EOF\nbody\nEOF", self.claude_personal())

    def test_heredoc_body_is_data(self):
        self.assertAllowed("cat <<'EOF' > note.txt\nclaude -p x\nEOF", self.claude_personal())

    def test_blocks_wrapped_launches(self):
        for command in ("timeout 600 claude -p x", "nice -n 5 claude -p x", "nohup claude -p x",
                        "sudo claude -p x", "echo x | xargs claude -p", "xargs -n 1 claude -p",
                        "caffeinate -i claude -p x", "stdbuf -oL claude -p x",
                        "find . -name x -exec claude -p {} \\;", "npx @anthropic-ai/claude-code -p x",
                        "env -C /tmp claude -p x", "CLAUDE -p x", "Claude -p x"):
            with self.subTest(command=command):
                self.assertBlocked(command, self.claude_personal())
        for command in ("npx @openai/codex exec x", "bunx codex exec x", "timeout 9 codex exec x"):
            with self.subTest(command=command):
                self.assertBlocked(command, self.env(CLAUDE_PROFILE="personal"))

    def test_blocks_more_wrapped_launches(self):
        # 2026-10-23 の調査で見逃していた起動の形
        for command in ("npm exec -- @anthropic-ai/claude-code -p x", "npm x @anthropic-ai/claude-code -p x",
                        "pnpm dlx @anthropic-ai/claude-code -p x", "yarn dlx @anthropic-ai/claude-code -p x",
                        "script -q /dev/null claude -p x", "watch claude -p x", "watch -n 5 claude -p x",
                        "env -S 'claude -p hi'", "env --split-string='claude -p hi'"):
            with self.subTest(command=command):
                self.assertBlocked(command, self.claude_personal())

    def test_package_manager_subcommands_without_agents_are_allowed(self):
        for command in ("npm exec -- prettier --check .", "pnpm dlx create-vite x", "watch ls", "env -S 'ls -l'"):
            with self.subTest(command=command):
                self.assertAllowed(command, self.claude_personal())

    def test_blocks_unresolvable_command_names_mentioning_agents(self):
        for command in ("c=claude; $c -p x", '"${CLAUDE_BIN:-claude}" -p x',
                        "$(command -v claude) -p x", "~/.local/bin/clau?e -p x"):
            with self.subTest(command=command):
                self.assertBlocked(command, self.claude_personal())

    def test_explicit_company_codex_home_must_be_real(self):
        for command in ("CODEX_HOME= codex exec x", "CODEX_HOME=x env -u CODEX_HOME codex exec x",
                        "CODEX_HOME=x env -i codex exec x", "export CODEX_HOME; codex exec x",
                        "export -n CODEX_HOME; codex exec x"):
            with self.subTest(command=command):
                self.assertBlocked(command, self.claude_personal())

    def test_only_read_only_claude_subcommands_are_safe(self):
        for command in ("claude auth logout", "claude mcp add x y", "claude update", "claude plugin install x"):
            with self.subTest(command=command):
                self.assertBlocked(command, self.claude_personal())
        for command in ("command -v claude", "which claude", "type claude"):
            with self.subTest(command=command):
                self.assertAllowed(command, self.claude_personal())

    def test_unparseable_command_with_agent_paths_only_is_allowed(self):
        # ~/.claude/ や ~/.codex のようなパスは、起動ではない
        self.assertAllowed("cat ~/.claude/settings.json ~/.codex/config.toml 'unterminated", self.claude_personal())

    def test_malformed_payload_does_not_crash(self):
        payload = json.dumps({"tool_name": "Bash", "tool_input": "claude -p x"})
        result = subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True,
                                text=True, env=self.claude_personal(), timeout=30)
        self.assertIn(result.returncode, (ALLOW, BLOCK), result.stderr)


if __name__ == "__main__":
    unittest.main()
