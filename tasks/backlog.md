# Backlog

着手していない課題の置き場。`todo.md`（実行中のタスク1件・使い捨て）とは役割が違う。

- 着手したら `todo.md` へ移して展開する
- 完了したらここから消す（履歴は git に残る）
- 判断待ちの項目は「決めること」を明記する。作業内容だけ書くと放置される

---

## テスト実行環境と再実行の削減

### P3: Codexサンドボックスでlocalhostの待受が拒否される理由を特定する

全テストの再実行を防ぐ対応（fixtureの環境隔離、localhostの事前検査）はPR #51で完了した。
そのとき未確認のまま残った2点だけを追う。Codex側の調査のため優先度は低い。

- `socket.bind` の制約が、起動引数・CLI設定・ホスト管理設定のどこで決まるか
- 過去の「毎回」の失敗が、すべて同じ原因（localhost拒否とGit署名の継承）だったか

**着手条件**: Codexのサンドボックス内で全テストを回す必要が出たとき。恒久的な権限設定の変更は別途判断する。

---

## Claude Codeのプロファイル切り替え

### P3: サブエージェントやフックが起動する `claude -p` も、親と同じプロファイルで動かす

2026-10-04に `bin/claude-headless` と、`settings.personal.json` の目印 `CLAUDE_PROFILE=personal` を入れた。
Bashから手で起動する経路はこれで足りるが、サブエージェントやフックが `claude -p` を起動する経路は、まだ `claude-headless` に寄せていない。

**決めること**: 該当する経路が出てきたときに、`claude-headless` を呼ぶよう書き換えるか。
目印を読めるのは、`ccp` で起動したセッションと、そのBashから起動したプロセスだけである。

### P3: 2026-10-04のセキュリティレビューで残ったLow

PR作成時の日本語レビュー、マージ済みPRの照会、`claude-headless` をレビューしたところ、次のLowが残った。どれも、実際に困った例が出てから直す。

- 個人プロファイルが空にする認証系のenvは5つだけ。`ANTHROPIC_API_KEY`、`CLAUDE_CODE_OAUTH_TOKEN`、`apiKeyHelper` などは空にしない（`ccp` から引き継いだ挙動）
- `block-commit-on-merged-pr.py` は `cd <dir> && git commit` で移動先を追わず、`bash -c` の中も見ない。
  `gh pr list --head` はforkの持ち主を区別しないので、同じ名前のブランチで別人がマージしたPRがあると誤って止める
- `jp-doc-review.py` の `--base` の取り出しは、コマンド全体から最初の `--base` を拾う。`gh -R x pr create` のように語の並びが違う形は、PR作成とみなさない
- `gh` の標準エラーを、そのまま画面に表示している

---

## 日本語文書レビュー（yomiyasu）の続き

設計は `docs/superpowers/specs/2026-10-01-jp-doc-review-design.md`、判断の経緯はADR 0024と0025。
最初の実装はClaude Codeだけを対象にした。

### P1: `cd <別のリポジトリ> && gh pr create` でPR作成時のレビューが止まらなかった

2026-10-08、sakurai-transcripts を cwd にしたセッションから `cd ~/garage/my-claude-code-settings && gh pr create ...` を実行して PR #68 を作った。
仕様書とADR（日本語のMarkdown）を含むのに、`pre-tool-use-bash` は止めなかった。

コードを読んだ範囲では、`handle_pre_tool_use_bash` はPRを作るリポジトリを、入力の `cwd` から `_find_git_root` で決めている。
コマンド中の `cd` を見ていないので、cwd 側のリポジトリ（差分に日本語文書が無い）を調べた可能性がある。原因はまだ再現で確かめていない。
ADR 0025 の背景で挙げた、コミットでの `cd` による取り違えと同じ型にあたる。

**決めること**: PRを作るリポジトリの解決に、`guard-dangerous-bash.py` のディレクトリ解決（`apply_directory_change`・`git_target_dirs`）を再利用するか。
`gh` の `-R` / `--repo` の指定も扱うか。

### P2: Codexでも日本語文書のレビューを動かす

Codexの公式ドキュメント（2026-10-01確認）では、PreToolUse・PostToolUseが `apply_patch` とMCPツールにも動き、
Stopの `decision: block` で作業を続けさせられる。ただし0.159.2の実機では未確認で、
このリポジトリには「合成テストが通っても実機で動く証拠にならない」という教訓がある。

**決めること**: Claude Code用の `hooks/jp-doc-review.py` を共有するか、Codex用の入口を分けるか。
`/hooks` で信頼されていないフックが通知なくスキップされる問題を、どう利用者に知らせるか。

### P3: スキル一覧に `yomiyasu:yomiyasu` が重複して出る

yomiyasuのリポジトリには、同じスキルの複製が `skills/yomiyasu/` に入っている。

**決めること**: 上流に報告するか、こちらで重複を読み込まない設定にするか。

### P3: 日本語文書レビューの細かい残り

- 状態ファイルを開くときに `O_NOFOLLOW` を使っていない。出力の中のパスをエスケープしていない
- 依頼文から取り出せるパスは英数字と記号だけ。日本語やスペースを含むパスのファイルは、レビュワーが直せない（止める扱いになる）
- Confluenceの投稿は本文だけを見る。タイトルだけが長い投稿は、タイトルをレビューしない
- `pre-tool-use-bash` はBashを使うたびにPythonを起動する

**決めること**: どれも、実際に困った例が出てから個別に直す。それまでは着手しない。

### P2: 日本語文書レビューで、実機ではまだ確かめていない点

2026-10-02の実機確認（`docs/research/2026-10-02-claude-code-hook-payloads.md`）では、次の点を確かめられなかった。

- 利用者が `/yomiyasu` と打ったときに会話記録に残る `Base directory for this skill:` の行の形（Skillツールからの呼び出しだけ確かめた）
- サブエージェントがPRを作るときに、PreToolUse の入力に `agent_type` が入るか
- worktreeの中でのsubmoduleの判定
- 対話のセッションで、SubagentStop の誤った表示が出ないか（利用中に見る）

**決めること**: 該当する場面になったら、会話記録と状態ディレクトリを見る。形が設計と違ったら、設計書とテストを先に直す。

---

## Codex CLI 対応の続き

全量監査と判断根拠は `docs/codex-compatibility-audit.md`、設計判断は
`docs/adr/0003-codex-native-first-activation-policy.md`、実装手順は
`docs/superpowers/plans/2026-08-18-codex-compatibility-migration.md` を参照。

### P2: 個人用の `CODEX_HOME` 分離（ADR 0026）の残り

2026-10-06に、本体（`cxp` の切り替え、setupによる両方へのリンク、個人プロファイル生成の廃止、
会社用の `auth.json` をSessionStartで警告する検査）を実装し、ホスト側も `~/.codex-personal` へ移行した。
残りは、個人アカウントでCodexを使えるようになるまで止めている。

**着手条件**: 個人アカウントのCodex契約を再開したとき。

- `cxp` で `/hooks` を承認する（個人用はhooks.jsonのパスが変わったので承認し直しが要る）
- setupで、両方の `CODEX_HOME` のSessionStart hookが承認済みか（`[hooks.state]` の `trusted_hash`）を検査し、
  未承認ならFAILURESに積む。hookが未承認だと、`auth.json` の検知そのものが通知なく走らない
- SSH署名の設定とサブエージェントの既定値は、setupが会社用の `config.toml` にしか当てていない。
  個人用にも要るかを決める
- 実機確認: `cxp` で `/hooks` 承認後、hookが動くこと
- `codex/hooks.json` のhookコマンドは `$HOME/.codex/hooks/...` の直書き。個人用でも会社用のリンク経由で動くので、
  `~/.codex` が無いマシンでは個人用のhookも動かない。`CODEX_HOME` 基準にするかを決める
