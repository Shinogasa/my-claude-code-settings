---
date: 2026-09-16
status: draft-reviewed
implementation_status: not-started
related_research: 2026-09-15-mattpocock-skills-evaluation.md
routing_review_date: 2026-09-16
implementation_plan_date: 2026-09-17
---

# コード理解・レビュー能力を育てる学習モードの設計検討

> この文書は実装仕様の候補と、その根拠・反証条件を残す調査資料である。
> ルールやskillの導入決定を表すADRではない。実装前に設計を再確認し、
> 正式な判断は `docs/adr/` に採用案と却下案を記録する。

## 要約

現行の `rules/learning-mode.md` は、不可逆性・競合する選択肢・一般化可能性を持つ
設計判断を鍛えるために作られている。L2以上の判断点がある場合はL1実装で発火しないため、
境界、依存方向、運用などの上位判断を優先できる一方、コードを読み、レビューし、修正する
能力を継続的に練習する用途には構造的に向いていない。

コード学習は現行ルールへ統合せず、次の二層構成で独立させる案を採用候補とする。

1. 短い常時ルール `rules/code-learning.md` が発火候補とOFF条件を検出する
2. 詳細な `skills/code-learning/SKILL.md` が演習とフィードバックを実行する

演習形式は、学習対象とユーザーの現在地に応じて次の優先順位で選ぶ。

1. ユーザーが本質的なコードを書く
2. ユーザーがAIのコードを変更する
3. ユーザーがAIのコードをレビューする
4. AIが最後に解説する

ここでの目的はタイピング量を増やすことではない。コードの挙動、依存、失敗条件、
変更影響をユーザー自身が生成し、実行可能な検査または一次資料で即時に確かめ、
小さな別条件へ転移できる状態を作ることである。

モデルルーティング導入後は、安価な実装モデルがコード学習の候補検出から採点までを
一貫して担当しない。実装は安価なモデルへ委譲できるが、学習対象の選定、模範となるコードの
妥当性確認、ユーザー回答の評価、専門的フィードバックは設計・意味レビューに近い。
これらは後述の「教育的権限境界」に従い、必要な能力を持つ読み取り専用agentへ限定的に昇格する。

## 背景と目的

AIが実装の大部分を生成できても、利用者が出力を理解・評価できなければ、次が起きる。

- テストが通ったことを、意図どおり動くことと誤認する
- 依存方向、失敗経路、並行実行、リソース寿命などを追えない
- 障害時に仮説を立てられず、AIの修正をさらにAIへ評価させる循環になる
- デザインパターンや言語イディオムを名前だけ覚え、適用条件を判断できない
- 動いているが誰も説明できないブラックボックスを維持する

目標は「AIなしで全コードを書けること」ではない。AIが生成したコードについて、
少なくとも次を自力で行えることを目標とする。

- 実行前に主要な挙動と状態変化を予測する
- データ、制御、エラー、依存の流れを説明する
- 最も重大な欠陥候補と変更影響を優先順位づけする
- 検証可能なテストケースまたは観測方法を作る
- 言語・ライブラリ固有の定石と危険な書き方を見分ける
- パターンの適用条件と不適用条件を説明する
- AIの提案を採用、修正、却下のいずれかに判断できる

## 現行資産との関係

### 現行学習モード

`rules/learning-mode.md` の目的は判断基準の質を高めることである。発火には次を要求する。

- 後から変えるのが高くつく
- 成立する選択肢が競合している
- 別の文脈へ一般化できる
- 同じ作業にL2以上の判断がある場合、L1実装では発火しない

この条件は設計判断の選別には合理的だが、null処理、例外伝播、非同期制御、所有権、
コレクション操作、リソース解放などの学習価値を拾えない。これらは後から安全に変更できたり、
実装方針が実質一つだったりしても、コードレビュー能力には不可欠だからである。

したがってコード学習では「判断の不可逆性」ではなく、次を中心に選ぶ。

- 正しさ、変更容易性、デバッグ可能性への影響
- 他のコードでも使える理解か
- ユーザーがまだ実証していない能力か
- 小さく真正な演習にできるか
- 結果または根拠を検証できるか

### 既存のコード参加

現行ルールには、ユーザーが5〜10行を書く「コード参加」がPredictの代替として存在する。
ただし設計判断と同じ発火条件を使い、L2優先ゲートの下にある。そのため新しいコード学習と
併存させると、同じ箇所で二種類の参加要求が発火する可能性がある。

実装時は、現行のコード参加を次のどちらかに整理する必要がある。

- 推奨: コードを書く学習を新skillへ完全移管し、現行ルールには参照だけ残す
- 代替: 現行コード参加をL2以上の設計判断をコードで表現する場合だけに限定する

二重発火を防ぎ、責務を説明しやすいため、完全移管を第一候補とする。

### 保留中のレビュー訓練モード

`tasks/backlog.md` には、2026-08-14に設計された次の未実装案が残っている。

1. AIが実装する
2. ユーザーが初稿をレビューする
3. AIのレビューを開示する
4. 見つけた・見逃した・的外れをDeltaで分類する

この案は、今回の「変更する」「レビューする」に包含できる。ただし今回の案は、可能なら
AIが本質部分を書く前にユーザーへ渡すため、常に「AIが先に実装する」とは限らない。
実装時は古いbacklog項目を独立実装せず、新しいコード学習skillへ統合した旨を記録する。

### TDD・検証・セキュリティskill

コード学習は実装プロセスの品質規約を置き換えない。

- TDDが適用される変更では、production実装を書く前に失敗するテストを用意する。学習対象を
  テストケースの設計にするか、redを確認した後の最小実装にする
- コード学習中の局所検証は、タスク完了前のverificationを置き換えない
- 認証、認可、秘密情報、外部入力、決済などでは、security reviewの判断を優先する。
  未知の危険な実装をユーザーへ無支援で書かせる演習にしない
