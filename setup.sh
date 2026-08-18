#!/bin/bash
# Claude Code / Codex CLI 個人設定のシンボリックリンクセットアップ
# 冪等：何度実行しても安全

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
CODEX_DIR="$HOME/.codex"
AGENTS_DIR="$HOME/.agents"  # Agent Skills オープン標準のユーザースコープ
BACKUP_DIR="$CLAUDE_DIR/backups/$(date +%Y%m%d_%H%M%S)"

# テンプレート/生成先のパス。settings.json 生成セクションだけでなく、その手前の
# プラグイン導入セクションも settings.json.template を読むため、ここでまとめて定義する。
BASE_TEMPLATE="$SCRIPT_DIR/settings.json.template"
ENV_TEMPLATE="$SCRIPT_DIR/env.json.template"
SETTINGS_DEST="$CLAUDE_DIR/settings.json"
ENV_FILE="$SCRIPT_DIR/.env"

# シンボリックリンク対象の定義
# 形式: "リポジトリ内パス:リンク先パス"
# 同一ソースを複数ホストへ配る場合はエントリを分けて列挙する。
TARGETS=(
  "CLAUDE.md:$CLAUDE_DIR/CLAUDE.md"
  "skills:$CLAUDE_DIR/skills"
  "commands:$CLAUDE_DIR/commands"
  "rules:$CLAUDE_DIR/rules"
  "statusline.js:$CLAUDE_DIR/statusline.js"
  "output-styles:$CLAUDE_DIR/output-styles"
  "agents:$CLAUDE_DIR/agents"
  "hooks:$CLAUDE_DIR/hooks"
  "bin:$CLAUDE_DIR/bin"
  "claude-code-best-practice:$CLAUDE_DIR/claude-code-best-practice"
)

# 色付き出力
green() { printf "\033[32m%s\033[0m\n" "$1"; }
yellow() { printf "\033[33m%s\033[0m\n" "$1"; }
red() { printf "\033[31m%s\033[0m\n" "$1"; }

echo "=== Claude Code / Codex 設定セットアップ ==="
echo "リポジトリ: $SCRIPT_DIR"
echo ""

# ~/.claude/ の存在確認
if [ ! -d "$CLAUDE_DIR" ]; then
  red "エラー: $CLAUDE_DIR が存在しません。Claude Code を一度起動してください。"
  exit 1
fi

# === Codex CLI 向けリンクの追加 ===
# skills / commands / CLAUDE.md は Claude Code と Codex で同じ形式がそのまま通る。
#   - skills: Agent Skills オープン標準 (name + description の frontmatter)。
#             Codex はスキャン時にシンボリックリンクを追従する
#   - commands: Codex の custom prompts は description / argument-hint の frontmatter が同形式
#   - CLAUDE.md: Codex のグローバル指示は ~/.codex/AGENTS.md
#   - rules: AGENTS.md から `rules/...` の相対参照で辿れるよう同じ階層に置く
# 内容の二重管理を避けるため、単一ソースを両ホストへリンクする。
#
#   - hooks: PreToolUse の payload が Claude Code と同一 (tool_name / tool_input.command / cwd)
#            で、ブロック手段も終了コード2 + stderr で共通。スクリプトをそのまま共有する。
#            参照先を ~/.claude 側にすると Codex 単独マシンで壊れるため、~/.codex 配下に置く
#   - codex/hooks.json: フックの定義そのもの。ユーザーレベルに置くとプロジェクトの
#            trust 状態から独立して効く (プロジェクト配下だと新規リポジトリが無防備で始まる)
#
# agents/ (Codex は config.toml の TOML 定義)、output-styles/ ・ statusline.js ・
# settings.json (Codex に相当機能なし) は形式が違うため対象外。
#
# 導入判定は ~/.codex の有無で行う。未導入マシンに設定ファイルを先回りで生やすと
# Codex 初回起動時の状態が読めなくなるため、無ければ何も作らない。
# 判定結果は TARGETS 自体を伸ばして反映する。別配列に分けると、配線されなかった事実が
# 末尾の「現在のシンボリックリンク状態」サマリーから消えて観測できなくなる。
echo "=== Codex CLI 検出 ==="
if [ -d "$CODEX_DIR" ]; then
  # ~/.agents は Codex が自動生成しないため、ユーザースコープを自前で用意する
  mkdir -p "$AGENTS_DIR"
  TARGETS+=(
    "skills:$AGENTS_DIR/skills"
    "commands:$CODEX_DIR/prompts"
    "rules:$CODEX_DIR/rules"
    "CLAUDE.md:$CODEX_DIR/AGENTS.md"
    "hooks:$CODEX_DIR/hooks"
    "codex/hooks.json:$CODEX_DIR/hooks.json"
  )
  green "✓ $CODEX_DIR を検出しました。Codex 向けリンクも作成します"
  # Codex はフック定義のハッシュに対して trust を記録する。未承認のフックは
  # エラーにならず「スキップ」される (fail-open)。hooks.json を書き換えた直後は
  # 承認が外れた状態になるため、リンクを張っただけでは防御が効かない。
  # 呼び出し先スクリプト (guard-dangerous-bash.py) の編集ではハッシュは変わらない。
  yellow "  注意: Codex 側で /hooks を開き、ガードフックを承認してください"
  yellow "        未承認のフックは黙ってスキップされます (エラーになりません)"
