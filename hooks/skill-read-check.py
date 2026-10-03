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
    TranscriptError, after_last_compact, emit, first_text, read_entries, since_last_prompt, tool_uses, with_messages,
)

DEFAULT_MANIFEST = Path(__file__).resolve().parent.parent / "manifests" / "skill-required-reads.json"
EVENTS = {"stop": "transcript_path", "subagent-stop": "agent_transcript_path"}
BASE_DIRECTORY_PREFIX = "Base directory for this skill: "  # スラッシュコマンドでスキルを呼んだときに残る行


def manifest_path() -> Path:
    override = os.environ.get("SKILL_READ_CHECK_MANIFEST")
    return Path(override) if override else DEFAULT_MANIFEST


def load_manifest() -> Dict[str, dict]:
    value = json.loads(manifest_path().read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schemaVersion") != 1 or not isinstance(value.get("skills"), dict):
        raise ValueError("skill-required-reads.json の形式が不正")
    for name, entry in value["skills"].items():
        alternates = entry.get("alternateRoots", []) if isinstance(entry, dict) else None
        if not isinstance(alternates, list) or not all(isinstance(item, str) for item in alternates):
            raise ValueError(f"skill-required-reads.json の {name} の alternateRoots が文字列のリストではない")
    return value["skills"]


def real(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path))


def roots(entry: dict) -> List[str]:
    """スキルの置き場（実体のパス）。複製の置き場も含める。"""
    return [real(root) for root in [entry["root"], *entry.get("alternateRoots", [])]]


def bash_commands(entries: List[dict]) -> List[str]:
    return [
        tool_input["command"]
        for name, tool_input in tool_uses(entries)
        if name == "Bash" and isinstance(tool_input.get("command"), str)
    ]


def base_directories(entries: List[dict]) -> Set[str]:
    """スラッシュコマンドで呼ばれたスキルの置き場（実体のパス）。"""
    found = set()
    for entry in entries:
        if entry.get("type") != "user" or not entry.get("isMeta"):
            continue
        text = first_text(entry) or ""
        if text.startswith(BASE_DIRECTORY_PREFIX):
            found.add(real(text[len(BASE_DIRECTORY_PREFIX):].split("\n", 1)[0].strip()))
    return found


def read_paths(entries: List[dict]) -> Set[str]:
    return {
        real(tool_input["file_path"])
        for name, tool_input in tool_uses(entries)
        if name == "Read" and isinstance(tool_input.get("file_path"), str)
    }


def invoked_skills(manifest: Dict[str, dict], window: List[dict]) -> List[str]:
    """windowの中で呼ばれた登録済みのスキル。

    Skillの呼び出し、いずれかの置き場のSKILL.mdのRead、スラッシュコマンドで残る置き場の行のどれかで判定する。
    """
    called = {str(tool_input.get("skill", "")).split(":")[-1] for name, tool_input in tool_uses(window) if name == "Skill"}
    window_reads = read_paths(window)
    bases = base_directories(window)
    invoked = []
    for name, entry in manifest.items():
        skill_roots = roots(entry)
        if (name in called or bases.intersection(skill_roots)
                or any(os.path.join(root, "SKILL.md") in window_reads for root in skill_roots)):
            invoked.append(name)
    return invoked


def _was_read(relative: str, candidates: List[str], reads: Set[str], commands: List[str]) -> bool:
    """Readの呼び出しか、Bashのコマンドに相対パスか実体のパスがあれば、読んだとみなす（近似）。"""
    if any(full in reads for full in candidates):
        return True
    return any(relative in command or any(full in command for full in candidates) for command in commands)


def missing_reads(entry: dict, reads: Set[str], commands: List[str]) -> Tuple[List[Tuple[str, str]], List[str]]:
    """読まれていない必読資料と、ディスクに無い資料（対応表が古い）を返す。

    戻り値:
    - missing: (display_name, full_description) のタプルのリスト
      - allOf: ("filename", "/full/path")
      - anyOf: ("x.md / y.md のうち1つ", "/…/x.md / /…/y.md のうち1つ")
    - stale: 文字列のリスト
    """
    skill_roots = roots(entry)

    def existing(relative: str) -> List[str]:
        candidates = [os.path.realpath(os.path.join(root, relative)) for root in skill_roots]
        return [full for full in candidates if os.path.exists(full)]

    missing: List[Tuple[str, str]] = []
    stale: List[str] = []
    for relative in entry.get("allOf", []):
        candidates = existing(relative)
        if not candidates:
            stale.append(relative)
        elif not _was_read(relative, candidates, reads, commands):
            missing.append((Path(relative).name, candidates[0]))
    for group in entry.get("anyOf", []):
        found = {relative: existing(relative) for relative in group}
        if not any(found.values()):
            stale.append(" / ".join(group))
        elif not any(_was_read(relative, candidates, reads, commands) for relative, candidates in found.items()):
            display = " / ".join(Path(relative).name for relative in group) + " のうち1つ"
            full_description = " / ".join(candidates[0] for candidates in found.values() if candidates) + " のうち1つ"
            missing.append((display, full_description))
    return missing, stale


def _block_reason(problems: Dict[str, List[Tuple[str, str]]]) -> str:
    lines = ["スキルを呼んだのに、そのスキルが読むよう求める資料をまだ読んでいない。"
             "作業を終える前に、次の資料をReadで全文読み、その基準で作業を見直して。"]
    for name, missing in problems.items():
        lines.extend(f"- {name}: {description}" for _display, description in missing)
    return "\n".join(lines)


def check(event: str, payload: dict) -> None:
    try:
        manifest = load_manifest()
    except (OSError, ValueError) as error:
        emit({"systemMessage": f"スキルの読み込み確認: 対応表を読めなかった（{error}）"})
        return
    if event == "subagent-stop" and not payload.get("agent_type"):
        return  # Claude Codeの内部のエージェント（プロンプト候補など）でも発火するため、何もしない
    try:
        entries = after_last_compact(read_entries(payload.get(EVENTS[event])))
    except TranscriptError as error:
        emit({"systemMessage": f"スキルの読み込み確認: 会話記録を読めなかったので確認していない（{error}）"})
        return
    window = entries if event == "subagent-stop" else since_last_prompt(entries)
    reads = read_paths(entries)
    commands = bash_commands(entries)
    problems: Dict[str, List[Tuple[str, str]]] = {}
    messages: List[str] = []
    for name in invoked_skills(manifest, window):
        missing, stale = missing_reads(manifest[name], reads, commands)
        if stale:
            messages.append(f"スキルの読み込み確認: {name} の対応表が古い。ディスクに無い資料: {', '.join(stale)}")
        if missing:
            problems[name] = missing
    if problems and not payload.get("stop_hook_active"):
        emit(with_messages({"decision": "block", "reason": _block_reason(problems)}, messages))
        return
    if problems:
        summary = "; ".join(f"{name}（{', '.join(display for display, _desc in missing)}）" for name, missing in problems.items())
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