- systematic debuggingが適用される場合、原因仮説と測定の順序を崩さず、コード学習は
  trace、仮説説明、回帰テスト作成のいずれかへ接続する

したがって `code-learning` は「どう学ぶか」を所有し、TDD、debugging、security、verificationは
「どう安全に実装・検査するか」を所有する。

### teach

`mattpocock/skills` の `teach` は、専用workspaceで一つのmissionを複数sessionにわたり学ぶ
明示起動型skillである。実作業中の短いコード学習イベントとは責務が違う。

| 観点 | コード学習モード | teach |
|---|---|---|
| 起動 | 実装・修正・レビュー中に条件を満たすと候補化 | ユーザーが明示して開始 |
| 単位 | 実際の変更から選んだ一つのコード能力 | missionに沿った一つのlesson |
| 文脈 | production作業と同じコード | 専用のteaching workspace |
| 主目的 | その場で理解、検証、転移する | 数週間以上の体系的な習得と保持 |
| 記録 | 実証したコード能力と未解消のgap | MISSION、資料、lesson、理解証拠 |

二つを自動同期しない。コード学習で同種のgapが繰り返し観測された場合だけ、
「体系学習候補」として抽象化して記録する。ユーザーが望んだときに、その候補を入力として
teachの専用workspaceを作る。通常の開発repoや本設定repoをteaching workspaceにしない。

teachの直接導入は決まっていない。採用前に、固定commitを再確認し、既知の出力先問題、
初回assessment、復習スケジューラ不在、引用の検証方法を補う必要がある。詳細は
`docs/research/2026-09-15-mattpocock-skills-evaluation.md` を参照する。

## 検討した構成

### A. 現行 `learning-mode.md` へ統合する

利点は、ON/OFF、回数上限、記録を再利用できること。欠点は、設計判断とコード技能で異なる
発火条件を一つの規則へ詰め込み、L1抑制ゲートを例外だらけにすること。責務が曖昧になるため
採用しない。

### B. 独立した常時ルールだけで完結させる

発火条件、演習、記録を `rules/code-learning.md` にまとめる。発火経路は単純だが、
コードを書かないタスクにも長い教育手順が常時入り、既存の長いルール群との競合や
コンテキスト消費が増えるため採用しない。

### C. 短い常時ルールと詳細skillへ分ける

常時ルールは「いつ詳細skillを読むか」だけを判断し、教育手順は必要時にskillから読む。
発火の見落としを抑えつつ、段階的に詳細を開示できる。ユーザーは2026-09-15にこの構成へ
同意した。現時点の採用候補とする。

## 提案アーキテクチャ

### `rules/code-learning.md`

常時有効にする短いポリシー。将来含める内容は次に限定する。

- 目的: AI生成コードを理解・レビュー・修正できる能力を育てる
- デフォルトONとタスク単位のOFF条件
- コードを作る、直す、レビューするタスクで発火候補を探す義務
- 候補を検出したら、実装の本質部分を確定する前にskillを読む義務
- 機械的変更、生成物、ボイラープレートなどの除外
- 1イベントでは学習対象を一つに絞ること
- `rules/learning-mode.md` と `skills/code-learning/` の責務境界

Claude Codeでは `paths:` のないruleとして常時読み込ませる。Codexでは起動時必須読込一覧へ
追加する必要がある。ホスト固有のツール名はrule本文へ埋め込まず、停止方法だけホスト別に示す。

### `skills/code-learning/SKILL.md`

発火後に読むワークフロー。ルート文書は共通ループと振り分けに集中させ、言語別の細かな
イディオム集を大量に埋め込まない。バージョン依存の知識が必要なら、公式言語仕様、標準
ライブラリ、フレームワークの一次資料をその都度確認する。

将来、特定言語で繰り返し必要になる場合だけ、`references/` に言語別の確認観点を追加する。
一般論の巨大な「ベストプラクティス集」にはしない。

### 学習記録

現行の `learning/entries/` は判断エピソードを固定3軸で記録するため、同じ形式を使わない。
実装候補は `learning/code/entries/` のような別namespaceとする。

一件の記録は、少なくとも次を持つ。

- 能力・概念の正規名
- 抽象化した出題文脈
- 実施形式: write / modify / review
- ユーザーが実証したこと
- 未解消の誤解または弱点
- 検証方法と結果
- 転移課題の結果
- 将来の想起に使える短い問い
- teachで体系学習する候補か

活動ログやAIが説明しただけの内容は記録しない。PUBLIC repoのため、業務コード、内部パス、
顧客名、非公開の型名・データ名は抽象化する。記録の粒度と保存要否は正式設計時に再承認する。

## モデルルーティングとの統合

### 問題の分解

「弱いモデルでコード学習が発火する」という懸念は、少なくとも次の四つへ分ける。

1. 弱いモデルがproductionコードを書く
2. 弱いモデルが学習対象を選ぶ
3. 弱いモデルがユーザーのコードや説明を採点する
4. 弱いモデルが定石、パターン、効率、安全性を教える

1は通常の実装品質、TDD、verification、security reviewの問題である。コード学習固有の追加リスクは
2〜4にある。同じモデルがコードを生成し、そのコードを模範として選び、自分と同じ見落としを
含む基準で採点すると、誤ったコードと誤った説明が相互に補強される。もっともらしい説明が付くため、
単なる実装バグよりもユーザーの誤学習として残りやすい。

一方、弱いモデルへ候補検出を一切させないと、全実装タスクを上位モデルで監視することになり、
ルーティングの費用対効果を失う。したがって全工程の昇格ではなく、教育上の権限を分離する。

### 教育的権限境界

安価な実装モデルが担当してよいこと:

