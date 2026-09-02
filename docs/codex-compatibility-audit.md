# Claude Code 資産の Codex 互換性監査

調査日: 2026-08-18（RTKは2026-09-02追補）
対象: `my-claude-code-settings` at `e5a5289`（RTK追補はADR 0007参照）
実機: Codex CLI 0.147.0（RTK追補はCodex CLI 0.151.0 / RTK 0.45.0）
参照スナップショット: `codex-cli-best-practice` at `b79f473`

## 結論

このリポジトリは Codex でも有用だが、**全資産を同じ場所へリンクするだけでは移行は完了しない**。
維持すべき境界は次のとおり。

- ポリシー、手順、ドメイン知識は共有する
- 発火方法、設定形式、権限、プラグイン有効化はホスト別アダプターで管理する
- Claude Code から自動移行されたプラグインは、Codex で改めて allowlist 判定する
- 非互換な資産はキャッシュを消すのではなく、Codex 側で無効化する

最優先の対応は次の2件。

1. `security-guidance@claude-plugins-official` を Codex 側だけ無効化する。Claude Code 固有の
   `async` handshake、`asyncRewake`、rewake 出力契約に依存しており、Codex の
   SessionStart で invalid JSON エラーを起こす。
2. リポジトリ直下の `AGENTS.md` を Codex 固有の差分だけに縮める。現在は `CLAUDE.md` の
   誤った機械置換版で、グローバルの `CLAUDE.md → ~/.codex/AGENTS.md` と二重適用され、
   存在しない `~/.Codex` や `/Codex-best-practice` を指している。

調査ブランチでは上記の実環境変更は行わず、監査結果と実装計画だけを記録する。

その後の個別判断では、**Codexはnative-firstとし、`claude-plugins-official`由来pluginは
明示的にallowしたもの以外を実行しない**方針を採った。未知のpluginもmarketplace単位で
default denyにする。`learning-output-style`はpluginとして維持せず、意味のある5〜10行を
人間が実装する部分だけを自前学習モードへ統合する。詳細と却下案は
`docs/adr/0003-codex-native-first-activation-policy.md`に記録した。

## 判定基準

| 判定 | 意味 |
|---|---|
| 共有可 | 同一ソースを両ホストへ配ってよい。実機または現行仕様で契約を確認済み |
| アダプター必要 | 内容は再利用できるが、配置・設定・出力契約・ツール名の変換が必要 |
| Codex で無効 | 現在の Codex では実行させない。Claude Code 側の有効性とは独立に扱う |
| 未検証 | 構文や配置は成立するが、実機で機能が完結するところまで確認できていない |

根拠の優先順位は、Codex 公式資料、ローカル 0.147.0 の `--help` と実測、
`codex-cli-best-practice` の順とする。参照リポジトリは有用な索引だが、後述のとおり
0.147.0 より古い記述を含むため、一次資料の代わりにはしない。

## 配線の全体像

| 正本・流入元 | Claude Code | Codex | 注意点 |
|---|---|---|---|
| `CLAUDE.md` | `~/.claude/CLAUDE.md` | `~/.codex/AGENTS.md` | 同一ソース。ホスト差は本文中で明示する |
| `codex/RTK.md` | 使用しない | `~/.codex/RTK.md` | RTK公式のCodex向け指示をsymlink配布する |
| 直下 `AGENTS.md` | 読まない | このリポジトリの project guidance | グローバル指示への Codex 固有差分だけにする |
| `skills/` | `~/.claude/skills` | `~/.agents/skills` | 基本形式は共有可。本文のホスト固有語は別途監査する |
| `commands/` | `~/.claude/commands` | `~/.codex/prompts` | Codex custom prompts は deprecated。skills へ移す |
| `rules/*.md` | 条件付き指示としてロード | `AGENTS.md` から必要時に読む | Codex の Starlark `.rules` とは別物 |
| `agents/*.md` | 直接ロード | 直接は使用しない | `codex/agents/*.toml` の正本 |
| `codex/agents/*.toml` | 使用しない | `~/.codex/agents` | 生成物。権限写像は情報を失う |
| `hooks/` | `settings.json` から起動 | `codex/hooks.json` から起動 | スクリプト共有、イベント定義はホスト別 |
| Claude `enabledPlugins` | Claude plugin install | `/import` で Codex に流入しうる | Codex 側の enabled 状態は独立して残る |
| `CODEX_PLUGINS` | 使用しない | Codex marketplace から導入 | 現在は `superpowers@openai-api-curated` のみ |
| MCP | マシンローカルまたはプラグイン | マシンローカルまたはプラグイン | リポジトリ内に共通の MCP 正本はない |

