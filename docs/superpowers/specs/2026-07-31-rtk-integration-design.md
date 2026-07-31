# rtk導入設計（Claude Code連携側）

## 背景

トークン節約のため、コマンド出力圧縮CLIの [rtk](https://github.com/rtk-ai/rtk) を導入する。
dotfilesリポジトリ側では Homebrew インストール定義（`Brewfile`）と設定ファイル
（`config/rtk/config.toml` → `~/.config/rtk/config.toml`）の管理を完了済み（2026-07-31）。

Claude Codeのフック登録（`rtk init -g`）は本リポジトリ（`my-claude-code-settings`）側で扱う。
headroom（コンテキスト圧縮ツール）の導入は、既存の `ANTHROPIC_BASE_URL`（独自LLMゲートウェイ
経由）との衝突リスクが未検証のため、別タスクとして先送りする。

## 制約・前提の確認結果

### 1. `settings.json` の生成方式との競合

`rtk init -g`（フルモード）は `~/.claude/settings.json` を直接書き換える設計だが、本リポジトリの
`setup.sh` は `settings.json.template` + `.env` から毎回**再生成**する運用のため、直接書き込み方式は
再生成時に消える。

→ **対応**: `rtk init -g` の直接書き込み機能は使わず、生成されるべきフック定義を
`settings.json.template` に静的に記載し、テンプレートを唯一の管理元とする。

### 2. 実際に生成されるフック内容（実機検証済み）

`rtk init -g --hook-only`（dry-run、`~/.claude/settings.json` は変更されないことを確認済み）を
実行し、rtk 0.44.1 で生成される内容を確認した：

```json
{
  "hooks": { "PreToolUse": [{
    "matcher": "Bash",
    "hooks": [{ "type": "command",
      "command": "rtk hook claude"
    }]
  }]}
}
```

Web上の情報には旧バージョンの `rtk-rewrite.sh` 経由方式の記述もあったが、現行バージョンでは
`rtk hook claude` という直接コマンド実行方式に変わっている。バージョン差異があるため、
実機確認を経て転記する方針が正しかった。

### 3. 既存の `guard-dangerous-bash.sh` フックとの関係

`settings.json.template` には既に `PreToolUse` + `matcher: "Bash"` の危険コマンドブロックフック
（`guard-dangerous-bash.sh`）が登録済み。rtkのフックも同じ `matcher: "Bash"` に登録されるため、
以下を確認した。

- Claude Codeの公式ドキュメントにより、同一matcherにマッチする複数のPreToolUseフックは
  **並列実行**され、各フックは**常に元の（他フックによる書き換え前の）tool_input**を受け取る
- そのためrtkによるコマンド書き換え（例: `git push --force` → `rtk git push --force`のような
  `updatedInput`)が、`guard-dangerous-bash.sh` の危険コマンド判定をすり抜けさせる懸念はない
  （判定は常に元のコマンド文字列に対して行われる）
- deny（block）とallow（updatedInput）が競合した場合の最終的な優先順位は、公式ドキュメントの
  参照範囲内では明示的な確認が取れなかったが、一般的な権限システムの設計原則としてdenyが
  優先されると想定する

→ **対応**: 両フックは`PreToolUse.hooks`配列内で別々のブロック（別のmatcherエントリ）として
並記し、関心を分離する。将来的にheadroom等のフックを追加/削除する際に、既存フックへの影響を
最小化する。

## 変更内容

### `settings.json.template`

`hooks.PreToolUse` 配列に、確認済みのrtkフックブロックを追加する（既存の
`guard-dangerous-bash.sh` ブロックは変更せずそのまま残す）。

### 導入手順

1. `brew install rtk`（dotfiles Brewfileには定義済み。`brew bundle install`は無関係な
   `kayac/tap`の信頼問題で失敗するため、rtk単体でインストールする）
2. `rtk init -g --hook-only` で生成内容を確認（実施済み、上記参照）
3. `settings.json.template` にフックエントリを追記
4. `bash setup.sh` を実行し `~/.claude/settings.json` を再生成
5. Claude Codeを再起動し、`rtk init --show` でフック有効化を確認
6. `README.md` のhooks説明を軽微に更新

## 既知の制約（todo.mdより引継ぎ）

- rtkのフックは `Bash` ツール呼び出しのみが対象。`Read`/`Grep`/`Glob` 等の組み込みツールは
  対象外のため、圧縮効果を得たい場面では `rtk read` / `rtk grep` / `rtk find` 等の明示利用を
  検討する

## スコープ外

- headroom導入は別タスクとして先送り（既存のANTHROPIC_BASE_URLとの衝突リスクが未検証のため）
- rtk/headroom同時利用時の重複圧縮検証もheadroom側タスクに含める
