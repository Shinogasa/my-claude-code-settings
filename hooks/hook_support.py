"""Claude Codeのフックが共通で使う、会話記録の読み取りと出力の組み立て。

会話記録（JSONL）の形式はClaude Codeの内部仕様で、公開された契約ではない。
形式が変わって読めなくなったときは TranscriptError を投げ、呼び出し側が画面に表示する。
"""
import json
from typing import List, Optional, Tuple

ToolUse = Tuple[str, dict]
TASK_NOTIFICATION = "<task-notification>"  # バックグラウンドの作業の完了通知。userの行として残る


class TranscriptError(Exception):
    """会話記録を読めなかったことを表す。"""


def read_entries(path: Optional[str], start_offset: int = 0) -> List[dict]:
    """会話記録の各行をdictで返す。JSONとして読めない行は飛ばす。

    中身があるのに1行も読めないときは、形式が変わったとみなして例外にする。
    """
    if not path:
        raise TranscriptError("入力に会話記録のパスが無い")
    try:
        with open(path, "rb") as handle:
            handle.seek(start_offset)
            raw = handle.read().decode("utf-8", errors="replace")
    except OSError as error:
        raise TranscriptError(f"会話記録を開けない: {error}") from error
    entries = []
    for line in raw.split("\n"):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            entries.append(value)
    if raw.strip() and not entries:
        raise TranscriptError("会話記録の行をJSONとして読めない")
    return entries


def after_last_compact(entries: List[dict]) -> List[dict]:
    """最後のcompactの区切りより後の行だけを返す。"""
    last = -1
    for index, entry in enumerate(entries):
        if entry.get("type") == "system" and entry.get("subtype") == "compact_boundary":
            last = index
    return entries[last + 1:]


def _content(entry: dict):
    message = entry.get("message")
    return message.get("content") if isinstance(message, dict) else None


def first_text(entry: dict) -> Optional[str]:
    """行の本文の最初の文字列を返す。本文が文字列ならそのまま、textのリストなら最初のtextを返す。"""
    content = _content(entry)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                return part["text"]
    return None


def is_human_prompt(entry: dict) -> bool:
    """ユーザーが入力したプロンプトの行か。ツールの結果、メタ情報、作業の完了通知の行は含めない。"""
    if entry.get("type") != "user" or entry.get("isMeta"):
        return False
    content = _content(entry)
    if isinstance(content, list):
        kinds = {part.get("type") for part in content if isinstance(part, dict)}
        if "text" not in kinds or "tool_result" in kinds:
            return False
    elif not isinstance(content, str):
        return False
    text = first_text(entry)
    return not (text or "").startswith(TASK_NOTIFICATION)


def since_last_prompt(entries: List[dict]) -> List[dict]:
    """最後のユーザーのプロンプトより後の行だけを返す。"""
    last = -1
    for index, entry in enumerate(entries):
        if is_human_prompt(entry):
            last = index
    return entries[last + 1:]


def tool_uses(entries: List[dict]) -> List[ToolUse]:
    """アシスタントのツール呼び出しを、(ツール名, 入力) の組にして順に返す。"""
    result: List[ToolUse] = []
    for entry in entries:
        if entry.get("type") != "assistant":
            continue
        content = _content(entry)
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "tool_use":
                tool_input = part.get("input")
                result.append((str(part.get("name", "")), tool_input if isinstance(tool_input, dict) else {}))
    return result


def emit(value: dict) -> None:
    """フックの出力を標準出力に書く。空なら何も書かない。"""
    if value:
        print(json.dumps(value, ensure_ascii=False))


def with_messages(value: dict, messages: List[str]) -> dict:
    """画面に表示する文があれば、systemMessage として足した新しいdictを返す。"""
    if not messages:
        return dict(value)
    return {**value, "systemMessage": "\n".join(messages)}
