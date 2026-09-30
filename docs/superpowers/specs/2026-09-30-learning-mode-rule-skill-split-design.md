# learning-mode の常時rule／詳細skill分割 設計書

- 日付: 2026-09-30
- 状態: 承認済み（ユーザー承認: 「判定と開示順だけ」を常時ruleに残す案）
- 関連ADR: `docs/adr/0021-learning-mode-rule-skill-split.md`（proposed。実装PRで accepted にする）
- 前例: `docs/adr/0012-code-learning-mode.md` の「常時ruleと詳細skillの二層構成」

## 1. 背景と測定値

`rules/learning-mode.md` は `paths:` を持たない常時ruleで、毎ターン全文がコンテキストへ載る。

| 対象 | 実測 |
|---|---|
| `rules/learning-mode.md` | 12,334文字 / 474行 / ASCII比率0.26 / `/context` で **11.4k tokens** |
| `rules/code-learning.md`（入口のみ） | 1,114文字 / `/context` で 0.75k tokens |
| Memory files 合計（`/context`） | 22.7k tokens。その約半分が `learning-mode.md` |

節ごとの文字数（`## ` 見出し単位）:

| 節 | 文字数 | 必要になる時点 |
|---|---|---|
| 停止は「応答を待つ対話ツール」で行う | 2,067 | 発火後（問いの出し方） |
| ★ Delta の返し方 | 1,976 | 発火後（差分を返すとき） |
| 両学習モードの共通方針 | 1,952 | **常時**（ON/OFF・担当・上限・開示順・保存・成長判定の正本） |
| 合理化防止 | 1,533 | 判定に迷ったとき |
| 設計Predict固有の発火規則 | 1,151 | **常時**（3条件・層ゲート） |
| 定石の供給 | 687 | ★ Delta を書くとき |
| 概念名の供給 | 601 | ★ Delta を書くとき |
| 次の問いの立て方 | 494 | ★ Delta を書くとき |
| 基本方針 | 451 | 常時（要約で足りる） |
| 記録 | 421 | 保存時 |
| ループ / 対象領域 / コード学習との境界 | 802 | 発火後（境界の一文だけ常時） |

常時必要なのは判定に関わる約4割で、残りは発火が決まってから読めば足りる手順・書式である。
`code-learning` は既にこの二層構成で、両ホストでの発火を実測済み（ADR 0012・0017）。

## 2. 公式仕様から導いた制約（一次資料で確認済み）

| 事実 | 出典 | 設計上の帰結 |
|---|---|---|
| `paths:` の無いruleはcompact後にディスクから再注入される | code.claude.com/docs/en/context-window「What survives compaction」 | 判定部分は常時ruleに残せばcompact後も必ず効く |
| `paths:` 付きruleはcompactで要約され、対象ファイルを再読するまで戻らない | 同上 | `paths:` を付ける案は採らない |
| 呼び出したskill本文はcompact後に再注入されるが、1 skill 5,000 tokens・合計25,000 tokensで打ち切り。先頭が残る | 同上 / docs/en/skills | skill本文は5k tokens以内、重要事項を先頭に置く |
| `SKILL.md` は500行未満、詳細は別ファイルへ | docs/en/skills | 補助資料は `references/` に分離 |
| skill一覧の description は1件1,536文字で切られる。主用途を先頭に | docs/en/skills | description は発火条件を先頭に短く書く |
| 手順になったものはCLAUDE.mdからskillへ。ruleは毎セッションまたは対象ファイルで読み込まれる | docs/en/memory | 分割方針は公式推奨どおり |
| Codexはskillの名前・description・pathだけを先に見て、使うと決めてから `SKILL.md` 全文を読む。`references/` `scripts/` による段階的開示 | learn.chatgpt.com/docs/build-skills、`codex-cli-best-practice/best-practice/codex-skills.md` | 同じ構成が両ホストで使える |
| Codexの AGENTS.md 連結は `project_doc_max_bytes`（既定32 KiB）で打ち切り。リンク先の自動読込は記載なし | learn.chatgpt.com/docs/agent-configuration/agents-md | Codexはruleを自分でReadする。ruleを軽くする効果はCodexにも及ぶ |
| Codexでcompact後にskill本文がどうなるかは記載なし | build-skills | ruleの入口に「継続中の学習イベントではskillを再読する」を置く（code-learningと同じ） |

## 3. 決定した構成

```
rules/learning-mode.md                    常時。判定と開示順だけ
skills/learning-mode/SKILL.md             発火が決まったときに全文読む
skills/learning-mode/references/
  ├ delta-supplements.md                  概念名・定石・次の問いの供給規則
  └ rationalizations.md                   合理化防止の表
```

