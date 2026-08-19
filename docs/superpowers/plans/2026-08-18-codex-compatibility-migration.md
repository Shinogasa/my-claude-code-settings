# Codex Compatibility Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude Code 向け資産を、Codex では互換性を確認したものだけ有効にする再現可能な設定へ移行する。

**Architecture:** ポリシー・知識は共有正本に残し、instructions、commands、agents、hooks、plugins、statusline の発火部分をホスト別アダプターに分ける。Codexはnative-firstとし、自動移行されたpluginはpolicyで明示allowされたものだけを実行する。学習用コード参加はpluginではなく共有ruleへ統合する。

**Tech Stack:** Bash, Python 3.11+, JSON, TOML, unittest, Claude Code settings, Codex CLI 0.147+

---

## File map

| File | 責務 |
|---|---|
| `AGENTS.md` | このリポジトリでだけ必要な Codex project guidance。グローバル指示を複製しない |
| `skills/codex-cli-best-practice/SKILL.md` | Codex 設定作業を公式資料優先で案内する |
| `codex/plugin-policy.json` | Codex での Claude 由来プラグイン判定を version control する |
| `bin/audit-codex-plugins.py` | `codex plugin list --json` と policy の差を検出する。状態は変更しない |
| `rules/learning-mode.md` | pluginに依存しないコード参加の発火条件、上限、停止、振り返りを定義する |
| `settings.json.template` | Claude側で重複する`learning-output-style`を無効にする |
| `setup.sh` | Claude-only / Codex-only を独立してセットアップする |
| `hooks/detect-parallel-sessions.sh` | 実行ホストに依存せず helper を解決する |
| `commands/` | Claude Code の command 正本として維持する |
| `skills/source-command-*` | Codex の command 相当。deprecated prompts を置換する |
| `tests/test_host_activation.py` | instructions、setup、配線のホスト境界を固定する |
| `tests/test_codex_plugin_policy.py` | plugin policy の schema と分類漏れを固定する |
| `tests/test_learning_mode_contract.py` | コード参加が既存の上限・OFF条件・除外条件に従うことを固定する |
| `tests/test_detect_parallel_sessions_hook.py` | Codex-only path と SessionStart 出力契約を固定する |

### Task 1: Codex project guidance をグローバル指示の差分へ縮める

**Files:**

- Create: `skills/codex-cli-best-practice/SKILL.md`
- Modify: `AGENTS.md`
- Create: `tests/test_host_activation.py`

- [ ] **Step 1: Write the failing instruction-boundary test**

```python
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent


class TestCodexProjectGuidance(unittest.TestCase):
    def test_agents_is_a_delta_not_a_rewritten_claude_file(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn("~/.Codex", text)
        self.assertNotIn("/Codex-best-practice", text)
        self.assertLess(len(text.encode()), 2048)
        self.assertIn("codex-cli-best-practice", text)

    def test_codex_best_practice_skill_exists(self):
        skill = ROOT / "skills/codex-cli-best-practice/SKILL.md"
        text = skill.read_text(encoding="utf-8")
        self.assertIn("name: codex-cli-best-practice", text)
        self.assertIn("公式", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run the test and verify the current duplicate fails**

Run: `python3 -m unittest tests.test_host_activation -v`

Expected: FAIL because `AGENTS.md` contains `~/.Codex`, references the missing skill, and exceeds 2 KiB.

- [ ] **Step 3: Replace `AGENTS.md` with Codex-only delta guidance**

```markdown
# Codex project guidance

このリポジトリでは、グローバル指示は `CLAUDE.md → ~/.codex/AGENTS.md` から既に読み込まれる。
このファイルにはプロジェクト固有の Codex 差分だけを書く。

