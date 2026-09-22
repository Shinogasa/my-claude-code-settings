# Codex親セッションの工程境界モデルルーティング設計

> **適用範囲変更:** 本書の状態機械は同一threadの補助gateとして維持する。親工程の標準経路、
> fresh runtime実測、preflight開始条件はADR 0015と`codex/MODEL_ROUTING.md`を正本とする。

## 目的と範囲

親AIが同じセッションで設計から実装へ進む場合にも、次の工程のmodelとreasoning effortを
ペアで再分類する。推奨ペアを使うための手動切替、検証済みhandoff、切替待ちの停止、
対象工程だけの明示overrideを一つの状態機械で扱う。

provider、通常のmodel既定値、既存custom agentのペアを変えない。security reviewと
integration reviewの実行・回収はADR 0013のreview runnerへ渡す。ADR 0011のhandoff
schema 1は変更しない。

## 実測した境界

- OpenAI公式Modelsは、CLIの/modelとアプリのcomposer下の操作でmodel・effortを選べるとする。
- OpenAI公式Hooksは、UserPromptSubmitのprompt拒否とPreToolUseの対象local tool拒否を定義する。
  hookの共通入力はactive model slugを含むが、reasoning effortを含まない。
- Codex CLI 0.154.0の生成schemaでは、thread/readのmodel・reasoningEffortはloaded
  threadの現在設定、またはlatest persisted valueであり、per-turn execution telemetry
  ではない。Thread.sessionIdはsession tree内の複数threadで共有され得る。
- hookのsession_idから現在のapp-server threadIdを一意に特定できることは未実測。
  初回実装はその同一視を使わず、通常工程のuser-attested再開を提供する。

effort fieldに関する不在判断の探索範囲は、公式Hooksの共通入力と該当event、
CLI 0.154.0の生成schemaである。hook入力契約の正本が公式Hooksなので
この範囲を採る。surface固有の拡張、未確認event、将来版にfieldが増えた場合は
この判断を再検討する。

## Checkpoint

1. 新しい実質的taskで、短い読み取り調査により次工程の性質が定まった時。
2. 承認済み成果物から親AIの別工程へ移る時。代表例は探索から設計、設計・計画から実装。
3. 証拠から現在ペアの推論の深さ、探索範囲、設計判断能力が不足した時。

同じペアを使う場合、単発読み取り、短い説明、同じ受入条件内の局所debug、
通常のtest再実行では停止しない。降格は、検証済みhandoffだけで次の担当が着手できる
安定した工程境界に限る。分類の意味判断は親AIに残るので、checkpointの見落としは
機械的には検出できない。

## 状態と保存先

状態はACTIVE、PREPARING、SWITCH_PENDING、CANCELLEDとする。private manifestを
.superpowers/model-switch/へ置き、Git追跡対象から除外する。repoとsession_idで
pendingを分離し、各sessionに同時に一件だけ許す。hookのsession_idはsubagentでは
親sessionを指すため、親のpending中はそのsubagentのlocal toolも止まる。
異なるcwdへ移った時もpendingを見失わないよう、`CODEX_HOME/model-switch-registry/`に
owner-onlyのsession→repo対応を置く。対応先repoが欠落・不正、またはpending中のcwdが
対応先repo外なら拒否する。cancelでは対応を削除する。CANCELLEDのmanifestは履歴として
残し、repo移動後も同じsessionの通常promptを妨げない。

manifestにはschema version、transition ID、session ID、task ID、current/next phase、
target model・effort、handoff path、INPUT_DIGEST、pre-switch branch・HEAD・fingerprint、
各軸のevidence source、verification tier、override理由とphase leaseを記録する。
ユーザーprompt全文、環境変数一覧、認証情報、Codex config全文は保存しない。
書込みはowner-onlyなprivate directoryでatomic replaceし、不正・欠落・symlinkを
成功へ畳まない。

## 切替フロー

1. 親AIがcheckpointで基準ペアを決める。同じペアならACTIVEのまま続ける。
2. 変更が必要なら小CLIのbeginでPREPARINGを作る。以後、指定handoffの作成、
   validator、状態照会以外のlocal toolを拒否する。
3. ADR 0011のschema 1 handoffを作り、validatorの期待model・effort、Git鮮度、
   参照hash、INPUT_DIGESTを照合する。private manifestへ遷移metadataを保存して
   SWITCH_PENDINGへ進める。
4. 親AIは切替操作、target pair、transition ID、handoff pathを示してターンを終える。
5. ユーザーが/modelまたはアプリのcomposer下で切り替え、厳密な再開commandを送る。
   hookは現在promptからだけ再開・override・cancelを受ける。
