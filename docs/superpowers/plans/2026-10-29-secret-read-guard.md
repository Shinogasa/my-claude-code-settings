# secret 読み取りガード 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude Code の Read・Grep・Bash で secret を含むファイルの中身が出力されるのを、`permissions.deny`・フック・構造だけを見せる読み口の3層で止める。
Codex は対象外（利用者が2026-10-29に決定）。MCP のファイル読み取りツールも対象外（AIが提案し、利用者が2026-10-29に承認）。

**Architecture:** 層1は `settings.json.template` の `permissions.deny` を広げる。層2は新しい PreToolUse フック `hooks/guard-secret-read.py` で、
Read・Grep・Bash の対象パスを「場所（`~/.config` とホーム直下のドットディレクトリ）× 権限（本人だけ）」で判定する。
層3は `bin/show-config-structure` で、設定ファイルのキー構造だけを出し、許可したキー以外の値を伏せる。

**Tech Stack:** Python 3（標準ライブラリのみ。`tomllib`・`shlex`・`json`）、unittest、Claude Code の PreToolUse フック

**Spec:** `docs/superpowers/specs/2026-10-29-secret-read-guard-design.md`

## Global Constraints

- フックの契約: stdin に JSON（`tool_name`・`tool_input`・`cwd`）。exit 0 で許可、exit 2 でブロック。理由は stderr に日本語で書く
- ホームは環境変数 `HOME` から求める（テストで差し替えるため）。パスは判定の前に `os.path.realpath` で symlink の実体へ解決する
- 対象範囲: 実体パスが `$HOME/.config/` 配下、または `$HOME/.<名前>`（ホーム直下のドットファイル・ドットディレクトリとその配下）
- 本人だけの権限: `stat.S_IMODE(st_mode) & 0o077 == 0` の通常ファイル
- 例外（場所で書く）: `$HOME/.claude/projects`、`$HOME/.claude/state`、`$HOME/.claude/plugins`、`$HOME/.claude/plans`、`$HOME/.claude/jobs`、`$HOME/.claude/tasks` の配下
- 判定できないとき（パスを解決できない、stat が失敗する、解析で例外が出る）は、対象が対象範囲に見えるなら止める
- Codex には登録しない（`codex/hooks.json` を変えない）。`guard-dangerous-bash.py` は変えない
- 層3で値を出すのは許可したキーだけ。`hooks` は許可しない。伏せ方は値の形を見ない
- コメントとメッセージは日本語

## Review Focus

- `~/.claude/skills` など、このリポジトリへの symlink 経由の読み取りが止まらないこと（Task 2 の `test_symlink_into_repo_is_allowed`）
- jp-doc-review のレビュワーが `~/.claude/state/jp-doc-review/diffs/*.diff`（600）を読めること（Task 2 の `test_state_dir_is_exempt`）
- `cat ~/.config/x/token > /tmp/a` のように、リダイレクトや変数を含むコマンドでも判定が抜けないこと（Task 3 の `test_redirect_source_blocked`・`test_unresolvable_home_variable_blocked`）
- フック自体の例外で全 Bash が通る（exit 1 は Claude Code では許可扱い）ことが無いこと（Task 2 の `test_internal_error_in_range_blocks`）
- 読み口が、値の形に関係なく許可していないキーを伏せること（Task 1 の `test_plain_value_under_unknown_key_masked`）
- `cd ~ && cat .config/app/token` のように、同じコマンドの中で移動してから相対パスで読む形（Task 3 の `test_cd_then_relative_path_blocked`）

受け入れる抜け道（設計書の「既知の穴」。Task 5 で backlog にも積む）: `python3 -c` や `node -e` の中でパスを組み立てて読む経路。
引数の文字列に対象範囲のパスがそのまま現れる場合だけ止める。

---

### Task 1: 層3 値を伏せて構造だけ見せる読み口

**Files:**
- Create: `bin/show-config-structure`（実行権限付き、`#!/usr/bin/env python3`）
- Test: `tests/test_show_config_structure.py`

