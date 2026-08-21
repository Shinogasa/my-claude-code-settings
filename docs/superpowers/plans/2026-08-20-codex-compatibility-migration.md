# Codex Compatibility Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox
> syntax for tracking.

**Goal:** Claude Code向け資産の共有正本を保ちながら、Codexではnative-firstなallowlist、
明示的なホスト選択、安全な衝突処理、実機検証を備えた再現可能な設定へ移行する。

**Architecture:** 共有するポリシーと知識はCLAUDE.md、rules、skills、agentsを正本とし、
発火・配置・モデル・hookはホスト別adapterへ分離する。setupは選択ホスト全体をpreflightしてから
applyし、所有権を証明できない既存物を自動変更しない。Codexのsuperpowers読込と
セキュリティレビューはADR 0004の段階的な実行経路を使う。

**Tech Stack:** Bash, Python 3.11+, JSON, TOML, unittest, Claude Code, Codex CLI

---

## Decision baseline

- ADR 0003: Codex pluginはnative-first。claude-plugins-officialはdefault deny
- ADR 0004: superpowersはCodex SessionStart hookで注入し、セキュリティ境界だけLunaでレビュー
- 常駐ルール: learning-mode、proving-absence、task-management、parallel-worktree、
  output-formatting、persona、security-review-policy
- skillsは共有正本を維持し、shared、claude、codexのmanifestで配布先だけを選ぶ
- setupは --claude、--codex、--all のいずれかを必須にする
- 通常実行は衝突を1件でも検出したら、選択した全ホストを変更前に中断する
- --replace-conflicts は再検査後、全衝突をホスト別backupへ退避して置換する
- setup所有の生成物は前回checksumと現在値が一致するときだけ通常更新できる
- plugin失敗は独立処理を続行して最後に集約し、ターミナル表示と非ゼロ終了だけを残す
- hookの信頼承認はsetupを止めず、初回Codex起動時に /hooks で行うよう警告する
- Codex custom promptsは廃止し、skillsまたは標準機能へ移す
- context7とserenaは移行完了後、実務上必要になった時点で個別評価する
- Codex statuslineは公式defaultを維持し、具体的な不足を観測するまでadapterを作らない
- Everything Claude Code由来の34資産は本移行で削除せず、runtime検証後の別タスクで棚卸しする

## File map

| File | Responsibility |
|---|---|
| CLAUDE.md | 両ホストで共有するグローバル指示と常駐ルールの索引 |
| AGENTS.md | このリポジトリ固有のCodex差分。共有指示を複製しない |
| skills/codex-cli-best-practice/SKILL.md | Codex設定作業で公式資料を優先するrouting skill |
| manifests/skills.json | shared、claude、codexのskill配布集合 |
| codex/plugin-policy.json | Codexで許可するpluginの宣言 |
| bin/audit-codex-plugins.py | plugin policy違反を状態変更なしで検出 |
| setup.sh | 明示ホスト選択、preflight、apply、plugin失敗集約 |
| bin/setup-state.py | ownership checksum、衝突分類、backup pathを管理 |
| hooks/inject-superpowers.sh | Codex SessionStartへusing-superpowers読込指示を注入 |
| codex/hooks.json | Codex native hook wiring |
| rules/security-review-policy.md | セキュリティ境界、軽量review、上位model確認の共有契約 |
| agents/security-reviewer.md | 共有security reviewer正本 |
| codex/agents/security-reviewer.toml | Lunaを使うread-only生成物 |
| docs/codex-runtime-smoke-test.md | 実機で確認したversion、操作、結果 |

### Task 1: Instruction graphとskill manifestを固定する

**Files:**

- Modify: CLAUDE.md
- Modify: AGENTS.md
- Create: skills/codex-cli-best-practice/SKILL.md
- Create: manifests/skills.json
- Create: tests/test_instruction_graph.py
- Create: tests/test_skill_manifest.py

