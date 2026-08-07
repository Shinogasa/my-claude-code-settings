# Codex CLI への superpowers 導入設計

## 背景

Claude Code 側では superpowers を公式マーケットプレイス経由で導入済み
（`settings.json.template` の `enabledPlugins` に `superpowers@claude-plugins-official`）。
同じ methodology を Codex CLI 側でも使えるようにする。

本リポジトリは skills / commands / rules / CLAUDE.md を単一ソースで両ホストへリンクする
構成を取っているため、superpowers についても「どこまでをリポジトリ管理下に置くか」を
先に決める必要がある。

## 調査結果（実機検証済み・Codex CLI 0.146.0）

### 1. 非対話インストールが可能

upstream の README は `/plugins` の対話 UI を案内しているが、CLI サブコマンドが存在する。

```bash
codex plugin add superpowers@openai-curated
```

`openai-curated` は Codex が自前で同期するスナップショット（`codex plugin marketplace list`
に自動で現れる。`config.toml` への marketplace 登録は不要）。したがってこのセレクタは
Codex CLI が入っているマシンなら追加設定なしで解決できる。

`codex plugin list --json` は `installed[]` / `available[]` を返し、各要素が `pluginId`
（例 `superpowers@openai-curated`）を持つ。冪等判定にはこれを使う。

### 2. Codex 版 superpowers は hook を同梱していない（本設計の中心的な制約）

Claude Code 版 superpowers は SessionStart hook で `using-superpowers` スキルの全文を
セッション冒頭に注入し、これがスキル群の発火起点になっている。Codex 版にはこれが無い。

Codex のプラグイン hook 機構自体は存在する。ただし `plugin.json` のキーではなく、
**プラグイン直下の `hooks.json`** という別ファイルで定義する（スキーマは Claude Code と同形）。

```json
{ "hooks": { "PostToolUse": [ { "matcher": "Write|Edit",
  "hooks": [ { "type": "command", "command": "./scripts/..." } ] } ] } }
```

マーケットプレイススナップショット全体を走査した結果:

- `hooks.json` を持つプラグイン: `figma` `replayio`（実在する。機構は生きている）
- `plugin.json` に `hooks` 系キーを持つプラグイン: **ゼロ**（定義場所が別ファイルのため）
- `superpowers` の導入実体（`~/.codex/plugins/cache/openai-curated/superpowers/<hash>/`）:
  `skills/` `assets/` `.codex-plugin/` のみ。**`hooks.json` は無い**

つまり「Codex に hook 機構が無い」のではなく「**superpowers の Codex 配布物が hook を
使っていない**」。結論は変わらず、14 個の skills は「インデックスに載るだけ」になる。

**インストールしただけでは実質的に使われない。** 発火の配線を別途用意する必要がある。

なお hook を自前で足す道は取らない。プラグインキャッシュは Codex が管理する領域で、
更新時に上書きされるうえ、hook の実行には信頼承認が要る。リポジトリが保持できる状態でもない。

### 3. バージョン差

| ホスト | マーケットプレイス | バージョン |
|---|---|---|
| Claude Code | `claude-plugins-official` | 6.2.0 |
| Codex CLI | `openai-curated` | 5.1.3 |

skills のディレクトリ構成は 14 個で一致している。ワークフロー手順の細部に差がある可能性は
あるが、本タスクでは追随しない（upstream の更新に任せる）。

### 4. 既存 skills との名前衝突は無い

本リポジトリの `skills/`（12 個）と superpowers の `skills/`（14 個）に同名は存在しない。
`~/.agents/skills` と plugin cache の同居による解決順の問題は発生しない。

### 5. `~/.codex/config.toml` はリポジトリ管理下に置けない

`codex plugin add` の書き込み先は `~/.codex/config.toml` だが、このファイルには
モデルプロバイダの認証ヘッダが平文で含まれる。本リポジトリは PUBLIC のため、
シンボリックリンク管理・テンプレート生成のいずれの対象にもしない。

→ プラグイン導入は「リポジトリが状態を保持する」のではなく
「`setup.sh` が冪等なコマンドを叩く」形にする。

## 設計判断: 発火の配線をどこに置くか

調査結果 2 により、何らかの形で「Codex では自分でスキルを読め」と指示する必要がある。

### 採用: `CLAUDE.md` にホスト別併記の節を追加

`CLAUDE.md` は `~/.claude/CLAUDE.md` と `~/.codex/AGENTS.md` の両方へリンクされている。
ここに 1 節足せば、Codex は毎セッション読む。

同ファイルは既に「依存する場合はホスト別に併記する」という方針を掲げ、`rules/...` の
解決先を 2 行の表で書き分けている。superpowers の節も同じイディオムに揃える。

