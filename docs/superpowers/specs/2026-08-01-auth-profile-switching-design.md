# 認証プロファイル切り替え設計（`claude` = 会社 / `ccp` = 個人）

## 背景

会社PCという単一マシン上で、Claude Code の接続先を2種類使い分けたい。

- 会社の業務 → LiteLLM プロキシ経由（`ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN`）
- 個人の作業 → 個人 Anthropic アカウント（Pro プランの OAuth/keychain 認証）

本リポジトリは既に `.env` の有無で両者を切り替える仕組み（`setup.sh` + `env.json.template`）を
持つが、これは**マシン単位で `setup.sh` を1回実行して固定**する方式であり、
`~/.claude/settings.json` に実際の URL/トークンが焼き込まれる。同一マシン上での動的な
切り替えはできない。

## 制約・前提の確認結果（実機検証済み: Claude Code v2.1.220 / macOS）

### 1. `--settings` による env 注入は成立する

```bash
claude --settings '{"env":{"ANTHROPIC_BASE_URL":"http://127.0.0.1:9","ANTHROPIC_AUTH_TOKEN":"dummy"}}' auth status
# → {"loggedIn": true, "authMethod": "oauth_token", "apiProvider": "firstParty"}
```

ベースライン（`--settings` なし）は `authMethod: "claude.ai"` + `email`/`orgId`/`subscriptionType` が
付く。シェル環境変数を一切変えずに認証方式が切り替わったため、`--settings` の `env` ブロックが
プロセス環境へ注入されているのは確定。

### 2. 空文字列 `""` は「未設定」として扱われ、上位の env を無効化できる

```bash
ANTHROPIC_BASE_URL=http://127.0.0.1:9 ANTHROPIC_AUTH_TOKEN=dummy \
  claude --settings '{"env":{"ANTHROPIC_BASE_URL":"","ANTHROPIC_AUTH_TOKEN":""}}' -p 'say OK'
# → 正常応答、終了コード 0。auth status も claude.ai + email に復帰
```

→ **これが本設計の技術的な土台**。既存の `~/.claude/settings.json` に手を触れずに無効化できる。

### 3. 現在の接続先を判定する手段

`claude auth status` は既定で JSON を出力する。

| 状態 | `authMethod` | 付随フィールド |
|---|---|---|
| 個人アカウント | `"claude.ai"` | `email` / `orgId` / `subscriptionType` が**出る** |
| LiteLLM 経由 | `"oauth_token"` | 上記フィールドが**消える** |

### 4. `--settings` はサブコマンドより前に置く

`claude --settings <X> auth status` は正しくパースされ、サブコマンド側も注入された env を読む
（`claude doctor` が `ANTHROPIC_BASE_URL is set and does not point at api.anthropic.com` と報告する）。

### 5. 未検証事項

上記2は「シェル環境変数 vs `--settings`」で実証した。「`~/.claude/settings.json` の env vs
`--settings`」は未実測（検証機に `.env` が無いため再現できなかった）。settings 階層上
CLI 引数（優先度2）は user settings（優先度5）より上位なので成立する見込みだが、
会社PCでの確認を要する。

## 設計

### 採用方式: 「既定は会社のまま、個人用コマンドを追加する」

`~/.claude/settings.json` には**一切手を触れない**。個人用コマンド `ccp` だけを新設し、
起動時に `--settings` で認証系 env を空文字列に上書きして無効化する。

```
claude   → 素の起動 → ~/.claude/settings.json の env が効く       → LiteLLM（会社）
ccp      → claude --settings ~/.claude/settings.personal.json   → 個人アカウント
```

### なぜこの向きか（逆方向を採らない理由）

「`settings.json` から認証 env を抜き、会社用のときだけ `--settings` で注入する」逆方向の
設計も技術的には成立する。しかし**障害モードが危険**：

| 方式 | シェル統合が読み込まれなかったとき |
|---|---|
| 逆方向（`claude` にラッパー必須） | `claude` が黙って個人アカウントで動く → 会社のコードが個人契約に流れる。無言の事故 |
| **採用方式**（`claude` は素のまま） | `ccp: command not found` → 即座に気づく |

加えて採用方式は既存の会社PC設定を変更しないため、`CLAUDE.md` の「影響を最小化する」に沿う。

### `settings.personal.json` のキーは `env.json.template` から導出する

無効化すべきキーを手書きの第2テンプレートに持たせると、`env.json.template` にキーを足したとき
無効化漏れが起きる。`setup.sh` が `env.json.template` のキー集合を読み、全て `""` にした
`env` ブロックを生成することで、この drift を構造的に防ぐ。

### statusline にプロファイル表示を出す

`statusline.js` は既に `process.env.ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` を読んでいる
（`getLitellmBudget()`）。同じ判定条件で `🏢WORK` / `🏠PERSONAL` を Line 1 に常時表示する。

**どちらの状態でも必ず表示する**のが要点。印の「不在」は見落とすが、`🏠PERSONAL` の明示は
見落とさない。設定ミスで意図しない接続先になっていても常に目に入る。

## 実装対象

| ファイル | 変更 |
|---|---|
| `bin/ccp` | 新規（755）。設定欠損時に fail loud |
| `setup.sh` | `TARGETS` に `bin/` / `settings.personal.json` 生成 / PATH 案内 |
| `statusline.js` | `formatProfile()` 追加 + `buildEnvLine` に1行 |
| `README.md` | 新セクション + 既存記述の改訂 |
| `~/.claude/settings.json` | **変更しない** |

## フォールバック（未検証事項5が不成立だった場合）

`--settings` が user settings の env に勝てないなら設計を反転させる。`setup.sh` が LiteLLM env を
`~/.claude/settings.json` ではなく `~/.claude/settings.litellm.json` に書き出し、会社用も
`bin/ccw` 経由の `--settings` 注入にする。この場合 `claude` を素で叩くと個人アカウントに
落ちるため、statusline のプロファイル表示が事故検知の生命線になる。
