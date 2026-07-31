# rtk導入（Claude Code連携側） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** rtkのPreToolUse(Bash)フックをClaude Codeのグローバル設定に登録し、既存の危険コマンドブロックフックと共存させる。

**Architecture:** `settings.json.template` に確認済みのrtkフックブロックを、既存の`guard-dangerous-bash.sh`ブロックとは別要素として追記する。`setup.sh`でテンプレートから`~/.claude/settings.json`を再生成し、実機で有効化を確認する。

**Tech Stack:** Claude Code hooks (PreToolUse), rtk 0.44.1 (Homebrew), bash (setup.sh)

## Global Constraints

- `~/.claude/settings.json` は `setup.sh` によって `settings.json.template` + `.env` から毎回再生成される。rtk側の自動書き込み機能（`rtk init -g --auto-patch`）は使わない
- rtkフックの内容は実機確認済みの以下の内容を使う（rtk 0.44.1）:
  ```json
  { "type": "command", "command": "rtk hook claude" }
  ```
- 既存の `guard-dangerous-bash.sh` ブロックは変更しない。rtkフックは`PreToolUse`配列内の別要素として追加する
- rtkは`brew install rtk`でインストール済み（このマシン）。dotfiles Brewfileには定義済み

---

### Task 1: settings.json.template にrtkフックを追記する

**Files:**
- Modify: `settings.json.template:29-42`

**Interfaces:**
- なし（設定ファイルの追記のみ、コードインターフェースは発生しない）

- [ ] **Step 1: 現在の`hooks`セクションを確認する**

```bash
sed -n '29,42p' settings.json.template
```

Expected: 既存の`guard-dangerous-bash.sh`ブロックのみが表示される

- [ ] **Step 2: `PreToolUse`配列にrtkフックのブロックを追記する**

`settings.json.template`の`hooks.PreToolUse`配列を以下の内容に置き換える（既存の
`guard-dangerous-bash.sh`ブロックは維持し、2番目の要素として`rtk hook claude`ブロックを追加する）:

```json
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/guard-dangerous-bash.sh",
            "timeout": 5000
          }
        ]
      },
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "rtk hook claude"
          }
        ]
      }
    ]
  }
```

- [ ] **Step 3: JSONとして妥当か検証する**

```bash
python3 -m json.tool settings.json.template > /dev/null && echo "VALID JSON"
```

Expected: `VALID JSON` が出力される

- [ ] **Step 4: コミットする**

```bash
git add settings.json.template
git commit -m "feat: settings.json.templateにrtk PreToolUseフックを追加"
```

---

### Task 2: setup.shを実行して`~/.claude/settings.json`を再生成する

**Files:**
- Modify: なし（`setup.sh`自体は変更しない、実行のみ）
- 対象: `~/.claude/settings.json`（生成物、リポジトリ管理外）

**Interfaces:**
- Consumes: Task 1で追記した`settings.json.template`
- Produces: `~/.claude/settings.json`（rtkフック入り）

- [ ] **Step 1: 現在の`~/.claude/settings.json`をバックアップする**

```bash
cp ~/.claude/settings.json /tmp/settings.json.before_task2
```

Expected: バックアップファイルが作成される

- [ ] **Step 2: setup.shを実行する**

```bash
bash setup.sh
```

Expected: `✓ settings.json を生成しました → /Users/sasakin/.claude/settings.json` が出力される。
既存ファイルが上書きされる場合は`setup.sh`が自動でバックアップを`~/.claude/backups/`配下に作成する

- [ ] **Step 3: 生成された`~/.claude/settings.json`にrtkフックが含まれることを確認する**

```bash
grep -A3 "rtk hook claude" ~/.claude/settings.json
```

Expected: `"command": "rtk hook claude"` を含むブロックが表示される

- [ ] **Step 4: 既存のguard-dangerous-bashフックが維持されていることを確認する**

```bash
grep "guard-dangerous-bash.sh" ~/.claude/settings.json
```

