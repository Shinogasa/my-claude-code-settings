# Codex project guidance

グローバル指示は ~/.codex/AGENTS.md から読み込まれる。
このファイルには、この設定リポジトリで必要なCodex差分だけを書く。

- Codex設定の変更・レビューでは codex-cli-best-practice skillを読む
- 根拠はOpenAI公式資料、ローカルCLI実測、固定submoduleの順で採る
- Claude由来資産は docs/adr/0003-codex-native-first-activation-policy.md に従う
- runtimeの強制境界は docs/adr/0004-codex-runtime-enforcement-policy.md に従う