- [ ] **Step 1: Write failing instruction and manifest tests**

    from pathlib import Path
    import json
    import unittest

    ROOT = Path(__file__).resolve().parent.parent
    CORE_RULES = {
        "rules/learning-mode.md",
        "rules/proving-absence.md",
        "rules/task-management.md",
        "rules/parallel-worktree.md",
        "rules/output-formatting.md",
        "rules/persona.md",
    }

    class TestInstructionGraph(unittest.TestCase):
        def test_shared_instructions_reference_every_core_rule(self):
            text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertIn("セッション開始時に以下をすべて全文読む", text)
            for path in CORE_RULES:
                self.assertIn(path, text)

        def test_project_agents_is_only_a_codex_delta(self):
            text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
            self.assertNotIn("~/.Codex", text)
            self.assertNotIn("/Codex-best-practice", text)
            self.assertLess(len(text.encode()), 4096)

    class TestSkillManifest(unittest.TestCase):
        def test_every_skill_is_classified_once(self):
            data = json.loads((ROOT / "manifests/skills.json").read_text())
            groups = [set(data[name]) for name in ("shared", "claude", "codex")]
            self.assertFalse(groups[0] & groups[1])
            self.assertFalse(groups[0] & groups[2])
            self.assertFalse(groups[1] & groups[2])
            actual = {p.name for p in (ROOT / "skills").iterdir() if p.is_dir()}
            self.assertEqual(set().union(*groups), actual)

- [ ] **Step 2: Run tests and observe the current failures**

Run:

    python3 -m unittest tests.test_instruction_graph tests.test_skill_manifest -v

Expected: FAIL because the Codex skill、security rule、manifestが無く、AGENTS.mdが旧ホスト名を含む。

- [ ] **Step 3: Make CLAUDE.md the shared instruction index**

Keep the language、Git、learning、absence、workflow、core-principle summaries. Add an explicit session-start
instruction that resolves rules relative to each host configuration directory and reads all six existing files in
CORE_RULES. State that a Markdown link is only a route and does not prove transclusion. Task 5 adds the security
policy to this same list when that policy file is created.

- [ ] **Step 4: Replace AGENTS.md with a repository-only Codex delta**

The complete file must contain:

    # Codex project guidance

    グローバル指示は ~/.codex/AGENTS.md から読み込まれる。
    このファイルには、この設定リポジトリで必要なCodex差分だけを書く。

    - Codex設定の変更・レビューでは codex-cli-best-practice skillを読む
    - 根拠はOpenAI公式資料、ローカルCLI実測、固定submoduleの順で採る
    - Claude由来資産は docs/adr/0003-codex-native-first-activation-policy.md に従う
    - runtimeの強制境界は docs/adr/0004-codex-runtime-enforcement-policy.md に従う

- [ ] **Step 5: Add the Codex best-practice routing skill**

Create a valid SKILL.md that requires official OpenAI documentation first、then local CLI help、then the
codex-cli-best-practice submodule. It must explicitly cover AGENTS.md、skills、agents、hooks、plugins、
MCP、rules、config.toml and proving-absence.

- [ ] **Step 6: Add the complete host manifest**

manifests/skills.json must use schemaVersion 1. Its claude list contains only
claude-code-best-practice、its codex list contains only codex-cli-best-practice、and shared contains the
remaining nineteen existing skill directories. The test must fail when a directory is added without classification.

- [ ] **Step 7: Verify and commit**

Run:

    python3 -m unittest tests.test_instruction_graph tests.test_skill_manifest -v
    python3 -m json.tool manifests/skills.json >/dev/null

Expected: all tests PASS and JSON validation exits 0.

Commit:

    git add CLAUDE.md AGENTS.md skills/codex-cli-best-practice manifests/skills.json tests/test_instruction_graph.py tests/test_skill_manifest.py
    git commit -m "feat(config): 共有指示とskill配布境界を固定する"

### Task 2: Codex plugin policyをversion controlする

**Files:**

- Create: codex/plugin-policy.json
- Create: bin/audit-codex-plugins.py
- Create: tests/test_codex_plugin_policy.py

- [ ] **Step 1: Write failing policy tests**

Tests must assert schemaVersion 1、defaultDenyMarketplaces equals claude-plugins-official、and the exact
classification from ADR 0003:

- allow: superpowers@openai-curated
- review: context7@claude-plugins-official、serena@claude-plugins-official
- deny: learning-output-style@claude-plugins-official、
  security-guidance@claude-plugins-official、claude-md-management@claude-plugins-official、
  asana@claude-plugins-official、code-review@claude-plugins-official、
  gopls-lsp@claude-plugins-official

find_violations must report enabled review、deny、and unlisted plugins from the default-deny marketplace,
while ignoring disabled entries and unlisted personal marketplaces.

- [ ] **Step 2: Run the tests and observe missing files**

Run:

    python3 -m unittest tests.test_codex_plugin_policy -v

Expected: FAIL because policy and auditor do not exist.

- [ ] **Step 3: Implement a read-only auditor**

The module exposes:

    def find_violations(policy_doc: dict, installed: list[dict]) -> list[str]
    def load_installed(command: list[str] | None = None) -> list[dict]
    def main() -> int

