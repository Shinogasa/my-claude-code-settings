# Codex親工程ルーティングの運用引継書

更新: 2026-09-22。現行判断は[ADR 0016](adr/0016-codex-parent-routing-pilot.md)。
コード学習の実装など、実際の作業で不具合が出たときは本書から調査を再開する。

## 普段の使い方

- 分割できる作業: 検証済みhandoffを、modelとreasoning effortを明示したsubagentへ渡す。
- 親工程を移す作業: 明示ペアのfresh sessionを開始する。期待ペアでhandoffを`validate`し、
  固定`INPUT_DIGEST`のvalidator `read`でhandoffと参照文書を全文読む。
- 旧pendingからの復旧: Codexへ「モデル切替を診断して」「切替待ちを取り消して」と依頼する。

`diagnose` / `cancel`はこのrepoの`bin/codex-model-switch.py`のサブコマンドである。
Codexがlocal shell toolから実行する。利用者に別Terminalへの手入力を要求する運用ではない。
標準CLIの`codex diagnose`を追加したわけでもない。hookの復旧contextには絶対repo、session ID、
transition IDを埋め込んだ実行commandが入る。

```bash
python3 ~/.codex/bin/codex-model-switch.py diagnose --repo <絶対repo> --session-id <ID>
python3 ~/.codex/bin/codex-model-switch.py cancel --repo <絶対repo> --session-id <ID> --transition-id <transition-id>
```

新規`begin`は常にexit 2で拒否する。旧grantの有無やhook配送にかかわらず、新しいmanifestは作らない。
`diagnose`は`same_thread_begin_enabled: false`と保存状態を返す。配送receiptは過去の観測であり、
今のguard稼働・両軸のruntime保証を表さない。

旧`PREPARING` / `SWITCH_PENDING`では通常promptを復旧依頼として受け付けるが、通常local toolは
停止を維持する。status / diagnose / transitionが一致するcancelと既存handoff操作だけを許す。
旧resume / override / publishも互換のため残す。cancel後に`CANCELLED`とregistry解除を確認して
通常作業へ戻る。ACTIVEの次checkpointも新規beginへ戻らず、標準経路で処理する。

## 実測の範囲

### 現行修正で確認したこと

Codex CLI 0.155.1、隔離`HOME` / `CODEX_HOME`、一時Git repo、認証不要のlocalhost mock providerで
`tests/test_codex_model_switch_runtime.py`の4ケースを実行した。

1. 実UserPromptSubmit / PreToolUse配送後もbeginはexit 2。manifest / registry / grantを作らず、
   通常のファイル作成は続行できる。
2. 旧PREPARINGをfixtureで再現してpublishし、実runtimeで旧pendingの通常promptを配送する。
   `touch`を拒否して対象fileが存在しないこと、diagnoseがpendingを返すこと、cancelが状態とregistryを
   更新すること、その後の`touch`は成功することを同じturnで照合する。
3. 旧pendingを明示resumeするとACTIVEへ遷移し、provider requestのmodelは`gpt-5.6-sol`となる。
   model証拠は`hook-observed`、effortと全体tierは`user-attested`のまま維持する。
4. hookを`/usr/bin/python3`（ローカル3.9.6）で実行し、深くネストしたreceipt JSONを与える。
   実UserPromptSubmitが`blocked`となり、provider request数が増えず、pendingを維持する。

各ケースで`hooks/list`のsource path、current hash、enabled / trustedと、実`hook/started` /
`hook/completed`のevent ID、thread / turn / session、結果を照合する。
旧状態のfixture作成は移行データの準備であり、新規begin成功や実modelの自発的判断の証拠ではない。
関連unitテストでは古い完全一致grantの流用拒否、復旧commandの引数制限、ACTIVEから別repoへ移動した
後の配送receiptを確認する。全体の検証結果はマージPRにも記録する。

### 未検証・保証しないこと

