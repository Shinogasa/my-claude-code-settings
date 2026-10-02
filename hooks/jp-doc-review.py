#!/usr/bin/env python3
"""日本語文書のレビューをjp-doc-reviewerへ依頼するClaude Codeフック。

使い方: jp-doc-review.py <post-tool-use|pre-tool-use-bash|pre-tool-use-confluence|pre-tool-use-reviewer-bash|pre-tool-use-reviewer-edit>（入力はstdinのJSON）
設計: docs/superpowers/specs/2026-10-01-jp-doc-review-design.md
判断の経緯: docs/adr/0024-jp-doc-review-hook.md
"""
import fcntl
import hashlib
import json
import os
import re
import shlex
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_support import TranscriptError, emit, read_entries, tool_uses, with_messages  # noqa: E402

MIN_JP_CHARS = 100
DRAFT_SUFFIXES = {"markdown": ".md", "adf": ".json"}  # それ以外（html、指定なし）は .html
TARGET_SUFFIXES = {".md", ".toml", ".yaml", ".yml", ".json"}
STATE_RETENTION_DAYS = 7
CLEANUP_INTERVAL_SECONDS = 3600  # 掃除の走査は、この間隔に1回に抑える
CLEANUP_STAMP_NAME = ".last-cleanup"
REVIEWER_AGENT = "jp-doc-reviewer"
AGENT_TOOL_NAMES = {"Agent", "Task"}  # 古い版ではサブエージェントの起動ツールがTaskという名前だった
EXCLUDED_DIR_NAMES = {"node_modules", "vendor", "dist", "build", ".git"}
LOCKFILE_NAMES = {
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock",
    "composer.lock", "Pipfile.lock", "poetry.lock", "uv.lock", "Cargo.lock",
}
KANA = re.compile(r"[ぁ-ゖァ-ヺー]")
JP_CHAR = re.compile(r"[ぁ-ゖァ-ヺー々一-鿿]")
SUBMODULE_GITDIR = re.compile(r"\.git/modules/")
UNSAFE_ID_CHARS = re.compile(r"[^A-Za-z0-9_-]")
# git commit の判定に使う。区切りの文字だけでできた語を、コマンドの区切りとみなす
SEPARATOR_CHARS = ";&|()<>\n"
ENV_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
GIT_OPTIONS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env", "--attr-source"}


def state_dir() -> Path:
    override = os.environ.get("JP_DOC_REVIEW_STATE_DIR")
    return Path(override) if override else Path.home() / ".claude" / "state" / "jp-doc-review"


def drafts_dir() -> Path:
    return state_dir() / "drafts"


def yomiyasu_skill() -> Path:
    override = os.environ.get("JP_DOC_REVIEW_YOMIYASU_SKILL")
    return Path(override) if override else Path.home() / ".claude" / "skills" / "yomiyasu" / "SKILL.md"


def claude_home() -> Path:
    override = os.environ.get("JP_DOC_REVIEW_CLAUDE_HOME")
    return Path(override) if override else Path.home() / ".claude"


def temporary_roots() -> List[Path]:
    """一時ディレクトリの置き場。JP_DOC_REVIEW_TEMP_DIRS（os.pathsep区切り）で差し替えられる。"""
    override = os.environ.get("JP_DOC_REVIEW_TEMP_DIRS")
    if override is not None:
        return [Path(item) for item in override.split(os.pathsep) if item]
    return [Path(tempfile.gettempdir()), Path("/tmp"), Path("/private/tmp")]


def _is_disposable(path: Path) -> bool:
    """使い捨ての作業ファイルか。pathはsymlinkを解決した絶対パスで渡す。

    ~/.claude/ の下は、このリポジトリが管理する設定ならsymlinkを解決するとリポジトリ側になるので、ここには当たらない。
    """
    if path.name == "todo.md" and path.parent.name == "tasks":
        return True
    if ".superpowers" in path.parts[:-1]:
        return True
    roots = [claude_home(), drafts_dir(), *temporary_roots()]
    return any(Path(os.path.realpath(root)) in path.parents for root in roots)


def reviewer_definition() -> Path:
    override = os.environ.get("JP_DOC_REVIEW_AGENT_DEF")
    return Path(override) if override else Path.home() / ".claude" / "agents" / f"{REVIEWER_AGENT}.md"


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


