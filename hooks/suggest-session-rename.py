#!/usr/bin/env python3
"""ブランチを作った直後に、/rename の提案を促す文をエージェントの文脈へ差し込むClaude Codeフック（PostToolUse）。

規約: CLAUDE.md の「セッションの見つけやすさ（Claude Code）」
設計: docs/adr/0053-session-rename-nudge-hook.md

促すだけで、提案が実際に出たかは確かめない。効果は会話記録の再測定で確かめる（ADR参照）。
入力が読めないときは何も出さずに終える。止める役割を持たないので、fail-openでよい。
"""
import json
import re
import sys

# コマンドの先頭か、区切り（; & | 改行 括弧）の直後にある git だけを見る。echo の引用符の中などは拾わない
BRANCH_CREATING = re.compile(
    r"(?:^|[;&|\n(])\s*git\s+(?:-C\s+\S+\s+)?"
    r"(?:switch\s+(?:-c|-C|--create|--force-create)\b"
    r"|checkout\s+(?:-b|-B)\b"
    r"|worktree\s+add\b)"
)
MESSAGE = (
    "ブランチを作った（またはworktreeに入った）。CLAUDE.md の「セッションの見つけやすさ」に従い、"
    "この応答でユーザーへ `/rename <作業内容> (<ブランチ名>)` を提案する。作業内容は日本語で短く書く。"
    "Planモードの承認でセッションに自動タイトルが付いている場合は省いてよい。"
)


def creates_branch(payload: dict) -> bool:
    tool_name = payload.get("tool_name")
    if tool_name == "EnterWorktree":
        return True
    if tool_name != "Bash":
        return False
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    return isinstance(command, str) and BRANCH_CREATING.search(command) is not None


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0
    # サブエージェントは /rename を提案する相手（ユーザー）と話していない
    if payload.get("agent_id"):
        return 0
    if not creates_branch(payload):
        return 0
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": MESSAGE}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
