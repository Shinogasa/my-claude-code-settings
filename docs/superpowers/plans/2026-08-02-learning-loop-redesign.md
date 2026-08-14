# 学習ループ再設計 Implementation Plan

> **⚠ 実装済み。ただし一部は 2026-08-14 に置き換えられた。当時の記録として残している。**
> 現行仕様は `rules/learning-mode.md`、変更の理由は
> `docs/adr/0001-learning-mode-prediction-format.md` を参照。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `learning-mode` と `protege-output` の2機構を、★ Predict / ★ Delta の単一ループに統合し、実際に発火して蓄積される状態にする。

**Architecture:** 「答えを開示する前に予測させ、差分を返す」ループに一本化する。停止は散文の指示ではなく `AskUserQuestion` ツールの呼び出しで機構的に担保し、発火回数に下限（1タスク1回）を設ける。学習ログの実体をPRIVATEな作業環境リポジトリから本リポジトリへ移し、symlink 集約機構を撤去する。

**Tech Stack:** Markdown（rules / CLAUDE.md / output-styles）、Bash（setup.sh）

**設計書:** `docs/superpowers/specs/2026-08-02-learning-loop-redesign-design.md`

## Global Constraints

- **このリポジトリは PUBLIC**（`github.com/Shinogasa/my-claude-code-settings`）。journal に社名・組織名・プロジェクト名・リポジトリ名・内部ホスト名・内部URL・テーブル名・内部パス・業務コードを書かない。
- 日本語で記述する（ドキュメント・コメント・コミットメッセージ）。
- `TODO(human)` は `learning-output-style` プラグインが管理する**別機構**。`output-styles/review-and-design.md:105` の言及は**残す**。今回の削除対象ではない。
- PRIVATEな作業環境リポジトリ側のファイルは**一切変更しない**（読み取りのみ）。後始末は実装完了後に引継書で委譲する。
- コミットメッセージは Conventional Commits 形式。末尾に `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` を付ける。

---

## File Structure

| ファイル | 責務 | 変更 |
|---|---|---|
| `rules/learning-mode.md` | ★ Predict / ★ Delta ループの唯一の仕様 | 全面書き直し |
| `rules/protege-output.md` | （廃止） | 削除 |
| `rules/task-management.md` | タスク管理手順 | 7項目目のみ修正 |
| `CLAUDE.md` | 全体方針。詳細は rules に委譲 | 学習モード節と学習アウトプット行 |
| `output-styles/review-and-design.md` | 出力ブロックの出し分け | Protégé 参照1行 |
| `setup.sh` | symlink 配置 | journal 集約ブロック削除 |
| `.gitignore` | 追跡除外 | journal の行を削除 |
| `tasks/learning-journal.md` | 学習ログ実体 | 新規作成 |
| `README.md` | リポジトリ説明 | 管理対象外リスト＋集約節 |

---

### Task 1: ルール本体の刷新と全参照の更新

**Files:**
- Rewrite: `rules/learning-mode.md`
- Delete: `rules/protege-output.md`
- Modify: `rules/task-management.md:13`
- Modify: `CLAUDE.md:28-33`, `CLAUDE.md:43`
- Modify: `output-styles/review-and-design.md:106`

**Interfaces:**
- Produces: `★ Predict` / `★ Delta` という用語、`tasks/learning-journal.md` への記録契約（Task 2・3 が依存する）

- [ ] **Step 1: `rules/learning-mode.md` を全面書き直し**

以下で全置換する。

````markdown
---
alwaysApply: true
---

# 学習モード（★ Predict / ★ Delta）

## 基本方針

答えを先に渡さない。**答えを開示する前に予測させ、予測と実際の差分を返す**。
差分フィードバックがこの機構の本体であり、予測を取ること自体が目的ではない。

## ループ

```
[1] 予測フェーズ  最重要判断点で、答えを出す前に AskUserQuestion で予測を求める
[2] 開示フェーズ  こちらの答え・調査結果・実装方針を提示する
[3] 差分フェーズ  ★ Delta で予測と実際の差分を返す
```

