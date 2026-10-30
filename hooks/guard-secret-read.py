#!/usr/bin/env python3
"""secret を含みうるファイルや環境変数の値が、AIのツール呼び出しで出力されるのを止める PreToolUse フック。

使い方: guard-secret-read.py（入力は stdin の JSON。exit 0 で許可、exit 2 でブロック）
設計: docs/superpowers/specs/2026-10-29-secret-read-guard-design.md、判断の経緯: docs/adr/0043-secret-read-guard.md

permissions.deny（層1）は一覧に載せた場所しか止めない。このフック（層2）は、一覧に無いファイルも
「場所 × 権限」で判定して止める。対象範囲は ~/.config 配下と、ホーム直下のドットファイル・ドットディレクトリ。
その中で、本人だけが読める権限（600 など）の通常ファイルを secret とみなす。
判定できないとき（stat が失敗する、解析で例外が出る）は、対象範囲に見えるなら止める（fail-close）。

守るのは、うっかり読んで出力してしまう事故だけである。Bash はコマンドの文字列から推定しているので、
意図して書き換えたコマンドは見抜けない。Claude Code にだけ登録し、Codex（codex/hooks.json）には登録しない。
"""
import functools
import glob
import json
import os
import pwd
import re
import shlex
import stat
import sys
from pathlib import Path

# permissions.deny の正本。実機で、deny が Read ツールにしか効かず Bash の cat には効かないと分かった（2026-10-30）。
# そのため同じ一覧をフックでも読み、Read・Grep・Bash のどれでも、権限に関係なく止める
SETTINGS_TEMPLATE = Path(__file__).resolve().parent.parent / "settings.json.template"
DENY_READ_RULE = re.compile(r"^Read\((.+)\)$")

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
    "echo", "printf", "export", "true", "false", "type", "which", "show-config-structure",
    "mkdir", "touch", "rmdir",
})
# 中身を出さないコマンドのうち、出力が名前の一覧ではないもの。パイプの後段に渡しても読み取りにならない
NON_LISTING_COMMANDS = frozenset({
    "show-config-structure", "echo", "printf", "export", "true", "false", "type", "which",
    "mkdir", "touch", "rmdir",
})
# HOME を書き込み先に取りうる組み込みコマンド
HOME_WRITERS = frozenset({"unset", "read", "mapfile", "readarray", "declare", "typeset", "readonly", "local", "export"})
# 権限を絞るだけの chmod のモード（600・0700、go-rwx、u+x など）。権限を広げる変更は、権限で判定するガードをすり抜けさせる
TIGHTENING_NUMERIC_MODE = re.compile(r"^0?[0-7]?[0-7]00$")
TIGHTENING_SYMBOLIC_CLAUSE = re.compile(r"^(?:[ugoa]*-[rwxXst]+|u[+=][rwxXst]*)$")
# find でも、これらがあれば中身を出しうる
FIND_OUTPUT_ACTIONS = frozenset({"-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls"})
# 語の区切りになる文字。この直後の # はコメントの始まり
WORD_BOUNDARY_CHARS = frozenset(" \t\n;&|()<>")
# 単純コマンドの区切りに使う文字。; & | ( ) と改行
SEPARATOR_CHARS = frozenset(";&|()\n")
# 出力側のリダイレクト。直後のトークンは書き込み先なので判定しない
OUTPUT_REDIRECTS = frozenset({">", ">>", ">&", "&>", ">|", "&>>"})
# 先頭にあっても本体のコマンドではないもの
WRAPPERS = frozenset({"env", "sudo", "command", "exec", "time", "nohup", "rtk", "nice", "timeout", "caffeinate"})
ASSIGNMENT = re.compile(r"^[A-Za-z_]\w*=")
GLOB_CHARS = re.compile(r"[*?\[]")
DURATION = re.compile(r"^\d+(\.\d+)?[smhd]?$")
# パスではなくコードや文として書かれた引数（python3 -c "..." など）
CODE_LIKE = re.compile(r"[\s()'\";]")
HOME_VARIABLE = re.compile(r"\$\{HOME\}|\$HOME(?![A-Za-z0-9_])")
VARIABLE_REFERENCE = re.compile(r"\$\{?([A-Za-z_]\w*)")
# 名前にこれらの部分を含む環境変数は、値が secret でありうる
SECRET_NAME_PARTS = frozenset({
    "TOKEN", "KEY", "SECRET", "PASSWORD", "PASSWD", "PASS", "CREDENTIAL", "CREDENTIALS", "AUTH", "PAT", "APIKEY",
})
# 環境変数を一覧で出すコマンド。引数なしで動かすと値まで出る
ENV_DUMPERS = frozenset({"env", "printenv"})
SHELL_DUMPERS = frozenset({"set", "export", "declare", "typeset"})
# 引数や本文をコードとして実行するコマンド。文字列の中に書かれたパスを読みうる
INTERPRETER = re.compile(
    r"^(?:python[0-9.]*|node(?:js)?|deno|bun|tsx|ts-node|ruby|perl|php|lua|sh|bash|zsh|fish|osascript"
    r"|awk|gawk|sed|sqlite3|eval|source|\.)$"
)
# パイプの前段から名前の一覧を受け取っても、名前を文字列として扱うだけのコマンド。これ以外の後段は止める
SAFE_CONSUMERS = frozenset({
    "grep", "egrep", "fgrep", "head", "tail", "sort", "uniq", "wc", "cut", "tr", "column", "nl", "cat", "less", "more",
    "tee", "rev", "fold", "fmt", "comm",
})
# パスを省くと作業ディレクトリを再帰的に走査するコマンド
ALWAYS_RECURSIVE = frozenset({"rg", "ag", "ack"})
# heredoc の開始。<<EOF、<<-EOF、<<'EOF'、<<"EOF"、<<\EOF の形を受ける（<<< は here-string なので除く）
HEREDOC_OPENER = re.compile(r"<<(?!<)(-?)\s*(\\?)(['\"]?)([^\s'\"<>;&|()]+)\3")
SUBSTITUTION_MARK = re.compile(r"__SUBST(\d+)__")
# コマンド置換を解析できなかったときに、ホームを指しうる書き方
HOME_REFERENCES = re.compile(r"(?:^|[\s=@:])~(?:/|\s|$)|\bHOME\b")


