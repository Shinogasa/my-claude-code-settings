#!/usr/bin/env python3
"""日本語文書のレビューをjp-doc-reviewerへ依頼するClaude Codeフック。

使い方: jp-doc-review.py <post-tool-use|stop|pre-tool-use>（入力はstdinのJSON）
設計: docs/superpowers/specs/2026-10-01-jp-doc-review-design.md
判断の経緯: docs/adr/0024-jp-doc-review-hook.md
"""
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_support import emit, with_messages  # noqa: E402

MIN_JP_CHARS = 100
TARGET_SUFFIXES = {".md", ".toml", ".yaml", ".yml", ".json"}
STATE_RETENTION_DAYS = 7
REVIEWER_AGENT = "jp-doc-reviewer"
EXCLUDED_DIR_NAMES = {"node_modules", "vendor", "dist", "build", ".git"}
LOCKFILE_NAMES = {
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock",
    "composer.lock", "Pipfile.lock", "poetry.lock", "uv.lock", "Cargo.lock",
}
KANA = re.compile(r"[ぁ-ゖァ-ヺー]")
JP_CHAR = re.compile(r"[ぁ-ゖァ-ヺー々一-鿿]")
SUBMODULE_GITDIR = re.compile(r"\.git/modules/")
UNSAFE_ID_CHARS = re.compile(r"[^A-Za-z0-9_-]")


def state_dir() -> Path:
    override = os.environ.get("JP_DOC_REVIEW_STATE_DIR")
    return Path(override) if override else Path.home() / ".claude" / "state" / "jp-doc-review"


def drafts_dir() -> Path:
    return state_dir() / "drafts"


def yomiyasu_skill() -> Path:
    override = os.environ.get("JP_DOC_REVIEW_YOMIYASU_SKILL")
    return Path(override) if override else Path.home() / ".claude" / "skills" / "yomiyasu" / "SKILL.md"


def session_key(payload: dict) -> str:
    """状態ファイルの名前に使うセッションIDを返す。使えない文字を含むときはハッシュにする。"""
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("入力にsession_idが無い")
    if UNSAFE_ID_CHARS.search(session_id):
        return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
    return session_id


def count_jp_chars(text: str) -> int:
    """日本語の文字数を数える。かなを含まない文字列は、中国語と区別できないので0とみなす。"""
    if not text or not KANA.search(text):
        return 0
    return len(JP_CHAR.findall(text))


def _git_marker_kind(marker: Path) -> str:
    """.git の種類を返す。repo（通常の作業ツリーかworktree）、submodule、none のどれか。"""
    if marker.is_dir():
        return "repo"
    if not marker.is_file():
        return "none"
    try:
        first_line = marker.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    except (OSError, IndexError):
        return "repo"
    return "submodule" if SUBMODULE_GITDIR.search(first_line.replace("\\", "/")) else "repo"


def _find_git_root(path: Path) -> Tuple[Optional[Path], str]:
    for parent in path.parents:
        kind = _git_marker_kind(parent / ".git")
        if kind != "none":
            return parent, kind
    return None, "none"


def is_target(path: Path) -> bool:
    """レビューの記録対象か。pathはsymlinkを解決した絶対パスで渡す。"""
    if path.suffix not in TARGET_SUFFIXES or path.name in LOCKFILE_NAMES:
        return False
    if drafts_dir().resolve() in path.parents:
        return False
    root, kind = _find_git_root(path)
    if kind == "submodule":
        return False
    inner = path.relative_to(root).parts if root else path.parts
    return not any(part in EXCLUDED_DIR_NAMES for part in inner[:-1])


def _written_text(tool_name: str, tool_input: dict) -> Tuple[Optional[str], str]:
    if tool_name == "Write":
        return tool_input.get("file_path"), str(tool_input.get("content") or "")
    if tool_name == "Edit":
        return tool_input.get("file_path"), str(tool_input.get("new_string") or "")
    return None, ""


def _log_path(key: str) -> Path:
    return state_dir() / f"{key}.jsonl"


def _append_record(key: str, record: dict) -> None:
    """記録を1行追記する。並行した書き込みでも行が混ざらないよう、1回のwriteで書く。"""
    state_dir().mkdir(parents=True, exist_ok=True)
    line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(_log_path(key), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def read_records(key: str) -> Tuple[List[dict], int]:
    """記録と、形式が合わずに飛ばした行の数を返す。"""
    path = _log_path(key)
    if not path.exists():
        return [], 0
    records, skipped = [], 0
    for line in path.read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if isinstance(value, dict) and isinstance(value.get("path"), str) and isinstance(value.get("jp_chars"), int):
            records.append(value)
        else:
            skipped += 1
    return records, skipped


def write_records(key: str, records: List[dict]) -> None:
    path = _log_path(key)
    if not records:
        path.unlink(missing_ok=True)
        return
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def handle_post_tool_use(payload: dict) -> None:
    if payload.get("agent_type") == REVIEWER_AGENT:
        return
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    raw_path, text = _written_text(str(payload.get("tool_name", "")), tool_input)
    if not raw_path:
        return
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(str(payload.get("cwd") or ".")) / path
    path = Path(os.path.realpath(path))
    if not is_target(path):
        return
    jp_chars = count_jp_chars(text)
    if jp_chars == 0:
        return
    _append_record(session_key(payload), {"path": str(path), "jp_chars": jp_chars})


HANDLERS = {
    "post-tool-use": handle_post_tool_use,
}


def main(argv: List[str]) -> int:
    if len(argv) != 2 or argv[1] not in HANDLERS:
        print(f"使い方: {Path(argv[0]).name} <{'|'.join(HANDLERS)}>", file=sys.stderr)
        return 1
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            raise ValueError("入力がJSONオブジェクトではない")
        HANDLERS[argv[1]](payload)
    except Exception as error:  # 検査できなかったことを黙って通さず、フックのエラーとして画面に出す
        print(f"jp-doc-review {argv[1]}: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