- keyringに保存する設定（`cli_auth_credentials_store`）では、`auth.json` が作られないので検知できない
- 2026-10-06のセキュリティレビューの指摘（どちらも分離前からある穴で、今回の変更で悪化はしていない）
  - `cxp` はシェルの環境変数をそのまま引き継ぐ。`ASANA_TOKEN` や `ANTHROPIC_AUTH_TOKEN` はexportされているので、
    個人用のCodexの子プロセス（ツール実行、MCPサーバ）から読める。会社のゲートウェイの認証は `config.toml` のヘッダにあり、
    環境変数では渡していない
  - 会社のリポジトリで `cxp` を実行すると、信頼済みプロジェクトの `.codex/config.toml` が適用されうる（未確認）。
    `CODEX_HOME` を分けても、プロジェクトの設定層は分かれない
- 9/21に `model_provider` を消した主体は未特定。opencodeの初回起動（9/21 20:29）の4分後に `config.toml` が
  更新されているが、opencodeのログに書き込みの記録は無い

### P2: Claude用のpluginがCodexで有効に戻る

2026-08-26に `~/.codex/config.toml` で無効にした8件（`@claude-plugins-official` のasana、claude-md-management、
code-review、context7、learning-output-style、security-guidance、serena、superpowers）が、10/03に `enabled = true` に戻っていた。
`security-guidance` はCodexのSessionStartで `invalid session start JSON output` を起こす。

**原因（2026-10-05に特定）**: Codexの「Claude Codeから取り込む」機能。`~/.codex/state_5.sqlite` の
`external_agent_config_imports` に、2026-09-22 17:30に `PLUGINS` 8件を取り込んだ記録があり、8件は完全に一致した。
取り込みを実行したときだけ起きるので、起動のたびに戻す処理は要らない。

**決めたこと**: 既存のsetupの監査（`bin/audit-codex-plugins.py`）で検知する。取り込み後に気づけるよう、
SessionStartの検査（`hooks/check-codex-base-provider.py`）にもplugin監査を足す。

**着手条件**: Codexの作業を再開したとき。

### P2: `setup.sh` に dry-run を追加する

現状は実行するまで何が起きるか分からない。特に `setup_claude_plugins()` は
`claude plugin install` を走らせる外部副作用を持つのに、事前に対象を確認する手段がない。
「影響が小さい」と見積もる根拠を、実行前に数え上げられない状態になっている。

**完了条件**: 配布先の分類（missing / linked / managed-update / conflict）とplugin導入予定を、
副作用なしで列挙できる。

### P2: `context7` / `serena` のCodex向け候補を個別評価する

両者は有用候補だが、Claude版のimportをそのまま使わない。Codex公式・curated・公開pluginを
含めて候補を探し、version、起動、認証、代表read-only操作、エラー伝播、副作用を1件ずつ
確認してからallowへ移す。

**着手条件**: Codex移行が完了し、どちらかの機能が実務タスクで必要になったとき。

### P2: Codex agentsのruntime適用を検証する

生成ドリフトとschemaのテストは通っている。read-onlyの`code-explorer`、write可能な
`code-simplifier`、高reasoningの`planner`を実際にspawnし、modelとsandboxを確認する。
静的TOML検査だけで完了扱いにしない。read-onlyの確認では、ファイルを1つ作らせて失敗するところまで見る。

2026-08-18に `codex exec` で1回試したが、結論は出ていない。`agent_type` を指定したspawnは、
「Full-history forked agents inherit the parent agent type」というメッセージで拒否された。この文面はforkの使い方についてのもので、
定義が読まれていない証拠にはならない。指定を外して再試行した直後に、ゲートウェイが高負荷で落ちた。
`~/.codex/agents/*.toml` が適用されない不具合（openai/codex#26868）は2026-06-09にclosedになったが、手元では確かめていない。

Codexのモデルには別名が無い（`codex debug models` の `alias` が全件null）。そのため、モデルの世代交代のたびに
`bin/generate-codex-agents.py` の `CODEX_AGENT_PROFILES` などを書き換える必要がある。
更新箇所の集約は下の「P2 TODO」で扱う。

### P2: `codex/agents/*.toml`のモデル・推論ペアを公式基準で再評価する

**追加要望（2026-09-30）**: GPT-6.1の登場に追従し、既存のGPT-6基準ペアを
性能・推論ベンチマークから再評価する。旧形式skills親symlinkの移行とは別タスクで扱う。
公式ベンチマークの評価条件・推論強度・価格・待ち時間と、ローカルCLIで提供される
モデルを確認し、従来モデルの維持も含めて各工程・roleの変更を判断する。

現行8 roleのGPT-6固定ペアは、公式のモデル位置づけと公開単価を基に移行した暫定値であり、
個別roleの品質・所要時間・実際の総コストを代表タスクで比較して決めたものではない。
`security-reviewer`のGPT-6 Sol + highと旧GPT-5.6 Terra + highも実測で比較する。

**調べること**:

- OpenAI公式のモデル選択・推論強度・custom agent例と各roleの責務を照合する
- GPT-6 Luna / Sol / Astraと旧GPT-5.6 Terraの品質、待ち時間、総コストを代表タスクで比較する
- 固定roleが必要な範囲と、動的ルーターへ委ねる範囲を分ける
- `sandbox_mode`とdeveloper instructionsも、モデル変更と独立に再監査する

**決めること**:

- 各roleの基準ペアを維持・変更・統合のどれにするか
- 公式例から外すroleに、どの実測根拠を必須とするか
- 新しいモデル世代が出たときの再評価条件をどう検知するか

**完了条件**:

- 8 roleすべてに公式根拠または再現可能な実測根拠がある
- 生成元、生成済みTOML、テスト、モデルルーティング文書、ADRが一致する
- read-only / workspace-writeの権限がモデル選択の都合で広がっていない
- runtime smoke testで実際のmodel、reasoning effort、sandboxを確認する

### P2 TODO: 新しいモデル世代へのルーティング更新を容易にする

今回のGPT-6移行では生成元、既定値、validator、方針、テストを個別に更新した。
次の世代交代前に、基準ペアの正本を一つに寄せ、生成物・validator許可ペア・setup既定値・
文書とテストの整合性を検査する方法を設計する。履歴用handoff、ADR、runtime fixtureは
一括置換しない。公式のmodel/effort対応、ローカルCLIの提供状況、代表タスクの品質・
所要時間・総コストを確認してから新世代へ切り替える。今回の変更では共通化を実装しない。

### pilot待ち: 親工程ルーティングの実タスク検証

**実装判断**: ADR 0016（0015を置換）。工程ごとに再分類し、検証済みhandoff付きの明示ペアsubagent、
または明示ペアfresh sessionへ渡す。新規same-thread beginは停止。旧pendingは自然文の復旧依頼を
受け付け、Codex内からdiagnose / cancelを実行できる。通常local toolは取消まで止める。

**実測済み**: 隔離HOME・一時repo・localhost mockを使う実App Serverで、新規begin拒否、旧pendingの
副作用拒否→診断→取消→通常操作、およびresumeのmodel観測とeffort申告を検証した。
Python 3.9の深いJSONによるhook例外も拒否へ変換し、providerへ配送しないことを検証した。

**残作業**（[運用引継書](../docs/codex-parent-routing-operations-handoff.md)を正本とする）:

- コード学習の実装タスクで明示ペアの委譲・handoff読了・最終reviewまで完走する
- Desktop/CLIとhosted modelでの利用を記録し、旧Desktop threadの原因は証拠が揃った時点で再調査する
- fresh sessionの起動・両軸のloaded設定・handoff受信を同じ試行で記録する
- review runner本体は別タスクで実装する。設計資料を稼働証拠と呼ばない
- 新規beginを再開するなら、別hookの拒否・turn終了・後続のraw CLI実行にまたがるgrant流用を防ぐ
  実行束縛を実runtimeで証明する。期限追加やActive表示だけでは再開しない

### Codex review runnerの初回除外項目

ADR 0013と`docs/superpowers/specs/2026-09-18-codex-review-runner-design.md`の初回実装は、
read-onlyなsecurity / integration reviewの起動・回収・resume-once・重複実行抑止に限定する。
次は初回へ混ぜず、着手条件が成立した項目だけを独立タスクへ移す。