def resolve_home() -> str:
    """HOME が空でも判定できるよう、アカウントのホームへ倒す。"""
    return os.environ.get("HOME") or pwd.getpwuid(os.getuid()).pw_dir


def expand_variables(text: str, home: str, variables=None) -> str:
    """同じコマンドの中で代入した変数、$HOME（判定に使うホーム）、フックの環境の値の順に展開する。"""
    for name, value in (variables or {}).items():
        text = re.sub(r"\$\{" + name + r"\}|\$" + name + r"(?![A-Za-z0-9_])", lambda _: value, text)
    return os.path.expandvars(HOME_VARIABLE.sub(lambda _: home, text))


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


def glob_to_regex(pattern: str) -> str:
    """gitignore 形式（**・*・?）のパターンを、パス全体に当てる正規表現にする。"""
    out, index = [], 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            out.append(".*")
            index += 2
        elif pattern[index] == "*":
            out.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(pattern[index]))
            index += 1
    return "^" + "".join(out) + "$"


@functools.lru_cache(maxsize=None)
def deny_patterns(home: str) -> tuple:
    """テンプレートの Read(...) の deny を、ホームを展開した正規表現にする。~/ と // の形だけを扱う。"""
    rules = json.loads(SETTINGS_TEMPLATE.read_text(encoding="utf-8"))["permissions"]["deny"]
    patterns = []
    for rule in rules:
        match = DENY_READ_RULE.match(rule)
        if not match:
            continue
        pattern = match.group(1)
        if pattern.startswith("~/"):
            pattern = home + pattern[1:]
        elif pattern.startswith("//"):
            pattern = pattern[1:]
        else:
            continue
        patterns.append(re.compile(glob_to_regex(pattern)))
    return tuple(patterns)


def is_denied(path: str, home: str) -> bool:
    """要求されたパスか、その実体が deny の一覧に当たるか。"""
    candidates = {os.path.normpath(path), os.path.realpath(path)}
    return any(p.match(c) for p in deny_patterns(home) for c in candidates)


def is_owner_only_file(path: str) -> bool:
    st = os.stat(path)
    return stat.S_ISREG(st.st_mode) and stat.S_IMODE(st.st_mode) & 0o077 == 0


