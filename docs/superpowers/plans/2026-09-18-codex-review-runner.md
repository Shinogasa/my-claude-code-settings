# Codex Review Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** validated cross-model handoffからread-only Codex reviewを一度だけ起動し、全行読了、最終report、turn完了、resume-onceを機械的に判定するrunnerを実装する。

**Architecture:** report契約とJSONL evidenceを副作用のない`bin/codex_review_contracts.py`へ分離し、path・lock・subprocess・manifest・状態機械を`bin/codex_review_runner.py`へ置く。`bin/run-codex-review.py`はargument parseと固定終了コードだけを担当する薄いCLIにし、既存`bin/validate-codex-handoff.py`は変更せず入力完全性の境界として利用する。

**Tech Stack:** Python 3.11+ standard library (`argparse`, `dataclasses`, `fcntl`, `hashlib`, `json`, `os`, `selectors`, `shlex`, `signal`, `subprocess`), `unittest`, Bash setup, Markdown

**Spec:** `docs/superpowers/specs/2026-09-18-codex-review-runner-design.md`

## Global Constraints

- provider、profile、`--oss`、`--local-provider`、任意config overrideをrunnerの公開引数にしない
- modelとreasoning effortは常にペア指定し、handoff metadataと一致させる
- 初回turnとresumeのsandboxは`read-only`を明示し、resumeでも`-c sandbox_mode="read-only"`を渡す
- `--json`と`--output-last-message`を常に併用し、`--last`と`--ephemeral`を使わない
- resumeは入力読了済み・exit 0・`turn.completed`・session IDあり・reportだけ無効の場合に最大1回
- resume失敗後に新しいreview、2回目のresume、provider切替を自動実行しない
- raw stderr、prompt、environment、config全文、report本文をmanifestや親terminalへ保存・転記しない
- artifact rootは`.superpowers/review-runs/`、directory `0700`、file `0600`、Git ignore必須
- validatorはrunner実体に隣接する`validate-codex-handoff.py`だけを使い、対象repositoryから探索しない
- 外部modelを通常test suiteから呼ばない。fixture JSONLとstub `codex`で状態機械を検証する
- 実装完了前にTerra + high + read-onlyのsecurity review、Sol + highのintegration reviewを行う

---

## File Map

| File | Responsibility |
|---|---|
| `bin/codex_review_contracts.py` | handoff metadata、report契約、JSONL event、validated-read receiptの純粋parse/検証 |
| `bin/codex_review_runner.py` | validator precheck、safe artifact、task lock、child process、manifest、resume-once状態機械 |
| `bin/run-codex-review.py` | CLI argument、終了コード、標準エラーへの安全な1行summary |
| `tests/test_codex_review_runner.py` | 純粋契約、path、lock、stub process、resume、manifestの回帰test |
| `tests/fixtures/codex-review-runner/double-read.jsonl` | 過去に観測した一括＋分割readの最小匿名fixture |
| `tests/fixtures/codex-review-runner/resume-success.jsonl` | 同一sessionでreportだけ回収した最小匿名fixture |
| `.gitignore` | `.superpowers/review-runs/`をrepository-localにignore |
| `setup.sh` | runnerの3 Python file欠落をCodex setup preflightで拒否 |
| `tests/test_setup_cli.py` | preflightと`~/.codex/bin/`配布経路 |
| `codex/MODEL_ROUTING.md` | cross-model reviewをrunner経由にする運用契約 |
| `tests/test_codex_model_routing.py` | runner経由、provider不変、model + effort pairの文書契約 |
| `README.md` | CLI利用方法、成果物、状態、失敗時の確認場所 |

## Shared Interfaces

`bin/codex_review_contracts.py`は次を公開する。

```python
@dataclass(frozen=True)
class HandoffContext:
    task_id: str
    input_digest: str
    model: str
    reasoning_effort: str
    contract: str
    required_documents: tuple[str, ...]

@dataclass(frozen=True)
class ReadExpectation:
    rtk_path: str
    python_path: str
    validator_path: str
    repo_argument: str
    handoff_argument: str
    model: str
    reasoning_effort: str
    input_digest: str

@dataclass(frozen=True)
class ReadReceipt:
    document: str
    start_line: int
    end_line: int
    total_lines: int

@dataclass(frozen=True)
class ReportMetadata:
    source: str
    human_confirmation_required: bool | None
    confidence: str | None
    ready_to_commit: str | None

@dataclass(frozen=True)
class ValidatedReport:
    text: str
    metadata: ReportMetadata

@dataclass
class EventSummary:
    session_id: str | None
    turn_completed: bool
    terminal_error: bool
    invalid_json: bool
    unknown_event_count: int
    agent_messages: list[str]
    receipts: list[ReadReceipt]
```

`bin/codex_review_runner.py`は次を公開する。

```python
@dataclass(frozen=True)
class RunnerRequest:
    repo: Path
    handoff: Path
    model: str
    reasoning_effort: str
    contract: str

@dataclass(frozen=True)
class RunnerResult:
    state: str
    exit_code: int
    run_directory: Path | None
    session_id: str | None

run_review(request: RunnerRequest) -> RunnerResult
```

---

### Task 1: Markdown ReportとValidated Handoff契約

**Files:**

- Create: `bin/codex_review_contracts.py`
- Create: `tests/test_codex_review_runner.py`

**Interfaces:**

- Consumes: validator `read`の`DOCUMENT: handoff lines 1-N of N` + handoff bytes
- Produces: `HandoffContext`, `ReportMetadata`, `parse_validated_handoff()`, `validate_report()`

- [ ] **Step 1: Write the failing report-contract tests**

`tests/test_codex_review_runner.py`へimport helperと次の代表caseを追加する。

