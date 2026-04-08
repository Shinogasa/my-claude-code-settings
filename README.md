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
| `agents/` | `~/.claude/agents/` | サブエージェント定義 |
| `contexts/` | `~/.claude/contexts/` | コンテキスト切替 |
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
│   ├── api-design/              #   REST API設計パターン
│   ├── architecture-decision-records/  # ADR記録
│   ├── backend-patterns/        #   バックエンドパターン
│   ├── claude-code-best-practice/  # 設定ベストプラクティス参照
│   ├── coding-standards/        #   コーディング規約
│   ├── database-migrations/     #   DBマイグレーション
│   ├── deployment-patterns/     #   デプロイパターン
│   ├── hexagonal-architecture/  #   ヘキサゴナルアーキテクチャ
│   ├── security-review/         #   セキュリティレビュー
│   ├── systematic-debugging/    #   構造化デバッグ（4フェーズ）
│   ├── subagent-driven-development/  # サブエージェント駆動開発
│   ├── tdd-workflow/            #   TDD（Iron Law付き）
│   └── verification-loop/       #   検証ループ（Iron Law付き）
├── commands/                    # スラッシュコマンド
│   ├── aside.md                 #   サイドクエスチョン
│   ├── build-fix.md             #   ビルドエラー修正
│   ├── code-review.md           #   コードレビュー
│   ├── explain.md               #   プロジェクト説明
│   ├── feature-dev.md           #   フィーチャー開発
│   ├── plan.md                  #   実装計画
│   ├── pr-create.md             #   PR作成
│   ├── quality-gate.md          #   品質ゲート
│   ├── refactor-clean.md        #   リファクタリング
│   ├── tdd.md                   #   TDD（shimコマンド）
│   ├── test-coverage.md         #   テストカバレッジ
│   └── verify.md                #   検証（shimコマンド）
├── agents/                      # サブエージェント定義
│   ├── planner.md               #   実装計画（opus, bite-sized tasks）
│   ├── code-architect.md        #   アーキテクチャ設計
│   ├── code-explorer.md         #   コードベース調査
│   ├── code-simplifier.md       #   コード簡素化
│   ├── refactor-cleaner.md      #   デッドコード除去
│   ├── security-reviewer.md     #   セキュリティレビュー
│   ├── build-error-resolver.md  #   ビルドエラー解決
│   └── silent-failure-hunter.md #   サイレント障害検出
├── rules/                       # 常時適用ルール
│   ├── learning-mode.md         #   学習モード詳細仕様
│   ├── output-formatting.md     #   URL表示フォーマット
│   ├── task-management.md       #   タスク管理手順
│   ├── ecc-coding-style.md      #   コーディングスタイル
│   ├── ecc-development-workflow.md  # 開発ワークフロー
│   └── ecc-testing.md           #   テスト要件
├── contexts/                    # コンテキスト切替
│   ├── dev.md                   #   開発モード
│   ├── research.md              #   調査モード
│   └── review.md                #   レビューモード
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

## Superpowers由来の強化

[obra/superpowers](https://github.com/obra/superpowers)（MIT License）のエッセンスをチェリーピックで取り入れている。丸ごとの導入ではなく、学習モードやoutput-styleなど独自の仕組みとの共存を優先して選択的に採用。

| 取り入れた要素 | 適用先 | 内容 |
|---|---|---|
| Rationalization Prevention Tables | tdd-workflow, verification-loop, planner | エージェントの自己正当化を事前にブロックする対応表 |
| Systematic Debugging | skills/systematic-debugging/ | 4フェーズ構造化デバッグ手法（新規） |
| Bite-Sized Task Granularity | agents/planner.md | 2-5分粒度のタスク分解 + プレースホルダー禁止 |
| Subagent-Driven Development | skills/subagent-driven-development/ | サブエージェント実行 + 2段階レビュー（新規） |
| Verification Iron Law | skills/verification-loop/ | 「証拠なしに完了を主張するな」の行動規範 |
| TDD Iron Law | skills/tdd-workflow/ | 「テスト前にコード書いたら削除」の鉄則 |

## 参考

- https://github.com/obra/superpowers — エージェント向けスキルフレームワーク（チェリーピック元）
- https://github.com/shanraisshan/claude-code-best-practice — Claude Code設定ベストプラクティス（submodule）
- https://github.com/affaan-m/everything-claude-code — Claude Code設定集
