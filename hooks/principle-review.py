#!/usr/bin/env python3
"""仕様書・ADR・計画を含む git commit の直前に1回だけ止め、principle-reviewer の起動を促す。

設計: docs/superpowers/specs/2026-10-08-work-principles-design.md、ADR 0026
"""
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

TARGET_DIRS = {
    "spec": ("docs/superpowers/specs/", "docs/specs/", "docs/adr/"),
    "plan": ("docs/superpowers/plans/", "docs/plans/"),
}
EXCLUDED_NAMES = {"README.md"}
SHORT_FLAGS_WITH_VALUE = set("mFCct")  # この後ろの文字は値なので、-a の判定に使わない


def classify(relative: str) -> Optional[str]:
    """リポジトリ内の相対パスから節目を返す。対象外なら None。"""
    if not relative.endswith(".md") or Path(relative).name in EXCLUDED_NAMES:
        return None
    for checkpoint, prefixes in TARGET_DIRS.items():
        if relative.startswith(prefixes):
            return checkpoint
    return None


def uses_all_flag(tokens: List[str]) -> bool:
    """git commit に -a / --all があるか。-m の値として書かれた -a は数えない。"""
    skip_next = False
    for token in tokens[2:]:
        if skip_next:
            skip_next = False
            continue
        if token == "--all":
            return True
        if token.startswith("-") and not token.startswith("--") and len(token) > 1:
            for index, char in enumerate(token[1:]):
                if char == "a":
                    return True
                if char in SHORT_FLAGS_WITH_VALUE:
                    skip_next = index == len(token) - 2  # 値が次のトークンにある
                    break
    return False
