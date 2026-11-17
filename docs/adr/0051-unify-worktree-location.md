---
adr: 51
date: 2026-11-17
status: accepted
---

# worktreeの置き場所を、ホストごとにrepoの中の1か所へ固定する

## 背景

解く問題: エージェントがworktreeを作るとき、どのホスト・どの経路で作っても、置き場所がホストごとに1つに決まるようにする。

2026-11-17に、業務の作業ディレクトリ（複数の子repoを束ねるworkspace。以下WS）を調べた。worktreeは次の場所に散らばっていた。

| 置き場所 | 件数 | 作ったもの |
|---|---|---|
| `.claude/worktrees/<名前>` | WSに3件、子repoに3件 | Claude Codeの `EnterWorktree` |
| `.worktrees/<名前>` | WSに1件、子repoのブランチ2件 | superpowersの手作業ルート（推測。作成時の記録は見ていない） |
| `.worktrees/<子repo>/<slug>/<子repo>` | 4件 | WSの旧ツール（すでに削除済み） |
| `<子repo>-wt-<名前>`（WS直下） | 3件 | 未確認 |

困りごとは3つあった。どこに作ったかを毎回思い出す必要がある。ignoreされない場所に作られ、`git status` に `??` で出る。
片付け漏れが見えず、残骸の `.worktrees/` があるとsuperpowersがそこを選び続ける。

原因は、ルールの隙間にsuperpowersの既定が入り込んでいたことだった。

- `rules/parallel-worktree.md` は置き場所を設定repoの節（ADR 0031）でしか決めておらず、ネイティブ機能の無いホスト向けの行は
  `git worktree add <path> -b <branch>` で `<path>` が未指定だった
- superpowers `using-git-worktrees`（7.0.2）は、ネイティブ機能（ホストに組み込まれたworktree作成機能）があればそれを使う。
  無いときは `git worktree add` を手で打ち、置き場所を「指示で宣言された場所 → 既存の `.worktrees/` → `worktrees/` → 既定 `.worktrees/`」の順で決める
- gitには既定の置き場所が無い（`git worktree add` では `<path>` が必須。git 2.56.0の `-h` で確認）

## 決定

2026-11-17、ユーザーが会話の中で決めた。

- Claude Codeは `<repo>/.claude/worktrees/<名前>` に作る。ネイティブ機能（`EnterWorktree`、`claude -w`）をそのまま使う
- Codexは `<repo>/.codex/worktrees/<名前>` に作る。ネイティブ機能（`codex --worktree`、`create_worktree`）は使わず、
  常に `git worktree add` で作る。superpowersがネイティブ機能を優先するよう求めても、ruleを優先する
- `<repo>` は、そのブランチを持つrepoのルート（`git rev-parse --show-toplevel`）とする。子repoのworktreeを親の作業ディレクトリへ集めない
- 2つの置き場所は、dotfilesのグローバルignore（`**/.claude/worktrees/`、`**/.codex/worktrees/`）で無視する。
  作る前に `git check-ignore` で確かめ、無視されていなければ `.git/info/exclude` に足す
- 宣言は `rules/parallel-worktree.md` の「worktreeの置き場所」節だけに置き、`tests/test_worktree_location_contract.py` で固定する

ユーザーは、Claude Codeについて `.claude/worktrees/`・`.worktrees/`・repoごとに任せるの3案から `.claude/worktrees/` を選んだ。
Codexについては、原則レビューで「Codexだけで使うrepoにも `.claude/` が作られる」と問われ、別の場所にすると決めた。
その後、Codexにもネイティブ機能があると分かり、3案（ネイティブに合わせる、ネイティブ＋手作業は `.codex/worktrees/`、すべて `.codex/worktrees/`）から
「すべて `.codex/worktrees/`」を選んだ。

設計は `docs/superpowers/specs/2026-11-17-unify-worktree-location-design.md`。

## 検討した代替案

### 全ホストで `.worktrees/` に揃える