**順序が本質。** 開示してから問うと再読になり、事前に予測させる効果が消える。

## 対象領域

| 領域 | 予測フェーズの問い |
|---|---|
| 設計判断 | 「A案とB案、どちらを選ぶ？」 |
| 原因分析 | 「調査結果はこれ。どのレイヤーが原因だと思う？」 |
| レビュー力 | 「この変更で最初に壊れるのはどこだと思う？」 |
| 実装方針 | 「この関数、どういう方針で実装する？1行で」 |

## 発火規則

- **下限: 1タスクにつき最低1回（必須）。** タスク終了前に一度も発火していなければ、完了報告の前に必ず1回入れる
- **上限: 2回**（テンポを殺さない）
- **発火点**: そのタスクで最も「後から変えるのが高くつく判断」を1つ選ぶ

## 停止は AskUserQuestion で行う

予測を求めるときは、散文で「停止する」と書くのではなく **`AskUserQuestion` ツールを呼ぶ**。
このツールは応答があるまで戻らないため、停止が構造的に担保される。

- 選択肢は2〜4個。自由記述は自動付与される「Other」で受ける
- 選択肢には互いに排他的な立場を置く（「どちらとも言える」を選ばせない）
- 推奨案がある場合は先頭に置き、ラベル末尾に「（推奨）」を付ける

**上書き宣言**: `AskUserQuestion` の既定ガイダンスは「ユーザーが決めるべき判断にのみ使え」と用途を制限しているが、
学習モードの予測フェーズにおける教育目的の使用を明示的に許可する。この指示が同ツールの既定ガイダンスに優先する。

## ★ Delta の返し方

```
★ Delta ───────────────────────────────────────
予測: [ユーザーの予測]
実際: [実際の判断・原因・リスク]
差分: [下表に従う]
─────────────────────────────────────────────────
```

| 予測の結果 | 返し方 |
|---|---|
| 一致 | 一致を認めた上で、**予測に含まれていなかった観点**を1つ名指しする |
| 部分一致 | 欠けていた観点 ＋ **それが実務でどう事故るか**の具体例 |
| 不一致 | 正解を直接言わず、**その予測が破綻する反例**を1つ出す |

**禁止**: 「その通り」「正解」だけで終えること。一致時も必ず一段深い観点を1つ足す。
差分フィードバックがこの機構の本体であり、ここを省くと機構全体が無意味になる。

## 合理化防止

以下を考えたら、それは回避の兆候である。

| 思考 | 現実 |
|---|---|
| 「今回は自明だから不要」 | 自明なら選択肢を2つ書けないはず。書けるなら問える |
| 「急いでいそうだから省く」 | OFFは明示指示のみ。推測で省くな |
| 「もう説明したから予測は不要」 | 説明後の質問は再読であって想起ではない。説明の**前**に問え |
| 「後でまとめて聞く」 | 開示後の予測は事前予測にならない。順序が本質 |
| 「タスクが小さすぎる」 | 小さいタスクほど判断点は1つに絞りやすい |
| 「調べ物だから対象外」 | 調査こそ原因分析の予測が効く場面 |

## OFF条件

明示指示のみ: 「全部やって」「任せる」「急ぎ」「予測なしで」
1タスク完了後は自動的に ON に戻る。

**「実装して」は OFF 条件ではない**（コーディング依頼のほぼ全てに含まれる語であり、誤 OFF の主因だったため除外した）。

## 記録

★ Delta を返したら `tasks/learning-journal.md` の**末尾**に追記する。

- 日付昇順を維持する（先頭に挿入しない）
- 見出しは `## [YYYY-MM-DD] | タスク概要` 形式に統一する
- 予測を外した回は見出し末尾に `[MISS]` を付ける（将来の優先再出題用）
- **追記時に journal 冒頭の検証チェックポイントを必ず確認する**