Expected: `guard-dangerous-bash.sh` のパスが表示される（削除されていないこと）

- [ ] **Step 5: JSONとして妥当か検証する**

```bash
python3 -m json.tool ~/.claude/settings.json > /dev/null && echo "VALID JSON"
```

Expected: `VALID JSON` が出力される

このタスクはリポジトリへのコミットを伴わない（生成物のみの変更）。コミットステップはなし。

---

### Task 3: Claude Codeを再起動してフック有効化を確認する

**Files:**
- なし（動作確認のみ）

**Interfaces:**
- Consumes: Task 2で生成された`~/.claude/settings.json`

- [ ] **Step 1: 現在実行中のClaude Codeセッションがあれば再起動が必要であることをユーザーに伝える**

このタスクはセッション外での確認が必要。ユーザーに以下を依頼する：
「設定を反映するため、Claude Codeを再起動してから `rtk init --show` を実行してください」

- [ ] **Step 2: フック有効化を確認する（再起動後、新しいセッションまたはターミナルで実行）**

```bash
rtk init --show
```

Expected出力に以下が含まれる:
```
[--] Hook: ...  (not found ではなく、hook found的な表示になっていること)
```
`No hook installed` の警告が出ないこと。

- [ ] **Step 3: 実際にBashツール経由でrtkが動作することを簡易確認する**

Claude Codeの新しいセッション内で、Bashツールを使い次を実行してもらう:

```bash
git status
```

Expected: コマンドが正常に実行され、エラーが出ないこと（rtkによる書き換え・圧縮が裏側で
行われるが、ユーザー体感としては通常のgit statusの結果が返る）。

- [ ] **Step 4: 危険コマンドブロックフックが依然として機能することを確認する**

Claude Codeの新しいセッション内で、Bashツールで次を実行しようとしてもらう（実行されず
ブロックされることを期待するテスト）:

```bash
rm -rf /
```

Expected: `guard-dangerous-bash.sh` によりブロックされ、
「ブロック: 確定的に危険なコマンドを検出しました」のエラーが出ること。rtkのフックが
書き換えを行っても、ブロック判定が回避されないことを確認する。

このタスクはコミットを伴わない（動作確認のみ）。確認結果を次のタスクの前提として記録する。

---

### Task 4: README.mdのhooks説明を更新する

**Files:**
- Modify: `README.md:29`, `README.md:83`

**Interfaces:**
- なし

- [ ] **Step 1: 現在の記述を確認する**

```bash
grep -n "hooks" README.md
```

Expected:
```
29:| `hooks/` | `~/.claude/hooks/` | 危険コマンドブロック等のhooksスクリプト |
83:├── hooks/                       # 危険コマンドブロック等のhooksスクリプト
```

- [ ] **Step 2: 両箇所の説明にrtkフックの言及を追記する**

`README.md:29`を以下に変更:
```
| `hooks/` | `~/.claude/hooks/` | 危険コマンドブロック等のhooksスクリプト（rtkフックはsettings.json.template側で管理） |
```

`README.md:83`を以下に変更:
```
├── hooks/                       # 危険コマンドブロック等のhooksスクリプト（rtkフックはsettings.json.template側で管理）
```

- [ ] **Step 3: 変更を確認する**

```bash
grep -n "hooks" README.md
```

Expected: 更新後の文言が表示される

- [ ] **Step 4: コミットする**

```bash
git add README.md
git commit -m "docs: READMEにrtkフックの管理場所を明記"
```

---

## 完了条件

- [ ] `settings.json.template` にrtkフックが追記されコミットされている
- [ ] `~/.claude/settings.json` が再生成され、rtkフックと既存フックの両方を含む
- [ ] `rtk init --show` でフックが有効になっていることが確認できる
- [ ] 危険コマンドブロックが依然として機能する（rtkの書き換えに影響されない）
- [ ] README.mdの更新がコミットされている
