#!/bin/bash
# Claude Code 個人設定のシンボリックリンクセットアップ
# 冪等：何度実行しても安全

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
BACKUP_DIR="$CLAUDE_DIR/backups/$(date +%Y%m%d_%H%M%S)"

# シンボリックリンク対象の定義
# 形式: "リポジトリ内パス:リンク先パス"
TARGETS=(
  "CLAUDE.md:$CLAUDE_DIR/CLAUDE.md"
  "skills:$CLAUDE_DIR/skills"
  "commands:$CLAUDE_DIR/commands"
  "rules:$CLAUDE_DIR/rules"
  "statusline.js:$CLAUDE_DIR/statusline.js"
  "output-styles:$CLAUDE_DIR/output-styles"
  "agents:$CLAUDE_DIR/agents"
  "hooks:$CLAUDE_DIR/hooks"
  "claude-code-best-practice:$CLAUDE_DIR/claude-code-best-practice"
)

# 色付き出力
green() { printf "\033[32m%s\033[0m\n" "$1"; }
yellow() { printf "\033[33m%s\033[0m\n" "$1"; }
red() { printf "\033[31m%s\033[0m\n" "$1"; }

echo "=== Claude Code 設定セットアップ ==="
echo "リポジトリ: $SCRIPT_DIR"
echo "リンク先:   $CLAUDE_DIR"
echo ""

# ~/.claude/ の存在確認
if [ ! -d "$CLAUDE_DIR" ]; then
  red "エラー: $CLAUDE_DIR が存在しません。Claude Code を一度起動してください。"
  exit 1
fi

# git submodule の初期化・更新
echo "=== git submodule 初期化 ==="
if [ -f "$SCRIPT_DIR/.gitmodules" ]; then
  (cd "$SCRIPT_DIR" && git submodule update --init --recursive)
  green "✓ submodule を初期化しました"
else
  yellow "スキップ: .gitmodules が見つかりません"
fi
echo ""

backup_created=false

for target in "${TARGETS[@]}"; do
  src_rel="${target%%:*}"
  dest="${target##*:}"
  src="$SCRIPT_DIR/$src_rel"

  # リポジトリ内にソースが存在するか確認
  if [ ! -e "$src" ]; then
    red "スキップ: $src_rel （リポジトリ内に存在しません）"
    continue
  fi

  # 既に正しいシンボリックリンクが張られている場合
  if [ -L "$dest" ]; then
    current_target="$(readlink "$dest")"
    if [ "$current_target" = "$src" ]; then
      green "✓ $src_rel → $dest （リンク済み）"
      continue
    else
      # 別の場所を指すシンボリックリンクがある場合は削除して再作成
      yellow "  更新: $dest （旧リンク先: $current_target）"
      rm "$dest"
    fi
  elif [ -e "$dest" ]; then
    # 実ファイル/ディレクトリが存在する場合はバックアップ
    if [ "$backup_created" = false ]; then
      mkdir -p "$BACKUP_DIR"
      backup_created=true
    fi
    yellow "  バックアップ: $dest → $BACKUP_DIR/$src_rel"
    mv "$dest" "$BACKUP_DIR/$src_rel"
  fi

  # シンボリックリンク作成
  ln -s "$src" "$dest"
  green "✓ $src_rel → $dest （新規作成）"
done

# === settings.json テンプレート生成 ===
echo ""
echo "=== settings.json 生成 ==="

TEMPLATE="$SCRIPT_DIR/settings.json.template"
SETTINGS_DEST="$CLAUDE_DIR/settings.json"
ENV_FILE="$SCRIPT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
  yellow "警告: .env が見つかりません。settings.json の生成をスキップします。"
  yellow "  → cp .env.example .env して値を設定してください。"