```python
ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "bin" / "codex_review_contracts.py"

def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

class ReportContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts = load_module("codex_review_contracts", CONTRACTS)

    def test_security_report_requires_human_confirmation_for_critical(self):
        report = """## Findings
Severity: Critical

## Confidence
Confidence: sufficient

## Human confirmation required
Human confirmation required: no
"""
        with self.assertRaisesRegex(ValueError, "SECURITY_CONFIRMATION_MISMATCH"):
            self.contracts.validate_report(report, "security", "fixture")

    def test_integration_report_requires_all_severity_sections(self):
        report = """## Strengths
Safe.

## Issues
### Critical
None
### Important
None

## Recommendations
None

## Assessment
Ready to commit: Yes
"""
        with self.assertRaisesRegex(ValueError, "REPORT_SECTION_MISSING: Minor"):
            self.contracts.validate_report(report, "integration", "fixture")
```

追加case:

- security: `No findings` + sufficient + confirmation noは成功
- security: insufficient + confirmation yesは成功
- security: `No findings`と`Severity:`混在は失敗
- security: section欠落、重複、順序逆転は失敗
- integration: Critical / Important / Minorが各`None`で`Ready to commit: Yes`は成功
- integration: `Ready to commit`重複、未知値、空sectionは失敗
- placeholder: 空白と完全一致`Please continue.`を除外し、それ以外は保持

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `rtk python3 -m unittest tests.test_codex_review_runner.ReportContractTests -v`

Expected: ERROR because `bin/codex_review_contracts.py` does not exist.

- [ ] **Step 3: Implement exact report parsing**

`bin/codex_review_contracts.py`へdataclassと次のAPIを実装する。

```python
class ContractError(ValueError):
    pass

def is_placeholder_message(text: str) -> bool:
    normalized = text.strip()
    return not normalized or normalized == "Please continue."

def validate_report(text: str, contract: str, source: str) -> ReportMetadata:
    if contract == "security":
        return _validate_security_report(text, source)
    if contract == "integration":
        return _validate_integration_report(text, source)
    raise ContractError("UNKNOWN_CONTRACT")
```

実装規則:

- headingは`^## ` / `^### `のmultiline regexで位置を取り、必須headingが各1件かつ順序どおりか確認する
- fieldはcase-sensitiveな完全行一致で数え、候補値がちょうど1件でなければ固定reason codeを返す
- `ReportMetadata.source`へ呼出し側の`output-last-message`または`jsonl-agent-message`を保持する
- report本文をexception messageへ含めない

- [ ] **Step 4: Write failing validated-handoff tests**

```python
class HandoffContractTests(unittest.TestCase):
    def test_security_context_comes_only_from_validated_bytes(self):
        payload = make_handoff_bytes(
            task_id="review-task",
            model="gpt-5.6-terra",
            effort="high",
            requirements=("none", "none"),
            review_package=("review.diff", "a" * 64),
            report_contract=("Findings", "Confidence", "Human confirmation required"),
        )
        context = self.contracts.parse_validated_handoff(
            b"DOCUMENT: handoff lines 1-41 of 41\n" + payload,
            input_digest="b" * 64,
            model="gpt-5.6-terra",
            reasoning_effort="high",
            contract="security",
        )
        self.assertEqual(context.task_id, "review-task")
        self.assertEqual(context.required_documents, ("handoff", "review-package"))
```

追加case:

- headerが`1-N of N`でない、1 MiB超、100万行超を拒否
- task ID、model、effort、SHA-256、required fieldの不正を拒否
- CLI pairとfrontmatter pair不一致を拒否
- security/integration markerの欠落・混在・重複を`CONTRACT_MISMATCH`で拒否
- requirements/review-packageの`none` pair不一致を拒否

- [ ] **Step 5: Run handoff tests and verify RED**

Run: `rtk python3 -m unittest tests.test_codex_review_runner.HandoffContractTests -v`

Expected: FAIL because `parse_validated_handoff` is missing.

- [ ] **Step 6: Implement validated-handoff parsing**

```python
def parse_validated_handoff(
    output: bytes,
    *,
    input_digest: str,
    model: str,
    reasoning_effort: str,
    contract: str,
) -> HandoffContext:
    header, separator, body = output.partition(b"\n")
    if not separator:
        raise ContractError("HANDOFF_HEADER_MISSING")
    start, end, total = parse_document_header(header, expected_document="handoff")
    if start != 1 or end != total:
        raise ContractError("HANDOFF_READ_INCOMPLETE")
    metadata, sections = parse_handoff_bytes(body)
    validate_handoff_contract_markers(sections["返却レポート契約"], contract)
    required_documents = ["handoff"]
    if metadata["requirements_path"] != "none":
        required_documents.append("requirements")
    if metadata["review_package_path"] != "none":
        required_documents.append("review-package")
    return HandoffContext(
        task_id=metadata["task_id"],
        input_digest=input_digest,
        model=metadata["model"],
        reasoning_effort=metadata["reasoning_effort"],
        contract=contract,
        required_documents=tuple(required_documents),
    )
```

`required_documents`は常に`handoff`を先頭にし、`requirements_path != none`、
`review_package_path != none`の順で追加する。

- [ ] **Step 7: Run Task 1 tests and verify GREEN**

Run: `rtk python3 -m unittest tests.test_codex_review_runner.ReportContractTests tests.test_codex_review_runner.HandoffContractTests -v`

Expected: all Task 1 tests PASS.

- [ ] **Step 8: Commit Task 1**

```bash
rtk git add bin/codex_review_contracts.py tests/test_codex_review_runner.py
rtk git commit -m "feat(codex): review report契約を追加"
```

---

