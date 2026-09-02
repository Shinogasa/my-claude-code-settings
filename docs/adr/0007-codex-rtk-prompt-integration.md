---
adr: 7
date: 2026-09-02
status: accepted
---

# CodexのRTK統合を指示アダプターで管理する

## 背景

Claude Codeでは`rtk hook claude`が`PreToolUse`でシェルコマンドを書き換えている。一方、
このhookの応答はCodexの契約と互換性がなく、過去の実測ではCodexが受理せずエラーになった。

RTK 0.45.0の公式Codex統合はhookではない。`rtk init --global --codex`が
`~/.codex/RTK.md`を作り、`~/.codex/AGENTS.md`から参照させる。ローカルのdry-runでも、
この2ファイルへの変更を確認した。

ただし本リポジトリは`~/.codex/AGENTS.md`を`CLAUDE.md`へのsymlinkとして管理する。
公式initをそのまま実行すると、管理外の`RTK.md`を作り、symlink先の共有ファイルへ
マシン固有の絶対パスを追記する。設定の正本と責務が分裂する。

コンテナのバイナリ導入は`cw-workspace-local`の責務であり、同リポジトリの
`devcontainer/Dockerfile.local`には既にRTK 0.45.0の導入がある。コンテナはホストの
`~/.codex`をmountするため、本リポジトリはCodex向け指示の配布だけを担当する。

## 決定

- RTK 0.45.0の公式Codex向け指示を`codex/RTK.md`としてリポジトリ管理する
- `setup.sh --codex`で`codex/RTK.md`を`~/.codex/RTK.md`へsymlinkする
- 共有正本`CLAUDE.md`には、Codexだけが`~/.codex/RTK.md`を読む経路を短く記す
- Codexに`rtk hook claude`を再導入しない
- 管理対象のホームに`rtk init --global --codex`を直接実行しない
- 効果は`rtk gain`と実際のCodexツール呼び出しで確認し、「最大90%」をセッション全体の
  トークンまたは料金の削減率として扱わない

## 検討した代替案

### `rtk init --global --codex`をそのまま実行する

公式コマンドである点は単純だが、`AGENTS.md`がsymlinkである現在の管理方式では、共有正本へ
マシン固有の絶対パスを追記し、`RTK.md`だけがリポジトリ外に残る。公式が生成する内容と
配線を再現しつつ、既存のsymlink管理へ統合する方を採った。

### `rtk hook claude`をCodexでも使う

コマンドを強制的に書き換えられるが、Claude Code固有のhook応答をCodexが受理しない。
無言で効かないのではなくエラーを発生させるため採らない。

### RTK指示の全文を共有`CLAUDE.md`へ埋め込む

Claude Codeでは既にhookが担当しており、毎セッション同じ指示を追加で読む必要がない。
共有正本にはCodex向けファイルへの経路だけを置き、ホスト固有の詳細を分離する。

### Codex用hookがRTKへ正式実装されるまで待つ

将来は指示遵守への依存を減らせる可能性があるが、現時点の公式リリースにはない。
正式リリースされ、Codexのhook契約と実機で確認できた時点で再評価する。

## 結果

Codexが指示に従って`rtk`経由で対応コマンドを実行すれば、Claude Codeと同じRTKの
フィルター処理による出力削減を得られる。一方で、Claude Codeのhookと違い、全コマンドへの
適用は保証されない。新しいCodexセッションで指示を読み込ませ、ツール呼び出しを観測する必要がある。

RTKは失敗時の全出力を既定でローカルへ保存する。機密を含む可能性がある環境では、
tee設定と保存先を確認する。フィルターが診断情報を隠す場合は`rtk proxy <command>`で
生の出力へ戻す。外部サービス用の秘密値や新しい実行権限は、この変更では追加しない。

公式指示をリポジトリへ複製するため、RTK更新時には`codex/RTK.md`との差分確認が必要になる。

## 根拠

- [RTK: Supported AI Agents](https://github.com/rtk-ai/rtk/blob/develop/docs/guide/getting-started/supported-agents.md)
- [RTK v0.45.0: Codex awareness](https://github.com/rtk-ai/rtk/blob/v0.45.0/hooks/codex/rtk-awareness.md)
- [RTK README: Codex setup、gain、tee、telemetry](https://github.com/rtk-ai/rtk/blob/v0.45.0/README.md)
- [OpenAI: Codex AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- ローカルの`rtk init --global --codex --dry-run`、Codex CLI 0.151.0、RTK 0.45.0の実測
