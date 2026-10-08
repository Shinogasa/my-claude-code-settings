#!/usr/bin/env python3
"""仕様書・ADR・計画を含む git commit の直前に1回だけ止め、principle-reviewer の起動を促す。

設計: docs/superpowers/specs/2026-10-08-work-principles-design.md、ADR 0026
"""
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hook_support import TranscriptError, emit, read_entries, tool_uses, with_messages  # noqa: E402

_guard_spec = importlib.util.spec_from_file_location(
    "guard_dangerous_bash", Path(__file__).resolve().parent / "guard-dangerous-bash.py")
guard = importlib.util.module_from_spec(_guard_spec)
_guard_spec.loader.exec_module(guard)

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


REVIEWER_AGENT = "principle-reviewer"
GIT_TIMEOUT_SECONDS = 10
STATE_RETENTION_DAYS = 7
UNSAFE_ID_CHARS = re.compile(r"[^A-Za-z0-9_-]")


class GitError(Exception):
    """git の実行に失敗したことを表す。リポジトリ外であることとは区別する。"""


def state_dir() -> Path:
    override = os.environ.get("PRINCIPLE_REVIEW_STATE_DIR")
    return Path(override) if override else Path.home() / ".claude" / "state" / "principle-review"


def data_path() -> Path:
    override = os.environ.get("PRINCIPLE_REVIEW_DATA")
    return Path(override) if override else Path.home() / ".claude" / "skills" / "work-principles" / "principles.json"


def commit_targets(command: str, cwd: str) -> List[Tuple[str, bool]]:
    """コマンド中の git commit ごとに、コミット先のディレクトリと -a の有無を返す。

    ディレクトリの解決は guard-dangerous-bash.py の main と同じ手順で行う。
    確定できない移動先（UNRESOLVED）は、guard がコミットごと止めるので、ここでは数えない。
    """
    tokens = guard.tokenize_command(guard.strip_heredocs(command))
    if tokens is None:
        return []
    candidates = {os.path.abspath(cwd)}
    seen = set(candidates)
    cdpath_possible = "CDPATH" in command or bool(os.environ.get("CDPATH"))
    targets: List[Tuple[str, bool]] = []
    for previous_op, simple_command, next_op, _raw in guard.split_with_operators(tokens):
        if guard.operator_kind(previous_op) in ("SEQ", "BREAK"):
            candidates = set(seen)
        candidates = guard.apply_directory_change(previous_op, simple_command, next_op, candidates, cdpath_possible)
        seen |= candidates
        if guard.is_git_commit(simple_command):
            all_flag = uses_all_flag(simple_command)
            for target in guard.git_target_dirs(simple_command, candidates):
                if target is not guard.UNRESOLVED:
                    targets.append((target, all_flag))
    return targets


def _git(repo: str, *args: str) -> subprocess.CompletedProcess:
    try:
        # メッセージで「リポジトリ外」を見分けるので、翻訳されないよう LC_ALL=C にする
        return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                              timeout=GIT_TIMEOUT_SECONDS, env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError) as error:
        raise GitError(f"git を実行できない: {error}") from error


