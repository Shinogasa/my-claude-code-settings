# Codex親モデル切替の実行境界と先行例（2026-09-21）

## 調査の問い

親セッションの工程変更に合わせてモデルを選び直す運用はCodexで成立するか。
今回の`MODEL_SWITCH_RESUME`が進まなかった原因と、現在のテストで欠けた証拠を分ける。
本書は調査結果と改設計の入力である。後続実測と採用判断はADR 0015に記録する。

## 今回の観測

- 学習ブランチ上で`begin → handoff validate → publish`が成功し、manifestは`SWITCH_PENDING`になった。
- ユーザーはcomposerで`gpt-5.6-sol / high`へ切り替えた。該当turnのローカル`turn_context`にも同じペアが記録された。
- チャットに完全一致の`MODEL_SWITCH_RESUME`が2回送られ、いずれの後もmanifestは`SWITCH_PENDING`のままだった。通常のチャットとlocal toolも進められた。
- `/hooks`には`UserPromptSubmit 1/1`、`PreToolUse 3/3`がActiveと表示され、設定には該当hookのtrusted hashがあった。repo版と配布版のPythonのSHA-256も一致した。
- このthreadの作成は9月18日。親切替の配布commitは9月20日で、配布版hookの作成は9月21日。古いthreadがhook設定を保持している可能性がある。
- ユーザーの中止指示に基づき、この遷移は`CANCELLED`へ更新した。学習ブランチの設計commitはremoteへ保存済み。

これらから、**このthreadでhookによる再開を観測できなかった**ことは確定する。
hookが一度も呼ばれなかったか、呼ばれて拒否・失敗したか、あるいは異なるsession IDやruntime設定を見たかは、hookのイベントログと実入力を採取していないため未確定。
古いthreadに設定が反映されなかったという説明は、時系列と整合する仮説であって確定原因ではない。
`/hooks`のActive表示を、このthreadで`UserPromptSubmit`が実行された証拠として扱ったことが運用上の誤りだった。

## 新規threadでのruntime実測

2026-09-21にCodex CLI 0.154.0のApp Serverを、使い捨て`HOME` / `CODEX_HOME`、
一時Git repo、credentialを使わないlocalhost Responses mock providerで起動した。
`hooks/list`ではmodel switchの`SessionStart`、`UserPromptSubmit`、`PreToolUse`がすべて
`enabled: true` / `trusted`で、sourceは隔離HOMEの`hooks.json`だった。

`thread/start`が返したroot thread IDとsession IDはともに
`01a0c3cf-2490-7dd2-833c-23bc4b6a4bf8`だった。このIDでmanifestを
`SWITCH_PENDING`にし、通常promptを送ると、event ID
`user-prompt-submit:6:<isolated-CODEX_HOME>/hooks.json`の`hook/completed`は
`blocked`となり、manifestは`SWITCH_PENDING`を維持した。続いてturnのmodel / effortを
`gpt-5.6-sol` / `high`として完全一致の`MODEL_SWITCH_RESUME`を送ると、同eventは
`completed`となり、manifestは同じsession IDの`ACTIVE`へ遷移した。保存された証拠は
`model_evidence: hook-observed`、`effort_evidence: user-attested`、
`verification_tier: user-attested`だった。model inferenceはlocalhost probeで中断しており、
hosted inferenceの成功を示す試験ではない。

PreToolUseは別のfresh thread `01a0c3e4-5eaf-75d0-9401-cdb76cf15fb6`で測った。
最初のpromptの`UserPromptSubmit`に続き、modelが出した完全一致の`begin` commandに対して
event ID `pre-tool-use:0:<isolated-CODEX_HOME>/hooks.json:call_c356998b5f47496ba84285cddbb9ba44`
が`completed`となり、同じsession IDのmanifestを`PREPARING`へ作成した。次のmodel応答に
`touch forbidden.txt`を返すと、event ID
`pre-tool-use:0:<isolated-CODEX_HOME>/hooks.json:call_f1f2f404ddea40f18a65b4059bbe3fbb`
は`blocked`となり、target fileは作成されなかった。

この試行中、sandboxの`python3`がmacOS標準Python 3.9.6を指し、validatorの
実行時type alias `Path | int`をimportできない問題も観測した。`typing.Union`へ変更後、
同じruntime sequenceで`begin`はexit 0となった。またCodex 0.154.0ではPreToolUseの
`updatedInput`を前提にCLIへtokenを注入する方式が実コマンドへ反映されなかったため、
hookが同一turn・repo・session・hook hash・begin引数へ束縛したone-time grantを保存し、
元のbegin commandが直接消費する方式へ変更した。

以上から、fresh App Server threadでは実hook配送と状態遷移が成立することが確定した。
一方、旧Desktop threadで失敗した原因は未配送、session ID差、設定保持、surface差のどれかに
まだ絞り込めず、fresh試行の成功を「古いthreadが原因だった」という断定には使わない。

このsequenceは`tests/test_codex_model_switch_runtime.py`へ固定した。テストは現行hookのhashを
`hooks/list`から取得して隔離configだけでtrustし、event ID、thread / turn / session ID、model、
manifest遷移、副作用fileの不在を照合する。`codex` CLIが無い環境ではskipする。

```bash
python3 -m unittest tests.test_codex_model_switch_runtime -v
```

## Codexの機能境界

