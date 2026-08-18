#!/bin/bash
# SessionStart フック: 同一リポジトリ・同一作業ディレクトリで動いている
# 他の Claude セッションを検出し、分離の判断材料をコンテキストへ注入する。
#
# 通知に留める理由:
#   セッション開始フックからツールは呼べず、できるのは情報の注入まで。
#   作業ディレクトリを機構の判断で動かさない方針を採ったため、
#   誤検出があっても失われるのは注入されたテキスト1件分のコンテキストのみ。
#
# 対象外リポジトリ:
#   エージェント設定リポジトリ自身。~/.claude 配下は絶対パスのリンクで
#   本体の作業ツリーを指すため、worktree 側で rules や hooks を編集しても
#   動作中のエージェントには反映されない。分離するとむしろ壊れる。
#   リポジトリ名はハードコードせず ~/.claude/rules の実体から導出する。
#
# 制約:
#   後から起動したセッションにしか届かない。先に起動していた側は
#   自分の SessionStart を既に通過している。移動すべきなのは後発の方
#   (先発は作業中で中断コストが高い) なので、この非対称性は設計どおり。

set -uo pipefail

cat >/dev/null   # payload は使わないが読み捨てる

# 通知が無いときも空文字列ではなく空の JSON を返す。
# Codex は SessionStart の stdout を JSON として解釈するため、無出力は
# "invalid session start JSON output" として失敗扱いになる (実測)。
# Claude Code は空 JSON を無視するので、両ホストで同じスクリプトが使える。
quiet_exit() {
  printf '{}\n'
  exit 0
}

DETECT="${PARALLEL_SESSIONS_DETECT_CMD:-$HOME/.claude/bin/detect-parallel-sessions}"
EXCLUDE_PATH="${PARALLEL_SESSIONS_EXCLUDE_PATH:-$HOME/.claude/rules}"

[ -x "$DETECT" ] || quiet_exit
command -v git >/dev/null 2>&1 || quiet_exit
command -v jq  >/dev/null 2>&1 || quiet_exit

my_common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || quiet_exit
[ -n "$my_common" ] || quiet_exit

# 対象外判定。リンクの実体からリポジトリを導出するため、別名で配置しても効く。
if [ -e "$EXCLUDE_PATH" ]; then
  exclude_real=$(cd "$EXCLUDE_PATH" 2>/dev/null && pwd -P)
  if [ -n "${exclude_real:-}" ]; then
    exclude_common=$(git -C "$exclude_real" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
    [ "${exclude_common:-}" = "$my_common" ] && quiet_exit
  fi
fi

sessions=$("$DETECT" 2>/dev/null) || quiet_exit
count=$(printf '%s' "$sessions" | jq 'length' 2>/dev/null) || quiet_exit
[ "${count:-0}" -gt 0 ] 2>/dev/null || quiet_exit

pids=$(printf '%s' "$sessions" | jq -r '[.[].pid] | join(", ")' 2>/dev/null) || quiet_exit
cwd=$(pwd -P)
branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "HEAD")

detail="このディレクトリで別の Claude セッションが ${count} 件動いています (pid: ${pids})。
作業ディレクトリ: ${cwd}
現在のブランチ: ${branch}

同じ作業ツリーを共有しているため、片方がブランチを切り替えると、もう片方は
足元が変わったことに気づかないまま作業を続けます。

移動するのは後から始めた側です。編集を始める前に worktree で分離してください
(先に始めた側は作業中で、中断コストが高いため)。

どちらが後発か判断できない場合は、相手のセッションと突き合わせてください。
このフックは自分が後発かどうかを知りません。

分離の手順と、追跡外資産 (サブモジュール・.env・依存パッケージ) の復元については
rules/parallel-worktree.md を参照してください。

読み取りや調査だけで終わるセッションなら分離は不要です。"

jq -n \
  --arg ctx "$detail" '{
    hookSpecificOutput: {
      hookEventName: "SessionStart",
      additionalContext: $ctx
    }
  }'

exit 0
