---
adr: 53
date: 2026-11-18
status: accepted
---

# ブランチ作成後の /rename 提案を、PostToolUse フックで促す

## 背景

CLAUDE.md の「セッションの見つけやすさ（Claude Code）」は、ブランチを作った直後に
`/rename <作業内容> (<ブランチ名>)` を提案するよう求めている（2026-10-11 に追加）。
2026-11-18、brainstorming → writing-plans の途中で `git switch -c` したセッションが提案せず、PRのマージ後にユーザーが気づいた。

「直後に提案する」という指示は、破っても成果物に跡が残らない（`rules/proving-absence.md` の「順序の指示」と同じ構造）。
文面は明確なので、書き直しても漏れは減らないと見た。

会話記録（`~/.claude/projects/*/*.jsonl`）で、ブランチを作ったセッションのうち、その後の本文に `/rename` が出たものを数えた。

| 月 | ブランチを作ったセッション | `/rename` あり |
|---|---|---|
| 2026-10 | 22 | 13（59%） |
| 2026-11 | 35 | 24（69%） |

測定の限界: 10月分にはルール追加前（10/1〜10/10）のセッションが混ざる。`/rename` の文字があれば提案でなくても数える。
Planモードの自動タイトルで提案を省いてよいセッションも、漏れに数える。会話記録は `guard-secret-read.py` が読み取りを止めるので、
集計はユーザーが `!` で実行した（件数だけを出すスクリプト）。

## 決定

ユーザーが3案から選んだ（2026-11-18）。

1. `hooks/suggest-session-rename.py` を PostToolUse（matcher `Bash|EnterWorktree`）に置く
2. `git [-C <dir>] switch -c/-C/--create/--force-create`、`checkout -b/-B`、`worktree add`、`EnterWorktree` の直後に、
   `additionalContext` で提案を促す文を差し込む。コマンドの先頭か区切りの直後の `git` だけを見る
3. `agent_id` がある呼び出し（サブエージェント内）では出さない。提案する相手のユーザーと話していないため
4. 会話記録は読まない。Planモードの自動タイトルは判定せず、促す文に「付いていれば省いてよい」と書いてエージェントに任せる
5. 入力が読めないときは何も出さない（fail-open）。止める役割を持たないため

## 検討した代替案

- **Stop フックで検査して差し戻す**（却下）: ターンの終わりに会話記録を読み、ブランチ作成があったのに `/rename` が無ければ一度だけ応答をやり直させる。
  提案が出たことまで確かめられるのはこの案だけだが、会話記録の形式に依存する。また、Stopフックが書き込み前の会話記録を読んで誤検知する件
  （`code-learning-check.py`、backlog 積み済み）と同じ弱点を持ち込む。Planモードの例外判定も要る
- **フックを入れない**（却下）: 文面のまま運用する。3〜4割の漏れが続き、目的を果たせない
- **CLAUDE.md の文面を書き直す**（却下）: 文面は明確で、漏れの原因は文面ではなく、跡が残らない順序の指示であること

## 結果

- 促すだけなので、提案が出たかは確かめない。効果は、数週間後に同じ集計をやり直して確かめる
  （ブランチ作成のツール呼び出し以降の assistant 本文に `/rename` があるかを月ごとに数える。導入月以降の割合を見る）
- 促す文がエージェントに読み流されれば漏れは残る。再測定で割合が上がらなければ、Stop 案を検討し直す
- `agent_id` が PostToolUse の入力に乗ることは、公式ドキュメントの共通フィールドの記述から推測したもの。実セッションで確かめる
- Codex CLI には配線しない。CLAUDE.md の該当節が Claude Code 限定のため

## 根拠

- Claude Code hooks reference（https://code.claude.com/docs/en/hooks）: PostToolUse の入力（`tool_name`、`tool_input`、共通フィールドの `agent_id`）と、
  `hookSpecificOutput.additionalContext` で文脈を足せること。要約経由で読んだ
