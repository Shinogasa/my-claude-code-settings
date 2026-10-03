#!/usr/bin/env python3
"""PreToolUse(Bash)フック: 確定的に危険なコマンドをブロックする。

対象は3種類。

  1. 状況に依存せず常にNG (rm -rf / , git reset --hard)
  2. 実行環境を見れば確定的に有害と判定できるもの
     (git の --no-verify, 保護ブランチへの直接コミット,
      保護ブランチへの force push と削除)
  3. 操作自体は正当だが、エージェントが自律的に行ってよいものではないもの
     (terraform state の書き換え、state の中身を平文で出す操作)

3 は 1 と意味が違う。「やってはいけない」ではなく「人間が判断して実行すべき」。
禁止ではなく実行主体の指定なので、メッセージでは端末での実行を案内する。

3 の判定だけ allowlist にしている (読み取り系を通し、残りを止める)。terraform が
state サブコマンドを追加したとき、denylist では新しい書き換え操作が黙って通るが、
allowlist なら新しい読み取り操作が誤ってブロックされる。前者は気づけないが
後者は使った瞬間に分かるので、壊れ方として後者を選んだ。

2 を後から追加した経緯: 本リポジトリは PUBLIC で、pre-commit フックが公開履歴への
機密混入を止めている (README「禁止パターン検査」参照)。AI が --no-verify で自動的に
迂回できると、その機構は存在しないのと同じになる。当初この種の判断は対象外としていたが、
守るべき機構が実在するようになったため分類が変わった。

ただし検証フックが無いリポジトリではスキップする対象自体が存在しないため素通しする。
このフックはグローバル (~/.claude/hooks/) で全プロジェクトに効くので、無条件に
ブロックすると無関係なリポジトリで摩擦を生み、結局フックごと無効化されて逆効果になる。
「常にNG」ではなく「環境を見れば確定」なので、判定には cwd を使う。

保護ブランチ (main / master) への直接コミットも 2 に含める。CLAUDE.md に
「作業前にブランチを切る」と書いてあったが、散文の指示は守らなくても何も起きないため
強制力が無かった。コミット時点で止めれば作業内容は未コミットのまま残るので、
`git switch -c` するだけで復帰できる (作業のやり直しは発生しない)。
初回コミット (unborn branch) と detached HEAD は、切るべき作業ブランチが
存在しない・既に名前付きブランチ上にないため対象外。

判定対象のリポジトリは、PreToolUse が渡す cwd を起点に、同じコマンド内の `cd` と
`git -C` を順に適用して決める。cwd は前回までの cd に追従するが、同じコマンド内の
cd は反映されないため、ここで追う。相対パスは hook プロセスの cwd ではなく、この起点から解決する。

cd を信じすぎると、実際のコミット先ではない場所で判定して素通しする。そのため判定対象は
「シェルがいる可能性のあるディレクトリの集合」で持ち、どれか1つでも保護ブランチなら止める。
- cd の直後が `&&` なら、後続は cd が成功したときだけ走るため、集合を移動先に置き換える
- それ以外の cd は効かない可能性があるため、移動前の候補も残す
- `&&` の連鎖が切れたら（`;`、`||`、`|`、`&`、改行、括弧）、それまでに通りうる
  ディレクトリすべてを候補に戻す（`cd x && false; git commit` で cd が失敗した場合など）
- 移動先が今は存在しない場合は、同じコマンド内で作られうるため確定できないとみなす
- 移動先を文字列から確定できない cd / `git -C`（変数、glob、ブレース、`cd -`、`~-`、
  `-P` などのオプション、CDPATH が効きうる相対パス、pushd / popd）の後に git commit /
  --no-verify がある場合は、推測で判定せず止めて `git -C <path>` を案内する。
  止めるのは commit / --no-verify を含むときだけに絞る（範囲を広げると hook ごと外される）
- `git -C` は文字列上で正規化せず git に解決させ、複数指定は累積する
- 判定の前に、リダイレクト、先頭の `NAME=value`、前置き（time / exec / nohup / command /
  builtin / env）、予約語（! / if / then / do / { など）を取り除く

既知の限界: `bash -c '...'` や `"$(...)"` の中のような入れ子のシェル、`GIT_DIR` などの
環境変数による対象の差し替え、引用符で名前を隠した CDPATH の設定は追わない。

コマンド文字列全体への正規表現マッチではなく、シェルの引用規則を
尊重してトークン化した上で、各サブコマンドの先頭トークン(コマンド名)
と引数トークンを見て判定する。これにより、コミットメッセージや
テストデータの中に"rm -rf /"のような文字列が引用符付きで
含まれているだけのケースを誤検知しない。
"""
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

HEREDOC_RE = re.compile(r"<<[-~]?\s*['\"]?(\w+)['\"]?.*?\n.*?\n\1\b", re.DOTALL)
OPERATOR_CHARS = "|&;()<>\n"
# 引用符の中の演算子文字を、トークン化の間だけ私用領域の文字へ退避する対応表。
MASK_TABLE = {ord(c): 0xE000 + i for i, c in enumerate(OPERATOR_CHARS)}
UNMASK_TABLE = {value: key for key, value in MASK_TABLE.items()}
OPERATOR_SET = set(OPERATOR_CHARS)
# 直後の # がコメントの始まりになる文字。`)` は語の途中（$(...)#）でありうるため含めない。
COMMENT_START_AFTER = set(" \t\r") | (OPERATOR_SET - {")"})


