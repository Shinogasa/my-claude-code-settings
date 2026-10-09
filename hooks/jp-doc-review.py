#!/usr/bin/env python3
"""日本語文書のレビューをjp-doc-reviewerへ依頼するClaude Codeフック。

使い方: jp-doc-review.py <pre-tool-use-bash|pre-tool-use-confluence|pre-tool-use-agent|pre-tool-use-reviewer-bash|pre-tool-use-reviewer-edit>（入力はstdinのJSON）
設計: docs/superpowers/specs/2026-10-01-jp-doc-review-design.md
判断の経緯: docs/adr/0024-jp-doc-review-hook.md
"""
import fcntl
import functools
import hashlib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set, Tuple

HOOK_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HOOK_DIR))
from hook_support import TranscriptError, emit, read_entries, tool_uses, with_messages  # noqa: E402


@functools.lru_cache(maxsize=None)
def guard():
    """guard-dangerous-bash.py を読み込む。cd の移動先の解決を、コミットの判定とそろえるために使う。"""
    spec = importlib.util.spec_from_file_location("guard_dangerous_bash", HOOK_DIR / "guard-dangerous-bash.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

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
PATH_LIKE = re.compile(r"[A-Za-z0-9_~./\-]+")
UNSAFE_ID_CHARS = re.compile(r"[^A-Za-z0-9_-]")
# PR作成の判定に使う。区切りの文字だけでできた語を、コマンドの区切りとみなす
SEPARATOR_CHARS = ";&|()<>\n"
ENV_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
COMMAND_PREFIXES = {"command", "builtin", "exec", "env", "time", "nohup", "noglob"}
PR_CREATE_WORDS = ["gh", "pr", "create"]
SHELLS = {"bash", "sh", "zsh"}
CLAUDE_TRAILER = re.compile(r"^Co-Authored-By:\s*Claude\b", re.IGNORECASE | re.MULTILINE)
GIT_TIMEOUT_SECONDS = 10
CONTROL_CHAR = re.compile(r"[\x00-\x1f\x7f]")


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


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def write_json(path: Path, value: dict) -> None:
    _write_private(path, json.dumps(value, ensure_ascii=False))


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


class GitError(Exception):
    """レビューの候補を決めるためのgitの操作に失敗した。"""


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                                timeout=GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as error:
        raise GitError(f"git {' '.join(args)}: {type(error).__name__}") from error
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {result.stderr.strip() or result.returncode}")
    return result.stdout


def _shell_words(command: str) -> List[str]:
    """コマンドを語と区切りに分ける。最後まで分けられないときは、分けられたところまでを返す。"""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=SEPARATOR_CHARS)
    lexer.whitespace = " \t\r"  # 改行は区切りとして返させる
    words: List[str] = []
    try:
        for word in lexer:
            words.append(word)
    except ValueError:
        pass
    return words


def is_pr_create(command: str, depth: int = 0) -> bool:
    """コマンドの位置に PR_CREATE_WORDS があるか。bash -c などの文字列の中も1段だけ調べる。

    引用符の中（コミットメッセージや echo の文字列）は1語として扱うので、PRの作成とみなさない。
    """
    segment: List[str] = []
    for word in [*_shell_words(command), ";"]:
        if word and all(char in SEPARATOR_CHARS for char in word):
            words = segment
            segment = []
            while words and (ENV_ASSIGNMENT.match(words[0]) or words[0] in COMMAND_PREFIXES):
                words = words[1:]
            if words[:3] == PR_CREATE_WORDS:
                return True
            if depth == 0 and words and Path(words[0]).name in SHELLS and "-c" in words[1:-1]:
                if is_pr_create(words[words.index("-c", 1) + 1], depth + 1):
                    return True
            continue
        segment.append(word)
    return False


def pr_create_dirs(command: str, cwd: str) -> Set[Optional[str]]:
    """gh pr create を実行するときに、シェルがいる可能性のあるディレクトリの集合を返す。

    同じコマンドの中の cd は、guard-dangerous-bash.py の main と同じ手順で追う。移動先を確定できなければ、
    集合に guard().UNRESOLVED（None）が入る。is_pr_create が見つけたのにここで見つからない形
    （ヒアドキュメントの本文の行頭など）は、従来どおり cwd で判定する。
    """
    dirs = _pr_create_dirs(command, {os.path.abspath(cwd)}, 0)
    return dirs or {os.path.abspath(cwd)}


