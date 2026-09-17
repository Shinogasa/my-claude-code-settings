# Code Learning Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This repository itself must not use a worktree; see `rules/parallel-worktree.md`.

**Goal:** 実務のコード変更から、ユーザーが書く・直す・レビューする能力を検証可能な形で練習できる、両ホスト共通のコード学習モードを導入する。

**Architecture:** 常時読み込む短い `rules/code-learning.md` は候補検出と停止条件だけを扱い、演習の手順は `skills/code-learning/SKILL.md` に置く。既存の設計判断用 `learning-mode.md` からコード参加を移管し、両者の発火回数を一つのタスク予算で管理する。教師モデルへの委譲は別計画 `2026-09-17-code-learning-teacher-routing.md` の責務とし、検証できない専門的採点は行わない。

**Tech Stack:** Markdown/YAML frontmatter、Python 3 `unittest`、Bash `setup.sh`、共有skill manifest

**Spec:** `docs/research/2026-09-16-code-learning-mode-design.md`、`docs/research/2026-09-15-mattpocock-skills-evaluation.md`、`docs/adr/0001-learning-mode-prediction-format.md`、`docs/adr/0007-learning-mode-decision-layer-gate.md`

## Global Constraints

- このリポジトリは公開設定リポジトリ。学習記録に業務コード、内部パス、顧客名、非公開の型名・データ名を保存しない。
- 共有rule/skillにホスト固有のAPI名・パスを単独で書かず、必要なら両ホストの経路を併記する。
- TDD、debugging、security、verificationの順序と責務を変更しない。コード学習はその中の学習方法だけを決める。
- 対話の停止には実際に応答を待つ仕組みを使う。Codexでは環境にその仕組みが無い場合、通常のターン終了で回答を待ち、作業が進んだと偽らない。
- 初期値はコード学習1イベント/タスク、設計学習との合計2イベント/タスク。「全部やって」「任せる」「急ぎ」「学習なし」はそのタスク中OFF。ユーザーの明示的な承認要求は教育イベントと数えない。
- Write → Modify → Review → Explain は、真正で安全な形式のうち成立するものを選ぶ優先順位であり、ユーザーへ無理にコードを書かせない。
- skill作成時に `skill-creator` と `superpowers:writing-skills`、設定変更時に `codex-cli-best-practice` を読み、両ホストの実動作を確認する。
- この計画は実装承認ではない。Task 1のADRをレビュー・承認してからrule/skillの実装へ進む。モデルrouteは別計画の代表ケース評価まで暫定案とする。

## File Map

| ファイル | 責務 |
|---|---|
| `docs/adr/0012-code-learning-mode.md` / `docs/adr/README.md` | C案、旧コード参加の移管、合計予算、却下案と制約を永続記録 |
| `rules/code-learning.md` | 常時有効な候補検出・OFF・安全ゲートだけ |
| `skills/code-learning/SKILL.md` | 1能力の演習、自己説明、検証、feedback、転移、記録の手順 |
| `rules/learning-mode.md` / `CLAUDE.md` | 設計判断モードとの境界、起動時読み込み、共通予算 |
| `manifests/skills.json` / `tests/test_skill_manifest.py` | skillの両ホスト配布分類 |
| `learning/code/README.md` | 証拠だけを書く匿名化されたコード能力記録のschema |
| `tasks/backlog.md` | 旧レビュー訓練案の統合先を明示 |
| `tests/test_code_learning_contract.py` / `tests/test_instruction_graph.py` / `tests/test_learning_mode_contract.py` | 発火・非発火・相互排他・記録契約の回帰検査 |

## Task 1: 設計判断をADRとして確定する

**Files:** Create `docs/adr/0012-code-learning-mode.md`; Modify `docs/adr/README.md`.

**Interfaces:** Consumes research文書、ADR 0001/0007。Produces後続taskが従う決定と却下案。

- [ ] **Step 1:** `docs/adr/README.md` の末尾番号を再確認し、0012が空いていることを確認する。新しいADRには下記の決定表を入れ、statusはレビュー前 `proposed` とする。