else
  # 環境変数をロード
  set -a
  source "$ENV_FILE"
  set +a

  # 必須項目の検証
  if [ -z "${ANTHROPIC_AUTH_TOKEN:-}" ]; then
    red "エラー: ANTHROPIC_AUTH_TOKEN が設定されていません。"
    exit 1
  fi

  # 既存 settings.json のバックアップ
  if [ -f "$SETTINGS_DEST" ] && [ ! -L "$SETTINGS_DEST" ]; then
    if [ "$backup_created" = false ]; then
      mkdir -p "$BACKUP_DIR"
      backup_created=true
    fi
    yellow "  バックアップ: $SETTINGS_DEST → $BACKUP_DIR/settings.json"
    cp "$SETTINGS_DEST" "$BACKUP_DIR/settings.json"
  fi

  # テンプレートから settings.json を生成
  if command -v envsubst > /dev/null 2>&1; then
    envsubst < "$TEMPLATE" > "$SETTINGS_DEST"
  else
    yellow "envsubst が見つかりません。sed で代替します。"
    cp "$TEMPLATE" "$SETTINGS_DEST"
    sed -i '' \
      -e "s|\${ANTHROPIC_BASE_URL}|${ANTHROPIC_BASE_URL}|g" \
      -e "s|\${ANTHROPIC_AUTH_TOKEN}|${ANTHROPIC_AUTH_TOKEN}|g" \
      -e "s|\${ANTHROPIC_MODEL}|${ANTHROPIC_MODEL}|g" \
      -e "s|\${CLAUDE_CODE_SUBAGENT_MODEL}|${CLAUDE_CODE_SUBAGENT_MODEL}|g" \
      -e "s|\${CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS}|${CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS}|g" \
      "$SETTINGS_DEST"
  fi

  # JSON検証
  if python3 -m json.tool "$SETTINGS_DEST" > /dev/null 2>&1; then
    green "✓ settings.json を生成しました → $SETTINGS_DEST"
  else
    red "エラー: 生成された settings.json が不正なJSONです。"
    cat "$SETTINGS_DEST"
    exit 1
  fi

  # === settings.ollama.json テンプレート生成（任意） ===
  OLLAMA_TEMPLATE="$SCRIPT_DIR/settings.ollama.json.template"
  OLLAMA_SETTINGS_DEST="$CLAUDE_DIR/settings.ollama.json"

  if [ -z "${OLLAMA_BASE_URL:-}" ]; then
    yellow "スキップ: settings.ollama.json（.env に OLLAMA_BASE_URL が未設定）"
  else
    if [ -f "$OLLAMA_SETTINGS_DEST" ] && [ ! -L "$OLLAMA_SETTINGS_DEST" ]; then
      if [ "$backup_created" = false ]; then
        mkdir -p "$BACKUP_DIR"
        backup_created=true
      fi
      yellow "  バックアップ: $OLLAMA_SETTINGS_DEST → $BACKUP_DIR/settings.ollama.json"
      cp "$OLLAMA_SETTINGS_DEST" "$BACKUP_DIR/settings.ollama.json"
    fi

    if command -v envsubst > /dev/null 2>&1; then
      envsubst < "$OLLAMA_TEMPLATE" > "$OLLAMA_SETTINGS_DEST"
    else
      cp "$OLLAMA_TEMPLATE" "$OLLAMA_SETTINGS_DEST"
      sed -i '' \
        -e "s|\${OLLAMA_BASE_URL}|${OLLAMA_BASE_URL}|g" \
        -e "s|\${OLLAMA_AUTH_TOKEN}|${OLLAMA_AUTH_TOKEN}|g" \
        -e "s|\${OLLAMA_MODEL}|${OLLAMA_MODEL}|g" \
        "$OLLAMA_SETTINGS_DEST"
    fi

    if python3 -m json.tool "$OLLAMA_SETTINGS_DEST" > /dev/null 2>&1; then
      green "✓ settings.ollama.json を生成しました → $OLLAMA_SETTINGS_DEST"
    else
      red "エラー: 生成された settings.ollama.json が不正なJSONです。"
      cat "$OLLAMA_SETTINGS_DEST"
      exit 1
    fi
  fi
fi

# === learning-journal.md を PRIVATE 実体へ symlink 集約 ===
# 学習ログの実体は cw-workspace-local (PRIVATE) 側に一元化する。
# 本リポジトリは PUBLIC のため業務ナレッジを含む journal を追跡してはならない
# (.gitignore 済み)。ここでは実体への symlink を張り、ホストからの参照性だけ確保する。
# 実体が無い環境 (cw-workspace-local 未 clone のマシン) では何もしない。
echo ""
echo "=== learning-journal.md 集約 ==="

consolidate_learning_journal() {
  local journal_src="$HOME/garage/cw-workspace-local/tasks/learning-journal.md"
  local journal_dest="$SCRIPT_DIR/tasks/learning-journal.md"

  # 実体 (集約先) が存在しない環境ではスキップ (冪等ガード)
  if [ ! -f "$journal_src" ]; then
    yellow "スキップ: cw-workspace-local の実体が見つかりません ($journal_src)"
    return
  fi

  mkdir -p "$(dirname "$journal_dest")"

  # 既に正しい symlink ならスキップ
  if [ -L "$journal_dest" ]; then
    if [ "$(readlink "$journal_dest")" = "$journal_src" ]; then
      green "✓ tasks/learning-journal.md → 実体 (リンク済み)"
      return
    fi
    yellow "  更新: tasks/learning-journal.md （旧リンク先: $(readlink "$journal_dest")）"
    rm "$journal_dest"
  elif [ -f "$journal_dest" ]; then
    # 実ファイルが残っている場合はバックアップしてから symlink へ置換
    if [ "$backup_created" = false ]; then
      mkdir -p "$BACKUP_DIR"
      backup_created=true
    fi
    mkdir -p "$BACKUP_DIR/tasks"
    yellow "  バックアップ: $journal_dest → $BACKUP_DIR/tasks/learning-journal.md"
    mv "$journal_dest" "$BACKUP_DIR/tasks/learning-journal.md"
  fi

  ln -s "$journal_src" "$journal_dest"
  green "✓ tasks/learning-journal.md → $journal_src （新規作成）"
}

consolidate_learning_journal

echo ""
echo "=== 完了 ==="

if [ "$backup_created" = true ]; then
  yellow "バックアップ先: $BACKUP_DIR"
fi

# 結果を表示
echo ""
echo "現在のシンボリックリンク状態:"
for target in "${TARGETS[@]}"; do
  dest="${target##*:}"
  if [ -L "$dest" ]; then
    echo "  $dest -> $(readlink "$dest")"
  elif [ -e "$dest" ]; then
    echo "  $dest （通常ファイル/ディレクトリ）"
  else
    echo "  $dest （存在しません）"
  fi
done