`setup.sh` 以外に、Codex の `/import` が第二の流入経路になる。Claude 側でプラグインを
`false` にしても、既に Codex の `config.toml` と cache へ移行された状態は自動では消えない。
Codexのinstall状態とenabled状態は別であり、`/plugins`でSpaceを押すとcacheを残したまま
個別pluginを無効化できる。`codex plugin remove`はconfigとcacheを削除するため、この移行では使わない。

## 互換性マトリクス

### 指示ファイルと rules

| 資産 | 判定 | 調査結果と移行方針 |
|---|---|---|
| `CLAUDE.md` | アダプター必要 | グローバル指示の共有正本として成立。Claude/Codex の発火差を表で併記する現方式を維持する |
| `AGENTS.md` | Codex で修正必須 | project guidance として実際に読まれるが、`~/.Codex`、`/Codex-best-practice`、hooks 未配線など事実と異なる記述がある。共有本文の複製をやめ、Codex 固有差分だけにする |
| `rules/ecc-coding-style.md` | 共有可 | 指示内容はホスト非依存。`alwaysApply` は Claude のメタデータであり Codex では意味を持たない |
| `rules/ecc-development-workflow.md` | 共有可 | 同上 |
| `rules/ecc-testing.md` | 共有可 | 同上 |
| `rules/output-formatting.md` | 共有可 | 出力規約としてホスト非依存 |
| `rules/persona.md` | 共有可 | 応答規約としてホスト非依存 |
| `rules/proving-absence.md` | 共有可 | 応答規約としてホスト非依存 |
| `rules/task-management.md` | アダプター必要 | 内容は共有可。frontmatter は Claude 用で、Codex は `CLAUDE.md` からの参照で読む |
| `rules/learning-mode.md` | アダプター必要 | 本文は両ホストを併記済み。先頭が空白付き `  ---` のため Claude 側 frontmatter 認識を別途検証する |
| `rules/parallel-worktree.md` | アダプター必要 | `EnterWorktree`、`~/.claude/projects` などをホスト別に分岐済みだが、Codex のサブエージェント API と現行記述を再同期する |

`~/.codex/rules/*.rules` はコマンドの sandbox 外実行を制御する Starlark であり、上の
Markdown rules とは名前が同じだけで役割が異なる。Markdown を `~/.codex/rules/` に置いても
execpolicy としてはロードされない。現在のリンクは `~/.codex/AGENTS.md` から相対参照するために
必要だが、README では「Codex Rules」と誤解されないよう明記する。

### skills

