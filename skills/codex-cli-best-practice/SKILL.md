---
name: codex-cli-best-practice
description: Use when creating, changing, or reviewing Codex configuration (AGENTS.md, skills, agents, hooks, plugins, MCP, rules, config.toml), or when investigating and proving absence.
---

# Codex CLI ベストプラクティス

Codex設定の仕様と実際の挙動を、次の優先順位で確認する。

1. **OpenAI公式ドキュメント**を一次資料として読む。
2. **ローカルにインストールされたCLIのヘルプと実測**で、使用中のバージョンの挙動を確認する。
3. 次のいずれかに該当するときだけ、**固定したcodex-cli-best-practice submodule**を補助資料として読む。
   - 設定例や運用例を求められたとき
   - plugin、skill、新機能、運用パターンの候補を比較するとき
   - 公式資料とローカルCLIの実測だけでは、必要な設計判断の材料が揃わないとき

通常の仕様・動作確認は、公式資料とローカルCLIの実測で完結させる。

固定submoduleは一般的なコミュニティ資料と同列に扱わず、再現可能な補助資料として参照する。
ただし、現在のOpenAI公式ドキュメントやローカルで観測したruntimeの挙動を上書きしてはならない。

## 対象

- 指示: `AGENTS.md`、`rules`
- 拡張: `skills`、`agents`、`hooks`、`plugins`、`MCP`
- 設定: `config.toml`
- 不在の報告: `rules/proving-absence.md`に従い、主張・探索範囲・範囲の根拠・反証条件を示す