Claude Code 側にも同じ節が載るが、増分は約 230 文字（≈ 180 tokens）。
`CLAUDE.md` + `rules/*.md` + hook 注入分で既に約 24 KB が常時ロードされているため、
相対増は 2% 程度に収まる。ホスト別の表形式にすることで「この行は自分に該当しない」と
判別でき、指示の矛盾としては働かない。

### 却下 A: `~/.codex/AGENTS.md` を `CLAUDE.md` から切り離して個別管理

ホスト固有の差分を正面から書けるが、単一ソース原則を恒久的に壊す。
`CLAUDE.md` の更新が Codex へ届かなくなる事故を、以後ずっと抱え込むことになる。

### 却下 B: `setup.sh` で `AGENTS.md` を「`CLAUDE.md` + Codex 用追記」の連結生成物にする

Claude Code 側の増分を literally ゼロにできる唯一の案。単一ソースも形式上は保たれる。

しかしシンボリックリンクをやめた時点で、`CLAUDE.md` を編集しても `setup.sh` を再実行するまで
Codex 側へ反映されなくなる。Claude Code は即時反映されるため、両ホストの指示が
**エラーを出さずに食い違う**。180 tokens と引き換えに払うコストとして見合わない。

### 却下 C: インストールのみ行い、発火はユーザーの都度指定に任せる

追加実装ゼロだが、調査結果 2 の通り 14 個の skills がほぼ死蔵される。導入の目的を満たさない。

## 変更内容

### `setup.sh`

シンボリックリンクのループ完了後、`settings.json` 生成セクションより前に、独立した関数
`setup_codex_plugins` として追加する（既存の `setup_git_hooks` と同じ構成）。

冒頭の Codex 検出ブロック（`TARGETS` を伸ばす箇所）には入れない。あそこはリンク定義を
組み立てるだけの場所で、副作用のある外部コマンド実行を混ぜると責務が濁るため。

- 実行条件: `~/.codex` が存在し、かつ `codex` が PATH にあること。
  どちらか欠ける場合は警告を出してスキップする（`setup.sh` の主責務はリンク作成であり、
  プラグイン導入の失敗で全体を止めない）
- 冪等性: `codex plugin list --json` の `installed[]` に `superpowers@openai-curated` が
  含まれていればスキップ。`codex plugin add` を無条件に叩かないのは、既導入時の終了コードが
  未確認で `set -euo pipefail` 下では全体停止のリスクがあるため
- 導入済みかつユーザーが `enabled = false` にしている場合も `installed[]` には現れるため
  スキップされる。ユーザーの明示的な無効化を `setup.sh` が握り潰さない挙動になる

### `CLAUDE.md`

`### このファイル内の rules/... の解決先` の直後に、以下の節を追加する。
ホスト差分の記述をファイル内で隣接させる。

```md
## superpowers

skills の発火方式がホストで異なる。

| ホスト | 発火方式 |
|---|---|
| Claude Code | プラグインの SessionStart hook が `using-superpowers` を自動注入する。追加操作は不要 |
| Codex CLI | hook 機構が無い。**応答を始める前に `superpowers:using-superpowers` を自分で読むこと** |
```

### `README.md`

Codex CLI 対応セクションに、プラグイン導入が `setup.sh` の管轄に入ったことと、
hook 差分により発火方式が異なることを追記する。

## 検証手順

1. `bash setup.sh` を実行し、プラグイン導入セクションが成功終了すること
2. `codex plugin list --json` の `installed[]` に `pluginId: "superpowers@openai-curated"` が
   現れること
3. `bash setup.sh` を再実行し、2 回目が「導入済み」としてスキップされること（冪等）
4. `grep -c superpowers ~/.codex/AGENTS.md` が 1 以上を返すこと（リンク経由で節が届いている）
5. `~/.codex/plugins/cache/openai-curated/superpowers/<hash>/skills/` に skills が
   展開されていること（Codex がスキャンする位置に実体があることの確認）

### 検証結果（2026-08-05 実施）

1〜5 すべて通過。5 は当初 `codex exec` による実機 1 ターンで確認する手順にしていたが、
LLM ゲートウェイの予算上限超過（HTTP 429）で実行できず、展開先の構造確認に差し替えた。
本変更とは無関係な外部要因のため、実機ターンでの動作確認は予算回復後の宿題として残る。

## スコープ外

- Codex 版（5.1.3）と Claude Code 版（6.2.0）のバージョン差の解消。upstream の更新に任せる
- `~/.codex/config.toml` 自体のリポジトリ管理。認証情報を含むため対象外
- Codex 用の agents / hooks / output-styles の移植。形式が異なるため従来通り対象外
