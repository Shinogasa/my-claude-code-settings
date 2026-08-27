# Codex runtime smoke test 証跡

記録日: 2026-08-27
対象BASE: `77974734bed817fc79e7940ef74461db4f185e05`
検証時HEAD: `77974734bed817fc79e7940ef74461db4f185e05`

## 実行環境

- Codex CLI: `codex-cli 0.149.1`
- 作業ツリー: BASEと同一HEAD。既存の未コミット変更は保全し、本タスクで変更・stage・revertしていない。
- 実HOME: setup/runtime probeは実行していない。したがって実HOMEへの変更はない。

## Step 1: 静的スイート

| コマンド | 期待結果 | 観測結果 | 状態 |
| --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -v` | failure 0、全件完走 | exit 1。正本環境では236件中 failure 1 / error 11。Gitの署名設定がテスト用一時リポジトリの空コミットを失敗させた。 | 失敗 |
| 同コマンド（`GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1` の補助診断） | failure 0 | exit 1。280件中 failure 2。 | 失敗 |
| `bash -n setup.sh hooks/*.sh bin/ccp bin/detect-parallel-sessions` | exit 0 | exit 0 | 成功 |
| `python3 -m json.tool`（`settings.json.template`、`codex/hooks.json`、`codex/plugin-policy.json`、`manifests/skills.json`） | 各exit 0 | 各exit 0 | 成功 |

補助診断の失敗は次の2件である。

1. `test_policy_schema_and_exact_classifications`: 既存の未コミット変更 `codex/plugin-policy.json` に `atlassian@claude-plugins-official` の deny エントリが追加され、テストの固定期待値と異なる。本タスクの変更所有権外のため変更しない。
2. `test_own_process_tree_is_excluded`: `bin/detect-parallel-sessions` がテストプロセスの祖先PIDを検出結果から除外できず、空配列期待に対して一時リポジトリの1件を返した。

正本環境の11 errorは、グローバルGit署名設定がテストfixtureの空コミットに適用され、利用可能な署名agentがないことで発生した。補助診断ではこの環境要因を除去して280件まで完走したが、上記2 failureは残った。

## Step 2: 隔離HOMEでのsetup

期待結果: `--claude`、`--codex`、`--all` の再実行が冪等であり、未所有パスと `--replace-conflicts` の所有権・backup復旧を確認する。
観測結果: 未実行。Step 1失敗時に停止する実行順序に従った。
状態: 未確認。

## Step 3: hook信頼とSessionStart

期待結果: 隔離Codexで `/hooks` を確認・承認し、新規起動とcompact継続でsuperpowers注入および有効なSessionStart出力を確認する。
観測結果: 未実行。Step 1失敗のため。
状態: 未確認。

## Step 4: 代表subagent（controller実測）

| agent | repository生成設定 | runtime観測 | 操作結果 | 状態 |
| --- | --- | --- | --- | --- |
| `code-explorer` | model `gpt-5.6-luna`、sandbox `read-only` | modelはGPT-5（正確なvariant未確認）、sandbox `workspace-write` | hook 2ファイルをread。SDD一時ファイルの作成・削除に成功。 | 部分確認。runtime read-only期待は未達。 |
| `code-simplifier` | model `gpt-5.6-luna`、sandbox `workspace-write` | model未確認、sandbox `workspace-write` | SDD一時Pythonを`if/else`から`return bool(value)`へ編集。構文・挙動検査PASS。 | sandboxのみ確認。 |
| `planner` | model `gpt-5.6-sol`、reasoning `high`、sandbox `read-only` | model/effort非公開で未確認、sandbox `workspace-write` | 一時ファイルの作成・削除に成功。 | 部分確認。runtime read-only期待は未達。 |

OpenAI公式の[Subagents documentation](https://developers.openai.com/codex/concepts/subagents)は、subagentが親のsandbox policyを継承し、親turnのlive runtime overrideがcustom agent fileのdefaultより再適用されると説明する。したがって、read-only TOMLとworkspace-write実測の差は現行仕様と整合する。

ただし、この親turnではTask 6の「`code-explorer`をread-onlyでruntime確認」は達成していない。反証条件は、親をread-onlyにした別sessionで`code-explorer`を実行したときにworkspace-writeを観測すること。未実行のため、configured read-onlyがruntimeで有効になることは未確認である。

## Step 5: security cost boundary

期待結果: 通常の文書差分はLLM security reviewを起動せず、認証/入力検証差分はLunaの`security-reviewer`を起動し、判断不能時に親が人間へ上位モデルの確認を求める。
観測結果: 未実行。Step 1失敗のため。
状態: 未確認。

## Step 6: pluginとlearning

期待結果: plugin audit、`codex plugin list --json`、両ホストでのコード参加・skip・構成作業を確認する。
観測結果: 未実行。Step 1失敗のため。
状態: 未確認。

## Step 7: 公式default statusline

期待結果: 明示的な`tui.status_line`なしの隔離Codexで可視フィールドを記録する。
観測結果: 未実行。Step 1失敗のため。
状態: 未確認。

## 限界と次の確認

- runtime成功の主張はできない。停止条件となった静的失敗を、変更所有権外の別タスクで解消してから本証跡を更新する。
- 「runtime hookが未承認」「plugin状態が不適合」「statuslineが未確認」は、実行していないため存在を結論づけない。探索範囲はStep 1の静的検査とcontrollerが実施したStep 4だけであり、他のruntime状態を覆う根拠はない。これらが誤りなら隔離HOMEの実機実行で観測される。
- `code-explorer`と`planner`のruntime sandboxがread-onlyであることは未確認である。親read-only sessionの追加試験が必要である。
- 本タスクでは実HOME、既存の `codex/plugin-policy.json`、`tasks/backlog.md`、`learning/entries/2026-08-27-*` を変更していない。
