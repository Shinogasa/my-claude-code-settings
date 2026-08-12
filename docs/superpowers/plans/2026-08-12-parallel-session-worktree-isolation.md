# 並列セッションの作業ツリー分離 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 同一リポジトリ・同一作業ディレクトリで動いている他の Claude セッションをセッション開始時に検出し、git worktree による分離の判断材料をコンテキストへ注入する。

**Architecture:** 検出ロジックを `bin/detect-parallel-sessions`（純粋な検出）に切り出し、`hooks/detect-parallel-sessions.sh`（ポリシー: 対象外判定と通知文の生成）がそれを呼ぶ2層構成。検出は `pgrep` + `lsof` でセッションの作業ディレクトリを取り、`git rev-parse --git-common-dir` で同一リポジトリを判定する。分離の実行は規約（`rules/parallel-worktree.md`）を通じてエージェントの判断に委ねる。

**Tech Stack:** bash, jq, git, Python 3 unittest（テスト）

設計書: `docs/superpowers/specs/2026-08-12-parallel-session-worktree-isolation-design.md`

## Global Constraints

- コメント・ドキュメント・通知文はすべて**日本語**で書く。
- **fail-open を貫く**: `pgrep` / `lsof` / `git` / `jq` のいずれかが使えない、値が取れない場合は黙って正常終了する。検出できないことより、検出処理がセッション開始を妨げることの方が高くつく。
- 既存フックの流儀に合わせる: シェバンは `#!/bin/bash`、先頭に `set -uo pipefail`、JSON 生成は `jq`、判定不能なら無出力で `exit 0`。参考実装は `hooks/warn-branch-behind-main.sh`。
- **出力に同一リポジトリ以外の絶対パスを含めない。** `lsof` は全セッションの作業ディレクトリを取得できるため、絞り込み前の値をそのまま出すと無関係な他プロジェクトのパスがコンテキストへ漏れる。
- テストは `tests/test_<対象名>.py` に置き、`python3 tests/test_<対象名>.py` 単体で実行できること。既存の `tests/test_warn_branch_behind_main.py` の流儀（`unittest` + `tempfile` + `subprocess` でフックの契約を直接叩く）に合わせる。
- スクリプトはリポジトリ名をハードコードしない。対象外リポジトリは `~/.claude/rules` の実体パスから導出する。

---

### Task 1: 検出コマンド `bin/detect-parallel-sessions`

同一リポジトリ・同一作業ディレクトリの他セッションを JSON 配列で出力する。ポリシー（対象外リポジトリ・通知文）は持たない。

**Files:**
- Create: `bin/detect-parallel-sessions`
- Test: `tests/test_detect_parallel_sessions.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - 実行形式: `bin/detect-parallel-sessions [--self-pid <PID>]`
  - 標準出力: JSON 配列 `[{"pid":1234,"cwd":"/path/to/repo"}]`。検出ゼロなら `[]`
  - 終了コード: 常に 0
  - テスト用の差し込み口: 環境変数 `DETECT_PARALLEL_SESSIONS_FIXTURE` にファイルパスを与えると、`pgrep`/`lsof` の代わりにそのファイルを読む。ファイル形式は `PID<TAB>CWD` の行

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_detect_parallel_sessions.py` を作成する。

