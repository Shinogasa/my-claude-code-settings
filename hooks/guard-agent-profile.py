#!/usr/bin/env python3
"""PreToolUse(Bash)フック: 個人用のセッションから、会社用の claude / codex を起動させない（ADR 0036）。

個人用のセッションは2種類ある。
  - Claude Code の ccp: 設定の env に CLAUDE_PROFILE=personal がある
  - Codex の cxp: CLAUDE_PROFILE が無く、CODEX_HOME が ~/.codex-personal を指す
それ以外（会社用）のセッションでは何もしない。

個人用のセッションで止めるもの
  - 素の `claude`: 子は ~/.claude/settings.json を読み直し、会社の接続先で動く。環境変数では防げない。
    読み取りだけのサブコマンド（--version、auth status、mcp list など）は通す
  - 素の `codex` で、CODEX_HOME が無いか、消したか、実体が会社用の ~/.codex と同じもの。
    最初は setup.sh の実行忘れ、最後は setup.sh の後のディレクトリの差し替えに当たる
  - コマンド名を確定できず（変数、ワイルドカード）、claude / codex の語を含むもの
会社用を指示されたときの書き方（`CODEX_HOME=~/.codex codex ...`、`CLAUDE_PROFILE=default claude-headless ...`）は通す。

このフックは、エージェントが誤って会社用で動かすのを防ぐ。意図的な回避は防がない。
明示の例外はエージェント自身も書けるし、スクリプトの中や `bash -c '...'` の中からの起動は見逃す。

コマンドの分解は guard-dangerous-bash.py の関数を使う（引用符、&& などの区切り、前置きの除去）。
その前に、ヒアドキュメントの本文を消し、コマンド置換（$(...) とバッククォート）の中身を取り出して同じ検査にかける。
分解できないときや、このフック自体が失敗したときは、claude / codex の語を含む場合だけ止める。
"""
import fnmatch
import importlib.util
import json
import os
import re
import shlex
import sys
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parent
ALLOW = 0
BLOCK = 2

# 読み取りだけで、会社用の設定で動いても予算を使わず、設定も変えないもの（引数の先頭がこれに一致すれば通す）
CLAUDE_SAFE_ARGS = (("--version",), ("-v",), ("--help",), ("-h",), ("doctor",),
                    ("auth", "status"), ("mcp", "list"), ("plugin", "list"), ("plugins", "list"))
CODEX_SAFE_ARGS = (("--version",), ("-V",), ("--help",), ("-h",))
# パスの一部（~/.claude/、~/.codex、claude.json、claude-headless）には反応しない
AGENT_WORD_RE = re.compile(r"(?<![\w.])(claude|codex)(?![\w./-])", re.IGNORECASE)
AGENTS = {"claude", "codex"}
# env の短いフラグのうち、-S の前にまとめて書けるもの（値を取らない -i、-0、-v）
ENV_SPLIT_SHORT_RE = re.compile(r"-[i0v]*S.*", re.DOTALL)
HEREDOC_START_RE = re.compile(r"(?<!<)<<(?!<)(-?)\s*(['\"]?)([A-Za-z_][\w-]*)\2")
UNRESOLVED_NAME_RE = re.compile(r"[$`*?\[{]")
# 実際のコマンドの前に置かれ、後ろのコマンドを起動するもの。値を取るオプションも併記する
WRAPPERS = {
    "timeout": {"-s", "--signal", "-k", "--kill-after"}, "gtimeout": {"-s", "--signal", "-k", "--kill-after"},
    "nice": {"-n", "--adjustment"}, "nohup": set(), "caffeinate": {"-t", "-w"}, "setsid": set(),
    "stdbuf": {"-i", "-o", "-e"}, "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U"},
    "xargs": {"-n", "-I", "-L", "-P", "-s", "-d", "-E", "-a", "--max-args", "--max-procs", "--delimiter"},
    "env": {"-C", "--chdir", "-S", "--split-string", "-u", "--unset"},
    "exec": {"-a"}, "time": set(), "command": set(), "builtin": set(),
    "watch": {"-n", "--interval"}, "script": {"-t"},
}
# オプションの後ろに、コマンドの前の位置引数を1つ取るもの（timeout の時間、script の記録先のファイル）
TAKES_ONE_ARGUMENT = {"timeout", "gtimeout", "script"}
PACKAGE_RUNNERS = {"npx", "bunx", "pnpx"}
# サブコマンドでパッケージを起動するもの（npm exec、pnpm dlx など）
PACKAGE_RUNNER_SUBCOMMANDS = {"npm": {"exec", "x"}, "pnpm": {"dlx", "exec"}, "yarn": {"dlx", "exec"}, "bun": {"x"}}
FIND_EXEC = {"-exec", "-execdir", "-ok", "-okdir"}


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


