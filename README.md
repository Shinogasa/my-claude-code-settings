# my-claude-code-settings

Claude Codeの個人設定をGit管理するリポジトリ。
セットアップスクリプトでシンボリックリンクを作成し、`~/.claude/` と同期する。

## セットアップ

```bash
git clone <this-repo>
cd my-claude-code-settings
bash setup.sh
```

`setup.sh` は以下のシンボリックリンクを `~/.claude/` 配下に作成する：

| リポジトリ | リンク先 | 内容 |
|---|---|---|
| `CLAUDE.md` | `~/.claude/CLAUDE.md` | グローバル指示（全プロジェクト共通） |
| `skills/` | `~/.claude/skills/` | カスタムスキル |
| `commands/` | `~/.claude/commands/` | カスタムスラッシュコマンド |
| `rules/` | `~/.claude/rules/` | 条件付きルール |
| `statusline.js` | `~/.claude/statusline.js` | ステータスライン表示スクリプト |

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
├── statusline.js      # ステータスライン表示
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

以下は機密情報を含むため、このリポジトリでは管理しない：

- `~/.claude/settings.json` — APIキー・トークン等
- `.claude/settings.local.json` — プロジェクト固有設定

## 参考

- https://github.com/affaan-m/everything-claude-code
- https://x.com/heygurisingh/status/2025572300658287030?s=20
  - https://qiita.com/uno_ha07/items/5820d195510861b5be71
