#!/usr/bin/env python3
"""モデル間handoff Markdownの完全性とGit鮮度を検証する。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


RepoLocation = Path | int


MODEL_REASONING_EFFORTS = {
    "gpt-6-astra": {"low", "medium", "high", "xhigh", "max", "ultra"},
    "gpt-5.6-sol": {"low", "medium", "high", "xhigh", "max", "ultra"},
    "gpt-5.6-terra": {"low", "medium", "high", "xhigh", "max", "ultra"},
    "gpt-5.6-luna": {"low", "medium", "high", "xhigh", "max"},
    "gpt-5.5": {"low", "medium", "high", "xhigh"},
}
VALID_MODELS = set(MODEL_REASONING_EFFORTS)
VALID_REASONING_EFFORTS = set().union(*MODEL_REASONING_EFFORTS.values())
REQUIRED_FIELDS = (
    "handoff_schema",
    "task_id",
    "branch",
    "head",
    "worktree_fingerprint",
    "target_model",
    "target_reasoning_effort",
    "requirements_path",
    "requirements_sha256",
    "review_package_path",
    "review_package_sha256",
)
REQUIRED_SECTIONS = (
    "目的と対象外",
    "Git状態",
    "確定済み設計判断と根拠",
    "対象ファイルと作業所有範囲",
    "受入条件と検証コマンド",
    "制約",
    "未解決事項",
    "実行モデル",
    "返却レポート契約",
)
SHA256_RE = re.compile(r"[0-9a-f]{64}")
HEAD_RE = re.compile(r"[0-9a-f]{40,64}")
TASK_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class HandoffError(ValueError):
    """handoffを安全に受け取れない。"""


class RepoEntryMissing(HandoffError):
    """repository entryが安全なopen中に存在しない。"""


def open_directory_path(path: Path) -> int:
    """安定した起点FDからsymlinkを辿らずdirectory pathを開く。"""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    anchor = path.anchor or "."
    components = path.parts[1:] if path.anchor else path.parts
    descriptor = os.open(anchor, flags)
    try:
        for component in components:
            next_descriptor = os.open(
                component, flags, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def run_git(
    repo: RepoLocation, *arguments: str, pin_work_tree: bool = True
) -> bytes:
    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith("GIT_"):
            env.pop(key)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env.pop("GIT_EXTERNAL_DIFF", None)
    subprocess_options: dict[str, object] = {}
    if isinstance(repo, int):
        # submoduleのcore.worktreeが元の文字列pathへ戻るのを防ぎ、
        # fchdirした開済みdirectory inodeをworktreeとして固定する。
        if pin_work_tree:
            env["GIT_WORK_TREE"] = "."
        subprocess_options["pass_fds"] = (repo,)
        subprocess_options["preexec_fn"] = lambda: os.fchdir(repo)
    else:
        subprocess_options["cwd"] = repo
    result = subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "-c",
            "core.fsmonitor=false",
            *arguments,
        ],
        env=env,
        capture_output=True,
        check=False,
        **subprocess_options,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise HandoffError(f"git {' '.join(arguments)} failed: {detail}")
    return result.stdout


@contextmanager
def repository_root(path: Path) -> Iterator[tuple[Path, int]]:
    """--repoをGit実行前からFDへ固定し、処理終了まで同じinodeを保持する。"""
    requested_descriptor: int | None = None
    root_descriptor: int | None = None
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        requested_descriptor = open_directory_path(path)
        requested_path = Path(os.path.abspath(path))
        root = Path(
            run_git(
                requested_descriptor,
                "rev-parse",
                "--show-toplevel",
                pin_work_tree=False,
            )
            .decode()
            .strip()
        )
        root_descriptor = os.open(root, flags)
        requested_stat = os.fstat(requested_descriptor)
        root_stat = os.fstat(root_descriptor)
        if (requested_stat.st_dev, requested_stat.st_ino) != (
            root_stat.st_dev,
            root_stat.st_ino,
        ):
            raise HandoffError("repository root does not match --repo")
        yield requested_path, requested_descriptor
    except OSError as error:
        raise HandoffError("repository root could not be opened safely") from error
    finally:
        if root_descriptor is not None:
            os.close(root_descriptor)
        if requested_descriptor is not None:
            os.close(requested_descriptor)


def repo_relative_path(
    repo: RepoLocation,
    value: str,
    label: str,
    repo_path: Path | None = None,
) -> Path:
    """repositoryを基準に、安全にopenatできる相対pathへ正規化する。"""
    candidate = Path(value)
    if candidate.is_absolute():
        lexical_root = repo_path if isinstance(repo, int) else repo
        if lexical_root is None:
            raise HandoffError(f"{label} must stay inside repository: {value}")
        try:
            relative = candidate.relative_to(lexical_root)
        except ValueError as error:
            raise HandoffError(f"{label} must stay inside repository: {value}") from error
    else:
        relative = candidate
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise HandoffError(f"{label} must stay inside repository: {value}")
    return Path(*relative.parts)


@contextmanager
def open_repo_parent(
    repo: RepoLocation, relative: Path, label: str
) -> Iterator[tuple[int, str]]:
    """rootから各directoryをO_NOFOLLOWで固定し、親FDとbasenameを返す。"""
    descriptors: list[int] = []
    try:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptors.append(
            os.dup(repo) if isinstance(repo, int) else os.open(repo, directory_flags)
        )
        for component in relative.parts[:-1]:
            descriptors.append(
                os.open(component, directory_flags, dir_fd=descriptors[-1])
            )
        yield descriptors[-1], relative.parts[-1]
    except FileNotFoundError as error:
        raise RepoEntryMissing(f"{label} does not exist: {relative}") from error
    except OSError as error:
        raise HandoffError(
            f"{label} must use non-symlink repository directories: {relative}"
        ) from error
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


@contextmanager
def open_repo_directory(
    repo: RepoLocation, relative: Path, label: str
) -> Iterator[int]:
    """root FDからdirectoryを開き、path差し替え後も同じinodeへ束縛する。"""
    descriptor: int | None = None
    try:
        with open_repo_parent(repo, relative, label) as (parent, name):
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent,
            )
            yield descriptor
    except FileNotFoundError as error:
        raise RepoEntryMissing(f"{label} does not exist: {relative}") from error
    except OSError as error:
        raise HandoffError(
            f"{label} must be a non-symlink repository directory: {relative}"
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def read_descriptor(descriptor: int) -> bytes:
    chunks = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def read_safe_repo_file(
    repo: RepoLocation,
    value: str,
    label: str,
    repo_path: Path | None = None,
) -> tuple[Path, bytes]:
    """repository内の非symlink通常ファイルをopenatでFD固定して読む。"""
    relative = repo_relative_path(repo, value, label, repo_path)
    descriptor: int | None = None
    try:
        with open_repo_parent(repo, relative, label) as (parent, name):
            descriptor = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent
            )
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise HandoffError(
                    f"{label} must be a regular non-symlink file: {value}"
                )
            return relative, read_descriptor(descriptor)
    except OSError as error:
        raise HandoffError(
            f"{label} must be a readable regular non-symlink file: {value}"
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def hash_worktree_entry(
    repo: RepoLocation, relative_bytes: bytes, digest: "hashlib._Hash"
) -> None:
    """tracked/untracked entryをGitのcontent filterを通さず生bytesでhashする。"""
    decoded = os.fsdecode(relative_bytes)
    relative = repo_relative_path(repo, decoded, "worktree entry")
    digest.update(b"\0path\0" + relative_bytes + b"\0")
    descriptor: int | None = None
    try:
        with open_repo_parent(repo, relative, "worktree entry") as (parent, name):
            try:
                metadata = os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                digest.update(b"missing\0")
                return
            digest.update(f"mode:{metadata.st_mode & 0o177777:o}\0".encode())
            if stat.S_ISLNK(metadata.st_mode):
                digest.update(b"symlink\0" + os.fsencode(os.readlink(name, dir_fd=parent)))
            elif stat.S_ISREG(metadata.st_mode):
                descriptor = os.open(
                    name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent
                )
                current = os.fstat(descriptor)
                if not stat.S_ISREG(current.st_mode):
                    raise HandoffError(
                        f"worktree entry changed type while reading: {decoded}"
                    )
                digest.update(b"file\0" + read_descriptor(descriptor))
            else:
                digest.update(f"special:{stat.S_IFMT(metadata.st_mode):o}".encode())
    except RepoEntryMissing:
        digest.update(b"missing\0")
    except OSError as error:
        raise HandoffError(f"worktree entry could not be read safely: {decoded}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def parse_index_entries(repo: RepoLocation) -> list[tuple[bytes, bytes, bytes, bytes]]:
    entries = []
    for entry in (item for item in run_git(repo, "ls-files", "--stage", "-z").split(b"\0") if item):
        metadata, separator, relative = entry.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3:
            raise HandoffError("git index entry has an invalid format")
        mode, object_id, stage = fields
        if stage != b"0":
            raise HandoffError(f"git index is conflicted: {os.fsdecode(relative)}")
        entries.append((mode, object_id, stage, relative))
    return entries


def is_handoff_path(relative: bytes) -> bool:
    return relative.startswith(b".superpowers/handoffs/")


def parse_head_tree_entries(repo: RepoLocation) -> list[tuple[bytes, bytes, bytes]]:
    entries = []
    output = run_git(repo, "ls-tree", "-r", "-z", "--full-tree", "HEAD")
    for entry in (item for item in output.split(b"\0") if item):
        metadata, separator, relative = entry.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3:
            raise HandoffError("git HEAD tree entry has an invalid format")
        mode, _object_type, object_id = fields
        entries.append((mode, object_id, relative))
    return entries


def raw_worktree_blob(repo: RepoLocation, relative_bytes: bytes) -> tuple[bytes, bytes]:
    """filterを通さずworktree entryのGit modeとblob payloadを返す。"""
    decoded = os.fsdecode(relative_bytes)
    relative = repo_relative_path(repo, decoded, "submodule worktree entry")
    descriptor: int | None = None
    try:
        with open_repo_parent(repo, relative, "submodule worktree entry") as (
            parent,
            name,
        ):
            metadata = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                return b"120000", os.fsencode(os.readlink(name, dir_fd=parent))
            if not stat.S_ISREG(metadata.st_mode):
                raise HandoffError(
                    f"submodule worktree entry has an unsupported type: {decoded}"
                )
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            mode = b"100755" if metadata.st_mode & 0o111 else b"100644"
            return mode, read_descriptor(descriptor)
    except OSError as error:
        raise HandoffError(
            f"submodule worktree entry could not be read safely: {decoded}"
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def git_blob_id(payload: bytes, hex_length: int) -> bytes:
    if hex_length == 40:
        algorithm = hashlib.sha1
    elif hex_length == 64:
        algorithm = hashlib.sha256
    else:
        raise HandoffError(f"unsupported Git object id length: {hex_length}")
    digest = algorithm()
    digest.update(f"blob {len(payload)}\0".encode() + payload)
    return digest.hexdigest().encode()


def require_clean_submodule(repo: RepoLocation, relative: bytes) -> bytes:
    """repository commandを起動せず、HEAD/index/worktreeの一致を検査する。"""
    entries = parse_index_entries(repo)
    index_manifest = [(mode, object_id, path) for mode, object_id, _stage, path in entries]
    if index_manifest != parse_head_tree_entries(repo):
        raise HandoffError(
            f"submodule worktree is dirty: {os.fsdecode(relative)}"
        )
    untracked = run_git(
        repo, "ls-files", "--others", "--exclude-standard", "-z"
    )
    if untracked:
        raise HandoffError(
            f"submodule worktree is dirty: {os.fsdecode(relative)}"
        )
    for mode, object_id, _stage, path in entries:
        if mode == b"160000":
            try:
                with open_repo_directory(
                    repo, Path(os.fsdecode(path)), "nested submodule"
                ) as nested:
                    nested_head = require_clean_submodule(
                        nested, relative + b"/" + path
                    )
            except RepoEntryMissing:
                raise HandoffError(
                    f"submodule worktree is dirty: {os.fsdecode(relative)}"
                )
            if nested_head != object_id:
                raise HandoffError(
                    f"submodule worktree is dirty: {os.fsdecode(relative)}"
                )
            continue
        actual_mode, payload = raw_worktree_blob(repo, path)
        if actual_mode != mode or git_blob_id(payload, len(object_id)) != object_id:
            raise HandoffError(
                f"submodule worktree is dirty: {os.fsdecode(relative)}"
            )
    return run_git(repo, "rev-parse", "HEAD").strip()


def hash_clean_submodules(
    repo: RepoLocation,
    entries: list[tuple[bytes, bytes, bytes, bytes]],
    digest: "hashlib._Hash",
) -> set[bytes]:
    """cleanなsubmoduleの実HEADをhashし、内部変更は推測せず拒否する。"""
    submodules = set()
    for mode, _object_id, _stage, relative in entries:
        if mode != b"160000":
            continue
        submodules.add(relative)
        try:
            with open_repo_directory(
                repo, Path(os.fsdecode(relative)), "submodule path"
            ) as submodule:
                head = require_clean_submodule(submodule, relative)
        except RepoEntryMissing:
            digest.update(b"\0submodule-uninitialized\0" + relative + b"\0")
            continue
        digest.update(b"\0submodule\0" + relative + b"\0" + head + b"\0")
    return submodules


def worktree_fingerprint(repo: RepoLocation) -> str:
    digest = hashlib.sha256()
    handoff_exclude = " :(exclude).superpowers/handoffs/**".strip()
    entries = [entry for entry in parse_index_entries(repo) if not is_handoff_path(entry[3])]
    submodules = hash_clean_submodules(repo, entries, digest)
    for mode, object_id, stage, relative in entries:
        digest.update(
            b"\0index\0"
            + mode
            + b" "
            + object_id
            + b" "
            + stage
            + b"\t"
            + relative
            + b"\0"
        )
        if relative not in submodules:
            hash_worktree_entry(repo, relative, digest)
    untracked = run_git(
        repo,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
        ".",
        handoff_exclude,
    )
    for relative in sorted(path for path in untracked.split(b"\0") if path):
        hash_worktree_entry(repo, relative, digest)
    return digest.hexdigest()


def current_state(repo: RepoLocation) -> dict[str, str]:
    if isinstance(repo, Path):
        with repository_root(repo) as (_root_path, root_descriptor):
            return current_state(root_descriptor)
    branch = run_git(repo, "branch", "--show-current").decode().strip() or "DETACHED"
    head = run_git(repo, "rev-parse", "HEAD").decode().strip()
    return {
        "branch": branch,
        "head": head,
        "worktree_fingerprint": worktree_fingerprint(repo),
    }


def parse_handoff(content: bytes) -> tuple[dict[str, str], str]:
    text = content.decode("utf-8")
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if match is None:
        raise HandoffError("YAML-like frontmatter is missing")
    metadata: dict[str, str] = {}
    for line_number, line in enumerate(match.group(1).splitlines(), 2):
        if ":" not in line:
            raise HandoffError(f"frontmatter line {line_number} is not key: value")
        key, value = (part.strip() for part in line.split(":", 1))
        if not key or not value:
            raise HandoffError(f"frontmatter line {line_number} is empty")
        if key in metadata:
            raise HandoffError(f"frontmatter field is duplicated: {key}")
        metadata[key] = value
    return metadata, match.group(2)


def validate_sections(body: str) -> list[str]:
    errors = []
    for heading in REQUIRED_SECTIONS:
        match = re.search(
            rf"^## {re.escape(heading)}[ \t]*$\n(.*?)(?=^## |\Z)",
            body,
            re.MULTILINE | re.DOTALL,
        )
        if match is None:
            errors.append(f"required section is missing: {heading}")
        elif not match.group(1).strip():
            errors.append(f"required section is empty: {heading}")
    return errors


def validate_handoff(
    handoff: Path,
    repo: RepoLocation,
    repo_path: Path,
    expected_model: str | None,
    expected_effort: str | None,
    expected_input_digest: str | None,
) -> tuple[list[str], str, dict[str, bytes]]:
    errors: list[str] = []
    input_digest = hashlib.sha256()
    documents: dict[str, bytes] = {}
    try:
        path, handoff_content = read_safe_repo_file(
            repo, str(handoff), "handoff", repo_path
        )
        documents["handoff"] = handoff_content
        input_digest.update(b"handoff\0" + os.fsencode(path) + b"\0")
        input_digest.update(handoff_content)
        metadata, body = parse_handoff(handoff_content)
    except (HandoffError, OSError, UnicodeError) as error:
        return [str(error)], input_digest.hexdigest(), documents

    for field in REQUIRED_FIELDS:
        if not metadata.get(field, "").strip():
            errors.append(f"required frontmatter field is missing or empty: {field}")
    errors.extend(validate_sections(body))
    if errors:
        return errors, input_digest.hexdigest(), documents

    if metadata["handoff_schema"] != "1":
        errors.append("handoff_schema must be 1")
    if TASK_ID_RE.fullmatch(metadata["task_id"]) is None:
        errors.append("task_id has an invalid format")
    if HEAD_RE.fullmatch(metadata["head"]) is None:
        errors.append("head must be a full hexadecimal commit id")
    if SHA256_RE.fullmatch(metadata["worktree_fingerprint"]) is None:
        errors.append("worktree_fingerprint must be a SHA-256 digest")
    if metadata["target_model"] not in VALID_MODELS:
        errors.append(f"unknown target_model: {metadata['target_model']}")
    if metadata["target_reasoning_effort"] not in VALID_REASONING_EFFORTS:
        errors.append(
            "unknown target_reasoning_effort: "
            f"{metadata['target_reasoning_effort']}"
        )
    elif (
        metadata["target_model"] in MODEL_REASONING_EFFORTS
        and metadata["target_reasoning_effort"]
        not in MODEL_REASONING_EFFORTS[metadata["target_model"]]
    ):
        errors.append(
            "unsupported model/reasoning pair: "
            f"{metadata['target_model']}+{metadata['target_reasoning_effort']}"
        )
    if (expected_model is None) != (expected_effort is None):
        errors.append("expected model and reasoning effort must be supplied together")
    elif expected_model is not None and (
        metadata["target_model"], metadata["target_reasoning_effort"]
    ) != (expected_model, expected_effort):
        errors.append(
            "expected model/reasoning pair does not match handoff: "
            f"expected {expected_model}+{expected_effort}, got "
            f"{metadata['target_model']}+{metadata['target_reasoning_effort']}"
        )

    for path_field, hash_field in (
        ("requirements_path", "requirements_sha256"),
        ("review_package_path", "review_package_sha256"),
    ):
        referenced_path = metadata[path_field]
        referenced_hash = metadata[hash_field]
        if (referenced_path, referenced_hash) == ("none", "none"):
            continue
        if "none" in (referenced_path, referenced_hash):
            errors.append(f"{path_field} and {hash_field} must both be none or set")
            continue
        if SHA256_RE.fullmatch(referenced_hash) is None:
            errors.append(f"{hash_field} must be a SHA-256 digest")
            continue
        try:
            referenced, referenced_content = read_safe_repo_file(
                repo, referenced_path, path_field, repo_path
            )
            input_digest.update(
                b"reference\0"
                + path_field.encode()
                + b"\0"
                + os.fsencode(referenced)
                + b"\0"
            )
            input_digest.update(referenced_content)
            document_name = (
                "requirements"
                if path_field == "requirements_path"
                else "review-package"
            )
            documents[document_name] = referenced_content
            actual = hashlib.sha256(referenced_content).hexdigest()
            if actual != referenced_hash:
                errors.append(f"{hash_field} does not match referenced file")
        except (HandoffError, OSError) as error:
            errors.append(str(error))

    try:
        state = current_state(repo)
        for field in ("branch", "head", "worktree_fingerprint"):
            if metadata[field] != state[field]:
                errors.append(
                    f"{field} is stale: handoff={metadata[field]} current={state[field]}"
                )
    except HandoffError as error:
        errors.append(str(error))

    actual_input_digest = input_digest.hexdigest()
    if expected_input_digest is not None:
        if SHA256_RE.fullmatch(expected_input_digest) is None:
            errors.append("expected input digest must be a SHA-256 digest")
        elif expected_input_digest != actual_input_digest:
            errors.append("input digest changed before validated read")
    return errors, actual_input_digest, documents


def document_chunk(
    documents: dict[str, bytes],
    document: str,
    start_line: int,
    line_count: int,
) -> tuple[bytes, str]:
    """検証済みbytesから1始まりの行範囲を返す。"""
    if document not in documents:
        raise HandoffError(f"requested document is not present: {document}")
    if start_line < 1 or line_count < 1:
        raise HandoffError("start-line and line-count must be positive")
    lines = documents[document].splitlines(keepends=True)
    total = len(lines)
    if start_line > max(total, 1):
        raise HandoffError(
            f"start-line exceeds document length: {start_line} > {total}"
        )
    end_line = min(total, start_line + line_count - 1)
    content = b"".join(lines[start_line - 1 : end_line])
    return content, f"DOCUMENT: {document} lines {start_line}-{end_line} of {total}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    state_parser = subparsers.add_parser("state", help="現在のGit識別子をJSONで出力する")
    state_parser.add_argument("--repo", type=Path, default=Path.cwd())
    validate_parser = subparsers.add_parser("validate", help="handoffを検証する")
    validate_parser.add_argument("handoff", type=Path)
    validate_parser.add_argument("--repo", type=Path, default=Path.cwd())
    validate_parser.add_argument("--expected-model")
    validate_parser.add_argument("--expected-reasoning-effort")
    validate_parser.add_argument("--expected-input-digest")
    read_parser = subparsers.add_parser(
        "read", help="検証済みhandoff入力をdigest固定で読み出す"
    )
    read_parser.add_argument("handoff", type=Path)
    read_parser.add_argument("--repo", type=Path, default=Path.cwd())
    read_parser.add_argument("--expected-model")
    read_parser.add_argument("--expected-reasoning-effort")
    read_parser.add_argument("--expected-input-digest", required=True)
    read_parser.add_argument(
        "--document",
        required=True,
        choices=("handoff", "requirements", "review-package"),
    )
    read_parser.add_argument("--start-line", type=int, default=1)
    read_parser.add_argument("--line-count", type=int, default=400)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    try:
        with repository_root(arguments.repo) as (repo_path, repo):
            if arguments.command == "state":
                print(json.dumps(current_state(repo), sort_keys=True))
                return 0
            errors, input_digest, documents = validate_handoff(
                arguments.handoff,
                repo,
                repo_path,
                arguments.expected_model,
                arguments.expected_reasoning_effort,
                arguments.expected_input_digest,
            )
    except (HandoffError, OSError) as error:
        errors = [str(error)]
    if errors:
        for error in errors:
            print(f"NEEDS_CONTEXT: {error}", file=sys.stderr)
        return 2
    if arguments.command == "read":
        try:
            content, header = document_chunk(
                documents,
                arguments.document,
                arguments.start_line,
                arguments.line_count,
            )
        except HandoffError as error:
            print(f"NEEDS_CONTEXT: {error}", file=sys.stderr)
            return 2
        sys.stdout.buffer.write(header.encode() + b"\n" + content)
        return 0
    print("VALID: cross-model handoff is complete and current")
    print(f"INPUT_DIGEST: {input_digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