### 抽象化ルール（セキュリティ要件）

このリポジトリは **PUBLIC**。journal への書き込み前に必ず以下を満たすこと。

**禁止**
- 社名・組織名・プロジェクト名・リポジトリ名
- 内部ホスト名・内部URL・エンドポイント
- テーブル名・カラム名・内部ファイルパス
- 業務コードの直貼り

**必須**
- 技術的本質のみを一般化して書く。具体例は最小再現形に置き換える
- 判断に迷ったら書かない
````

- [ ] **Step 2: `rules/protege-output.md` を削除**

```bash
git rm rules/protege-output.md
```

- [ ] **Step 3: `rules/task-management.md:13` を修正**

置換前:
```markdown
7. **理解を言語化する**: ★ Protégé の回答を `tasks/learning-journal.md` に記録する（ユーザー側の学びの言語化）
```

置換後:
```markdown
7. **理解を言語化する**: ★ Predict の予測と ★ Delta の差分を `tasks/learning-journal.md` に記録する（ユーザー側の学びの言語化）
```

- [ ] **Step 4: `CLAUDE.md:28-33` の学習モード節を修正**

置換前:
```markdown
## 学習モード

- デフォルト: **ON**（常に学習機会を探す）
- 「全部やって」「任せる」「急ぎ」「実装して」→ **OFF**（そのタスク中のみ）
- 1タスク完了後は自動的にONに戻る
- 詳細仕様は `rules/learning-mode.md` を参照
```

置換後:
```markdown
## 学習モード

- デフォルト: **ON**（常に学習機会を探す）
- **1タスクにつき最低1回、★ Predict（予測フェーズ）を必ず発火させる**（上限2回）
- 予測は `AskUserQuestion` ツールで求める（散文で「停止する」と書かない）
- 「全部やって」「任せる」「急ぎ」「予測なしで」→ **OFF**（そのタスク中のみ）
- 1タスク完了後は自動的にONに戻る
- 詳細仕様は `rules/learning-mode.md` を参照
```

- [ ] **Step 5: `CLAUDE.md:43` の学習アウトプット行を修正**

置換前:
```markdown
- **学習アウトプット**: タスク完了時、学習要素があれば ★ Protégé で問いかけ、`tasks/learning-journal.md` に記録する（実体はPRIVATEな作業環境リポジトリに集約された symlink。詳細は README「learning-journal.md の集約」参照）
```

置換後:
```markdown
- **学習アウトプット**: ★ Delta を返したら `tasks/learning-journal.md` の末尾に追記する。このリポジトリは PUBLIC のため、業務固有情報を抽象化してから書く（`rules/learning-mode.md` の抽象化ルール参照）
```

- [ ] **Step 6: `output-styles/review-and-design.md:106` を修正**

置換前:
```markdown
- ★ Protégé（rules/protege-output.md）が発動する場合、質問プロンプトは省略する
```

置換後:
```markdown
- ★ Predict / ★ Delta（rules/learning-mode.md）が発動する場合、質問プロンプトは省略する
```

- [ ] **Step 7: 参照切れが無いことを検証**

Run:
```bash
grep -rn "protege\|Protégé" . --exclude-dir=.git --exclude-dir=docs --exclude-dir=claude-code-best-practice
```
Expected: **0件**（終了コード1、出力なし）

出力があれば、そのファイルも Step 3〜6 と同様に修正してから再実行する。

- [ ] **Step 8: コミット**