- 常時ruleの機械的な適格条件と除外条件を照合する
- 実際のdiff、関連コード、テスト結果、制約を学習候補packetへ集める
- 強い教師agentが確定した問い、足場、検証手順をそのままユーザーへ提示する
- compiler、test、lintなど決定的検査を実行し、結果を返す
- 教師agentが確定した修正を通常の実装workflowへ戻す

安価な実装モデルが単独で確定してはいけないこと:

- 何を「一流のエンジニアが知るべき定石」とみなすか
- AI生成コードを学習用の模範として採用してよいか
- ユーザーの理由説明が技術的・概念的に正しいか
- Factoryなどのパターンやアーキテクチャを採用すべきか
- 性能、安全性、並行性、リソース寿命、エラー意味論について一般則を教えること
- 検証できない主張を、確信度の表現だけで正解として扱うこと

ここで「強い教師agent」は特定モデル名ではなく、必要な能力と検証責務を表す。共有skill本文へ
特定ホストのモデル名を固定せず、各ホストのルーティング規約が具体的なモデルへ写像する。

### Codexでの初期ルーティング案

現在の `codex/MODEL_ROUTING.md` とCodex CLI 0.154.0の実測に基づく初期案は次のとおり。

| 処理 | 初期route | 理由 |
|---|---|---|
| 候補の機械的検出、packet作成、検査実行 | Luna + medium | 明確で反復可能な通常作業 |
| 局所的なコード意味、失敗経路、言語イディオムの検証 | Terra + high、read-only | 複雑なロジックとedge caseを扱う意味レビュー |
| モジュール境界、設計パターン、複数の成立解を含む採点 | Sol + high、read-only | 曖昧で多段の設計・統合判断 |
| 公式仕様で一意に決まり、決定的検査で証明できる単純課題 | Luna + highでも可 | 対象が狭く、採点基準を外部化できる |

これはモデル名による永久ルールではない。公式上の位置付け、利用可能モデル、pilot evalの結果が
変われば写像を更新する。特に「学習だから常にSol」とすると、単純な型エラーや境界値演習まで
最高tierへ移り、費用対効果が崩れる。逆に「production実装がLunaだから指導もLuna」とすると、
教育上の判断責務を実装工程へ誤って束ねる。

ローカル実測では `multi_agent` はstableかつ有効で、`step_model_switching` はunder developmentかつ
無効だった。したがって同一agentを会話途中で切り替える前提にせず、実装agentが読み取り専用の
教師agentをspawnし、その結果を受け取る構成を前提にする。将来runtimeが変わった場合は再実測する。

### 分岐元のrouting branchとの整合性

分岐元の `feat/codex-adaptive-model-routing` には、学習設計を接続する前に区別すべき暫定状態がある。

- `planner`はSol + highだが、`code-architect`はLuna + highに固定されている
- `codex/MODEL_ROUTING.md`はarchitectureをSol + highへ分類する一方、custom agentの固定値が
  明示spawn値より優先されるとも規定している
- ADR 0010はsecurity reviewer以外のrole再評価を後続taskへ明示的に送っており、この不一致を
  既知の暫定状態として受け入れている
- `tests/test_codex_model_routing.py`はrouting文書に各モデル名と分類語が含まれることを検査するが、
  task分類から実際に選ばれるcustom roleと固定pairの一致までは検査していない

したがって「設計は常にfrontier model、実装は常に安価なmodel」という性質は、現branchの全roleで
機械的に保証された状態ではない。コード学習だけに教師routeを足す前に、少なくとも
`code-architect`を使う条件とSol routeとの優先関係を解消する必要がある。

これは現在確認したrepository内のrouting文書、ADR、`codex/agents/*.toml`、routing testに対する
結論である。runtime側がrole選択を別途強制している、または未確認の外部gatewayが書き換えるなら
結論は反証される。その経路は今回のrepository調査では確認していない。

### 学習候補packet

教師agentへ渡す入力は会話要約だけにしない。ADR 0011のcross-model handoffを再利用し、少なくとも
次を検証可能な形で含める。

- 学習対象候補と、品質・転移価値への具体的な影響
- 対象diff、必要な周辺コード、repositoryの既存契約
- 外部から観測できる受入条件
- 実行済み検査と未検査事項
- ユーザーへまだ開示していない答えと、先に開示してよい制約
- 学習形式の候補: Write / Modify / Review / Explain
- security boundary、TDD、debuggingなど優先workflow
- 教師agentへ求める返却形式と、確信ではなく根拠を返す契約

教師agentはpacket不足、参照hash不一致、検証不能な技術主張を検出したら、推測で教材を作らず
`NEEDS_CONTEXT`または「今回は発火させない」を返す。学習機会の取りこぼしは許容するが、
誤った学習内容を確定する側へ倒さない。

### 強制昇格条件

次のいずれかに該当する場合、安価な実装モデル単独の指導を禁止する。

- 言語・標準ライブラリ・frameworkの挙動がcompiler/testまたは一次資料で未確認
- architecture、依存方向、design patternの適用・不適用を扱う
- security、並行性、キャンセル、性能、resource lifetime、error semanticsを扱う
- 成立する解が複数あり、ユーザーの理由をtrade-offとして評価する
- AI自身が生成したコードを模範または比較基準に使う
- 「効率的」「idiomatic」「保守しやすい」など、測定軸を明示しないと好みになりうる
- ユーザーの回答を誤りと判定する根拠が、同じモデルの自然言語説明しかない

security boundaryに一致する場合、コード学習用教師は必須のsecurity reviewを代替しない。
学習イベント自体を安全なReviewまたはTraceへ制限し、通常のセキュリティ規約を先に満たす。

### 教師agentの出力契約

教師agentは次を区別して返す。

- `verified_fact`: compiler、test、benchmark、一次資料、repository契約で確認した事実
- `repo_convention`: このrepositoryで観測した慣例。一般的ベストプラクティスとは呼ばない
- `engineering_judgment`: 複数案のtrade-off評価。唯一解のように書かない
- `unverified`: 未確認事項と、確認に必要な測定

