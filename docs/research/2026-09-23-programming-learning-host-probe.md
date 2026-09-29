# コード学習拡張の実装・実ホスト検証

実施開始: 2026-09-23。継続: 2026-09-24、2026-09-28、2026-09-29。

## 検証する範囲

承認済みの[設計](../superpowers/specs/2026-09-21-programming-learning-integration-design.md)と
[実装計画](../superpowers/plans/2026-09-22-programming-learning-integration.md)に従う。
保存CLIの決定的検査、両ホストの配布経路、実際のモデルによる対話、実ユーザーの成長は別々に判定する。
この文書は実施途中の記録であり、準備した項目を成功として数えない。

## 環境と分離

- ローカルCLI: Codex 0.155.1（9月28日）/0.158.0（9月29日）、Claude Code 2.1.274（9月23日）/2.1.283（9月28日、いずれも`--version`で確認）。
- macOS付属Python: `/usr/bin/python3 --version` は 3.9.6。
- `~/.claude/bin/learning-store.py` と `~/.codex/bin/learning-store.py` は、どちらも本設定repoの同じ実装へ解決する。
  これは配布pathの確認であり、保存成功の証拠ではない。
- ホストごと・シナリオごとに一時Git repoを分け、`probe/learning-runtime`ブランチを使用する。
- fixtureのテストはキャンセルされた操作の結果が既存の状態を変更しない外部挙動を要求する。
  通常依頼のpromptには故障箇所や正解を含めない。
- 通常のホスト設定・providerを維持し、学習bindingだけ一時的な`XDG_CONFIG_HOME`へ向ける。
  権限不足・認証失敗・対話機能の不足はそのまま記録し、設定を迂回して成功扱いしない。
- 模擬回答と試験用recordは使い捨てstoreにだけ保存する。本人の能力や保持の証拠へ加算しない。
- 生のJSONL、入力、終了code、session ID、cwd、差分は一時領域で回収する。
  公開文書には秘密情報や実HOMEの内容を転載せず、必要な観測だけを記す。

## 実施状況

| 検証 | 状態 | 判定の根拠 |
|---|---|---|
| CLI helpと両ホスト入口 | 確認済み | version、exec/resume/stream-jsonのoption、同じsourceへのpath解決 |
| 保存CLI・Python 3.9実動 | 関連49件成功 | `/usr/bin/python3`、ResourceWarningをerrorにして再検証 |
| 両ホスト入口から同じstoreへの保存・冪等再送 | 成功 | 親がPython3.9.6で6コマンド実行、全て終了0。下記の保存結果を照合 |
| 実Codex対話 | 複数scenarioを一部確認 | Investigateの継続とReviewの開示順、Predict競合、skip・未設定、中断再開を確認。初回は答え漏れや保存失敗も再現して修正。既定ON、上限・後日候補、転移は未確認 |
| 実Claude Code対話 | 追加実施しない | 9月28日の学習OFFは修正・検証を完了。ユーザーの運用はCodex中心で、Claude Codeは契約対象外のため、以降の対話検証を停止 |
| CLI securityレビュー | 再レビュー済み | 9月29日の追加レビューはMedium 2件・Low 1件。directory lockとmarker v2へ変更後、同じGPT-6 Sol/high担当が3件解消・Lowの移設時競合リスク1件・Confidence sufficientと報告 |
| 最終統合レビュー | 未実施 | sandbox修正と学習ルール変更後に独立担当が実施 |
| 旧記録の公開監査 | 全件読了・3件を抽象化 | 原文99件のhash照合。Terraが1〜60、親が61〜99の本文を全文確認。ユーザー承認後に3件を更新 |
| 専用repoへの旧記録移管 | 未実施 | CLI検証・レビュー後、更新済み原文のhashを取り直して実施 |
| 実ユーザー5〜10件pilot | 未観測 | 模擬対話では代替しない |

## 事前に固定した対話観点

