#!/bin/bash
# PreToolUse(Bash)フック: 確定的に危険なコマンドをブロックする。
# 対象は「状況に依存せず常にNG」なパターンと、「実行環境を見れば確定的に有害」なパターン。
# 後者の例が git の --no-verify で、検証フックが設定されたリポジトリでのみブロックする。
# 判定の詳細と経緯は guard-dangerous-bash.py の docstring を参照。

set -euo pipefail

cat | python3 "$(dirname "$0")/guard-dangerous-bash.py"
