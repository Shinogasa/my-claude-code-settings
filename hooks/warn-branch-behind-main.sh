#!/bin/bash
# PreToolUse(Bash)フック: terraform 実行時に、現在のブランチがリモートの
# デフォルトブランチより遅れていたら知らせる。
#
# 背景:
#   apply 済みの変更が main に入る前に、古い main から派生したブランチで
#   terraform plan を打つと、実在するリソースが「設定に無い」と判定されて
#   destroy 計画が出る。これを本物の差分だと誤認して apply すると、
#   別ブランチで正しく適用したリソースが消える。
#
#   plan の出力だけを見てもマージ漏れとの区別がつかないため、
#   ブランチの位置関係という別の観点から気づけるようにする。
#
# 挙動:
#   terraform の plan/apply/destroy/import/refresh/state のみ対象。
#   apply / destroy はブロックする (deny)。それ以外は警告を出すだけで実行を妨げない。
#
#   強度を apply / destroy に限っているのは、被害が不可逆な操作に合わせたため。
#   ただし state / import も state を書き換えるので、この境界は再検討の余地がある。
#
# 制約:
#   timeout(1) が無い環境があるため、fetch は SSH の ConnectTimeout で縛る。
#   fetch に失敗しても取得済みの ref で判定を続ける（fail-open）。
#   判定できない場合は黙って通す。フック自身が作業を止めないことを優先する。

set -uo pipefail

input=$(cat)
command=$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null) || exit 0

# terraform が「コマンドの位置」に現れる場合だけを対象にする。
# 行頭か、; & | ( の直後（`cd dir && terraform apply` を含む）に限定することで、
# `echo terraform apply is dangerous` のような文字列中の語に反応しない。
tf_prefix='(^|[;&|(])[[:space:]]*terraform[[:space:]]+(-[^[:space:]]+[[:space:]]+)*'

# 状態を変えうるサブコマンドだけを対象にする。fmt / validate / version は巻き込まない。
if ! printf '%s' "$command" | grep -Eq "${tf_prefix}(plan|apply|destroy|import|refresh|state)\b"; then
  exit 0
fi

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

# リモートのデフォルトブランチを解決する。main 固定にすると master 運用で誤作動する。
default_ref=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null)
if [ -z "$default_ref" ]; then
  for candidate in origin/main origin/master; do
    if git rev-parse --verify --quiet "$candidate" >/dev/null 2>&1; then
      default_ref="$candidate"
      break
    fi
  done
fi
[ -n "$default_ref" ] || exit 0

# ローカルの ref が古いと判定を外すため取りに行くが、
# ネットワーク断でセッションを止めないよう接続時間を縛る。
remote_branch="${default_ref#origin/}"
GIT_SSH_COMMAND='ssh -o ConnectTimeout=3 -o BatchMode=yes' \
  git fetch --quiet origin "$remote_branch" >/dev/null 2>&1 || true

behind=$(git rev-list --count "HEAD..${default_ref}" 2>/dev/null) || exit 0
[ "${behind:-0}" -gt 0 ] 2>/dev/null || exit 0

current_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "HEAD")

detail="現在のブランチ '${current_branch}' は ${default_ref} より ${behind} コミット遅れています。
${default_ref} に入っている変更がこのブランチには無いため、terraform はそれらを
「設定に存在しないリソース」とみなし、実在するリソースへの destroy を計画に出すことがあります。
その destroy は本物の差分ではなく、ブランチが古いことによる偽陽性の可能性があります。

確認: git merge origin/${remote_branch}  で取り込んでから plan を取り直してください。"

# apply / destroy は取り返しがつかないためブロックする。
#
# ask ではなく deny にしている理由: ask のプロンプトが出るのは「plan を見て
# 問題ないと判断した後」であり、判断済みの流れの中で確認を求めても覆りにくい。
# 偽陽性の destroy を見抜けなかった人に、同じ情報でもう一度尋ねることになる。
# deny なら判断ではなく状態の変更 (main を取り込んで plan を取り直す) を要求できる。
#
# それ以外（plan 等）は読み取りのみなので警告に留める。plan はむしろ
# 偽陽性に気づくための経路なので、止めると発見が遅れる。
if printf '%s' "$command" | grep -Eq "${tf_prefix}(apply|destroy)\b"; then
  jq -n --arg reason "${detail}

このブランチのまま apply することはできません。次のいずれかで解消してください:
  1. git merge origin/${remote_branch} で取り込み、plan を取り直す
  2. 遅れを承知の上で実行する場合は、あなた自身が端末で実行する" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
else
  jq -n \
    --arg msg "ブランチが ${default_ref} より ${behind} コミット遅れています。plan の destroy は偽陽性の可能性があります。" \
    --arg ctx "$detail" '{
      systemMessage: $msg,
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        additionalContext: $ctx
      }
    }'
fi

exit 0
