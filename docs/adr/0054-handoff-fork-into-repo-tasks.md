---
adr: 54
date: 2026-11-19
status: accepted
---

# handoff skill を上流からフォークし、引き継ぎ資料を作業repoの `tasks/handoff/` に置く

## 背景

解く問題: ホストで作った引き継ぎ資料を、翌日以降も devcontainer の中のセッションから読めるようにする。

上流 `mattpocock-skills` の handoff skill は、引き継ぎ資料を OS の一時ディレクトリ（`$TMPDIR`、無ければ `/tmp`）へ保存するよう指示している。
2026-11-18、業務repoのホスト側セッションで `/handoff` を実行すると、資料は `/var/folders/...` に保存された。この場所には2つの問題があった。

- devcontainer にマウントされない。マウントされるのはワークスペースのディレクトリだけ（`/workspace`）
- 翌日には消えていた。再起動で消えたのか、macOS の定期掃除で消えたのかは確かめていない

これまで `skills/handoff` は、ADR 0035 の形で上流 submodule を指す symlink だった。submodule の中を直接書き換えると、更新のたびに上書きされる。
上流の SKILL.md を上書きした前例は無い。調べたのは ADR 一覧の題名と、ADR 0035・0038 の本文。

## 決定

2026-11-19、ユーザーが案A（自前の skill）を選んだ。さらに、薄いラッパーではなくフォークにすると決めた。

- `skills/handoff` を実ディレクトリにする。上流 `4ae2317`（`v1.3.2-3`）の `SKILL.md` と `agents/openai.yaml` を写し、置き場所の文だけを書き換える
- 置き場所は、作業repoのtopにある `tasks/handoff/<名前>.md`。ワークスペースで同じ名前の置き場がすでに使われていた
- 書く前に `git check-ignore -q` で確かめる。無視されていないとき（終了コード1）は、`git rev-parse --git-path info/exclude` が指すファイルへ
  `/tasks/handoff/` を足してよいかを一度だけ聞き、了承されたら足して保存する。断られたときと、ほかの終了コード（repoの外の128など）のときは、置き場所を聞く
- このリポジトリの `.gitignore` に `tasks/handoff/` を足す
- 配布の経路は変えない。`manifests/skills.json` の `shared` に残すので、Claude Code と Codex の両方に届く

選んだ理由（ユーザー）: rule と skill の指示が食い違う形は避けたい。上流へPRを送るほどの変更でもない。

フォークの欠点（上流の更新が自動で入らない）は、薄いラッパーと比べたうえで受け入れた。ラッパーなら更新は入るが、
上流の本文の `$TMPDIR` の指示と食い違う。ユーザーは、更新を手で取り込む手間よりも、指示の食い違いを重く見た。
上流の SKILL.md は940バイトしかないので、差分を読む手間は小さいと見ている。

exclude への追加は、2026-11-19 の原則レビューで「毎回聞かれる手間を避ける手段を比べたか」と問われて足した（ユーザーの判断）。
ADR 0051 で worktree の置き場所を exclude に足すのと同じ形である。

## 却下した案

### 薄いラッパー（自前の SKILL.md から上流の SKILL.md を読ませ、置き場所だけを上書きする）

上流の更新は自動で入る。しかし上流の本文にある「`$TMPDIR` に置き、作業ディレクトリには置かない」がそのまま読まれる。
同じ skill の中で指示が食い違い、案Bで避けたかった形が残る。

### rule で上書きする

skill と rule の指示が食い違い、どちらを採るかがエージェント任せになる。

### 上流へPRを送る

受け入れられるか分からない。変更の規模に対して手間が見合わない（ユーザーの判断）。

### 無視されていない repo では毎回置き場所を聞く

最初の版はこの形だった。安全だが、同じ repo で `/handoff` を打つたびに聞かれる。

### 無視されていない repo では、確認せずに exclude へ足す

手間は無くなる。代わりに、業務 repo の git の設定を断りなく書き換えることになる。

### `tasks/todo/` に置く

タスクファイル（`rules/fix-completion-criteria.md`）と同じ場所に混ざる。使い捨ての計画と、セッションをまたぐ引き継ぎ資料は役割が違う。

## 結果

- 上流の handoff の更新は、自動では入らない。submodule を進めるときに `mattpocock-skills/skills/productivity/handoff` の差分を読み、手で取り込む。
  上流では直近5コミットのうち2回、置き場所まわりが変わっていた。取り込みを忘れても気づく仕組みは無い
- `tests/test_skill_manifest.py` の `TestHandoffFork` が、次の点を検査する。symlink に戻っていないこと、`$TMPDIR` と `/tmp` の指示が無いこと、
  `tasks/handoff/` と `git check-ignore` と exclude への追加の指示があること、このリポジトリが `tasks/handoff/` を無視していること
- `tasks/handoff/` を無視していない repo では、最初の `/handoff` で exclude への追加を一度だけ聞かれる

### 達成する範囲

- 解決する: ホストで `/handoff` を実行して作った資料を、devcontainer の中のセッションが `/workspace` の下で読める。再起動でも消えない
- 解決しない: devcontainer の中で `/handoff` を実行した場合。コンテナの `~/.claude/skills/handoff` は、ホストと共有しない volume（`claude-home`）に入った静的なコピーで、
  今も `$TMPDIR` に置く版のままになっている。この変更はコピーに届かない。指示そのものはホスト固有のパスを使わないので、コピーを差し替えればコンテナの中でも通じる。
  差し替えはワークスペース側の課題とした（ユーザーの判断）

### 見直す条件

- 上流が置き場所を選べるようにしたら、フォークをやめて symlink に戻す
- 上流の handoff に、置き場所以外の大きな変更が続いたら、薄いラッパーとの比較をやり直す

## 根拠

- 上流 `SKILL.md` の8行目（`4ae2317` の時点）
- ワークスペースの `.devcontainer/docker-compose.yml`（`..` → `/workspace` の bind と、`claude-home` volume）
- `git check-ignore -q` の終了コードを、一時repoで確かめた（無視されていない: 1、無視されている: 0、repoの外: 128。2026-11-19）