class Operator(str):
    """引用符の外にあった演算子トークン。引用符付きの `">"` などの引数と区別する。"""
SEPARATOR_CHARS = set(";&|\n()")
# リダイレクト演算子。直後のトークン（宛先）と、直前の fd 番号もコマンドから除く。
REDIRECT_CHARS = set("<>")
REDIRECT_OPS = {">", ">>", "<", "<<", "<<<", "&>", "&>>", ">&", "<&", ">|", "<>"}
# 後ろに実際のコマンドが続く前置き・予約語。判定前に取り除く。
PREFIX_WORDS = {"time", "exec", "nohup", "command", "builtin", "env", "!",
                "if", "then", "elif", "else", "while", "until", "do", "{", "}"}
ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# --no-verify を受け付ける git サブコマンド
NO_VERIFY_SUBCOMMANDS = {"commit", "merge", "push"}
# 値を伴う git のグローバルオプション (サブコマンド探索時に2トークン読み飛ばす)
GIT_GLOBAL_OPTS_WITH_VALUE = {
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path",
}
# 存在すれば --no-verify のスキップ対象となる検証フック
VERIFICATION_HOOKS = ("pre-commit", "commit-msg", "prepare-commit-msg", "pre-push")
# 直接コミットを止めるブランチ
PROTECTED_BRANCHES = {"main", "master"}
# state を読むだけのサブコマンド。これ以外の state 操作はエージェントに実行させない。
# denylist ではなく allowlist にしているのは、terraform が state サブコマンドを
# 追加したときの壊れ方を選ぶため。denylist だと新しい書き換え操作が黙って通るが、
# allowlist なら新しい読み取り操作が誤ってブロックされる (気づける失敗になる)。
TERRAFORM_STATE_READONLY = {"list", "show", "pull"}
# サブコマンドごとの影響範囲。allowlist のため未知のサブコマンドも来る。
TERRAFORM_STATE_IMPACT = {
    "rm": "指定したリソースを state から外します。terraform の管理対象から消えるため、"
          "次の apply で重複作成されるか、放置されて課金だけが残ります。",
    "push": "state を丸ごと差し替えます。差分ではなく全体の置き換えなので、"
            "取り違えると管理下の全リソースが一度に管理外になります。",
    "mv": "state 上のアドレスを付け替えます。取り違えると、"
          "別のリソースを指したまま apply が走ります。",
    "replace-provider": "state 内の provider 参照を一括で書き換えます。",
}
TERRAFORM_STATE_DEFAULT_IMPACT = (
    "state を書き換える可能性があります。"
    "このガードは読み取り系 (list / show / pull) 以外を既定で止めます。"
)

# state の中身を平文で出力する state サブコマンド。state を壊さないため
# 書き換え判定では拾えないが、出力はファイル・ターミナル・会話ログに
# 複製として残るため、実行主体は同じく人間にする。
TERRAFORM_STATE_EXPOSING = {"pull"}
# サブコマンドごとの「付いていても機微な値を出さない」フラグ。
# -json / -raw を止める denylist にすると、terraform が新しい出力形式を
# 追加したとき黙って通る。allowlist なら新しいフラグは止まる側に入る。
TERRAFORM_SAFE_FLAGS = {
    "output": {"no-color", "state"},
    "show": {"no-color"},
}
# terraform 自体のグローバルオプション。サブコマンドのフラグと混同しない。
TERRAFORM_GLOBAL_FLAGS = {"chdir", "help", "version"}
GIT_TIMEOUT_SEC = 3
# 解析できないコマンドのうち、止める対象になりうる語。含まなければ従来どおり通す。
UNPARSEABLE_RISK_RE = re.compile(
    r"\b(git|commit|push|reset|rm|terraform|dd)\b|--no-verify|/dev/|(^|[\s;&|(])-n\b")
# cd の移動先を確定できないことを表す。空文字列（判定対象なし）とは区別する。
UNRESOLVED = None
# hook がシェルと同じ展開をできない文字。含む cd の移動先は確定できないとみなす。
UNEXPANDABLE_CHARS = set("$`*?[{")

RM_FLAG_RE = re.compile(r"^-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*$|^-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*$")
RM_TARGET_RE = re.compile(r"^(/|~)$|^/\*$")
DEV_TARGET_RE = re.compile(r"^/dev/sd[a-z]")
# force push を表すフラグ。完全一致で "--force" と "-f" だけを見ていた頃は、
# --force-with-lease / --force-with-lease=<ref>:<oid> / -uf が素通りしていた。
# git が force 系のオプションを増やしても拾えるよう、長い方は接頭辞で判定する。
# 誤ってブロックする側の失敗は使った瞬間に気づけるが、素通しは気づけない。
#
# フラグを見るだけでは足りない。refspec の先頭 "+" (git push origin +main) も
# force update であり、フラグを一切使わずに保護ブランチを上書きできる。
FORCE_PUSH_FLAG_RE = re.compile(r"^--force|^-[a-zA-Z]*f[a-zA-Z]*$")
# push のフラグのうち値を次のトークンに取るもの。読み飛ばさないと
# 値 (`-o main`) を refspec と取り違えて判定対象を誤る。
GIT_PUSH_OPTS_WITH_VALUE = {"-o", "--push-option", "--receive-pack", "--exec", "--repo"}
# 対象 ref を1つに絞れないフラグ。保護ブランチを含みうるため特定不能として扱う。
GIT_PUSH_BROADCAST_FLAGS = {"--all", "--branches", "--mirror"}
# ref の削除を表すフラグ。短縮形は他のフラグと束ねられる (-du) ため綴りで拾う。
# 削除も refspec 側に別経路がある (`git push origin :main`)。
REF_DELETE_FLAG_RE = re.compile(r"^--delete$|^-[a-zA-Z]*d[a-zA-Z]*$")