def strip_heredoc_bodies(command: str) -> str:
    """ヒアドキュメントの本文だけを消す。`<<` のある行は残して検査する。"""
    lines = command.split("\n")
    kept = []
    pending = []
    for line in lines:
        if pending:
            strip_tabs, delimiter = pending[0]
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                pending.pop(0)
            continue
        kept.append(line)
        pending = [(dash == "-", word) for dash, _, word in HEREDOC_START_RE.findall(line)]
    return "\n".join(kept)


def command_substitutions(command: str) -> list:
    """$(...) とバッククォートの中身を返す。単一引用符の中は文字列なので取り出さない。"""
    found = []
    index = 0
    in_single = False
    while index < len(command):
        char = command[index]
        if char == "\\" and not in_single:
            index += 2
            continue
        if char == "'" and not in_single and not inside_double(command, index):
            in_single = True
        elif char == "'" and in_single:
            in_single = False
        elif not in_single and command.startswith("$(", index):
            end = matching_paren(command, index + 1)
            found.append(command[index + 2:end])
            index = end + 1
            continue
        elif not in_single and char == "`":
            end = command.find("`", index + 1)
            end = len(command) if end < 0 else end
            found.append(command[index + 1:end])
            index = end + 1
            continue
        index += 1
    return found


def inside_double(command: str, index: int) -> bool:
    """index の位置が二重引用符の中にあるかを、単純に数えて返す（単一引用符の判定用）。"""
    count = 0
    in_single = False
    for position, char in enumerate(command[:index]):
        if char == "'" and count % 2 == 0:
            in_single = not in_single
        elif char == '"' and not in_single and (position == 0 or command[position - 1] != "\\"):
            count += 1
    return count % 2 == 1


