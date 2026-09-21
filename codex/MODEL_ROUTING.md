# Codex サブエージェントのモデルルーティング

サブエージェントを起動するたびに、タスクの現在の状態を分類し、`model` と
`reasoning_effort` を必ず同時に指定する。片方だけを指定して実行時既定へ委ねない。

## 初期値

分類できない通常作業は `gpt-5.6-luna` + `medium` を使う。
`~/.codex/config.toml` の `[agents]` にも同じペアを設定し、指定漏れのバックストップにする。

## 基準ペア

| 状況 | model | reasoning_effort |
|---|---|---|
| 手順が一意な機械作業 | `gpt-5.6-luna` | `low` |
| 明確で反復可能な通常作業 | `gpt-5.6-luna` | `medium` |
| 複雑なロジック、仮定確認、エッジケース、狭い一次確認・再レビュー | `gpt-5.6-luna` | `high` |
| 対象は狭いが特に難しい推論 | `gpt-5.6-luna` | `max` |
| 広い読み取り調査、大きなファイル、コードベース探索 | `gpt-5.6-terra` | `medium` |
| 複数レイヤーをまたぐデバッグ、統合判断、通常の意味的セキュリティレビュー | `gpt-5.6-terra` | `high` |
| 曖昧で多段の設計、アーキテクチャ、最終統合レビュー | `gpt-5.6-sol` | `high` |

custom agentを使う場合は、そのTOMLに固定された基準ペアを適用する。明示spawn値より
custom agentファイルが優先されるため、別ペアが必要なら一致するroleを選ぶか、固定roleを
使わず明示ペアで起動する。

## セキュリティレビュー

OpenAI公式のcorrectness/security reviewer例に合わせ、必須の通常レビューは
`security-reviewer`の`gpt-5.6-terra` + `high` + `read-only`で行う。Luna highは、対象と
確認観点が絞られた狭い一次確認・再レビューには使えるが、security boundaryに一致する変更の
必須レビューを単独では満たさない。

重大・多層・曖昧でSol highによる追加レビューが必要な場合、またはレビューがCritical findingか
`Confidence: insufficient`を返した場合は、`rules/security-review-policy.md`に従って人間へ
確認する。標準レビューから上位モデルへ黙って切り替えない。

## 自律的な昇降

開始時だけでなく、調査結果や失敗原因が変わるたびに再分類する。

- 推論の深さ不足: 同じモデル内で `low` → `medium` → `high` → `max` と上げる
- 探索範囲不足: effortを上げ続けず、LunaからTerraへモデルを上げる
- 設計判断不足: 要件が曖昧、多段のトレードオフ、最終統合判断ならSolへ上げる
- 作業が明確・局所的・機械的になった: 後続agentをLuna mediumまたはlowへ降格する
- 失敗した: 回数だけで昇格せず、証拠から深さ不足・範囲不足・権限／環境問題を分類する

高いtierを親から子へ惰性で継承しない。各agentへ必要最小限の文脈だけを渡し、同じ結果を
より低いペアで安全に得られる段階では降格する。

## 親セッションの工程境界

親AIも新しい実質的taskの調査後、承認済み成果物から別工程へ移る時、現在ペアの能力不足が
証拠から分かった時に、次工程のmodelとeffortをペアで再分類する。同じペアなら続行する。
単発の読み取り、同じ受入条件内の局所debugやtest再実行だけでは切替を開始しない。
降格は、検証済みhandoffだけで次工程へ着手できる安定した境界で行う。

別ペアが必要なら、SessionStartが通知する`session_id`で次を行う。

1. `python3 ~/.codex/bin/codex-model-switch.py begin --repo <絶対repo> --session-id <ID> --task-id <task> --current-phase <工程> --next-phase <工程> --model <model> --effort <effort> --handoff .superpowers/handoffs/<task>.md`を実行する。
2. 指定handoffをschema 1で作り、`validate-codex-handoff.py validate`を期待ペア付きで実行する。`codex-model-switch.py publish --repo <絶対repo> --session-id <ID>`がGit鮮度とINPUT_DIGESTを再確認して`SWITCH_PENDING`へ移す。
3. 親AIはtransition ID、handoff path、対象ペア、切替操作を示してターンを終える。ユーザーが`/model`またはアプリのcomposer下でmodelとeffortを両方選び、次の一行だけを送る。

```text
MODEL_SWITCH_RESUME <transition-id> <model> <effort>
```

hookが観測するmodelと申告ペアが一致し、保存digestとGit鮮度が維持されれば、通常工程を
`user-attested`として再開する。effortはhookから観測できないため、これはruntime設定の
機械的な両軸証明ではない。再開後、作業前にvalidatorの`read`でhandoffと参照文書を
全行取得する。hook自体は読了を証明しない。`runtime-config-verified`は同一threadと
両軸のloaded設定を確実に結び付けられるまで生成しない。

