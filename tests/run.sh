#!/bin/bash
# テストを実行する。既定はsetup.shを実際に実行する遅いテストを除き、並列で流す。
# 並列化にはuvの一時環境でpytest-xdistを使い、システムやdotfilesへは何も入れない（ADR 0029）。

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# 1件ごとにsetup.shを実行し、全体の実行時間の大半を占めるテスト
SLOW_FILES=(tests/test_setup_cli.py tests/test_setup_preflight.py)
PYTEST_DEPS=(--with "pytest==9.1.1" --with "pytest-xdist==3.8.0")
INCLUDE_SLOW=false
DRY_RUN=false

usage() {
  echo "Usage: bash tests/run.sh [--all] [--dry-run]" >&2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --all) INCLUDE_SLOW=true ;;
    --dry-run) DRY_RUN=true ;;
    *) usage; exit 2 ;;
  esac
  shift
done

is_slow() {
  local file="$1" slow
  for slow in "${SLOW_FILES[@]}"; do
    [ "$file" = "$slow" ] && return 0
  done
  return 1
}

cd "$ROOT"

# pytestはサブディレクトリのfixtureまで集めるので、unittest discoverと同じく直下のtest_*.pyだけを渡す
FILES=()
for file in tests/test_*.py; do
  if [ "$INCLUDE_SLOW" = false ] && is_slow "$file"; then
    continue
  fi
  FILES+=("$file")
done

if command -v uv >/dev/null 2>&1; then
  COMMAND=(uv run --no-project --python python3 "${PYTEST_DEPS[@]}"
    python3 -m pytest -n auto -p no:cacheprovider -q -W error::ResourceWarning "${FILES[@]}")
else
  echo "注意: uv が見つからないため、並列化せずに unittest で順に実行します。" >&2
  MODULES=()
  for file in "${FILES[@]}"; do
    module="${file%.py}"
    MODULES+=("${module//\//.}")
  done
  COMMAND=(python3 -W error::ResourceWarning -m unittest "${MODULES[@]}")
fi

if [ "$DRY_RUN" = true ]; then
  echo "${COMMAND[*]}"
  exit 0
fi

if [ "$INCLUDE_SLOW" = false ]; then
  exec "${COMMAND[@]}"
fi

# PR作成時のhook（hooks/require-full-tests-before-pr.py）が、このファイル名と目印を見る
TESTS_ALL_PASSED_STAMP="tests-all-passed"

# 追跡中のファイルに未コミットの変更が無ければHEADを返す。あれば何も返さない
clean_head() {
  git diff --quiet HEAD -- 2>/dev/null || return 0
  git rev-parse HEAD 2>/dev/null || true
}

STARTED_AT="$(clean_head)"
STATUS=0
"${COMMAND[@]}" || STATUS=$?
if [ "$STATUS" -ne 0 ]; then
  exit "$STATUS"
fi

if [ -n "$STARTED_AT" ] && [ "$(clean_head)" = "$STARTED_AT" ]; then
  echo "$STARTED_AT" > "$(git rev-parse --git-path "$TESTS_ALL_PASSED_STAMP")"
  echo "全件の通過を記録した: $STARTED_AT" >&2
else
  echo "注意: 未コミットの変更があったか、実行中にHEADが変わったため、全件の通過は記録しない。" >&2
fi