gitやsuperpowersの慣習には合う。Claude Codeのネイティブ機能は置き場所を変える設定キーを持たない。
変えるには `WorktreeCreate` フックを自作し、保守し続ける必要がある。

### repoごとに任せる

今の不揃いがそのまま続く。superpowersの手作業ルートは、宣言が無ければ既存の `.worktrees/` か既定の `.worktrees/` を選ぶ。

### 全ホストで `.claude/worktrees/` に揃える

最初はこの案で進めていた。Codexだけで使うrepoにも、別ホストの名前を持つ `.claude/` を作らせることになるため、ユーザーが退けた。

### Codexはネイティブ機能に合わせる（`$CODEX_HOME/worktrees/`）

Codexのネイティブ機能はrepoの外に作る。置き場所の設定は絶対パスしか受け付けないと報告されており、repoごとの場所には向けられない。
ユーザーは、置き場所をrepoの中に揃えるほうを選んだ。理由は2つ。repoの中を見ればClaude Codeと同じように見つかること。
Codexは仕事用と個人用で `CODEX_HOME` を分けている（ADR 0026）ので、ネイティブ機能ではworktreeが2つの `CODEX_HOME` に分かれてしまうこと。

### Codexはネイティブ機能を使い、手作業ルートだけ `.codex/worktrees/` にする

経路によって置き場所が分かれ、今の不揃いと同じ形が残る。

### 各repoの `.gitignore` に足してコミットする

チームで共有するrepoに、個人の道具の都合を持ち込む。

### 子repoのworktreeを親の作業ディレクトリ（WS）に集める

Claude Codeの `EnterWorktree` は、子repoの中で使うと子repoの `.claude/worktrees/` に作る。親に集めると、再びネイティブ機能と食い違う。

## 結果

- ruleの宣言としては、どちらのホストでもworktreeの置き場所はrepoの中の1か所に決まる。superpowersの手作業ルートも、宣言を最優先にするので同じ場所を選ぶ。
  Codexのエージェントが実際に従うかは未確認（下記）
- 覚えることは、ホストごとの1か所に減る。作った場所は、ホストに関係なく `git worktree list` で一覧できる
- 諦めたこと: Codexのネイティブ機能が持つホスト管理の掃除（直近15件を残す）と、`.worktreeinclude` による未追跡ファイルのコピーが効かない。
  未追跡ファイルは同じruleの「分離した後にやること」で、掃除は `git worktree list` で見つけて、ブランチを仕上げるときの `git worktree remove` で補う。
  ユーザーは、この損失を原則レビュー（P03a）で示されたうえで、決定を変えないと答えた
- 未確認: CodexのCLIのネイティブ機能が `$CODEX_HOME/worktrees/` に作ること（公式ドキュメントはアプリについての記述で、CLIはissueの報告のみ）
- 未確認: Codexのエージェントが、ruleに従ってネイティブ機能を使わずに `.codex/worktrees/` へ作ること。
  確かめる手段はあるが、手間との兼ね合いで、ユーザーが完了条件から外した。契約テストはruleの文面を固定するだけで、エージェントの挙動は確かめない
- WSに残る既存worktreeの移動と残骸の片付けは、WSの別の作業で行う

## 根拠

- `~/.claude/plugins/cache/claude-plugins-official/superpowers/7.0.2/skills/using-git-worktrees/SKILL.md`（Step 1a・1b、Directory Selection）
- `claude-code-best-practice/best-practice/claude-settings.md`（`worktree.*` の設定キー）、`claude-code-best-practice/.claude/hooks/HOOKS-README.md`（`WorktreeCreate`）
- Codex CLI 0.165.0 の `codex --help`（`--worktree`）
- https://developers.openai.com/codex/app/worktrees （Codexアプリのworktreeの置き場所と設定）
- https://github.com/openai/codex/issues/10599 （置き場所の設定）
- https://github.com/openai/codex/issues/60015 （CLIのworktreeが `.worktreeinclude` を扱わない）
