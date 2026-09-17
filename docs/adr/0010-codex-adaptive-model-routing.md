---
adr: 10
date: 2026-09-14
status: accepted
---

# Codexサブエージェントのモデルと推論強度を適応的に選ぶ

## 背景

サブエージェントのモデルだけを固定し、推論強度を省略すると、選んだモデルの実行時既定が
使われる。実測では狭い読み取り調査をLunaへ委譲した際、推論強度を指定しなかったため
`xhigh`で起動し、軽量workerとしては規約確認と探索が膨らんだ。既存8 roleのうち、
`model_reasoning_effort`を明示していたのは2 roleだけだった。

OpenAI公式資料は、subagentのモデルと推論強度を明示spawn、`[agents]`の既定、または
custom agentファイルで設定できるとしている。推論強度はmediumを通常の均衡点、highを
複雑なロジック・仮定確認・エッジケース、maxを特に難しい推論に位置づける。モデルは、
Lunaを明確で反復可能な作業、Terraを広い探索、上位モデルを曖昧で多段の仕事に使い分ける。
同じ公式資料のcustom agent例は、correctness・security・test riskを扱うreviewerに
`gpt-5.6-terra` + `high` + `read-only`を指定している。

## 決定

- custom agentは、役割ごとの再現可能な基準値として`model`と
  `model_reasoning_effort`の両方を必須にする
- 今回は既存roleのモデルを維持し、推論強度だけを明示する。公式例がある
  `security-reviewer`だけTerra + highへ是正し、他7 roleのモデル再評価は別タスクで行う
- 指定漏れのバックストップはLuna + mediumとし、`setup.sh`が既存
  `~/.codex/config.toml`の`[agents]`へ2キーだけを安全に設定する
- 親AIはタスク開始時と状態変化時に再分類し、モデルと推論強度を必ずペアで選ぶ
- 推論の深さ不足なら同一モデル内でeffortを上げ、探索範囲不足ならLunaからTerraへ上げる
- 曖昧で多段の設計・アーキテクチャ・最終統合レビューだけSolへ上げる
- security boundaryに一致する通常の意味レビューは、公式例に合わせて
  `security-reviewer`のTerra + high + read-onlyで行う。Luna highは狭い一次確認・
  再レビューに限定し、単独では必須レビューを満たさない
- 作業が明確・局所的・機械的になった後続工程はLuna mediumまたはlowへ降格する
- 失敗回数だけでは昇格せず、深さ不足・範囲不足・権限／環境問題を証拠から分類する
- 通常のモデル・推論強度の昇降はAIが自律判断する。ユーザー確認は既存のセキュリティ、
  不可逆操作、外部副作用、明示された予算・provider・モデル制約の境界だけで行う
- モデルルーティングを理由に現在のproviderを変更しない。選択したペアを使えない場合は
  別providerへ黙って切り替えず、fail-closedで事実と代替案を示す

custom agentファイルは明示spawn値より優先されるため、固定roleと異なるペアが必要なら、
一致するroleを選ぶか、固定roleを使わず明示ペアで起動する。

この決定は、ADR 0004のセキュリティレビュー発火境界と人間確認の境界を維持し、
同ADRの背景16〜17行目、決定26〜28行目、結果62〜66行目にある
`security-reviewer`をLunaへ固定したモデル選択・軽量モデル前提だけを置換する。重大・多層・曖昧で
Solによる追加レビューが必要な場合、またはCritical finding・判断不能を検出した場合は、
ADR 0004どおり上位モデルを自動起動せず人間へ確認する。

## 検討した代替案

### A. Luna + maxを全subagentの既定にする

採らない。モデル単価が低くても、単純作業まで推論時間とトークンを増やす。maxは対象が狭い
難問への昇格先として残し、通常作業は公式の均衡点であるmediumから始める。

### B. モデルだけを固定し、推論強度は実行時既定へ委ねる

採らない。モデルを下げてもeffortが高い値へ解決されると、コスト制御の意図が崩れる。
実測したLuna + xhighがこの失敗例である。

### C. 失敗回数だけでLunaからTerra、Solへ順に上げる

採らない。権限不足やprovider互換性の問題はモデルを上げても直らない。推論の深さと探索範囲を
別軸にし、原因を分類してから必要な軸だけを上げる。

### D. 推論強度やモデルを上げるたびにユーザーへ確認する

採らない。通常の実行判断で作業を頻繁に止め、ハーネスへ委譲する価値が下がる。
既存の安全境界とユーザーが明示した制約を越えない範囲はAIが自律選択する。

