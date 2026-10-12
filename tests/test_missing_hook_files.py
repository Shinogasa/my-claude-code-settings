#!/usr/bin/env python3
"""settings.json.template のフックが、呼ぶファイルの無いときに全 Bash を止めないことを検証する。

~/.claude/hooks は作業ツリーへのリンクだが、~/.claude/settings.json は setup.sh が生成したコピーである。
フックを足す前のブランチへ設定リポジトリを戻すと、settings.json は無いファイルを呼ぶ。
python3 は無いファイルで exit 2 になり、PreToolUse ではブロックとして扱われる。

実行: python3 -m unittest tests.test_missing_hook_files
"""
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS = json.loads((REPO_ROOT / "settings.json.template").read_text(encoding="utf-8"))
HOOK_FILE = re.compile(r"~/\.claude/hooks/([\w.-]+)")
BLOCKING_EXIT = 2


def hook_commands():
    """(イベント, command) の一覧。~/.claude/hooks の下のファイルを呼ぶものだけ。"""
    return [(event, hook["command"]) for event, groups in SETTINGS["hooks"].items()
            for group in groups for hook in group["hooks"] if HOOK_FILE.search(hook["command"])]


def run(command, home):
    # テンプレートに登録された文字列そのものを走らせる
    return subprocess.run(["sh", "-c", command], input="{}", capture_output=True, text=True,
                          env={**os.environ, "HOME": str(home)})


class MissingHookFileTests(unittest.TestCase):
    def test_commands_are_found(self):
        # 抽出の式が壊れて0件になっても、下のテストが黙って通らないようにする
        self.assertGreaterEqual(len(hook_commands()), 9)

    def test_missing_hook_file_does_not_block(self):
        with tempfile.TemporaryDirectory() as home:
            for event, command in hook_commands():
                with self.subTest(event=event, command=command):
                    self.assertNotEqual(run(command, home).returncode, BLOCKING_EXIT)

    def test_missing_python_hook_file_passes_with_message(self):
        with tempfile.TemporaryDirectory() as home:
            for event, command in hook_commands():
                if "python3" not in command:
                    continue
                with self.subTest(event=event, command=command):
                    result = run(command, home)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    output = json.loads(result.stdout)
                    self.assertIn("見つからないので検査しなかった", output["systemMessage"])
                    self.assertIn("bash setup.sh --claude", output["systemMessage"])
                    self.assertIn(HOOK_FILE.search(command).group(0), output["systemMessage"])
                    self.assertNotIn("hookSpecificOutput", output)

    def test_present_python_hook_file_is_run_with_its_arguments_and_input(self):
        with tempfile.TemporaryDirectory() as home:
            hooks = Path(home) / ".claude" / "hooks"
            hooks.mkdir(parents=True)
            for event, command in hook_commands():
                if "python3" not in command:
                    continue
                name = HOOK_FILE.search(command).group(1)
                (hooks / name).write_text("import sys\nprint(sys.argv[1:], sys.stdin.read())\n", encoding="utf-8")
                arguments = command.split(f"python3 ~/.claude/hooks/{name}", 1)[1].split(";", 1)[0].split()
                with self.subTest(event=event, command=command):
                    result = run(command, home)
                    self.assertEqual((result.returncode, result.stdout.strip()), (0, f"{arguments} {{}}"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