def _pr_create_dirs(command: str, start: Set[Optional[str]], depth: int) -> Set[Optional[str]]:
    g = guard()
    tokens = g.tokenize_command(g.strip_heredocs(command))
    if tokens is None:
        return {g.UNRESOLVED}
    candidates, seen, dirs = set(start), set(start), set()
    cdpath_possible = "CDPATH" in command or bool(os.environ.get("CDPATH"))
    for previous_op, words, next_op, _raw in g.split_with_operators(tokens):
        if g.operator_kind(previous_op) in ("SEQ", "BREAK"):
            candidates = set(seen)
        candidates = g.apply_directory_change(previous_op, words, next_op, candidates, cdpath_possible)
        seen |= candidates
        if words[:3] == PR_CREATE_WORDS:
            dirs |= candidates
        elif depth == 0 and words and Path(words[0]).name in SHELLS and "-c" in words[1:-1]:
            dirs |= _pr_create_dirs(words[words.index("-c", 1) + 1], candidates, depth + 1)
    return dirs


def _target_reason(dirs: Set[Optional[str]], roots: List[Path]) -> str:
    """PRを作るリポジトリを1つに決められないときの、止める理由。"""
    if guard().UNRESOLVED in dirs:
        lines = ["PRを作るリポジトリを決められなかった。同じコマンドの中の cd の移動先を、文字列から確定できない"
                 "（変数、cd -、pushd / popd、まだ無いディレクトリなど）。"]
    else:
        lines = ["PRを作るリポジトリを1つに決められなかった。cd の後ろが && でないと、cd が失敗しても後ろが走る。"
                 "次のどれでもPRが作られうる。"]
        lines += [f"- {root}" for root in roots if not CONTROL_CHAR.search(str(root))]
    return "\n".join(lines)


def _pr_base(command: str) -> Optional[str]:
    """gh pr create の --base / -B の値。指定が無ければ None。"""
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    for index, word in enumerate(words):
        if word in ("--base", "-B") and index + 1 < len(words):
            return words[index + 1]
        if word.startswith("--base="):
            return word.split("=", 1)[1]
    return None


def _resolve_base(root: Path, base: Optional[str]) -> str:
    """比べる相手のref。指定があれば origin/<base> か <base>、無ければ既定のブランチ。"""
    if base:
        candidates = [f"origin/{base}", base]
    else:
        try:
            candidates = [_git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()]
        except GitError:
            candidates = []
        candidates += ["origin/main", "origin/master", "main", "master"]
    for ref in candidates:
        try:
            _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
            return ref
        except GitError:
            continue
    raise GitError(f"比べる相手のブランチを決められない（候補: {', '.join(candidates)}）")


def _claude_authored(root: Path, merge_base: str) -> set:
    """merge_base より後で、Co-Authored-By: Claude の行が付いたコミットが触ったファイル（リポジトリからの相対パス）。"""
    files: set = set()
    for sha in _git(root, "rev-list", f"{merge_base}..HEAD").split():
        if CLAUDE_TRAILER.search(_git(root, "log", "-1", "--format=%B", sha)):
            files.update(name for name in _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", sha).split("\0") if name)
    return files


def _added_text(root: Path, merge_base: str, relative: str) -> str:
    diff = _git(root, "diff", "--no-color", "--unified=0", merge_base, "HEAD", "--", relative)
    return "\n".join(line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))


def pr_candidates(root: Path, base_ref: str) -> Tuple[List[str], List[str], int]:
    """ブランチで変わった日本語の文書を、Claudeが書いたものとそれ以外に分けて返す（絶対パス）。

    3つ目は、制御文字を含むために外したパスの数。パスは止める理由の文面にそのまま並ぶので、
    ファイル名の改行で偽の指示を書き込めないよう、候補にしない。
    """
    merge_base = _git(root, "merge-base", base_ref, "HEAD").strip()
    changed = [name for name in _git(root, "diff", "--name-only", "--diff-filter=AMR", "-z", merge_base, "HEAD").split("\0") if name]
    claude = _claude_authored(root, merge_base)
    authored, others, unsafe = [], [], 0
    for relative in sorted(changed):
        if CONTROL_CHAR.search(relative):
            unsafe += 1
            continue
        path = Path(os.path.realpath(root / relative))
        if not path.is_file() or not is_target(path):
            continue
        if count_jp_chars(_added_text(root, merge_base, relative)) < MIN_JP_CHARS:
            continue
        if not KANA.search(path.read_text(encoding="utf-8", errors="replace")):
            continue
        (authored if relative in claude else others).append(str(path))
    return authored, others, unsafe


