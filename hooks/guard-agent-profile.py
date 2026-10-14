#!/usr/bin/env python3
"""PreToolUse(Bash)フック: 個人用のセッションから、会社用の claude / codex を起動させない（ADR 0036）。

個人用のセッションは2種類ある。
  - Claude Code の ccp: 設定の env に CLAUDE_PROFILE=personal がある
  - Codex の cxp: CLAUDE_PROFILE が無く、CODEX_HOME が ~/.codex-personal を指す
それ以外（会社用）のセッションでは何もしない。

個人用のセッションで止めるもの
  - 素の `claude`: 子は ~/.claude/settings.json を読み直し、会社の接続先で動く。環境変数では防げない。
    モデルを呼ばないサブコマンド（--version、plugin、mcp など）は通す
  - 素の `codex` で、CODEX_HOME が無いか、実体が会社用の ~/.codex と同じもの。
    前者は setup.sh の実行忘れ、後者は setup.sh の後のディレクトリの差し替え
会社用を指示されたときの書き方（`CODEX_HOME=~/.codex codex ...`、`CLAUDE_PROFILE=default claude-headless ...`）は通す。

コマンドの分解は guard-dangerous-bash.py の関数を使う（引用符、&& などの区切り、前置きの除去）。
分解できないときや、このフック自体が失敗したときは、claude / codex の語を含む場合だけ止める。

既知の限界: スクリプトの中や `bash -c '...'` の中からの起動は見逃す。
"""
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parent
ALLOW = 0
BLOCK = 2

# モデルを呼ばないので、会社用の設定で動いても予算を使わないサブコマンド
CLAUDE_SAFE_FIRST_ARGS = {"--version", "-v", "--help", "-h", "plugin", "plugins", "mcp", "auth", "doctor", "update"}
CODEX_SAFE_FIRST_ARGS = {"--version", "-V", "--help", "-h"}
AGENT_WORD_RE = re.compile(r"(?<![\w-])(claude|codex)(?![\w-])")


def load_guard():
    spec = importlib.util.spec_from_file_location("guard_dangerous_bash", HOOK_DIR / "guard-dangerous-bash.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def same_path(left: str, right: Path) -> bool:
    return os.path.realpath(os.path.expanduser(left)) == os.path.realpath(right)


def session_host(env: dict, home: Path):
    """個人用のセッションなら 'claude' か 'codex' を、会社用なら None を返す。"""
    profile = env.get("CLAUDE_PROFILE", "")
    if profile == "personal":
        return "claude"
    if profile:
        return None
    codex_home = env.get("CODEX_HOME", "")
    if codex_home and same_path(codex_home, home / ".codex-personal"):
        return "codex"
    return None


def drop_env_unsets(raw: list):
    """`env -u NAME` を取り除き、CODEX_HOME を消すかどうかと、残りのトークン列を返す。"""
    cleared = False
    tokens = []
    index = 0
    in_env = False
    while index < len(raw):
        token = raw[index]
        if token == "env":
            in_env = True
        elif in_env and token in ("-i", "--ignore-environment", "-"):
            cleared = True
        elif in_env and token in ("-u", "--unset") and index + 1 < len(raw):
            cleared = cleared or raw[index + 1] == "CODEX_HOME"
            index += 2
            continue
        elif in_env and token.startswith("--unset="):
            cleared = cleared or token.split("=", 1)[1] == "CODEX_HOME"
            index += 1
            continue
        elif in_env and not token.startswith("-") and "=" not in token:
            in_env = False
        tokens.append(token)
        index += 1
    return cleared, tokens


def claude_message(host: str) -> str:
    if host == "claude":
        return ("ブロック: 個人用のセッションから素の claude を起動すると、~/.claude/settings.json の会社用の接続先で動きます。\n"
                "  claude-headless を使ってください（CLAUDE_PROFILE を見て、同じプロファイルで起動します）。\n"
                "  会社用を使うよう指示されたときは、CLAUDE_PROFILE=default claude-headless ... と明示してください。")
    return ("ブロック: 個人用の Codex から素の claude を起動すると、~/.claude/settings.json の会社用の接続先で動きます。\n"
            "  個人用の ccp を使ってください（例: ccp -p ...）。")


def codex_message(reason: str) -> str:
    return (f"ブロック: {reason}このまま codex を起動すると、会社用の ~/.codex で動きます。\n"
            "  個人用の cxp を使うか、bash setup.sh --claude を実行して新しいセッションを始めてください。\n"
            "  会社用を使うよう指示されたときは、CODEX_HOME=~/.codex codex ... と明示してください。")


def check_command(guard, command: str, env: dict, home: Path, host: str):
    """止めるならメッセージを、通すなら None を返す。"""
    tokens = guard.tokenize_command(guard.strip_heredocs(command))
    if tokens is None:
        if AGENT_WORD_RE.search(command):
            return "ブロック: コマンドを解析できないため、会社用の claude / codex を起動するか判定できません。コマンドを単純にしてください。"
        return None
    codex_home = env.get("CODEX_HOME") or None
    explicit = False
    for _, _, _, raw in guard.split_with_operators(tokens):
        cleared, raw_tokens = drop_env_unsets(list(raw))
        command_tokens = guard.normalize_command(raw_tokens)
        prefix = raw_tokens[:len(raw_tokens) - len(command_tokens)] if command_tokens else raw_tokens
        assigns_codex_home = any(token.startswith("CODEX_HOME=") for token in prefix)
        if not command_tokens:
            # `CODEX_HOME=x` だけの行は、シェル変数として後続の同じ行の codex に効かない。明示とはみなさない
            continue
        name = os.path.basename(command_tokens[0])
        args = command_tokens[1:]
        if name == "export" and any(arg.startswith("CODEX_HOME=") for arg in args):
            explicit, codex_home = True, None
            continue
        if name == "unset" and "CODEX_HOME" in args:
            explicit, codex_home = False, None
            continue
        if name == "claude":
            if args and args[0] in CLAUDE_SAFE_FIRST_ARGS:
                continue
            return claude_message(host)
        if name != "codex" or (args and args[0] in CODEX_SAFE_FIRST_ARGS):
            continue
        if assigns_codex_home or (explicit and not cleared):
            continue
        if cleared:
            return codex_message("env で CODEX_HOME が消えています。")
        if codex_home is None:
            return codex_message("CODEX_HOME が設定されていません（setup.sh の実行忘れの可能性があります）。")
        if same_path(codex_home, home / ".codex"):
            return codex_message(f"CODEX_HOME（{codex_home}）の実体が会社用の ~/.codex と同じです。")
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return ALLOW
    command = payload.get("tool_input", {}).get("command", "") if isinstance(payload, dict) else ""
    if not command:
        return ALLOW
    env = dict(os.environ)
    home = Path(env.get("HOME") or Path.home())
    host = session_host(env, home)
    if host is None:
        return ALLOW
    try:
        message = check_command(load_guard(), command, env, home, host)
    except Exception as error:  # noqa: BLE001 判定できないときは、対象の語を含む場合だけ止める
        if not AGENT_WORD_RE.search(command):
            return ALLOW
        message = f"ブロック: 会社用の claude / codex の起動を判定できませんでした（{type(error).__name__}: {error}）。"
    if message is None:
        return ALLOW
    print(message, file=sys.stderr)
    return BLOCK


if __name__ == "__main__":
    sys.exit(main())
