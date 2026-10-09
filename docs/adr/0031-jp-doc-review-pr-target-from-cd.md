---
adr: 31
date: 2026-10-09
status: accepted
---

# 日本語文書のレビューで、PRを作るリポジトリを cd の移動先から決める

## 背景

ADR 0025で、日本語文書のレビューをPR作成の直前に行うことにした。PRを作るリポジトリは、
PreToolUseの入力の `cwd` から決めていた。

2026-10-08、別のリポジトリをcwdにしたセッションで `cd <このリポジトリ> && gh pr create ...` を実行した。
仕様書とADRを含むPRだったのに、フックは止めなかった。cwd側のリポジトリには日本語文書の差分が無いからである。
2026-10-09に、cwdを日本語文書の無い別の実リポジトリにしたテストで再現した（`PrReviewTests` の7件）。
逆向きの取り違え（cwd側の文書で止め、cd先の別リポジトリのPRを止める）も同じ原因で起きる。

ADR 0025の背景で挙げた「`cd <別のリポジトリ> && git commit` でコミット先を取り違える」と同じ型である。
コミットの側では、`guard-dangerous-bash.py` がすでに同じコマンドの中の `cd` を追っている。

## 決定

1. `hooks/jp-doc-review.py` は `guard-dangerous-bash.py` を読み込み、そのディレクトリ解決
   （`tokenize_command`・`split_with_operators`・`apply_directory_change`）で、`gh pr create` の時点で
   シェルがいる可能性のあるディレクトリを決める。`principle-review.py` と同じ読み込み方にする
2. `bash -c` などに渡した文字列の中も1段だけ追う（ADR 0025の決定5と同じ深さ）
3. 移動先を文字列から確定できない（変数、`cd -`、pushd / popd、まだ無いディレクトリ）ときと、
   候補が複数のリポジトリにまたがる（`cd x ; gh pr create` など）ときは、**毎回**止めて
   `cd <絶対パス> && gh pr create` への書き直しを求める。サブエージェントは止めずに知らせる
4. `gh` の `-R` / `--repo` は扱わない。`is_pr_create` が拾う書き方を広げる課題（backlog）でまとめて扱う

## 検討した代替案

**ディレクトリ解決を共通モジュールへ切り出し、両方のフックから使う**

採らなかった。`guard-dangerous-bash.py` も書き換わり、差分が大きくなる。
`principle-review.py` がすでにguardを直接読み込んでおり、読み込み方をそろえる方が少ない変更で済む。
guardの関数名を変えると両方のフックが動かなくなるが、どちらもテストで検出できる。

**jp-doc-review.pyの中にcdの追跡を別に書く**

採らなかった。`&&`・`;`・`||` の扱いや、確定できない移動先の判定がguardとずれる。
同じコマンドで、コミットの判定とPR作成の判定が別のリポジトリを指しうる。

**確定できないときも、ADR 0025の決定6と同じく1回だけ止めて2回目は通す**

採らなかった。決定6が想定したのは、baseを決められないときのように、書き直しでは直らない場合である。
cdの移動先は、絶対パスで書き直せば必ず判定できる。2回目を通すと、どのリポジトリの文書も
レビューしないままPRが作られる。止め続けても、書き直すだけで抜けられる。

## 結果

- `cd <別のリポジトリ> && gh pr create` で、移動先のリポジトリの日本語文書をレビューする
- 移動先を確定できない書き方では、PRを作るたびに止まる。書き直しの手間が増える
- jp-doc-review.pyがguard-dangerous-bash.pyに依存する。guardを読み込めないと、フックのエラーとして画面に出る
- ヒアドキュメントの本文の行頭にPR作成のコマンドがある場合は、guardがその本文を除くので、従来どおりcwdで判定する
- `require-full-tests-before-pr.py` は、まだcwdだけでリポジトリを決めている（backlog）

## 根拠

- `docs/adr/0025-jp-doc-review-at-pr-creation.md`
- `hooks/guard-dangerous-bash.py` の docstring（cdの追い方と、確定できないときに止める理由）
- `tests/test_jp_doc_review_hook.py` の `PrReviewTests`（cd を含む7件。修正前に失敗し、修正後に通過した）