else
  yellow "スキップ: $CODEX_DIR がないため Codex 向けリンクは作成しません"
fi
echo ""

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
      yellow "  更新: $dest （旧リンク先: ${current_target}）"
      rm "$dest"
    fi
  elif [ -e "$dest" ]; then
    # 実ファイル/ディレクトリが存在する場合はバックアップ。
    # 保存名はソース名ではなくリンク先パスから導出する。同一ソースを複数ホストへ配るため、
    # ソース名を使うと ~/.claude/CLAUDE.md と ~/.codex/AGENTS.md のバックアップが
    # どちらも $BACKUP_DIR/CLAUDE.md に落ちて、先に退避した方が黙って上書き消失する。
    backup_path="$BACKUP_DIR/${dest#"$HOME"/}"
    if [ "$backup_created" = false ]; then
      mkdir -p "$BACKUP_DIR"
      backup_created=true
    fi
    mkdir -p "$(dirname "$backup_path")"
    yellow "  バックアップ: $dest → $backup_path"
    mv "$dest" "$backup_path"
  fi

  # シンボリックリンク作成
  ln -s "$src" "$dest"
  green "✓ $src_rel → $dest （新規作成）"
done

# === Claude Code プラグイン導入 ===
# settings.json.template の enabledPlugins は「有効にしろ」という宣言でしかなく、実体の取得は
# しない。実体 (~/.claude/plugins/cache/) と installed_plugins.json はマシンローカルかつ
# 絶対パス込みのため、このリポジトリでは同期できない。
#
# その結果、新しいマシンでは「enabled なのに not cached」になり、プラグインが黙って機能しない
# (実際に別環境で発生した)。宣言と実体の乖離をここで埋める。
#
# 導入対象は settings.json.template から導出する。setup.sh に専用の配列を持つと二重管理になり、
# 「enabledPlugins に足したが導入リストに足し忘れた」が起きる。しかもその状態は、実体が既に
# あるマシンでは何も壊れないため気づけず、別マシンで初めて発症する。
# settings.personal.json のキーを env.json.template から導出しているのと同じ理由。
echo ""
echo "=== Claude Code プラグイン導入 ==="