def classify(path: str, home: str, cwd: str) -> str:
    """allow・block・unknown のどれかを返す。ディレクトリは、対象範囲にあれば中を走査されうるので止める。"""
    requested = expand(path, home, cwd)
    if is_denied(requested, home):
        return BLOCK
    target = os.path.realpath(requested)
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


# ---- Bash ----

def is_secret_name(name: str) -> bool:
    return bool(SECRET_NAME_PARTS.intersection(name.upper().split("_")))


def secret_variable(text: str):
    """名前が secret らしい変数の参照があれば、その名前を返す。"""
    return next((m.group(1) for m in VARIABLE_REFERENCE.finditer(text) if is_secret_name(m.group(1))), None)


def strip_heredoc_bodies(command: str):
    """heredoc の本文と終端行を取り除く。開始行の残り（&& の後のコマンドなど）は残す。

    戻り値は (本文を除いたコマンド, (本文, 区切り語を引用したか) の一覧)。終端が見つからない heredoc は、そのまま残す。
    """
    bodies, result, position = [], [], 0
    for opener in HEREDOC_OPENER.finditer(command):
        if opener.start() < position:
            continue
        line_end = command.find("\n", opener.end())
        if line_end < 0:
            continue
        terminator = re.compile(r"^\t*" + re.escape(opener.group(4)) + r"[ \t]*$", re.MULTILINE)
        end = terminator.search(command, line_end + 1)
        if not end:
            continue
        result.append(command[position:opener.start()])
        result.append(command[opener.end():line_end])
        quoted = bool(opener.group(2) or opener.group(3))
        bodies.append((command[line_end + 1:end.start()], quoted))
        position = end.end()
    result.append(command[position:])
    return "".join(result), bodies


def _construct_end(command: str, index: int):
    """index から始まる引用・置換の終わりの次の位置を返す。閉じていなければ None。

    扱うもの: '...'、$'...'（ANSI-C。\\' はエスケープ）、"..."、`...`、$(...)・<(...)（入れ子と、中の引用符を追う）。
    """
    if command.startswith("$'", index):
        position = index + 2
        while position < len(command):
            if command[position] == "\\":
                position += 2
            elif command[position] == "'":
                return position + 1
            else:
                position += 1
        return None
    char = command[index]
    if char == "'":
        close = command.find("'", index + 1)
        return None if close < 0 else close + 1
    if char in ('"', "`"):
        position = index + 1
        while position < len(command):
            current = command[position]
            if current == "\\":
                position += 2
            elif current == char:
                return position + 1
            elif char == '"' and (current == "`" or command.startswith("$(", position)):
                position = _construct_end(command, position)
                if position is None:
                    return None
            else:
                position += 1
        return None
    # $( か <(
    depth, position = 1, index + 2
    while position < len(command):
        current = command[position]
        if current == "\\":
            position += 2
        elif current in ("'", '"', "`") or command.startswith(("$'", "$("), position):
            position = _construct_end(command, position)
            if position is None:
                return None
        elif current == "(":
            depth += 1
            position += 1
        elif current == ")":
            depth -= 1
            position += 1
            if depth == 0:
                return position
        else:
            position += 1
    return None


def _starts_substitution(command: str, index: int, heredoc: bool) -> bool:
    if command[index] == "`":
        return True
    if command.startswith("$((", index):
        return False
    return command.startswith("$(", index) or (not heredoc and command.startswith("<(", index))