def _pr_reason(base_ref: str, authored: List[str], others: List[str]) -> str:
    lines = ["日本語の文書を含むPRを作る前に、レビューが要る。このPRはまだ作っていない。"]
    if authored:
        lines += [f"Agentツールで、subagent_typeを{REVIEWER_AGENT}にしたサブエージェントを1回起動し、次のファイルを渡して。",
                  *(f"- {path}" for path in authored)]
    if others:
        lines += ["次のファイルは、Claudeのコミット（Co-Authored-By: Claude）では変わっていない。"
                  "レビューに含めてよいかを、AskUserQuestionでユーザーに確かめて。",
                  *(f"- {path}" for path in others)]
    lines += [
        "依頼文には、対象のパスを絶対パスでそのまま書く。書かれていないファイルは、レビュワーが直せない。",
        f"レビュワーには、ブランチで変わった行（git diff {base_ref}...HEAD -- <ファイル>）だけを直させること。",
        "直したらコミットしてpushし、もう一度 gh pr create を実行して。2回目は止めない。",
        "レビュワーの報告を受けたら、変えた点と書き手に確かめたい点をユーザーに伝えて。",
    ]
    return "\n".join(lines)


def _pr_state_path(key: str) -> Path:
    return state_dir() / f"{key}.pr-dispatched.json"


def _finish_pr_dispatch(key: str, payload: dict, entry: dict) -> None:
    """止めた後の2回目。通したうえで、レビュワーが起動したかを確かめる。"""
    try:
        invoked = reviewer_invoked_after(payload.get("transcript_path"), entry.get("transcript_offset"))
    except TranscriptError as error:
        emit({"systemMessage": f"{REVIEWER_AGENT}が起動したかを確認できなかった（{error}）"})
        return
    if not invoked:
        names = "、".join(sorted(Path(path).name for path in entry.get("paths", [])))
        emit({"systemMessage": f"{REVIEWER_AGENT}が起動されないまま、2回目のPR作成を通した。レビューされていない文書: {names}"})


def handle_pre_tool_use_bash(payload: dict) -> None:
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        raise ValueError("Bashの入力にcommand（文字列）が無い")
    if not is_pr_create(command):
        return
    try:
        _check_pr_create(payload, command)
    except Exception as error:  # PR作成と分かった後の失敗は、終了コード1で通さず止める側に倒す
        print(f"jp-doc-review pre-tool-use-bash: {type(error).__name__}: {error}", file=sys.stderr)
        emit({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"日本語の文書のレビュー対象を確かめられなかったので、このPRはまだ作っていない"
                                        f"（{type(error).__name__}: {error}）。原因を直してから、もう一度 gh pr create を実行して。",
        }})


def _check_pr_create(payload: dict, command: str) -> None:
    key = session_key(payload)
    cleanup_old_state()
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        raise ValueError("入力にcwdが無く、PRを作るリポジトリを決められない")
    dirs = pr_create_dirs(command, cwd)
    unresolved = guard().UNRESOLVED
    found = (_find_git_root(Path(os.path.realpath(path))) for path in dirs if path is not unresolved)
    roots = {root: kind for root, kind in found if root is not None}
    if unresolved in dirs or len(roots) > 1:
        # 検査できなかったことを「問題なし」に畳まない。書き直せば判定できるので、毎回止める
        reason = _target_reason(dirs, sorted(roots))
        if payload.get("agent_type"):
            emit({"systemMessage": f"{reason}\n日本語の文書をレビューしないまま、サブエージェントのPR作成を通した。"})
            return
        emit({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"{reason}\n日本語の文書のレビュー対象を決められないので、このPRはまだ作っていない。\n"
                                        "cd <リポジトリの絶対パス> && gh pr create ... の形で、もう一度実行して。",
        }})
        return
    if not roots:
        return
    [(root, kind)] = roots.items()
    if kind == "submodule":
        return
    with session_lock(key):
        _handle_pr_create(key, payload, root, command)


