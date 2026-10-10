#!/usr/bin/env python3
"""全件テストの通過を記録し、PR作成時にその記録を確かめる仕組みを検証する。"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.git_fixture import git


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "require-full-tests-before-pr.py"
RUN_SCRIPT = ROOT / "tests" / "run.sh"
SETTINGS_TEMPLATE = ROOT / "settings.json.template"
STAMP_NAME = "tests-all-passed"


def make_repository(base: Path, *, with_run_script: bool = True, test_body: str = "pass") -> Path:
    repository = base / "repository"
    (repository / "tests").mkdir(parents=True)
    if with_run_script:
        shutil.copy2(RUN_SCRIPT, repository / "tests" / "run.sh")
    (repository / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (repository / "tests" / "test_sample.py").write_text(
        "import unittest\n\n\nclass Sample(unittest.TestCase):\n"
        f"    def test_sample(self):\n        {test_body}\n",
        encoding="utf-8",
    )
    git(repository, "init", "-q", "-b", "main")
    git(repository, "add", ".")
    git(repository, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "init")
    return repository


def stamp_path(repository: Path) -> Path:
    relative = git(repository, "rev-parse", "--git-path", STAMP_NAME).stdout.strip()
    return repository / relative


def head(repository: Path) -> str:
    return git(repository, "rev-parse", "HEAD").stdout.strip()


def run_all_without_uv(repository: Path, base: Path) -> subprocess.CompletedProcess[str]:
    # uvを外したPATHで逐次実行させ、ネットワークを使わずに記録の挙動だけを確かめる
    bindir = base / "bin"
    bindir.mkdir(exist_ok=True)
    for tool in ("python3", "git"):
        link = bindir / tool
        if not link.exists():
            link.symlink_to(shutil.which(tool))
    env = os.environ.copy()
    env["PATH"] = f"{bindir}{os.pathsep}/usr/bin{os.pathsep}/bin"
    return subprocess.run(["bash", "tests/run.sh", "--all"], cwd=repository, text=True,
                          capture_output=True, env=env, check=False)


def run_hook(command: str, cwd: Path, env=None) -> subprocess.CompletedProcess[str]:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}
    return subprocess.run(["python3", str(HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, check=False, env={**os.environ, **(env or {})})


def decision(result: subprocess.CompletedProcess[str]):
    if not result.stdout.strip():
        return None
    return json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]


class RunScriptStampTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def test_passing_all_run_on_clean_tree_records_head(self):
        repository = make_repository(self.base)
        result = run_all_without_uv(repository, self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(stamp_path(repository).read_text(encoding="utf-8").strip(), head(repository))

    def test_failing_run_does_not_record(self):
        repository = make_repository(self.base, test_body="self.fail('x')")
        result = run_all_without_uv(repository, self.base)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(stamp_path(repository).exists())

    def test_run_with_uncommitted_tracked_change_does_not_record(self):
        repository = make_repository(self.base)
        (repository / "tests" / "test_sample.py").write_text(
            "import unittest\n\n\nclass Sample(unittest.TestCase):\n"
            "    def test_sample(self):\n        pass\n\n# 未コミットの変更\n",
            encoding="utf-8",
        )
        result = run_all_without_uv(repository, self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(stamp_path(repository).exists())
        self.assertIn("記録しない", result.stderr)


class RequireFullTestsHookTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def test_other_commands_pass_through(self):
        repository = make_repository(self.base)
        result = run_hook("git status", repository)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(decision(result))

    def test_quoted_pr_create_is_not_treated_as_pr_creation(self):
        repository = make_repository(self.base)
        result = run_hook("echo 'gh pr create'", repository)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(decision(result))

    def test_repository_without_marked_run_script_is_not_checked(self):
        repository = make_repository(self.base, with_run_script=False)
        (repository / "tests" / "run.sh").write_text("#!/bin/bash\necho other project\n", encoding="utf-8")
        result = run_hook("gh pr create --fill", repository)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(decision(result))

    def test_pr_creation_without_record_is_denied(self):
        repository = make_repository(self.base)
        result = run_hook("gh pr create --fill", repository)
        self.assertEqual(decision(result), "deny", result.stdout + result.stderr)
        self.assertIn("bash tests/run.sh --all", result.stdout)

    def test_pr_creation_with_record_for_head_is_allowed(self):
        repository = make_repository(self.base)
        stamp_path(repository).write_text(head(repository) + "\n", encoding="utf-8")
        result = run_hook("gh pr create --fill", repository)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(decision(result))

    def test_pr_creation_with_record_for_older_commit_is_denied(self):
        repository = make_repository(self.base)
        stamp_path(repository).write_text("0" * 40 + "\n", encoding="utf-8")
        result = run_hook("gh pr create --fill", repository)
        self.assertEqual(decision(result), "deny", result.stdout + result.stderr)

    def test_pr_creation_in_cd_target_without_run_script_is_allowed(self):
        # cwd ではなく、cd した先のリポジトリでPRを作る。cwd 側の記録で止めない
        target = make_repository(self.base / "target")
        other = make_repository(self.base / "other", with_run_script=False)
        result = run_hook(f"cd {other} && gh pr create --fill", target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(decision(result), result.stdout)

    def test_pr_creation_in_cd_target_without_record_is_denied(self):
        target = make_repository(self.base / "target")
        other = make_repository(self.base / "other", with_run_script=False)
        result = run_hook(f"cd {target} && gh pr create --fill", other)
        self.assertEqual(decision(result), "deny", result.stdout + result.stderr)
        self.assertIn("bash tests/run.sh --all", result.stdout)

    def test_unresolved_cd_target_is_denied(self):
        # 移動先を確定できなければ、検査できなかったとして止める
        other = make_repository(self.base / "other", with_run_script=False)
        result = run_hook('cd "$HOME/somewhere" && gh pr create --fill', other)
        self.assertEqual(decision(result), "deny", result.stdout + result.stderr)

    def test_pr_creation_through_rtk_is_checked(self):
        # rtk hook claude はコマンドを rtk gh ... へ書き換える。書き換え後を受け取っても判定する
        repository = make_repository(self.base)
        result = run_hook("rtk gh pr create --fill", repository)
        self.assertEqual(decision(result), "deny", result.stdout + result.stderr)

    def test_exhausted_time_budget_is_denied(self):
        # settings.json の timeout で打ち切られると、Claude Code は通してしまう。先に自分で止める
        repository = make_repository(self.base)
        stamp_path(repository).write_text(head(repository) + "\n", encoding="utf-8")
        result = run_hook("gh pr create --fill", repository, env={"REQUIRE_FULL_TESTS_TIME_BUDGET": "0"})
        self.assertEqual(decision(result), "deny", result.stdout + result.stderr)
        self.assertIn("時間予算", result.stdout)

    def test_unreadable_head_is_denied_instead_of_passed(self):
        # 検査できなかったことを「問題なし」に畳まない
        repository = make_repository(self.base)
        stamp_path(repository).write_text(head(repository) + "\n", encoding="utf-8")
        shutil.rmtree(repository / ".git" / "refs")
        (repository / ".git" / "HEAD").write_text("broken\n", encoding="utf-8")
        result = run_hook("gh pr create --fill", repository)
        self.assertEqual(decision(result), "deny", result.stdout + result.stderr)

    def test_unreadable_input_that_looks_like_pr_creation_is_denied(self):
        # 終了コード1は止める扱いにならないので、例外で抜けずにdenyを返す
        result = subprocess.run(["python3", str(HOOK)], input='{"tool_input": {"command": "gh pr create"',
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(decision(result), "deny", result.stdout + result.stderr)

    def test_unreadable_input_for_other_commands_is_passed_with_notice(self):
        # hookの故障で、あらゆるBashを止めない
        result = subprocess.run(["python3", str(HOOK)], input='{"tool_input": {"command": "git status"',
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(decision(result))
        self.assertIn("require-full-tests-before-pr", result.stderr)

    def test_broken_shared_detector_falls_back_and_denies_pr_creation(self):
        hooks = self.base / "hooks"
        hooks.mkdir()
        shutil.copy2(HOOK, hooks / HOOK.name)
        (hooks / "jp-doc-review.py").write_text("this is not python\n", encoding="utf-8")
        repository = make_repository(self.base)
        payload = {"tool_name": "Bash", "tool_input": {"command": "gh pr create --fill"}, "cwd": str(repository)}
        stamp_path(repository).write_text(head(repository) + "\n", encoding="utf-8")
        result = subprocess.run(["python3", str(hooks / HOOK.name)], input=json.dumps(payload),
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(decision(result), "deny", result.stdout + result.stderr)

    def test_hook_is_wired_for_bash_in_settings_template(self):
        settings = json.loads(SETTINGS_TEMPLATE.read_text(encoding="utf-8"))
        commands = [
            hook["command"]
            for group in settings["hooks"]["PreToolUse"]
            if group.get("matcher") == "Bash"
            for hook in group["hooks"]
        ]
        self.assertTrue(any("require-full-tests-before-pr.py" in command for command in commands))


if __name__ == "__main__":
    unittest.main()