### 3.1 `rules/learning-mode.md`（常時）に残すもの

見出しと順序はこのとおりにする。

1. `# 学習モード（★ Predict / ★ Delta）`
2. `## 基本方針` — 4文に要約する
   - 答えを開示する前に予測させ、差分を返す
   - 評価対象は結論ではなく判断基準。ユーザーが生成した基準だけを数える。選ばせるのは結論、書かせるのが基準
   - 結論の一致や正答率を習得の証拠にしない
   - 経緯は ADR 0001 / 0007 / 0021
3. `## コード学習との境界` — 現行の4行をそのまま残す（`skills/code-learning/SKILL.md`、3条件とL2優先ゲートはコード学習に適用しない、同じ箇所で二重に出題しない）
4. `## 両学習モードの共通方針` — **現行の節を本文ごと移さず残す**。この節はテストで固定された単一の正本で、`rules/code-learning.md` と `skills/code-learning/SKILL.md` が参照している
5. `## 設計Predict固有の発火規則` — 残す。圧縮してよいのは例示の文だけ
   - 下限なし／3条件／層ゲートの表と「L2以上が実在するならL1で発火させない」「判定不能はL1」／発火させない場面／複数案だけでは強制発火しない
   - 「L1を捨てるわけではない」段落は「L1の書き方は ★ Delta の `定石` で供給する（skill参照）」の1文にする
6. `## 開示前の禁止事項`（新設）
   - 予測は応答を待つ対話ツールで取る。現行のホスト別停止手段の表をそのまま置く（Claude Codeは `AskUserQuestion`、同等ツールが無いホストは問いと選択肢だけを出してターンを終える）
   - 現行の「上書き宣言（2件）」段落をそのまま置く（6.2.1 参照）
   - 選択肢に判断基準・`（推奨）` を書かない
   - 理由を聞く前に答え・推奨・定石・模範解を出さない
   - 選択肢の作り方と理由フェーズの詳細は skill
7. `## 詳細手順の読み込み`（新設。`rules/code-learning.md` の入口と同じ形）
   - 発火すると判定したら、問いを出す前に `skills/learning-mode/SKILL.md` を全文読む
   - 解決先: Claude Code は `~/.claude/skills/learning-mode/SKILL.md`、Codex CLI は `~/.agents/skills/learning-mode/SKILL.md`
   - 継続中の学習イベントでcompactやresumeが入ったら、続きを出す前にskillを再読する
   - skillを発見できない場合は学習イベントを見送り、そのsessionで一度だけ導入未完了を明示する。見送りを「候補が無かった」と扱わない

`alwaysApply: true` のfrontmatterは現行どおり維持する（Codex側の互換目的。`paths:` は付けない）。

**目標サイズ: 6,000文字以下**（現行12,334文字）。判定と共通方針だけで約5,000文字あるため、
当初見込みの3,000文字は採らない。共通方針の文言は削らず、削るのは例示・重複・手順だけにする。

### 3.2 `skills/learning-mode/SKILL.md`（発火後）

frontmatter:

```yaml
---
name: learning-mode
description: Use when a design, root-cause, review, or implementation-strategy decision point has passed the always-on learning-mode gate and a ★ Predict question, reason prompt, or ★ Delta must be produced.
---
```

本文は **compact後の再注入で先頭が残る**ことを前提に、実行順に並べる。

1. 冒頭3行: このskillは常時ruleの判定を通過した後に読む／上限・開示順・保存の正本は常時ruleの「両学習モードの共通方針」／ここでは手順と書式だけを扱う
2. `## ループ` — 4段（予測→理由→開示→差分）と「順序が本質」「[1]と[2]を分ける」
3. `## 対象領域` — 現行の表
4. `## 予測フェーズ` — 常時ruleの停止手段で問うこと（ホスト名は書かない）、選択肢は2〜4個・Otherで自由記述、選択肢には結論だけ（禁止例と正例、description にも基準を書かない）、competitive（事故例の参照を含む）、予測フェーズ以外では推奨を明示してよい
5. `## 理由フェーズ` — 禁止事項、書いてよい一言、選択肢の再掲、Otherが選ばれた回
6. `## ★ Delta` — 書式ブロック、過剰帰属の禁止、過去の判断原則の接続、結論の差分表、固定3軸の評価と全軸充足時の扱い
7. `## ★ Delta の補足欄` — `概念` `定石` `次の問い` は `references/delta-supplements.md` を読んでから書く、とだけ置く
8. `## 記録` — 専用学習storeへ `kind: "decision"` で保存、旧 `learning/entries/` は読み取り専用、抽象化ルール（禁止・必須）
9. `## 迷ったとき` — 判定の回避パターンは `references/rationalizations.md`

