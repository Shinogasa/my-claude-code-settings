# Backlog

着手していない課題の置き場。`todo.md`（実行中のタスク1件・使い捨て）とは役割が違う。

- 着手したら `todo.md` へ移して展開する
- 完了したらここから消す（履歴は git に残る）
- 判断待ちの項目は「決めること」を明記する。作業内容だけ書くと放置される

---

## Codex CLI 対応の続き

### `agents/` を Codex 向けに移植する

Claude Code は Markdown + frontmatter、Codex は `config.toml` の `[agents]` / `.codex/agents/` で
TOML 定義。8ファイルの書き直しが必要。

**保留理由**: Codex 側のサブエージェント粒度が固まっていない。先に移植すると使わない設定が残る。
**着手条件**: Codex でサブエージェントを実際に使う場面が出てきたとき。

### `hooks/` を Codex に配線する

`guard-dangerous-bash.py` のロジック本体は流用できる見込み。イベント名（`PreToolUse` 等）は
Claude Code と共通。配線先が `settings.json` → `config.toml` / `hooks.json` に変わる。

**未検証**: フックが受け取る標準入力の payload キー。Claude Code は `tool_input.command`。
Codex が同じキーかは実機で確認が必要。ここが違うと**フックは起動するがコマンドを読めず、
何もブロックしないまま正常終了する**（危険コマンド防御が黙って無効化される）。

**着手条件**: Codex で破壊的コマンドを扱う作業が発生する前。

### `setup.sh` が Codex 専用マシンで動かない

`~/.claude` がないと `exit 1` する。現状そのようなマシンはないため見送り。

---

## 学習モード

### 段階2（間隔反復出題）の導入可否を決める

`learning-journal.md` のエントリが20件条件を達成した。SessionStart hook で `[MISS]` 付きの
エントリを優先的に再出題する仕組みを入れるか、見送るかを判断する。

**決めること**: 導入する / 見送る。見送るなら理由を journal 冒頭のチェックポイントに書き残す
（判断せずに追記だけ続けると条件が形骸化する）。

---

## エージェント生成物の git 管理

### 個人導入プラグインの生成物を無視する仕組み → dotfiles へ移管済み

superpowers の生成物（`docs/superpowers/` `.superpowers/`）を `~/project/` 配下で
コミットさせない件。グローバル無視の実体は dotfiles リポジトリが持っているため
（`config/git/ignore` → `~/.config/git/ignore`）、**このリポジトリの管轄ではない**。

調査結果・選択肢・検証済みの制約は dotfiles 側の `tasks/backlog.md` に記載した。

**このリポジトリ自身は対象外**: `docs/superpowers/` の5ファイルは設計履歴として意図的に
tracked にしてある。gitignore は tracked ファイルに効かないため、無視設定を足しても影響はない。