```python
#!/usr/bin/env python3
"""bin/detect-parallel-sessions の振る舞いを検証する。

このコマンドはプロセスの cwd を基準に判定するため、テストでも subprocess の
cwd を切り替えて実行する。実プロセスの列挙は環境変数
DETECT_PARALLEL_SESSIONS_FIXTURE で差し替える（pgrep/lsof に依存させない）。

実行: python3 tests/test_detect_parallel_sessions.py
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DETECT = REPO_ROOT / "bin" / "detect-parallel-sessions"


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


def make_repo(base, name):
    """コミットを1つ持つリポジトリを作って返す。"""
    repo = Path(base) / name
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("init\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def run_detect(cwd, sessions, self_pid="0"):
    """sessions: [(pid, cwd), ...] を列挙結果として注入して実行し、JSON を返す。"""
    with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False) as fh:
        for pid, session_cwd in sessions:
            fh.write(f"{pid}\t{session_cwd}\n")
        fixture = fh.name
    try:
        env = dict(os.environ)
        env["DETECT_PARALLEL_SESSIONS_FIXTURE"] = fixture
        result = subprocess.run(
            ["bash", str(DETECT), "--self-pid", str(self_pid)],
            capture_output=True, text=True, cwd=str(cwd), env=env,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout or "[]")
    finally:
        os.unlink(fixture)


class TestCollisionDetection(unittest.TestCase):
    """同一リポジトリ・同一作業ディレクトリのセッションだけを衝突とみなす。"""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.repo = make_repo(cls._tmp.name, "repo")
        cls.other = make_repo(cls._tmp.name, "other")
        cls.worktree = Path(cls._tmp.name) / "wt"
        git(cls.repo, "worktree", "add", "-q", "--detach", str(cls.worktree), "HEAD")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_same_cwd_session_is_detected(self):
        found = run_detect(self.repo, [("111", str(self.repo))], self_pid="999")
        self.assertEqual([s["pid"] for s in found], [111])

    def test_own_pid_is_excluded(self):
        found = run_detect(self.repo, [("111", str(self.repo))], self_pid="111")
        self.assertEqual(found, [])

    def test_separated_worktree_is_not_detected(self):
        # common-dir は一致するが作業ディレクトリが違う = 分離済み
        found = run_detect(self.repo, [("111", str(self.worktree))], self_pid="999")
        self.assertEqual(found, [])

    def test_other_repository_is_not_leaked(self):
        # 無関係なプロジェクトの絶対パスを出力に含めない
        found = run_detect(self.repo, [("111", str(self.other))], self_pid="999")
        self.assertEqual(found, [])

    def test_mixed_sessions_return_only_colliding(self):
        found = run_detect(self.repo, [
            ("111", str(self.other)),
            ("222", str(self.repo)),
            ("333", str(self.worktree)),
        ], self_pid="999")
        self.assertEqual([s["pid"] for s in found], [222])
        self.assertEqual(found[0]["cwd"], str(self.repo))

    def test_no_sessions_returns_empty_array(self):
        self.assertEqual(run_detect(self.repo, [], self_pid="999"), [])

    def test_nonexistent_cwd_is_skipped(self):
        found = run_detect(self.repo, [("111", "/no/such/dir")], self_pid="999")
        self.assertEqual(found, [])


class TestOutsideGitRepo(unittest.TestCase):
    """git 管理外では判定できないので空配列を返す (fail-open)。"""

    def test_returns_empty_array(self):
        with tempfile.TemporaryDirectory() as plain:
            self.assertEqual(run_detect(plain, [("111", plain)], self_pid="999"), [])


class TestMissingTools(unittest.TestCase):
    """lsof が使えない環境でも空配列を返して正常終了する (fail-open)。

    差し込み口を使わず、既定の列挙経路 (pgrep + lsof) を通したうえで
    lsof だけを PATH から隠す。
    """

    def test_returns_empty_array_without_lsof(self):
        with tempfile.TemporaryDirectory() as base:
            repo = make_repo(base, "repo")
            # 必要な道具だけを見せる PATH を作り、lsof と pgrep を隠す
            bindir = Path(base) / "bin"
            bindir.mkdir()
            for tool in ("bash", "git", "jq", "ps", "basename",
                         "grep", "cut", "cat", "tr"):
                found = shutil.which(tool)
                if found:
                    (bindir / tool).symlink_to(found)
            env = dict(os.environ)
            env["PATH"] = str(bindir)
            env.pop("DETECT_PARALLEL_SESSIONS_FIXTURE", None)
            result = subprocess.run(
                ["bash", str(DETECT), "--self-pid", "999"],
                capture_output=True, text=True, cwd=str(repo), env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout or "[]"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `python3 tests/test_detect_parallel_sessions.py`
Expected: FAIL。`bin/detect-parallel-sessions` が存在しないため `bash: ... No such file or directory` となり `returncode == 0` のアサートで落ちる。

- [ ] **Step 3: `bin/detect-parallel-sessions` を実装する**

```bash
#!/bin/bash
# 同一リポジトリ・同一作業ディレクトリで動いている他の Claude セッションを検出する。
#
# 出力: JSON 配列。検出ゼロなら []
#   [{"pid":1234,"cwd":"/path/to/repo"}]
#
# 判定:
#   git の common-dir が一致し、かつ作業ディレクトリも一致するものだけを衝突とみなす。
#   common-dir が一致して作業ディレクトリが違う場合は worktree で分離済みなので出さない。
#   common-dir は worktree から呼んでも本体と同じ値を返すため、同一リポジトリの
#   判定キーとして使える。
#
#   出力を同一リポジトリのセッションに絞るのは、無関係な他プロジェクトの絶対パスを
#   コンテキストへ漏らさないため。lsof は全セッションの作業ディレクトリを取れてしまう。
#
# fail-open:
#   pgrep / lsof / git / jq のいずれかが使えない、値が取れない場合は [] を返して
#   正常終了する。検出できないことより、検出処理がセッション開始を妨げることの方が
#   高くつく。