切替を明示的に取り消す場合は`MODEL_SWITCH_CANCEL <transition-id>`を送る。対象工程だけ
現在ペアで進める明示指示は、理由を付けて
`MODEL_SWITCH_OVERRIDE <transition-id> <next-phase> <reason>`を一行で送る。
overrideはそのtask・工程・session・handoff digestに束縛し、次checkpointまたはcancelで
失効する。cancelではsessionとrepoの対応を解除し、同じsessionの通常promptを再開できる。
provider、sandbox、permissions、必須security review、人間確認境界は変えない。

`PREPARING`では指定handoffの編集とvalidator・状態CLIだけ、`SWITCH_PENDING`では
validator readと状態照会だけをlocal toolへ許す。`UserPromptSubmit`と`PreToolUse`の
同期hookが拒否を返すが、hook未承認・無効・timeout・実行不能、hosted toolと特殊tool経路を
完全には強制できない。`/hooks`で承認と実行状態を確認できない場合、guard稼働を確認済みと
表示しない。manifestはrepoの`.superpowers/model-switch/`、sessionとrepoの対応は
`CODEX_HOME/model-switch-registry/`へowner-onlyで保存し、pending中のrepo外cwdは拒否する。
指定handoffの編集はsymlink・hardlinkを拒否し、相対patchはrepo rootのcwdからだけ許す。
ローカルのCodex CLI 0.154.0では、拒否理由は対話画面に表示されたが、`codex exec --json`は
通常promptの拒否時も終了0・空turnを返した。自動実行では終了コードだけで成功と判定せず、
`status`で状態を確認する。
ペア自体を保証条件とする工程は明示ペアでfresh sessionを起動し、handoffと
Git鮮度を移行先で検証する。security reviewと最終integration reviewはreview runnerの
明示ペアで行う。

## モデル間handoff

実装、探索、修正、セキュリティレビュー、最終レビューを別モデルへ移す前、およびモデルや
推論強度の昇格・降格・再レビューで実行主体を変える前に、必ずMarkdownのhandoffを作る。
会話履歴だけを引き継ぎとみなさない。

Superpowersのtask briefまたはreview packageがある場合は、そのファイルを要件・差分の正本として
再利用し、handoffの`requirements_path` / `review_package_path`からSHA-256付きで参照する。内容を
handoffへ複製しない。該当する成果物が無い場合は`none`にし、
`.superpowers/handoffs/<task-id>.md`の本文を正本にする。

handoffにはschema 1のfrontmatterとして次を記録する。

- `task_id`
- `branch`、完全な`head`、`worktree_fingerprint`
- `target_model`、`target_reasoning_effort`
- `requirements_path`、`requirements_sha256`
- `review_package_path`、`review_package_sha256`

本文には次の空でないsectionを置く。

- `目的と対象外`
- `Git状態`
- `確定済み設計判断と根拠`
- `対象ファイルと作業所有範囲`
- `受入条件と検証コマンド`
- `制約`
- `未解決事項`
- `実行モデル`
- `返却レポート契約`

作成側は次でGit識別子を取得し、Markdown作成後、spawn前に`validate`を成功させる。

```bash
python3 ~/.codex/bin/validate-codex-handoff.py state --repo <repo>
python3 ~/.codex/bin/validate-codex-handoff.py validate <handoff> \
  --repo <repo> --expected-model <model> \
  --expected-reasoning-effort <effort>
```

受信側custom agentは最初の操作として`validate-codex-handoff.py validate`を実行し、handoff、
task brief、review packageを全文読む。欠落、空欄、古さ、矛盾、参照hash不一致、期待する
modelとeffortの不一致・実行不能なペア・dirty submoduleがあれば、推測で補わず
`NEEDS_CONTEXT`を返す。初回検証の`INPUT_DIGEST`を保持し、handoffと参照成果物はpathから
直接読まず、同じdigestを指定したvalidatorの`read`経由で全行を取得する。長い成果物は
`--start-line` / `--line-count`で分割し、全chunkの取得が終わる前に作業を始めない。
validatorは受信前処理で外部Git helperを実行しない。作業途中で別モデルへ再移行するときは、
現在のGit状態と未解決事項で新しいhandoffを作り直す。

## ユーザー確認の境界

通常のモデル・推論強度の昇降では確認しない。AIが作業の品質と総コストを見て自律選択する。
ユーザー確認が必要なのは、次の既存境界に一致するときだけである。

- `rules/security-review-policy.md` が人間確認を要求する重大所見または判断不能
- 不可逆・破壊的な操作
- merge、push、publishなど、規約上先に確認する外部副作用
- ユーザーが明示した予算上限、provider、モデル制約を超える必要がある場合

## providerと失敗時の扱い

モデルルーティングは接続先を変える権限ではない。現在の `model_provider` を変更しない。
tool引数が欠落する、選んだモデルをproviderが提供しない、設定ペアが拒否される場合は、
別providerへ黙って切り替えずfail-closedで停止し、観測した事実と代替案をユーザーへ示す。
