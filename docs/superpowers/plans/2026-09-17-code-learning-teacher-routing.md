# Code Learning Teacher Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This repository itself must not use a worktree; see `rules/parallel-worktree.md`.

**Goal:** 安価な実装モデルが教材選定・採点・専門的説明を自己完結しないよう、検証可能なhandoffとread-only教師routeを導入する。

**Architecture:** `code-learning` の共有skillはモデル名を持たず、候補packetと権限境界を定義する。Codex固有routeは `codex/MODEL_ROUTING.md` へ置き、既存のADR 0011 handoff validatorをそのまま通す。代表ケースevalでroute品質を確認するまでは、モデル名を能力保証とみなさず、根拠不足なら学習イベントを見送る。

**Tech Stack:** Markdown、Python 3 `unittest`、既存 `bin/validate-codex-handoff.py`、Codex custom agent TOML

**Spec:** `docs/research/2026-09-16-code-learning-mode-design.md` の「モデルルーティングとの統合」、`docs/adr/0010-codex-adaptive-model-routing.md`、`docs/adr/0011-codex-cross-model-handoff.md`、`docs/superpowers/plans/2026-09-17-code-learning-core.md`

## Global Constraints

- 共有rule/skillへLuna/Terra/Solのモデル名を固定しない。Codex固有のモデル指定は `codex/MODEL_ROUTING.md` に置く。
- 実装agentは候補照合、packet収集、検査実行まで。規範的な教材選定、AI製コードの模範認定、理由説明の採点、未検証の性能・安全性・設計一般則は単独で確定しない。
- 教師agentはread-only。productionコードの変更と最終検証は元の実装workflowが所有する。security reviewは別途必須。
- 既存handoff validatorのbranch、HEAD、fingerprint、参照hash、input digest、モデル/effort照合を省略しない。packet不足・検証不能・`NEEDS_CONTEXT` は発火見送りに倒す。
- この計画はcore計画Task 1のADR承認後に実行する。routeの最終閾値は評価結果を見て決め、ユーザーが明示した予算・provider制約を越えない。
- 外部一次資料は導入時点で再確認する。モデルの提供状態とeffortの対応はCLI実測と公式資料で検査する。

## File Map

| ファイル | 責務 |
|---|---|
| `docs/adr/0013-code-learning-teacher-routing.md` / `docs/adr/README.md` | 教育的権限境界と代替案を記録 |
| `codex/MODEL_ROUTING.md` | Codexの教師route選択とfail-closed条件 |
| `skills/code-learning/SKILL.md` | host-neutralな候補packet・返却契約 |
| `tests/test_codex_model_routing.py` / `tests/test_code_learning_contract.py` | モデル名の分離、route表、権限境界の静的契約 |
| `docs/research/code-learning-routing-eval.md` | 匿名化代表ケース、採点rubric、結果、pilot判定 |
| `tests/test_codex_handoff.py` | 既存validatorがlearning packet参照を検証できる回帰ケース |

## Task 1: 教育的権限境界とhandoffを固定する

**Files:** Create `docs/adr/0013-code-learning-teacher-routing.md`; Modify `docs/adr/README.md`, `skills/code-learning/SKILL.md`, `tests/test_code_learning_contract.py`.

**Interfaces:** Consumes core計画のshared skillとADR 0010/0011。Produces教師agentへ渡すpacketと返却契約。

- [ ] **Step 1:** ADR番号0013の空きを確認する。次の区分を `tests/test_code_learning_contract.py` に追加し、まず失敗を確認する。

```python
def test_teacher_feedback_distinguishes_evidence(self):
    text = SKILL.read_text(encoding="utf-8")
    for label in ("verified_fact", "repo_convention", "engineering_judgment", "unverified", "NEEDS_CONTEXT"):
        self.assertIn(label, text)
    self.assertNotIn("gpt-5.6-sol", text)
```

- [ ] **Step 2:** shared skillにpacketの必須情報を明記する: 対象diffと周辺コード、受入条件、実行済み/未実行検査、ユーザーに未開示の答え、候補形式、安全境界、教師への問い、根拠付き返却形式。packetは既存handoffの `requirements_path` または `review_package_path` が指すMarkdown成果物へ置き、重複コピーを作らない。教師が `NEEDS_CONTEXT` / 未検証を返したら、実装agentは採点せず見送る。
- [ ] **Step 3:** ADR 0013へ「全実装をSolへ昇格」「実装モデルが自己採点」「上位モデルを無条件に正解扱い」「軽量handoffでhash省略」を却下案として記録する。README一覧へ加え、ユーザーの承認後に `accepted` へ変える。
- [ ] **Step 4:** `python3 -m unittest discover -s tests -p 'test_code_learning_contract.py' -v` と `rtk git diff --check` を実行し、対象だけコミットする。

