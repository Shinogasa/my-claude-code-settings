---
adr: 45
date: 2026-10-30
status: accepted
---

# `pr-create` をモデルから呼べるように戻す

旧番号は 0043。PR #123 でマージしたときの番号で、先にマージされた `0043-secret-read-guard.md` と重なったため、2026-10-30に 0045 へ振り直した。
PR #123 の本文やコミットメッセージの「ADR 0043」は、このADRを指す。

## 背景

解く問題: ClaudeにPRの作成を任せる運用なのに、`pr-create` の呼び出し制限のせいで、ClaudeがPRの手前で止まる。

ADR 0040の決定5で、`pr-create` 系のskillとcommandに `disable-model-invocation: true` を付けた。
Codex CLI向けには `agents/openai.yaml` に `policy.allow_implicit_invocation: false` を置いた。
理由は「副作用のあるskillは、Claudeが自分の判断で呼べないようにする」という公式の勧めに合わせることだった。

2026-10-30、別のリポジトリの作業でClaudeが `pr-create` を呼んだところ、次のエラーで断られた。

> Skill pr-create cannot be used with Skill tool due to disable-model-invocation. Ask the user to run /pr-create themselves — it cannot be invoked via the Skill tool. Do not replicate this skill's workflow by other means

最後の一文があるため、Claudeは `gh pr create` を直接実行することも「別の方法で同じ手順をなぞる」ことだと解釈した。
そしてPRを作らずに止まり、ユーザーに `/pr-create` を打つよう頼んだ。

一方で、このリポジトリの運用はClaudeにPRを作らせる前提になっている。

- `CLAUDE.md` はブランチを仕上げるときにpushしてPRを作るよう定めている（superpowersの finishing-a-development-branch）
- PRを作る前の確認は、`gh pr create` に反応する PreToolUse フックが受け持つ
  - `hooks/require-full-tests-before-pr.py`: 全件テストの通過
  - `hooks/jp-doc-review.py`: 日本語の文書のレビュー

ADR 0040を決めたときは、この運用との関係を検討していなかった。

ユーザーの方針は「PRはよしなに作ってほしい。その前の事前チェックやレビューはフックで制限している」。

## 決定

AIが3つの案（この決定と、下の代替案2つ）を出してこの決定を勧め、ユーザーがこれを選んだ。

`pr-create` 系のskillとcommandから `disable-model-invocation: true` を外し、
Codex CLI向けの `agents/openai.yaml` も削除する。ADR 0040の決定5だけを取り消し、ほかの決定は残す。

PRを作る操作の安全は、skillの呼び出し制限ではなく、`gh pr create` に掛かるフックで守る。

ADR 0040の「基本はベストプラクティスに沿わせる」は見直さない。ここで決めるのは、その例外として扱う基準である。
同じ守りをフックが受け持っているなら、公式の勧めから外れてよい。

## 検討した代替案

### 制限を残し、PRのたびにユーザーが `/pr-create` を打つ

ハーネスの意図どおりに動き、PRを作るタイミングを人が必ず決める。
しかし、ユーザーはPRの作成を任せたいと考えている。毎回の手打ちを求めると、
finishing-a-development-branch の流れがPRの手前で止まる。

### 制限を残し、`gh pr create` の直接実行は「なぞり」に当たらないとCLAUDE.mdに書く

自動の流れは残せる。しかし、ハーネスが出すエラー文は「別の方法でなぞるな」と言い続けるので、
CLAUDE.mdの記述と食い違う。Claudeがどちらを優先するかが安定せず、同じ止まり方がまた起きうる。

## 結果

- Claudeは `pr-create` を自分で呼べるようになり、`gh pr create` の直接実行で止まらなくなる
- skillの仕組みでは、ClaudeによるPRの作成を止めなくなる。代わりに、全件テストと日本語レビューの検査をフックに頼る。
  フックの対象は `gh pr create` だけで、GitHub APIやMCPでPRを作る経路は止めない。
  これらの経路では、テストもレビューも通らずにPRができうる。ユーザーはこれをリスクとして受け入れ、
  ほかの経路でPRを作るようになったときに対策することにした
- Codex CLIでも暗黙の呼び出しを許す。Codex側のフックは `/hooks` の承認が無いと通知なくスキップされるので、
  Codex CLIで同じ守りが働くかは承認状態による

## 根拠

- ADR 0040（決定5と、その背景）
- 2026-10-30に別のリポジトリのセッションで出たエラー文（背景に引用）
- `hooks/require-full-tests-before-pr.py`、`hooks/jp-doc-review.py`