def _find_git_root(start: Path) -> Tuple[Optional[Path], str]:
    """ディレクトリ start から親へたどり、最初に見つかった .git の場所と種類を返す。"""
    for candidate in (start, *start.parents):
        kind = _git_marker_kind(candidate / ".git")
        if kind != "none":
            return candidate, kind
    return None, "none"


def is_target(path: Path) -> bool:
    """レビューの記録対象か。pathはsymlinkを解決した絶対パスで渡す。"""
    if path.suffix not in TARGET_SUFFIXES or path.name in LOCKFILE_NAMES:
        return False
    if _is_disposable(path):
        return False
    root, kind = _find_git_root(path.parent)
    if kind == "submodule":
        return False
    inner = path.relative_to(root).parts if root else path.parts
    return not any(part in EXCLUDED_DIR_NAMES for part in inner[:-1])


WRITTEN_TEXT_KEYS = {"Write": "content", "Edit": "new_string"}


def _written_text(tool_name: str, tool_input: object) -> Tuple[str, str]:
    """書き込み先のパスと、書き込んだ文字列を返す。入力の形が想定と違えば ValueError を投げる。

    何も知らせずに終えると、全リポジトリで記録が止まっても気づけない。そのため、形の違いはエラーにする。
    Editのnew_stringが空文字列なのは削除として正当なので、キーの有無と型で判定する。
    """
    text_key = WRITTEN_TEXT_KEYS[tool_name]
    if not isinstance(tool_input, dict):
        raise ValueError(f"{tool_name}の入力の形が想定と違う（tool_inputがオブジェクトではない）")
    file_path, text = tool_input.get("file_path"), tool_input.get(text_key)
    if not isinstance(file_path, str) or not file_path:
        raise ValueError(f"{tool_name}の入力の形が想定と違う（file_pathが文字列ではない）")
    if not isinstance(text, str):
        raise ValueError(f"{tool_name}の入力の形が想定と違う（{text_key}が文字列ではない）")
    return file_path, text


def _ensure_private_dir(path: Path) -> None:
    """状態ファイルと下書きは社内文書の写しを含みうるので、ディレクトリを0700にする。"""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)


@contextmanager
def session_lock(key: str) -> Iterator[None]:
    """セッションごとのロック。状態ファイルを読んで書き戻す処理を囲む。

    同じセッションのメインとサブエージェントのフックは並行して動く。囲まないと、書き戻すときに
    別のプロセスの追記が消えたり、2つのプロセスが同じ投稿を1回目とみなしたりする。
    """
    _ensure_private_dir(state_dir())
    lock_path = state_dir() / f"{key}.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.utime(lock_path)  # 使っているロックを、古い状態の掃除で消さないようにする
        yield
    finally:
        os.close(fd)


def _write_private(path: Path, text: str) -> None:
    """一意な名前の一時ファイル（0600）に書いてから置き換える。"""
    _ensure_private_dir(path.parent)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _log_path(key: str) -> Path:
    return state_dir() / f"{key}.jsonl"


