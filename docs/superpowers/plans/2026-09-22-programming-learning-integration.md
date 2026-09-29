# Programming Learning Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. この設定リポジトリ自身は worktree を使わない（`rules/parallel-worktree.md`）。

**Goal:** 実務で本人が調査・変更・検証する担当範囲を広げ、その観測証拠を両ホスト共通の専用学習repoへ安全に保存する。

**Architecture:** 発火・回数・開示順の正本は `rules/learning-mode.md` に置き、コード技能の入口と演習を既存の `rules/code-learning.md` と `skills/code-learning/SKILL.md` に分ける。`bin/learning-store.py` は教育判断をせず、binding、記録の構造・版グラフ、排他的な保存、旧記録の照合だけを担う。記録のGit commit、remote反映、実対話とpilotは別ゲートとする。

**Tech Stack:** Python 3.9以上の標準ライブラリ、Git、Bash `setup.sh`、Markdown、`unittest`。

**実機検証後の改訂:** Task 1–4の初期例にあるmarker version 1とGit metadata内lockは、
Codex sandboxと排他競合の実測を受けて[ADR 0020](../../adr/0020-learning-store-directory-lock.md)で
marker version 2とstore directory lockへ置き換えた。binding・record・manifestのschema version 1は維持する。

**Spec:** `docs/superpowers/specs/2026-09-21-programming-learning-integration-design.md`（2026-09-22 accepted）。継続レビューは `docs/research/2026-09-22-code-learning-design-review.md`。決定記録は作成済みの `docs/adr/0017-programming-learning-integration.md` を前提とし、この計画から重複作成しない。

## Global Constraints

- 製品実装は計画の提示・確認後に開始する。今回の担当成果は計画文書だけであり、製品コード変更、新しい学習repoの作成、旧記録移管、製品実装のcommit、pushは行わない。親工程による本計画とADRのcommitはこの制約の対象外。
- Python標準ライブラリと既存Gitだけを使う。新規hook、常駐サービス、DB、意味検索、教員route、モデルrouting変更、teach導入をしない。
- 公開記録には業務コード・顧客名・非公開URL・内部パスを含めない。本文、能力ID、ファイル名、operation、import manifestを保存前に確認し、抽象化で証拠が失われる場合は保存しない。
- 共有rule/skillはホスト依存の単独経路を書かない。CLI入口は Claude Code `~/.claude/bin/learning-store.py`、Codex `~/.codex/bin/learning-store.py`。
- pilot中の上限は設計Predictとコード学習の合計2イベント、コード学習は最大1イベント、下限なし。OFF・skip・本人の引取り希望を尊重し、通常作業を完了する。
- 本人の担当範囲は固定の再試行回数や時間でAIへ取り上げない。必要時は前提を補足するか範囲を調整し、同じevent_idで継続する。
- 初版と訂正版を混ぜて独立成功を水増ししない。支援・開始契機・課題条件を本文に残し、過去のhitや模擬回答を成長証拠へ変換しない。
- TDD、原因調査、security、verificationの順序を維持する。CLIのsecurity boundaryは Terra / high の読み取り専用レビュー、最終統合は Sol / high のレビューを通す。

## Review Focus

次の5条件を、それぞれ所有するTaskの失敗テストへ入れる。

1. bindingが未設定・別store・移設済み: `status/list/record`が0件や成功を返さず、`bind --replace-binding`だけで明示再接続できる（Task 1）。
2. recordの親参照が欠落・循環・別eventを指す: listもrecordも読取失敗とし、成功扱いの末尾を選ばない（Task 2）。
3. 2台の訂正がGit統合後に分岐: 通常訂正を拒否し、全末尾を明示した競合解消だけが1有効版に戻す（Task 3）。
4. importが途中停止、同名異内容、旧記録0件: 原文とhashを照合して再開し、不一致はactiveへ切り替えず、0件は空manifestで確定する（Task 4）。
5. AIのtool出力や完成テストが対象箇所・検証を先渡し: 独立発見・本人設計の証拠に数えない（Task 5・7）。

## File Map と固定インターフェース

| ファイル | 責務 |
|---|---|
| `bin/learning-store.py` | `argparse`のCLI入口、JSON出力、終了コード。Git push/commitや採点はしない |
| `bin/learning_store/store.py` | bindingとmarker、Git root、安全なディレクトリ、排他・原子的保存、import。Python 3.9互換 |
| `bin/learning_store/schema.py` | 固定キーJSON入力、限定frontmatter、operation schema、UUID・日時・参照の検査 |
| `bin/learning_store/__init__.py` | packageとしての空の入口。CLIから同階層をimportする |
| `tests/test_learning_store.py` | temp HOME・Git repo・subprocess CLIで保存と失敗時の副作用を検証 |
| `tests/test_setup_cli.py` | 既存 `copy_repository` / `run_setup` fixtureで両ホストのbin linkと暗黙init無しを検証 |
| `rules/learning-mode.md` | 共通ON/OFF、候補担当、上限、先渡しと保存状態の正本。設計Predictと3軸は同ファイルで維持 |
| `rules/code-learning.md` / `skills/code-learning/SKILL.md` | 前者は短い入口、後者はInvestigate等の実課題、再修正、転移・保持確認 |
| `output-styles/review-and-design.md` | Predictと全能動形式で対象解説を理由回答まで保留 |
| `learning/README.md` / `learning/code/README.md` | 外部store schemaと証拠の解釈、legacyの読取専用履歴 |
| `CLAUDE.md` / `rules/task-management.md` / `README.md` | 現行のrepo内保存先、発火条件、回数の古い説明を更新 |
| `tests/test_code_learning_contract.py` / `tests/test_learning_mode_contract.py` / `tests/test_instruction_graph.py` | 静的契約と参照経路。教育効果の証明には使わない |