- Codex 設定の変更・レビューでは `codex-cli-best-practice` skill を読む
- 参照順は Codex 公式資料、ローカル CLI の実測、固定 submodule の順とする
- `codex-cli-best-practice/` の例を、公式資料との突合なしに設定へ転記しない
- Claude Code 由来の plugin、hook、command は `docs/codex-compatibility-audit.md` の判定に従う
```

- [ ] **Step 4: Add the Codex best-practice routing skill**

```markdown
---
name: codex-cli-best-practice
description: Codex CLI設定（AGENTS.md、skills、agents、hooks、plugins、MCP、rules、config.toml）の作成・更新・レビュー時に使う。Claude Codeだけの設定作業では使わない。
---

# Codex CLI ベストプラクティス

1. 対象機能の Codex 公式資料を先に確認する。
2. ローカル `codex --version` と対象 subcommand の `--help` で実装差を確認する。
3. `~/.codex/codex-cli-best-practice/` は索引と例として読み、公式資料と矛盾する記述は採用しない。
4. hooks、plugins、rules は配置だけでなく trust・enabled・runtime output を検証する。
5. 不在を結論にするときは `rules/proving-absence.md` の形式で報告する。
```

- [ ] **Step 5: Run the instruction tests**

Run: `python3 -m unittest tests.test_host_activation -v`

Expected: 2 tests PASS.

- [ ] **Step 6: Commit the instruction boundary**

```bash
git add AGENTS.md skills/codex-cli-best-practice/SKILL.md tests/test_host_activation.py
git commit -m "fix(codex): project guidanceをホスト差分へ縮める"
```

### Task 2: Codex plugin policy を version control する

**Files:**

- Create: `codex/plugin-policy.json`
- Create: `bin/audit-codex-plugins.py`
- Create: `tests/test_codex_plugin_policy.py`
- Modify: `setup.sh`

- [ ] **Step 1: Write the failing policy tests**

```python
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "codex/plugin-policy.json"
AUDITOR = ROOT / "bin/audit-codex-plugins.py"


class TestCodexPluginPolicy(unittest.TestCase):
    def test_every_entry_has_supported_status(self):
        data = json.loads(POLICY.read_text(encoding="utf-8"))
        self.assertEqual(data["schemaVersion"], 1)
        self.assertEqual(data["defaultDenyMarketplaces"], ["claude-plugins-official"])
        for plugin_id, entry in data["plugins"].items():
            with self.subTest(plugin=plugin_id):
                self.assertIn(entry["status"], {"allow", "deny", "review"})
                self.assertTrue(entry["reason"].strip())

    def test_decided_plugin_classification(self):
        data = json.loads(POLICY.read_text(encoding="utf-8"))
        actual = {name: entry["status"] for name, entry in data["plugins"].items()}
        self.assertEqual(actual, {
            "superpowers@openai-curated": "allow",
            "learning-output-style@claude-plugins-official": "deny",
            "security-guidance@claude-plugins-official": "deny",
            "claude-md-management@claude-plugins-official": "deny",
            "context7@claude-plugins-official": "review",
            "serena@claude-plugins-official": "review",
            "asana@claude-plugins-official": "deny",
            "code-review@claude-plugins-official": "deny",
            "gopls-lsp@claude-plugins-official": "deny",
        })

    def test_auditor_reports_enabled_non_allowed_plugins(self):
        spec = importlib.util.spec_from_file_location("auditor", AUDITOR)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        policy = {
            "defaultDenyMarketplaces": ["claude-plugins-official"],
            "plugins": {
                "allowed@openai-curated": {"status": "allow", "reason": "native"},
                "deferred@claude-plugins-official": {"status": "review", "reason": "not tested"},
                "blocked@claude-plugins-official": {"status": "deny", "reason": "incompatible"},
            },
        }
        installed = [
            {"pluginId": "allowed@openai-curated", "marketplaceName": "openai-curated", "enabled": True},
            {"pluginId": "deferred@claude-plugins-official", "marketplaceName": "claude-plugins-official", "enabled": True},
            {"pluginId": "blocked@claude-plugins-official", "marketplaceName": "claude-plugins-official", "enabled": True},
            {"pluginId": "future@claude-plugins-official", "marketplaceName": "claude-plugins-official", "enabled": True},
            {"pluginId": "personal@local", "marketplaceName": "local", "enabled": True},
        ]
        self.assertEqual(module.find_violations(policy, installed), [
            "blocked@claude-plugins-official",
            "deferred@claude-plugins-official",
            "future@claude-plugins-official",
        ])

    def test_disabled_plugin_is_not_a_violation(self):
        spec = importlib.util.spec_from_file_location("auditor", AUDITOR)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        policy = {
            "defaultDenyMarketplaces": ["claude-plugins-official"],
            "plugins": {},
        }
        installed = [{
            "pluginId": "future@claude-plugins-official",
            "marketplaceName": "claude-plugins-official",
            "enabled": False,
        }]
        self.assertEqual(module.find_violations(policy, installed), [])