def _append_record(key: str, record: dict) -> None:
    """記録を1行追記する。呼び出し側でsession_lockを取る。"""
    _ensure_private_dir(state_dir())
    line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(_log_path(key), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def _read_log_lines(key: str) -> List[str]:
    """記録の行を返す。行の数は、依頼した時点までの行を数えるのに使う。"""
    path = _log_path(key)
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def _parse_record(line: str) -> Optional[dict]:
    """記録の1行を読む。形式が合わない行は None を返す。"""
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    if isinstance(value, dict) and isinstance(value.get("path"), str) and isinstance(value.get("jp_chars"), int):
        return value
    return None


def read_records(key: str) -> Tuple[List[dict], int]:
    """記録と、形式が合わずに飛ばした行の数を返す。"""
    parsed = [_parse_record(line) for line in _read_log_lines(key)]
    records = [record for record in parsed if record is not None]
    return records, len(parsed) - len(records)


def _write_log_lines(key: str, lines: List[str]) -> None:
    path = _log_path(key)
    if not lines:
        path.unlink(missing_ok=True)
        return
    _write_private(path, "".join(line + "\n" for line in lines))


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def write_json(path: Path, value: dict) -> None:
    _write_private(path, json.dumps(value, ensure_ascii=False))


def handle_post_tool_use(payload: dict) -> None:
    tool_name = payload.get("tool_name")
    if tool_name not in WRITTEN_TEXT_KEYS or payload.get("agent_type") == REVIEWER_AGENT:
        return
    key = session_key(payload)
    cleanup_old_state()
    raw_path, text = _written_text(tool_name, payload.get("tool_input"))
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(str(payload.get("cwd") or ".")) / path
    path = Path(os.path.realpath(path))
    if not is_target(path):
        return
    jp_chars = count_jp_chars(text)
    if jp_chars == 0:
        return
    with session_lock(key):
        _append_record(key, {"path": str(path), "jp_chars": jp_chars})


def _dispatched_path(key: str) -> Path:
    return state_dir() / f"{key}.dispatched.json"


def _flags_path(key: str) -> Path:
    return state_dir() / f"{key}.flags.json"


def _mark_once(key: str, flag: str) -> bool:
    """初めて立てるフラグなら記録してTrueを返す。2回目以降はFalse。"""
    flags = read_json(_flags_path(key))
    if flags.get(flag):
        return False
    write_json(_flags_path(key), {**flags, flag: True})
    return True


def cleanup_old_state() -> None:
    """保存日数を過ぎた状態ファイルと下書きを消す。走査は1時間に1回に抑える（印のファイルのmtimeで判定）。"""
    if not state_dir().is_dir():
        return
    stamp = state_dir() / CLEANUP_STAMP_NAME
    now = time.time()
    try:
        if now - stamp.stat().st_mtime < CLEANUP_INTERVAL_SECONDS:
            return
    except FileNotFoundError:
        pass
    limit = now - STATE_RETENTION_DAYS * 86400
    for directory in (state_dir(), drafts_dir()):
        if not directory.is_dir():
            continue
        for entry in directory.iterdir():
            try:
                if entry.is_file() and entry.stat().st_mtime < limit:
                    entry.unlink()
            except FileNotFoundError:
                continue  # 並行して動いた別のフックが先に消した
    _write_private(stamp, "")


def _shell_tokens(command: str) -> List[str]:
    """コマンドを語と区切りに分ける。shlexで最後まで分けられないときは、分けられたところまでを返す。"""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=SEPARATOR_CHARS)
    lexer.whitespace = " \t\r"  # 改行は区切りとして返させる
    tokens: List[str] = []
    try:
        for token in lexer:
            tokens.append(token)
    except ValueError:
        pass  # 閉じていない引用符など。コミットのメッセージの中で起きやすいので、それより前の語で判定する
    return tokens


def _segments(tokens: List[str]) -> List[List[str]]:
    segments: List[List[str]] = [[]]
    for token in tokens:
        if token and all(char in SEPARATOR_CHARS for char in token):
            segments.append([])
        else:
            segments[-1].append(token)
    return segments


def _commit_dash_c(words: List[str]) -> Optional[List[str]]:
    """1つの部分が git commit なら、-C の値の一覧を返す。そうでなければ None。"""
    index = 0
    while index < len(words) and ENV_ASSIGNMENT.match(words[index]):
        index += 1
    if index >= len(words) or os.path.basename(words[index]) != "git":
        return None
    dash_c: List[str] = []
    index += 1
    while index < len(words):
        word = words[index]
        if word in GIT_OPTIONS_WITH_VALUE:
            if word == "-C" and index + 1 < len(words):
                dash_c.append(words[index + 1])
            index += 2
        elif word.startswith("-"):
            index += 1
        else:
            return dash_c if word == "commit" else None
    return None


def find_commit(command: str) -> Optional[List[str]]:
    """コマンドに git commit があれば、最初のものの -C の値の一覧を返す。無ければ None。"""
    for words in _segments(_shell_tokens(command)):
        dash_c = _commit_dash_c(words)
        if dash_c is not None:
            return dash_c
    return None


def _commit_directory(payload: dict, dash_c: List[str]) -> Path:
    """コミット先のディレクトリ。-C があればそのパス（相対なら cwd 基準）、無ければ cwd。"""
    cwd = payload.get("cwd")
    directory = Path(cwd) if isinstance(cwd, str) and cwd else None
    for value in dash_c:
        candidate = Path(os.path.expanduser(value))
        if candidate.is_absolute():
            directory = candidate
        elif directory is not None:
            directory = directory / candidate
    if directory is None:
        raise ValueError("入力にcwdが無く、コミット先のリポジトリを決められない")
    return Path(os.path.realpath(directory))