性能を教える場合は計算量、allocation、I/O回数、benchmarkなど対象軸を必要とする。
短い記法を「効率的」と呼ばない。パターンを教える場合は名前より先に、解決する変更圧力、
追加される間接層、適用しない条件を確認する。

教師agentの自然言語評価はproductionコードの検証証拠に数えない。最終的なコードの正しさは、
既存どおり決定的検査と必要な意味レビューで確認する。

### ルーティングeval

導入前またはpilot開始時に、実際の対象言語とrepositoryから匿名化した代表ケースを作り、同じpacketを
候補モデルへ渡して比較する。公開benchmarkの総合点だけでrouteを決めない。

最低限のケース群:

- 正しいコードを誤って批判しないか
- syntaxではなく、境界値や深い論理誤りを特定できるか
- 存在しないAPI、言語仕様、性能特性を教えないか
- repository conventionと一般則を混同しないか
- パターンを不要な箇所へ適用しないか
- ユーザーの別解を、模範解答との差だけで誤りにしないか
- security、並行性、キャンセル、resource lifetimeの重大リスクを見逃さないか
- 根拠が不足したときに発火を見送れるか

評価は、可能な項目をcompiler、test、static analysis、benchmark、公式仕様との一致で採点する。
設計判断は事前にrubricと成立条件を固定し、少なくとも初期pilotでは人間がサンプル監査する。
同じモデルが教材を生成して採点する自己評価だけで合格させない。

route採用の判定には、少なくとも次を分けて記録する。

- 教えるべき問題の検出率
- 正しいコードへの誤警告率
- 技術的に誤ったfeedback率
- 根拠なしに一般則を述べた率
- 転移課題の妥当性
- 1イベント当たりのtoken、時間、費用

「TerraまたはSolなら安全」「Lunaなら危険」とは先に決めない。候補モデル間の品質差が実務上の
許容範囲内なら安いrouteを採り、差が大きい領域だけ昇格する。

## 発火候補の選び方

### 必須条件

次をすべて満たす場合だけ候補にする。

1. 実装、修正、リファクタリング、レビューのいずれかでコードを扱っている
2. 正しさ、変更容易性、デバッグ可能性、性能、安全性のいずれかへ実質的に関係する
3. 他の箇所や将来の仕事へ転用できる
4. ユーザーがまだ理解を実証していない、または以前のgapを再確認する価値がある
5. 小さく真正な課題へ切り出せる
6. 実行可能な検査か一次資料で、フィードバックの根拠を示せる

「高度に見える構文」「短く書ける構文」「有名なパターン名」であることは発火理由にしない。

### 優先する対象

- 正常系だけでは見えない失敗経路、境界値、部分失敗
- 例外・エラーの伝播と観測可能性
- 非同期処理、競合、キャンセル、リソース寿命
- 型によって不正状態を表現不能にする方法
- モジュール境界、依存方向、テスト用seam
- データ構造やアルゴリズム選択が性能へ与える影響
- 言語固有の安全で一般的なイディオム
- 短くても誤読、誤用、将来の事故を招きやすい書き方
- Factory、Strategyなどのパターンが解決する変更圧力と不適用条件

「効率的な書き方」は意味を固定する。実行時間、メモリ、記述量、レビュー時間、変更容易性は
別の軸であり、短いコードを自動的に効率的と評価しない。

### 発火させない対象

- 自動生成物、vendored code、lockfile
- ボイラープレート、機械的置換、formatterの差分
- 設定値、文言、単純な委譲だけの変更
- ユーザーが既に同能力を複数回実証し、転移にも成功している内容
- 真正な課題へ切り出せず、穴埋めのためだけに作る問題
- 検証根拠を用意できず、AIの好みを正解として教えることになる内容

## 学習ループ

### 0. 学習対象を一つに絞る

一つのイベントで、Factory、例外設計、非同期制御、テスト設計を同時に教えない。
タスクの成功に関係し、今後へ最も転移し、未習得であるものを一つ選ぶ。

概念名や模範解答は先に提示しない。ただし前提知識が不足して問題を理解できない場合は、
必要最小限の知識を先に説明する。誤答させることを目的にしない。

### 1. 足場を準備する

実際の作業ツリーへ、必要な範囲だけを準備する。

- 変更の目的と外部から観測できる契約
- 判断に必要な周辺コード
- 関数または型のシグネチャ
- 入出力、失敗時、性能などの制約
- 対象箇所を一意に示すTODOまたはdiff
- 必要ならテストの外枠。ただし答えを直接明かすassertionは避ける

### 2. 能動的な形式を選ぶ

次の順で、最初に成立する形式を選ぶ。

#### Write

ユーザーが本質的な5〜15行程度を書く。単なるAPI名の暗記ではなく、分岐、変換、依存、
エラー処理など、挙動を決める部分を渡す。広いクラスや機能全体を書かせない。

#### Modify

AIが書いた動作する初稿、または安全な練習用断片を、条件追加、依存分離、型改善、
エラー処理、性能改善などの目的で変更してもらう。productionへわざと欠陥を混入しない。

#### Review

ユーザーに、挙動予測、制御・データ・エラーの流れ、重大な欠陥候補、変更影響、必要な
テストのいずれかを問う。「自由にレビューして」ではなく、今回鍛える能力に焦点を絞る。

#### Explain

上の三形式が成立しない場合だけ、AIが解説する。解説だけで理解を実証したとは記録しない。

### 3. 理由を自己説明する

コードまたはレビュー回答の直後に、なぜその実装・指摘にしたかを一問だけ尋ねる。
回答例や観点一覧を同時に渡さない。ここで得たいのは正解の復唱ではなく、ユーザーが持つ
mental modelと誤解の位置である。