setup_claude_plugins() {
  if ! command -v claude > /dev/null 2>&1; then
    yellow "スキップ: claude コマンドが PATH にありません"
    return
  fi

  local wanted
  wanted="$(python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    plugins = json.load(f).get('enabledPlugins', {})
# 値が false のものは意図的な無効化なので導入しない
print('\n'.join(k for k, v in plugins.items() if v))
" "$BASE_TEMPLATE")"

  if [ -z "$wanted" ]; then
    yellow "スキップ: settings.json.template に enabledPlugins がありません"
    return
  fi

  local installed
  if ! installed="$(claude plugin list --json 2>/dev/null)"; then
    yellow "スキップ: claude plugin list に失敗しました"
    return
  fi

  local plugin_id
  while IFS= read -r plugin_id; do
    [ -n "$plugin_id" ] || continue

    if printf '%s' "$installed" | python3 -c "
import json, sys
target = sys.argv[1]
sys.exit(0 if any(p.get('id') == target for p in json.load(sys.stdin)) else 1)
" "$plugin_id"; then
      green "✓ $plugin_id （導入済み）"
      continue
    fi

    # 失敗しても setup.sh 全体は止めない。マーケットプレイス未登録が主な失敗要因のため、
    # 復旧コマンドまで出す。黙って続けると「宣言だけあって実体がない」状態に逆戻りする。
    if claude plugin install "$plugin_id" > /dev/null 2>&1; then
      green "✓ $plugin_id （新規導入）"
    else
      red "  失敗: $plugin_id"
      yellow "    マーケットプレイス未登録の可能性があります。次を試してください:"
      yellow "      claude plugin marketplace add anthropics/${plugin_id##*@}"
      yellow "      claude plugin install $plugin_id"
    fi
  done <<< "$wanted"

  yellow "  ※ 導入内容は次回の Claude Code 起動時から有効になります"
}

setup_claude_plugins

# === Codex プラグイン導入 ===
# superpowers は Codex 公式マーケットプレイス (openai-curated) から入れる。
# openai-curated は Codex 自身が同期するスナップショットで、config.toml への marketplace
# 登録は不要 (codex plugin marketplace list に自動で現れる)。
#
# インストール先は ~/.codex/config.toml だが、このファイルはモデルプロバイダの認証ヘッダを
# 平文で持つためリポジトリ管理下に置けない。よって「リポジトリが状態を持つ」のではなく
# 「冪等なコマンドを setup.sh が叩く」形にする。
#
# なお Codex 版プラグインは skills のみを提供し、Claude Code 版のような SessionStart hook を
# 持たない (manifest に hooks 相当のキーが存在しない)。入れただけでは skills が発火しないため、
# 発火の指示は CLAUDE.md (= ~/.codex/AGENTS.md) の superpowers 節が担う。
echo ""
echo "=== Codex プラグイン導入 ==="

CODEX_PLUGINS=(
  "superpowers@openai-curated"
)

setup_codex_plugins() {
  if [ ! -d "$CODEX_DIR" ]; then
    yellow "スキップ: $CODEX_DIR がないため Codex プラグインは導入しません"
    return
  fi
  if ! command -v codex > /dev/null 2>&1; then
    yellow "スキップ: codex コマンドが PATH にありません"
    return
  fi

  # 導入済み一覧を1回だけ取得する。プラグインごとに codex を起動すると遅く、
  # かつ途中で状態が変わる余地を作ってしまう。
  local installed
  if ! installed="$(codex plugin list --json 2>/dev/null)"; then
    yellow "スキップ: codex plugin list に失敗しました (Codex のバージョンを確認してください)"
    return
  fi

  local plugin_id
  for plugin_id in "${CODEX_PLUGINS[@]}"; do
    # 導入済み判定は installed[] の pluginId で行う。
    # ユーザーが enabled = false にした場合も installed[] には残るため、ここでスキップされる。
    # 明示的な無効化を setup.sh が握り潰さないための挙動。
    if printf '%s' "$installed" | python3 -c "
import json, sys
target = sys.argv[1]
data = json.load(sys.stdin)
sys.exit(0 if any(p.get('pluginId') == target for p in data.get('installed', [])) else 1)
" "$plugin_id"; then
      green "✓ $plugin_id （導入済み）"
      continue
    fi

    # 導入は失敗しても setup.sh 全体を止めない。このスクリプトの主責務はリンク作成であり、
    # マーケットプレイス側の一時的な不調で設定全体の適用が落ちる方が損害が大きい。
    if codex plugin add "$plugin_id" > /dev/null 2>&1; then
      green "✓ $plugin_id （新規導入）"
    else
      red "  失敗: $plugin_id の導入に失敗しました。手動で 'codex plugin add $plugin_id' を実行してください"
    fi
  done
}

setup_codex_plugins

# === settings.json テンプレート生成 ===
# 共通設定(statusLine/plugins/theme等)は machine非依存のため .env の有無に
# 関わらず常に生成する。会社PCのLiteLLM経由API利用に必要な env ブロック
# (ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN等)は .env がある場合のみ追加マージする。
echo ""
echo "=== settings.json 生成 ==="

