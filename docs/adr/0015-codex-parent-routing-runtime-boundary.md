---
adr: 15
date: 2026-09-22
status: accepted
---

# Codex親工程の標準経路を明示agentとfresh sessionにする

## 背景

ADR 0014は、親sessionのmodelとreasoning effortを工程境界で手動変更し、
`UserPromptSubmit`と`PreToolUse`で同一threadを停止・再開する方式を標準にした。しかし既存の
Desktop threadでは、manifestが`SWITCH_PENDING`のまま通常promptとlocal toolが進み、完全一致の
resumeも処理されなかった。`/hooks`のActive表示とtrusted hashは確認できたが、そのthreadでの
実event、session ID、handler結果を採取していなかったため、未配送、起動失敗、session ID差、
別runtime状態、古いthread設定のどれが原因かは確定していない。

Codex CLI 0.154.0のfresh App Server threadを、使い捨て`HOME` / `CODEX_HOME`、一時Git repo、
localhost mock providerで実測した。rootのthread IDとsession IDは一致し、通常promptの
`UserPromptSubmit`は`blocked`となって`SWITCH_PENDING`を維持した。`gpt-5.6-sol` / `high`を
申告したresumeでは同eventが`completed`となり、同じsession IDのmanifestが`ACTIVE`へ遷移した。
別のfresh threadでは、begin commandの`PreToolUse`完了後にmanifestが`PREPARING`となり、続く
`touch`の`PreToolUse`は`blocked`となってfileを作らなかった。

この実測はfresh App Server threadでhook配送が成立することを示すが、旧Desktop threadの失敗原因を
確定しない。また公式hook入力はmodelを含む一方、reasoning effortを含まないため、同一thread resumeの
effort証拠は`user-attested`を超えない。

## 決定

- 親工程で別ペアが必要な場合、分離可能な作業は検証済みhandoff付きの明示ペアsubagentへ渡す。
- 親ペア自体が保証条件である、または直列の親作業を移す場合は、検証済みhandoffで明示ペアの
  fresh sessionへ移す。移行先は期待ペアを含めてvalidateし、固定`INPUT_DIGEST`のvalidator
  `read`でhandoffと参照文書を全文取得する。
- 同一thread gateは標準経路にせず、実配送preflight済みsession向けの補助経路として残す。
  `begin`は同じturnの実`UserPromptSubmit`と`PreToolUse`が、session、repo、現行hook hash、
  完全一致のbegin引数へ束縛したone-time grantを発行した場合だけ成功させる。
- `/hooks`のActive/trusted表示と合成payloadテストは、対象turnの実配送証拠に数えない。
  App Serverでは`hook/started` / `hook/completed`、event ID、thread/turn/session ID、manifest遷移を
  結び付けてruntime証拠とする。
- `diagnose`でrepo binding、manifest、preflight receiptを表示する。hook配送が壊れても復旧できる
  直接`cancel` CLIを維持する。
- 同一thread resumeのmodelは`hook-observed`、effortは`user-attested`、全体tierは
  `user-attested`とする。reasoning effortをruntimeから観測できるまで
  `runtime-config-verified`を生成しない。
- provider、sandbox、permissions、security review、人間確認境界、handoff schema 1は変更しない。

この決定はADR 0014を置換する。ADR 0010の基準ペア、ADR 0011のhandoff契約、ADR 0013の
review runnerは維持する。

## 検討した代替案

### A. 同一thread gateを標準のまま維持する

- **利点**: 会話履歴とUIを維持し、fresh sessionの起動負担を減らせる。
- **欠点**: 旧Desktop threadの失敗原因が未確定で、effortをhookから観測できない。
- **採らない理由**: fresh App Serverの成功を別surface・既存threadの成功へ一般化できず、保証強度が
  `user-attested`に留まるため。

### B. 同一thread gateを全面削除する

- **利点**: runtime差と手動resume状態機械をなくせる。
- **欠点**: fresh threadではprompt block、resume、local side-effect blockが実配送で成立した。
- **採らない理由**: 実配送preflightでfail-closedに開始できる補助経路まで捨てる必要はないため。

### C. config.tomlの既定ペアを書き換えて親を移す

- **利点**: 専用manifestとresume commandを減らせる。
- **欠点**: 現在threadへの反映を保証せず、他のfresh sessionの既定も変更する。
- **採らない理由**: 対象sessionと工程へ変更を束縛できないため。

### D. `/hooks`表示と合成payloadテストをpreflightにする

- **利点**: 実model requestを伴うE2Eより軽い。
- **欠点**: hook定義の発見・信頼と、対象turnへの配送・handler結果を区別できない。
- **採らない理由**: 旧失敗でこの取り違えを実際に起こしたため。

## 結果

良くなること:

- ペア保証が必要な工程はspawn時に両軸を明示でき、同一threadのeffort未観測へ依存しない。
- 同一thread gateは実hook配送を確認できないsessionでmanifestを作らず、開始時にfail-closedになる。
- hook不調時も診断と直接cancelでpendingから復旧できる。
- parser・manifest回帰テストとruntime配送証拠の役割が分離される。

諦めること・既知のリスク:

- fresh sessionでは会話履歴を自動継承せず、検証済みhandoffの作成・読了が必須になる。
- subagentへ分離できない作業ではsession移行の操作負担が増える。
- 同一thread gateを選んだ場合、effortは引き続きユーザー申告である。
- 旧Desktop threadの未配送原因は未確定であり、将来のDesktop実測で再分類する余地がある。
- `PreToolUse`対象外のhosted/special toolを完全には停止できない。

## 根拠

- OpenAI Hooks: https://developers.openai.com/codex/hooks
- OpenAI App Server: https://developers.openai.com/codex/app-server
- OpenAI Subagents: https://developers.openai.com/codex/subagents
- `docs/codex-parent-model-routing-runtime-research.md`
- Codex CLI 0.154.0の隔離App Server runtime実測（2026-09-21）
- ADR 0010、0011、0013、0014