```bash
git add docs/adr/0013-code-learning-teacher-routing.md docs/adr/README.md skills/code-learning/SKILL.md tests/test_code_learning_contract.py
git commit -m "docs: コード学習の教師権限境界を確定"
```

## Task 2: Codex routeを既存handoffに接続する

**Files:** Modify `codex/MODEL_ROUTING.md`, `tests/test_codex_model_routing.py`, `tests/test_codex_handoff.py`; Test `bin/validate-codex-handoff.py`.

**Interfaces:** Consumes Task 1 packetとADR 0011。Produces教師のread-only起動規約。固定custom roleは作らず、既存roleのモデル固定値との衝突を避けて明示ペアで起動する。

- [ ] **Step 1:** `tests/test_codex_model_routing.py` に次の静的契約を追加し、失敗を確認する。

```python
def test_code_learning_route_requires_read_only_teacher(self):
    text = (ROOT / "codex/MODEL_ROUTING.md").read_text(encoding="utf-8")
    section = text.split("## コード学習の教師route", 1)[1].split("\n## ", 1)[0]
    for marker in ("read-only", "Terra", "Sol", "NEEDS_CONTEXT", "validate-codex-handoff.py"):
        self.assertIn(marker, section)
```

- [ ] **Step 2:** route節を追加する。候補・検査はLuna medium、局所的な意味・失敗経路はTerra high、依存方向・pattern・複数成立解の評価はSol highをeval前の仮説と書く。一次資料と決定的検査で一意な狭い課題のみLuna high単独を許す。実際の指定値は現行CLIで再実測し、custom roleの固定pairが勝つ場合は固定roleを使わない。`code-architect`の固定Luna highとSol設計routeの不整合を説明し、教師用途では使わない。
- [ ] **Step 3:** `tests/test_codex_handoff.py` にlearning packetを `requirements_path` とSHA-256で参照する正常ケース、packet変更後にvalidatorが拒否するケースを追加する。既存validatorのschemaは変更しない。教師起動前の `state` → packet作成 → `validate` → `read` と、受信側 `INPUT_DIGEST`照合を実測する。
- [ ] **Step 4:** routing/handoffテストを実行する。read-onlyがツール権限として設定できないruntimeでは「read-only教師として起動可能」と主張せず、その環境で教師イベントをOFFにする。

```bash
python3 -m unittest discover -s tests -p 'test_codex_model_routing.py' -v
python3 -m unittest discover -s tests -p 'test_codex_handoff.py' -v
git add codex/MODEL_ROUTING.md tests/test_codex_model_routing.py tests/test_codex_handoff.py
git commit -m "feat(codex): コード学習の教師routeをhandoffへ接続"
```

## Task 3: 代表ケースevalで初期routeを採否判定する

**Files:** Create `docs/research/code-learning-routing-eval.md`; Modify `codex/MODEL_ROUTING.md` only if results require different routes.

**Interfaces:** Consumes Task 2の同一packet。Produces領域別routeの採用・保留・見送り判断。

- [ ] **Step 1:** 実ケースを匿名化し、少なくとも8分類（正しいコードへの誤警告、境界値、架空API、repo慣例、不要pattern、別解、重大リスク、根拠不足）を1件ずつ用意する。各ケースはモデル実行前に入力packet、正解を一つに固定しないrubric、決定的検査、見送り許容条件を記録する。
- [ ] **Step 2:** 同一packetを候補routeに渡し、事実の正誤、誤feedback率、誤警告率、根拠なし一般化率、転移課題の妥当性、token/時間/費用を別欄で記録する。教師自身が自分の採点だけで合格を決めない。設計ケースは人間のサンプル監査を残す。
- [ ] **Step 3:** 重大な誤学習を誘うfeedback、根拠を偽るfeedback、検証不能なのに正解と断定するfeedbackが1件でも出た領域はそのrouteを採用しない。ケース数が少ない間は品質率を母集団推定と呼ばず、pilotの仮説として扱う。予算と品質の両方を満たす領域だけroute節を更新し、満たさない領域は発火見送りにする。
- [ ] **Step 4:** 結果文書に実施日・CLI version・モデルpair・匿名化方法・未実施ケースを明示し、`rtk git diff --check` とrouting/handoff testsを再実行する。データがまだないなら結果を捏造せず、このtaskを未完了のままにする。

```bash
git add docs/research/code-learning-routing-eval.md codex/MODEL_ROUTING.md
git commit -m "test(codex): コード学習教師routeの代表ケース評価を記録"
```

## 実行ゲート

Task 1のADR承認、Task 2の実際のread-only handoff成功、Task 3の代表ケースevalを満たすまで、自動の専門的採点と一般則の指導を有効化しない。teachの直接導入は別の判断であり、この計画はskillをインストールしない。