### Task 2: JSONL EventとValidated Read Receipt

**Files:**

- Modify: `bin/codex_review_contracts.py`
- Modify: `tests/test_codex_review_runner.py`
- Create: `tests/fixtures/codex-review-runner/double-read.jsonl`
- Create: `tests/fixtures/codex-review-runner/resume-success.jsonl`

**Interfaces:**

- Consumes: Codex JSONL `thread.started`, `turn.completed`, `turn.failed`, `error`, `item.completed`
- Produces: `ReadExpectation`, `ReadReceipt`, `EventSummary`, `parse_event_lines()`, `validate_read_coverage()`

- [ ] **Step 1: Add the two minimal fixtures**

`double-read.jsonl`は同じdigestで次のeventだけを持つ。command string内のpathは
`/__RTK__`、`/__PYTHON__`、`/__VALIDATOR__`、`/__REPO__`、`/__HANDOFF__` tokenにし、test helperが
実pathへ置換する。

```jsonl
{"type":"thread.started","thread_id":"01a0a7fa-fd0d-75e1-b2c5-e92f0bc28db9"}
{"type":"item.completed","item":{"type":"command_execution","status":"completed","exit_code":0,"command":"/bin/zsh -lc '/__RTK__ /__PYTHON__ /__VALIDATOR__ read /__HANDOFF__ --repo /__REPO__ --expected-model gpt-5.6-sol --expected-reasoning-effort high --expected-input-digest aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa --document review-package --start-line 1 --line-count 5000'","aggregated_output":"DOCUMENT: review-package lines 1-4759 of 4759\n"}}
{"type":"item.completed","item":{"type":"command_execution","status":"completed","exit_code":0,"command":"/bin/zsh -lc '/__RTK__ /__PYTHON__ /__VALIDATOR__ read /__HANDOFF__ --repo /__REPO__ --expected-model gpt-5.6-sol --expected-reasoning-effort high --expected-input-digest aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa --document review-package --start-line 1 --line-count 600'","aggregated_output":"DOCUMENT: review-package lines 1-600 of 4759\n"}}
{"type":"turn.completed"}
```

`resume-success.jsonl`は同一thread ID、agent message、`turn.completed`だけを持つ。

- [ ] **Step 2: Write failing event and receipt tests**

```python
class EventContractTests(unittest.TestCase):
    def test_double_read_fixture_is_rejected(self):
        summary = self.contracts.parse_event_lines(
            render_fixture("double-read.jsonl"), self.expectation()
        )
        with self.assertRaisesRegex(ValueError, "READ_RANGE_OVERLAP"):
            self.contracts.validate_read_coverage(
                summary.receipts, ("review-package",)
            )

    def test_agent_message_cannot_forge_document_receipt(self):
        lines = [json.dumps({
            "type": "item.completed",
            "item": {"type": "agent_message", "text":
                "DOCUMENT: handoff lines 1-80 of 80"},
        }).encode()]
        summary = self.contracts.parse_event_lines(lines, self.expectation())
        self.assertEqual(summary.receipts, [])
```

追加case:

- session ID 1件、異なるID 2件、missing ID
- `turn.completed`、`turn.failed`、top-level `error`
- 壊れたJSON / JSON scalarはinvalid、未知eventはcountのみ
- 最後の非placeholder agent messageだけをfallback候補にする
- command status非completed、exit code非0、headerが先頭行でないものはreceiptにしない
- outer shellが`/bin/zsh -lc`または`/bin/bash -lc`以外なら拒否
- inner commandのpipe、`&&`、`;`、redirect、backtick、`$(`を拒否
- rtk / Python / validator / repo / handoff / model / effort / digestの1項目違いを拒否
- range gap、overlap、duplicate、total不一致、先頭非1、末尾非totalを拒否

- [ ] **Step 3: Run event tests and verify RED**

Run: `rtk python3 -m unittest tests.test_codex_review_runner.EventContractTests -v`

Expected: FAIL because event APIs are missing.

- [ ] **Step 4: Implement strict event parsing**

```python
def parse_event_lines(
    lines: Iterable[bytes], expectation: ReadExpectation
) -> EventSummary:
    summary = EventSummary(None, False, False, False, 0, [], [])
    for raw_line in lines:
        event = parse_json_object(raw_line)
        event_type = event.get("type")
        if event_type == "thread.started":
            summary.session_id = merge_session_id(summary.session_id, event)
        elif event_type == "turn.completed":
            summary.turn_completed = True
        elif event_type in {"turn.failed", "error"}:
            summary.terminal_error = True
        elif event_type == "item.completed":
            consume_completed_item(summary, event["item"], expectation)
        else:
            summary.unknown_event_count += 1
    return summary
```

