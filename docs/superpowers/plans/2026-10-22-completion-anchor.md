# 完了条件の固定（completion-anchor）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 作業の始めに完了条件をタスク用ファイルへ固定し、作業中の論点を仕分ける常時rule `rules/completion-anchor.md` を導入する。

**Architecture:** 振る舞いは常時rule 1本に書き、`rules/task-management.md` から参照する。タスク用ファイルは `tasks/todo/<タスク名>.md` に分け、
日本語レビューのフックとignoreを、その置き場所に合わせる。振る舞いは文字列の契約テストで固定し、効き目は手動の代表検証で確かめる。

**Tech Stack:** Markdown（rule）、Python 3 標準ライブラリの `unittest`（テスト）、`bash tests/run.sh`（実行）

**Spec:** `docs/superpowers/specs/2026-10-22-completion-anchor-design.md`、ADR 0039

## Global Constraints

- 新しいruleは `rules/completion-anchor.md`。`paths:` frontmatterを付けない
- ruleは200行未満（公式のCLAUDE.mdの目標値。テストで縛る）。目標は60行前後だが参考にとどめ、効き目を削ってまで縮めない（テストしない）
- タスク用ファイルは `tasks/todo/<タスク名>.md`。タスク名は短いkebab-case
- 3欄の名前は「依頼された結果」「暫定の完了条件」「今回は扱わない論点」
- 仕分けの名前は「① 完了に必要」「② 完了条件が変わる」「③ 関係ない」。作業を止めてユーザーの承認を得るのは②だけ
- ②の記録は「作業中に変わった判断」に「当初 → 変更後 → 理由」の形で、変わったその場で追記する
- ホスト固有のツール名は「Claude Codeでは」と添える（Codexにもリンクされるため）
- Task 1〜3は本体の作業ツリーで行う（`rules/`・`hooks/`・`CLAUDE.md` は本体で作業するパス。ADR 0031）。
  本体に並列セッションがいる間は始めない。始める前に `bin/detect-parallel-sessions` を実行する
- Task 4はdotfilesリポジトリで行う。別のリポジトリなので、そちらのブランチとPRで扱う
- コミットはTDDの段階ごと（RED・GREEN）に分ける。Conventional Commits、日本語

## Review Focus

契約テストは「書いてあること」しか確かめない。次の5つは、文字列があっても振る舞いとして外れうる。Task 5の代表検証で確かめる。

1. すぐ済む明確なタスク（typo修正）でも3欄の確認を挟む（過剰発火）→ 代表検証2
2. 急ぎのタスクで、タスク用ファイルを作らずに作業を始める（未発火）→ 代表検証1
3. 親からパスを渡されていないサブエージェントが、自分でタスク用ファイルを作る → 代表検証1でサブエージェントへの切り出しを依頼する
4. brainstormingが動くタスクで、最初の質問より前にファイルを書き始める → 代表検証3
5. ③の論点まで作業を止めて承認を求める → 代表検証1で範囲外の論点を投げる

**回帰の確認**: 代表検証は1回で終わりにしない。`rules/completion-anchor.md` を直したら、PRを作る前に、Task 5の3本を同じ依頼文で回し直す。
依頼文はTask 5に固定してあるので、回し直す人が作り直さなくて済む（原則レビューの問いP07aを受けて追記）。

---

### Task 1: 日本語レビューのフックで `tasks/todo/` を使い捨てとして扱う

**Files:**
- Modify: `hooks/jp-doc-review.py:125-135`（`_is_disposable`）
- Test: `tests/test_jp_doc_review_hook.py`（`test_disposable_files_are_not_candidates` の近く）

**Interfaces:**
- Consumes: なし
- Produces: `_is_disposable(path: Path) -> bool` が、`tasks/todo/` 直下の `.md` にも `True` を返す

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_task_files_under_todo_dir_are_not_candidates(self):
    self.commit_file("tasks/todo/fix-cert.md", JP_LONG)
    self.assertEqual(self.pr(), (0, {}, ""))