#### P1: Markdown reportを`--output-schema`へ移行する → 安定性評価待ち

OpenAI公式の`--output-schema`を使えばseverity、confidence、ready-to-commitを構造化できる。
一方、初回から導入するとreview実行の状態機械と既存Markdown返却契約の移行を同時にデバッグする
ことになる。

**決めること**:

- Markdownを互換出力として残すか、JSONを唯一の正本にするか
- security / integrationを一つのunion schemaにするか、別schemaにするか
- schema不成立時にresumeするか、即時fail-closedにするか

**着手条件**: 初回runnerのfixture suiteと明示smoke testが完了し、Markdown契約違反または
downstream parseの不便を1件以上観測したとき。

#### P1: validatorへ機械可読read plan / range receiptを追加する → JSONL解析の限界待ち

初回runnerは、成功した`command_execution`のvalidator commandと`DOCUMENT:` headerを突き合わせて、
全行がgap・overlap・duplicateなしで読まれたか検査する。validator自身にread planやreceiptを
追加すると証拠は強くなるが、入力検証CLIのinterfaceも変わる。

**決めること**:

- validatorが署名またはdigest付きreceiptを返すか
- planをrunnerが作るか、validatorがdocument行数から作るか
- command eventを証拠にする現行方式から移行する互換期間を置くか

**着手条件**: CLI version差でcommand event shapeが変わる、strict tokenizeできない正当な実行が
発生する、またはreceipt偽装を防げない反例を観測したとき。

#### P1: 修正後review範囲を保証境界から自動選択する → policy設計待ち

初回runnerはhandoffで指定された範囲をそのまま読む。Critical、confidence不足、設計境界変更は
全体review、局所Importantはdiff中心という候補はあるが、runnerがfile数だけで局所判定してはいけない。

**決めること**:

- 保証境界の変化を機械入力でどう表すか
- 局所再reviewから全体reviewへ戻す条件
- security boundaryと最終integration reviewの最低範囲

**着手条件**: 初回runnerで修正後reviewを3件以上実行し、全体再読が不要だった事例と、
局所reviewでは不足した事例の両方を得たとき。

#### P2: review runnerを汎用agent runnerへ広げる → review運用の安定待ち

実装agentはwrite sandbox、承認、変更回収、rollbackを必要とし、read-only reviewと成功条件が異なる。
初回runnerへ任意agent、任意prompt、任意sandboxを追加しない。

**決めること**:

- review runnerと共通化する最小coreが実在するか
- write agentの変更成果物、承認、cancel、rollback契約
- model + effort以外に固定すべきroleとsandbox境界

**着手条件**: review runnerが安定し、同じJSONL監視・lock・manifestを別agentで再利用したい
具体的タスクが発生したとき。

#### P2: Web UIと長時間実行monitorを追加する → CLI不足の証拠待ち

初回はmanifest、event件数、経過時間のCLI表示だけを提供する。UIを先に作ると、未安定な状態機械を
表示層へ固定してしまう。

**着手条件**: CLIだけでは実行状態や失敗理由を判断できず、同じ誤操作が2回以上起きたとき。

#### P2: retry / backoffを一般化する → failure taxonomyと予算設計待ち

初回はreport欠落時の同一session resumeを1回だけ許可し、resume失敗後の新規review自動実行を
禁止する。network、rate limit、provider障害を区別せずretryすると二重課金とthundering herdを招く。

**決めること**:

- retry可能なerror codeと、retryしてはいけない契約違反
- attempt、wall-clock、tokenまたは費用の上限
- cancellationと部分成果物の扱い

**着手条件**: runnerのmanifestからtransient failureを再現可能に分類でき、ユーザーが自動retryの
予算上限を決めたとき。

#### P2: 複数provider対応・provider自動切替 → 却下状態を維持

ADR 0010のprovider不変・fail-closed方針を維持する。runnerはprovider関連引数を公開しない。
再検討する場合は、認証、データ境界、model同等性、費用の判断を新しいADRへ記録する。

#### P2: 高度なmodel router → 代表taskの実測待ち

初回runnerは親AIが選んだmodel + effortを検証して実行するだけで、自動選択しない。
全custom agent profileの基準ペアは直前の独立backlogで再評価し、runnerへ混ぜない。

**着手条件**: role別の品質、待ち時間、token量を同じfixtureで比較できるようになったとき。

#### P1: spawn gatewayがtool引数を空objectへ落とす問題を切り分ける

model routing作業中、`agents__spawn_agent`へ渡したmodel、reasoning effort、task等の引数が
gateway経路で空objectへ落ちる症状を同一sessionで複数回観測した。正しいペアを選んでもchildへ
伝わらず、routing policyでは回避できない。review runnerは同じproviderの`codex exec`を使うため、
この互換性問題を修正したことにはしない。

**調べること**:

- clientが送ったtool call、gatewayが転送したpayload、backendが受け取ったargumentsのどこで消えるか
- `fork_turns`、`agent_type`、model + effortの組み合わせで再現条件が変わるか
- gatewayを通さない同一CLI versionのbaselineでは引数が保持されるか

**決めること**:

- repository設定で回避できる互換性問題か、gatewayまたはCodex本体の修正待ちか
- runtime smoke testへ引数round-trip検査を追加するか
- 修正までspawnをfail-closedにし、review runnerへ限定する範囲

**完了条件**:

- 引数が保持される成功caseと空になる失敗caseを同じ観測点で区別できる
- modelとreasoning effortの実runtime値をchild側の証拠で確認できる
- providerを変更せず、根因または上流issueと安全な暫定運用が文書化されている

#### P2: 外部modelを使うintegration test → 明示smoke testとして分離

通常suiteはfixture JSONLとstub `codex`だけを使う。credential、rate limit、model更新で不安定な
external callを毎回のtestへ入れない。

**決めること**: 手動または明示flag付きsmoke testの頻度、費用上限、成功証拠の保存期間。

**着手条件**: fixture suite完成後、runnerを実環境へ配布する直前。

既存の独立backlogへ残す項目:

- 全custom agent profileのモデル再評価: 直前のP2項目
- gatewayの空引数問題: gateway互換性の調査タスク
- コード学習統合: `feat/code-learning-mode-plan`が所有するADR 0012の統合後に判断する
- resume失敗後の新規review自動実行: 後続候補ではなく、ADR 0013で禁止した失敗時契約

### Codex statuslineの自前化 → 着手条件待ち

当面はCodex公式のデフォルトstatuslineを使い、`statusline.js`はClaude専用のまま維持する。
公式footerで足りない項目が実務上の事故や継続的な不便を起こした場合だけadapterを検討する。

**着手条件**: 不足している表示項目と、それにより起きた具体的な問題を記録できたとき、
またはCodex公式がcustom providerを公開したとき。

### 定期: skills・commands・agents・rules の棚卸し → 次回 2027-01

資産は足すだけでは減らない。使っていないものがコンテキストを圧迫し、モデルの進歩で不要になるものも出る。
組み込みスキルを同名で上書きしていても気づけない（2026-10-07に `verify` などで判明）。定期的に見直す。

**着手条件**（どれか1つ）

- 四半期ごと。前回は2026-10-07なので、次回は2027-01
- Claude CodeまたはCodexで、使うモデルの世代を切り替えたとき
- Claude Code本体を大きく更新したとき（組み込みスキルが増えると、手元の資産と名前がぶつかる）

**見ること**

1. 利用: 直近60日の会話記録で、スキル（`"skill":"<名前>"`）、サブエージェント（`"subagent_type":"<名前>"`）、
   スラッシュコマンド（`<command-name>/<名前></command-name>`）の呼び出しを数える。
   **先に、確実に使った資産が検出できることを確かめる**（2026-10-07は `pr-create`、`jp-doc-reviewer`、`/rename` で確認した）。
   検出できなければ、0件は「使っていない」の証拠にならない。Codexでの利用とSKILL.mdの直接読み込みは、この方法では数えられない