command検証は、outerを`shlex.split`して`[shell, "-lc", inner]`の3 tokenへ固定し、inner raw
stringへ`&&|\|\||;|[<>`]|\$\(`があれば拒否してから`shlex.split(inner)`する。inner argvは
`ReadExpectation`から生成した完全な1列と一致させる。

- [ ] **Step 5: Implement exact coverage validation**

```python
def validate_read_coverage(
    receipts: Sequence[ReadReceipt], required_documents: Sequence[str]
) -> dict[str, list[ReadReceipt]]:
    grouped = {document: [] for document in required_documents}
    for receipt in receipts:
        if receipt.document not in grouped:
            raise ContractError("UNEXPECTED_READ_DOCUMENT")
        grouped[receipt.document].append(receipt)
    for document, values in grouped.items():
        ordered = sorted(values, key=lambda value: (value.start_line, value.end_line))
        if not ordered:
            raise ContractError(f"READ_RANGE_MISSING: {document}")
        expected_start = 1
        total = ordered[0].total_lines
        for receipt in ordered:
            if receipt.total_lines != total:
                raise ContractError("READ_TOTAL_MISMATCH")
            if receipt.start_line < expected_start:
                raise ContractError("READ_RANGE_OVERLAP")
            if receipt.start_line > expected_start:
                raise ContractError("READ_RANGE_GAP")
            expected_start = receipt.end_line + 1
        if expected_start != total + 1:
            raise ContractError("READ_RANGE_INCOMPLETE")
    return grouped
```

- [ ] **Step 6: Run Task 2 tests and verify GREEN**

Run: `rtk python3 -m unittest tests.test_codex_review_runner.EventContractTests -v`

Expected: all event/receipt tests PASS.

- [ ] **Step 7: Commit Task 2**

```bash
rtk git add bin/codex_review_contracts.py tests/test_codex_review_runner.py tests/fixtures/codex-review-runner
rtk git commit -m "feat(codex): review event証拠を検証"
```

---

### Task 3: Validator Precheck、Private Artifact、Task Lock

**Files:**

- Create: `bin/codex_review_runner.py`
- Modify: `tests/test_codex_review_runner.py`
- Modify: `.gitignore`

**Interfaces:**

- Consumes: `RunnerRequest`, adjacent validator CLI, repository-local `.gitignore`
- Produces: `PrecheckResult`, `RunWorkspace`, `TaskLock`, safe manifest/file helpers

- [ ] **Step 1: Write failing precheck tests**

test fixtureは一時Git repositoryを作り、real validatorと同形式のstub validatorをrunner実体の
隣接directoryへ置く。stubは呼出しargvをJSONL logへ残し、`validate`でdigest、`read`でvalidated
handoff bytesを返す。

```python
class PrecheckTests(RepositoryTestCase):
    def test_validator_is_adjacent_to_runner_not_target_repository(self):
        (self.repository / "validate-codex-handoff.py").write_text(
            "raise SystemExit('wrong validator')\n", encoding="utf-8"
        )
        result = self.runner.precheck(self.request())
        self.assertEqual(result.context.task_id, "review-task")
        calls = [json.loads(line) for line in self.validator_log.read_text().splitlines()]
        self.assertEqual(calls[0][0], "validate")
        self.assertEqual(calls[1][0], "read")

    def test_contract_mismatch_stops_before_codex(self):
        self.write_handoff(contract="integration")
        with self.assertRaisesRegex(ValueError, "CONTRACT_MISMATCH"):
            self.runner.precheck(self.request(contract="security"))
        self.assertFalse(self.codex_log.exists())
```

追加case:

- validator symlink / missing / non-regularを拒否
- validate non-zero、digest欠落・重複、read non-zero、1 MiB超を拒否
- `--expected-model`と`--expected-reasoning-effort`が必ずペアでvalidator argvにある
- handoff pathをrunner自身が直接openしない（target handoffをvalidator stubだけが読めるfixture）
- `.superpowers/review-runs/`がrepository-local ignoreでない、追跡済み、Git検査不能を拒否

- [ ] **Step 2: Run precheck tests and verify RED**

Run: `rtk python3 -m unittest tests.test_codex_review_runner.PrecheckTests -v`

Expected: ERROR because `bin/codex_review_runner.py` does not exist.

- [ ] **Step 3: Implement validator precheck**

```python
@dataclass(frozen=True)
class PrecheckResult:
    context: HandoffContext
    repo_path: Path
    validator_path: Path
    rtk_path: Path
    python_path: Path
    repo_argument: str
    handoff_argument: str

def precheck(request: RunnerRequest) -> PrecheckResult:
    validator = adjacent_regular_file("validate-codex-handoff.py")
    digest = run_validator_validate(validator, request)
    handoff_output = run_validator_read_all(validator, request, digest)
    context = parse_validated_handoff(
        handoff_output, input_digest=digest, model=request.model,
        reasoning_effort=request.reasoning_effort, contract=request.contract,
    )
    repo_path = request.repo.resolve(strict=True)
    return PrecheckResult(
        context=context,
        repo_path=repo_path,
        validator_path=validator,
        rtk_path=resolve_required_executable("rtk"),
        python_path=Path(sys.executable).resolve(strict=True),
        repo_argument=os.fspath(repo_path),
        handoff_argument=os.fspath(request.handoff),
    )
```

validator subprocessはshellを使わずargv配列、`capture_output=True`、最大output 1 MiBとする。
stderr本文を親へ転記せず、non-zero時は`VALIDATOR_VALIDATE_FAILED`または`VALIDATOR_READ_FAILED`だけを
raiseする。

- [ ] **Step 4: Add repository-local ignore**

`.gitignore`の`.superpowers`説明の直後へ追加する。

```gitignore
# Codex review runnerの実行logとreport。認証・review内容を含み得るprivate artifact。
.superpowers/review-runs/
```

- [ ] **Step 5: Write failing artifact and lock tests**

```python
class WorkspaceTests(RepositoryTestCase):
    def test_workspace_is_private_and_unique(self):
        workspace = self.runner.create_run_workspace(
            self.repository, task_id="review-task"
        )
        self.assertEqual(stat.S_IMODE(workspace.run_directory.stat().st_mode), 0o700)
        manifest = workspace.run_directory / "manifest.json"
        self.assertEqual(stat.S_IMODE(manifest.stat().st_mode), 0o600)

    def test_same_task_lock_is_non_blocking(self):
        with self.runner.acquire_task_lock(self.repository, "review-task"):
            with self.assertRaisesRegex(ValueError, "ALREADY_RUNNING"):
                with self.runner.acquire_task_lock(self.repository, "review-task"):
                    self.fail("second lock acquired")
```

追加case:

- `.superpowers` / `review-runs` / task directory / run directoryの各component symlink拒否
- task ID allowlist、128-bit randomを含むrun ID、exclusive create
- file createが`O_EXCL | O_NOFOLLOW`、existing fileを上書きしない
- task IDが異なればlock取得可能
- `last-message`回収時のregular file、owner、0600、link count 1
- manifest atomic replace後も0600

- [ ] **Step 6: Run workspace tests and verify RED**

Run: `rtk python3 -m unittest tests.test_codex_review_runner.WorkspaceTests -v`

Expected: FAIL because workspace/lock APIs are missing.

- [ ] **Step 7: Implement safe workspace and lock**

`os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)`で
componentごとにdirectory FDを固定する。
作成時はprocessの旧umaskを保存して`0o077`へ変更し、finallyで復元する。

```python
@contextmanager
def acquire_task_lock(repo: Path, task_id: str) -> Iterator[int]:
    lock_fd = open_private_lock_file(repo, task_id)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        os.close(lock_fd)
        raise RunnerError(3, "ALREADY_RUNNING", "ALREADY_RUNNING") from error
    try:
        yield lock_fd
    finally:
        os.close(lock_fd)
