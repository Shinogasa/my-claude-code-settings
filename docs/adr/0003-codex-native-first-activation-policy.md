---
adr: 3
date: 2026-08-18
status: accepted
---

# Codex移行をnative-firstなallowlistで管理する

## 背景

ADR 0002 は、共有する知識とホスト別の発火方法を分離し、Claude Code から Codex へ
流入したpluginをallowlistで管理すると決めた。ただし個別pluginの扱いは仮置きで、
`learning-output-style`を有効候補、MCPやskillを持つpluginをsmoke test候補としていた。

実機ではClaude marketplace由来の8 pluginを確認した。互換JSONを返せることと、Codexで
維持する価値があることは別である。`learning-output-style`はSessionStart注入には成功するが、
人間にコードを書かせる発火はモデル判断で、回数制限・OFF条件・実行記録がない。
一方、自前の`rules/learning-mode.md`には発火ゲート、上限、停止条件、学習記録がある。

また、自前の`commands/code-review.md`は2026-04-07にEverything Claude Codeから導入した
289行のcommandで、その後の更新はない。Codexにはローカル`/review`、GitHub Code Review、
GitHub Actionがあり、機械的検査はCIへ分離するのが公式方針である。

## 決定

ADR 0002のホスト別アダプター境界を維持し、Codex側は**native-firstなallowlist**にする。
Claude Codeからimportされたこと、cacheに存在すること、構文上動くことだけでは許可しない。
`claude-plugins-official` marketplaceはdefault denyとし、policyで明示的に`allow`したpluginだけを
有効化できる。別marketplaceの未登録pluginはこの移行policyの対象外とする。

Codex plugin policyを次のように固定する。

| plugin | 状態 | 理由 |
|---|---|---|
| `superpowers@openai-curated` | allow | Codex向け配布物で、skillsの利用を確認済み |
| `learning-output-style@claude-plugins-official` | deny | 自前学習モードと重複・競合する。コード参加だけ共有ruleへ統合する |
| `security-guidance@claude-plugins-official` | deny | Claude固有の非同期hook契約でSessionStartが失敗する |
| `claude-md-management@claude-plugins-official` | deny | `CLAUDE.md`だけを対象にし、Codexの`AGENTS.md`階層を扱わない |
| `asana@claude-plugins-official` | deny | Codexで使える構成要素を確認できない |
| `code-review@claude-plugins-official` | deny | Claude commandのみで、Codex標準reviewと重複する |
| `gopls-lsp@claude-plugins-official` | deny | Go開発上の具体的な不足が出ておらず、公開仕様でのruntime契約も未確認 |
| `atlassian@claude-plugins-official` | deny | Codexは `atlassian-http` を MCP として直接設定済みで、plugin版とは重複する |
| `context7@claude-plugins-official` | review | 有用候補だが、Codex向け候補を個別評価するまで導入しない |
| `serena@claude-plugins-official` | review | 有用候補だが、Codex向け候補を個別評価するまで導入しない |

`review`も実行許可ではない。代表操作・認証・エラー伝播・副作用を個別に確認し、
明示的に`allow`へ変更するまでCodexでは無効にする。無効化は`/plugins`のenabled切り替えで行い、
cacheとinstall記録は保持する。policyにない別marketplaceの個人pluginは勝手に変更・削除しない。

学習・レビュー・表示は次のように扱う。

- `learning-output-style`のうち、意味のある5〜10行を人間が実装する仕組みだけを
  `rules/learning-mode.md`へ統合する。既存の発火ゲート、最大2回、OFF条件、記録を共有する
- `★ Insight`は`★ Delta`と重複するため取り込まない。pluginは統合後に両ホストで無効にする
- `output-styles/`はCodexへ移行しない。`★ Review`は将来のレビュー訓練モードと合わせて再設計する
- Codex statuslineは当面公式デフォルトを使う。必要な不足が実務で観測されるまでadapterを作らない
- 自前`code-review` commandと`.claude/PRPs`成果物はCodexへ移行せず、標準`/review`、
  `verification-loop`、必要時の公式GitHub連携へ分離する
- ClaudeとCodexのpluginを自動同期しない。必要になったpluginだけ、その時点の候補を再評価する

Everything Claude Code由来の34資産は今回削除しない。Codex移行完了後に、Codex native機能、
Superpowers、他の共有ruleとの重複・競合・利用実績を別タスクで棚卸しする。

## 検討した代替案

### A. 構文上動くClaude pluginをCodexでも維持する

採らない。`learning-output-style`は注入成功と実際のコード参加が別で、既存学習モードの
ヒント禁止、回数上限、OFF条件と競合する。互換性だけでは運用価値を示せない。

### B. Claude pluginを一括importし、壊れたものだけ直す

採らない。enabled状態がホスト間で同期されず、cache修正は更新で消える。未検証pluginが
新しいSessionStartや外部接続を増やすため、問題発生後に止める方式では遅い。

### C. 各Claude pluginのCodex adapterを今すぐ作る

採らない。標準機能で代替できるreviewやstatuslineまで保守対象になり、実際の不足がない
`gopls-lsp`にもruntime契約を背負う。具体的な摩擦が出てから再選定する方が小さい。

### D. Claude由来pluginを将来もすべて禁止する

採らない。`context7`や`serena`のように有用性が見込まれるものまで永久に除外する必要はない。
`review`で停止し、Codex向け候補を含めて個別評価できる余地を残す。

### E. 自前code-reviewを共有skillへ移植する

採らない。意味レビューはCodex標準機能、決定的検査はCIと`verification-loop`、PR投稿は
公式GitHub連携で分担できる。289行の外部テンプレートを複製する追加価値がない。

## 結果

良くなること:

- Codexで未検証のClaude pluginが暗黙に起動しなくなる
- `claude-plugins-official`に将来pluginが追加されても、明示allowまではfail-closedになる
- 標準機能と自前機能の責務が明確になり、同じ指示の二重注入を避けられる
- コード参加は学習モードの発火条件・上限・記録下で再現可能になる
- 後からpluginを導入するとき、具体的な不足と検証結果を根拠に選べる

諦めること・コスト:

- `context7`と`serena`は個別評価までCodexで利用しない
- Claude公式pluginの更新をそのまま享受せず、取り込んだコード参加ルールを自分で保守する
- 公式statuslineにない表示項目は当面表示しない

既知のリスク:

- 学習モードのコード参加は文章指示であり、発火遵守は引き続きモデル依存である。
  実装タスクで発火とスキップを観測し、ルールだけ置いて完了扱いにしない
- ECC由来資産の競合は未監査のまま残る。移行中は削除せず、別タスクで利用実績と代替を確認する
- policy外の個人pluginは監査対象外なので、組織・個人設定に別の実行経路があれば本判断を迂回しうる
- marketplace名が変わったClaude由来pluginはdefault deny境界から外れる。監査時は
  `marketplaceName`と`marketplaceSource`を記録し、新しい流入元をpolicyへ追加する

## 根拠

- [Codex Plugins](https://developers.openai.com/codex/plugins)
- [Package your plugin](https://developers.openai.com/codex/plugins/build)
- [Codex CLI developer commands](https://developers.openai.com/codex/cli/reference)
- [Codex Code Review](https://developers.openai.com/codex/app/review)
- [Review GitHub pull requests with Codex](https://developers.openai.com/codex/integrations/github)
- [Codex GitHub Action](https://developers.openai.com/codex/github-action)
- [互換性監査](../codex-compatibility-audit.md)
- `git show 0ca03372e3ecb09c00ffedb707dc819a4b664334`
