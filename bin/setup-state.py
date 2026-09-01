#!/usr/bin/env python3
"""setup.sh が管理する生成物と退避先を判定する小さな状態管理モジュール。"""
import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path


DEFAULT_STATE = {"version": 1, "generated": {}}


def sha256_file(path):
    """ファイル内容の SHA-256 を16進数で返す。"""
    digest = hashlib.sha256()
    with Path(path).open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_path(path):
    """競合検査後の変更検知に使う、path自身のfingerprintを返す。"""
    path = Path(path)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return {"kind": "missing"}
    snapshot = {
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
        "mode": metadata.st_mode,
        "size": metadata.st_size,
        "mtime_ns": metadata.st_mtime_ns,
        "links": metadata.st_nlink,
    }
    if stat.S_ISLNK(metadata.st_mode):
        snapshot.update(kind="symlink", target=os.readlink(path))
    elif stat.S_ISREG(metadata.st_mode):
        snapshot.update(kind="file", sha256=sha256_file(path))
    elif stat.S_ISDIR(metadata.st_mode):
        snapshot["kind"] = "directory"
    else:
        snapshot["kind"] = "other"
    return snapshot


def _restore_quarantined_file(quarantined, destination, remove_parent=False):
    """regular fileを既存destinationへ上書きせず隔離先から戻す。"""
    quarantined_path = Path(quarantined)
    destination_path = Path(destination)
    try:
        if not stat.S_ISREG(quarantined_path.lstat().st_mode):
            return False
        os.link(quarantined_path, destination_path)
    except (FileExistsError, FileNotFoundError):
        return False
    quarantined_path.unlink()
    if remove_parent:
        quarantined_path.parent.rmdir()
    return True


def install_generated_file(staged, destination, expected_snapshot):
    """staged生成物を、検査後の更新を上書きせずdestinationへ配置する。"""
    staged_path = Path(staged)
    destination_path = Path(destination)
    if expected_snapshot == {"kind": "missing"}:
        if snapshot_path(destination_path) != expected_snapshot:
            raise RuntimeError(f"target changed after preflight: {destination_path}")
        try:
            os.link(staged_path, destination_path)
        except FileExistsError as error:
            raise RuntimeError(
                f"target appeared during generated apply: {destination_path}"
            ) from error
        staged_path.unlink()
        return

    quarantine_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{destination_path.name}.setup-quarantine.",
            dir=destination_path.parent,
        )
    )
    quarantined = quarantine_dir / destination_path.name
    try:
        os.rename(destination_path, quarantined)
    except FileNotFoundError as error:
        quarantine_dir.rmdir()
        raise RuntimeError(
            f"target changed after preflight: {destination_path}"
        ) from error

    actual_snapshot = snapshot_path(quarantined)
    if actual_snapshot != expected_snapshot:
        if _restore_quarantined_file(
            quarantined,
            destination_path,
            remove_parent=True,
        ):
            raise RuntimeError(
                f"target changed after preflight; restored at {destination_path}"
            )
        raise RuntimeError(
            f"target changed after preflight; preserved at {quarantined}"
        )
    try:
        os.link(staged_path, destination_path)
    except FileExistsError as error:
        raise RuntimeError(
            f"target appeared during generated apply; previous file preserved at {quarantined}"
        ) from error
    staged_path.unlink()
    quarantined.unlink()
    quarantine_dir.rmdir()


def backup_conflict(source, backup, expected_snapshot):
    """競合pathを差し替え競合から守りながらbackupへ移す。"""
    source_path = Path(source)
    backup_path = Path(backup)
    try:
        os.rename(source_path, backup_path)
    except FileNotFoundError as error:
        raise RuntimeError(f"target changed after preflight: {source_path}") from error

    actual_snapshot = snapshot_path(backup_path)
    if actual_snapshot != expected_snapshot:
        if _restore_quarantined_file(backup_path, source_path):
            raise RuntimeError(
                f"target changed after preflight; restored at {source_path}"
            )
        raise RuntimeError(
            f"target changed after preflight; preserved at {backup_path}"
        )

    if actual_snapshot["kind"] == "file" and actual_snapshot["links"] > 1:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{backup_path.name}.setup-copy.",
            dir=backup_path.parent,
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            shutil.copy2(backup_path, temporary, follow_symlinks=False)
            if (
                snapshot_path(backup_path) != expected_snapshot
                or sha256_file(temporary) != expected_snapshot["sha256"]
            ):
                if _restore_quarantined_file(backup_path, source_path):
                    raise RuntimeError(
                        f"target changed during backup; restored at {source_path}"
                    )
                raise RuntimeError(
                    f"target changed during backup; preserved at {backup_path}"
                )
            os.replace(temporary, backup_path)
        finally:
            temporary.unlink(missing_ok=True)

    if source_path.exists() or source_path.is_symlink():
        raise RuntimeError(
            f"target appeared while backing up conflict: {source_path}; "
            f"previous file preserved at {backup_path}"
        )


def classify(source, destination, recorded, generated=False):
    """destination の所有状態を missing/linked/managed-update/conflict に分類する。"""
    source_path = Path(source).resolve()
    destination_path = Path(destination)
    if not destination_path.exists() and not destination_path.is_symlink():
        return "missing"
    if generated:
        if destination_path.is_symlink():
            return "conflict"
        try:
            if destination_path.is_file() and destination_path.stat().st_nlink > 1:
                return "conflict"
        except OSError:
            return "conflict"
    if destination_path.is_symlink():
        try:
            if destination_path.resolve() == source_path:
                return "linked"
        except OSError:
            pass
        return "conflict"
    if recorded and destination_path.is_file() and sha256_file(destination_path) == recorded:
        return "managed-update"
    return "conflict"


def backup_path(host_root, destination, timestamp, home_root=None):
    """host別backup配下の衝突退避先を返す。"""
    host_path = Path(host_root).absolute()
    destination_path = Path(destination).absolute()
    try:
        relative = destination_path.relative_to(host_path)
    except ValueError:
        if home_root is None:
            raise ValueError("destination must be inside host_root") from None
        try:
            relative = destination_path.relative_to(Path(home_root).absolute())
        except ValueError as error:
            raise ValueError("destination must be inside home_root") from error
    return host_path / "backups" / timestamp / relative


def load_state(path):
    """ownership state を読み、欠損・不正形式なら空の安全な状態を返す。"""
    state_path = Path(path)
    if not state_path.is_file():
        return {"version": 1, "generated": {}}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "generated": {}}
    if not isinstance(state, dict) or state.get("version") != 1:
        return {"version": 1, "generated": {}}
    generated = state.get("generated")
    if not isinstance(generated, dict) or not all(
        isinstance(path_name, str) and isinstance(checksum, str)
        for path_name, checksum in generated.items()
    ):
        return {"version": 1, "generated": {}}
    return {"version": 1, "generated": dict(generated)}


def save_state(path, state):
    """state を同じディレクトリで原子的に保存する。"""
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_name(f".{state_path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(state_path)
