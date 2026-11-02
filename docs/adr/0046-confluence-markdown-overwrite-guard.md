---
adr: 46
date: 2026-11-02
status: accepted
---

# 既存の Confluence ページを Markdown で上書きする呼び出しを、フックで送る前に止める

## 背景

目的は、AI が既存の Confluence ページを更新するときにマクロを失わないようにしつつ、下書きは Markdown のまま書き続けられるようにすることである。

2026-11-02、既存の Confluence ページを `updateConfluencePage` の `contentFormat: markdown` で全文置き換えしようとした。
そのページには info パネル、目次マクロ、折りたたみがあった。API は 422 で拒否した
（`Markdown body replacement would cause data loss. The existing content contains elements that cannot be represented in markdown: confluence macro (info), generic html, confluence macro (toc), confluence macro (expand)`）。
`getContentFormatGuide` の書式で HTML に変換し、`contentFormat: html` で送り直すと通った。
この時点で `jp-doc-review` のレビューは済んでいたので、変換し直した分だけ手間が増えた。
利用者の記憶では、過去にも Markdown で投稿して戻したことが何度かある（会話記録では未確認）。

`updateConfluencePage` の説明には、HTML が既定であることと、リッチな要素があるなら HTML を使うことが書いてある。
それでも Markdown を選んだので、ツールの説明やルールの文章で指示するだけでは足りない。

下書きは Markdown で書く運用を続けたい。そのため、止めるだけでなく、Markdown を HTML に変換する手段も要る。

## 決定

1. PreToolUse フック `hooks/guard-confluence-markdown.py` を、matcher `mcp__.*__updateConfluencePage` の独立したエントリとして
   `settings.json.template` に登録する。`contentFormat` が `markdown`（前後の空白と大文字小文字は無視）なら deny する。
   `createConfluencePage` と、`html` / `adf` / 省略（既定は HTML）の更新は止めない
2. 既存ページにマクロがあるかどうかは見ず、Markdown の更新は**常に**止める。ページの取得はしない
3. deny の理由に、送り直す手順を書く。jp-doc-review の下書きがあれば先にレビューを終える → 既存ページを HTML で取得して残すマクロを確かめる →
   `getContentFormatGuide` を読む → 変換スクリプトで HTML にする → 残すマクロを戻して `contentFormat: html` で送る
4. 入力を読めなかったときは `ask` にする。終了コード1やタイムアウトでは、Claude Code は止めずに送ってしまうため（ADR 0033 の決定5と同じ理由）
5. 変換スクリプト `bin/md-to-confluence-html.py` を置く。標準ライブラリだけで書き、`getContentFormatGuide`（2026-11-02取得）の書式に合わせる。
   info パネルは `> [!INFO]` の引用、折りたたみは `<details>`、目次は `--toc` で付ける
6. 対象は Claude Code だけにする。Codex には登録しない

誰が決めたか（2026-11-02、作業の会話の中で）:

| 決定 | 決めた人 | 経路 |
|---|---|---|
| 1 独立したフックにする | 利用者 | AI が出した3案（独立・jp-doc-review の先頭・独立にして jp-doc-review は見送る）から選んだ |
| 2 常に止める | 利用者 | backlog の「決めること」。AI が推奨を添えて聞いた |
| 3 理由にレビュー→変換の順を書く | 利用者 | 決定1の後に、AI が完了条件の改訂として出し、承認を得た |
| 4 読めなければ ask | AI | ADR 0033 の決定5に合わせた |
| 5 置き場所を `bin/` にする | 利用者 | backlog の「決めること」 |
| 5 標準ライブラリだけで書き、対応する記法を絞る | AI | 下の「既存の Markdown ライブラリで変換する」を参照 |
| 5 未対応の記法を警告する | 利用者 | 原則レビュー（P03a）の問いを受けて選んだ |
| 6 Codex は対象外 | 利用者 | backlog の「決めること」 |

決定2は、過去に Markdown で上書きした頻度を確かめないまま決めた（背景のとおり、会話記録では未確認）。
根拠にしたのは、変換スクリプトがあれば、マクロの無いページで増える手間が小さいことである。

## 検討した代替案

**ルールの文章だけにする**（「既存ページは先に HTML で取得してから送る」）

採らなかった。手順を守らなくても成果物に跡が残らないので、守られなくなっても誰も気づけない
（`rules/proving-absence.md` と ADR 0024 の「常時ruleだけで指示する」と同じ理由）。
今回も、ツールの説明に「HTML を使え」と書いてあったのに Markdown を選んでいる。

**`cw_coding_agent_workspace` 側に置く**

採らなかった。同じ Confluence 投稿に効く jp-doc-review のフックは、このリポジトリにある。
同じツール呼び出しへのフックが2つのリポジトリに分かれると、片方を変えたときにもう片方との関係を確かめる場所が増える。
また、Atlassian MCP がつながっていないセッションでは matcher が一致しないので、共通の設定に置いても何も起きない。
仕事用のセッションでだけ効かせるために置き場所を分ける必要がない。
なお、そのリポジトリの構成（フックを配る仕組みがあるか）は、この判断の時点では確かめていない。

**プロファイルで分ける**（仕事用と個人用で settings を生成し分ける）