- Desktop/CLIとhosted modelによる通常タスクの完走。mock providerの成功をhosted inferenceへ拡張しない。
- 自然文から実modelが正しく復旧commandを選ぶこと。runtimeテストはproviderが返すcommandを固定する。
- 旧Desktop threadでの未配送原因。Active/trusted表示だけで原因や復旧成功を断定しない。
- fresh sessionの起動から両軸のloaded設定、handoff読了までを結び付けた実タスクの完走。
- hosted/special toolの完全停止、hook未承認・無効・timeout・実行不能時の強制。
- 同一UIDの悪意ある並行操作に対する完全なTOCTOU防御、クラッシュを挟むmanifest / registry更新の
  原子性、大規模な同時操作。安全なパス検査はOSの隔離境界の代わりではない。
- review runner本体の実装・稼働。現状のreviewは検証済みhandoff付きの明示ペアagentを使う。

## 過去の不具合と再調査の入口

### 未消費grantの再利用（549aebcまで）

隔離App Serverでrouting hookの後に別の拒否hookを置く。beginのgrant発行後、後続hookが元commandを
拒否する。turnを終了しApp Serverも閉じ、次のUserPromptSubmit配送を挟まず同じCLIを直接実行すると
PREPARINGを作れた。現行版では新規beginを停止している。将来再開する場合はこの反例を実runtimeで
防ぎ、grantを実行そのものへ束縛すること。TTLの追加やActive表示だけでは再開しない。

### Python 3.9の深いJSON

receiptへ`[`を1500個、`0`、`]`を1500個書くと旧版はRecursionErrorでexit 1となり、runtimeが
promptを配送した。現行版はJSON読込とhook最上位で捕捉して拒否する。Python最新版だけでなく、
実際にhookが使うinterpreterでも再現すること。

### ACTIVEのまま別repoへ移動

旧版はsessionの以前のbindingを配送receiptにも記録した。現行版は実cwdのrepoを記録する。
ただしpendingでのrepo外移動は引き続き拒否する。この場合は元repoをcwdにしたCodex sessionで
対象の元session IDを使って診断・取消する。壊れたregistry / manifestや不正receiptがある場合は
自然文の配送自体が拒否され得る。新しいsessionで元repoを指定し、保存状態を診断する。
削除・上書きによる推測修復はせず、採取したエラーから個別に対処する。

## 更新とhook trust

setupはCLI・hook・配線をリンクする。自分の設定との競合がある場合はsetupの結果を確認する。
`/hooks`で承認状態を確認し、新しいsessionの実配送で確認する。
trust hashはhook定義のhashであり、参照するPythonファイルすべての内容hashではない。
定義変更時は新しいhashへの承認が必要になり得る。handlerだけの変更で必ず再承認になるとは
説明しない。preflight receipt内のPython hook hashも、Codexのtrustを代替しない。

## 不具合時に集める項目

同じ試行について、次を記録する。

- commit、Codex版、surface（Desktop / CLI / App Server）、新旧thread
- session ID、thread ID、turn ID、hook event ID、started / completedとstatus
- hooks/listのsource、current hash、enabled / trusted
- diagnose / statusの結果、manifest遷移、実際のcwd
- provider requestが送られたか、toolの結果、作成されるはずのfileの有無

credential、秘密、token、個人情報、会話全文は公開repoへ保存しない。必要な識別子は一貫した仮名へ
置換する。証拠が採れなかった項目は「未確認」と書く。検査不能を成功として扱わない。

## 次のpilot: コード学習実装

- 工程境界でmodelとeffortを再分類し、現在の親ペアを惰性で継承しない。
- 検証済みhandoffを固定digestで全文読む。マージ前のhandoffはGit鮮度が変わるため作り直す。
- 明示ペアの実装と必須security / integration reviewまで進め、所見と実測を記録する。
- 不具合は上記採取項目と最小再現を添えて改善する。未検証事項を全て解消することをpilot開始条件にしない。
