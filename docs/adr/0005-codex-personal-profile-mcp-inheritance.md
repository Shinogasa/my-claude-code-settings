---
adr: 5
date: 2026-08-31
status: accepted
---

# 個人プロファイルが会社設定の MCP サーバを継承する既定

## 背景

1台のマシンで Codex CLI を2つの接続先へ振り分けたい。

- 素の `codex` → 会社のゲートウェイ（`~/.codex/config.toml` に provider と Authorization ヘッダを直書き）
- `cxp` → 個人アカウント（`codex -p personal` でプロファイルを重ねる）

Claude Code 側は既に同じ構造を持つ（`ccp`。→ `docs/superpowers/specs/2026-08-01-auth-profile-switching-design.md`）。
そちらは認証系の環境変数を空文字列で潰すだけで完結していた。

Codex では完結しない。**プロファイルは base 設定を置き換えるのではなく重ねる**ためで、
実測で確定している（codex-cli 0.150.1 / macOS）。

```
# プロファイルには model_provider しか書いていない
$ codex exec -p <probe> --json 'x'
ERROR codex_rmcp_client::oauth::refresh_transaction:
      error=failed to refresh OAuth tokens for server atlassian-http
```

`atlassian-http` は base の `config.toml` にしか定義されていない MCP サーバである。
プロファイルに1文字も書いていないのに、個人プロファイルのセッションで起動を試みた。
同時に `model` と `model_reasoning_effort` も base の値が引き継がれていた。

つまり `config.toml` の MCP サーバは、プロファイル側で明示的に無効化しない限り
個人セッションでも生きる。判断時点で `config.toml` にあったサーバは4つで、
うち2つが会社のゲートウェイ上または会社アカウントで認証するものだった。

関連する実測をもう1つ挙げる。`codex -p` に**存在しないプロファイル名を渡しても
エラーにならず、base 設定のまま起動する**（exit 0、provider は会社のまま）。
名前の打ち間違いが無言の会社接続になる。

## 決定

個人プロファイルの MCP サーバは **deny by default** とする。

`setup.sh` が `~/.codex/config.toml` の `[mcp_servers.*]` を全列挙し、
`codex/personal-mcp-allowlist.txt` に列挙されたものだけ `enabled = true`、
それ以外を `enabled = false` にしたプロファイルを生成する。

生成時点でしか守られない設計にはしない。`bin/cxp` は起動前に、
`config.toml` にあってプロファイルに無いサーバを検査し、あれば停止する。

`bin/cxp` はプロファイルファイルの実在も自分で検査する。
`codex -p` の無言フォールバックを塞ぐため。

## 検討した代替案

### A. 無効化リストをリポジトリの固定ファイルに手書きする

`codex/personal.config.toml` を置いてシンボリックリンクするだけで済み、
`setup.sh` は TOML を読む必要がない。

**採らなかった理由**: `config.toml` にサーバを足したとき、無効化リストへの追記を
忘れても何も壊れない。壊れないまま個人セッションが会社のサーバを使い続ける。
`settings.personal.json` のキーを `env.json.template` から導出しているのと同じ問題で、
同じ解き方（導出）を採る。

### B. allow by default（会社設定に増えたサーバは個人へも引き継ぐ）

「会社設定に増えるものは個人でも使うはずで、不要なら後で切ればよい」という考え方。
判断時点の候補として実際に検討した。

**採らなかった理由は2つある。**

1つ目。判断時点で `config.toml` にあった MCP サーバのうち、
**個人セッションで有効にしてよいものは4つ中1つだけ**だった（ローカル完結のツール1つ）。
残り3つは会社のゲートウェイ上か、会社アカウントで認証するか、既に無効化されていた。
「増えるものは個人でも使う」という前提は、手元のデータで既に反証されている。

2つ目。**「不要なら後で切る」が成立しない。** 切る契機がどこにも無いためである。
新しいサーバは何も告げずに使える状態になり、モデルが自分で選んで呼ぶ。
エラーも警告も出ず、正常系として完了する。気づく経路が設計に含まれていない。
そして会社の資格情報で外部へ出た通信は、後から取り消せない。

3つ目に、allow by default では生成する意味がほぼ消える。
結局 A（手書きの無効化リスト）と同じ挙動に落ちる。

### C. 個人用に `CODEX_HOME` を分ける

認証・履歴・セッション・MCP がすべて別ファイルになり、継承の問題自体が消える。

**採らなかった理由**: 設定リポジトリから `~/.codex` へ張っているリンク（`AGENTS.md`、
`prompts`、`rules`、`hooks`、`hooks.json`、`agents`、`skills`）を新ホームにも
張り直すことになり、`setup.sh` が二重管理になる。
得られる分離に対して運用コストが見合わない。

また会社経路は `auth.json` を読まないことを実測で確認した
（`codex doctor` が `model provider requires OpenAI auth false` と報告する。
実際 `auth.json` が存在しない状態で動いている）。
個人ログインが `auth.json` を作っても会社経路には影響しないため、
分離しなくても認証は共存できる。

## 結果

**良くなったこと**

- 会社設定に MCP サーバが増えても、個人セッションは既定で使わない
- 生成が古いまま起動する経路を `cxp` が塞ぐため、`setup.sh` の実行忘れが無言の事故にならない
- 会社設定（`~/.codex/config.toml`）を一切変更しない

**諦めたこと**

- 個人セッションで新しいサーバを使いたいとき、allowlist への追記が要る（1行）
- `setup.sh` が TOML を読む依存を持つ（Python 3.11+ の `tomllib`）

**既知のリスク**

plugin marketplace 由来の MCP サーバは `~/.codex/plugins/` 配下で定義され、
`config.toml` には現れない。`codex mcp list` には出るが、**この生成にも `cxp` の検査にも
含まれない**。判断時点で該当するのは1つで、既に無効化されていた。
plugin 由来のサーバを有効化する場合は、素性を自分で確認する必要がある。

この不在は「`config.toml` を読む範囲では見つからない」ことしか示していない。
plugin の定義位置を一次資料で確認したわけではないため、
**上の「1つ」という数は `codex mcp list` の出力に依存する**。
反証条件: plugin 由来のサーバが `config.toml` にも書ける経路があるなら、この整理は誤り。

## 根拠

実測はすべて codex-cli 0.150.1 / macOS 26.6.2 で取得した。

- merge であること: プロファイル未記載の MCP サーバが起動を試みた（`codex exec -p <probe> --json`）
- 無効化が効くこと: プロファイルに `enabled = false` を書くと該当エラーが消えた
- 存在しないプロファイル名: `codex exec -p <不在の名前>` が exit 0 で base 設定のまま起動した
- 会社経路が `auth.json` を読まないこと: `codex doctor` の
  `model provider requires OpenAI auth false` および `auth.json` 不在での動作
- `codex --help` の `-p, --profile <CONFIG_PROFILE_V2>`:
  「Layer $CODEX_HOME/<name>.config.toml on top of the base user config」