def matching_paren(command: str, open_index: int) -> int:
    depth = 0
    for index in range(open_index, len(command)):
        if command[index] == "(":
            depth += 1
        elif command[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return len(command)


def split_string(value: str) -> list:
    """env -S の値を、env と同じように空白で分ける。分けられなければ1語のまま残す（後段が名前で判定する）。"""
    try:
        return shlex.split(value)
    except ValueError:
        return [value]


def drop_env_unsets(raw: list):
    """`env -u NAME` と `env -i` を見て、CODEX_HOME を消すかどうかと、`-u NAME` を除いたトークン列を返す。"""
    cleared = False
    tokens = []
    index = 0
    in_env = False
    while index < len(raw):
        token = raw[index]
        if os.path.basename(token) == "env":
            in_env = True
        elif in_env and token in ("-i", "--ignore-environment", "-"):
            cleared = True
        elif in_env and token in ("-u", "--unset") and index + 1 < len(raw):
            cleared = cleared or raw[index + 1] == "CODEX_HOME"
            index += 2
            continue
        elif in_env and token in ("-S", "--split-string") and index + 1 < len(raw):
            # 値をコマンドとして分けて実行する（env -S 'claude -p x'）。分けたトークンに置き換える
            raw = raw[:index] + split_string(raw[index + 1]) + raw[index + 2:]
            continue
        elif in_env and ENV_SPLIT_SHORT_RE.fullmatch(token):
            # 短いフラグのまとめ書き（-iS 'x'）と、値を続けた形（-S'x'）。S より後ろか次のトークンが値。
            # S より前は値を取らないフラグに限る。-uSHELL は -u SHELL で、-S の形ではない
            flags, value = token[1:].split("S", 1)
            cleared = cleared or "i" in flags
            if value:
                raw = raw[:index] + split_string(value) + raw[index + 1:]
            elif index + 1 < len(raw):
                raw = raw[:index] + split_string(raw[index + 1]) + raw[index + 2:]
            else:
                index += 1
            continue
        elif in_env and token.startswith("--split-string="):
            raw = raw[:index] + split_string(token.split("=", 1)[1]) + raw[index + 1:]
            continue
        elif in_env and token in ("-C", "--chdir") and index + 1 < len(raw):
            # 値を取るオプション。guard の前置き除去は値を読み飛ばさないので、ここで落とす
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


def unwrap(tokens: list):
    """前置き（timeout、xargs、npx、find -exec など）を剥がし、(名前, 引数) を返す。起動でなければ None。

    名前を読み切れなくても、前置きやパッケージの起動の後ろに次のものがあれば起動とみなす。
    値を取るオプション（npx -p foo、script -c 'claude'）をすべて数え上げるのは無理なので、止める側に倒す。
    - 先頭の語が claude / codex の、1語にまとめたコマンド文字列（watch 'claude -p x'、script -c 'claude'）
    - パッケージの起動なら、claude / codex という単独の語（npx -p foo -- claude、npm --prefix x exec claude）
    ただの引数（xargs grep claude、git log --grep=claude）では止めない。
    """
    result = unwrap_names(tokens)
    if result is not None and result[0] in AGENTS:
        return result
    rest, is_package = launched_part(tokens)
    for token in rest:
        words = split_string(token) if any(char.isspace() for char in token) else []
        if words and os.path.basename(words[0]).lower() in AGENTS:
            return os.path.basename(words[0]).lower(), words[1:]
        if is_package and os.path.basename(token).lower() in AGENTS:
            return os.path.basename(token).lower(), []
    return result


def launched_part(tokens: list):
    """最初の前置き・パッケージの起動より後ろのトークンと、パッケージの起動かどうか。無ければ ([], False)。"""
    for index, token in enumerate(tokens):
        name = os.path.basename(token).lower()
        subcommands = PACKAGE_RUNNER_SUBCOMMANDS.get(name, ())
        if name in PACKAGE_RUNNERS or any(t in subcommands for t in tokens[index + 1:]):
            return tokens[index + 1:], True
        if name in WRAPPERS:
            return tokens[index + 1:], False
        if not ("=" in token and not token.startswith("-")):
            return [], False
    return [], False


def unwrap_names(tokens: list):
    """前置きを剥がして、起動する名前と引数を読む。"""
    index = 0
    while index < len(tokens):
        name = os.path.basename(tokens[index]).lower()
        if name == "command" and index + 1 < len(tokens) and tokens[index + 1] in ("-v", "-V"):
            return None
        if name in WRAPPERS:
            index += 1
            while index < len(tokens) and (tokens[index].startswith("-") or (name == "env" and "=" in tokens[index])):
                option = tokens[index]
                index += 1
                if option in WRAPPERS[name] and index < len(tokens):
                    index += 1
            if name in TAKES_ONE_ARGUMENT and index < len(tokens):
                index += 1
            continue
        if name in PACKAGE_RUNNERS or (index + 1 < len(tokens)
                                       and tokens[index + 1] in PACKAGE_RUNNER_SUBCOMMANDS.get(name, ())):
            index += 1 if name in PACKAGE_RUNNERS else 2
            while index < len(tokens) and tokens[index].startswith("-"):
                index += 1
            if index >= len(tokens):
                return None
            package = tokens[index].lower()
            if "claude-code" in package:
                return "claude", tokens[index + 1:]
            if re.search(r"(^|/)codex(@|$)", package):
                return "codex", tokens[index + 1:]
            # パッケージ名でなく、入っているコマンドの名前のこともある（pnpm exec claude、npm exec --package=X -- claude）
            return unwrap_names(tokens[index:])
        if name == "find":
            for position in range(index + 1, len(tokens)):
                if tokens[position] in FIND_EXEC:
                    return unwrap_names(tokens[position + 1:])
            return None
        return name, tokens[index + 1:]
    return None


def is_safe(args: list, safe: tuple) -> bool:
    return any(tuple(args[:len(prefix)]) == prefix for prefix in safe)


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


UNPARSEABLE_MESSAGE = ("ブロック: コマンドを解析できないため、会社用の claude / codex を起動するか判定できません。"
                       "コマンドを単純にしてください。")
UNRESOLVED_MESSAGE = ("ブロック: コマンド名を確定できず（変数やワイルドカード）、claude / codex を起動するか判定できません。"
                      "claude-headless、ccp、cxp などの名前をそのまま書いてください。")


class CodexHomeState:
    """同じコマンドの中で export / unset された CODEX_HOME を追う。"""

    def __init__(self, value):
        self.value = value or None
        self.explicit = False
        self.unknown = False

    def apply(self, name: str, args: list) -> bool:
        """export / unset なら状態を更新して True を返す。"""
        if name == "export":
            for arg in args:
                if arg.startswith("CODEX_HOME="):
                    value = arg.split("=", 1)[1]
                    self.value, self.explicit, self.unknown = (value or None), bool(value), not value
                elif arg == "CODEX_HOME" or ("-n" in args and "CODEX_HOME" in arg):
                    self.unknown = True
            return True
        if name == "unset" and "CODEX_HOME" in args:
            self.value, self.explicit, self.unknown = None, False, False
            return True
        return False


def check_codex(state: CodexHomeState, prefix: list, cleared: bool, home: Path):
    assigned = [token.split("=", 1)[1] for token in prefix if token.startswith("CODEX_HOME=")]
    if cleared:
        return codex_message("env で CODEX_HOME が消えています。")
    if assigned:
        if assigned[-1]:
            return None
        return codex_message("CODEX_HOME が空です。")
    if state.unknown:
        return codex_message("CODEX_HOME の値を、コマンドから確定できません。")
    if state.explicit:
        return None
    if state.value is None:
        return codex_message("CODEX_HOME が設定されていません（setup.sh の実行忘れの可能性があります）。")
    if same_path(state.value, home / ".codex"):
        return codex_message(f"CODEX_HOME（{state.value}）の実体が会社用の ~/.codex と同じです。")
    return None


def check_command(guard, command: str, env: dict, home: Path, host: str, state=None):
    """止めるならメッセージを、通すなら None を返す。"""
    state = state or CodexHomeState(env.get("CODEX_HOME"))
    body = strip_heredoc_bodies(command)
    for inner in command_substitutions(body):
        message = check_command(guard, inner, env, home, host, CodexHomeState(state.value))
        if message:
            return message
    tokens = guard.tokenize_command(body)
    if tokens is None:
        return UNPARSEABLE_MESSAGE if AGENT_WORD_RE.search(body) else None
    for _, _, _, raw in guard.split_with_operators(tokens):
        cleared, raw_tokens = drop_env_unsets(list(raw))
        command_tokens = guard.normalize_command(raw_tokens)
        if not command_tokens:
            continue
        prefix = raw_tokens[:len(raw_tokens) - len(command_tokens)]
        if any(token == "command" and nxt in ("-v", "-V") for token, nxt in zip(prefix, prefix[1:])):
            continue  # command -v は場所を調べるだけで、起動しない
        if state.apply(os.path.basename(command_tokens[0]), command_tokens[1:]):
            continue
        resolved = unwrap(command_tokens)
        if resolved is None:
            continue
        name, args = resolved
        if UNRESOLVED_NAME_RE.search(name):
            if AGENT_WORD_RE.search(body) or any(fnmatch.fnmatch(agent, name) for agent in ("claude", "codex")):
                return UNRESOLVED_MESSAGE
            continue
        if name == "claude" and not is_safe(args, CLAUDE_SAFE_ARGS):
            return claude_message(host)
        if name == "codex" and not is_safe(args, CODEX_SAFE_ARGS):
            message = check_codex(state, prefix, cleared, home)
            if message:
                return message
    return None


def evaluate(raw_input: str) -> int:
    payload = json.loads(raw_input)
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command:
        return ALLOW
    env = dict(os.environ)
    home = Path(env.get("HOME") or Path.home())
    host = session_host(env, home)
    if host is None:
        return ALLOW
    message = check_command(load_guard(), command, env, home, host)
    if message is None:
        return ALLOW
    print(message, file=sys.stderr)
    return BLOCK


def main() -> int:
    raw_input = sys.stdin.read()
    try:
        return evaluate(raw_input)
    # 判定できないときは、対象の語を含む場合だけ止める。guard の読み込み中の sys.exit も、判定できない側に入れる
    except (Exception, SystemExit) as error:  # noqa: BLE001
        if not AGENT_WORD_RE.search(raw_input):
            return ALLOW
        print(f"ブロック: 会社用の claude / codex の起動を判定できませんでした（{type(error).__name__}: {error}）。",
              file=sys.stderr)
        return BLOCK


if __name__ == "__main__":
    sys.exit(main())
