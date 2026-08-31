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

このcheckpointは部分確認であり、Step 3を完了扱いにはしない。model contextはSessionStartのsource値、persist済みtrust hash、launch時のtrust bypass有無を公開しないため、これらを確認済みとは書かない。`/hooks` UIでのsource/hash/trustの表示・操作、fresh disposable startup、実際の`/compact` continuationについて、このcheckpointには実行を示す証跡がない。trust state、hook enabled state、credential、実HOMEファイルは変更していない。

証跡不在の主張は次の範囲に限定する。主張: このcheckpointには、上記3種類のruntime確認の実行を示す証跡がない。探索範囲: このcheckpointに記録したcurrent sessionのdeveloper context、active symlinkとcontent hash、active scriptへのsynthetic payload、および公式Hooks文書である。範囲の根拠: これらは配線・出力契約・現sessionの注入を記録するが、UI state、fresh process startup、compact continuationの実行記録を取得する操作ではない。反証条件: このcheckpointの記録に、`/hooks` UI、fresh disposable startup、または実際の`/compact` continuationの実行を示すsource/hash/trust、起動時注入、compact後注入の証跡が含まれる場合、この主張は誤りである。Step 3はこの未確認を含むため未完了である。

### Step 3 app-server checkpoint（2026-08-28）