| 資産 | 判定 | 調査結果と移行方針 |
|---|---|---|
| `api-design` | 共有可 | ホスト非依存の知識 |
| `backend-patterns` | 共有可 | ホスト非依存の知識 |
| `coding-standards` | 共有可 | ホスト非依存の知識 |
| `database-migrations` | 共有可 | ホスト非依存の知識 |
| `deployment-patterns` | 共有可 | ホスト非依存の知識 |
| `grill-me` | 共有可 | 対話方式だけを規定し、特定ツールに依存しない |
| `hexagonal-architecture` | 共有可 | ホスト非依存の知識 |
| `security-review` | 共有可 | `security-guidance` を Codex で止める間の明示的レビュー手段にもなる |
| `tdd-workflow` | 共有可 | Git checkpoint の副作用はあるが、ホスト固有 API には依存しない |
| `architecture-decision-records` | アダプター必要 | description の「Claude Code sessions」をホスト中立化する |
| `verification-loop` | アダプター必要 | 「Claude Code sessions」と `/verify` の記述をホスト別にする |
| `claude-code-best-practice` | Claude 専用 | `~/.claude/claude-code-best-practice` を読む。Codex 設定作業では発火させない |
| `source-command-aside` | 共有可 | Codex skill への変換済み |
| `source-command-explain` | 共有可 | Codex skill への変換済み |
| `source-command-feature-dev` | 共有可 | Codex skill への変換済み |
| `source-command-pr-create` | 共有可 | Codex skill への変換済み |
| `source-command-test-coverage` | 共有可 | Codex skill への変換済み |
| `source-command-build-fix` | アダプター必要 | `Read` / `Edit` という Claude のツール名を能力ベースの表現へ変える |
| `source-command-plan` | アダプター必要 | planner agent と確認待ちの方法を Codex の対話契約に合わせる |
| `source-command-refactor-clean` | アダプター必要 | `Grep` / `Edit` という Claude のツール名を能力ベースの表現へ変える |

`codex-cli-best-practice` を参照する skill はまだない。実装時は Codex 設定作業だけで発火する
`codex-cli-best-practice` skill を追加し、公式資料と実機を優先する旨を明記する。

### commands / custom prompts

Codex 公式資料は custom prompts を deprecated とし、再利用可能な手順には skills を推奨している。
`commands/ → ~/.codex/prompts/` は 0.147.0 でも動くが、移行先としては増やさない。

| command | Codex skill | 判定 |
|---|---|---|
| `aside` | `source-command-aside` | 変換済み |
| `build-fix` | `source-command-build-fix` | 変換済み、用語修正要 |
| `explain` | `source-command-explain` | 変換済み |
| `feature-dev` | `source-command-feature-dev` | 変換済み |
| `plan` | `source-command-plan` | 変換済み、対話契約修正要 |
| `pr-create` | `source-command-pr-create` | 変換済み |
| `refactor-clean` | `source-command-refactor-clean` | 変換済み、用語修正要 |
| `test-coverage` | `source-command-test-coverage` | 変換済み |
| `code-review` | なし | Codex の組み込み `/review` を使う。外部テンプレート由来の `.claude/PRPs` 成果物と投稿処理は移植しない |
| `quality-gate` | なし | `verification-loop` へ統合する |
| `tdd` | なし | `tdd-workflow` へ統合する |
| `verify` | なし | `verification-loop` または Codex 公式 verification skill へ統合する |

全12 command の skill 移行後、Codex 向け `commands:$CODEX_DIR/prompts` リンクを外す。
Claude Code の `commands/` はそのまま維持できる。

### subagents

| 資産 | 判定 | 調査結果と移行方針 |
|---|---|---|
| `agents/*.md` 8件 | Claude 専用正本 | Claude の `tools`、model alias、color を含む |
| `bin/generate-codex-agents.py` | アダプター | Markdown から Codex TOML を生成する境界。現在の方針を維持する |
| `codex/agents/*.toml` 8件 | 未検証 | 必須フィールド、生成ドリフト、read-only 写像はテスト済み。実際の spawn で model と sandbox が適用されるところは未確認 |

変換時に失われる情報は次のとおり。

| Claude Code | Codex | 影響 |
|---|---|---|
| tool allowlist | `sandbox_mode` | ツール単位制限を表現できず、read-only / workspace-write に粗くなる |
| `sonnet` / `opus` | 世代名 | Codex モデル更新時に `MODEL_MAP` の保守が必要 |
| `color` | 対応なし | UI メタデータを捨てる |

### リポジトリ管理 hooks