set -uo pipefail

self_pid=""
while [ $# -gt 0 ]; do
  case "$1" in
    --self-pid) self_pid="${2:-}"; shift 2 ;;
    *)          shift ;;
  esac
done

emit_empty() { printf '[]\n'; exit 0; }

command -v git >/dev/null 2>&1 || emit_empty
command -v jq  >/dev/null 2>&1 || emit_empty

my_common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || emit_empty
[ -n "$my_common" ] || emit_empty
my_cwd=$(pwd -P)

# セッションの列挙。テストから差し替えられるようファイル経由の差し込み口を持つ。
# eval を使わないのは、環境変数の中身をコマンドとして実行しないため。
enumerate() {
  if [ -n "${DETECT_PARALLEL_SESSIONS_FIXTURE:-}" ]; then
    cat "$DETECT_PARALLEL_SESSIONS_FIXTURE" 2>/dev/null
    return
  fi
  command -v pgrep >/dev/null 2>&1 || return
  command -v lsof  >/dev/null 2>&1 || return
  local p c
  for p in $(pgrep -x claude 2>/dev/null); do
    c=$(lsof -a -p "$p" -d cwd -Fn 2>/dev/null | grep '^n' | cut -c2-)
    [ -n "$c" ] && printf '%s\t%s\n' "$p" "$c"
  done
}

# 自分自身の pid。--self-pid が無ければ祖先をたどって claude プロセスを探す。
# フックは claude の子として起動されるため、祖先に必ず現れる。
if [ -z "$self_pid" ]; then
  p=$$
  while [ -n "$p" ] && [ "$p" -gt 1 ] 2>/dev/null; do
    if [ "$(basename "$(ps -o comm= -p "$p" 2>/dev/null)" 2>/dev/null)" = "claude" ]; then
      self_pid="$p"
      break
    fi
    p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')
  done
fi