def changed_targets(repo: str, include_unstaged: bool) -> List[Tuple[str, str]]:
    """コミットに入る対象ファイルを、(絶対パス, 節目) で返す。リポジトリ外なら空。"""
    top = _git(repo, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        if "not a git repository" in top.stderr:
            return []
        raise GitError(top.stderr.strip() or "git rev-parse に失敗した")
    root = top.stdout.strip()
    # -z で取り、日本語やスペースを含むパスが引用されないようにする。d（小文字）は削除を除く
    queries = [["diff", "--cached", "--name-only", "-z", "--diff-filter=d"]]
    if include_unstaged:
        queries.append(["diff", "--name-only", "-z", "--diff-filter=d"])
    found: List[Tuple[str, str]] = []
    for query in queries:
        result = _git(root, *query)
        if result.returncode != 0:
            raise GitError(result.stderr.strip() or "git diff に失敗した")
        for relative in filter(None, result.stdout.split("\0")):
            checkpoint = classify(relative)
            item = (str(Path(root) / relative), checkpoint)
            if checkpoint and item not in found:
                found.append(item)
    return found


def session_key(payload: dict) -> Optional[str]:
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None
    if UNSAFE_ID_CHARS.search(session_id):
        return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
    return session_id


@contextmanager
def session_lock(key: str) -> Iterator[None]:
    """同じセッションのフックが並行して動いても、同じファイルを2回「1回目」と数えないようにする。"""
    state_dir().mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(state_dir(), 0o700)
    lock_path = state_dir() / f"{key}.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.utime(lock_path)  # 使っているロックを、古い状態の掃除で消さないようにする
        yield
    finally:
        os.close(fd)


def read_state(key: str) -> dict:
    path = state_dir() / f"{key}.json"
    if not path.exists():
        return {"paths": {}, "error_shown": False}
    fresh = {"paths": {}, "error_shown": False}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return fresh  # 壊れた状態は空に置き換える。対象は未記録になるので1回止まる
    if not isinstance(state, dict) or not isinstance(state.get("paths"), dict):
        return fresh
    state.setdefault("error_shown", False)  # error_shown が欠けた状態でも KeyError にしない
    return state


def write_state(key: str, value: dict) -> None:
    fd, temporary = tempfile.mkstemp(dir=state_dir(), prefix=f".{key}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False)
        os.replace(temporary, state_dir() / f"{key}.json")
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def cleanup_old_state() -> None:
    limit = time.time() - STATE_RETENTION_DAYS * 86400
    for path in state_dir().glob("*"):
        try:
            if path.is_file() and path.stat().st_mtime < limit:
                path.unlink()
        except FileNotFoundError:
            continue  # 並行して動いた別のフックが先に消した


def transcript_size(payload: dict) -> int:
    path = payload.get("transcript_path")
    try:
        return os.path.getsize(path) if isinstance(path, str) else 0
    except OSError:
        return 0


def deny(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def review_request(pending: List[Tuple[str, str]]) -> str:
    lines = [f"- {checkpoint}: {path}" for path, checkpoint in pending]
    return "\n".join([
        "原則レビュー: 次の成果物を、コミットの前に仕事の原則と照らす。",
        *lines,
        f"Agentツールで {REVIEWER_AGENT} を起動し、上のパスと節目だけを渡す（会話の要約は渡さない）。",
        "返ってきた問いは要約せずにユーザーへ出す。直すかどうかはユーザーが決める。",
        "レビューを依頼したら、同じコミットをやり直してよい（このファイルでは2回目は止めない）。",
    ])


AGENT_TOOL_NAMES = {"Agent", "Task"}  # 古い版ではサブエージェントの起動ツールがTaskという名前だった


def data_problem() -> Optional[str]:
    try:
        json.loads(data_path().read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return f"原則集を読めない（{data_path()}: {type(error).__name__}）。setup.sh を実行したか確かめる"
    return None


def reviewer_started(payload: dict, offset: int) -> Optional[bool]:
    try:
        entries = read_entries(payload.get("transcript_path"), offset)
    except TranscriptError:
        return None
    return any(name in AGENT_TOOL_NAMES and tool_input.get("subagent_type") == REVIEWER_AGENT
               for name, tool_input in tool_uses(entries))


def handle(payload: dict) -> dict:
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    cwd = payload.get("cwd")
    if not isinstance(command, str) or not isinstance(cwd, str) or not cwd:
        raise ValueError("入力に command か cwd が無い")
    targets: List[Tuple[str, str]] = []
    errors: List[str] = []
    for repo, all_flag in commit_targets(command, cwd):
        try:
            for item in changed_targets(repo, all_flag):
                if item not in targets:
                    targets.append(item)
        except GitError as error:
            errors.append(f"{repo}: {error}")
    if not targets and not errors:
        return {}
    key = session_key(payload)
    if key is None:
        return with_messages({}, ["原則レビューを検査できなかった（入力に session_id が無い）。止めずに通した"])
    with session_lock(key):
        cleanup_old_state()
        state = read_state(key)
        pending = [(path, checkpoint) for path, checkpoint in targets if path not in state["paths"]]
        problem = data_problem()
        if problem:
            # 原則集を読めないとレビュワーが動けない。対象は記録せず、レビューできなかった対象を毎回名指す
            problems = [*errors, problem]
            unreviewed = [f"レビューできなかった対象: {path}" for path, _checkpoint in targets]
            if not state["error_shown"]:
                state["error_shown"] = True
                write_state(key, state)
                lines = "\n".join(f"- {line}" for line in [*problems, *unreviewed])
                return deny("原則レビューを検査できなかったので1回止めた。\n" + lines)
            return with_messages({}, ["原則レビューを検査できないまま通した:", *problems, *unreviewed])
        if pending:
            for path, _checkpoint in pending:
                state["paths"][path] = {"offset": transcript_size(payload), "checked": False}
            reason = review_request(pending)
            if errors:
                state["error_shown"] = True
                reason += "\n次のリポジトリは検査できなかった:\n" + "\n".join(f"- {e}" for e in errors)
            write_state(key, state)
            return deny(reason)
        if errors:
            if not state["error_shown"]:
                state["error_shown"] = True
                write_state(key, state)
                return deny("原則レビューを検査できなかったので1回止めた。\n" + "\n".join(f"- {e}" for e in errors))
            return with_messages({}, ["原則レビューを検査できないまま通した:", *errors])
        messages = []
        for path, _checkpoint in targets:
            record = state["paths"][path]
            if record["checked"]:
                continue
            record["checked"] = True
            started = reviewer_started(payload, record["offset"])
            if started is None:
                messages.append(f"{REVIEWER_AGENT} の起動を確かめられなかった（会話記録を読めない）: {path}")
            elif not started:
                messages.append(f"{REVIEWER_AGENT} が起動していないまま通した: {path}")
        write_state(key, state)
        return with_messages({}, messages)


def main(argv: List[str]) -> int:
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            raise ValueError("入力がJSONオブジェクトではない")
    except ValueError as error:
        emit(with_messages({}, [f"原則レビューを検査できなかった（入力を読めない: {error}）。止めずに通した"]))
        return 0
    try:
        emit(handle(payload))
    except Exception as error:  # 検査できなかったことを黙って通さず、フックのエラーとして画面に出す
        print(f"principle-review: {type(error).__name__}: {error}", file=sys.stderr)
        emit(with_messages({}, [f"原則レビューを検査できなかった（{type(error).__name__}: {error}）。止めずに通した"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
