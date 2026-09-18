---
adr: 13
date: 2026-09-18
status: accepted
---

# Codexレビュー実行と出力回収を専用runnerへ分離する

## 背景

ADR 0011は、別モデルへレビューを移す前の入力完全性をMarkdown handoff、Git fingerprint、
参照hash、validated readerで検証する。しかし、`codex exec`の起動、JSONL監視、最終回答回収、
resume、重複実行抑止は親AIの手順解釈に残っていた。実運用では4,759行のreview packageを
一括読了した後に同じ全範囲を分割再読し、`gpt-5.6-sol` + `high`の実行が入力756,817 tokens、
出力10,852 tokensに達した。processはexit 0で、JSONLに最終`agent_message`と
`turn.completed`が存在したが、通常の回収経路から見えず、無出力終了と誤認しやすかった。

OpenAI公式の非対話実行仕様では、`codex exec --json`が`thread.started`、
`turn.completed`、`item.completed`等をJSONLで返し、`--output-last-message`が最終回答を
ファイルへ保存する。特定session IDを指定した`codex exec resume`も利用できる。これらを
組み合わせれば、空のPTY pollや親AIの解釈ではなく、成果物とeventで完了を判定できる。

## 決定

- `bin/run-codex-review.py`を追加し、review用`codex exec`の起動、JSONL監視、最終回答回収、
  Markdown契約検査、最大1回のresume、重複実行抑止、完了状態の確定を担当させる
- `bin/validate-codex-handoff.py`は入力handoffの完全性、Git鮮度、参照hash、model + effort、
  validated readだけを担当し、agent実行責務を追加しない
- runnerは`--json`と`--output-last-message`を必ず併用する。report fileを一次成果物とし、
  不在・空・契約不成立時だけJSONLの最後の非placeholder `agent_message`を検査する
- 成功は、process exit 0、`turn.completed`、有効なreport、必須documentの読了range完全性を
  すべて満たした場合だけとする。成功したvalidator `read` commandのeventだけを証拠にし、
  agent message内の`DOCUMENT:`文字列は読了証拠にしない
- 読了rangeは同じ`INPUT_DIGEST`で1行目から最終行までをgap、overlap、duplicateなしで
  一度だけ覆うことを必須にする。一括読了後の全範囲再読を成功扱いしない
- 初回turnが正常完了し、入力読了済みでreportだけが無い場合は、`thread.started`から得た
  正確なsession IDを指定して最大1回だけresumeする。`--last`は使わない
- resumeが失敗しても新しいreviewを自動起動しない。失敗理由と成果物pathを返して停止する
- task ID単位のnon-blocking lockで同時実行を拒否する。各attemptは新しいprivate run directoryを
  使い、過去のreportやJSONLを再利用しない
- `manifest.json`へmodel + effort、入力digest、session ID、exit code、turn完了、report source、
  読了range、resume有無、最終状態を記録する。prompt全文、環境変数一覧、認証情報、
  `~/.codex/config.toml`全文は記録しない
- modelとreasoning effortを常にペア指定し、reviewはread-only sandboxで実行する。
  provider選択の引数は公開せず、現在のproviderを変更しない
- 初回はsecurity reviewとintegration reviewのMarkdown契約だけを扱う。構造化JSON出力や
  任意agent runnerへの一般化は、runnerの状態機械が安定してから別タスクで判断する

## 検討した代替案

### A. `MODEL_ROUTING.md`とhandoff promptへ手順だけを書く

採らない。差分は小さいが、最終回答の選択、resume、新規実行、range重複の判断が親AIへ残り、
今回の誤回収と重複読込を機械的に防げない。

### B. handoff validatorへreview実行責務を追加する

採らない。安全な入力読込と外部process orchestrationでは、必要な権限、失敗状態、テスト対象が
異なる。validatorをread-onlyな入力境界として保ち、出力完全性は専用runnerへ分ける。

### C. 初回から`--output-schema`で最終回答をJSON Schema化する

採らない。公式に対応しており将来候補として有用だが、既存handoffのMarkdown返却契約と同時に
導入すると、状態機械の修正とreport schema移行を切り分けられない。初回はMarkdown契約を
固定し、構造化出力は後続タスクで評価する。

### D. 任意agent、複数provider、一般retryを扱う汎用runnerにする

採らない。review以外の成功条件、write sandbox、provider障害、backoffを同じ抽象へ入れると、
今回必要な「レビューを一度だけ確実に完了・回収する」という境界が広がる。provider自動切替は
ADR 0010のfail-closed方針にも反する。

### E. reportが無ければ新しいreviewを自動起動する

採らない。元sessionが完了済みでも二重課金と重複レビューを起こす。正確なsession IDでの
resumeを一度だけ許可し、それでも回収できなければ人間または親AIへ失敗を返す。

## 結果

良くなること:

- 入力完全性と出力完全性の責務境界が明確になる
- exit 0、空poll、空reportを単独の成功・失敗根拠にしなくなる
- 最終回答がJSONLにある実行を新規reviewとしてやり直さず回収できる
- 同じreview packageの一括＋分割二重読込を完了条件で拒否できる
- モデル、推論強度、resume、完了根拠を`manifest.json`から監査できる

諦めること・既知のリスク:

- 初回reportはMarkdown契約なので、見出し・終端fieldの厳密な生成をmodelへ要求する必要がある
- JSONLのcommand stringを厳格に解析してvalidator実行を識別する実装が必要になる
- 任意agent、Web UI、一般retry、複数provider、review範囲の自動選択は初回に含まれない
- 外部modelを呼ぶintegration testは通常suiteへ入れず、fixtureとstubで状態機械を検証する
- runner自身のpath、process、private成果物処理はuser input、external integration、permissionsの
  security boundaryに該当するため、実装完了前にTerra + highの意味レビューが必要になる

## 根拠

- OpenAI Docs: https://developers.openai.com/codex/noninteractive
- OpenAI Docs: https://developers.openai.com/codex/cli/reference
- `docs/adr/0010-codex-adaptive-model-routing.md`
- `docs/adr/0011-codex-cross-model-handoff.md`
- `.superpowers/handoffs/codex-model-routing-review-execution-reliability.md`
