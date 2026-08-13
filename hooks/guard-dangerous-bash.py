#!/usr/bin/env python3
"""PreToolUse(Bash)フック: 確定的に危険なコマンドをブロックする。

対象は3種類。

  1. 状況に依存せず常にNG (rm -rf / , git push --force , git reset --hard)
  2. 実行環境を見れば確定的に有害と判定できるもの (git の --no-verify, 保護ブランチ)
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

既知の限界: 判定には PreToolUse が渡す cwd と `git -C` の値を使う。
`cd other-repo && git commit` のようにコマンド内でディレクトリを移動された場合、
移動先を追跡しないため検出できない。--no-verify 判定も同じ制約を持つ。

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
CONTROL_TOKENS = {";", "&&", "||", "|", "&"}

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

RM_FLAG_RE = re.compile(r"^-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*$|^-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*$")
RM_TARGET_RE = re.compile(r"^(/|~)$|^/\*$")
DEV_TARGET_RE = re.compile(r"^/dev/sd[a-z]")


def strip_heredocs(command: str) -> str:
    """ヒアドキュメント本体(実行されないテキスト)を空文字に置換する。"""
    return HEREDOC_RE.sub("", command)


def tokenize_command(command: str) -> list:
    """シェルの引用規則を尊重してコマンド全体をトークン化する。パース不能なら空リスト。

    改行を whitespace から外して punctuation_chars に回すことで、裸の改行
    (クォート外・コマンド置換の外にあるもの) を独立トークンとして残す。
    行ごとに shlex へ渡すと、ヒアドキュメントを取り除いた結果クォートや
    コマンド置換の閉じ括弧が次の行に落ちるケース (`"$(cat <<'EOF' ... EOF\n)"` 等)
    で引用符が閉じないままパース不能になり、コマンド全体の検査が素通りしていた。
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars="|&;()<>\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return []


def split_simple_commands(tokens: list) -> list:
    """制御演算子(; && || | & および裸の改行)でトークン列を単純コマンド列に分割する。"""
    commands = []
    current = []
    for tok in tokens:
        if tok in CONTROL_TOKENS or (tok and set(tok) <= {"\n"}):
            if current:
                commands.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        commands.append(current)
    return commands


def is_dangerous(tokens: list) -> bool:
    if not tokens:
        return False

    if tokens[0] == "rm":
        has_rf_flag = any(RM_FLAG_RE.match(t) for t in tokens[1:])
        has_danger_target = any(RM_TARGET_RE.match(t) for t in tokens[1:])
        if has_rf_flag and has_danger_target:
            return True

    if tokens[0] == "git":
        if len(tokens) >= 2 and tokens[1] == "push" and ("--force" in tokens or "-f" in tokens):
            return True
        if len(tokens) >= 2 and tokens[1] == "reset" and "--hard" in tokens:
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


def git_dash_c_path(tokens: list) -> str:
    """`git -C <path>` の path を返す。指定が無ければ空文字列。

    サブコマンドより後ろの -C は git のグローバルオプションではないため、
    サブコマンドに到達した時点で探索を打ち切る。
    """
    i = 1
    while i < len(tokens):
        token = tokens[i]
        if token == "-C" and i + 1 < len(tokens):
            return tokens[i + 1]
        if token in GIT_GLOBAL_OPTS_WITH_VALUE:
            i += 2
            continue
        if token.startswith("-"):
            i += 1
            continue
        break
    return ""


def commit_target_dir(tokens: list, cwd: str) -> str:
    """git commit ならブランチ判定に使うディレクトリを返す。commit でなければ空文字列。"""
    if not tokens or tokens[0] != "git":
        return ""

    subcommand, _ = extract_subcommand(tokens)
    if subcommand != "commit":
        return ""

    return git_dash_c_path(tokens) or cwd


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

    has_bypass = False
    commit_dirs = []
    tokens = tokenize_command(executable_part)
    for simple_command in split_simple_commands(tokens):
        if is_dangerous(simple_command):
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
        if is_verification_bypass(simple_command):
            has_bypass = True
        target = commit_target_dir(simple_command, cwd)
        if target:
            commit_dirs.append(target)

    # git config の参照は毎回の Bash 呼び出しに載せたくないため、
    # 該当コマンドが実際にあったときだけリポジトリを調べる。
    if has_bypass and verification_hooks_active(cwd):
        print("ブロック: git の検証フックをスキップしようとしています (--no-verify)。",
              file=sys.stderr)
        print("  このリポジトリには検証フックが設定されています。", file=sys.stderr)
        print("  フックは公開リポジトリへの機密混入を防ぐために置かれているため、", file=sys.stderr)
        print("  AI による自動スキップは行いません。", file=sys.stderr)
        print("  フックの指摘内容を修正してからコミットしてください。", file=sys.stderr)
        print("  意図的に回避する必要がある場合は、あなた自身が端末で実行してください。",
              file=sys.stderr)
        return 2

    for target in commit_dirs:
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