first=1
printf '['
while IFS=$'\t' read -r pid cwd; do
  [ -n "${pid:-}" ] && [ -n "${cwd:-}" ] || continue
  [ "$pid" = "$self_pid" ] && continue
  [ -d "$cwd" ] || continue

  common=$(git -C "$cwd" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || continue
  [ "$common" = "$my_common" ] || continue

  real=$(cd "$cwd" 2>/dev/null && pwd -P) || continue
  [ "$real" = "$my_cwd" ] || continue

  [ $first -eq 1 ] || printf ','
  first=0
  printf '{"pid":%s,"cwd":%s}' "$pid" "$(printf '%s' "$real" | jq -R .)"
done < <(enumerate)
printf ']\n'
```

- [ ] **Step 4: 実行権限を付けてテストを通す**

Run:
```bash
chmod +x bin/detect-parallel-sessions
python3 tests/test_detect_parallel_sessions.py
```
Expected: PASS（9 tests: 衝突判定7 + git 管理外1 + lsof 欠落1）

- [ ] **Step 5: 実環境で1回叩いて確認する**

Run: `bin/detect-parallel-sessions`
Expected: `[]`（このリポジトリで動いているセッションが自分だけの場合）。`jq` でパースできる JSON であること。

- [ ] **Step 6: コミット**

```bash
git add bin/detect-parallel-sessions tests/test_detect_parallel_sessions.py
git commit -m "feat(bin): 並列セッションの衝突を検出するコマンドを追加"
```

---

### Task 2: SessionStart フック `hooks/detect-parallel-sessions.sh`

Task 1 の検出コマンドを呼び、対象外リポジトリを除外したうえで判断材料を `additionalContext` として注入する。

**Files:**
- Create: `hooks/detect-parallel-sessions.sh`
- Test: `tests/test_detect_parallel_sessions_hook.py`

**Interfaces:**
- Consumes: `bin/detect-parallel-sessions`（Task 1）。既定では `$HOME/.claude/bin/detect-parallel-sessions` を呼び、環境変数 `PARALLEL_SESSIONS_DETECT_CMD` で差し替えられる
- Produces:
  - 標準入力: SessionStart の payload（内容は使わないが読み捨てる）
  - 標準出力: 検出ありのとき `{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"..."}}`。検出なし・対象外・判定不能なら**無出力**
  - 対象外リポジトリの差し込み口: 環境変数 `PARALLEL_SESSIONS_EXCLUDE_PATH`（既定 `$HOME/.claude/rules`）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_detect_parallel_sessions_hook.py` を作成する。

