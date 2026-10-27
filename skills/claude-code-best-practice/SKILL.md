---
name: claude-code-best-practice
description: Claude Code設定（CLAUDE.md、skills、commands、rules、hooks、settings.json、subagents、MCP、output-styles）の作成・更新・レビュー時に自動参照するベストプラクティス集。
---

# Claude Code ベストプラクティス

Claude Code設定に関する作業時、関連するベストプラクティスを参照してから実装する。

## 参照先

`~/.claude/claude-code-best-practice/` 配下のファイルを、作業内容に応じて読み込む。

| トピック | ファイル |
|---|---|
| CLAUDE.mdの書き方・配置・サイズ制限 | `best-practice/claude-memory.md` |
| スキル定義 | `best-practice/claude-skills.md` |
| コマンド定義 | `best-practice/claude-commands.md` |
| サブエージェント定義 | `best-practice/claude-subagents.md` |
| settings.json設定項目 | `best-practice/claude-settings.md` |
| MCPサーバー設定 | `best-practice/claude-mcp.md` |
| CLIフラグ | `best-practice/claude-cli-startup-flags.md` |
| パワーアップ機能 | `best-practice/claude-power-ups.md` |

運用の考え方（CLAUDE.mdに書くこと、検査のさせ方、hookとdenyで強制する範囲、サブエージェントの使い方、effort）は、
submoduleが扱っていない。公式の https://code.claude.com/docs/en/best-practices を読む。
このリポジトリでの採否は `docs/adr/0040-align-with-official-best-practices.md` にある。

## ルール

- **作業に関連するファイルのみ読み込む**（全量読み込み禁止）
- 内容はそのまま適用するのではなく、プロジェクトの文脈に合わせて判断する
- 最新化が必要な場合は `git submodule update --remote claude-code-best-practice` を実行する。
  パスを付けないと、ほかのsubmodule（yomiyasu・agent-toolkit-for-aws）まで進んでしまう
