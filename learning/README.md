# 学習記録

新規記録の正本は、この設定リポジトリとは別の**専用学習store**である。
設計Predictとコード学習は同じstoreへ保存し、schemaと証拠の解釈だけを分ける。
設計Predictの発火とフィードバックは `rules/learning-mode.md`、コード学習の記録契約は
`learning/code/README.md` を参照する。

このリポジトリの `learning/entries/` と旧 `learning/code/entries/` は、既存ADRからの参照を
保つための**読み取り専用履歴**である。新規記録を追加せず、専用storeとの双方向同期もしない。

## 公開前の境界

記録には、社名、組織・顧客名、リポジトリ名、内部ホスト・URL・path、非公開の型・データ名、
業務コードを含めない。本文だけでなく、能力ID、ファイル名、operation、import manifestも確認する。
安全に抽象化すると判断や証拠が失われる場合は保存せず、未保存であることをユーザーへ伝える。
機密の生データを一時入力ファイルへ書いてから消す運用もしない。

## CLI入口

`setup.sh` は同じ `bin/learning-store.py` を両ホストへ配布するが、storeの作成やbindingは行わない。

| ホスト | CLI |
|---|---|
| Claude Code | `~/.claude/bin/learning-store.py` |
| Codex CLI | `~/.codex/bin/learning-store.py` |

以下では利用中ホストのCLIを `LEARNING_STORE` と表記する。

```bash
# Claude Codeの場合
LEARNING_STORE="$HOME/.claude/bin/learning-store.py"

# Codex CLIの場合
LEARNING_STORE="$HOME/.codex/bin/learning-store.py"
```

bindingは `$XDG_CONFIG_HOME/agent-learning/config.json`、`XDG_CONFIG_HOME` 未指定時は
`~/.config/agent-learning/config.json` に置かれる。共有ruleや作業repoへマシン固有pathを書かない。

Codexを`workspace-write`で使う場合は、専用storeをそのsessionの書込可能なrootへ
追加する。たとえば起動時に`--add-dir`を指定するか、マシン固有のCodex設定で
書込可能rootを追加する。`init`と`bind`ではbinding先にも書込権限が必要で、
`record`ではbindingを読み取れる必要がある。
Codexは書込可能root内でも`.git`を保護するため、排他にはstore directory自体の
OS lockを使う。lock fileは作らない。markerの`schema_version: 2`はこの
排他方式を識別し、旧CLIが同じstoreへ同時に書くことを防ぐ。
`status`の`writable`はOS権限の予備確認であり、sandbox内の保存成功を保証しない。
実際の保存可否は`record`の結果で確認する。

## 初回作成と旧記録の取込

`init` の対象は、利用者が明示した正規化済み絶対pathの空ディレクトリだけにする。
この時点のstoreは `prepared` であり、新規recordはまだ保存できない。

```bash
"$LEARNING_STORE" init --repo /absolute/path/to/learning-store
"$LEARNING_STORE" import --source /absolute/path/to/my-claude-code-settings
"$LEARNING_STORE" status
```

`import` は旧 `learning/entries/` と `learning/code/entries/` を本文不変でlegacy領域へ複製し、
source commit、相対path、SHA-256をmanifestへ残す。対象が0件でも空manifestを確定し、全件照合後だけ
storeを `active` にする。中断後は同じ `import --source` を再実行し、同名異内容なら解決せず停止する。
旧marker（`schema_version: 1`）のstoreは新CLIで読み書きできない。旧CLIの実行を止め、
移行前後のmarkerとbindingを確認してから排他方式を移す。無検証でmarkerだけを書き換えない。

## 日常操作

保存前に `status` でbinding、marker、Git root、`store_id`、state、書込可否を確認する。
能力IDを知らない場合は引数なしの `list`、既知の能力を調べる場合は `list --capability` を使う。
0件と読取失敗は異なる結果であり、失敗を「記録なし」に読み替えない。

```bash
"$LEARNING_STORE" status
"$LEARNING_STORE" list
"$LEARNING_STORE" list --capability public-capability-id
"$LEARNING_STORE" record --input /absolute/path/to/abstracted-record.json
```

`record` の入力は公開可能な内容だけを持つJSONファイルである。同じID・同じ内容の再送は
`created: false`、異なる内容の再送は競合になる。訂正は現在の有効版を `supersedes` へ指定する。
複数末尾へ分岐した場合は、全末尾を指定した `record --resolve-conflict --input ...` だけを使い、
旧版を消さない。CLIは採点、Git commit、push、remote作成を行わない。

成功時に返るrecord IDと相対pathは**ファイル保存**の証拠である。**Git commit**と**remote反映**は
それぞれ別の状態として確認・報告する。commitする場合は新規対象ファイルだけをstageし、store内の
無関係なdirty差分を含めない。

保存に失敗した場合は、session内の演習と通常作業を続け、抽象化済みの記録案を会話へ返す。
元の作業repoやこの設定リポジトリへfallbackしない。

## 別マシンと移設

別マシンでは既存の専用storeを `clone` し、clone先へbindingを作る。再度 `init` や `import` はしない。

```bash
git clone <approved-remote> /absolute/path/to/learning-store
"$LEARNING_STORE" bind --repo /absolute/path/to/learning-store
"$LEARNING_STORE" status
```

最初のマシンと同じ `store_id` が返ることを確認する。既存bindingが別storeを指す場合は停止し、
意図的な切替時だけ `bind --replace-binding --repo ...` を使う。storeを移設した場合も同じ手順で
markerとGit rootを再検査してbindingだけを更新する。

## 旧記録の読み方

旧 `learning/entries/` の `result: hit|miss` は当時の結論一致だけを表す。hit率から習得、難易度、
保持を断定しない。`axis` や本文の判断基準も当時の形式と支援条件の範囲で読む。
旧コード記録も新schemaの独立成功へ変換しない。後日の関連実作業で本人が示した行動は、
新しいrecordとして専用storeへ保存する。

履歴の形式と設計経緯は次を参照する。

- `docs/adr/0001-learning-mode-prediction-format.md`: 自己生成、再出題、旧Predict形式
- `docs/adr/0007-learning-mode-decision-layer-gate.md`: 判断層と評価の限界
- `docs/adr/0012-code-learning-mode.md`: コード技能の証拠とteachの境界
- `docs/adr/0017-programming-learning-integration.md`: 専用store統合の決定

2026-07-01までの11件はPRIVATEな作業環境から抽象化して取り込んだ履歴である。
2026-08-09には `tasks/learning-journal.md` から1エントリ1ファイルへ移行した。
これらの履歴本文を新schemaへ合わせて改作しない。
