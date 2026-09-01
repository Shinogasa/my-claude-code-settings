---
adr: 6
date: 2026-09-01
status: accepted
---

# Codex個人プロファイルのMCP定義を単体検証可能にする

## 背景

ADR 0005 により、個人プロファイルは base の全 MCP サーバを列挙し、allowlist にないものを
`enabled = false` にしている。runtime では base と merge されるため、この部分定義でも
MCP の有効・無効は意図どおりに動いていた。

一方、Codex CLI 0.151.0 の TUI は設定保存時に `personal.config.toml` を単体検証する。
`enabled` しかない MCP 定義は `url` も `command` も持たないため `invalid transport` となり、
モデル既定や project trust など、MCP と無関係な設定の保存まで失敗した。

隔離環境では、base 設定だけなら `config/batchWrite` が成功し、`enabled` だけの profile を
書き込み対象にすると失敗した。profile から MCP 部分定義を除くと再び成功した。

## 決定

ADR 0005 の deny-by-default と base 設定非変更を維持する。

生成する各 MCP 定義へ、HTTP なら `url`、stdio なら `command` を base から転記する。
認証ヘッダー、token 環境変数、stdio の引数・環境変数は転記せず、runtime merge で
base から継承する。

`cxp` は起動前に、base と profile の MCP サーバ名集合、transport の種別と値、profile の
明示的な boolean の `enabled` を検査する。不一致は再生成を促して停止する。

## 検討した代替案

### A. profile の MCP 定義を削除する

**採らなかった理由**: base の MCP が個人セッションへ継承され、ADR 0005 の
deny-by-default を破る。profile への未記載は無効化を意味しない。

### B. MCP 定義を丸ごと複製する

**採らなかった理由**: 認証情報、環境変数、実行引数まで複製すると、秘密情報と陳腐化の
範囲が広がる。単体検証に必要なのは transport discriminator だけである。

### C. TUI の設定保存を使わない

**採らなかった理由**: モデル既定以外の `config/batchWrite` 利用箇所も壊れたままになり、
通常操作を回避手順へ置き換えるだけになる。

### D. upstream 修正または CLI 更新を待つ

**採らなかった理由**: 修正の有無と時期を確認できず、現在利用中の 0.151.0 で保存を
回復できない。完全な transport 定義は公式の設定形式にも適合する。

### E. 個人用に `CODEX_HOME` を分ける

**採らなかった理由**: ADR 0005 で却下した、共有設定資産の二重配布コストは変わらない。

## 結果

**良くなったこと**

- profile 単体で MCP transport の構文要件を満たし、TUI の設定保存を妨げない
- 個人側で有効にする MCP は従来どおり allowlist へ1行追加して選べる
- 認証値と runtime option を生成物へ複製しない

**増えた制約**

- profile だけでも transport を持つため、base から削除したサーバが古い profile に残り得る
- `url` / `command` を変更した場合も profile の再生成が必要になる

いずれも `cxp` の起動前完全一致検査で fail closed にする。

## 根拠

- OpenAI Config basics: https://developers.openai.com/codex/config-basic
- OpenAI Configuration Reference: https://developers.openai.com/codex/config-reference
- Codex CLI 0.151.0 / macOS における `config/batchWrite` の隔離実測
- `docs/adr/0005-codex-personal-profile-mcp-inheritance.md`