```markdown
| 論点 | 初期決定 |
|---|---|
| 構成 | 短い常時rule + 詳細skill（C案） |
| 旧コード参加 | 新skillへ完全移管。設計Predictとの二重出題を禁止 |
| 回数 | code最大1回、設計Predictと合計最大2回/タスク |
| 記録 | pilotでは実証できた場合だけ `learning/code/entries/` に保存 |
| 既習 | 異なる実務文脈で2回成功し、2回目は実質的なヒントなし |
| 出力 | `★ Code Delta`。既存の `★ Delta` と別の能力記録 |
| teach | 自動導入・自動同期しない。反復gapを体系学習候補として提案 |
```

- [ ] **Step 2:** 代替案A「旧ruleへ統合」、B「常時ruleだけ」、旧コード参加の限定併存、別々の回数上限、全件保存をそれぞれ却下理由付きで記録する。`docs/adr/README.md` に0012を追加する。
- [ ] **Step 3:** ユーザーにADR案を提示する。判断が変わればplanも同時修正し、承認されたらstatusを `accepted` にする。承認前にTask 2以降を実行しない。
- [ ] **Step 4:** `rtk git diff --check` を実行し、ADRと一覧だけをコミットする。

```bash
git add docs/adr/0012-code-learning-mode.md docs/adr/README.md
git commit -m "docs: コード学習モードの設計判断を記録"
```

## Task 2: 詳細skillの教育ループを契約テストから作る

**Files:** Create `skills/code-learning/SKILL.md`, `tests/test_code_learning_contract.py`; Modify `manifests/skills.json`, `tests/test_skill_manifest.py`.

**Interfaces:** Consumes Task 1のADR。Produces `code-learning` というshared skill。常時ruleは後続Task 3で作る。

- [ ] **Step 1:** `tests/test_code_learning_contract.py` に最初の失敗テストを追加する。固定文字列だけでなく、重要な順序と除外を検査する。

```python
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/code-learning/SKILL.md"

class CodeLearningContract(unittest.TestCase):
    def test_loop_order_and_single_target(self):
        text = SKILL.read_text(encoding="utf-8")
        markers = ("学習対象を一つ", "Write", "Modify", "Review", "Explain",
                   "理由を自己説明", "事実を検証", "転移", "実証したことだけ記録")
        positions = [text.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("productionコードへ教材用の欠陥を仕込まない", text)
```

- [ ] **Step 2:** `python3 -m unittest discover -s tests -p 'test_code_learning_contract.py' -v` を実行し、skill不在で失敗することを確認する。
- [ ] **Step 3:** `SKILL.md` を作る。frontmatterは `name: code-learning` と、実装・修正・レビュー時に候補化することを明示したdescriptionだけにする。本文は候補条件、Write/Modify/Review/Explain、理由質問、外部検査、`verified_fact`/`repo_convention`/`engineering_judgment`/`unverified` を分けたfeedback、1条件変更の転移、skip/OFF、公開記録の匿名化に分ける。AIが解説しただけの場合は理解済みと判定しない。

```markdown
---
name: code-learning
description: Use during implementation, fixes, refactoring, or code review when a small, verifiable code skill can be practiced safely.
---

# コード学習

1. 品質への影響と転移価値を根拠に、未実証の能力を一つ選ぶ。
2. 真正で安全な最初の形式を Write → Modify → Review → Explain から選ぶ。
3. ユーザーの実装・指摘の直後に理由を一問だけ尋ね、回答を待つ。
4. 実行可能な検査、一次資料、repo契約の順に事実を確かめる。
5. `★ Code Delta` で事実と設計判断を分けて返す。
6. 条件を一つ変えた転移課題を確認し、実証したことだけ記録する。
```
- [ ] **Step 4:** `manifests/skills.json` の `shared` に `code-learning` を辞書順で追加し、`tests/test_skill_manifest.py` のshared件数を19から20へ更新する。`tests/test_code_learning_contract.py` に「frontmatter名」「自動生成物・ボイラープレート・検証不能な主張は除外」「TDD等の優先」を加える。
- [ ] **Step 5:** 対象テストと `rtk git diff --check` を実行し、成功したらコミットする。

```bash
python3 -m unittest discover -s tests -p 'test_code_learning_contract.py' -v
python3 -m unittest discover -s tests -p 'test_skill_manifest.py' -v
git add skills/code-learning/SKILL.md manifests/skills.json tests/test_code_learning_contract.py tests/test_skill_manifest.py
git commit -m "feat: コード学習skillの教育ループを追加"
```