def strip_heredocs(command: str) -> str:
    """ヒアドキュメント本体(実行されないテキスト)を空文字に置換する。"""
    return HEREDOC_RE.sub("", command)


def strip_line_continuations(command: str) -> str:
    """バックスラッシュ+改行 (シェルの行継続) を除去し、論理行を1行にまとめる。

    shlex の posix モードは `\\<改行>` を「エスケープされた改行文字」として
    次のトークンにそのまま含めてしまい (`git` が `'\\ngit'` のように壊れる)、
    シェルの「行継続 = 何も無かったことにする」という意味論と食い違う。
    このズレにより `git ... && \\\n git commit ...` のような複数行コマンドで
    先頭トークンが `git` と一致しなくなり、以降の判定全体が素通りしていた。
    """
    return command.replace("\\\n", "")


def tokenize_command(command: str):
    """シェルの引用規則を尊重してコマンド全体をトークン化する。パース不能なら None。

    空リストに畳むと「検査するものが無い」と区別できず素通しになるため、None で返す。

    改行を whitespace から外して punctuation_chars に回すことで、裸の改行
    (クォート外・コマンド置換の外にあるもの) を独立トークンとして残す。
    行ごとに shlex へ渡すと、ヒアドキュメントを取り除いた結果クォートや
    コマンド置換の閉じ括弧が次の行に落ちるケース (`"$(cat <<'EOF' ... EOF\n)"` 等)
    で引用符が閉じないままパース不能になり、コマンド全体の検査が素通りしていた。
    """
    lexer = shlex.shlex(
        # コメントを先に取り除く。行継続を先に畳むと、コメント末尾の \ が次の行を飲み込む。
        strip_line_continuations(mask_quoted_operators(command)),
        posix=True, punctuation_chars=OPERATOR_CHARS)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    # コメントは退避の段階でシェルと同じ規則（語の先頭の # だけ）で取り除く。
    # shlex の既定は語の途中の # もコメントとみなし、後ろのコマンドを落とす。
    lexer.commenters = ""
    try:
        # 退避後も演算子文字だけでできたトークンは、引用符の外にあった本物の演算子。
        return [Operator(tok) if set(tok) <= OPERATOR_SET else tok.translate(UNMASK_TABLE)
                for tok in lexer]
    except ValueError:
        return None


def mask_quoted_operators(command: str) -> str:
    """引用符・バックスラッシュの中にある演算子文字を私用領域の文字へ退避する。

    posix モードの shlex は引用符を外したトークンを返すため、`-m ">"` の `>` と
    リダイレクトの `>` を区別できない。shlex に渡す前に退避し、トークン化の後で戻す。
    """
    result = []
    quote = ""
    escaped = False
    in_comment = False
    previous = ""
    for char in command:
        if in_comment:
            # 引用符の追跡をずらさないよう、コメントの中身は捨てる
            if char == "\n":
                in_comment = False
                result.append(char)
                previous = char
            continue
        # `)` の直後は $(...)# のように語の途中でありうるため、コメントの始まりにしない。
        if not quote and not escaped and char == "#" and (
                previous == "" or previous in COMMENT_START_AFTER):
            in_comment = True
            continue
        if escaped:
            # 行継続の改行は後段で取り除くため、退避せずに残す
            result.append(char if char == "\n" else char.translate(MASK_TABLE))
            escaped = False
            # エスケープされた空白は語の一部。直後の # をコメントにしない。
            previous = "\\"
            continue
        previous = char
        if char == "\\" and quote != "'":
            escaped = True
            result.append(char)
            continue
        if quote:
            if char == quote:
                quote = ""
                result.append(char)
            else:
                result.append(char.translate(MASK_TABLE))
            continue
        if char in "'\"":
            quote = char
        result.append(char)
    return "".join(result)


def is_separator(tok: str) -> bool:
    """制御演算子・改行・括弧だけでできたトークンか。

    shlex は `&&\n` や `;(` のような記号の連続を1トークンにまとめるため、
    完全一致だけで判定すると後ろのコマンドが前のコマンドに飲み込まれる。
    """
    return isinstance(tok, Operator) and bool(tok) and set(tok) <= SEPARATOR_CHARS


