#!/usr/bin/env python3
"""既存の Confluence ページを Markdown で全文置き換えする呼び出しを、送る前に止める。

Markdown では info パネル・目次・折りたたみなどのマクロを表せないので、既存ページに
それらがあると API が 422 で拒否する（2026-11-02）。止めるときは、HTML で送り直す手順を理由に書く。

jp-doc-review の pre-tool-use-confluence と同じ呼び出しで並列に動く（順序は保証されない）。
そのため、日本語レビューを先に済ませてから変換する順番も、理由に書いて指示する（ADR 0046）。

終了コード1やタイムアウトでは止まらずに送られるので、入力を読めなかったときは ask にする。
"""
import json
import sys

UPDATE_TOOL_SUFFIX = "__updateConfluencePage"
BLOCKED_FORMAT = "markdown"
CONVERTER = "~/.claude/bin/md-to-confluence-html.py"

REASON = (
    "既存の Confluence ページを Markdown で全文置き換えしようとしたので、送る前に止めた。この更新はまだ送っていない。\n"
    "Markdown ではページにある info パネル・目次・折りたたみなどのマクロを表せず、API が 422 で拒否するか、内容が失われる。\n"
    "次の順で、HTML で送り直して。\n"
    "1. jp-doc-review が同時に下書きを書き出していたら、先にそのレビューを終える。以降は、レビュー後の下書きを使う\n"
    "2. getConfluencePage で既存ページを contentFormat: html で取得し、残すべきマクロや拡張要素（data-type=\"extension\" など）を確かめる\n"
    "3. getContentFormatGuide（toolName: updateConfluencePage）を読み、書式を確かめる\n"
    f"4. Markdown の下書きを `python3 {CONVERTER} <下書き.md>` で HTML に変換する。"
    "info パネル・目次・折りたたみは、変換スクリプトのオプション（--help を参照）で付けられる\n"
    "5. 既存ページから残すマクロを変換結果に戻し、updateConfluencePage を contentFormat: html で呼び直す"
)


def decide(decision: str, reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
    }}, ensure_ascii=False))


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
        tool_name = str(payload["tool_name"])
        tool_input = payload.get("tool_input") or {}
        if not isinstance(tool_input, dict):
            raise TypeError("tool_input がオブジェクトではない")
    except Exception as error:  # 検査できなかったときは通さず、ユーザーに確かめる
        print(f"guard-confluence-markdown: {type(error).__name__}: {error}", file=sys.stderr)
        decide("ask", f"Confluence へ送る本文の形式を検査できなかった（{type(error).__name__}: {error}）。"
                      "このまま送ってよいかを確かめて。")
        return
    if not tool_name.endswith(UPDATE_TOOL_SUFFIX):
        return
    content_format = str(tool_input.get("contentFormat") or "").strip().lower()
    if content_format == BLOCKED_FORMAT:
        decide("deny", REASON)


if __name__ == "__main__":
    main()