load_installed executes codex plugin list --json. main prints every violation in sorted order and returns 1
when any violation exists. It never enables、disables、removes、or installs a Codex plugin.

- [ ] **Step 4: Verify and commit**

Run:

    python3 -m unittest tests.test_codex_plugin_policy -v
    python3 -m json.tool codex/plugin-policy.json >/dev/null

Expected: all tests PASS and JSON validation exits 0.

Commit:

    git add codex/plugin-policy.json bin/audit-codex-plugins.py tests/test_codex_plugin_policy.py
    git commit -m "feat(codex): plugin allowlistを監査可能にする"

### Task 3: setupを明示選択とtransactional preflightへ変える

**Files:**

- Modify: setup.sh
- Create: bin/setup-state.py
- Create: tests/test_setup_cli.py
- Create: tests/test_setup_preflight.py
- Modify: tests/test_detect_parallel_sessions_hook.py
- Modify: hooks/detect-parallel-sessions.sh

- [ ] **Step 1: Write failing CLI tests**

Use a temporary HOME and copied repository. The tests invoke setup.sh with a stub claude and codex on PATH.
Assert:

- no host flag exits non-zero and does not create links
- --claude touches only the Claude directories
- --codex touches only the Codex and Agent Skills directories
- --all requires both selected host configuration directories before any mutation
- unknown flags and multiple selector flags fail before mutation

- [ ] **Step 2: Write failing conflict tests**

Create fixtures for missing destinations、correct symlinks、wrong symlinks、unowned files、unchanged managed
generated files、and manually edited generated files. Assert:

- one conflict aborts every selected host before links、generated files、or plugin commands change
- --all aborts both hosts when only one host conflicts
- --replace-conflicts backs up every current conflict and then applies all selected hosts
- backups use the same timestamp under ~/.claude/backups and ~/.codex/backups
- ownership state loss classifies an existing generated file as a conflict

- [ ] **Step 3: Implement the setup-state helper**

bin/setup-state.py owns these operations:

    def sha256_file(path: Path) -> str
    def classify(source: Path, destination: Path, recorded: dict | None) -> str
    def backup_path(host_root: Path, destination: Path, timestamp: str) -> Path
    def load_state(path: Path) -> dict
    def save_state(path: Path, state: dict) -> None

classify returns missing、linked、managed-update、or conflict. A correct symlink is linked. A generated file is
managed-update only when its current SHA-256 equals the previously recorded checksum. Every other existing
destination is conflict. State files live at ~/.claude/.my-claude-code-settings/ownership.json and
~/.codex/.my-claude-code-settings/ownership.json.

- [ ] **Step 4: Parse explicit host selectors before all other work**

setup.sh accepts exactly one of --claude、--codex、--all plus optional --replace-conflicts. It validates every
selected host directory、manifest、template、and source before calling submodule、link、generation、or plugin
operations. With no selector it prints usage and exits 2.

- [ ] **Step 5: Build per-skill and per-host target lists**

Read manifests/skills.json. Create the destination skill directories and link each shared skill plus the selected
host-specific list individually. Do not link the whole skills directory. Do not create ~/.codex/prompts.

Codex targets include ~/.codex/rules、~/.codex/AGENTS.md、~/.codex/hooks、~/.codex/hooks.json、
~/.codex/agents、~/.codex/bin、and ~/.codex/codex-cli-best-practice. Claude-only assets remain under
~/.claude and are never added by --codex.

- [ ] **Step 6: Run preflight before apply**

Collect every conflict for every selected host. A normal run prints host、destination、current kind、expected
source and exits 1 without mutation. With --replace-conflicts, re-run preflight、move conflicts to the
host-specific backup path、then create links and generated files. Record checksums only after successful writes.

- [ ] **Step 7: Aggregate plugin failures**

Claude plugin installation continues across independent plugin IDs. Store host、plugin ID、operation、and exact
retry command in memory. The Codex auditor is also recorded as a failure when it exits non-zero, but setup does
not mutate Codex plugin state. After every independent setup step, print one terminal-only summary and exit 1
when any failure remains. Do not create JSON、log、or history files.

- [ ] **Step 8: Keep hook approval outside setup success**

After placing Codex hooks, print that definitions are installed but awaiting trust review and instruct the user to
open /hooks. Do not query or modify trust state and do not fail setup solely because approval is pending.

- [ ] **Step 9: Make the parallel-session helper host-neutral**