```bash
git add -A rules/ CLAUDE.md output-styles/
git commit -F - <<'EOF'
feat: 学習モードを ★ Predict / ★ Delta の単一ループに統合

learning-mode と protege-output が発火しない・浅いという問題に対し、
「開示前に予測させ、差分を返す」1機構へ統合した。

- 停止を AskUserQuestion 呼び出しで構造的に担保（散文の指示は上位指示に負けるため）
- 発火回数に下限（1タスク1回）を設定。従来は上限のみで0回が合法だった
- 差分フィードバックを必須化し「その通り」で終えるのを禁止
- OFFトリガーから「実装して」を除去（誤OFFの主因）
- rules/protege-output.md を削除し、参照元4ファイルを更新

設計書: docs/superpowers/specs/2026-08-02-learning-loop-redesign-design.md

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 2: journal インフラの切り替え

**Files:**
- Modify: `.gitignore:8-10`
- Modify: `setup.sh:193-237`（ブロック削除）
- Create: `tasks/learning-journal.md`（ヘッダのみ。エントリは Task 3）
- Modify: `README.md:156-186`

**Interfaces:**
- Consumes: Task 1 が定義した記録契約（末尾追記・日付昇順・`[MISS]` タグ・抽象化ルール）
- Produces: `tasks/learning-journal.md` が git 追跡下に存在する状態（Task 3 が追記する）

- [ ] **Step 1: 既存 symlink が残っていれば除去**

`setup.sh` を実行済みの環境では symlink が張られている可能性がある。実ファイルを作る前に確認する。

Run:
```bash
ls -la tasks/learning-journal.md 2>/dev/null || echo "存在しない（正常）"
```
symlink（`->` 表示）だった場合のみ `rm tasks/learning-journal.md` で除去する。実ファイルだった場合は中身を確認し、勝手に消さずユーザーに報告する。

- [ ] **Step 2: `.gitignore` から journal の除外を削除**

置換前（8-10行目、直前の空行含む）:
```
# learning-journal.md は業務ナレッジを含み、実体はPRIVATEな作業環境リポジトリ側に集約する。
# 本リポジトリは PUBLIC のため追跡しない (setup.sh が実体への symlink を張る)。
tasks/learning-journal.md
```

置換後: **上記3行を削除する**（前後の空行を1行に整える）。`tasks/todo.md` の除外はそのまま残す。

- [ ] **Step 3: `setup.sh` から journal 集約ブロックを削除**

`setup.sh` の 193〜237行目を削除する。範囲は以下の通り。

削除開始（193行目）:
```bash
# === learning-journal.md を PRIVATE 実体へ symlink 集約 ===
```

削除終了（236行目 + 直後の空行237行目）:
```bash
consolidate_learning_journal
```

削除後、191行目 `fi` の次が空行、その次が `echo ""` / `echo "=== 完了 ==="` となること。

**注意**: `backup_created` 変数は51行目で定義され77-79・104-106行でも使われているため、この削除で孤児参照は発生しない（確認済み）。

- [ ] **Step 4: `tasks/learning-journal.md` を新規作成**

```markdown
# Learning Journal

★ Predict（予測）と ★ Delta（差分）の記録。仕様は `rules/learning-mode.md` を参照。

<!-- ============================================================
     検証チェックポイント（このファイルに追記するたびに確認すること）

     判定: 2026-08-02 の再設計以降のエントリが3件に達しているか。
     　　  （移行してきた 2026-08-02 より前のエントリは対象外）

     達していれば: 発火下限（1タスク1回）が機能している。この判定を
     　　  「エントリ20件で段階2（SessionStart hook による間隔反復出題）を
     　　  検討する」に更新する。

     達していなければ: この再設計は失敗している。散文と AskUserQuestion
     　　  だけでは発火を担保できていないため、SessionStart hook による
     　　  強制注入（段階2の前倒し）を検討する。
     ============================================================ -->

> **⚠ このリポジトリは PUBLIC**
> 社名・組織名・プロジェクト名・リポジトリ名・内部ホスト名・内部URL・
> テーブル名・内部パス・業務コードを書かないこと。
> 技術的本質のみを一般化して記録する。判断に迷ったら書かない。
> 詳細は `rules/learning-mode.md` の「抽象化ルール」を参照。

## 記録フォーマット

```
## [YYYY-MM-DD] | タスク概要 [MISS]

**判断点:** 何を判断する場面だったか

**予測:** ユーザーの予測をそのまま記録

**実際:** 実際の判断・原因・リスク

**差分:** ★ Delta で返した内容
```

