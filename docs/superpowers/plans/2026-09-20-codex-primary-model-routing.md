# Codex Primary Model Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 親セッションの工程境界で、検証済みhandoffと手動モデル切替を状態機械で結び付ける。

**Architecture:** `bin/codex_model_switch.py`がprivate manifest、Git鮮度、validator連携を持ち、`bin/codex-model-switch.py`が薄いCLIを提供する。`hooks/codex-model-switch-hook.py`がCodexの三eventを処理し、同じ状態遷移を使ってpromptとlocal toolを制御する。

**Tech Stack:** Python 3.11+標準ライブラリ、`unittest`、Codex command hooks、既存handoff validator。

**Spec:** `docs/superpowers/specs/2026-09-18-codex-primary-model-routing-design.md`

## Global Constraints

- provider、通常のmodel既定値、既存custom agentのペアを変えない。
- ADR 0011のhandoff schema 1とvalidatorは変更しない。
- sessionごとにpendingは一件だけとし、`.superpowers/model-switch/`のprivate manifestはGit追跡から除外する。
- 初回実装は`runtime-config-verified`を生成せず、通常工程だけ`user-attested`で再開する。
- hookにeffort観測値は無い。resumeではユーザー申告のpairとhook観測modelを照合する。
- hook未承認、無効、timeout、実行不能、hosted toolと特殊tool経路を完全強制と表示しない。
- 外部model呼出しを通常suiteに含めない。

---

## File Map

| File | Responsibility |
|---|---|
| `bin/codex_model_switch.py` | manifestの安全な読書き、begin/publish/resume/override/cancel、validator連携 |
| `bin/codex-model-switch.py` | begin、publish、statusのCLIと固定終了コード |
| `hooks/codex-model-switch-hook.py` | SessionStart、UserPromptSubmit、PreToolUseのJSON契約と拒否 |
| `codex/hooks.json` | 同期hook配線 |
| `tests/test_codex_model_switch.py` | 一時Git repoでCLI、状態、hook、配線を実行して検証 |
| `.gitignore` | private manifestの明示ignore |
| `codex/MODEL_ROUTING.md`、`README.md` | checkpointと手動操作の案内 |
| `tests/test_setup_cli.py`、`setup.sh` | 必要ファイルの配布検査 |

### Task 1: Private manifestとvalidated publish

**Files:** `bin/codex_model_switch.py`、`bin/codex-model-switch.py`、`tests/test_codex_model_switch.py`、`.gitignore`

**Interfaces:** `begin(repo: Path, session_id: str, task_id: str, current_phase: str, next_phase: str, model: str, effort: str, handoff: Path) -> dict`、`publish(repo: Path, session_id: str) -> dict`、`status(repo: Path, session_id: str) -> dict | None`。失敗は`SwitchError`で表し、CLIは終了2にする。

- [x] **Step 1: Write the failing test.** 一時Git repoを作り、`begin`後のstatusが`PREPARING`、handoff schema 1を作った`publish`後が`SWITCH_PENDING`でdigestを持つことを検証する。別session・symlink・validator失敗も拒否を観測する。

```python
result = run_switch("begin", "--session-id", "s1", "--task-id", "task-a",
                    "--current-phase", "design", "--next-phase", "implementation",
                    "--model", "gpt-5.6-luna", "--effort", "medium",
                    "--handoff", ".superpowers/handoffs/task-a.md")
self.assertEqual(result.returncode, 0, result.stderr)
self.assertEqual(run_status("s1")["state"], "PREPARING")
```

- [x] **Step 2: Run RED.** `python3 -m unittest tests.test_codex_model_switch -v`がCLI不在で失敗することを確認する。
- [x] **Step 3: Implement minimal code.** `begin`でvalidator `state`のbranch/HEAD/fingerprintを保存し、`publish`でvalidator `validate`の`INPUT_DIGEST`とhandoff frontmatterのtask/pair/Git識別子を照合する。owner-onlyなdir/file、atomic replace、同一sessionへの再begin拒否を実装する。
- [x] **Step 4: Run GREEN.** `python3 -m unittest tests.test_codex_model_switch -v`を成功させる。
- [x] **Step 5: Commit.** `git add`でTask 1のファイルをstageし、`git commit -m "feat(codex): 切替manifestと検証済みhandoffを管理する"`。

