# Codex親セッションの工程境界モデルルーティング案

## 状態

- status: proposed
- 実装: 未着手
- 優先度: P1
- 関連: ADR 0010、ADR 0011、ADR 0013

この文書は次の実装候補を記録する。採用済みADRや実装仕様ではない。実装へ進む場合は、
runtimeで現在のmodel + reasoning effortを観測できるか先にspikeし、新しいADRと設計specを作る。

## 問題

現行の`codex/MODEL_ROUTING.md`とADR 0010は、サブエージェントを起動するときの
model + reasoning effort選択を中心にしている。親AIが設計、計画、実装、レビューを同じ
セッションで続ける場合、サブエージェントの起動境界が発生しないため、ルーティング方針が
実行されない。

これは元の目的に対する設計上の不足である。目的は「サブエージェントを安く使う」ことではなく、
タスクの状態に応じて必要十分なmodel + effortを使い、品質と総コストを両立することだった。
親セッションが高価なモデルのまま明確な実装を抱え続けられるなら、この目的を満たせない。

review runnerもこの不足を埋めない。ADR 0013のrunnerは、別セッションのread-onlyな
security / integration reviewを確実に起動・回収するためのものであり、親セッションの
設計から実装への遷移を制御しない。

## 目標

- サブエージェントを起動しない作業でも、親セッションの工程が変わるたびにmodel + effortを再分類する
- 推奨ペアが現在のペアと異なる場合、次工程へ進む前に検証済みhandoffを作って作業を停止する
- モデル変更はCodexの公式UIまたはCLIの`/model`を使ってユーザーが行える
- 切替完了後は同じタスクをhandoffから再開し、弱いモデルが会話履歴だけを独自解釈するのを防ぐ
- 切替待ちを無視したrepo変更は、可能な範囲でhookによりfail-closedにする
- ユーザーが切替を望まない場合は、現在のペアで続行する明示overrideを認め、対象工程と理由を記録する

## 発火条件

コード実装だけを発火条件にしない。次のcheckpointで、親AIは現在のタスク状態を
`codex/MODEL_ROUTING.md`の基準ペアへ再分類する。

1. 新しい実質的タスクを開始するとき
2. 要件探索から設計へ移るとき
3. 設計または実装計画が承認され、最初のrepo変更へ移る直前
4. 実装からデバッグ、セキュリティレビュー、最終統合レビューへ移るとき
5. 失敗原因から、推論の深さ不足・探索範囲不足・設計判断不足のいずれかが判明したとき
6. 作業が明確・局所的・機械的になり、より低いペアで安全に継続できるとき

短い説明、単発の読み取り、ユーザーとの要件確認のたびには停止しない。checkpointは
「ここから先のまとまった工程を別ペアに任せる価値があるか」で判定する。

代表的な遷移は次のとおり。

| 工程 | 基準ペア | 切替checkpoint |
|---|---|---|
| 曖昧で多段の設計・アーキテクチャ | Sol + high | 設計開始前 |
| 明確になった通常実装 | Luna + medium | 計画承認後、最初の変更前 |
| 狭いが難しい実装・再現可能な複雑ロジック | Luna + high / max | 実装前または深さ不足判明時 |
| 広い探索・複数レイヤーのデバッグ | Terra + medium / high | 広い探索が必要と判明した時 |
| 必須セキュリティレビュー | Terra + high + read-only | security boundary判定後 |
| 最終統合判断 | Sol + high | 完了を主張する前 |

モデル名と推論強度の具体値は`codex/MODEL_ROUTING.md`を正本とし、この提案へ複製固定しない。
上表は工程遷移を説明する例である。

## 推奨する方式: 親セッションのswitch gate

親AIが工程遷移を検出し、ユーザーが同じ対話セッションのmodel + effortを切り替える
協調方式を採る。親AIがツールや設定ファイルを使って、ユーザーに見えない形で現在スレッドの
モデルを変更してはいけない。

### 1. 分類

checkpointで次の値を決める。

- 現在の工程
- 次の工程
- 推奨model + effort
- 切替理由: 深さ、探索範囲、設計判断、セキュリティ境界、または降格
- 切替を行わない場合の品質・コスト上の影響

