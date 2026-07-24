#!/bin/bash
# PreToolUse(Bash)フック: 確定的に危険なコマンドをブロックする。
# 対象は「状況に依存せず常にNG」なパターンのみ（--no-verify等の判断が必要なものは対象外）。

set -euo pipefail

cat | python3 "$(dirname "$0")/guard-dangerous-bash.py"