def _handle_pr_create(key: str, payload: dict, root: Path, command: str) -> None:
    state = read_json(_pr_state_path(key))
    try:
        branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    except GitError:
        branch = "HEAD"
    state_id = f"{root}\0{branch}"
    is_subagent = bool(payload.get("agent_type"))
    entry = state.get(state_id)
    if not is_subagent and isinstance(entry, dict):
        # 止めた記録は消さずに残し、以降は通す。1回のBashでフックが2回呼ばれる環境があり、
        # 記録を消すと止める・通すが交互になる。レビュワーが起動したかは、会話記録が伸びた後に1回だけ確かめる
        size, offset = _transcript_size(payload), entry.get("transcript_offset")
        grown = size is None or not isinstance(offset, int) or size > offset
        if grown and not entry.get("reported"):
            write_json(_pr_state_path(key), {**state, state_id: {**entry, "reported": True}})
            _finish_pr_dispatch(key, payload, entry)
        return
    base = _pr_base(command)
    try:
        base_ref = _resolve_base(root, base)
        authored, others, unsafe = pr_candidates(root, base_ref)
    except GitError as error:
        # 検査できなかったことを「問題なし」に畳まない。1回だけ止めて、理由を伝える
        if is_subagent:
            emit({"systemMessage": f"日本語の文書のレビュー対象を決められなかった（{error}）"})
            return
        write_json(_pr_state_path(key), {**state, state_id: {"paths": [], "transcript_offset": _transcript_size(payload)}})
        emit({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"日本語の文書のレビュー対象を決められなかった（{error}）。"
                                        "--base の指定を確かめて、もう一度 gh pr create を実行して。2回目は止めない。",
        }})
        return
    messages = [f"制御文字を含むパスの{unsafe}件は、日本語の文書のレビュー対象から外した。名前を確かめてほしい"] if unsafe else []
    candidates = authored + others
    if not candidates:
        emit(with_messages({}, messages))
        return
    if not yomiyasu_skill().is_file() or not reviewer_definition().is_file():
        if _mark_once(key, "missing-reviewer"):
            emit({"systemMessage":
                  f"yomiyasuのSKILL.mdか、{REVIEWER_AGENT}の定義が見つからないので、日本語の文書のレビューを省略した。"
                  "skills/yomiyasuのsubmoduleと、setup.shを実行したかを確かめてほしい。"})
        return
    if is_subagent:
        names = "、".join(Path(path).name for path in candidates)
        emit({"systemMessage": f"サブエージェントは{REVIEWER_AGENT}を起動できないので、このPR作成は止めない。"
                               f"次の日本語の文書は、レビューしないままPRになる: {names}"})
        return
    write_json(_pr_state_path(key), {**state, state_id: {"paths": candidates, "transcript_offset": _transcript_size(payload)}})
    emit(with_messages({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": _pr_reason(base or base_ref, authored, others),
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
        "依頼文には、対象のパスを絶対パスでそのまま書く。書かれていないファイルは、レビュワーが直せない。\n"
        "レビュワーには、このセッションで書いた箇所だけを直させること。"
        "HTMLのタグ、data-*属性、ADFの構造は変えさせない。\n"
        "レビューが終わったら、レビュワーが変えた点をユーザーに見せ、投稿してよいかを確かめてから送る。"
        "ユーザーの確認なしに2回目を送らない。\n"
        "確認が取れたら、直した下書きの内容で、同じツールを同じ投稿先へもう一度呼んで投稿して。"
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


def _allow_path(key: str) -> Path:
    return state_dir() / f"{key}.reviewer-allow.json"


def _requested_files(prompt: str, cwd: object) -> List[str]:
    """依頼文の中で、実在する通常ファイルのパス（実体）を返す。/ を含む語だけを候補にする。"""
    found: List[str] = []
    for word in PATH_LIKE.findall(prompt):
        word = word.rstrip(".,:")
        if "/" not in word:
            continue
        path = Path(os.path.expanduser(word) if word.startswith("~") else word)
        if not path.is_absolute():
            if not (isinstance(cwd, str) and cwd):
                continue
            path = Path(cwd) / path
        real = os.path.realpath(path)
        if os.path.isfile(real) and real not in found:
            found.append(real)
    return found


def handle_pre_tool_use_agent(payload: dict) -> None:
    """jp-doc-reviewerへの依頼文に書かれたファイルを、そのレビュワーがEditしてよいファイルとして記録する。"""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict) or tool_input.get("subagent_type") != REVIEWER_AGENT:
        return
    if payload.get("agent_type"):
        return  # サブエージェントがさらに呼んだ依頼では、許可を広げない
    key = session_key(payload)
    cleanup_old_state()
    prompt = tool_input.get("prompt")
    paths = _requested_files(prompt if isinstance(prompt, str) else "", payload.get("cwd"))
    if not paths:
        emit({"systemMessage": f"{REVIEWER_AGENT}への依頼文にパスが無いので、レビュワーはファイルを直せない"})
        return
    with session_lock(key):
        known = _read_allowed(key) or []
        write_json(_allow_path(key), {"paths": [*known, *(path for path in paths if path not in known)]})


def _read_allowed(key: str) -> Optional[List[str]]:
    """許可リストを読む。無い、読めない、形が違うときは None。"""
    try:
        value = json.loads(_allow_path(key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    paths = value.get("paths") if isinstance(value, dict) else None
    if isinstance(paths, list) and all(isinstance(path, str) for path in paths):
        return paths
    return None


def _protected_paths() -> List[str]:
    """レビュワーのEditで書き換えさせないものの実体。制限の仕組みそのもの。許可リストに入っていても守る。"""
    paths = [yomiyasu_skill().parent, Path(__file__).resolve().parent, reviewer_definition(),
             *(claude_home() / name for name in PROTECTED_CLAUDE_HOME_FILES)]
    return [os.path.realpath(path) for path in paths]


def _is_editable(key: str, file_path: str, cwd: object) -> bool:
    path = Path(file_path)
    if not path.is_absolute() and isinstance(cwd, str) and cwd:
        path = Path(cwd) / path
    real = os.path.realpath(path)
    if any(real == protected or real.startswith(protected + os.sep) for protected in _protected_paths()):
        return False
    return real in (_read_allowed(key) or [])


def handle_pre_tool_use_reviewer_edit(payload: dict) -> None:
    """jp-doc-reviewerのEditを、依頼文に書かれたファイルだけに絞る。想定外の入力と許可リストの不備は拒否にする。"""
    tool_input = payload.get("tool_input")
    file_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if isinstance(file_path, str) and file_path and _is_editable(session_key(payload), file_path, payload.get("cwd")):
        return
    emit({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"{REVIEWER_AGENT} は、依頼文に書かれたファイルだけを直せる。"
            "yomiyasuの置き場、フック、自身の定義、設定ファイルは、依頼文に書かれていても直せない。"
        ),
    }})


def handle_post_tool_use(payload: dict) -> None:
    """何もしない。書き込みの記録はやめた（ADR 0025）。setup.sh をやり直す前の古い settings.json が呼ぶので、入口だけ残す。"""


HANDLERS = {
    "post-tool-use": handle_post_tool_use,
    "pre-tool-use-bash": handle_pre_tool_use_bash,
    "pre-tool-use-confluence": handle_pre_tool_use_confluence,
    "pre-tool-use-agent": handle_pre_tool_use_agent,
    "pre-tool-use-reviewer-bash": handle_pre_tool_use_reviewer_bash,
    "pre-tool-use-reviewer-edit": handle_pre_tool_use_reviewer_edit,
}


FAIL_CLOSED_EVENTS = {"pre-tool-use-reviewer-bash", "pre-tool-use-reviewer-edit"}


def _deny_after_error(event: str, error: Exception) -> None:
    """制限のフックは、検査できなかったときに通さず、止める側に倒す。終了コード1は止めたことにならない。"""
    emit({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": f"{REVIEWER_AGENT}の操作を確かめられなかったので止めた（{type(error).__name__}: {error}）",
    }})


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
        if argv[1] in FAIL_CLOSED_EVENTS:
            _deny_after_error(argv[1], error)
            return 0
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