| hook | 判定 | 根拠・残課題 |
|---|---|---|
| `guard-dangerous-bash.sh/.py` | 共有可 | PreToolUse の `tool_name`、`tool_input.command`、`cwd` と、exit 2 + stderr のブロック契約を両ホストで利用。Codex payload 回帰テストあり |
| `warn-branch-behind-main.sh` | 共有可 | Codex が受け付ける `systemMessage` と `hookSpecificOutput.additionalContext/permissionDecision` を使う。trust 承認は別途必要 |
| `detect-parallel-sessions.sh` | アダプター必要 | SessionStart の成功時は exit 0 + 無出力で正しい。既定ヘルパーが `~/.claude/bin` を向き、Codex 専用マシンでは静かに無効化される |
| `bin/detect-parallel-sessions` | アダプター必要 | Codex 側にも `bin/` を配るか、hook がホスト別パスを解決する必要がある |
| `rtk hook claude` | Codex で無効 | Claude の書き換え出力を Codex PreToolUse が受理せず、エラーだけを出すため `codex/hooks.json` から除外済み |
| `codex/RTK.md` | アダプター必要 | RTK 0.45.0の公式Codex統合。`AGENTS.md`から読み、モデルが`rtk`付きコマンドを選ぶ。hookの強制書き換えではない |

Codex hooks は 0.147.0 で既定有効であり、正規 feature key は `features.hooks`。
`features.codex_hooks` は deprecated alias である。非 managed hook は定義ハッシュごとに `/hooks` の
trust が必要で、未承認時はスキップされる。したがって配置成功だけでは防御の有効性を証明しない。

RTKはhook非互換のまま放置するのではなく、0.45.0で公式に案内されている
`AGENTS.md` + `RTK.md`方式へ切り替えた。圧縮自体はClaude Codeと同じRTKバイナリが行うが、
Codexで`rtk`が選ばれるかは指示遵守に依存する。詳細は
[ADR 0007](adr/0007-codex-rtk-prompt-integration.md)を参照。

### Claude 由来プラグイン

ローカル Codex で確認できた Claude marketplace 由来プラグインを、Codex での扱いに絞って分類する。
OpenAI bundled/runtime の標準プラグインは移行対象外とした。

| プラグイン | Codex での判定 | 根拠・方針 |
|---|---|---|
| `superpowers@openai-api-curated` | 共有可 | Codex native 配布。skills は動作確認済み。SessionStart hook は同梱しないため AGENTS の明示指示を維持 |
| `learning-output-style@claude-plugins-official` | **Codex で無効** | hook注入は動くが、コード参加の発火はモデル依存で、自前学習モードのヒント禁止・上限・OFF条件と競合する。コード参加部分だけ共有ruleへ統合する |
| `security-guidance@claude-plugins-official` | **Codex で無効** | 下記「security-guidance」で詳述。プラグイン単位で止め、Claude 側は維持する |
| `claude-md-management@claude-plugins-official` | **Codex で無効** | `CLAUDE.md`だけを対象にし、Codexの`AGENTS.md`階層とこのリポジトリの共有正本構造を扱わない |
| `context7@claude-plugins-official` | **保留・無効** | 有用候補だが、Codex向け候補を含めて個別評価するまで導入しない |
| `serena@claude-plugins-official` | **保留・無効** | 有用候補だが、Codex向け候補を含めて個別評価するまで導入しない |
| `asana@claude-plugins-official` | **Codex で無効** | cache 上は Claude command と README のみ。Codex で有効な skill/MCP/hook を確認できない |
| `code-review@claude-plugins-official` | **Codex で無効** | cache 上は Claude command のみ。Codex は組み込み `/review` と公式GitHub連携を持つ |
| `gopls-lsp@claude-plugins-official` | **Codex で無効** | `.codex-plugin`形式だがruntime未検証。Go開発で具体的な不足が出た時点で現行候補を再選定する |
| `atlassian@claude-plugins-official` | **Codex で無効** | Codexは `atlassian-http` を MCP として直接設定済みで、plugin版とは重複する |
| 未登録の`*@claude-plugins-official` | **Codex で無効** | 将来のimportをfail-closedにする。個別判断をADRとpolicyへ追加してからallowする |