## Task 3: 常時ruleと両ホストの発火経路を接続する

**Files:** Create `rules/code-learning.md`; Modify `CLAUDE.md`, `tests/test_instruction_graph.py`, `tests/test_code_learning_contract.py`; Test `tests/test_setup_cli.py`.

**Interfaces:** Consumes Task 2の `skills/code-learning/SKILL.md`。Produces適格タスクでskill全文を読む入口。

- [ ] **Step 1:** `tests/test_instruction_graph.py` の `SESSION_RULES` に `rules/code-learning.md` を追加し、`tests/test_code_learning_contract.py` に次のテストを追加する。

```python
def test_router_is_small_and_points_to_skill(self):
    rule = (ROOT / "rules/code-learning.md").read_text(encoding="utf-8")
    self.assertIn("skills/code-learning/SKILL.md", rule)
    self.assertIn("学習なし", rule)
    self.assertIn("生成物", rule)
    self.assertLess(len(rule), 3000)
```

- [ ] **Step 2:** `python3 -m unittest discover -s tests -p 'test_instruction_graph.py' -v` とコード学習契約テストを実行し、rule不在で失敗することを確認する。
- [ ] **Step 3:** `rules/code-learning.md` を `paths:` なしのfrontmatterで作る。候補条件6項目はresearch文書の「発火候補の選び方」を参照し、rule本文には1段落へ圧縮する。候補があれば「本質部分確定前にskill全文を読む」、OFF語、除外、1イベント、設計Predictとの二重出題禁止、教師検証不能なら発火見送りを明記する。`CLAUDE.md` の必須読込一覧へruleを追加する。

```markdown
---
alwaysApply: true
---

# コード学習の入口

実装・修正・リファクタリング・レビューで、品質へ実質的な影響があり、転移可能で、
まだ実証していない能力を小さく真正な課題として検証できる場合、
本質部分の確定前に `skills/code-learning/SKILL.md` を全文読む。
生成物、機械的変更、単純設定、検証不能な好みの押し付けでは発火しない。
1タスク最大1イベント。同じ箇所で設計Predictと二重出題しない。
「全部やって」「任せる」「急ぎ」「学習なし」はタスク中OFF。
```
- [ ] **Step 4:** `python3 -m unittest discover -s tests -p 'test_instruction_graph.py' -v`、コード学習契約テスト、`tests/test_setup_cli.py` を実行する。Claude Codeはrule linkが `paths:` なしであることを確認し、Codexは新規セッションの読込指示に現れることを確認する。実セッションでの自動発火はここで推定せず、Task 5のscenario検証に残す。
- [ ] **Step 5:** `rtk git diff --check` 後に対象ファイルだけをコミットする。

```bash
git add rules/code-learning.md CLAUDE.md tests/test_instruction_graph.py tests/test_code_learning_contract.py
git commit -m "feat: コード学習の常時発火入口を接続"
```

## Task 4: 設計Predictとの二重発火を取り除く

**Files:** Modify `rules/learning-mode.md`, `CLAUDE.md`, `tests/test_learning_mode_contract.py`, `tests/test_code_learning_contract.py`, `tasks/backlog.md`.

**Interfaces:** Consumes Task 1の共通予算とTask 3のrouter。Produces設計判断とコード能力で一貫したイベント計数。

- [ ] **Step 1:** `tests/test_learning_mode_contract.py` の `TestCodeParticipationContract` を、旧見出しの不在、新skillへの移管、共通予算のテストへ置換する。例:

```python
def test_code_participation_is_owned_by_new_skill(self):
    self.assertNotIn("## コード参加（Predictの代替イベント）", RULE)
    self.assertIn("skills/code-learning/SKILL.md", RULE)
    self.assertIn("合計で最大2回", RULE)
```

- [ ] **Step 2:** 対象テストを実行し、旧見出しが残っているため失敗することを確認する。
- [ ] **Step 3:** `rules/learning-mode.md` の旧コード参加章と、そこに依存する回数・Deltaの説明を削り、L2優先は設計Predictだけに適用すると明記する。コード技能は新skillが所有し、同じ箇所を両モードで問わない。`CLAUDE.md` の学習モード要約へ共通予算と新ruleを追記する。`tasks/backlog.md` のレビュー訓練案には「code-learningへ統合する」と追記し、古い検討本文は履歴として残す。
- [ ] **Step 4:** `python3 -m unittest discover -s tests -p 'test_learning_mode_contract.py' -v` とコード学習契約テストを実行する。差分を見て旧コード参加の一部が偶然残っていないことを確認する。
- [ ] **Step 5:** `rtk git diff --check` 後に対象ファイルだけをコミットする。

