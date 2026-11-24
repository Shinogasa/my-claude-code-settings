# ステータスライン3段化 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `statusline.js` を3段に固定し、新しい項目（キャッシュ・PR・spend limit）を足し、`COLUMNS` に合わせて1段目と3段目を縮める。

**Architecture:** 各段を「セグメント（`{ id, text }` か、名前を持つ `{ id, name, render(name) }`）の配列」として組み立て、最後に `fitRow` で幅に合わせてから連結する。段の割り当ては固定で、縮める処理は段ごとに決まった順で行う。

**Tech Stack:** Node.js（依存パッケージなし）、テストは Python unittest からサブプロセスで実行。

**Spec:** `docs/superpowers/specs/2026-11-24-statusline-layout-design.md`

## Global Constraints

- 3段に固定する。1段目・3段目の項目は別の段へ移さない。2段目は縮めず、端末の折り返しに任せる
- 幅は `COLUMNS` から読む。無い、または正の整数でなければ縮めない
- 表示幅は ANSI を除き、絵文字と全角文字を2桁で数える
- 3段目の落とす順: 時刻 → 経過時間 → 変更行数 → トークン数。コストと output style は落とさない
- 1段目の省略順: セッション名 → ブランチ名 → worktree名。中央を `…` で省略し、各名前は8文字までは残す。リポジトリ名は省略しない
- 色のしきい値は 70% で警告色、90% で危険色
- 時刻系フィールド（`expires_at`、`resets_at`）は Unix epoch 秒
- `statusline.js` は本体のシンボリックリンク先なので、保存した瞬間に実行中のステータスラインへ効く。
  表示が壊れたら `git checkout HEAD -- statusline.js` で直前のコミットへ戻す。RED のコミットはテストだけを変えるので、
  直前のコミットの `statusline.js` は常に動く
- TDD の段階ごとにコミットする（RED で1回、GREEN で1回。メッセージに段階と、失敗・成功したテスト名を書く）

## Review Focus

1. `COLUMNS` が無い・`abc`・`0` → 縮めずに全項目を出す（Task 3 でテスト）
2. 極端に狭い幅（`COLUMNS=20`）→ 落ちずに3段を出し、リポジトリ名は完全な形で残る（Task 3）
3. `prompt_cache.warm` が true でも `expires_at` が過去 → 冷えた表示にする（Task 2）
4. `prompt_cache.hit_ratio` が null、`expires_at` が null → その部分だけ出さず、落ちない（Task 2）
5. セッション名が日本語 → 全角2桁で数えて省略する。文字の途中で切らない（Task 3）

---

### Task 0: `COLUMNS` が実際に届くかを確かめる

幅への追従はこの前提の上に立つので、実装の前に確かめる。

- [ ] **Step 1:** `statusline.js` の入力処理の先頭に、一時的に
  `fs.writeFileSync(path.join(os.homedir(), '.claude', 'cache', 'statusline-columns.log'), String(process.env.COLUMNS))` を足す（コミットしない）
- [ ] **Step 2:** 次の応答で再描画されたら、ログを読む / Expected: 正の整数。`undefined` なら spec の前提が崩れているので、利用者に報告して止まる
- [ ] **Step 3:** 足した行を `git checkout HEAD -- statusline.js` で消し、ログファイルも消す。結果を `tasks/todo/statusline-layout.md` に1行書く

### Task 1: 3段への組み替えとブランチ名の重複除去

**Files:**
- Modify: `statusline.js`（`buildStatusLines`、`buildEnvLine`、`buildUsageLine` を3つの段の関数に置き換える）
- Test: `tests/test_statusline.py`

**Interfaces:**
- Produces: `buildRepoRow(data) -> Segment[]`、`buildBudgetRow(data) -> Promise<Segment[]>`、`buildMetricsRow(data) -> Segment[]`。
  `Segment` は `{ id: string, text: string }` または `{ id: string, name: string, render: (name: string) => string }`。
  `id` は Task 3 が使う: 1段目 `repo` `worktree` `branch` `pr` `session` `agent`、3段目 `tokens` `cost` `lines` `duration` `style` `time`
- `getGitInfo` は文字列ではなく `{ branch, dirty }` を返すように変える（ブランチ名を `name` として省略できるようにするため）

段の中身（spec の「段の割り当て」どおり）:
- 1段目: 📁 リポジトリ、🌲 worktree、⎇ ブランチ + dirty、PR（Task 2）、📌 セッション、🤝 エージェント
- 2段目: 🤖 モデル[effort 🧠]、プロファイル、💳 または 📊 5h/7d、コンテキストのバー、キャッシュ（Task 2）
- 3段目: 🪙 トークン、💰 コスト、+/- 行数、⏱ 経過時間、🎨 output style、🕐 時刻