def test_other_files_named_todo_dir_are_still_candidates(self):
    # tasks/ の下でない todo/ は使い捨てではない
    self.commit_file("docs/todo/plan.md", JP_LONG)
    self.assertEqual(decision_of(self.pr()), "deny")
```

- [ ] **Step 2: REDを確かめる**

Run: `python3 -m unittest tests.test_jp_doc_review_hook -k todo -v`
Expected: `test_task_files_under_todo_dir_are_not_candidates` がFAIL（deny が返る）。もう1本はPASS

- [ ] **Step 3: REDをコミットする**（メッセージに失敗したテスト名を書く）

- [ ] **Step 4: `_is_disposable` に条件を足す**

`path.parent.name == "todo" and path.parent.parent.name == "tasks"` のとき `True`。既存の `tasks/todo.md` の条件は残す。

- [ ] **Step 5: GREENを確かめる**

Run: `python3 -m unittest tests.test_jp_doc_review_hook -v`
Expected: 全件PASS

- [ ] **Step 6: GREENをコミットする**

### Task 2: 常時rule `rules/completion-anchor.md` を作る

**Files:**
- Create: `rules/completion-anchor.md`
- Create: `tests/test_completion_anchor_contract.py`

**Interfaces:**
- Consumes: なし
- Produces: `rules/completion-anchor.md`（Task 3が参照する）

- [ ] **Step 1: 失敗する契約テストを書く**

`tests/test_learning_mode_contract.py` の書き方に合わせる。`RULE_PATH = ROOT / "rules" / "completion-anchor.md"`。
ファイルが無いときは `assertTrue(RULE_PATH.is_file())` で、パスを示して失敗させる。

```python
def test_rule_is_always_on_and_under_official_size_target(self):
    # 公式: CLAUDE.md 1ファイル200行未満（https://code.claude.com/docs/en/memory）
    self.assertNotIn("paths:", rule)
    self.assertLess(len(rule.splitlines()), 200)

def test_rule_names_three_fields(self):
    for field in ("依頼された結果", "暫定の完了条件", "今回は扱わない論点"):
        self.assertIn(field, rule)

def test_rule_names_three_sorts_and_stops_only_on_second(self):
    for name in ("完了に必要", "完了条件が変わる", "関係ない"):
        self.assertIn(name, rule)
    self.assertIn("当初 → 変更後 → 理由", rule)

def test_rule_applies_even_when_urgent(self):
    self.assertIn("急ぎ", rule)

def test_rule_places_task_file_and_checks_ignore(self):
    self.assertIn("tasks/todo/", rule)
    self.assertIn("git check-ignore", rule)

def test_rule_passes_absolute_path_to_subagents(self):
    self.assertIn("絶対パス", rule)
    self.assertIn("サブエージェント", rule)

def test_rule_defers_to_brainstorming_design_doc(self):
    self.assertIn("brainstorming", rule)

def test_rule_asks_to_log_parallel_cases(self):
    self.assertIn("並列", rule)
    self.assertIn("tasks/backlog.md", rule)
