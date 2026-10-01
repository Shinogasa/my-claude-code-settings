# 日本語文書レビューとスキル読み込み確認 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude Codeが日本語の文書を書いたときにyomiyasuでレビューさせ、スキルの必読資料の読み漏れを会話記録で見つけるフックを入れる。

**Architecture:** PostToolUseで書き込みを記録し、Stopでまとめてレビュー用サブエージェント `jp-doc-reviewer` に依頼する。Confluenceへの投稿はPreToolUseで1回だけ止める。汎用の `skill-read-check.py` が、StopとSubagentStopで会話記録と必読資料の対応表を照合する。yomiyasuはsubmoduleとして固定する。

**Tech Stack:** Python 3（標準ライブラリのみ）、unittest、Claude Code hooks、git submodule、bash（setup.sh）

**Spec:** `docs/superpowers/specs/2026-10-01-jp-doc-review-design.md`（判断の経緯は `docs/adr/0024-jp-doc-review-hook.md`）

## Global Constraints

- 対象ホストはClaude Codeだけ。`codex/hooks.json` は変更しない
- フックのスクリプトは標準ライブラリだけで書く（他のフックと同じ）
- `MIN_JP_CHARS = 100`、`TARGET_SUFFIXES = {".md", ".toml", ".yaml", ".yml", ".json"}`、`STATE_RETENTION_DAYS = 7`、`REVIEWER_AGENT = "jp-doc-reviewer"`
- 状態の置き場は `~/.claude/state/jp-doc-review/`。テストでは環境変数 `JP_DOC_REVIEW_STATE_DIR` で差し替える
- yomiyasuの場所は `~/.claude/skills/yomiyasu/SKILL.md`。テストでは `JP_DOC_REVIEW_YOMIYASU_SKILL` で差し替える
- 必読資料の対応表は `manifests/skill-required-reads.json`。テストでは `SKILL_READ_CHECK_MANIFEST` で差し替える
- 検査できなかったことは、問題なしとして扱わない。`systemMessage` か標準エラー（終了コード1）で必ず画面に出す
- yomiyasuの固定先は `b14ee43c9b722cf4fd2bb1e893c6c386f1a362aa`（2026-10-01時点の上流HEAD）
- テストは `env -u FORCE_COLOR python3 -m unittest ...` で実行する（`FORCE_COLOR` があると既存の1件が落ちる。backlog参照）
- このリポジトリはPUBLIC。会話記録や入力の実物を記録するときは、組織名・内部URL・ID類を伏せる
- コミットメッセージはConventional Commitsで、日本語。末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` を付ける
- 日本語の文章（docs、agent定義、フックの出力文）は、yomiyasuの手順を通してから書き終える

## Review Focus

- **git worktreeの中の文書**: worktreeの `.git` はファイルなので、submoduleと誤って判定するとレビューされなくなる。worktreeの文書は記録されるべき（Task 4でテスト）
- **同じファイルをsymlink経由と実体の両方で書いた場合**: `~/.claude/rules/x.md` と `rules/x.md` のように別のパスでも、合算して1件として扱うべき（Task 4でテスト）
- **小さな編集が何ターンにも分かれた場合**: 1回ずつは100文字未満でも、合計が100文字を超えた時点でレビューされるべき（Task 5でテスト）
- **別のフックのblockで2回目のStopが来た場合**: `skill-read-check.py` がblockしただけで、こちらが何も依頼していないときに「レビュワーが起動されなかった」と表示してはいけない（Task 5でテスト）
- **入力が壊れている、またはsession_idが無い場合**: 作業を止めず、終了コード1と標準エラーで知らせるべき。session_idに `/` などが入っていても、状態ディレクトリの外へ書いてはいけない（Task 4でテスト）

---

### Task 1: 実機のフック入力と会話記録の形式を記録する

設計は、一次資料（`claude-code-best-practice/.claude/hooks/HOOKS-README.md`）と既存の会話記録の観察に基づいている。
合成した入力でのテストは、実機で動く証拠にならない。実装の前に、Claude Code 2.1.286の実物を記録する。

**Files:**
- Create: `docs/research/2026-10-02-claude-code-hook-payloads.md`
- Modify（結果が想定と違う場合だけ）: `docs/superpowers/specs/2026-10-01-jp-doc-review-design.md`、この計画

**Interfaces:**
- Produces: 後続タスクが前提にするフィールド名の確認結果。想定は次のとおり
  - PostToolUse: `session_id`、`cwd`、`tool_name`、`tool_input.file_path`、`tool_input.content`（Write）、`tool_input.new_string`（Edit）、サブエージェント内では `agent_type`
  - Stop: `session_id`、`transcript_path`、`stop_hook_active`
  - SubagentStop: `agent_type`、`agent_transcript_path`、`stop_hook_active`
  - PreToolUse（MCP）: `tool_name`（`mcp__atlassian-http__createConfluencePage` など）、`tool_input.body`、`tool_input.title`
  - 会話記録: compactの区切りは `{"type": "system", "subtype": "compact_boundary"}`。ツール呼び出しは `type: "assistant"` の行の `message.content[]` にある `{"type": "tool_use", "name", "input"}`。Stopフックのblockで続いた回の差し戻し文が、どの形の行で残るか

- [ ] **Step 1: 入力を記録するだけの一時フックを作る**

一時ディレクトリを作り、そこに次の2ファイルを置く。

```bash
SPIKE=$(mktemp -d)
mkdir -p "$SPIKE/repo" && git -C "$SPIKE/repo" init -q
cat > "$SPIKE/log-hook.sh" <<'EOF'
#!/bin/bash
# 入力をイベント名ごとのファイルへ追記するだけ。Confluenceの投稿は送らせないためにdenyする。
event="$1"
payload=$(cat)
printf '%s\n' "$payload" >> "$SPIKE_LOG_DIR/$event.jsonl"
if [ "$event" = "pre-tool-use" ]; then
  printf '%s' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"spike: 送信しない"}}'
fi
if [ "$event" = "stop" ] && ! printf '%s' "$payload" | grep -q '"stop_hook_active":true'; then
  printf '%s' '{"decision":"block","reason":"spike: もう一度だけ続けて、何もせずに終えて"}'
fi
exit 0
EOF
chmod +x "$SPIKE/log-hook.sh"
mkdir -p "$SPIKE/logs"
cat > "$SPIKE/settings.json" <<EOF
{
  "hooks": {
    "PostToolUse": [{"matcher": "Write|Edit", "hooks": [{"type": "command", "command": "SPIKE_LOG_DIR=$SPIKE/logs $SPIKE/log-hook.sh post-tool-use"}]}],
    "PreToolUse": [{"matcher": "mcp__.*__(create|update)Confluence(Page|FooterComment|InlineComment)", "hooks": [{"type": "command", "command": "SPIKE_LOG_DIR=$SPIKE/logs $SPIKE/log-hook.sh pre-tool-use"}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "SPIKE_LOG_DIR=$SPIKE/logs $SPIKE/log-hook.sh stop"}]}],
    "SubagentStop": [{"hooks": [{"type": "command", "command": "SPIKE_LOG_DIR=$SPIKE/logs $SPIKE/log-hook.sh subagent-stop"}]}]
  }
}
EOF
echo "$SPIKE"
```

- [ ] **Step 2: ヘッドレスのClaude Codeで、書き込み・サブエージェント・Confluence投稿を1回ずつ起こす**

```bash
cd "$SPIKE/repo" && claude -p --settings "$SPIKE/settings.json" \
  --allowedTools "Write,Edit,Agent,mcp__atlassian-http__createConfluencePage" \
  "次を順に実行して。1) note.md に日本語で3文書く。2) note.md の1文目をEditで書き換える。3) general-purposeのサブエージェントを1回起動し、sub.md に日本語で2文書かせる。4) mcp__atlassian-http__createConfluencePage を cloudId: example.atlassian.net、spaceId: 1、title: テスト、body: これは送らないテストです。 で呼ぶ（拒否されたらそのまま次へ）。5) 終える。"
ls "$SPIKE/logs"
```

Expected: `post-tool-use.jsonl`、`pre-tool-use.jsonl`、`stop.jsonl`、`subagent-stop.jsonl` ができる。Confluenceへの投稿はフックがdenyするので送られない。

ヘッドレスの実行でAtlassianのMCPが使えず、`pre-tool-use.jsonl` ができなかった場合は、PreToolUseの入力を「未確認」として記録する。Task 6はツールの定義（`body`・`title`・`pageId`・`parentCommentId`・`contentFormat`）に基づいて進め、Task 10のStep 6で実機を確かめる。

- [ ] **Step 3: 記録した入力を確かめる**

```bash
python3 - "$SPIKE/logs" <<'EOF'
import json, sys
from pathlib import Path
for name in ("post-tool-use", "pre-tool-use", "stop", "subagent-stop"):
    path = Path(sys.argv[1]) / f"{name}.jsonl"
    if not path.exists():
        print(name, "記録なし"); continue
    for line in path.read_text().splitlines():
        value = json.loads(line)
        tool_input = value.get("tool_input") or {}
        print(name, sorted(value), value.get("tool_name"), sorted(tool_input), value.get("agent_type"), value.get("stop_hook_active"))
EOF
```

確かめる点は次のとおり。

1. Writeの入力に `file_path` と `content`、Editの入力に `file_path` と `new_string` がある
2. サブエージェントが書いたWriteの入力に `agent_type` があり、`session_id` がメインと同じか違うか
3. Stopの入力に `transcript_path` と `stop_hook_active` がある
4. SubagentStopの入力に `agent_type` と `agent_transcript_path` がある
5. PreToolUseの入力に `tool_input.body` と `tool_input.title` がある

- [ ] **Step 4: 会話記録で、Stopフックの差し戻し文がどう残るかを確かめる**

```bash
python3 - "$(python3 -c "import json,sys;print(json.loads(open('$SPIKE/logs/stop.jsonl').readline())['transcript_path'])")" <<'EOF'
import json, sys
for line in open(sys.argv[1]):
    entry = json.loads(line)
    message = entry.get("message") or {}
    content = message.get("content") if isinstance(message, dict) else None
    if entry.get("type") in ("user", "system"):
        kinds = [part.get("type") for part in content] if isinstance(content, list) else type(content).__name__
        print(entry.get("type"), entry.get("subtype"), entry.get("isMeta"), kinds, str(content)[:80])
