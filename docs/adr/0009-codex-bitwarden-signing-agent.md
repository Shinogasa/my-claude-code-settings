---
adr: 9
date: 2026-09-03
status: accepted
---

# Codex子プロセスへBitwarden SSH agentを配布する

## 背景

Codexのshell sandboxや子プロセスからGitのSSH署名を行うとき、親シェルの
`SSH_AUTH_SOCK`が渡らず、agentへ接続できないことがあった。Git側はSSH形式の署名を
有効にしていても、署名なしfallbackへ退避すると履歴の検証可能性が失われる。
macOSのBitwarden Desktop socketを`SSH_AUTH_SOCK`へ明示すると、Codex CLI 0.152.1の
freshな子commandからagent鍵を取得できることを実測した。

Codex公式リファレンスは、`shell_environment_policy.set`を子プロセスへ注入する
文字列mapとして定義している。

## 決定

- `setup.sh --codex`から`bin/configure_codex_signing.py`を呼び出す。
- macOSだけをhost discoveryの対象とし、socketは`$HOME/Library/Containers/com.bitwarden.desktop/Data/.bitwarden-ssh-agent.sock`から導出する。ユーザー名を含む絶対pathはリポジトリへ保存しない。
- configが無い、macOS以外、socketが無い、Bitwardenがlock中、鍵が0件、agentへ接続できない場合は警告して継続する。既存の`config.toml`は変更しない。
- agent疎通はsocketの存在だけで成功扱いにせず、`SSH_AUTH_SOCK=<socket> ssh-add -l`の成功で判定する。agentの標準出力・標準エラーはログへ流さない。
- `~/.codex/config.toml`はGit管理せず、`[shell_environment_policy.set]`の`SSH_AUTH_SOCK`だけを管理対象として追加・更新する。既存の別socketは、Bitwarden agentの鍵を確認できた場合に限り置き換える。
- TOMLを再シリアライズせず、コメント・無関係な設定・認証情報を保持する。変更前後をparserで比較し、重複・inline table・壊れたTOML・symlink・所有者不一致は書き込まず失敗する。書き込みは元のmodeを保った一時ファイルからatomicに行う。
- 設定を適用または確認できた場合だけ、既存Codexセッションの再起動を案内する。未署名の既存commitは自動rewriteしない。
- 開発コンテナ内のBitwarden relayとRTKバイナリは`cw-workspace-local`の責務とし、このhost adapterでは変更しない。

## 検討した代替案

- **`config.toml`全体をTOML writerで書き直す**: コメントや未知の設定、認証情報の表現を壊すため採用しない。
- **socket pathを追記するだけにする**: 既存keyとの重複でCodexの設定が壊れるため採用しない。対象tableとkeyを一意に検査する。
- **agentが無い場合にsetupを停止する**: Bitwarden未導入のマシン、lock中、CI、LinuxでCodex設定まで失敗するため採用しない。署名設定だけを警告付きでskipする。
- **既存の`SSH_AUTH_SOCK`を常に保持する**: 別agentを使うとBitwardenの署名鍵が選ばれる保証がなく、今回の子プロセス障害を再発させるため採用しない。Bitwarden agentを検証できたときだけ置き換える。
- **全OSのsocket discoveryを同時に実装する**: 現在根拠があるmacOSのBitwarden Desktopに限定し、Linuxコンテナはrelayを持つ別リポジトリで扱う。
- **シェル環境やhookだけで`SSH_AUTH_SOCK`を注入する**: Codexのsandbox境界を越えて子プロセス・subagentへ伝播する保証がないため採用しない。
- **configや秘密鍵をリポジトリへ配置する**: 認証情報とユーザー固有pathを公開履歴へ持ち込むため採用しない。

## 結果

新しいCodexセッションのshell tool・子command・subagentが、Bitwardenで管理するSSH署名鍵を
同じagent経由で利用できる。設定ができない状態を成功と誤認せず、既存の認証情報や利用者の
設定を保護したまま再実行を促せる。一方、Bitwardenをunlockした後にsetupを再実行しない限り、
現在のセッションへは反映されない。また、署名鍵が複数ある場合のGit側の選択はこのadapterの
責務外であり、`ssh-add -l`と署名検証で確認する。

## 根拠

- [Codex Configuration Reference](https://developers.openai.com/codex/config-reference/): `shell_environment_policy.set`は明示環境値のmapで、子プロセスへ注入される。
- ローカル実測: `codex-cli 0.152.1`、一時config fixture、`tests/test_codex_signing.py`、`tests/test_setup_cli.py`。
