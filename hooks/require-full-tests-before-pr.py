#!/usr/bin/env python3
"""PreToolUse(Bash)フック: 全件テストの通過を記録していないコミットでは、PRを作らせない。

背景:
  テストの既定の組から、setup.shを実行する遅いテストを外した（ADR 0029）。
  代わりにPRの前に `bash tests/run.sh --all` を流す必要があるが、CIが無いので記憶頼みになる。

挙動:
  コマンドの位置に gh pr create があり、リポジトリの tests/run.sh に通過記録の目印があるときだけ調べる。
  リポジトリは cwd ではなく、同じコマンドの中の cd を追った移動先で決める。移動先を確定できなければ止める。
  tests/run.sh --all は、未コミットの変更が無い状態で全件が通るとHEADを .git の下へ記録する。
  記録がHEADと一致すれば通し、無いか古ければ止める（テストは流さないので、確認は一瞬で終わる）。
  gitの照会に失敗するなど、確かめられなかったときも止める。検査できなかったことを問題なしに畳まない。
"""
import functools
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

HOOKS_DIR = Path(__file__).resolve().parent
RUN_SCRIPT = Path("tests") / "run.sh"
# tests/run.sh が記録先のファイル名を持つ変数。これがあるリポジトリだけを対象にする
MARKER = "TESTS_ALL_PASSED_STAMP"
STAMP_NAME = "tests-all-passed"
GIT_TIMEOUT_SECONDS = 5
TIME_BUDGET_SECONDS = 20  # settings.json の timeout（30秒）より先に、自分で止める。打ち切られたフックは止めたことにならない
STARTED = time.monotonic()
RUN_ALL = "bash tests/run.sh --all"


@functools.lru_cache(maxsize=None)
def _jp_doc_review():
    # gh pr create の判定（引用符の中や bash -c の扱い）と cd の移動先の解決は、日本語レビューのフックと共有する
    spec = importlib.util.spec_from_file_location("jp_doc_review", HOOKS_DIR / "jp-doc-review.py")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(HOOKS_DIR))
    spec.loader.exec_module(module)
    return module


class CheckError(Exception):
    """記録とHEADを照らし合わせられなかったことを表す。"""


def _remaining() -> float:
    budget = float(os.environ.get("REQUIRE_FULL_TESTS_TIME_BUDGET", TIME_BUDGET_SECONDS))
    remaining = STARTED + budget - time.monotonic()
    if remaining <= 0:
        raise CheckError(f"時間予算（{budget:g}秒）を使い切った")
    return remaining


def _git(cwd: Path, *args: str) -> str:
    try:
        result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                                timeout=min(GIT_TIMEOUT_SECONDS, _remaining()))
    except subprocess.TimeoutExpired as error:
        _remaining()  # 予算の側で切れたなら、そう伝える
        raise CheckError(f"git {' '.join(args)}: {type(error).__name__}") from error
    except (OSError, subprocess.SubprocessError) as error:
        raise CheckError(f"git {' '.join(args)}: {type(error).__name__}") from error
    if result.returncode != 0:
        raise CheckError(f"git {' '.join(args)}: {result.stderr.strip() or result.returncode}")
    return result.stdout.strip()


def _find_root(cwd: Path) -> Optional[Path]:
    # gitが壊れていても対象かどうかは判定したいので、gitに頼らず .git を親方向へ探す
    for directory in (cwd, *cwd.parents):
        if (directory / ".git").exists():
            return directory
    return None  # リポジトリの外。gh pr create 自体が失敗するので、ここでは止めない


def _is_target(root: Path) -> bool:
    script = root / RUN_SCRIPT
    try:
        return MARKER in script.read_text(encoding="utf-8")
    except OSError:
        return False


def _deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}, ensure_ascii=False))


def check(root: Path) -> Optional[str]:
    """PRを作ってよければNone、止めるなら理由を返す。"""
    head = _git(root, "rev-parse", "HEAD")
    stamp = root / _git(root, "rev-parse", "--git-path", STAMP_NAME)
    try:
        recorded = stamp.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        recorded = None
    except OSError as error:
        raise CheckError(f"{stamp}: {type(error).__name__}") from error
    if recorded == head:
        return None
    state = "記録が無い" if recorded is None else f"記録は {recorded[:12]} のもので、HEADは {head[:12]}"
    return (f"このリポジトリ（{root}）は、PRの前に全件テストの通過が要る（{state}）。"
            f"未コミットの変更が無い状態で `{RUN_ALL}` を流し、通ったらもう一度 gh pr create を実行して。")


def _check_targets(command: str, cwd: str) -> Optional[str]:
    """PRを作りうるリポジトリごとに記録を確かめる。PRを作ってよければNone、止めるなら理由を返す。"""
    module = _jp_doc_review()
    dirs = module.pr_create_dirs(command, cwd)
    if module.guard().UNRESOLVED in dirs:
        # 検査できなかったことを問題なしに畳まない。書き直せば判定できるので止める
        return ("PRを作るリポジトリを決められなかった（同じコマンドの中の cd の移動先を、文字列から確定できない）。"
                "cd <リポジトリの絶対パス> && gh pr create ... の形で、もう一度実行して。")
    roots = {_find_root(Path(os.path.realpath(path))) for path in dirs} - {None}
    reasons = [check(root) for root in sorted(roots) if _is_target(root)]
    return "\n".join(reason for reason in reasons if reason) or None


def _looks_like_pr_create(text: str) -> bool:
    # 正しく判定できないときの代わり。取りこぼすより、止めすぎる側に倒す
    return all(word in text for word in ("gh", "pr", "create"))


def _is_pr_create(raw: str) -> tuple:
    """(PR作成か, コマンドの入ったpayload) を返す。判定できなければ文字列から推し量る。"""
    try:
        payload = json.loads(raw or "{}")
        tool_input = payload.get("tool_input")
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if not isinstance(command, str):
            raise ValueError("Bashの入力にcommand（文字列）が無い")
        return _jp_doc_review().is_pr_create(command), payload
    except Exception as error:  # 判定できなかったことを黙って通さない
        print(f"require-full-tests-before-pr: 判定できなかった: {type(error).__name__}: {error}", file=sys.stderr)
        return _looks_like_pr_create(raw), None


def main() -> int:
    raw = sys.stdin.read()
    is_pr_create, payload = _is_pr_create(raw)
    if not is_pr_create:
        return 0
    try:
        if payload is None:
            raise CheckError("入力を読めず、PRを作るリポジトリを決められない")
        cwd = payload.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            return 0
        reason = _check_targets(payload["tool_input"]["command"], cwd)
    except Exception as error:  # PR作成と分かった後の失敗は、すべて止める側に倒す
        reason = f"全件テストの通過記録を確かめられなかった（{error}）。`{RUN_ALL}` を流してから、もう一度試して。"
    if reason:
        _deny(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