EOF
```

「spike: もう一度だけ続けて」の文が、`type: "user"` の行として残るのか、`isMeta` が付くのか、`system` の行なのかを記録する。
`hooks/hook_support.py` の `is_human_prompt` は「`type` が `user` で、`isMeta` が真でなく、内容が文字列か、`text` を含み `tool_result` を含まないリスト」をプロンプトとみなす（Task 3）。
差し戻し文がこの条件に当てはまる形なら、差し戻し文を除外する条件を `is_human_prompt` に加える必要がある。その場合は、記録した形をTask 3のテストにも入れる。

- [ ] **Step 5: 結果を記録する**

`docs/research/2026-10-02-claude-code-hook-payloads.md` に、確認したフィールド名と、想定との違いを書く。
ID、パス、本文の実物は貼らず、キーの一覧と型だけを書く（このリポジトリはPUBLIC）。
想定と違った点があれば、設計書とこの計画の該当箇所を直してから次へ進む。

- [ ] **Step 6: コミットする**

```bash
git add docs/research/2026-10-02-claude-code-hook-payloads.md
git commit -m "docs: Claude Codeのフック入力と会話記録の形式を実機で確かめる"
```

`rm -rf "$SPIKE"` で一時ディレクトリを消す。

---

### Task 2: yomiyasuをsubmoduleとして取り込み、共有スキルに登録する

**Files:**
- Modify: `.gitmodules`（`git submodule add` が書く）
- Create: `skills/yomiyasu`（submodule）
- Modify: `manifests/skills.json`
- Test: `tests/test_skill_manifest.py`

**Interfaces:**
- Produces: リポジトリ内の `skills/yomiyasu/SKILL.md` と `skills/yomiyasu/references/`。setup.shが `~/.claude/skills/yomiyasu` と `~/.agents/skills/yomiyasu` にリンクする

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_skill_manifest.py` の末尾（`if __name__` の前）に足す。

```python
class TestExternalSkillSubmodule(unittest.TestCase):
    """外部のyomiyasuをcommit固定のsubmoduleとして共有配布しているか。"""

    def test_yomiyasu_is_declared_submodule_listed_as_shared(self):
        gitmodules = (REPO_ROOT / ".gitmodules").read_text(encoding="utf-8")
        self.assertIn("path = skills/yomiyasu", gitmodules)
        self.assertIn("url = https://github.com/nanaism/yomiyasu.git", gitmodules)
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertIn("yomiyasu", manifest["shared"])
        self.assertTrue((SKILLS_DIR / "yomiyasu" / "SKILL.md").is_file())
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `env -u FORCE_COLOR python3 -m unittest tests.test_skill_manifest -v`
Expected: `test_yomiyasu_is_declared_submodule_listed_as_shared` が `path = skills/yomiyasu` の `AssertionError` で FAIL

- [ ] **Step 3: submoduleを追加して固定する**

```bash
git submodule add https://github.com/nanaism/yomiyasu.git skills/yomiyasu
git -C skills/yomiyasu checkout -q b14ee43c9b722cf4fd2bb1e893c6c386f1a362aa
git add .gitmodules skills/yomiyasu
```

`manifests/skills.json` の `shared` の末尾（`"verification-loop"` の後）に `"yomiyasu"` を足す。並びは辞書順のまま保つ。

```json
        "verification-loop",
        "yomiyasu"
    ],
```

- [ ] **Step 4: テストが通ることを確かめる**

Run: `env -u FORCE_COLOR python3 -m unittest tests.test_skill_manifest tests.test_learning_mode_contract -v`
Expected: すべて PASS。`test_shared_skills_are_host_neutral` もyomiyasuのSKILL.mdで通る（2026-10-02に4つの禁止パターンが無いことを確認済み）

Run: `env -u FORCE_COLOR python3 -m unittest tests.test_setup_cli tests.test_setup_preflight`
Expected: OK（それぞれ数分かかる）

- [ ] **Step 5: コミットする**

```bash
git add tests/test_skill_manifest.py manifests/skills.json .gitmodules skills/yomiyasu
git commit -m "feat: yomiyasuをcommit固定のsubmoduleとして共有スキルに加える"
```

---

### Task 3: 会話記録の読み取りとフック出力の補助モジュール

**Files:**
- Create: `hooks/hook_support.py`
- Test: `tests/test_hook_support.py`

**Interfaces:**
- Produces: `hooks/hook_support.py` の次の関数と例外
  - `class TranscriptError(Exception)`
  - `read_entries(path: Optional[str], start_offset: int = 0) -> List[dict]`
  - `after_last_compact(entries: List[dict]) -> List[dict]`
  - `is_human_prompt(entry: dict) -> bool`
  - `since_last_prompt(entries: List[dict]) -> List[dict]`
  - `tool_uses(entries: List[dict]) -> List[Tuple[str, dict]]`
  - `emit(value: dict) -> None`（空のdictなら何も出さない）
  - `with_messages(value: dict, messages: List[str]) -> dict`（`systemMessage` を足す）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_hook_support.py` を作る。

```python
#!/usr/bin/env python3
"""hooks/hook_support.py の会話記録の読み取りと出力の組み立てを検証する。

実行: python3 -m unittest tests.test_hook_support
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))

import hook_support  # noqa: E402

COMPACT = {"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted"}


def prompt(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def tool_result():
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}}


def call(name, **tool_input):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": tool_input}]}}


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "t.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, *entries, raw_lines=()):
        with self.path.open("a", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            for line in raw_lines:
                handle.write(line + "\n")

    def test_skips_broken_lines_and_reads_the_rest(self):
        self.write(prompt("a"), raw_lines=["{broken"])
        self.assertEqual(hook_support.read_entries(str(self.path)), [prompt("a")])

    def test_raises_when_no_line_can_be_read(self):
        self.write(raw_lines=["not json", "{also broken"])
        with self.assertRaises(hook_support.TranscriptError):
            hook_support.read_entries(str(self.path))

    def test_raises_when_path_is_missing(self):
        with self.assertRaises(hook_support.TranscriptError):
            hook_support.read_entries(None)
        with self.assertRaises(hook_support.TranscriptError):
            hook_support.read_entries(str(self.path))

    def test_reads_only_after_offset(self):
        self.write(prompt("before"))
        offset = self.path.stat().st_size
        self.write(prompt("after"))
        self.assertEqual(hook_support.read_entries(str(self.path), offset), [prompt("after")])

    def test_empty_slice_after_offset_is_not_an_error(self):
        self.write(prompt("only"))
        self.assertEqual(hook_support.read_entries(str(self.path), self.path.stat().st_size), [])

    def test_after_last_compact(self):
        entries = [prompt("old"), COMPACT, prompt("mid"), COMPACT, prompt("new")]
        self.assertEqual(hook_support.after_last_compact(entries), [prompt("new")])
        self.assertEqual(hook_support.after_last_compact([prompt("x")]), [prompt("x")])

    def test_human_prompt_excludes_tool_results_and_meta(self):
        self.assertTrue(hook_support.is_human_prompt(prompt("hi")))
        self.assertTrue(hook_support.is_human_prompt(
            {"type": "user", "message": {"content": [{"type": "text", "text": "hi"}]}}))
        self.assertFalse(hook_support.is_human_prompt(tool_result()))
        self.assertFalse(hook_support.is_human_prompt({**prompt("x"), "isMeta": True}))
        self.assertFalse(hook_support.is_human_prompt(call("Read", file_path="/a")))

    def test_since_last_prompt(self):
        entries = [prompt("1"), call("Skill", skill="x"), prompt("2"), call("Read", file_path="/a"), tool_result()]
        self.assertEqual(hook_support.since_last_prompt(entries), entries[3:])

    def test_tool_uses_in_order(self):
        entries = [call("Skill", skill="yomiyasu"), prompt("x"), call("Read", file_path="/a")]
        self.assertEqual(hook_support.tool_uses(entries),
                         [("Skill", {"skill": "yomiyasu"}), ("Read", {"file_path": "/a"})])


class OutputTests(unittest.TestCase):
    def test_emit_prints_json_and_skips_empty(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            hook_support.emit({})
            hook_support.emit({"systemMessage": "日本語"})
        self.assertEqual(buffer.getvalue().strip(), json.dumps({"systemMessage": "日本語"}, ensure_ascii=False))

    def test_with_messages_joins_lines(self):
        self.assertEqual(hook_support.with_messages({}, []), {})
        self.assertEqual(hook_support.with_messages({"decision": "block"}, ["a", "b"]),
                         {"decision": "block", "systemMessage": "a\nb"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

Task 1で、Stopフックの差し戻し文が `is_human_prompt` に当てはまる形で残ると分かった場合は、その形の行を
`test_human_prompt_excludes_tool_results_and_meta` に `assertFalse` として足してから進める。

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `env -u FORCE_COLOR python3 -m unittest tests.test_hook_support -v`
Expected: `ModuleNotFoundError: No module named 'hook_support'` で ERROR

- [ ] **Step 3: 実装を書く**

`hooks/hook_support.py` を作る。

```python
"""Claude Codeのフックが共通で使う、会話記録の読み取りと出力の組み立て。

会話記録（JSONL）の形式はClaude Codeの内部仕様で、公開された契約ではない。
形式が変わって読めなくなったときは TranscriptError を投げ、呼び出し側が画面に表示する。
"""
import json
from typing import List, Optional, Tuple

ToolUse = Tuple[str, dict]


class TranscriptError(Exception):
    """会話記録を読めなかったことを表す。"""


def read_entries(path: Optional[str], start_offset: int = 0) -> List[dict]:
    """会話記録の各行をdictで返す。JSONとして読めない行は飛ばす。

    中身があるのに1行も読めないときは、形式が変わったとみなして例外にする。
    """
    if not path:
        raise TranscriptError("入力に会話記録のパスが無い")
    try:
        with open(path, "rb") as handle:
            handle.seek(start_offset)
            raw = handle.read().decode("utf-8", errors="replace")
    except OSError as error:
        raise TranscriptError(f"会話記録を開けない: {error}") from error
    entries = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            entries.append(value)
    if raw.strip() and not entries:
        raise TranscriptError("会話記録の行をJSONとして読めない")
    return entries


def after_last_compact(entries: List[dict]) -> List[dict]:
    """最後のcompactの区切りより後の行だけを返す。"""
    last = -1
    for index, entry in enumerate(entries):
        if entry.get("type") == "system" and entry.get("subtype") == "compact_boundary":
            last = index
    return entries[last + 1:]