CLIの成功は標準出力に1個のJSON objectと終了0、失敗は標準エラーに、例えば未設定なら `{"ok":false,"error":{"code":"NOT_CONFIGURED","message":"bindingが設定されていません"}}` と終了2を返す。無引数`list`の正常な0件は `{"ok":true,"capabilities":[],"count":0}`、`list --capability <id>`の正常な0件は `{"ok":true,"records":[],"count":0}`、どちらも読取失敗は終了2とする。`status`はroot、store_id、state、`writable`を返し、保存不能理由は失敗側で返す。`record`成功は `id`、`event_id`、`path`、`created`を返し、同一入力の再実行は `created:false`。pathはrootからの相対path。これらの出力契約を全テスト・文書で揃える。

`record --input`の能力記録JSONは `schema_version:1`, UUIDの`id`/`event_id`, UTC ISO 8601の`observed_at`, `kind`=`decision|code`, `mode`=`predict|investigate|review|modify|write`, 公開可能な`capability_id`と短い`scope`, `initial_result`=`pass|partial|fail|unverified`, `retry_result`/`transfer_result`=`pass|partial|fail|unverified|not_attempted`, UUID配列の`supersedes`, 非空の`body`を固定キーとする。本文には担当範囲・外部完了条件・開始契機・提示済み情報・ヒントとAI修正・本人が選んだ次の行動・行動と理由・検証と残る不確実性・関連IDを見出しで記す。CLIは本文の教育的真偽を判定しない。`kind=operation`は別固定schemaとして `schema_version,id,event_id,observed_at,kind,capability_id`（未特定ならnull）, `end_reason,wait_count`のみを受け、`operations/YYYY/YYYY-MM-DD-UUID.json`に保存する。operationは習得証拠にしない。

能力記録はCLI生成の `---` と `key: JSON値` の限定frontmatter、空行、本文で構成する。配列は`supersedes`だけ。未知のキー・schema version・重複キー・非JSON値・範囲外enumを拒否する。`records/<kind>/YYYY/YYYY-MM-DD-UUID.md`へ保存し、ユーザー入力をpath要素に使わない。`list`は引数なしなら能力IDとscope・有効件数、`--capability ID`ならその能力の有効な新形式記録を返す。対象範囲の同一性は人間が本文まで照合し、CLIは意味検索をしない。

実装内の型は次で固定する。`History`は構造が正しいグラフを表し、複数末尾を正常に保持する。分岐は構造破損ではないため、`analyze_history(records: Tuple[Record, ...]) -> History`では例外にしない。`list`は`conflicting_events`が空でなければ`EVENT_CONFLICT`を返す一方、Task 3の競合解消は同じ`History`から全末尾を取得できる。

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Tuple

Record = Dict[str, object]

@dataclass(frozen=True)
class Store:
    root: Path
    binding: Path
    store_id: str
    state: str

@dataclass(frozen=True)
class History:
    records: Tuple[Record, ...]
    by_id: Mapping[str, Record]
    heads_by_event: Mapping[str, Tuple[Record, ...]]

def conflicting_events(history: History) -> Dict[str, Tuple[str, ...]]:
    return {
        event_id: tuple(str(record["id"]) for record in heads)
        for event_id, heads in history.heads_by_event.items()
        if len(heads) > 1
    }
```

`tests/test_learning_store.py`は以下のfixtureを最初に置き、後続の例はこの署名だけを使う。fixtureが直接作るrecordも製品の限定frontmatterと同じ固定順・JSON表現にする。`branch_fixture`はA/B/Cをすべてrecord dictで返し、IDが必要な箇所は明示的に`record["id"]`を使う。

```python
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "learning-store.py"
FRONTMATTER_KEYS = (
    "schema_version", "id", "event_id", "observed_at", "kind", "mode",
    "capability_id", "scope", "initial_result", "retry_result",
    "transfer_result", "supersedes",
)

class LearningStoreCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.home = self.base / "home"
        self.home.mkdir()
        self.env = os.environ.copy()
        self.env.update(HOME=str(self.home), XDG_CONFIG_HOME=str(self.base / "xdg"))
        self.event_id = str(uuid.uuid4())

    def tearDown(self):
        self.temporary.cleanup()

    def cli(self, *arguments):
        return subprocess.run(
            [sys.executable, str(CLI), *arguments], text=True,
            capture_output=True, env=self.env, check=False,
        )

    def cli_with_json(self, value, *record_arguments):
        input_path = self.base / f"input-{uuid.uuid4()}.json"
        input_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return self.cli("record", *record_arguments, "--input", str(input_path))

    def make_prepared_store(self):
        self.store = self.base / "store"
        self.store.mkdir()
        result = self.cli("init", "--repo", str(self.store))
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.store

    def marker(self):
        return json.loads((self.store / ".learning-store.json").read_text(encoding="utf-8"))

    def make_active_store(self):
        self.make_prepared_store()
        marker = self.marker()
        marker["state"] = "active"
        (self.store / ".learning-store.json").write_text(
            json.dumps(marker, sort_keys=True) + "\n", encoding="utf-8"
        )
        return self.store

    def record_payload(self, *, record_id=None, event_id=None, supersedes=(), body="## 担当範囲\n仮説を区別する"):
        return {
            "schema_version": 1,
            "id": record_id or str(uuid.uuid4()),
            "event_id": event_id or self.event_id,
            "observed_at": "2026-09-23T00:00:00+00:00",
            "kind": "code", "mode": "investigate",
            "capability_id": "diagnosis.distinguish-competing-hypotheses",
            "scope": "競合する仮説を観測で区別する",
            "initial_result": "unverified", "retry_result": "not_attempted",
            "transfer_result": "not_attempted", "supersedes": list(supersedes),
            "body": body,
        }

    def write_record_fixture(self, value):
        target = self.store / "records" / value["kind"] / "2026" / f"2026-09-23-{value['id']}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = ["---"]
        lines.extend(f"{key}: {json.dumps(value[key], ensure_ascii=False)}" for key in FRONTMATTER_KEYS)
        lines.extend(["---", "", value["body"], ""])
        target.write_text("\n".join(lines), encoding="utf-8")
        return target

    def branch_fixture(self):
        self.make_active_store()
        first = self.record_payload()
        left = self.record_payload(event_id=first["event_id"], supersedes=[first["id"]])
        right = self.record_payload(event_id=first["event_id"], supersedes=[first["id"]])
        for value in (first, left, right):
            self.write_record_fixture(value)
        return first, left, right

    def list_event(self, event_id):
        result = self.cli("list", "--capability", "diagnosis.distinguish-competing-hypotheses")
        self.assertEqual(result.returncode, 0, result.stderr)
        return [item for item in json.loads(result.stdout)["records"] if item["event_id"] == event_id]
