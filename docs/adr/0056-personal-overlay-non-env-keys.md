---
adr: 56
date: 2026-11-19
status: accepted
---

# 個人プロファイルのoverlayに、`env` 以外のキーも通す

## 背景

解く問題: 会社のgatewayで追加したモデル（OpenAI系など）を、`/model` で選べるようにする。
ただし、会社プロファイル（`claude`）だけに出し、個人プロファイル（`ccp`）では出さない。

追加モデルは、ホストの `~/.claude/settings.json` の `modelPicker` に手で書いてあった。
コンテナの `settings.json` は `settings.json.template` から作られるので、コンテナでは選べなかった。

一次資料（settings）で確認した仕様は次のとおり。

- `modelPicker` は `{"options": [{"model": ..., "label": ...}], "replaceBuiltInOptions": ...}` のobjectである
- 設定ファイルをまたいでマージされない。managed・`--settings`・userのうち、定義している最も優先度の高いファイルの値がまるごと使われる。
  `ccp` は `--settings ~/.claude/settings.personal.json` で起動するので、overlayに書いた値が会社用の値に勝つ
- `replaceBuiltInOptions` を付けなければ、行は組み込みの一覧の後ろに足される。有効な行が無ければ、組み込みの一覧だけになる
  （settings-referenceの記述。空配列を明示した場合の挙動は書かれていないので、`ccp` の `/model` で確かめる）

overlayを生成するコードは2か所ある。コンテナ側（cw-workspace-local の `claude_snapshot.py`）は、
`env.json.template` をまるごと写して `env` だけを空にする。ホスト側（`setup.sh` の `prepare_claude_files`）は、
`{"env": {...}}` だけを組み立てていた。両者で扱いがずれていた。

## 決定

- 会社用の `modelPicker` は `settings.json.template` に書く。このrepoは公開されているが、それを承知のうえで利用者が決めた（2026-11-19）
- 個人用は `env.json.template` に `"modelPicker": {"options": []}` を書き、会社用の一覧を打ち消す
- `setup.sh` は、`env.json.template` の `env` 以外のトップレベルのキーを、`settings.personal.json` にそのまま書く。
  会社の `settings.json` へは今までどおり `env` だけを写す
- `modelSettings` は今回は扱わない（利用者の判断）

## 却下した案

### A. 個人用の `settings.personal.json.template` を別に作る

置き場は分かりやすくなるが、コンテナ側の生成は `env.json.template` を写す作りになっている。
別ファイルにすると、cw-workspace-local 側の変更も要る。コンテナ側の扱いにホスト側を合わせる方が、変更が小さい。

### B. 個人用にもClaudeのモデル一覧を手で書く

組み込みの一覧に戻せるなら、手で持つ必要は無い。新しいモデルが出るたびに、個人用の一覧を直す手間も生じる。

### C. 会社用の一覧を、gitで追跡しない別ファイルに置く

社内のモデル構成を公開repoに載せずに済む。ただし、ホストとコンテナの両方の生成処理に、新しい入力を足す必要がある。
利用者は、公開されることを承知のうえで、テンプレートに直接書く方を選んだ。

## 結果

- `env.json.template` が、認証情報のテンプレートに加えて「個人プロファイルだけの設定」も持つ。名前と役割が少しずれる
- `env.json.template` に置いたトップレベルのキーは、`.env` が無いマシンでも個人overlayに入る（overlayは常に生成される）
- `modelPicker` の行をすべて打ち消せないバージョンや仕様変更があると、`ccp` に会社のモデルが出る。`/model` を見れば気づける
- 会社のモデルを選べても、`ANTHROPIC_BASE_URL` が指すgatewayが対応していなければ使えない。これはこのADRの範囲外

## 根拠

- https://code.claude.com/docs/en/settings （「Lists merge instead of overriding」の節。2026-11-19に取得）
- https://code.claude.com/docs/en/settings-reference （`modelPicker` の節。2026-11-19に取得。抜粋の要約で読んだ）
