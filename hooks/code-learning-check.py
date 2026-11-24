#!/usr/bin/env python3
"""重点学習中の領域のコードを扱ったターンで、コード学習の判定の一行が無ければ差し戻すClaude Codeフック。

使い方: code-learning-check.py stop（入力はstdinのJSON）
規約: rules/code-learning.md の「判定の一行」
設計: docs/adr/0050-code-learning-judgment-line-hook.md

確かめられるのは一行の有無と形式だけで、判定の中身が正しいかは確かめられない。
Stopで走るので、そのターンの本文は表示された後になる。役割は判定漏れの検出で、開示の防止ではない。
"""
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_support import (  # noqa: E402
    TranscriptError, after_last_compact, emit, read_entries, since_last_prompt, tool_uses,
)

DEFAULT_PROFILE = Path(__file__).resolve().parent.parent / "CLAUDE.md"
DECLARATION = re.compile(r"重点学習中:\s*([^\n]+)")

@dataclass(frozen=True)
class Language:
    """そのコードを扱ったとみなす手がかり。編集内容の文字列は見ない（正規表現やfixtureで誤検出するため）。"""
    path: "re.Pattern[str]"      # パス・コマンド・本文の中の、パスとして読める形
    command: "re.Pattern[str]"   # Bashで実行したツール
    grep_type: str               # Grepの type


# 宣言された言語名 → 手がかり。直前が \ のもの（エスケープした正規表現）と、直後に . や英数字が続くもの（.go.jp）は除く
LANGUAGES = {
    "Go": Language(
        path=re.compile(r"[\w/*-]\.go(?![\w.])"),
        command=re.compile(r"\bgo\s+(?:-C\s+\S+\s+)?(?:test|build|vet|run|mod|fmt|generate|get|install)\b"
                           r"|\bgofmt\b|\bgolangci-lint\b"),
        grep_type="go",
    ),
}
PATH_FIELDS = ("file_path", "path", "notebook_path", "glob")
# Bashでファイルの中身を読むコマンド。これが無いコマンドの .go パスは「扱った」に数えない。
# 文字列として渡しただけのパス（heredoc・python -c・echo）で差し戻していた（2026-11-19 の誤検知）
READ_COMMANDS = frozenset({"cat", "sed", "head", "tail", "grep", "egrep", "fgrep", "rg", "awk",
                           "less", "more", "nl", "bat", "diff"})
GIT_READ_SUBCOMMANDS = frozenset({"show", "diff", "blame", "log", "grep"})
# コマンドの前に置かれ、後ろのコマンドを起動するもの。シェルの予約語（for の do など）も同じく飛ばす
WRAPPERS = frozenset({"rtk", "sudo", "env", "command", "time", "xargs", "nice",
                      "do", "then", "else", "elif", "!", "{"})
SEPARATORS = frozenset({";", "&&", "||", "|", "&", "(", ")"})
HEREDOC_START = re.compile(r"(?<!<)<<(?!<)(-?)\s*(['\"]?)([A-Za-z_][\w-]*)\2")
ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")
STATES = "出題|継続中|見送り|候補なし|OFF"
# 推敲で起きやすい揺れ（全角コロン、半角括弧、->）は受け付ける
JUDGMENT_LINE = re.compile(rf"^\W*コード学習[:：]\s*.+?\s*(?:→|->)\s*({STATES})\s*[（(][^）)]+[）)]", re.MULTILINE)
FORMAT = "コード学習: <能力と対象> → <状態>（<根拠>）"


def profile_path() -> Path:
    override = os.environ.get("CODE_LEARNING_PROFILE")
    return Path(override) if override else DEFAULT_PROFILE


def declared_languages(text: str) -> List[str]:
    """ユーザープロファイルの「重点学習中: Go（初学者）、…」から言語名だけを取り出す。"""
    match = DECLARATION.search(text)
    if not match:
        return []
    names = []
    for item in re.split(r"[、,]", match.group(1)):
        name = re.split(r"[（(。\s]", item.strip(), maxsplit=1)[0]
        if name:
            names.append(name)
    return names


def assistant_texts(entries: List[dict]) -> List[str]:
    texts = []
    for entry in entries:
        message = entry.get("message") if entry.get("type") == "assistant" else None
        content = message.get("content") if isinstance(message, dict) else None
        for part in content if isinstance(content, list) else []:
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                texts.append(part["text"])
    return texts


def strip_heredoc_bodies(command: str) -> str:
    """heredoc の本文と終端行を除く。`<<` のある行は残す。"""
    kept: List[str] = []
    pending: List[tuple] = []
    for line in command.split("\n"):
        if pending:
            strip_tabs, delimiter = pending[0]
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                pending.pop(0)
            continue
        kept.append(line)
        pending = [(dash == "-", word) for dash, _, word in HEREDOC_START.findall(line)]
    return "\n".join(kept)


