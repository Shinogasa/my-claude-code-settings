# Claude Codeのフック入力と会話記録の形式（実機確認）

日本語文書レビューのフック（`docs/superpowers/specs/2026-10-01-jp-doc-review-design.md`）を実装する前に、
Claude Code 2.1.286 のフックが受け取る入力と、会話記録の形式を実機で確かめた。
確かめたのは2026-10-02。ID・パス・本文の実物は載せず、キーの一覧と判断だけを書く。

## 確かめ方

一時ディレクトリに空のgitリポジトリを作り、入力をファイルへ追記するだけのフックを、
`claude -p --settings <一時ファイル>` で4つのイベント（PostToolUse、PreToolUse、Stop、SubagentStop）に付けた。
プロンプトでは、Write・Edit・サブエージェントによるWrite・Confluenceのページ作成を1回ずつ起こした。
Confluenceへの投稿は、フックがdenyしたので送られていない。Stopは1回目だけblockし、差し戻し文の残り方を見た。

## フックの入力

| イベント | 確かめたキー | 設計の前提との違い |
|---|---|---|
| PostToolUse（Write） | `session_id`、`cwd`、`transcript_path`、`tool_name`、`tool_input.file_path`、`tool_input.content` | なし |
| PostToolUse（Edit） | `tool_input.file_path`、`tool_input.new_string`（ほかに `old_string`、`replace_all`） | なし |
| PostToolUse（サブエージェント内） | 上に加えて `agent_id`、`agent_type` | なし。`session_id` はメインと同じだった |
| PreToolUse（MCP） | `tool_name`、`tool_input.body`、`tool_input.title`、`tool_input.contentFormat`、`mcp_server` | なし。`mcp_server` が付く |
| Stop | `session_id`、`transcript_path`、`stop_hook_active`、`last_assistant_message` | なし。1回目は `false`、blockで続いた2回目は `true` |
| SubagentStop | `agent_id`、`agent_type`、`agent_transcript_path`、`transcript_path`、`stop_hook_active` | なし |

サブエージェントの書き込みもメインと同じ `session_id` で届く。そのため、レビュワー以外のサブエージェントが
書いた文書も、メインのセッションの記録に入る。設計書の「既知の制約」で未確認にしていた点はこれで解けた。

## 会話記録の形式

- compactの区切りは `{"type": "system", "subtype": "compact_boundary"}` の行（既存の会話記録20件で確認）
- ツール呼び出しは `type: "assistant"` の行の `message.content[]` に `{"type": "tool_use", "name", "input"}` として残る。
  Skillは `input.skill`、Readは `input.file_path`、Agentは `input.subagent_type` を持つ
- ツールの結果は `type: "user"` の行で、`message.content` が `tool_result` を含むリストになる
- Stopフックの差し戻し文は `type: "user"`、`isMeta: true` の行で、本文は「Stop hook feedback:」で始まる文字列になる。
  そのあとに `{"type": "system", "subtype": "stop_hook_summary"}` の行が続く

計画の `is_human_prompt`（`isMeta` が真の行をプロンプトとみなさない）で、差し戻し文を正しく除外できる。

## ヘッドレス実行の接続先

この確認の `claude -p` は、意図せず会社のLiteLLMを経由して動いた。

- 対話のセッションは、個人用の設定（接続情報を空文字列で上書きする `settings.personal.json` 相当）を
  `--settings` で渡して起動されており、個人のアカウントで動いていた
- Bashから起動した `claude -p` は、起動時に `~/.claude/settings.json` を読み直す。そこにある会社の接続情報が、
  空だった環境変数を埋めてしまう
- 警告「claude.ai connectors are disabled because ANTHROPIC_API_KEY or another auth source is set」が出ていた

フックの入力の形はClaude Code本体が決めるので、この確認の結果は接続先によらず使える。
今後Bashから `claude -p` を動かすときは、個人用の設定を `--settings` で渡す（`bin/ccp -p ...`）。
試験用のフックも渡す場合は、個人用の `env` と試験用の `hooks` を1つの設定ファイルにまとめて渡す。
