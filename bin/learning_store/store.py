"""学習記録storeの識別、binding、状態検査を提供する。"""

from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from typing import Dict, Mapping, Optional
import uuid


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
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
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
    if value["schema_version"] != 1 or value["state"] not in {"prepared", "active"}:
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


def assert_git_root(root: Path) -> None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
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
    if _existing_binding(env) is not None:
        raise StoreError("BINDING_CONFLICT", "bindingが既にあります")
    try:
        subprocess.run(
            ["git", "init", "-b", "learning-records", str(root)],
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise StoreError("GIT_INIT_FAILED", "Git repositoryを初期化できません") from error
    store_id = str(uuid.uuid4())
    _atomic_json(
        root / ".learning-store.json",
        {"schema_version": 1, "state": "prepared", "store_id": store_id},
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
    files = []
    for path in directory.rglob("*"):
        relative = path.relative_to(root)
        current = root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise StoreError("UNSAFE_PATH", f"{directory_name}配下にsymlinkがあります")
        if path.is_dir():
            continue
        if not path.is_file() or path.suffix != suffix:
            raise StoreError("UNSAFE_PATH", f"{directory_name}配下に想定外のfileがあります")
        files.append(path)
    return tuple(sorted(files))


def scan_records(store: Store):
    from learning_store.schema import parse_record, validate_operation

    records = []
    for path in _safe_files(store.root, "records", ".md"):
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise StoreError("INVALID_RECORD", "recordを読み取れません") from error
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
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
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


def _git_lock_path(root: Path) -> Path:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--git-path", "agent-learning.lock"],
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise StoreError("NOT_GIT_REPOSITORY", "Git metadata pathを取得できません") from error
    path = Path(result.stdout.strip())
    if not path.is_absolute():
        path = root / path
    return path


def _safe_parent(root: Path, relative: Path) -> Path:
    current = root
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
    try:
        existing = target.read_bytes()
    except OSError as error:
        raise StoreError("RECORD_ID_CONFLICT", "既存fileを照合できません") from error
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
    relative = _target_for(normalized)
    lock_path = _git_lock_path(store.root)
    try:
        lock_file = lock_path.open("a+b")
    except OSError as error:
        raise StoreError("WRITE_FAILED", "排他lockを開けません") from error
    with lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
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
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StoreError("INVALID_INPUT", "inputはUTF-8のJSON objectである必要があります") from error
    if not isinstance(value, dict):
        raise StoreError("INVALID_INPUT", "inputはJSON objectである必要があります")
    return value