**上限: 5,000 tokens 以内**（日本語主体のため目安8,000文字以下）、500行未満。

### 3.3 `skills/learning-mode/references/`

| ファイル | 中身 | 移動元 |
|---|---|---|
| `delta-supplements.md` | 概念名の供給・定石の供給・次の問いの立て方（`次に同種の判断で確認する問い` の固定文字列を含む） | 現行 331〜414行 |
| `rationalizations.md` | 合理化防止の3つの表 | 現行 415〜454行 |

文言は原則移動のみ。書き換えるのは相互参照（「→『定石の供給』」等）のリンク先だけ。

## 4. 周辺の変更

| ファイル | 変更 |
|---|---|
| `manifests/skills.json` | `shared` に `learning-mode` を追加（両ホストへ配布） |
| `CLAUDE.md` | 学習モード節の「詳細仕様は `rules/learning-mode.md`」を「判定は `rules/learning-mode.md`、手順と書式は `skills/learning-mode/SKILL.md`」に更新。135行目の抽象化ルール参照先をskillへ |
| `output-styles/review-and-design.md` | 110行目の参照に skill を併記（「★ Predict・★ Delta は `rules/learning-mode.md` と `skills/learning-mode/SKILL.md`」） |
| `README.md` | ディレクトリ構成に `skills/learning-mode/` を追記、`rules/learning-mode.md` の説明を「学習モードの判定と共通方針」に |
| `docs/adr/0021-learning-mode-rule-skill-split.md` | 実装PRで `status: accepted` に変更し、実測したサイズを「結果」に追記 |
| `rules/code-learning.md` / `skills/code-learning/SKILL.md` | **変更しない**（共通方針の参照先は常時ruleのまま） |

## 5. 対象外

- `CLAUDE.md` の「セッション開始時に rules を全文読む」の見直し（Claude Codeでの二重読込）。`tests/test_instruction_graph.py` が固定しており、両ホストの指示索引の設計判断になるため別タスクにする
- 学習モードの効果測定・継続可否の判断、専用学習storeのbinding復旧
- `learning-output-style` プラグイン、MCP、`skills/synced/` の扱い
- 旧 `learning/entries/` の変更

## 6. テスト契約

既存テストは `rules/learning-mode.md` の本文に文字列があることを検査している。分割後の所在に合わせ、
**正本の所在を固定する**形へ直す。

### 6.1 常時ruleに残ることを固定する（既存assertの対象はRULEのまま）

`tests/test_learning_mode_contract.py` と `tests/test_code_learning_contract.py` が現在RULEに要求している次の文字列は、
すべて常時ruleに残る。テストは変更せず通ること。

- `skills/code-learning/SKILL.md`、`同じ箇所で二重に`、`合計最大2イベント`、`- **上限:` がちょうど1回
- `L2`、`コード学習には適用しない`
- `## 両学習モードの共通方針`、`同じ能力・同じ解法`、`理由まで回答する前`、`status`、`未保存`
- `複数案`、`強制発火`、`結論の一致`、`習得の証拠`
- `7日以上`、`関連実作業`、`保持は未確認`
- `学習なし`、`設計Predictとコード学習が同じ箇所で競合`、`本人が見つけるべき原因箇所や因果の解釈`、`選択と理由の前に示さない`
- `発火・skip・中断・再開`、`同じevent_id`、`operation`
- `能力ID`、`scope`、`別文脈2回`、`2回目`、`ヒントなし`、`比較不能`

否定assert（`## コード参加（Predictの代替イベント）` `Predict とコード参加` `意味のある5〜10行` `必ず発火する場面: こちらが複数案` `外した予測ほど後の定着に効く` を含まない）は、ruleとskillの両方に適用する。

### 6.2 新規テスト（`tests/test_learning_mode_contract.py` に `TestLearningModeSplit` を追加）

