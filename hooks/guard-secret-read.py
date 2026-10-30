#!/usr/bin/env python3
"""secret を含みうるファイルの中身が、AIのツール呼び出しで出力されるのを止める PreToolUse フック。

使い方: guard-secret-read.py（入力は stdin の JSON。exit 0 で許可、exit 2 でブロック）
設計: docs/superpowers/specs/2026-10-29-secret-read-guard-design.md

permissions.deny（層1）は一覧に載せた場所しか止めない。このフック（層2）は、一覧に無いファイルも
「場所 × 権限」で判定して止める。対象範囲は ~/.config 配下と、ホーム直下のドットファイル・ドットディレクトリ。
その中で、本人だけが読める権限（600 など）の通常ファイルを secret とみなす。
判定できないとき（stat が失敗する、解析で例外が出る）は、対象範囲に見えるなら止める（fail-close）。

Claude Code にだけ登録する。Codex（codex/hooks.json）には登録しない。
"""
import glob
import json
import os
import re
import shlex
import stat
import sys

# Claude Code 自身が作る600のファイルのうち、作業で読むものの置き場所。権限ではなく場所で例外にする
EXEMPT_DIRS = (
    ".claude/projects", ".claude/state", ".claude/plugins", ".claude/plans", ".claude/jobs", ".claude/tasks",
)
# 解決前の文字列が対象範囲を指しているように見える書き方
HOME_DOT_PREFIXES = ("~/.", "$HOME/.", "${HOME}/.")
ALLOW, BLOCK, UNKNOWN = "allow", "block", "unknown"
BLOCK_EXIT = 2

# 中身を出さないコマンド。対象範囲のパスを引数に取っても通す
METADATA_COMMANDS = frozenset({
    "ls", "stat", "test", "[", "file", "wc", "du", "cd", "realpath", "readlink", "basename", "dirname",
    "show-config-structure",
})
# find でも、これらがあれば中身を出しうる
FIND_OUTPUT_ACTIONS = frozenset({"-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls"})
# 単純コマンドの区切り
SEPARATORS = frozenset({";", "&&", "||", "|", "|&", "&", "(", ")", "\n"})
# 出力側のリダイレクト。直後のトークンは書き込み先なので判定しない
OUTPUT_REDIRECTS = frozenset({">", ">>", ">&", "&>", ">|"})
# 先頭にあっても本体のコマンドではないもの
WRAPPERS = frozenset({"env", "sudo", "command", "exec", "time", "nohup", "rtk"})
ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")
GLOB_CHARS = re.compile(r"[*?\[]")
# パスではなくコードや文として書かれた引数（python3 -c "..." など）
CODE_LIKE = re.compile(r"[\s()'\";]")
HOME_VARIABLE = re.compile(r"\$\{HOME\}|\$HOME(?![A-Za-z0-9_])")
SUBSTITUTIONS = ("$(", "`", "<(")
PIPES = frozenset({"|", "|&"})
# 引数をコードとして実行するコマンド。文字列の中に書かれたパスを読みうる
INTERPRETERS = frozenset({
    "python", "python3", "node", "deno", "bun", "ruby", "perl", "php", "sh", "bash", "zsh", "fish", "osascript",
})
# heredoc の本文はコマンドの入力データで、パスとして解釈されない
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\s*\2(?=\n|$)", re.DOTALL)
# コマンド置換と組み合わさると、置換の中でホームを指しうる書き方
HOME_REFERENCES = re.compile(r"(?:^|[\s=@:])~(?:/|\s|$)|\bHOME\b")


def expand_home_variable(text: str, home: str) -> str:
    return HOME_VARIABLE.sub(lambda _: home, text)


def path_candidates(arg: str) -> list:
    """引数から、パスとして読まれうる部分を取り出す（--opt=x、KEY=x、@x、-fx の x）。"""
    candidates = [] if arg.startswith("-") else [arg]
    if "=" in arg:
        candidates.append(arg.split("=", 1)[1])
    if arg.startswith("-") and not arg.startswith("--") and len(arg) > 2 and "=" not in arg:
        candidates.append(arg[2:])
    return [c[1:] if c.startswith("@") else c for c in candidates if c]


def expand(path: str, home: str, cwd: str) -> str:
    """~ をホームへ展開し、相対パスは cwd 起点で絶対パスにする。"""
    if path == "~" or path.startswith("~/"):
        path = home + path[1:]
    return os.path.join(cwd, path)