### 4. 事実を検証する

次の順で安い根拠を使う。

1. 型検査、compiler、unit test、property test、再現手順などの実行可能な検査
2. 言語・標準ライブラリ・フレームワークの公式資料
3. repositoryの契約、テスト、既存convention
4. 上記で決められない設計評価は、事実と判断を分けて明示する

AIの自己採点だけで正誤を確定しない。検査できない部分を「問題なし」に畳まない。

### 5. 専門的フィードバックを返す

フィードバックは、情報を詰め込まず次を扱う。

- ユーザーの説明と実際が一致した点
- 最も重要な差分または見逃し
- その差分がバグや変更コストになる条件
- 概念名、デザインパターン名、言語イディオム
- この場面で採る理由と、採らない方がよい条件
- レビュー時に再利用できる短い確認問い

パターン名は原則としてこの段階で供給する。先に名前を教えてコードを当てはめさせると、
問題を見て必要性を判断する練習にならないためである。

### 6. 小さな転移を確認する

元コードを暗記しただけでないことを確かめるため、条件を一つだけ変えた問いを出す。

- 入力が空、重複、巨大になった場合
- 依存先が失敗、遅延、再試行した場合
- 同期処理が非同期になった場合
- 実装を別の型・モジュールへ移した場合
- 同じ概念を使う短い別コードをレビューする場合

productionコードへ不要な変更を加える必要はない。回答、短いpatch、テストケースのいずれかで
確認する。転移に失敗した場合は、理解済みとして記録しない。

### 7. 実証したことだけ記録する

記録対象は、ユーザーが書いた、変更した、説明した、レビューした、転移できた内容である。
AIが解説した内容や、テストが偶然通っただけの実装は理解の証拠にしない。

## 難易度の調整

優先順位はWrite、Modify、Review、Explainだが、Writeを強制する順位ではない。

- 十分な前提と局所的な課題がある: Write
- 方針は理解しているが適用経験が薄い: Modify
- 初見のコードや複数要素が絡む: ReviewまたはTrace
- 前提概念そのものを知らない: 最小限のExplain後にModifyまたはReview

同じ概念で理解が進んだら、説明量を減らし、Write、制約追加、別文脈へのReviewへ移す。
逆に失敗が続く場合は、範囲を狭め、入出力例や部分実装を増やす。難易度を上げること自体を
成果にしない。

## タスク進行と安全性

- ユーザーは常にスキップできる。スキップ後はAIが実装を完成させる
- 「全部やって」「任せる」「急ぎ」「学習なし」などの明示で、そのタスク中はOFFにする
- ユーザーの実装を未検証のまま採用しない
- productionコードへ教材用の欠陥を意図的に仕込まない
- レビューで見つかった問題は完了前に修正し、検証する
- 学習イベント後も、通常の品質・テスト・セキュリティ規約を省略しない
- 学習のためにタスクの要求範囲を広げない

初期案では一つのタスクにつきコード学習イベントを最大1回とする。これは学習量を減らす
ためではなく、一つの能力へ十分な自己説明・検証・転移を行うためである。現行学習モードとの
合計停止回数は未決定であり、pilotで調整する。

## 学習効果の測定

説明回数、作業時間、ユーザーの満足度だけでは学習を証明できない。導入後は、少なくとも
5〜10件の適格な実装タスクでpilotし、次を観測する。

### 主指標

- 元コードと異なる小さな転移課題に成功したか
- 挙動、依存、失敗条件を根拠つきで説明できたか
- 欠陥候補へ対応するテストまたは観測方法を作れたか
- 同種のgapが再発したとき、必要な足場が減ったか

### 運用指標

- 発火候補数、実際の発火数、除外理由
- Write / Modify / Review / Explainの割合
- スキップ率
- 学習イベントで増えた時間と中断感
- 検証不能で見送った件数

### 判定上の注意

問題を選び、採点し、改善を主張する主体が同じAIであるため、自己評価には構造的な偏りがある。
可能な限りcompilerやtestの結果を使い、転移課題の事前条件を出題前に固定する。
設計・レビュー判断のように唯一解がない場合は、事実誤認とトレードオフ評価を分ける。

## エビデンスレビュー

### 支持される部分

| 根拠 | 観測されたこと | 本設計への限定的な含意 |
|---|---|---|
| PRIMM（Sentanceほか、2019） | 11〜14歳493人、13校と対照群を含むmixed-methodsで、Predict・Run・Investigate・Modify・Makeを評価 | 書く前にコードを予測・調査し、変更から作成へ足場を外す構造 |
| Chiほか（1989） | worked exampleから多く自己説明した学習者は、原理と例を結び付け、例に依存しない知識を示した | AIの説明を読むだけでなく、ユーザー自身の理由を生成させる |
| Oliほか（2024） | 大学生90人のRCTで、expert解説を読む条件とscaffolded self-explanationを比較。効果はprior knowledgeにより異なった | 受動的読解だけにせず、自己説明する。ただし一律強制せず難易度を適応する |
| Roediger & Karpicke（2006） | 散文教材で、再学習より想起テストが遅延後の保持を高めた | 後続タスクで短く思い出す仕組みを入れる。ただしコード技能への直接証拠ではない |
| CodeAid（Kazemitabaarほか、2024） | 700人、12週間、約8,000利用の教室導入で、直接解答を避けつつ認知的関与と制御を保つ設計課題を抽出 | 最初から完成コードを渡さず、ヒント、疑似コード、修正支援へ段階化する |
| TiCoder（Fakhouryほか、2024） | 15人のprogrammer studyで、テストを介した意図確認によりAI生成コードを正しく評価しやすくなった | コード理解を自然言語の納得だけで終えず、テストによる評価へ接続する |
| Bacchelli & Bird（2013） | Microsoftの観察・面接・570コメント・大規模surveyで、code/change understandingがreviewの鍵と報告 | Review演習で文脈、変更、依存、影響を説明する能力を中心にする |
| Rigby & Bird（2013） | 複数企業・OSSで、peer reviewによる知識共有のproxyが66〜150%増加 | レビューを欠陥検出だけでなく、コードベース知識の獲得として扱う |
| Silva & Costa（2025） | 4モデル、45件の学生解答から生成した190件のhintのうち、正確かつ完全だったのは63%。残り37%には誤った行、誤説明、存在しない問題のhallucinationが含まれた | programming feedbackをLLM単独の採点へ委ねず、外部検証と教師routeを置く |
| Zhengほか（2023） | LLM judgeには位置、冗長性、自己強化、推論能力のbiasがあり、reference-guided gradingで一部を改善できた | 実装モデルが自作コードを自己採点する構成を避け、参照解・決定的検査・独立routeを使う |
| Kulsumほか（2024） | 脆弱性修正でreasoningとcompiler・test・sanitizerのfeedbackを組み合わせ、baselineより正しいpatchが増えた | モデルの説明より、外部toolの結果を反復的に返す構造を優先する |
| OpenAI model guidance（2026-09-16確認） | mediumを均衡点とし、search・planning・multi-step判断を含む場合はlowより慎重に評価する。高effortは自動的に優れるのではなく、代表例で測定して選ぶ | 学習指導を常に最高tierへ固定せず、実課題evalで領域別routeを決める |