```python
#!/usr/bin/env python3
"""hooks/detect-parallel-sessions.sh の振る舞いを検証する。

フックの契約 (stdin に JSON、stdout に SessionStart の JSON) をそのまま叩く。
検出コマンドと対象外リポジトリのパスは環境変数で差し替え、
実際のプロセス状態や ~/.claude の構成に依存させない。

実行: python3 tests/test_detect_parallel_sessions_hook.py
"""
import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "detect-parallel-sessions.sh"


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True,
                   capture_output=True, text=True)


def make_repo(base, name):
    repo = Path(base) / name
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("init\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def make_fake_detect(base, name, payload):
    """固定の JSON を返す検出コマンドを作って返す。"""
    path = Path(base) / name
    path.write_text(f"#!/bin/bash\ncat <<'EOF'\n{payload}\nEOF\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def run_hook(cwd, detect_cmd, exclude_path):
    payload = {"hook_event_name": "SessionStart", "source": "startup"}
    env = dict(os.environ)
    env["PARALLEL_SESSIONS_DETECT_CMD"] = str(detect_cmd)
    env["PARALLEL_SESSIONS_EXCLUDE_PATH"] = str(exclude_path)
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True, text=True, cwd=str(cwd), env=env,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


class TestHook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.repo = make_repo(cls._tmp.name, "repo")
        cls.settings_repo = make_repo(cls._tmp.name, "settings")
        cls.found = make_fake_detect(
            cls._tmp.name, "detect-found",
            '[{"pid":111,"cwd":"%s"}]' % cls.repo,
        )
        cls.none = make_fake_detect(cls._tmp.name, "detect-none", "[]")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_emits_context_when_collision_found(self):
        out = run_hook(self.repo, self.found, self.settings_repo)
        parsed = json.loads(out)
        self.assertEqual(
            parsed["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("additionalContext", parsed["hookSpecificOutput"])

    def test_context_tells_how_to_separate(self):
        out = run_hook(self.repo, self.found, self.settings_repo)
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("worktree", ctx)
        self.assertIn("111", ctx)

    def test_silent_when_no_collision(self):
        self.assertEqual(run_hook(self.repo, self.none, self.settings_repo), "")

    def test_silent_in_excluded_repository(self):
        # 対象外リポジトリ (~/.claude/rules の実体) では検出ありでも黙る
        self.assertEqual(run_hook(self.settings_repo, self.found, self.settings_repo), "")

    def test_silent_outside_git_repo(self):
        with tempfile.TemporaryDirectory() as plain:
            self.assertEqual(run_hook(plain, self.found, self.settings_repo), "")

    def test_silent_when_detect_command_missing(self):
        missing = Path(self._tmp.name) / "no-such-command"
        self.assertEqual(run_hook(self.repo, missing, self.settings_repo), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: テストを実行して失敗を確認する**

Run: `python3 tests/test_detect_parallel_sessions_hook.py`
Expected: FAIL。`hooks/detect-parallel-sessions.sh` が存在しないため `returncode == 0` のアサートで落ちる。

- [ ] **Step 3: `hooks/detect-parallel-sessions.sh` を実装する**

```bash
#!/bin/bash
# SessionStart フック: 同一リポジトリ・同一作業ディレクトリで動いている
# 他の Claude セッションを検出し、分離の判断材料をコンテキストへ注入する。
#
# 通知に留める理由:
#   セッション開始フックからツールは呼べず、できるのは情報の注入まで。
#   作業ディレクトリを機構の判断で動かさない方針を採ったため、
#   誤検出があっても失われるのは注入されたテキスト1件分のコンテキストのみ。
#
# 対象外リポジトリ:
#   エージェント設定リポジトリ自身。~/.claude 配下は絶対パスのリンクで
#   本体の作業ツリーを指すため、worktree 側で rules や hooks を編集しても
#   動作中のエージェントには反映されない。分離するとむしろ壊れる。
#   リポジトリ名はハードコードせず ~/.claude/rules の実体から導出する。
#
# 制約:
#   後から起動したセッションにしか届かない。先に起動していた側は
#   自分の SessionStart を既に通過している。移動すべきなのは後発の方
#   (先発は作業中で中断コストが高い) なので、この非対称性は設計どおり。

set -uo pipefail

cat >/dev/null   # payload は使わないが読み捨てる

DETECT="${PARALLEL_SESSIONS_DETECT_CMD:-$HOME/.claude/bin/detect-parallel-sessions}"
EXCLUDE_PATH="${PARALLEL_SESSIONS_EXCLUDE_PATH:-$HOME/.claude/rules}"

[ -x "$DETECT" ] || exit 0
command -v git >/dev/null 2>&1 || exit 0
command -v jq  >/dev/null 2>&1 || exit 0

my_common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || exit 0
[ -n "$my_common" ] || exit 0

# 対象外判定。リンクの実体からリポジトリを導出するため、別名で配置しても効く。
if [ -e "$EXCLUDE_PATH" ]; then
  exclude_real=$(cd "$EXCLUDE_PATH" 2>/dev/null && pwd -P)
  if [ -n "${exclude_real:-}" ]; then
    exclude_common=$(git -C "$exclude_real" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
    [ "${exclude_common:-}" = "$my_common" ] && exit 0
  fi
fi

sessions=$("$DETECT" 2>/dev/null) || exit 0
count=$(printf '%s' "$sessions" | jq 'length' 2>/dev/null) || exit 0
[ "${count:-0}" -gt 0 ] 2>/dev/null || exit 0

pids=$(printf '%s' "$sessions" | jq -r '[.[].pid] | join(", ")' 2>/dev/null) || exit 0
cwd=$(pwd -P)
branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "HEAD")

detail="このディレクトリで別の Claude セッションが ${count} 件動いています (pid: ${pids})。
作業ディレクトリ: ${cwd}
現在のブランチ: ${branch}

