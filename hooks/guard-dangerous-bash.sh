#!/bin/bash
# PreToolUse(Bash)フック: 確定的に危険なコマンドをブロックする。
# 対象は「状況に依存せず常にNG」なパターンと、「実行環境を見れば確定的に有害」なパターン。
# 後者の例が git の --no-verify で、検証フックが設定されたリポジトリでのみブロックする。
# 判定の詳細と経緯は guard-dangerous-bash.py の docstring を参照。

set -euo pipefail

# 個人用のセッションから会社用の claude / codex を起動させない検査も、ここから呼ぶ（ADR 0036）。
# このラッパーは Claude Code と Codex（codex/hooks.json）の両方から呼ばれるので、設定を変えずに両方へ効く。
hook_dir="$(dirname "$0")"
payload="$(cat)"
printf '%s' "$payload" | python3 "$hook_dir/guard-dangerous-bash.py"
printf '%s' "$payload" | python3 "$hook_dir/guard-agent-profile.py"