def split_glued_operator(tok: str) -> list:
    """`;>` のように区切りとリダイレクトが1トークンにまとまったものを分ける。"""
    if not isinstance(tok, Operator) or tok in REDIRECT_OPS or not set(tok) & REDIRECT_CHARS:
        return [tok]
    index = min(tok.index(c) for c in REDIRECT_CHARS if c in tok)
    separator, redirect = tok[:index], tok[index:]
    return [Operator(part) for part in (separator, redirect) if part]


def strip_redirections(tokens: list) -> list:
    """リダイレクト演算子・宛先・fd 番号を除く。コマンド名の位置を正しく見るため。"""
    result = []
    skip_next = False
    for tok in tokens:
        if skip_next:
            skip_next = False
            continue
        if isinstance(tok, Operator) and set(tok) & REDIRECT_CHARS:
            if result and result[-1].isdigit():
                result.pop()
            skip_next = True
            continue
        result.append(tok)
    return result


def strip_prefixes(tokens: list) -> list:
    """先頭の `NAME=value`・前置き（time / env など）・予約語を除いた実際のコマンドを返す。"""
    index = 0
    while index < len(tokens):
        tok = tokens[index]
        if ASSIGNMENT_RE.match(tok):
            index += 1
            continue
        if tok in PREFIX_WORDS:
            index += 1
            # env / command / time のオプション（-i、-p など）も読み飛ばす
            while tok in ("env", "command", "time") and index < len(tokens) \
                    and tokens[index].startswith("-"):
                index += 1
            continue
        break
    return tokens[index:]


def normalize_command(tokens: list) -> list:
    return strip_prefixes(strip_redirections(tokens))


def split_with_operators(tokens: list) -> list:
    """単純コマンドごとに (直前の区切り, 前処理後のトークン列, 直後の区切り, 元のトークン列) を返す。

    元のトークン列は、リダイレクト先を見る検査（ブロックデバイスへの書き込み）に使う。
    """
    expanded = [part for tok in tokens for part in split_glued_operator(tok)]
    commands = []
    previous = ""
    current = []
    for tok in expanded:
        if is_separator(tok):
            if current:
                commands.append([previous, normalize_command(current), tok, current])
                current = []
                previous = tok
            else:
                previous += tok
        else:
            current.append(tok)
    if current:
        commands.append([previous, normalize_command(current), "", current])
    return [tuple(command) for command in commands if command[1] or command[3]]


def split_simple_commands(tokens: list) -> list:
    """制御演算子・改行・括弧でトークン列を単純コマンド列に分割する。"""
    return [command for _, command, _, _ in split_with_operators(tokens) if command]


def is_dangerous(tokens: list) -> bool:
    if not tokens:
        return False

    if tokens[0] == "rm":
        has_rf_flag = any(RM_FLAG_RE.match(t) for t in tokens[1:])
        has_danger_target = any(RM_TARGET_RE.match(t) for t in tokens[1:])
        if has_rf_flag and has_danger_target:
            return True

    if tokens[0] == "git":
        # tokens[1] の直接比較ではなく extract_subcommand を通す。
        # `git -C path reset --hard` のようにグローバルオプションを挟まれると
        # 直接比較では素通りするため。
        subcommand, args = extract_subcommand(tokens)
        if subcommand == "reset" and "--hard" in args:
            return True

    for i, tok in enumerate(tokens[:-1]):
        if tok == ">" and DEV_TARGET_RE.match(tokens[i + 1]):
            return True

    return False


def terraform_state_write(tokens: list) -> str:
    """state を書き換える terraform 操作ならサブコマンド名を返す。該当しなければ空文字列。

    terraform のグローバルオプション (-chdir=DIR 等) はサブコマンドの前に置かれ、
    サブコマンドの引数のフラグ (-backup=PATH 等) は後ろに置かれる。
    どちらもハイフン始まりなので、まとめて除いた残りを語の並びとして見る。

    サブコマンドが無い `terraform state` は usage を出すだけなので対象外。
    """
    if not tokens or tokens[0] != "terraform":
        return ""

    words = [t for t in tokens[1:] if not t.startswith("-")]
    if len(words) < 2 or words[0] != "state":
        return ""

    subcommand = words[1]
    return "" if subcommand in TERRAFORM_STATE_READONLY else subcommand


def terraform_flag_names(tokens: list) -> set:
    """フラグ名を取り出す。-json / --json / -state=path を同じ名前として扱う。"""
    return {
        token.lstrip("-").split("=", 1)[0]
        for token in tokens if token.startswith("-")
    }


def terraform_secret_exposure(tokens: list) -> str:
    """state の中身を平文で出す terraform 操作なら、その形を返す。該当しなければ空文字列。

    state を書き換えないので terraform_state_write では拾えないが、
    機密性の観点では読み取りの方が危害そのものになる。
    """
    if not tokens or tokens[0] != "terraform":
        return ""

    words = [t for t in tokens[1:] if not t.startswith("-")]
    if not words:
        return ""

    if words[0] == "state":
        subcommand = words[1] if len(words) > 1 else ""
        return f"state {subcommand}" if subcommand in TERRAFORM_STATE_EXPOSING else ""

    safe_flags = TERRAFORM_SAFE_FLAGS.get(words[0])
    if safe_flags is None:
        return ""

    unsafe = terraform_flag_names(tokens[1:]) - safe_flags - TERRAFORM_GLOBAL_FLAGS
    if not unsafe:
        return ""
    return words[0] + " " + " ".join("-" + name for name in sorted(unsafe))


