#!/usr/bin/env python3
"""PreToolUse(Bash)フック: `rtk hook claude` を呼ぶ。ただしlinked worktreeのgitは書き換えさせない。

Claude Codeのworktree分離チェックは、PreToolUseのフックが書き換えた後のコマンドを判定する。
rtkが `git status` を `rtk git status` に書き換えると、rtkが何を実行するか読めないとして拒否する
（anthropics/claude-code#99895）。そのため、worktreeに閉じ込めたセッションではgitをまったく使えない。

回避する範囲は「linked worktreeの中」かつ「gitの語を含むコマンド」に限り、それ以外はrtkに任せる。
gitの語を含めば `grep git` のようなコマンドも省く。分離チェックがそれらも拒否するため。
上流（Claude Codeの上の不具合、rtk-ai/rtk#3879・#4490）が直ったら、このフックを外して `rtk hook claude` に戻す。
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

GIT_WORD = re.compile(r"(?<![\w.-])git(?![\w-])")
LINKED_WORKTREE_GITDIR = re.compile(r"[/\\]worktrees[/\\][^/\\]+[/\\]?$")


def is_linked_worktree(cwd):
    """cwdから上へ `.git` を探し、linked worktreeの作業ツリーかを返す。

    linked worktreeの `.git` はファイルで、`gitdir:` が `<共通dir>/worktrees/<名前>` を指す。
    submoduleの `.git` もファイルだが、`<共通dir>/modules/<名前>` を指すので除く。
    """
    for directory in (cwd, *cwd.parents):
        marker = directory / ".git"
        if marker.is_dir():
            return False
        if marker.is_file():
            try:
                content = marker.read_text(encoding="utf-8").strip()
            except OSError:
                return False
            if not content.startswith("gitdir:"):
                return False
            return bool(LINKED_WORKTREE_GITDIR.search(content[len("gitdir:"):].strip()))
    return False


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {}
    command = str(payload.get("tool_input", {}).get("command", ""))
    cwd = Path(payload.get("cwd") or os.getcwd())
    if GIT_WORD.search(command) and is_linked_worktree(cwd):
        return 0
    try:
        result = subprocess.run(["rtk", "hook", "claude"], input=raw, capture_output=True, text=True)
    except FileNotFoundError:
        # rtkが無ければ書き換えずに通す。以前の `rtk hook claude` 直書きでも止めてはいなかった
        return 0
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