- [ ] **Step 1: テストの土台を直す**
  `run_statusline(data, env=None)` に追加の環境変数を受け取らせ、継承した環境から `COLUMNS` と `LINES` を除く。戻り値は今のまま（1段目と git 呼び出し）。`self.lines` に全段が入る
- [ ] **Step 2: 失敗するテストを書く**

```python
def test_3段に分かれ各段に決まった項目が出る(self):
    self.run_statusline({
        "cwd": str(self.repo), "workspace": self.workspace(self.repo),
        "model": {"display_name": "Opus"},
        "context_window": {"used_percentage": 40, "total_input_tokens": 1000, "total_output_tokens": 10},
        "cost": {"total_cost_usd": 0.5, "total_duration_ms": 61000},
    })
    self.assertEqual(len(self.lines), 3)
    self.assertIn("📁 origin_repo", self.lines[0])
    self.assertIn("⎇ main", self.lines[0])
    self.assertIn("🤖 Opus", self.lines[1])
    self.assertIn("🏠PERSONAL", self.lines[1])
    self.assertIn("40%", self.lines[1])
    self.assertIn("🪙", self.lines[2])
    self.assertIn("💰", self.lines[2])
    self.assertIn("⏱", self.lines[2])
    self.assertIn("🕐", self.lines[2])

def test_ブランチ名がworktree名由来なら名前を二度出さない(self):
    # setUp とは別に worktree-wt2 ブランチの worktree を作る
    wt = self.repo / ".claude" / "worktrees" / "wt2"
    git(self.repo, "worktree", "add", "-q", "-b", "worktree-wt2", str(wt))
    line, _ = self.run_statusline({"cwd": str(wt), "workspace": self.workspace(wt, git_worktree="wt2")})
    self.assertIn("🌲 wt2", line)
    self.assertNotIn("worktree-wt2", line)
    self.assertIn("⎇", line)
```

- [ ] **Step 3: 実行して失敗を確かめ、RED でコミット**
  Run: `python3 tests/test_statusline.py -v` / Expected: 上の2件が FAIL（段数が2、`worktree-wt2` が出る）。既存の6件は PASS
- [ ] **Step 4: 3段の関数を実装する**
  ブランチ名が `worktree-${worktree名}` と一致したら、⎇ の後ろはブランチ名を出さず dirty 表示だけにする
- [ ] **Step 5: 全テストが通ることを確かめ、GREEN でコミット**
  Run: `python3 tests/test_statusline.py -v` / Expected: 全件 PASS

### Task 2: キャッシュ・PR・spend limit を出す

**Files:**
- Modify: `statusline.js`（`formatCache(pc, nowSec)`、`formatPr(pr)`、`formatSpendLimit(sl)` を足し、各段へ入れる）
- Test: `tests/test_statusline.py`

**Interfaces:**
- Consumes: Task 1 の `buildRepoRow`（PR を `id: 'pr'` で ⎇ の直後に入れる）、`buildBudgetRow`（キャッシュを最後、spend limit をバジェットの直後に入れる）

表示の形（決めた値）:
- キャッシュ: 温かい `🔥cache 4m (hit 92%)`、冷えた `🧊cache cold (hit 92%)`。残り分は `Math.ceil((expires_at - now) / 60)`。
  `warm` が false、`expires_at` が null、または `expires_at <= now` なら冷えた表示。`hit_ratio` が null なら `(hit …)` を省く。`prompt_cache` が無ければ何も出さない
- PR: `#1234 approved`。`pr.kind === 'mr'` なら `!1234`。`review_state` が無ければ番号だけ。`pr` が無ければ何も出さない
- spend limit: `💸 63%`、`used_usd` と `limit_usd` があれば `💸 63% $314/$500`。色は 70% / 90%

- [ ] **Step 1: 失敗するテストを書く**
  `test_温かいキャッシュは残り分とヒット率を出す`（`expires_at = now+240`、`hit_ratio 0.92` → 2段目に `🔥cache 4m (hit 92%)`）、
  `test_期限切れのキャッシュは冷えた表示にする`（`warm: True`、`expires_at = now-10` → `🧊cache cold`）、
  `test_ヒット率とexpires_atがnullでも落ちない`（`warm: False`、両方 null → `🧊cache cold` を含み `hit` を含まない）、
  `test_PR番号とレビュー状態を1段目に出す`（`{"number": 1234, "review_state": "approved"}` → `#1234 approved`）、
  `test_spend_limitを2段目に出す`（`used_percentage 62.8, used_usd 314.12, limit_usd 500` → `💸 63% $314/$500`）