def extract_subcommand(tokens: list) -> tuple:
    """git のグローバルオプションを読み飛ばしてサブコマンドと残り引数を返す。

    `git -C path commit --no-verify` のような形を正しく解釈するために必要。
    サブコマンドが見つからなければ (None, []) を返す。
    """
    i = 1
    while i < len(tokens):
        token = tokens[i]
        if token in GIT_GLOBAL_OPTS_WITH_VALUE:
            i += 2
            continue
        if token.startswith("-"):
            i += 1
            continue
        return token, tokens[i + 1:]
    return None, []


def is_verification_bypass(tokens: list) -> bool:
    """git の検証フックをスキップするコマンドか判定する。"""
    if not tokens or tokens[0] != "git":
        return False

    subcommand, args = extract_subcommand(tokens)
    if subcommand not in NO_VERIFY_SUBCOMMANDS:
        return False

    if "--no-verify" in args:
        return True

    # -n は commit でのみ --no-verify の別名。push では --dry-run を意味するため
    # 一律に扱うと安全側のつもりで誤検知になる。
    return subcommand == "commit" and "-n" in args


def resolve_path(base, path: str, cdpath_possible: bool = False):
    """base から path へ移動した先を返す。文字列から確定できなければ UNRESOLVED。

    絶対パスは base に依存しないため、base が UNRESOLVED でも解決する。
    """
    if path == "-" or any(c in path for c in UNEXPANDABLE_CHARS):
        return UNRESOLVED
    if path.startswith("~") and path != "~" and not path.startswith("~/"):
        return UNRESOLVED
    expanded = os.path.expanduser(path)
    if os.path.isabs(expanded):
        return expanded
    if base is UNRESOLVED:
        return UNRESOLVED
    # CDPATH は ./ ../ で始まらない相対パスにだけ効く。値は hook から見えない。
    explicit = expanded in (".", "..") or expanded.startswith(("./", "../"))
    if cdpath_possible and not explicit:
        return UNRESOLVED
    return os.path.join(base, expanded)


def cd_target_paths(tokens: list):
    """cd の引数から移動先の文字列を1つ返す。解釈できなければ UNRESOLVED。"""
    arguments = tokens[1:]
    if arguments and arguments[0] == "--":
        arguments = arguments[1:]
    elif any(token.startswith("-") and token != "-" for token in arguments):
        return UNRESOLVED
    if not arguments:
        return "~"
    if len(arguments) > 1:
        return UNRESOLVED
    return arguments[0]


def operator_kind(op: str) -> str:
    """区切りを分類する。

    START（先頭）/ AND（&&）/ SEQ（; と改行。前の結果によらず次が走る）/
    BREAK（||、|、&、括弧。次が走らない、または別のシェルで走る）。
    """
    if op == "":
        return "START"
    if op.strip("\n") == "&&":
        return "AND"
    if set(op) <= {";", "\n"}:
        return "SEQ"
    return "BREAK"


def apply_directory_change(previous_op: str, tokens: list, next_op: str, candidates: set,
                           cdpath_possible: bool) -> set:
    """単純コマンドを実行した後に、シェルがいる可能性のあるディレクトリの集合を返す。

    cd 自体が必ず実行され（直前が先頭・&&・;）、直後が `&&` なら、後続は cd が成功したとき
    だけ走るため移動先に置き換える。`||` の後やパイプの中の cd は実行されない、または
    別のシェルで走るため、移動前の候補も残す。
    移動先が今は存在しない（同じコマンド内で作られうる）場合は確定できないとみなす。
    """
    if not tokens or tokens[0] not in ("cd", "pushd", "popd"):
        return candidates
    if tokens[0] != "cd":
        return candidates | {UNRESOLVED}
    path = cd_target_paths(tokens)
    moved = set()
    for base in candidates:
        target = UNRESOLVED if path is UNRESOLVED else resolve_path(base, path, cdpath_possible)
        if target is not UNRESOLVED:
            # bash の既定（論理パス）に合わせて `..` は文字列上で畳む。-P は確定できない扱い。
            target = os.path.normpath(target)
        if target is UNRESOLVED or not os.path.isdir(target):
            moved |= {base, UNRESOLVED}
        else:
            moved.add(target)
    runs_in_this_shell = operator_kind(previous_op) in ("START", "AND", "SEQ")
    if runs_in_this_shell and operator_kind(next_op) == "AND":
        return moved
    return candidates | moved


def git_dash_c_paths(tokens: list) -> list:
    """`git -C <path>` の path を指定順にすべて返す。git は複数の -C を累積して解釈する。"""
    paths = []
    i = 1
    while i < len(tokens):
        token = tokens[i]
        if token == "-C" and i + 1 < len(tokens):
            paths.append(tokens[i + 1])
            i += 2
            continue
        if token in GIT_GLOBAL_OPTS_WITH_VALUE:
            i += 2
            continue
        if token.startswith("-"):
            i += 1
            continue
        break
    return paths