- 末尾に追記する（日付昇順を維持し、先頭に挿入しない）
- 予測を外した回は見出し末尾に `[MISS]` を付ける

---

## 記録
```

- [ ] **Step 5: `README.md:156-163` の管理対象外リストから journal を削除**

削除する行:
```markdown
- `tasks/learning-journal.md` — 学習ログ（後述の理由で symlink 集約 + 非追跡）
```

- [ ] **Step 6: `README.md` の「learning-journal.md の集約」節を書き換え**

165行目から始まる `## learning-journal.md の集約` 節（ASCII図と箇条書きを含む、次の `##` 見出しの直前まで）を、以下で全置換する。

```markdown
## learning-journal.md の運用

学習ログ（★ Predict / ★ Delta の記録）の実体は **このリポジトリの `tasks/learning-journal.md`** に置き、git で追跡する。

- **なぜこのリポジトリに置くか**: マシン間で同期され、バックアップされ、後から振り返れる。
  以前は業務用の PRIVATE リポジトリに実体を集約し symlink で参照していたが、
  個人の学習ログを業務用リポジトリに同居させる構成が適切でないため 2026-08-02 に移行した。
  これに伴い `setup.sh` の symlink 集約機構は撤去した。
- **PUBLIC であることの制約**: このリポジトリは PUBLIC のため、社名・プロジェクト名・
  リポジトリ名・内部パス・業務コードを書かない。技術的本質のみを一般化して記録する
  （`rules/learning-mode.md` の抽象化ルール）。抽象化の強制はセキュリティ要件であると同時に、
  本質だけを取り出して言語化する訓練としても機能する。
- **移行前のアーカイブ**: 2026-08-02 以前の詳細版（業務固有情報を含む）は
  移行元の PRIVATE リポジトリにアーカイブとして残しており、以降そちらには追記しない。
```

- [ ] **Step 7: setup.sh を2回連続実行して冪等性を検証**

Run:
```bash
bash setup.sh && echo "--- 2回目 ---" && bash setup.sh
```
Expected:
- 両回とも終了コード0
- `learning-journal.md 集約` セクションが**出力されないこと**
- 2回目に「新規作成」ではなく「リンク済み」相当の出力になること（既存 TARGETS の冪等性）

- [ ] **Step 8: journal が追跡対象になったことを検証**

Run:
```bash
git status --short tasks/learning-journal.md && git check-ignore -v tasks/learning-journal.md; echo "exit=$?"
```
Expected:
- `git status` に `?? tasks/learning-journal.md` が表示される
- `git check-ignore` は**何も出力せず** `exit=1`（＝無視されていない）

- [ ] **Step 9: コミット**