現在のeffective model + effortをruntimeから取得できる場合は推奨ペアと比較する。取得できない場合、
「一致している」と推測して継続せず、観測不能として扱う。

### 2. handoffとpending stateの作成

推奨ペアが現在のペアと異なる、または現在ペアを観測できない場合、最初の変更前に
ADR 0011のschema 1 handoffを作成・検証する。親セッション内の切替でも会話履歴だけに依存しない。

handoffには既存項目に加えて、少なくとも次を記録する。

- `transition_kind: primary-session`
- 切替前のmodel + effort。観測不能なら`unknown`と根拠
- 切替後に期待するmodel + effort
- 現在工程と次工程
- 再開時に最初に行う作業
- ユーザーoverrideの有無、有効範囲、理由

同時にrepo固有のprivateなpending stateを`.superpowers/`配下へ作る。pending stateは
handoff path、digest、期待ペア、対象工程、作成時のGit fingerprintだけを持ち、promptや環境変数を
保存しない。

### 3. ユーザーへの切替依頼と停止

親AIは次の情報を返して、そのターンを終了する。

```text
MODEL_SWITCH_REQUIRED
次工程: 通常実装
推奨: gpt-5.6-luna + medium
理由: 設計が確定し、残作業が明確で反復可能になった
handoff: .superpowers/handoffs/<task-id>.md
操作: /model またはcomposer下のモデル選択で切り替える
再開: 切替後に「切替完了」と送る
override: 現在のモデルで続ける場合は、その旨と対象工程を明示する
```

切替待ちの状態で親AIが「ついでに」実装や検証へ進んではいけない。

### 4. 再開検証

次のユーザーメッセージを受けたら、handoffとGit fingerprintを再検証してから再開する。

- effective model + effortをruntimeから観測できる場合は期待ペアとの一致を機械検証する
- 観測できない場合は、ユーザーの切替完了申告を暫定的なattestationとして記録する
- handoff作成後にGit状態が変わっていたら、推測で続けずhandoffを作り直す
- モデルは一致してもeffortが一致しなければ再開しない
- 再開側はhandoffと参照成果物を全行読み終えてから作業する

runtimeでペアを観測できない構成では、ユーザー申告は「実際の選択を証明した」とは扱わない。
UI表示やthread metadataから証明できるようになるまで、manifestへ`verification: user-attested`と残す。

### 5. pending中のruntime guard

文章規約だけでは、親AIが停止を忘れる抜け道が残る。pending stateが存在する間は、
PreToolUse hookで少なくともworkspaceへの変更、commit、push、外部副作用をブロックする。
handoff検証、状態確認、ユーザーが明示したcancel / override処理だけをallowlistする。

ただし、現在のCodex hook payloadでeffective model + effortを取得できるかは未確認である。
hookがペアを観測できない場合でも「pending中の変更を止める」ことはできるが、
「正しいペアへ切り替わったので自動解除する」ことはできない。この差を隠さない。

## 実装前spike

本実装より先に、使用中のCodex CLIとデスクトップアプリで次を実測する。

1. `/model`またはcomposer下の選択で、同じthreadの次ターンからmodelとeffortが変わるか
2. 切替前後でthread ID、resume、会話履歴、sandbox、providerがどう維持されるか
3. SessionStart、UserPromptSubmit、PreToolUse、app-serverのthread metadataのどこから
   effective model + effortを取得できるか
4. モデルだけ、effortだけ、未対応ペアを選んだ場合のruntime挙動
5. hookが未承認・無効・失敗した場合に、pending stateを安全側へ倒せるか
6. CLIとアプリの両方で、ユーザー操作後の再開を同じ状態機械へ接続できるか

判定は次の3状態を区別する。

- verified: runtime証拠でmodel + effortの一致を確認できた
- user-attested: ユーザーは切替を申告したがruntime証拠を取得できない
- unverified: 切替も申告も確認できないため停止を継続する

spikeでeffective pairを観測できない場合、初回実装は`user-attested`を許容するguided gateに
限定する。機械検証済みと表示したり、hookだけで完全に強制できると主張してはいけない。

