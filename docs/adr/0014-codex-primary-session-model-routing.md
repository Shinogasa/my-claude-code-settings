---
adr: 14
date: 2026-09-18
status: accepted
---

# Codex親セッションを工程境界で手動切替する

## 背景

ADR 0010はsubagentのmodelとreasoning effortをペアで選ぶが、親AIが同じsessionで
設計から実装まで続ける場合はspawn境界が無い。設計が確定した後も高いペアで
明確な実装を続けられ、品質と総コストを両立する目的を満たせない。

OpenAI公式ModelsはCLIの/modelとアプリのcomposer下のmodel・effort選択を案内する。
公式HooksはUserPromptSubmitでprompt、PreToolUseで対象local toolを拒否できる。
ただしhosted tool等はPreToolUseの対象外であり、非managed hookは信頼承認まで
実行されない。Codex CLI 0.154.0の生成schemaではthread/readのmodelとeffortは
現在設定または保存済み設定で、per-turn execution telemetryではない。
Thread.sessionIdはsession tree内で共有され得るため、hook session_idから
現在threadを一意に決められるとは未確認である。
effort fieldの不在判断は、公式Hooksの共通入力と該当event、CLI 0.154.0の
生成schemaを探索範囲とする。hook入力契約の正本が公式Hooksなのでこの範囲を採る。
surface固有の拡張、未確認event、将来版で追加された場合は再検討する。

## 決定

- 親AIは新しい実質的task、承認済み成果物から別の親工程への移行、能力不足の証拠が
  出た時にペアを再分類する。同じペアや非実質工程では停止しない。
- ペア変更時はPREPARINGを作り、ADR 0011のschema 1 handoffを検証して
  SWITCH_PENDINGへ移り、親AIは切替依頼を返して停止する。
- 遷移ID、工程、target pair、evidence、handoff digest、Git fingerprintは
  session別のprivate manifestへ置く。handoff schema 1は変更しない。
- 実装時のsecurity reviewで、hookのcwdだけからmanifestを探すとrepo外のcwdで
  pendingを見失うと判明した。`CODEX_HOME/model-switch-registry/`にowner-onlyの
  session→repo対応を追加し、対応先が欠落・不正、またはpending中に別repoへ移ったら拒否する。
  cancelでは対応を削除し、repo移動後も同じsessionを続けられるようにする。
- 最終レビューで、PREPARINGのpatchがsymlinkを追って別ファイルを書き換えると判明した。
  beginとpatch許可時にhandoffの親path・ファイルのsymlinkとファイルのhardlinkを拒否し、
  相対patchはrepo rootのcwdからだけ許す。
- ユーザーが公式UIまたはCLIで切り替える。UserPromptSubmitは現在promptの
  厳密なresume・override・cancel commandだけを受け、pending中の通常promptを拒否する。
  PreToolUseは対象local toolの副作用を拒否するbackstopとする。
- modelとeffortの両方を同一threadの次turn直前の現在設定として照合できた場合だけ
  runtime-config-verifiedとする。初回実装ではthread同定が未確認なので、この状態を
  生成せず、観測可能なmodelとの一致とユーザー申告によるuser-attestedを
  通常工程だけで許す。証拠不足・不一致はunverifiedで停止する。
- overrideは現在promptだけを出所とし、task・phase・transition・session・handoff digestへ
  束縛する。provider、sandbox、permissions、必須security review、人間確認の境界は
  overrideできない。phase leaseは次checkpoint、別task、別session、cancelで失効する。
- same-thread検証が必要なのに得られない場合は、明示ペアのfresh sessionへhandoffする。
  必須security reviewと最終integration reviewはADR 0013のreview runnerが担当する。
- hook未承認・無効・失敗と対象外tool経路を強制成功に数えない。checkpointの意味分類は
  親AIの判断に残るため、pending作成前の見落としは機械的に防げない。

この決定はADR 0010の親AIによる再分類と移行方法を部分置換する。
subagentの基準ペア、provider不変、人間確認境界は維持する。

## 検討した代替案

### A. subagent起動だけを切替境界にする

採らない。親AIが直列作業を続ける経路では切替が発火しない。

### B. 推奨ペアを表示して同じturnで続行する

採らない。切替忘れを検知できず、元の問題を再現する。

### C. PreToolUseだけで親の作業を止める

採らない。通常promptの送信と対象外toolを止められない。
UserPromptSubmitを主gateとし、PreToolUseは対象local toolのbackstopにする。

### D. ユーザー申告をruntime検証済みと扱う

採らない。hook共通payloadからeffortを得られず、modelとeffortの証拠強度が異なる。

### E. ADR 0011のhandoff schemaへ遷移fieldを追加する

採らない。既存consumerの入力契約と、handoff本文の正本性を変える。
遷移状態はprivate manifestへ分ける。

### F. review runnerを親のwrite工程へ拡張する

採らない。read-onlyな別process reviewと、親のwrite工程では権限と成功条件が異なる。

### G. config.tomlの既定ペアを書き換える

採らない。現在threadへの反映が不明確で、別sessionの通常既定も変わる。

### H. handoff patchの文字列上のpath一致だけで編集を許す

採らない。patch適用時にsymlinkが解決され、指定handoff以外を変更できる。

## 結果

良くなること:

- 親AIだけで進むタスクにも工程境界の切替を適用できる。
- handoffの鮮度、target pair、再開prompt、overrideの範囲を検査できる。
- review runnerと親switch gateの責務が分かれる。

諦めること・既知のリスク:

- 手動切替とhandoff作成による操作負担が増える。
- user-attestedは実行ペアの機械証明ではない。
- hook未承認、失敗、対象外tool、pending前の分類忘れでは完全な強制を保証できない。
- handoff pathの検査とpatch適用の間に別processがpathを差し替える競合は、初回実装の
  local hookだけでは排除できない。
- app-serverとhookのcurrent thread対応はCLI・アプリ双方のruntime spikeが必要である。

## 根拠

- OpenAI Models: https://learn.chatgpt.com/docs/models
- OpenAI Hooks: https://learn.chatgpt.com/docs/hooks
- OpenAI App Server: https://learn.chatgpt.com/docs/app-server
- docs/codex-primary-session-model-routing-proposal.md
- docs/superpowers/specs/2026-09-18-codex-primary-model-routing-design.md
- ADR 0010、0011、0013