```

- [ ] **Step 2: REDを確かめる**

Run: `python3 -m unittest tests.test_completion_anchor_contract -v`
Expected: ファイルが無いことを示してFAIL

- [ ] **Step 3: REDをコミットする**

- [ ] **Step 4: ruleを書く**

設計書§4.1〜§4.7と§7の事例欄の指示を、60行前後を目標にまとめる（参考値。超えてもよい）。節立ては作る人に任せる。
入れること: 対象と対象外（§4.1）、急ぎでも外さないこと、3欄と確認（§4.2）、仕分けの表（§4.3）、
サブエージェントへの絶対パスと②の中継（§4.4）、パスを渡されていないサブエージェントは作らないこと（§4.5）、
置き場所と `git check-ignore`（§4.6）、brainstormingの設計書を完了条件の基準にすること（§4.6）、
並列にできた事例を `tasks/backlog.md` の該当項目へ1行追記すること（§7）。

- [ ] **Step 5: GREENを確かめる**

Run: `python3 -m unittest tests.test_completion_anchor_contract -v`
Expected: 全件PASS

- [ ] **Step 6: GREENをコミットする**

### Task 3: 既存の指示とignoreを新しいruleにつなぐ

**Files:**
- Modify: `rules/task-management.md`（「`tasks/` の使い分け」の表と「`todo.md` の運用」）
- Modify: `CLAUDE.md:34-41`（セッション開始時の必須読み込み）
- Modify: `.gitignore:23`
- Modify: `tests/test_instruction_graph.py`（`SESSION_RULES`）
- Test: `tests/test_completion_anchor_contract.py`

**Interfaces:**
- Consumes: Task 2の `rules/completion-anchor.md`
- Produces: なし

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_instruction_graph.py` の `SESSION_RULES` に `"rules/completion-anchor.md"` を足す。
`tests/test_completion_anchor_contract.py` に次を足す。

```python
def test_task_management_drops_single_file_premise(self):
    self.assertNotIn("常に1ファイルで足りる", task_management)
    self.assertIn("rules/completion-anchor.md", task_management)
    self.assertIn("tasks/todo/", task_management)

def test_gitignore_covers_task_files(self):
    self.assertIn("tasks/todo/", gitignore.splitlines())
```

- [ ] **Step 2: REDを確かめる**

Run: `python3 -m unittest tests.test_instruction_graph tests.test_completion_anchor_contract -v`
Expected: 上の3件（`test_routes_to_every_session_rule` を含む）がFAIL

- [ ] **Step 3: REDをコミットする**

- [ ] **Step 4: 3ファイルを直す**

- `rules/task-management.md`: `todo.md` を `tasks/todo/<タスク名>.md` に変える。「複数のタスクを並行しない前提なので、常に1ファイルで足りる」を、
  タスクごとに1ファイル作る運用に書き換える。完了条件と仕分けは `rules/completion-anchor.md` に従う、と参照を足す。既存の `tasks/todo.md` は終わるまで使ってよい、と書く
- `CLAUDE.md`: 必読一覧の末尾に `- \`rules/completion-anchor.md\`` を足す
- `.gitignore`: `tasks/todo.md` の次の行に `tasks/todo/` を足す

- [ ] **Step 5: GREENを確かめる**

Run: `bash tests/run.sh`
Expected: 全件PASS

- [ ] **Step 6: GREENをコミットする**

### Task 4: グローバルなignoreに `tasks/todo/` を足す（dotfilesリポジトリ）

**Files:**
- Modify: dotfilesリポジトリの `config/git/ignore`（`~/.config/git/ignore` のsymlink先）

- [ ] **Step 1: 効いていないことを確かめる**

Run: 任意のGitリポジトリ（このリポジトリ以外）で `git check-ignore -v tasks/todo/x.md`
Expected: 何も出ず、終了コード1

- [ ] **Step 2: dotfilesで最新のmainからブランチを切り、`tasks/todo/` を1行足してコミットする**

- [ ] **Step 3: 効いたことを確かめる**

Run: Step 1と同じコマンド
Expected: `~/.config/git/ignore` の該当行が表示され、終了コード0

### Task 5: backlogに並列化の項目を積み、代表検証を行う

**Files:**
- Modify: `tasks/backlog.md`
- Create（検証後に削除）: 代表検証で作られる `tasks/todo/*.md`

- [ ] **Step 1: backlogに項目を足す**

見出しは「並列化の判定と統合 → 決めること」。設計書§7の4項目（決めること、着手条件、事例欄、材料）を書く。
材料として、引継書（本体の未追跡ファイル `.superpowers/handoffs/parallel-task-orchestration.md`）の§2の事例の表、
§3.4の「賄える部分と賄えない部分」の表、§7の反証条件の未確認項目、§9の未解決事項を写す。業務固有の名前は抽象化する。コミットする