def git_target_dirs(tokens: list, candidates: set) -> set:
    """git コマンドが操作しうるディレクトリの集合を返す。

    `-C` は文字列上で正規化せず、そのまま連結して git（カーネル）に解決させる。
    symlink を含む `link/..` を文字列で畳むと、実際の移動先とずれる。
    """
    targets = set()
    for base in candidates:
        current = base
        for path in git_dash_c_paths(tokens):
            current = resolve_path(current, path)
            if current is UNRESOLVED:
                break
        if current is not UNRESOLVED and not os.path.isdir(current):
            # 同じコマンド内で作られた場所を指しうる。今の状態では判定できない。
            current = UNRESOLVED
        targets.add(current)
    return targets


def is_git_commit(tokens: list) -> bool:
    if not tokens or tokens[0] != "git":
        return False
    subcommand, _ = extract_subcommand(tokens)
    return subcommand == "commit"


def run_git(cwd: str, *args: str) -> str:
    """git コマンドの標準出力を返す。失敗時は空文字列。"""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True, text=True, timeout=GIT_TIMEOUT_SEC,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def protected_branch(cwd: str) -> str:
    """cwd が保護ブランチ上にあればその名前を返す。対象外なら空文字列。

    git リポジトリでない場合と detached HEAD の場合は symbolic-ref が失敗するため
    自然に空文字列になる。まだ1つもコミットが無いリポジトリは、そもそも作業ブランチを
    切りようがないので対象から外す (初回コミットを止めても行き場が無い)。
    """
    branch = run_git(cwd, "symbolic-ref", "--short", "HEAD")
    if branch not in PROTECTED_BRANCHES:
        return ""
    if not run_git(cwd, "rev-parse", "--verify", "HEAD"):
        return ""
    return branch


def push_positional_args(args: list) -> list:
    """push のフラグを読み飛ばして位置引数 (remote, refspec...) を返す。"""
    positional = []
    i = 0
    while i < len(args):
        token = args[i]
        if token in GIT_PUSH_OPTS_WITH_VALUE:
            i += 2
            continue
        if token.startswith("-"):
            i += 1
            continue
        positional.append(token)
        i += 1
    return positional


def is_force_push(args: list) -> bool:
    """push の引数が force update を含むか。フラグと refspec の "+" の両方を見る。"""
    if any(FORCE_PUSH_FLAG_RE.match(a) for a in args):
        return True
    # 位置引数の先頭は remote。refspec はその後ろ。
    return any(spec.startswith("+") for spec in push_positional_args(args)[1:])


def push_target_branches(args: list, cwd: str, has_command_line_config: bool = False) -> list:
    """push が書き換えるリモート側のブランチ名を返す。特定できなければ None。

    None は「安全」ではなく「検査できなかった」を表す。呼び出し側でブロックへ倒す。
    cwd が UNRESOLVED でも、宛先を明示した refspec だけなら判定できる。
    """
    if any(a in GIT_PUSH_BROADCAST_FLAGS for a in args):
        return None

    positional = push_positional_args(args)
    refspecs = positional[1:]
    if not refspecs:
        # refspec 省略時の宛先は push.default 依存だが、既定 (simple/current) では
        # 同名のブランチ。detached HEAD や git 管理外では特定できない。
        # `git -c push.default=...` のような設定は、フックが照会する git config に現れない
        if cwd is UNRESOLVED or has_command_line_config:
            return None
        if not implicit_push_targets_current_branch(cwd, positional[:1]):
            return None
        branch = run_git(cwd, "symbolic-ref", "--short", "HEAD")
        return [branch] if branch else None

    targets = []
    for spec in refspecs:
        # glob は複数のブランチへ展開されるため、名前の一致では判定できない
        if "*" in spec:
            return None
        dst = spec.lstrip("+")
        if ":" in dst:
            dst = dst.split(":", 1)[1]
            # `:` / `+:` は matching push で、両側にある全ブランチへ向かう。`src:` も宛先を確定できない
            if not dst:
                return None
        if dst.startswith("refs/heads/"):
            dst = dst[len("refs/heads/"):]
        elif dst == "@" or dst.startswith(("refs/", "heads/")):
            # `@` や `heads/main` は保護ブランチを指しうる。正規化はせず、確定できない形として止める
            return None
        if dst in ("", "HEAD"):
            if cwd is UNRESOLVED:
                return None
            branch = run_git(cwd, "symbolic-ref", "--short", "HEAD")
            if not branch:
                return None
            dst = branch
        targets.append(dst)
    return targets


def git_config_lookup(cwd: str, *args: str):
    """git config の照会結果を返す。未設定は ""、照会できなかったときは None。

    run_git は失敗を "" に畳むため、未設定（exit 1）と照会の失敗を区別できない。
    失敗を未設定として扱うと「検査できなかった」を「問題なし」に畳むことになる。
    """
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "config", *args],
            capture_output=True, text=True, timeout=GIT_TIMEOUT_SEC,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode == 0:
        return result.stdout.strip()
    if result.returncode == 1:
        return ""
    return None