```

## Task 1: storeの識別・init・bind・statusを決定的にする

**Files:** Create `bin/learning-store.py`, `bin/learning_store/__init__.py`, `bin/learning_store/store.py`, `tests/test_learning_store.py`。

**Interfaces:** Produces `StoreError(code: str, message: str)`, `binding_path(env: Mapping[str,str]) -> Path`, `load_store(env) -> Store`, `init_store(repo: Path, env) -> dict`, `bind_store(repo: Path, replace: bool, env) -> dict`, `status(env) -> dict`。後続Taskはこの関数を使う。CLI subcommandは `init --repo`, `bind --repo [--replace-binding]`, `status`。

- [ ] **Step 1:** `tests/test_learning_store.py` に一時HOME・実GitでCLIを呼ぶfixtureと失敗テストを作る。`--repo`は正規化された絶対pathのみ、initは実在する空ディレクトリだけ、bindingが別storeなら上書きしない。`XDG_CONFIG_HOME`指定時はそこを使い、未指定なら `~/.config/agent-learning/config.json`。markerは `.learning-store.json` の `schema_version:1`, `store_id` UUID, `state:prepared|active`。通常initは`learning-records`ブランチにGit repoを作る。

```python
def test_init_bind_and_wrong_store(self):
    repo = self.base / "store"
    repo.mkdir()
    created = self.cli("init", "--repo", str(repo))
    self.assertEqual(created.returncode, 0, created.stderr)
    self.assertEqual(json.loads((repo / ".learning-store.json").read_text())["state"], "prepared")
    self.assertEqual(subprocess.check_output(["git", "-C", str(repo), "branch", "--show-current"], text=True).strip(), "learning-records")
    other = self.base / "other"
    other.mkdir()
    self.assertEqual(self.cli("init", "--repo", str(other)).returncode, 2)
    self.assertEqual(self.cli("bind", "--repo", str(other)).returncode, 2)
```

- [ ] **Step 2:** `python3 -m unittest tests.test_learning_store -v`を実行し、CLI不在で失敗することを確認する。
- [ ] **Step 3:** 実装する。shellを使わず、下記`assert_git_root`の引数配列で`git -C <root> rev-parse --show-toplevel`を実行し、Git rootの実体とmarkerの親の実体を照合する。bindingは `os.replace` する前に同ディレクトリへ一時ファイルを書きfsyncする。既存bindingのstore_idが違う場合は `--replace-binding`が無ければ拒否し、同じ場合は冪等に返す。init失敗でprepared repoが残った場合はbindで回復し、隠れて再初期化しない。`status`のread失敗を0件に変換しない。

```python
def binding_path(env):
    base = Path(env["XDG_CONFIG_HOME"]) if env.get("XDG_CONFIG_HOME") else Path(env["HOME"]) / ".config"
    return base / "agent-learning" / "config.json"

def assert_git_root(root):
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                            check=True, text=True, capture_output=True)
    if Path(result.stdout.strip()).resolve() != root.resolve():
        raise StoreError("GIT_ROOT_MISMATCH", "markerとGit rootの実体が一致しません")
```

- [ ] **Step 4:** 未設定、marker不一致、Git内の子ディレクトリ、移設後の旧binding、symlinkのrepo指定、読み取り不能な設定JSON、`--replace-binding`を個別に検査し、失敗前後の既存ファイルhash一致を確認する。`python3 -m unittest tests.test_learning_store -v`が成功する。
- [ ] **Step 5:** `git add bin/learning-store.py bin/learning_store tests/test_learning_store.py`、`git diff --cached --check`後、`feat: 学習storeの識別とbindingを追加`でこのTaskだけをcommitする。

## Task 2: 限定schema・能力検索・訂正版グラフを読む

**Files:** Create `bin/learning_store/schema.py`; Modify `bin/learning_store/store.py`, `bin/learning-store.py`, `tests/test_learning_store.py`。

**Interfaces:** Consumes Task 1の`Store`。Produces `parse_record(raw: bytes) -> Record`, `validate_input(value: dict) -> Record`, `scan_records(store: Store) -> Tuple[Record, ...]`, `analyze_history(records: Tuple[Record, ...]) -> History`, `conflicting_events(history: History) -> Dict[str, Tuple[str, ...]]`。構造検査は欠落参照・別event参照・循環を`INVALID_HISTORY`として拒否するが、複数末尾を保持した`History`は返せる。CLI `list [--capability ID]`だけが分岐を`EVENT_CONFLICT`として終了2にし、event_idと全末尾IDを返す。分岐が無ければ有効末尾だけを返す。初版はsupersedes空配列で1件だけ。

- [ ] **Step 1:** fixtureに有効なMarkdown recordを置き、0件、単純訂正A→B、分岐A→B/C、参照欠落、循環、別event、破損frontmatter、未知schemaをテストする。`list --capability`はAを返さずBだけ、引数なしはscopeを返す。分岐は成功0件でなく終了2。

```python
def test_missing_parent_is_read_error(self):
    self.make_active_store()
    self.write_record_fixture(event_id=self.event_id, supersedes=[str(uuid.uuid4())])
    result = self.cli("list", "--capability", "diagnosis.distinguish-competing-hypotheses")
    self.assertEqual(result.returncode, 2)
    self.assertEqual(json.loads(result.stderr)["error"]["code"], "INVALID_HISTORY")
