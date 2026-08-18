# Codex Compatibility Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude Code 向け資産を、Codex では互換性を確認したものだけ有効にする再現可能な設定へ移行する。

**Architecture:** ポリシー・知識は共有正本に残し、instructions、commands、agents、hooks、plugins、statusline の発火部分をホスト別アダプターに分ける。Codex へ自動移行されたプラグインは policy file と監査コマンドで判定し、非互換なものを実行経路から外す。

**Tech Stack:** Bash, Python 3.11+, JSON, TOML, unittest, Claude Code settings, Codex CLI 0.147+

---

## File map

| File | 責務 |
|---|---|
| `AGENTS.md` | このリポジトリでだけ必要な Codex project guidance。グローバル指示を複製しない |
| `skills/codex-cli-best-practice/SKILL.md` | Codex 設定作業を公式資料優先で案内する |
| `codex/plugin-policy.json` | Codex での Claude 由来プラグイン判定を version control する |
| `bin/audit-codex-plugins.py` | `codex plugin list --json` と policy の差を検出する。状態は変更しない |
| `setup.sh` | Claude-only / Codex-only を独立してセットアップする |
| `hooks/detect-parallel-sessions.sh` | 実行ホストに依存せず helper を解決する |
| `commands/` | Claude Code の command 正本として維持する |
| `skills/source-command-*` | Codex の command 相当。deprecated prompts を置換する |
| `tests/test_host_activation.py` | instructions、setup、配線のホスト境界を固定する |
| `tests/test_codex_plugin_policy.py` | plugin policy の schema と分類漏れを固定する |
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
3. `codex-cli-best-practice/` は索引と例として読み、公式資料と矛盾する記述は採用しない。
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
        for plugin_id, entry in data["plugins"].items():
            with self.subTest(plugin=plugin_id):
                self.assertIn(entry["status"], {"allow", "deny", "review"})
                self.assertTrue(entry["reason"].strip())

    def test_security_guidance_is_denied(self):
        data = json.loads(POLICY.read_text(encoding="utf-8"))
        entry = data["plugins"]["security-guidance@claude-plugins-official"]
        self.assertEqual(entry["status"], "deny")

    def test_auditor_reports_enabled_denied_plugin(self):
        spec = importlib.util.spec_from_file_location("auditor", AUDITOR)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        policy = {"security-guidance@claude-plugins-official": {"status": "deny", "reason": "hook contract"}}
        installed = [{"pluginId": "security-guidance@claude-plugins-official", "enabled": True}]
        self.assertEqual(module.find_violations(policy, installed), ["security-guidance@claude-plugins-official"])