同じ作業ツリーを共有しているため、片方がブランチを切り替えると、もう片方は
足元が変わったことに気づかないまま作業を続けます。

このセッションが後から起動した側です。編集を始める前に worktree で分離してください
(先に動いているセッションは作業中のため、移動するのはこちら側が適切です)。

分離の手順と、追跡外資産 (サブモジュール・.env・依存パッケージ) の復元については
rules/parallel-worktree.md を参照してください。

読み取りや調査だけで終わるセッションなら分離は不要です。"

jq -n \
  --arg ctx "$detail" '{
    hookSpecificOutput: {
      hookEventName: "SessionStart",
      additionalContext: $ctx
    }
  }'

exit 0
```

- [ ] **Step 4: テストを通す**

Run: `python3 tests/test_detect_parallel_sessions_hook.py`
Expected: PASS（6 tests）

- [ ] **Step 5: 既存テストが壊れていないことを確認する**

Run:
```bash
python3 tests/test_detect_parallel_sessions.py
python3 tests/test_warn_branch_behind_main.py
python3 tests/test_guard_dangerous_bash.py
```
Expected: すべて PASS

- [ ] **Step 6: コミット**

```bash
git add hooks/detect-parallel-sessions.sh tests/test_detect_parallel_sessions_hook.py
git commit -m "feat(hooks): 並列セッション検出を SessionStart で通知するフックを追加"
```

---

### Task 3: 規約 `rules/parallel-worktree.md`

`EnterWorktree` ツールは発動条件を「ユーザーが明示的に指示した時」または「CLAUDE.md / memory がそう指示している時」に限定している。この規約が無いとツール自体が使えないため、ドキュメントではなく機構の一部として必須。

**Files:**
- Create: `rules/parallel-worktree.md`
- Modify: `CLAUDE.md`（`## ワークフロー設計` 節の直後に参照を追加）

**Interfaces:**
- Consumes: Task 2 の通知文が `rules/parallel-worktree.md` を名指しで参照する
- Produces: なし（ドキュメント）

- [ ] **Step 1: `rules/parallel-worktree.md` を作成する**

```markdown
# 並列セッションと作業ツリーの分離

同一リポジトリで複数のエージェントが動くと、同じ作業ツリーを共有するため
ブランチが衝突する。片方がブランチを切り替えると、もう片方は足元が
変わったことに気づかないまま作業を続ける。

## サブエージェントを起動するとき（既定）

`Agent` ツールでサブエージェントを起動し、**そのエージェントがコミットを作る場合は
`isolation: "worktree"` を指定する。** 読み取り・調査のみのエージェントには不要。

起動する側がエージェント自身であるため、ここは検出も通知も要らない。
並列作業の大半はこの経路で発生するので、既定化すればほとんどの衝突が消える。

## セッション開始時に通知を受けたとき

`hooks/detect-parallel-sessions.sh` が「別のセッションが動いている」と通知したら、
**編集を始める前に**分離する。

| ホスト | 分離の手段 |
|---|---|
| Claude Code | `EnterWorktree` ツールを呼ぶ |
| 同等ツールを持たないホスト | `git worktree add <path> -b <branch>` を実行し、以降そのパスで作業する |

通知が届くのは後から起動した側だけ。先に動いているセッションは作業中で
中断コストが高いため、**移動するのは通知を受けた側**が適切。

読み取りや調査だけで終わるセッションなら分離は不要。ただし途中で編集に転じる場合は、
その時点で分離を検討する（通知はセッション開始時にしか出ない）。

## 分離した後にやること

`git worktree` は**追跡されていないファイルを持ってこない**。
以下は新しい作業ツリーに存在しないため、必要なものを復元する。

- サブモジュール → `git submodule update --init --recursive`
- `.env` などの gitignore された設定ファイル → 元の作業ツリーからコピー
- 依存パッケージ・仮想環境・ビルドキャッシュ → 各エコシステムの手順で再構築

## worktree では解決しないこと

worktree は**ファイルシステムの分離であって実行環境の分離ではない**。
以下はリポジトリ外の共有資源なので、分離しても衝突し続ける。

- 開発サーバのポート
- ローカル DB（別ブランチのマイグレーションが相互に干渉する）
- コンテナ名・ボリューム名

これらは並列作業一般の制約であり、worktree の採否とは独立に扱う。

## 対象外のリポジトリ

**エージェント設定リポジトリ自身は worktree で分離しない。**

`~/.claude/` 配下は絶対パスのシンボリックリンクで本体の作業ツリーを指しているため、
worktree 側で `rules/` や `hooks/` を編集しても動作中のエージェントには反映されない。
「設定を直したのに効かない」という形で現れる。

さらに `setup.sh` を worktree で実行するとリンク先が worktree になり、
その worktree を削除した時点でリンクが全て壊れる。

`hooks/detect-parallel-sessions.sh` はこのリポジトリを自動で除外するため、
通知自体が出ない。
```

