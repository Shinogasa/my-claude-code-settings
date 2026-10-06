# my-claude-code-settings

コーディングエージェント（Claude Code / Codex CLI）の個人設定をGit管理するリポジトリ。
セットアップスクリプトでシンボリックリンクを作成し、各ホストの設定ディレクトリと同期する。

## セットアップ

```bash
git clone --recursive <this-repo>
cd my-claude-code-settings
# Claude Codeだけを設定する
bash setup.sh --claude
# Codex CLIだけを設定する
bash setup.sh --codex
# 両方を設定する
bash setup.sh --all
```

対象ホストを一度起動して `~/.claude/` または `~/.codex/` を作成してから、対象のセレクタを指定する。
`setup.sh` は `--claude`、`--codex`、`--all` のいずれかを必須とする。

`.env` はLiteLLM等のAPIキー経由でClaude Codeを利用する場合（会社PC等）のみ必要。
個人のAnthropicアカウント（Pro/Maxプランの通常ログイン）を使う場合は `.env` 不要で、
`statusLine`/`enabledPlugins`/`theme`等の共通設定はそのまま反映される。

```bash
# LiteLLM/APIキー経由で使う場合のみ
cp .env.example .env
# .env を編集して ANTHROPIC_AUTH_TOKEN 等を設定
bash setup.sh --claude
```

`setup.sh` は選択したホストだけを対象に、以下を実行する：

1. git submodule の初期化・更新
2. 選択したホストの設定ディレクトリへシンボリックリンクを作成
3. Claudeを選択した場合、`settings.json.template` から `~/.claude/settings.json` を生成し、
   `.env` が存在すれば `env` ブロック（APIキー等）を追加マージ
