---
adr: 4
date: 2026-08-20
status: accepted
---

# Codexの起動時規約とセキュリティレビューを段階的に強制する

## 背景

`superpowers@openai-api-curated` v1e285826 はCodex向けskillを配るが、manifestは`skills`だけを宣言し、
配布物に`hooks/`を含まない。`AGENTS.md`の散文指示による`using-superpowers`読込は1ターンで
観測できたものの、読み忘れを検知できない。Claude由来の`security-guidance`はCodexと異なる
SessionStart出力契約で失敗するため、ADR 0003でCodex側をdenyにした。

セキュリティ検査は、既知パターンの決定的検査を常時行い、意味的なLLMレビューは必要な差分だけへ
限定する方針まで決まっている。Codex用`security-reviewer`は軽量な`gpt-5.6-luna`へ生成済みである。

## 決定

- `superpowers@openai-api-curated`を維持し、リポジトリ管理のCodexネイティブ`SessionStart` hookで
  `superpowers:using-superpowers`の読込指示を追加developer contextとして注入する。
- hookは`startup`、`resume`、`clear`、`compact`を対象にし、Codex公式契約の平文stdoutを使う。
- セキュリティ境界は、認証・認可、ユーザー入力、API、ファイルアップロード、秘密情報、決済、
  raw SQL、暗号、外部連携、権限・デプロイ設定を含む。
- 差分の決定的分類は毎回行うが、LLMは境界に一致した場合だけ`security-reviewer`
  (`gpt-5.6-luna`)を起動する。通常の変更ではLLMレビューを起動しない。
- 軽量レビューが重大な懸念または判断不能を返した場合、上位モデルを自動起動せず、人間へ確認する。
- 非managed hookの信頼承認はsetupの責務に含めず、配置後に`/hooks`で承認するよう警告する。

## 検討した代替案

### A. `AGENTS.md`の散文指示だけを維持する

採らない。現在の観測では読めているが、モデル判断へ依存し、読まれなかったことを検知できない。

### B. Claude版superpowers pluginを再導入する

採らない。Codex向け配布物との重複が戻り、ADR 0003のnative-firstなdefault denyと衝突する。

### C. すべての変更でLLMセキュリティレビューを行う

採らない。通常変更まで推論コストと待ち時間を増やし、決定的検査と意味レビューの責務も曖昧になる。

### D. セキュリティレビューを都度の人間判断だけにする

採らない。認可漏れや入力境界の変更を見落とした場合、レビュー自体が発火しない。

### E. 軽量レビューから上位モデルへ自動エスカレーションする

採らない。コストの高い推論を利用者の認識なしに開始する。重大所見または判断不能を表示し、
上位モデルを使うかは人間が決める。

## 結果

良くなること:

- Codex版superpowers pluginを単一のskill正本として保ちつつ、セッション開始時の読込経路を機構化できる
- セキュリティ境界を広く扱いながら、LLMコストは該当差分に限定できる
- 高コストモデルの利用に人間の明示判断が残る

諦めること・既知のリスク:

- hookは初回配置時と定義変更時に信頼承認が必要で、未承認ならスキップされる
- 差分分類には偽陽性と偽陰性があり、軽量モデルは複数ファイルをまたぐ脆弱性を見逃しうる
- 人間が上位レビューを拒否または後回しにした場合、軽量レビュー以上の保証は得られない

## 根拠

- OpenAI Docs: https://developers.openai.com/codex/hooks
- OpenAI Docs: https://developers.openai.com/codex/subagents
- `docs/adr/0003-codex-native-first-activation-policy.md`
- `codex/agents/security-reviewer.toml`
- `learning/entries/2026-08-18-セキュリティ検査をどこまで自動化するか.md`