### 証拠から直接は言えないこと

- 上記の教育研究の多くは初学者または学生対象で、ミドルからシニアを目指す実務者への
  効果量を直接示していない
- PRIMM全体を日常のproductionタスクへ短縮して適用した比較試験は確認していない
- 自己説明を毎タスク挟めば専門性が最速で伸びる、という頻度の証拠はない
- デザインパターン名を必ず後出しにすることの直接比較は確認していない。本設計では
  cargo-cultを避けるための設計仮説として扱う
- code review研究は知識共有を示すが、今回提案する一人＋AIの演習が同じ効果を持つとは限らない
- retrieval practiceの代表研究は記憶課題であり、コードの設計・レビュー能力への転移は
  pilotで確かめる必要がある
- Silva & Costaの対象は初学者の小規模datasetであり、現在のLuna、Terra、Solや実務者を
  直接比較していない。さらに同研究では小型モデルが全指標で一貫して劣るわけではなかったため、
  「弱いモデルほど必ず誤る」という根拠には使えない
- LLM-as-a-judge研究は一般対話の選好評価が中心で、productionコードの教育的feedbackを
  直接評価したものではない。biasの存在と独立検証の必要性を示す補助根拠として使う
- モデル名とtierは更新されるため、現在の公式な位置付けを固定的な能力保証として扱えない

したがって「この仕組みで一流エンジニアになれる」とは主張しない。現時点で言えるのは、
受動的な説明だけより、真正なコードを使った生成、自己説明、外部検証、転移確認を組み合わせる
設計の方が、目的と既存研究に整合するということまでである。

## 矛盾・失敗モードレビュー

### 1. 現行コード参加との二重発火

新skillがWriteを所有するなら、現行コード参加を残すと発火条件と回数計上が二重になる。
実装時に完全移管または明確な限定が必要である。

### 2. 保留中レビュー訓練との重複

`tasks/backlog.md` の古い案をそのまま実装すると、AIレビューの開示順と学習記録が二系統になる。
新skillへ吸収し、backlogを更新する必要がある。

### 3. 現行モードとの停止回数

設計判断が最大2回、コード学習が最大1回なら、同一タスクで最大3イベントになりうる。
学習効果を優先しても中断過多は自己説明の質を下げうる。初期pilotでは発火した層と停止時間を
記録し、タスク全体の共通上限を設けるか判断する。

### 4. AIが出題者・採点者・実装者を兼ねる

AIの好みを正解として教える危険がある。実行可能な検査、公式資料、repo契約を優先し、
唯一解がない設計判断では複数の成立条件を示す。

### 5. 「高度」「効率的」の誤認

珍しい構文、短い記法、有名パターンを上級と誤認すると、可読性や単純さを損なう。
発火理由を品質への影響と転移価値で説明できない候補は落とす。

### 6. Write優先がタスクと難易度に合わない

ユーザーに書かせるためだけに人工的なTODOを作ると、production作業との直接性が失われる。
Writeが真正でない場合はModifyまたはReviewへ下げる。

### 7. 知識不足を誤答で埋める

未習得のAPIや言語仕様を、ヒントなしで推測させても学習にならない。知識獲得では難しさを
下げ、必要な説明や一次資料を渡した後、適用・レビューで難しさを作る。

### 8. 記録が説明ログになる

AIが説明した概念をすべて保存すると、理解証拠と教材一覧が混ざる。記録はユーザーが
実証した内容、誤解修正、転移結果に限定する。

### 9. PUBLIC repoへの情報漏えい

実務コードをそのまま学習記録へ保存できない。抽象化できない場合は記録せず、session内だけで
完結させる。

### 10. teachとの自動結合

実務イベントごとにteach workspaceへ書き込むと、missionとlesson設計を迂回し、二つの
記録体系が同期不能になる。接続は「体系学習候補」の提案までに限定する。

### 11. 常時指示の肥大化

詳細手順をruleへ入れると、コードを扱わないタスクにも影響する。常時ruleをルーターへ限定し、
skillのdescriptionも発火場面を狭く明示する。

### 12. 即時転移と長期保持の混同

同じsession内の転移成功は、数日後にも使えることを証明しない。関連する将来タスクで短く
想起させる経路は作れるが、同種のタスクが来なければspacingは起きない。コード学習モードは
即時理解と実務内の再遭遇を扱い、計画的な間隔反復が必要なテーマはteach側で扱う。

