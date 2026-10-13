# 設定リポジトリでworktreeを使ってよい範囲を広げる

日付: 2026-10-09
関連: `docs/superpowers/specs/2026-08-12-parallel-session-worktree-isolation-design.md`（項目7）、ADR 0031
決めた人: ユーザー（2026-10-09の会話で、方針・判定方法・強制の範囲を選んだ。経緯はADR 0031）

## 背景

解く問題: 並列で動いているセッションが読む規約を入れ替えずに（ユーザーが承知のうえで進める場合を除く）、動作中の設定に効かない作業（テスト・ADR・backlog・仕様書）をworktreeで進められるようにする。

経緯（このリポジトリを丸ごとworktreeの対象外にしていた理由と、その結果起きたこと）は、ADR 0031の背景を参照する。

## 目的

動作中の設定に影響が無い作業は、worktreeで並列に進められるようにする。動作中の設定に効く作業だけを本体で行い、本体のブランチが動く機会を減らす。

## 本体で作業するパス

`setup.sh` がsymlinkを張る元のパスを、本体で作業するパスとする。**正本は `setup.sh` のリンク定義（`add_link_target`）**で、規約には現時点の一覧を写す。

- `CLAUDE.md`、`rules/`、`hooks/`、`agents/`、`commands/`、`output-styles/`、`bin/`、`statusline.js`、`skills/<各skill>`
- `codex/` のうちリンクするもの（`RTK.md`、`MODEL_ROUTING.md`、`hooks.json`、`agents/`）
- サブモジュール `claude-code-best-practice`、`codex-cli-best-practice`

`settings.json.template`、`env.json.template`、`setup.sh` 自体は、`setup.sh` を実行して初めて効く。編集はworktreeでよい。マージ後に本体で `setup.sh` を実行する。

## 作業の流れ

1. 作業を始める前に、触る予定のパスを上の一覧と照合し、本体とworktreeのどちらで作業するかを提案してユーザーに確認する
2. worktreeで作業するときは `.claude/worktrees/` に作る。一時ディレクトリなど、リポジトリの外には作らない。開始時にサブモジュールを初期化する。永続メモリは空から始まる
3. 本体で作業するときは、`bin/detect-parallel-sessions` で並列セッションがいないことを確かめてからブランチを切る。いれば、待つ・worktreeに回す・構わず進めるのどれにするかをユーザーに聞く
4. 途中で一覧のパスを触る必要が出たら、ユーザーに確認し直す。本体へ移るときはpushしてから移る
5. 終わったら本体を `main` に戻す
6. `settings.json.template`、`env.json.template`、`setup.sh` のどれかを変えたPRをマージしたら、エージェントが本体で `setup.sh` を実行するよう提案する。実行は `~/.claude/` などを書き換えるので、ユーザーの了承を得てから行う（2026-10-13、ADR 0031の原則レビューの問いP03aを受けてユーザーが決めた）

## 仕組みでの強制

取り返しがつかない壊れ方だけを仕組みで止める。分類を誤っても反映が遅れるだけで済むので、分類は規約と事前確認に任せる。

### `setup.sh`

`git rev-parse --git-dir` と `git rev-parse --git-common-dir` を絶対パスで比べ、一致しなければworktreeで実行されたとみなし、何も変更せずに非0で終わる。
エラーには、本体の作業ツリーのパスで実行し直すよう案内を出す。

`.git` が無い場合（tarballで配布された場合など）は、判定せずに今までどおり動かす。`.git` があるのに判定できない場合（`git` が無い、Git 2.31より古い、safe.directory違反など）は、何も変更せずに止める。判定の前に、呼び出し元の `GIT_DIR`・`GIT_COMMON_DIR`・`GIT_WORK_TREE` を外す（2026-10-09のセキュリティレビューを受けて変更）。

### `.githooks/pre-commit`

`patterns-local.txt` は自分の階層（`HOOK_DIR`）を先に探す。無ければ、`git rev-parse --path-format=absolute --git-common-dir` の親ディレクトリ（本体の作業ツリー）にある `.githooks/patterns-local.txt` を探す。
どちらにも無ければ、今までどおりfail closedで止める。`git` の呼び出しに失敗した場合も、無いものとして扱って止める。

## 検討して採らなかった案

現状維持、常にworktreeで作業して本体を `main` に固定する案、worktree内での編集を警告するフック、並列セッション検出の除外を外す案は、ADR 0031に書く。

## テスト

- `setup.sh`: worktreeの中で実行すると非0で終わり、リンクも状態ファイルも変わらないこと。本体では今までどおり動くこと
- `pre-commit`: worktreeの中で、本体の `patterns-local.txt` を使って検査すること。どちらにも無ければ止まること

## 文書の更新

- `rules/parallel-worktree.md` の「対象外のリポジトリ」の節を、この仕様に合わせて書き換える
- `tasks/backlog.md` から「worktreeでは `.githooks/patterns-local.txt` が無く、pre-commitがマージコミットを止める」を消す
- ADR 0031を書き、一覧に足す