- [ ] **Step 2: 実行して失敗を確かめ、RED でコミット** / Expected: 新しい5件が FAIL
- [ ] **Step 3: 3つの整形関数を実装し、段へ入れる**
- [ ] **Step 4: 全テストが通ることを確かめ、GREEN でコミット** / Run: `python3 tests/test_statusline.py -v`

### Task 3: 幅に合わせて1段目と3段目を縮める

**Files:**
- Modify: `statusline.js`（`displayWidth`、`truncateMiddle`、`fitRow` を足し、`buildStatusLines` で1段目と3段目に適用する）
- Test: `tests/test_statusline.py`

**Interfaces:**
- Consumes: Task 1 の `Segment` と `id`
- Produces:
  - `displayWidth(s: string) -> number`: ANSI を除き、`\p{Extended_Pictographic}` と全角（CJK、ひらがな、カタカナ、全角記号）を2、異体字セレクタ（U+FE0F）とゼロ幅結合子を0、それ以外を1で数える
  - `truncateMiddle(name: string, maxWidth: number) -> string`: 前後を残し、中央を `…` にする。8文字未満にはしない。コードポイント単位で切る
  - `fitRow(segments: Segment[], columns: number|null, plan: { drop?: string[], shrink?: string[] }) -> string`:
    幅を超えている間、`drop` の順にセグメントを落とし、次に `shrink` の順に名前を超過分だけ（最小8文字まで）縮める。`columns` が null なら全部連結するだけ
- `COLUMNS` の解釈: `parseInt` して正の整数なら使い、それ以外は null

- [ ] **Step 1: 失敗するテストを書く**（すべて `env={"COLUMNS": ...}` を渡す）
  - `test_3段目は幅が足りないと時刻から落とす`: 3段目の全項目を出す入力で、3段目の幅から時刻の分だけ削った `COLUMNS` → `🕐` が無く `⏱` と `💰` がある
  - `test_3段目を極端に縮めてもコストは残る`: `COLUMNS=20` → 3段目に `💰` があり `🪙` `+` `⏱` `🕐` が無い
  - `test_1段目はセッション名から中央省略しリポジトリ名は残す`: 長いセッション名と worktree 名で `COLUMNS=60` → `📁 origin_repo ` を含み、セッション名に `…` が入り、1段目の表示幅が60以下
  - `test_日本語のセッション名は全角2桁で数えて省略する`: `session_name` に日本語30文字、`COLUMNS=50` → `…` を含み、
    残ったセッション名の文字数が、手で数えた期待値と一致する。期待値は実装と同じ関数で計算せず、テストに固定値で書く
  - `test_2段目は狭くても縮めない`: `COLUMNS=20` → 2段目に、モデル・プロファイル・バー・キャッシュがすべて残る
  - 幅の期待値はすべて手で数えた固定値にする。それでも、端末が絵文字を実際に何桁で描くかはテストでは確かめられない。Task 4 の目視で見る
  - `test_COLUMNSが無いか不正なら縮めない`: `None`、`"abc"`、`"0"` のそれぞれで、3段目に `🕐` が残る
  - `test_極端に狭くても落ちずにリポジトリ名を出す`: `COLUMNS=20`、長い worktree 名 → 3段出て、`origin_repo` が完全な形で含まれる
- [ ] **Step 2: 実行して失敗を確かめ、RED でコミット** / Expected: 「COLUMNSが無いか不正なら縮めない」と「2段目は狭くても縮めない」以外の5件が FAIL
- [ ] **Step 3: `displayWidth`・`truncateMiddle`・`fitRow` を実装し、1段目に `{ shrink: ['session', 'branch', 'worktree'] }`、3段目に `{ drop: ['time', 'duration', 'lines', 'tokens'] }` で適用する**
- [ ] **Step 4: 全テストが通ることを確かめ、GREEN でコミット** / Run: `python3 tests/test_statusline.py -v`

### Task 4: 実セッションで確かめる

**Files:** なし（必要なら `tasks/todo/statusline-layout.md` に結果を書く）

- [ ] **Step 1: 実データで描画を確かめる**
  Run: 実セッションで取った形の JSON（`prompt_cache`、`pr` を含む）を `COLUMNS=200` と `COLUMNS=60` で `node statusline.js` に流す / Expected: 3段、60では3段目の時刻が落ち、1段目が60桁に収まる
- [ ] **Step 2: 実際の端末での見た目を確かめる**
  実セッションで3段の表示を見てもらい、絵文字の幅のずれで段がはみ出していないかを確かめる（テストでは確かめられない部分）
- [ ] **Step 3: 全テストと worktree での表示を確かめる** / Run: `python3 tests/test_statusline.py -v` / Expected: 全件 PASS
