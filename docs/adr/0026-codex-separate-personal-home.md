---
adr: 26
date: 2026-10-04
status: accepted
---

# Codexの個人用に `CODEX_HOME` を分ける

## 背景

1台のマシンで、素の `codex` は会社のゲートウェイへ、`cxp` は個人アカウントへ振り分けている。
今は両方が `~/.codex/` を共有し、`cxp` は `codex -p personal` で個人プロファイルを重ねている（ADR 0005・0006・0023）。

ADR 0005は、`CODEX_HOME` を分ける案を却下した。理由の1つは「会社の経路は `auth.json` を読まないので、
個人ログインの `auth.json` が同じ場所にあっても会社の経路に影響しない」ことだった。

この前提は、`config.toml` に `model_provider` がある間しか成り立たないと分かった。

- 2026-09-21に外部ツールの書き換えで `model_provider` が消え、9/28まで素の `codex` が
  既定の `openai` provider で動いた。認証には同じ場所の `auth.json`（個人ログイン）が使われ、
  会社の作業が個人アカウントへ送られた。エラーは一度も出ていない
- SessionStartの検査（`hooks/check-codex-base-provider.py`）は、起動した後に警告するので間に合わない。
  Codexのhookは `/hooks` で承認されるまで黙ってスキップされる

2026-10-04に、`model_provider` も `auth.json` も無い空の `CODEX_HOME` で `codex exec` を実行した
（codex-cli 0.159.2 / macOS）。`api.openai.com` が `401 Unauthorized: Missing bearer or basic authentication`
を返し、約19秒で失敗した。個人の認証情報が同じ場所に無ければ、provider の欠落はエラーとして表に出る。

## 決定

個人用の Codex は、`~/.codex/` とは別の `CODEX_HOME`（例: `~/.codex-personal/`）で動かす。

- 会社用は `~/.codex/` のまま。素の `codex`、GUIアプリ、外部ツールが書き込む先を変えない
- 個人ログインの `auth.json` は個人用の `CODEX_HOME` だけに置き、`~/.codex/` からは無くす
- `cxp` は `CODEX_HOME` を個人用へ向けて起動する。プロファイルを重ねる方式（`-p personal`）はやめる
- `setup.sh` は、共有資産のリンク（`AGENTS.md`、`hooks`、`skills`、`agents` など）を両方の `CODEX_HOME` へ張る
- `~/.codex/auth.json` が再び作られたら検知する（GUIアプリから個人アカウントでログインした場合など）。
  検知の場所と方法は実装時に決める

## 検討した代替案

### A. 素の `codex` を包むラッパーで、起動前に `model_provider` を検査する

**採らなかった理由**: ラッパーを通らない起動（GUIアプリ、フルパスでの起動、シェル統合が読み込まれない環境）では
検査が走らない。検査が走らなかったことにも気づけない。原因（個人の認証情報が会社側の場所にあること）は残したまま、
検査を1つ足すだけになる。

### B. 現状のまま、SessionStartの警告を強める

**採らなかった理由**: providerは起動時に決まるため、SessionStartでは既に個人アカウントで動いている。
hookが未承認ならスキップされる点も変わらない。

### C. 会社用を別の `CODEX_HOME` へ移し、`~/.codex/` を個人用にする

**採らなかった理由**: 素の `codex` が個人アカウントで動く向きになる。`cxp` が会社設定を既定にしているのは、
シェル統合が読み込まれなかったときに `cxp: command not found` で気づけるようにするためで（`bin/cxp` の冒頭）、
この向きを逆にするとその性質を失う。GUIアプリや外部ツールの書き込み先も会社用から外れる。

### D. ADR 0005のまま、`CODEX_HOME` を共有する

ADR 0005・0006が却下した理由は、共有資産のリンクを2か所へ張ると `setup.sh` が二重管理になることだった。

**今回は覆す理由**: 二重管理のコストは、リンク先の一覧をループで回せば一覧1つに収まる。
一方、共有を続けると、9/21のような無言の個人アカウント利用を構造的に防げない。
さらに、個人プロファイルが会社設定を引き継ぐことから生じていた次の問題が、分離すると発生しなくなる。

- MCPサーバの継承と、allowlistによる無効化（ADR 0005・0006）
- 所有キーの管理と、Codexが書き足した値の引き継ぎ（ADR 0023）
- `cxp` が照合しない経路（プロジェクトの `.codex/config.toml`、plugin同梱のMCP）。2026-10-03のレビューで残った指摘

## 結果

**良くなること**

- `model_provider` が消えても、会社の作業は個人アカウントで動かず、401で失敗する
- 個人用の設定は会社設定を引き継がないので、個人プロファイルの生成・照合の仕組みを減らせる

**諦めること・残るリスク**

- 履歴とセッションが個人用と会社用で分かれる
- providerが消えたとき、認証は失敗するが、リクエスト本体は `api.openai.com` まで送られる。
  これを防ぐかは決めていない
- `~/.codex/auth.json` が再び作られると、9/21と同じ状態に戻る。決定に書いた検知が要る
- GUIアプリが `CODEX_HOME` を尊重するか、個人用をGUIで使う必要があるかは未確認
- 既存の個人ログインとセッションの移し方は、実装時に決める

ADR 0005・0006・0023は、この決定の実装（2026-10-06）で置き換えた。

## 根拠

- `docs/adr/0005-codex-personal-profile-mcp-inheritance.md` の代替案C
- `docs/adr/0006-codex-personal-profile-standalone-mcp-transport.md` の代替案E
- `tasks/backlog.md` の「base provider 検査を起動前に止める経路が無い」（9/21〜9/28の事故の記録）
- 2026-10-04の実測: 空の `CODEX_HOME` での `codex exec` が401で失敗（codex-cli 0.159.2 / macOS）