1. **ruleのサイズ上限**: `len(RULE) < 6000`、かつ `paths:` を含まない
2. **ruleに手順が残っていない**: `## ★ Delta の返し方` `## 概念名の供給` `## 定石の供給` `## 次の問いの立て方` `## 合理化防止` `★ Delta ───` を含まない
3. **ruleの入口**: `skills/learning-mode/SKILL.md`、`~/.claude/skills/learning-mode/SKILL.md`、`~/.agents/skills/learning-mode/SKILL.md`、`skillを再読`、`導入未完了` を含む
4. **ruleの開示前禁止事項**: `AskUserQuestion`、`（推奨）`、`理由を聞く前`、`上書き宣言` を含む
5. **skillのfrontmatter**: `name: learning-mode`、`description: Use when` で始まる
6. **skillの手順順序**: `## ループ` → `## 予測フェーズ` → `## 理由フェーズ` → `## ★ Delta` → `## 記録` の出現位置が昇順
7. **skillの必須要素**: `★ Delta ───`、`トレードオフ`、`失敗モード`、`前提の検証`、`全軸充足`、`kind: "decision"`、`PUBLIC`、`references/delta-supplements.md`、`references/rationalizations.md`
8. **skillのサイズ**: 500行未満かつ8,000文字以下
9. **referencesの固定文字列**: `delta-supplements.md` が `次に同種の判断で確認する問い` を含む（過去記録のgrepキー。ADR 0001 D8）。`rationalizations.md` が `層ゲート` と `下限` を含む
10. **重複禁止**: `## 両学習モードの共通方針` と `- **上限:` がskillとreferencesに現れない（正本を1つに保つ）
11. **manifest**: `manifests/skills.json` の `shared` に `learning-mode` がある
12. **ホスト中立**: skillとreferencesは `tests/test_learning_mode_contract.py` の `TestSharedSkillPortability` が禁止する `\bClaude Code\b` に当たらない（`manifests/skills.json` の `shared` に入るため自動で検査対象になる。親が確認済み）

### 6.2.1 ホスト固有の記述をどこに置くか（確定）

現行ruleにはホスト固有の記述が2箇所ある。shared skillには `Claude Code` と書けないため、次のように分ける。

| 記述 | 置き場所 | 理由 |
|---|---|---|
| 停止手段の表（Claude Code は `AskUserQuestion`、同等ツールが無いホストは問いだけ出して終える） | **常時ruleの `## 開示前の禁止事項`** | ruleはshared skillの検査対象外。停止は開示順の一部なので常時ruleに置くのが妥当 |
| `AskUserQuestion` の既定ガイダンスに対する上書き宣言2件（(a)教育目的の使用を許可、(b)`（推奨）` 付与を禁止） | **常時ruleの `## 開示前の禁止事項`** | ツール既定より優先させる指示なので、発火前から効いている必要がある |
| skill側の予測フェーズ | 「常時ruleの停止手段で問う」とだけ書き、ホスト名は書かない。`AskUserQuestion` というツール名は書いてよい（禁止パターンはホスト名だけ） | shared skillのホスト中立を保つ |

このため 6.2 の7番（skillの必須要素）から `上書き宣言` を外し、4番（ruleの開示前禁止事項）に `上書き宣言` を加える。
ruleの目標6,000文字にはこの2項目（約700文字）を含める。

### 6.3 実行する検査

```bash
python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -v
bash -n setup.sh
git diff --check
python3 - <<'PY'
from pathlib import Path
r = Path('rules/learning-mode.md').read_text(encoding='utf-8')
s = Path('skills/learning-mode/SKILL.md').read_text(encoding='utf-8')
print('rule chars', len(r), 'skill chars', len(s), 'skill lines', s.count('\n'))
PY
```

## 7. リスクと対策

| リスク | 対策 |
|---|---|
| 発火時にskillを読み忘れ、★ Delta の書式が崩れる | ruleの入口に「問いを出す前に全文読む」を明記。code-learningで両ホスト実測済みの形を踏襲 |
| compactでskill本文が欠ける | 5k tokens以内・重要事項を先頭。ruleに「継続中の学習イベントではskillを再読」 |
| 判定の精度が下がる | 判定に使う文（3条件・層ゲート・発火させない場面・共通方針）は削らない。削るのは例示と手順だけ |
| 正本が二重化する | 共通方針はruleだけに置き、テスト10で重複を禁止 |
| 実ホストで新skillが発見されない | `setup.sh` 後に両ホストでskillが一覧に出ることを親が実ホスト確認する（handoffの未解決事項） |

## 8. 成功条件

- 全テストが通る
- `rules/learning-mode.md` が6,000文字以下、`/context` のMemory filesが約6k tokens以上減る（実ホスト確認は親）
- 判定・共通方針の文言が現行と同一（diffで削除されていないことを確認できる）
- skillとreferencesへ移した文言が現行から欠落していない（移動前後の見出し単位で照合できる）
