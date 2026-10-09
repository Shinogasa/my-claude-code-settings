#!/usr/bin/env python3
"""tests/run.sh が組み立てるテスト実行コマンドの契約を検証する。"""

import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tests" / "run.sh"
SLOW_FILES = ("tests/test_setup_cli.py", "tests/test_setup_preflight.py")


def dry_run(*args: str, path: str | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if path is not None:
        env["PATH"] = path
    return subprocess.run(
        ["bash", str(SCRIPT), "--dry-run", *args],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


class RunScriptTests(unittest.TestCase):
    def test_quick_mode_runs_in_parallel_without_slow_setup_tests(self):
        result = dry_run()
        self.assertEqual(result.returncode, 0, result.stderr)
        command = result.stdout
        self.assertIn("pytest==9.1.1", command)
        self.assertIn("pytest-xdist==3.8.0", command)
        self.assertIn("-n auto", command)
        self.assertIn("error::ResourceWarning", command)
        self.assertIn("tests/test_run_script.py", command)
        for slow in SLOW_FILES:
            with self.subTest(slow=slow):
                self.assertNotIn(slow, command)

    def test_all_mode_includes_slow_setup_tests(self):
        result = dry_run("--all")
        self.assertEqual(result.returncode, 0, result.stderr)
        for slow in SLOW_FILES:
            with self.subTest(slow=slow):
                self.assertIn(slow, result.stdout)

    def test_collection_is_limited_to_top_level_test_files(self):
        # pytestは既定でサブディレクトリまで集める。演習用のfixtureを実行させない
        result = dry_run("--all")
        # 空の出力でも「含まない」は成り立つので、先に実行とファイル列挙を確かめる
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("tests/test_run_script.py", result.stdout)
        self.assertNotIn("tests/fixtures", result.stdout)
        self.assertNotIn(" tests/ ", f"{result.stdout} ")

    def test_falls_back_to_sequential_unittest_with_notice_without_uv(self):
        result = dry_run(path="/usr/bin:/bin")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("-m unittest", result.stdout)
        self.assertIn("tests.test_run_script", result.stdout)
        self.assertNotIn("tests.test_setup_cli", result.stdout)
        self.assertIn("uv", result.stderr)

    def test_unknown_option_is_rejected(self):
        result = dry_run("--fast")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Usage:", result.stderr)


if __name__ == "__main__":
    unittest.main()