```

- [ ] **Step 2: Run the policy test and verify missing files fail**

Run: `python3 -m unittest tests.test_codex_plugin_policy -v`

Expected: FAIL because the policy and auditor do not exist.

- [ ] **Step 3: Add the reviewed policy**

```json
{
  "schemaVersion": 1,
  "plugins": {
    "superpowers@openai-curated": {"status": "allow", "reason": "Codex native skill distribution"},
    "learning-output-style@claude-plugins-official": {"status": "allow", "reason": "SessionStart injection observed on Codex 0.147.0"},
    "security-guidance@claude-plugins-official": {"status": "deny", "reason": "Claude asyncRewake and SessionStart handshake are incompatible"},
    "claude-md-management@claude-plugins-official": {"status": "review", "reason": "Skill is visible; representative workflow is not smoke-tested"},
    "context7@claude-plugins-official": {"status": "review", "reason": "MCP startup and tool call are not smoke-tested"},
    "serena@claude-plugins-official": {"status": "review", "reason": "MCP startup and tool call are not smoke-tested"},
    "asana@claude-plugins-official": {"status": "deny", "reason": "Installed artifact exposes only a Claude command"},
    "code-review@claude-plugins-official": {"status": "deny", "reason": "Installed artifact exposes only a Claude command; Codex has native review"},
    "gopls-lsp@claude-plugins-official": {"status": "review", "reason": "Codex manifest exists but repository ownership is undecided"}
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


def find_violations(policy, installed):
    return sorted(
        p.get("pluginId", "")
        for p in installed
        if p.get("enabled") and policy.get(p.get("pluginId", ""), {}).get("status") == "deny"
    )


def main():
    policy_doc = json.loads((ROOT / "codex/plugin-policy.json").read_text(encoding="utf-8"))
    result = subprocess.run(["codex", "plugin", "list", "--json"], check=True, text=True, capture_output=True)
    installed = json.loads(result.stdout).get("installed", [])
    violations = find_violations(policy_doc["plugins"], installed)
    if violations:
        print("Codexで無効化が必要なプラグイン:")
        for plugin_id in violations:
            print(f"- {plugin_id}")
        return 1
    print("Codex plugin policy: deny状態の有効プラグインなし")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Add a setup warning without mutating unknown plugins**

After `setup_codex_plugins`, run the auditor. A policy violation prints the exact manual removal command,
but `setup.sh` does not remove `review` or unlisted user plugins.

```bash
if ! python3 "$SCRIPT_DIR/bin/audit-codex-plugins.py"; then
  yellow "  deny対象をCodex側で無効化してください:"
  yellow "    codex plugin remove security-guidance@claude-plugins-official"
fi
```

- [ ] **Step 6: Run policy tests and perform the explicit deny action**

Run: `python3 -m unittest tests.test_codex_plugin_policy -v`

Expected: 3 tests PASS.

Then, after confirming the target from `codex plugin list --json`, run:

```bash
codex plugin remove security-guidance@claude-plugins-official
codex plugin remove asana@claude-plugins-official
codex plugin remove code-review@claude-plugins-official
```

Expected: each command reports only the named plugin as removed. Claude Code plugin state remains unchanged.

- [ ] **Step 7: Commit plugin policy**

```bash
git add codex/plugin-policy.json bin/audit-codex-plugins.py tests/test_codex_plugin_policy.py setup.sh
git commit -m "feat(codex): 移行プラグインをpolicyで監査する"
```

### Task 3: `setup.sh` をホストごとに独立させる

**Files:**

- Modify: `setup.sh`
- Modify: `tests/test_host_activation.py`
- Modify: `hooks/detect-parallel-sessions.sh`
- Modify: `tests/test_detect_parallel_sessions_hook.py`

- [ ] **Step 1: Add failing setup contract tests**

Add these assertions to `tests/test_host_activation.py`:

```python
class TestSetupHostIndependence(unittest.TestCase):
    def test_codex_targets_include_bin_and_best_practice(self):
        text = (ROOT / "setup.sh").read_text(encoding="utf-8")
        self.assertIn('"bin:$CODEX_DIR/bin"', text)
        self.assertIn('"codex-cli-best-practice:$CODEX_DIR/codex-cli-best-practice"', text)

    def test_codex_no_longer_receives_deprecated_prompts(self):
        text = (ROOT / "setup.sh").read_text(encoding="utf-8")
        self.assertNotIn('"commands:$CODEX_DIR/prompts"', text)

    def test_missing_claude_dir_does_not_exit_before_codex_setup(self):
        text = (ROOT / "setup.sh").read_text(encoding="utf-8")
        self.assertNotIn('Claude Code を一度起動してください。\n  exit 1', text)
```

- [ ] **Step 2: Run tests and verify all three fail**

Run: `python3 -m unittest tests.test_host_activation -v`

Expected: FAIL for missing Codex bin/submodule links, deprecated prompts link, and early exit.

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

The Codex target list becomes:

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

### Task 4: Codex custom prompts を skills へ集約する

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

No new prompt files are added. `commands/` remains Claude-only after Task 3 removes its Codex link.

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

### Task 5: Runtime smoke tests と運用証跡を固定する

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

- [ ] **Step 3: Verify review-state plugins one at a time**

For each of `claude-md-management`, `context7`, `serena`, enable only that plugin, start a fresh session, and run one representative read-only operation. Record:

- plugin version
- startup error presence
- authentication prompt/result
- one tool or skill result
- disable/allow decision

Do not test Asana with a write operation. It remains denied unless a Codex-native connector and explicit authorization are selected later.

- [ ] **Step 4: Decide statusline scope from actual Codex footer**

Use `/statusline` to configure the native footer. Compare the available fields with `statusline.js` output.
If host, model, branch, and context usage are available, use native config and leave `statusline.js` Claude-only.
Create a Codex script adapter only when a required field is absent.

- [ ] **Step 5: Run the full repository suite**

```bash
python3 -m unittest discover -s tests -v
bash -n setup.sh hooks/*.sh bin/ccp bin/detect-parallel-sessions
python3 -m json.tool settings.json.template >/dev/null
python3 -m json.tool codex/hooks.json >/dev/null
python3 -m json.tool codex/plugin-policy.json >/dev/null
python3 -m unittest tests.test_codex_agents -v
```

Expected: all unittest cases PASS, shell/JSON checks exit 0, and `test_no_drift` reports no agent-generation drift.

- [ ] **Step 6: Commit runtime evidence**

```bash
git add docs/codex-runtime-smoke-test.md tasks/backlog.md
git commit -m "docs(codex): 移行後の実機検証結果を記録する"
```
