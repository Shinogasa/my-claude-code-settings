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

## 実機での確認（2026-10-02、導入後）

npx版のyomiyasuを外し、`bash setup.sh --claude` で配線を入れた。そのあと、ホームの下に作った一時リポジトリで
`bin/ccp -p` を使って確かめた。ヘッドレスの実行なので、個人のアカウントで動いている。

| 確かめた点 | 結果 |
|---|---|
| 日本語のMarkdownを書いてコミットすると、1回目が止められる | 止められた。理由の文に対象の絶対パスが出た |
| 止められた後に、メインが jp-doc-reviewer を起動する | 起動した。依頼文に絶対パスが入っていた |
| レビュワーが SKILL.md と資料3つを Read で全文読み、Edit で直し、リンターを許可された形で動かす | そのとおりに動いた |
| 直した後のコミットが通る | 通った。`dispatched.json` と記録は残らなかった |
| 状態ディレクトリとファイルの権限 | ディレクトリは0700、ファイルは0600 |
| レビュワーの Bash でリンター以外を呼ぶ（`echo`） | エージェント定義の hooks が deny した |
| レビュワーが依頼文に無いファイルを Edit する | エージェント定義の hooks が deny した |
| yomiyasuを呼び、資料を読まずに終える | Stopで1回差し戻された |
| 資料をBashの `cat` で読んでから終える | 差し戻されなかった |
| `yomiyasu:yomiyasu` をSkillツールで呼び、資料をReadで読んでから終える | 差し戻されなかった |
| `rtk hook claude` が同じBashのグループにある状態での `git commit` の見分け | 見分けられた |
| 対話のセッションでConfluenceのページを作る（利用者が別のリポジトリで実行） | 1回目が止められ、下書きができた。レビュワーが下書きを直し、メインは報告を待ってから、直した本文で2回目を送った。2回目の後に下書きは消えた |

Confluenceの確認では、レビューが終わるとメインが確認なしに2回目を送り、社内のConfluenceにページが公開された。
利用者は、レビューの後に止まって確認してから送る形を選んだ。1回目を止めるときの理由の文に、その指示を足した。

サブエージェント定義のfrontmatterに書いた `hooks` は、そのサブエージェントの中のツール呼び出しにも適用された。
レビュワーは、自分の定義にBashの制限が書いてあるため、許可されていないコマンドを自分から実行しないことがある。
フックが止めるところを見るには、依頼文に「制限を確かめるため」と書く必要があった。

確かめられなかった点は `tasks/backlog.md` の「日本語文書レビューで、実機ではまだ確かめていない点」に残した。
