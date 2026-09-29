---
adr: 20
date: 2026-09-29
status: accepted
---

# 学習store directoryを排他し旧CLIと書込方式を分離する

## 背景

ADR 0019のstore直下lock fileはCodex sandboxから開けるが、Git管理外のため
`git clean -fdX`で保存中に削除できる。削除前後で別inodeへlockが分かれ、
同一イベントの競合検査が同時に通る可能性をsecurity reviewが指摘した。
旧CLIは`.git/agent-learning.lock`を使うため、新旧CLIの同時実行でも
排他が分かれる。ローカルの一時Git repoでdirectoryの`flock`がmacOSと
Codex sandboxの両方で成功した。

## 決定

保存とimportはstore directoryのfile descriptorへ`flock`を掛ける。
lock取得後に開いたdirectoryと現在のpathが同じdevice・inodeか確認する。
lock fileは作らず、Git cleanの対象にもならない。

markerの`schema_version`を2にし、新CLIは旧markerを拒否する。旧CLIは
markerのschemaが1以外なら拒否するため、旧CLIと新CLIが同じstoreに
書き込まない。旧markerの移行は旧CLIの停止とデータ照合を伴う明示的な
運用作業にする。

## 検討した代替案

- **ADR 0019の無視対象fileを維持する**: 保存中のGit cleanでlock inodeが分かれる。
- **lock fileをGitで追跡する**: clone先の権限とcheckout中の置換を管理する必要がある。
- **共通設定directoryへlockを移す**: 作業repo外の書込許可とstore IDごとの管理が増える。
- **新旧CLIの同時実行を注意書きだけで防ぐ**: 実行中の旧processを検知できず、
  誤った履歴末尾を作る可能性を残す。

## 結果

Git cleanで消せる排他fileがなくなり、marker versionで旧CLIが失敗する。
既存のschema 1 storeは新CLIで失敗するため、移行を済ませるまで使えない。
directory自体を権限外で差し替えられる同一userの動作や、OS間での
directory `flock`対応は運用時に確認を続ける。移設時は全保存処理を停止する。

## 根拠

- `tests/test_learning_store.py`のGit clean中の排他検査と旧marker拒否
- 2026-09-29のmacOS標準Python 3.9とCodex sandboxによるdirectory `flock`実測
- [ADR 0019](0019-learning-store-lock-outside-git.md)