2. 名前の衝突: 手元の資産が、組み込みスキルやpluginと同じ名前になっていないか。セッション開始時のスキル一覧で、
   手元の説明文に置き換わっていないかを見る。組み込みの一覧を取る公式の手段は未確認
3. コンテキスト: 常時読み込まれる rules と CLAUDE.md の文字数。増えていれば、`paths:` での遅延読み込みや削除を検討する
4. モデルの進歩: モデルが自力でできるようになった指示（手順の念押し、汎用の規約）が残っていないか

結果は棚卸しした日付と件数をこの項目に追記し、次回の日付を更新する。

### Everything Claude Code由来資産の残り（agents 6件） → Codex再開待ち

commit `0ca03372` でECCから取り込んだ資産を、2026-10-07に棚卸しした。直近60日のClaude Codeの会話記録206件で
利用を数え、使っていないcommand 10件・skill 7件と、対応する `skills/source-command-*` 6件を削除した。
rulesは、superpowersと重なる `ecc-testing.md` を削除し、`ecc-development-workflow.md` を重ならない部分だけに縮めた。

`verify`・`code-review`・`security-review` は、Claude Code本体の組み込みスキルを同名で上書きしていた。
消したことで組み込み版が使えるようになった。名前の衝突は、上の定期の棚卸しで確かめる。

**残り**: agentsのうち、60日の利用が0件の6件（build-error-resolver、code-architect、code-simplifier、planner、
refactor-cleaner、silent-failure-hunter）。`codex/agents/*.toml` がこの定義から生成されるため、消すとCodex側も変わる。

**着手条件**: Codexの作業を再開したとき。Codexでの利用も合わせて数えてから決める。

### superpowers の自動注入をプラグイン同梱フックで賄えるか → 決めること

今は、`AGENTS.md` に「応答の前に `using-superpowers` を読む」と散文で書いて発火させている。
2026-08-18に、`codex exec` の1ターンでCodexがSKILL.mdを自分で読みに行くことを確かめた。
観測したのはその1ターンだけで、毎セッション同じように読むかは確かめていない。散文指示が守られなかったことに気づく手段も無い。

Codex は**プラグイン同梱の `hooks/hooks.json` を読む**（実測: `[hooks.state]` に
`security-guidance@claude-plugins-official:hooks/hooks.json` と
`learning-output-style@claude-plugins-official:hooks/hooks.json` のエントリがある）。

一方、採用している `superpowers@openai-api-curated` は**配布物に `hooks/` を含まない**
（`assets` / `CODE_OF_CONDUCT.md` / `LICENSE` / `README.md` / `skills` のみ）。
`superpowers@claude-plugins-official` の方は `hooks/hooks.json` を同梱し、
`SessionStart` で `run-hook.cmd session-start` を呼ぶ形になっていた。

つまり **Claude 版を採ればフックによる自動注入が成立した可能性がある**。
ただし当該プラグインの trust エントリは存在しなかったため、
**Codex 上で実際に発火したかは未確認**（matcher が `startup|clear|compact` である点が
関係する可能性がある）。2026-08-18 に重複解消のため Claude 版は削除済み。

**決めること**: 散文指示のままにするか、自動注入の機構を作るか。
機構にするなら (a) `codex/hooks.json` の `SessionStart` で
`using-superpowers` を読ませる、(b) Claude 版を再導入して同梱フックに任せる、
のどちらか。(b) は重複が復活するため `setup.sh` の重複削除と衝突する。

**着手条件**: 散文指示が守られなかった事例を観測したとき、または
Codex を主ホストとして使う頻度が上がったとき。

---

## PR作成の判定（is_pr_create）の取りこぼし

### P3: `gh -R x pr create` などをPR作成と判定できない

`hooks/jp-doc-review.py` の `is_pr_create` は、コマンドの先頭3語が `gh pr create` かだけを見る。
`gh -R org/repo pr create`、`gh --repo x pr create`、`/usr/bin/gh pr create`、`timeout 60 gh pr create` などを見逃す。
日本語レビューのhookと、全件テストの記録を確かめるhook（ADR 0029）の両方が、この関数を使っている。
2026-10-09のsecurity-reviewerの指摘3。

**決めること**: どこまでの書き方を拾うか。少なくとも `-R` / `--repo` の読み飛ばしと、パス付きの `gh` は拾いたい。
エイリアスやスクリプト経由は、静的な判定では拾えないので対象外にするか。

## 学習モード

### コード学習の候補が拾われていない → 着手条件待ち

2026-09-30〜2026-10-08の学習storeでは、能力recordが設計Predict 10件、コード学習 1件だった。
ADR 0027で重点学習領域の上限を上げたが、上限に達する前に候補が拾われていないなら効果は出ない。
慣れた言語で知らないテクニックに出会う場面も、AIが候補として拾わない限り出題されない。

**着手条件**: `end_reason: cap_reached` のoperationを記録できる状態で、Goを主に扱うタスクを5件こなしたとき。
cap_reachedが少ないのにコード学習も少なければ、詰まりは検出側にある。

**決めること**: 検出側を直すか。直すなら、`rules/code-learning.md` の発火条件を広げるか、
実装・レビューの区切りで候補の有無を確認する手順を足すか。

### 書籍・一次資料の提示を検証付きで解禁する → 着手条件待ち

捏造を防ぐため、`skills/learning-mode/references/delta-supplements.md` は書籍名・記事名・URLを出すことを禁止している。
2026-08-14 に**検証を通したものだけ解禁する**方針で合意したが、
レビュー訓練モードと同時に入れるとスコープが膨らむため保留。
レビュー訓練は、2026-09-17に `code-learning` skillの `Review` 形式として導入した（ADR 0012）。

**運用方針（合意済み）**

- 提示前に必ず検索して**実在・著者・版**を確認する。確認できなければ出さない
- **書籍単体で薦めない。** その場の判断に紐付けて出す
  （「◯◯を読め」ではなく「今回の見逃しの背景はこの考え方で、出典はこれ」）。
  紐付いていない推薦は読まれないまま消える

**着手条件**: `code-learning` の `Review` で、見逃しの背景を説明するために出典を示したくなったとき。
単独で入れても使いどころが無い。

**決めること**: 解禁するか。解禁するなら、`code-learning` の解説だけに限るか、★ Delta の `概念` 欄にも広げるか。

### 確信度（1〜5）の追加 → 決めること

正誤に確信度を掛けて「自信満々で外した」セルを拾う。追加コストは選択肢1問と安く、
最優先の再学習対象を特定できる。ADR 0001 の A2 で**保留**にした。

**保留理由**: 生成効果という根本原因には触れないため、
D1/D4（結論のみの選択肢＋理由の自由記述）の是正を先行させた。

**決めること**: `result` に確信度の次元を足すか。足すなら frontmatter を
`result: hit` から `result: hit` + `confidence: 4` の2フィールドに分けるか、
`result: hit-confident` のような複合値にするか。
**複合値は集計時に分解が必要になるため、2フィールドが素直**。

**着手条件**: D1/D4 での記録が10件たまり、hit 率が実際に下がったことを確認できたとき。

### 難易度サーボ（85%ルール） → 決めること

直近7件の正答率が90%超なら発火の難易度を上げ、70%未満なら下げる。
ADR 0001 の A3 で**保留**にした。

**保留理由**: 正答率の自動集計が先に必要で、機構が増える。
D5（発火条件の3ゲート）で発火を絞った結果として難易度がどう動くかを観測してから決める。

**決めること**: 自動集計を入れるか、`grep '^result: ' | tail -7` の手動確認で足りるとするか。
手動なら「いつ確認するか」を決めないと形骸化する。

**着手条件**: D1/D4/D5 の運用が20件たまったとき。

### ヒント梯子（5段階） → 決めること

予測を外したとき、★ Delta で全開示せず段階的にヒントを出す。
ADR 0001 の A4 で**保留**にした。

**保留理由**: D4 で既に往復が1回増えている。同時に入れると摩擦が過大になる。