`保留・無効`は実行許可ではない。代表ツール、認証、副作用、エラー伝播を個別に確認し、
人間が明示的にallowへ変更するまでCodexでは起動しない。無効化は`/plugins`のenabled切り替えで
行い、install記録とcacheは保持する。plugin cacheを直接patchせず、ClaudeとCodexのenabled状態を
自動同期しない。別marketplaceの未登録pluginはこの移行policyの対象外とし、勝手に変更しない。

#### `security-guidance` が非互換である理由

プラグインの価値と、現在の実装契約の互換性は分けて判断する。セキュリティレビュー自体は有用だが、
2.0.7 の hook 実装は Claude Code の非同期契約に深く依存する。

- SessionStart script は最初に `{"async": true, "asyncTimeout": 180000}` を stdout へ出す。
  Codex はこれを SessionStart の有効な応答として扱わず、invalid JSON output になる
- `hooks.json` は `asyncRewake`、`rewakeMessage`、`rewakeSummary`、`if` を使う。
  Codex の非同期指定は handler の `"async": true` であり、終了後も自動で新しい turn を起こさない
- Stop と PostToolUse の stderr、exit 2、`hookSpecificOutput` の使い分けが Claude Code の
  parser と rewake loop を前提にしている
- LLM review は Anthropic API credentials と `claude_agent_sdk` bootstrap に依存する

よって Codex ではプラグイン全体をいったん無効にする。代替は次の順で採る。

1. `security-review` skill と `security-reviewer` subagent による明示レビュー
2. 決定的な pattern check だけを Codex contract の PostToolUse adapter として切り出す
3. 非同期 LLM review は Codex の `async: true` と safe-point delivery に合わせて別実装する

plugin cache を直接 patch しない。更新で消える上、信頼するコードとローカル改変の境界が見えなくなる。

### settings、statusline、output style、bin

| 資産 | 判定 | 調査結果と移行方針 |
|---|---|---|
| `settings.json.template` | Claude 専用 | Codex は `config.toml`。キー単位で写像し、ファイル全体は共有しない |
| `env.json.template` / `.env.example` | Claude 専用 | Anthropic/LiteLLM 認証用。Codex config へ転記しない |
| `statusline.js` | Claude 専用 | Codex 0.147.0 は `/statusline` と footer config を持つ。当面は公式デフォルトを使い、実務上の不足が出るまでadapterを作らない |
| `output-styles/` | Codex で直接無効 | `★ Design Decision`は学習モードと重複する。`★ Review`は将来のレビュー訓練と合わせて再設計し、直接移植しない |
| `bin/ccp` | Claude 専用 | Claude の認証 profile 切り替え wrapper |
| `setup.sh` | アダプター必要 | `~/.claude` を最初に必須化するため Codex 専用マシンで動かない。ホストごとの処理を独立させる |

### MCP

リポジトリ内には Claude/Codex 共通の MCP 設定正本がない。確認した範囲では、Codex 側の
MCP はローカル `config.toml` または plugin の `.mcp.json` から供給される。

- 探索範囲: Git 追跡ファイル、導入済み Claude 由来プラグインの manifest と `.mcp.json`
- 範囲の根拠: Codex 公式資料が `config.toml` と plugin `.mcp.json` を標準入口としている
- 反証条件: `~/.claude.json`、未追跡ファイル、組織 managed config に別の正本がある場合

このため「共通 MCP が存在しない」とは断定せず、**このリポジトリの追跡資産には正本がない**とする。

## `codex-cli-best-practice` の評価

参照リポジトリは、設定項目の索引、サンプル、Codex 固有の用語を把握する入口として有用である。
一方、HEAD は 2026-06-04 で、ローカル 0.147.0 と差がある。

| 項目 | 参照リポジトリ | 0.147.0 / 公式 |
|---|---|---|
| hooks feature | `codex_hooks = true` が必須 | `features.hooks` が正規、既定有効。旧名は deprecated alias |
| marketplace list | subcommand は無い | `codex plugin list --json` が inventory の根拠 |
| hook handler | 一部文書で `type: shell` | 現在実行されるのは `type: command` のみ |
| hook events | 5イベント中心 | Permission/Compact/Subagent/SessionEnd を含む |
| config profile | `[profiles.*]` | 0.134.0 以降は `<name>.config.toml` |
| skill invocation | 一部で `/skill-name` | `$skill-name` または `/skills` |
| AGENTS fallback | `CODEX.md` を標準 alias とする | fallback は config で明示する |
| memory key | legacy alias を使用 | `disable_on_external_context` が正規 |