### 13. TDDなど既存workflowとの順序衝突

Writeを優先する指示だけを置くと、失敗するテストより先にproductionコードを書かせる可能性が
ある。コード学習は適用中のTDD・debugging・security workflowの順序を守り、その中で
ユーザーが担当する最も学習価値の高い部分を選ぶ。

### 14. 弱い実装モデルが教師と採点者を兼ねる

実装コストを下げるためのモデル降格が、そのまま教材選定と専門的feedbackまで降格させると、
誤ったコードを同じモデルが正当化する閉ループになる。教育的権限境界を設け、局所的な意味確認は
Terra + high、設計・pattern・複数成立解の評価はSol + highを初期routeとする。ただし正式な閾値は
代表ケースevalで決める。

### 15. 上位モデルへ全件昇格してコスト設計を無効化する

学習候補の検出だけで全実装taskを上位モデルへ移すと、適応的ルーティングの価値が失われる。
安価なモデルに適格条件照合、packet作成、決定的検査を残し、教育判断だけを限定昇格する。

### 16. 上位モデルを真実のoracleとして扱う

上位モデルでもhallucination、judge bias、不要なpattern適用は起こりうる。昇格は誤りを減らす
手段の一つであり、正しさの証明ではない。compiler、test、static analysis、benchmark、一次資料を
優先し、検証不能なら発火を見送る。

### 17. cross-model handoffが学習eventより重くなる

各eventで大きなhandoffを作ると、短い実務内学習より文脈移行の費用が大きくなる。一方、会話要約だけに
戻すとADR 0011の欠落検知を失う。既存validatorを再利用できる最小learning packetと、同じ教師agentを
理由回答後も継続利用する手順をpilotで測定する。便利さのためにhash・鮮度検証を黙って省かない。

## レビュー後の改善点

初期案から次を改善した。

1. 「実装後に読む」だけでなく、AI生成前のWriteを第一候補にした
2. 読む行為を受動的閲覧と、予測・trace・reviewを伴う能動的読解に分けた
3. Writeを形式的に強制せず、真正性と難易度でModify・Reviewへ適応させた
4. 説明の直後で終わらず、一条件だけ変えた転移確認を追加した
5. AIの自己採点を避け、compiler、test、公式資料を根拠の上位に置いた
6. デザインパターンを名前ではなく、解決する変更圧力と不適用条件から教えるようにした
7. 現行コード参加と古いレビュー訓練案を、新skillへ統合すべき重複として明示した
8. teachを競合skillではなく、繰り返し観測したgapの体系学習先として位置付けた
9. 学生・初学者研究を実務者へ外挿する限界を明記し、pilotを必須にした
10. 「一流になる」という抽象目標を、転移可能なレビュー・説明・検証能力へ分解した
11. 即時の転移確認と長期保持を分け、計画的なspacingはteachの責務とした
12. TDD、debugging、security、verificationとの所有範囲と実行順序を明示した
13. 実装モデルと教師・採点者の責務を分ける教育的権限境界を追加した
14. CodexではLunaによるpacket作成、Terra/Solによる限定的なread-only指導という初期routeを置いた
15. モデルtierを能力保証にせず、誤feedback率と誤警告率を含む代表ケースevalを必須にした
16. ADR 0011のhandoffを学習candidateにも適用し、入力欠落を推測で補わない構成にした

## 実装前に決めること

1. 現行コード参加を削除して完全移管するか、L2判断専用として残すか
2. 現行学習モードとコード学習を合わせたタスク全体の停止上限
3. `learning/code/entries/` をpilot初日から保存するか、session内測定から始めるか
4. 既習判定を何回の成功と、どの種類の転移で成立させるか
5. `★ Code Learning` など、既存の `★ Delta` と混同しない出力ラベル
6. teachをいつ提案するか。同種gapの回数だけでなく、mission化できる広さをどう判定するか
7. Claude CodeとCodexの両方で、常時ruleからskillが発火したことをどう検証するか
8. 教師agentのcustom roleを作るか、固定roleを使わず動的routeだけで起動するか
9. learning packetを既存handoff本文へ含めるか、hash参照する別成果物にするか
10. Luna / Terra / Solの教師品質を比較する代表ケースと合格閾値

## 将来の実装候補

設計承認後、別ブランチまたは競合しない作業状態で次を行う。

1. 正式ADRを作り、A/B/Cと既存案の扱いを記録する
2. `rules/code-learning.md` を短いルーターとして作る
3. `skills/code-learning/SKILL.md` と必要最小限のreferencesを作る
4. `rules/learning-mode.md` のコード参加を移管し、責務境界への参照を残す
5. `tasks/backlog.md` のレビュー訓練モードを統合済みとして更新する
6. 必要なら `learning/code/` のschemaとPUBLIC向け抽象化規約を作る
7. README、起動時必須読込、instruction graphの検査を更新する
8. Write、Modify、Review、除外、OFF、スキップ、二重発火防止のscenario testを作る
9. 両ホストで発火と停止の実測を行う
10. 5〜10件の適格タスクでpilotし、頻度と停止上限を見直す
11. 同一learning packetを候補モデルへ渡すrouting evalを作り、誤feedback率、誤警告率、
    根拠なし一般化率、費用、時間を比較する
12. 弱い実装agent → read-only教師agent → 弱い実装agentの往復を、ADR 0011の検証付きhandoffで実測する

skillの作成・検証時は `skill-creator` と `superpowers:writing-skills` を使う。
実装計画はユーザーの依頼により承認前の草案として先に作成した。
`docs/superpowers/plans/2026-09-17-code-learning-core.md` と
`docs/superpowers/plans/2026-09-17-code-learning-teacher-routing.md` を参照する。
計画内の最初の実行ゲートで正式ADRを承認し、それまでルールやskillを変更しない。

## 後続モデルへの引継ぎ