```

- [ ] **Step 8: Run Task 3 tests and verify GREEN**

Run: `rtk python3 -m unittest tests.test_codex_review_runner.PrecheckTests tests.test_codex_review_runner.WorkspaceTests -v`

Expected: all Task 3 tests PASS.

- [ ] **Step 9: Commit Task 3**

```bash
rtk git add .gitignore bin/codex_review_runner.py tests/test_codex_review_runner.py
rtk git commit -m "feat(codex): private review workspaceを追加"
```

---

### Task 4: Codex Process監視、Report回収、Resume-once状態機械

**Files:**

- Modify: `bin/codex_review_runner.py`
- Create: `bin/run-codex-review.py`
- Modify: `tests/test_codex_review_runner.py`

**Interfaces:**

- Consumes: `PrecheckResult`, `RunWorkspace`, stub/real `codex` executable
- Produces: `run_codex_attempt()`, `run_review()`, CLI終了コード0/2/3/4/5/128+signal

- [ ] **Step 1: Add a configurable stub Codex fixture**

testの一時`PATH`先頭へ`codex` executableを置く。stubは`CODEX_STUB_SCENARIO`のJSON fileを読み、
呼出しargvとstdin SHA-256を`CODEX_STUB_LOG`へ追記する。scenarioのattempt順にJSONLをstdout、
任意bytesをstderr、最終messageを`--output-last-message` pathへ書き、指定exit codeで終了する。
stub sourceはtest helperが生成し、credentialやreal configを参照しない。

- [ ] **Step 2: Write failing argv and process-evidence tests**

```python
class AttemptTests(RepositoryTestCase):
    def test_initial_argv_pins_model_effort_sandbox_and_outputs(self):
        result = self.run_cli(scenario=successful_security_scenario())
        self.assertEqual(result.returncode, 0, result.stderr)
        argv = self.stub_calls()[0]["argv"]
        self.assertEqual(argv[:2], ["exec", "--json"])
        self.assertIn("--output-last-message", argv)
        self.assertIn("gpt-5.6-terra", argv)
        self.assertIn('model_reasoning_effort="high"', argv)
        self.assertIn('sandbox_mode="read-only"', argv)
        self.assertIn("read-only", argv)
        self.assertNotIn("--last", argv)
        self.assertNotIn("--ephemeral", argv)
        self.assertFalse({"--oss", "--local-provider", "--profile"} & set(argv))
```

追加case:

- `subprocess.Popen`へ`start_new_session=True`、`shell=False`が渡ることをmockで検査
- stdout/stderrを同時drainし、stderrはfile/親stderrへ出さずbytes数とSHA-256だけmanifestへ残す
- JSONL 64 MiB、report 1 MiB、stderr 8 MiB超過でchild process group終了 + `FAILED_OUTPUT`
- non-zero、`turn.failed`、top-level errorは`FAILED_EXECUTION`
- exit 0でも`turn.completed`なし、invalid JSON、receipt不足は`FAILED_OUTPUT`
- safe `last-message`が有効ならprimary、無効なら最後の非placeholder agent messageだけをfallback
- 古いrun directoryのreportを参照しない

- [ ] **Step 3: Run attempt tests and verify RED**

Run: `rtk python3 -m unittest tests.test_codex_review_runner.AttemptTests -v`

Expected: FAIL because process APIs and CLI do not exist.

- [ ] **Step 4: Implement bounded concurrent drain**

```python
@dataclass(frozen=True)
class AttemptResult:
    kind: str
    exit_code: int
    summary: EventSummary
    report_text: str | None
    report_source: str | None
    stderr_bytes: int
    stderr_sha256: str

def select_valid_report(
    attempt: AttemptResult, contract: str
) -> ValidatedReport | None:
    """output-last-message、次に最後の非placeholder agent messageを検査する。"""

def finish_success(
    *,
    state: str,
    report: ValidatedReport,
    attempt: AttemptResult,
    request: RunnerRequest,
    checked: PrecheckResult,
    workspace: RunWorkspace,
    manifest: dict[str, object],
) -> RunnerResult:
    """reportをprivate fileへ保存し、terminal manifestと結果を返す。"""