- 通常の修正依頼から適格なInvestigateが発火するか。
- 本人の行動と理由を分けて待ち、誤答が続いても固定回数で完成解を引き取らないか。
- 同じ能力に設計Predictとコード学習が重なった場合に二重出題しないか。
- Review等の対象解説が本人の提出・理由より先に漏れないか。
- OFFは学習operationを作らず完了し、skip後は理由や転移を強制しないか。
- binding未設定を一度通知し、未保存を明示しながら通常作業を完了できるか。
- 中断・再開で担当範囲とevent_idを保ち、上限や後日確認候補を正しく扱うか。

実行できないscenarioは理由付きで未検証とする。ホストの終了0だけでは成功とせず、
assistant本文・tool event・fixture差分・保存結果を照合する。

## 9月28日の実ホスト観測と運用範囲

使い捨てrepoに失敗するテスト2件を用意し、通常のhost設定・providerでCLIを起動した。
Codexへの「急ぎ、学習なし」依頼では、モデルが失敗1件を再現し、分岐を修正して
2件成功まで検証した。storeのoperation・recordはともに0件だった。
回答には`★ Insight`の補足が含まれたため、学習OFF時の表示規約との整合は継続確認する。

Codexへの通常の修正依頼では、モデルが学習候補を認識したが、指定された
`~/.agents/skills/code-learning/SKILL.md`を読み込めず、演習を見送って自力で修正した。
この時点でmanifestにはskillが登録済みだったが、実HOMEの配布先にリンクが無かった。
9月28日にCodex用のリンクを配置し、新しいsessionで同じ種類の依頼を再検証した。
モデルはskill本文を読み、失敗を再現したうえで修正前にInvestigate課題を提示して停止した。
正解コードや原因箇所はこのターンで開示せず、storeのoperation・recordも0件だった。
模擬応答で「スキップ」と返すと、理由説明を要求せず、通常の修正とテスト2件の成功まで進めた。
スキップ後もoperation・recordは0件だった。最初のskill未配布による見送りは、
skill適用後の発火品質の判定には使わない。

store未設定の別sessionも起動したが、初期tool実行後にCodexの利用上限が発生し、
最終messageが無いままturnが失敗した。このscenarioは未検証とし、失敗を
「未設定でも正常に進めた」という証拠へ読み替えない。Investigateの提出・理由・
誤答再試行・転移・記録保存も未検証のまま残る。

Claude Codeは9月28日に学習OFFを一度試し、修正と2件の検証を完了した。
ユーザーはClaude Codeを通常利用せず、以後の実機検証はCodexに絞ると指定した。
Claude Code側の学習ON・保存・再開の検証は保留し、必要が生じたときの検討事項とする。

### 9月28日の追加Codex実測

利用上限解除後、同じ通常providerを使い、`gpt-6-sol` / `high` のfresh sessionで
3回試した。最初の2回は取消時に誤った結果を採用する小さいfixtureで、
1回はbinding未設定、もう1回は使い捨てstoreへbinding済みだった。
3回目は古い非同期完了通知が結果を公開するfixtureで、binding済みだった。
いずれもskill本文の読込と失敗テストの再現、AIによる修正とテスト成功を確認したが、
Investigate課題は提示せず、本人の回答待ちにも移らなかった。
よってこの3回をコード学習の発火成功に数えない。

非同期fixtureのJSONLでは、モデルが保存CLIを`rg --files`と`find`で探索した。
`~/.codex/bin`はこのrepoの`bin`へのsymlinkであり、`find`の既定では配下を辿らず、
既存の`learning-store.py`を発見できなかった。実際のpathは親が`ls -ld`で確認し、
同じ`XDG_CONFIG_HOME`で直接`status`を実行すると`state:active`、`writable:true`を返した。
モデルは`status`を実行せず、未保存の通知もせずに修正した。これは共通方針の
「候補前のstatus」「保存不能なら一度通知」と食い違う実機観測である。
入口を探索に依存させないため、両ホストのCLI pathを直接指定するruleと契約テストを追加した。
修正後の別sessionでは`status`が成功し、AIが本人へコード変更を依頼する文まで進んだ。
ただしAIがproductionに教材用TODOを追加し、対象関数と判定条件を先に伝えていた。
240秒のrunner制限に達して`turn.completed`も無いため、正常な課題提示の成功には数えない。
skillへ、未知の原因を本人が調べられるときはInvestigateを優先し、教材用TODOを
productionへ追加しない規約を補った。