**決めること**: 入れるか。入れるなら**全ての miss に適用するか、
確信度が高かった miss だけに絞るか**（後者は確信度の実装が前提）。

**着手条件**: D4 の往復増が許容範囲だと確認できたとき。

### 軸そのものが妥当か（3軸で足りているか） → 決めること

`axis` の値の問題（2026-08-16 に `全軸充足` を追加して解決）とは別に、
**3軸（トレードオフ / 失敗モード / 前提の検証）が正しい分解なのかは未検証**。

現時点で言えるのは「まだ測れていない」ことだけ。軸評価が付いているのは28件で、
うちトレードオフは2件しかないが、これは得意だからではなく
**旧設計で構造的に検出できなかった**ため（→ `learning/README.md` の「集計する前に確認すること」）。
D1/D4 改訂後のエントリは7件（2026-08-16 時点）で、判定に足りない。

**取りこぼしの候補: 観測可能性**（壊れたときに気づけるか）。
「どう壊れるか」（失敗モード）とは別の問いだが、現状は失敗モード軸に吸収されて
記録に残らない。2026-08-16 のセッションだけで3回出た論点。

**決めること**: 4軸目を足すか、3軸のままにするか。
足すと既存28件との比較可能性が切れる（`rules/learning-mode.md` が
「軸を勝手に増やすな」と書いているのはこのため）。

**着手条件**: D1/D4 改訂後のエントリが20件たまり、軸別分布を出せるようになったとき。

### 概念ノート層を新設してエントリと相互リンクする → 決めること

ADR 0005 の A2。2026-08-21 の測定で、供給した概念名（`fail-safe defaults` /
`failure domain` / `policy-mechanism separation` 等）は抽象度としては十分だが、
**23件に付いたまま一度も再訪されていない**ことが分かった。
エントリ間の相互リンク（wiki 記法・相対 `.md` リンク）は実質0件で、
「過去の判断原則との接続」節は23件あるが全て散文のためたどれない。

ADR 0001 の A5（カレンダー駆動の間隔反復）を却下した理由は
「エピソードは当時の文脈を再現できず orphan prompt になる」だった。
**概念ノートはこの制約に当たらない**（概念は元から文脈を剥がした単位）ため、
A5 の却下理由をこの案の却下根拠に流用してはいけない。

**決めること**:

- ノートの粒度（1概念1ファイルにするか、関連概念を束ねるか）
- エントリ側からの参照記法（`[[name]]` か通常の相対リンクか）
- バックリンクを手で書くか、生成物として作るか（生成物ならソースのみコミットする運用が要る）

**着手条件**: 無し。ADR 0005 の層ゲートが効いたかを判定する経路でもあるため、
D1〜D3 の運用が数週間回った時点で着手する。

### エントリ書式を機械可読に固定する → 決めること

ADR 0005 の A3。`### 判断点` 見出しの一致は76件中31件で、
`## 判断点` / `### 判断点1` / 見出し無し が混在している。
2026-08-31 に `learning/README.md` のテンプレート側は実態へ合わせたが、
**過去エントリは揃っていない**。このため全件を母数にした見出し grep は信頼できない。

**決めること**: 過去エントリを遡って統一するか、「2026-08-21 以降のみ」で切るか。
遡ると ADR 0001 が依存している「1エントリ1ファイル移行時に本文を1文字も変更していない」
という保証が失われる。

**着手条件**: 上の概念ノート層と同時に決める（どちらも書式に触るため）。

### 実作業の外から題材を持ってくる → 決めること

ADR 0005 の A4。現在の発火は実作業に完全従属しており、
設定リポジトリを触っている期間は設定リポジトリの判断しか出題対象にならない
（2026-08-19 は11件中10件がメタ作業）。

**決めること**: 予測に対する「実際」を何で担保するか。
AI が正解を作ると差分フィードバックの信頼性が落ちるため、
**正解が外部に既に存在する題材**（マージ済み OSS PR、公開 postmortem）に
限定できるかを先に決める必要がある。

**着手条件**: 層ゲート（ADR 0005 D1）を入れた結果、題材の偏りがどれだけ解消したかを
測ってから。層ゲートだけで足りるなら不要になる可能性がある。

---

## フックの守備範囲の穴

PR #17 の本文にレビュー観点として書いたが、マージで参照されなくなったため移した。
**PR 本文は残課題の置き場にならない。**

### terraform の state 書き換えが `state` サブコマンドの外にもある

`guard-dangerous-bash.py` は `terraform state` 配下を allowlist で守っているが、
以下は `state` の外なので対象外。

- `terraform import` — state にリソースを書き込む
- `terraform taint` / `untaint` — 次の apply での再作成を予約する
- `terraform apply -replace=ADDR` — 同上。ブランチが遅れているときのみ別フックが止める

**決めること**: allowlist の範囲を `terraform` のトップレベルまで上げるか、
これらを名指しで足すか、対象外のままにするか。
トップレベルまで上げると `fmt` `validate` `version` まで巻き込むため、
そのままでは摩擦が大きい。

**着手条件**: terraform を扱うリポジトリで `import` を実際に使う場面が出たとき。

### 共同作業ブランチへの force push は素通りする → 受け入れ済み（2026-08-16）

force push を対象 ref で判定する形に変えた（保護ブランチ以外は通す）。この例外が
成立する前提は**そのブランチに自分以外がコミットしていないこと**だが、フックは
それを検査していない。上書きされたコミットの退避先は上書きした本人のローカル
reflog だけなので、他人が push したブランチでは復旧経路が無い。

リモートの ref に誰のコミットがあるかは push 前には確定しない（fetch が要り、
fetch 直後でも競合しうる）。フックの層では原理的に見切れない。

**決めたこと**: 受け入れる。実際に事象が起きてから対応する。
**着手条件**: 共同作業ブランチへの force push で実際にコミットを失ったとき。

### `--all` / `--mirror` の判定が denylist になっている

`GIT_PUSH_BROADCAST_FLAGS` は3つを名指しする denylist。git が新しい一括更新フラグを
足すと「対象を特定できた」側に落ちて通る。`TERRAFORM_STATE_READONLY` が allowlist を
選んだ理由（新しい操作は止まる側に入る）と方針が揃っていない。

**決めること**: push の位置引数解析を allowlist 側へ寄せるか、現状維持か。
**着手条件**: git が新しい一括 push フラグを追加したとき、または誤判定を観測したとき。

---

### 入れ子のシェルと環境変数で判定対象を見失う

2026-10-01 のセキュリティレビューの指摘（以前からある穴）。`guard-dangerous-bash` は
次の形では commit や移動先を見失う。前置き（time / exec / nohup / command / builtin / env）、
予約語、リダイレクト、先頭の `NAME=value` は除去するようにした。

- `bash -c 'git commit'`、`x="$(git commit -m y)"`（文字列が1トークンで解析されない）
- `GIT_DIR=` / `GIT_WORK_TREE=` / `git -c core.hooksPath=...` による対象・フックの差し替え
- 引用符で名前を隠した CDPATH の設定（`export "CDP"ATH=...`）
- 値を取る前置きのオプション（`env -u NAME`、`env -C DIR`、`exec -a NAME`）と、
  `sudo` / `timeout` / `nice` / `xargs` のような前置きコマンド
- プロセス置換 `<(...)` / `>(...)` の中のコマンド
- リダイレクト直前の数字を fd とみなすため、`cd 2 >/dev/null` の `2` を引数として扱えない
- `${v/ #/y}` のようにパラメータ展開の中の空白の直後にある `#` を、コメントの始まりとみなす
- 環境変数で渡すgitの設定（`GIT_CONFIG_COUNT` / `GIT_CONFIG_KEY_n` / `GIT_CONFIG_PARAMETERS`）。
  先頭の `NAME=value` を取り除いて判定するので、refspecを省略したforce pushで `push.default` を差し替えられても検出できない。
  `git -c` で渡す形は、2026-10-03に止めるようにした