def _content(entry: dict):
    message = entry.get("message")
    return message.get("content") if isinstance(message, dict) else None


def is_human_prompt(entry: dict) -> bool:
    """ユーザーが入力したプロンプトの行か。ツールの結果やメタ情報の行は含めない。"""
    if entry.get("type") != "user" or entry.get("isMeta"):
        return False
    content = _content(entry)
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        kinds = {part.get("type") for part in content if isinstance(part, dict)}
        return "text" in kinds and "tool_result" not in kinds
    return False


def since_last_prompt(entries: List[dict]) -> List[dict]:
    """最後のユーザーのプロンプトより後の行だけを返す。"""
    last = -1
    for index, entry in enumerate(entries):
        if is_human_prompt(entry):
            last = index
    return entries[last + 1:]


def tool_uses(entries: List[dict]) -> List[ToolUse]:
    """アシスタントのツール呼び出しを、(ツール名, 入力) の組にして順に返す。"""
    result: List[ToolUse] = []
    for entry in entries:
        if entry.get("type") != "assistant":
            continue
        content = _content(entry)
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "tool_use":
                tool_input = part.get("input")
                result.append((str(part.get("name", "")), tool_input if isinstance(tool_input, dict) else {}))
    return result


def emit(value: dict) -> None:
    """フックの出力を標準出力に書く。空なら何も書かない。"""
    if value:
        print(json.dumps(value, ensure_ascii=False))


def with_messages(value: dict, messages: List[str]) -> dict:
    """画面に表示する文があれば、systemMessage として足した新しいdictを返す。"""
    if not messages:
        return dict(value)
    return {**value, "systemMessage": "\n".join(messages)}
```

- [ ] **Step 4: テストが通ることを確かめる**

Run: `env -u FORCE_COLOR python3 -m unittest tests.test_hook_support -v`
Expected: すべて PASS

- [ ] **Step 5: コミットする**

```bash
git add hooks/hook_support.py tests/test_hook_support.py
git commit -m "feat: フック用に会話記録の読み取りと出力の補助モジュールを追加する"
```

---

### Task 4: jp-doc-review.py の記録（PostToolUse）

**Files:**
- Create: `hooks/jp-doc-review.py`
- Test: `tests/test_jp_doc_review_hook.py`

**Interfaces:**
- Consumes: `hook_support.emit`、`hook_support.with_messages`
- Produces: `hooks/jp-doc-review.py` の次の使い方・関数・状態ファイル（後続のTask 5・6が同じファイルに足す）
  - 使い方 `jp-doc-review.py <post-tool-use|stop|pre-tool-use>`、入力はstdinのJSON
  - `count_jp_chars(text: str) -> int`
  - `is_target(path: Path) -> bool`
  - `session_key(payload: dict) -> str`
  - `read_records(key: str) -> Tuple[List[dict], int]`（記録と、読めなかった行の数）
  - `write_records(key: str, records: List[dict]) -> None`
  - `read_json(path: Path) -> dict`、`write_json(path: Path, value: dict) -> None`
  - 状態ファイル: `<state>/<key>.jsonl`（記録）、`<key>.dispatched.json`、`<key>.confluence.json`、`<key>.flags.json`、`<state>/drafts/`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_jp_doc_review_hook.py` を作る。Task 5・6で同じファイルにテストを足す。

```python
#!/usr/bin/env python3
"""hooks/jp-doc-review.py の振る舞いを、合成した入力で検証する。

合成した入力でのテストは、実機で動く証拠にならない。実機の入力は
docs/research/2026-10-02-claude-code-hook-payloads.md に記録している。

実行: python3 -m unittest tests.test_jp_doc_review_hook
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "jp-doc-review.py"
JP_LONG = "日本語の文書をレビューするためのテスト用の文です。" * 6
JP_HALF = "日本語の文書を少しずつ書き足すためのテスト用の文です。" * 2


def agent_call(subagent_type):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Agent",
         "input": {"subagent_type": subagent_type, "description": "d", "prompt": "p"}}]}}


class HookCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.state = self.base / "state"
        self.skill = self.base / "yomiyasu" / "SKILL.md"
        self.skill.parent.mkdir(parents=True)
        self.skill.write_text("---\nname: yomiyasu\n---\n", encoding="utf-8")
        self.repo = self.base / "repo"
        (self.repo / ".git").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, event, payload, raw=None):
        env = {**os.environ, "JP_DOC_REVIEW_STATE_DIR": str(self.state),
               "JP_DOC_REVIEW_YOMIYASU_SKILL": str(self.skill)}
        env.pop("FORCE_COLOR", None)
        result = subprocess.run(
            [sys.executable, str(HOOK), event],
            input=raw if raw is not None else json.dumps(payload, ensure_ascii=False),
            capture_output=True, text=True, env=env,
        )
        output = json.loads(result.stdout) if result.stdout.strip() else {}
        return result.returncode, output, result.stderr

    def write_file(self, relative, text, root=None):
        path = (root or self.repo) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def post(self, path, text, tool="Write", session="s1", **extra):
        key = "content" if tool == "Write" else "new_string"
        payload = {"session_id": session, "cwd": str(self.repo), "tool_name": tool,
                   "tool_input": {"file_path": str(path), key: text}, **extra}
        return self.run_hook("post-tool-use", payload)

    def stop(self, active=False, transcript=None, session="s1"):
        payload = {"session_id": session, "stop_hook_active": active}
        if transcript is not None:
            payload["transcript_path"] = str(transcript)
        return self.run_hook("stop", payload)

    def records(self, session="s1"):
        path = self.state / f"{session}.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class RecordTests(HookCase):
    def test_records_japanese_markdown_without_output(self):
        path = self.write_file("docs/a.md", JP_LONG)
        code, output, _ = self.post(path, JP_LONG)
        self.assertEqual((code, output), (0, {}))
        # JP_LONG の日本語の文字数は144（句点「。」は数えない）
        self.assertEqual(self.records(), [{"path": str(path), "jp_chars": 144}])

    def test_counts_only_japanese_characters(self):
        path = self.write_file("a.md", "x")
        self.post(path, "abc 日本語です。 def")
        self.assertEqual(self.records()[0]["jp_chars"], 5)

    def test_text_without_kana_is_not_recorded(self):
        path = self.write_file("a.md", "x")
        self.post(path, "中文文档没有假名" * 20)
        self.assertEqual(self.records(), [])

    def test_ignores_non_target_suffix_and_lockfiles(self):
        for relative in ("a.py", "package-lock.json", "pnpm-lock.yaml"):
            self.post(self.write_file(relative, "x"), JP_LONG)
        self.assertEqual(self.records(), [])

    def test_ignores_excluded_directories_inside_repository(self):
        for relative in ("node_modules/p/README.md", "vendor/a.md", "dist/a.md", "build/a.md"):
            self.post(self.write_file(relative, "x"), JP_LONG)
        self.assertEqual(self.records(), [])

    def test_excluded_names_above_repository_root_do_not_matter(self):
        repo = self.base / "build" / "project"
        (repo / ".git").mkdir(parents=True)
        path = self.write_file("a.md", "x", root=repo)
        self.post(path, JP_LONG)
        self.assertEqual(len(self.records()), 1)

    def test_ignores_files_inside_submodule(self):
        sub = self.repo / "skills" / "ext"
        sub.mkdir(parents=True)
        (sub / ".git").write_text("gitdir: ../../.git/modules/skills/ext\n", encoding="utf-8")
        self.post(self.write_file("skills/ext/README.md", "x"), JP_LONG)
        self.assertEqual(self.records(), [])

    def test_records_files_inside_worktree(self):
        worktree = self.base / "wt"
        worktree.mkdir()
        (worktree / ".git").write_text(f"gitdir: {self.repo}/.git/worktrees/wt\n", encoding="utf-8")
        self.post(self.write_file("a.md", "x", root=worktree), JP_LONG)
        self.assertEqual(len(self.records()), 1)

    def test_ignores_reviewer_writes(self):
        self.post(self.write_file("a.md", "x"), JP_LONG, agent_type="jp-doc-reviewer")
        self.assertEqual(self.records(), [])

    def test_ignores_drafts_directory(self):
        draft = self.state / "drafts" / "s1-abc.md"
        draft.parent.mkdir(parents=True)
        draft.write_text("x", encoding="utf-8")
        self.post(draft, JP_LONG)
        self.assertEqual(self.records(), [])

    def test_symlinked_path_is_recorded_as_real_path(self):
        real = self.write_file("rules/a.md", "x")
        alias_dir = self.base / "alias"
        alias_dir.symlink_to(self.repo / "rules")
        self.post(alias_dir / "a.md", JP_HALF)
        self.post(real, JP_HALF, tool="Edit")
        self.assertEqual({record["path"] for record in self.records()}, {str(real)})

    def test_relative_path_is_resolved_against_cwd(self):
        path = self.write_file("a.md", "x")
        payload = {"session_id": "s1", "cwd": str(self.repo), "tool_name": "Write",
                   "tool_input": {"file_path": "a.md", "content": JP_LONG}}
        self.run_hook("post-tool-use", payload)
        self.assertEqual(self.records()[0]["path"], str(path))

    def test_unsafe_session_id_stays_inside_state_directory(self):
        self.post(self.write_file("a.md", "x"), JP_LONG, session="../../escape")
        written = list(self.state.rglob("*.jsonl"))
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].parent, self.state)


class ErrorTests(HookCase):
    def test_invalid_json_fails_loudly_without_blocking(self):
        code, output, stderr = self.run_hook("post-tool-use", None, raw="{broken")
        self.assertEqual((code, output), (1, {}))
        self.assertIn("jp-doc-review post-tool-use", stderr)

    def test_missing_session_id_fails_loudly(self):
        path = self.write_file("a.md", "x")
        code, _, stderr = self.run_hook("post-tool-use", {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": JP_LONG}})
        self.assertEqual(code, 1)
        self.assertIn("session_id", stderr)

    def test_unknown_event_fails(self):
        code, _, stderr = self.run_hook("unknown", {})
        self.assertEqual(code, 1)
        self.assertIn("使い方", stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

テストで使う文字列の日本語の文字数は、2026-10-02に計算して確かめた。`JP_LONG` は144、`JP_HALF` は1回で52、2回の合計で104になる。

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `env -u FORCE_COLOR python3 -m unittest tests.test_jp_doc_review_hook -v`
Expected: スクリプトが無いので、ほとんどのテストが `json.decoder.JSONDecodeError` か終了コードの不一致で FAIL / ERROR

- [ ] **Step 3: 実装を書く**

`hooks/jp-doc-review.py` を作り、実行権限を付ける（`chmod +x hooks/jp-doc-review.py`）。

```python
#!/usr/bin/env python3
"""日本語文書のレビューをjp-doc-reviewerへ依頼するClaude Codeフック。

使い方: jp-doc-review.py <post-tool-use|stop|pre-tool-use>（入力はstdinのJSON）
設計: docs/superpowers/specs/2026-10-01-jp-doc-review-design.md
判断の経緯: docs/adr/0024-jp-doc-review-hook.md
"""
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_support import emit, with_messages  # noqa: E402

