"""学習記録storeの識別、binding、状態検査を提供する。"""

from dataclasses import dataclass
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
from typing import Dict, Mapping, Optional
import uuid


_GIT_EXECUTABLE = shutil.which("git", path=os.defpath)
MAX_JSON_BYTES = 1024 * 1024
MAX_RECORD_BYTES = 1024 * 1024
MAX_LEGACY_BYTES = 8 * 1024 * 1024


class StoreError(Exception):
    """利用者が修正できるstore境界の失敗。"""

    def __init__(self, code: str, message: str, details: Optional[Dict[str, object]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class Store:
    root: Path
    binding: Path
    store_id: str
    state: str


def _run_git(arguments, **kwargs):
    if _GIT_EXECUTABLE is None:
        raise OSError("trusted git executable was not found")
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    environment["PATH"] = os.defpath
    return subprocess.run(
        [_GIT_EXECUTABLE, *arguments],
        env=environment,
        **kwargs,
    )


def _read_limited(path: Path, limit: int, code: str, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(path), flags)
    except OSError as error:
        raise StoreError(code, f"{label}を読み取れません") from error
    try:
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise StoreError(code, f"{label}は通常fileである必要があります")
            if metadata.st_size > limit:
                raise StoreError(code, f"{label}がsize上限を超えています")
            payload = source.read(limit + 1)
    except StoreError:
        raise
    except OSError as error:
        raise StoreError(code, f"{label}を読み取れません") from error
    if len(payload) > limit:
        raise StoreError(code, f"{label}がsize上限を超えています")
    return payload


def binding_path(env: Mapping[str, str]) -> Path:
    if env.get("XDG_CONFIG_HOME"):
        base = Path(env["XDG_CONFIG_HOME"])
    elif env.get("HOME"):
        base = Path(env["HOME"]) / ".config"
    else:
        raise StoreError("NOT_CONFIGURED", "HOMEが設定されていません")
    return base / "agent-learning" / "config.json"


def _uuid(value: object, code: str) -> str:
    if not isinstance(value, str):
        raise StoreError(code, "store_idがUUIDではありません")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as error:
        raise StoreError(code, "store_idがUUIDではありません") from error
    if str(parsed) != value:
        raise StoreError(code, "store_idが正規化されたUUIDではありません")
    return value


def _read_json(path: Path, code: str, label: str) -> Dict[str, object]:
    if path.is_symlink():
        raise StoreError(code, f"{label}にsymlinkは使えません")
    try:
        raw = _read_limited(path, MAX_JSON_BYTES, code, label)
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StoreError(code, f"{label}を読み取れません") from error
    if not isinstance(value, dict):
        raise StoreError(code, f"{label}はJSON objectである必要があります")
    return value


def _validate_binding(value: Dict[str, object]) -> Dict[str, object]:
    if set(value) != {"schema_version", "store_id", "store_root"}:
        raise StoreError("INVALID_BINDING", "bindingのキーが不正です")
    if value["schema_version"] != 1:
        raise StoreError("INVALID_BINDING", "bindingのschema versionが不正です")
    _uuid(value["store_id"], "INVALID_BINDING")
    root = value["store_root"]
    if not isinstance(root, str) or not Path(root).is_absolute():
        raise StoreError("INVALID_BINDING", "store_rootは絶対pathである必要があります")
    return value


def _validate_marker(value: Dict[str, object]) -> Dict[str, object]:
    if set(value) != {"schema_version", "store_id", "state"}:
        raise StoreError("INVALID_MARKER", "markerのキーが不正です")
    if value["schema_version"] != 2 or value["state"] not in {"prepared", "active"}:
        raise StoreError("INVALID_MARKER", "markerのschemaまたはstateが不正です")
    _uuid(value["store_id"], "INVALID_MARKER")
    return value


def _canonical_directory(repo: Path, *, require_empty: bool = False) -> Path:
    if not repo.is_absolute():
        raise StoreError("INVALID_REPO", "repoは正規化された絶対pathで指定してください")
    try:
        resolved = repo.resolve(strict=True)
    except OSError as error:
        raise StoreError("INVALID_REPO", "repo directoryが存在しません") from error
    if resolved != repo or not repo.is_dir():
        raise StoreError("INVALID_REPO", "repoはsymlinkを含まない正規化されたdirectoryで指定してください")
    if require_empty:
        try:
            if next(repo.iterdir(), None) is not None:
                raise StoreError("REPO_NOT_EMPTY", "init先は空directoryである必要があります")
        except OSError as error:
            raise StoreError("INVALID_REPO", "repo directoryを読み取れません") from error
    return repo


def _assert_private_directory(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise StoreError("UNSAFE_PERMISSIONS", f"{label}の権限を確認できません") from error
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        raise StoreError("UNSAFE_PERMISSIONS", f"{label}は実directoryである必要があります")
    if metadata.st_uid != os.geteuid():
        raise StoreError("UNSAFE_PERMISSIONS", f"{label}のownerが実行userと一致しません")
    if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise StoreError("UNSAFE_PERMISSIONS", f"{label}をgroupまたはotherが書き込めます")


def _assert_private_store_tree(root: Path) -> None:
    for name in ("imports", "legacy", "operations", "records"):
        base = root / name
        if not base.exists() and not base.is_symlink():
            continue
        if base.is_symlink() or not base.is_dir():
            raise StoreError("UNSAFE_PATH", f"{name}は実directoryである必要があります")
        _assert_private_directory(base, name)
        for path in base.rglob("*"):
            if path.is_symlink():
                raise StoreError("UNSAFE_PATH", f"{name}配下にsymlinkがあります")
            if path.is_dir():
                _assert_private_directory(path, f"{name}配下のdirectory")


def assert_git_root(root: Path) -> None:
    try:
        result = _run_git(
            ["-C", str(root), "rev-parse", "--show-toplevel"],
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise StoreError("NOT_GIT_REPOSITORY", "storeはGit repositoryではありません") from error
    try:
        git_root = Path(result.stdout.strip()).resolve(strict=True)
    except OSError as error:
        raise StoreError("GIT_ROOT_MISMATCH", "Git rootを解決できません") from error
    if git_root != root.resolve(strict=True):
        raise StoreError("GIT_ROOT_MISMATCH", "markerとGit rootの実体が一致しません")


def _atomic_json(path: Path, value: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _assert_private_directory(path.parent, f"{path.name}の親directory")
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(str(temporary), str(path))
        directory_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as error:
        raise StoreError("WRITE_FAILED", f"{path.name}を原子的に保存できません") from error
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _existing_binding(env: Mapping[str, str]) -> Optional[Dict[str, object]]:
    path = binding_path(env)
    if not path.exists() and not path.is_symlink():
        return None
    return _validate_binding(_read_json(path, "INVALID_BINDING", "binding"))


def _store_at(repo: Path, env: Mapping[str, str]) -> Store:
    root = _canonical_directory(repo)
    _assert_private_directory(root, "store root")
    _assert_private_store_tree(root)
    marker = _validate_marker(_read_json(root / ".learning-store.json", "INVALID_MARKER", "marker"))
    assert_git_root(root)
    return Store(
        root=root,
        binding=binding_path(env),
        store_id=str(marker["store_id"]),
        state=str(marker["state"]),
    )


def _load_store_from_binding(path: Path) -> Store:
    if not path.exists() and not path.is_symlink():
        raise StoreError("NOT_CONFIGURED", "bindingが設定されていません")
    binding = _validate_binding(_read_json(path, "INVALID_BINDING", "binding"))
    root = Path(str(binding["store_root"]))
    if not root.exists():
        raise StoreError("STORE_NOT_FOUND", "binding先のstoreが存在しません")
    root = _canonical_directory(root)
    _assert_private_directory(root, "store root")
    _assert_private_store_tree(root)
    marker = _validate_marker(_read_json(root / ".learning-store.json", "INVALID_MARKER", "marker"))
    assert_git_root(root)
    store = Store(
        root=root,
        binding=path,
        store_id=str(marker["store_id"]),
        state=str(marker["state"]),
    )
    if store.store_id != binding["store_id"]:
        raise StoreError("STORE_ID_MISMATCH", "bindingとmarkerのstore_idが一致しません")
    if store.state == "active":
        _verify_active_import(store)
    return store


def load_store(env: Mapping[str, str]) -> Store:
    return _load_store_from_binding(binding_path(env))


def _binding_value(store: Store) -> Dict[str, object]:
    return {
        "schema_version": 1,
        "store_id": store.store_id,
        "store_root": str(store.root),
    }


def bind_store(repo: Path, replace: bool, env: Mapping[str, str]) -> Dict[str, object]:
    store = _store_at(repo, env)
    existing = _existing_binding(env)
    wanted = _binding_value(store)
    if existing == wanted:
        changed = False
    else:
        if existing is not None and not replace:
            raise StoreError("BINDING_CONFLICT", "別のstoreへのbindingが既にあります")
        _atomic_json(store.binding, wanted)
        changed = True
    return {
        "ok": True,
        "root": str(store.root),
        "state": store.state,
        "store_id": store.store_id,
        "binding_changed": changed,
    }


def init_store(repo: Path, env: Mapping[str, str]) -> Dict[str, object]:
    root = _canonical_directory(repo, require_empty=True)
    _assert_private_directory(root, "store root")
    if _existing_binding(env) is not None:
        raise StoreError("BINDING_CONFLICT", "bindingが既にあります")
    try:
        _run_git(
            ["init", "-b", "learning-records", str(root)],
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise StoreError("GIT_INIT_FAILED", "Git repositoryを初期化できません") from error
    store_id = str(uuid.uuid4())
    _atomic_json(
        root / ".learning-store.json",
        {"schema_version": 2, "state": "prepared", "store_id": store_id},
    )
    store = _store_at(root, env)
    _atomic_json(store.binding, _binding_value(store))
    return {
        "ok": True,
        "root": str(store.root),
        "state": store.state,
        "store_id": store.store_id,
    }


def status(env: Mapping[str, str]) -> Dict[str, object]:
    store = load_store(env)
    return {
        "ok": True,
        "root": str(store.root),
        "state": store.state,
        "store_id": store.store_id,
        "writable": store.state == "active" and os.access(str(store.root), os.W_OK),
    }


def _safe_files(root: Path, directory_name: str, suffix: str):
    directory = root / directory_name
    if not directory.exists() and not directory.is_symlink():
        return ()
    if directory.is_symlink() or not directory.is_dir():
        raise StoreError("UNSAFE_PATH", f"{directory_name}は実directoryである必要があります")
    _assert_private_directory(directory, directory_name)
    files = []
    for path in directory.rglob("*"):
        relative = path.relative_to(root)
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise StoreError("UNSAFE_PATH", f"{directory_name}配下にsymlinkがあります")
        if path.is_dir():
            _assert_private_directory(path, f"{directory_name}配下のdirectory")
            continue
        if not path.is_file() or path.suffix != suffix:
            raise StoreError("UNSAFE_PATH", f"{directory_name}配下に想定外のfileがあります")
        files.append(path)
    return tuple(sorted(files))


def scan_records(store: Store):
    from learning_store.schema import parse_record, validate_operation

    records = []
    for path in _safe_files(store.root, "records", ".md"):
        raw = _read_limited(path, MAX_RECORD_BYTES, "INVALID_RECORD", "record")
        record = parse_record(raw)
        relative = path.relative_to(store.root)
        observed = str(record["observed_at"])
        expected_name = f"{observed[:10]}-{record['id']}.md"
        expected = Path("records") / str(record["kind"]) / observed[:4] / expected_name
        if relative != expected:
            raise StoreError("INVALID_RECORD", "record pathと内容が一致しません")
        records.append(record)

    for path in _safe_files(store.root, "operations", ".json"):
        try:
            raw = _read_limited(path, MAX_JSON_BYTES, "INVALID_OPERATION", "operation")
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StoreError("INVALID_OPERATION", "operationを読み取れません") from error
        operation = validate_operation(value)
        relative = path.relative_to(store.root)
        observed = str(operation["observed_at"])
        expected = Path("operations") / observed[:4] / f"{observed[:10]}-{operation['id']}.json"
        if relative != expected:
            raise StoreError("INVALID_OPERATION", "operation pathと内容が一致しません")
    return tuple(records)


def list_records(env: Mapping[str, str], capability: Optional[str]) -> Dict[str, object]:
    from learning_store.schema import analyze_history, conflicting_events

    store = load_store(env)
    records = scan_records(store)
    history = analyze_history(records)
    conflicts = conflicting_events(history)
    if conflicts:
        raise StoreError(
            "EVENT_CONFLICT",
            "訂正履歴に複数の有効末尾があります",
            {"conflicts": {key: list(value) for key, value in conflicts.items()}},
        )
    heads = [heads[0] for heads in history.heads_by_event.values()]
    heads.sort(key=lambda item: (str(item["observed_at"]), str(item["id"])))
    if capability is not None:
        selected = [item for item in heads if item["capability_id"] == capability]
        return {"ok": True, "records": selected, "count": len(selected)}
    grouped: Dict[str, Dict[str, object]] = {}
    for item in heads:
        identifier = str(item["capability_id"])
        summary = grouped.setdefault(identifier, {
            "capability_id": identifier,
            "count": 0,
            "scopes": [],
        })
        summary["count"] = int(summary["count"]) + 1
        if item["scope"] not in summary["scopes"]:
            summary["scopes"].append(item["scope"])
    capabilities = [grouped[key] for key in sorted(grouped)]
    return {"ok": True, "capabilities": capabilities, "count": len(capabilities)}


@contextmanager
def _store_lock(root: Path):
    _assert_private_directory(root, "store root")
    try:
        descriptor = os.open(
            str(root), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
    except OSError as error:
        raise StoreError("WRITE_FAILED", "store directoryの排他lockを開けません") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise StoreError("UNSAFE_PATH", "store directoryのownerまたは型が不正です")
        if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise StoreError("UNSAFE_PERMISSIONS", "store directoryが他userから書込可能です")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError as error:
            raise StoreError("WRITE_FAILED", "store directoryの排他lockを取得できません") from error
        try:
            current = root.lstat()
        except OSError as error:
            raise StoreError("UNSAFE_PATH", "store directoryを再確認できません") from error
        if not stat.S_ISDIR(current.st_mode) or (
            current.st_dev, current.st_ino
        ) != (metadata.st_dev, metadata.st_ino):
            raise StoreError("UNSAFE_PATH", "store directoryがlock取得中に差し替わりました")
        yield
    finally:
        os.close(descriptor)


def _safe_parent(root: Path, relative: Path) -> Path:
    current = root
    _assert_private_directory(current, "store root")
    for part in relative.parts:
        if part in {"", ".", ".."}:
            raise StoreError("UNSAFE_PATH", "保存先pathが不正です")
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink() or not current.is_dir():
                raise StoreError("UNSAFE_PATH", "保存先にsymlinkまたは非directoryがあります")
        else:
            try:
                current.mkdir()
            except OSError as error:
                raise StoreError("WRITE_FAILED", "保存先directoryを作成できません") from error
        _assert_private_directory(current, "保存先directory")
    try:
        if current.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
            return current
    except AttributeError:
        try:
            current.resolve(strict=True).relative_to(root.resolve(strict=True))
            return current
        except ValueError:
            pass
    except (OSError, ValueError):
        pass
    raise StoreError("UNSAFE_PATH", "保存先がstore root外です")


def publish_exclusive(parent: Path, name: str, payload: bytes) -> None:
    _assert_private_directory(parent, "保存先directory")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".learning-", dir=str(parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(str(temporary), str(parent / name), follow_symlinks=False)
        except FileExistsError:
            raise StoreError("RECORD_ID_CONFLICT", "同じIDのfileが既にあります")
        directory_fd = os.open(str(parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except StoreError:
        raise
    except OSError as error:
        raise StoreError("WRITE_FAILED", "recordを排他的に保存できません") from error
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _target_for(value: Mapping[str, object]) -> Path:
    observed = str(value["observed_at"])
    if value["kind"] == "operation":
        return Path("operations") / observed[:4] / f"{observed[:10]}-{value['id']}.json"
    return Path("records") / str(value["kind"]) / observed[:4] / f"{observed[:10]}-{value['id']}.md"


def _idempotent_existing(store: Store, relative: Path, payload: bytes) -> Optional[Dict[str, object]]:
    target = store.root / relative
    if not target.exists() and not target.is_symlink():
        return None
    if target.is_symlink() or not target.is_file():
        raise StoreError("UNSAFE_PATH", "既存の保存先が通常fileではありません")
    limit = MAX_JSON_BYTES if relative.suffix == ".json" else MAX_RECORD_BYTES
    existing = _read_limited(target, limit, "RECORD_ID_CONFLICT", "既存file")
    if existing != payload:
        raise StoreError("RECORD_ID_CONFLICT", "同じIDに異なる内容が保存されています")
    return {
        "ok": True,
        "id": relative.stem[11:],
        "path": str(relative),
        "created": False,
    }


def save_record(store: Store, value: Dict[str, object], resolve_conflict: bool = False) -> Dict[str, object]:
    from learning_store.schema import (
        analyze_history,
        conflicting_events,
        serialize_operation,
        serialize_record,
        validate_input,
        validate_operation,
    )

    if store.state != "active":
        raise StoreError("STORE_NOT_ACTIVE", "prepared storeには新規記録を保存できません")
    if value.get("kind") == "operation":
        normalized = validate_operation(value)
        payload = serialize_operation(normalized)
    else:
        normalized = validate_input(value)
        payload = serialize_record(normalized)
    payload_limit = MAX_JSON_BYTES if normalized["kind"] == "operation" else MAX_RECORD_BYTES
    if len(payload) > payload_limit:
        raise StoreError("INVALID_INPUT", "serialize後のrecordがsize上限を超えています")
    relative = _target_for(normalized)
    with _store_lock(store.root):
        # lock取得後にbinding、marker、全履歴を再検査する。
        current = _load_store_from_binding(store.binding)
        if current.root != store.root or current.store_id != store.store_id or current.state != "active":
            raise StoreError("STORE_CHANGED", "操作中にbindingまたはmarkerが変わりました")
        records = scan_records(current)
        history = analyze_history(records)
        existing = _idempotent_existing(current, relative, payload)
        if existing is not None:
            existing["event_id"] = normalized["event_id"]
            return existing

        if normalized["kind"] != "operation":
            event_id = str(normalized["event_id"])
            heads = history.heads_by_event.get(event_id, ())
            head_ids = {str(item["id"]) for item in heads}
            supplied = set(str(item) for item in normalized["supersedes"])
            conflicts = conflicting_events(history)
            if resolve_conflict:
                body = str(normalized["body"])
                reason = body.split("## 統合理由", 1)[1].strip() if "## 統合理由" in body else ""
                if len(heads) < 2 or supplied != head_ids or not reason:
                    raise StoreError("INVALID_SUPERSEDES", "分岐解消には全末尾と統合理由が必要です")
            else:
                if conflicts:
                    raise StoreError(
                        "EVENT_CONFLICT",
                        "訂正履歴に複数の有効末尾があります",
                        {"conflicts": {key: list(ids) for key, ids in conflicts.items()}},
                    )
                expected = head_ids if heads else set()
                if len(heads) > 1 or supplied != expected or len(supplied) > 1:
                    raise StoreError("INVALID_SUPERSEDES", "現在の唯一の末尾を訂正元に指定してください")

        parent = _safe_parent(current.root, relative.parent)
        publish_exclusive(parent, relative.name, payload)
        return {
            "ok": True,
            "id": normalized["id"],
            "event_id": normalized["event_id"],
            "path": str(relative),
            "created": True,
        }


def read_record_input(path: Path) -> Dict[str, object]:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise StoreError("INVALID_INPUT", "input fileを読み取れません") from error
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise StoreError("INVALID_INPUT", "inputはsymlinkではない通常fileである必要があります")
    try:
        raw = _read_limited(path, MAX_JSON_BYTES, "INVALID_INPUT", "input")
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StoreError("INVALID_INPUT", "inputはUTF-8のJSON objectである必要があります") from error
    if not isinstance(value, dict):
        raise StoreError("INVALID_INPUT", "inputはJSON objectである必要があります")
    return value


def _source_entries(source: Path):
    try:
        result = _run_git(
            ["-C", str(source), "ls-tree", "-r", "-z", "--name-only", "HEAD", "--",
             "learning/entries", "learning/code/entries"],
            check=True,
            capture_output=True,
        )
        commit = _run_git(
            ["-C", str(source), "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise StoreError("INVALID_SOURCE", "取込元のGit HEADを読み取れません") from error
    try:
        tracked = {item for item in result.stdout.decode("utf-8").split("\0") if item}
    except UnicodeDecodeError as error:
        raise StoreError("INVALID_SOURCE", "取込元pathはUTF-8である必要があります") from error

    expected = set()
    locations = (
        (Path("learning/entries"), "decision"),
        (Path("learning/code/entries"), "code"),
    )
    for relative_directory, _kind in locations:
        directory = source / relative_directory
        if directory.is_symlink():
            raise StoreError("INVALID_SOURCE", "取込対象directoryにsymlinkは使えません")
        if not directory.exists():
            continue
        if not directory.is_dir():
            raise StoreError("INVALID_SOURCE", "取込対象がdirectoryではありません")
        for path in directory.glob("*.md"):
            if path.is_symlink() or not path.is_file():
                raise StoreError("INVALID_SOURCE", "取込対象にsymlinkまたは非通常fileがあります")
            expected.add(path.relative_to(source).as_posix())

    tracked_targets = set()
    for name in tracked:
        candidate = Path(name)
        if candidate.suffix != ".md":
            continue
        if candidate.parent in {location[0] for location in locations}:
            tracked_targets.add(candidate.as_posix())
    if expected != tracked_targets:
        raise StoreError("SOURCE_NOT_CLEAN", "取込対象の作業ツリーとHEADのfile集合が一致しません")

    entries = []
    for source_path in sorted(expected):
        path = source / source_path
        try:
            working_bytes = _read_limited(
                path, MAX_LEGACY_BYTES, "INVALID_SOURCE", "取込対象"
            )
            size_text = _run_git(
                ["-C", str(source), "cat-file", "-s", f"HEAD:{source_path}"],
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip()
            committed_size = int(size_text)
            if committed_size > MAX_LEGACY_BYTES:
                raise StoreError("INVALID_SOURCE", "取込対象がsize上限を超えています")
            committed = _run_git(
                ["-C", str(source), "cat-file", "blob", f"HEAD:{source_path}"],
                check=True,
                capture_output=True,
            ).stdout
            if len(committed) != committed_size:
                raise StoreError("INVALID_SOURCE", "取込対象のGit blob sizeが一致しません")
        except StoreError:
            raise
        except (OSError, ValueError, subprocess.CalledProcessError) as error:
            raise StoreError("INVALID_SOURCE", "取込対象のGit blobを読み取れません") from error
        if working_bytes != committed:
            raise StoreError("SOURCE_NOT_CLEAN", "取込対象の内容がHEADと一致しません")
        kind = "code" if source_path.startswith("learning/code/") else "decision"
        legacy_path = Path("legacy") / kind / path.name
        entries.append({
            "kind": kind,
            "source_path": source_path,
            "legacy_path": legacy_path.as_posix(),
            "sha256": hashlib.sha256(committed).hexdigest(),
            "payload": committed,
        })
    return commit, entries


def _canonical_source(source: Path) -> Path:
    if not source.is_absolute():
        raise StoreError("INVALID_SOURCE", "sourceは正規化された絶対pathで指定してください")
    try:
        resolved = source.resolve(strict=True)
    except OSError as error:
        raise StoreError("INVALID_SOURCE", "source directoryが存在しません") from error
    if resolved != source or not source.is_dir():
        raise StoreError("INVALID_SOURCE", "sourceにsymlinkは使えません")
    try:
        assert_git_root(source)
    except StoreError as error:
        raise StoreError("INVALID_SOURCE", "sourceはGit rootである必要があります") from error
    return source


def _manifest_files(store: Store):
    directory = store.root / "imports"
    if not directory.exists() and not directory.is_symlink():
        return ()
    if directory.is_symlink() or not directory.is_dir():
        raise StoreError("UNSAFE_PATH", "importsは実directoryである必要があります")
    _assert_private_directory(directory, "imports")
    manifests = []
    for path in sorted(directory.iterdir()):
        if path.is_symlink() or not path.is_file() or path.suffix != ".json":
            raise StoreError("IMPORT_CONFLICT", "imports配下に想定外のfileがあります")
        value = _read_json(path, "IMPORT_CONFLICT", "import manifest")
        if not isinstance(value, dict) or set(value) != {
            "schema_version", "import_id", "source_commit", "count", "files"
        }:
            raise StoreError("IMPORT_CONFLICT", "import manifestのキー集合が不正です")
        try:
            import_id = _uuid(value["import_id"], "IMPORT_CONFLICT")
        except StoreError as error:
            raise StoreError("IMPORT_CONFLICT", error.message) from error
        if value["schema_version"] != 1 or path.name != f"{import_id}.json":
            raise StoreError("IMPORT_CONFLICT", "import manifestのschemaまたはpathが不正です")
        if not isinstance(value["source_commit"], str) or len(value["source_commit"]) != 40:
            raise StoreError("IMPORT_CONFLICT", "source_commitが不正です")
        if not isinstance(value["count"], int) or isinstance(value["count"], bool):
            raise StoreError("IMPORT_CONFLICT", "manifest countが不正です")
        files = value["files"]
        if not isinstance(files, list) or len(files) != value["count"]:
            raise StoreError("IMPORT_CONFLICT", "manifest filesとcountが一致しません")
        for item in files:
            if not isinstance(item, dict) or set(item) != {
                "kind", "source_path", "legacy_path", "sha256"
            }:
                raise StoreError("IMPORT_CONFLICT", "manifest file entryが不正です")
            kind = item["kind"]
            source_path = item["source_path"]
            legacy_path = item["legacy_path"]
            digest = item["sha256"]
            if kind not in {"decision", "code"}:
                raise StoreError("IMPORT_CONFLICT", "manifest kindが不正です")
            if not all(isinstance(value, str) for value in (source_path, legacy_path, digest)):
                raise StoreError("IMPORT_CONFLICT", "manifest file entryの型が不正です")
            source = Path(source_path)
            expected_source_parent = (
                Path("learning/code/entries") if kind == "code" else Path("learning/entries")
            )
            if source.parent != expected_source_parent or source.name in {"", ".", ".."}:
                raise StoreError("IMPORT_CONFLICT", "manifest source pathが不正です")
            if Path(legacy_path) != Path("legacy") / str(kind) / source.name:
                raise StoreError("IMPORT_CONFLICT", "manifest legacy pathが不正です")
            if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
                raise StoreError("IMPORT_CONFLICT", "manifest hashが不正です")
        manifests.append((path, value))
    return tuple(manifests)


def _verify_active_import(store: Store) -> None:
    manifests = _manifest_files(store)
    if len(manifests) != 1:
        raise StoreError("INCOMPLETE_IMPORT", "active storeには照合済みmanifestが1件必要です")
    _path, manifest = manifests[0]
    expected = [Path(str(item["legacy_path"])) for item in manifest["files"]]
    actual = {
        path.relative_to(store.root)
        for path in _safe_files(store.root, "legacy", ".md")
    }
    if len(expected) != len(set(expected)) or set(expected) != actual:
        raise StoreError("INCOMPLETE_IMPORT", "manifestとlegacy file集合が一致しません")
    for item in manifest["files"]:
        target = store.root / str(item["legacy_path"])
        if target.is_symlink() or not target.is_file():
            raise StoreError("INCOMPLETE_IMPORT", "manifestが参照するlegacy fileがありません")
        payload = _read_limited(
            target, MAX_LEGACY_BYTES, "INCOMPLETE_IMPORT", "legacy file"
        )
        if hashlib.sha256(payload).hexdigest() != item["sha256"]:
            raise StoreError("INCOMPLETE_IMPORT", "legacy fileのhashがmanifestと一致しません")


def _manifest_core(commit: str, entries) -> Dict[str, object]:
    return {
        "schema_version": 1,
        "source_commit": commit,
        "count": len(entries),
        "files": [
            {key: entry[key] for key in ("kind", "source_path", "legacy_path", "sha256")}
            for entry in entries
        ],
    }


def _matching_manifest(store: Store, core: Dict[str, object]):
    manifests = _manifest_files(store)
    matches = []
    for path, value in manifests:
        comparable = {key: value[key] for key in core}
        if comparable == core:
            matches.append((path, value))
    if manifests and len(matches) != 1:
        raise StoreError("IMPORT_CONFLICT", "既存manifestと取込元が一致しません")
    return matches[0] if matches else None


def import_legacy(store: Store, source: Path) -> Dict[str, object]:
    source = _canonical_source(source)
    commit, entries = _source_entries(source)
    core = _manifest_core(commit, entries)
    with _store_lock(store.root):
        current = _load_store_from_binding(store.binding)
        if current.root != store.root or current.store_id != store.store_id:
            raise StoreError("STORE_CHANGED", "操作中にbindingまたはmarkerが変わりました")
        match = _matching_manifest(current, core)
        if current.state == "active" and match is None:
            raise StoreError("IMPORT_CONFLICT", "active storeへ異なる取込は追加できません")

        for entry in entries:
            relative = Path(str(entry["legacy_path"]))
            target = current.root / relative
            if target.exists() or target.is_symlink():
                if target.is_symlink() or not target.is_file():
                    raise StoreError("LEGACY_CONFLICT", "既存legacyが通常fileではありません")
                existing = _read_limited(
                    target, MAX_LEGACY_BYTES, "LEGACY_CONFLICT", "既存legacy"
                )
                if existing != entry["payload"]:
                    raise StoreError("LEGACY_CONFLICT", "既存legacyの内容が取込元と一致しません")
                continue
            parent = _safe_parent(current.root, relative.parent)
            try:
                publish_exclusive(parent, relative.name, entry["payload"])
            except StoreError as error:
                if error.code == "RECORD_ID_CONFLICT":
                    raise StoreError("LEGACY_CONFLICT", error.message) from error
                raise

        created = match is None
        if match is None:
            import_id = str(uuid.uuid4())
            manifest = dict(core, import_id=import_id)
            payload = (json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
            if len(payload) > MAX_JSON_BYTES:
                raise StoreError("IMPORT_CONFLICT", "import manifestがsize上限を超えています")
            parent = _safe_parent(current.root, Path("imports"))
            publish_exclusive(parent, f"{import_id}.json", payload)
            manifest_path = Path("imports") / f"{import_id}.json"
        else:
            existing_path, manifest = match
            import_id = str(manifest["import_id"])
            manifest_path = existing_path.relative_to(current.root)

        marker = {"schema_version": 2, "store_id": current.store_id, "state": "active"}
        _atomic_json(current.root / ".learning-store.json", marker)
        return {
            "ok": True,
            "import_id": import_id,
            "path": manifest_path.as_posix(),
            "count": len(entries),
            "created": created,
            "state": "active",
        }
