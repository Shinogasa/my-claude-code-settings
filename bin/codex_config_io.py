#!/usr/bin/env python3
"""Codex config.toml を安全に読み書きする共通トランザクション。"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import fcntl
import os
import secrets
import stat
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


# macOS SDK の sys/acl.h で定義されるACL定数。ctypesには公開されないため固定する。
ACL_TYPE_EXTENDED = 0x00000100
ACL_FIRST_ENTRY = 0
ACL_NEXT_ENTRY = -1
ACL_EXTENDED_ALLOW = 1
ACL_READ_DATA = 1 << 1
ACL_WRITE_DATA = 1 << 2
ACL_DELETE = 1 << 4
ACL_APPEND_DATA = 1 << 5
ACL_DELETE_CHILD = 1 << 6
ACL_WRITE_ATTRIBUTES = 1 << 8
ACL_WRITE_EXTATTRIBUTES = 1 << 10
ACL_WRITE_SECURITY = 1 << 12
ACL_CHANGE_OWNER = 1 << 13
ACL_MUTATION_MASK = (
    ACL_WRITE_DATA
    | ACL_DELETE
    | ACL_APPEND_DATA
    | ACL_DELETE_CHILD
    | ACL_WRITE_ATTRIBUTES
    | ACL_WRITE_EXTATTRIBUTES
    | ACL_WRITE_SECURITY
    | ACL_CHANGE_OWNER
)


class ConfigurationError(Exception):
    """設定を安全に更新できない場合の内部エラー。"""


def _extended_acl_allows(descriptor: int, permissions_to_reject: int) -> bool:
    """macOSのACLに指定権限を許すallow ACEがあるか構造化APIで判定する。"""
    if sys.platform != "darwin":
        return False
    library_name = ctypes.util.find_library("System")
    if library_name is None:
        raise ConfigurationError("ACL API is unavailable")
    library = ctypes.CDLL(library_name, use_errno=True)
    acl_get_fd_np = library.acl_get_fd_np
    acl_get_fd_np.argtypes = [ctypes.c_int, ctypes.c_int]
    acl_get_fd_np.restype = ctypes.c_void_p
    acl_free = library.acl_free
    acl_free.argtypes = [ctypes.c_void_p]
    acl_free.restype = ctypes.c_int
    acl_get_entry = library.acl_get_entry
    acl_get_entry.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
    acl_get_entry.restype = ctypes.c_int
    acl_get_tag_type = library.acl_get_tag_type
    acl_get_tag_type.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
    acl_get_tag_type.restype = ctypes.c_int
    acl_get_permset_mask_np = library.acl_get_permset_mask_np
    acl_get_permset_mask_np.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64)]
    acl_get_permset_mask_np.restype = ctypes.c_int

    ctypes.set_errno(0)
    acl = acl_get_fd_np(descriptor, ACL_TYPE_EXTENDED)
    if not acl:
        error_number = ctypes.get_errno()
        if error_number == errno.ENOENT:
            return False
        raise ConfigurationError("ACL could not be inspected")

    try:
        entry_id = ACL_FIRST_ENTRY
        while True:
            entry = ctypes.c_void_p()
            ctypes.set_errno(0)
            if acl_get_entry(acl, entry_id, ctypes.byref(entry)) != 0:
                if ctypes.get_errno() == errno.EINVAL:
                    return False
                raise ConfigurationError("ACL entry could not be inspected")
            entry_id = ACL_NEXT_ENTRY

            tag_type = ctypes.c_int()
            if acl_get_tag_type(entry, ctypes.byref(tag_type)) != 0:
                raise ConfigurationError("ACL tag could not be inspected")
            if tag_type.value != ACL_EXTENDED_ALLOW:
                continue

            permission_mask = ctypes.c_uint64()
            if acl_get_permset_mask_np(entry, ctypes.byref(permission_mask)) != 0:
                raise ConfigurationError("ACL permissions could not be inspected")
            if permission_mask.value & permissions_to_reject:
                return True
    finally:
        acl_free(acl)


def _extended_acl_allows_mutation(descriptor: int) -> bool:
    return _extended_acl_allows(descriptor, ACL_MUTATION_MASK)


def _validate_directory(descriptor: int) -> os.stat_result:
    directory_stat = os.fstat(descriptor)
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise ConfigurationError("config path component is not a directory")
    if directory_stat.st_uid not in {0, os.getuid()}:
        raise ConfigurationError("config path component has an unexpected owner")
    if stat.S_IMODE(directory_stat.st_mode) & (stat.S_IWGRP | stat.S_IWOTH):
        raise ConfigurationError("config path component is writable by another user")
    if _extended_acl_allows_mutation(descriptor):
        raise ConfigurationError("config path component has a mutating ACL")
    return directory_stat


def _validate_private_file(descriptor: int, *, label: str = "config.toml") -> os.stat_result:
    file_stat = os.fstat(descriptor)
    if not stat.S_ISREG(file_stat.st_mode):
        raise ConfigurationError(f"{label} is not a regular file")
    if file_stat.st_uid != os.getuid():
        raise ConfigurationError(f"{label} owner is not the current user")
    if stat.S_IMODE(file_stat.st_mode) & ~0o600:
        raise ConfigurationError(f"{label} has permissions outside 0600")
    if _extended_acl_allows(descriptor, ACL_READ_DATA | ACL_MUTATION_MASK):
        raise ConfigurationError(f"{label} has an unsafe ACL")
    return file_stat


def _open_validated_parent(path: Path) -> int:
    """親ディレクトリをsymlink非追従で開き、更新先をFDへ固定する。"""
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise ConfigurationError("config path is not an absolute file path")

    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        _validate_directory(descriptor)
        for component in path.parent.parts[1:]:
            next_descriptor = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
            _validate_directory(descriptor)
        return descriptor
    except (OSError, ConfigurationError) as error:
        os.close(descriptor)
        if isinstance(error, ConfigurationError):
            raise
        raise ConfigurationError("config directory could not be opened safely") from error


def _read_all(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _snapshot(file_stat: os.stat_result) -> tuple[int, ...]:
    """内容・metadataの競合を検知するためのstat snapshot。"""
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_mtime_ns,
        file_stat.st_ctime_ns,
        file_stat.st_size,
        file_stat.st_uid,
        file_stat.st_gid,
        stat.S_IMODE(file_stat.st_mode),
        getattr(file_stat, "st_flags", 0),
    )


def _preserved_metadata(file_stat: os.stat_result) -> tuple[int, ...]:
    return (
        file_stat.st_uid,
        file_stat.st_gid,
        stat.S_IMODE(file_stat.st_mode),
        getattr(file_stat, "st_flags", 0),
    )


def _copy_extended_metadata(source: int, destination: int) -> None:
    """owner、group、mode、flags、ACL、拡張属性を開いたFD間で複製する。"""
    source_stat = os.fstat(source)
    if sys.platform == "darwin":
        library_name = ctypes.util.find_library("System")
        if library_name is None:
            raise OSError("libSystem is unavailable")
        library = ctypes.CDLL(library_name, use_errno=True)
        fcopyfile = library.fcopyfile
        fcopyfile.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        fcopyfile.restype = ctypes.c_int
        # COPYFILE_STATはmtimeも復元するため、ACLとXATTRだけをcopyfileへ委ねる。
        if fcopyfile(source, destination, None, 0x5) != 0:
            error_number = ctypes.get_errno()
            raise OSError(error_number, os.strerror(error_number))
    elif hasattr(os, "listxattr"):
        for name in os.listxattr(source):
            os.setxattr(destination, name, os.getxattr(source, name))

    os.fchown(destination, source_stat.st_uid, source_stat.st_gid)
    os.fchmod(destination, stat.S_IMODE(source_stat.st_mode))
    if hasattr(os, "fchflags"):
        os.fchflags(destination, getattr(source_stat, "st_flags", 0))

    destination_stat = os.fstat(destination)
    source_metadata = (
        source_stat.st_uid,
        source_stat.st_gid,
        stat.S_IMODE(source_stat.st_mode),
        getattr(source_stat, "st_flags", 0),
    )
    destination_metadata = (
        destination_stat.st_uid,
        destination_stat.st_gid,
        stat.S_IMODE(destination_stat.st_mode),
        getattr(destination_stat, "st_flags", 0),
    )
    if destination_metadata != source_metadata:
        raise OSError("config metadata could not be preserved")


def _temporary_file(parent_descriptor: int, name: str) -> tuple[int, str]:
    for _ in range(128):
        temporary_name = f".{name}.{secrets.token_hex(8)}.tmp"
        try:
            descriptor = os.open(
                temporary_name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_descriptor,
            )
            return descriptor, temporary_name
        except FileExistsError:
            continue
    raise OSError(errno.EEXIST, "temporary filename attempts exhausted")


@dataclass
class LockedConfig:
    parent_descriptor: int
    name: str
    source_descriptor: int | None
    original: bytes | None
    original_stat: os.stat_result | None

    @property
    def exists(self) -> bool:
        return self.source_descriptor is not None

    def _assert_unchanged(self) -> None:
        if self.source_descriptor is None or self.original is None or self.original_stat is None:
            raise ConfigurationError("config.toml did not exist at transaction start")
        _validate_private_file(self.source_descriptor)
        if _snapshot(os.fstat(self.source_descriptor)) != _snapshot(self.original_stat):
            raise ConfigurationError("config.toml metadata changed during setup")

        current_descriptor: int | None = None
        try:
            current_descriptor = os.open(
                self.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.parent_descriptor
            )
            current_stat = _validate_private_file(current_descriptor)
            if (
                _snapshot(current_stat) != _snapshot(self.original_stat)
                or _read_all(current_descriptor) != self.original
            ):
                raise ConfigurationError("config.toml changed during setup")
        except FileNotFoundError as error:
            raise ConfigurationError("config.toml changed during setup") from error
        finally:
            if current_descriptor is not None:
                os.close(current_descriptor)

    def replace(self, content: bytes) -> None:
        if self.source_descriptor is None or self.original_stat is None:
            raise ConfigurationError("config.toml did not exist at transaction start")
        temporary_name: str | None = None
        temporary_descriptor: int | None = None
        try:
            self._assert_unchanged()
            temporary_descriptor, temporary_name = _temporary_file(
                self.parent_descriptor, self.name
            )
            _validate_private_file(temporary_descriptor, label="temporary config")
            with os.fdopen(temporary_descriptor, "wb", closefd=False) as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
            os.fsync(temporary_descriptor)
            _copy_extended_metadata(self.source_descriptor, temporary_descriptor)
            os.fsync(temporary_descriptor)

            # copy中にsource metadataが変わった場合も、危険な状態を複製せず停止する。
            self._assert_unchanged()
            temporary_stat = _validate_private_file(temporary_descriptor, label="temporary config")
            expected_metadata = (
                self.original_stat.st_uid,
                self.original_stat.st_gid,
                stat.S_IMODE(self.original_stat.st_mode),
                getattr(self.original_stat, "st_flags", 0),
            )
            actual_metadata = (
                temporary_stat.st_uid,
                temporary_stat.st_gid,
                stat.S_IMODE(temporary_stat.st_mode),
                getattr(temporary_stat, "st_flags", 0),
            )
            if actual_metadata != expected_metadata:
                raise ConfigurationError("temporary config metadata differs from source")

            # 同じlockを使うconfig mutatorの間では、この確認からrenameまで競合しない。
            self._assert_unchanged()
            os.rename(
                temporary_name,
                self.name,
                src_dir_fd=self.parent_descriptor,
                dst_dir_fd=self.parent_descriptor,
            )
            temporary_name = None
            os.fsync(self.parent_descriptor)
        except ConfigurationError:
            raise
        except OSError as error:
            raise ConfigurationError("config.toml could not be written safely") from error
        finally:
            if temporary_descriptor is not None:
                os.close(temporary_descriptor)
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name, dir_fd=self.parent_descriptor)
                except FileNotFoundError:
                    pass

    def create(self, content: bytes) -> None:
        if self.exists:
            raise ConfigurationError("config.toml already existed at transaction start")
        temporary_descriptor: int | None = None
        temporary_name: str | None = None
        try:
            temporary_descriptor, temporary_name = _temporary_file(
                self.parent_descriptor, self.name
            )
            initial_stat = _validate_private_file(
                temporary_descriptor, label="temporary config"
            )
            with os.fdopen(temporary_descriptor, "wb", closefd=False) as config_file:
                config_file.write(content)
                config_file.flush()
            os.fsync(temporary_descriptor)
            final_stat = _validate_private_file(
                temporary_descriptor, label="temporary config"
            )
            if _preserved_metadata(final_stat) != _preserved_metadata(initial_stat):
                raise ConfigurationError("temporary config metadata changed during setup")
            os.link(
                temporary_name,
                self.name,
                src_dir_fd=self.parent_descriptor,
                dst_dir_fd=self.parent_descriptor,
                follow_symlinks=False,
            )
            os.unlink(temporary_name, dir_fd=self.parent_descriptor)
            temporary_name = None
            os.fsync(self.parent_descriptor)
        except ConfigurationError:
            raise
        except OSError as error:
            raise ConfigurationError("config.toml could not be created safely") from error
        finally:
            if temporary_descriptor is not None:
                os.close(temporary_descriptor)
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name, dir_fd=self.parent_descriptor)
                except FileNotFoundError:
                    pass


@contextmanager
def locked_config(path: Path | str, *, allow_missing: bool) -> Iterator[LockedConfig]:
    """共通lock下でconfigをFDへ固定し、transaction終了まで保持する。"""
    config = Path(path)
    parent_descriptor: int | None = None
    lock_descriptor: int | None = None
    source_descriptor: int | None = None
    try:
        parent_descriptor = _open_validated_parent(config)
        lock_name = f".{config.name}.lock"
        lock_descriptor = os.open(
            lock_name,
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_descriptor,
        )
        _validate_private_file(lock_descriptor, label="config lock")
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)

        try:
            source_descriptor = os.open(
                config.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_descriptor
            )
        except FileNotFoundError:
            if not allow_missing:
                raise ConfigurationError("config.toml changed during setup")
            yield LockedConfig(parent_descriptor, config.name, None, None, None)
            return

        original_stat = _validate_private_file(source_descriptor)
        original = _read_all(source_descriptor)
        yield LockedConfig(
            parent_descriptor,
            config.name,
            source_descriptor,
            original,
            original_stat,
        )
    except ConfigurationError:
        raise
    except OSError as error:
        raise ConfigurationError("config.toml could not be opened safely") from error
    finally:
        if source_descriptor is not None:
            os.close(source_descriptor)
        if lock_descriptor is not None:
            os.close(lock_descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)