1. worktreeは作成していない。設定repo自身をworktree分離しない規約を優先した
2. 2026-09-17に `feat/codex-adaptive-model-routing` から `feat/code-learning-mode-plan` を作成し、
   既存の検討差分と二つの実装計画を同branchへ移した。ルーティング機能そのものの実装は追加していない
3. 本文書は `draft-reviewed` で、ルールやskillは未作成。計画はADR承認前の草案
4. 構成C「短い常時ルール＋詳細skill」にはユーザーが同意済み
5. Write → Modify → Review → Explainの優先順位にもユーザーが同意済み
6. 頻度は導入後に調整してよいが、学習ループの質を先に最大化する方針
7. 実装前に「実装前に決めること」を解消し、正式ADRをユーザーへ提示する
8. `tasks/backlog.md` の既存レビュー訓練モードを独立実装しない
9. teachの検討を破棄しない。詳細資料を読み、コード学習との役割分担を維持する
10. teachを採る場合も本repoをteaching workspaceにせず、専用repoを使う
11. upstream teachは固定commit時点の調査であり、導入直前に最新版とissueを再確認する
12. 外部資料の効果を実務者へ過剰に一般化せず、pilot結果で設計を更新する
13. 実装モデルが弱くても、教材選定・採点・専門的feedbackまで同じモデルへ委ねない
14. Codex CLI 0.154.0では `multi_agent` はstableかつ有効、`step_model_switching` は
    under developmentかつ無効だった。現設計は途中切替ではなくread-only subagent昇格を使う
15. 初期routeはLuna mediumでpacket作成、Terra highで局所意味レビュー、Sol highで
    architecture・pattern・複数成立解の評価。ただし正式採用は代表ケースeval後に行う
16. 現時点の証拠は「弱いモデルほど必ず誤る」とは示していない。示しているのは、モデル単独の
    programming feedbackに無視できない誤りがあり、tier名だけでは安全を証明できないことである

## 参照資料

### 既存資料

- `rules/learning-mode.md`
- `docs/adr/0001-learning-mode-prediction-format.md`
- `docs/adr/0007-learning-mode-decision-layer-gate.md`
- `learning/README.md`
- `tasks/backlog.md` の「レビュー訓練モードの導入」
- `docs/research/2026-09-15-mattpocock-skills-evaluation.md`

### 学習・プログラミング教育

- Sue Sentance, Jane Waite, Maria Kallia, “Teaching Computer Programming with PRIMM: A Sociocultural Perspective”:
  https://eric.ed.gov/?id=EJ1217966
- Sue Sentance, Jane Waite, Maria Kallia, “Teachers' Experiences of using PRIMM to Teach Programming in School”:
  https://doi.org/10.1145/3287324.3287477
- Michelene T. H. Chi et al., “Self-Explanations: How Students Study and Use Examples in Learning to Solve Problems”:
  https://doi.org/10.1207/s15516709cog1302_1
- Michelene T. H. Chi, Ruth Wylie, “The ICAP Framework: Linking Cognitive Engagement to Active Learning Outcomes”:
  https://doi.org/10.1080/00461520.2014.965823
- Henry L. Roediger III, Jeffrey D. Karpicke, “Test-Enhanced Learning”:
  https://doi.org/10.1111/j.1467-9280.2006.01693.x
- Priti Oli et al., “Exploring The Effectiveness of Reading vs. Tutoring For Enhancing Code Comprehension For Novices”:
  https://doi.org/10.1145/3605098.3636007

### AI支援プログラミング・コードレビュー

- Majeed Kazemitabaar et al., “CodeAid”:
  https://www.microsoft.com/en-us/research/publication/codeaid-evaluating-a-classroom-deployment-of-an-llm-based-programming-assistant-that-balances-student-and-educator-needs/
- Sarah Fakhoury et al., “LLM-Based Test-Driven Interactive Code Generation”:
  https://www.microsoft.com/en-us/research/publication/llm-based-test-driven-interactive-code-generation-user-study-and-empirical-evaluation/
- Alberto Bacchelli, Christian Bird, “Expectations, Outcomes, and Challenges of Modern Code Review”:
  https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/ICSE202013-codereview.pdf
- Peter C. Rigby, Christian Bird, “Convergent Software Peer Review Practices”:
  https://www.microsoft.com/en-us/research/publication/convergent-software-peer-review-practices/
- OpenAI, “Rethinking skills and prompts for GPT-6 Astra”:
  https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra
- OpenAI, “Custom instructions with AGENTS.md”:
  https://developers.openai.com/codex/agent-configuration/agents-md
- OpenAI, “Model guidance”:
  https://developers.openai.com/api/docs/guides/latest-model
- OpenAI, “Subagents”:
  https://learn.chatgpt.com/docs/agent-configuration/subagents
- Priscylla Silva, Evandro Costa, “Assessing Large Language Models for Automated Feedback Generation in Learning Programming Problem Solving”:
  https://proceedings.mlr.press/v273/silva25a.html
- Lianmin Zheng et al., “Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena”:
  https://arxiv.org/abs/2306.05685
- Ummay Kulsum et al., “A Case Study of LLM for Automated Vulnerability Repair: Assessing Impact of Reasoning and Patch Validation Feedback”:
  https://arxiv.org/abs/2405.15690
- Ishika Dutta et al., “CodeMirage: Hallucinations in Code Generated by Large Language Models”:
  https://arxiv.org/abs/2408.08333

### teach

- teach SKILL.md（調査固定commit）:
  https://github.com/mattpocock/skills/blob/3cca18b368ae95cdbdebbff572ccafa662551015/skills/productivity/teach/SKILL.md
- teach human-facing docs（調査固定commit）:
  https://github.com/mattpocock/skills/blob/3cca18b368ae95cdbdebbff572ccafa662551015/docs/productivity/teach.md
