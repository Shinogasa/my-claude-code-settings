---
adr: 23
date: 2026-10-01
status: superseded by 0026
---

# Codex個人プロファイルの所有をキー単位で分ける

## 背景

`~/.codex/personal.config.toml` は `setup.sh` が生成する（ADR 0005・0006）。一方で Codex は、
`cxp`（`codex -p personal`）で起動したセッションの設定保存を、起動中のプロファイルへ書き込む。
ADR 0006 は、この TUI の設定保存を使い続けると決めている。

`setup.sh` はファイル全体の SHA-256 で生成物の所有を判定していたため、Codex が書き足すたびに
次回の setup が競合で止まり、`--replace-conflicts` で再生成すると書き足した設定が消えた。

2026-10-01 の実例では、setup が生成する部分（`model_provider` と `[mcp_servers.*]`）に差分は無く、
差分はすべて Codex の追記だった: `model`、`model_reasoning_effort`、`[tui]`、`[projects]` の信頼設定、
`[plugins]` の無効化、`[hooks.state]` の `trusted_hash`。この競合で `setup.sh --codex` が完了できず、
新しい skill のリンクが張られない状態が続いた。

## 決定

setup が所有するのは `model_provider` と `mcp_servers` だけとし、それ以外のキーは Codex の所有とする。

- 生成器は既存のプロファイルを読み、所有キーだけを作り直し、所有外のキーはそのまま引き継ぐ
- 所有の記録は、所有キーだけを正規化した digest（`owned-sha256:<キー>:<hex>`）にする。
  所有外のキーの変更は競合にせず、所有キーの手編集だけを競合にする
- 引き継ぐ値は標準ライブラリに TOML の書き出しが無いため自前で書き出す。書き出した結果を
  `tomllib` で読み直し、引き継ぐ内容と一致しなければ書き込まずに失敗する。読めない既存ファイルと、
  書き出せない型（日時など）も失敗にする
- 引き継いだキーの一覧を setup の出力に表示し、setup 側へ取り込むべき設定に気づけるようにする
- 所有キーに触れずに接続先を差し替えうるキー（`openai_base_url`、`chatgpt_base_url`、
  `model_providers`、`profiles`、`profile`）が既存プロファイルにあれば、引き継がずに生成を止める。
  Codex がプロファイル内でこれらを解釈するかは未確認だが、止める側に倒す
- 記録したキー一覧が現在の所有キーと異なる場合や、所有部分の digest を計算できない場合は競合にする

所有キーの定義は生成器の `OWNED_KEYS` に一本化し、`setup.sh` はそれを読んで記録する。

## 検討した代替案

### A. ファイル単位で分ける（プロファイルは setup 専用、Codex の追記は base へ移す運用）

**採らなかった理由**: Codex の書き込み先は起動中のプロファイルで、利用者が選べない（ADR 0006 の
前提）。運用で base へ移しても、次の設定保存で再びプロファイルへ書き込まれ、競合が再発する。

### B. Codex に渡す（setup は初回だけ生成し、以降は上書きしない）

**採らなかった理由**: base の MCP サーバが増減したときに、無効化の行を人が手で書くことになる。
ADR 0005 が決めた「allowlist から無効化の集合を自動で導出する」仕組みを手放すことになり、
書き間違えると会社のサーバが個人セッションで有効になる。`cxp` の起動前検査が止めるため
fail closed ではあるが、復旧が手作業になる。生成器の改善も既存のプロファイルへ届かなくなる。

### C. TOML 書き出しライブラリを導入する

**採らなかった理由**: このリポジトリの Python スクリプトは標準ライブラリだけで動かしている。
引き継ぐ値の型は限られており、読み直し検証で書き出しの誤りを確実に止められるため、
依存を増やす理由が弱い。

### D. 既存ファイルのテキストを保ち、所有部分だけを文字列で置換する

**採らなかった理由**: Codex はトップレベルの値（`model` など）を `model_provider` の直後へ挿入するため、
setup の生成範囲を印で囲んでも、その内側へ Codex の追記が入り込む。コメントや並び順は保てても、
所有の境界をテキスト上の位置で表せない。

## 結果

**良くなったこと**

- Codex が書き足した設定を保ったまま、`setup.sh --codex` を競合なしで再実行できる
- 所有キーを手で編集した場合は、従来どおり競合として確認を求める
- MCP の deny-by-default と無効化集合の自動導出（ADR 0005）は維持される

**諦めたこと・残るリスク**

- 再生成すると、所有外の部分のコメントと並び順は保たれない。値は読み直し検証で一致を保証する
- 旧形式（ファイル全体の digest）で記録された既存環境では、移行時に一度だけ競合になる。
  `--replace-conflicts` で置き換えると、退避したうえで Codex の追記を引き継いで再生成する
- 接続先を変えうるキー以外は、Codex が書いた値を信頼して引き継ぐ。`[plugins]`、`[projects]` の
  信頼設定、`[hooks.state]` の改ざんは検知しない。plugin が同梱する MCP は `mcp_servers` の
  deny-by-default の外にある（セキュリティレビューの指摘。backlog で扱う）
- `cxp` は MCP の `enabled` を allowlist と照合しないため、所有キーの手編集は次回の setup まで
  検知されない。これは今回の変更以前からある制約である
- Codex が所有キーへ書き込むようになった場合（例: TUI から MCP を有効化する）、その変更は競合になる

## 根拠

- `docs/adr/0005-codex-personal-profile-mcp-inheritance.md`
- `docs/adr/0006-codex-personal-profile-standalone-mcp-transport.md`
- 2026-10-01 の実環境での生成結果と既存プロファイルの差分比較（Codex CLI 0.159.2 / macOS）
- 回帰テスト: `tests/test_codex_personal_profile.py` の `TestExistingProfileOwnership`、
  `tests/test_setup_cli.py` の `test_codex_rerun_keeps_settings_written_by_codex` と
  `test_codex_hand_edit_of_owned_keys_is_conflict`
