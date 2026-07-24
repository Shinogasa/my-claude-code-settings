#!/usr/bin/env python3
"""PreToolUse(Bash)フック: 確定的に危険なコマンドをブロックする。

対象は「状況に依存せず常にNG」なパターンのみ
(--no-verify等の判断が必要なものは対象外)。

コマンド文字列全体への正規表現マッチではなく、シェルの引用規則を
尊重してトークン化した上で、各サブコマンドの先頭トークン(コマンド名)
と引数トークンを見て判定する。これにより、コミットメッセージや
テストデータの中に"rm -rf /"のような文字列が引用符付きで
含まれているだけのケースを誤検知しない。
"""
import json
import re
import shlex
import sys

HEREDOC_RE = re.compile(r"<<[-~]?\s*['\"]?(\w+)['\"]?.*?\n.*?\n\1\b", re.DOTALL)
CONTROL_TOKENS = {";", "&&", "||", "|", "&"}

RM_FLAG_RE = re.compile(r"^-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*$|^-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*$")
RM_TARGET_RE = re.compile(r"^(/|~)$|^/\*$")
DEV_TARGET_RE = re.compile(r"^/dev/sd[a-z]")


def strip_heredocs(command: str) -> str:
    """ヒアドキュメント本体(実行されないテキスト)を空文字に置換する。"""
    return HEREDOC_RE.sub("", command)


def tokenize_line(line: str) -> list:
    """シェルの引用規則を尊重してトークン化する。パース不能なら空リスト。"""
    lexer = shlex.shlex(line, posix=True, punctuation_chars="|&;()<>")
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return []


def split_simple_commands(tokens: list) -> list:
    """制御演算子(; && || | &)でトークン列を単純コマンド列に分割する。"""
    commands = []
    current = []
    for tok in tokens:
        if tok in CONTROL_TOKENS:
            if current:
                commands.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        commands.append(current)
    return commands


def is_dangerous(tokens: list) -> bool:
    if not tokens:
        return False

    if tokens[0] == "rm":
        has_rf_flag = any(RM_FLAG_RE.match(t) for t in tokens[1:])
        has_danger_target = any(RM_TARGET_RE.match(t) for t in tokens[1:])
        if has_rf_flag and has_danger_target:
            return True

    if tokens[0] == "git":
        if len(tokens) >= 2 and tokens[1] == "push" and ("--force" in tokens or "-f" in tokens):
            return True
        if len(tokens) >= 2 and tokens[1] == "reset" and "--hard" in tokens:
            return True

    for i, tok in enumerate(tokens[:-1]):
        if tok == ">" and DEV_TARGET_RE.match(tokens[i + 1]):
            return True

    return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    command = payload.get("tool_input", {}).get("command", "")
    if not command:
        return 0

    executable_part = strip_heredocs(command)

    for line in executable_part.split("\n"):
        tokens = tokenize_line(line)
        for simple_command in split_simple_commands(tokens):
            if is_dangerous(simple_command):
                print(f"ブロック: 確定的に危険なコマンドを検出しました: {command}", file=sys.stderr)
                return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