```

- [ ] **Step 2:** 対象unittestが `list`未実装で失敗することを確認する。
- [ ] **Step 3:** frontmatterは各行を最初の`": "`で分割し、キー集合を厳密比較して`json.loads`で値を読む。`yaml`は使わない。`datetime.fromisoformat`でtimezone必須・UTCへ正規化、UUIDは`uuid.UUID`で検査する。`list`はmarkerと全対象recordを読めた後だけ成功を返す。scopeが複数ある同一capability IDはその差をそのまま出し、同一能力と自動判定しない。

```python
def analyze_history(records):
    by_id = {str(item["id"]): item for item in records}
    if len(by_id) != len(records):
        raise StoreError("INVALID_HISTORY", "record IDが重複しています")
    parents = {}
    replaced = set()
    for record_id, item in by_id.items():
        parent_ids = tuple(str(parent) for parent in item["supersedes"])
        for parent_id in parent_ids:
            parent = by_id.get(parent_id)
            if parent is None or parent["event_id"] != item["event_id"]:
                raise StoreError("INVALID_HISTORY", "訂正元が同じeventに存在しません")
            replaced.add(parent_id)
        parents[record_id] = parent_ids

    visiting, visited = set(), set()
    def visit(record_id):
        if record_id in visiting:
            raise StoreError("INVALID_HISTORY", "訂正履歴が循環しています")
        if record_id in visited:
            return
        visiting.add(record_id)
        for parent_id in parents[record_id]:
            visit(parent_id)
        visiting.remove(record_id)
        visited.add(record_id)
    for record_id in by_id:
        visit(record_id)

    grouped = {}
    for record_id, item in by_id.items():
        if record_id not in replaced:
            grouped.setdefault(str(item["event_id"]), []).append(item)
    heads = {event_id: tuple(items) for event_id, items in grouped.items()}
    return History(tuple(records), by_id, heads)
```

- [ ] **Step 4:** 上記に加えてDFSで循環、異なるidの同名path、symlinkを含む`records/`配下、壊れたoperation JSONも読取失敗にする。`python3 -m unittest tests.test_learning_store -v`成功を確認する。
- [ ] **Step 5:** このTaskの4ファイルだけstageし`git diff --cached --check`後、`feat: 学習記録のschemaと有効版検索を追加`でcommitする。

## Task 3: recordの排他・冪等保存と明示的な分岐解消

**Files:** Modify `bin/learning_store/store.py`, `bin/learning_store/schema.py`, `bin/learning-store.py`, `tests/test_learning_store.py`。

**Interfaces:** Consumes `validate_input`, `scan_records`, `analyze_history`, `conflicting_events`。Produces `save_record(store: Store, value: Record, resolve_conflict: bool=False) -> dict`。CLIは `record --input <json-file>` と `record --resolve-conflict --input <json-file>`。record前にactive、binding/marker、全履歴の構造を再検査する。分岐を含む`History`から競合解消対象の全末尾を取得する。operationは同じbindingと排他を使うが能力グラフへ入れない。

- [ ] **Step 1:** 同一ID・同一byteの再実行は`created:false`、同一ID・異内容は`RECORD_ID_CONFLICT`、2プロセス同時作成は1件、active前は拒否、同一eventの新規初版重複は拒否するテストを書く。A→Bの保存後にAを同一内容で再送しても、Aが現末尾でないことを理由に拒否せず`created:false`になることも固定する。A→B/Cの分岐fixtureを作り、Bだけ指定・古い末尾集合・別eventのID指定を拒否し、B/Cを両方指定したDで1件へ戻るテストを書く。operationは同じevent_idに紐づくが`list`の習得件数へ入らない。

```python
def test_branch_requires_all_heads(self):
    a, b, c = self.branch_fixture()
    incomplete = self.record_payload(
        event_id=a["event_id"], supersedes=[b["id"]], body="## 統合理由\n証拠不足"
    )
    self.assertEqual(self.cli_with_json(incomplete, "--resolve-conflict").returncode, 2)
    complete = self.record_payload(
        event_id=a["event_id"], supersedes=[b["id"], c["id"]],
        body="## 統合理由\n両枝の証拠を照合し未確定はunverified",
    )
    result = self.cli_with_json(complete, "--resolve-conflict")
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(len(self.list_event(a["event_id"])), 1)
```

- [ ] **Step 2:** 対象unittestがrecord未実装で失敗することを確認する。
- [ ] **Step 3:** Git metadata内の固定名lockを`fcntl.flock(LOCK_EX)`で保持し、その間に全履歴と現在末尾集合を再読する。処理順序は (a) 入力schema・active binding・marker・全履歴の構造を検査、(b) 指定IDの既存fileがあれば生成予定bytesと比較し、同一なら後続訂正でそのIDが末尾でなくても直ちに`created:false`、異なれば`RECORD_ID_CONFLICT`、(c) 新規IDだけについてeventの現在末尾とsupersedesを照合する。通常訂正は唯一の末尾を1件だけ指定、分岐解消は2件以上の全末尾と本文の統合理由を要求する。書込先pathはidと日時から生成し、親ディレクトリのsymlinkを拒否する。同じディレクトリの一時ファイルをflush/fsync後、`os.link(temp, final)`で原子的かつ上書き不能に公開し、一時ファイルを消す。ディレクトリをfsyncできる環境では行い、失敗なら保存成功と報告しない。

```python
def publish_exclusive(parent, name, payload):
    fd, temporary = tempfile.mkstemp(prefix=".learning-", dir=parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, parent / name)
        directory_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        os.unlink(temporary)