OpenAI公式の[Codex App Server](https://developers.openai.com/codex/app-server)は、`hooks/list`が1つ以上のcwdについて検出済みhookを列挙すると定義する。Codex CLI 0.150.1から`--experimental`付きで生成したJSON Schemaでは、各hookに`sourcePath`、`currentHash`、`enabled`、`trustStatus`があり、trust statusは`managed` / `untrusted` / `trusted` / `modified`の4値だった。

実行時version: Codex CLI `0.150.1`、Python `3.14.6`。以下の`<repo>`と`<scratch>`は使い捨ての作業領域であり、実HOMEの絶対パス、credential、active trust stateは記録・変更していない。2026-08-31のfix roundでは、下記fixture TOMLとJSONLを固定してtrust fixtureとfresh startupを再実行し、同じ結果を確認した。

| 操作 | 実行コマンド / JSONL操作 | expected | observed | version | 制約 / 限界 |
| --- | --- | --- | --- | --- | --- |
| Schema生成 | `codex app-server generate-json-schema --experimental --out <schema-dir>` | app-server protocol schemaを生成し、hookのsource/hash/enabled/trust fieldsを検査可能にする | exit 0。生成schemaに`sourcePath`、`currentHash`、`enabled`、`trustStatus`と4つのtrust status enumを確認した。 | Codex CLI `0.150.1` | experimental schemaはこのCLI versionの契約であり、別versionの互換性を証明しない。 |
| active stateの診断 | `codex app-server --stdio`、続いて`codex doctor --summary --no-color --ascii` | active state DBが使用可能ならapp-serverを通常起動でき、doctorはintegrity failureを返さない | 通常起動は`state_5.sqlite`初期化に失敗し、doctorもstate database integrity failureを返した。 | Codex CLI `0.150.1` | DBの退避・修復・再生成は実施しておらず、通常起動の成功は確認していない。 |
| active `hooks/list` | `codex app-server -c 'sqlite_home="<scratch>/active-hook-probe-sqlite"' --stdio`を起動し、下記の`initialize` → `initialized` → `hooks/list`を送信 | active hooksのsource、enabled、trust status、warning/errorを列挙する | warning / error 0、4件enabled、sourceはすべて`user`。PreToolUse 2件は`trusted`、SessionStart 0:0は`modified`、0:1は`untrusted`だった。 | Codex CLI `0.150.1` | SQLite runtime stateだけを分離したread-only列挙であり、`/hooks` UI承認や通常startupを実行していない。 |
| stateなしfixtureの`hooks/list` | `CODEX_HOME=<scratch>/isolated-codex-home codex app-server --stdio`を起動し、下記の同じ3 JSONLを送信 | stateなしでは現行SessionStart definitionが未trustとして列挙される | SessionStart 0:0と0:1はそれぞれ現行`currentHash`で列挙され、両方`untrusted`だった。 | Codex CLI `0.150.1` | credentialを持たない使い捨てHOMEであり、active trust stateを検査していない。 |
| trust fixture後の`hooks/list` | 下記2 symlinkと`config.toml`を`<scratch>/isolated-codex-home`へ作成し、同じ3 JSONLを送信 | fixtureに登録した2件だけが`trusted`になる | SessionStart 0:0と0:1はともに`trusted`。 | Codex CLI `0.150.1` / Python `3.14.6` | 現行hashを隔離configへ直接書いたfixtureであり、active `/hooks`承認の成功を意味しない。 |
| fresh startup | 同じapp-serverへ下記の`thread/start` → response由来IDによる`turn/start` → `turn/interrupt`を送信 | SessionStart 2件が開始・完了し、inject hookのcontextが期待した1行と完全一致し、invalid SessionStart JSONを報告しない | 両hookに各1回の`hook/started` / `hook/completed`を記録し、両方`completed`。context entryは期待値とexact matchした。 | Codex CLI `0.150.1` / Python `3.14.6` | hook完了後にmodel接続がDNS失敗したためinterruptした。model応答と実compact continuationは確認していない。 |

`hooks/list`で送ったJSONLは次の3行である。

```jsonl
{"id":1,"method":"initialize","params":{"clientInfo":{"name":"hook-probe","version":"1.0.0"},"capabilities":{"experimentalApi":true}}}
{"method":"initialized","params":{}}
{"id":2,"method":"hooks/list","params":{"cwds":["<repo>"]}}
```

trust fixtureは、`ln -s <repo>/codex/hooks.json <scratch>/isolated-codex-home/hooks.json`と`ln -s <repo>/hooks <scratch>/isolated-codex-home/hooks`を実行し、次の`config.toml`だけを使い捨てHOMEへ作成した。

```toml
[hooks.state."<scratch>/isolated-codex-home/hooks.json:session_start:0:0"]
trusted_hash = "sha256:e8115dac39817f461271372a24ea6d552f2b3999bd696847455cd5a65fcce634"

[hooks.state."<scratch>/isolated-codex-home/hooks.json:session_start:0:1"]
trusted_hash = "sha256:48a53495fa7bdae07490fdd5d231ed981fb13fdc54af5d50dc13b99383b9926c"
```

fresh startupで送ったJSONLは次の3行である。`<thread-id>`と`<turn-id>`は直前のresponseから得た値で置換した。

```jsonl
{"id":3,"method":"thread/start","params":{"cwd":"<repo>","ephemeral":true,"approvalPolicy":"never","sandbox":"read-only","sessionStartSource":"startup"}}
{"id":4,"method":"turn/start","params":{"threadId":"<thread-id>","input":[{"type":"text","text":"Reply with OK."}]}}
{"id":5,"method":"turn/interrupt","params":{"threadId":"<thread-id>","turnId":"<turn-id>"}}
```

期待したinject hookのcontext entryは次の1行である。

```text
Before responding, read and follow superpowers:using-superpowers from the enabled Codex plugin.
```

- active `~/.codex/config.toml`の`[hooks.state]`には、`~/.codex/hooks.json:session_start:0:0`に対応する保存済みhashとして`sha256:3f8911580f61c6f4450d1d74183566c6ec25f3502f5ed5db55238821b4bca7c5`があった。同じsource pathの`:0:1` stateは記録されていなかった。
- repoの現行`codex/hooks.json`をsymlinkした隔離`CODEX_HOME`に対する`hooks/list`は、SessionStart 0:0を`sha256:e8115dac39817f461271372a24ea6d552f2b3999bd696847455cd5a65fcce634`、0:1を`sha256:48a53495fa7bdae07490fdd5d231ed981fb13fdc54af5d50dc13b99383b9926c`として列挙した。stateを持たない最初の一覧では両方`untrusted`だった。
- 隔離`CODEX_HOME`だけに上記2つのcurrent hashをtrust fixtureとして設定すると、同じ`hooks/list`は両方を`trusted`と返した。続くephemeral `thread/start`（`sessionStartSource: "startup"`）の最初のturnでは、`detect-parallel-sessions.sh`と`inject-superpowers.sh`の`hook/started` / `hook/completed`が各1回記録され、両方`completed`になった。後者のcontext entryは次の1行だった。

  ```text
  Before responding, read and follow superpowers:using-superpowers from the enabled Codex plugin.
  ```

- model接続はhook完了後にDNSで失敗したためturnをinterruptした。SessionStartの完走とcontext生成はmodel応答の成功に依存せず観測でき、invalid SessionStart JSONは報告されなかった。
- active `CODEX_HOME`をそのまま使う最初のapp-server起動は、既存`state_5.sqlite`の初期化に失敗した。`codex doctor --summary`もstate database integrity failureを報告したため、state DBの退避・修復・再生成は行わず、公式設定`sqlite_home`だけを使い捨てディレクトリへoverrideして再実行した。
- このactive `hooks/list`はwarning / error 0で4件を返した。PreToolUse 0:0と0:1は`enabled: true` / `trusted`、SessionStart 0:0（`detect-parallel-sessions.sh`）は`enabled: true` / `modified`、0:1（`inject-superpowers.sh`）は`enabled: true` / `untrusted`だった。sourceはすべて`user`、source pathはactive `~/.codex/hooks.json`だった。

このcheckpointにより、active source/hash/enabled/trust statusと、trust fixture上のfresh disposable startupを確認できた。active SessionStart 2件は`modified` / `untrusted`であり、公式のhash連動契約上、`/hooks`で再review / trustするまで通常起動ではskipされる。現在sessionへ同じdeveloper contextが届いた事実は、active hookのpersist済みtrustやtrust bypassを証明しないという前checkpointの境界を維持する。実HOMEのconfig、hook trust、credential、plugin enabled stateは変更せず、trust fixtureとSQLite runtime stateは使い捨て領域だけに作成した。

Step 3はactive trust statusとfresh startupまで部分確認が進んだが、`/hooks` UIでのactive hook再承認と、実際のcompact完了後のcontinuationは未確認のため完了扱いにしない。

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
| statuslineの移行方針 | 独自adapterを作らずCodex公式の設定機構を使う。 | OpenAI公式の[Developer commands](https://developers.openai.com/codex/cli/slash-commands)は、`/statusline`で項目を選択・並べ替えし、`tui.status_line`へ保存すると定義する。active configには`model-with-reasoning`、`current-dir`、`project-name`、`git-branch`、`pull-request-number`、`approval-mode`、`context-used`の明示設定がある。ユーザー判断により公式defaultの追加実測は移行の合否対象から外し、custom item listの変更やadapter追加は行わない。 | 方針確定。default実測は対象外。 |

### checkpointの境界

- security boundary: 該当なし。今回の変更はdocs-onlyであり、認証・認可・入力・API・secrets・権限・deployment設定を変更しない。
- 実HOME、plugin enabled state、hook trust state、credentialは変更していない。

## 限界と次の確認

- Task 6全体の状態: in progress。
- static gate、隔離HOMEのsetup probe、security reviewのコスト境界（Step 5）、Step 6のplugin policy、Step 3のcurrent-session注入の部分証跡は確認した。runtime全体の成功は主張できない。
- Step 3は公式`hooks/list`でactive source/hash/enabled/trust statusを確認し、隔離trust fixtureでfresh startupも確認した。active SessionStartは`modified` / `untrusted`であり、`/hooks` UIでの再承認と実際の`/compact` continuationが未確認である。
- 残項目は、Step 3のactive UI trust / compact、Claude側Step 6、superpowers inventoryの根本原因である。`code-explorer`と`planner`のruntime sandboxがread-onlyであることも未確認であり、親read-only sessionの追加試験が必要である。Step 7の公式default実測はユーザー判断で合否対象から外した。
- 本タスクでは実HOME、既存の `codex/plugin-policy.json`、`tasks/backlog.md`、`learning/entries/2026-08-27-*` を変更していない。