# 既存 settings.json のバックアップ(生成物ではない実ファイルの場合のみ)
if [ -f "$SETTINGS_DEST" ] && [ ! -L "$SETTINGS_DEST" ]; then
  if [ "$backup_created" = false ]; then
    mkdir -p "$BACKUP_DIR"
    backup_created=true
  fi
  yellow "  バックアップ: $SETTINGS_DEST → $BACKUP_DIR/settings.json"
  cp "$SETTINGS_DEST" "$BACKUP_DIR/settings.json"
fi

# ベーステンプレートを常に適用。
# `/model` 等のCLIコマンドがsettings.jsonに書き込む値(テンプレート未管理のキー)は
# 上書きせず温存し、テンプレートが管理するキーだけを反映するマージ方式にする。
#
# base 側も env を持つ (機密でない機能トグル用)。認証情報とは寿命が違い、
# .env の有無に関わらず全マシンへ適用したいものはこちら側に置く。
# base の env が既存の env を置換するのは意図通り: .env を消したマシンで
# 古い認証キーが settings.json に残り続けるのを防ぐ。
python3 -c "
import json, sys
dest, template = sys.argv[1], sys.argv[2]
try:
    with open(dest) as f:
        settings = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    settings = {}
with open(template) as f:
    base = json.load(f)
settings.update(base)
with open(dest, 'w') as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)
    f.write('\n')
" "$SETTINGS_DEST" "$BASE_TEMPLATE"
green "✓ 共通設定を生成しました → $SETTINGS_DEST"

if [ ! -f "$ENV_FILE" ]; then
  yellow "  → .env が見つからないため、LiteLLM等のAPIキー設定(env)はスキップします。"
  yellow "    (個人Anthropicアカウント/Proプラン利用の場合はこれで問題ありません)"
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
  if [ "${ANTHROPIC_AUTH_TOKEN}" = "your-token-here" ]; then
    red "エラー: ANTHROPIC_AUTH_TOKEN が .env.example のプレースホルダのままです。実際のトークンに書き換えてください。"
    exit 1
  fi

  # env ブロックを生成してマージ
  ENV_JSON_TMP="$(mktemp)"
  if command -v envsubst > /dev/null 2>&1; then
    envsubst < "$ENV_TEMPLATE" > "$ENV_JSON_TMP"
  else
    yellow "envsubst が見つかりません。sed で代替します。"
    cp "$ENV_TEMPLATE" "$ENV_JSON_TMP"
    sed -i '' \
      -e "s|\${ANTHROPIC_BASE_URL}|${ANTHROPIC_BASE_URL}|g" \
      -e "s|\${ANTHROPIC_AUTH_TOKEN}|${ANTHROPIC_AUTH_TOKEN}|g" \
      -e "s|\${ANTHROPIC_MODEL}|${ANTHROPIC_MODEL}|g" \
      -e "s|\${CLAUDE_CODE_SUBAGENT_MODEL}|${CLAUDE_CODE_SUBAGENT_MODEL}|g" \
      -e "s|\${CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS}|${CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS}|g" \
      "$ENV_JSON_TMP"
  fi

  # env だけは追記マージにする。トップレベルの update だと env キーごと置換され、
  # base 側が入れた機能トグルが .env のあるマシンでだけ消える (= 会社PCでのみ
  # 設定が効かない、最も気づきにくい壊れ方) になるため。
  python3 -c "
import json, sys
dest, env_json = sys.argv[1], sys.argv[2]
with open(dest) as f:
    settings = json.load(f)
with open(env_json) as f:
    env_block = json.load(f)
env_values = env_block.pop('env', {})
settings.update(env_block)
settings.setdefault('env', {}).update(env_values)
with open(dest, 'w') as f:
    json.dump(settings, f, indent=2, ensure_ascii=False)
    f.write('\n')
" "$SETTINGS_DEST" "$ENV_JSON_TMP"
  rm -f "$ENV_JSON_TMP"

  green "✓ LiteLLM用env設定をマージしました → $SETTINGS_DEST"