```bash
git add -A .gitignore setup.sh tasks/learning-journal.md README.md
git commit -F - <<'EOF'
feat: learning-journal の実体を本リポジトリへ移し symlink 集約を撤去

学習ログを PRIVATE の業務用リポジトリに集約する
構成をやめ、本リポジトリで追跡する方式へ変更した。

- .gitignore から tasks/learning-journal.md を除外解除
- setup.sh の symlink 集約ブロック (193-237行) を削除し外部リポジトリ依存を解消
- tasks/learning-journal.md を新規作成。冒頭に検証チェックポイントと
  PUBLIC 向け抽象化ルールの警告を配置
- README の該当節を「集約」から「運用」へ書き換え

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 3: 既存11エントリの抽象化移行

**Files:**
- Read only: 移行元 PRIVATE リポジトリの `tasks/learning-journal.md`
- Modify: `tasks/learning-journal.md`（Task 2 で作成したファイルに追記）

**Interfaces:**
- Consumes: Task 2 が作成した journal ヘッダと記録フォーマット

**このタスクは PUBLIC リポジトリへの公開を伴う。Step 5 のユーザーレビューを飛ばしてコミットしてはならない。**

- [ ] **Step 1: 原本を全文読む**

Run:
```bash
cat <移行元PRIVATEリポジトリのパス>/tasks/learning-journal.md
```

11エントリ（143行、2026-04-17〜2026-07-01）。原本は**変更しない**。

- [ ] **Step 2: 抽象化しながら書き換える**

各エントリに対し、以下を適用する。

| 原本の要素 | 対応 |
|---|---|
| 業務リポジトリ名 | 役割で言い換える（例:「負荷試験スクリプトのリポジトリ」「エージェント作業用ワークスペース」） |
| 業務システム固有の構成・エンドポイント・パラメータ名 | 一般化するか削除する |
| 内部ファイルパス | 相対的な役割で表現する（例:「設定オブジェクト」） |
| 一般的技術トピック（分散DBの基礎、Kotlin の `by lazy`、モックテストの観点、CDN のキャッシュ挙動 等） | **そのまま残してよい** |
| 移行元リポジトリ / 本リポジトリへの言及 | 本リポジトリ自身への言及（`my-claude-code-settings`）は残してよい。移行元は「PRIVATE な作業環境リポジトリ」と表現する |

判断に迷う要素は**削除する**（残す方に倒さない）。

- [ ] **Step 3: 日付昇順に並べ替え、見出しフォーマットを統一**

原本には以下の乱れがある。修正すること。

- `2026-07-01` のエントリが**先頭**に挿入されている → 末尾へ移動する
- `## 2026-06-29 | ...`（角括弧なし）が1件ある → `## [2026-06-29] | ...` に統一する

最終的な並び: 2026-04-17 → 2026-04-21 → 2026-04-22 → 2026-04-23（2件）→ 2026-05-14 → 2026-05-15 → 2026-05-25 → 2026-06-01 → 2026-06-29 → 2026-07-01

- [ ] **Step 4: `tasks/learning-journal.md` の「## 記録」直下に挿入**

Task 2 で作成したヘッダの後、`## 記録` セクションの下に、上で整形した11エントリを昇順で配置する。

エントリ群の直前に以下の注記を入れる。

```markdown
> 以下 2026-07-01 までの11件は、移行前の PRIVATE な作業環境リポジトリから
> 抽象化して取り込んだもの。業務固有情報を含む原本はそちらにアーカイブとして残している。
```

- [ ] **Step 5: ユーザーレビュー（必須ゲート）**

`tasks/learning-journal.md` の**全文**をユーザーに提示し、以下を確認してもらう。

- 業務固有情報が残っていないか
- 抽象化しすぎて学習記録としての価値が失われていないか

**ユーザーの承認を得るまでコミットしない。** AI の抽象化判断だけで PUBLIC への公開を確定させてはならない。

修正指示があれば Step 2〜4 に戻る。

- [ ] **Step 6: コミット**

```bash
git add tasks/learning-journal.md
git commit -F - <<'EOF'
docs(journal): 既存11エントリを抽象化して移行

移行前の PRIVATE な作業環境リポジトリから、2026-04-17〜2026-07-01 の
11エントリを抽象化のうえ取り込んだ。

- 業務固有の識別子・構成情報を除去し、技術的本質のみを残した
- 日付昇順へ並べ替え (原本は最新エントリが先頭に混入していた)
- 見出しを `## [YYYY-MM-DD] | ...` 形式に統一
- 原本は移行元にアーカイブとして保持し、以降そちらには追記しない

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 4: 最終検証と PR 作成

**Files:** なし（検証とPRのみ）

- [ ] **Step 1: 静的検証をまとめて実行**