### E. custom agentの固定値を廃止し、毎回すべて動的に指定する

採らない。指定漏れと親の高価な設定の継承を検知しにくい。固定値はroleの再現可能な基準、
動的ルーターはrole選択と明示spawnペアを担当する二層構造にする。

### F. `security-reviewer`をLuna + highのまま維持する

採らない。狭い一次確認としては低コストだが、公式のcorrectness/security reviewer例は
Terra + highを使っている。認可や秘密情報など複数ファイルの意味関係を扱う必須レビューを、
低コストだけを理由にLunaへ固定しない。

## 結果

良くなること:

- 全roleでモデルと推論強度の組み合わせを静的検査できる
- 指定漏れがLuna + mediumへ倒れ、高価な親設定を暗黙継承しない
- 深さと範囲を別々に上げ、機械工程では下げるため、品質と総コストを両立しやすい
- セキュリティ意味レビューは公式例と同じTerra + highを基準にし、Lunaレビューを
  補助的な一次確認として明確に区別できる
- provider変更や安全境界はモデルルーティングから分離される

諦めること・既知のリスク:

- 分類と再分類は文章契約であり、AIの遵守に依存する
- モデル間のコンテキスト移行はADR 0011のMarkdown handoff契約で補強する
- custom agentの固定値が明示spawnより優先されるため、role選択を誤ると意図した動的ペアにならない
- security reviewer以外の固定ペアは暫定値であり、品質・待ち時間・コストの比較をまだ終えていない
- gatewayがtool引数を保持しない状態では、正しいペアを選んでもspawnへ伝達できない。
  この場合はルーティングで回避せず、gatewayの互換性問題として扱う
- モデル世代が更新されたら、基準ペアと公式の位置づけを再評価する必要がある

## 後続のコード学習モードとの接続制約

このADRの採用後に検討を始めたコード学習モードには、モデルルーティング側でも扱うべき
横断的な懸念がある。安価なモデルへ実装を委譲した場合、そのモデルが学習対象の選定、
AI生成コードの模範判定、ユーザー回答の採点、専門的な定石の説明まで兼ねると、同じ誤りを
生成と評価の両方で見逃し、誤った説明を学習内容として固定する閉ループになりうる。

一方、現時点の調査は「弱いモデルほど必ず誤る」とは示していない。モデルtierを安全性の
証明にせず、実際の対象言語とrepositoryから作った代表ケースで、誤feedback率、正しいコードへの
誤警告率、根拠なし一般化率、費用、時間を比較する必要がある。

後続設計では、次をルーティング要件として再検討する。

- 安価な実装agentには、機械的な候補検出、検証可能なlearning packet作成、決定的検査を残す
- 教材選定、模範コードの妥当性確認、採点、専門的feedbackは、必要な能力を持つread-only agentへ
  限定的に昇格する
- 局所的なコード意味とedge caseはTerra + high、architecture、design pattern、複数成立解の評価は
  Sol + highを初期候補とするが、正式routeは代表ケースevalで決める
- compiler、test、static analysis、benchmark、一次資料で確認できない主張は、上位モデルの
  自然言語説明だけで正解にしない。確認不能なら学習イベントを見送る
- cross-model移行ではADR 0011の検証可能なhandoffを再利用し、会話要約だけで教材文脈を渡さない
- code-learning用教師agentは、通常のverificationやsecurity reviewを代替しない

また、現在はrouting文書がarchitectureをSol + highへ分類する一方、`code-architect` custom agentは
Luna + highに固定されており、custom agentの固定値が明示spawn値より優先する。ADR本文で既に
他roleのモデル再評価を後続taskとしているため、この暫定不一致を解消するまでは
「設計工程は全経路でfrontier modelにより実行される」と保証しない。

コード学習側の調査、根拠、反証条件、learning packet案、routing eval案の正本は
`docs/research/2026-09-16-code-learning-mode-design.md` の「モデルルーティングとの統合」とする。
本節はその内容を複製する仕様ではなく、ルーティング作業を再開したときに接続検討を落とさないための
索引である。コード学習モード自体の採用や具体的な教師roleは、このADRでは決定しない。

## 根拠

- OpenAI Docs: https://developers.openai.com/codex/subagents
- `docs/adr/0004-codex-runtime-enforcement-policy.md`
- `docs/adr/0005-codex-personal-profile-mcp-inheritance.md`
- `docs/research/2026-09-16-code-learning-mode-design.md`
- Codex CLI 0.154.0でのLuna未指定effortが`xhigh`へ解決された実測