**Interfaces:**
- Produces: コマンド `show-config-structure <path>`。`.json` と `.toml` は構造を解析する。解析に失敗したら exit 1（stderr に理由、本文は出さない）
- それ以外の形式（YAML・INI・`.env`・シェルの設定など）は行単位で見る。`^\s*(export\s+)?([A-Za-z_][\w.-]*)\s*[=:]` に当たる行は `行N: <キー名> = <伏せた>`、
  当たらない行は `行N: <伏せた>` と出す。値はキーに関係なくすべて伏せる
- 出力形式: 1行1キー、`<ドット区切りのキーの経路>: <型>` または `<経路>: <型> = <値>`。値を出すのは、経路の先頭キーが `ALLOWED_TOP_KEYS` にあるときだけ
- `ALLOWED_TOP_KEYS = {"$schema", "model", "theme", "permissions", "enabledPlugins", "statusLine", "autoCompactEnabled", "askUserQuestionTimeout", "modelSettings", "model_reasoning_effort", "approval_policy", "sandbox_mode"}`
- 伏せた値は `<伏せた>` と書く。配列は `<経路>[i]` で要素ごとに出す

- [ ] **Step 1: 失敗するテストを書く**

`subprocess` でコマンドを実行し、一時ディレクトリの fixture を読ませる。

```python
def test_plain_value_under_unknown_key_masked(self):
    # 値の形が secret らしくなくても、許可していないキーは伏せる
    out = run_tool(write_json({"env": {"FOO": "hello"}}))
    self.assertIn("env.FOO: str = <伏せた>", out.stdout)
    self.assertNotIn("hello", out.stdout)

def test_allowed_key_value_shown(self):
    out = run_tool(write_json({"model": "opus", "permissions": {"deny": ["Read(~/.ssh/**)"]}}))
    self.assertIn("model: str = opus", out.stdout)
    self.assertIn("permissions.deny[0]: str = Read(~/.ssh/**)", out.stdout)

def test_hooks_masked(self):
    out = run_tool(write_json({"hooks": {"PreToolUse": [{"hooks": [{"command": "curl -H tok123"}]}]}}))
    self.assertNotIn("tok123", out.stdout)

def test_toml_supported(self):
    out = run_tool(write_text("x.toml", 'model = "gpt"\n[auth]\ntoken = "abc"\n'))
    self.assertIn("model: str = gpt", out.stdout)
    self.assertIn("auth.token: str = <伏せた>", out.stdout)
    self.assertNotIn("abc", out.stdout)

def test_line_mode_shows_key_names_only(self):
    out = run_tool(write_text(".zshrc.local", "export API_TOKEN=abc123\n# comment xyz\n"))
    self.assertIn("行1: API_TOKEN = <伏せた>", out.stdout)
    self.assertIn("行2: <伏せた>", out.stdout)
    self.assertNotIn("abc123", out.stdout)
    self.assertNotIn("xyz", out.stdout)

def test_unparsable_file_prints_nothing(self):
    out = run_tool(write_text("bad.json", "SECRET_RAW_VALUE"))
    self.assertEqual(out.returncode, 1)
    self.assertNotIn("SECRET_RAW_VALUE", out.stdout + out.stderr)
```

- [ ] **Step 2: 実行して失敗を確かめる**

Run: `python3 -m unittest tests.test_show_config_structure -v`
Expected: FAIL（コマンドが無い）

- [ ] **Step 3: `bin/show-config-structure` を実装する**

`walk(value, path: str, allowed: bool) -> Iterator[str]` で再帰的に行を作る。`allowed` は先頭キーで決め、下へ引き継ぐ。
解析の例外メッセージには原文の断片が入りうるので、stderr には例外の型名とパスだけを書く。

- [ ] **Step 4: 実行して通ることを確かめる**

Run: `python3 -m unittest tests.test_show_config_structure -v`
Expected: PASS

