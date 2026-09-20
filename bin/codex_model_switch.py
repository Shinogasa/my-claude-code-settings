#!/usr/bin/env python3
"""Codex親セッションの切替manifestとhandoff検証を管理する。"""
from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
import re
import stat
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterator


def _load_validator():
    path = Path(__file__).with_name("validate-codex-handoff.py")
    spec = importlib.util.spec_from_file_location("codex_handoff_validator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("handoff validatorを読み込めません")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_validator()
STATES = {"PREPARING", "SWITCH_PENDING", "ACTIVE", "CANCELLED"}
PHASE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class SwitchError(ValueError):
    """切替状態を安全に処理できない。"""


def _safe_handoff_path(path: Path) -> str:
    value = path.as_posix()
    parts = PurePosixPath(value).parts
    if (
        path.is_absolute()
        or len(parts) != 3
        or parts[:2] != (".superpowers", "handoffs")
        or parts[2] in (".", "..")
        or not parts[2].endswith(".md")
    ):
        raise SwitchError("handoffは.superpowers/handoffs/*.mdを指定してください")
    return value


def _state_directory(repo: Path, create: bool) -> Path | None:
    parent = repo / ".superpowers"
    directory = parent / "model-switch"
    if create:
        if parent.is_symlink():
            raise SwitchError(".superpowersはsymlinkにできません")
        parent.mkdir(mode=0o700, exist_ok=True)
        directory.mkdir(mode=0o700, exist_ok=True)
    elif not directory.exists() and not directory.is_symlink():
        return None
    if parent.is_symlink() or directory.is_symlink():
        raise SwitchError("切替状態のdirectoryはsymlinkにできません")
    info = directory.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise SwitchError("切替状態のdirectory所有者が不正です")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise SwitchError("切替状態のdirectoryは0700が必要です")
    return directory


def _manifest_path(directory: Path, session_id: str) -> Path:
    if not isinstance(session_id, str) or not session_id or len(session_id) > 256:
        raise SwitchError("session_idが不正です")
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return directory / f"{digest}.json"


def _read_manifest(path: Path, session_id: str, repo: Path) -> dict | None:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise SwitchError(f"manifestを開けません: {error}") from error
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > 65536
        ):
            raise SwitchError("manifestの型、所有者、権限またはサイズが不正です")
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = -1
            data = json.load(stream)
    except (ValueError, UnicodeError) as error:
        raise SwitchError(f"manifestが不正です: {error}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        not isinstance(data, dict)
        or data.get("schema") != 1
        or data.get("session_id") != session_id
        or data.get("repo") != str(repo)
        or data.get("state") not in STATES
    ):
        raise SwitchError("manifestの識別子または状態が不正です")
    return data


def _write_manifest(path: Path, data: dict) -> None:
    payload = (json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _locked(repo: Path, session_id: str) -> Iterator[tuple[Path, dict | None]]:
    directory = _state_directory(repo, create=True)
    assert directory is not None
    path = _manifest_path(directory, session_id)
    lock_path = directory / (path.stem + ".lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise SwitchError("lock fileの権限が不正です")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield path, _read_manifest(path, session_id, repo)
    finally:
        os.close(descriptor)


def _repo_root(repo: Path) -> Path:
    try:
        with VALIDATOR.repository_root(repo) as (root, _descriptor):
            return root
    except (VALIDATOR.HandoffError, OSError) as error:
        raise SwitchError(str(error)) from error


def status(repo: Path, session_id: str) -> dict | None:
    root = _repo_root(repo)
    directory = _state_directory(root, create=False)
    if directory is None:
        return None
    return _read_manifest(_manifest_path(directory, session_id), session_id, root)


def begin(
    repo: Path,
    session_id: str,
    task_id: str,
    current_phase: str,
    next_phase: str,
    model: str,
    effort: str,
    handoff: Path,
) -> dict:
    root = _repo_root(repo)
    if VALIDATOR.TASK_ID_RE.fullmatch(task_id) is None:
        raise SwitchError("task_idが不正です")
    if not PHASE_RE.fullmatch(current_phase) or not PHASE_RE.fullmatch(next_phase):
        raise SwitchError("phaseが不正です")
    if effort not in VALIDATOR.MODEL_REASONING_EFFORTS.get(model, set()):
        raise SwitchError("modelとeffortの組合せが使えません")
    handoff_path = _safe_handoff_path(handoff)
    with _locked(root, session_id) as (path, previous):
        if previous and previous["state"] != "CANCELLED":
            raise SwitchError("このsessionには進行中または完了済みの切替があります")
        with VALIDATOR.repository_root(root) as (_root, descriptor):
            git_state = VALIDATOR.current_state(descriptor)
        data = {
            "schema": 1,
            "state": "PREPARING",
            "repo": str(root),
            "session_id": session_id,
            "transition_id": uuid.uuid4().hex,
            "task_id": task_id,
            "current_phase": current_phase,
            "next_phase": next_phase,
            "target_model": model,
            "target_effort": effort,
            "handoff_path": handoff_path,
            "pre_switch_git": git_state,
            "input_digest": None,
            "model_evidence": "unverified",
            "effort_evidence": "unverified",
            "verification_tier": "unverified",
            "override_reason": None,
            "phase_lease": None,
        }
        _write_manifest(path, data)
        return data


def publish(repo: Path, session_id: str) -> dict:
    root = _repo_root(repo)
    with _locked(root, session_id) as (path, data):
        if data is None or data["state"] != "PREPARING":
            raise SwitchError("PREPARINGの切替がありません")
        try:
            with VALIDATOR.repository_root(root) as (root_path, descriptor):
                current = VALIDATOR.current_state(descriptor)
                if current != data["pre_switch_git"]:
                    raise SwitchError("begin後にGit状態が変化しました")
                errors, digest, documents = VALIDATOR.validate_handoff(
                    Path(data["handoff_path"]), descriptor, root_path,
                    data["target_model"], data["target_effort"], None,
                )
            if errors:
                raise SwitchError("handoff検証失敗: " + "; ".join(errors))
            metadata, _body = VALIDATOR.parse_handoff(documents["handoff"])
        except (VALIDATOR.HandoffError, OSError, UnicodeError) as error:
            raise SwitchError(str(error)) from error
        if metadata["task_id"] != data["task_id"]:
            raise SwitchError("handoffのtask_idが異なります")
        data["input_digest"] = digest
        data["state"] = "SWITCH_PENDING"
        _write_manifest(path, data)
        return data