Run:
```bash
echo "--- 1. protege 参照 ---"
grep -rn "protege\|Protégé" . --exclude-dir=.git --exclude-dir=docs --exclude-dir=claude-code-best-practice || echo "OK: 0件"

echo "--- 2. 移行元PRIVATEリポジトリ名の参照が残っていないこと ---"
grep -rn "<移行元PRIVATEリポジトリ名>" . --exclude-dir=.git || echo "OK: 0件"

echo "--- 3. journal 追跡状態 ---"
git ls-files --error-unmatch tasks/learning-journal.md && echo "OK: 追跡済み"

echo "--- 4. setup.sh 冪等性 ---"
bash setup.sh >/dev/null && bash setup.sh >/dev/null && echo "OK: 2回とも成功"
```

Expected: 1・2 は0件（`README.md` の「移行前のアーカイブ」節で移行元リポジトリ名に触れている場合はその1件のみ許容）、3・4 は OK。
検証範囲は `docs/` と `tasks/lessons.md` を除外しないこと（初回実装時、範囲をREADME/setup.sh/CLAUDE.md/rules/のみに絞ったため計画書・lessons.md内の実名記載を見落とした教訓）。

- [ ] **Step 2: 差分を確認**

Run:
```bash
git diff main...HEAD --stat
```
Expected: `rules/protege-output.md` が削除、`tasks/learning-journal.md` が追加、他6ファイルが変更。

- [ ] **Step 3: PR 作成**

```bash
git push -u origin feat/learning-loop-redesign
```

その後 `/pr-create` で PR を作成する。

- [ ] **Step 4: 引継書の作成**

`docs/handover/2026-08-02-journal-migration.md` を作成し、移行元PRIVATEリポジトリ側の Claude に委譲する作業を記述する。

含める項目:
- 背景（本リポジトリ側で何を変えたか、なぜ委譲するか）
- `setup.sh:257-302` 付近の journal symlink 集約ブロックの撤去
- `README.md:72-79` の「個人ナレッジ集約」節をアーカイブ方針へ書き換え
- `tasks/learning-journal.md` の冒頭に「アーカイブ。以降は追記しない。現行ログは my-claude-code-settings 側」の注記を追加
- `devcontainer/docker-compose.override.yml` の bind mount が journal 以外の目的でも使われているかの確認（使われていれば残す）
- 共有ワークスペース側の journal symlink の後始末
- **やってはいけないこと**: 原本の内容を削除・改変しない（アーカイブとして保持する）

---

## Self-Review

**1. Spec coverage**

| スペックの要求 | 対応タスク |
|---|---|
| 3. ★ Predict / ★ Delta ループ | Task 1 Step 1 |
| 3.2 停止の構造的担保（AskUserQuestion + 上書き宣言） | Task 1 Step 1「停止は AskUserQuestion で行う」 |
| 3.3 差分フィードバック（「その通り」禁止） | Task 1 Step 1「★ Delta の返し方」 |
| 3.4 発火規則（下限1・上限2） | Task 1 Step 1・Step 4 |
| 3.5 合理化防止テーブル | Task 1 Step 1 |
| 3.6 OFF条件（「実装して」除去） | Task 1 Step 1・Step 4 |
| 4.1 配置と追跡 | Task 2 Step 2・3 |
| 4.2 抽象化ルール | Task 1 Step 1・Task 2 Step 4 |
| 4.3 記録フォーマット | Task 2 Step 4 |
| 4.4 既存11エントリの移行 | Task 3 全体 |
| 5. 変更ファイル一覧（9ファイル） | Task 1（5ファイル）・Task 2（4ファイル） |
| 7. 静的検証1〜3 | Task 1 Step 7・Task 2 Step 7・8・Task 4 Step 1 |
| 7.1 検証チェックポイントの埋め込み | Task 2 Step 4・Task 1 Step 1「記録」 |
| 引継書 | Task 4 Step 4 |

ギャップなし。

**2. Placeholder scan**

「TBD」「後で」「適切に」等のプレースホルダなし。全ての置換内容は実文で記載済み。

**3. 用語一貫性**

`★ Predict` / `★ Delta` / `[MISS]` / `tasks/learning-journal.md` を全タスクで統一。`★ Protégé` は削除対象としてのみ登場。