def run_codex_attempt(
    *,
    kind: Literal["initial", "resume"],
    request: RunnerRequest,
    checked: PrecheckResult,
    workspace: RunWorkspace,
    expectation: ReadExpectation,
    session_id: str | None,
) -> AttemptResult:
    argv = build_codex_argv(
        kind=kind, request=request, workspace=workspace, session_id=session_id
    )
    prompt_bytes = build_review_prompt(
        kind=kind, request=request, checked=checked, expectation=expectation
    )
    process = subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=checked.repo_argument, start_new_session=True, shell=False, close_fds=True,
    )
    write_prompt_and_close(process.stdin, prompt_bytes)
    drained = drain_with_selectors(
        process=process,
        event_path=workspace.events_path(kind),
        event_limit=EVENT_LIMIT,
        stderr_limit=STDERR_LIMIT,
    )
    return collect_attempt_result(
        kind=kind,
        process=process,
        drained=drained,
        last_message_path=workspace.last_message_path(kind),
        expectation=expectation,
    )
```

selector loopはstdoutの完全な行をevent parserへ渡し、EOF後の末尾partial lineもJSONとして検査する。
limit超過またはsignal時は`os.killpg(process.pid, signal.SIGTERM)`、5秒以内に終了しなければ
`SIGKILL`し、必ず`wait()`する。

- [ ] **Step 5: Write failing state-machine and resume tests**

```python
class StateMachineTests(RepositoryTestCase):
    def test_missing_report_resumes_exact_session_once(self):
        scenario = initial_without_report_then_resume_report(
            session_id="01a0a7f7-2bd6-7b72-9676-3f5fd095b16f"
        )
        result = self.run_cli(scenario=scenario)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.stub_calls()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["argv"][:3], ["exec", "resume", "--json"])
        self.assertIn("01a0a7f7-2bd6-7b72-9676-3f5fd095b16f", calls[1]["argv"])
        self.assertNotIn("--last", calls[1]["argv"])
        self.assertEqual(self.manifest()["state"], "COMPLETED_RESUMED")
```

追加case:

- primary reportで`COMPLETED`、JSONL fallbackで`COMPLETED_RECOVERED`
- report無効でもrange不足、sessionなし、initial非0、error eventならresumeしない
- resume thread ID不一致、non-zero、turn未完了、report無効は`FAILED_OUTPUT`
- resumeでvalidated readが1件でも追加されたらduplicateとして失敗
- resume失敗後のcall数は常に2以下、新しいplain `exec`なし
- 同task lock競合はcall数0、exit 3
- manifestはRUNNINGからterminal stateへatomic更新し、full argv/prompt/environment/report本文を含まない
- SIGINT/SIGTERMは`CANCELLED` + `128 + signal`、resumeなし

- [ ] **Step 6: Run state-machine tests and verify RED**

Run: `rtk python3 -m unittest tests.test_codex_review_runner.StateMachineTests -v`

Expected: FAIL because `run_review` and resume behavior are missing.

- [ ] **Step 7: Implement `run_review` state machine**

```python
def run_review(request: RunnerRequest) -> RunnerResult:
    checked = precheck(request)
    with acquire_task_lock(checked.repo_path, checked.context.task_id):
        workspace = create_run_workspace(checked.repo_path, checked.context.task_id)
        manifest = initial_manifest(request, checked, workspace)
        write_manifest(workspace, manifest)
        expectation = build_read_expectation(request, checked)
        initial = run_codex_attempt(
            kind="initial",
            request=request,
            checked=checked,
            workspace=workspace,
            expectation=expectation,
            session_id=None,
        )
        validate_initial_execution(initial)
        validate_read_coverage(initial.summary.receipts, checked.context.required_documents)
        report = select_valid_report(initial, request.contract)
        if report is not None:
            return finish_success(
                state=report_state(report.metadata.source),
                report=report,
                attempt=initial,
                request=request,
                checked=checked,
                workspace=workspace,
                manifest=manifest,
            )
        validate_resume_preconditions(initial)
        resumed = run_codex_attempt(
            kind="resume",
            request=request,
            checked=checked,
            workspace=workspace,
            expectation=expectation,
            session_id=initial.summary.session_id,
        )
        reject_resume_receipts(resumed.summary.receipts)
        report = require_valid_resume_report(resumed, request.contract)
        return finish_success(
            state="COMPLETED_RESUMED",
            report=report,
            attempt=resumed,
            request=request,
            checked=checked,
            workspace=workspace,
            manifest=manifest,
        )
```

全failure pathは`RunnerError(exit_code, state, reason_code)`へ正規化する。exception文字列、child stderr、
report本文をCLIへ返さない。

- [ ] **Step 8: Implement the thin CLI**

`bin/run-codex-review.py`:

```python
#!/usr/bin/env python3
from codex_review_runner import RunnerError, RunnerRequest, run_review

def main() -> int:
    args = build_parser().parse_args()
    try:
        result = run_review(RunnerRequest(
            repo=Path(args.repo),
            handoff=Path(args.handoff),
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            contract=args.contract,
        ))
    except RunnerError as error:
        print(error.safe_summary(), file=sys.stderr)
        return error.exit_code
    print(result.safe_summary(), file=sys.stderr)
    return result.exit_code

if __name__ == "__main__":
    raise SystemExit(main())