def extract_substitutions(command: str, known: list, heredoc: bool = False):
    """引用符とエスケープを追いながら、外側の $(...)・`...`・<(...) を __SUBSTn__ へ置き換える。

    単一引用符・ANSI-C クォートの中と、エスケープした文字は置換として扱わない。
    語の頭にある # から行末まではコメントとして除く（bash と同じく、エスケープした空白の後は語の途中とみなす）。
    heredoc=True のときは heredoc の本文として読み、引用符を特別に扱わない。
    入れ子は、本文を判定するときに同じ処理で取り出す。番号は known（外側で取り出し済みの本文）に続けて振る。
    戻り値は (置換後のコマンド, known に足した本文の一覧, 閉じていない引用・置換が残ったか)。
    """
    bodies, out = list(known), []
    index, in_double, at_word_start = 0, False, True
    while index < len(command):
        char = command[index]
        if char == "\\":
            out.append(command[index:index + 2])
            index += 2
            at_word_start = False
            continue
        if not heredoc and not in_double and at_word_start and char == "#":
            newline = command.find("\n", index)
            index = len(command) if newline < 0 else newline
            continue
        if _starts_substitution(command, index, heredoc):
            end = _construct_end(command, index)
            if end is None:
                out.append(command[index:])
                return "".join(out), bodies, True
            opener = 1 if char == "`" else 2
            closer = 1
            bodies.append(command[index + opener:end - closer])
            out.append(f"__SUBST{len(bodies) - 1}__")
            index = end
            at_word_start = False
            continue
        if not heredoc and not in_double and (char == "'" or command.startswith("$'", index)):
            end = _construct_end(command, index)
            if end is None:
                out.append(command[index:])
                return "".join(out), bodies, True
            if char == "$":
                # shlex は ANSI-C クォートを読めないので、中身が同じ二重引用符の文字列に書き換える
                decoded = re.sub(r"\\(.)", lambda m: m.group(1), command[index + 2:end - 1])
                escaped = re.sub(r'(["\\$`\\\\])', r"\\\1", decoded)
                out.append(f'"{escaped}"')
            else:
                out.append(command[index:end])
            index = end
            at_word_start = False
            continue
        if not heredoc and char == '"':
            in_double = not in_double
        out.append(char)
        index += 1
        at_word_start = not in_double and char in WORD_BOUNDARY_CHARS
    return "".join(out), bodies, in_double


def is_separator(token: str) -> bool:
    return bool(token) and set(token) <= SEPARATOR_CHARS


def is_pipe(separator: str) -> bool:
    return separator.strip("\n") in ("|", "|&")