- force pushの宛先の判定に残った穴（2026-10-03のセキュリティレビューの指摘、Low・未検証）。`refs/heads//main` は `/main` とみなされて通る。
  大文字と小文字を区別しない保存先（macOSのローカルbareリポジトリなど）では `Main` が通る。これらの宛先をgitが受け付けるかは、確かめていない

**決めること**: どこまで追うか。入れ子のシェルの解析はシェル意味論の再実装に近づく。
追わない範囲は「確定できない」として止めるか、制約として受け入れるか。

**着手条件**: この経路での取りこぼしを観測したとき。

---

---

## フックの cwd 解決

### payload に cwd が無いときのフォールバック → 決めること

`guard-dangerous-bash.py` は `payload.get("cwd") or os.getcwd()` で判定対象を決める。
`cwd` が無いとき、**フックプロセスがたまたま居るディレクトリ**で判定する。
無関係なリポジトリのブランチを見て誤ブロックする、あるいは見るべきリポジトリを
見ずに素通しする可能性がある。

実際にこの経路がテストへ漏れた（`cwd` を渡さないテストが、チェックアウト中の
ブランチ次第で結果を変えた）。テスト側は既定 cwd を中立化して直したが、
**本体のフォールバックはそのまま**。現在の挙動は
`TestMissingCwdFallback` で意図的に固定してある。

**決めること**: `cwd` が無いときに (a) 現状どおり `os.getcwd()` を使うか、
(b) 判定不能として repo 依存のチェックを飛ばすか。
(b) は保護ブランチのブロックを取りこぼす方向なので、単純に安全とは言えない。

**関連**: `warn-branch-behind-main.sh` は payload の `cwd` を見ず、
プロセスの `cwd` だけで判定している。2つのフックで解決方法が揃っていない。
どちらかが正しいならもう片方は間違っている。

`detect-parallel-sessions.sh`（SessionStart フック）も同様に、payload は
`cat >/dev/null` で読み捨て、判定には `pwd -P`（プロセスの cwd）だけを使っている。
`warn-branch-behind-main.sh` と同じ側に付いたことで3フック中2つがプロセス cwd
派になったが、これは「多数派だから正しい」根拠にはならない。揃っていない問題
そのものは未解決のまま。

**着手条件**: ホストが `cwd` を渡さない事例を実際に観測したとき、
またはフックを別ホスト（Codex CLI）へ配線するとき。

---

## terraform state の機密性

### フックでは囲めない持ち出し経路 → 別の層で決めること

`guard-dangerous-bash.py` が塞いだのは terraform 経由の主要経路
（`state pull` / `output -json` / `output -raw` / `show -json`）のみ。

**塞げないもの**: local backend では state はただのファイルなので、
`cat` `grep` `cp`、任意の言語のワンライナーから読める。
**任意のコマンドから読めるものを Bash のトークン判定で囲むことは原理的にできない。**

現状のフックは「普通に作業しているエージェントが目立つ経路で結果的に漏らす」
ことは防ぐが、それ以上の保証はない。中途半端な防御を守られている証拠と
読み替えないこと。

**決めること**（どれを採るか。複数可）

1. remote backend + 保存時暗号化 + アクセス制御に寄せて、そもそもローカルに
   平文の state を置かない
2. state に秘密を入れない設計へ寄せる（外部シークレットマネージャ参照に置き換える）
3. `.githooks/pre-commit` の検査を state 由来の値に対しても効く形にする
   （ランダム生成のパスワードはパターン検査では捕まらないため、現状は素通りする）

**着手条件**: terraform を扱うリポジトリで、state に秘密が入る構成を実際に採るとき。

---

## 並列セッション検出フックの残課題

### 対象外リポジトリでも「衝突している」ことだけは伝えたい

現在のフックは「分離すべきか」と「何か伝えるべきか」を1つの除外判定にまとめており、
検出より**手前**で抜けている（`hooks/detect-parallel-sessions.sh` の除外判定）。
この2つは本来別の問い。分離できないリポジトリでも、衝突していることは伝えたい。

**動機**: 本ブランチの作業中に実際に事故が起きた（無関係なコミットが他人のブランチに混入）。

**決めること**: 除外判定を検出の**後ろ**に移し、対象外リポジトリでは別の文面
（「衝突しているが分離できないので共有ルールに従え」）を出すか、現状どおり完全に黙るか。
フックの挙動と fail-open のコスト構造が変わるため、別タスクとして扱う。

**着手条件**: F4 の規約追記だけでは事故が防げなかったと分かったとき。

### 動作中のエージェントの規約が背後で入れ替わる → 決めること

`~/.claude/rules` は本リポジトリの作業ツリーへの symlink であるため、別セッションが
本体でブランチを切り替えると、**動作中のエージェントが読む規約の内容が入れ替わる**。
エージェントに届く通知は「ファイルが変更された（意図的な変更）」としか読めず、
**編集とブランチ切替を区別できない**。結果、巻き戻った旧規約を現行規約として扱う。

`rules/parallel-worktree.md` は「worktree 側の編集が本体に反映されない」方向のみ扱っており、
この逆方向（本体の切替が動作中エージェントに影響する）を扱っていない。

**発生例**: 2026-08-13。規約が 25 コミット分巻き戻った状態で作業が進行した。
ただし**実際の判断は誤らなかった**（セッション前半に新しい規約を読んでいたため）。
現実化したのは潜在的な危険であって損害ではない。

**決めること**: 検知を入れるか、入れないか。
設計案（`UserPromptSubmit` フックで HEAD を監視し、動いていれば切替・動いていなければ編集、
と一意に判定する）は検討済みだが、2026-08-16 に**見送りと判断した**。理由は次の3点。

1. 発火条件が狭い（並列稼働 × セッション途中の切替 × 規約差が判断に効く、の連言）
2. 全リポジトリ・全セッションのプロンプト毎に git 呼び出しという恒久コストが乗る
3. 既存の `detect-parallel-sessions.sh` と重なる。**同フックの未解決の穴（上記項目）を
   塞ぐ前に3つ目の機構を足すのは順序が逆**

**着手条件**: 規約の巻き戻りが原因で**実際に誤った判断をした**とき。
潜在的な危険の再発だけでは着手しない。

**参照**: 設計と費用対効果の評価は `cw-workspace-local` の
`docs/superpowers/specs/2026-08-14-local-layer-and-rules-drift-design.md` に記載。

### 列挙を `pgrep` から `ps` へ替える選択肢

macOS の `pgrep` は呼び出し元の祖先プロセスを返さない（実測で確認）。現状は
祖先集合による除外で pgrep の挙動に依存しない形にしたため実害は無いが、
`pgrep` が祖先を返さないぶん**検出漏れ**の可能性は残る。
`ps -Ao pid=,comm=` + basename 一致なら全プロセスを拾えることは実測済み。

**決めること**: 置き換えるか、現状維持か。列挙器の変更は影響範囲が広く、
現時点で観測された不具合は無いため見送っている。

**着手条件**: 検出漏れ、または単独セッションの誤警告を実際に観測したとき。

---

## superpowers の実行フロー

### SDD のレビュー完走を検証する → 決めること

`subagent-driven-development` はタスクごとに実装 → レビュー → 修正ループを回すが、
**その一連が最後まで回ったことを検証する手段が無い**。台帳（`.superpowers/sdd/progress.md`）
はエージェント自身が書くため、書き漏れても誰も気づかない。

実際に起きた事例（2026-08-10 に別リポジトリで確認）:

- 全8タスクのうち7タスクは `complete (commits <base>..<head>, review clean)` の規定形式
- **最終タスクだけ `review clean` を欠き、コミット範囲も無い**
- そのタスクだけ実装者ブリーフとレビュー報告が生成されておらず、
  SDD のループを通らずに完了扱いになっていた
- 最終レビュー用の差分パッケージは生成済みだが、作業ディレクトリが削除されていない
  （スキルの規定では、最終レビューがクリーンになった時点で削除される）

このケースの生成物はドキュメント1件でコード差分ゼロのため実害は無い。
ただし**気づいたのは事後の調査による**もので、通常の運用では検出されない。

