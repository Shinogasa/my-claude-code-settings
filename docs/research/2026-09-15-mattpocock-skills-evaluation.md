---
date: 2026-09-15
status: draft
upstream_repository: "mattpocock/skills"
upstream_commit: "3cca18b368ae95cdbdebbff572ccafa662551015"
---

# mattpocock/skills の導入検討資料

> この文書は導入決定ではない。外部skill集を全量導入するか、個別に採るか、
> 既存設定へ考え方だけ取り込むかを後続の人間・モデルが判断するための調査正本である。
> 実装に進む前に、候補ごとの最新版、実行環境、既存skillとの同時発火を再確認する。

## 目的

公開リポジトリ mattpocock/skills を、現在のグローバル設定へ取り込む価値があるか調べた。
とくに productivity/teach を、単発の説明や教材HTML生成ではなく、継続的な学習環境として
理解し、既存の実務判断向け学習モードとの関係を明確にする。

この資料が答える問いは次のとおり。

- teach は何を保存し、どのように学習を進めるか
- 37 skill の目的、起動方式、副作用、成熟度は何か
- 現在の Superpowers、自前skills、rules とどこで重複・補完・競合するか
- 直接導入、アダプト、見送りの候補は何か
- 次のモデルが、どの根拠と未解決事項から検討を再開すべきか

## 調査範囲と根拠

### 調査対象

- upstream の commit 3cca18b368ae95cdbdebbff572ccafa662551015
- promoted bucket の engineering 18件、productivity 7件
- in-progress 8件、misc 4件
- 合計 37件の SKILL.md
- teach の補助資料である MISSION-FORMAT.md、RESOURCES-FORMAT.md、
  LEARNING-RECORD-FORMAT.md、GLOSSARY-FORMAT.md
- upstream の README、AGENTS.md、.agents/invocation.md、install-block.md、
  writing-docs.md、teach の人間向けdocs
- 現在の自前skills、rules、ADR 0001、ADR 0003、ADR 0004

deprecated bucket は README のみで、対象commit時点では廃止skillを含まない。

### 根拠の優先順位

この資料では、upstream の SKILL.md と同梱docsを一次資料として扱う。READMEの説明、
issueで紹介される既知の不具合・利用者報告は補助的な根拠であり、実行環境での再現確認ではない。
本資料の「競合」「補完」「導入候補」は、現在の設定を読んだ上での評価であり、導入決定ではない。

### 調査時の状態

- 調査自体は外部skillをインストールしていない
- upstream は Claude Code plugin と skills.sh によるコピー配布を区別している
- 同一環境へ両方導入するとskillが二重になるため、upstream 自身がどちらか一方を選ぶよう案内している
- 現在の設定は Codex native-first 方針を採っている。Claude由来の資産は構文上動くことではなく、
  具体的な不足・runtime契約・既存資産との責務境界を根拠に個別評価する

## 評価基準

候補skillを、名前やテーマだけで重複と判定しない。少なくとも次を比較する。

1. 起動方式: ユーザー明示起動か、モデルの暗黙起動か
2. 責務: 何を判断・実装・教育するか
3. 副作用: ファイル、Git、issue tracker、ブラウザ、秘密情報、依存関係をどう変更するか
4. 保存状態: 次のsessionへ何を残し、どのディレクトリを所有するか
5. 実行契約: 特定host、特定CLI、特定issue tracker、特定言語・ライブラリへの依存
6. 既存資産との関係: 同時発火時に重複、競合、補完のどれになるか
7. 保守コスト: upstream更新を追うか、自前契約として維持するか

## teach の詳細

### 位置付け

teach はユーザー明示起動専用の、状態を持つ継続学習skillである。新しい概念・技能を
複数sessionにわたって学ぶとき、実行したディレクトリ全体を teaching workspace として扱う。
一回の質問に答えるskillではなく、学習そのものがプロジェクトであるときに使う。

通常の開発リポジトリ、グローバルなskillsディレクトリ、既存設定リポジトリを teaching workspace
にしてはいけない。upstream の人間向けdocsは、トピックごとの専用repoで使うことを推奨している。
lesson、reference、assets が増え、Gitで履歴化・共有できるからである。