- [ ] **Step 5: コミット**（TDD の段階ごとに、RED と GREEN で1回ずつ）

### Task 2: 層2 フックの土台と Read・Grep の判定

**Files:**
- Create: `hooks/guard-secret-read.py`
- Test: `tests/test_guard_secret_read.py`

**Interfaces:**
- Produces（Task 3 が使う）:
  - `guarded_area(path: str, home: str) -> bool` 実体パスが対象範囲にあり、例外の場所に無いか
  - `is_owner_only_file(path: str) -> bool`
  - `classify(path: str, home: str, cwd: str) -> str` 戻り値は `"allow"`・`"block"`・`"unknown"`。`~` を展開し、相対パスは `cwd` 起点。ディレクトリが対象範囲にあれば `"block"`
  - `looks_guarded(text: str, home: str) -> bool` 解決前の文字列が対象範囲に見えるか（`~/.`、`$HOME/.`、`${HOME}/.`、`<home>/.` を含む）
  - `main() -> int` 例外を捕まえ、入力全体の文字列に `looks_guarded` が当たれば 2、当たらなければ 0 を返す

- [ ] **Step 1: 失敗するテストを書く**

`HOME` を一時ディレクトリへ差し替え、fixture を作ってフックを subprocess で叩く（`tests/test_guard_dangerous_bash.py` と同じ流儀）。

```python
def test_owner_only_file_in_config_blocked(self):       # ~/.config/app/token (600) を Read → 2
def test_world_readable_config_file_allowed(self):      # ~/.config/starship.toml (644) を Read → 0
def test_owner_only_file_outside_dot_dirs_allowed(self): # ~/garage/repo/x (600) を Read → 0
def test_dotfile_at_home_blocked(self):                 # ~/.zshrc.local (600) を Read → 2
def test_symlink_into_repo_is_allowed(self):            # ~/.claude/skills -> 一時repo、配下の600ファイルを Read → 0
def test_symlink_to_secret_blocked(self):               # repo内のリンク -> ~/.config/app/token を Read → 2
def test_state_dir_is_exempt(self):                     # ~/.claude/state/jp-doc-review/diffs/a.diff (600) → 0
def test_grep_directory_in_range_blocked(self):         # Grep path=~/.config → 2
def test_grep_repo_allowed(self):                       # Grep path=一時repo → 0
def test_missing_file_in_range_blocked(self):           # ~/.config/none を Read → 2（判定できない）
def test_internal_error_in_range_blocks(self):          # tool_input が壊れた JSON 型で、文字列に ~/.config を含む → 2
def test_other_tools_pass(self):                        # tool_name=Edit → 0
```

ブロック時の stderr には、対象のパスと、構造を見る手段として `show-config-structure` の名前を含むことも確かめる。

- [ ] **Step 2: 実行して失敗を確かめる**

Run: `python3 -m unittest tests.test_guard_secret_read -v`
Expected: FAIL（フックが無い）

- [ ] **Step 3: 上の関数と、Read（`file_path`）・Grep（`path`、無ければ `cwd`）の分岐を実装する**

- [ ] **Step 4: 実行して通ることを確かめる**

Run: `python3 -m unittest tests.test_guard_secret_read -v`
Expected: PASS

- [ ] **Step 5: コミット**（RED と GREEN で1回ずつ）

### Task 3: 層2 Bash の判定

**Files:**
- Modify: `hooks/guard-secret-read.py`
- Test: `tests/test_guard_secret_read.py`

**Interfaces:**
- Consumes: Task 2 の `classify`・`looks_guarded`
- Produces: `check_bash(command: str, home: str, cwd: str) -> Optional[str]`（ブロック理由。許可なら `None`）
- 中身を出さないコマンド: `METADATA_COMMANDS = {"ls", "stat", "test", "[", "file", "wc", "du", "cd", "realpath", "readlink", "basename", "dirname", "show-config-structure"}`。
  `diff` などの中身を出すコマンドは入れない。`find` は `-exec`・`-execdir`・`-ok`・`-okdir`・`-fprint`・`-fprintf`・`-fls` が無いときだけ通す