6. 再開時はhandoffとpre-switch Git fingerprintを再検証する。modelのhook値が
   観測できればtargetと照合する。effortのruntime証拠が無い初回実装は、ユーザーの
   ペア申告と観測済みmodelが一致した時だけuser-attestedとして通常工程を再開する。
7. 再開側はADR 0011のvalidated readerからhandoffと参照文書を全行読んでから作業する。
   これは受信agentの契約であり、初回実装は読了をhookから機械証明したとは表示しない。

構造化commandは次の三形だけにする。transition IDとmodel・effortまたはphaseを
manifestへ厳密照合し、余分な行や説明文に埋め込まれたcommandを受理しない。

    MODEL_SWITCH_RESUME <transition-id> <model> <effort>
    MODEL_SWITCH_OVERRIDE <transition-id> <phase> <reason>
    MODEL_SWITCH_CANCEL <transition-id>

overrideは現在のユーザーpromptだけを出所とし、task、phase、transition、session、
handoff digestへ束縛する。provider、sandbox、permissions、必須security review、
人間確認境界はoverrideできない。承認前はpre-switch fingerprint一致を要求する。
承認後はrepo変更だけでphase leaseを失効させず、次checkpoint、別task、別session、
cancelで失効させる。

## Hook契約

- SessionStartはsession IDを親AIへ渡す。hookが実行されなければguard能力を確認済みと
  表示しない。
- UserPromptSubmitはSWITCH_PENDINGで通常promptをblockし、上記commandを同期処理する。
  resumeに必要な証拠が不足・不一致ならpendingを維持する。
- PreToolUseはPREPARING・SWITCH_PENDINGのlocal toolをdeny-by-defaultにする。
  PREPARINGでは指定handoffの編集とvalidator・状態CLIだけ、SWITCH_PENDINGでは
  validator readと状態照会だけを許す。handoff編集時はpatchの指定pathだけでなく、
  親directory・ファイルのsymlinkとファイルのhardlinkを拒否し、相対pathはrepo rootの
  cwdからだけ許す。Bashは単一commandを厳密解析し、shell control operator、
  redirection、command substitutionを許可しない。
- 判定可能なエラーは公式のJSON blockまたはdenyで拒否する。非同期hookを使わない。
  hook未承認・無効・timeout・実行不能、hosted tool、特殊tool経路は
  このguardの完全な強制対象ではない。

## 証拠の階層

runtime-config-verifiedは、同一threadを一意に結び付け、次turn直前のloaded設定として
modelとeffortの両方を照合できた場合だけ使う。これは実際のturn実行telemetryではない。
user-attestedはユーザー申告に依存し、観測できた軸との矛盾が無い状態。
unverifiedは申告・観測・hook能力の不足または矛盾がある状態で、再開許可を発行しない。
初回実装はruntime-config-verifiedを生成しない。

same-thread検証が成立しないsurfaceでは、通常工程だけuser-attestedを許す。
ペア自体が保証条件なら明示ペアで起動するfresh sessionへhandoffを移す。
元sessionのleaseは移さず、移行先でhandoffとGit鮮度を検証する。
security reviewと最終integration reviewはreview runnerの明示ペアで実行する。

## ファイル責務

- bin/codex-model-switch.py: begin、publish、statusのCLI。
- bin/codex_model_switch.py: private manifest、状態遷移、validator連携。
- hooks/codex-model-switch-hook.py: 三つのhook eventの入力と拒否判断。
- codex/hooks.json: 同期hookの配線。既存の危険command guardを維持。
- codex/MODEL_ROUTING.md: 親工程のcheckpointと手動切替の指示。
- .gitignore、README.md、setup.shの検査: private stateと配布・操作を説明。
- docs/adr/0014-codex-primary-session-model-routing.md: 採用理由と却下案。

## 検証

一時Git repoと実validatorを用いて、beginからhandoff検証、pending、
model不一致・effort申告不一致・stale fingerprint・override・cancel・別sessionを
テストする。hookは実JSON payloadで起動し、通常prompt、local tool、許可操作、
不正JSONを検査する。外部modelを呼ぶ試験は通常suiteに含めない。
CLIとアプリの手動smokeではhook trustの状態を記録し、未承認ならguard成功としない。

## 根拠

- OpenAI Models: https://learn.chatgpt.com/docs/models
- OpenAI Hooks: https://learn.chatgpt.com/docs/hooks
- OpenAI App Server: https://learn.chatgpt.com/docs/app-server
- ADR 0010、0011、0013
- docs/codex-primary-session-model-routing-proposal.md
