# my-claude-code-settings

Claude Codeの個人設定をGit管理するリポジトリ。
セットアップスクリプトでシンボリックリンクを作成し、`~/.claude/` と同期する。

## セットアップ

```bash
git clone --recursive <this-repo>
cd my-claude-code-settings
cp .env.example .env
# .env を編集して ANTHROPIC_AUTH_TOKEN 等を設定
bash setup.sh
```

`setup.sh` は以下を実行する：

1. git submodule の初期化・更新
2. シンボリックリンクを `~/.claude/` 配下に作成
3. `.env` + テンプレートから `~/.claude/settings.json` を生成

| リポジトリ | リンク先 | 内容 |
|---|---|---|
| `CLAUDE.md` | `~/.claude/CLAUDE.md` | グローバル指示（全プロジェクト共通） |
| `skills/` | `~/.claude/skills/` | カスタムスキル |
| `commands/` | `~/.claude/commands/` | カスタムスラッシュコマンド |
| `rules/` | `~/.claude/rules/` | 条件付きルール |
| `statusline.js` | `~/.claude/statusline.js` | ステータスライン表示スクリプト |
| `output-styles/` | `~/.claude/output-styles/` | カスタムアウトプットスタイル |
| `claude-code-best-practice/` | `~/.claude/claude-code-best-practice/` | ベストプラクティス参照（submodule） |

- 何度実行しても安全（冪等）
- 既存ファイルは `~/.claude/backups/` に自動バックアップ

## ディレクトリ構成

```
├── CLAUDE.md                    # グローバル指示
├── claude-code-best-practice/   # ベストプラクティス（git submodule）
├── skills/                      # カスタムスキル
│   ├── backend-patterns/
│   ├── claude-code-best-practice/
│   └── coding-standards/
├── commands/                    # スラッシュコマンド
│   ├── explain.md
│   └── pr-create.md
├── rules/                       # 条件付きルール
│   ├── learning-mode.md         #   学習モード詳細仕様
│   ├── output-formatting.md     #   URL表示フォーマット
│   └── task-management.md       #   タスク管理手順
├── output-styles/               # カスタムアウトプットスタイル
│   ├── review-and-design.md     #   Review & Design（コードレビュー・設計判断特化）
│   └── fast.md                  #   高速実行（説明最小限）
├── statusline.js                # ステータスライン表示
├── settings.json.template       # settings.jsonテンプレート
├── .env.example                 # 環境変数サンプル
├── setup.sh                     # セットアップスクリプト
└── README.md
```

## claude-code-best-practice（submodule）

[shanraisshan/claude-code-best-practice](https://github.com/shanraisshan/claude-code-best-practice) をgit submoduleとして内包している。Claude Codeの設定パターンに関するベストプラクティス集で、以下のトピックをカバーする：

- **CLAUDE.md** — 書き方、配置戦略、サイズ制限、`<important if="...">`タグ
- **Skills / Commands** — 定義方法、フロントマター仕様、パターン
- **Subagents** — 定義方法、フロントマター仕様、オーケストレーションパターン
- **Settings** — settings.json の全設定項目リファレンス
- **MCP** — MCPサーバーの設定方法
- **CLIフラグ / パワーアップ** — 起動オプション、実験的機能

`skills/claude-code-best-practice/` スキルにより、Claude Code設定の作業時に自動参照される。手動で呼び出す場合は `/claude-code-best-practice` を使用する。

最新化:

```bash
git submodule update --remote
```

## CLAUDE.md と rules/ の使い分け

`rules/` のロードタイミングは `paths` フロントマターの有無で変わる：

| 配置 | ロード | コンテキストコスト |
|---|---|---|
| `CLAUDE.md` | 毎セッション | 常に消費 |
| `rules/`（`paths` なし） | 毎セッション | CLAUDE.md と同じ |
| `rules/`（`paths` あり） | マッチするファイルを開いたとき | 条件付き（節約） |

### CLAUDE.md に残すもの

- プロジェクト問わず常に適用したいルール（言語設定、Git、ワークフロー等）
- 目安：60行以下に収める（遵守率を最大化するため）

### rules/ に分離するもの

- 詳細な行動仕様（学習モード、タスク管理等）→ `alwaysApply: true` で常時読み込み
- 特定ファイルを扱うときだけ適用したいルール → `paths` フロントマターで条件付き

```markdown
# rules/typescript.md
---
paths:
  - "**/*.{ts,tsx}"
---
- 型は interface を優先する
- any は禁止
```

## 管理対象外

以下は機密情報を含むため、`.gitignore` で除外している：

- `.env` — APIトークン等の環境変数（`settings.json.template` と組み合わせて使用）
- `settings.json` — 生成済みの設定ファイル
- `.claude/settings.local.json` — プロジェクト固有設定

## 参考

- https://github.com/shanraisshan/claude-code-best-practice
- https://github.com/affaan-m/everything-claude-code
