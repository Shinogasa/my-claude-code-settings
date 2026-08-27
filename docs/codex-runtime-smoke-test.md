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

## Step 6: pluginとlearning

期待結果: plugin audit、`codex plugin list --json`、両ホストでのコード参加・skip・構成作業を確認する。
観測結果: 未実行。今回の実行単位はStep 2までとしたため。
状態: 未確認。

## Step 7: 公式default statusline

期待結果: 明示的な`tui.status_line`なしの隔離Codexで可視フィールドを記録する。
観測結果: 未実行。今回の実行単位はStep 2までとしたため。
状態: 未確認。

## 限界と次の確認

- static gateと隔離HOMEのsetup probe、security reviewのコスト境界（Step 5）は成功した。runtime全体の成功は主張できず、Step 3・6〜7を次の実行単位で確認する必要がある。
- 「runtime hookが未承認」「plugin状態が不適合」「statuslineが未確認」は、実行していないため存在を結論づけない。探索範囲はStep 1、Step 4、Step 5のsynthetic probeであり、他のruntime状態を覆う根拠はない。これらが誤りなら隔離HOMEの実機実行で観測される。
- `code-explorer`と`planner`のruntime sandboxがread-onlyであることは未確認である。親read-only sessionの追加試験が必要である。
- 本タスクでは実HOME、既存の `codex/plugin-policy.json`、`tasks/backlog.md`、`learning/entries/2026-08-27-*` を変更していない。
