# worktreeの置き場所の統一 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** worktreeの置き場所を、Claude Codeでは `<repo>/.claude/worktrees/<名前>`、Codexでは `<repo>/.codex/worktrees/<名前>` に固定し、両方をグローバルignoreで無視させる。

**Architecture:** 置き場所の宣言は `rules/parallel-worktree.md` に置く（両ホストが読み、superpowersが「宣言された置き場所」として最優先する）。宣言が消えないよう契約テストで固定する。ignoreはdotfiles repoのグローバルignoreで行う。

**Tech Stack:** Markdown、Python `unittest`（`bash tests/run.sh`）、git

**Spec:** `docs/superpowers/specs/2026-11-17-unify-worktree-location-design.md`

## Global Constraints

- `<repo>` は、そのブランチを持つrepoのルート（`git rev-parse --show-toplevel`）。子repoのworktreeはWS側に集めない
- Codexではネイティブ機能（`codex --worktree`、`create_worktree`）を使わず、常に `git worktree add` で作る
- 作る前に `git check-ignore -q` で確かめ、無視されていなければ `.git/info/exclude` に足す。各repoの `.gitignore` にはコミットしない
- ignoreのパターンは `**/.claude/worktrees/` と `**/.codex/worktrees/`（dotfilesの既存行と同じく `**/` を付ける）
- 文書は日本語。rule・ADRの日本語がフックで止まったら jp-doc-reviewer に回す

## Review Focus

1. 子repoの中で作業するとき、エージェントがWSのルートを `<repo>` と取り違える → ruleに `git rev-parse --show-toplevel` を明記する（Task 1のテストで固定）
2. Codexのエージェントが、superpowersの「ネイティブ優先」に従って `create_worktree` を使う → ruleにネイティブ機能を使わないと明記する（Task 1のテストで固定）
3. dotfilesを入れていない環境（コンテナなど）で、worktreeが `??` で出る → ruleに `check-ignore` と `.git/info/exclude` の手順を書く（Task 1のテストで固定）
4. 設定repoの節に古い置き場所の記述が残り、共通の宣言と食い違う → 設定repoの節は共通の宣言を参照するだけにする（Task 1のレビューで確かめる）
5. グローバルignoreのパターンにアンカーが付き、ネストした子repoで効かない → Task 3で子repo相当のパスでも `check-ignore` を確かめる

---

### Task 1: ruleで置き場所を宣言する（TDD）

**Files:**
- Create: `tests/test_worktree_location_contract.py`
- Modify: `rules/parallel-worktree.md`（「セッション開始時に通知を受けたとき」の表、「作業の流れ」の2）

**Interfaces:**
- Produces: ruleの節「worktreeの置き場所」。Task 2のADRがこの節を参照する

- [ ] **Step 1: 失敗するテストを書く**

`WorktreeLocationContract`（`unittest.TestCase`）に次を置く。対象は `ROOT / "rules" / "parallel-worktree.md"`。

- `test_declares_claude_location`: `"<repo>/.claude/worktrees/<名前>"` を含む
- `test_declares_codex_location_with_manual_command`: `"git worktree add <repo>/.codex/worktrees/<名前> -b <branch>"` を含む
- `test_codex_avoids_native_worktree`: `"codex --worktree"` と `"create_worktree"` を含む（使わない対象として名前を挙げている）
- `test_repo_root_is_toplevel`: `"git rev-parse --show-toplevel"` を含む
- `test_ignore_check_before_create`: `"git check-ignore"` と `".git/info/exclude"` を含む
- `test_no_unspecified_path`: `"git worktree add <path> -b <branch>"` を含まない

- [ ] **Step 2: REDを確かめる**

Run: `python3 -m unittest tests.test_worktree_location_contract -v`
Expected: `test_ignore_check_before_create` 以外の大半がFAIL。`test_no_unspecified_path` もFAIL

- [ ] **Step 3: REDでコミット**（メッセージに失敗したテスト名を書く）

- [ ] **Step 4: ruleを書き換える**

「サブエージェントを起動するとき」の前に節「worktreeの置き場所」を足す。内容は、ホスト別の置き場所の表、`<repo>` の定義、Codexでネイティブ機能を使わないこと（superpowersの1aより優先する）、作る前のignore確認。
「セッション開始時に通知を受けたとき」の表のCodex行と、「作業の流れ」2の「worktreeは `.claude/worktrees/` に作る」は、新しい節を参照する形にする。

- [ ] **Step 5: GREENを確かめる**

Run: `python3 -m unittest tests.test_worktree_location_contract -v` → 全件PASS
Run: `bash tests/run.sh` → 失敗0（`test_instruction_graph` などruleを読むテストを含む）

- [ ] **Step 6: GREENでコミット**（通ったテスト名を書く）

### Task 2: ADR 0051

**Files:**
- Create: `docs/adr/0051-unify-worktree-location.md`
- Modify: `docs/adr/README.md`（一覧の表に0051の行を足す）

- [ ] **Step 1: ADRを書く**。背景（WSの散らばりと3つの困りごと、原因）、決定（日付とユーザーが選んだ経緯）、却下案と理由（`.worktrees/`＋`WorktreeCreate` フック、repoごとに任せる、Codexをネイティブに合わせる、Codexはネイティブ＋手作業で分ける、各repoの `.gitignore`、子repoのworktreeをWS側に集める）、結果（諦めたこと: Codexのホスト管理の掃除と `.worktreeinclude` が効かない。未確認: CodexのCLIでの置き場所、Codexで実際に作ったときの挙動）。書式は `docs/adr/README.md`
- [ ] **Step 2: コミット**（原則レビューのフックが止めたら、principle-reviewerを回し、問いをユーザーに見せてから再実行）

### Task 3: dotfilesのグローバルignore（別repo・別PR）

**Files:**
- Modify: `~/garage/dotfiles/config/git/ignore`

- [ ] **Step 1: dotfilesの状態を確かめる**。`git -C ~/garage/dotfiles status -sb` で、mainと未追跡の `.claude/` 以外に変更が無いことを見る。mainをpullしてブランチ `chore/ignore-agent-worktrees` を切る
- [ ] **Step 2: `**/tasks/todo/` の後に、説明コメント1行と2つのパターンを足す**
- [ ] **Step 3: 確かめる**。`.gitignore` に `.claude/worktrees/` を持たないrepoで次を実行する。
  `git check-ignore -v --no-index .claude/worktrees/x .codex/worktrees/x sub/.codex/worktrees/x`
  Expected: 3行とも `…/config/git/ignore:<行番号>:**/…` を返す
- [ ] **Step 4: コミット、push、PR**

### Task 4: このrepoのPR

- [ ] **Step 1:** `bash tests/run.sh` が失敗0
- [ ] **Step 2:** push、PR作成。本文にdotfilesのPRへのリンクと、未確認事項（Codexでの実地確認）を書く
- [ ] **Step 3:** 本体をmainに戻すのはマージ後。`setup.sh` を実行して初めて効くファイルは触らないので、`setup.sh` の再実行は不要