def implicit_push_targets_current_branch(cwd: str, remote: list) -> bool:
    """refspec を省略した push が、現在のブランチと同名の宛先だけへ向かうと言えるか。

    push.default が upstream / matching / tracking のとき、remote.<name>.push があるとき、
    remote.<name>.mirror が有効なときは、同名でないブランチ（保護ブランチを含む）へ push されうる。
    設定を照会できなかったときも、言えないものとして扱う。
    """
    push_default = git_config_lookup(cwd, "--get", "push.default")
    if push_default is None or push_default not in ("", "simple", "current"):
        return False
    # remote を省略すると、どの remote へ向かうかは branch の設定次第なので、全 remote を見る
    name = re.escape(remote[0]) if remote else ".*"
    for key in ("push", "mirror"):
        found = git_config_lookup(cwd, "--get-regexp", rf"^remote\.{name}\.{key}$")
        if found is None or found:
            return False
    return True


def is_ref_deletion(args: list) -> bool:
    """push の引数がリモート ref の削除を含むか。フラグと `:dst` 形式の両方を見る。"""
    if any(REF_DELETE_FLAG_RE.match(a) for a in args):
        return True
    # 位置引数の先頭は remote。refspec はその後ろ。
    return any(spec.startswith(":") for spec in push_positional_args(args)[1:])


def has_git_config_option(tokens: list) -> bool:
    """サブコマンドより前に `-c` / `--config-env` があるか。値の中身は問わない。"""
    i = 1
    while i < len(tokens):
        token = tokens[i]
        if not token.startswith("-"):
            return False
        if token.startswith(("-c", "--config-env")):
            return True
        i += 2 if token in GIT_GLOBAL_OPTS_WITH_VALUE else 1
    return False


def destructive_push(tokens: list, candidates: set) -> tuple:
    """リモートの ref を破壊的に動かす push なら (種別, 理由) を返す。該当しなければ ("", "")。

    種別は "force" / "delete"。どちらも ref を fast-forward 以外の方向へ動かす点で
    同じ危険度を持つため、判定と方針を揃える。

    保護ブランチ以外は通す。未マージの自ブランチを rebase / amend してから上書きする
    用途や、マージ済みブランチを片付ける用途は正当で、塞ぐと
    「履歴に残したくないものが残る」「作業ブランチが溜まり続ける」方へ倒れる。
    保護ブランチは、上書き・削除されると他人のコミットが失われ、
    reflog も操作した本人の手元にしか無いため復旧経路が無い。
    """
    if not tokens or tokens[0] != "git":
        return "", ""

    subcommand, args = extract_subcommand(tokens)
    if subcommand != "push":
        return "", ""

    # 削除を先に見る。`git push --delete` は force フラグを伴わないことが多いが、
    # 併用された場合も削除として扱うのが実際の影響に近い。
    if is_ref_deletion(args):
        kind = "delete"
    elif is_force_push(args):
        kind = "force"
    else:
        return "", ""

    # commit と同じく、シェルがいる可能性のあるディレクトリすべてで宛先を求める
    protected = set()
    for directory in git_target_dirs(tokens, candidates):
        targets = push_target_branches(args, directory, has_git_config_option(tokens))
        if targets is None:
            return kind, "対象のブランチを特定できません"
        protected |= {t for t in targets if t in PROTECTED_BRANCHES}
    protected = sorted(protected)
    if protected:
        return kind, f"保護ブランチ ({', '.join(protected)}) が対象です"
    return "", ""


