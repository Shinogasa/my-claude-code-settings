"""個人のGit署名設定を通常fixtureへ持ち込まないことを検証する。"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import test_detect_parallel_sessions as detection
from tests import test_guard_dangerous_bash as guard
from tests import test_warn_branch_behind_main as warning


class GitFixtureIsolationTests(unittest.TestCase):
    def test_commit_succeeds_with_personal_signing_enabled(self):
        """存在しない署名プログラムを設定してもfixtureのcommitは成功する。"""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = base / "personal.gitconfig"
            config.write_text(
                f"[commit]\n\tgpgsign = true\n[gpg]\n\tprogram = {base / 'missing-gpg'}\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(config)}):
                enabled = subprocess.run(
                    ["git", "config", "--global", "--get", "commit.gpgsign"],
                    check=True, text=True, capture_output=True,
                )
                self.assertEqual(enabled.stdout.strip(), "true")
                for fixture in (detection, guard, warning):
                    with self.subTest(fixture=fixture.__name__):
                        root = base / fixture.__name__
                        root.mkdir()
                        try:
                            if fixture is detection:
                                repo = fixture.make_repo(root, "repo")
                            elif fixture is guard:
                                repo = fixture.make_repo(root, with_hooks=True)
                            else:
                                repo = fixture.make_repo(root, behind=1)
                            fixture.git(
                                repo, "-c", "user.email=t@example.com", "-c", "user.name=t",
                                "commit", "--allow-empty", "-m", "second",
                            )
                        except subprocess.CalledProcessError as error:
                            self.fail(f"fixtureが個人の署名設定を継承した: {error.stderr}")
                        commits = subprocess.run(
                            ["git", "-C", str(repo), "rev-list", "--count", "HEAD"],
                            check=True, text=True, capture_output=True,
                        )
                        self.assertEqual(commits.stdout.strip(), "2")

    def test_inherited_repository_location_does_not_redirect_fixture(self):
        """呼び出し元のGIT_DIR等が残っていても、fixture外のリポジトリへ書き込まない。"""
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            outside = base / "outside"
            outside.mkdir()
            detection.git(outside, "init", "-q", "-b", "main")
            detection.git(
                outside, "-c", "user.email=t@example.com", "-c", "user.name=t",
                "commit", "-q", "--allow-empty", "-m", "outside",
            )
            inherited = {
                "GIT_DIR": str(outside / ".git"),
                "GIT_WORK_TREE": str(outside),
                "GIT_INDEX_FILE": str(outside / ".git" / "index"),
            }
            fixture = base / "fixture"
            fixture.mkdir()
            with patch.dict(os.environ, inherited):
                repo = guard.make_repo(fixture, with_hooks=False)
            self.assertTrue((repo / ".git").is_dir())
            for path, expected in ((outside, "outside"), (repo, "init")):
                subjects = subprocess.run(
                    ["git", "-C", str(path), "log", "--format=%s"],
                    check=True, text=True, capture_output=True,
                )
                self.assertEqual(subjects.stdout.split(), [expected])


if __name__ == "__main__":
    unittest.main()