その後のfresh session（thread `01a0e75d-0e85-77a2-9361-f2a62a443501`）は、
直接`status`でactive/writableを確認し、失敗テストを再現した。最終回答で原因箇所や
完成解を示さず、本人に次の観測を一つ選ばせて`turn.completed`となった。
fixtureの製品コードは無変更。模擬観測を同threadの次turnへ送ると、
「なぜ`ticket`とその時点の`_current`を比較しようと考えた？」と一問だけ返し、
27.3秒で`turn.completed`となった。模擬入力の前後でfixture差分は増えず、
storeのrecords/operationsは各0件だった。
本人の実提出・理由・再修正・転移・record保存は未観測。

同threadの3ターン目へ、理由として誤った予想と「どう直せばいいですか？」を
模擬入力した。Codexは予想を実行して反証したが、本人に再調査を返さず、
`★ Code Delta`で原因と修正方針を開示し、使い捨てrepoの製品コードとテストを
自分で変更した。`turn.completed`、終了0、テスト2件成功でも、学習継続の契約には
失敗した。操作・能力recordは0件で、本人の成功には数えない。
このターンのJSONLには通常のdebugging skillの読込があり、進行中の
code-learning skillの再読は無かった。新規候補の入口だけが明示されていた
`rules/code-learning.md`へ、継続ターンもskillを再読し、助言要求を明示的な
実装引取りと扱わない条件を追加した。静的契約はRED→GREENで13件成功。
この段階では実ホストでの修正効果は未確定だった。

新しい使い捨てsessionで再検証を始めたが、並行する全suite実行中に
PreToolUse hook内のGit確認が5秒でタイムアウトし、必須ruleとskillの読込が
複数回ブロックされた。`status`も`NOT_CONFIGURED`を返し、配布・環境条件が
前回と一致しなかった。終了0で最初の調査依頼を返したが、この試行は
ルール修正の有効性を示す証拠から除外した。