```

- [ ] **Step 4:** `--input`は通常ファイルだけを読み、公開用に抽象化したJSON以外の一時生データをhelperが作らない。入力path symlink、root内symlink、権限不足、破損既存ファイル、同時process、Git統合での分岐を検査する。ファイル保存成功とcommit失敗をCLIが混同しないことも確認する。`python3 -m unittest tests.test_learning_store -v`成功。
- [ ] **Step 5:** 対象4ファイルだけstageし`git diff --cached --check`後、`feat: 学習記録を排他的に保存し訂正分岐を解消`でcommitする。

## Task 4: 旧記録を照合しpreparedからactiveへ切り替える

**Files:** Modify `bin/learning_store/store.py`, `bin/learning-store.py`, `tests/test_learning_store.py`。

**Interfaces:** Produces `import_legacy(store: Store, source: Path) -> dict`、CLI `import --source <settings-root>`。旧対象は`learning/entries/*.md`と`learning/code/entries/*.md`の直下だけ。相対path・source commit・各fileのSHA-256と件数を`imports/<UUID>.json`へ固定キーで記録し、原文を`legacy/decision|code/<旧ファイル名>.md`へbyte不変でcopyする。旧schemaの採点へ変換しない。

- [ ] **Step 1:** 小さい実Git fixtureに旧記録2種を作る。source commitとsha256・byte一致、途中で一件copyされた状態からの再実行、同名異内容、source symlink、既存legacy破損、0件の空manifest、manifest作成前の中断ではpreparedのまま、全件照合後だけactiveをテストする。

```python
def test_partial_import_conflict_never_activates_and_can_resume(self):
    self.make_prepared_store()
    source = self.base / "settings"
    decision = source / "learning" / "entries" / "decision.md"
    code = source / "learning" / "code" / "entries" / "code.md"
    decision.parent.mkdir(parents=True)
    code.parent.mkdir(parents=True)
    decision.write_bytes(b"decision original\n")
    code.write_bytes(b"code original\n")
    empty_hooks = self.base / "empty-hooks"
    empty_hooks.mkdir()
    subprocess.run(["git", "init", str(source)], check=True, capture_output=True, env=self.env)
    subprocess.run(["git", "-C", str(source), "config", "user.name", "Fixture"], check=True, env=self.env)
    subprocess.run(["git", "-C", str(source), "config", "user.email", "fixture@example.invalid"], check=True, env=self.env)
    subprocess.run(["git", "-C", str(source), "add", "learning"], check=True, env=self.env)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={empty_hooks}",
         "-C", str(source), "commit", "-m", "fixture"],
        check=True, capture_output=True, env=self.env,
    )

    legacy_decision = self.store / "legacy" / "decision" / decision.name
    legacy_code = self.store / "legacy" / "code" / code.name
    legacy_decision.parent.mkdir(parents=True)
    legacy_code.parent.mkdir(parents=True)
    legacy_decision.write_bytes(decision.read_bytes())  # 中断前に完了していた1件
    legacy_code.write_bytes(b"conflicting existing bytes\n")

    failed = self.cli("import", "--source", str(source))
    self.assertEqual(failed.returncode, 2)
    self.assertEqual(self.marker()["state"], "prepared")
    self.assertEqual(legacy_decision.read_bytes(), decision.read_bytes())
    legacy_code.write_bytes(code.read_bytes())  # 管理者が既知の原本から復元

    resumed = self.cli("import", "--source", str(source))
    self.assertEqual(resumed.returncode, 0, resumed.stderr)
    self.assertEqual(self.marker()["state"], "active")
    self.assertEqual(legacy_code.read_bytes(), code.read_bytes())
```

- [ ] **Step 2:** 対象unittestがimport未実装で失敗することを確認する。
- [ ] **Step 3:** sourceのGit rootを確認し、対象ファイルがsource commitの追跡内容と一致することを検査する。作業時点の対象件数・hashを集め、source相対pathだけをmanifestに入れる。公開前の人間による本文・名前の監査を運用手順に置き、CLIが機密の意味判定をしたと主張しない。準備中の同名同hash fileは再利用、異hashは停止。全byte照合後にmanifestを原子的に作り、最後にmarkerをactiveへ原子的に更新する。active後の同一source再実行はmanifest照合だけで冪等成功、変更・追加のある再importは拒否する。
- [ ] **Step 4:** `python3 -m unittest tests.test_learning_store -v`を通し、`git diff --check`で実装差分を確認する。実際の99件を固定母数として使わない。
- [ ] **Step 5:** 対象3ファイルだけstageし`git diff --cached --check`後、`feat: 旧学習記録を照合して専用storeを有効化`でcommitする。

## Task 5: 共通発火・本人の完遂・成長判定を規約へ反映

**Files:** Modify `rules/learning-mode.md`, `rules/code-learning.md`, `skills/code-learning/SKILL.md`, `output-styles/review-and-design.md`, `tests/test_learning_mode_contract.py`, `tests/test_code_learning_contract.py`。

**Interfaces:** Consumes Task 1–4のCLI出力契約。Produces全ホスト共通の教育手順。`learning-mode`共通節がON/OFF、候補担当、イベント数、開示順、保存失敗の扱いを所有し、コードruleとskillは参照するだけ。設計Predict固有の3条件・L2ゲート・3軸、コード技能固有のInvestigate/Review/Modify/Write/Explainを分離する。

- [ ] **Step 1:** 既存26件の静的契約を壊す箇所は古いassertionを新版の事実へ置換し、新たに「複数案だけでは強制発火しない」「同じ能力・解法の二重出題無し」「理由前の★ Review/定石/WHY保留」「Investigateで対象箇所を先渡ししない」「2回以上の再試行・中断再開で同じevent」「tool出力とAIテストを本人の能力と混同しない」「7日後は関連実作業がある場合だけ候補」を検査する。文言の存在だけでなく、節の正本と参照先、矛盾する旧指示の不在を検査する。

```python
def test_single_owner_and_no_fixed_retry_limit(self):
    common = (ROOT / "rules/learning-mode.md").read_text(encoding="utf-8")
    skill = (ROOT / "skills/code-learning/SKILL.md").read_text(encoding="utf-8")
    self.assertIn("同じ能力・同じ解法", common)
    self.assertIn("固定の再試行回数", skill)
    self.assertNotIn("真正かつ安全に成立する最初の形式", skill)
    self.assertIn("Investigate", skill)
```

- [ ] **Step 2:** `python3 -W error::ResourceWarning -m unittest tests.test_code_learning_contract tests.test_learning_mode_contract -v`が旧規約との違いを示して失敗することを確認する。
- [ ] **Step 3:** 共通節へ候補選定の優先順位、保存候補の前の`status`、保存不能を一度知らせてsession内演習は継続、書込時の再検査を記す。設計Predictは結論と理由を順に取得し3軸で評価するが、結論一致・hit率を習得証拠にしない。コードskillは能力と支援量で形式を選ぶ。課題開始時は目的・担当範囲・外部完了条件・資料/操作環境を提示し、対象範囲の完了まで本人が次の調査・変更・検証を選ぶ。停滞時は反例を一つずつ示し、前提補足・範囲調整をする。完成解は本人の引取りまで保留し、通常の進捗と生の観測は隠さない。skip・安全介入は自力成功に数えない。

- [ ] **Step 4:** 能力IDと本文scopeの照合、別文脈2回・2回目ヒントなし、コードでは検証可能な転移、7日以降の関連実作業での保持候補を記す。開始契機と課題の既知条件を比べ、比較不能なら成長判断を保留する。`output-styles/review-and-design.md`はPredictとWrite/Modify/Review/Investigateの理由回答まで答えとなる解説を保留する。`python3 -W error::ResourceWarning -m unittest tests.test_code_learning_contract tests.test_learning_mode_contract tests.test_instruction_graph -v`成功を確認する。
- [ ] **Step 5:** 6ファイルだけstageし`git diff --cached --check`後、`feat: 学習の共通発火と完遂手順を統合`でcommitする。

## Task 6: 記録契約・両ホスト配布・古い保存先説明を更新

**Files:** Modify `learning/README.md`, `learning/code/README.md`, `CLAUDE.md`, `rules/task-management.md`, `README.md`, `tests/test_instruction_graph.py`, `tests/test_setup_cli.py`, `tests/test_code_learning_contract.py`。必要な修正が確認された場合だけ`setup.sh`。

**Interfaces:** Consumes CLI `status/list/record/import`と共通規約。Produces両ホストから同じbindingを使う運用手順。`setup.sh`の現行配布はClaude側`bin`、Codex側`bin`のdirectory linkで成立しているため、暗黙の学習repo初期化を追加しない。

- [ ] **Step 1:** setup fixtureの両ホストbin link先に`learning-store.py`が存在し同じsourceへ解決すること、`bash setup.sh --all`後も学習bindingと`.learning-store.json`が作られないことを失敗テストにする。READMEと規約の古い`learning/entries/`新規保存先、`learning/code/entries/`新規保存先、hit率断定、Write固定優先を探す静的テストを追加する。

```python
def test_learning_store_is_distributed_without_initializing(self):
    # SetupCliTests.setUpでself.homeを作成済み。ホストdirだけを用意する。
    (self.home / ".claude").mkdir(exist_ok=True)
    (self.home / ".codex").mkdir(exist_ok=True)
    result = run_setup(self.repository, self.home, "--all")
    self.assertEqual(result.returncode, 0, result.stderr)
    source = (self.repository / "bin" / "learning-store.py").resolve()
    self.assertEqual((self.home / ".claude/bin/learning-store.py").resolve(), source)
    self.assertEqual((self.home / ".codex/bin/learning-store.py").resolve(), source)
    self.assertFalse((self.home / ".config/agent-learning/config.json").exists())
```

- [ ] **Step 2:** 対象unittestで旧READMEや既存fixtureとの差分による失敗を確認する。
- [ ] **Step 3:** `learning/README.md`に専用storeを新規正本、repo内旧記録を読み取り専用履歴と記し、旧ADRリンクを保持する。`learning/code/README.md`に能力の範囲、初回・再試行・転移の結果と支援、開始契機、完了/中断、operation非証拠、後日保持の条件を記す。`CLAUDE.md`/`rules/task-management.md`/`README.md`の新規記録先を外部storeに更新する。両ホストのCLI path、`init`/`bind`/`status`/`list`/`record`/`import`の呼び方と、保存成功・commit・remote反映が別状態であることを示す。別マシンはcloneしてbindし同じstore_idを確認する。Git commitは新規対象ファイルだけをstageし、無関係なdirty差分を含めない。
- [ ] **Step 4:** setup testと静的契約、`bash -n setup.sh`を通す。既存linkで足りない具体的失敗があればsetupだけを最小修正し、両ホスト fixtureで再検証する。
- [ ] **Step 5:** 対象8ファイル（setup修正時はそれも）だけstageし`git diff --cached --check`後、`docs: 学習storeの両ホスト運用と旧記録境界を更新`でcommitする。

## Task 7: 統合検査、security review、実ホストでの対話検証

**Files:** Modify `tests/test_learning_store.py`, `tests/test_code_learning_contract.py`; Create `tests/fixtures/code-learning-host-probe/worker.py`, `tests/fixtures/code-learning-host-probe/test_worker.py`, `docs/research/2026-09-23-programming-learning-host-probe.md`。

**Interfaces:** Consumes Task 1–6。Produces (A) subprocess fixtureによる決定的CLI検査、(B) インストール済み両ホストpathから同一storeへ保存する導線、(C) Claude Code/Codexの新規sessionにおける複数ターンの学習行動、(D) Terra / highのsecurity所見とSol / highの統合所見。Aはmock/fixture、Bは保存導線、Cはhosted modelの指示実行、Task 8は実ユーザーの成長観測として証拠を混ぜない。

- [ ] **Step 1:** unittestでは未設定、未clone、marker不一致、権限不足、破損record、symlink/path入力、同時書込、冪等再実行、A→B/C→D、0件とread failure、import中断・再実行を一時HOMEと実Git fixtureで個別に検査する。通常の別作業repoからの実保存導線は、設定repoで`bash setup.sh --all`を実施済みであることを確認してから、一時rootへ空のsource Git repoとstoreを作り、同じ`XDG_CONFIG_HOME`で次を順に実行する。

```bash
python3 ~/.claude/bin/learning-store.py init --repo "$PROBE_ROOT/store"
python3 ~/.claude/bin/learning-store.py import --source "$PROBE_ROOT/source"
python3 ~/.claude/bin/learning-store.py status
python3 ~/.codex/bin/learning-store.py status
python3 ~/.claude/bin/learning-store.py record --input "$PROBE_ROOT/operation.json"
python3 ~/.codex/bin/learning-store.py record --input "$PROBE_ROOT/operation.json"
```

すべてのcommandへ `XDG_CONFIG_HOME="$PROBE_ROOT/xdg"` を設定する。`source`は`git init`後、空commitを一つ作り、`store`は実在する空directoryにする。`operation.json`は固定UUID、UTC日時、`kind:"operation"`、公開可能な能力IDまたはnull、終了理由、wait_countだけを持つ。期待結果は両`status`のstore_id/root/stateが同一、1回目recordは`created:true`、Codex入口からの再送は同じpath/idで`created:false`、store内operationは1file、source/store以外の作業repoは無変更。各stdout/stderr、終了code、operation SHA-256、実行したCLIの`resolve()`先をresearch記録へ残す。破損ケースはunittest専用で、実storeへ注入しない。

- [ ] **Step 2:** 次の全体コマンドを実行し、失敗があれば原因を修正して再実行する。成功したテスト数と失敗した検査を実測値で報告する。現行26件の成功は拡張実装の証拠に数えない。

```bash
python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -v
bash -n setup.sh
git diff --check
```

- [ ] **Step 3:** Terra / highへCLIの入力・ファイル・Git境界の読み取り専用レビューを検証済みhandoff付きの別agentまたはfresh sessionで依頼し、symlink race、排他、public情報、bindingの乗換、破損file、既存file保護を検査する。修正後に別のSol / high担当で最終統合レビューを行う。同一threadの親モデル切替は使わず、モデル名だけをレビューの正しさの証拠にしない。
- [ ] **Step 4:** 実ホスト対話用fixtureは、キャンセル後の結果適用を防ぐ外部挙動だけをtestで示し、故障箇所や正解assertionをpromptに書かない。各ホスト・各scenarioで新規sessionを作り、cwdを設定repoでなくfixtureをcopyした一時Git repoへ固定する。ユーザー設定を読む通常modeで起動し、bindingだけはStep 1と同じ一時`XDG_CONFIG_HOME`へ向ける。全commandをfixture repoのcwdで実行する。Claude Codeは `claude -p --verbose --session-id <UUID> --output-format stream-json <turn-1>`、続きは `claude -p --verbose --resume <UUID> --output-format stream-json <turn-N>`とし、assistant本文に加えてtool eventも回収する。Codexは `codex exec -C <fixture-repo> --json -o <last-message> <turn-1>`で開始し、`thread.started`のthread IDを取得して同じcwdから `codex exec resume <thread-id> --json -o <last-message> <turn-N>`で続ける。`--ephemeral`はresume不能になるため使わない。これらのoptionがローカルCLIの`--help`に存在することを実行前に再確認し、help確認を実session成功の証拠には数えない。

  scenario入力と期待停止を事前に固定する。

  | scenario | turn入力 | 期待する停止と回収証拠 |
  |---|---|---|
  | Investigateと担当拡大 | T1: 「失敗testの原因を調べ、必要なら直して検証して。学習はON」 | 対象関数・仮説・正解assertionを先に示さず、本人の担当範囲と外部挙動を示して最初の調査行動を待つ。T2のユーザー観測後は理由を一問だけ尋ねて停止。T3以降の誤答を2回与えても完成解を引き取りにせず、反例/観測差を一つ示して再調査を待つ |
  | 同一能力の競合 | T1: Factory採否と実装読解が同じ箇所にある依頼 | Predictかコード技能の一方だけを選び、同じ解法で二重停止しない。選択したevent_idとoperation件数を回収する |
  | 開示順と中断再開 | T1: Review、別sessionではWrite/Modify/Predict。T2:提出、T3:理由、T4:「ここで中断」、同じsessionをresume | 提出前に★ Review/定石/WHY/模範解を出さず、理由後も未解消なら反例へ戻す。resume後も同じ担当範囲・event_idで、独立した成功を増やさない |
  | OFF・skip・保存不能 | T1: 「急ぎ、学習なしで完了して」。別sessionでは課題提示後にskip。別sessionでは未設定XDGで学習ON | OFFではoperationを作らず通常作業を完了。skip後は理由・転移を強制しない。保存不能はsession中一度通知し、未保存を明示して通常作業を完了する |
  | 上限・後日候補 | 1 task内に3候補。別fixtureでは最後の独立成功から7日を表す記録 | 合計2/code1を超えて停止しない。7日fixtureは確認候補の選択だけを検査し、保持成功とは記録しない |

  各turnの入力、JSON/JSONL、最終message、session/thread ID、cwd、host/CLI version、storeのrecord/operation IDとpath、開始前後の`git status --short`を保存する。AI tool出力・diff・agent報告や完成済みAIテストが答えを漏らした場合は支援として明記する。Aのmock成功をCの自動発火証拠へ、Cの架空回答をTask 8のユーザー成長へ変換しない。認証・runtime都合で実行不能なhost/scenarioは理由付き「未検証」とし、成功扱いしない。
- [ ] **Step 5:** テスト・レビュー・実ホスト記録を対象ファイルだけstageし`git diff --cached --check`後、`test: 学習storeと実ホスト導線を検証`でcommitする。実ホストを実行できなかった場合は、その未検証を記した文書だけをcommitし、このTaskの実ホスト受入は未完了とする。

## Task 8: 別工程で学習repo初期化・移管・pilotを実施

**Files:** 専用repo `programming-learning` のREADME、marker、legacy、imports、records、operations。設定repo内の旧記録本文は編集しない。pilot結果は公開可能な `docs/research/` 記録へ保存する。

**Interfaces:** Consumes Task 1–7の検証済み製品と、ユーザーが計画・配置値を確認した結果。提案名`programming-learning`、提案clone先`~/garage/programming-learning`、PUBLIC。外部GitHub remoteの作成とpushは明示的な別操作でありhelperは実行しない。

- [ ] **Step 1:** 実施時点で旧対象の件数と各SHA-256を取り、本文だけでなく旧ファイル名・import manifest公開面を監査する。不適合なら移管を止めて修正方針を別途決める。`init --repo <絶対path>`でpreparedにし、`import --source <設定repo>`を実行する。
- [ ] **Step 2:** manifestのsource commit、全相対path・hash・件数とlegacy原文bytesを照合し、markerのactive、bindingのstore_id、既存ADRリンク、同一import再実行の冪等性を確認する。ファイル保存とGit commitとremote反映の結果を別々に報告する。別マシンはclone後`bind`し同じstore_idを確認する。
- [ ] **Step 3:** 両ホストの実対話検証が通った後、適格な実作業5〜10件で少数の能力に絞ってpilotする。各回の担当範囲、開始契機、既知の箇所・仮説・検証、支援、本人が選んだ次の行動、再修正、skip/中断、別文脈・後日の証拠を対応づける。「一工程から範囲が広がったか」「本人が検証方法を選んだか」「促されず必要な確認を始めたか」を別々に報告する。機会無しは未観測、機会があってAIが担当し続けた場合は運用改善対象とする。本人の成長や因果効果を件数だけから主張しない。
- [ ] **Step 4:** pilot結果と誤採点・未確認事項をレビューし、変更が必要なら新ADRへ却下案と根拠を残して次の計画を作る。旧core計画 `docs/superpowers/plans/2026-09-17-code-learning-core.md` のTask 5の実ホスト対話とTask 6のpilotは本Task 7–8へ対応するが、現時点ではどちらも未完了。mockやruntime routing成功を学習の動作証拠へ読み替えない。
- [ ] **Step 5:** 初期移管の公開監査とmanifest照合が成功した時点で、専用repoのREADME、marker、legacy、import manifestだけをstageし、`learning-records`ブランチへ`chore: 学習記録storeを初期化`でcommitする。pilotのrecord/operationは観測ごとに対象fileだけを別commitし、設定repoのresearch記録もそのrepo内の対象文書だけでcommitする。remote作成・pushはこのcommit単位に含めず、ユーザーが具体的なremoteと可視性を確認した後の別操作にする。

## 要件・レビュー対応と依存

| 正本の節・所見 | 実装Task | 検証Task |
|---|---|---|
| §1 目的・承認境界、§2 現状 | 5–6 | 7–8 |
| §3 所有範囲、§4 発火競合 | 5–6 | 7 |
| §5 自力調査と担当範囲、レビュー所見1 | 5 | 7–8 |
| §6 回答・再修正、レビュー所見2 | 5 | 7–8 |
| §7 成長・後日確認、レビュー所見3 | 2、5–6 | 7–8 |
| §8 repo構造・記録・supersedes、レビュー所見4 | 2–3、6 | 7 |
| §9 binding・保存・両ホスト | 1–3、6 | 7 |
| §10 旧記録移管 | 4、6、8 | 7–8 |
| §11 変更範囲 | 1–6 | 7 |
| §12 静的・mock・実ホスト・pilot | 1–8 | 7–8 |
| §13 採らない案、§14 根拠と限界 | 5–6、8 | 7–8 |

依存は `1 → 2 → 3 → 4`（保存CLI）、`4 → 5 → 6 → 7 → 8`（契約と実機）とする。Task 5の文章草案はTask 1–4と並行に検討できるが、保存CLIの出力と失敗契約へ合わせてからcommitする。各Taskは対象テストが赤から緑へ変わり、対象ファイルだけのcommitで区切る。Task 7の実ホストとTask 8の実学習repo・pilotは自動テストが緑でも代替できない。

## 実装前の最小決定と未解決事項

- `scope`を短いfrontmatter文字列に加えるのは、引数なしlistで「能力IDと短い対象範囲」を返すための最小決定。意味の同一性は本文を読んで判断する。
- CLI成功/失敗のJSON形、終了2、UTC日時、入力固定キーは複数Taskのinterfaceを揃えるための実装上の決定。実装レビューで変更する場合は同じTask内のテスト・README・後続参照を同時に更新する。
- `fcntl`とGit metadata内lockはmacOS/LinuxのPython 3.9運用を前提とする。異なるOSへの配布が必要になった時点で別設計を行う。
- PUBLIC repo名とclone先は提案値。remote作成、旧記録の公開可否、実ホストでの対話、5〜10件pilotの結果はまだ未確認。security・最終統合レビューは実装後に実施する。

## Self-review

- 仕様§1–14とレビュー所見4件の対応を上表で確認した。レビュー所見1–3は静的契約だけで終わらせず、実ホストとpilotの観測へ接続した。
- `init/status/bind/list/record/import`、marker/binding、read失敗と0件、訂正分岐、operation、旧recordの本文不変、両ホスト配布と公開面をTask内で確認した。
- 重要経路のコード例はGit root照合、版グラフ、排他的公開と、赤になるテスト例で示した。説明文だけで実装済み・テスト済みとは扱っていない。
- ADR 0001/0007/0012の理由を維持し、親工程のADR 0017を重複作成しない。旧coreの実ホスト・pilot未完了を継承した。
- 文書検査では8 Task・40 Step、26個のcode fence（対応済み）、11個のPython例（Python 3.9の`ast.parse`成功）、既存参照22件の実在、禁止placeholderの不在を確認した。計画fileは未追跡のため`git diff --no-index --check /dev/null <plan>`を使い、差分ありを表す終了1・空の診断（空白errorなし）を確認した。製品CLIや実sessionはまだ存在・実行していないため、これらの成功は主張しない。

## Execution Handoff

この計画と実行方式をユーザーが確認するまでTask 1へ進まない。実行方法は**連続した一つの実装担当**を推奨する。検証済みhandoff付きのSol / high agentまたはfresh sessionがTask 1から7を順に実施し、親Astraは工程調整と結果確認を担う。CLIのschema・状態・エラー契約が後続のruleと運用文書へ連鎖するため、実装担当をTask間で替えず、各Taskの赤/緑・commit・interfaceを順に確定する。security reviewは別のTerra / high担当、最終統合reviewは実装担当ともsecurity担当とも別のSol / high担当にする。同一threadの親モデル切替は使わない。Task 8は製品検証と計画承認後の外部repo・実ユーザー工程として別に開始する。設定repo自身はworktreeを使わず、並列レビュー時はファイル所有を分けて他者の差分を戻さない。