```bash
git add rules/learning-mode.md CLAUDE.md tests/test_learning_mode_contract.py tests/test_code_learning_contract.py tasks/backlog.md
git commit -m "refactor: コード参加を新学習skillへ移管"
```

## Task 5: 記録schemaとpilot検証を追加する

**Files:** Create `learning/code/README.md`; Modify `skills/code-learning/SKILL.md`, `tests/test_code_learning_contract.py`, `README.md`.

**Interfaces:** Consumes Task 2の教育ループ。Produces証拠付き・匿名化された記録と実験可能なscenario集合。

- [ ] **Step 1:** `tests/test_code_learning_contract.py` にschema項目と安全制約の失敗テストを加える。

```python
def test_record_schema_requires_evidence(self):
    schema = (ROOT / "learning/code/README.md").read_text(encoding="utf-8")
    for field in ("能力", "形式", "ユーザーが実証", "検証方法", "転移結果", "未解消のgap"):
        self.assertIn(field, schema)
    self.assertIn("抽象化できない場合は保存しない", schema)
```

- [ ] **Step 2:** 対象テストを実行し、schema不在で失敗することを確認する。
- [ ] **Step 3:** `learning/code/README.md` に1エントリ1ファイルのschema、既習判定（別文脈2回・2回目は実質ヒントなし）、`★ Code Delta` と記録の対応、匿名化できない場合の非保存、teach候補はユーザーの承認なしに同期しないことを書く。skillとtop-level READMEから参照する。実ユーザー回答のない架空の理解済みエントリは作らない。
- [ ] **Step 4:** scenarioを別々に検査する: Write・Modify・Review、生成物の除外、OFF、skip、既習、設計Predictとの同一箇所重複、未検証feedbackの見送り。まずpromptと期待観測を固定し、両ホストの実セッションで応答と停止位置を記録する。simulationだけでは発火保証を主張しない。実セッションがすぐ使えない場合は、その項目を未検証として残す。
- [ ] **Step 5:** `python3 -m unittest discover -s tests -p 'test_*.py'`、`bash -n setup.sh`、`rtk git diff --check` を実行する。両ホスト実測は不可なら「未検証」と記録し、pilot開始を完了扱いしない。対象ファイルだけをコミットする。

```bash
git add learning/code/README.md skills/code-learning/SKILL.md tests/test_code_learning_contract.py README.md
git commit -m "docs: コード学習の証拠記録とpilot契約を追加"
```

## Task 6: 教師route評価後に実務pilotを行う

**Files:** Modify `docs/research/2026-09-16-code-learning-mode-design.md`; Test 実際の適格タスク5〜10件。

**Interfaces:** Consumes教師route計画Task 3のeval結果とTask 5の記録schema。Produces発火頻度と学習効果についての運用判断。

- [ ] **Step 1:** 代表ケースevalで許可された領域だけを対象に、適格タスク5〜10件の学習形式、転移結果、誤feedback、誤警告、中断時間、skipを匿名化して記録する。
- [ ] **Step 2:** 既習判定と合計停止上限が学習効果を妨げたかを確認する。改善するなら新ADRに却下案と測定値を記録してからruleを変更する。teachは反復gapにmission化できる広さがある場合だけユーザーへ提案し、自動導入しない。
- [ ] **Step 3:** 実測がまだ5件に満たない場合はpilotを未完了とし、成功を宣言しない。実測と反証条件を調査文書へ追記し、`rtk git diff --check` 後にその文書だけをコミットする。

```bash
git add docs/research/2026-09-16-code-learning-mode-design.md
git commit -m "docs: コード学習pilotの実測と改善判断を記録"
```

## 実行ゲート

Task 1のADR承認が最初のゲート。Task 2〜5のrule/skillは教育的採点を自動で許可しない。安価な実装モデルに指導を委ねる運用は、別計画の教師routeと代表ケース評価を満たしてから開始する。モデルrouteが使えない場合は、決定的検査と一次資料で閉じる単純課題に限定するか、イベントを見送る。