fi

# JSON検証
if python3 -m json.tool "$SETTINGS_DEST" > /dev/null 2>&1; then
  green "✓ settings.json の生成が完了しました → $SETTINGS_DEST"
else
  red "エラー: 生成された settings.json が不正なJSONです。"
  cat "$SETTINGS_DEST"
  exit 1
fi

# === settings.personal.json 生成 (個人Anthropicアカウント用) ===
# 会社PCでは settings.json に LiteLLM 経由の env が焼き込まれるため、素の `claude` は
# 常に LiteLLM を向く。個人アカウントで起動したいとき用に、認証系 env を全て空文字列に
# した設定を用意する。`bin/ccp` がこれを --settings で読ませて上書き無効化する
# (空文字列は「未設定」として扱われ、OAuth/keychain 認証にフォールバックする)。
#
# キーは env.json.template から導出する。無効化対象を手書きで二重管理すると
# env.json.template にキーを足したとき無効化漏れが起きるため、構造的に防ぐ。
# .env の有無に関わらず常に生成する (個人PCでは冗長だが無害で、分岐を持たない方が単純)。
echo ""
echo "=== settings.personal.json 生成 ==="

PERSONAL_DEST="$CLAUDE_DIR/settings.personal.json"

python3 -c "
import json, sys
env_template, dest = sys.argv[1], sys.argv[2]
with open(env_template) as f:
    keys = json.load(f)['env'].keys()
with open(dest, 'w') as f:
    json.dump({'env': {k: '' for k in keys}}, f, indent=2, ensure_ascii=False)
    f.write('\n')
" "$ENV_TEMPLATE" "$PERSONAL_DEST"

green "✓ 個人アカウント用設定を生成しました → $PERSONAL_DEST"

# === git pre-commit フック有効化 ===
# このリポジトリは PUBLIC。学習ログや設計ドキュメントに業務由来の固有名詞が混入すると、
# 公開 git 履歴 (fork・ミラー・既存クローン・コード検索索引) から消せない。
# 「抽象化ルールを守る」という規約だけでは実際に2回すり抜けたため、機構として検査する。
#
# .git/hooks は追跡できないので、tracked な .githooks/ を core.hooksPath で指す。
# この設定は .git/config に入る＝マシンごとに必要なため、setup.sh の責務に置く。
echo ""
echo "=== git pre-commit フック有効化 ==="

setup_git_hooks() {
  local hooks_dir=".githooks"
  local patterns_local="$SCRIPT_DIR/$hooks_dir/patterns-local.txt"
  local patterns_example="$SCRIPT_DIR/$hooks_dir/patterns-local.txt.example"

  if ! git -C "$SCRIPT_DIR" rev-parse --git-dir > /dev/null 2>&1; then
    yellow "スキップ: git リポジトリではないためフックを設定しません"
    return
  fi

  git -C "$SCRIPT_DIR" config core.hooksPath "$hooks_dir"
  green "✓ core.hooksPath → $hooks_dir"

  # 固有名詞パターンは untracked。欠損時フックは fail closed で全コミットを止めるため、
  # ここでひな形から初期化しておく (既存があれば内容を保持する)。
  if [ -f "$patterns_local" ]; then
    green "✓ patterns-local.txt は設定済みです"
  else
    cp "$patterns_example" "$patterns_local"
    yellow "  patterns-local.txt をひな形から作成しました。固有名詞を記入してください:"
    yellow "    $patterns_local"
  fi
}

setup_git_hooks

# === PATH 確認 ===
# bin/ 配下のラッパー (ccp 等) はPATHが通っていないと使えない。
# .zshrc は本リポジトリの管轄外かつ冪等な自動編集が難しいため、案内だけ出す。
echo ""
echo "=== PATH 確認 ==="

case ":$PATH:" in
  *":$CLAUDE_DIR/bin:"*)
    green "✓ $CLAUDE_DIR/bin は PATH に含まれています"
    ;;
  *)
    yellow "  $CLAUDE_DIR/bin が PATH にありません。~/.zshrc に次の1行を追加してください:"
    yellow "    export PATH=\"\$HOME/.claude/bin:\$PATH\""
    ;;
esac

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
