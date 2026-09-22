---
adr: 16
date: 2026-09-22
status: accepted
---

# Codex親モデル切替の実運用pilotを限定的に行う

## 背景

ADR 0015で、親工程の標準経路を明示ペアのsubagentまたはfresh sessionへ移した。
旧beginが別hookで拒否されてもgrantが残り、後からhook配送なしで消費できることを実測した。
配送receiptと実commandの実行を束縛できないため、同一threadの新規開始を停止する。
一方、既存の`PREPARING`と`SWITCH_PENDING`を読む利用者がいるため、状態の読み取り、resume、
diagnose、cancelは互換経路として残す必要がある。

この決定はADR 0015を置換する。基準ペア（ADR 0010）とhandoff契約（ADR 0011）は維持する。

今回のpilotでは、Codex CLI 0.155.1で隔離App Serverの復旧経路を確認した限定修正をmainへ統合し、
続く実タスクで運用経路を確認する。未検証事項と不具合時の収集項目を永続文書に残す。
設計だけのreview runnerを実稼働の証拠として扱わない。

## 決定

- 新規の親工程切替は、検証済みhandoff付きの明示ペアsubagent、または明示ペアのfresh sessionで行う。
  fresh sessionでは、期待modelとeffortを指定してvalidateし、固定した`INPUT_DIGEST`を指定した
  validatorの`read`でhandoffと参照文書を全文取得してから作業を始める。
- 同一threadの`begin`は新規経路として常に拒否する。旧manifestを読むresume、状態照会、cancelは
  互換・復旧のために許可する。通常promptを旧pending状態で受け付け、復旧contextをCodexへ渡す。
- 取消まではlocal toolを限定し、`diagnose`/`status`とtransitionに完全一致するcancel CLIを許可する。
  自然文の「モデル切替を診断して」「切替待ちを取り消して」も、Codexが対応するhelperを実行する依頼例とする。
  標準の`codex diagnose`コマンドが存在すると文書で主張しない。
- modelのhook観測、effortのユーザー申告、provider応答の有無を別々に記録する。mock providerの成功は
  hosted inferenceを証明しない。hosted toolやspecial toolを対象にした強制を主張しない。
- review runner本体はまだ実装しない。security reviewとintegration reviewは、現時点では明示ペアの
  read-only agentとvalidatorで行い、runnerの設計資料だけを実稼働結果として扱わない。

## pilotの受入条件

1. 利用可能な経路と自然文依頼例を運用handoffに記載する。
2. 実測済みと未検証を分け、テスト件数や成功数を推測で補わない。
3. 不具合時はcommit、Codex版とsurface、新旧thread、session/turn、hook event/status、diagnoseの
   状態、provider応答の有無を収集する。秘密、credential、会話全文は公開repoへ保存しない。
4. 未消費grantが残っていても新規beginが拒否されることを確認する。旧pendingはcancelで復旧し、同じsessionで
   通常作業へ戻れることを確認する。
5. コード学習実装を使う実タスクで、工程境界のペア再分類、handoff読了、明示ペアreview、未検証項目の
   記録を確認する。

## 検討した代替案

### A. 同一threadで新規beginを許可する

会話履歴は維持できるが、同一turnの配送確認だけでは拒否後のgrant流用を防げない。
token注入もCodex 0.154.0の実commandへ反映されなかった。期限だけを追加しても別実行への流用が
可能なため、開始条件の部分修正では保証できず採らない。

### B. 互換状態を削除する

既存のpendingを安全にcancelできず、hook不調時の復旧経路を失う。旧状態の検証・resume・cancelを残す方が
移行中の状態を安全に扱えるため採らない。

### C. review runnerを先に実装してpilotを自動化する

runnerの未実装部分を実測済みと誤認する危険がある。現時点の明示ペアagentとvalidatorで必要な
証拠を集め、runnerは別の実装判断として扱う。

## 未解決事項

Desktop/CLIと実モデルでの通常タスク完走は未実施である。guardが無効なsurfaceでの強制、旧Desktop
threadの原因、大規模競合試験、hosted/special toolの境界も未確認である。これらが解消されたときに
再評価する。

## 根拠

- `docs/adr/0015-codex-parent-routing-runtime-boundary.md`
- `docs/codex-parent-model-routing-runtime-research.md`
- `docs/codex-parent-routing-operations-handoff.md`