The hook first resolves CODEX_HOME/bin/detect-parallel-sessions、then ~/.claude/bin/detect-parallel-sessions.
Its test supplies only the Codex path and proves the helper is invoked.

- [ ] **Step 10: Verify and commit**

Run:

    python3 -m unittest tests.test_setup_cli tests.test_setup_preflight tests.test_detect_parallel_sessions_hook -v
    bash -n setup.sh hooks/detect-parallel-sessions.sh

Expected: all tests PASS and shell syntax checks exit 0.

Commit:

    git add setup.sh bin/setup-state.py hooks/detect-parallel-sessions.sh tests/test_setup_cli.py tests/test_setup_preflight.py tests/test_detect_parallel_sessions_hook.py
    git commit -m "feat(setup): 明示選択と衝突preflightを導入する"

### Task 4: Learning modeとdeprecated promptsを共有skillsへ統合する

**Files:**

- Modify: rules/learning-mode.md
- Modify: settings.json.template
- Modify: README.md
- Modify: skills/verification-loop/SKILL.md
- Modify: skills/tdd-workflow/SKILL.md
- Modify: skills/source-command-build-fix/SKILL.md
- Modify: skills/source-command-plan/SKILL.md
- Modify: skills/source-command-refactor-clean/SKILL.md
- Create: tests/test_learning_mode_contract.py

- [ ] **Step 1: Add failing contract tests**

Assert that code participation is a bounded alternative to Predict、uses meaningful 5 to 10 lines、counts toward
the two-event limit、supports skip、and excludes configuration、boilerplate、obvious implementations、and simple
CRUD. Assert learning-output-style is disabled in the Claude template and denied by the Codex policy.

- [ ] **Step 2: Integrate code participation into the shared rule**

Prepare the target file、surrounding code、function signature、purpose comment、and a marked implementation
location before asking the user. Ask only where multiple valid choices affect behavior. After receiving the code,
ask for the rationale、verify it、then return the existing Delta format. Do not add Insight output because it
duplicates Delta.

- [ ] **Step 3: Remove Codex custom prompt distribution**

Do not link commands to ~/.codex/prompts. Map code-review to native /review、quality-gate and verify to
verification-loop、and tdd to tdd-workflow. Keep commands as the Claude source and use source-command skills
for Codex discovery.

- [ ] **Step 4: Remove host-specific tool wording from shared skills**

Replace Read/Edit/Grep-specific instructions with capability-based wording. Keep
skills/claude-code-best-practice host-specific through the manifest instead of weakening its Claude instructions.

- [ ] **Step 5: Verify and commit**

Run:

    python3 -m unittest tests.test_learning_mode_contract tests.test_skill_manifest -v
    python3 -m json.tool settings.json.template >/dev/null

Expected: all tests PASS and JSON validation exits 0.

Commit:

    git add rules/learning-mode.md settings.json.template README.md skills/verification-loop/SKILL.md skills/tdd-workflow/SKILL.md skills/source-command-build-fix/SKILL.md skills/source-command-plan/SKILL.md skills/source-command-refactor-clean/SKILL.md tests/test_learning_mode_contract.py
    git commit -m "feat(learning): 学習モードとCodex skill入口を統合する"

### Task 5: Codex runtime enforcementを追加する

**Files:**

- Create: hooks/inject-superpowers.sh
- Modify: codex/hooks.json
- Create: rules/security-review-policy.md
- Modify: CLAUDE.md
- Modify: agents/security-reviewer.md
- Regenerate: codex/agents/security-reviewer.toml
- Create: tests/test_codex_runtime_policy.py
- Modify: tests/test_instruction_graph.py
- Modify: tests/test_codex_agents.py

- [ ] **Step 1: Write failing SessionStart tests**

Invoke inject-superpowers.sh with startup、resume、clear、compact payloads. Each invocation exits 0 and emits
plain text containing superpowers:using-superpowers. Invalid JSON and non-SessionStart payloads exit non-zero
with a diagnostic on stderr. Assert codex/hooks.json matches all four sources and does not use Claude
asyncRewake fields.

- [ ] **Step 2: Implement the native superpowers injection**

The script validates stdin JSON with Python and prints one short instruction:

    Before responding, read and follow superpowers:using-superpowers from the enabled Codex plugin.

Wire it as a synchronous SessionStart command alongside detect-parallel-sessions.sh. Use plain stdout because
Codex adds SessionStart plain text as developer context. Do not copy the plugin skill body or reference its
versioned cache path.

- [ ] **Step 3: Write the security review policy**

