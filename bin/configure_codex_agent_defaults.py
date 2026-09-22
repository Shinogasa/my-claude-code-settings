#!/usr/bin/env python3
"""Codex config.toml にサブエージェントの安全な既定ペアを設定する。"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import tomllib
from pathlib import Path

import codex_config_io as safe_config


DEFAULTS = {
    "default_subagent_model": "gpt-5.6-luna",
    "default_subagent_reasoning_effort": "medium",
}
TARGET_TABLE = ("agents",)
_TABLE_LINE = re.compile(
    r"^[ \t]*(?P<open>\[\[?)(?P<body>.*?)(?P<close>\]\]?)[ \t]*(?:#.*)?(?:\r?\n)?$"
)
_ASSIGNMENT = re.compile(
    r"^(?P<prefix>[ \t]*)(?P<key>\"(?:[^\"\\]|\\.)*\"|'(?:[^']|'')*'|[A-Za-z0-9_-]+)"
    r"(?P<separator>[ \t]*=[ \t]*)(?P<rhs>.*)$"
)


ConfigurationError = safe_config.ConfigurationError
_extended_acl_allows_mutation = safe_config._extended_acl_allows_mutation


def _line_parts(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    return line, ""


def _structural_line_mask(lines: list[str]) -> list[bool]:
    """TOMLの文字列外から始まる行だけを構文候補として印付けする。"""
    state: str | None = None
    structural = []
    for line in lines:
        structural.append(state is None)
        body, _ = _line_parts(line)
        index = 0
        while index < len(body):
            if state is None:
                if body[index] == "#":
                    break
                if body.startswith('\"\"\"', index):
                    state = "multiline-basic"
                    index += 3
                elif body.startswith("'''", index):
                    state = "multiline-literal"
                    index += 3
                elif body[index] == '\"':
                    state = "basic"
                    index += 1
                elif body[index] == "'":
                    state = "literal"
                    index += 1
                else:
                    index += 1
            elif state == "basic":
                if body[index] == "\\":
                    index += 2
                elif body[index] == '\"':
                    state = None
                    index += 1
                else:
                    index += 1
            elif state == "literal":
                if body[index] == "'":
                    state = None
                index += 1
            elif state == "multiline-basic":
                if body[index] == "\\":
                    index += 2
                elif body[index] == '\"':
                    quote_end = index
                    while quote_end < len(body) and body[quote_end] == '\"':
                        quote_end += 1
                    if quote_end - index >= 3:
                        state = None
                    index = quote_end
                else:
                    index += 1
            else:
                if body[index] == "'":
                    quote_end = index
                    while quote_end < len(body) and body[quote_end] == "'":
                        quote_end += 1
                    if quote_end - index >= 3:
                        state = None
                    index = quote_end
                else:
                    index += 1
    return structural


def _table_path_from_body(body: str) -> tuple[str, ...] | None:
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


def _rewrite_assignment(line: str, value: str) -> str:
    body, newline = _line_parts(line)
    match = _ASSIGNMENT.fullmatch(body)
    if match is None:
        raise ConfigurationError("target assignment could not be parsed")
    rhs = match.group("rhs")
    if '"""' in rhs or "'''" in rhs:
        raise ConfigurationError("multiline target assignment is unsupported")
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
        + json.dumps(value)
        + suffix
        + newline
    )


def _patched_text(text: str, document: dict[str, object]) -> str:
    lines = text.splitlines(keepends=True)
    structural = _structural_line_mask(lines)
    target_headers = [
        index
        for index, line in enumerate(lines)
        if structural[index] and _table_path(line) == TARGET_TABLE
    ]
    if len(target_headers) > 1:
        raise ConfigurationError("agents table is duplicated")

    current_agents = document.get("agents")
    if current_agents is not None and not isinstance(current_agents, dict):
        raise ConfigurationError("agents is not a table")

    newline = "\r\n" if "\r\n" in text else "\n"
    if not target_headers:
        if current_agents is not None:
            raise ConfigurationError("agents uses an unsupported inline or dotted form")
        separator = "" if not text or text.endswith(("\n", "\r")) else newline
        candidate = text + separator + f"[agents]{newline}"
        for key, value in DEFAULTS.items():
            candidate += f"{key} = {json.dumps(value)}{newline}"
    else:
        header_index = target_headers[0]
        table_end = len(lines)
        for index in range(header_index + 1, len(lines)):
            if structural[index] and _is_table_boundary(lines[index]):
                table_end = index
                break

        assignments: dict[str, int] = {}
        for index in range(header_index + 1, table_end):
            if not structural[index]:
                continue
            body, _ = _line_parts(lines[index])
            match = _ASSIGNMENT.fullmatch(body)
            if match is None:
                continue
            key = _decode_key(match.group("key"))
            if key not in DEFAULTS:
                continue
            if key in assignments:
                raise ConfigurationError(f"{key} is duplicated")
            assignments[key] = index

        for key, value in DEFAULTS.items():
            if key in assignments:
                lines[assignments[key]] = _rewrite_assignment(lines[assignments[key]], value)

        missing = [(key, value) for key, value in DEFAULTS.items() if key not in assignments]
        if missing:
            if table_end == len(lines) and lines and not lines[-1].endswith(("\n", "\r")):
                lines[-1] += newline
            additions = [f"{key} = {json.dumps(value)}{newline}" for key, value in missing]
            lines[table_end:table_end] = additions
        candidate = "".join(lines)

    expected = copy.deepcopy(document)
    agents = expected.setdefault("agents", {})
    if not isinstance(agents, dict):
        raise ConfigurationError("agents is not a table")
    agents.update(DEFAULTS)
    try:
        parsed_candidate = tomllib.loads(candidate)
    except (tomllib.TOMLDecodeError, ValueError) as error:
        raise ConfigurationError("patched config is invalid TOML") from error
    if parsed_candidate != expected:
        raise ConfigurationError("patch changed an unrelated config value")
    return candidate


def configure(config_path: Path | str) -> str:
    config = Path(config_path)
    try:
        with safe_config.locked_config(config, allow_missing=True) as transaction:
            if not transaction.exists:
                candidate = _patched_text("", {})
                transaction.create(candidate.encode("utf-8"))
                return "updated"

            if transaction.original is None:
                raise ConfigurationError("config.toml contents are unavailable")
            text = transaction.original.decode("utf-8")
            document = tomllib.loads(text)
            candidate = _patched_text(text, document)
            if candidate == text:
                return "unchanged"
            transaction.replace(candidate.encode("utf-8"))
            return "updated"
    except ConfigurationError:
        raise
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, ValueError) as error:
        raise ConfigurationError("config.toml could not be parsed") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="Codex config.toml のパス")
    args = parser.parse_args(argv)
    try:
        outcome = configure(args.config)
    except ConfigurationError:
        print(
            "Codexのサブエージェント既定値を設定できませんでした。config.tomlは変更していません。",
            file=sys.stderr,
        )
        return 1
    message = "設定しました" if outcome == "updated" else "設定済みです"
    print(f"Codexのサブエージェント既定値を{message}。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
