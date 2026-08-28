# Codex runtime smoke test 証跡

記録日: 2026-08-27
対象BASE: `77974734bed817fc79e7940ef74461db4f185e05`
検証時HEAD: `eb520766be67f894260a70e9e6a84648aa40ba32`

## 実行環境

- Codex CLI: `codex-cli 0.149.1`
- 作業開始時のHEADはBASEと一致していた。以後の検証commitを積む間も、既存の未コミット変更は保全し、本タスクで変更・stage・revertしていない。
- 実HOMEではsetup/runtime probeを実行していない。すべて使い捨てHOMEへ限定したため、実HOMEへの変更はない。
- Fix round 1の静的検証は、`/tmp/task-6-fix-round-1.pTHUgI/repo` にlocal clean cloneした `e7f1e57` のdetached HEADで実行した。clone前後の `git status --short` は空であり、実リポジトリのbranch、index、未コミット変更は操作していない。
- Fix round 2の静的検証は、`/tmp/task-6-fix-round-2.uILYi6/repo` にlocal clean cloneした `eb7e832` で実行した。clone直後の `git status --short` は空であり、実リポジトリの既存未コミット変更を検証対象へ混ぜていない。
- Step 2は、`/tmp/task-6-step-2.uJpLZp/repo` にlocal clean cloneした `eb52076` と、同ディレクトリ配下の使い捨てHOMEで実行した。submoduleは正本の固定済みcheckoutをlocal sourceとして初期化し、cloneに`.env`が無いことを確認した。実HOME、認証情報、ネットワークを使わないため、`claude`と`codex`は呼び出しを記録して固定JSONを返すstubへ差し替えた。

## Step 1: 静的スイート