## overrideとcancel

ユーザーは切替依頼に対して次を選べる。

- switch: 推奨ペアへ切り替えて再開する
- override: 現在ペアで指定工程だけ続行する
- cancel: pending stateを破棄してタスクを終了する

overrideは永続設定にしない。task ID、工程、Git fingerprintへ束縛し、次のcheckpointでは再分類する。
provider変更、安全境界の解除、権限拡大をoverrideに含めない。

## 初回実装の範囲

- `codex/MODEL_ROUTING.md`をサブエージェント限定から親セッションを含む工程境界ルーティングへ拡張
- routing checkpointと停止応答を定義するskillまたは共通instruction
- schema 1 handoffの親セッション遷移metadata
- pending stateの作成、照会、cancel、scoped overrideを行う小さなCLI
- pending中の変更を止めるPreToolUse guard
- CLIの`/model`切替とアプリのモデル選択を使った手動smoke test
- 状態機械、古いhandoff、effort不一致、override期限、hook無効時のテスト

## 初回へ含めないもの

- 親AIが現在threadのモデルを自動変更する機能
- providerの変更や自動fallback
- 任意prompt・任意sandboxを持つ汎用agent runner
- モデル単価やtoken量だけを入力にした自動最適化
- ユーザー確認なしのoverride
- review runnerとの状態機械の早すぎる共通化

## 検討した代替案

### A. サブエージェント起動を常に必須にする

採らない。明確な直列作業でも別thread、並列制御、worktree、結果統合が必要になり、
モデルを変えたいだけのケースに不必要な複雑さを持ち込む。親セッション自体を切り替えられる
公式UIがあるため、常時spawnを強制する理由がない。

### B. 親AIが推奨だけ表示して、そのまま作業を続ける

採らない。現行の文章契約と同じく、切替を忘れても正常に見える。元の設計ミスを再現する。
推奨ペアが異なると判定した時点で、handoffを保存してターンを終了する。

### C. config.tomlの既定modelを書き換える

採らない。現在threadにいつ反映されるかが不明確で、別sessionにも影響し、ユーザーの通常既定を
task固有判断で汚染する。切替は現在threadに限定した公式UIを使う。

### D. review runnerをwrite可能な汎用runnerへ直ちに拡張する

初回では採らない。親threadの手動切替と、別processのwrite agentでは承認、sandbox、成果物回収、
rollbackの境界が異なる。まずswitch gateを独立して成立させる。

## 完了条件

- 親AIがSolで設計を終えた後、サブエージェントを起動しなくてもLuna実装への切替依頼で停止する
- 切替前に検証済みMarkdown handoffとpending stateが存在する
- pending中は最初のrepo変更がhookで拒否される
- modelとeffortをペアで扱い、片方だけの変更で再開しない
- 切替後のAIがhandoffと参照成果物を全行読んでから実装を始める
- runtime検証済みとユーザー申告だけの状態を区別して表示する
- 明示overrideは対象工程だけに有効で、次のcheckpointへ持ち越されない
- review runner、provider、通常のmodel既定を変更しない
- CLIとデスクトップアプリの代表経路でsmoke testを行う

## ADRへの反映方針

実装を採用するときは新しいADRを作り、ADR 0010の「サブエージェント起動時を中心とした
適応的ルーティング」を、親セッションとサブエージェントの両方を対象にする工程境界
ルーティングへ置換する。ADR 0010の本文は当時の判断として残し、statusまたは一覧から
新ADRによる部分置換を参照する。ADR 0011のMarkdown handoff方針とADR 0013のreview runnerは維持する。

## 根拠

- OpenAI公式 Models: https://developers.openai.com/codex/models
  - 対話CLIでは`/model`、デスクトップアプリではcomposer下のモデル・推論設定で切替可能
- OpenAI公式 Subagents: https://developers.openai.com/codex/subagents
  - subagentのmodel + reasoning effortは明示spawn、`[agents]`、custom agentで設定する
- `docs/adr/0010-codex-adaptive-model-routing.md`
- `docs/adr/0011-codex-cross-model-handoff.md`
- `docs/adr/0013-codex-review-runner.md`

