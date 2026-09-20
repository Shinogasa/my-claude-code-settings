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


def validate_handoff_edit_target(repo: Path, handoff_path: str) -> None:
    """指定handoff以外への書込みにつながるpath aliasを拒否する。"""
    current = repo
    parts = PurePosixPath(_safe_handoff_path(Path(handoff_path))).parts
    for index, part in enumerate(parts):
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise SwitchError("handoffのpathにsymlinkは使えません")
        if index < len(parts) - 1:
            if not stat.S_ISDIR(info.st_mode):
                raise SwitchError("handoffの親pathがdirectoryではありません")
        elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise SwitchError("handoffは単独のregular fileが必要です")


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
    if create:
        # 対象repoに既定ignoreが無くても、manifestがhandoffのGit fingerprintを変えない。
        ignore = directory / ".gitignore"
        try:
            descriptor = os.open(ignore, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            descriptor = -1
        if descriptor >= 0:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(b"*\n")
                stream.flush()
                os.fsync(stream.fileno())
        try:
            descriptor = os.open(ignore, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stream.read() != b"*\n":
                    raise SwitchError("切替状態の.gitignoreが不正です")
        except OSError as error:
            raise SwitchError(f"切替状態の.gitignoreを確認できません: {error}") from error
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
        or not isinstance(data.get("repo"), str)
        or not Path(data["repo"]).is_absolute()
        or (data["repo"] != str(repo) and data.get("state") != "CANCELLED")
        or data.get("state") not in STATES
    ):
        raise SwitchError("manifestの識別子または状態が不正です")
    required = {
        "schema", "state", "repo", "session_id", "transition_id", "task_id",
        "current_phase", "next_phase", "target_model", "target_effort",
        "handoff_path", "pre_switch_git", "input_digest", "model_evidence",
        "effort_evidence", "verification_tier", "override_reason", "phase_lease",
    }
    if not required <= set(data) or set(data) - required - {"actual_model"}:
        raise SwitchError("manifestのfieldが欠落または未知です")
    if re.fullmatch(r"[0-9a-f]{32}", data["transition_id"]) is None:
        raise SwitchError("manifestのtransition IDが不正です")
    if VALIDATOR.TASK_ID_RE.fullmatch(data["task_id"]) is None:
        raise SwitchError("manifestのtask IDが不正です")
    if not PHASE_RE.fullmatch(data["current_phase"]) or not PHASE_RE.fullmatch(data["next_phase"]):
        raise SwitchError("manifestのphaseが不正です")
    if data["target_effort"] not in VALIDATOR.MODEL_REASONING_EFFORTS.get(data["target_model"], set()):
        raise SwitchError("manifestの対象ペアが不正です")
    if _safe_handoff_path(Path(data["handoff_path"])) != data["handoff_path"]:
        raise SwitchError("manifestのhandoff pathが不正です")
    git_state = data["pre_switch_git"]
    if (
        not isinstance(git_state, dict)
        or set(git_state) != {"branch", "head", "worktree_fingerprint"}
        or not isinstance(git_state["branch"], str)
        or not git_state["branch"]
        or VALIDATOR.HEAD_RE.fullmatch(git_state["head"]) is None
        or VALIDATOR.SHA256_RE.fullmatch(git_state["worktree_fingerprint"]) is None
    ):
        raise SwitchError("manifestのGit識別子が不正です")
    digest = data["input_digest"]
    if digest is not None and (not isinstance(digest, str) or VALIDATOR.SHA256_RE.fullmatch(digest) is None):
        raise SwitchError("manifestのdigestが不正です")
    if data["state"] in {"SWITCH_PENDING", "ACTIVE"} and digest is None:
        raise SwitchError("manifestのdigestが欠落しています")
    reason = data["override_reason"]
    if reason is not None and (not isinstance(reason, str) or not reason.strip() or len(reason) > 256):
        raise SwitchError("manifestのoverride理由が不正です")
    if data["state"] == "ACTIVE":
        expected_effort = "unverified" if reason is not None else "user-attested"
        expected_tier = "unverified" if reason is not None else "user-attested"
        if (
            data["phase_lease"] != data["next_phase"]
            or data["model_evidence"] != "hook-observed"
            or data["effort_evidence"] != expected_effort
            or data["verification_tier"] != expected_tier
            or (reason is not None and not data.get("actual_model"))
        ):
            raise SwitchError("manifestのACTIVE証拠が不整合です")
    elif data["state"] in {"PREPARING", "SWITCH_PENDING"}:
        if (
            data["phase_lease"] is not None
            or reason is not None
            or data["model_evidence"] != "unverified"
            or data["effort_evidence"] != "unverified"
            or data["verification_tier"] != "unverified"
        ):
            raise SwitchError("manifestの切替待ち証拠が不整合です")
    elif data["phase_lease"] is not None:
        raise SwitchError("取消済みmanifestにleaseが残っています")
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


def _registry_directory(create: bool) -> Path | None:
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    if not home.is_absolute() or home.is_symlink() or not home.is_dir():
        raise SwitchError("CODEX_HOMEが安全なdirectoryではありません")
    directory = home / "model-switch-registry"
    if create:
        directory.mkdir(mode=0o700, exist_ok=True)
    elif not directory.exists() and not directory.is_symlink():
        return None
    if directory.is_symlink():
        raise SwitchError("session registryはsymlinkにできません")
    info = directory.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise SwitchError("session registryは所有者本人の0700 directoryが必要です")
    return directory


def _read_binding(path: Path, session_id: str) -> Path | None:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    try:
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 4096:
                raise SwitchError("session registry fileが不正です")
            record = json.load(stream)
    except (OSError, ValueError, UnicodeError) as error:
        raise SwitchError(f"session registryを読めません: {error}") from error
    if (
        not isinstance(record, dict)
        or set(record) != {"schema", "session_id", "repo"}
        or record["schema"] != 1
        or record["session_id"] != session_id
        or not isinstance(record["repo"], str)
        or not Path(record["repo"]).is_absolute()
    ):
        raise SwitchError("session registryの識別子が不正です")
    return Path(record["repo"])


@contextmanager
def _locked_binding(session_id: str, create: bool) -> Iterator[tuple[Path | None, Path | None]]:
    directory = _registry_directory(create)
    if directory is None:
        yield None, None
        return
    path = _manifest_path(directory, session_id)
    lock_path = directory / (path.stem + ".lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise SwitchError("session registry lockが不正です")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield path, _read_binding(path, session_id)
    finally:
        os.close(descriptor)


def bound_repo(session_id: str) -> Path | None:
    """sessionが既に切替状態を持つ場合、cwdに依存せずrepoを返す。"""
    with _locked_binding(session_id, create=False) as (_path, repo):
        return repo


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
    validate_handoff_edit_target(root, handoff_path)
    with _locked_binding(session_id, create=True) as (binding_path, bound):
        assert binding_path is not None
        if bound is not None and bound != root:
            previous_bound = status(bound, session_id)
            if previous_bound is None or previous_bound["state"] in {"PREPARING", "SWITCH_PENDING"}:
                raise SwitchError("このsessionは別repoの切替に束縛されています")
        with _locked(root, session_id) as (path, previous):
            if previous and previous["state"] in {"PREPARING", "SWITCH_PENDING"}:
                raise SwitchError("このsessionには進行中の切替があります")
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
            # registry lock中に両fileを公開し、hookが中間状態を読まないようにする。
            _write_manifest(path, data)
            _write_manifest(binding_path, {
                "schema": 1, "session_id": session_id, "repo": str(root)
            })
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


def _validated_pending(root: Path, data: dict) -> None:
    if data.get("state") != "SWITCH_PENDING" or not data.get("input_digest"):
        raise SwitchError("SWITCH_PENDINGの切替がありません")
    try:
        with VALIDATOR.repository_root(root) as (root_path, descriptor):
            current = VALIDATOR.current_state(descriptor)
            if current != data["pre_switch_git"]:
                raise SwitchError("切替前のGit状態が変化しました")
            errors, digest, documents = VALIDATOR.validate_handoff(
                Path(data["handoff_path"]), descriptor, root_path,
                data["target_model"], data["target_effort"], data["input_digest"],
            )
        if errors:
            raise SwitchError("handoff再検証失敗: " + "; ".join(errors))
        metadata, _body = VALIDATOR.parse_handoff(documents["handoff"])
    except (VALIDATOR.HandoffError, OSError, UnicodeError, KeyError) as error:
        raise SwitchError(str(error)) from error
    if metadata["task_id"] != data["task_id"] or digest != data["input_digest"]:
        raise SwitchError("handoffのtaskまたはdigestが変化しました")


def resume(
    repo: Path, session_id: str, transition_id: str,
    model: str, effort: str, observed_model: str,
) -> dict:
    root = _repo_root(repo)
    with _locked(root, session_id) as (path, data):
        if data is None or data["state"] != "SWITCH_PENDING":
            raise SwitchError("再開可能な切替がありません")
        if transition_id != data["transition_id"]:
            raise SwitchError("transition IDが異なります")
        if (model, effort) != (data["target_model"], data["target_effort"]):
            raise SwitchError("申告されたmodelとeffortが対象ペアと異なります")
        if observed_model != model:
            raise SwitchError("hookが観測したmodelが申告と異なります")
        _validated_pending(root, data)
        data["state"] = "ACTIVE"
        data["model_evidence"] = "hook-observed"
        data["effort_evidence"] = "user-attested"
        data["verification_tier"] = "user-attested"
        data["phase_lease"] = data["next_phase"]
        _write_manifest(path, data)
        return data


def override(
    repo: Path, session_id: str, transition_id: str,
    phase: str, reason: str, observed_model: str,
) -> dict:
    root = _repo_root(repo)
    with _locked(root, session_id) as (path, data):
        if data is None or data["state"] != "SWITCH_PENDING":
            raise SwitchError("override可能な切替がありません")
        if transition_id != data["transition_id"] or phase != data["next_phase"]:
            raise SwitchError("transition IDまたはphaseが異なります")
        if not reason.strip() or len(reason) > 256:
            raise SwitchError("override理由が不正です")
        if not observed_model:
            raise SwitchError("現在のmodelを観測できません")
        _validated_pending(root, data)
        data["state"] = "ACTIVE"
        data["model_evidence"] = "hook-observed"
        data["effort_evidence"] = "unverified"
        data["verification_tier"] = "unverified"
        data["override_reason"] = reason
        data["phase_lease"] = phase
        data["actual_model"] = observed_model
        _write_manifest(path, data)
        return data


def cancel(repo: Path, session_id: str, transition_id: str) -> dict:
    root = _repo_root(repo)
    with _locked_binding(session_id, create=False) as (binding_path, bound):
        if binding_path is None or bound != root:
            raise SwitchError("session registryのrepoが一致しません")
        with _locked(root, session_id) as (path, data):
            if data is None or data["state"] not in {"PREPARING", "SWITCH_PENDING", "ACTIVE"}:
                raise SwitchError("取消可能な切替がありません")
            if transition_id != data["transition_id"]:
                raise SwitchError("transition IDが異なります")
            data["state"] = "CANCELLED"
            data["phase_lease"] = None
            _write_manifest(path, data)
            binding_path.unlink()
            return data