全suite終了後、さらに別のfresh Codex session（thread
`01a0e851-36e0-7811-9ccb-576977b02475`）で3ターンを再試行した。
最初は原因を区別する観測を本人へ依頼し、2ターン目は模擬観測の理由を
一問だけ尋ねた。3ターン目へ前回と同じ誤った理由と「どう直せば」を送ると、
モデルはcode-learning skillを再読し、実行した観測差を一つ示して本人の
次の調査を待った。全ターン終了0・`turn.completed`、使い捨てrepoの
製品コード差分なし、records/operations各0件。修正前と同じ場面で
担当を維持した一例だが、一般的な遵守率や本人の習得を示さない。
このfresh sessionではCodex内の`status`が`NOT_CONFIGURED`を返した。
親から同じ一時`XDG_CONFIG_HOME`を明示して直接・`rtk proxy`の両方で
`status`を実行するとactive/writableだった。ローカルCodex設定は
`shell_environment_policy.inherit = "core"`で、起動元の一時変数が
tool commandへ継承されない。OpenAIの[設定リファレンス](https://learn.chatgpt.com/docs/config-file/config-reference)は
環境継承の範囲と`set`による個別注入を定義している。
使い捨てrunnerへ`-c shell_environment_policy.set.XDG_CONFIG_HOME=<一時path>`を
追加して別のfresh Codex sessionで`status`を実行すると、終了0・
`state:active`・`writable:true`になった。先の`NOT_CONFIGURED`は
probe側の環境伝播不足と判定する。3ターンの学習対話自体は
保存不能を一度通知して進めたため、record保存の実機検証には使わない。

全suiteはsandbox内でlocalhost bindとGit署名agentの制約により16件エラー。
権限昇格後にGit署名を環境変数で無効化すると、runtime fixtureがその変数を
部分的に除去して4件エラー。署名無効の一時Git設定ファイルへ切り替えると、
全495件中2件がGit user identity不足でエラー、他493件は成功した。
一時設定へ検証用name/emailを足すと残る2件は単独再実行で成功。
同じ設定で全495件を一括再実行すると、494件成功・1件失敗、1040秒。
失敗は未追跡の`skills/synced/`がskill manifestの分類対象に入るため。
このディレクトリは他作業の所有物であり、変更・stageしない。
追加した継続ルールの静的契約13件はPython 3.9で別途成功した。
全suite成功とは表現しない。
macOS Python 3.9で関連49件、`bash -n setup.sh`、`git diff --check`は成功した。
最終変更後、Python 3.9で学習契約・instruction graphの39件、
`bash -n setup.sh`、`git diff --check`も終了0だった。

最初の実Codex子processは外側のCodex sandbox内で`Operation not permitted`により起動失敗した。
同一コマンドを承認済みの権限昇格で再実行すると正常終了した。拒否された個別操作は未特定。
この環境制約による失敗を製品の学習機能の失敗に数えない。

## 9月29日のCodex Review対話

Codex 0.158.0の`exec`と`exec resume`のoptionをhelpで再確認し、通常providerの
`gpt-6-sol` / `high`で、別の使い捨てGit repoからfresh sessionを起動した。
repoには非同期完了のfixtureと失敗する契約テストだけを置き、Reviewの依頼には
原因箇所・正解を含めなかった。既存の別fixture repoには「テストを修正せよ」という
局所指示があったため使わず、新しいrepoを作成した。使い捨てstoreへのbindingは
一時`XDG_CONFIG_HOME`を`-c shell_environment_policy.set.XDG_CONFIG_HOME`で
tool環境まで渡した。初回の子process起動は外側sandboxで`Operation not permitted`と
なり、承認済みの権限昇格で同じ入力を実行した。

thread `01a0e865-9cfb-7d20-86bb-46cb0537dd0b`の4ターンはいずれも終了0・
`turn.completed`を回収した。各turnの入力・JSONL・最終message・前後のGit statusは
一時ログに保存した。

| turn | 模擬入力と実際の停止 | 観測 |
|---|---|---|
| T1 | 本人が指摘と理由を説明するまで解説を待つReview依頼。モデルはコードとskillを読み、気になる箇所の指摘を待った | 原因や模範解の先出しなし。store `status`はactive/writable、製品コード差分なし |
| T2 | `cancel()`で現在値を消す箇所だけを指摘。モデルは「なぜ気になったか」と一問だけ返した | 理由や解説の先出しなし。製品コード差分なし |
| T3 | 「現在値を消すので旧完了は無視される」という誤った理由。モデルは既存テストを実行し、旧完了の値が反映されたという観測を一つ示して再調査を依頼した | `★ Code Delta`・修正コードの開示なし。既存テストは失敗、製品コード差分なし |
| T4 | 保持した識別子が公開処理へ渡り、現在値と照合されずに結果を書き換えると説明。モデルは`★ Code Delta`で観測と初回予想との差を返した | 既存テストの失敗を再確認。製品コード差分なし。使い捨てstoreへcode recordを1件作成 |

T3のテスト実行でfixture repoに未追跡の`__pycache__/`だけが生成された。
追跡対象の製品コード・テストには4ターンを通してdiffが無い。T4のrecordは
`initial_result: fail`、`retry_result: pass`、`transfer_result: not_attempted`で、
AIがテストを実行した支援を明記し、本人がテストを設計・実行したとは記していない。
operationsは0件。入力はすべて模擬利用者の回答であり、recordは使い捨てstore内だけの
実ホスト動作証拠である。実ユーザーの能力向上や保持の証拠には加算しない。

この例では正答後に転移確認を提示せず、`not_attempted`で終了した。転移を問う適切な
条件を作れなかったという証拠は無く、転移確認の自動開始は未検証とする。
Reviewの中断・再開、同一能力の競合、保存不能、上限・後日候補も未検証のまま残る。
4ターンの合計はinput 1,357,546 tokens（cache済みを含む）、output 11,192 tokens。
これは1つの模擬scenarioの観測値であり、一般的な運用コストの推定には使わない。

## 9月29日の追加Codex対話とsandbox修正

通常providerのCodex 0.158.0、GPT-6 Sol/high、使い捨てGit repoとstore、
隔離`XDG_CONFIG_HOME`で各scenarioをfresh sessionから実行した。子Codexの
app-server初期化は外側sandboxで失敗したため、承認済み権限昇格で再実行した。
入力、JSONL、最終message、終了code、前後のGit statusは一時ログへ保存した。

- store未設定のsessionは`status`の`NOT_CONFIGURED`を確認し、一度通知して課題を提示した。
  続く模擬「skip」では理由や転移を強制せず、通常の修正と2件のテスト成功まで進んだ。
  このfixtureには学習recordは作られていない。
- 同一箇所の設計Predictとコード読解が競合するsessionでは、初回の問いが原因箇所を
  先に開示した。共通ruleに開示境界を追加した後のfresh sessionでは、失敗の外部観測と
  A/B選択だけを提示し、選択後の理由を別turnで求めた。二重出題はなく、
  使い捨てstoreにdecision recordが1件保存された。初回の失敗は消さない。
- 中断・再開の初回sessionでは、ruleがoperation保存を明示しておらず、
  学習担当を維持したもののoperationsは0件だった。共通ruleに同一event IDの
  `started`、`interrupted_by_user`、`resumed_by_user`保存を追加した。
- 追加後の最初のfresh sessionは、保存CLIが`.git`内のlockを開けず
  `WRITE_FAILED`となった。Codexの`workspace-write`は追加した書込可能rootの
  `.git`も保護する。lockをstore直下へ移し、通常file・単一link・owner・modeを
  検査する実装と`.gitignore`を追加した。isolated Codex sandbox内からの
  operation保存は`created:true`になった。`status`の`writable:true`だけでは
  この失敗を検出できなかった。
- 最終fresh sessionのthread `01a0eb82-c1d5-7cc3-9904-ded91e040e49`は、
  明示的な学習ON依頼で原因を区別する観測を本人へ尋ねた。初回・中断・再開の
  3ターンはいずれも終了0・`turn.completed`。storeには同じevent ID
  `5f6b0d5e-5a6f-44a4-9bfb-ec107f477c9c`のoperationが3件あり、
  `wait_count`は0→1→1。再開後も原因や完成修正を開示せず、同じ調査行動を
  本人に選ばせた。tracked製品diffと能力recordは0件。

明示的に学習ONと指定しないfresh sessionで、skillとactive storeを読んだ後も
演習を始めずAIが修正した例がある。既定ONの安定した発火は未証明。
模擬回答・模擬中断は実ユーザーの成長証拠ではない。上限、後日候補、
転移の自動提示は実ホストで未確認。Claude Codeの追加対話は実施しない。

追加security reviewは、(1)旧CLIと新CLIでlock先が分かれる、
(2)Git cleanが無視対象のlockを保存中に消せる、(3)既存storeにGit除外規則が無い、
と報告した。macOSとCodex sandboxでdirectory自体の`flock`を実測し、
lock fileを廃止した。markerをversion 2へ上げ、旧CLIが新storeを拒否する方式に変更した。
Python 3.9のstoreテスト40件、契約・指示28件、補足の排他3件が成功した。
同じsecurity担当は3所見の解消を確認し、移設中に同じuserがstore rootを差し替える
場合のLowリスクを残した。移設時は全保存処理を止める運用へ明記した。

公開用ローカルstoreを提案場所に作り、旧記録99件のbytesとmanifestの
source commit・path・SHA-256を全件照合した。同一importの再実行は`created:false`。
その後、旧lock・暫定lock・directory lockを同時に取得してmanifestとbindingを
再確認し、markerをversion 2へ移した。旧lock fileと暫定`.gitignore`は除去した。
通常の`codex exec` fresh sessionでは、マシン固有の書込可能root設定だけで
store内の一時file作成・削除が終了0となった。補助の`codex sandbox -P :workspace`は、
別cwdからstoreへの書込を拒否し、storeをcwdにすると成功した。補助コマンドの
失敗を通常execの書込失敗へ拡張しない。実storeへの学習record保存とGit remote反映は
まだ行っていない。

## 両ホストの保存入口の実測

Task4の実装commit `058de55` 後、設定repo外の一時作業repoをcwdにして実行した。
空のGit sourceをimportすると0件manifestが確定し、markerが`prepared`から`active`へ遷移した。
両ホストpathの`status`はroot、store_id、state、writableまで一致した。

- store_id: `8b511e21-5813-4688-bdc2-ad134aeefd91`
- 1回目のoperation保存（Claude入口）: `created:true`
- 同一入力の再送（Codex入口）: `created:false`、同じid/path
- 保存されたoperationは1fileのみ。
- 保存bytesのSHA-256: `151312851ae868e3fa8b29ad4c52a582ecbb98a074697fceb2c31ee9e2c35707`
- 6コマンドともstderrは空、終了0。

これはインストール済み入口から実CLIを呼んだ結果であり、Claude/Codexのモデルが
自ら学習を開始・保存した実対話の証拠ではない。

## レビュー入力の不備と再開条件

初回のsecurity-reviewerへはhandoff・設計と固定snapshotのpathを渡したが、
このroleはvalidator以外のコマンド実行を許されず、ソースpathから本文を取得できなかった。
`Confidence: insufficient`で返却されたため、問題なしとは扱わない。
コード全文・完全差分・親が固定snapshotで実行した31件の検査結果をreview packageへまとめ、
SHA-256付きでvalidatorから全文を取得できるようにした。
これはモデルの推論能力の不足ではなく入力形式の不足であり、同じTerra/highで再レビューする。
リポジトリのsecurity-review-policyに従い、再開前にユーザーへ判定不能の結果を提示し、
「同じ担当で再レビューする」という回答を受けた。再レビューはConfidence sufficientで完了した。

所見は (1) Git環境の継承、(2) `active` markerだけでmanifest無しのrecord成功、
(3) 保存先ディレクトリの検査と作成の間の差替え、(4) 入力と記録の大きさの無制限読込。
うち (2) は使い捨てstoreで再現した。`init`後にmarkerのstateだけを`active`へ変更すると、
manifest 0件にもかかわらず`status`が`writable:true`、`record`が成功終了した。
これは取込照合完了後だけ保存するという設計契約に反する。
他の所見は攻撃者が変更できる環境と、既存権限の境界を分けて評価してから修正する。

その後の修正を含む現行コードについて、別のsecurity-reviewerは入力資料不足で
`Confidence: insufficient`と返した。コード全文、前回所見後の差分、
検証ログをvalidatorで読める約3962行のpackageへ固定し、
`rules/security-review-policy.md`に従ってユーザーの再レビュー確認を得た。
GPT-6 Sol/highの担当は3文書を全文読み、CLI・Git・公開記録・配布境界を
読み取り専用で再評価し、`Confidence: sufficient`、具体的な新規所見なしと報告した。
これは未実施の対話scenarioや最終統合レビューの代替ではない。

## 旧記録の移管前に残す判断

既存の公開状態だけを、新しい公開repoへの移管可否の根拠にはしない。
公開用の抽象化基準に照らし、業務環境の具体的な構成を記した記録と、由来未確認の
コード参照子を確認中。資格情報の値の検出とは区別する。
一般的なサービス名・HTTPステータス・ログ項目名だけを問題とは判定しない。
数値を含む技術的な障害記録についても、業務由来と断定できる根拠がない場合は
機密情報と決めつけない。2件の明示的な社内接続構成と1件の由来未確認のコード参照子は、
学習上の意味を保った抽象化案を用意した。
2026-09-24にユーザーが「3件を抽象化してから移管する」と明示承認した。
「旧本文は変更しない」という移管方針の例外として、準備した案で元の3件を更新した。
引用を変更した箇所は「公開用に抽象化」と表示し、原文引用のままと誤認させない。
import自体は本文を改作せず、更新済み原文のhashを取り直してそのbytesを照合する。
