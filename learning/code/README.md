# コード学習の記録契約（pilot）

`skills/code-learning/SKILL.md` の実課題で、ユーザーが実際に示した能力を専用学習storeへ残す。
新規ファイルの配置と排他保存は `learning-store.py record` が担う。このリポジトリの旧
`learning/code/entries/` は読み取り専用履歴であり、新規保存先ではない。

## 保存する条件

- Investigate、Review、Modify、Writeで、本人が調査・変更・レビュー・検証した実行動を観測した場合だけ保存する。
- 説明・転移回答だけ、AIによる解説だけ、skip、未回答は能力証拠として保存しない。
- tool出力、diff、agent報告、AIが完成させたテストや修正は支援として明記する。
- `★ Code Delta` と同じ一つの能力について、行動、理由、検証、未確認事項を分ける。
- 公開できる最小再現形へ一般化し、**抽象化できない場合は保存しない**。
- 記録をteachへ**自動同期しない**。

Writeを固定で優先しない。現在の要求に関係し、本人が所有でき、検証できる形式を
Investigate、Review、Modify、Writeから選ぶ。Explainだけなら能力recordを作らない。

## 能力recordのJSON

入力JSONは次の固定キーを持つ。未知のキーや範囲外の値は受理されない。

| キー | 内容 |
|---|---|
| `schema_version` | `1` |
| `id` | record固有のUUID |
| `event_id` | 初回・再試行・訂正で共有するUUID |
| `observed_at` | UTC ISO 8601 |
| `kind` | `code`。設計判断は `decision` |
| `mode` | `investigate` / `review` / `modify` / `write` |
| `capability_id` | 公開可能で安定した能力ID |
| `scope` | 行動と対象範囲を表す短い説明 |
| `initial_result` | `pass` / `partial` / `fail` / `unverified` |
| `retry_result` | 上記4値または `not_attempted` |
| `transfer_result` | 上記4値または `not_attempted` |
| `supersedes` | 同じeventの旧record ID配列。初版は空配列 |
| `body` | 下記見出しを持つ非空本文 |

`capability_id` が同じでも、`scope` が異なれば同じ能力として集計しない。初版と訂正版は
同じeventの履歴であり、別の成功回に数えない。

## 本文の形式

```markdown
# 抽象化した能力名

## 能力
能力IDとscope。扱った挙動・失敗経路・依存・変更影響を一つに絞る。

## 形式
Investigate / Review / Modify / Writeのどれを行ったか。

## 担当範囲と完了条件
本人が担った範囲、外部の完了条件、完了または中断の状態。

## 開始契機と提示済み情報
自発・依頼・再開の別。先に示されていた対象箇所、仮説、検証ケース。

## ユーザーが実証
本人が選んだ次の行動、実際の行動と理由。観測していない推測は書かない。

## 支援と再試行
ヒント、tool出力、AI修正、初回結果、再試行の差分と最終結果。

## 検証方法
本人が選んだ検査、実行結果、repository契約、残る不確実性。

## ★ Code Delta
一致点、重要な差分、事故条件、再利用できる確認問い。根拠の種類を分ける。

## 転移結果
変えた一条件、本人の行動、検証結果。未実施ならnot_attemptedと理由。

## 未解消のgap
次の関連実作業で確認する一点。関連record IDもここへ記す。
```

中断後に再開する場合も同じ `event_id` を使い、途中の支援と観測済み結果を残す。
完了と中断を曖昧にせず、AIが引き取った範囲を本人の成功に数えない。

## operation record

`kind: operation` は発火、skip、中断、再開などの運用回数を数える別schemaである。
日時、ID、能力ID、終了理由、回答待ち回数だけを持ち、会話やコードを入れない。
operationは習得証拠ではなく、同じ `event_id` の能力recordとも別に解釈する。
OFF中はoperationも作らない。

`end_reason: cap_reached` は、上限に達したため出題を見送った候補を表す。
学習イベントではないので、イベント数や発火数に含めない。上限が候補を落としているのか、
候補の検出自体が少ないのかを切り分けるために使う。

## 成長と保持

同じ能力を**別文脈で2回**実証し、2回目は**実質ヒントなし**で、理由・検証・転移が
scopeに合う場合だけ独立成功の候補にする。開始契機、既知のコード、提示済み情報、支援量が
比較不能なら判断を保留する。記録が無いことは未習得の証拠ではない。

最後の独立成功から**7日以上**空いた**関連実作業**が来た場合だけ保持確認の候補に戻せる。
日付を変えたfixtureや即時の転移を長期保持と呼ばない。関連実作業が来なければ保持は未確認とする。