### Task 2: Prompt再開とlocal tool guard

**Files:** `bin/codex_model_switch.py`、`hooks/codex-model-switch-hook.py`、`codex/hooks.json`、`tests/test_codex_model_switch.py`

**Interfaces:** `resume(repo, session_id, transition_id, model, effort, observed_model)`、`override(repo, session_id, transition_id, phase, reason, observed_model)`、`cancel(repo, session_id, transition_id)`。hookはstdinの`hook_event_name`でdispatchし、prompt拒否は公式JSON block、tool拒否はexit 2と日本語のstderrで示す。

- [x] **Step 1: Write the failing test.** `SWITCH_PENDING`で通常prompt、model不一致、effort申告不一致、stale handoff、一般toolを拒否し、完全一致の`MODEL_SWITCH_RESUME <id> <model> <effort>`だけを`ACTIVE`へ移す。overrideは対象phaseだけ、cancelはterminal、別sessionは影響されないことを検証する。

```python
payload = {"hook_event_name": "UserPromptSubmit", "session_id": "s1",
           "cwd": str(repo), "model": "gpt-5.6-luna",
           "prompt": f"MODEL_SWITCH_RESUME {transition_id} gpt-5.6-luna medium"}
result = run_hook(payload)
self.assertEqual(result.returncode, 0, result.stderr)
self.assertEqual(run_status("s1")["state"], "ACTIVE")
```

- [x] **Step 2: Run RED.** 同じ`unittest`で新caseが機能欠落により失敗することを確認する。
- [x] **Step 3: Implement minimal code.** promptを全文一致parseし、resume前にvalidatorへ保存digestを渡す。`PreToolUse`はPREPARINGのhandoff編集・validator・status/publishとPENDINGのvalidator read・status以外を拒否し、Bash入力のshell演算子等を拒否する。SessionStartはsession IDとpending状態を追加contextへ出す。
- [x] **Step 4: Run GREEN.** hookをsubprocessで起動するtestを成功させ、`codex/hooks.json`の同期配線をJSONから検証する。
- [x] **Step 5: Commit.** Task 2のファイルをstageし、`git commit -m "feat(codex): 親工程切替のpromptとtoolを制御する"`。

### Task 3: 配布、運用、実機smoke

**Files:** `setup.sh`、`tests/test_setup_cli.py`、`codex/MODEL_ROUTING.md`、`README.md`

**Interfaces:** `setup.sh --codex`がCLI・hookを既存の`~/.codex/bin`・`~/.codex/hooks`経由で配布し、欠落時はpreflightで拒否する。

- [x] **Step 1: Write the failing test.** 一時HOMEで`setup.sh --codex`を起動し、新CLIとhookがリンク先に存在すること、必要ファイル欠落時はpreflight失敗することを検証する。
- [x] **Step 2: Run RED.** `python3 -m unittest tests.test_setup_cli -v`で新caseの失敗を確認する。
- [x] **Step 3: Implement minimal code.** setup preflightを追加し、routing文書とREADMEへcheckpoint、begin/publish、手動切替、厳密resume/override/cancel、証拠tier、fresh session fallbackを記す。
- [x] **Step 4: Run GREEN.** 変更したtest suiteを成功させ、CLIの手動smokeで`begin → publish → pending拒否 → resume`を一時Git repoに対して確認する。実Codex hook trust状態も観測し、未承認ならguard稼働の証拠にしない。
- [x] **Step 5: Review and commit.** security-reviewerにread-onlyで意味レビューを依頼し、指摘を修正後に`verification-loop`を実行し、Task 3をcommitする。

## Self-review

- specのcheckpoint、状態、handoff、三command、二hook gate、証拠tier、fallback、配布、検証はTask 1〜3に対応する。
- `runtime-config-verified`を生成しないこととhook限界の表示をTask 3で維持する。
- `status`は状態照会のみ、`publish`はPREPARINGのみ、prompt commandはUserPromptSubmitのみを入口にする。
