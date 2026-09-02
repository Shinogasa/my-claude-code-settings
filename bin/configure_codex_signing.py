#!/usr/bin/env python3
"""Codex の shell_environment_policy へ Bitwarden SSH agent を設定する。"""

from __future__ import annotations

import argparse
import copy
import json
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path


SKIPPED_EXIT = 10
BITWARDEN_SOCKET_RELATIVE = Path(
    "Library/Containers/com.bitwarden.desktop/Data/.bitwarden-ssh-agent.sock"
)
TARGET_TABLE = ("shell_environment_policy", "set")
TARGET_KEY = "SSH_AUTH_SOCK"
_TABLE_LINE = re.compile(
    r"^[ \t]*(?P<open>\[\[?)(?P<body>.*?)(?P<close>\]\]?)[ \t]*(?:#.*)?(?:\r?\n)?$"
)
_ASSIGNMENT = re.compile(
    r"^(?P<prefix>[ \t]*)(?P<key>\"(?:[^\"\\]|\\.)*\"|'(?:[^']|'')*'|[A-Za-z0-9_-]+)"
    r"(?P<separator>[ \t]*=[ \t]*)(?P<rhs>.*)$"
)


class ConfigurationError(Exception):
    """設定を安全に更新できない場合の内部エラー。"""


@dataclass(frozen=True)
class Outcome:
    """設定処理の結果。reason はログへ出さず、表示文の選択にだけ使う。"""

    kind: str
    reason: str | None = None


def discover_socket(home: Path | str | None = None, *, system: str | None = None) -> Path | None:
    """Bitwarden Desktop のホスト別 socket を HOME 基準で導出する。"""

    if (system or platform.system()) != "Darwin":
        return None
    home_value = os.environ.get("HOME", "") if home is None else str(home)
    home_path = Path(home_value)
    if not home_path.is_absolute():
        return None
    return home_path / BITWARDEN_SOCKET_RELATIVE


