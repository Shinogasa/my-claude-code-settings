# my-claude-code-settings

コーディングエージェント（Claude Code / Codex CLI）の個人設定をGit管理するリポジトリ。
セットアップスクリプトでシンボリックリンクを作成し、各ホストの設定ディレクトリと同期する。

## セットアップ

```bash
git clone --recursive <this-repo>
cd my-claude-code-settings
bash setup.sh
```

`.env` はLiteLLM等のAPIキー経由でClaude Codeを利用する場合（会社PC等）のみ必要。
個人のAnthropicアカウント（Pro/Maxプランの通常ログイン）を使う場合は `.env` 不要で、
`statusLine`/`enabledPlugins`/`theme`等の共通設定はそのまま反映される。

```bash
# LiteLLM/APIキー経由で使う場合のみ
cp .env.example .env
# .env を編集して ANTHROPIC_AUTH_TOKEN 等を設定
bash setup.sh
```

`setup.sh` は以下を実行する：

1. git submodule の初期化・更新
2. シンボリックリンクを `~/.claude/` 配下に作成
3. `settings.json.template` から共通設定を `~/.claude/settings.json` へ生成（`.env` の有無に関わらず常に実行）
4. `.env` が存在する場合のみ、`env.json.template` から生成した `env` ブロック（APIキー等）を追加マージ
5. `~/.claude/settings.personal.json` と `~/.codex/personal.config.toml` を生成（[認証プロファイルの切り替え](#認証プロファイルの切り替え)用）

| リポジトリ | リンク先 | 内容 |
|---|---|---|
| `CLAUDE.md` | `~/.claude/CLAUDE.md` | グローバル指示（全プロジェクト共通） |
| `skills/` | `~/.claude/skills/` | カスタムスキル |
| `commands/` | `~/.claude/commands/` | カスタムスラッシュコマンド |
| `rules/` | `~/.claude/rules/` | 条件付きルール |
| `agents/` | `~/.claude/agents/` | サブエージェント定義 |
| `bin/` | `~/.claude/bin/` | 起動ラッパー（`ccp` / `cxp` = 個人アカウントでの起動） |
| `hooks/` | `~/.claude/hooks/` | 危険コマンドブロック等のhooksスクリプト（Claude向けrtkフックはsettings.json.template側で管理） |
| `statusline.js` | `~/.claude/statusline.js` | ステータスライン表示スクリプト |
| `output-styles/` | `~/.claude/output-styles/` | カスタムアウトプットスタイル |
| `claude-code-best-practice/` | `~/.claude/claude-code-best-practice/` | ベストプラクティス参照（submodule） |

- 何度実行しても安全（冪等）
- 既存ファイルは `~/.claude/backups/` に自動バックアップ

### Codex CLI 向けリンク

`~/.codex/` が存在する場合のみ、同じソースを Codex 向けにもリンクする（内容は二重管理しない）。
未導入マシンでは何も作成せず、スキップした旨を表示する。

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
| `tdd` | `tdd-workflow` |

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

`setup.sh` は Codex 公式マーケットプレイス（`openai-api-curated`）から以下を冪等に導入する。
導入先は `~/.codex/config.toml` だが、同ファイルは認証情報を平文で持つためリポジトリ管理下には
置かない。「リポジトリが状態を持つ」のではなく「冪等なコマンドを `setup.sh` が叩く」形にしている。

| プラグイン | 備考 |
|---|---|
| `superpowers@openai-api-curated` | Codex側のpolicyで管理 |

導入済みのものはスキップする。ユーザーが `enabled = false` にした場合も「導入済み」と判定される
ため、明示的な無効化を `setup.sh` が上書きすることはない。

Codex の `/import` は、Claude Code 側のプラグインを Codex のローカル設定へ取り込むことがある。
取り込まれた enabled 状態は Claude 側と独立して残り、Claude 側で無効化しても自動では止まらない。
特に `security-guidance@claude-plugins-official` 2.0.7 は Claude 固有の非同期hook契約に依存するため、
Codex 側では無効化する。詳細と全プラグインの判定は
[Codex互換性監査](docs/codex-compatibility-audit.md)を参照。

**発火方式がホストで異なる。** Claude Code 版は SessionStart hook が `using-superpowers` を
自動注入するが、Codex 版の配布物は hook を同梱していないため、skills がインデックスに載るだけで
自動発火しない（Codex 自体はプラグイン直下の `hooks.json` で hook を定義でき、他のプラグインは
実際に使っている。superpowers が使っていないだけ）。この差は `CLAUDE.md` の
`## superpowers` 節（＝ `~/.codex/AGENTS.md`）でホスト別に併記して埋めている。

**ホスト別アダプターで扱う資産**

| 資産 | 現在の扱い |
|---|---|
| `agents/` | Markdownを正本にし、`bin/generate-codex-agents.py` で `codex/agents/*.toml` を生成する。実機spawnは未検証 |
| `hooks/` | スクリプト本体は共有し、イベント定義を `settings.json.template` と `codex/hooks.json` に分ける |
| RTK | Claudeは`PreToolUse` hook、Codexは`AGENTS.md` + `RTK.md`の公式方式を使う |
| `output-styles/` | Codexへ直接は配らない。必要な挙動をAGENTS、skills、plugin hooksへ分解する |
| `statusline.js` | Claude payload専用。Codexには組み込み `/statusline` があるため別設定として扱う |
| `settings.json` | Codexは `~/.codex/config.toml`。認証値を含むためファイル全体をリポジトリ管理しない |
| Claude由来plugins | Codex側で互換性を再判定する。cacheの存在やClaude側enabledを実行許可とみなさない |

これらを共有ソース（`skills/` `commands/` `rules/` `CLAUDE.md`）に書くときは、
特定ホスト固有のツール名・パスに依存させない。Codex は未対応の frontmatter キーや設定を
**エラーにせず黙って読み飛ばす**ため、依存が残ると「リンクは成功しているのに機能だけ落ちる」状態になる。

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
| `cxp` | 個人ChatGPTアカウント | `codex -p personal` で `~/.codex/personal.config.toml` を重ね、`model_provider` を `openai` へ切り替える |

初回は個人アカウントでのログインが要る（`~/.codex/auth.json` に入る）。

```bash
codex login          # 個人ChatGPTアカウントでログイン
cxp                  # 個人アカウントで起動
```

会社経路は `auth.json` を読まない（`codex doctor` が
`model provider requires OpenAI auth false` と報告する）ため、
個人ログインを追加しても業務側には影響しない。`~/.codex` は共有のままでよい。

現在どちらに繋がっているかは `codex doctor` の `default model provider` で確認する。

#### 会社の MCP サーバは明示的に無効化する

Codex のプロファイルは base 設定を**置き換えるのではなく重ねる**。プロファイルに書いて
いない `[mcp_servers.*]` は個人セッションでもそのまま起動する（実測: プロファイル未記載の
サーバが接続を試みた）。会社のゲートウェイ上にあるサーバや会社アカウントで認証するサーバが
残ると、**個人作業が会社インフラを会社の鍵で叩く**。エラーも通知も出ないため気づけない。

そのため `setup.sh` は `~/.codex/config.toml` の `[mcp_servers.*]` を全列挙し、
**deny by default** でプロファイルを生成する。個人セッションで有効にするサーバだけを
`codex/personal-mcp-allowlist.txt` に列挙する。

各エントリには `enabled` に加え、HTTP サーバなら `url`、stdio サーバなら `command` を
転記する。Codex CLI 0.151.0 の TUI が設定保存時に profile を単体検証するためである。
認証ヘッダー、token 環境変数、引数、環境変数は転記せず、base から継承する。
URL に userinfo、query、fragment がある場合は、endpoint と秘密値を安全に分離できないため
生成を拒否する。個人 profile 側の MCP エントリも `{url, enabled}` または
`{command, enabled}` 以外のキーがあれば `cxp` が起動前に拒否する。

allowlist 外のサーバは継承した設定を持っていても `enabled = false` のため起動しない。
allowlist へ追加したサーバは base の headers、token 環境変数、args、env も実行時に利用する。
したがって allowlist への追加は、そのサーバの接続先と実行パラメータをまとめて信頼する判断である。

生成後にサーバが追加・削除された場合、または `url` / `command` が変わった場合、
`cxp` は起動前に不一致を検出し、`setup.sh` の再実行を促して停止する。

**検査の範囲**: `config.toml` の `[mcp_servers.*]` のみ。プラグイン marketplace 由来の
MCP サーバ（`~/.codex/plugins/` 配下で定義され `codex mcp list` には出る）は
`config.toml` に現れないため、この生成にも検査にも**含まれない**。
plugin 由来のサーバを有効化する場合は、その素性を自分で確認すること。

#### 設計上の判断

`claude` / `ccp` と同じ向きにしてある。素の `codex` を会社設定のままにするのは、
逆向きにするとシェル統合が読み込まれなかったときに `codex` が黙って個人アカウントで
動くため。この向きなら `cxp: command not found` で気づける。

加えて Codex 固有の事情がある。`codex -p` は**存在しないプロファイル名を渡しても
エラーにせず base 設定で起動する**（実測: exit 0、provider は会社のまま）。
`cxp` はプロファイルの実在を自分で検査して落とす。

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
│   ├── coding-standards/        #   コーディング規約
│   ├── database-migrations/     #   DBマイグレーション
│   ├── deployment-patterns/     #   デプロイパターン
│   ├── hexagonal-architecture/  #   ヘキサゴナルアーキテクチャ
│   ├── security-review/         #   セキュリティレビュー
│   ├── tdd-workflow/            #   TDD（Iron Law付き）
│   └── verification-loop/       #   検証ループ（Iron Law付き）
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
│   └── silent-failure-hunter.md #   サイレント障害検出
├── codex/                       # Codex固有アダプター
│   ├── RTK.md                   #   RTK公式のCodex向けシェル指示
│   ├── agents/                  #   agents/*.mdから生成したTOML
│   └── hooks.json               #   Codex向けhookイベント定義
├── rules/                       # 常時適用ルール
│   ├── learning-mode.md         #   学習モード詳細仕様
│   ├── proving-absence.md       #   「無い」と主張するときの形式
│   ├── output-formatting.md     #   URL表示フォーマット
│   ├── task-management.md       #   タスク管理手順
│   ├── ecc-coding-style.md      #   コーディングスタイル
│   ├── ecc-development-workflow.md  # 開発ワークフロー
│   └── ecc-testing.md           #   テスト要件
├── hooks/                       # 危険コマンドブロック等のhooksスクリプト（Claude向けrtkフックはsettings.json.template側で管理）
│   ├── guard-dangerous-bash.sh  #   PreToolUse(Bash)フックのエントリポイント
│   └── guard-dangerous-bash.py  #   危険コマンド判定の実処理
├── bin/                         # 起動ラッパー（PATHを通して使う）
│   ├── ccp                      #   個人Anthropicアカウントで Claude Code を起動する
│   └── cxp                      #   個人ChatGPTアカウントで Codex CLI を起動する
├── output-styles/               # カスタムアウトプットスタイル
│   ├── review-and-design.md     #   Review & Design（コードレビュー・設計判断特化）
│   └── fast.md                  #   高速実行（説明最小限）
├── statusline.js                # ステータスライン表示
├── settings.json.template       # settings.jsonテンプレート（共通設定、.env不要）
├── env.json.template            # envブロックテンプレート（LiteLLM等APIキー利用時のみ、.env必要）
├── .env.example                 # 環境変数サンプル
├── setup.sh                     # セットアップスクリプト
└── README.md
```

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

学習ログ（★ Predict / ★ Delta の記録）の実体は **このリポジトリの `learning/entries/`** に置き、git で追跡する。運用の詳細は `learning/README.md`。

- **1エントリ1ファイル + frontmatter**: 2026-08-09 に単一ファイル `tasks/learning-journal.md`
  から移行した。後日の集計と学び直しのため、日付・当否・欠けた軸を構造化データで持つ。
  単一ファイルへの追記だった頃は、テンプレート行を実エントリとして数える誤りが2回起きており、
  この形式ではその混同が構造的に起きない。並行セッションでの追記衝突も避けられる。
- **なぜこのリポジトリに置くか**: マシン間で同期され、バックアップされ、後から振り返れる。
  以前は業務用の PRIVATE リポジトリに実体を集約し symlink で参照していたが、
  個人の学習ログを業務用リポジトリに同居させる構成が適切でないため 2026-08-02 に移行した。
  これに伴い `setup.sh` の symlink 集約機構は撤去した。
- **PUBLIC であることの制約**: このリポジトリは PUBLIC のため、社名・プロジェクト名・
  リポジトリ名・内部パス・業務コードを書かない。技術的本質のみを一般化して記録する
  （`rules/learning-mode.md` の抽象化ルール）。抽象化の強制はセキュリティ要件であると同時に、
  本質だけを取り出して言語化する訓練としても機能する。
- **移行前のアーカイブ**: 2026-08-02 以前の詳細版（業務固有情報を含む）は移行元の
  PRIVATE リポジトリにアーカイブとして残しており、以降そちらには追記しない。

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

`bash setup.sh` が `core.hooksPath` を `.githooks` に設定し、`patterns-local.txt` を
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

[obra/superpowers](https://github.com/obra/superpowers)（MIT License）は`superpowers@claude-plugins-official`プラグインとして丸ごと導入している（`settings.json.template`の`enabledPlugins`参照）。プラグイン本体が`systematic-debugging`・`subagent-driven-development`等のスキルを提供するため、同名で重複する独自skillは置かない。

一方、学習モードやoutput-styleなど本リポジトリ独自の仕組みと組み合わせる形で、以下の要素は独自ファイルに部分的に取り込んでいる。

| 取り入れた要素 | 適用先 | 内容 |
|---|---|---|
| Rationalization Prevention Tables | tdd-workflow, verification-loop, planner | エージェントの自己正当化を事前にブロックする対応表 |
| Bite-Sized Task Granularity | agents/planner.md | 2-5分粒度のタスク分解 + プレースホルダー禁止 |
| Verification Iron Law | skills/verification-loop/ | 「証拠なしに完了を主張するな」の行動規範 |
| TDD Iron Law | skills/tdd-workflow/ | 「テスト前にコード書いたら削除」の鉄則 |

## 参考

- https://github.com/obra/superpowers — エージェント向けスキルフレームワーク（`superpowers`プラグインとして導入）
- https://github.com/shanraisshan/claude-code-best-practice — Claude Code設定ベストプラクティス（submodule）
- https://github.com/shanraisshan/codex-cli-best-practice — Codex CLI設定の補助資料（submodule、公式資料を優先）
- https://github.com/affaan-m/everything-claude-code — Claude Code設定集