def guarded_area(path: str, home: str) -> bool:
    """実体パスが対象範囲にあり、例外の場所に無いか。"""
    real = os.path.realpath(path)
    home_real = os.path.realpath(home)
    if not real.startswith(home_real + os.sep):
        return False
    rel = os.path.relpath(real, home_real)
    if not rel.startswith("."):
        return False
    return not any(rel == d or rel.startswith(d + os.sep) for d in EXEMPT_DIRS)


def is_owner_only_file(path: str) -> bool:
    st = os.stat(path)
    return stat.S_ISREG(st.st_mode) and stat.S_IMODE(st.st_mode) & 0o077 == 0


def classify(path: str, home: str, cwd: str) -> str:
    """allow・block・unknown のどれかを返す。ディレクトリは、対象範囲にあれば中を走査されうるので止める。"""
    target = os.path.realpath(expand(path, home, cwd))
    home_real = os.path.realpath(home)
    # ホームそのものや、その上のディレクトリを走査されると対象範囲まで届く
    if os.path.isdir(target) and (home_real + os.sep).startswith(target.rstrip(os.sep) + os.sep):
        return BLOCK
    if not guarded_area(target, home):
        return ALLOW
    try:
        if os.path.isdir(target):
            return BLOCK
        return BLOCK if is_owner_only_file(target) else ALLOW
    except OSError:
        return UNKNOWN


def looks_guarded(text: str, home: str) -> bool:
    """解決前の文字列が対象範囲に見えるか。解析できないときの最後の判定に使う。"""
    prefixes = HOME_DOT_PREFIXES + (os.path.realpath(home) + "/.", home + "/.")
    return any(prefix in text for prefix in prefixes)


def check_path(path: str, home: str, cwd: str):
    """ブロックの理由を返す。許可なら None。"""
    verdict = classify(path, home, cwd)
    if verdict == BLOCK:
        return f"{path} は secret を含みうる場所です（本人だけが読める権限のファイル、または対象範囲のディレクトリ）"
    if verdict == UNKNOWN:
        return f"{path} は対象範囲にあり、権限を確かめられませんでした"
    return None


def split_simple_commands(command: str) -> list:
    """(直前の区切り, トークン) の並びに分ける。先頭の区切りは空文字列。"""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    commands, current, separator = [], [], ""
    for token in lexer:
        if token in SEPARATORS:
            if current:
                commands.append((separator, current))
            current, separator = [], token
        else:
            current.append(token)
    if current:
        commands.append((separator, current))
    return commands


def strip_prefixes(tokens: list) -> list:
    """先頭の VAR=value と、env・sudo などの包み込むコマンドを外す。"""
    index = 0
    while index < len(tokens) and (ASSIGNMENT.match(tokens[index]) or os.path.basename(tokens[index]) in WRAPPERS):
        index += 1
    return tokens[index:]


def split_redirects(tokens: list):
    """(引数, 入力リダイレクトの読み取り元) に分ける。出力リダイレクトの書き込み先は捨てる。"""
    args, sources = [], []
    iterator = iter(tokens)
    for token in iterator:
        if token == "<":
            sources.append(next(iterator, ""))
        elif token in OUTPUT_REDIRECTS:
            next(iterator, None)
        else:
            args.append(token)
    return args, sources


def judge_arg(arg: str, home: str, cwd, cwd_guarded: bool, interpreter: bool = False) -> str:
    """1つの引数を判定する。cwd が None なのは、解決できない cd の後。"""
    arg = expand_home_variable(arg, home)
    # ~user の形は展開先を確かめられないので止める
    if arg.startswith("~") and arg != "~" and not arg.startswith("~/"):
        return BLOCK
    if CODE_LIKE.search(arg):
        # コードとして実行されるときだけ、中に書かれたパスを読みうる。それ以外は文（コミットメッセージなど）
        return BLOCK if interpreter and looks_guarded(arg, home) else ALLOW
    if "$" in arg or "`" in arg:
        return BLOCK if looks_guarded(arg, home) else ALLOW
    if cwd is None and not (arg.startswith("/") or arg.startswith("~")):
        return BLOCK if cwd_guarded else ALLOW
    base = cwd or "/"
    if GLOB_CHARS.search(arg):
        matches = glob.glob(expand(arg, home, base))
        if not matches:
            return BLOCK if looks_guarded(arg, home) or guarded_area(expand(arg, home, base), home) else ALLOW
        return BLOCK if any(classify(m, home, base) != ALLOW for m in matches) else ALLOW
    verdict = classify(arg, home, base)
    if verdict == UNKNOWN:
        return BLOCK
    return verdict