def _probe_agent(socket_path: Path) -> bool:
    """socket の存在だけで成功にせず、ssh-add で鍵一覧取得を確認する。"""

    try:
        if not socket_path.is_socket():
            return False
    except OSError:
        return False

    environment = os.environ.copy()
    environment["SSH_AUTH_SOCK"] = str(socket_path)
    try:
        result = subprocess.run(
            ["ssh-add", "-l"],
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _line_parts(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    return line, ""


def _table_path_from_body(body: str) -> tuple[str, ...] | None:
    """TOML の表記ゆれを parser に解釈させて semantic path を得る。"""

    try:
        parsed = tomllib.loads(f"[{body}]\n__codex_marker = true\n")
    except (tomllib.TOMLDecodeError, ValueError):
        return None

    paths: list[tuple[str, ...]] = []

    def walk(value: object, prefix: tuple[str, ...] = ()) -> None:
        if not isinstance(value, dict):
            return
        for key, child in value.items():
            path = prefix + (key,)
            if key == "__codex_marker" and child is True:
                paths.append(prefix)
            else:
                walk(child, path)

    walk(parsed)
    return paths[0] if len(paths) == 1 else None


def _table_path(line: str) -> tuple[str, ...] | None:
    body, _ = _line_parts(line)
    match = _TABLE_LINE.fullmatch(body)
    if match is None or match.group("open") != "[" or match.group("close") != "]":
        return None
    return _table_path_from_body(match.group("body").strip())


def _is_table_boundary(line: str) -> bool:
    body, _ = _line_parts(line)
    stripped = body.lstrip(" \t")
    if not stripped.startswith("["):
        return False
    match = _TABLE_LINE.fullmatch(body)
    return match is not None and match.group("open") in {"[", "[["}


def _decode_key(key: str) -> str | None:
    if key.startswith('"'):
        try:
            value = json.loads(key)
        except (json.JSONDecodeError, TypeError):
            return None
        return value if isinstance(value, str) else None
    if key.startswith("'"):
        return key[1:-1].replace("''", "'")
    return key


def _find_unquoted_comment(value: str) -> int | None:
    quote: str | None = None
    escaped = False
    for index, character in enumerate(value):
        if quote == '"':
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quote = None
        elif quote == "'":
            if character == "'":
                quote = None
        elif character in {'"', "'"}:
            quote = character
        elif character == "#":
            return index
    return None


def _toml_string(value: str) -> str:
    if any(character in value for character in "\r\n\x00"):
        raise ConfigurationError("socket path contains a line break")
    return json.dumps(value, ensure_ascii=False)


def _rewrite_assignment(line: str, socket_path: str) -> str:
    body, newline = _line_parts(line)
    match = _ASSIGNMENT.fullmatch(body)
    if match is None:
        raise ConfigurationError("target assignment could not be parsed")
    rhs = match.group("rhs")
    if "\"\"\"" in rhs or "'''" in rhs:
        raise ConfigurationError("multiline target assignment is not rewritten")
    comment_index = _find_unquoted_comment(rhs)
    if comment_index is None:
        suffix = rhs[len(rhs.rstrip(" \t")) :]
    else:
        before_comment = rhs[:comment_index]
        suffix = before_comment[len(before_comment.rstrip(" \t")) :] + rhs[comment_index:]
    return (
        match.group("prefix")
        + match.group("key")
        + match.group("separator")
        + _toml_string(socket_path)
        + suffix
        + newline
    )


def _expected_document(document: object, socket_path: str) -> dict[str, object]:
    if not isinstance(document, dict):
        raise ConfigurationError("config document is not a table")
    expected = copy.deepcopy(document)
    policy = expected.setdefault("shell_environment_policy", {})
    if not isinstance(policy, dict):
        raise ConfigurationError("shell_environment_policy is not a table")
    policy_set = policy.setdefault("set", {})
    if not isinstance(policy_set, dict):
        raise ConfigurationError("shell_environment_policy.set is not a table")
    policy_set[TARGET_KEY] = socket_path
    return expected


def _patched_text(text: str, document: dict[str, object], socket_path: str) -> str:
    lines = text.splitlines(keepends=True)
    target_headers = [index for index, line in enumerate(lines) if _table_path(line) == TARGET_TABLE]
    if len(target_headers) > 1:
        raise ConfigurationError("target table is duplicated")

    expected = _expected_document(document, socket_path)
    if not target_headers:
        policy = document.get("shell_environment_policy")
        if isinstance(policy, dict) and "set" in policy:
            raise ConfigurationError("target table is represented by an inline or dotted value")
        newline = "\r\n" if "\r\n" in text else "\n"
        separator = "" if not text or text.endswith(("\n", "\r")) else newline
        candidate = text + separator
        candidate += (
            f"[shell_environment_policy.set]{newline}"
            f"SSH_AUTH_SOCK = {_toml_string(socket_path)}{newline}"
        )
    else:
        header_index = target_headers[0]
        table_end = len(lines)
        for index in range(header_index + 1, len(lines)):
            if _is_table_boundary(lines[index]):
                table_end = index
                break
        assignments: list[int] = []
        for index in range(header_index + 1, table_end):
            body, _ = _line_parts(lines[index])
            match = _ASSIGNMENT.fullmatch(body)
            if match is not None and _decode_key(match.group("key")) == TARGET_KEY:
                assignments.append(index)
        if len(assignments) > 1:
            raise ConfigurationError("target key is duplicated")
        if assignments:
            current_value = document.get("shell_environment_policy", {}).get("set", {}).get(TARGET_KEY)  # type: ignore[union-attr]
            if not isinstance(current_value, str):
                raise ConfigurationError("target value is not a string")
            lines[assignments[0]] = _rewrite_assignment(lines[assignments[0]], socket_path)
            candidate = "".join(lines)
        else:
            current_value = document.get("shell_environment_policy", {}).get("set", {}).get(TARGET_KEY)  # type: ignore[union-attr]
            if current_value is not None:
                raise ConfigurationError("target key uses an unsupported TOML form")
            newline = "\r\n" if "\r\n" in text else "\n"
            if table_end == len(lines) and lines and not lines[-1].endswith(("\n", "\r")):
                lines[-1] += newline
            lines.insert(table_end, f"SSH_AUTH_SOCK = {_toml_string(socket_path)}{newline}")
            candidate = "".join(lines)

    try:
        parsed_candidate = tomllib.loads(candidate)
    except (tomllib.TOMLDecodeError, ValueError) as error:
        raise ConfigurationError("patched config is invalid TOML") from error
    if parsed_candidate != expected:
        raise ConfigurationError("patch changed an unrelated config value")
    return candidate


def _atomic_write(path: Path, content: bytes, original: bytes, original_stat: os.stat_result) -> None:
    try:
        if path.is_symlink():
            raise ConfigurationError("config.toml is a symlink")
        current_stat = path.stat()
        if (
            current_stat.st_dev,
            current_stat.st_ino,
            current_stat.st_mtime_ns,
            current_stat.st_size,
        ) != (
            original_stat.st_dev,
            original_stat.st_ino,
            original_stat.st_mtime_ns,
            original_stat.st_size,
        ) or path.read_bytes() != original:
            raise ConfigurationError("config.toml changed during setup")
        if current_stat.st_uid != os.getuid():
            raise ConfigurationError("config.toml owner is not the current user")
    except OSError as error:
        raise ConfigurationError("config.toml could not be rechecked") from error

    temporary_path: Path | None = None
    file_descriptor: int | None = None
    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        os.fchmod(file_descriptor, stat.S_IMODE(original_stat.st_mode))
        with os.fdopen(file_descriptor, "wb") as temporary_file:
            file_descriptor = None
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    except OSError as error:
        raise ConfigurationError("config.toml could not be written") from error
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def configure(
    config_path: Path | str,
    socket_path: Path | str | None = None,
    *,
    home: Path | str | None = None,
    system: str | None = None,
) -> Outcome:
    """agent を検査してから、config.toml の対象キーだけを冪等に更新する。"""

    config = Path(config_path)
    if config.is_symlink():
        raise ConfigurationError("config.toml is a symlink")
    if not config.exists():
        return Outcome("skipped", "config-missing")
    if not config.is_file():
        raise ConfigurationError("config.toml is not a regular file")

    try:
        original_bytes = config.read_bytes()
        original_stat = config.stat()
        text = original_bytes.decode("utf-8")
        document = tomllib.loads(text)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, ValueError) as error:
        raise ConfigurationError("config.toml could not be parsed") from error

    if socket_path is None:
        current_system = system or platform.system()
        if current_system != "Darwin":
            return Outcome("skipped", "unsupported-platform")
        socket = discover_socket(home, system=current_system)
        if socket is None:
            return Outcome("skipped", "home-unavailable")
    else:
        socket = Path(socket_path)
    if not socket.is_absolute() or any(character in str(socket) for character in "\r\n\x00"):
        raise ConfigurationError("socket path is not absolute")
    if not _probe_agent(socket):
        return Outcome("skipped", "agent-unavailable")

    socket_value = str(socket)
    candidate = _patched_text(text, document, socket_value)
    if candidate == text:
        return Outcome("unchanged")
    _atomic_write(config, candidate.encode("utf-8"), original_bytes, original_stat)
    return Outcome("updated")


def _message(outcome: Outcome) -> str:
    if outcome.kind == "updated":
        return "CodexのBitwarden SSH署名用ソケットを設定しました。"
    if outcome.kind == "unchanged":
        return "CodexのBitwarden SSH署名用ソケットは設定済みです。"
    return {
        "config-missing": "Codexのconfig.tomlがまだ無いため、SSH署名設定をスキップしました。",
        "unsupported-platform": "macOS以外ではBitwarden SSH署名設定をスキップしました。",
        "home-unavailable": "HOMEを解決できないため、SSH署名設定をスキップしました。",
        "agent-unavailable": "Bitwarden SSH agentの鍵を確認できないため、設定を変更しませんでした。",
    }.get(outcome.reason, "SSH署名設定をスキップしました。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="Codex config.toml のパス")
    parser.add_argument("--socket", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        outcome = configure(args.config, args.socket)
    except ConfigurationError:
        print("CodexのBitwarden SSH署名設定に失敗しました。config.tomlは変更していません。", file=sys.stderr)
        return 1
    print(_message(outcome), file=sys.stderr if outcome.kind == "skipped" else sys.stdout)
    return SKIPPED_EXIT if outcome.kind == "skipped" else 0


if __name__ == "__main__":
    raise SystemExit(main())
