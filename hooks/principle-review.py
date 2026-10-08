#!/usr/bin/env python3
"""仕様書・ADR・計画を含む git commit の直前に1回だけ止め、principle-reviewer の起動を促す。

設計: docs/superpowers/specs/2026-10-08-work-principles-design.md、ADR 0026
"""
import fcntl
import functools
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

HOOK_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HOOK_DIR))


@functools.lru_cache(maxsize=None)
def guard():
    """guard-dangerous-bash.py を読み込む。読み込めない失敗は main が「検査できなかった」として表示する。"""
    spec = importlib.util.spec_from_file_location("guard_dangerous_bash", HOOK_DIR / "guard-dangerous-bash.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TARGET_DIRS = {
    "spec": ("docs/superpowers/specs/", "docs/specs/", "docs/adr/"),
    "plan": ("docs/superpowers/plans/", "docs/plans/"),
}
EXCLUDED_NAMES = {"README.md"}
SHORT_FLAGS_WITH_VALUE = set("mFCct")  # この後ろの文字は値なので、-a の判定に使わない
SHORT_FLAGS_WITH_ATTACHED_VALUE = set("uS")  # -uno・-S<鍵ID> のように、値を同じトークンにだけ取る
# git commit の長いオプションのうち、値を次のトークンに取りうるもの。値を pathspec と取り違えない
LONG_OPTS_WITH_VALUE = {"--message", "--file", "--author", "--date", "--cleanup", "--reuse-message",
                        "--reedit-message", "--fixup", "--squash", "--template", "--trailer"}
# 未ステージの変更もコミットに入れる git commit のオプション
WORKTREE_LONG_OPTS = {"--all", "--only", "--include", "--pathspec-from-file"}
WORKTREE_SHORT_FLAGS = set("aoi")
# フックは利用者がコマンドを承認する前に動く。git add は実行せず、次のオプションだけを解釈して
# 足されるファイルを plumbing（diff-files・ls-files）で推定する。これ以外のオプションがあれば広めに取る
SAFE_ADD_OPTS = {"-A", "--all", "-u", "--update", "-f", "--force", "--no-ignore-removal", "--ignore-removal", "--no-all"}
WHOLE_TREE_ADD_OPTS = {"-A", "--all", "--no-ignore-removal", "-u", "--update"}  # pathspec が無ければ全体が対象
UPDATE_ONLY_ADD_OPTS = {"-u", "--update"}  # 追跡済みのファイルだけ
FORCE_ADD_OPTS = {"-f", "--force"}  # 無視されたファイルも足す
# フックの git 呼び出しすべてに付ける。fsmonitor とフックのコマンドを止め、利用者の attributes ファイルを読まない。
# リポジトリ内の .gitattributes は読まれるので、filter は _filter_overrides で別に打ち消す
SAFE_GIT_CONFIG = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "core.attributesFile=/dev/null")
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # まだコミットが無いリポジトリの比較元
# 対象外にするパスの文字。理由の文面へ改行などを持ち込ませない
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
MAX_SHOWN_LENGTH = 200


def commit_options(args: List[str]) -> Tuple[set, set, List[str]]:
    """git commit の引数を、短いフラグの文字、長いオプションの名前、位置引数（pathspec）に分ける。"""
    shorts, longs, positional = set(), set(), []
    index = 0
    while index < len(args):
        token = args[index]
        index += 1
        if token == "--":
            positional.extend(args[index:])
            break
        if token.startswith("--"):
            name = token.split("=", 1)[0]
            longs.add(name)
            if "=" not in token and name in LONG_OPTS_WITH_VALUE:
                index += 1  # 値が次のトークンにある
            continue
        if token.startswith("-") and len(token) > 1:
            for offset, char in enumerate(token[1:]):
                shorts.add(char)
                if char in SHORT_FLAGS_WITH_VALUE:
                    if offset == len(token) - 2:
                        index += 1  # 値が次のトークンにある
                    break
                if char in SHORT_FLAGS_WITH_ATTACHED_VALUE:
                    break
            continue
        positional.append(token)
    return shorts, longs, positional


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
    shorts, longs, _positional = commit_options(guard().extract_subcommand(tokens)[1])
    return "a" in shorts or "--all" in longs