The rule classifies authentication、authorization、user input、API endpoints、file uploads、secrets、payments、
raw SQL、cryptography、external integrations、permissions、and deployment settings as security boundaries.
For matching changes it requires the security-reviewer before completion. For ordinary changes it forbids an
automatic LLM security review. Critical findings or insufficient confidence must be shown to the user before any
stronger model is spawned. Add rules/security-review-policy.md to CLAUDE.md's session-start read list and to
the instruction-graph contract test in the same change.

- [ ] **Step 4: Make the lightweight reviewer read-only**

Remove Write and Edit from agents/security-reviewer.md tools while retaining model sonnet, which the generator
maps to gpt-5.6-luna. Regenerate all Codex TOML files. Extend tests to assert security-reviewer uses Luna and
read-only sandbox.

- [ ] **Step 5: Verify and commit**

Run:

    python3 -m unittest tests.test_codex_runtime_policy tests.test_codex_agents tests.test_instruction_graph -v
    python3 -m json.tool codex/hooks.json >/dev/null
    bash -n hooks/inject-superpowers.sh

Expected: all tests PASS、JSON validation exits 0、and shell syntax exits 0.

Commit:

    git add hooks/inject-superpowers.sh codex/hooks.json rules/security-review-policy.md CLAUDE.md agents/security-reviewer.md codex/agents tests/test_codex_runtime_policy.py tests/test_instruction_graph.py tests/test_codex_agents.py
    git commit -m "feat(codex): 起動規約と段階的security reviewを配線する"

### Task 6: Runtime smoke testsと運用証跡を固定する

**Files:**

- Create: docs/codex-runtime-smoke-test.md

- [ ] **Step 1: Run the full static suite**

Run:

    python3 -m unittest discover -s tests -v
    bash -n setup.sh hooks/*.sh bin/ccp bin/detect-parallel-sessions
    python3 -m json.tool settings.json.template >/dev/null
    python3 -m json.tool codex/hooks.json >/dev/null
    python3 -m json.tool codex/plugin-policy.json >/dev/null
    python3 -m json.tool manifests/skills.json >/dev/null

Expected: zero unittest failures and every syntax validation exits 0.

- [ ] **Step 2: Verify setup in isolated homes**

Run --claude、--codex、and --all against disposable HOME directories. Re-run each selector to prove idempotency.
Add an unowned destination and prove normal execution leaves both selected hosts unchanged. Re-run with
--replace-conflicts and prove the host-specific backup and ownership state permit the next normal update.

- [ ] **Step 3: Review and trust repository-owned hooks**

Start a disposable Codex session、open /hooks、review the exact definitions、and trust them. Record Codex version、
hook source、hash state、and approval result. A fresh startup and a compact continuation must both show
superpowers injection and must not show invalid SessionStart JSON.

- [ ] **Step 4: Verify representative subagents**

Spawn code-explorer for read-only、code-simplifier for workspace-write、and planner for the high-reasoning path.
Record runtime model and sandbox result. The other five agents remain statically verified rather than individually
runtime verified.

- [ ] **Step 5: Verify the security cost boundary**

Use one ordinary documentation diff and one disposable authentication/input-validation diff. The ordinary diff
must not start an LLM security review. The boundary diff must invoke security-reviewer on Luna. Simulate an
insufficient-confidence result and verify the parent asks the user before spawning a stronger model.

- [ ] **Step 6: Verify plugin and learning behavior**

Run bin/audit-codex-plugins.py and codex plugin list --json. Confirm superpowers may be enabled、every
default-deny plugin is disabled、and context7/serena remain unapproved. On both hosts, verify one valid
code-participation task、one skip response、and one configuration task that must not ask for code participation.

- [ ] **Step 7: Verify the official default statusline**

Start a disposable Codex session without an explicit tui.status_line setting. Record the visible default fields.
Do not create a Codex statusline adapter or persist a custom item list.

- [ ] **Step 8: Record evidence and commit**

docs/codex-runtime-smoke-test.md records commands、versions、expected result、observed result、and remaining
limits. Do not edit tasks/backlog.md in this task. If a failed check must be carried over、ask the user after this
commit and create a separate backlog change so existing working-tree edits are not staged accidentally.

Commit:

    git add docs/codex-runtime-smoke-test.md
    git commit -m "docs(codex): 移行後のruntime検証を記録する"

---

## Execution order

Execute one task per commit in numeric order. Stop after each task if its verification fails. Plugin failures may
leave a documented partial state by design, but static preflight failures must leave every selected host unchanged.