```

- [ ] **Step 2: Run the policy test and verify missing files fail**

Run: `python3 -m unittest tests.test_codex_plugin_policy -v`

Expected: FAIL because the policy and auditor do not exist.

- [ ] **Step 3: Add the reviewed policy**

```json
{
  "schemaVersion": 1,
  "defaultDenyMarketplaces": ["claude-plugins-official"],
  "plugins": {
    "superpowers@openai-curated": {"status": "allow", "reason": "Codex native skill distribution"},
    "learning-output-style@claude-plugins-official": {"status": "deny", "reason": "Code participation moves to the shared learning-mode rule"},
    "security-guidance@claude-plugins-official": {"status": "deny", "reason": "Claude asyncRewake and SessionStart handshake are incompatible"},
    "claude-md-management@claude-plugins-official": {"status": "deny", "reason": "CLAUDE.md-only workflow does not model Codex AGENTS.md hierarchy"},
    "context7@claude-plugins-official": {"status": "review", "reason": "Re-evaluate a current Codex-oriented option when the capability is needed"},
    "serena@claude-plugins-official": {"status": "review", "reason": "Re-evaluate a current Codex-oriented option when the capability is needed"},
    "asana@claude-plugins-official": {"status": "deny", "reason": "Installed artifact exposes only a Claude command"},
    "code-review@claude-plugins-official": {"status": "deny", "reason": "Installed artifact exposes only a Claude command; Codex has native review"},
    "gopls-lsp@claude-plugins-official": {"status": "deny", "reason": "No observed Go workflow gap justifies an unverified LSP plugin"}
  }
}
```

- [ ] **Step 4: Implement the read-only auditor**

```python
#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def find_violations(policy_doc, installed):
    policy = policy_doc["plugins"]
    default_deny = set(policy_doc.get("defaultDenyMarketplaces", []))
    violations = []
    for plugin in installed:
        if not plugin.get("enabled"):
            continue
        plugin_id = plugin.get("pluginId", "")
        entry = policy.get(plugin_id)
        if entry is not None:
            if entry.get("status") != "allow":
                violations.append(plugin_id)
        elif plugin.get("marketplaceName") in default_deny:
            violations.append(plugin_id)
    return sorted(violations)


def main():
    policy_doc = json.loads((ROOT / "codex/plugin-policy.json").read_text(encoding="utf-8"))
    result = subprocess.run(["codex", "plugin", "list", "--json"], check=True, text=True, capture_output=True)
    installed = json.loads(result.stdout).get("installed", [])
    violations = find_violations(policy_doc, installed)
    if violations:
        print("Codexで無効化が必要なプラグイン:")
        for plugin_id in violations:
            print(f"- {plugin_id}")
        return 1
    print("Codex plugin policy: allow以外のClaude由来プラグインは無効")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Add a setup warning without mutating unknown plugins**

After Codex link setup, run the auditor. A policy violation prints the exact plugin IDs that must be disabled.
`setup.sh` does not mutate plugin state. Unlisted plugins from `claude-plugins-official` fail closed;
unlisted plugins from other marketplaces remain outside this migration policy.

Remove the existing `remove_duplicate_codex_plugins` function and its call. A same-name Claude marketplace copy
is also a default-deny violation and must be disabled without deleting its config or cache.

