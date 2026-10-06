#!/usr/bin/env python3
"""`bin/cxp` が個人用の CODEX_HOME で codex を起動することを検証する（ADR 0026）。

個人用の認証情報は ~/.codex-personal にだけ置く。cxp がここ以外を CODEX_HOME にすると、
会社用の設定と個人アカウントが同じ場所に戻り、分離した意味がなくなる。

実行: python3 -m unittest tests.test_cxp
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CXP = REPO_ROOT / "bin" / "cxp"


class TestCxp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        self.home = base / "home"
        self.home.mkdir()
        self.personal = self.home / ".codex-personal"

        # 本物の codex を起動しないよう、PATH の先頭にスタブを置く。
        # スタブは受け取った CODEX_HOME と引数を記録する。
        bindir = base / "bin"
        bindir.mkdir()
        self.record = base / "codex-launch.txt"
        stub = bindir / "codex"
        stub.write_text(
            f'#!/bin/bash\nprintf "%s\\n" "$CODEX_HOME" "$@" > "{self.record}"\n',
            encoding="utf-8",
        )
        stub.chmod(0o755)
        self.path = f"{bindir}{os.pathsep}{os.environ['PATH']}"

    def run_cxp(self, *args, codex_home=None):
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        env["PATH"] = self.path
        env.pop("CODEX_HOME", None)
        if codex_home is not None:
            env["CODEX_HOME"] = codex_home
        return subprocess.run(
            [str(CXP), *args], env=env, capture_output=True, text=True, timeout=30
        )

    def launched(self):
        return self.record.read_text(encoding="utf-8").splitlines()

    def test_launches_codex_with_personal_home_and_passes_arguments(self):
        self.personal.mkdir(mode=0o700)
        result = self.run_cxp("exec", "-c", 'model="x"', "hello world")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.launched(),
            [str(self.personal), "exec", "-c", 'model="x"', "hello world"],
        )

    def test_overrides_inherited_codex_home(self):
        # 会社用の CODEX_HOME が環境に残っていても、個人用で起動する
        self.personal.mkdir(mode=0o700)
        result = self.run_cxp(codex_home=str(self.home / ".codex"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.launched()[0], str(self.personal))

    def test_stops_when_personal_home_resolves_to_company_home(self):
        # ~/.codex-personal が ~/.codex へのsymlinkだと、個人用のつもりで会社用の設定と認証で動く
        (self.home / ".codex").mkdir(mode=0o700)
        self.personal.symlink_to(self.home / ".codex", target_is_directory=True)
        result = self.run_cxp()
        self.assertEqual(result.returncode, 1)
        self.assertIn("会社用", result.stderr)
        self.assertFalse(self.record.exists(), "codex が起動してしまった")

    def test_stops_when_personal_home_is_readable_by_others(self):
        # 個人の auth.json を置く場所なので、本人以外に権限があれば止める
        self.personal.mkdir(mode=0o755)
        self.personal.chmod(0o755)
        result = self.run_cxp()
        self.assertEqual(result.returncode, 1)
        self.assertIn("700", result.stderr)
        self.assertFalse(self.record.exists(), "codex が起動してしまった")

    def test_stops_before_launching_when_personal_home_is_missing(self):
        result = self.run_cxp()
        self.assertEqual(result.returncode, 1)
        self.assertIn(".codex-personal", result.stderr)
        self.assertFalse(self.record.exists(), "codex が起動してしまった")


if __name__ == "__main__":
    unittest.main()