- [ ] **Step 2: `CLAUDE.md` に参照を追加する**

`## ワークフロー設計` 節の末尾（`- **学習アウトプット**: ...` の行の後）に以下を追加する。

```markdown
- **並列作業**: 複数エージェントが同一リポジトリで動くときは worktree で分離する。
  サブエージェント起動時は `isolation: "worktree"` を既定とする。詳細は
  `rules/parallel-worktree.md` を参照
```

- [ ] **Step 3: `rules/...` の解決先の表と整合しているか確認する**

`CLAUDE.md` 冒頭の「このファイル内の `rules/...` の解決先」の表に、新しい規約が
Codex CLI では自動読み込みされない旨が既に書かれていることを確認する。
表は個別のファイル名を列挙していないため、**追記は不要**。確認のみ。

Run: `grep -n "rules/" CLAUDE.md`
Expected: 解決先の表と新しい参照行の両方が出力される。

- [ ] **Step 4: コミット**

```bash
git add rules/parallel-worktree.md CLAUDE.md
git commit -m "docs(rules): 並列セッションの作業ツリー分離の規約を追加"
```

---

### Task 4: 配線（`settings.json.template` と `.gitignore`）

フックを実際に発火させ、`EnterWorktree` の生成先が `git status` を汚さないようにする。挙動が変わる唯一のタスク。

**Files:**
- Modify: `settings.json.template`（`hooks` に `SessionStart` を追加）
- Modify: `.gitignore`（`.claude/worktrees/` を追加）

**Interfaces:**
- Consumes: `hooks/detect-parallel-sessions.sh`（Task 2）
- Produces: なし

- [ ] **Step 1: `.gitignore` に追記する**

既存の `.claude/*settings.local.json` の行の直後に追加する。

```gitignore
# EnterWorktree の生成先。作業ツリーの実体なので追跡しない
.claude/worktrees/
```

- [ ] **Step 2: `.gitignore` が効くことを確認する**

Run:
```bash
git worktree add --detach .claude/worktrees/_probe HEAD
git status --porcelain | grep '\.claude' || echo "汚れなし"
git worktree remove --force .claude/worktrees/_probe
rmdir .claude/worktrees .claude 2>/dev/null || true
```
Expected: `汚れなし` が出力される（追記前は `?? .claude/` が出ていた）

- [ ] **Step 3: `settings.json.template` に `SessionStart` を配線する**

`hooks` オブジェクト内、`PreToolUse` 配列の後ろに `SessionStart` を追加する。

```json
  "hooks": {
    "PreToolUse": [
      ...既存のまま...
    ],
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/detect-parallel-sessions.sh",
            "timeout": 10000
          }
        ]
      }
    ]
  }
```