```

CLI stdoutは空に保ち、stderr summaryはstate、session ID、run directoryのrepository-relative pathだけを
含める。

- [ ] **Step 9: Run Task 4 tests and verify GREEN**

Run: `rtk python3 -m unittest tests.test_codex_review_runner.AttemptTests tests.test_codex_review_runner.StateMachineTests -v`

Expected: all Task 4 tests PASS.

- [ ] **Step 10: Run the complete runner test file**

Run: `rtk python3 -m unittest tests.test_codex_review_runner -v`

Expected: all runner tests PASS; no external network/model invocation occurs.

- [ ] **Step 11: Commit Task 4**

```bash
rtk git add bin/codex_review_runner.py bin/run-codex-review.py tests/test_codex_review_runner.py
rtk git commit -m "feat(codex): review実行を確実に回収"
```

---

### Task 5: Setup、Routing、README配線

**Files:**

- Modify: `setup.sh`
- Modify: `tests/test_setup_cli.py`
- Modify: `codex/MODEL_ROUTING.md`
- Modify: `tests/test_codex_model_routing.py`
- Modify: `README.md`
- Modify: `docs/adr/0013-codex-review-runner.md` only if implementation differs from the accepted decision

**Interfaces:**

- Consumes: runner 3 Python files and fixed CLI
- Produces: setup preflight, installed `~/.codex/bin/`, user-facing operation contract

- [ ] **Step 1: Write failing setup preflight tests**

`tests/test_setup_cli.py`へ2 case追加する。

```python
def test_missing_review_runner_stops_before_home_mutation(self):
    (self.home / ".codex").mkdir()
    (self.repository / "bin" / "run-codex-review.py").unlink()
    result = run_setup(self.repository, self.home, "--codex")
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("run-codex-review.py", result.stderr)
    self.assertEqual(list((self.home / ".codex").iterdir()), [])

def test_codex_bin_link_exposes_review_runner(self):
    (self.home / ".codex").mkdir()
    result = run_setup(self.repository, self.home, "--codex")
    self.assertEqual(result.returncode, 0, result.stderr)
    installed = self.home / ".codex" / "bin" / "run-codex-review.py"
    self.assertEqual(installed.resolve(), (self.repository / "bin" / "run-codex-review.py").resolve())
```

同じmissing testを`codex_review_runner.py`と`codex_review_contracts.py`へsubTestで適用する。

- [ ] **Step 2: Run setup tests and verify RED**

Run: `rtk python3 -m unittest tests.test_setup_cli.SetupCliTests.test_missing_review_runner_stops_before_home_mutation tests.test_setup_cli.SetupCliTests.test_codex_bin_link_exposes_review_runner -v`

Expected: missing helper is not detected yet.

- [ ] **Step 3: Add setup preflight checks**

`setup.sh`の既存handoff validator check直後に3 fileをloop検査する。

```bash
  if selected_codex; then
    local review_helper
    for review_helper in codex_review_contracts.py codex_review_runner.py run-codex-review.py; do
      if [ ! -f "$SCRIPT_DIR/bin/$review_helper" ]; then
        red "Codex review runner が存在しません: $review_helper"
        return 1
      fi
    done
  fi
```

既存の`bin/` link targetを再利用し、個別linkは追加しない。

- [ ] **Step 4: Add failing routing-document tests**

```python
def test_cross_model_review_uses_review_runner(self):
    self.assertIn("run-codex-review.py", self.text)
    self.assertIn("--model", self.text)
    self.assertIn("--reasoning-effort", self.text)
    self.assertIn("--contract", self.text)
    self.assertIn("--last", self.text)
    self.assertIn("新しいreviewを自動起動しない", self.text)
    self.assertIn("provider", self.text)
```

`--last`は「使用しない」という文脈を正規表現で確認する。

- [ ] **Step 5: Run routing tests and verify RED**

Run: `rtk python3 -m unittest tests.test_codex_model_routing.CodexModelRoutingTests.test_cross_model_review_uses_review_runner -v`

Expected: FAIL because runner operation is undocumented.

- [ ] **Step 6: Document the runtime operation**

`codex/MODEL_ROUTING.md`の「モデル間handoff」後へ次を追加する。

- security / integration reviewはvalidated handoff作成後に`~/.codex/bin/run-codex-review.py`を使う
- model + effort + contractを常に明示する
- success state 3種とfailure state 4種
- exact session resume-once、`--last`禁止、新規review自動実行禁止
- provider不変、artifact root、manifest/report確認path

`README.md`のCodex model routing節へ実行例、state表、artifact tree、失敗時に見る
`manifest.json`と安全境界を追加する。URLはOpenAI公式2件を1行ずつflat listで示す。

- [ ] **Step 7: Run setup/routing tests and verify GREEN**

Run:

```bash
rtk python3 -m unittest tests.test_setup_cli tests.test_codex_model_routing -v
rtk bash -n setup.sh
```

Expected: all selected tests PASS and Bash syntax exits 0.

- [ ] **Step 8: Commit Task 5**

```bash
rtk git add setup.sh tests/test_setup_cli.py codex/MODEL_ROUTING.md tests/test_codex_model_routing.py README.md
rtk git commit -m "docs(codex): review runnerを運用へ配線"
```

---

### Task 6: Security Review、Integration Review、Fresh Verification

**Files:**

- Modify only files required by validated findings
- Create ignored: `.superpowers/handoffs/codex-review-runner-security.md`
- Create ignored: `.superpowers/handoffs/codex-review-runner-integration.md`
- Create ignored: `.superpowers/review-runs/`配下のtask ID別・random run ID別directory via the runner
- Modify: `tasks/todo.md` review section (ignored)

**Interfaces:**

- Consumes: complete implementation diff and new runner
- Produces: Terra security report, Sol integration report, full deterministic verification evidence

- [ ] **Step 1: Run deterministic verification before model review**

Run:

```bash
rtk python3 -m unittest discover -s tests -p 'test_*.py' -v
rtk python3 -m py_compile bin/codex_review_contracts.py bin/codex_review_runner.py bin/run-codex-review.py bin/validate-codex-handoff.py
rtk bash -n setup.sh
rtk git diff --check
```

Expected: all tests PASS; compile, Bash syntax, and diff check exit 0.

- [ ] **Step 2: Verify regression-test effectiveness**

Temporarily patch `validate_read_coverage()` to ignore `receipt.start_line < expected_start`, run only
`EventContractTests.test_double_read_fixture_is_rejected`, and confirm it FAILS. Restore the implementation with
`apply_patch` and rerun the test to PASS. Do not use `git checkout` or `git reset`.

Temporarily patch `run_review()` to allow a second plain `codex exec` after resume failure, run the corresponding
call-count test, confirm it FAILS, restore with `apply_patch`, and rerun to PASS.

- [ ] **Step 3: Create a fixed review package and security handoff**

実装開始時点のbase commit `11d451c`から現在のindexとworktreeまでを、Git自身のfile出力で一つの
固定packageへ書く。Task 1〜5の新規fileは各Taskでcommit済みなので、この比較に含まれる。先に
`rtk git ls-files --others --exclude-standard`を実行し、review対象の未追跡fileが0件であることを確認する。
handoffや過去のreview packageなどignore済みfileだけがある場合はこの検査へ現れない。

```bash
rtk mkdir -p .superpowers/sdd/codex-review-runner
rtk git diff --binary 11d451c --output=.superpowers/sdd/codex-review-runner/security-review.diff
rtk shasum -a 256 .superpowers/sdd/codex-review-runner/security-review.diff
```

`security-review.diff`のSHA-256をschema 1 handoffの`review_package_sha256`へ記録する。
`git diff 11d451c`はcommit `11d451c`のtreeと現在のindex + worktreeを直接比較するため、
Task 1〜5のcommitとその後のtracked unstaged修正を重複なく含む。

The security handoff must specify:

- model `gpt-5.6-terra`, effort `high`, read-only
- scope: user input, external integration, permissions, path traversal, symlink/hardlink, command injection,
  process group, signal, log/secret exposure, lock, manifest integrity
- report headings exactly `Findings`, `Confidence`, optional `Missing evidence`,
  `Human confirmation required`
- Critical or insufficient confidence requires human confirmation yes
- provider change, file edits, subagent spawn, repository-external reads are forbidden

Run validator `validate` and all-document `read` manually once before invoking the runner, and retain the returned
`INPUT_DIGEST`.

- [ ] **Step 4: Dogfood Terra security review through the new runner**

Run:

```bash
rtk python3 bin/run-codex-review.py --repo . \
  --handoff .superpowers/handoffs/codex-review-runner-security.md \
  --model gpt-5.6-terra --reasoning-effort high --contract security
