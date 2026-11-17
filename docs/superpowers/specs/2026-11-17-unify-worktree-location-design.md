# worktreeの置き場所を統一する（短い設計）

2026-11-17。規模は小さい変更。

## 解く問題

エージェントがworktreeを作るとき、どのホスト・どの経路で作っても、置き場所がホストごとに1つに決まるようにする。

業務の作業ディレクトリ（複数の子repoを束ねるworkspace。以下WS）を調べると、worktreeが `.worktrees/`・`.claude/worktrees/`・
`<子repo>-wt-<名前>` などに散らばっていた。これには3つの困りごとがある。

- 探せない。どこに作ったかを、作業のたびに思い出す必要がある
- ignoreされない場所に作られ、`git status` に `??` で出る。そのままコミットに混ざるおそれがある
- 片付け漏れが見えない。残骸の `.worktrees/` があると、superpowersがそこを選び続ける

## 原因

- Claude Codeのネイティブ機能（ホストに組み込まれたworktree作成機能。`EnterWorktree`、`claude -w`）は、
  repoの `.claude/worktrees/` に作る。置き場所を変える設定キーは無く、変えるには `WorktreeCreate` フックを自作するしかない
- Codex CLI（0.165.0）にもネイティブ機能（`codex --worktree`、エージェント用の `create_worktree`）がある。
  これはrepoの外の `$CODEX_HOME/worktrees/` に作る。置き場所の設定は絶対パスしか受け付けないと報告されている
  （CLIでの置き場所はissueの報告のみで、未確認）
- superpowers `using-git-worktrees`（7.0.2）は、ネイティブ機能があればそれを使う。無ければ `git worktree add` を手で打ち、
  置き場所を「指示で宣言された場所 → 既存の `.worktrees/` → `worktrees/` → 既定 `.worktrees/`」の順で決める
- `rules/parallel-worktree.md` は、置き場所を設定repoの節でしか決めていない。ネイティブ機能の無いホスト向けの行は `<path>` が未指定
- gitには既定の置き場所が無い（`git worktree add` では `<path>` が必須）

## 目標・非目標

- 目標: worktreeを、次の場所に作らせる。`<repo>` は、そのブランチを持つrepoの本体の作業ツリー（`git worktree list --porcelain` の先頭の `worktree` 行。worktreeの中の `--show-toplevel` は入れ子を生むので使わない。最終レビューで判明）
  - Claude Code: `<repo>/.claude/worktrees/<名前>`（ネイティブ機能をそのまま使う）
  - Codex: `<repo>/.codex/worktrees/<名前>`（ネイティブ機能は使わず、常に `git worktree add` で作る）
  - 両方の置き場所が、どのrepoでも `git status` に出ない
- 非目標: WSに残っている既存worktreeの移動と、残骸の片付け（WSの別セッションで行う）
- 失敗とみなす状態: 宣言を書いても、Codexが `.worktrees/` か `$CODEX_HOME/worktrees/` に作り続ける

## 検討した方法

### Claude Codeの置き場所（ユーザーが選んだ）

`.claude/worktrees/` を選んだ。`.worktrees/` に寄せるには `WorktreeCreate` フックを自作して保守し続ける必要があり、
repoごとに任せると今の不揃いが続く。

### Codexの置き場所（ユーザーが選んだ）

| 案 | 内容 | 採否 |
|---|---|---|
| ネイティブに合わせる | `$CODEX_HOME/worktrees/` に作る | 不採用 |
| ネイティブ＋手作業は `.codex/worktrees/` | 経路によって場所が分かれる | 不採用。今の不揃いと同じ形が残る |
| すべて `<repo>/.codex/worktrees/` | ネイティブ機能を使わず、常に手作業で作る | 採用 |

Codexだけで使うrepoに `.claude/` を作らせないため、Claude Codeと同じ場所にはしない（原則レビューP03aへの回答）。
ネイティブ機能を使わない代わりに、ホストが管理する掃除（直近15件を残す）や、`.worktreeinclude` のコピーは効かない。

### ignoreの方法（ユーザーが選んだ）

| 案 | 内容 | 採否 |
|---|---|---|
| A | dotfiles repoのグローバルignoreに `**/.claude/worktrees/` と `**/.codex/worktrees/` を足す | 採用。全repoに一度で効き、`**/docs/superpowers/` などと同じやり方 |
| B | 作る前に `git check-ignore` で確かめ、無視されていなければ `.git/info/exclude` に足す | 採用（確認だけ）。dotfilesを入れていない環境（コンテナなど）向け |
| C | 各repoの `.gitignore` に足してコミットする | 不採用。共有repoに個人の道具の都合を持ち込む |

## 決めた内容

1. `rules/parallel-worktree.md` で、ホストごとの置き場所を宣言する。Codexには、ネイティブ機能を使わず
   `git worktree add <repo>/.codex/worktrees/<名前> -b <branch>` で作るよう書く（superpowersの1a「ネイティブ優先」より、この指示を優先する）。
   作る前のignoreの確認（B）を添える。設定repoの節の「`.claude/worktrees/` に作る」は、共通の宣言を参照する形にまとめる
2. ADR 0051に、決定と却下案を残す
3. dotfiles repoの `config/git/ignore` に2つのパターンを足す（別PR）

子repoのworktreeは、WS側に集めず、そのブランチを持つrepoのルート直下に置く。ユーザーはCodexの置き場所を子repoの `.codex/worktrees/` と答えており、
Claude Codeの `EnterWorktree` を子repoの中で使ったときの挙動とも合う（原則レビューP15aへの回答）。

## 完了の判定

このrepoとdotfilesの2つのPRが両方そろった時点で完了とする（原則レビューP17aへの回答）。dotfilesの反映後、WS以外のrepoで
`git check-ignore -v` が2つのパターンを返すことを確かめる。

Codexで実際にworktreeを作り、`.codex/worktrees/` に作られるかは、ユーザーの判断で完了条件に含めない。未確認として報告する。

## 作る人に任せること

ルールの文面の細部。superpowersが「宣言された置き場所」として読み取れるように、置き場所を1行で明示すること。
