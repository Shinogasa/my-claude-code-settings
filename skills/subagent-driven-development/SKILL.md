---
name: subagent-driven-development
description: 実装計画の独立したタスクをサブエージェントで実行するとき使用する。タスクごとにフレッシュなサブエージェント + 2段階レビュー（spec compliance → code quality）で品質を担保する。
---

# Subagent-Driven Development

実装計画をタスクごとにサブエージェントで実行し、2段階レビューで品質を担保する。

**なぜサブエージェントか:** タスクごとにフレッシュなコンテキストで実行することで、コンテキスト汚染を防ぎ、メインセッションを調整作業に集中させる。

## When to Use

- 実装計画がある（plannerエージェントで作成済み）
- タスクが概ね独立している
- 同一セッション内で完結させたい

## Process

```
1. 計画を読み、全タスクのテキストとコンテキストを抽出する
2. TaskCreateで全タスクを登録する
3. タスクごとに以下を繰り返す:
   a. implementerサブエージェントをディスパッチ（./implementer-prompt.md）
   b. ステータスをハンドリング（下記参照）
   c. spec-reviewerサブエージェントをディスパッチ（./spec-reviewer-prompt.md）
   d. ✅になるまでフィードバック→再レビュー
   e. code-quality-reviewerサブエージェントをディスパッチ（./code-quality-reviewer-prompt.md）
   f. ✅になるまでフィードバック→再レビュー
   g. タスクを完了マーク
4. 全タスク完了後、最終コードレビューをディスパッチ
```

## Implementer Status Handling

| Status | Action |
|---|---|
| **DONE** | Spec compliance reviewへ進む |
| **DONE_WITH_CONCERNS** | 懸念内容を読み、正当性・スコープに関わるものは先に対処。観察レベルなら記録してレビューへ |
| **NEEDS_CONTEXT** | 不足コンテキストを提供して再ディスパッチ |
| **BLOCKED** | ①コンテキスト不足→追加して再ディスパッチ ②能力不足→より高性能モデルで再ディスパッチ ③タスクが大きすぎる→分割 ④計画自体の問題→ユーザーにエスカレーション |

## Model Selection

コストと速度を最適化するため、タスクの複雑度に応じてモデルを選択する:

- **1-2ファイル + 明確なspec** → haiku or sonnet（安い・速い）
- **複数ファイル + 統合的な判断** → sonnet
- **設計判断 + レビュー** → opus

## Review Order

**必ず spec compliance → code quality の順。逆にしない。**

仕様に合っていないコードの品質をレビューしても無意味。

## Prompt Templates

- `./implementer-prompt.md` — 実装サブエージェント用
- `./spec-reviewer-prompt.md` — 仕様準拠レビュー用
- `./code-quality-reviewer-prompt.md` — コード品質レビュー用

## Rationalization Prevention

| Rationalization | Reality |
|---|---|
| "Simple task, skip review" | Simple tasks have spec drift too. Review both stages |
| "Implementer self-reviewed, that's enough" | Self-review supplements but never replaces external review |
| "Spec review passed, skip quality review" | Spec-compliant code can still be poorly written |
| "Run reviews in parallel to save time" | Quality review before spec compliance wastes effort on wrong code |
| "I'll fix it myself instead of re-dispatching" | Manual fixes pollute the main context. Re-dispatch the implementer |

## Red Flags

**Never:**
- Skip either review stage
- Dispatch multiple implementers in parallel (conflict risk)
- Let the implementer read the plan file (provide full text instead)
- Ignore subagent questions
- Accept "close enough" on spec compliance
- Move to next task while reviews have open issues