```bash
if ! python3 "$SCRIPT_DIR/bin/audit-codex-plugins.py"; then
  yellow "  allowされていないClaude由来pluginをCodex側で無効化してください"
  yellow "  /pluginsを開き、上のpluginを選んでSpaceで無効化してください（removeはしません）"
fi
```

- [ ] **Step 6: Run policy tests and disable non-allowed plugins without removing them**

Run: `python3 -m unittest tests.test_codex_plugin_policy -v`

Expected: 4 tests PASS.

Then open `/plugins`, select each reported plugin, and press Space to set it to disabled. Do not run
`codex plugin remove`: removal deletes the local config entry and cache, while `review` intentionally retains
the installed artifact for later evaluation.

```bash
codex plugin list --json
python3 bin/audit-codex-plugins.py
```

Expected: every non-allowed `claude-plugins-official` entry remains installed with `enabled: false`, the auditor
exits 0, and Claude Code plugin state remains unchanged.

- [ ] **Step 7: Commit plugin policy**

```bash
git add codex/plugin-policy.json bin/audit-codex-plugins.py tests/test_codex_plugin_policy.py setup.sh
git commit -m "feat(codex): 移行プラグインをpolicyで監査する"
```

### Task 3: コード参加を共有学習モードへ統合する

**Files:**

- Modify: `rules/learning-mode.md`
- Modify: `settings.json.template`
- Modify: `README.md`
- Create: `tests/test_learning_mode_contract.py`

- [ ] **Step 1: Write the failing learning-mode contract test**

```python
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent


class TestLearningModeCodeContribution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rule = (ROOT / "rules/learning-mode.md").read_text(encoding="utf-8")

    def test_code_contribution_is_bounded_learning_event(self):
        for phrase in ["コード参加", "5〜10行", "代替学習イベント", "1タスク最大2回"]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.rule)

    def test_code_contribution_has_skip_and_exclusions(self):
        for phrase in ["スキップ", "設定", "ボイラープレート", "明白な実装", "単純CRUD"]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.rule)

    def test_claude_plugin_is_disabled_after_rule_migration(self):
        settings = json.loads((ROOT / "settings.json.template").read_text(encoding="utf-8"))
        self.assertFalse(settings["enabledPlugins"]["learning-output-style@claude-plugins-official"])

    def test_codex_policy_denies_the_duplicated_plugin(self):
        policy = json.loads((ROOT / "codex/plugin-policy.json").read_text(encoding="utf-8"))
        self.assertEqual(
            policy["plugins"]["learning-output-style@claude-plugins-official"]["status"],
            "deny",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run the test and verify the missing contract fails**

Run: `python3 -m unittest tests.test_learning_mode_contract -v`

Expected: FAIL because the shared rule has no code-contribution contract and the Claude plugin is enabled.

- [ ] **Step 3: Add the code-contribution branch to `learning-mode.md`**

Add this section after the existing trigger-gate section. It is an alternative to ★ Predict, not an extra
question stacked on the same decision.

```markdown
## コード参加（★ Predictの代替学習イベント）

学習モードがONで、次を全て満たす実装判断では、選択肢による★ Predictの代わりに
ユーザーが意味のある5〜10行を実装するコード参加を使える。1回のコード参加は、
1タスク最大2回の学習機会を1回消費する。

- 実装タスクであり、設定・セットアップではない
- 業務ロジック、エラー処理、アルゴリズム、データ構造、UX、アーキテクチャのいずれかである
- 複数の成立する実装があり、ユーザーの判断が振る舞いを変える
- 5〜10行へ安全に切り出せ、既存テストまたは小さい追加テストで検証できる

依頼前に、対象ファイル、周辺コード、関数シグネチャ、目的コメント、TODOを用意する。
答えやトレードオフを先に開示せず、正確なファイルと位置、満たすべき入出力制約だけを伝え、
ユーザーに実装を依頼してそのメッセージを終える。

実装を受け取ったら、なぜその形を選んだかだけを自由記述で問い、そのメッセージを終える。
次の応答でテストとレビューを行い、既存形式の★ Deltaと学習記録を返す。