```

Expected: exit 0 with `COMPLETED`, `COMPLETED_RECOVERED`, or `COMPLETED_RESUMED`; manifest shows
read-only, inherit-unchanged provider policy, complete non-overlapping receipts, and no raw prompt/environment.

If Critical or `Confidence: insufficient`, stop and ask the user before any Sol review. Otherwise fix every validated
High/Medium issue, add a RED regression test, rerun the security review with a new handoff/current digest, and require
`Confidence: sufficient`.

- [ ] **Step 5: Commit security fixes**

Run focused tests and then:

```bash
rtk git status --short
rtk git add bin/codex_review_contracts.py bin/codex_review_runner.py bin/run-codex-review.py tests/test_codex_review_runner.py
rtk git diff --cached --check
rtk git commit -m "fix(codex): review runnerの安全境界を強化"
```

If there are no security fixes, skip this commit rather than creating an empty commit.

- [ ] **Step 6: Create a fresh integration handoff**

security修正後もbaseは`11d451c`に固定し、現在の全差分を新しいfileへ再生成する。

```bash
rtk git diff --binary 11d451c --output=.superpowers/sdd/codex-review-runner/integration-review.diff
rtk shasum -a 256 .superpowers/sdd/codex-review-runner/integration-review.diff
```

The integration handoff must specify
`gpt-5.6-sol` + `high`, all changed implementation/tests/docs, and exact report headings `Strengths`, `Issues` with
Critical / Important / Minor, `Recommendations`, `Assessment`, `Ready to commit`.

- [ ] **Step 7: Dogfood Sol integration review through the new runner**

Run:

```bash
rtk python3 bin/run-codex-review.py --repo . \
  --handoff .superpowers/handoffs/codex-review-runner-integration.md \
  --model gpt-5.6-sol --reasoning-effort high --contract integration
```

Expected: runner exit 0 and report `Ready to commit: Yes`. Fix validated Important issues with RED regression tests.
Minor issues are fixed only when they affect correctness/security or are smaller than the backlog cost; otherwise add
a concrete backlog item. Regenerate the handoff before every new model execution.

- [ ] **Step 8: Run the final full gate**

Run fresh after all review fixes:

```bash
rtk python3 -m unittest discover -s tests -p 'test_*.py' -v
rtk python3 -m py_compile bin/codex_review_contracts.py bin/codex_review_runner.py bin/run-codex-review.py bin/validate-codex-handoff.py
rtk bash -n setup.sh
rtk git diff --check
rtk git status --short --branch
```

Expected: zero test failures, compile/syntax/diff exit 0, only intended files changed.

- [ ] **Step 9: Commit final review fixes and verification record**

Update the ignored `tasks/todo.md` review section with test counts, Terra confidence, Sol assessment, runner states,
and remaining backlog. Commit only tracked implementation/docs/test changes:

```bash
rtk git add .gitignore bin/codex_review_contracts.py bin/codex_review_runner.py bin/run-codex-review.py setup.sh README.md codex/MODEL_ROUTING.md tests/test_codex_review_runner.py tests/test_setup_cli.py tests/test_codex_model_routing.py tests/fixtures/codex-review-runner tasks/backlog.md
rtk git diff --cached --check
rtk git commit -m "feat(codex): review runnerを完成"
```

Do not push or create a PR unless the user asks.