def includes_worktree(tokens: List[str]) -> bool:
    """git commit が未ステージの変更もコミットに入れうるか。-a のほか、pathspec・-o・-i もそうなる。"""
    shorts, longs, positional = commit_options(guard().extract_subcommand(tokens)[1])
    return bool(shorts & WORKTREE_SHORT_FLAGS or longs & WORKTREE_LONG_OPTS or positional)


REVIEWER_AGENT = "principle-reviewer"
GIT_TIMEOUT_SECONDS = 10
TIME_BUDGET_SECONDS = 25  # settings.json の timeout（30秒）より先に、自分で打ち切る
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


Add = Tuple[Optional[str], Tuple[str, ...]]  # (git add を実行するディレクトリ, サブコマンドより後の引数)
Commit = Tuple[str, bool, Tuple[Add, ...]]  # (コミット先, 未ステージも入るか, 先に出た git add)


def is_git_add(tokens: List[str]) -> bool:
    return bool(tokens) and tokens[0] == "git" and guard().extract_subcommand(tokens)[0] in ("add", "stage")


def commit_targets(command: str, cwd: str) -> List[Commit]:
    """コマンド中の git commit ごとに、コミット先のディレクトリ、未ステージの扱い、先に出た git add を返す。

    ディレクトリの解決は guard-dangerous-bash.py の main と同じ手順で行う。
    コミット先を確定できない（UNRESOLVED）ときは、guard がコミットごと止めるので、ここでは数えない。
    git add は、PreToolUse の時点ではまだ実行されていない。コミットより前に出た add は、
    区切りの種類によらずそのコミットに結び付ける（実行されない add も含めて、広めに取る）。
    """
    g = guard()
    tokens = g.tokenize_command(g.strip_heredocs(command))
    if tokens is None:
        return []
    candidates = {os.path.abspath(cwd)}
    seen = set(candidates)
    cdpath_possible = "CDPATH" in command or bool(os.environ.get("CDPATH"))
    adds: List[Add] = []
    targets: List[Commit] = []
    for previous_op, simple_command, next_op, _raw in g.split_with_operators(tokens):
        if g.operator_kind(previous_op) in ("SEQ", "BREAK"):
            candidates = set(seen)
        candidates = g.apply_directory_change(previous_op, simple_command, next_op, candidates, cdpath_possible)
        seen |= candidates
        if is_git_add(simple_command):
            args = tuple(g.extract_subcommand(simple_command)[1])
            adds.extend((target, args) for target in g.git_target_dirs(simple_command, candidates))
        elif g.is_git_commit(simple_command):
            unstaged = includes_worktree(simple_command)
            for target in g.git_target_dirs(simple_command, candidates):
                if target is not g.UNRESOLVED:
                    targets.append((target, unstaged, tuple(adds)))
    return targets


def _git_env() -> dict:
    """利用者の GIT_* 環境変数（GIT_DIR・GIT_INDEX_FILE など）を引き継がない環境を返す。"""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    # メッセージで「リポジトリ外」を見分けるので、翻訳されないよう LC_ALL=C にする。
    # GIT_OPTIONAL_LOCKS=0 で、検査中にインデックスの stat 情報を書き戻さない
    return {**env, "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}


def _git(repo: str, deadline: float, *args: str) -> subprocess.CompletedProcess:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise GitError(f"フック全体の時間予算（{TIME_BUDGET_SECONDS}秒）を使い切った")
    try:
        return subprocess.run(["git", "-C", repo, *SAFE_GIT_CONFIG, *args], capture_output=True, text=True,
                              timeout=min(GIT_TIMEOUT_SECONDS, remaining), env=_git_env())
    except (OSError, subprocess.SubprocessError) as error:
        raise GitError(f"git を実行できない: {error}") from error


def _git_paths(directory: str, deadline: float, *args: str) -> List[str]:
    """-z で区切られたパスの一覧を返す。日本語やスペースを含むパスも引用されない。"""
    result = _git(directory, deadline, *args)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or f"git {args[0]} に失敗した")
    return list(filter(None, result.stdout.split("\0")))