- 解析: `shlex.shlex(command, posix=True, punctuation_chars=True)` で分け、`;` `&&` `||` `|` で単純コマンドへ分ける。先頭の `VAR=value` と `env`・`sudo`・`command`・`exec` は飛ばす。
  コマンド名は basename で比べる（`~/.claude/bin/show-config-structure` も通す）。`<` の直後のトークンも対象パスとして扱う
- `cd <dir>` を見たら、それ以降の単純コマンドの相対パスを `<dir>` 起点で解決する（引数なしの `cd` はホーム。解決できない `cd` の後は、相対パスをすべて `"unknown"` として扱う）
- 引数ごとに: `$` か `` ` `` を含むなら `looks_guarded` で判定。glob（`*?[`）を含むなら `glob.glob` で展開し、0件なら `"unknown"`。
  それ以外は `classify`。`"block"` か、`"unknown"` かつ `looks_guarded` なら、中身を出さないコマンドでない限り止める

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_cat_owner_only_blocked(self):              # cat ~/.zshrc.local → 2
def test_cat_world_readable_allowed(self):          # cat ~/.config/starship.toml → 0
def test_ls_and_stat_allowed(self):                 # ls -l ~/.config/app/token / stat ... → 0
def test_find_without_exec_allowed(self):           # find ~/.config -perm 600 → 0
def test_find_with_exec_blocked(self):              # find ~/.config -name token -exec cat {} \; → 2
def test_grep_recursive_on_config_blocked(self):    # grep -r KEY ~/.config → 2
def test_copy_source_blocked(self):                 # cp ~/.config/app/token /tmp/x → 2
def test_redirect_source_blocked(self):             # wc -c < ~/.config/app/token → 2
def test_pipeline_second_command_blocked(self):     # echo a | cat ~/.zshrc.local → 2
def test_unresolvable_home_variable_blocked(self):  # cat $HOME/.config/app/$NAME → 2
def test_glob_in_range_blocked(self):               # cat ~/.config/app/* → 2
def test_show_config_structure_allowed(self):       # ~/.claude/bin/show-config-structure ~/.claude/settings.json → 0
def test_repo_commands_allowed(self):               # git status / python3 tests/... → 0
def test_cd_then_relative_path_blocked(self):       # cd ~ && cat .config/app/token → 2
def test_wc_allowed(self):                          # wc -l ~/.zshrc.local → 0
```

- [ ] **Step 2: 実行して失敗を確かめる**

Run: `python3 -m unittest tests.test_guard_secret_read -v`
Expected: Bash の新しいテストが FAIL

- [ ] **Step 3: `check_bash` を実装し、`main` の Bash 分岐から呼ぶ**

- [ ] **Step 4: 実行して通ることを確かめる**

Run: `python3 -m unittest tests.test_guard_secret_read -v`
Expected: PASS

- [ ] **Step 5: コミット**（RED と GREEN で1回ずつ）

### Task 4: 配線と層1（`settings.json.template`）

**Files:**
- Modify: `settings.json.template`（`hooks.PreToolUse` と `permissions.deny`）
- Test: `tests/test_guard_secret_read_wiring.py`（新規）

**Interfaces:**
- フックの登録: `PreToolUse` に matcher `"Read|Grep|Bash"` のグループを足す。command は既存と同じ形
  `if [ -f ~/.claude/hooks/guard-secret-read.py ]; then python3 ~/.claude/hooks/guard-secret-read.py; else echo '{"systemMessage":"..."}'; fi`
  （ファイルが無いときに全 Bash を止めない既存の決まり。`tests/test_missing_hook_files.py` がこれを検査する）
- 足す deny（`Read(...)` の形）: `~/.zshrc.local`、`~/.gitconfig.local`、`~/.claude/settings.json`、`~/.claude/settings.*.json`、`~/.claude/.credentials.json`、
  `~/.claude/backups/**`、`~/.codex/config.toml`、`~/.codex/config.toml.*`、`~/.codex/*.bak`、`~/.codex/*.config.toml`、`~/.codex/auth.json`、`~/.codex/history.jsonl`、
  `~/.codex-personal/**`、`~/.config/cw-workspace-local/**`、`~/.config/github-copilot/**`、`~/.gnupg/**`、
  `~/.config/**/*token*`、`~/.config/**/*secret*`、`~/.config/**/*credential*`、`~/.config/**/auth.json`、`~/.config/**/*.pem`、`~/.config/**/*.key`
  （名前のパターンは `~/.config` 配下だけにする。`~/.claude` 配下の plugin や submodule の文書を巻き込まないため）

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_registered_for_read_grep_bash(self):   # PreToolUse に matcher "Read|Grep|Bash" で guard-secret-read.py がある
def test_not_registered_for_codex(self):        # codex/hooks.json に "guard-secret-read" の文字列が無い
def test_deny_covers_leaked_files(self):        # deny に Read(~/.zshrc.local)・Read(~/.codex/config.toml)・Read(~/.claude/settings.json) がある
def test_deny_name_patterns_scoped_to_config(self):  # *token* などのパターンは "Read(~/.config/" で始まる
```

- [ ] **Step 2: 実行して失敗を確かめる**

Run: `python3 -m unittest tests.test_guard_secret_read_wiring tests.test_missing_hook_files -v`
Expected: wiring の4件が FAIL、missing_hook_files は PASS

- [ ] **Step 3: `settings.json.template` を編集する**

- [ ] **Step 4: 実行して通ることを確かめる**

Run: `python3 -m unittest tests.test_guard_secret_read_wiring tests.test_missing_hook_files -v`
Expected: PASS

- [ ] **Step 5: コミット**（RED と GREEN で1回ずつ）

### Task 5: ADR と backlog

**Files:**
- Create: `docs/adr/0043-secret-read-guard.md`
- Modify: `tasks/backlog.md`

- [ ] **Step 1: ADR を書く。** 採用した3層と、採らなかった案と理由を残す: 出力側の伏せ字（外れると値が出る。2026-10-29に2回漏れた型）、
  パスの一覧だけ（置き場所が増えるたびに足す必要がある）、sandbox（SSH の git push や Go 製 CLI の TLS が壊れる）、
  `guard-dangerous-bash.py` に足す（Codex と共有していて、振る舞いを変えないことを配線で保証できない）、
  層3で `hooks` の値を出す（コマンド文字列にトークンを直書きしうる）
- [ ] **Step 2: backlog に積む。** Codex への展開。`python3 -c` などの中でパスを組み立てて読む経路（受け入れた抜け道）。ファイルが無いときにフックが止めない決まりと fail-close の食い違い。MCP のファイル読み取りツール。
  `~/.claude/settings.json` の `ANTHROPIC_AUTH_TOKEN` を `apiKeyHelper` などで外へ出すか（決めること付き）
- [ ] **Step 3: コミット**

### Task 6: 全件テスト・security-reviewer・実機確認

- [ ] **Step 1:** `bash tests/run.sh --all` が通ることを確かめる
- [ ] **Step 2:** security-reviewer に、ブランチの差分と設計書のパスを渡して意味レビューを受ける。Critical か `Confidence: insufficient` なら利用者に見せて確認を取る
- [ ] **Step 3:** 利用者の了承を得てから、本体で `bash setup.sh --claude` を実行し、`~/.claude/settings.json` を作り直す
- [ ] **Step 4:** 実機で確かめる（値は出さない）: Read ツールで `~/.zshrc.local` が拒否される、`cat ~/.config/cw-workspace-local/asana-access-token` が拒否される、
  `show-config-structure ~/.claude/settings.json` で `env.ANTHROPIC_AUTH_TOKEN: str = <伏せた>` が出る、`~/.claude/skills/learning-mode/SKILL.md` を Read できる
- [ ] **Step 5:** PR を作る