したがって submodule は採用するが、skill 内に「公式資料とローカル CLI を優先する」と書き、
記述をそのまま設定へ転記しない。

## 実装順序

### Wave 0: エラーと暗黙有効化を止める

- `claude-plugins-official`をdefault denyにし、明示allow以外をCodex側で無効化する
- Codex の Claude 由来プラグインを allowlist 方式にする
- 直下 `AGENTS.md` の誤記とグローバル指示の重複を解消する

### Wave 1: 正本とアダプターを分離する

- `setup.sh` を Claude-only / Codex-only のどちらでも完走できる構造にする
- Codex 側へ `bin/` と `codex-cli-best-practice` の必要部分を配る
- hooks の trust と enabled 状態を setup 後の検証項目として表示する
- `learning-output-style`のコード参加だけを、既存の上限・OFF条件を保った学習モードへ統合する

### Wave 2: deprecated 経路を閉じる

- 残り4 command の扱いを既存 skills / native `/review` へ統合する
- `commands → ~/.codex/prompts` のリンクを外す
- shared skills の Claude 固有ツール名を能力ベースの表現へ直す

### Wave 3: 実機 smoke test を完了する

- 8 agent の代表3種（read-only、workspace-write、high reasoning）を spawn する
- plugin policyでdefault-deny marketplaceの明示allow以外が無効であることを確認する
- Claude/Codex両方でコード参加の発火・スキップ・設定タスク非発火を実会話で確認する
- Codexのデフォルトstatuslineが設定追加なしで表示されることを確認する
- クリーンな Codex 専用環境で setup と SessionStart を検証する

## 不在の主張と監査の限界

### 調査した範囲

- Git 追跡資産: instructions、settings、skills、commands、rules、agents、hooks、plugins、MCP、
  output styles、statusline、bin、tests、docs
- `setup.sh` が作る symlink と生成経路
- ローカル Codex 0.147.0 の feature / plugin metadata
- 導入済み Claude 由来プラグインの manifest、hooks、skills、`.mcp.json`
- Codex 公式統合マニュアルと、固定した2つの best-practice submodule

### この範囲が妥当な根拠

Codex 公式資料が列挙する主な customization 入口
（AGENTS、skills、custom prompts、rules、agents、hooks、plugins、MCP、config）と、
このリポジトリの setup 入口を突き合わせた。単なるファイル名走査だけではなく、実行時の
plugin list と plugin-bundled hooks まで確認した。

### 反証条件

次の場所に別の設定がある場合、この監査の「見つからない」は覆る。

- 組織の managed config / requirements
- Git 管理外の `~/.claude.json`、`~/.codex/config.toml` の値部分
- 未追跡の project `.codex/`、個人 marketplace、remote plugin update
- ChatGPT desktop app 側だけに存在する設定や connector

認証値と secrets は監査対象外とし、ローカル config はキー名と enabled 状態だけを確認した。

## 参照した一次資料

- https://learn.chatgpt.com/docs/hooks
- https://learn.chatgpt.com/docs/custom-prompts
- https://learn.chatgpt.com/docs/agent-configuration/rules
- https://learn.chatgpt.com/docs/agent-configuration/agents-md
- https://learn.chatgpt.com/docs/agent-configuration/subagents
- https://learn.chatgpt.com/docs/import
- https://learn.chatgpt.com/docs/developer-commands?surface=cli
- https://developers.openai.com/codex/app/review
- https://developers.openai.com/codex/integrations/github
- https://developers.openai.com/codex/github-action
- https://developers.openai.com/codex/plugins/build
- https://developers.openai.com/codex/cli/reference
- https://developers.openai.com/plugins/concepts/skills
- https://developers.openai.com/plugins/build/plugins
