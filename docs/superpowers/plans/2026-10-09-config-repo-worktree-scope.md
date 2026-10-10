# 設定リポジトリでworktreeを使える範囲を広げる 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 動作中の設定に効かない作業をworktreeで行えるようにする。仕組みで止めるのは、取り返しがつかない壊れ方をする `setup.sh` のworktreeでの実行だけにする。pre-commitは、worktreeでも検査を続けられるようにする。

**決めた人:** ユーザー（2026-10-09、経緯はADR 0031）。作業前の確認を省く案は、ADR 0031の「検討した代替案」に保留として記録済み。

**Architecture:** pre-commitは、worktreeでは本体の作業ツリーにある `patterns-local.txt` を読む。`setup.sh` は、`--git-dir` と `--git-common-dir` が一致しなければ何も変更せずに止まる。規約（`rules/parallel-worktree.md`、`CLAUDE.md`）を書き換え、本体で作業するパスの一覧と作業前の確認手順を載せる。

**Tech Stack:** bash、Python 3（標準ライブラリだけ）、unittest、Git 2.55

**Spec:** `docs/superpowers/specs/2026-10-09-config-repo-worktree-scope-design.md`、ADR 0031

## Global Constraints

- hookと `setup.sh` は標準ライブラリだけで書く（依存を足さない）
- pre-commitは、`patterns-local.txt` がどこにも無ければfail closedで止める（今の挙動を保つ）
- `setup.sh` は、`git` が使えない、またはGitの作業ツリーでない場合は今までどおり動かす
- テストの禁止語はプレースホルダだけで書く（PUBLICリポジトリ）
- テスト中のGit操作は `tests/git_fixture.py` の `git()` で隔離する
- TDDの段階ごとにコミットし、メッセージに段階と証拠（失敗・通過したテスト名）を書く

## Review Focus

- worktreeの中でpre-commitが走ったとき、`GIT_DIR` などGitが渡す環境変数があっても本体の定義を見つけること（Task 1のテスト3）
- 本体にも `patterns-local.txt` が無いworktreeでは、黙って通さずに止まること（Task 1のテスト2）
- 既存の `setup.sh` のテストが、stubの `git` に `rev-parse` を渡しても結果が変わらないこと（Task 2のステップ4で全件を流す）
- `setup.sh` がworktreeで止まったとき、リンクも状態ファイルも作られていないこと（Task 2のテスト1）
- 本体（`.git` がディレクトリ）では、ガードが何も出力せずに通ること（Task 2のテスト2）

---

### Task 1: pre-commitが本体の `patterns-local.txt` を読む

**Files:**
- Modify: `.githooks/pre-commit`（`main()` の `LOCAL_PATTERNS` を使う箇所、118〜127行）
- Create: `tests/test_precommit_local_patterns.py`

**Interfaces:**
- Produces: `find_local_patterns(hook_dir: Path = HOOK_DIR) -> Optional[Path]`。自分の階層の `patterns-local.txt`、無ければ本体の作業ツリーの `.githooks/patterns-local.txt`、どちらにも無ければ `None`

- [ ] **Step 1: 失敗するテストを書く**