def _command_segments(line: str) -> List[List[str]]:
    """1行を、区切り記号（; && || | & 括弧）でコマンドごとの語の並びに分ける。引用が閉じていなければ ValueError。"""
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    segments: List[List[str]] = [[]]
    for token in lexer:
        if token in SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(token)
    return [segment for segment in segments if segment]


def _is_read_command(words: List[str]) -> bool:
    """コマンドの語の並びが、ファイルの中身を読むコマンドか。前置きのラッパーと変数の代入は飛ばす。"""
    index = 0
    while index < len(words) and (words[index] in WRAPPERS or ASSIGNMENT.match(words[index])):
        index += 1
    if index >= len(words):
        return False
    name = os.path.basename(words[index])
    if name == "git":
        subcommands = [word for word in words[index + 1:] if not word.startswith("-")]
        return bool(subcommands) and subcommands[0] in GIT_READ_SUBCOMMANDS
    return name in READ_COMMANDS


def bash_touched(command: str, language: Language) -> bool:
    """Bashのコマンドが、対象言語のツールを実行したか、対象言語のファイルを読んだか。

    パスは、読むコマンドの引数に限らず、同じコマンドのどこにあっても数える。
    変数（f=x.go; sed $f）、for の並び、$(...) を経由して読む形が、過去のログに多いため。
    heredoc の本文は、スクリプトに渡す文字列なので見ない。
    """
    body = strip_heredoc_bodies(command)
    if language.command.search(body):
        return True
    if not language.path.search(body):
        return False
    for line in body.split("\n"):
        try:
            segments = _command_segments(line)
        except ValueError:
            # 解析できない行は、読んだかどうかを確かめられない。見逃しより差し戻しの側に倒す
            return True
        if any(_is_read_command(words) for words in segments):
            return True
    return False


def _tool_touched(name: str, tool_input: dict, language: Language) -> bool:
    paths = [tool_input[field] for field in PATH_FIELDS if isinstance(tool_input.get(field), str)]
    if name == "Glob" and isinstance(tool_input.get("pattern"), str):
        paths.append(tool_input["pattern"])
    if any(language.path.search(value) for value in paths):
        return True
    if name == "Grep" and tool_input.get("type") == language.grep_type:
        return True
    command = tool_input.get("command") if name == "Bash" else None
    return isinstance(command, str) and bash_touched(command, language)


def touched(window: List[dict], language: Language) -> bool:
    """ツールで扱ったか、本文でパスを引用したか。前のターンで読んだコードを記憶から説明する応答も対象にする。"""
    if any(_tool_touched(name, tool_input, language) for name, tool_input in tool_uses(window)):
        return True
    return any(language.path.search(text) for text in assistant_texts(window))


def check(payload: dict) -> Optional[dict]:
    try:
        languages = declared_languages(profile_path().read_text(encoding="utf-8"))
    except OSError as error:
        return {"systemMessage": f"コード学習の確認: プロファイルを読めなかったので確認していない（{error}）"}
    if not languages:
        return None
    unknown = [name for name in languages if name not in LANGUAGES]
    known = [LANGUAGES[name] for name in languages if name in LANGUAGES]
    messages = [f"コード学習の確認: 重点学習中の {', '.join(unknown)} はフックの対応表に無いので確認していない"] if unknown else []
    try:
        window = since_last_prompt(after_last_compact(read_entries(payload.get("transcript_path"))))
    except TranscriptError as error:
        return {"systemMessage": f"コード学習の確認: 会話記録を読めなかったので確認していない（{error}）"}
    # Stopの時点では、最後の本文がまだ会話記録に書かれていないことがある。入力の本文も一行の検索に含める
    last_message = payload.get("last_assistant_message")
    texts = assistant_texts(window) + ([last_message] if isinstance(last_message, str) else [])
    if any(touched(window, language) for language in known) and not any(
            JUDGMENT_LINE.search(text) for text in texts):
        if payload.get("stop_hook_active"):
            messages.append("コード学習の確認: 判定の一行が無いまま応答が終わった")
        else:
            reason = ("重点学習中の領域のコードを扱ったのに、コード学習の判定の一行が無い。"
                      f"rules/code-learning.md に従って候補かどうかを判定し、次の形式で一行書いて。\n{FORMAT}\n"
                      f"状態は {STATES.replace('|', ' / ')} のどれか。候補なら、所見と理由を書かずに課題として出す。")
            return {"decision": "block", "reason": reason, **({"systemMessage": "\n".join(messages)} if messages else {})}
    return {"systemMessage": "\n".join(messages)} if messages else None


def main(argv: List[str]) -> int:
    if len(argv) != 2 or argv[1] != "stop":
        print(f"使い方: {Path(argv[0]).name} stop", file=sys.stderr)
        return 1
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            raise ValueError("入力がJSONオブジェクトではない")
        result = check(payload)
        if result:
            emit(result)
    except Exception as error:  # 検査できなかったことを黙って通さず、フックのエラーとして画面に出す
        print(f"code-learning-check: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
