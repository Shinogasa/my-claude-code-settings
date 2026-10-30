#!/usr/bin/env python3
"""secret を含みうるファイルの中身が、AIのツール呼び出しで出力されるのを止める PreToolUse フック。

使い方: guard-secret-read.py（入力は stdin の JSON。exit 0 で許可、exit 2 でブロック）
設計: docs/superpowers/specs/2026-10-29-secret-read-guard-design.md

permissions.deny（層1）は一覧に載せた場所しか止めない。このフック（層2）は、一覧に無いファイルも
「場所 × 権限」で判定して止める。対象範囲は ~/.config 配下と、ホーム直下のドットファイル・ドットディレクトリ。
その中で、本人だけが読める権限（600 など）の通常ファイルを secret とみなす。
判定できないとき（stat が失敗する、解析で例外が出る）は、対象範囲に見えるなら止める（fail-close）。

Claude Code にだけ登録する。Codex（codex/hooks.json）には登録しない。
"""
import json
import os
import stat
import sys

# Claude Code 自身が作る600のファイルのうち、作業で読むものの置き場所。権限ではなく場所で例外にする
EXEMPT_DIRS = (
    ".claude/projects", ".claude/state", ".claude/plugins", ".claude/plans", ".claude/jobs", ".claude/tasks",
)
# 解決前の文字列が対象範囲を指しているように見える書き方
HOME_DOT_PREFIXES = ("~/.", "$HOME/.", "${HOME}/.")
ALLOW, BLOCK, UNKNOWN = "allow", "block", "unknown"
BLOCK_EXIT = 2


def expand(path: str, home: str, cwd: str) -> str:
    """~ をホームへ展開し、相対パスは cwd 起点で絶対パスにする。"""
    if path == "~" or path.startswith("~/"):
        path = home + path[1:]
    return os.path.join(cwd, path)


def guarded_area(path: str, home: str) -> bool:
    """実体パスが対象範囲にあり、例外の場所に無いか。"""
    real = os.path.realpath(path)
    home_real = os.path.realpath(home)
    if not real.startswith(home_real + os.sep):
        return False
    rel = os.path.relpath(real, home_real)
    if not rel.startswith("."):
        return False
    return not any(rel == d or rel.startswith(d + os.sep) for d in EXEMPT_DIRS)


def is_owner_only_file(path: str) -> bool:
    st = os.stat(path)
    return stat.S_ISREG(st.st_mode) and stat.S_IMODE(st.st_mode) & 0o077 == 0


def classify(path: str, home: str, cwd: str) -> str:
    """allow・block・unknown のどれかを返す。ディレクトリは、対象範囲にあれば中を走査されうるので止める。"""
    target = os.path.realpath(expand(path, home, cwd))
    home_real = os.path.realpath(home)
    # ホームそのものや、その上のディレクトリを走査されると対象範囲まで届く
    if os.path.isdir(target) and (home_real + os.sep).startswith(target.rstrip(os.sep) + os.sep):
        return BLOCK
    if not guarded_area(target, home):
        return ALLOW
    try:
        if os.path.isdir(target):
            return BLOCK
        return BLOCK if is_owner_only_file(target) else ALLOW
    except OSError:
        return UNKNOWN


def looks_guarded(text: str, home: str) -> bool:
    """解決前の文字列が対象範囲に見えるか。解析できないときの最後の判定に使う。"""
    prefixes = HOME_DOT_PREFIXES + (os.path.realpath(home) + "/.", home + "/.")
    return any(prefix in text for prefix in prefixes)


def check_path(path: str, home: str, cwd: str):
    """ブロックの理由を返す。許可なら None。"""
    verdict = classify(path, home, cwd)
    if verdict == BLOCK:
        return f"{path} は secret を含みうる場所です（本人だけが読める権限のファイル、または対象範囲のディレクトリ）"
    if verdict == UNKNOWN:
        return f"{path} は対象範囲にあり、権限を確かめられませんでした"
    return None


def decide(data: dict, home: str):
    tool = data.get("tool_name")
    tool_input = data["tool_input"]
    cwd = data.get("cwd") or os.getcwd()
    if tool == "Read":
        return check_path(tool_input["file_path"], home, cwd)
    if tool == "Grep":
        return check_path(tool_input.get("path") or cwd, home, cwd)
    return None


def block(reason: str) -> int:
    print(f"ブロック: {reason}。中身を出さずに構造だけ見るなら show-config-structure <path> を使って。", file=sys.stderr)
    return BLOCK_EXIT


def main() -> int:
    raw = sys.stdin.read()
    home = os.environ.get("HOME", "")
    try:
        reason = decide(json.loads(raw), home)
    except Exception as error:
        if looks_guarded(raw, home):
            return block(f"入力を判定できませんでした（{type(error).__name__}）。対象範囲のパスを含むので止めます")
        return 0
    return block(reason) if reason else 0


if __name__ == "__main__":
    sys.exit(main())