def _review_candidates(records: List[dict], root: Optional[Path]) -> List[str]:
    """コミット先のリポジトリの中で、レビューを依頼するファイルを返す。"""
    if root is None:
        return []
    totals: Dict[str, int] = {}
    for record in records:
        totals[record["path"]] = totals.get(record["path"], 0) + record["jp_chars"]
    candidates = []
    for path, total in sorted(totals.items()):
        file = Path(path)
        if total < MIN_JP_CHARS or not file.is_file() or _find_git_root(file.parent)[0] != root:
            continue
        if KANA.search(file.read_text(encoding="utf-8", errors="replace")):
            candidates.append(path)
    return candidates


def _transcript_size(payload: dict) -> Optional[int]:
    """会話記録の今の大きさ。分からないときは None。"""
    path = payload.get("transcript_path")
    if not isinstance(path, str) or not path:
        return None
    try:
        return os.path.getsize(path)
    except OSError:
        return None


def reviewer_invoked_after(transcript_path: object, offset: object) -> bool:
    """会話記録の offset より後に、jp-doc-reviewerを起動したか。確かめられないときは TranscriptError。"""
    if not isinstance(offset, int):
        raise TranscriptError("依頼した時点の会話記録の大きさが分からない")
    entries = read_entries(transcript_path if isinstance(transcript_path, str) else None, offset)
    return any(
        name in AGENT_TOOL_NAMES and tool_input.get("subagent_type") == REVIEWER_AGENT
        for name, tool_input in tool_uses(entries)
    )


def _commit_reason(paths: List[str]) -> str:
    listed = "\n".join(f"- {path}" for path in paths)
    return (
        "日本語の文書をコミットする前に、レビューが要る。このコミットはまだ実行していない。\n"
        f"Agentツールで、subagent_typeを{REVIEWER_AGENT}にしたサブエージェントを1回起動し、次のファイルを渡して。\n"
        f"{listed}\n"
        "レビュワーには、このセッションで書いた箇所をファイルごとに伝え、その範囲だけを直させること。\n"
        "直したファイルをgit addし直してから、もう一度コミットして。2回目のコミットは止めない。\n"
        "レビュワーの報告を受けたら、変えた点と書き手に確かめたい点をユーザーに伝えて。"
    )


def _finish_dispatch(key: str, payload: dict) -> None:
    """依頼した後のコミット。通したうえで、依頼した記録を消し、レビュワーが起動したかを確かめる。"""
    dispatched = read_json(_dispatched_path(key))
    paths = {path for path in dispatched.get("paths", []) if isinstance(path, str)}
    limit = int(dispatched.get("record_lines", 0))
    lines = _read_log_lines(key)
    # 依頼した時点までの行から、依頼したパスの行を消す。依頼の後に書き足した行は、次のコミットのために残す
    kept = [line for line in lines[:limit] if (record := _parse_record(line)) and record["path"] not in paths]
    _write_log_lines(key, kept + lines[limit:])
    _dispatched_path(key).unlink(missing_ok=True)
    try:
        invoked = reviewer_invoked_after(payload.get("transcript_path"), dispatched.get("transcript_offset"))
    except TranscriptError as error:
        emit({"systemMessage": f"{REVIEWER_AGENT}が起動したかを確認できなかった（{error}）"})
        return
    if not invoked:
        names = "、".join(sorted(Path(path).name for path in paths))
        emit({"systemMessage": f"{REVIEWER_AGENT}が起動されないまま、2回目のコミットを通した。レビューされていない文書: {names}"})


def handle_pre_tool_use_bash(payload: dict) -> None:
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        raise ValueError("Bashの入力にcommand（文字列）が無い")
    dash_c = find_commit(command)
    if dash_c is None:
        return
    key = session_key(payload)
    root, _ = _find_git_root(_commit_directory(payload, dash_c))
    cleanup_old_state()
    with session_lock(key):
        _handle_commit(key, payload, root)