def verification_hooks_active(cwd: str) -> bool:
    """cwd の git リポジトリに、実際にスキップ対象となる検証フックがあるか。

    git リポジトリでない場合や検証フックが無い場合は False (＝ブロックしない)。
    """
    git_dir = run_git(cwd, "rev-parse", "--absolute-git-dir")
    if not git_dir:
        return False

    hooks_path = run_git(cwd, "config", "--get", "core.hooksPath")
    if hooks_path:
        base = Path(hooks_path)
        if not base.is_absolute():
            # core.hooksPath の相対パスはリポジトリのトップレベル基準
            toplevel = run_git(cwd, "rev-parse", "--show-toplevel")
            if not toplevel:
                return False
            base = Path(toplevel) / base
    else:
        base = Path(git_dir) / "hooks"

    # .sample は git が実行しないため、拡張子なしの正確な名前のみを見る
    return any(
        (base / name).is_file() and os.access(base / name, os.X_OK)
        for name in VERIFICATION_HOOKS
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    command = payload.get("tool_input", {}).get("command", "")
    if not command:
        return 0

    executable_part = strip_heredocs(command)
    cwd = payload.get("cwd") or os.getcwd()

    bypass_dirs = set()
    commit_dirs = set()
    candidates = {os.path.abspath(cwd)}
    # これまでに通りうるディレクトリすべて。&& の連鎖が切れたら、どこにいてもおかしくない。
    seen = set(candidates)
    cdpath_possible = "CDPATH" in command or bool(os.environ.get("CDPATH"))
    tokens = tokenize_command(executable_part)
    if tokens is None:
        # 解析できないなら判定もできない。対象になりうる語を含むときだけ止める。
        if UNPARSEABLE_RISK_RE.search(executable_part):
            print("ブロック: コマンドを解析できないため、安全か判定できません。", file=sys.stderr)
            print("  引用符の組み合わせ（$'...' や \"$(...)\" の中の引用符など）を単純にして、",
                  file=sys.stderr)
            print("  コマンドを分けて実行し直してください。", file=sys.stderr)
            return 2
        return 0
    for previous_op, simple_command, next_op, raw_command in split_with_operators(tokens):
        if operator_kind(previous_op) in ("SEQ", "BREAK"):
            candidates = set(seen)
        candidates = apply_directory_change(
            previous_op, simple_command, next_op, candidates, cdpath_possible)
        seen |= candidates
        if is_dangerous(simple_command) or is_dangerous(raw_command):
            print(f"ブロック: 確定的に危険なコマンドを検出しました: {command}", file=sys.stderr)
            return 2
        state_write = terraform_state_write(simple_command)
        if state_write:
            impact = TERRAFORM_STATE_IMPACT.get(
                state_write, TERRAFORM_STATE_DEFAULT_IMPACT)
            print(f"ブロック: terraform state {state_write} は state を書き換えます。",
                  file=sys.stderr)
            print(f"  {impact}", file=sys.stderr)
            print("  remote backend では自動バックアップが作られないため、backend 側に",
                  file=sys.stderr)
            print("  versioning が無い場合は復旧できません。", file=sys.stderr)
            print("  操作自体は正当ですが、影響範囲の判断が要るため AI では実行しません。",
                  file=sys.stderr)
            print("  必要な場合は、あなた自身が端末で実行してください。", file=sys.stderr)
            return 2
        exposure = terraform_secret_exposure(simple_command)
        if exposure:
            print(f"ブロック: terraform {exposure} は state の中身を平文で出力します。",
                  file=sys.stderr)
            print("  state は DB パスワード・秘密鍵・トークンを平文で保持します",
                  file=sys.stderr)
            print("  (sensitive = true は表示の抑制であって、state の暗号化ではありません)。",
                  file=sys.stderr)
            print("  出力はファイル・ターミナル・会話ログに複製として残り、", file=sys.stderr)
            print("  消しても複製が残る場所があります。", file=sys.stderr)
            print("  必要な場合は、あなた自身が端末で実行してください。", file=sys.stderr)
            return 2
        kind, reason = destructive_push(simple_command, candidates)
        if kind:
            label = "リモートブランチの削除" if kind == "delete" else "force push"
            print(f"ブロック: この{label}は{reason}。", file=sys.stderr)
            if kind == "delete":
                print("  削除された ref はリモートに残りません。復旧できるのは、"
                      "同じコミットを持つ手元のクローンがある場合だけです。",
                      file=sys.stderr)
                print("  保護ブランチ以外の削除は通ります。対象を明示してください:",
                      file=sys.stderr)
                print("      git push origin --delete <feature-branch>", file=sys.stderr)
            else:
                print("  上書きされたコミットは、上書きした本人の reflog にしか残りません。",
                      file=sys.stderr)
                print(f"  保護ブランチ以外への{label}は通ります。対象を明示してください:",
                      file=sys.stderr)
                print("      git push --force-with-lease origin <feature-branch>",
                      file=sys.stderr)
            print(f"  保護ブランチを対象にする必要がある場合は、"
                  "あなた自身が端末で実行してください。", file=sys.stderr)
            return 2
        if is_verification_bypass(simple_command):
            bypass_dirs |= git_target_dirs(simple_command, candidates)
        if is_git_commit(simple_command):
            commit_dirs |= git_target_dirs(simple_command, candidates)

    if UNRESOLVED in bypass_dirs or UNRESOLVED in commit_dirs:
        print("ブロック: git commit の対象リポジトリを特定できません。", file=sys.stderr)
        print("  同じコマンド内の cd の移動先（変数、cd -、コマンド置換、pushd / popd）を",
              file=sys.stderr)
        print("  文字列から確定できないため、保護ブランチと検証フックを判定できません。",
              file=sys.stderr)
        print("  対象を明示して実行し直してください:", file=sys.stderr)
        print("      git -C <リポジトリのパス> commit ...", file=sys.stderr)
        return 2

    # git config の参照は毎回の Bash 呼び出しに載せたくないため、
    # 該当コマンドが実際にあったときだけリポジトリを調べる。
    if any(verification_hooks_active(target) for target in sorted(bypass_dirs)):
        print("ブロック: git の検証フックをスキップしようとしています (--no-verify)。",
              file=sys.stderr)
        print("  このリポジトリには検証フックが設定されています。", file=sys.stderr)
        print("  フックは公開リポジトリへの機密混入を防ぐために置かれているため、", file=sys.stderr)
        print("  AI による自動スキップは行いません。", file=sys.stderr)
        print("  フックの指摘内容を修正してからコミットしてください。", file=sys.stderr)
        print("  意図的に回避する必要がある場合は、あなた自身が端末で実行してください。",
              file=sys.stderr)
        return 2

    for target in sorted(commit_dirs):
        branch = protected_branch(target)
        if branch:
            print(f"ブロック: 保護ブランチ ({branch}) への直接コミットです。", file=sys.stderr)
            print("  作業ブランチを切ってからコミットしてください:", file=sys.stderr)
            print("      git switch -c <branch-name>", file=sys.stderr)
            print("  未コミットの変更はブランチ作成後もそのまま引き継がれるため、", file=sys.stderr)
            print("  作業をやり直す必要はありません。", file=sys.stderr)
            print(f"  {branch} へ直接コミットする必要がある場合は、"
                  "あなた自身が端末で実行してください。", file=sys.stderr)
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