4. Claudeを選択した場合、`~/.claude/settings.personal.json` を生成する
5. Codexを選択した場合、`~/.codex-personal` があれば、そこにも同じリンクを張る（[認証プロファイルの切り替え](#認証プロファイルの切り替え)用）

| リポジトリ | リンク先 | 内容 |
|---|---|---|
| `CLAUDE.md` | `~/.claude/CLAUDE.md` | グローバル指示（全プロジェクト共通） |
| `skills/` | `~/.claude/skills/` | カスタムスキル |
| `commands/` | `~/.claude/commands/` | カスタムスラッシュコマンド |
| `rules/` | `~/.claude/rules/` | 条件付きルール |
| `agents/` | `~/.claude/agents/` | サブエージェント定義 |
| `bin/` | `~/.claude/bin/` | 起動ラッパー。`ccp` と `cxp` は個人アカウントで起動し、`claude-headless` は親と同じプロファイルで `claude -p` を起動する |
| `hooks/` | `~/.claude/hooks/` | 危険コマンドブロック等のhooksスクリプト（Claude向けrtkフックはsettings.json.template側で管理） |
| `statusline.js` | `~/.claude/statusline.js` | ステータスライン表示スクリプト |
| `output-styles/` | `~/.claude/output-styles/` | カスタムアウトプットスタイル |
| `claude-code-best-practice/` | `~/.claude/claude-code-best-practice/` | ベストプラクティス参照（submodule） |

- 所有権を確認できる管理対象は何度実行しても安全（冪等）
- 未管理の既存ファイルとの衝突は、通常は変更せず停止する
- `--replace-conflicts` を指定した場合だけ、選択ホストごとのbackupへ退避して置換する

旧形式からの移行: 選択したホストの `~/.claude/skills` または `~/.agents/skills` が、このrepoの `skills/` と同じ解決先を持つsymlinkで、その親ディレクトリもsymlink解決後にrepoの外にある場合、フラグ無しで実ディレクトリへ移行する。git追跡中の項目はrepoに残し、`synced` などの追跡外項目を新しい実ディレクトリへ移す。別の場所へのリンクや壊れたリンクは変更せず拒否する。`skills.migrating.*` が残っていたら、そのパスを表示して停止する。親symlinkが残る場合は一時ディレクトリ内の項目を元のrepoの `skills/` へ戻して空の一時ディレクトリを除き、親パスが消えている場合は表示された `mv <一時ディレクトリ> <親パス>` で復旧してから、setupを再実行する。

### Codex CLI 向けリンク

`--codex` または `--all` を選んだ場合、`~/.codex/` が存在することを事前に検査してから、
同じソースを Codex 向けにもリンクする（内容は二重管理しない）。未導入マシンでは設定を変更せず、
Codexを一度起動してから再実行するようエラーを表示する。`--claude` だけならCodex側へは触れない。

| リポジトリ | リンク先 | 備考 |
|---|---|---|
| `skills/` | `~/.agents/skills/` | Agent Skills オープン標準。Codex はスキャン時にシンボリックリンクを追従する |
| `rules/` | `~/.codex/rules/` | `AGENTS.md` から Markdown を相対参照するための配置。Codex の Starlark `.rules` とは別物 |
| `CLAUDE.md` | `~/.codex/AGENTS.md` | Codex のグローバル指示 |
| `codex/RTK.md` | `~/.codex/RTK.md` | RTK公式のCodex向けシェル指示 |
| `hooks/` | `~/.codex/hooks/` | Claude Code と共有するhookスクリプト本体 |
| `codex/hooks.json` | `~/.codex/hooks.json` | Codex向けのイベント配線。`/hooks` で定義ごとの承認が必要 |
| `codex/agents/` | `~/.codex/agents/` | `agents/*.md` から生成したCodex TOML |

`~/.agents/` は Codex が自動生成しないため、Codex 検出時に `setup.sh` が作成する。

Codex custom prompts は deprecated のため、`commands/` は `~/.codex/prompts/` へ配布しない。
Claude Codeでは既存commandを維持し、Codexでは次のnative機能または共有skillを使う。

| Claude command | Codexの入口 |
|---|---|
| `code-review` | Codex組み込み `/review` |
| `quality-gate` | `verification-loop` |
| `verify` | `verification-loop` |
| `tdd` | `superpowers:test-driven-development` |

その他のcommandは `skills/source-command-*` として共有し、Codexのskill discoveryから利用する。

### Codex CLI の RTK

RTK 0.45.0 の公式Codex統合は、Claude Codeの`PreToolUse` hookとは異なり、
`AGENTS.md`から`RTK.md`を読ませてCodex自身に`rtk`付きのコマンドを選ばせる方式である。
このリポジトリでは`~/.codex/AGENTS.md`をsymlink管理しているため、
`rtk init --global --codex`でホームを直接書き換えず、同等の指示を`codex/RTK.md`として管理し、
`setup.sh --codex`で`~/.codex/RTK.md`へリンクする。反映には新しいCodexセッションが必要。

`rtk`経由でコマンドが実行された場合の圧縮処理はClaude Codeと共通で、同じトークン節約を得られる。
ただしCodex側はモデルが指示に従うことが前提で、hookによる強制書き換えではない。
また公式の「最大90%」は対応シェルコマンドの**出力バイト数**の削減率であり、セッション全体の
トークン消費や料金の削減率ではない。実績は`rtk gain`、フィルターなしの出力は
`rtk proxy <command>`で確認する。失敗時の全出力は既定でローカルへ保存されるため、
機密を含むコマンドではRTKのtee設定と保存先も確認する。

コンテナ側は`cw-workspace-local`がRTKバイナリの導入を担当する。このリポジトリは
`~/.codex`へ指示ファイルを配布し、コンテナがそのディレクトリをmountすることで設定を共有する。
責務と却下案は[ADR 0008](docs/adr/0008-codex-rtk-prompt-integration.md)に記録した。

### Codex CLI の Git SSH 署名（Bitwarden Desktop）

Codexのshell sandboxや子プロセスは、親シェルの`SSH_AUTH_SOCK`をそのまま継承しないことがある。
Codex公式の[`shell_environment_policy.set`](https://developers.openai.com/codex/config-reference/)
へ明示値を設定すると、shell tool・fresh session・subagentから同じSSH agentを利用できる。

`setup.sh --codex` はmacOSのBitwarden Desktop socketを`$HOME`から導出し、次の順で処理する。

- Bitwarden Desktopをunlockし、SSH agentと署名鍵を利用可能にしてからsetupを実行する
- `SSH_AUTH_SOCK=<socket> ssh-add -l`が成功したときだけ、`~/.codex/config.toml`の
  `[shell_environment_policy.set]`にある`SSH_AUTH_SOCK`だけを追加・更新する
- configのコメント、無関係な設定、認証情報は再シリアライズせず保持する。config本体はGit管理しない
- configは現在ユーザー所有かつ`0600`相当だけを受理し、ACL・拡張属性を保持する。
  signing設定とsubagent既定値設定は同じlockと安全更新処理を使う
- configが無い、macOS以外、socketが無い、Bitwardenがlock中、鍵が0件、agentへ接続できない場合は
  警告して設定を変更しない（setup全体は継続する）
- 既存の別socketは、Bitwarden agentの鍵を確認できた場合だけ管理対象keyとして置き換える。確認できない場合は既存値を保持する

反映後は新しいCodexセッションが必要なため、setupが成功または設定済みと報告したら、実行中のCodexを終了して再起動する。
診断はローカル端末で行い、fingerprintをログやチャットへ貼り付けない。

```bash
SSH_AUTH_SOCK="$HOME/Library/Containers/com.bitwarden.desktop/Data/.bitwarden-ssh-agent.sock" ssh-add -l
git log --show-signature --format='%G?' -n 5
```

未署名の既存commitをsetupが自動rewriteすることはない。署名を直す場合は対象branchと履歴の扱いを明示的に決める。
ホストのBitwarden socketをコンテナへ直接持ち込む設定はこのリポジトリの責務ではない。
開発コンテナ側のrelayとRTKバイナリは`cw-workspace-local`で管理し、そこで追加対応が必要ならそのリポジトリへ引き継ぐ。

### Claude Code 向けプラグイン

`settings.json` の `enabledPlugins` は「有効にしろ」という**宣言**でしかなく、実体の取得はしない。
実体（`~/.claude/plugins/cache/`）と `installed_plugins.json` はマシンローカルかつ絶対パス込みの
ため、このリポジトリでは同期できない。

そのため新しいマシンでは「enabled なのに not cached」となり、**プラグインが黙って機能しない**。
`setup.sh` はこの乖離を埋めるため、`enabledPlugins` に列挙されたプラグインを冪等に導入する。

導入対象は `settings.json.template` から導出している。専用リストを別に持つと
「`enabledPlugins` に足したが導入リストに足し忘れた」が起き、しかも**実体が既にあるマシンでは
何も壊れないため気づけず、別マシンで初めて発症する**。

導入内容は次回の Claude Code 起動時から有効になる。

### Codex CLI 向けプラグイン

`setup.sh --codex` は Codex プラグインの導入・更新・削除・有効化を行わない。
Codex側のプラグイン状態は Codex CLI のユーザー設定（主に `~/.codex/config.toml`）と
ローカルキャッシュで管理されるため、これらはGit管理しない。

このリポジトリが管理するのは、実行を許可するプラグインの方針である。
`codex/plugin-policy.json` は `superpowers@openai-api-curated` を明示的に許可し、
`claude-plugins-official` をdefault denyとする。`review`も実行許可ではなく、個別評価が
終わるまで無効として扱う。

| プラグイン | 備考 |
|---|---|
| `superpowers@openai-api-curated` | Codex側のpolicyで管理 |

`bin/audit-codex-plugins.py` は `codex plugin list --json` の現在状態を読み取り、policy違反を
報告する読み取り専用監査である。`setup.sh --codex` もリンク配置後にこの監査を実行するだけで、
Codex側のプラグイン状態を変更しない。違反があれば対象IDを表示して非ゼロ終了する。

プラグインの操作はCodex側で行う。

- `/plugins` でインストール・有効化・無効化する
- `codex plugin add <plugin>@<marketplace>` でインストールする
- `codex plugin marketplace upgrade` でマーケットプレイスのスナップショットを更新する
- `codex plugin list --json` で現在の状態を確認する
- `codex plugin remove <plugin>@<marketplace>` でキャッシュを含めて削除する

操作後は `python3 bin/audit-codex-plugins.py` または `bash setup.sh --codex` で監査する。
意図的にCodexの許可対象を変える場合だけ `codex/plugin-policy.json` を編集してコミットする。
Codexのプラグイン状態をこのリポジトリへ自動同期する経路は設けていない。

Codex のプラグイン状態は Claude Code 側の `settings.json.template` と独立している。
Claude側で有効化・無効化してもCodexへ自動同期されない。特に
`security-guidance@claude-plugins-official` は Claude 固有の非同期hook契約に依存するため、
Codex側ではpolicyで無効とする。詳細と全プラグインの判定は
[Codex互換性監査](docs/codex-compatibility-audit.md)を参照。

**発火方式がホストで異なる。** Claude Code 版は SessionStart hook が `using-superpowers` を
自動注入する。Codex 版の公式配布物自体は hook を同梱していないが、このリポジトリの
`codex/hooks.json` と `hooks/inject-superpowers.sh` がCodexのSessionStartで
`superpowers:using-superpowers` の読込指示を注入する。プラグインの導入経路と、
リポジトリで管理するhook配線は別の責務として扱う。

**ホスト別アダプターで扱う資産**

| 資産 | 現在の扱い |
|---|---|
| `agents/` | Markdownを正本にし、`bin/generate-codex-agents.py` でモデル＋推論強度を明示した `codex/agents/*.toml` を生成する |
| `hooks/` | スクリプト本体は共有し、イベント定義を `settings.json.template` と `codex/hooks.json` に分ける |
| RTK | Claudeは`PreToolUse` hook、Codexは`AGENTS.md` + `RTK.md`の公式方式を使う |
| `output-styles/` | Codexへ直接は配らない。必要な挙動をAGENTS、skills、plugin hooksへ分解する |
| `statusline.js` | Claude payload専用。Codexには組み込み `/statusline` があるため別設定として扱う |
| `settings.json` | Codexは `~/.codex/config.toml`。認証値を含むためファイル全体をリポジトリ管理しない |
| Claude由来plugins | Codex側で互換性を再判定する。cacheの存在やClaude側enabledを実行許可とみなさない |

これらを共有ソース（`skills/` `commands/` `rules/` `CLAUDE.md`）に書くときは、
特定ホスト固有のツール名・パスに依存させない。Codex は未対応の frontmatter キーや設定を
**エラーにせず黙って読み飛ばす**ため、依存が残ると「リンクは成功しているのに機能だけ落ちる」状態になる。

### Codex subagentのモデルルーティング

`setup.sh --codex`は`~/.codex/config.toml`の`[agents]`へ、指定漏れ用の既定値
`gpt-6-luna` + `medium`を設定する。設定ファイル全体は置換せず、対象2キーだけを更新する。
更新時はowner、`0600`相当、ACL、symlinkを検査し、同じリポジトリのconfig更新処理を
永続lockで直列化する。共有lockを使うmutator間では競合を防ぎ、未協調writerについても
内容・metadataをrename直前まで再検査し、検出した競合は原本を上書きせず停止する。
通常renameには比較条件が無いため、最終検査後の未協調更新まで完全に防ぐものではない。
この保証境界と残余リスクはADR 0009に記録している。
各custom agentはモデルと推論強度を明示し、親AIは`~/.codex/MODEL_ROUTING.md`に従って
深さ不足・探索範囲不足・設計判断不足を分けて自律的に昇降する。
security boundaryに一致する通常の意味レビューは、OpenAI公式のモデル選択指針を踏まえて
`security-reviewer`の`gpt-6-sol` + `high` + `read-only`を使う。

別モデルへ実装・探索・修正・レビューを移す前には、
`.superpowers/handoffs/<task-id>.md`を作成する。Superpowersのtask brief / review packageが
ある場合は複製せずSHA-256付きで参照し、無い場合はhandoff本文を要件の正本にする。
`bin/validate-codex-handoff.py`が必須section、branch、HEAD、worktree fingerprint、参照hash、
実行可能なmodel + reasoning effortの組み合わせを検査し、各custom agentも最初に同じ検査と
全文読み込みを行う。validatorは`--repo`を事前に`resolve()`せず、cwdまたはfilesystem rootの
directory FDから全componentを`O_NOFOLLOW`で辿ってGit実行前に固定し、継承された
`GIT_*`環境を除去する。Git top-levelとのdevice・inode一致を確認した後も同じroot FDを
validate / read終了までGit subprocessとfile openへ共有する。fingerprintはGitにworktree内容の
変換・diff生成をさせず、index entryと、root FDから中間directoryを`O_NOFOLLOW`で固定して
読んだtracked/untracked fileの生bytesをhashする。submoduleも`git status`へ内容変換を委ねず、
root FDから`O_NOFOLLOW`で開いた
directory inodeをGit subprocess、HEAD tree・index・生bytes比較、nested submodule再帰で共有する。
検査中にsubmodule pathが差し替わっても、文字列pathからrepository外を再解決しない。
dirty submoduleは内部差分を曖昧な状態へ畳まず`NEEDS_CONTEXT`として拒否する。
初回検証が返すhandoff＋参照成果物の`INPUT_DIGEST`を保持し、agentは各pathを直接読まず、
同じdigestを指定したvalidatorの`read`経由で検証済みbytesを全行取得する。長い成果物は行範囲で
分割しても、各chunkで入力全体のdigestを再照合する。検証後に内容が差し替わった場合は返却しない。
不備・古さ・矛盾は推測で補わず`NEEDS_CONTEXT`として親へ返す。

モデルルーティングはproviderを変更しない。選んだペアを現在のproviderで利用できない場合、
別providerへ黙って切り替えず停止して報告する。設計理由は
`docs/adr/0010-codex-adaptive-model-routing.md`と
`docs/adr/0011-codex-cross-model-handoff.md`を参照。

### Codex親セッションの工程切替

親AIも設計から実装など別工程へ進む時、次工程のmodelとeffortを再分類する。標準経路は、
分離できる作業を検証済みhandoff付きの明示ペアsubagentへ渡すこと、または親ペア自体の保証が
必要なら明示ペアのfresh sessionへ移すことである。

新規の同一thread `begin`は常に拒否する。旧grantが残っていても開始できない。
旧`PREPARING` / `SWITCH_PENDING`は互換・復旧用に扱い、通常promptで「モデル切替を診断して」
「切替待ちを取り消して」とCodexへ依頼できる。Codexが`python3 ~/.codex/bin/codex-model-switch.py`
の`diagnose` / `cancel`を実行する方式で、利用者が別Terminalへ入力する運用を前提にしない。
これは標準CLIの`codex diagnose`ではない。

取消までは通常local toolを止め、対象repo・session・transitionに完全一致する復旧操作を許す。
取消後はmanifestが`CANCELLED`になりregistryを解除する。旧resumeのmodel証拠はhook観測、
effortは`user-attested`に留まる。review runner本体は未実装であり、現状の必須reviewは
検証済みhandoffを渡した明示ペアのread-only agentで行う。

`setup.sh --codex`でCLI・hook・配線を配布する。Codexの`/hooks`でhook定義を承認し、
新しいsessionで案内を確認する。Active/trustedの表示は対象turnの配送証拠ではない。
hook未承認・無効・timeout・実行不能のとき、guardが動作したとは扱わない。
状態は`.superpowers/model-switch/`、`CODEX_HOME/model-switch-registry/`、
`CODEX_HOME/model-switch-preflight/`へowner-onlyで保存する。

操作は`codex/MODEL_ROUTING.md`、判断根拠は[ADR 0016](docs/adr/0016-codex-parent-routing-pilot.md)、
未検証事項と不具合時の調査手順は[運用引継書](docs/codex-parent-routing-operations-handoff.md)を参照。

## 認証プロファイルの切り替え

会社PCのように1台のマシンで「業務のゲートウェイ経由」と「個人アカウント」を
使い分けたい場合、起動コマンドで切り替えられる。Claude Code / Codex CLI の両方に用意してある。

### Claude Code

| コマンド | 接続先 | 仕組み |
|---|---|---|
| `claude` | LiteLLM経由（会社） | `~/.claude/settings.json` の `env` がそのまま効く |
| `ccp` | 個人Anthropicアカウント | `--settings` で認証系 `env` を空文字列に上書きし、OAuth/keychain認証にフォールバックさせる |

`ccp` を使うには `~/.claude/bin` にPATHを通す（`setup.sh` が未通しの場合に案内する）：

```bash
# ~/.zshrc に追記
export PATH="$HOME/.claude/bin:$PATH"
```

現在どちらに繋がっているかは statusline に常時表示される（`🏢WORK` / `🏠PERSONAL`）。
コマンドで確認する場合：

```bash
claude auth status   # 会社: authMethod = "oauth_token"（email等は出ない）
ccp auth status      # 個人: authMethod = "claude.ai" + email/subscriptionType
```

### 設計上の判断

**なぜ `claude` 側を素のままにするか**: 逆向き（`settings.json` から認証 `env` を抜き、
会社用のときだけラッパーで注入する）も技術的には成立するが、シェル統合が読み込まれなかったとき
`claude` が**黙って個人アカウントで動く**ため、業務コードが個人契約に流れる無言の事故になる。
本方式なら `ccp: command not found` で即座に気づける。既存の会社PC設定を一切変更しない点でも
影響が小さい。

**プラグインも認証 env を読む**: この切り替えは Claude Code 本体だけでなく、
`ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` を読むプラグインの LLM 呼び出しにも及ぶ。
`ccp` では両者が空文字列になるため、そうしたプラグインは**課金先を失って起動しない**
（security-guidance で実測確認済み）。裏を返すと素の `claude` では会社ゲートウェイに乗るので、
プラグインが毎ターン LLM を叩く種類のものかどうかは導入時に確認する。

**Bashから起動する `claude -p` は `claude-headless` を使う**: `ccp` で起動したセッションの中から素の `claude -p` を起動すると、
子は `~/.claude/settings.json` を読み直し、会社の接続情報で動く。`--settings` はコマンドライン引数なので子に届かない。
`setup.sh` は、`settings.personal.json` の `env` に目印 `CLAUDE_PROFILE=personal` を書く。この値は、Bashを通して子まで届く。
`settings.json` の `env` にも `CLAUDE_PROFILE=default` を置く。会社のセッションに `personal` が紛れ込んでも、この値で上書きされる。
`bin/claude-headless` は、`personal` なら `--settings ~/.claude/settings.personal.json` を付け、`default` ならそのまま `claude` を起動する。
目印が無いとき（`env -i` などで消えたとき）は、どちらのプロファイルか決められないので止まる。
サブエージェントやフックから `claude -p` を起動する経路は、まだこのスクリプトに寄せていない。

### 機密でない機能トグルの置き場

`settings.json` の `env` には2種類の値が入る。**寿命が違うので置き場を分ける。**

| 種類 | 置き場 | 適用範囲 |
|---|---|---|
| 認証情報（マシン固有・機密） | `env.json.template` | `.env` があるマシンのみ |
| 機能トグル（全マシン共通・非機密） | **`settings.json.template` の `env`** | 常に |

トグルを `env.json.template` に置いてはいけない。`.env` の無いマシンに適用されない上、
`settings.personal.json` は `env.json.template` のキーを**全て空文字列で潰す**設計なので、
`"0"` で無効化するタイプのトグルが `ccp` 側で有効に戻ってしまう。

`setup.sh` は `env` だけ追記マージする。トップレベルの `update` では `env` キーごと
置換され、base 側のトグルが `.env` のあるマシンでだけ消える（会社PCでのみ設定が効かない、
最も気づきにくい壊れ方）ため。

**無効化キーの二重管理を避ける**: `settings.personal.json` は `env.json.template` のキー集合から
`setup.sh` が導出する。テンプレートにキーを足したときの無効化漏れを構造的に防ぐため。

詳細は `docs/superpowers/specs/2026-08-01-auth-profile-switching-design.md` を参照。

### Codex CLI

| コマンド | 接続先 | 仕組み |
|---|---|---|
| `codex` | LLM gateway経由（会社） | `~/.codex/config.toml` の `model_provider` がそのまま効く |
| `cxp` | 個人ChatGPTアカウント | `CODEX_HOME=~/.codex-personal` で起動する。設定・認証・履歴は会社用と分かれる |

個人用の `CODEX_HOME` は自分で作り、そこでログインする。`bash setup.sh --codex` は、
`~/.codex-personal` があれば会社用と同じ共有資産のリンクを張る（無ければ個人用への配布だけを飛ばす）。

```bash
mkdir -m 700 ~/.codex-personal
CODEX_HOME=~/.codex-personal codex login   # 個人ChatGPTアカウントでログイン
bash setup.sh --codex                      # 個人用にもリンクを張る
cxp                                        # 個人アカウントで起動（初回は /hooks で承認する）
```

**会社用の `~/.codex` に `auth.json` を置かない。** 会社用の `model_provider` が外部ツールの書き換えなどで
消えると、Codexは既定の `openai` に倒れ、同じ `CODEX_HOME` の `auth.json` で認証する。
個人の認証情報が会社用に無ければ、この場合は401で止まり、黙って個人アカウントで動くことはない。
2026-09-21に実際に起きた事故と、`CODEX_HOME` を分けた判断は `docs/adr/0026-codex-separate-personal-home.md` を参照。

`hooks/check-codex-base-provider.py` はSessionStartで、会社用（`[model_providers.*]` を定義している側）について
次の2つを検査し、UIへ警告する。正常時は何も出さない。

- `model_provider` が無い、または定義していない provider を選んでいる
- `auth.json` がある（壊れたsymlinkも含む）

provider は起動時に確定するため、警告は次の起動前に直すための通知であり、そのセッションを止めるものではない。
hook は `/hooks` で承認するまで動かない。認証情報をOSのkeyringに保存する設定（`cli_auth_credentials_store`）では
`auth.json` が作られないので、この検査では検知できない。

`codex/hooks.json` のhookコマンドは `$HOME/.codex/hooks/...` を指す。個人用で起動しても、hookの実体は
会社用のリンク経由で読まれる。

#### 設計上の判断

`claude` / `ccp` と同じ向きにしてある。素の `codex` を会社設定のままにするのは、
逆向きにするとシェル統合が読み込まれなかったときに `codex` が黙って個人アカウントで
動くため。この向きなら `cxp: command not found` で気づける。

以前は `codex -p personal` で会社用の設定に個人プロファイルを重ねていた。重ねる方式では
会社のMCPサーバや設定を個人セッションが引き継ぐため、allowlistによる無効化や所有キーの管理が必要だった
（ADR 0005・0006・0023）。`CODEX_HOME` を分けたことで、これらの仕組みは削除した。

## ディレクトリ構成

```
├── CLAUDE.md                    # グローバル指示
├── AGENTS.md                    # このリポジトリのCodex project guidance
├── claude-code-best-practice/   # ベストプラクティス（git submodule）
├── codex-cli-best-practice/      # Codexベストプラクティス（git submodule、補助資料）
├── skills/                      # カスタムスキル
│   ├── api-design/              #   REST API設計パターン
│   ├── architecture-decision-records/  # ADR記録
│   ├── backend-patterns/        #   バックエンドパターン
│   ├── claude-code-best-practice/  # 設定ベストプラクティス参照
│   ├── code-learning/           #   実作業でのコード理解・変更・レビュー演習
│   ├── coding-standards/        #   コーディング規約
│   ├── database-migrations/     #   DBマイグレーション
│   ├── deployment-patterns/     #   デプロイパターン
│   ├── hexagonal-architecture/  #   ヘキサゴナルアーキテクチャ
│   ├── learning-mode/           #   学習モードの手順と書式
│   ├── security-review/         #   セキュリティレビュー
│   ├── verification-loop/       #   検証ループ（Iron Law付き）
│   └── yomiyasu/                #   日本語文書の書き直し（git submodule）
├── commands/                    # スラッシュコマンド
│   ├── aside.md                 #   サイドクエスチョン
│   ├── build-fix.md             #   ビルドエラー修正
│   ├── code-review.md           #   コードレビュー
│   ├── explain.md               #   プロジェクト説明
│   ├── feature-dev.md           #   フィーチャー開発
│   ├── plan.md                  #   実装計画
│   ├── pr-create.md             #   PR作成
│   ├── quality-gate.md          #   品質ゲート
│   ├── refactor-clean.md        #   リファクタリング
│   ├── tdd.md                   #   TDD（shimコマンド）
│   ├── test-coverage.md         #   テストカバレッジ
│   └── verify.md                #   検証（shimコマンド）
├── agents/                      # サブエージェント定義
│   ├── planner.md               #   実装計画（opus, bite-sized tasks）
│   ├── code-architect.md        #   アーキテクチャ設計
│   ├── code-explorer.md         #   コードベース調査
│   ├── code-simplifier.md       #   コード簡素化
│   ├── refactor-cleaner.md      #   デッドコード除去
│   ├── security-reviewer.md     #   セキュリティレビュー
│   ├── build-error-resolver.md  #   ビルドエラー解決
│   ├── jp-doc-reviewer.md       #   日本語文書のレビュー（opus、yomiyasu）
│   └── silent-failure-hunter.md #   サイレント障害検出
├── codex/                       # Codex固有アダプター
│   ├── RTK.md                   #   RTK公式のCodex向けシェル指示
│   ├── agents/                  #   agents/*.mdから生成したTOML
│   └── hooks.json               #   Codex向けhookイベント定義
├── rules/                       # 常時適用ルール
│   ├── learning-mode.md         #   学習モードの判定と共通方針
│   ├── code-learning.md         #   コード学習の常時発火入口
│   ├── proving-absence.md       #   「無い」と主張するときの形式
│   ├── output-formatting.md     #   URL表示フォーマット
│   ├── task-management.md       #   タスク管理手順
│   ├── ecc-coding-style.md      #   コーディングスタイル
│   ├── ecc-development-workflow.md  # 開発ワークフロー
│   └── ecc-testing.md           #   テスト要件
├── hooks/                       # 危険コマンドブロック等のhooksスクリプト（Claude向けrtkフックはsettings.json.template側で管理）
│   ├── block-commit-on-merged-pr.py # マージ済みPRのブランチへのコミットを止める
│   ├── guard-dangerous-bash.sh  #   PreToolUse(Bash)フックのエントリポイント
│   ├── guard-dangerous-bash.py  #   危険コマンド判定の実処理
│   ├── hook_support.py          #   会話記録の読み取りと出力の補助
│   ├── jp-doc-review.py         #   PR作成前の日本語文書のレビュー依頼・Confluenceの事前チェック
│   └── skill-read-check.py      #   スキルの必読資料の読み漏れ確認
├── bin/                         # 起動ラッパー（PATHを通して使う）
│   ├── ccp                      #   個人Anthropicアカウントで Claude Code を起動する
│   ├── cxp                      #   個人ChatGPTアカウントで Codex CLI を起動する
│   └── configure_codex_signing.py #   Bitwarden SSH agentをCodex子プロセスへ配布する
├── output-styles/               # カスタムアウトプットスタイル
│   ├── review-and-design.md     #   Review & Design（コードレビュー・設計判断特化）
│   └── fast.md                  #   高速実行（説明最小限）
├── learning/                    # 学習ログ（公開可能な抽象化済み記録）
│   ├── entries/                 #   設計Predict / ★ Delta
│   └── code/                    #   コード学習の実証記録とschema
├── statusline.js                # ステータスライン表示
├── settings.json.template       # settings.jsonテンプレート（共通設定、.env不要）
├── env.json.template            # envブロックテンプレート（LiteLLM等APIキー利用時のみ、.env必要）
├── .env.example                 # 環境変数サンプル
├── setup.sh                     # セットアップスクリプト
└── README.md
```

## 日本語文書のレビュー（Claude Code専用）

Claude Codeが `gh pr create` でPRを作るときに、フックが1回だけ止める。そして、ブランチで変わった日本語のMarkdownや設定ファイルを、
`jp-doc-reviewer` サブエージェントにyomiyasuの基準でレビューさせる。対象は、baseとの分岐点からHEADまでの差分にある文書である。
`Co-Authored-By: Claude` の行が付いたコミットで変わった文書は、自動でレビューを依頼する。それ以外の文書は、レビューに含めてよいかをユーザーに確かめる。
Confluenceへの日本語の投稿も、送る前に1回止めて下書きのレビューを求める。2回目のPR作成と投稿は止めない。
あわせて、スキルを呼んだのに必読資料を読まずに作業を終えようとしたときに、`skill-read-check.py` が差し戻す。

PRを作らないリポジトリや、Claude Codeの外（ブラウザなど）で作ったPRでは、レビューは動かない。

| フック | イベント | 役割 |
|---|---|---|
| `jp-doc-review.py pre-tool-use-bash` | PreToolUse（Bash） | `gh pr create` の前にレビューを依頼する |
| `jp-doc-review.py pre-tool-use-confluence` | PreToolUse（Confluenceの投稿） | 投稿の前に下書きのレビューを依頼する |
| `jp-doc-review.py pre-tool-use-agent` | PreToolUse（Agent・Task） | レビュワーへの依頼文のパスを、Editの許可リストに記録する |
| `skill-read-check.py` | Stop・SubagentStop | 必読資料の読み漏れを会話記録から見つける |

配線は `settings.json.template` だけにある。`codex/hooks.json` には配線していないので、Codex CLIでは動かない。

記録と下書きは `~/.claude/state/jp-doc-review/` に置く。下書きは社内文書の写しを含みうるので、
ディレクトリは0700、ファイルは0600で作る。Confluenceの下書きは、2回目の投稿を通したときに消す。
7日を過ぎた状態ファイルと下書きは、PR作成時の確認とConfluenceへの投稿のときに消す。走査は1時間に1回までにしている。

`jp-doc-reviewer` が使えるBashは、yomiyasuのリンターだけにしている。レビュワーは社内文書を読むので、
本文に仕込まれた指示でコマンドを実行されないよう、定義のhooksで `jp-doc-review.py pre-tool-use-reviewer-bash` を呼び、
リンター以外のコマンドを止める。
Editは、依頼文に書かれたファイルだけに絞る。`Agent|Task` のPreToolUseフックが、`jp-doc-reviewer` への依頼文からパスを取り出して
セッションごとの許可リストに記録し、Editのフックは、許可リストにあるファイルだけを通す。
yomiyasuの置き場、フック、レビュワーの定義、`settings*.json` は、依頼文に書かれていても通さない。
パスは `/` を含む英数字と `._~-` の連続として取り出すので、日本語やスペースを含むパスは取り出せず、レビュワーは直せない。

yomiyasuはsubmodule（`skills/yomiyasu`）として固定している。npx版のyomiyasuを入れていたPCでは、
先に `npx skills remove -g yomiyasu` で外してから `bash setup.sh --claude` を実行する。
npx版を残すと、`npx skills update` がリンクをたどってsubmoduleの中身を上書きするおそれがある。
既存のリンクが残っていれば、setup.shが衝突として止まるので、中身を確かめてから置き換える。

レビュワーはyomiyasuの `SKILL.md`、`references/`、`scripts/yomiyasu_lint.py` をそのまま読み、実行する。
固定を上げるとき（`git submodule update --remote skills/yomiyasu` など）は、差分を読んでからコミットする。

設計は `docs/superpowers/specs/2026-10-01-jp-doc-review-design.md`、判断の経緯と却下した案は
`docs/adr/0024-jp-doc-review-hook.md` を参照。レビューの時機をPR作成時へ移した経緯は `docs/adr/0025-jp-doc-review-at-pr-creation.md` にある。

## claude-code-best-practice（submodule）

[shanraisshan/claude-code-best-practice](https://github.com/shanraisshan/claude-code-best-practice) をgit submoduleとして内包している。Claude Codeの設定パターンに関するベストプラクティス集で、以下のトピックをカバーする：

- **CLAUDE.md** — 書き方、配置戦略、サイズ制限、`<important if="...">`タグ
- **Skills / Commands** — 定義方法、フロントマター仕様、パターン
- **Subagents** — 定義方法、フロントマター仕様、オーケストレーションパターン
- **Settings** — settings.json の全設定項目リファレンス
- **MCP** — MCPサーバーの設定方法
- **CLIフラグ / パワーアップ** — 起動オプション、実験的機能

`skills/claude-code-best-practice/` スキルにより、Claude Code設定の作業時に自動参照される。手動で呼び出す場合は `/claude-code-best-practice` を使用する。

## codex-cli-best-practice（submodule）

[shanraisshan/codex-cli-best-practice](https://github.com/shanraisshan/codex-cli-best-practice) を
Codex固有設定の補助資料として内包している。AGENTS、skills、subagents、hooks、plugins、MCP、
config、memoryの例を横断して確認できる。

ただし、固定したHEADはCodex CLI 0.147.0より古く、旧feature名、旧profile形式、
現在存在するmarketplace `list`を否定する記述などがある。**Codex公式資料とローカルCLIの
`--help`を優先し、このsubmoduleだけを根拠に設定しない。** 差分の一覧は
[Codex互換性監査](docs/codex-compatibility-audit.md#codex-cli-best-practice-の評価)を参照。

最新化:

```bash
git submodule update --remote
```

## CLAUDE.md と rules/ の使い分け

`rules/` のロードタイミングは `paths` フロントマターの有無で変わる：

| 配置 | ロード | コンテキストコスト |
|---|---|---|
| `CLAUDE.md` | 毎セッション | 常に消費 |
| `rules/`（`paths` なし） | 毎セッション | CLAUDE.md と同じ |
| `rules/`（`paths` あり） | マッチするファイルを開いたとき | 条件付き（節約） |

### CLAUDE.md に残すもの

- プロジェクト問わず常に適用したいルール（言語設定、Git、ワークフロー等）
- 目安：60行以下に収める（遵守率を最大化するため）

### rules/ に分離するもの

- 詳細な行動仕様（学習モード、タスク管理等）→ `alwaysApply: true` で常時読み込み
- 特定ファイルを扱うときだけ適用したいルール → `paths` フロントマターで条件付き

```markdown
# rules/typescript.md
---
paths:
  - "**/*.{ts,tsx}"
---
- 型は interface を優先する
- any は禁止
```

## 管理対象外

以下は機密情報を含むため、`.gitignore` で除外している：

- `.env` — APIトークン等の環境変数（LiteLLM等APIキー経由で利用する場合のみ必要。`env.json.template` と組み合わせて使用）
- `settings.json` — 生成済みの設定ファイル
- `.claude/settings.local.json` — プロジェクト固有設定

## learning/ の運用

新規の学習記録は、この設定リポジトリとは別の専用学習storeへ保存する。
`setup.sh` はClaude Codeの `~/.claude/bin/learning-store.py` とCodex CLIの
`~/.codex/bin/learning-store.py` に同じCLIを配布するが、storeの初期化やbindingは行わない。
初回作成、別マシンでのcloneとbind、保存・commit・remote反映の状態区分は
`learning/README.md` を参照する。コード学習のschemaと証拠条件は `learning/code/README.md` に置く。

このリポジトリの `learning/entries/` と旧 `learning/code/entries/` は、既存ADRから参照される
読み取り専用履歴である。新規記録を追加せず、旧hit/missやAI評価を新schemaの習得証拠へ変換しない。
このリポジトリはPUBLICのため、旧履歴も業務固有情報を抽象化した状態を保つ。

## テスト実行

リポジトリのルートから実行する。通常のGit fixtureは一時HOMEと環境変数で個人設定を
隔離し、署名とhookの実行を無効にする。実環境のGit設定や署名agentは変更しない。
hookの判定テストには元の環境を渡し、リポジトリ内のhookファイルをそのまま検査する。

全suiteの前に、runtimeテストが必要とするlocalhostの待受権限を短く検査する。

```bash
python3 -c 'from tests.test_codex_model_switch_runtime import check_localhost_permission; check_localhost_permission()'
```

拒否されたら、同じ環境で全suiteを繰り返さず、`127.0.0.1` の待受を許可した実行環境で
事前検査を再実行する。コマンドの承認だけでOSのサンドボックス制約が解除されるとは限らない。
権限確認後は、まず失敗したモジュールだけを検証する（以下はruntimeの例）。

```bash
python3 -W error::ResourceWarning -m unittest tests.test_codex_model_switch_runtime -v -f
```

`-f` は最初の失敗・エラーで停止するfailfast。ログを保存した場合は末尾だけでなく、
全体の `FAIL`・`ERROR` とtracebackを確認する。失敗対象の修正と検証が済んだら、最後に全suiteを実行する。

```bash
python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_*.py' -v
```

件数・終了コード・所要時間を記録する。localhost拒否はruntimeクラスの初期化エラー1件として
表示し、skipにしない。その場合、runtimeの各テスト本体は未実行として扱う。

## 禁止パターン検査（pre-commit フック）

抽象化ルールは規約なので、守り忘れれば素通りする。実際に2回すり抜けた（計画書・lessons への
実名混入、エントリの誤爆）。公開 git 履歴は SHA 直参照・PR ref・fork ネットワーク・既存クローン・
コード検索索引に残り、一度 push した内容は取り消せないため、規約ではなく機構で止める。

`.githooks/pre-commit` が **ステージ済み差分の追加行** を検査し、禁止パターンに当たれば
コミットをブロックする。既存行を対象にしないのは、既に履歴へ入った記述で無関係なコミットまで
止まり続けると `--no-verify` が習慣化し、機構そのものが死ぬため。

### パターン定義は2層

| ファイル | 追跡 | 内容 |
|---|---|---|
| `.githooks/patterns-common.txt` | tracked | 内部IP・内部TLD・秘密鍵形式・ローカル絶対パス等の**構造的**パターン |
| `.githooks/patterns-local.txt` | **untracked** | 社名・プロジェクト名・内部ホスト等の**固有名詞** |

固有名詞を分離しているのは、禁止したい語そのものが機密だから。PUBLIC なこのリポジトリに
書いた時点で目的と矛盾する。ひな形として `.githooks/patterns-local.txt.example` を追跡している。

### 有効化

`bash setup.sh --all` などのセットアップ実行が `core.hooksPath` を `.githooks` に設定し、`patterns-local.txt` を
ひな形から初期化する（既存があれば保持）。初期化直後は固有名詞が未記入なので、
`patterns-local.txt` を編集して実際の語を追加する。

`patterns-local.txt` が存在しない場合、フックは**コミットをブロックする**（fail closed）。
黙って通すと「検査したつもり」で漏洩が素通りするため、必ず止めて復旧手順を表示する。
有効なパターンが0件の場合は警告のみ出して続行する。

### バイパス

`git commit --no-verify` で回避できる。ただし **Claude Code 経由の実行はブロックされる**
（`hooks/guard-dangerous-bash.py`）。AI が自動的に迂回できると、この機構は存在しないのと
同じになるため。ブロックは「検証フックが実際に設定されているリポジトリ」でのみ働くので、
フックを持たない他プロジェクトには影響しない。

回避が必要なときは端末で自分で実行する。判断する主体を人間に残すのが意図。

## Superpowers由来の強化

[obra/superpowers](https://github.com/obra/superpowers)（MIT License）は、Claude Codeでは
`superpowers@claude-plugins-official`、Codex CLIでは`superpowers@openai-api-curated`として
それぞれのホスト側へ導入する。Claude側は`settings.json.template`、Codex側は
`codex/plugin-policy.json`で管理し、両ホストのプラグイン状態は自動同期しない。
プラグイン本体が`systematic-debugging`・`subagent-driven-development`等のスキルを提供するため、
同名で重複する独自skillは置かない。

一方、学習モードやoutput-styleなど本リポジトリ独自の仕組みと組み合わせる形で、以下の要素は独自ファイルに部分的に取り込んでいる。

| 取り入れた要素 | 適用先 | 内容 |
|---|---|---|
| Rationalization Prevention Tables | verification-loop, planner | エージェントの自己正当化を事前にブロックする対応表 |
| Bite-Sized Task Granularity | agents/planner.md | 2-5分粒度のタスク分解 + プレースホルダー禁止 |
| Verification Iron Law | skills/verification-loop/ | 「証拠なしに完了を主張するな」の行動規範 |

## 参考

- https://github.com/obra/superpowers — エージェント向けスキルフレームワーク（Claude/Codexの各公式プラグインとして導入）
- https://github.com/shanraisshan/claude-code-best-practice — Claude Code設定ベストプラクティス（submodule）
- https://github.com/shanraisshan/codex-cli-best-practice — Codex CLI設定の補助資料（submodule、公式資料を優先）
- https://github.com/affaan-m/everything-claude-code — Claude Code設定集