MIN_JP_CHARS = 100
TARGET_SUFFIXES = {".md", ".toml", ".yaml", ".yml", ".json"}
STATE_RETENTION_DAYS = 7
REVIEWER_AGENT = "jp-doc-reviewer"
EXCLUDED_DIR_NAMES = {"node_modules", "vendor", "dist", "build", ".git"}
LOCKFILE_NAMES = {
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock",
    "composer.lock", "Pipfile.lock", "poetry.lock", "uv.lock", "Cargo.lock",
}
KANA = re.compile(r"[ぁ-ゖァ-ヺー]")
JP_CHAR = re.compile(r"[ぁ-ゖァ-ヺー々一-鿿]")
SUBMODULE_GITDIR = re.compile(r"\.git/modules/")
UNSAFE_ID_CHARS = re.compile(r"[^A-Za-z0-9_-]")


def state_dir() -> Path:
    override = os.environ.get("JP_DOC_REVIEW_STATE_DIR")
    return Path(override) if override else Path.home() / ".claude" / "state" / "jp-doc-review"


def drafts_dir() -> Path:
    return state_dir() / "drafts"


def yomiyasu_skill() -> Path:
    override = os.environ.get("JP_DOC_REVIEW_YOMIYASU_SKILL")
    return Path(override) if override else Path.home() / ".claude" / "skills" / "yomiyasu" / "SKILL.md"


def session_key(payload: dict) -> str:
    """状態ファイルの名前に使うセッションIDを返す。使えない文字を含むときはハッシュにする。"""
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("入力にsession_idが無い")
    if UNSAFE_ID_CHARS.search(session_id):
        return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
    return session_id


def count_jp_chars(text: str) -> int:
    """日本語の文字数を数える。かなを含まない文字列は、中国語と区別できないので0とみなす。"""
    if not text or not KANA.search(text):
        return 0
    return len(JP_CHAR.findall(text))


def _git_marker_kind(marker: Path) -> str:
    """.git の種類を返す。repo（通常の作業ツリーかworktree）、submodule、none のどれか。"""
    if marker.is_dir():
        return "repo"
    if not marker.is_file():
        return "none"
    try:
        first_line = marker.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    except (OSError, IndexError):
        return "repo"
    return "submodule" if SUBMODULE_GITDIR.search(first_line.replace("\\", "/")) else "repo"


def _find_git_root(path: Path) -> Tuple[Optional[Path], str]:
    for parent in path.parents:
        kind = _git_marker_kind(parent / ".git")
        if kind != "none":
            return parent, kind
    return None, "none"


def is_target(path: Path) -> bool:
    """レビューの記録対象か。pathはsymlinkを解決した絶対パスで渡す。"""
    if path.suffix not in TARGET_SUFFIXES or path.name in LOCKFILE_NAMES:
        return False
    if drafts_dir().resolve() in path.parents:
        return False
    root, kind = _find_git_root(path)
    if kind == "submodule":
        return False
    inner = path.relative_to(root).parts if root else path.parts
    return not any(part in EXCLUDED_DIR_NAMES for part in inner[:-1])


def _written_text(tool_name: str, tool_input: dict) -> Tuple[Optional[str], str]:
    if tool_name == "Write":
        return tool_input.get("file_path"), str(tool_input.get("content") or "")
    if tool_name == "Edit":
        return tool_input.get("file_path"), str(tool_input.get("new_string") or "")
    return None, ""


def _log_path(key: str) -> Path:
    return state_dir() / f"{key}.jsonl"


