# Codex Plugin Documentation Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `setup.sh` のCodexプラグイン監査専用という実装と、README・互換性監査の現行運用説明を一致させる。

**Architecture:** Codexの実行状態はCodex CLIの設定・キャッシュに残し、リポジトリは `codex/plugin-policy.json` のallowlistを正本とする。`setup.sh --codex` は設定リンクと読み取り専用監査だけを行い、プラグインの導入・更新・削除・有効化は行わない。

**Tech Stack:** Bash, Python 3, JSON, Markdown, unittest

**Spec:** `docs/adr/0003-codex-native-first-activation-policy.md`、`docs/adr/0004-codex-runtime-enforcement-policy.md`

## Global Constraints

- Codex側はnative-firstなallowlistで管理し、`claude-plugins-official`はdefault denyとする。
- `bin/audit-codex-plugins.py` はCodex plugin stateを変更しない。
- 認証情報を含みうる `~/.codex/config.toml` とプラグインキャッシュはGit管理しない。
- 共有ドキュメントには、Claude CodeとCodex CLIの管理経路を混同する説明を書かない。

---

### Task 1: Codex setupの非変更契約を回帰テストで固定する

**Files:**
- Modify: `tests/test_setup_cli.py`

**Interfaces:**
- Consumes: `setup.sh --codex` とテスト用Codex CLI stub
- Produces: `codex plugin list --json` は実行するが、`codex plugin add/remove` は実行しない契約

- [x] **Step 1: 読み取り専用監査の統合テストを追加する**

`SetupCliTests` に、Codex setup後のコマンドログへ `codex plugin list --json` があり、
`codex plugin add` と `codex plugin remove` が無いことを検証するテストを追加する。

- [x] **Step 2: 対象テストを実行する**

Run: `python3 -m unittest tests.test_setup_cli.SetupCliTests.test_codex_setup_audits_without_mutating_plugin_state -v`

Expected: PASS

- [x] **Step 3: コミットする**

```bash
git add tests/test_setup_cli.py
git commit -m "test(codex): setupのplugin監査専用契約を固定する"
```

### Task 2: READMEのCodexプラグイン運用を実装へ同期する

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: `setup.sh`、`bin/audit-codex-plugins.py`、`codex/plugin-policy.json`、現行Codex CLIのhelp
- Produces: 導入経路、監査経路、ローカル状態とGit管理対象の境界を説明する現行手順

- [x] **Step 1: setupが導入しないことを明記する**

既存の「`setup.sh` が公式マーケットプレイスから冪等に導入する」という説明を、
`setup.sh --codex` はリンク配置と読み取り専用監査だけを行う説明へ置き換える。

- [x] **Step 2: CLIによる管理手順を明記する**

`/plugins`、`codex plugin add/list/remove`、`codex plugin marketplace` を、
Codex側のインストール・更新・削除経路として説明する。監査は
`python3 bin/audit-codex-plugins.py` または `bash setup.sh --codex` で行う。

- [x] **Step 3: Claude由来pluginの説明を現行境界へ修正する**

Codexでは `codex/plugin-policy.json` のallowlistとdefault denyで判定し、
Claude側の `settings.json.template` と自動同期しないことを明記する。

### Task 3: 互換性監査の現行運用補足を追加する

**Files:**
- Modify: `docs/codex-compatibility-audit.md`

**Interfaces:**
- Consumes: 既存の2026-08-18監査結果と現行 `setup.sh` / `bin/audit-codex-plugins.py`
- Produces: 歴史的な調査記録を壊さず、現在のCodex plugin管理経路を示す補足

- [x] **Step 1: 歴史的記録と現行実装を分離して追記する**

調査時点の `/import` や旧 `CODEX_PLUGINS` の記述は歴史的記録として残し、
現行実装では `setup.sh` がplugin stateを変更せず、policy監査のみを行うことを追記する。

- [x] **Step 2: READMEから参照される運用説明を確認する**

READMEのリンク先を読み、現行手順と矛盾する箇所がないことを確認する。

### Task 4: 検証と引き渡し

**Files:**
- Test: `tests/test_setup_cli.py`
- Test: `tests/test_codex_plugin_policy.py`
- Test: `tests/test_codex_runtime_policy.py`

- [x] **Step 1: 対象テストを実行する**

Run: `python3 -m unittest tests.test_setup_cli tests.test_codex_plugin_policy tests.test_codex_runtime_policy -v`

Expected: all tests PASS

- [x] **Step 2: BashとJSONを検証する**

Run: `bash -n setup.sh`

Run: `python3 -m json.tool codex/plugin-policy.json >/dev/null`

Expected: exit 0

- [x] **Step 3: 差分とリンク対象を確認する**

Run: `git diff --check`

Run: `rg -n 'setup\.sh.*(導入|install)|CODEX_PLUGINS|/import' README.md docs/codex-compatibility-audit.md`

Expected: 現行運用の誤説明が残っていない。歴史的記録として残す箇所は補足で明示されている。