**決めること**: 散文ルールとして書くか、機構で強制するか。

- 散文: `CLAUDE.md` に「SDD 完了時に台帳と作業ディレクトリを確認する」を足す。
  数行で済むが、`guard-dangerous-bash.py` を作った経緯と同じ理由で守られない可能性がある
  （このリポジトリは既に「散文だけでは守られない」前提で書かれている）
- 機構: Stop hook で `.superpowers/sdd/` の残存と台帳の行形式を検査する。
  検出条件は機械的に書ける（全 `complete` 行に `review clean` か `parked` があるか）。
  誤検知でセッション終了を妨げない設計にできるかが論点

**着手条件**: 次に SDD で実装を回すとき。それまでは台帳を目視する運用で足りる。

---

## design doc に埋もれている未検証事項

`docs/superpowers/specs/` に「未検証」と書いたまま backlog へ上げていなかったもの。
**spec は設計時点の記録であって、残課題の置き場にはならない**（PR 本文と同じ問題）。

### `ANTHROPIC_BASE_URL` と headroom 設定の衝突

`docs/superpowers/specs/2026-07-31-rtk-integration-design.md:11,88` — headroom 導入を
「既存の `ANTHROPIC_BASE_URL` との衝突リスクが未検証」として先送りしたまま。

**決めること**: headroom を入れるか。入れるなら衝突の有無を先に実機で確認する。
**着手条件**: headroom が必要になったとき。

### 認証プロファイル切り替えの「未検証事項5」

`docs/superpowers/specs/2026-08-01-auth-profile-switching-design.md:52,107` — 未検証事項5と
そのフォールバック節が残っている。設計は入れたが、前提が成立しているかを確認していない。

**決めること**: 検証するか、フォールバック側の設計に倒すか。
**着手条件**: プロファイル切り替えを実際に使うとき。

### Codex 配線スクリプトの `set -euo pipefail` 下での挙動

`docs/superpowers/specs/2026-08-05-codex-superpowers-design.md:131` — 未確認のまま。
**全体停止のリスク**があると spec 自身が書いている。

**着手条件**: 同じ実行経路なので、「superpowers の自動注入をプラグイン同梱フックで賄えるか」に着手するときに一緒に確認する。
分けると2度手間になる。superpowersがCodexで発火することは、2026-08-18に1ターンだけ確かめた。

---

## フックの実行環境

### P2: 1回のBashにつき、PreToolUseのフックが2回呼ばれているらしい

2026-10-04に、`claude bg-spare` で動くバックグラウンドのセッションで起きた。PR作成時の日本語レビューのフックが、
2回目の `gh pr create` 相当の呼び出しでも止め続けた。状態ファイル（`~/.claude/state/jp-doc-review/<session>.pr-dispatched.json`）には、
2回目の呼び出しのときの会話記録の位置が残っていた。1回目の呼び出しの記録は残っていなかった。

1回のBashでフックが2回呼ばれたと考えると説明がつく。どちらのBashでも、一方の呼び出しが止めて記録し、
もう一方がその記録を見て通して記録を消した。止める判定が優先されるので、結果はどちらも止まる。
2回目のBashでも同じことが起き、最後に止めた側の記録だけが残った、という見立てである。

確かめたことは次のとおり。
- フックを単体で同じ入力から2回動かすと、2回目は設計どおり通る
- `jp-doc-review.py pre-tool-use-bash` の登録は `~/.claude/settings.json` に1件だけで、プロジェクトの設定には無い

確かめていないことは次のとおり。
- 本当に2回呼ばれているか。推定の根拠は状態ファイルだけで、呼び出しの回数を直接数えていない
- 対話のセッションでも起きるのか、バックグラウンドのセッションだけなのか
- 自動モード（auto mode）でツールの実行を許すか判定するときに、フックが余分に1回実行されているのか

PR作成時のレビューは止めた記録を消さない形に直したので、2回呼ばれても判定は変わらない（ADR 0025）。
ほかのフックのうち「1回目は止め、2回目は通す」形のものは、同じ影響を受けうる。Confluenceへの投稿前のレビュー、
`skill-read-check.py`、`guard-dangerous-bash.py` の状態を持つ判定が候補になる。

**決めること**: 調べ方。フックに呼び出しの記録（時刻、PID、tool_use_id）を一時的に出させ、対話のセッションとバックグラウンドのセッションで回数を数える。
2回呼ばれていると分かったら、状態を持つフックをすべて、2回呼ばれても同じ結果になる形にそろえるかを決める。

---

## Claude Code 設定の追随

### `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` を外せるか → 残すと決めた（2026-10-07）

`.env` 経由で `settings.json` に `"1"` が焼き込まれており、beta 配信される機能を
受け取れない。**この変数は公式の env-vars ページに記載が無い**（submodule の
全 env var 一覧にはある）。

LiteLLM 公式ドキュメントによれば、Claude Code の beta ヘッダ問題は
**Anthropic 直呼びでは発生せず**、Bedrock / Azure AI / Vertex AI へルーティングする
場合に起きる。恒久対応は proxy 側（`anthropic_beta_headers_config.json` の整備と
v1.81.11-nightly 以降への更新）であり、クライアント側の無効化は回避策でしかない。

**決めること**: 外すかどうか。判断には次の2つが要る。

1. gateway のバックエンドが Anthropic 直か、Bedrock / Vertex か
2. gateway 側 LiteLLM のバージョンが v1.81.11-nightly 以降か

両方が「Anthropic 直 かつ 更新済み」なら、この変数は不要になる。

**決めたこと（2026-10-07）**: 残す。gatewayのバックエンドはBedrock経由で、betaヘッダの問題が起きる経路にあたる。
LiteLLMのバージョンは分からない（gatewayの `/health/readiness` と `/health/liveliness` の応答にバージョンは含まれず、`/version` は404）。
試しに外して1回通っても、betaヘッダは機能ごとに送られるので、外して大丈夫な証拠にはならない。

**着手条件**: gatewayの管理者に、LiteLLMが v1.81.11-nightly 以降かを確かめられたとき。

### rules を `paths:` で遅延読み込みにするか → 決めること

`rules/` 配下は frontmatter が無いため全ファイルが毎セッション展開される。
TypeScript/React 前提の `ecc-coding-style.md` と `ecc-testing.md` が、
Python や Markdown だけを触る作業中も常に効いている。

`paths:` を付ければマッチするファイルを読んだときだけ読み込まれるが、
**`/compact` 後に再注入されない**（次にマッチするファイルを読むまで復帰しない）。
常時効いている必要がある規約（学習モード等）には付けられない。

**決めること**: どの rules を条件付きにするか。候補は `ecc-coding-style.md`
`ecc-testing.md` `ecc-development-workflow.md` の3つで、いずれも「コードを書くとき」
にしか要らない。

**2026-08-16 の `/doctor` 実測で数値を更新**: `rules/` 全体は 21KB ではなく
**40,554 文字（約 10,100 トークン）**まで増えている。常駐コンテキスト全体
（約 14,500 トークン）の **70%** を `rules/` が占める。

ただし候補3ファイルの合計は 6,035 文字（約 1,500 トークン）で、`rules/` 全体の
**15% にとどまる**。**3つ全てを条件付きにしても、削減できるのは常駐全体の約10%**。

| ファイル | 文字数 | 概算トークン | `rules/` 内の割合 |
|---|---|---|---|
| `learning-mode.md` | 20,765 | ~5,190 | **51%** |
| `proving-absence.md` | 4,986 | ~1,246 | 12% |
| `parallel-worktree.md` | 4,945 | ~1,236 | 12% |
| 他6ファイル（候補3つを含む） | 9,858 | ~2,464 | 25% |

つまり**この項目を実行しても、常駐コンテキストの支配的な要因は残る**。
本命は次項の `learning-mode.md` 側にある。