```python
#!/usr/bin/env python3
"""pre-commit が worktree でも本体の patterns-local.txt を読むことを検証する（ADR 0031）。"""
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from git_fixture import git  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / ".githooks" / "pre-commit"


def load_hook_module():
    loader = importlib.machinery.SourceFileLoader("precommit_hook_local", str(HOOK))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


hook = load_hook_module()


class FindLocalPatternsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.main = self.base / "main"
        (self.main / ".githooks").mkdir(parents=True)
        git(self.main, "init", "-q")
        git(self.main, "commit", "-q", "--allow-empty", "-m", "init")
        self.worktree = self.base / "wt"
        git(self.main, "worktree", "add", "-q", "--detach", str(self.worktree))
        (self.worktree / ".githooks").mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def test_worktree_reads_main_patterns(self):
        main_patterns = self.main / ".githooks" / "patterns-local.txt"
        main_patterns.write_text("placeholder-name\n", encoding="utf-8")
        self.assertEqual(hook.find_local_patterns(self.worktree / ".githooks"), main_patterns)

    def test_returns_none_when_missing_everywhere(self):
        self.assertIsNone(hook.find_local_patterns(self.worktree / ".githooks"))

    def test_ignores_git_dir_environment(self):
        main_patterns = self.main / ".githooks" / "patterns-local.txt"
        main_patterns.write_text("placeholder-name\n", encoding="utf-8")
        # 無関係なリポジトリを指させる。GIT_DIRを外さない実装は、こちらを探して None を返す
        unrelated = self.base / "unrelated"
        unrelated.mkdir()
        git(unrelated, "init", "-q")
        env = {"GIT_DIR": str(unrelated / ".git")}
        with unittest.mock.patch.dict(os.environ, env):
            self.assertEqual(hook.find_local_patterns(self.worktree / ".githooks"), main_patterns)

    def test_prefers_own_patterns(self):
        own = self.worktree / ".githooks" / "patterns-local.txt"
        own.write_text("placeholder-name\n", encoding="utf-8")
        (self.main / ".githooks" / "patterns-local.txt").write_text("other\n", encoding="utf-8")
        self.assertEqual(hook.find_local_patterns(self.worktree / ".githooks"), own)

    def test_outside_git_returns_none(self):
        outside = self.base / "plain" / ".githooks"
        outside.mkdir(parents=True)
        self.assertIsNone(hook.find_local_patterns(outside))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 失敗を確かめる**

Run: `python3 -m unittest discover -s tests -p 'test_precommit_local_patterns.py' -v`
Expected: `AttributeError: module 'precommit_hook_local' has no attribute 'find_local_patterns'` で全件ERROR

- [ ] **Step 3: REDをコミットする**

```bash
git add tests/test_precommit_local_patterns.py
git commit -m "test: worktreeでpre-commitが本体のpatterns-local.txtを読むテストを足す（RED）"
```

- [ ] **Step 4: 最小の実装**

`.githooks/pre-commit` に関数を足す（`import subprocess` と `Optional` は既存のimportを確かめて足す）。

```python
def find_local_patterns(hook_dir: Path = HOOK_DIR) -> Optional[Path]:
    """固有名詞の禁止パターンの定義を探す。

    worktree には gitignore されたファイルが持ち込まれないので、自分の階層に無ければ
    本体の作業ツリーの定義を使う（ADR 0031）。見つからなければ None を返し、呼び出し側で止める。
    """
    own = hook_dir / LOCAL_PATTERNS.name
    if own.exists():
        return own
    # フックの実行中は GIT_DIR などが渡ってくる。外して、hook_dir から解決し直す
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    try:
        result = subprocess.run(
            ["git", "-C", str(hook_dir), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True, env=env,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    common_dir = result.stdout.strip()
    if not common_dir:
        return None
    candidate = Path(common_dir).parent / ".githooks" / LOCAL_PATTERNS.name
    return candidate if candidate.exists() else None
```

`main()` の118〜127行を、この関数の戻り値で置き換える。

```python
    local_path = find_local_patterns()
    if local_path is None:
        print(red(f"ブロック: {LOCAL_PATTERNS.name} がありません。"), file=sys.stderr)
        print("  固有名詞の禁止パターンが未設定のため検査を実行できません。", file=sys.stderr)
        print("  本体の作業ツリーの .githooks/ で次を実行して初期化してください", file=sys.stderr)
        print("  （worktreeでは、本体の定義を読みます）:", file=sys.stderr)
        print(f"    cp {LOCAL_EXAMPLE.name} {LOCAL_PATTERNS.name}", file=sys.stderr)
        print("    (または本体で bash setup.sh)", file=sys.stderr)
        return 1

    common = load_patterns(COMMON_PATTERNS)
    local = load_patterns(local_path)
```

- [ ] **Step 5: 通過を確かめる**

Run: `python3 -m unittest discover -s tests -p 'test_precommit_local_patterns.py' -v` → 5件OK
Run: `python3 -m unittest discover -s tests -p 'test_patterns.py' -v` → 既存のテストもOK

- [ ] **Step 6: GREENをコミットする**

```bash
git add .githooks/pre-commit
git commit -m "fix: worktreeではpre-commitが本体のpatterns-local.txtを読む（GREEN）"
```

---

### Task 2: `setup.sh` がworktreeでの実行を止める

**Files:**
- Modify: `setup.sh`（`SCRIPT_DIR` を決めた直後）
- Modify: `tests/test_setup_cli.py`（stubの `git`、テスト2件）

**Interfaces:**
- Consumes: なし
- Produces: `setup.sh` の関数 `refuse_worktree`。worktreeなら標準エラーに案内を出して `exit 1`

- [ ] **Step 1: stubの `git` が `rev-parse` を本物へ渡せるようにする**

`make_stub_commands` の `git` の本文の先頭（ログを書く前）に、次の1行を足す。`SETUP_REAL_GIT` が無ければ今までどおり。

```sh
if [ -n "${SETUP_REAL_GIT:-}" ] && [ "$3" = rev-parse ]; then exec "$SETUP_REAL_GIT" "$@"; fi
```

- [ ] **Step 2: 失敗するテストを書く**

`SetupCliTests` に足す（`from git_fixture import git` を先頭のimportへ。`sys.path` は `tests/` を指すよう既存の方法に合わせる）。

```python
    def make_worktree_repository(self) -> Path:
        main = self.base / "main-repository"
        main.mkdir()
        git(main, "init", "-q")
        git(main, "commit", "-q", "--allow-empty", "-m", "init")
        worktree = self.base / "worktree-repository"
        git(main, "worktree", "add", "-q", "--detach", str(worktree))
        for entry in self.repository.iterdir():
            shutil.move(str(entry), worktree / entry.name)
        return worktree

    def test_refuses_to_run_in_worktree(self):
        worktree = self.make_worktree_repository()
        result = run_setup(worktree, self.home, "--claude",
                           extra_env={"SETUP_REAL_GIT": shutil.which("git")})
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("worktree", result.stderr)
        self.assertFalse((self.home / ".claude" / "rules").exists())

    def test_main_working_tree_passes_guard(self):
        git(self.repository, "init", "-q")
        result = run_setup(self.repository, self.home, "--claude",
                           extra_env={"SETUP_REAL_GIT": shutil.which("git")})
        self.assertNotIn("worktree", result.stderr)
```

`self.home` は既存の `setUp` の名前に合わせる（違えば読み替える）。

- [ ] **Step 3: 失敗を確かめてREDをコミットする**

Run: `python3 -m unittest discover -s tests -p 'test_setup_cli.py' -k worktree -v`
Expected: `test_refuses_to_run_in_worktree` がFAIL（returncodeが0）、`test_main_working_tree_passes_guard` はPASS

```bash
git add tests/test_setup_cli.py
git commit -m "test: worktreeでsetup.shが止まるテストを足す（RED）"
```

- [ ] **Step 4: 最小の実装**

`setup.sh` の `SCRIPT_DIR=...` の直後に足す。

```bash
# worktreeで実行するとリンク先がworktreeへ移り、消した時点で全リンクが切れる（ADR 0031）。
# Gitの作業ツリーでない、またはgitが使えないときは判定できないので、今までどおり進める。
refuse_worktree() {
  local dirs git_dir common_dir
  dirs="$(git -C "$SCRIPT_DIR" rev-parse --path-format=absolute --git-dir --git-common-dir 2>/dev/null)" || return 0
  git_dir="$(printf '%s\n' "$dirs" | sed -n 1p)"
  common_dir="$(printf '%s\n' "$dirs" | sed -n 2p)"
  if [ -z "$git_dir" ] || [ -z "$common_dir" ] || [ "$git_dir" = "$common_dir" ]; then
    return 0
  fi
  echo "エラー: setup.sh を worktree で実行しようとしました。何も変更していません。" >&2
  echo "  本体の作業ツリー（$(dirname "$common_dir")）で実行し直してください。" >&2
  exit 1
}
refuse_worktree
```

Run: `python3 -m unittest discover -s tests -p 'test_setup_cli.py' -v` → 全件OK
Run: `python3 -m unittest discover -s tests -p 'test_setup_preflight.py'` → 全件OK（stubの変更で結果が変わらないこと）

- [ ] **Step 5: GREENをコミットする**

```bash
git add setup.sh
git commit -m "fix: setup.shをworktreeで実行したら何も変更せずに止める（GREEN）"
```

---

### Task 3: 規約と文書を書き換える

**Files:**
- Modify: `rules/parallel-worktree.md`（「対象外のリポジトリ」の節、「対象外リポジトリで衝突したとき」の節）
- Modify: `CLAUDE.md`（151〜153行、並列作業の項目）
- Modify: `tasks/backlog.md`（「worktreeでは `.githooks/patterns-local.txt` が無く…」の節を消す）

- [ ] **Step 1: `rules/parallel-worktree.md` の節を書き換える**

「## 対象外のリポジトリ」を「## エージェント設定リポジトリ（範囲を限って使う）」に替え、次を書く。

- 本体で作業するパスの一覧（仕様書のとおり）と、正本が `setup.sh` のリンク定義であること
- 作業前に、触る予定のパスから本体かworktreeかを提案し、ユーザーへ確認すること。途中で変わったら確認し直し、pushしてから本体へ移ること
- worktreeは `.claude/worktrees/` に作り、サブモジュールを初期化すること。永続メモリは空から始まること
- 本体でブランチを切る前に `bin/detect-parallel-sessions` を実行し、並列セッションがいれば、待つ・worktreeに回す・構わず進めるのどれにするかをユーザーに聞くこと。終わったら本体を `main` に戻すこと
- `setup.sh` はworktreeで実行すると止まること、pre-commitは本体の定義を読むこと
- 「サブエージェントを起動するとき」の既定より、この節を優先すること

既存の「対象外リポジトリで衝突したとき」の3項目（ブランチを切り替えない、無関係な変更をコミットしない、stashしない）は、本体で作業するときの注意として残す。

- [ ] **Step 2: `CLAUDE.md` の並列作業の項目を合わせる**

「ただし本リポジトリ自身は対象外（理由は同ファイル参照）」を、「ただし本リポジトリでは、動作中の設定に効くパスを触る作業だけ本体で行う（同ファイル参照）」に替える。

- [ ] **Step 3: backlogの節を消す**

- [ ] **Step 4: コミットする**（日本語文書のレビューや原則レビューのhookに止められたら、その指示に従う）

```bash
git add rules/parallel-worktree.md CLAUDE.md tasks/backlog.md
git commit -m "docs: 設定リポジトリでworktreeを使える範囲を規約に反映する"
```

---

### Task 4: 検証とPR

- [ ] **Step 1:** 未コミットの変更が無い状態で `bash tests/run.sh --all` を流し、全件の通過を確かめる
- [ ] **Step 2:** 手元で実機確認する。`.claude/worktrees/` にworktreeを作り、`bash setup.sh --claude` が止まることを確かめる。そのworktreeで `patterns-local.txt` を置かずにコミットし、pre-commitが本体の定義で検査することを確かめる。確かめたらworktreeを消す
- [ ] **Step 3:** security boundaryの分類をする（`deployment settings` に当たる `setup.sh` と、secretsの漏洩を防ぐpre-commitを触るので、`security-reviewer` を起動する）
- [ ] **Step 4:** push してPRを作る
- [ ] **Step 5:** マージ後、本体で `git pull` する。`setup.sh` の再実行は不要（リンク先は変わらない）