def _handle_commit(key: str, payload: dict, root: Optional[Path]) -> None:
    is_subagent = bool(payload.get("agent_type"))
    if not is_subagent and _dispatched_path(key).exists():
        _finish_dispatch(key, payload)
        return
    lines = _read_log_lines(key)
    records, skipped = read_records(key)
    messages = [f"日本語文書レビューの記録で、読めない行を{skipped}件飛ばした"] if skipped else []
    candidates = _review_candidates(records, root)
    if not candidates:
        emit(with_messages({}, messages))
        return
    if not yomiyasu_skill().is_file() or not reviewer_definition().is_file():
        if _mark_once(key, "missing-reviewer"):
            messages.append(
                f"yomiyasuのSKILL.mdか、{REVIEWER_AGENT}の定義が見つからないので、日本語の文書のレビューを省略した。"
                "skills/yomiyasuのsubmoduleと、setup.shを実行したかを確かめてほしい。"
            )
        emit(with_messages({}, messages))
        return
    if is_subagent:
        names = "、".join(Path(path).name for path in candidates)
        messages.append(
            f"サブエージェントは{REVIEWER_AGENT}を起動できないので、このコミットは止めない。"
            f"次の日本語の文書は、レビューしないままコミットされる: {names}"
        )
        emit(with_messages({}, messages))
        return
    write_json(_dispatched_path(key), {
        "paths": candidates, "record_lines": len(lines), "transcript_offset": _transcript_size(payload),
    })
    emit(with_messages({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": _commit_reason(candidates),
    }}, messages))


def _confluence_path(key: str) -> Path:
    return state_dir() / f"{key}.confluence.json"


def _confluence_target(tool_name: str, tool_input: dict) -> str:
    for field in ("pageId", "parentCommentId", "title"):
        value = tool_input.get(field)
        if value:
            return f"{tool_name}:{field}:{value}"
    return f"{tool_name}:none"


def _write_draft(key: str, digest: str, body: str, content_format: object) -> Path:
    suffix = DRAFT_SUFFIXES.get(str(content_format or ""), ".html")
    path = drafts_dir() / f"{key}-{digest[:12]}{suffix}"
    _write_private(path, body)
    return path


def _remove_draft(value: object) -> None:
    """1回目で作った下書きを消す。下書きの置き場の外は、状態ファイルが書き換えられていても消さない。"""
    if isinstance(value, str) and Path(value).parent == drafts_dir():
        Path(value).unlink(missing_ok=True)


def _confluence_reason(draft: Path) -> str:
    return (
        "Confluenceへ送る前に、日本語のレビューが要る。この投稿はまだ送っていない。\n"
        f"本文を下書き {draft} に書き出した。\n"
        f"Agentツールで、subagent_typeを{REVIEWER_AGENT}にしたサブエージェントを起動し、この下書きを渡して。\n"
        "レビュワーには、このセッションで書いた箇所だけを直させること。"
        "HTMLのタグ、data-*属性、ADFの構造は変えさせない。\n"
        "直した下書きの内容で、同じツールを同じ投稿先へもう一度呼んで投稿して。"
    )


def handle_pre_tool_use_confluence(payload: dict) -> None:
    tool_name = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    body = str(tool_input.get("body") or "")
    title = str(tool_input.get("title") or "")
    cleanup_old_state()
    if count_jp_chars(f"{title}\n{body}") < MIN_JP_CHARS:
        return
    key = session_key(payload)
    with session_lock(key):
        _handle_confluence(key, payload, tool_name, tool_input, body)


def _handle_confluence(key: str, payload: dict, tool_name: str, tool_input: dict, body: str) -> None:
    target = _confluence_target(tool_name, tool_input)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    state = read_json(_confluence_path(key))
    first = state.pop(target, None)
    if first is not None:
        _remove_draft(first.get("draft"))
    if first is None:
        draft = _write_draft(key, digest, body, tool_input.get("contentFormat"))
        write_json(_confluence_path(key), {
            **state, target: {"digest": digest, "transcript_offset": _transcript_size(payload), "draft": str(draft)},
        })
        emit({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": _confluence_reason(draft),
        }})
        return
    write_json(_confluence_path(key), state)
    if first.get("digest") == digest:
        emit({"systemMessage": f"本文が1回目と同じなので、Confluenceへの投稿は日本語のレビューを通らないまま送られる（{tool_name}）"})
        return
    try:
        invoked = reviewer_invoked_after(payload.get("transcript_path"), first.get("transcript_offset"))
    except TranscriptError as error:
        emit({"systemMessage": f"Confluenceへの投稿の前に{REVIEWER_AGENT}が起動したかを確認できなかった（{error}）"})
        return
    if not invoked:
        emit({"systemMessage": f"{REVIEWER_AGENT}が起動されないまま、Confluenceへの投稿を通した（{tool_name}）"})