def _filter_overrides(directory: str, deadline: float) -> Tuple[str, ...]:
    """設定された filter のコマンドを空で打ち消す -c 引数を返す。

    diff-files は、インデックスと同じ秒に書き換えられたファイル（racy）の中身を確かめるときに
    clean filter を走らせる。設定の読み取りはコマンドを走らせないので、先に名前を取って打ち消す。
    """
    result = _git(directory, deadline, "config", "-z", "--name-only", "--get-regexp",
                  r"^filter\..+\.(clean|smudge|process)$")
    if result.returncode not in (0, 1):  # 1 は該当なし
        raise GitError(result.stderr.strip() or "git config に失敗した")
    overrides: List[str] = []
    for driver in sorted({name.rsplit(".", 1)[0] for name in filter(None, result.stdout.split("\0"))}):
        if "=" in driver or CONTROL_CHARS.search(driver):
            raise GitError("filter の名前を -c で打ち消せない")
        for key in ("clean=", "smudge=", "process=", "required=false"):
            overrides += ["-c", f"{driver}.{key}"]
    return tuple(overrides)


def _modified(directory: str, deadline: float, pathspecs: List[str]) -> List[str]:
    """変更された追跡ファイル（削除を除く）の、ルートからの相対パス。"""
    return _git_paths(directory, deadline, *_filter_overrides(directory, deadline),
                      "diff-files", "--name-only", "-z", "--diff-filter=d", "--", *pathspecs)


def _untracked(directory: str, deadline: float, pathspecs: List[str], force: bool) -> List[str]:
    """未追跡のファイルの、ルートからの相対パス。force なら無視されたファイルも含める。"""
    exclude = [] if force else ["--exclude-standard"]
    return _git_paths(directory, deadline, "ls-files", "-z", "--others", "--full-name", *exclude, "--", *pathspecs)


def _staged(root: str, deadline: float) -> List[str]:
    head = _git(root, deadline, "rev-parse", "--verify", "-q", "HEAD^{commit}")
    base = "HEAD" if head.returncode == 0 else EMPTY_TREE
    return _git_paths(root, deadline, "diff-index", "--cached", "--name-only", "-z", "--diff-filter=d", base, "--")


def _broad_paths(root: str, deadline: float) -> List[str]:
    """git add が何を足すか推定できないとき、足されうるものを広めに取る。"""
    prefixes = [prefix for group in TARGET_DIRS.values() for prefix in group]
    return [*_modified(root, deadline, []), *_untracked(root, deadline, prefixes, force=False)]


def _split_add_args(args: Tuple[str, ...]) -> Optional[Tuple[set, List[str]]]:
    """git add の引数を、解釈できるオプションと pathspec に分ける。解釈できないオプションがあれば None。"""
    options: set = set()
    pathspecs: List[str] = []
    for index, token in enumerate(args):
        if token == "--":
            pathspecs.extend(args[index + 1:])
            break
        if token.startswith("-"):
            if token not in SAFE_ADD_OPTS:
                return None
            options.add(token)
        else:
            pathspecs.append(token)
    return options, pathspecs


