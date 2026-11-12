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
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_support import (  # noqa: E402
    TranscriptError, after_last_compact, emit, read_entries, since_last_prompt, tool_uses,
)

DEFAULT_PROFILE = Path(__file__).resolve().parent.parent / "CLAUDE.md"
DECLARATION = re.compile(r"重点学習中:\s*([^\n]+)")
# 宣言された言語名 → そのコードを扱ったとみなすツール入力のパターン
LANGUAGE_PATTERNS = {
    "Go": re.compile(r"\.go\b|\bgo (test|build|vet|run)\b"),
}
STATES = "出題|継続中|見送り|候補なし|OFF"
JUDGMENT_LINE = re.compile(rf"^\W*コード学習: .+ → ({STATES})（[^）]+）", re.MULTILINE)
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


def touched(window: List[dict], pattern: "re.Pattern[str]") -> bool:
    """ツールで扱ったか、本文で引用したか。前のターンで読んだコードを記憶から説明する応答も対象にする。"""
    inputs = [json.dumps(tool_input, ensure_ascii=False) for _name, tool_input in tool_uses(window)]
    return any(pattern.search(text) for text in inputs + assistant_texts(window))


def check(payload: dict) -> Optional[dict]:
    try:
        languages = declared_languages(profile_path().read_text(encoding="utf-8"))
    except OSError as error:
        return {"systemMessage": f"コード学習の確認: プロファイルを読めなかったので確認していない（{error}）"}
    if not languages:
        return None
    unknown = [name for name in languages if name not in LANGUAGE_PATTERNS]
    patterns = [LANGUAGE_PATTERNS[name] for name in languages if name in LANGUAGE_PATTERNS]
    messages = [f"コード学習の確認: 重点学習中の {', '.join(unknown)} はフックの対応表に無いので確認していない"] if unknown else []
    try:
        window = since_last_prompt(after_last_compact(read_entries(payload.get("transcript_path"))))
    except TranscriptError as error:
        return {"systemMessage": f"コード学習の確認: 会話記録を読めなかったので確認していない（{error}）"}
    if any(touched(window, pattern) for pattern in patterns) and not any(
            JUDGMENT_LINE.search(text) for text in assistant_texts(window)):
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