LINTER_RELATIVE_PATHS = ("scripts/yomiyasu_lint.py", "skills/yomiyasu/scripts/yomiyasu_lint.py")
COMMAND_SEPARATORS = ("&&", "||", ";", "|", "&", "\n", "\r", "$(", "`", ">", "<")


def _allowed_linters() -> List[str]:
    skill_root = yomiyasu_skill().parent
    return [str(skill_root / relative) for relative in LINTER_RELATIVE_PATHS]


def _is_linter_command(command: str) -> bool:
    """python3 <リンター> <ファイル1つ> の形か。区切りを含むもの、shlexで分けられないものは偽。

    1語目と2語目は、引用符やバックスラッシュを含まない生の語でなければならない。シェルは引用符の中の ~ を
    展開しないので、shlexの後に展開すると、シェルが実行するものと食い違う。
    """
    if any(separator in command for separator in COMMAND_SEPARATORS):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    raw_words = command.split(None, 2)  # 3語目は空白を含む引用符付きのことがあるので、分けない
    if len(words) != 3 or len(raw_words) != 3 or words[:2] != raw_words[:2]:
        return False
    program, linter, target = words
    if any(char in word for word in raw_words[:2] for char in "'\"\\") or target.startswith("-"):
        return False
    if linter.startswith("~/"):
        linter = os.path.expanduser(linter)
    return program == "python3" and linter in _allowed_linters()


def handle_pre_tool_use_reviewer_bash(payload: dict) -> None:
    """jp-doc-reviewerのBashをリンターだけに絞る。想定外の入力は、フックのエラーでなく拒否にする。"""
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, str) and _is_linter_command(command):
        return
    emit({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"{REVIEWER_AGENT} が使える Bash はリンターだけ。"
            "python3 <yomiyasuの置き場>/scripts/yomiyasu_lint.py '<ファイル>' の形で、区切りや別のコマンドを付けずに呼んで。"
        ),
    }})


PROTECTED_CLAUDE_HOME_FILES = ("settings.json", "settings.local.json", "settings.personal.json")


def _protected_paths() -> List[str]:
    """レビュワーのEditで書き換えさせないものの実体。制限の仕組みそのもの。"""
    paths = [yomiyasu_skill().parent, Path(__file__).resolve().parent, reviewer_definition(),
             *(claude_home() / name for name in PROTECTED_CLAUDE_HOME_FILES)]
    return [os.path.realpath(path) for path in paths]


def _is_protected(file_path: str, cwd: object) -> bool:
    path = Path(file_path)
    if not path.is_absolute() and isinstance(cwd, str) and cwd:
        path = Path(cwd) / path
    real = os.path.realpath(path)
    return any(real == protected or real.startswith(protected + os.sep) for protected in _protected_paths())


def handle_pre_tool_use_reviewer_edit(payload: dict) -> None:
    """jp-doc-reviewerのEditが、リンター・フック・自身の定義・設定を書き換えるのを止める。"""
    tool_input = payload.get("tool_input")
    file_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if isinstance(file_path, str) and file_path and not _is_protected(file_path, payload.get("cwd")):
        return
    emit({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"{REVIEWER_AGENT} は、yomiyasuの置き場、フック、自身の定義、設定ファイルを書き換えられない。"
            "直してよいのは、依頼されたファイルだけ。"
        ),
    }})


HANDLERS = {
    "post-tool-use": handle_post_tool_use,
    "pre-tool-use-bash": handle_pre_tool_use_bash,
    "pre-tool-use-confluence": handle_pre_tool_use_confluence,
    "pre-tool-use-reviewer-bash": handle_pre_tool_use_reviewer_bash,
    "pre-tool-use-reviewer-edit": handle_pre_tool_use_reviewer_edit,
}


def main(argv: List[str]) -> int:
    if len(argv) != 2 or argv[1] not in HANDLERS:
        print(f"使い方: {Path(argv[0]).name} <{'|'.join(HANDLERS)}>", file=sys.stderr)
        return 1
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            raise ValueError("入力が空")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("入力がJSONオブジェクトではない")
        HANDLERS[argv[1]](payload)
    except Exception as error:  # 検査できなかったことを黙って通さず、フックのエラーとして画面に出す
        print(f"jp-doc-review {argv[1]}: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