| コマンド | 期待結果 | 観測結果 | 状態 |
| --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -v` | failure 0、全件完走 | exit 1。正本環境では236件中 failure 1 / error 11。Gitの署名設定がテスト用一時リポジトリの空コミットを失敗させた。 | 失敗 |
| 同コマンド（`GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1` の補助診断） | failure 0 | exit 1。280件中 failure 2。 | 失敗 |
| clean clone `e7f1e57` での `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 python3 -m unittest discover -s tests -v` | failure 0、全件完走 | exit 1。280件中 failure 1。`test_own_process_tree_is_excluded` が空配列期待に対して自己プロセスの一時repoを1件返した。 | 失敗 |
| clean clone `eb7e832` での `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 python3 -m unittest discover -s tests` | failure 0、全件完走 | exit 0。281件を168.430秒で完走。 | 成功 |
| `bash -n setup.sh hooks/*.sh bin/ccp bin/detect-parallel-sessions` | exit 0 | exit 0 | 成功 |
| `python3 -m json.tool`（`settings.json.template`、`codex/hooks.json`、`codex/plugin-policy.json`、`manifests/skills.json`） | 各exit 0 | 各exit 0 | 成功 |

補助診断の失敗は次の2件である。

1. `test_policy_schema_and_exact_classifications`: 既存の未コミット変更 `codex/plugin-policy.json` に `atlassian@claude-plugins-official` の deny エントリが追加され、テストの固定期待値と異なる。本タスクの変更所有権外のため変更しない。
2. `test_own_process_tree_is_excluded`: `bin/detect-parallel-sessions` がテストプロセスの祖先PIDを検出結果から除外できず、空配列期待に対して一時リポジトリの1件を返した。

正本環境の11 errorは、グローバルGit署名設定がテストfixtureの空コミットに適用され、利用可能な署名agentがないことで発生した。補助診断ではこの環境要因を除去して280件まで完走したが、上記2 failureは残った。

Fix round 1では、未コミットのuser変更を除外するため `mktemp -d /tmp/task-6-fix-round-1.XXXXXX`、`git clone --no-local --no-hardlinks`、`git checkout --detach e7f1e57513903c5d0daedf1cc31f683b6a76c619` を順に実行した。clean cloneでの探索範囲は、このcommitの全テスト（280件）である。この時点では自己祖先除外failureが残ったため、Step 2〜3・5〜7のruntime検証には進まなかった。

Fix round 2では、CodexのmacOS sandboxで`ps`が拒否されると、検出スクリプトが直接親のPIDを祖先集合へ追加できないことを根本原因とした。OpenAI公式の[Sandbox](https://developers.openai.com/codex/concepts/sandboxing/)は、spawnしたコマンドも同じsandbox境界を継承し、macOSではSeatbeltで強制すると説明しており、この環境差と整合する。`ps`をexit 1へ固定した回帰テストは、修正前に親Python PIDを1件返してREDとなった。直接親をshellの`PPID`から登録し、`ps`を祖父以上の補完だけに使う最小修正後、同テストと関連14件がGREENになった。続いてclean cloneの全281件、shell構文、4 JSONを検証し、すべてexit 0となった。これによりStep 1のstatic gateは成功へ転じたが、Task 6のruntime検証は未完了である。

## Step 2: 隔離HOMEでのsetup

期待結果: `--claude`、`--codex`、`--all` の再実行が冪等であり、未所有パスと `--replace-conflicts` の所有権・backup復旧を確認する。

OpenAI公式の[Advanced Configuration](https://developers.openai.com/codex/config-advanced)は、Codexのlocal stateが`CODEX_HOME`（既定`~/.codex`）に置かれると説明する。setupは`HOME/.codex`を配布先にするため、実HOMEではなくselectorごとに独立した使い捨てHOMEを与えた。

| selector | 初回 | 2回目 | host境界 |
| --- | --- | --- | --- |
| `--claude` | exit 0 | exit 0 | `.codex`のsentinel 1件だけを維持し、`.agents`を作らない |
| `--codex` | exit 0 | exit 0 | `.claude`のsentinel 1件だけを維持する |
| `--all` | exit 0 | exit 0 | Claude、Codex、Agent skillsの対象をすべて配置する |

初回後のHOMEをcopyし、2回目後とregular file checksumおよびsymlink targetで比較した。3 selectorとも内容とsymlink topologyに差分はなく、代表4 symlinkのinodeも一致した。Claude生成JSONと両hostのownership stateは同内容で再配置されるためmtimeだけが更新された。したがって確認できた冪等性は「同一状態へ収束すること」であり、「2回目が一切writeしないこと」ではない。

`--all`の競合fixtureには、Claude側の`.claude/CLAUDE.md`とCodex側の`.agents/skills/api-design`を未所有regular fileとして置いた。通常実行は2件を報告してexit 1となり、HOMEのchecksum・symlink topologyは実行前copyと一致した。backup、ownership state、CLI stub logも作成されず、選択hostへの部分適用はなかった。

同じHOMEへ`--all --replace-conflicts`を実行するとexit 0となり、両方の元ファイルを同一timestamp `20260827_142934` のhost別backupへ退避した。Claude側は`.claude/backups/20260827_142934/CLAUDE.md`、Codex側は`.codex/backups/20260827_142934/.agents/skills/api-design`である。backupと実行前copyはbyte単位で一致し、各destinationは正しいsymlinkへ置換され、両hostのownership stateが作成された。その直後の通常`--all`もexit 0で、backupの個数と内容を維持した。

手動復旧はHOMEを複製し、`.claude/CLAUDE.md`と`.agents/skills/api-design`のsymlinkを明示的に外して、対応するbackupを元パスへmoveする形でシミュレートした。復旧した元ファイルの**内容**は実行前copyとbyte単位で一致した。これは内容を手動復旧できる証拠であり、permission、mtime、ownerなどのmetadata復元や、setup自身のrestore CLIを確認したものではない。

回帰検査として`bash -n setup.sh`はexit 0、`GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 python3 -m unittest tests.test_setup_cli tests.test_setup_preflight -v`は47件を159.529秒で完走し、failure / error 0だった。

このprobeが確認したのはsetupのbash、Git、Python、filesystem上の配布契約である。plugin CLIはstubのため、pluginの実導入・監査runtimeはStep 6の未確認事項として残る。cloneに`.env`を含めていないため、実credentialを使うClaude設定生成も実行していない。

状態: 成功。

## Step 3: hook信頼とSessionStart

期待結果: 隔離Codexで `/hooks` を確認・承認し、新規起動とcompact継続でsuperpowers注入および有効なSessionStart出力を確認する。
観測結果: 未実行。今回の実行単位はStep 2までとしたため。
状態: 未確認。

### Step 3 後続部分checkpoint（2026-08-28）

OpenAI公式の[Hooks](https://developers.openai.com/codex/hooks)は、non-managed hookを実行前にreview/trustすること、trustがcurrent definition hashに紐づき定義変更後は再reviewまでskipされることを定義する。同文書で、SessionStartのsourceは`startup` / `resume` / `clear` / `compact`、commandのplain stdoutはdeveloper contextへ追加されること、root sessionのcompact後は`compact`にmatchするSessionStart hookが次のmodel request前に実行されることを確認した。

- 実測時のCodex CLIは`0.150.1`、Pythonは`3.14.6`だった。これは既存の古いcheckpointを置換せず、その後続versionとして記録する。
- active `~/.codex/hooks.json`はrepoの`codex/hooks.json`、active `~/.codex/hooks`はrepoの`hooks`へのsymlinkだった。`hooks.json`のrepo/active SHA-256は双方`ac3b2dd184eab6466ab9ec3c9ff77b4146116218cbcf3c1a5d1a07b70d5fc6ec`、`inject-superpowers.sh`のrepo/active SHA-256は双方`afe066762399fef808257da4b7fb4e9a455cd34d4fcb2c025c3ec22035473da5`だった。
- active scriptへsynthetic payloadを与えると、`startup` / `resume` / `clear` / `compact`のすべてで次の1行をstdoutへ返した。invalid JSONおよびnon-SessionStart payloadはexit 1とdiagnosticになった。

  ```text
  Before responding, read and follow superpowers:using-superpowers from the enabled Codex plugin.
  ```

- 現sessionのdeveloper contextにも同じ1行が正確に届き、main agentは実際に`superpowers:using-superpowers`を全文読んだ。配線、content hash、synthetic output、model-visible contextが一致するため、current-sessionでactive repo hookの出力が注入されたことと整合する。

このcheckpointは部分確認であり、Step 3を完了扱いにはしない。model contextはSessionStartのsource値、persist済みtrust hash、launch時のtrust bypass有無を公開しないため、これらを確認済みとは書かない。`/hooks` UIでのsource/hash/trustの表示・操作、fresh disposable startup、実際の`/compact` continuationは実行していない。trust state、hook enabled state、credential、実HOMEファイルは変更していない。

未確認の不在主張は次の範囲に限定する。主張: 上記3種類のruntime確認は未実行である。探索範囲: current sessionのdeveloper context、active symlinkとcontent hash、active scriptへのsynthetic payload、および公式Hooks文書である。範囲の根拠: これらは配線・出力契約・現sessionの注入を覆うが、UI state、fresh process startup、compact continuationを発生させない。反証条件: `/hooks` UI、fresh disposable startup、または実際の`/compact` continuationを実行してsource/hash/trust、起動時注入、compact後注入を観測した場合、この未確認範囲は更新される。

## Step 4: 代表subagent（controller実測）

このStepは隔離HOMEで実行していない。controllerは現在の親Codex sessionからCodexの`spawn_agent`操作で各agentを起動した。書込み対象は、リポジトリ内でグローバルGit ignoreされるSDD一時領域 `.superpowers/` に限定され、configとHOMEは変更していない。独立したnested session用HOME、`HOME`の値、個々の一時ファイル名はcontroller記録にないため、隔離HOMEだったとは主張しない。

| agent | repository生成設定 | runtime観測 | 操作結果 | 状態 |
| --- | --- | --- | --- | --- |
| `code-explorer` | model `gpt-5.6-luna`、sandbox `read-only` | modelはGPT-5（正確なvariant未確認）、sandbox `workspace-write` | hook 2ファイルをread。SDD一時ファイルの作成・削除に成功。 | 部分確認。runtime read-only期待は未達。 |
| `code-simplifier` | model `gpt-5.6-luna`、sandbox `workspace-write` | model未確認、sandbox `workspace-write` | SDD一時Pythonを`if/else`から`return bool(value)`へ編集。構文・挙動検査PASS。 | sandboxのみ確認。 |
| `planner` | model `gpt-5.6-sol`、reasoning `high`、sandbox `read-only` | model/effort非公開で未確認、sandbox `workspace-write` | 一時ファイルの作成・削除に成功。 | 部分確認。runtime read-only期待は未達。 |

OpenAI公式の[Subagents documentation](https://developers.openai.com/codex/concepts/subagents)は、subagentが親のsandbox policyを継承し、親turnのlive runtime overrideがcustom agent fileのdefaultより再適用されると説明する。したがって、read-only TOMLとworkspace-write実測の差は現行仕様と整合する。

ただし、この親turnではTask 6の「`code-explorer`をread-onlyでruntime確認」は達成していない。反証条件は、親をread-onlyにした別sessionで`code-explorer`を実行したときにworkspace-writeを観測すること。未実行のため、configured read-onlyがruntimeで有効になることは未確認である。

## Step 5: security cost boundary

期待結果: 通常の文書差分はLLM security reviewを起動せず、認証/入力検証差分はLunaの`security-reviewer`を起動し、判断不能時に親が人間へ上位モデルの確認を求める。

観測結果:

- 通常のdocs-only synthetic diffはsecurity boundary非該当と分類し、LLM reviewerをspawnしなかった。
- authentication + user inputを含むsynthetic diffだけを`agent_type=security-reviewer`へdispatchした。現在のspawn tool contractとrepo生成設定では、このroleは`gpt-5.6-luna`固定である。
- 最初のdispatchでは、gitignoredな`.superpowers` artifactをchild環境から取得できず、入力不足として`Confidence: insufficient`になった。これはコードレビュー結果ではなく、artifact delivery failureとして分離した。その後、同じ軽量reviewerへdiffをinlineで再送した。
- 軽量review結果は、token長上限なしがMedium、`verifyWithIdentityProvider`契約不明が条件付きHigh、caller認可不明が条件付きHighだった。`Confidence: insufficient`かつ`Human confirmation required: yes`だったため、親は強いmodelを自動spawnせず、ユーザーへ確認した。
- ユーザーの回答「おkつづき」で承認を得た後だけ、default agent（`gpt-5.6-sol`、reasoning `high`）をdispatchした。上位review結果は、認証検証契約がコード上で保証されない点が条件付きHigh、token長無制限が条件付きMedium、無効credentialの失敗動作未定義が条件付きMediumだった。意図的に根拠を欠いたfixtureのため、こちらも`Confidence: insufficient`だった。
- このprobeはコスト境界の制御経路を確認するためのsynthetic inputであり、実credentialやproduction codeは変更していない。

判定: 成功。通常差分の非起動、境界差分の軽量review、判断不能時の人間確認、承認後だけの上位review dispatchを確認した。

限界: reviewer自身による正確なruntime model名のself-reportは未確認である。`gpt-5.6-luna`はspawn toolの固定role contractとrepo生成設定に基づくrouting証拠であり、runtime self-reportの代替ではない。
状態: 成功。

### Step 5 fix round 1: 再現可能な操作記録

- ordinary fixture: docs-only synthetic diff。artifact SHA-256は`9c2b93d9dc2a2d3ed52bee703ade42aa49a0ace5a27d5d91b1f5effb427e12d0`。security boundary非該当として分類し、LLM reviewerはspawnしなかった。
- boundary fixture: `resolveSession` / `verifyWithIdentityProvider`を含むauthentication + user input validationのsynthetic diff。artifact SHA-256は`6e4b99a9d8618bffc12a9b3a805ae00ee79c326f525ea2abdc5148a85b39947e`。
- 操作列: boundary fixtureについて`spawn_agent(agent_type="security-reviewer")`を実行 → gitignored `.superpowers` artifactをchild環境から取得できず、artifact delivery failureとして入力不足の`Confidence: insufficient`を記録 → 同一reviewerへinline diffを`send_input`して再送 → 軽量reviewの`Confidence: insufficient` / `Human confirmation required: yes`を受け、ユーザーの「おkつづき」を取得 → 承認後に`spawn_agent(agent_type="default", model="gpt-5.6-sol", reasoning_effort="high")`を実行した。
- 初回artifact delivery failureはコードreview所見ではなく配信失敗として扱い、inline retry後のreview結果と分離した。Lunaのexact runtime self-reportが未確認である限界は変わらない。

## Step 6: pluginとlearning

期待結果: plugin audit、`codex plugin list --json`、両ホストでのコード参加・skip・構成作業を確認する。
観測結果: 未実行。今回の実行単位はStep 2までとしたため。
状態: 未確認。

## Step 7: 公式default statusline

期待結果: 明示的な`tui.status_line`なしの隔離Codexで可視フィールドを記録する。
観測結果: 未実行。今回の実行単位はStep 2までとしたため。
状態: 未確認。

## Step 6/7 checkpoint（2026-08-28）

### Step 6: plugin policy と learning behavior

| 対象 | expected | observed | status |
| --- | --- | --- | --- |
| plugin policy | `bin/audit-codex-plugins.py` が違反なしとなり、default-deny plugin はすべてdisabled、context7 / serenaもunapprovedのままである | `python3 bin/audit-codex-plugins.py` はexit 0（`Codex plugin policy violations: none`）。clean cloneでの `python3 -m unittest tests.test_codex_plugin_policy -v` は20件、failure / error 0。`codex plugin list --json` はexit 0、installed 17 / enabled 8で、enabled 8は`openai-primary-runtime` / `openai-bundled`由来。`claude-plugins-official`由来9件（context7 / serenaを含む）はすべてdisabled。 | 成功 |
| superpowers current-session利用 | 有効なsuperpowers skillを現在sessionで利用できる | active configの`[plugins."superpowers@openai-curated"] enabled = true`、cache manifest（superpowers 6.3.0、skillsあり、hooks `{}`）を確認した。このsessionでcacheの`superpowers:using-superpowers`と`subagent-driven-development`を実際に読んで利用した。 | 確認済み |
| superpowers inventory | `codex plugin list --json`がsuperpowersのinventory登録状態を示す | Codex CLI 0.150.1でinstalled 17 / available 0、superpowers entryは0件だった。active configのplugin宣言は18件で、installedとの集合差は`superpowers@openai-curated`だけだった。これはcurrent-sessionでのskill利用確認とは別の観測である。 | 未確認（config/cacheとCLI inventoryが不一致。再インストール・ID変更は未実施） |
| Codex controlled code participation | learning-mode ruleを正確に読んだ後、signature・目的コメント・TODO・テストを先に用意し、5〜10行の参加依頼、skip後の自己実装、構成作業除外を確認する | controlled probeでは前提を用意して参加を依頼し、`スキップ`後に同じ判断を再質問せず自己実装した。親実測の`GOCACHE=/tmp/task-6-step-6.HIWqiw/go-cache-verify-1 go test -cover ./...`はPASS（coverage 100%）、同GOCACHEの`go vet ./...`もPASS。configuration exclusion probeでは`agent-config.toml`を質問・コード参加なしで作成し、`tomllib` parse resultは`{'log_level': 'debug', 'max_retries': 3}`だった。 | 部分確認（Codex側のみ） |
| Codex natural learning probe | ruleを明示しない通常の発火でもlearning-mode契約を満たす | 選択式Predictで選択と理由を同時に質問し、参加依頼前にsignature・目的コメント・TODOを実作業ツリーへ用意しなかった。skip後の再質問はせず自己実装し、親実測の`go test -cover ./...`はPASS（coverage 100%）、`go vet ./...`もPASS。 | 未達。モデル判断だけで常時遵守されるとは主張しない。 |
| Claude learning probe | Claude側でもcode participation、skip、configuration exclusionを確認する | isolated HOMEの最初のprobe sessionはassistant実行前に`API Error: Can't reach the API server — check your internet or DNS (ENOTFOUND)`で終了した。再試行はユーザーが中断した。sandboxではprocess listを検査できなかったためprocess不在は未確認。 | 未確認。networkを使える環境で別タスクへ延期。 |

#### superpowers inventoryの追加切り分け

- OpenAI公式の[Developer commands](https://developers.openai.com/codex/cli/reference)は、`codex plugin list --json`が`installed`と`available`の2配列を返すと定義する。今回の不在主張はこの2配列だけを対象とし、runtime loaderやcache全体へ拡張しない。
- OpenAI公式の[Plugins](https://developers.openai.com/codex/plugins)は、OpenAI API keyでCodexへsign inすると、対応するOpenAI-curated pluginを閲覧・install・管理できると説明する。実測の`codex login status`は`Not logged in`で、`available`が0件なのはこの条件と整合する。ただし、未認証がsuperpowersの`installed`脱落まで引き起こしたとは確認していない。
- `codex plugin marketplace list --json`が返した現在のcurated marketplace名は`openai-api-curated`だった。一方、active configとruntime cacheは`superpowers@openai-curated`および`~/.codex/plugins/cache/openai-curated/superpowers/6d99ee14`を使う。marketplace checkoutのHEADとcache hashはともに`6d99ee14`で、同checkoutの`openai-curated` / `openai-api-curated`両catalogにsuperpowers entryがある。cache manifestはversion 6.3.0、skillsあり、hooks `{}`であり、このsessionでは同cacheのskillを実際に読めた。
- `codex plugin list --json`はsandbox内外のどちらでもinstalled 17 / available 0だったため、sandbox内のDNS制限だけでは差分を説明できない。active config 18件とinstalled 17件の集合差は`superpowers@openai-curated`だけである。

現時点の仮説は、runtime loaderが旧marketplace IDのcacheを利用できる一方、CLI inventoryは現在のmarketplace IDまたは認証状態と整合せずentryを返していない、というものである。これは原因確定ではない。ID変更だけの効果は、実HOMEを変更せずにreserved marketplace名を再現する試験がCLIに拒否されたため未確認である。再install、config ID変更、plugin enabled state変更は実施していない。

不在主張を次の範囲へ限定する。主張: Codex CLI 0.150.1で取得した`installed` / `available`配列にsuperpowers entryが無かった。探索範囲: sandbox内外の`codex plugin list --json`出力をpluginId/nameで照合し、active configのplugin ID集合とも比較した。範囲の根拠: OpenAI公式Developer commandsが、この2配列を同コマンドのinventory出力として定義している。反証条件: 認証、marketplace refresh、config ID、または別versionの条件を変えた同コマンドがentryを返す場合、今回の観測はその条件を覆わない。runtime loaderやcacheがentryを利用できないという主張はしておらず、実際にcurrent-session利用が反証している。

Claude scratchの不在主張は次の範囲に限定する。主張: `claude-learning-code-participation`と`claude-learning-config`の両scratchに、検査時点で`rg --files`が列挙するファイルは無かった。探索範囲: `/tmp/task-6-step-6.HIWqiw/claude-learning-code-participation`と`/tmp/task-6-step-6.HIWqiw/claude-learning-config`へ個別に`rg --files`を実行し、両方exit 1・出力なしを観測した。親ディレクトリの`ls -la`で両scratchの存在を確認し、各scratchへの`ls -la`で空ディレクトリであることを観測した。範囲の根拠: 前者はcode-participation probeのJSONLに記録されたcwd、後者は予定していたconfiguration probe用scratchであり、各probeが意図して書き込む場所である。反証条件: Claudeがこれら以外へ書いた、hidden fileだけを作った、または検査後に書いた場合はこの主張と両立する。この検査は意図した2 scratch外を覆わない。再試行session JSONLの有無は今回のscratch走査では検査していないため未確認とする。

### Step 7: 公式default statusline

| 対象 | expected | observed | status |
| --- | --- | --- | --- |
| 隔離Codexのdefault statusline | 明示的な`tui.status_line`なしでTUIを起動し、公式defaultの可視fieldを記録する。custom item listは保存しない。 | isolated `CODEX_HOME=/tmp/task-6-step-6.HIWqiw/codex-statusline-home`で`codex login status`はexit 1（`Not logged in`）。実HOMEのcredentialをcopy / symlinkせず、TUIを起動しなかった。`tui.status_line`を保存する操作もしていない。 | 未確認。認証済みの隔離環境を用意できた場合に確認・反証できる。 |

### checkpointの境界

- security boundary: 該当なし。今回の変更はdocs-onlyであり、認証・認可・入力・API・secrets・権限・deployment設定を変更しない。
- 実HOME、plugin enabled state、hook trust state、credentialは変更していない。

## 限界と次の確認

- static gate、隔離HOMEのsetup probe、security reviewのコスト境界（Step 5）、Step 6のplugin policy、Step 3のcurrent-session注入の部分証跡は確認した。runtime全体の成功は主張できない。
- Step 3は`/hooks` UI trust、fresh disposable startup、実際の`/compact` continuationが未確認である。探索範囲・範囲根拠・反証条件はStep 3後続部分checkpointに限定して記録した。
- 残項目は、Step 3のUI trust/fresh startup/compact、Claude側Step 6、Step 7、superpowers inventoryの根本原因である。`code-explorer`と`planner`のruntime sandboxがread-onlyであることも未確認であり、親read-only sessionの追加試験が必要である。
- 本タスクでは実HOME、既存の `codex/plugin-policy.json`、`tasks/backlog.md`、`learning/entries/2026-08-27-*` を変更していない。