採らなかった。上と同じ理由で、仕事用以外では何もしないフックである。1本のフックのために、
settings の生成を分ける仕組みを足すのは釣り合わない。

**既存ページにマクロがあるときだけ止める**

採らなかった。フックの中でページを取得する必要があり、ネットワークと認証に左右される。timeout（10秒）や認証切れで取得できなかったときに通すと、
「検査できなかった」を「問題なし」に畳むことになる（`rules/proving-absence.md`）。止めるなら、マクロの無いページまで毎回止めることになり、条件を付けた意味が薄れる。
マクロの無いページでは HTML に変換する手間が増えるが、変換スクリプトがあるので小さい。

**jp-doc-review の pre-tool-use-confluence の先頭で検査する**

採らなかった。Claude Code は一致した PreToolUse フックを並列に実行する。そのため、settings で前に並べても、jp-doc-review より先に評価されるとは限らない。
先頭に入れれば下書きも状態も作られずに止まるが、そうすると、HTML に変換した後でレビューすることになる。
HTML の下書きでは、yomiyasu のリンターが本文を0文字と数える問題がある（ADR 0034 でラッパーを足して対処した）。
Markdown のままレビューを先に済ませ、レビュー後の下書きを変換する順番のほうが、レビューは1回で済み、リンターもそのまま効く。
また、日本語レビューとは別の関心事なので、jp-doc-review.py に Confluence の形式の扱いを入れない。

**独立したフックにしたうえで、jp-doc-review は Markdown の更新を見送る**

採らなかった。「update かつ markdown」という同じ条件の判定が2つのファイルに入る。片方だけを変えると、どちらのフックも止めない穴ができる。
両方が deny しても、jp-doc-review の状態は投稿先（pageId）ごとに残る。HTML で送り直すと、レビュワーが完了していれば通る（ADR 0033）。

**既存の Markdown ライブラリ（markdown-it-py など）で変換する**

採らなかった。投稿のたびに uv などで依存を取ってくることになり、オフラインや社内のネットワーク制限で使えなくなる場面が出る。
ライブラリを使っても、タスクリスト、パネル、入れ子のタスクの置き方（親の `<li>` の直後）、目次の拡張要素は、
Confluence 固有の書式に書き換える後処理が要る。扱う範囲は AI が書く下書きの範囲に絞れるので、標準ライブラリで書いた。

**変換スクリプトを、Confluence 投稿用の skill の中に置く**

採らなかった。そのような skill は今のところ無く、置くには skill を新しく作ることになる。
`bin/` なら setup.sh が Claude Code にリンクするので、deny の理由に固定のパスを書ける。

**Codex にも登録する**

今回は見送った。Codex での MCP のツール名と、`codex/hooks.json` の matcher の書式を、一次資料でまだ確かめていない。
jp-doc-review の Confluence 処理も Claude Code だけで動かしている（ADR 0024 の決定4）。

## 結果

- 既存ページを Markdown で上書きしようとすると、送る前に止まり、HTML で送り直す手順がその場で分かる
- 下書きは Markdown のまま書ける。日本語レビューは Markdown の下書きに対して1回で済む
- マクロの無いページでも、Markdown での更新は毎回止まる。変換スクリプトを通す手間が増える
- Codex では止まらない

既知の限界:

- 変換結果には、既存ページのマクロ（目次や info パネル以外の拡張要素も含む）は入らない。既存ページの HTML からマクロを戻す作業は、deny の理由に書いた手順に頼る
- 変換スクリプトは、リスト内のコードブロック、斜体、取り消し線、画像、生の HTML（`<details>` と `<summary>` 以外）に対応しない。
  前の4つは標準エラーに行番号つきで警告し、記号はそのまま文字として残す。生の HTML は警告せず、文字としてエスケープする
- フックが動かないとき（`python3` が無い、異常終了、timeout）は、Markdown の更新がそのまま送られる。`ask` で補えるのは、入力の JSON を読めなかったときだけである。
  送られても、マクロを含むページなら API が 422 で拒否する
- `contentFormat` が `markdown` 以外の未知の値（今のツール定義には無い）や、`updateConfluencePage` 以外の名前で同じ操作をするツールは止めない
- 2つのフックが同時に deny したときに、Claude Code が両方の理由をどう表示するかは、実機で確かめていない
- フックの動作は、Atlassian MCP がつながる仕事用のセッションでしか実機確認できない。今回はテストで契約（入力 JSON → 出力 JSON）を確かめた

## 根拠

- 2026-11-02 の 422 応答の本文（背景に引用）
- `getContentFormatGuide`（toolName: updateConfluencePage、2026-11-02取得）。パネル、折りたたみ、タスクリスト、入れ子のルール、目次の拡張要素の書式
- `updateConfluencePage` のツール定義（2026-11-02確認）。`contentFormat` は `html` / `markdown` / `adf` で、省略時は HTML
- Claude Code の hooks の公式ドキュメント（https://code.claude.com/docs/en/hooks 、2026-11-02確認）。
  "When an event fires, its matching hooks run in parallel." 異なるフックの間の順序の保証は書かれていない。
  複数のフックが deny したときに、それぞれの `permissionDecisionReason` が Claude に届くかも書かれていない
- ADR 0024・0033・0034（jp-doc-review の Confluence 処理と、HTML のリンター）