タイムアウトを 10000 にしているのは、`lsof` をセッション数ぶん呼ぶため。
実測では 7 プロセスで 326ms だが、プロセス数に比例して伸びる。

- [ ] **Step 4: JSON として妥当か確認する**

Run: `jq . settings.json.template > /dev/null && echo OK`
Expected: `OK`

- [ ] **Step 5: 実環境の手動検証**

以下を順に確認する。設計書の「検証手順」に対応する。

1. **分離済みが検出されないこと**

   一時リポジトリと worktree を用意し、worktree 側にセッションがいる状況を注入する。
   ```bash
   base=$(mktemp -d)
   git init -q -b main "$base/r"
   git -C "$base/r" -c user.email=t@e.c -c user.name=t commit -q --allow-empty -m init
   git -C "$base/r" worktree add -q --detach "$base/wt" HEAD
   printf '111\t%s\n' "$base/wt" > "$base/fixture.tsv"
   ( cd "$base/r" && DETECT_PARALLEL_SESSIONS_FIXTURE="$base/fixture.tsv" \
       ~/.claude/bin/detect-parallel-sessions --self-pid 999 )
   ```
   Expected: `[]`（common-dir は一致するが作業ディレクトリが違うため衝突ではない）

   続けて、同じ作業ディレクトリなら検出されることも確認する。
   ```bash
   printf '111\t%s\n' "$base/r" > "$base/fixture.tsv"
   ( cd "$base/r" && DETECT_PARALLEL_SESSIONS_FIXTURE="$base/fixture.tsv" \
       ~/.claude/bin/detect-parallel-sessions --self-pid 999 )
   rm -rf "$base"
   ```
   Expected: `[{"pid":111,"cwd":"..."}]`

2. **このリポジトリでは通知が出ないこと**（対象外の確認）
   ```bash
   cd ~/garage/my-claude-code-settings && echo '{}' | bash hooks/detect-parallel-sessions.sh
   ```
   Expected: 無出力（検出の有無にかかわらず対象外として抜ける）

3. **`lsof` が無い環境で落ちないこと**

   必要な道具だけを見せる PATH を作って実行する。
   ```bash
   sandbox=$(mktemp -d)
   for t in bash git jq ps basename grep cut cat tr; do
     src=$(command -v "$t")
     # zsh では別名や関数が絶対パス以外を返すことがあり、
     # そのまま張ると自己参照の壊れたリンクになる
     case "$src" in /*) ln -s "$src" "$sandbox/$t" ;; esac
   done
   ( cd ~/garage/my-claude-code-settings \
       && env -u DETECT_PARALLEL_SESSIONS_FIXTURE PATH="$sandbox" \
          bash bin/detect-parallel-sessions --self-pid 999 )
   echo "exit=$?"
   rm -rf "$sandbox"
   ```
   Expected: `[]` を出力し `exit=0`

4. **後発セッションに通知が届くこと**

   同一ディレクトリで `claude` を2つ起動し、後発側のコンテキストに
   「別の Claude セッションが動いています」が入ることを目視で確認する。
   このリポジトリは対象外なので、**別のリポジトリで**実施する。

- [ ] **Step 6: コミット**

```bash
git add .gitignore settings.json.template
git commit -m "feat(settings): 並列セッション検出フックを SessionStart に配線"
```

---

## 完了条件

- [ ] `python3 tests/test_detect_parallel_sessions.py` が PASS
- [ ] `python3 tests/test_detect_parallel_sessions_hook.py` が PASS
- [ ] 既存の `tests/test_warn_branch_behind_main.py` と `tests/test_guard_dangerous_bash.py` が PASS
- [ ] Task 4 Step 5 の手動検証 1〜4 がすべて期待どおり
- [ ] `tasks/backlog.md` の「フックの cwd 解決」に、このフックがどちらの方式
      （payload の cwd / プロセスの cwd）を採ったかを追記する。既存2フックで
      解決方法が揃っていない問題に3つ目を足すことになるため、記録を残す
