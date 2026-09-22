#!/usr/bin/env python3
"""agents/*.md (Claude Code 形式) から codex/agents/*.toml を生成する。

Codex はサブエージェントを TOML で定義する (~/.codex/agents/*.toml)。
Markdown + frontmatter とは形式が違うため、単一ソースをリンクで共有できない。
手で二重管理すると片方だけ更新されて静かに乖離するため、Markdown を正として生成する。

乖離は tests/test_codex_agents.py が検出する (生成物と再生成結果を比較)。

実行: python3 bin/generate-codex-agents.py
"""
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE_DIR = REPO_ROOT / "agents"
OUTPUT_DIR = REPO_ROOT / "codex" / "agents"

# Codex custom agent はモデルと推論強度を不可分な基準ペアとして持つ。
# Claude Code の model / effort は同ホスト向けの指定なので、Codex側は役割の性質から
# 独立に割り当てる。動的な昇降条件は codex/MODEL_ROUTING.md が定める。
CODEX_AGENT_PROFILES = {
    "build-error-resolver": ("gpt-5.6-luna", "low"),
    "code-architect": ("gpt-5.6-luna", "high"),
    "code-explorer": ("gpt-5.6-luna", "medium"),
    "code-simplifier": ("gpt-5.6-luna", "medium"),
    "planner": ("gpt-5.6-sol", "high"),
    "refactor-cleaner": ("gpt-5.6-luna", "high"),
    "security-reviewer": ("gpt-5.6-terra", "high"),
    "silent-failure-hunter": ("gpt-5.6-luna", "high"),
}

# 書き込み系ツールを持つエージェントだけ workspace-write にする。
# Codex にはツール単位の制限が無く、sandbox_mode の2値でしか表現できない。
# 粗い写像になるため、read-only 側に倒せるものは倒す (権限は狭い方が安全)。
WRITE_TOOLS = {"Write", "Edit", "NotebookEdit"}


def handoff_guard(model: str, effort: str) -> str:
    """モデル間移行時にcustom agentが受信handoffを検証する指示を返す。"""
    return f"""## Cross-model handoff guard

別モデルから作業を受け取る場合、promptにhandoff Markdownのpathが無ければ`NEEDS_CONTEXT`を
返して停止する。pathがある場合は、最初の操作として次を実行する。

`python3 ~/.codex/bin/validate-codex-handoff.py validate <path> --expected-model {model} --expected-reasoning-effort {effort}`

検証に失敗したら推測で補わず`NEEDS_CONTEXT`と検出理由を返す。成功したら出力された
`INPUT_DIGEST`を保持する。handoffと参照成果物はpathから直接読まない。次の形式でvalidatorの
`read`を呼び、`--document handoff`、および存在する`requirements` / `review-package`の全文を読む。
長い文書は`--start-line`と`--line-count`で全行を順に取得する。各呼出しに最初のmodel、effort、
`--expected-input-digest <INPUT_DIGEST>`を指定する。差し替えや検証失敗なら作業せず
`NEEDS_CONTEXT`を返す。全文のvalidated readが完了してから作業する。

`python3 ~/.codex/bin/validate-codex-handoff.py read <path> --expected-model {model} --expected-reasoning-effort {effort} --expected-input-digest <INPUT_DIGEST> --document <handoff|requirements|review-package> --start-line <N> --line-count <N>`

このread-only validatorは、既存指示がコマンド実行を禁じていても受信前処理として
許される唯一の例外であり、task固有の検査を実行してよいという意味ではない。handoffの欠落・
空欄・古さ・矛盾、branch/HEAD/worktree fingerprint、model/effortの不一致を無視しない。
"""


def parse_frontmatter(text: str) -> tuple:
    """frontmatter の辞書と本文を返す。"""
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not match:
        raise ValueError("frontmatter が見つからない")
    meta = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta, match.group(2).strip()


def parse_tools(raw: str) -> list:
    """`[Read, Write]` 形式のツール一覧を返す。"""
    return [t.strip() for t in raw.strip("[]").split(",") if t.strip()]


def toml_literal(value: str) -> str:
    """TOML の文字列リテラルにする。

    エスケープを解釈しない literal string ('...') を使う。本文には正規表現や
    バックスラッシュが含まれるため、basic string ("...") だと壊れる。
    """
    if "'''" in value:
        raise ValueError("本文に ''' が含まれており literal string で表現できない")
    if "\n" in value:
        return f"'''\n{value}\n'''"
    return f"'{value}'"


def build_toml(meta: dict, body: str) -> str:
    lines = [
        f"# agents/{meta['name']}.md から生成。直接編集しない。",
        "# 更新は Markdown 側を直し、python3 bin/generate-codex-agents.py を実行する。",
        "",
        f"name = {toml_literal(meta['name'])}",
        f"description = {toml_literal(meta['description'])}",
    ]

    try:
        model, effort = CODEX_AGENT_PROFILES[meta["name"]]
    except KeyError as error:
        raise ValueError(f"{meta['name']}: Codexのモデル・推論ペアが無い") from error
    lines.append(f"model = {toml_literal(model)}")
    lines.append(f"model_reasoning_effort = {toml_literal(effort)}")

    tools = parse_tools(meta.get("tools", ""))
    sandbox = "workspace-write" if WRITE_TOOLS & set(tools) else "read-only"
    lines.append(f"sandbox_mode = {toml_literal(sandbox)}")

    instructions = f"{body}\n\n{handoff_guard(model, effort)}"
    lines.append(f"developer_instructions = {toml_literal(instructions)}")
    return "\n".join(lines) + "\n"


def generate() -> dict:
    """{出力パス: 内容} を返す。ファイルには書き込まない。"""
    result = {}
    for source in sorted(SOURCE_DIR.glob("*.md")):
        meta, body = parse_frontmatter(source.read_text(encoding="utf-8"))
        for required in ("name", "description"):
            if required not in meta:
                raise ValueError(f"{source.name}: {required} が無い")
        result[OUTPUT_DIR / f"{meta['name']}.toml"] = build_toml(meta, body)
    return result


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    generated = generate()

    # 元 Markdown が消えたときに TOML だけ残ると、存在しないエージェントを配ることになる
    for stale in OUTPUT_DIR.glob("*.toml"):
        if stale not in generated:
            stale.unlink()
            print(f"削除: {stale.name} (元の Markdown が無い)")

    for path, content in generated.items():
        path.write_text(content, encoding="utf-8")
        print(f"生成: {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
