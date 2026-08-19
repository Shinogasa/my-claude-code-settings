---
adr: 2
date: 2026-08-18
status: superseded by 0003
---

# 共有ポリシーをホスト別アダプターで発火させる

## 背景

このリポジトリは Claude Code と Codex CLI の設定を単一ソースから配る。
skills や指示本文は共有できる一方、commands、rules、agents、hooks、plugins、settings は
形式だけでなく実行契約も異なる。

2026-08-18 の監査では次を確認した。

- 20 skills の大半は共有できるが、Claude 固有ツール名を含むものがある
- 12 commands のうち8件は Codex skill へ変換済み。Codex custom prompts 自体は deprecated
- 8 agents は TOML へ変換済みだが、tool allowlist と model alias の情報を失う
- リポジトリ管理 hook はスクリプトを共有できるが、定義と trust はホスト別である
- Claude から自動移行されたプラグインが Codex 側で独立して enabled 状態を持つ
- `security-guidance` 2.0.7 は Claude 固有の非同期 hook 契約により Codex SessionStart で失敗する
- リポジトリ直下 `AGENTS.md` と、`CLAUDE.md → ~/.codex/AGENTS.md` が重複し、内容も矛盾している

同じファイルを読めることと、同じ意味で安全に動くことは別である。全資産を symlink すると、
未対応フィールドが黙って無視されるか、hook のようにセッション全体へエラーを出す。

## 決定

**ポリシーと知識を共有正本に置き、発火方法と実行契約はホスト別アダプターに置く。**

共有正本に置くもの:

- ホスト非依存の skills、規約本文、ドメイン知識
- host-neutral に書ける subagent の developer instructions
- JSON stdin を受ける hook の判定ロジック。ただしイベント出力を共有できる場合に限る

ホスト別アダプターに置くもの:

- Claude `settings.json.template` と Codex の config / setup 操作
- Claude commands と Codex skills
- Claude agent Markdown と生成した Codex agent TOML
- Claude `settings.json` hooks と `codex/hooks.json`
- statusline、output style、plugin manifest、有効化状態

Codex の plugin 有効化は **allowlist** で管理する。Claude Code から `/import` されたこと、
cache に実体があること、Claude 側で enabled であることは、Codex での実行許可とみなさない。
cache は削除せず、有効化状態を止める。

現時点の扱いを次のように固定する。

- `superpowers@openai-curated` は Codex native として有効にする
- `learning-output-style` は Codex 0.147.0 の SessionStart で動作を観測済みのため有効候補とする
- `security-guidance@claude-plugins-official` は Codex 側で無効にする
- MCP / skill を持つ Claude 由来プラグインは代表操作の smoke test 後に allowlist へ加える
- command しか持たない Claude 由来プラグインは Codex native 機能または skill へ置換する

互換性の根拠は次の順で採用する。

1. 対象バージョンの公式資料
2. ローカル CLI の `--help` と最小実機検証
3. 固定した best-practice submodule

plugin cache を直接 patch しない。必要な変更は、このリポジトリの adapter または upstream で行う。

## 検討した代替案

### A. 全資産を同じディレクトリへ symlink する

採らない。skills のように共通形式のものには有効だが、Codex custom prompts の廃止予定、
Codex Starlark rules、agent TOML、hook 非同期契約、plugin enabled 状態の差を表現できない。
「リンクはあるが機能しない」という静かな失敗を増やす。

### B. Claude Code 用と Codex 用を完全に別リポジトリ・別ツリーで管理する

採らない。ドメイン skills、規約本文、subagent instructions の重複が増え、片側だけ直す
ドリフトが恒常化する。差が必要なのは発火境界であり、内容全体ではない。

### C. `/import` の自動変換を正本とする

採らない。import は既存設定を消さず、plugin の enabled 状態と cache をマシンローカルに残す。
変換結果のバージョン管理、レビュー、再現性が不足し、Claude 側の無効化も Codex へ伝播しない。

### D. 非互換な Claude plugin の cache を直接修正する

採らない。marketplace update で上書きされ、trust 対象の upstream コードとローカル改変の境界が
見えなくなる。特に security hook は安全機構なので、出所不明な差分を cache に持たない。

### E. Claude 由来の全 plugin を Codex で無効にする

採らない。`learning-output-style` のように互換環境変数と標準 hook output だけで動くもの、
`.mcp.json` や skills を再利用できるものまで捨てる。plugin 単位の allowlist で同じ安全性を
より小さい損失で得られる。

### F. `security-guidance` をエラーが出ても有効のままにする

採らない。内容が有用でも、SessionStart の invalid output は毎セッションの信頼性を落とす。
決定的 pattern check、明示的 security skill、非同期 LLM review を分け、Codex 契約へ移植してから
再度有効化する。

## 結果

良くなること:

- 共有できる知識は一箇所で保守し続けられる
- ホスト差が adapter に集まり、silent no-op と startup error を検査しやすくなる
- `/import` や cache の存在と、実際の実行許可を分離できる
- Codex 専用マシンでも、Claude 設定を前提にせず setup できる設計へ進められる

諦めること・コスト:

- 形式の違う資産には生成物とドリフトテストが必要になる
- plugin ごとの smoke test とバージョン追随が必要になる
- 同じ名前の機能でも、ホストごとの実装差を明記する必要がある

既知のリスク:

- Codex plugin enabled 状態は認証情報を含むローカル `config.toml` にあり、リポジトリだけでは
  完全再現できない。setup は差分を表示し、ユーザーが明示無効化した状態を上書きしない
- hooks は trust 未承認時に skip される。配置テストとは別に trust の運用確認が必要
- Codex agent の runtime 適用は未検証。生成整合性テストだけで完了扱いにしない

## 根拠

- [Codex Hooks](https://learn.chatgpt.com/docs/hooks)
- [Codex Custom Prompts](https://learn.chatgpt.com/docs/custom-prompts)
- [Codex Rules](https://learn.chatgpt.com/docs/agent-configuration/rules)
- [Codex Import](https://learn.chatgpt.com/docs/import)
- [Codex Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Codex Skills](https://developers.openai.com/plugins/concepts/skills)
- [互換性監査](../codex-compatibility-audit.md)