### workspace が保持する成果物

| パス | 意味 | 更新の契機 |
|---|---|---|
| MISSION.md | なぜ学ぶのか、成功条件、制約、範囲外 | 初回。目的が変化したときはユーザー確認後に更新 |
| RESOURCES.md | 知識源と知恵を得るコミュニティの台帳 | 教材作成前と、資料の評価が変化したとき |
| lessons/*.html | 一つの具体的な到達を扱う短い対話型lesson | 各lesson |
| reference/*.html | 後で見返す要約、用語、アルゴリズム、チートシート | lessonから再利用価値のある知識が得られたとき |
| learning-records/*.md | 実証済みの理解、既有知識、誤解修正、mission変更 | 理解の根拠が得られたときだけ |
| assets/* | 共通stylesheet、quiz、simulator、diagram helperなど | 二つ目のlessonでも再利用できる部品が必要なとき |
| NOTES.md | 教え方の好み、作業上のメモ | ユーザーが継続的な好みを示したとき |
| GLOSSARY.md | 正しく使えるようになった用語の正規表現 | 用語の理解が実証されたとき |

MISSION.md には Why、Success looks like、Constraints、Out of scope を置く。
一workspace一missionであり、抽象的な「理解したい」ではなく、現実で何ができるようになるかを
書く。MISSION.md が薄いときは、lessonを作る前に目的を聞き取る。

RESOURCES.md は Knowledge と Wisdom (Communities) を分ける。各資料は裸のURLではなく、
何を扱い、いつ使うかを一行で注記する。一次資料、認められた専門家、査読研究、強い
モデレーションを優先する。良い資料がない部分は Gaps として明示し、弱い資料で埋めない。

learning record は活動ログではない。以下だけを連番で残す。

- 利用者が非自明な理解を実証した
- 既に知っていることと、その深さを開示した
- 誤解が修正された
- 学びを通じてmissionが変化した

単に説明した内容、用語集と重複する定義、session日誌は記録しない。過去の理解と矛盾したときは
削除せず superseded として履歴を残す。

### 教育設計

teach は知識、技能、知恵を分ける。

- 知識: 高信頼資料から得る。モデルのパラメトリックな知識を信頼せず、RESOURCES.mdと引用で
  検証可能にする
- 技能: missionに直接結び付く短いlessonと、対話的な練習・即時feedbackで身につける
- 知恵: 実務家やコミュニティで現実の問題に当て、判断を検証する

さらに、その場で思い出せる fluency strength と、時間が経っても残る storage strength を
区別する。後者を強めるため、retrieval practice、spacing、技能に限った interleaving を
推奨する。知識を最初に理解するときは難しさを避け、技能を定着させるときは
desirable difficulty を与える、という分担である。

lesson は一回で完了できる範囲に絞り、missionに結び、利用者の zone of proximal development
に置く。つまり、既にできることの反復でも、前提が足りない飛躍でもなく、少しの支援で届く
次の技能を扱う。lessonには一次資料へのリンク、読者が読むべき主要資料、follow-upを促す導線を
含める。quizでは文面や選択肢の長さから正解を推測できないよう、語数、可能なら文字数も揃える。

### 初回と継続sessionの流れ

#### 初回

1. 専用workspaceと一つのmissionを確認する
2. 現実の目的、成功の観測方法、制約、範囲外を聞き、MISSION.mdへ残す
3. 高信頼な資料とコミュニティを探し、RESOURCES.mdへ用途つきで記録する
4. 利用者の既有知識と不足を確認する
5. missionに直結する小さいlessonを作り、知識を最小限にしてから練習へ進む
6. 再利用する教材部品をassetsへ切り出す

#### 継続

1. MISSION.md、RESOURCES.md、learning record、assets、reference、NOTES.mdを読んで現在地を復元する
2. missionと既に示された理解から、次のZPD内の技能を選ぶ
3. lessonと練習を実施し、理解の根拠が出た場合だけlearning recordを追加する
4. 用語を正しく扱えることが示された場合、GLOSSARY.mdへ正規化する
5. missionが変わる場合はユーザー確認後にmissionとrecordを更新する

### 既知の制約と注意点

以下は upstream の人間向けdocsとissue参照で説明される制約であり、この調査では独立再現していない。

- spacing と interleaving は原則であって、復習予定を保存・通知・自動出題するschedulerはない
- 初回の明示的な知識診断は実装されていない。利用者が既有知識と不足を言わないと、前提を誤ることがある
- 相対パスの解釈が曖昧になり、教材が意図したworkspaceではなくskillのインストール先へ出る報告がある。
  最初のlessonの出力場所を確認してから続ける
- quizの正解が先頭に偏る報告がある。選択肢位置を学習根拠にしてはいけない
- 引用はモデルの正しさを保証しない。とくに精密な手順・記法を扱う領域では、一次資料を実際に読んで検証する
- lessonを生成し続ける一方で、いつ復習・実践・終了へ切り替えるかを自動的に判断する仕組みは弱い
- GLOSSARY-FORMAT.md は存在するが、SKILL.mdが直接リンクしていない版があり、glossaryの配置説明にも
  referenceとrootの二系統がある。採用時は rootのGLOSSARY.mdに統一する

### 現在の学習モードとの関係

二つは同じ目的ではないため、記録を混ぜない。

| 観点 | 現在の学習モード | teach |
|---|---|---|
| 主対象 | 実作業中の設計、原因分析、実装判断 | 任意トピックの知識、技能、知恵 |
| 発火 | 不可逆・競合・一般化可能な判断点 | ユーザーが明示して始める長期学習 |
| 学び方 | Predict、理由、Delta、定石、次の問い | 引用付きlesson、練習、即時feedback、reference |
| 記録 | 公開安全化した判断エピソードと固定3軸 | 理解の証拠、既有知識、誤解修正、mission変更 |
| 継続性 | 同型の実務判断へ原則を接続 | 専用workspaceで教材と到達度を蓄積 |
| 実務との関係 | production作業の中で判断力を鍛える | productionから切り離して体系的に学ぶ |

現在の学習モードは、文脈依存の判断エピソードを数か月後にそのまま再出題しない。
当時の文脈を復元できない orphan prompt を避けるためである。teachは再利用できるlessonを
独立した教材として持つため、spacingの考え方を採っても矛盾しない。

### teach を採る場合の最小契約

直接コピーではなく、次の差分を持つ自前skillとしてアダプトする。

1. 専用workspaceのパスを明示させる。設定repoや通常の開発repoを暗黙に使わない
2. 現在のlearning/entriesとは別namespaceを使う
3. 既有知識と不足を確認する初回assessmentを追加する
4. 資料は公式・一次資料を優先し、引用を正しさの保証として扱わない
5. glossaryはrootのGLOSSARY.mdに統一する
6. lesson生成後に、出力先、引用、主要資料、練習の成立を確認する
7. review・実践・終了への切替条件は、少なくともユーザーが指示できる形で明記する

## 全skillカタログ

判定は次の三つを使う。

- 要アダプト: 考え方は有用だが、host、言語、保存先、外部副作用、既存規約を調整する必要がある
- 重複で非推奨: 現在のassetと同じ責務を持ち、別の手順を増やすだけになる
- 対象限定: 特定リポジトリ・言語・移行でのみ明示利用する。一律のグローバル導入はしない

### promoted: engineering

| Skill | 起動 | 目的と副作用 | 現時点の評価 |
|---|---|---|---|
| ask-matt | ユーザー | skill群のルーター。ファイル変更なし | 重複で非推奨。既存skillカタログとSuperpowersの起動規則に別ルーターを足す |
| code-review | モデル | 差分を Standards と Spec の二軸で別agentにレビューさせ、報告する | 要アダプト。既存review、security review、並列agent規約と一体化が必要 |
| codebase-design | モデル | deep module、seam、adapterなどの設計語彙を提供する | 要アダプト。hexagonal-architectureを補完するが、強い語彙制約は採らない |
| diagnosing-bugs | モデル | 最小再現、赤いfeedback loop、仮説、計測、修正、回帰テストで難しいバグを扱う | 要アダプト。systematic-debuggingへ反証可能な計測と最小化を統合する候補 |
| domain-modeling | モデル | 曖昧語を正規化し、CONTEXT.md、必要時ADRを更新する | 要アダプト。語彙集は有用だが、既存ADRの代替案・理由の必須契約を弱めない |
| grill-with-docs | ユーザー | 設計インタビューから用語集とADRを作る | 重複で非推奨。既存grill-meとbrainstormingに、文書化だけを必要時追加する方が小さい |
| implement | ユーザー | spec/ticketをTDD、review、commitまで一気に実装する | 重複で非推奨。既存planning、TDD、verification、Git規約を迂回しうる |
| improve-codebase-architecture | ユーザー | shallow moduleの改善候補を調査し、HTMLで可視化して選ぶ | 要アダプト。設計負債の定期調査は有用だが、HTML、ブラウザ、CDN依存を任意化する |
| prototype | モデル | 設計疑問を捨てる前提のHTMLまたはrouteで検証する | 要アダプト。spikeとして有用だが、branch、昇格、削除、検証を現行規約へ接続する |
| research | モデル | 一次資料を調べ、引用付きMarkdownをrepoへ残す | 要アダプト。保存先、ネットワーク、subagent、公開安全性を明確にする |
| resolving-merge-conflicts | モデル | 両側の一次資料から意図を復元してmerge/rebase競合を解消する | 要アダプト。意図復元は有用だが、abort禁止・常時commitは採らない |
| setup-matt-pocock-skills | ユーザー | issue tracker、ラベル、文書配置を初期設定する | 重複で非推奨。後続skill専用の構造がtasks、ADR、AGENTSと二重になる |
| tdd | モデル | 合意済みseamで公開挙動をred-greenの縦スライスとして実装する | 重複で非推奨。seam合意、実装詳細をmockしない原則だけを既存TDDへ採る候補 |
| to-spec | ユーザー | 会話を再質問せず仕様に合成し、issue trackerへ公開する | 要アダプト。外部投稿と既存planningの境界を定める |
| to-tickets | ユーザー | blocking edge付きtracer-bullet ticketへ分解する | 要アダプト。依存関係の明示は有用だが、tasksとtrackerの役割分担が必要 |
| triage | ユーザー | issueや外部PRを分類し、ラベル、コメント、close、briefを扱う | 要アダプト。外部副作用が多く、明示承認と不在の根拠を追加する |
| wayfinder | ユーザー | 一sessionに収まらない大きな案件を決定ticketの地図として進める | 要アダプト。tracker、並列agent、外部書込みの再設計が必要 |
| wizard | モデル | 人間しか行えないdashboard操作、認証、移行を対話bash化する | 要アダプト。秘密情報、外部操作、不可逆手順にsecurity reviewと承認を必須化する |

### promoted: productivity

| Skill | 起動 | 目的と副作用 | 現時点の評価 |
|---|---|---|---|
| grill-me | ユーザー | grillingを呼ぶ薄い入口。ファイル変更なし | 重複で非推奨。既存grill-meと同名・同責務 |
| grilling | モデル | 依存が解けた質問群をroundごとに出し、推奨解つきで設計木を掘る | 要アダプト。Predict対象では推奨を先出ししない分岐が必要 |
| handoff | ユーザー | 会話を次session用に圧縮し、一時ディレクトリへ文書を作る | 要アダプト。軽量な補完候補。安全な一時保存、保持期間、host中立の参照に変える |
| teach | ユーザー | 専用workspaceで長期学習の教材・資料・理解証拠を持続管理する | 要アダプト。詳細は teach の章を参照 |
| to-questionnaire | ユーザー | 知識保有者へ送るMarkdown質問票を作る | 要アダプト。保存先、衝突回避、日本語、外部送信の承認を定める |
| wait-what | ユーザー | 伝わらなかった説明を共有語彙と平易な言葉で言い直す | 要アダプト。日本語、CONTEXT.md不在時のfallbackを定めれば小さく有用 |
| writing-for-agents | モデル | skill、AGENTS、ポインタ先文書をagentが辿りやすく書く | 要アダプト。文書設計原則は有用だが、runtime仕様は公式docsとローカル実測を優先する |

### in-progress

| Skill | 起動 | 目的と副作用 | 現時点の評価 |
|---|---|---|---|
| claude-handoff | ユーザー | 現会話をClaudeのbackground agentへ引き渡す | 対象限定。Claude固定でCodexへそのまま移植できない |
| implement-spec | ユーザー | ticket DAGを並列worktreeで実装し、一つのPRへ収束する | 要アダプト。Superpowersと重複し、設定repoのworktree例外に合わない |
| loop-me | ユーザー | 繰り返し業務を聞き取り、workflows配下へ仕様化する | 要アダプト。保存先と既存grill-meとの役割分担が必要 |
| retro | ユーザー | coding sessionを振り返り、agent環境の改善候補を優先順位つきで出す | 要アダプト。lessons、ADR、Codexの会話取得経路と接続すれば有用 |
| setup-ts-deep-modules | ユーザー | dependency-cruiserでTypeScript packageの公開境界を強制する | 対象限定。特定TS構造と依存追加が前提 |
| writing-beats | ユーザー | 読者が理解済みの概念を追いながら、素材から記事を組み立てる | 要アダプト。文章制作用途では補完的だが、試験中 |
| writing-fragments | ユーザー | 構成を決めず、文章断片を蓄積して素材を掘る | 要アダプト。小さく独立しており、文章制作では候補 |
| writing-shape | ユーザー | 素材を読み、段落・表・リストなどを選んで別記事に編集する | 要アダプト。writing-beatsと用途の違いを明示する |

### misc

| Skill | 起動 | 目的と副作用 | 現時点の評価 |
|---|---|---|---|
| git-guardrails-claude-code | モデル | Claude CodeのPreToolUse hookで危険Git操作を止める | 重複で非推奨。既存の両host対応guardrailと重なる |
| migrate-to-shoehorn | モデル | TypeScript testの型アサーションを特定ライブラリへ置換する | 対象限定。一回限りのライブラリ移行であり、常設skillにしない |
| scaffold-exercises | モデル | 特定コース形式のexerciseディレクトリを生成する | 対象限定。特定CLIと固定ディレクトリ規約に依存する |
| setup-pre-commit | モデル | Husky、lint-staged、formatter、typecheck、testのpre-commitを導入する | 要アダプト。既存hook検出、依存追加承認、commitの扱いを定める |

## 重複・補完マトリクス

| upstreamの関心 | 既存の主な資産 | 評価 |
|---|---|---|
| TDD | Superpowers test-driven-development、tdd-workflow | 同じred-green-refactorを複数の強制規約で走らせない。seamとmockingの原則のみ検討 |
| 難しいバグの診断 | Superpowers systematic-debugging | 最小化、赤い観測、反証可能な仮説を補強できる |
| 設計インタビュー | brainstorming、grill-me、learning-mode | grillingの推奨先出しはPredictと衝突する。設計聞き取りに限定するか、推奨を後送りする |
| 設計記録 | architecture-decision-records、docs/adr | domain-modelingの語彙集は補完的。ADRの代替案・根拠の必須契約を維持する |
| 調査 | proving-absence、codex-cli-best-practice、Web | researchの一次資料・引用・知見保存は補完的。根拠階層と公開安全性を維持する |
| 実装オーケストレーション | writing-plans、executing-plans、subagent-driven-development、verification-loop | implement、implement-specは二重化しやすい |
| 引継ぎ | MODEL_ROUTING.mdのhandoff契約、tasks/todo.md、ADR | handoffは簡潔な人間向け引継ぎとして補完しうるが、モデル間handoffの検証契約を置換しない |
| 長期学習 | learning-mode、learning/entries | teachは補完関係。専用workspaceと記録namespaceを分離する |
| 安全なGit操作 | 既存hooks、Git規約 | git-guardrails-claude-codeは重複。setup-pre-commitは既存hookを検査してから個別評価する |

## 導入方針の選択肢

### A. 導入しない

upstreamを参考資料として読むだけにする。現在の設定は増えず、責務の重複も起きない。
一方、teachの継続学習、handoff、文章制作、seam設計などの不足は残る。

### B. 個別にアダプトする

候補の目的だけを採り、現在の日本語、両host、Git、安全性、学習モードの契約へ接続する。
保守コストは増えるが、責務境界を明確に保てる。現時点の有力候補は teach、handoff、
writing-for-agents、codebase-designの語彙、diagnosing-bugsの反証可能なfeedback loopである。

### C. upstreamをそのまま全量導入する

upstreamのworkflowを素早く使える。しかし同名skill、複数のTDD規約、Claude固有操作、
issue tracker書込み、worktree、外部副作用、英語・host固有の文面が既存設定と競合する。
この選択肢は推奨しない。

## 次に導入を判断するための検証

導入を決める前に、次を順に行う。

1. upstreamの最新commitと、対象skillの本文・補助資料・既知issueを再確認する
2. 導入候補ごとに、起動条件、書込み先、外部副作用、既存skillとの同時発火を表にする
3. teachを選ぶ場合は、専用学習repoを一つだけ用意し、最初のlessonの出力先、引用、assessment、
   lessonの品質を小さく試す
4. 小さい試行で、lessonから実際の演習・一次資料・referenceへ戻れるかを確認する
5. 継続利用する価値が確認できた候補だけ、host中立の自前skillとして設計する
6. 後から変えるコストが高い保存先・記録形式・発火規約を決めるときは、別ADRに選択肢と却下理由を残す

## 後続モデルへの引継ぎ

次のモデルは、導入作業を始める前にこの文書を全文読み、次を確認する。

1. この資料は調査正本であり、導入承認ではない
2. current repositoryの未コミット差分は、この調査とは別作業である。関連しないファイルを変更・stage・commitしない
3. upstreamを直接コピーする場合でも、導入対象の最新版と実行契約を再調査する
4. teachを扱う場合は、現在のリポジトリをworkspaceにせず、専用workspaceを明示する
5. 設定・ルール・skillを変更する場合は、Codex公式資料、ローカルCLI実測、固定submoduleの順で根拠を取る
6. 外部書込み、依存追加、秘密情報、Git hook、issue tracker、browser操作を伴う候補は、通常の文書変更として扱わない
7. 導入の前に、対象skillの責務が既存資産と重複しないことを、名前ではなく発火条件・手順・保存状態で確認する
8. コード理解・レビュー能力を育てる独立モードの検討は
   `docs/research/2026-09-16-code-learning-mode-design.md` へ続いている。teachとの役割分担、
   学習記録の分離、繰り返すgapをteachへ渡す境界を同文書と合わせて読む

## 関連する後続検討

- `docs/research/2026-09-16-code-learning-mode-design.md`
  - 実作業中のWrite / Modify / Review / Explainを扱うコード学習モードの設計候補
  - teachを体系的・長期的な学習先として残し、自動同期しない境界
  - 学習科学とcode review研究のエビデンス、および実務者へ一般化する際の限界
  - 現行コード参加と保留中レビュー訓練モードの重複・統合方針

## 主要な一次資料

- upstream repository: https://github.com/mattpocock/skills/tree/3cca18b368ae95cdbdebbff572ccafa662551015
- upstream README: https://github.com/mattpocock/skills/blob/3cca18b368ae95cdbdebbff572ccafa662551015/README.md
- teach skill: https://github.com/mattpocock/skills/blob/3cca18b368ae95cdbdebbff572ccafa662551015/skills/productivity/teach/SKILL.md
- teach docs: https://github.com/mattpocock/skills/blob/3cca18b368ae95cdbdebbff572ccafa662551015/docs/productivity/teach.md
- teach mission format: https://github.com/mattpocock/skills/blob/3cca18b368ae95cdbdebbff572ccafa662551015/skills/productivity/teach/MISSION-FORMAT.md
- teach resources format: https://github.com/mattpocock/skills/blob/3cca18b368ae95cdbdebbff572ccafa662551015/skills/productivity/teach/RESOURCES-FORMAT.md
- teach learning record format: https://github.com/mattpocock/skills/blob/3cca18b368ae95cdbdebbff572ccafa662551015/skills/productivity/teach/LEARNING-RECORD-FORMAT.md