def _append_record(key: str, record: dict) -> None:
    """記録を1行追記する。並行した書き込みでも行が混ざらないよう、1回のwriteで書く。"""
    state_dir().mkdir(parents=True, exist_ok=True)
    line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(_log_path(key), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def read_records(key: str) -> Tuple[List[dict], int]:
    """記録と、形式が合わずに飛ばした行の数を返す。"""
    path = _log_path(key)
    if not path.exists():
        return [], 0
    records, skipped = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if isinstance(value, dict) and isinstance(value.get("path"), str) and isinstance(value.get("jp_chars"), int):
            records.append(value)
        else:
            skipped += 1
    return records, skipped


def write_records(key: str, records: List[dict]) -> None:
    path = _log_path(key)
    if not records:
        path.unlink(missing_ok=True)
        return
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def handle_post_tool_use(payload: dict) -> None:
    if payload.get("agent_type") == REVIEWER_AGENT:
        return
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    raw_path, text = _written_text(str(payload.get("tool_name", "")), tool_input)
    if not raw_path:
        return
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(str(payload.get("cwd") or ".")) / path
    path = Path(os.path.realpath(path))
    if not is_target(path):
        return
    jp_chars = count_jp_chars(text)
    if jp_chars == 0:
        return
    _append_record(session_key(payload), {"path": str(path), "jp_chars": jp_chars})


HANDLERS = {
    "post-tool-use": handle_post_tool_use,
}


def main(argv: List[str]) -> int:
    if len(argv) != 2 or argv[1] not in HANDLERS:
        print(f"使い方: {Path(argv[0]).name} <{'|'.join(HANDLERS)}>", file=sys.stderr)
        return 1
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            raise ValueError("入力がJSONオブジェクトではない")
        HANDLERS[argv[1]](payload)
    except Exception as error:  # 検査できなかったことを黙って通さず、フックのエラーとして画面に出す
        print(f"jp-doc-review {argv[1]}: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 4: テストが通ることを確かめる**

Run: `env -u FORCE_COLOR python3 -m unittest tests.test_jp_doc_review_hook -v`
Expected: すべて PASS

- [ ] **Step 5: コミットする**

```bash
git add hooks/jp-doc-review.py tests/test_jp_doc_review_hook.py
git commit -m "feat: 日本語文書の書き込みをPostToolUseで記録するフックを追加する"
```

---

### Task 5: jp-doc-review.py の集約（Stop）

**Files:**
- Modify: `hooks/jp-doc-review.py`（`handle_stop` などを足し、`HANDLERS` に `"stop"` を加える）
- Test: `tests/test_jp_doc_review_hook.py`（`StopTests` を足す）

**Interfaces:**
- Consumes: Task 3の `read_entries`、`tool_uses`、`TranscriptError`。Task 4の `read_records`、`write_records`、`read_json`、`write_json`、`session_key`、`KANA`
- Produces: Stopの出力
  - 依頼するとき `{"decision": "block", "reason": "..."}`
  - 表示だけのとき `{"systemMessage": "..."}`
  - `<key>.dispatched.json` の形 `{"paths": [str], "transcript_offset": int}`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_jp_doc_review_hook.py` の `ErrorTests` の前に足す。

```python
class StopTests(HookCase):
    def transcript(self, *entries):
        path = self.base / "transcript.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return path

    def test_blocks_and_lists_files_over_threshold(self):
        path = self.write_file("a.md", JP_LONG)
        self.post(path, JP_LONG)
        code, output, _ = self.stop(transcript=self.transcript({"type": "user", "message": {"content": "x"}}))
        self.assertEqual(code, 0)
        self.assertEqual(output["decision"], "block")
        self.assertIn(str(path), output["reason"])
        self.assertIn("jp-doc-reviewer", output["reason"])

    def test_does_not_block_below_threshold(self):
        self.post(self.write_file("a.md", JP_HALF), JP_HALF)
        self.assertEqual(self.stop()[1], {})

    def test_small_edits_accumulate_across_turns(self):
        path = self.write_file("a.md", JP_HALF)
        self.post(path, JP_HALF)
        self.assertEqual(self.stop()[1], {})
        self.post(path, JP_HALF, tool="Edit")
        self.assertEqual(self.stop()[1]["decision"], "block")

    def test_deleted_file_is_not_reviewed(self):
        path = self.write_file("a.md", JP_LONG)
        self.post(path, JP_LONG)
        path.unlink()
        self.assertEqual(self.stop()[1], {})

    def test_file_without_kana_now_is_not_reviewed(self):
        path = self.write_file("a.md", JP_LONG)
        self.post(path, JP_LONG)
        path.write_text("rewritten in english", encoding="utf-8")
        self.assertEqual(self.stop()[1], {})

    def test_missing_yomiyasu_is_reported_once_without_blocking(self):
        self.skill.unlink()
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        first = self.stop()[1]
        self.assertNotIn("decision", first)
        self.assertIn("yomiyasu", first["systemMessage"])
        self.assertEqual(self.stop()[1], {})

    def test_second_stop_clears_and_warns_when_reviewer_was_not_invoked(self):
        transcript = self.transcript({"type": "user", "message": {"content": "x"}})
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        self.assertEqual(self.stop(transcript=transcript)[1]["decision"], "block")
        code, output, _ = self.stop(active=True, transcript=transcript)
        self.assertEqual(code, 0)
        self.assertNotIn("decision", output)
        self.assertIn("jp-doc-reviewer", output["systemMessage"])
        self.assertEqual(self.records(), [])
        self.assertEqual(self.stop(transcript=transcript)[1], {})

    def test_second_stop_is_quiet_when_reviewer_was_invoked(self):
        transcript = self.transcript({"type": "user", "message": {"content": "x"}})
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        self.stop(transcript=transcript)
        self.transcript(agent_call("jp-doc-reviewer"))
        self.assertEqual(self.stop(active=True, transcript=transcript)[1], {})

    def test_reviewer_call_before_dispatch_does_not_count(self):
        transcript = self.transcript(agent_call("jp-doc-reviewer"))
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        self.stop(transcript=transcript)
        self.assertIn("systemMessage", self.stop(active=True, transcript=transcript)[1])

    def test_active_stop_without_our_dispatch_is_silent(self):
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        self.assertEqual(self.stop(active=True)[1], {})
        self.assertEqual(len(self.records()), 1)

    def test_unreadable_transcript_on_second_stop_is_reported(self):
        transcript = self.transcript({"type": "user", "message": {"content": "x"}})
        self.post(self.write_file("a.md", JP_LONG), JP_LONG)
        self.stop(transcript=transcript)
        transcript.unlink()
        output = self.stop(active=True, transcript=transcript)[1]
        self.assertIn("確認できなかった", output["systemMessage"])

    def test_broken_log_lines_are_counted_in_message(self):
        self.state.mkdir(parents=True)
        (self.state / "s1.jsonl").write_text("{broken\n", encoding="utf-8")
        self.assertIn("1件", self.stop()[1]["systemMessage"])

    def test_old_state_files_are_removed(self):
        self.state.mkdir(parents=True)
        old = self.state / "old-session.jsonl"
        old.write_text("", encoding="utf-8")
        eight_days_ago = time.time() - 8 * 86400
        os.utime(old, (eight_days_ago, eight_days_ago))
        self.stop()
        self.assertFalse(old.exists())
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `env -u FORCE_COLOR python3 -m unittest tests.test_jp_doc_review_hook.StopTests -v`
Expected: `使い方` のエラー（`stop` がまだ無い）で FAIL

- [ ] **Step 3: 実装を書く**

`hooks/jp-doc-review.py` のimport文を次に変える。

```python
from hook_support import TranscriptError, emit, read_entries, tool_uses, with_messages  # noqa: E402
```

定数に足す。

```python
AGENT_TOOL_NAMES = {"Agent", "Task"}  # 古い版ではサブエージェントの起動ツールがTaskという名前だった
```

`handle_post_tool_use` の後に足す。

```python
def _dispatched_path(key: str) -> Path:
    return state_dir() / f"{key}.dispatched.json"


def _flags_path(key: str) -> Path:
    return state_dir() / f"{key}.flags.json"


def _mark_once(key: str, flag: str) -> bool:
    """初めて立てるフラグなら記録してTrueを返す。2回目以降はFalse。"""
    flags = read_json(_flags_path(key))
    if flags.get(flag):
        return False
    write_json(_flags_path(key), {**flags, flag: True})
    return True


def cleanup_old_state() -> None:
    limit = time.time() - STATE_RETENTION_DAYS * 86400
    for directory in (state_dir(), drafts_dir()):
        if not directory.is_dir():
            continue
        for entry in directory.iterdir():
            if entry.is_file() and entry.stat().st_mtime < limit:
                entry.unlink(missing_ok=True)


def _review_candidates(records: List[dict]) -> List[str]:
    totals: Dict[str, int] = {}
    for record in records:
        totals[record["path"]] = totals.get(record["path"], 0) + record["jp_chars"]
    candidates = []
    for path, total in sorted(totals.items()):
        file = Path(path)
        if total < MIN_JP_CHARS or not file.is_file():
            continue
        if KANA.search(file.read_text(encoding="utf-8", errors="replace")):
            candidates.append(path)
    return candidates


def _transcript_size(payload: dict) -> int:
    path = payload.get("transcript_path")
    try:
        return os.path.getsize(path) if path else 0
    except OSError:
        return 0


def _dispatch_reason(paths: List[str]) -> str:
    listed = "\n".join(f"- {path}" for path in paths)
    return (
        "日本語の文書を書いたので、作業を終える前にレビューが要る。\n"
        f"Agentツールで subagent_type が {REVIEWER_AGENT} のサブエージェントを1回起動し、次のファイルをまとめて渡して。\n"
        f"{listed}\n"
        "レビュワーの報告を受けたら、変えた点と書き手に確かめたい点をユーザーに伝えてから作業を終えて。"
    )


def _finish_dispatch(key: str, payload: dict) -> None:
    """2回目のStop。依頼した記録を消し、レビュワーが起動したかを確かめる。"""
    dispatched = read_json(_dispatched_path(key))
    paths = [path for path in dispatched.get("paths", []) if isinstance(path, str)]
    if not paths:
        return  # 別のフックのblockで続いた回。こちらは何も依頼していない
    records, _ = read_records(key)
    write_records(key, [record for record in records if record["path"] not in set(paths)])
    _dispatched_path(key).unlink(missing_ok=True)
    try:
        entries = read_entries(payload.get("transcript_path"), int(dispatched.get("transcript_offset", 0)))
    except TranscriptError as error:
        emit({"systemMessage": f"jp-doc-reviewerが起動したかを確認できなかった（{error}）"})
        return
    invoked = any(
        name in AGENT_TOOL_NAMES and tool_input.get("subagent_type") == REVIEWER_AGENT
        for name, tool_input in tool_uses(entries)
    )
    if not invoked:
        names = "、".join(Path(path).name for path in paths)
        emit({"systemMessage": f"jp-doc-reviewerが起動されないまま作業が終わった。レビューされていない文書: {names}"})


def handle_stop(payload: dict) -> None:
    key = session_key(payload)
    cleanup_old_state()
    if payload.get("stop_hook_active"):
        _finish_dispatch(key, payload)
        return
    records, skipped = read_records(key)
    messages = [f"日本語文書レビューの記録で、読めない行を{skipped}件飛ばした"] if skipped else []
    candidates = _review_candidates(records)
    if not candidates:
        emit(with_messages({}, messages))
        return
    if not yomiyasu_skill().is_file():
        if _mark_once(key, "missing-yomiyasu"):
            messages.append(
                "yomiyasuが見つからないため、日本語文書のレビューを省略した。"
                "skills/yomiyasu のsubmoduleとsetup.shの実行状態を確かめてほしい"
            )
        emit(with_messages({}, messages))
        return
    write_json(_dispatched_path(key), {"paths": candidates, "transcript_offset": _transcript_size(payload)})
    emit(with_messages({"decision": "block", "reason": _dispatch_reason(candidates)}, messages))
```

`HANDLERS` に `"stop": handle_stop,` を足す。

- [ ] **Step 4: テストが通ることを確かめる**

Run: `env -u FORCE_COLOR python3 -m unittest tests.test_jp_doc_review_hook -v`
Expected: すべて PASS

- [ ] **Step 5: コミットする**

```bash
git add hooks/jp-doc-review.py tests/test_jp_doc_review_hook.py
git commit -m "feat: 作業の終わりに日本語文書のレビューをjp-doc-reviewerへ依頼する"
```

---

### Task 6: jp-doc-review.py のConfluenceの事前チェック（PreToolUse）

**Files:**
- Modify: `hooks/jp-doc-review.py`（`handle_pre_tool_use` などを足し、`HANDLERS` に `"pre-tool-use"` を加える）
- Test: `tests/test_jp_doc_review_hook.py`（`ConfluenceTests` を足す）

**Interfaces:**
- Consumes: Task 4の `count_jp_chars`、`session_key`、`read_json`、`write_json`、`drafts_dir`
- Produces: 1回目の出力 `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "..."}}`、下書き `<state>/drafts/<key>-<sha256の先頭12文字><拡張子>`、`<key>.confluence.json` の形 `{"<投稿先キー>": "<本文のsha256>"}`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_jp_doc_review_hook.py` の `ErrorTests` の前に足す。

```python
class ConfluenceTests(HookCase):
    TOOL = "mcp__atlassian-http__createConfluencePage"

    def pre(self, body, title="", tool=None, **tool_input):
        payload = {"session_id": "s1", "tool_name": tool or self.TOOL,
                   "tool_input": {"cloudId": "c", "spaceId": "1", "title": title, "body": body, **tool_input}}
        return self.run_hook("pre-tool-use", payload)

    def test_short_japanese_passes(self):
        self.assertEqual(self.pre("短い本文です。"), (0, {}, ""))

    def test_first_post_is_denied_with_draft(self):
        code, output, _ = self.pre(f"<p>{JP_LONG}</p>", contentFormat="html")
        decision = output["hookSpecificOutput"]
        self.assertEqual((code, decision["permissionDecision"]), (0, "deny"))
        drafts = list((self.state / "drafts").iterdir())
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].suffix, ".html")
        self.assertEqual(drafts[0].read_text(encoding="utf-8"), f"<p>{JP_LONG}</p>")
        self.assertIn(str(drafts[0]), decision["permissionDecisionReason"])

    def test_draft_suffix_follows_content_format(self):
        self.pre(JP_LONG, contentFormat="markdown", pageId="1")
        self.pre(JP_LONG + "。", contentFormat="adf", pageId="2")
        self.pre(JP_LONG + "、", pageId="3")
        suffixes = sorted(path.suffix for path in (self.state / "drafts").iterdir())
        self.assertEqual(suffixes, [".html", ".json", ".md"])

    def test_title_counts_toward_threshold(self):
        self.assertEqual(self.pre("本文。", title=JP_LONG)[1]["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_second_post_passes_and_warns_when_unchanged(self):
        self.pre(JP_LONG, pageId="9")
        code, output, _ = self.pre(JP_LONG, pageId="9")
        self.assertEqual(code, 0)
        self.assertNotIn("hookSpecificOutput", output)
        self.assertIn("レビューを通らない", output["systemMessage"])

    def test_second_post_with_reviewed_body_is_silent(self):
        self.pre(JP_LONG, pageId="9")
        self.assertEqual(self.pre(JP_LONG.replace("テスト用", "確認用"), pageId="9")[1], {})

    def test_targets_are_tracked_separately(self):
        self.pre(JP_LONG, pageId="1")
        denied = self.pre(JP_LONG, pageId="2")[1]
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_after_passing_the_same_target_is_checked_again(self):
        self.pre(JP_LONG, pageId="1")
        self.pre(JP_LONG + "。", pageId="1")
        self.assertEqual(self.pre(JP_LONG + "、", pageId="1")[1]["hookSpecificOutput"]["permissionDecision"], "deny")
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `env -u FORCE_COLOR python3 -m unittest tests.test_jp_doc_review_hook.ConfluenceTests -v`
Expected: `使い方` のエラー（`pre-tool-use` がまだ無い）で FAIL

- [ ] **Step 3: 実装を書く**

定数に足す。

```python
DRAFT_SUFFIXES = {"markdown": ".md", "adf": ".json"}  # それ以外（html、指定なし）は .html
```

`handle_stop` の後に足す。

```python
def _confluence_path(key: str) -> Path:
    return state_dir() / f"{key}.confluence.json"


def _confluence_target(tool_name: str, tool_input: dict) -> str:
    for field in ("pageId", "parentCommentId", "title"):
        value = tool_input.get(field)
        if value:
            return f"{tool_name}:{field}:{value}"
    return f"{tool_name}:none"


def _write_draft(key: str, digest: str, body: str, content_format: object) -> Path:
    suffix = DRAFT_SUFFIXES.get(str(content_format or ""), ".html")
    path = drafts_dir() / f"{key}-{digest[:12]}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _confluence_reason(draft: Path) -> str:
    return (
        "Confluenceへ送る前に、日本語のレビューが要る。この投稿はまだ送っていない。\n"
        f"本文を下書き {draft} に書き出した。\n"
        f"Agentツールで subagent_type が {REVIEWER_AGENT} のサブエージェントを起動してこの下書きを渡し、文章だけを直させて。"
        "HTMLのタグ、data-* 属性、ADFの構造は変えさせないこと。\n"
        "直した下書きの内容で、同じツールを同じ投稿先へもう一度呼んで投稿して。"
    )


def handle_pre_tool_use(payload: dict) -> None:
    tool_name = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    body = str(tool_input.get("body") or "")
    title = str(tool_input.get("title") or "")
    if count_jp_chars(f"{title}\n{body}") < MIN_JP_CHARS:
        return
    key = session_key(payload)
    target = _confluence_target(tool_name, tool_input)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    state = read_json(_confluence_path(key))
    first_digest = state.pop(target, None)
    if first_digest is None:
        draft = _write_draft(key, digest, body, tool_input.get("contentFormat"))
        write_json(_confluence_path(key), {**state, target: digest})
        emit({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": _confluence_reason(draft),
        }})
        return
    write_json(_confluence_path(key), state)
    if first_digest == digest:
        emit({"systemMessage": f"Confluenceへの投稿が、日本語のレビューを通らないまま送られた（{tool_name}）"})
```

`HANDLERS` に `"pre-tool-use": handle_pre_tool_use,` を足す。

- [ ] **Step 4: テストが通ることを確かめる**

Run: `env -u FORCE_COLOR python3 -m unittest tests.test_jp_doc_review_hook -v`
Expected: すべて PASS

- [ ] **Step 5: コミットする**

```bash
git add hooks/jp-doc-review.py tests/test_jp_doc_review_hook.py
git commit -m "feat: Confluenceへの日本語の投稿を1回止めて下書きのレビューを求める"
```

---

### Task 7: skill-read-check.py と必読資料の対応表

**Files:**
- Create: `hooks/skill-read-check.py`
- Create: `manifests/skill-required-reads.json`
- Test: `tests/test_skill_read_check.py`

**Interfaces:**
- Consumes: Task 3の `read_entries`、`after_last_compact`、`since_last_prompt`、`tool_uses`、`emit`、`with_messages`、`TranscriptError`。Task 2の `skills/yomiyasu/references/`
- Produces: 使い方 `skill-read-check.py <stop|subagent-stop>`。対応表の形

```json
{"schemaVersion": 1, "skills": {"<スキル名>": {"root": "<パス>", "allOf": ["<rootからの相対パス>"], "anyOf": [["<相対パス>", "<相対パス>"]]}}}
```

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_skill_read_check.py` を作る。

```python
#!/usr/bin/env python3
"""hooks/skill-read-check.py と manifests/skill-required-reads.json を検証する。

実行: python3 -m unittest tests.test_skill_read_check
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "skill-read-check.py"
MANIFEST = REPO_ROOT / "manifests" / "skill-required-reads.json"
COMPACT = {"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted"}


def prompt(text="go"):
    return {"type": "user", "message": {"role": "user", "content": text}}


def call(name, **tool_input):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": tool_input}]}}


class SkillReadCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "skills" / "demo"
        for relative in ("SKILL.md", "references/a.md", "references/b.md",
                         "references/domains/x.md", "references/domains/y.md"):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")
        self.alias = self.base / "alias-demo"
        self.alias.symlink_to(self.root)
        self.manifest = self.base / "manifest.json"
        self.manifest.write_text(json.dumps({"schemaVersion": 1, "skills": {"demo": {
            "root": str(self.alias),
            "allOf": ["references/a.md", "references/b.md"],
            "anyOf": [["references/domains/x.md", "references/domains/y.md"]],
        }}}), encoding="utf-8")
        self.transcript_path = self.base / "t.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def transcript(self, *entries):
        with self.transcript_path.open("a", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def reads(self, *relatives, root=None):
        return [call("Read", file_path=str((root or self.root) / relative)) for relative in relatives]

    def run_hook(self, event="stop", active=False):
        key = "agent_transcript_path" if event == "subagent-stop" else "transcript_path"
        payload = {"session_id": "s1", key: str(self.transcript_path), "stop_hook_active": active}
        env = {**os.environ, "SKILL_READ_CHECK_MANIFEST": str(self.manifest)}
        env.pop("FORCE_COLOR", None)
        result = subprocess.run([sys.executable, str(HOOK), event], input=json.dumps(payload),
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def test_not_invoked_is_silent(self):
        self.transcript(prompt(), *self.reads("references/a.md"))
        self.assertEqual(self.run_hook(), {})

    def test_all_required_reads_present_is_silent(self):
        self.transcript(prompt(), call("Skill", skill="demo"),
                        *self.reads("references/a.md", "references/b.md", "references/domains/y.md"))
        self.assertEqual(self.run_hook(), {})

    def test_missing_read_blocks_with_full_path(self):
        self.transcript(prompt(), call("Skill", skill="demo"), *self.reads("references/a.md", "references/domains/x.md"))
        output = self.run_hook()
        self.assertEqual(output["decision"], "block")
        self.assertIn(str(self.root / "references" / "b.md"), output["reason"])
        self.assertNotIn("a.md", output["reason"].replace("b.md", ""))

    def test_missing_any_of_group_is_reported_once(self):
        self.transcript(prompt(), call("Skill", skill="demo"), *self.reads("references/a.md", "references/b.md"))
        reason = self.run_hook()["reason"]
        self.assertIn("x.md", reason)
        self.assertIn("y.md", reason)
        self.assertIn("のうち1つ", reason)

    def test_plugin_style_skill_name_counts(self):
        self.transcript(prompt(), call("Skill", skill="plugin:demo"))
        self.assertEqual(self.run_hook()["decision"], "block")

    def test_reading_skill_md_through_symlink_counts_as_invocation(self):
        self.transcript(prompt(), *self.reads("SKILL.md", root=self.alias))
        self.assertEqual(self.run_hook()["decision"], "block")

    def test_reads_through_symlink_satisfy_requirements(self):
        self.transcript(prompt(), call("Skill", skill="demo"),
                        *self.reads("references/a.md", "references/b.md", "references/domains/x.md", root=self.alias))
        self.assertEqual(self.run_hook(), {})

    def test_reads_before_compact_do_not_count(self):
        self.transcript(*self.reads("references/a.md", "references/b.md", "references/domains/x.md"),
                        COMPACT, prompt(), call("Skill", skill="demo"))
        self.assertEqual(self.run_hook()["decision"], "block")

    def test_reads_from_earlier_turn_after_compact_count(self):
        self.transcript(prompt("1"), *self.reads("references/a.md", "references/b.md", "references/domains/x.md"),
                        prompt("2"), call("Skill", skill="demo"))
        self.assertEqual(self.run_hook(), {})

    def test_invocation_in_earlier_turn_is_not_checked_on_main_stop(self):
        self.transcript(prompt("1"), call("Skill", skill="demo"), prompt("2"))
        self.assertEqual(self.run_hook(), {})

    def test_second_stop_passes_with_message(self):
        self.transcript(prompt(), call("Skill", skill="demo"))
        output = self.run_hook(active=True)
        self.assertNotIn("decision", output)
        self.assertIn("読まれないまま", output["systemMessage"])

    def test_subagent_stop_checks_whole_subagent_transcript(self):
        self.transcript(prompt("task"), call("Skill", skill="demo"), prompt("follow-up"))
        self.assertEqual(self.run_hook("subagent-stop")["decision"], "block")

    def test_stale_manifest_entry_is_reported(self):
        (self.root / "references" / "b.md").unlink()
        self.transcript(prompt(), call("Skill", skill="demo"),
                        *self.reads("references/a.md", "references/domains/x.md"))
        output = self.run_hook()
        self.assertNotIn("decision", output)
        self.assertIn("対応表が古い", output["systemMessage"])

    def test_unreadable_transcript_is_reported(self):
        self.transcript_path.write_text("not json\n", encoding="utf-8")
        self.assertIn("確認していない", self.run_hook()["systemMessage"])

    def test_unreadable_manifest_is_reported(self):
        self.manifest.write_text("{", encoding="utf-8")
        self.transcript(prompt())
        self.assertIn("対応表を読めなかった", self.run_hook()["systemMessage"])


class RepositoryManifestTests(unittest.TestCase):
    def test_yomiyasu_entry_points_to_existing_files_in_submodule(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schemaVersion"], 1)
        entry = manifest["skills"]["yomiyasu"]
        self.assertEqual(entry["root"], "~/.claude/skills/yomiyasu")
        submodule = REPO_ROOT / "skills" / "yomiyasu"
        for relative in entry["allOf"] + [item for group in entry["anyOf"] for item in group]:
            with self.subTest(relative=relative):
                self.assertTrue((submodule / relative).is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `env -u FORCE_COLOR python3 -m unittest tests.test_skill_read_check -v`
Expected: スクリプトと対応表が無いので FAIL / ERROR

- [ ] **Step 3: 対応表を書く**

`manifests/skill-required-reads.json` を作る。

```json
{
  "schemaVersion": 1,
  "skills": {
    "yomiyasu": {
      "root": "~/.claude/skills/yomiyasu",
      "allOf": [
        "references/gemini-syntax.md",
        "references/slop-catalog.md"
      ],
      "anyOf": [
        [
          "references/domains/tech.md",
          "references/domains/business.md",
          "references/domains/essay.md"
        ]
      ]
    }
  }
}
```

- [ ] **Step 4: 実装を書く**

`hooks/skill-read-check.py` を作り、実行権限を付ける（`chmod +x hooks/skill-read-check.py`）。

```python
#!/usr/bin/env python3
"""スキルを呼んだのに必読資料を読んでいないことを、会話記録で見つけるClaude Codeフック。

使い方: skill-read-check.py <stop|subagent-stop>（入力はstdinのJSON）
対応表: manifests/skill-required-reads.json
設計: docs/superpowers/specs/2026-10-01-jp-doc-review-design.md の5節

確かめられるのは「読んだかどうか」だけで、読んだ内容に従ったかは確かめられない。
"""
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_support import (  # noqa: E402
    TranscriptError, after_last_compact, emit, read_entries, since_last_prompt, tool_uses, with_messages,
)

DEFAULT_MANIFEST = Path(__file__).resolve().parent.parent / "manifests" / "skill-required-reads.json"
EVENTS = {"stop": "transcript_path", "subagent-stop": "agent_transcript_path"}


def manifest_path() -> Path:
    override = os.environ.get("SKILL_READ_CHECK_MANIFEST")
    return Path(override) if override else DEFAULT_MANIFEST


def load_manifest() -> Dict[str, dict]:
    value = json.loads(manifest_path().read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schemaVersion") != 1 or not isinstance(value.get("skills"), dict):
        raise ValueError("skill-required-reads.json の形式が不正")
    return value["skills"]


def real(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path))


def read_paths(entries: List[dict]) -> Set[str]:
    return {
        real(tool_input["file_path"])
        for name, tool_input in tool_uses(entries)
        if name == "Read" and isinstance(tool_input.get("file_path"), str)
    }


def invoked_skills(manifest: Dict[str, dict], window: List[dict]) -> List[str]:
    """windowの中で呼ばれた登録済みのスキル。Skillの呼び出しか、SKILL.mdのReadで判定する。"""
    called = {str(tool_input.get("skill", "")).split(":")[-1] for name, tool_input in tool_uses(window) if name == "Skill"}
    window_reads = read_paths(window)
    return [
        name for name, entry in manifest.items()
        if name in called or os.path.join(real(entry["root"]), "SKILL.md") in window_reads
    ]


def missing_reads(entry: dict, reads: Set[str]) -> Tuple[List[str], List[str]]:
    """読まれていない必読資料（フルパス）と、ディスクに無い資料（対応表が古い）を返す。"""
    root = real(entry["root"])
    missing, stale = [], []
    for relative in entry.get("allOf", []):
        full = os.path.realpath(os.path.join(root, relative))
        if not os.path.exists(full):
            stale.append(relative)
        elif full not in reads:
            missing.append(full)
    for group in entry.get("anyOf", []):
        existing = [os.path.realpath(os.path.join(root, relative)) for relative in group]
        existing = [full for full in existing if os.path.exists(full)]
        if not existing:
            stale.append(" / ".join(group))
        elif not any(full in reads for full in existing):
            missing.append(" / ".join(existing) + " のうち1つ")
    return missing, stale


def _block_reason(problems: Dict[str, List[str]]) -> str:
    lines = ["スキルを呼んだのに、そのスキルが読むよう求める資料をまだ読んでいない。"
             "作業を終える前に、次の資料をReadで全文読み、その基準で作業を見直して。"]
    for name, missing in problems.items():
        lines.extend(f"- {name}: {item}" for item in missing)
    return "\n".join(lines)


def check(event: str, payload: dict) -> None:
    try:
        manifest = load_manifest()
    except (OSError, ValueError) as error:
        emit({"systemMessage": f"スキルの読み込み確認: 対応表を読めなかった（{error}）"})
        return
    try:
        entries = after_last_compact(read_entries(payload.get(EVENTS[event])))
    except TranscriptError as error:
        emit({"systemMessage": f"スキルの読み込み確認: 会話記録を読めなかったので確認していない（{error}）"})
        return
    window = entries if event == "subagent-stop" else since_last_prompt(entries)
    reads = read_paths(entries)
    problems: Dict[str, List[str]] = {}
    messages: List[str] = []
    for name in invoked_skills(manifest, window):
        missing, stale = missing_reads(manifest[name], reads)
        if stale:
            messages.append(f"スキルの読み込み確認: {name} の対応表が古い。ディスクに無い資料: {', '.join(stale)}")
        if missing:
            problems[name] = missing
    if problems and not payload.get("stop_hook_active"):
        emit(with_messages({"decision": "block", "reason": _block_reason(problems)}, messages))
        return
    if problems:
        summary = "; ".join(f"{name}（{', '.join(Path(item).name for item in missing)}）" for name, missing in problems.items())
        messages.append(f"スキルの必読資料が読まれないまま作業が終わった: {summary}")
    emit(with_messages({}, messages))


def main(argv: List[str]) -> int:
    if len(argv) != 2 or argv[1] not in EVENTS:
        print(f"使い方: {Path(argv[0]).name} <{'|'.join(EVENTS)}>", file=sys.stderr)
        return 1
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            raise ValueError("入力がJSONオブジェクトではない")
        check(argv[1], payload)
    except Exception as error:  # 検査できなかったことを黙って通さず、フックのエラーとして画面に出す
        print(f"skill-read-check {argv[1]}: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 5: テストが通ることを確かめる**

Run: `env -u FORCE_COLOR python3 -m unittest tests.test_skill_read_check -v`
Expected: すべて PASS

- [ ] **Step 6: コミットする**

```bash
git add hooks/skill-read-check.py manifests/skill-required-reads.json tests/test_skill_read_check.py
git commit -m "feat: スキルの必読資料の読み漏れを会話記録で見つけるフックを追加する"
```

---

### Task 8: レビュー用サブエージェント jp-doc-reviewer

**Files:**
- Create: `agents/jp-doc-reviewer.md`
- Modify: `bin/generate-codex-agents.py`（`CODEX_AGENT_PROFILES` に1行足す）
- Create（生成）: `codex/agents/jp-doc-reviewer.toml`
- Test: `tests/test_codex_agents.py`（既存のテストで生成物のずれを検出する）、`tests/test_jp_doc_review_wiring.py`（Task 9で作る。ここではagent定義の契約だけを先に足す）

**Interfaces:**
- Produces: agent名 `jp-doc-reviewer`（`REVIEWER_AGENT` と一致させる）、tools `[Read, Edit, Bash]`、model `opus`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_jp_doc_review_wiring.py` を作る（Task 9で配線のテストを足す）。

```python
#!/usr/bin/env python3
"""日本語文書レビューのagent定義と、settings.json.template の配線を検証する。

実行: python3 -m unittest tests.test_jp_doc_review_wiring
"""
import importlib.util
import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT = REPO_ROOT / "agents" / "jp-doc-reviewer.md"

_spec = importlib.util.spec_from_file_location("codex_agents", REPO_ROOT / "bin" / "generate-codex-agents.py")
codex_agents = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(codex_agents)


class ReviewerAgentTests(unittest.TestCase):
    def setUp(self):
        self.meta, self.body = codex_agents.parse_frontmatter(AGENT.read_text(encoding="utf-8"))

    def test_name_tools_and_model(self):
        self.assertEqual(self.meta["name"], "jp-doc-reviewer")
        self.assertEqual(set(codex_agents.parse_tools(self.meta["tools"])), {"Read", "Edit", "Bash"})
        self.assertEqual(self.meta["model"], "opus")

    def test_body_requires_reading_all_references_before_rewriting(self):
        for marker in ("references/gemini-syntax.md", "references/slop-catalog.md", "references/domains/",
                       "主張", "比重", "言い切りの強さ", "文の働き", "yomiyasu_lint.py"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.body)

    def test_body_lists_what_must_not_change(self):
        for marker in ("★", "コード", "URL", "テスト", "data-*"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `env -u FORCE_COLOR python3 -m unittest tests.test_jp_doc_review_wiring -v`
Expected: `FileNotFoundError`（`agents/jp-doc-reviewer.md` が無い）で ERROR

- [ ] **Step 3: agent定義を書く**

`agents/jp-doc-reviewer.md` を作る。本文は日本語の文書なので、書いた後にyomiyasuの手順で見直す。

```markdown
---
name: jp-doc-reviewer
description: Reviews Japanese documents (Markdown, config files, Confluence drafts) with the yomiyasu skill and rewrites them into natural Japanese without changing their meaning. Use when a hook or the user asks to review Japanese documents.
tools: [Read, Edit, Bash]
model: opus
color: green
---

# 日本語文書レビュワー

渡されたファイルの日本語を、yomiyasuの基準で自然な日本語に直す。言っていることは変えない。

## 手順

1. yomiyasuの `SKILL.md` を読む。置き場は `~/.claude/skills/yomiyasu/`
2. `SKILL.md` が参照する資料を、書き直す前にすべて読む
   - `references/gemini-syntax.md`（構文変換の原則）
   - `references/slop-catalog.md`（語彙と構文のカタログ）
   - `references/domains/` のうち、対象のドメインの仕様（tech、business、essay）
3. ファイルごとにドメインを決め、書き直す前に、元の文の主張・比重・言い切りの強さ・文の働きを確かめる
4. この4点を変えずに書き直し、書き直した後にもう一度4点を確かめる
5. `python3 ~/.claude/skills/yomiyasu/scripts/yomiyasu_lint.py <ファイル>` で確かめる。指摘を消すためだけの言い換えはしない

`SKILL.md` を読んだだけで、手順を実行したことにはならない。資料を読む前に書き直しを始めない。

## 変えないもの

- エージェント向けの指示ファイル（CLAUDE.md、`rules/`、`skills/`、`agents/`、`output-styles/`）の★ブロック、表、太字、箇条書き
- コード、識別子、URL、パス、コマンド
- テストやgrepが参照している文言
- Confluenceの下書きにあるHTMLのタグ、`data-*` 属性、ADFの構造

## 報告

メインのエージェントには、ファイルごとに次だけを返す。書き直した本文は返さない。

- 変えた点（短く）
- 書き手に確かめたい点（迷った点がある場合だけ、最大2点）
```

- [ ] **Step 4: Codex用の定義を生成する**

`bin/generate-codex-agents.py` の `CODEX_AGENT_PROFILES` に1行足す（辞書順の位置に入れる）。

```python
    "jp-doc-reviewer": ("gpt-6-sol", "high"),
```

```bash
python3 bin/generate-codex-agents.py
```

Expected: `生成: codex/agents/jp-doc-reviewer.toml` が出る。書き込み系のツール（Edit）を持つので `sandbox_mode = 'workspace-write'` になる

- [ ] **Step 5: テストが通ることを確かめる**

Run: `env -u FORCE_COLOR python3 -m unittest tests.test_jp_doc_review_wiring tests.test_codex_agents -v`
Expected: すべて PASS

- [ ] **Step 6: agent定義の本文をyomiyasuの手順で見直す**

`agents/jp-doc-reviewer.md` の本文を、yomiyasuの `SKILL.md` と参照資料の基準で1文ずつ見直し、リンターをかける。
直したら `python3 bin/generate-codex-agents.py` で生成し直し、Step 5のテストをもう一度通す。

- [ ] **Step 7: コミットする**

```bash
git add agents/jp-doc-reviewer.md bin/generate-codex-agents.py codex/agents/jp-doc-reviewer.toml tests/test_jp_doc_review_wiring.py
git commit -m "feat: yomiyasuで日本語文書を直すレビュー用サブエージェントを追加する"
```

---

### Task 9: settings.json.template の配線とREADME

**Files:**
- Modify: `settings.json.template`（`hooks`）
- Modify: `README.md`（ディレクトリ構成）
- Test: `tests/test_jp_doc_review_wiring.py`（`WiringTests` を足す）

**Interfaces:**
- Consumes: Task 4〜7のスクリプトとイベント名

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_jp_doc_review_wiring.py` の `if __name__` の前に足す。

```python
SETTINGS = json.loads((REPO_ROOT / "settings.json.template").read_text(encoding="utf-8"))
CONFLUENCE_MATCHER = "mcp__.*__(create|update)Confluence(Page|FooterComment|InlineComment)"


def commands(event, matcher=None):
    found = []
    for group in SETTINGS["hooks"].get(event, []):
        if matcher is not None and group.get("matcher") != matcher:
            continue
        found.extend(hook["command"] for hook in group["hooks"])
    return found


class WiringTests(unittest.TestCase):
    def test_post_tool_use_records_writes_and_edits(self):
        self.assertIn("python3 ~/.claude/hooks/jp-doc-review.py post-tool-use", commands("PostToolUse", "Write|Edit"))

    def test_confluence_matcher_catches_only_posting_tools(self):
        self.assertIn("python3 ~/.claude/hooks/jp-doc-review.py pre-tool-use", commands("PreToolUse", CONFLUENCE_MATCHER))
        pattern = re.compile(f"^(?:{CONFLUENCE_MATCHER})$")
        for name in ("createConfluencePage", "updateConfluencePage",
                     "createConfluenceFooterComment", "createConfluenceInlineComment"):
            with self.subTest(name=name):
                self.assertTrue(pattern.match(f"mcp__atlassian-http__{name}"))
        self.assertFalse(pattern.match("mcp__atlassian-http__getConfluencePage"))

    def test_existing_bash_guards_are_kept(self):
        self.assertIn("~/.claude/hooks/guard-dangerous-bash.sh", commands("PreToolUse", "Bash"))

    def test_stop_runs_review_and_read_check(self):
        stop = commands("Stop")
        self.assertIn("python3 ~/.claude/hooks/jp-doc-review.py stop", stop)
        self.assertIn("python3 ~/.claude/hooks/skill-read-check.py stop", stop)

    def test_subagent_stop_runs_read_check(self):
        self.assertIn("python3 ~/.claude/hooks/skill-read-check.py subagent-stop", commands("SubagentStop"))

    def test_codex_wiring_is_untouched(self):
        codex = (REPO_ROOT / "codex" / "hooks.json").read_text(encoding="utf-8")
        self.assertNotIn("jp-doc-review", codex)
        self.assertNotIn("skill-read-check", codex)
```

- [ ] **Step 2: テストが失敗することを確かめる**

Run: `env -u FORCE_COLOR python3 -m unittest tests.test_jp_doc_review_wiring.WiringTests -v`
Expected: `KeyError` か `AssertionError`（配線がまだ無い）で FAIL

- [ ] **Step 3: 配線を書く**

`settings.json.template` の `hooks` を次の形にする。既存の `PreToolUse`（Bash）と `SessionStart` はそのまま残す。

```json
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {"type": "command", "command": "~/.claude/hooks/guard-dangerous-bash.sh", "timeout": 30},
          {"type": "command", "command": "rtk hook claude"},
          {"type": "command", "command": "~/.claude/hooks/warn-branch-behind-main.sh", "timeout": 30}
        ]
      },
      {
        "matcher": "mcp__.*__(create|update)Confluence(Page|FooterComment|InlineComment)",
        "hooks": [
          {"type": "command", "command": "python3 ~/.claude/hooks/jp-doc-review.py pre-tool-use", "timeout": 10}
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {"type": "command", "command": "python3 ~/.claude/hooks/jp-doc-review.py post-tool-use", "timeout": 10}
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {"type": "command", "command": "python3 ~/.claude/hooks/jp-doc-review.py stop", "timeout": 10},
          {"type": "command", "command": "python3 ~/.claude/hooks/skill-read-check.py stop", "timeout": 10}
        ]
      }
    ],
    "SubagentStop": [
      {
        "hooks": [
          {"type": "command", "command": "python3 ~/.claude/hooks/skill-read-check.py subagent-stop", "timeout": 10}
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          {"type": "command", "command": "~/.claude/hooks/detect-parallel-sessions.sh", "timeout": 10}
        ]
      }
    ]
  }
```

ファイル全体の整形は既存の書き方（インデント1段で1キー1行）に合わせる。

`README.md` のディレクトリ構成に足す。

- `skills/` の一覧の末尾に `│   └── yomiyasu/                #   日本語文書の書き直し（git submodule）`（直前の行の `└──` を `├──` に変える）
- `agents/` の一覧に `│   ├── jp-doc-reviewer.md       #   日本語文書のレビュー（opus、yomiyasu）`
- `hooks/` の一覧に次の3行
  - `│   ├── hook_support.py          #   会話記録の読み取りと出力の補助`
  - `│   ├── jp-doc-review.py         #   日本語文書の記録・レビュー依頼・Confluenceの事前チェック`
  - `│   ├── skill-read-check.py      #   スキルの必読資料の読み漏れ確認`

- [ ] **Step 4: テストが通ることを確かめる**

Run: `env -u FORCE_COLOR python3 -m unittest tests.test_jp_doc_review_wiring tests.test_learning_mode_contract tests.test_setup_cli -v`
Expected: すべて PASS（`test_setup_cli` は数分かかる）

- [ ] **Step 5: コミットする**

```bash
git add settings.json.template README.md tests/test_jp_doc_review_wiring.py
git commit -m "feat: 日本語文書レビューとスキル読み込み確認のフックを配線する"
```

---

### Task 10: 移行と実機での確認

この作業は利用者の環境（`~/.agents/skills/`、`~/.claude/settings.json`）を書き換える。各ステップの前にユーザーへ確認する。

**Files:**
- Modify: `docs/research/2026-10-02-claude-code-hook-payloads.md`（実機確認の結果を追記）

- [ ] **Step 1: 全テストを通す**

Run: `env -u FORCE_COLOR python3 -m unittest discover -s tests -p 'test_*.py'`
Expected: OK（10分前後かかる）

- [ ] **Step 2: npx版のyomiyasuを外す（ユーザーの確認を取ってから）**

```bash
npx -y skills remove -g yomiyasu -y
ls -la ~/.agents/skills/ ~/.claude/skills/ | grep yomiyasu
```

Expected: npx版の `~/.agents/skills/yomiyasu` と、そこを指していた `~/.claude/skills/yomiyasu` が無くなる。
残っていれば中身を確かめ、ユーザーに確認してから消す。

- [ ] **Step 3: setup.shを実行する（ユーザーの確認を取ってから）**

```bash
bash setup.sh
readlink ~/.claude/skills/yomiyasu ~/.agents/skills/yomiyasu
python3 -c "import json;print(sorted(json.load(open('$HOME/.claude/settings.json'))['hooks']))"
```

Expected: 2つのリンクがリポジトリの `skills/yomiyasu` を指す。`hooks` に `PostToolUse`、`PreToolUse`、`SessionStart`、`Stop`、`SubagentStop` がある。
衝突が出たら、内容を確かめてユーザーに報告し、指示に従う。

- [ ] **Step 4: 新しいセッションで、日本語の文書のレビューが起動することを確かめる**

```bash
SPIKE=$(mktemp -d) && git -C "$SPIKE" init -q
cd "$SPIKE" && claude -p --allowedTools "Write,Edit,Agent,Read,Bash" \
  "README.md に、このディレクトリの目的を日本語で5文書いて。書き終えたら作業を終えて。"
ls ~/.claude/state/jp-doc-review/
```

確かめる点は次のとおり。

1. 応答の中で `jp-doc-reviewer` が起動している
2. レビュワーの書き込みが記録されていない（状態ディレクトリの記録に、レビュワーの書き込みの行が増えていない）
3. 最後のStopで止まらずに終わる
4. 「jp-doc-reviewerが起動されないまま」「必読資料が読まれないまま」の表示が出ていない

- [ ] **Step 5: 読み漏れの確認が止めることを確かめる**

```bash
cd "$SPIKE" && claude -p --allowedTools "Skill,Read,Write" \
  "yomiyasuスキルを呼んで、references は読まずに、note.md に日本語で1文だけ書いて終えて。"
```

Expected: 作業を終える前に、`references/gemini-syntax.md` などを読むよう差し戻される。

- [ ] **Step 6: Confluenceの1回目が止まることを確かめる（送らない範囲だけ）**

対話のセッションで、ユーザーに次を依頼してもらう。「テスト用に、Confluenceの個人スペースへ、日本語で200文字ほどのページを作って」。
1回目の投稿が止められ、`~/.claude/state/jp-doc-review/drafts/` に下書きができることだけを確かめる。
止まった時点で作業を中断してもらい、2回目の投稿（実際の送信）はしない。

- [ ] **Step 7: 結果を記録してコミットする**

`docs/research/2026-10-02-claude-code-hook-payloads.md` に「実機での確認」の節を足し、Step 4〜6で確かめた点と、想定と違った点を書く。

```bash
git add docs/research/2026-10-02-claude-code-hook-payloads.md
git commit -m "docs: 日本語文書レビューとスキル読み込み確認を実機で確かめる"
rm -rf "$SPIKE"
```