def is_metadata_command(name: str, args: list) -> bool:
    if name == "find":
        return not FIND_OUTPUT_ACTIONS.intersection(args)
    return name in METADATA_COMMANDS


def check_bash(command: str, home: str, cwd: str):
    """ブロックの理由を返す。許可なら None。同じコマンドの中の cd を追う。"""
    command = HEREDOC.sub("<<heredoc", command)
    # コマンド置換の中身は1つのコマンドとして追えないので、ホームを指しうる書き方があれば止める
    if any(s in command for s in SUBSTITUTIONS) and (
            looks_guarded(expand_home_variable(command, home), home) or HOME_REFERENCES.search(command)):
        return "コマンド置換と、ホームを指す書き方が一緒に使われています"
    cwd_guarded = False
    # 中身を出さないコマンドが対象範囲を指したか。パイプの後段はその出力を読みうる
    listed_guarded = False
    for separator, tokens in split_simple_commands(command):
        if separator in PIPES and listed_guarded:
            consumer = strip_prefixes(tokens)
            if not consumer or not is_metadata_command(os.path.basename(consumer[0]), consumer[1:]):
                return "secret を含みうる場所の一覧を、パイプの後段で読もうとしています"
        elif separator not in PIPES:
            listed_guarded = False
        tokens = strip_prefixes(tokens)
        if not tokens:
            continue
        name = os.path.basename(tokens[0])
        args, sources = split_redirects(tokens[1:])
        # 入力リダイレクトは、どのコマンドでも中身を読む経路になる
        for source in sources:
            if judge_arg(source, home, cwd, cwd_guarded) == BLOCK:
                return f"{source} を入力リダイレクトで読もうとしています"
        if name == "cd":
            target = expand_home_variable(next((a for a in args if not a.startswith("-")), "~"), home)
            if "$" in target or "`" in target or GLOB_CHARS.search(target):
                cwd, cwd_guarded = None, looks_guarded(target, home) or "HOME" in target
            elif cwd is not None or target.startswith(("/", "~")):
                cwd = os.path.realpath(expand(target, home, cwd or "/"))
            continue
        # まとめたショートオプション（-vf~/.x など）は、どこからがパスか分からないので文字列で判定する
        if any(a.startswith("-") and not a.startswith("--") and looks_guarded(expand_home_variable(a, home), home)
               for a in args):
            return f"{name} のオプションが、secret を含みうる場所を指しています"
        candidates = [c for arg in args for c in path_candidates(arg)]
        if is_metadata_command(name, args):
            # 引数が無いときは、作業ディレクトリが暗黙の対象になる
            implicit = cwd_guarded if cwd is None else guarded_area(cwd, home)
            listed_guarded = listed_guarded or (not candidates and implicit) or any(
                judge_arg(c, home, cwd, cwd_guarded) == BLOCK or guarded_area(expand(c, home, cwd or "/"), home)
                for c in candidates)
            continue
        interpreter = name in INTERPRETERS
        for candidate in candidates:
            if judge_arg(candidate, home, cwd, cwd_guarded, interpreter) == BLOCK:
                return f"{name} が {candidate} を読もうとしています（secret を含みうる場所）"
    return None


def decide(data: dict, home: str):
    tool = data.get("tool_name")
    tool_input = data["tool_input"]
    cwd = data.get("cwd") or os.getcwd()
    if tool == "Read":
        return check_path(tool_input["file_path"], home, cwd)
    if tool == "Grep":
        return check_path(tool_input.get("path") or cwd, home, cwd)
    if tool == "Bash":
        return check_bash(tool_input["command"], home, cwd)
    return None


def block(reason: str) -> int:
    print(f"ブロック: {reason}。中身を出さずに構造だけ見るなら show-config-structure <path> を使って。", file=sys.stderr)
    return BLOCK_EXIT


def main() -> int:
    raw = sys.stdin.read()
    home = os.environ.get("HOME", "")
    try:
        reason = decide(json.loads(raw), home)
    except Exception as error:
        if looks_guarded(raw, home):
            return block(f"入力を判定できませんでした（{type(error).__name__}）。対象範囲のパスを含むので止めます")
        return 0
    return block(reason) if reason else 0


if __name__ == "__main__":
    sys.exit(main())
