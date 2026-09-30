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


if __name__ == "__main__":
    unittest.main()
