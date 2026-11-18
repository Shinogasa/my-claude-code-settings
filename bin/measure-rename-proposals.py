#!/usr/bin/env python3
"""ブランチを作ったセッションのうち、その後に /rename を提案したものを月ごとに数える。

使い方: python3 ~/.claude/bin/measure-rename-proposals.py [--root ~/.claude/projects]
設計: docs/adr/0053-session-rename-nudge-hook.md

出力は件数だけで、会話の中身は出さない。会話記録は guard-secret-read.py が
エージェントからの読み取りを止めるので、ユーザーが端末（Claude Codeでは `!`）で実行する。

数えているのは「ブランチ作成の後の本文に /rename の文字があるか」で、ユーザーが実際に
/rename したかや、セッションを見つけやすくなったかは測っていない（ADR 0053 の「結果」）。
"""
import argparse
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "suggest-session-rename.py"


def load_hook():
    """ブランチ作成の判定はフックと同じものを使う。測る対象と促す対象をずらさないため。"""
    spec = importlib.util.spec_from_file_location("suggest_session_rename", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def measure(path: Path, creates_branch):
    """(ブランチを作った最初の時刻, 提案したか) を返す。ブランチを作っていなければ None。"""
    first = None
    proposed = False
    for line in path.open(encoding="utf-8", errors="replace"):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        for content in (entry.get("message") or {}).get("content") or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") == "tool_use":
                payload = {"tool_name": content.get("name"), "tool_input": content.get("input")}
                if first is None and creates_branch(payload):
                    first = entry.get("timestamp") or ""
            elif content.get("type") == "text" and first is not None and "/rename" in content.get("text", ""):
                proposed = True
    return None if first is None else (first, proposed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.home() / ".claude" / "projects")
    args = parser.parse_args()

    files = sorted(args.root.glob("*/*.jsonl"))
    if not files:
        # 0件を「漏れなし」と区別できなくなるので、目立つ形で失敗させる
        print(f"会話記録が見つからない: {args.root}/*/*.jsonl", file=sys.stderr)
        return 2

    creates_branch = load_hook().creates_branch
    months = defaultdict(lambda: [0, 0])
    unreadable = 0
    for path in files:
        try:
            result = measure(path, creates_branch)
        except OSError:
            unreadable += 1
            continue
        if result is None:
            continue
        first, proposed = result
        months[first[:7] or "(時刻なし)"][0] += 1
        months[first[:7] or "(時刻なし)"][1] += int(proposed)

    print("月 ブランチ作成セッション数 /rename提案あり")
    for month in sorted(months):
        print(month, *months[month])
    print("読めなかったファイル", unreadable)
    return 0


if __name__ == "__main__":
    sys.exit(main())
