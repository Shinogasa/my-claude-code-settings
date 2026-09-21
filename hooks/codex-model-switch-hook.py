#!/usr/bin/env python3
"""親セッションのモデル切替中にpromptとlocal toolを制御する。"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path


BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))
from codex_model_switch import (  # noqa: E402
    SwitchError, bound_repo, cancel, issue_begin_preflight, override,
    record_user_prompt_delivery, resume, status, validate_handoff_edit_target,
)


RESUME_RE = re.compile(r"MODEL_SWITCH_RESUME ([0-9a-f]{32}) ([A-Za-z0-9.-]+) ([a-z]+)")
OVERRIDE_RE = re.compile(r"MODEL_SWITCH_OVERRIDE ([0-9a-f]{32}) ([A-Za-z0-9._-]+) ([^\r\n]{1,256})")
CANCEL_RE = re.compile(r"MODEL_SWITCH_CANCEL ([0-9a-f]{32})")
SHELL_META = set(";&|<>`$\\\n\r*?[]{}")
BASH_TOOL_NAMES = {"Bash", "exec_command", "shell_command"}


def _root(cwd: str) -> Path | None:
    if not isinstance(cwd, str) or not cwd:
        raise SwitchError("hookのcwdが不正です")
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith("GIT_"):
            environment.pop(key)
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    result = subprocess.run(
        ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "rev-parse", "--show-toplevel"],
        cwd=cwd, env=environment, capture_output=True, text=True, check=False, timeout=5,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def _context(message: str, event: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": message,
        }
    }, ensure_ascii=False))


def _reject(reason: str) -> int:
    print(f"MODEL_SWITCH_BLOCKED: {reason}", file=sys.stderr)
    return 2


def _block_prompt(reason: str) -> int:
    message = f"MODEL_SWITCH_BLOCKED: {reason}"
    print(json.dumps({
        "decision": "block",
        "reason": message,
    }, ensure_ascii=False))
    return 0


def _session_state(cwd_repo: Path | None, session_id: str) -> tuple[Path | None, dict | None]:
    binding = bound_repo(session_id)
    if binding is not None:
        data = status(binding, session_id)
        if data is None:
            raise SwitchError("session registryに対応するmanifestがありません")
        if data["state"] in {"PREPARING", "SWITCH_PENDING"} and cwd_repo != binding:
            raise SwitchError("切替中のsessionが対象repo外へ移動しました")
        return binding, data
    data = status(cwd_repo, session_id) if cwd_repo is not None else None
    if data is not None and data["state"] in {"PREPARING", "SWITCH_PENDING"}:
        raise SwitchError("切替中のmanifestにsession registryがありません")
    return cwd_repo, data


def _prompt(repo: Path | None, data: dict | None, session_id: str, model: str, prompt: str) -> int:
    match = CANCEL_RE.fullmatch(prompt)
    if data is not None and match and data["state"] != "CANCELLED":
        cancel(repo, session_id, match.group(1))
        _context("モデル切替を取消しました。", "UserPromptSubmit")
        return 0
    if data is None or data["state"] in {"ACTIVE", "CANCELLED"}:
        if prompt.startswith("MODEL_SWITCH_"):
            return _block_prompt("有効な切替待ちではありません")
        return 0
    if data["state"] != "SWITCH_PENDING":
        return _block_prompt("handoff準備中です。publishまたは取消を完了してください")
    match = RESUME_RE.fullmatch(prompt)
    if match:
        updated = resume(repo, session_id, *match.groups(), model)
        _context(
            "切替をuser-attestedで再開しました。作業前にhandoffと参照文書を"
            "validate-codex-handoff.py read --expected-input-digest "
            f"{updated['input_digest']}で全行読んでください。"
            f"handoff={updated['handoff_path']} phase={updated['phase_lease']}",
            "UserPromptSubmit",
        )
        return 0
    match = OVERRIDE_RE.fullmatch(prompt)
    if match:
        updated = override(repo, session_id, *match.groups(), model)
        _context(
            f"このtaskの{updated['phase_lease']}工程に限りoverrideしました。"
            "handoffと参照文書をvalidator readで全行読んでください。"
            "次checkpointではペアを再分類してください。",
            "UserPromptSubmit",
        )
        return 0
    return _block_prompt("切替待ちです。厳密なRESUME、OVERRIDE、CANCELだけを受け付けます")


def _same_script(argument: str, expected: Path) -> bool:
    candidate = Path(argument).expanduser()
    try:
        return candidate.samefile(expected)
    except OSError:
        return False


def _flag_values(arguments: list[str]) -> dict[str, str] | None:
    if len(arguments) % 2:
        return None
    values = {}
    for key, value in zip(arguments[::2], arguments[1::2]):
        if not key.startswith("--") or key in values or not value:
            return None
        values[key] = value
    return values


def _begin_flags(command: str, repo: Path, session_id: str) -> dict[str, str] | None:
    if not isinstance(command, str) or set(command) & SHELL_META:
        return None
    try:
        arguments = shlex.split(command)
    except ValueError:
        return None
    if arguments[:2] == ["rtk", "proxy"]:
        arguments = arguments[2:]
    if len(arguments) < 4 or arguments[0] != "python3":
        return None
    script, operation = arguments[1:3]
    if operation != "begin" or not _same_script(script, BIN / "codex-model-switch.py"):
        return None
    flags = _flag_values(arguments[3:])
    expected = {
        "--repo", "--session-id", "--task-id", "--current-phase", "--next-phase",
        "--model", "--effort", "--handoff",
    }
    if flags is None or set(flags) != expected or flags["--session-id"] != session_id:
        raise SwitchError("begin commandの引数がhook preflight契約と一致しません")
    candidate = Path(flags["--repo"]).expanduser()
    try:
        if not candidate.is_absolute() or not candidate.samefile(repo):
            raise SwitchError("begin commandのrepoが現在のrepoと一致しません")
    except OSError as error:
        raise SwitchError("begin commandのrepoを確認できません") from error
    return {key: value for key, value in flags.items() if key != "--repo"}


def _allowed_bash(command: str, repo: Path, session_id: str, data: dict) -> bool:
    if not isinstance(command, str) or set(command) & SHELL_META:
        return False
    try:
        arguments = shlex.split(command)
    except ValueError:
        return False
    if arguments[:2] == ["rtk", "proxy"]:
        arguments = arguments[2:]
    if len(arguments) < 4 or arguments[0] != "python3":
        return False
    script, operation = arguments[1:3]
    tail = arguments[3:]
    flags = _flag_values(tail)
    if _same_script(script, BIN / "codex-model-switch.py"):
        return (
            operation in ({"status", "publish"} if data["state"] == "PREPARING" else {"status"})
            and flags == {"--repo": str(repo), "--session-id": session_id}
        )
    if not _same_script(script, BIN / "validate-codex-handoff.py"):
        return False
    if operation == "state" and data["state"] == "PREPARING":
        return flags == {"--repo": str(repo)}
    if operation not in ({"validate", "read"} if data["state"] == "PREPARING" else {"read"}):
        return False
    if not tail:
        return False
    handoff = tail[0]
    expected = data["handoff_path"]
    if handoff not in {expected, str(repo / expected)}:
        return False
    flags = _flag_values(tail[1:])
    if flags is None:
        return False
    required = {
        "--repo": str(repo),
        "--expected-model": data["target_model"],
        "--expected-reasoning-effort": data["target_effort"],
    }
    if any(flags.get(key) != value for key, value in required.items()):
        return False
    if operation == "validate":
        return set(flags) == set(required)
    return (
        flags.get("--expected-input-digest") == data["input_digest"]
        and flags.get("--document") in {"handoff", "requirements", "review-package"}
        and set(flags) <= set(required) | {
            "--expected-input-digest", "--document", "--start-line", "--line-count"
        }
    )


def _allowed_patch(command: str, repo: Path, cwd: str, data: dict) -> bool:
    if not isinstance(command, str) or not command.startswith("*** Begin Patch\n") or not command.endswith("*** End Patch"):
        return False
    headers = [line for line in command.splitlines() if line.startswith("*** ")]
    if len(headers) != 3 or headers[-1] != "*** End Patch":
        return False
    expected = data["handoff_path"]
    relative = {f"*** Add File: {expected}", f"*** Update File: {expected}"}
    absolute = {f"*** Add File: {repo / expected}", f"*** Update File: {repo / expected}"}
    if headers[1] in relative:
        if not Path(cwd).samefile(repo):
            return False
    elif headers[1] not in absolute:
        return False
    validate_handoff_edit_target(repo, expected)
    return True


def _pretool(repo: Path | None, data: dict | None, session_id: str, cwd: str, tool_name: str, tool_input: object) -> int:
    if data is None or data["state"] in {"ACTIVE", "CANCELLED"}:
        if repo is None or not isinstance(tool_input, dict):
            return 0
        command = tool_input.get("command", tool_input.get("cmd"))
        flags = _begin_flags(command, repo, session_id)
        if flags is None:
            return 0
        turn_id = tool_input.get("turn_id")
        issue_begin_preflight(repo, session_id, turn_id, flags)
        return 0
    if not isinstance(tool_input, dict):
        return _reject("tool入力が不正です")
    if tool_name in BASH_TOOL_NAMES and _allowed_bash(
        tool_input.get("command", tool_input.get("cmd")), repo, session_id, data
    ):
        return 0
    if (
        data["state"] == "PREPARING"
        and tool_name == "apply_patch"
        and _allowed_patch(tool_input.get("command"), repo, cwd, data)
    ):
        return 0
    return _reject("モデル切替中のlocal toolは許可されたhandoff操作だけです")


def main() -> int:
    event = None
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise SwitchError("hook入力はJSON objectが必要です")
        event = payload.get("hook_event_name")
        if event not in {"SessionStart", "UserPromptSubmit", "PreToolUse"}:
            raise SwitchError("対象外のhook eventです")
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise SwitchError("session_idが不正です")
        cwd_repo = _root(payload.get("cwd"))
        repo, data = _session_state(cwd_repo, session_id)
        if event == "SessionStart":
            state = data["state"] if data else "NONE"
            _context(
                f"Codex model switch session_id={session_id} state={state}。"
                "切替中は指定handoffだけを扱い、hookが無効ならguard確認済みと表示しないでください。",
                event,
            )
            return 0
        if event == "UserPromptSubmit":
            prompt = payload.get("prompt")
            if not isinstance(prompt, str):
                raise SwitchError("promptが不正です")
            if repo is not None:
                record_user_prompt_delivery(
                    repo, session_id, payload.get("turn_id"), payload.get("model", ""),
                )
            return _prompt(repo, data, session_id, payload.get("model", ""), prompt)
        tool_input = payload.get("tool_input")
        if isinstance(tool_input, dict):
            tool_input = {**tool_input, "turn_id": payload.get("turn_id")}
        return _pretool(repo, data, session_id, payload["cwd"], payload.get("tool_name"), tool_input)
    except (SwitchError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        if event == "UserPromptSubmit":
            return _block_prompt(str(error))
        return _reject(str(error))


if __name__ == "__main__":
    sys.exit(main())