ユーザーは「スキップ」と答えられる。スキップは1回として数え、エージェントが実装を完了する。
ボイラープレート、反復コード、明白な実装、設定、単純CRUDでは依頼しない。
既存の「全部やって」「任せる」「急ぎ」「予測なしで」によるOFF条件はコード参加にも適用する。
```

- [ ] **Step 4: Disable the duplicated Claude plugin and document the source of truth**

Set the template entry to false:

```json
"learning-output-style@claude-plugins-official": false
```

In `README.md`, state that code participation now lives in `rules/learning-mode.md` for both hosts and that
the upstream plugin remains disabled to avoid duplicate prompting. The Codex declarative policy is checked here;
its effective `enabled: false` state is verified by the auditor in Task 2 and again in the runtime smoke test.

- [ ] **Step 5: Run the learning contract and JSON checks**

Run:

```bash
python3 -m unittest tests.test_learning_mode_contract -v
python3 -m json.tool settings.json.template >/dev/null
```

Expected: 4 tests PASS and the JSON parser exits 0.

- [ ] **Step 6: Commit the shared learning behavior**

```bash
git add rules/learning-mode.md settings.json.template README.md tests/test_learning_mode_contract.py
git commit -m "feat(learning): コード参加を共有学習モードへ統合する"
```

### Task 4: `setup.sh` をホストごとに独立させる

**Files:**

- Modify: `setup.sh`
- Modify: `tests/test_host_activation.py`
- Modify: `hooks/detect-parallel-sessions.sh`
- Modify: `tests/test_detect_parallel_sessions_hook.py`

- [ ] **Step 1: Add a failing Codex-only setup integration test**

Add a real setup fixture to `tests/test_host_activation.py`; do not prove host independence with source-string
assertions. Copy the repository without `.git`, `.gitmodules`, or `.env`, create only `~/.codex`, and place a
stub `codex` command first on `PATH` so the test never reads or mutates the developer's real config.

```python
import os
import shutil
import subprocess
import tempfile