- 公式[Codex CLI](https://developers.openai.com/codex/cli/)は`/model`でモデルと推論強度を選ぶ手段を示す。AIが同一親threadのモデルを自動変更するAPIを、この資料は示していない。
- 公式[Hooks](https://developers.openai.com/codex/hooks)は、`UserPromptSubmit`のprompt・現在modelとブロック出力、`PreToolUse`のlocal tool guardを定義する。hook入力には推論強度が無い。信頼済みの設定の列挙と、対象threadでeventが完了したことは別の観測である。
- 公式[Subagents](https://developers.openai.com/codex/subagents)ではspawn時にmodelとreasoning effortを明示できる。親を変更せずに、分割可能な作業を別ペアへ渡せる。
- Codex本体の[session実装](https://github.com/openai/codex/blob/main/codex-rs/core/src/session/session.rs)は、sessionが持つ有効feature集合を生存期間中不変と記述している。ただし本件の既存threadに、hookが実際にどの時点で読み込まれたかまでは証明しない。

## 見つかった先行例

| 例 | ルーティング箇所 | 今回への示唆 |
|---|---|---|
| [codex-model-router](https://github.com/Saadfk/codex-model-router/blob/main/docs/codex_model_router.md) | タスク起動前のlauncherで親のmodel/effortを選ぶ。別途spawn hookで子を補完 | 親の初期選択はできるが、開いているDesktopタスクの送信済みpromptは移動できないと明記 |
| [codex-orchestration](https://github.com/razor-ai/codex-orchestration/blob/main/plugins/codex-orchestration/skills/codex-orchestration/references/providers-and-models.md) | 既に選ばれた親をcontrollerとし、子に明示ペアと作業packetを渡す | 主眼はsubagent経由の配分。hostごとの能力実測を要求 |
| [Codex Delegation Deployment](https://github.com/Concrete333/Codex-Delegation-Deployment) | skillで委譲判断と子のモデル選択を案内 | 指示遵守だけで発火や配送は保証できないと明記 |

探索範囲はOpenAI公式のHooks・Codex CLI・Subagents、本体session実装、公開GitHubで見つかった上記ルーター・skillの一次資料。
この範囲では、**同一親threadの途中で同期hookとprivate manifestを必須にする同型の公開実装は確認できなかった**。
公開されていない運用、検索語で見つからないrepo、別providerのgatewayを含めれば反証され得る。網羅的な不在主張ではない。

## テストで見落とした境界

`tests/test_codex_model_switch.py`は一時Git repoと実Python subprocessを使い、合成したhook payloadに対する状態遷移を検証している。
このテストはparser、handoff検証、manifest操作の回帰には有効だった。
一方、Codex runtimeが現在のthreadでhookを読み、`UserPromptSubmit`を発行し、結果を採用したことは検証していない。
設計計画にあった「実機smoke」はhook scriptへの直接入力であり、hook runtimeを通る試験ではなかった。

追加すべき境界試験は次の三つ。

1. 新規threadで、`hooks/list`のActive表示に加え、実promptの`hook/started`・`hook/completed`とmanifestの`ACTIVE`化を観測する。
2. hook導入前から続くthreadで同じpromptを送り、設定一覧と実行結果の差、または正常な再読込を観測する。
3. pending中の通常promptと対象local toolが実際に拒否されるか確認する。`rtk codex exec`の終了コードだけで判定せず、hook event、状態、model応答の有無まで照合する。

全試験でsession ID、hook source、model、event status、manifestの遷移を同じ試行へ結び付ける。
credentialや実業務repoを使わない隔離HOME・一時repo・local mock providerを優先する。

## 改設計の選択肢

### A. 親の通常作業は軽い案内、子は明示ペア、厳密な親移行はfresh session（推奨）

親は新タスク・大きな工程境界でペアを再評価する。通常作業は既存親を継続し、分割可能な探索・実装・レビューを明示ペアのsubagentへ渡す。
親自体の変更が重要で残作業が大きいときは、検証済みhandoffを作って新規sessionを指定ペアで開始する。
同一threadの切替はUIで行える場合もあるが、hookの実行証拠が無ければ`hook-observed`や強制済みを名乗らない。
この案は現在の`SWITCH_PENDING`の手詰まりを避け、Codexの確認済み操作と先行例に近い。
新規sessionの引き継ぎと追加操作は残る。

### B. 現在の厳密な同一thread gateを維持し、事前のevent実行証拠を必須にする

`begin`より前に、**このsessionの実`UserPromptSubmit`が動いた**証拠を作り、未確認ならpendingを作らずfresh sessionへ案内する。
合成payloadテストに加え、対象Codex surfaceのend-to-end試験を必須にする。
gateを維持できる可能性がある一方、hook再読込・失敗・special toolを含むsurface差を管理し続け、通常の工程切替が重くなる。

### C. launcherで全親タスクを開始前に分類する

既存の公開例に近いが、現在のcomposerから始まる作業は捕捉できない。
分類用の追加model呼出し、別起動経路、現行プロバイダ制約の検証が必要で、今回の設定repoの既定には重い。

採用判断前に、新規threadでの実hook deliveryを一度測る。Aを選ぶ場合も、既存pendingの停止条件とcancelの復旧手段を文書・CLIで明確にする。
ADR 0014の採用範囲を変える際は新ADRに却下案と理由を残す。

## 採用判断

新規threadで配送可能なことは確認できたが、reasoning effortをhookから観測できず、旧threadの
失敗原因も未確定である。このため選択肢Aを標準経路として採用する。分割可能な作業は明示ペアの
subagentへ渡し、親ペア自体が保証条件なら検証済みhandoffでfresh sessionへ移す。
同一thread gateは標準経路にせず、同じturnの実`UserPromptSubmit`と`PreToolUse`を
one-time grantで証明できた場合だけ使える補助経路として残す。詳細はADR 0015を正本とする。