def split_simple_commands(command: str) -> list:
    """(直前の区切り, トークン) の並びに分ける。改行も区切りとして扱い、# はコメントとして扱わない。"""
    lexer = shlex.shlex(command, posix=True, punctuation_chars="();<>|&\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    commands, current, separator = [], [], ""
    for token in lexer:
        if is_separator(token):
            if current:
                commands.append((separator, current))
            current, separator = [], token
        else:
            current.append(token)
    if current:
        commands.append((separator, current))
    return commands


def strip_prefixes(tokens: list) -> list:
    """先頭の VAR=value と、env・sudo・timeout などの包み込むコマンドを外す。"""
    index = 0
    while index < len(tokens):
        word = os.path.basename(tokens[index])
        if ASSIGNMENT.match(tokens[index]):
            index += 1
        elif word in WRAPPERS:
            index += 1
            while index < len(tokens) and (tokens[index].startswith("-") or
                                           (word == "timeout" and DURATION.match(tokens[index]))):
                index += 1
        else:
            break
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


def path_candidates(arg: str) -> list:
    """引数から、パスとして読まれうる部分を取り出す（--opt=x、KEY=x、@x、-fx の x）。"""
    candidates = [] if arg.startswith("-") else [arg]
    if "=" in arg:
        candidates.append(arg.split("=", 1)[1])
    if arg.startswith("-") and not arg.startswith("--") and len(arg) > 2 and "=" not in arg:
        candidates.append(arg[2:])
    return [c[1:] if c.startswith("@") else c for c in candidates if c]


def judge_arg(arg: str, home: str, cwd, cwd_guarded: bool, interpreter: bool = False, variables=None) -> str:
    """1つの引数を判定する。cwd が None なのは、解決できない cd の後。"""
    arg = expand_variables(arg, home, variables)
    # ~user の形は展開先を確かめられないので止める
    if arg.startswith("~") and arg != "~" and not arg.startswith("~/"):
        return BLOCK
    base = cwd or "/"
    if CODE_LIKE.search(arg):
        # 空白を含むパスは、実在すればパスとして判定する。実在しなければコードや文として扱う
        if os.path.lexists(expand(arg, home, base)):
            return BLOCK if classify(arg, home, base) != ALLOW else ALLOW
        # コードとして実行されるときだけ、中に書かれたパスを読みうる。それ以外は文（コミットメッセージなど）
        return BLOCK if interpreter and looks_guarded(arg, home) else ALLOW
    if "$" in arg or "`" in arg:
        return BLOCK if looks_guarded(arg, home) else ALLOW
    if cwd is None and not (arg.startswith("/") or arg.startswith("~")):
        return BLOCK if cwd_guarded else ALLOW
    if GLOB_CHARS.search(arg):
        matches = glob.glob(expand(arg, home, base))
        if not matches:
            return BLOCK if looks_guarded(arg, home) or guarded_area(expand(arg, home, base), home) else ALLOW
        return BLOCK if any(classify(m, home, base) != ALLOW for m in matches) else ALLOW
    verdict = classify(arg, home, base)
    return BLOCK if verdict == UNKNOWN else verdict


def is_metadata_command(name: str, args: list) -> bool:
    if name == "find":
        return not FIND_OUTPUT_ACTIONS.intersection(args)
    return name in METADATA_COMMANDS


def searches_cwd_recursively(name: str, args: list) -> bool:
    """パスを省いて、作業ディレクトリを再帰的に走査するか。"""
    positional = [a for a in args if not a.startswith("-")]
    if name in ALWAYS_RECURSIVE:
        return len(positional) <= 1
    if name == "git" and positional[:1] == ["grep"]:
        return len(positional) <= 2
    recursive = any(a in ("--recursive", "--dereference-recursive") or
                    (a.startswith("-") and not a.startswith("--") and ("r" in a or "R" in a)) for a in args)
    return name == "grep" and recursive and len(positional) <= 1


def is_names_only_view(tokens: list) -> bool:
    """env の出力から変数名だけを取り出す `cut -d= -f1` か。"""
    stripped = strip_prefixes(tokens)
    if not stripped or os.path.basename(stripped[0]) != "cut":
        return False
    # -d= と -f1 だけを許す（-d = や -f 1 と分けた書き方も受ける）。それ以外の引数があれば値が出うる
    joined = " ".join(stripped[1:])
    return joined in ("-d= -f1", "-f1 -d=", "-d = -f 1", "-f 1 -d =", "-d= -f 1", "-f 1 -d=", "-d = -f1", "-f1 -d =")


def dumps_environment(tokens: list) -> bool:
    """環境変数を値ごと一覧で出すか（引数なしの env・printenv・set、export -p など）。"""
    if not tokens:
        return False
    name = os.path.basename(tokens[0])
    args, _ = split_redirects(tokens[1:])
    names = [t for t in args if not t.startswith("-")]
    if name == "env":
        return not [t for t in names if not ASSIGNMENT.match(t)]
    if name == "printenv":
        return not names or any(is_secret_name(t) for t in names)
    if name == "set":
        return not args
    if name in SHELL_DUMPERS:
        return not names or any(is_secret_name(n.split("=", 1)[0]) for n in names if "=" not in n)
    return False


def writes_home(tokens: list) -> bool:
    """HOME へ書き込む形か（HOME=、HOME+=、unset HOME、declare HOME=、printf -v HOME、read HOME など）。"""
    if any(re.match(r"^HOME\+?=", t) for t in tokens):
        return True
    stripped = strip_prefixes(tokens)
    if stripped and os.path.basename(stripped[0]) in HOME_WRITERS and "HOME" in stripped[1:]:
        return True
    return any(t == "-v" and following == "HOME" for t, following in zip(tokens, tokens[1:]))


def is_tightening_chmod(args: list) -> bool:
    """chmod が権限を絞るだけか。モードを解釈できなければ、絞るだけとはみなさない。"""
    mode = next((a for a in args if not a.startswith("-") or re.match(r"^-[rwxXst]+$", a)), "")
    if TIGHTENING_NUMERIC_MODE.match(mode):
        return True
    clauses = mode.split(",") if mode else []
    return bool(clauses) and all(TIGHTENING_SYMBOLIC_CLAUSE.match(c) for c in clauses)


class BashChecker:
    """1つの Bash コマンドを、単純コマンドごとに判定する。同じコマンドの中の cd を追う。"""

    def __init__(self, home: str, cwd: str, substitutions=None, variables=None):
        self.home = home
        self.cwd = cwd
        self.cwd_guarded = False
        self.listed_guarded = False
        self.substitutions = list(substitutions or [])
        self.variables = dict(variables or {})

    def check(self, command: str):
        command, heredocs = strip_heredoc_bodies(command)
        # 区切り語を引用しない heredoc の本文は展開されるので、変数の参照と置換を判定する
        for body, quoted in heredocs:
            if quoted:
                continue
            variable = secret_variable(body)
            if variable:
                return f"heredoc の中で、環境変数 {variable} の値を展開します"
            # heredoc の本文では引用符は特別な意味を持たない。heredoc として読んで置換を取り出す
            _, inner_bodies, unclosed = extract_substitutions(body, [], heredoc=True)
            if unclosed and (looks_guarded(body, self.home) or HOME_REFERENCES.search(body)):
                return "heredoc の中に、解析できない置換とホームを指す書き方があります"
            for inner_body in inner_bodies:
                inner = BashChecker(self.home, self.cwd, [], self.variables)
                if inner.check(inner_body) or inner.listed_guarded:
                    return "heredoc の中のコマンド置換で、secret を含みうる場所を指しています"
        words = {os.path.basename(w) for w in re.split(r"[\s;&|()]+", command) if w}
        if any(INTERPRETER.match(w) for w in words):
            # インタプリタは heredoc の本文をコードとして実行するので、本文に書かれたパスを読みうる
            if any(looks_guarded(expand_variables(b, self.home), self.home) for b, _ in heredocs):
                return "インタプリタに渡す heredoc の中で、secret を含みうる場所を指しています"
            # 区切り語を解析できなかった heredoc は、ホームを指す書き方があれば止める
            if re.search(r"<<(?!<)", command) and (looks_guarded(command, self.home) or HOME_REFERENCES.search(command)):
                return "解析できない heredoc と、ホームを指す書き方が一緒に使われています"
        command, self.substitutions, unclosed = extract_substitutions(command, self.substitutions)
        if unclosed and (
                looks_guarded(expand_variables(command, self.home), self.home) or HOME_REFERENCES.search(command)):
            return "解析できないコマンド置換と、ホームを指す書き方が一緒に使われています"
        commands = split_simple_commands(command)
        for index, (separator, tokens) in enumerate(commands):
            following = commands[index + 1] if index + 1 < len(commands) else None
            reason = self.check_simple(separator, tokens, following)
            if reason:
                return reason
        return None

    def check_substitutions(self, tokens: list):
        """引数に埋め込まれたコマンド置換の中身を、今の作業ディレクトリで判定する。"""
        for token in tokens:
            for mark in SUBSTITUTION_MARK.finditer(token):
                body = self.substitutions[int(mark.group(1))]
                inner = BashChecker(self.home, self.cwd, self.substitutions, self.variables)
                inner.cwd_guarded = self.cwd_guarded
                reason = inner.check(body)
                if reason or inner.listed_guarded:
                    return f"コマンド置換の中で、secret を含みうる場所を指しています（{reason or '一覧'}）"
        return None

    def check_simple(self, separator: str, tokens: list, following):
        if is_pipe(separator) and self.listed_guarded:
            consumer = strip_prefixes(tokens)
            name = os.path.basename(consumer[0]) if consumer else ""
            if name not in SAFE_CONSUMERS:
                return "secret を含みうる場所の一覧を、パイプの後段で開きうるコマンドへ渡しています"
        elif not is_pipe(separator):
            self.listed_guarded = False
        variable = secret_variable(" ".join(tokens))
        if variable:
            return f"環境変数 {variable} の値を出力しうるコマンドです"
        if dumps_environment(tokens) or dumps_environment(strip_prefixes(tokens)):
            names_only = following and is_pipe(following[0]) and is_names_only_view(following[1])
            if not names_only:
                return "環境変数を値ごと一覧で出すコマンドです。名前だけ見るなら env | cut -d= -f1 を使って"
        reason = self.check_substitutions(tokens)
        if reason:
            return reason
        # HOME へ書き込むと、~ や $HOME の展開先が判定の基準とずれるので、どの形でも止める
        if writes_home(tokens):
            return "HOME へ書き込んでいます。判定の基準のホームとずれるので止めます"
        # 代入だけの単純コマンドは、以降のコマンドの変数として覚える。HOME は判定の基準なので上書きさせない。
        # VAR=x cmd のような前置きの代入は、bash が引数を先に展開するので、その引数の判定には使わない
        if all(ASSIGNMENT.match(token) for token in tokens):
            for token in tokens:
                name, value = token.split("=", 1)
                if name != "HOME":
                    self.variables[name] = expand(value, self.home, "") if value.startswith("~") else value
        tokens = strip_prefixes(tokens)
        if not tokens:
            return None
        name = os.path.basename(tokens[0])
        args, sources = split_redirects(tokens[1:])
        # 入力リダイレクトは、どのコマンドでも中身を読む経路になる
        for source in sources:
            if judge_arg(source, self.home, self.cwd, self.cwd_guarded, variables=self.variables) == BLOCK:
                return f"{source} を入力リダイレクトで読もうとしています"
        if name == "cd":
            self.change_directory(args)
            return None
        # まとめたショートオプション（-vf~/.x など）は、どこからがパスか分からないので文字列で判定する
        if any(a.startswith("-") and not a.startswith("--") and
               looks_guarded(expand_variables(a, self.home, self.variables), self.home) for a in args):
            return f"{name} のオプションが、secret を含みうる場所を指しています"
        candidates = [c for arg in args for c in path_candidates(arg)]
        if name == "chmod" and is_tightening_chmod(args):
            return None
        if is_metadata_command(name, args):
            if name not in NON_LISTING_COMMANDS:
                self.listed_guarded = self.listed_guarded or self.touches_guarded(candidates)
            return None
        if searches_cwd_recursively(name, args) and self.cwd_is_guarded():
            return f"{name} が、パスを省いて作業ディレクトリ（secret を含みうる場所）を走査します"
        interpreter = bool(INTERPRETER.match(name))
        for candidate in candidates:
            if judge_arg(candidate, self.home, self.cwd, self.cwd_guarded, interpreter, variables=self.variables) == BLOCK:
                return f"{name} が {candidate} を読もうとしています（secret を含みうる場所）"
        return None

    def change_directory(self, args: list):
        target = expand_variables(next((a for a in args if not a.startswith("-")), "~"), self.home, self.variables)
        if "$" in target or "`" in target or GLOB_CHARS.search(target) or "__SUBST" in target:
            self.cwd, self.cwd_guarded = None, looks_guarded(target, self.home) or "HOME" in target
        elif self.cwd is not None or target.startswith(("/", "~")):
            self.cwd = os.path.realpath(expand(target, self.home, self.cwd or "/"))

    def cwd_is_guarded(self) -> bool:
        if self.cwd is None:
            return self.cwd_guarded
        return classify(self.cwd, self.home, "/") != ALLOW

    def touches_guarded(self, candidates: list) -> bool:
        """中身を出さないコマンドが、対象範囲を指したか。引数が無ければ作業ディレクトリが対象になる。"""
        if not candidates:
            return self.cwd_is_guarded() or (self.cwd is not None and guarded_area(self.cwd, self.home))
        base = self.cwd or "/"
        return any(judge_arg(c, self.home, self.cwd, self.cwd_guarded, variables=self.variables) == BLOCK or
                   guarded_area(expand(expand_variables(c, self.home, self.variables), self.home, base), self.home)
                   for c in candidates)


def check_bash(command: str, home: str, cwd: str):
    """ブロックの理由を返す。許可なら None。"""
    return BashChecker(home, cwd).check(command)


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


def suspicious_after_error(raw: str, data, home: str) -> bool:
    """判定中に例外が出たとき、止めるべきか。対象範囲のパス・ホームの参照・対象範囲の作業ディレクトリを見る。"""
    if looks_guarded(raw, home) or HOME_REFERENCES.search(raw):
        return True
    cwd = data.get("cwd") if isinstance(data, dict) else None
    if not isinstance(cwd, str) or not cwd:
        return False
    real = os.path.realpath(cwd)
    return real == os.path.realpath(home) or guarded_area(real, home)


def main() -> int:
    raw = sys.stdin.read()
    home = resolve_home()
    data = None
    try:
        data = json.loads(raw)
        reason = decide(data, home)
    except Exception as error:
        if suspicious_after_error(raw, data, home):
            return block(f"入力を判定できませんでした（{type(error).__name__}）。対象範囲を指しうるので止めます")
        return 0
    return block(reason) if reason else 0


if __name__ == "__main__":
    sys.exit(main())