この作業は完了条件の固定そのものには要らない。並列化の判定と統合を、今回の範囲から外す（設計書の非ゴール）ための後始末である。
backlogへ積むことと材料を写すことは、ユーザーが2026-10-22に決めた。引継書は本体の未追跡ファイルなので、写さないと消えたときに調査結果が失われる。

- [ ] **Step 2: PRを作る前に、ユーザーへ代表検証を依頼する**（設計書§6、手動）

本体のブランチに入った状態で、ユーザーが新しいセッションを開き、次の依頼文を投げて結果を伝える。
手動にしたのはユーザーの決定である（2026-10-22）。`claude -p` のheadless実行やサブエージェントでは `AskUserQuestion` に答えられず、
完了条件の確認と②の承認の場面を再現できない。そのため、自動化は採らなかった。

1. 「急ぎで、このリポジトリの `hooks/` のどれかに既知の弱点が無いか調べて、報告資料にまとめたい。調査はサブエージェントに任せて」。
   途中で範囲外の論点（例: 「ついでに `tests/` の遅さも見て」）を投げる。
   確かめること: 作業前に `tasks/todo/<タスク名>.md` と3欄が作られ、確認を求められる。範囲外の論点が③として退避され、作業が止まらない。
   サブエージェントのプロンプトに絶対パスが入り、サブエージェント自身はタスク用ファイルを作らない
2. 「`README.md` のtypoを1つ直して」。確かめること: 3欄の確認が挟まらない
3. 「新しいskillを作りたい」（brainstormingが動く依頼）。確かめること: 最初の応答が質問1つで、その前にタスク用ファイルを書かない

- [ ] **Step 3: 結果をこの計画のレビュー欄に書く。外れた項目があれば、ruleを直してTask 2のテストを回し直す**

## レビュー

2026-10-23、本体を `feat/completion-anchor`（main を取り込んだ後の状態）にして、ユーザーが3本を手動で流した。
結果は、各セッションの会話ログと本体の `tasks/todo/` を読んで確かめた。

1. 急ぎの調査（Review Focus 2・3・5）: 合格
   - 作業前に `tasks/todo/hooks-weakness-report.md` を作り（先に `git check-ignore` で追跡対象外かを確かめた）、範囲と形式を `AskUserQuestion` で確認した
   - サブエージェント2本の両方に絶対パスを渡し、完了条件を変える論点は親へ返すよう指示した。サブエージェントはタスク用ファイルを作っていない
   - 「ついでに `tests/` の遅さも見て」は、計画では③を期待していたが、②（完了条件を広げる）として扱われた。
     ユーザー本人の依頼なので承認済みとし、作業は止めず、「当初 → 変更後 → 理由」をその場で追記した。
     本人がはっきり頼んだ追加を③で退けるのは依頼に反するので、外れたのは計画の期待の方だと判断した。
     ただ、広げた後の完了条件（tests/ の結果を資料に載せるか）は確かめずに後回しにし、完了時に聞いていた
   - 完了時に、③の論点を backlog に移すかを提案した
2. typo修正（Review Focus 1）: 合格。タスク用ファイルを作らず、確認も挟まなかった
3. brainstorming（Review Focus 4）: 合格（確かめた範囲は最初の質問まで）。brainstorming が先に動き、最初の応答は質問1つで、その前にタスク用ファイルを書いていない。
   設計書ができた後にそれを完了条件の基準にするかは、設計書まで進めていないので**未確認**

検証の途中で、rule の見出しの比喩「錨」を「完了条件の固定」に直し、ADR の番号を 0039 に付け直した（代表検証2が番号の重複を見つけた）。
見出しと設計書の節の文言だけの変更で、振る舞いの指示は変えていない。そのため、3本は回し直していない。
