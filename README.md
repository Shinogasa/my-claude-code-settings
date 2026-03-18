# my-claude-code-settings

Claude Codeの個人設定をGit管理するリポジトリ。
セットアップスクリプトでシンボリックリンクを作成し、`~/.claude/` と同期する。

## セットアップ

```bash
git clone <this-repo>
cd my-claude-code-settings
cp .env.example .env
# .env を編集して ANTHROPIC_AUTH_TOKEN 等を設定
bash setup.sh
```

`setup.sh` は以下を実行する：

1. シンボリックリンクを `~/.claude/` 配下に作成
2. `.env` + テンプレートから `~/.claude/settings.json` を生成

| リポジトリ | リンク先 | 内容 |
|---|---|---|
| `CLAUDE.md` | `~/.claude/CLAUDE.md` | グローバル指示（全プロジェクト共通） |
| `skills/` | `~/.claude/skills/` | カスタムスキル |
| `commands/` | `~/.claude/commands/` | カスタムスラッシュコマンド |
| `rules/` | `~/.claude/rules/` | 条件付きルール |
| `statusline.js` | `~/.claude/statusline.js` | ステータスライン表示スクリプト |
| `output-styles/` | `~/.claude/output-styles/` | カスタムアウトプットスタイル |

- 何度実行しても安全（冪等）
- 既存ファイルは `~/.claude/backups/` に自動バックアップ

## ディレクトリ構成

```
├── CLAUDE.md          # グローバル指示
├── skills/            # カスタムスキル
│   ├── backend-patterns/
│   └── coding-standards/
├── commands/          # スラッシュコマンド
│   ├── explain.md
│   └── pr-create.md
├── rules/             # 条件付きルール
├── output-styles/     # カスタムアウトプットスタイル
│   ├── mentoring.md   #   統合メンタリング（教育・レビュー・設計思考）
│   └── fast.md        #   高速実行（説明最小限）
├── statusline.js      # ステータスライン表示
├── settings.json.template  # settings.jsonテンプレート
├── .env.example       # 環境変数サンプル
├── setup.sh           # セットアップスクリプト
└── README.md
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
- 目安：200行以下に収める

### rules/ に分離するもの

特定ファイルを扱うときだけ適用したいルール。`paths` フロントマターが必須。

```markdown
# rules/typescript.md
---
paths:
  - "**/*.{ts,tsx}"
---
- 型は interface を優先する
- any は禁止
```

```markdown
# rules/testing.md
---
paths:
  - "**/*.test.ts"
  - "**/*.spec.ts"
---
- describe/it の命名は日本語で書く
```

### 分割の判断基準

- CLAUDE.md が200行を超えたら分割を検討する
- 言語・フレームワーク固有のルールができたら `paths` 付きで `rules/` へ
- `paths` なしの分割は節約にならないので意味がない

## 管理対象外

以下は機密情報を含むため、`.gitignore` で除外している：

- `.env` — APIトークン等の環境変数（`settings.json.template` と組み合わせて使用）
- `settings.json` — 生成済みの設定ファイル
- `.claude/settings.local.json` — プロジェクト固有設定

## 参考

- https://github.com/affaan-m/everything-claude-code
- https://x.com/heygurisingh/status/2025572300658287030?s=20
  - https://qiita.com/uno_ha07/items/5820d195510861b5be71
