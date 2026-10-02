#!/usr/bin/env python3
"""スキルを呼んだのに必読資料を読んでいないことを、会話記録で見つけるClaude Codeフック。

使い方: skill-read-check.py <stop|subagent-stop>（入力はstdinのJSON）
対応表: manifests/skill-required-reads.json
設計: docs/superpowers/specs/2026-10-01-jp-doc-review-design.md の5節

確かめられるのは「読んだかどうか」だけで、読んだ内容に従ったかは確かめられない。
"""
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_support import (  # noqa: E402
    TranscriptError, after_last_compact, emit, read_entries, since_last_prompt, tool_uses, with_messages,
)

DEFAULT_MANIFEST = Path(__file__).resolve().parent.parent / "manifests" / "skill-required-reads.json"
EVENTS = {"stop": "transcript_path", "subagent-stop": "agent_transcript_path"}


def manifest_path() -> Path:
    override = os.environ.get("SKILL_READ_CHECK_MANIFEST")
    return Path(override) if override else DEFAULT_MANIFEST


def load_manifest() -> Dict[str, dict]:
    value = json.loads(manifest_path().read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schemaVersion") != 1 or not isinstance(value.get("skills"), dict):
        raise ValueError("skill-required-reads.json の形式が不正")
    return value["skills"]


def real(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path))


def read_paths(entries: List[dict]) -> Set[str]:
    return {
        real(tool_input["file_path"])
        for name, tool_input in tool_uses(entries)
        if name == "Read" and isinstance(tool_input.get("file_path"), str)
    }


def invoked_skills(manifest: Dict[str, dict], window: List[dict]) -> List[str]:
    """windowの中で呼ばれた登録済みのスキル。Skillの呼び出しか、SKILL.mdのReadで判定する。"""
    called = {str(tool_input.get("skill", "")).split(":")[-1] for name, tool_input in tool_uses(window) if name == "Skill"}
    window_reads = read_paths(window)
    return [
        name for name, entry in manifest.items()
        if name in called or os.path.join(real(entry["root"]), "SKILL.md") in window_reads
    ]


def missing_reads(entry: dict, reads: Set[str]) -> Tuple[List[str], List[str]]:
    """読まれていない必読資料（フルパス）と、ディスクに無い資料（対応表が古い）を返す。"""
    root = real(entry["root"])
    missing, stale = [], []
    for relative in entry.get("allOf", []):
        full = os.path.realpath(os.path.join(root, relative))
        if not os.path.exists(full):
            stale.append(relative)
        elif full not in reads:
            missing.append(full)
    for group in entry.get("anyOf", []):
        existing = [os.path.realpath(os.path.join(root, relative)) for relative in group]
        existing = [full for full in existing if os.path.exists(full)]
        if not existing:
            stale.append(" / ".join(group))
        elif not any(full in reads for full in existing):
            missing.append(" / ".join(existing) + " のうち1つ")
    return missing, stale


def _block_reason(problems: Dict[str, List[str]]) -> str:
    lines = ["スキルを呼んだのに、そのスキルが読むよう求める資料をまだ読んでいない。"
             "作業を終える前に、次の資料をReadで全文読み、その基準で作業を見直して。"]
    for name, missing in problems.items():
        lines.extend(f"- {name}: {item}" for item in missing)
    return "\n".join(lines)


def check(event: str, payload: dict) -> None:
    try:
        manifest = load_manifest()
    except (OSError, ValueError) as error:
        emit({"systemMessage": f"スキルの読み込み確認: 対応表を読めなかった（{error}）"})
        return
    try:
        entries = after_last_compact(read_entries(payload.get(EVENTS[event])))
    except TranscriptError as error:
        emit({"systemMessage": f"スキルの読み込み確認: 会話記録を読めなかったので確認していない（{error}）"})
        return
    window = entries if event == "subagent-stop" else since_last_prompt(entries)
    reads = read_paths(entries)
    problems: Dict[str, List[str]] = {}
    messages: List[str] = []
    for name in invoked_skills(manifest, window):
        missing, stale = missing_reads(manifest[name], reads)
        if stale:
            messages.append(f"スキルの読み込み確認: {name} の対応表が古い。ディスクに無い資料: {', '.join(stale)}")
        if missing:
            problems[name] = missing
    if problems and not payload.get("stop_hook_active"):
        emit(with_messages({"decision": "block", "reason": _block_reason(problems)}, messages))
        return
    if problems:
        summary = "; ".join(f"{name}（{', '.join(Path(item).name for item in missing)}）" for name, missing in problems.items())
        messages.append(f"スキルの必読資料が読まれないまま作業が終わった: {summary}")
    emit(with_messages({}, messages))


def main(argv: List[str]) -> int:
    if len(argv) != 2 or argv[1] not in EVENTS:
        print(f"使い方: {Path(argv[0]).name} <{'|'.join(EVENTS)}>", file=sys.stderr)
        return 1
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            raise ValueError("入力がJSONオブジェクトではない")
        check(argv[1], payload)
    except Exception as error:  # 検査できなかったことを黙って通さず、フックのエラーとして画面に出す
        print(f"skill-read-check {argv[1]}: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