def _simulated_add(directory: str, args: Tuple[str, ...], deadline: float) -> Optional[List[str]]:
    """git add が足すファイルの絶対パスを、実行せずに推定する。推定できなければ None。"""
    split = _split_add_args(args)
    if split is None:
        return None
    options, pathspecs = split
    if not pathspecs:
        if not options & WHOLE_TREE_ADD_OPTS:
            return []  # git add だけでは何も足さない
        pathspecs = [":(top)"]
    top = _git(directory, deadline, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return None
    relatives = _modified(directory, deadline, pathspecs)
    if not options & UPDATE_ONLY_ADD_OPTS:
        relatives += _untracked(directory, deadline, pathspecs, force=bool(options & FORCE_ADD_OPTS))
    return [str(Path(top.stdout.strip()) / relative) for relative in relatives]


def _added_paths(root: str, adds: Tuple[Add, ...], deadline: float) -> List[str]:
    """先に出た git add が、このコミットのリポジトリに足しうるファイルの、ルートからの相対パスを返す。"""
    relatives: List[str] = []
    for directory, args in adds:
        absolute = None if directory is None else _simulated_add(directory, args, deadline)
        if absolute is None:
            relatives.extend(_broad_paths(root, deadline))
            continue
        for path in absolute:
            relative = os.path.relpath(path, root)
            if not relative.startswith(".." + os.sep) and relative != "..":
                relatives.append(Path(relative).as_posix())
    return relatives


def exclusion_reason(root: str, relative: str) -> Optional[str]:
    """レビューに回さない対象なら、その理由を返す。"""
    if CONTROL_CHARS.search(relative):
        return "パスに制御文字を含む"
    absolute = Path(root) / relative
    if absolute.is_symlink():
        return "symlink である"
    real_root = os.path.realpath(root)
    if os.path.commonpath([real_root, os.path.realpath(absolute)]) != real_root:
        return "実体がリポジトリの外にある"
    return None


def changed_targets(repo: str, include_unstaged: bool, adds: Tuple[Add, ...],
                    deadline: float) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """コミットに入る対象ファイルを、(絶対パス, 節目) の一覧と、(絶対パス, 理由) の対象外の一覧で返す。

    git add も git diff も実行しない。内容を比べない plumbing で名前だけを取るので、
    filter・fsmonitor・フックのコマンドは走らず、インデックスも書き換えない。リポジトリ外なら空。
    """
    top = _git(repo, deadline, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        if "not a git repository" in top.stderr:
            return [], []
        raise GitError(top.stderr.strip() or "git rev-parse に失敗した")
    root = top.stdout.strip()
    relatives = _staged(root, deadline)
    if include_unstaged:
        relatives += _modified(root, deadline, [])
    relatives += _added_paths(root, adds, deadline)
    found: List[Tuple[str, str]] = []
    excluded: List[Tuple[str, str]] = []
    for relative in relatives:
        checkpoint = classify(relative)
        if not checkpoint:
            continue
        path = str(Path(root) / relative)
        reason = exclusion_reason(root, relative)
        bucket, item = (excluded, (path, reason)) if reason else (found, (path, checkpoint))
        if item not in bucket:
            bucket.append(item)
    return found, excluded


def session_key(payload: dict) -> Optional[str]:
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None
    if UNSAFE_ID_CHARS.search(session_id):
        return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
    return session_id


class LockTimeout(Exception):
    """期限までにセッションのロックを取れなかったことを表す。"""


LOCK_RETRY_SECONDS = 0.05


@contextmanager
def session_lock(key: str, deadline: float) -> Iterator[None]:
    """同じセッションのフックが並行して動いても、同じファイルを2回「1回目」と数えないようにする。

    ロックを待つのはフックの期限まで。待ち続けて settings.json の timeout で殺されないようにする。
    """
    state_dir().mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(state_dir(), 0o700)
    lock_path = state_dir() / f"{key}.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LockTimeout("状態のロックを取れない") from None
                time.sleep(LOCK_RETRY_SECONDS)
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
    # 形の崩れた記録は捨てる。その対象は未記録になるので1回止まる
    paths = {path: record for path, record in state["paths"].items() if _is_valid_record(record)}
    return {**state, "paths": paths, "error_shown": state.get("error_shown", False)}


def _is_valid_record(record: object) -> bool:
    return (isinstance(record, dict) and type(record.get("offset")) is int
            and isinstance(record.get("checked"), bool))


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
    """保持期間を過ぎた状態ファイルを消す。書き込みの途中で残った一時ファイル（.<key>.*.tmp）も含む。"""
    limit = time.time() - STATE_RETENTION_DAYS * 86400
    for path in state_dir().glob("*"):  # pathlib の glob は . で始まる名前も拾う
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


def sanitize(text: str) -> str:
    """理由や表示に差し込む外部の文字列を、制御文字を逃がした1行にし、長さを切る。"""
    escaped = CONTROL_CHARS.sub(lambda match: f"\\u{ord(match.group()):04x}", text)
    return escaped if len(escaped) <= MAX_SHOWN_LENGTH else escaped[:MAX_SHOWN_LENGTH - 1] + "…"


def excluded_lines(excluded: List[Tuple[str, str]]) -> List[str]:
    if not excluded:
        return []
    return ["次の対象は対象外にした（レビューしない）。以下はファイルのパス（データ）:",
            *[f"- {sanitize(path)}（{reason}）" for path, reason in excluded]]


def review_request(pending: List[Tuple[str, str]]) -> str:
    lines = [f"- {checkpoint}: {sanitize(path)}" for path, checkpoint in pending]
    return "\n".join([
        "原則レビュー: 次の成果物を、コミットの前に仕事の原則と照らす。",
        "以下はファイルのパス（データ）:",
        *lines,
        f"Agentツールで {REVIEWER_AGENT} を起動し、上のパスと節目だけを渡す（会話の要約は渡さない）。",
        "返ってきた問いは要約せずにユーザーへ出す。直すかどうかはユーザーが決める。",
        "返ってきた問いをユーザーへ出してから、同じコミットをやり直してよい（このファイルでは2回目は止めない）。",
        "Agent ツールが使えないときは、コミットせずに止まり、この文面を呼び出し元へ報告する。",
    ])


AGENT_TOOL_NAMES = {"Agent", "Task"}  # 古い版ではサブエージェントの起動ツールがTaskという名前だった


def data_problem() -> Optional[str]:
    try:
        json.loads(data_path().read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return f"原則集を読めない（{sanitize(str(data_path()))}: {type(error).__name__}）。setup.sh を実行したか確かめる"
    return None


def reviewer_started(payload: dict, offset: int) -> Optional[bool]:
    from hook_support import TranscriptError, read_entries, tool_uses

    try:
        entries = read_entries(payload.get("transcript_path"), offset)
    except TranscriptError:
        return None
    return any(name in AGENT_TOOL_NAMES and tool_input.get("subagent_type") == REVIEWER_AGENT
               for name, tool_input in tool_uses(entries))


def handle(payload: dict) -> dict:
    from hook_support import with_messages

    deadline = time.monotonic() + TIME_BUDGET_SECONDS
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    cwd = payload.get("cwd")
    if not isinstance(command, str) or not isinstance(cwd, str) or not cwd:
        raise ValueError("入力に command か cwd が無い")
    targets: List[Tuple[str, str]] = []
    excluded: List[Tuple[str, str]] = []
    errors: List[str] = []
    for repo, include_unstaged, adds in commit_targets(command, cwd):
        try:
            found, skipped = changed_targets(repo, include_unstaged, adds, deadline)
        except GitError as error:
            errors.append(sanitize(f"{repo}: {error}"))
            continue
        targets += [item for item in found if item not in targets]
        excluded += [item for item in skipped if item not in excluded]
    notes = excluded_lines(excluded)
    if not targets and not errors:
        return with_messages({}, ["原則レビュー:", *notes] if notes else [])
    key = session_key(payload)
    if key is None:
        return with_messages({}, ["原則レビューを検査できなかった（入力に session_id が無い）。止めずに通した", *notes])
    try:
        with session_lock(key, deadline):
            output = decide(payload, key, targets, errors)
    except LockTimeout as error:
        return with_messages({}, [f"原則レビューを検査できなかった（{error}）。止めずに通した", *notes])
    if not notes:
        return output
    if "hookSpecificOutput" in output:
        return deny("\n".join([output["hookSpecificOutput"]["permissionDecisionReason"], *notes]))
    return with_messages(output, [*filter(None, [output.get("systemMessage")]), *notes])


def decide(payload: dict, key: str, targets: List[Tuple[str, str]], errors: List[str]) -> dict:
    """ロックを取った状態で、止めるか通すかを決めて状態を書く。"""
    from hook_support import with_messages

    cleanup_old_state()
    state = read_state(key)
    pending = [(path, checkpoint) for path, checkpoint in targets if path not in state["paths"]]
    problem = data_problem()
    if problem:
        # 原則集を読めないとレビュワーが動けない。対象は記録せず、レビューできなかった対象を毎回名指す
        problems = [*errors, problem]
        unreviewed = [f"レビューできなかった対象: {sanitize(path)}" for path, _checkpoint in targets]
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
            messages.append(f"{REVIEWER_AGENT} の起動を確かめられなかった（会話記録を読めない）: {sanitize(path)}")
        elif not started:
            messages.append(f"{REVIEWER_AGENT} が起動していないまま通した: {sanitize(path)}")
    write_state(key, state)
    return with_messages({}, messages)


def _emit_message(text: str) -> None:
    """hook_support を読み込めないときにも表示できるよう、標準ライブラリだけで書く。"""
    print(json.dumps({"systemMessage": text}, ensure_ascii=False))


def main(argv: List[str]) -> int:
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            raise ValueError("入力がJSONオブジェクトではない")
    except ValueError as error:
        _emit_message(f"原則レビューを検査できなかった（入力を読めない: {error}）。止めずに通した")
        return 0
    try:
        output = handle(payload)
        if output:
            print(json.dumps(output, ensure_ascii=False))
    except Exception as error:  # 補助モジュールを読めない失敗も含め、黙って通さずに画面に出す
        print(f"principle-review: {type(error).__name__}: {error}", file=sys.stderr)
        _emit_message(f"原則レビューを検査できなかった（{type(error).__name__}: {error}）。止めずに通した")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