class TestSetupHostIndependence(unittest.TestCase):
    def test_codex_only_setup_runs_in_clean_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            repo = fixture / "repo"
            shutil.copytree(
                ROOT,
                repo,
                ignore=shutil.ignore_patterns(".git", ".gitmodules", ".env", "__pycache__"),
            )
            home = fixture / "home"
            (home / ".codex").mkdir(parents=True)
            fake_bin = fixture / "bin"
            fake_bin.mkdir()
            codex = fake_bin / "codex"
            codex.write_text(
                "#!/bin/sh\n"
                "if [ \"$1 $2\" = \"plugin list\" ]; then\n"
                "  printf '%s\\n' '{\"installed\":[{\"pluginId\":\"superpowers@openai-curated\",\"marketplaceName\":\"openai-curated\",\"enabled\":true}]}'\n"
                "  exit 0\n"
                "fi\n"
                "exit 1\n",
                encoding="utf-8",
            )
            codex.chmod(0o755)
            env = os.environ | {
                "HOME": str(home),
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
            }

            result = subprocess.run(
                ["bash", str(repo / "setup.sh")],
                cwd=repo,
                env=env,
                text=True,
                capture_output=True,
                timeout=60,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((home / ".claude").exists())
            self.assertEqual((home / ".agents/skills").resolve(), (repo / "skills").resolve())
            self.assertEqual((home / ".codex/bin").resolve(), (repo / "bin").resolve())
            self.assertEqual(
                (home / ".codex/codex-cli-best-practice").resolve(),
                (repo / "codex-cli-best-practice").resolve(),
            )
            self.assertFalse((home / ".codex/prompts").exists())
```

- [ ] **Step 2: Run the integration test and verify the current early exit fails**

Run: `python3 -m unittest tests.test_host_activation -v`

Expected: FAIL because the current script exits when `~/.claude` is absent.

- [ ] **Step 3: Separate host detection from host setup**

Use two booleans and skip only the unavailable host. Do not return from the whole script while either host exists.

```bash
claude_available=false
codex_available=false
[ -d "$CLAUDE_DIR" ] && claude_available=true
[ -d "$CODEX_DIR" ] && codex_available=true

if [ "$claude_available" = false ] && [ "$codex_available" = false ]; then
  red "エラー: Claude Code と Codex の設定ディレクトリがどちらも存在しません。"
  exit 1
fi
```

Guard Claude settings generation, Claude plugin install, personal profile generation, and Claude PATH guidance with
`if [ "$claude_available" = true ]`. Keep repository-local git hooks independent of both hosts.

- [ ] **Step 4: Update Codex targets**

The Codex target list becomes. `skills/codex-cli-best-practice/SKILL.md` reaches the Agent Skills root through
the `skills` link; the separate `codex-cli-best-practice` target exposes the repository submodule that the skill
reads as reference material.

```bash
TARGETS+=(
  "skills:$AGENTS_DIR/skills"
  "rules:$CODEX_DIR/rules"
  "CLAUDE.md:$CODEX_DIR/AGENTS.md"
  "hooks:$CODEX_DIR/hooks"
  "bin:$CODEX_DIR/bin"
  "codex/hooks.json:$CODEX_DIR/hooks.json"
  "codex/agents:$CODEX_DIR/agents"
  "codex-cli-best-practice:$CODEX_DIR/codex-cli-best-practice"
)
```

- [ ] **Step 5: Make parallel-session helper host-neutral**

Resolve the helper from the same host first, then the other host for backward compatibility:

```bash
helper="${CODEX_HOME:-$HOME/.codex}/bin/detect-parallel-sessions"
if [ ! -x "$helper" ]; then
  helper="$HOME/.claude/bin/detect-parallel-sessions"
fi
[ -x "$helper" ] || exit 0
```

Add a test that creates a temporary Codex home with the helper only under `.codex/bin`, invokes the hook with
`CODEX_HOME` set to that directory, and asserts that the helper is called.

- [ ] **Step 6: Run host and hook tests**

Run:

```bash
python3 -m unittest tests.test_host_activation tests.test_detect_parallel_sessions_hook -v
bash -n setup.sh hooks/detect-parallel-sessions.sh
```

Expected: all tests PASS and both scripts pass syntax check.

- [ ] **Step 7: Commit host-independent setup**

```bash
git add setup.sh hooks/detect-parallel-sessions.sh tests/test_host_activation.py tests/test_detect_parallel_sessions_hook.py
git commit -m "fix(setup): ClaudeとCodexのセットアップを独立させる"
```

### Task 5: Codex custom prompts を skills へ集約する

**Files:**

- Modify: `skills/verification-loop/SKILL.md`
- Modify: `skills/tdd-workflow/SKILL.md`
- Modify: `skills/source-command-build-fix/SKILL.md`
- Modify: `skills/source-command-plan/SKILL.md`
- Modify: `skills/source-command-refactor-clean/SKILL.md`
- Modify: `README.md`
- Modify: `tests/test_host_activation.py`

- [ ] **Step 1: Add a failing deprecated-prompt test**

```python
    def test_setup_does_not_link_commands_to_codex_prompts(self):
        text = (ROOT / "setup.sh").read_text(encoding="utf-8")
        self.assertNotIn("$CODEX_DIR/prompts", text)
```

- [ ] **Step 2: Replace host-specific tool names in shared skills**

Apply these exact wording changes:

- `Use Read tool` → `Read the relevant file with an available file-reading tool`
- `Use Edit tool` → `Apply the smallest available file edit`
- `use Grep` → `search the repository text, preferring rg when available`
- `Claude Code sessions` → `coding-agent sessions`
- `/verify` → `the host's verification skill or verification-loop`

Keep Claude command files unchanged; only shared Codex skills need host-neutral wording.

- [ ] **Step 3: Map the four remaining commands**

- `code-review`: document Codex native `/review` as the replacement; do not duplicate `.claude/PRPs` behavior
- `quality-gate` and `verify`: route users to `verification-loop`
- `tdd`: route users to `tdd-workflow`

No new prompt files are added. `commands/` remains Claude-only after Task 4 removes its Codex link.

- [ ] **Step 4: Run skill metadata and host-boundary checks**

Run:

```bash
python3 -m unittest tests.test_host_activation -v
rg -n 'Use (Read|Edit) tool|use Grep|Claude Code sessions' skills
```

Expected: tests PASS and `rg` returns no matches in shared skills except the intentionally Claude-specific
`skills/claude-code-best-practice`.

- [ ] **Step 5: Commit prompt migration**

```bash
git add skills README.md tests/test_host_activation.py
git commit -m "refactor(codex): deprecated promptsをskillsへ集約する"
```

### Task 6: Runtime smoke tests と運用証跡を固定する

**Files:**

- Create: `docs/codex-runtime-smoke-test.md`
- Modify: `tasks/backlog.md`

- [ ] **Step 1: Verify repository-owned hooks**

Run the full hook tests and then start one disposable Codex session after approving only the repository hook definitions in `/hooks`.

```bash
python3 -m unittest tests.test_guard_dangerous_bash tests.test_warn_branch_behind_main tests.test_detect_parallel_sessions_hook -v
```

Expected: all tests PASS. In the disposable session, SessionStart produces no invalid JSON error.

- [ ] **Step 2: Verify representative agents**

Spawn these three roles:

- `code-explorer`: attempts one read and one file creation; creation must be denied by read-only sandbox
- `code-simplifier`: creates and removes one file under a temporary directory; workspace write must succeed
- `planner`: report active model and reasoning mode from runtime metadata without editing files

Record observed model, sandbox result, and Codex version in `docs/codex-runtime-smoke-test.md`.

- [ ] **Step 3: Verify plugin policy in a fresh Codex session**

Run:

```bash
python3 bin/audit-codex-plugins.py
codex plugin list --json
```

Expected: the auditor exits 0; `superpowers@openai-curated` may be enabled; every installed plugin from a
default-deny marketplace is disabled unless explicitly `allow`. Disabled entries remain installed in the cache.
Start a fresh session and confirm there is no SessionStart JSON error and no `learning-output-style` developer
instruction. Do not enable `context7` or `serena` in this migration; their selection is a separate backlog item.

- [ ] **Step 4: Verify learning-mode code participation on both hosts**

Prepare one disposable repository with a 5-10 line business-logic TODO that has two valid implementations, plus
one configuration-only task. Start fresh Claude Code and Codex sessions so both read the same
`rules/learning-mode.md`, and run the same two prompts on each host.

Pass criteria:

- the implementation task produces exactly one code-participation request before the agent fills the TODO
- replying `スキップ` causes the agent to complete and verify the implementation
- the configuration-only task does not produce a code-participation request
- neither host exceeds the existing two-event task limit or emits `★ Insight`

Record the host version, prompt fixture, transcript/session reference, and observed result in
`docs/codex-runtime-smoke-test.md`. If either host misses the expected branch, record it as a failed runtime check;
do not treat the rule's wording test as proof of behavior.

- [ ] **Step 5: Verify the official default statusline without customizing it**

Start a disposable Codex session with no explicit `tui.status_line` setting. Confirm the default footer is visible
and record the observed default fields in `docs/codex-runtime-smoke-test.md`. Do not create a Codex statusline
adapter and do not persist a custom item list.

- [ ] **Step 6: Run the full repository suite**

```bash
python3 -m unittest discover -s tests -v
bash -n setup.sh hooks/*.sh bin/ccp bin/detect-parallel-sessions
python3 -m json.tool settings.json.template >/dev/null
python3 -m json.tool codex/hooks.json >/dev/null
python3 -m json.tool codex/plugin-policy.json >/dev/null
python3 -m unittest tests.test_codex_agents -v
```

Expected: all unittest cases PASS, shell/JSON checks exit 0, and `test_no_drift` reports no agent-generation drift.

- [ ] **Step 7: Commit runtime evidence**

```bash
git add docs/codex-runtime-smoke-test.md tasks/backlog.md
git commit -m "docs(codex): 移行後の実機検証結果を記録する"
```
