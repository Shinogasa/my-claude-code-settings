#!/usr/bin/env python3
"""PreToolUse(Bash)フック: マージ済みPRのブランチへコミットしようとしたら止める。

背景:
  PRがマージされた後も同じブランチでコミットを続ける事故が2回起きた（PR #22、PR #28）。
  git status も git push も成功し、gh pr view はマージ済みのPRの古い状態を正常に返すので、
  症状が正常系と区別できない。コミットのたびにPRの状態を照会して気づかせる。

挙動:
  コマンドの位置にある git commit だけを対象にする。現在のブランチのPRを gh で照会し、
  開いているPRが無く、マージ済みのPRがあれば止める（deny）。クローズされただけのPRは警告に留める。
  既定のブランチ（main / master）と detached HEAD は照会しない（直接のコミットは別のフックが止める）。

  照会に失敗したとき（gh が無い、認証が無い、ネットワークに届かない、時間切れ）は、
  確かめられなかったことを表示して通す。フック自身が作業を止め続けないことを優先する。

判断の経緯: tasks/backlog.md の「マージ済み PR のブランチに作業を積み続ける事故」（2026-10-03にコミット時の照会を選んだ）
"""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

SEPARATOR_CHARS = ";&|()<>\n"
COMMAND_PREFIXES = {"command", "builtin", "exec", "env", "time", "nohup", "noglob"}
GIT_OPTIONS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--attr-source"}
DEFAULT_BRANCHES = {"main", "master", "HEAD"}
GH_TIMEOUT_SECONDS = 5
GIT_TIMEOUT_SECONDS = 5


def _words(command: str) -> List[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=SEPARATOR_CHARS)
    lexer.whitespace = " \t\r"  # 改行は区切りとして返させる
    words: List[str] = []
    try:
        for word in lexer:
            words.append(word)
    except ValueError:
        pass
    return words


def commit_directories(command: str) -> Optional[List[str]]:
    """コマンドの位置に git commit があれば、その -C の値の一覧を返す。無ければ None。

    引用符の中（echo の文字列など）は1語として扱うので、コミットとみなさない。
    """
    segment: List[str] = []
    for word in [*_words(command), ";"]:
        if not (word and all(char in SEPARATOR_CHARS for char in word)):
            segment.append(word)
            continue
        words, segment = segment, []
        while words and ("=" in words[0] and not words[0].startswith("-") or words[0] in COMMAND_PREFIXES):
            words = words[1:]
        if not words or words[0] != "git":
            continue
        index, dash_c = 1, []
        while index < len(words) and words[index].startswith("-"):
            if words[index] in GIT_OPTIONS_WITH_VALUE:
                if words[index] == "-C" and index + 1 < len(words):
                    dash_c.append(words[index + 1])
                index += 2
            else:
                index += 1
        if index < len(words) and words[index] == "commit":
            return dash_c
    return None


def _git(directory: Path, *args: str) -> Optional[str]:
    try:
        result = subprocess.run(["git", "-C", str(directory), *args], capture_output=True, text=True,
                                timeout=GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _commit_directory(cwd: str, dash_c: List[str]) -> Path:
    directory = Path(cwd)
    for value in dash_c:
        candidate = Path(os.path.expanduser(value))
        directory = candidate if candidate.is_absolute() else directory / candidate
    return directory


def emit(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False))


def main() -> int:
    payload = json.load(sys.stdin)
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    if not isinstance(command, str) or not isinstance(cwd, str) or not cwd:
        return 0
    dash_c = commit_directories(command)
    if dash_c is None:
        return 0
    directory = _commit_directory(cwd, dash_c)
    branch = _git(directory, "symbolic-ref", "--quiet", "--short", "HEAD")
    if not branch or branch in DEFAULT_BRANCHES:
        return 0
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--head", branch, "--state", "all", "--json", "number,state,url", "--limit", "20"],
            cwd=directory, capture_output=True, text=True, timeout=GH_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"終了コード {result.returncode}")
        prs = json.loads(result.stdout or "[]")
        if not isinstance(prs, list):
            raise ValueError("gh の出力が一覧ではない")
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as error:
        emit({"systemMessage": f"ブランチ '{branch}' のPRがマージ済みかを確かめられなかった（{type(error).__name__}: {error}）"})
        return 0
    states = {pr.get("state") for pr in prs if isinstance(pr, dict)}
    if "OPEN" in states:
        return 0
    merged = [pr for pr in prs if isinstance(pr, dict) and pr.get("state") == "MERGED"]
    if merged:
        numbers = "、".join(f"#{pr.get('number')}" for pr in merged)
        emit({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"ブランチ '{branch}' のPR（{numbers}）はマージ済みで、開いているPRが無い。"
                "このままコミットしても、どのPRにも載らない。\n"
                "git switch -c <新しいブランチ> で移ってからコミットして（未コミットの変更は引き継がれる）。"
                "PRを作る前に git rebase origin/main で、マージ済みのコミットを取り除く。\n"
                "意図して続ける場合は、ユーザー自身が端末でコミットする。"
            ),
        }})
        return 0
    closed = [pr for pr in prs if isinstance(pr, dict) and pr.get("state") == "CLOSED"]
    if closed:
        numbers = "、".join(f"#{pr.get('number')}" for pr in closed)
        emit({"systemMessage": f"ブランチ '{branch}' のPR（{numbers}）はクローズされている。開いているPRは無い。"})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # 検査できなかったことを黙って通さず、画面に出す
        print(f"block-commit-on-merged-pr: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