**2026-10-01 に再計測**: ADR 0021 で `learning-mode.md` を常時ruleと詳細skillに分けた結果、
`rules/` 全体は **18,094 文字**、`learning-mode.md` は **4,340 文字**になった。候補3ファイルの合計は
5,999 文字で、`rules/` 全体の **33%** を占める。支配的な要因は解消したため、残る判断は
「コードを書かない作業で ECC の規約を読ませ続けるか」だけになった。

**トークン量ではなく指示の希薄化を減らすことが目的**であり、効果は定量的に測れない。
「測れない改善」であることを承知した上で着手すること。

**着手条件**: 指示が守られない事例が実際に出たとき、または CLAUDE.md と rules の
合計がさらに増えたとき。

2026-10-07の棚卸しで `ecc-testing.md` を削除し、`ecc-development-workflow.md` を縮めた。
候補は `ecc-coding-style.md` と `ecc-development-workflow.md` の2つになった。`paths:` を付けるかは、上の着手条件のとおり。

### コンテナ環境で PreToolUse フックが fail-open している → `cw-workspace-local` へ移管する（先方への追記待ち）

2026-08-16 に、Linux コンテナで `rtk: Permission denied` などの `hook_non_blocking_error` が
多発し、PreToolUse の hook が静かに素通りしていた。2026-10-01 の確認では次のとおり。

- `cw-workspace-local` はコンテナ起動時に `cw_doctor.py --check-pre-tool-use-hooks-only` を実行し、
  PreToolUse の hook が起動できない・他ユーザーが書き込めるときは起動を止める（fail-closed）
- 直近のコンテナセッション（2026-09-08 の3件）に hook のエラーは無い
- コンテナ内で `guard-dangerous-bash` が登録され効いているかは未確認。記録に残る PreToolUse:Bash は
  `rtk hook claude` だけだが、無出力で成功した hook が記録に残るかが分からない

残りの確認は、コンテナの設定を管理する `cw-workspace-local/tasks/backlog.md` で追跡する（二重管理を避ける）。
2026-10-01 時点で先方の作業ツリーに未コミットの変更があったため、追記は保留している。
追記したらこの項目を参照だけに縮める。

---

## リンク先のディレクトリへの混入

### P3: ツールが書き込んだファイルが、未追跡のままリポジトリに現れる

**着手条件**: 同じ形の混入がもう一度起きたとき。それまでは `.gitignore` に1件ずつ足して対処する。
**決めること**: 次の2つのどちらで止めるか。両方を使うか。
- リンクの粒度: `rules/`・`commands/` はディレクトリごとリンクしている。skills のように中身を1件ずつリンクする形に変える
- 検出: `setup.sh` かコミット前の検査で、リンク対象のディレクトリにある未追跡のファイルを警告する

これまでに2回起きた。`rules/*.rules` は、Codex が `~/.codex/rules`（ディレクトリごとのリンク）を通して書き込んでいた。
`skills/synced/`（2026-10-08作成、claude.ai から同期されたスキル）は、`~/.claude/skills` と `~/.agents/skills` が skill ごとのリンクなので、どの経路で書き込まれたか分かっていない。
エージェント向けのルールでは止められない。書き込んでいるのはツール本体だからだ。

---

## 仕事の原則集

`jp-doc-review` の課題は、上の「日本語文書レビュー（yomiyasu）の続き」にある（P1）。ここには重ねて書かない。

### 原則集の basis を照合して公開する

**決めること**: basis を動画と照合する範囲（全25件か、助言でよく引かれる原則だけか）。
仕事の原則集の公開コピーには、照合していない basis を入れていない（ADR 0028）。照合したら、書き出しの公開する欄に basis を足す。

### 原則レビューのフックと助言スキルを Codex に対応させる

**決めること**: Codex のフック（`codex/hooks.json`）で同じ挙動を作るか、助言スキルだけを共有するか。
`principle-reviewer` の指示文が名指しする原則集のパスは `~/.claude/skills/work-principles/` だけで、Codex では読む先が違う。対応するときに、ホスト別のパスを併記する。

### フックの無いブランチへ戻すと全 Bash が止まる

**決めること**: 全フックの command を「ファイルが無ければ表示して通す」形にそろえるか、`setup.sh` がブランチの切り替えを検知して生成し直すか。
設定リポジトリの作業ツリーを、あるフックを足す前のブランチへ戻すと、生成済みの `~/.claude/settings.json` がまだそのフックを呼び、
ファイルが無いので exit 2 になって全 Bash が止まる。`principle-review.py` だけは command 側で避けた（仕様書 2026-10-08-work-principles-design.md の10章）。

### `unittest discover` が一部のテストで止まる

**決めること**: 原因の調査を先にするか、止まるモジュールを分けて走らせるか。
`python3 -m unittest discover -s tests` を実行すると、`test_codex_model_switch`・`test_learning_store`・`test_setup_cli`・`test_setup_preflight` で止まる（2026-10-08、main 由来、原因は未調査）。

### `permissions.deny` で Read・Grep の機密パスを拒否するか

**決めること**: 拒否するパス（`~/.ssh`・`~/.aws`・`.env` など、どこまで含めるか）と、`settings.json.template` に書くと全セッションの Read・Grep に効くことを受け入れるか。
`principle-reviewer` は Read だけを使うが、成果物に読み先を指示されても従わないことは指示文で頼んでいるだけで、仕組みでは止めていない（2026-10-08 のセキュリティレビュー）。

### guard-dangerous-bash.py と jp-doc-review.py の git 呼び出しも、承認前に相手の設定で動く経路（lazy fetch・filter など）を塞ぐか

**決めること**: `hooks/principle-review.py` の `_git`（GIT_ 環境変数を引き継がない、`GIT_NO_LAZY_FETCH=1`、fsmonitor・フック・通信の無効化、
filter の打ち消し、新しいセッションで起動してグループごと止める）を共通の補助に切り出して使うか、それぞれに必要な分だけ足すか。
どちらのフックも利用者がコマンドを承認する前に、作業中のリポジトリで `git` を実行する。原則レビューのフックでは、
partial clone の lazy fetch とサブモジュールの filter が承認前に走ることを 2026-10-08 に実測した。ほかの2つは確かめていない。

### Git 2.45 未満で lazy fetch を止められない／per-protocol の allow で -c が上書きされる

**決めること**: Git 2.45 未満を「検査できなかった」扱いにするか、`protocol.{file,ssh,git,http,https,ext}.allow=never` を明示するか。
`GIT_NO_LAZY_FETCH` は Git 2.45.0 以降で効く。それ未満では lazy fetch を止められず、リポジトリの設定のコマンドが承認前に走りうる。
`-c protocol.allow=never` も、リポジトリの `protocol.<名前>.allow=always` に上書きされる（仕様書 2026-10-08-work-principles-design.md の6章・10章）。

### mainのマージで入ってきたレビュー済みのADRを、原則レビューが新規として止める

**決めること**: マージコミットでは、マージ元ですでにコミット済みのADRを対象から外すか（`MERGE_HEAD` の有無で判定するなど）。
2026-10-09に、PR #71のブランチへmainをマージして、ADRのコンフリクトを解消した。すると、mainですでにレビュー済みのADR 0029が新規の追加として扱われ、コミットが止まった。
このときは、ユーザーの判断でレビューを省いた。

### worktreeでは `.githooks/patterns-local.txt` が無く、pre-commit がマージコミットを止める

**決めること**: worktreeを作るときに本体からコピーするか、pre-commitが `git rev-parse --git-common-dir` で本体の作業ツリーにある定義を探すか。
`patterns-local.txt` はgitignoreされていて、`git worktree add` では持ち込まれない（`rules/parallel-worktree.md` の「分離した後にやること」）。
2026-10-09に、PR #71のworktreeでマージコミットを作ろうとしたところ、pre-commitに止められた。

### リポジトリのルートに制御文字・書式文字があるとレビュワーがファイルを開けない

**決めること**: `has_control` を絶対パスに当てて除外するか。
いまは相対パスにだけ当てているので、ルートに制御文字・書式文字があると、パスは escape して表示され、レビュワーがファイルを開けない（仕様書の10章）。
