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

# Claude Code のモデル別名 → Codex の世代名。
# Codex には別名が無く (codex debug models の alias は全件 null)、世代名を直接書くしかない。
# 新世代が出たらこの表を更新する。
#
# 対応の根拠はモデルカタログの説明文:
#   gpt-5.6-luna "Fast and affordable agentic coding model."
#   gpt-5.6-sol  "Latest frontier agentic coding model."
# サブエージェントに重いモデルを使うと、本来の「安く並列に回す」利点が消えるため、
# 既定は安い側に寄せ、思考量を要求するもの (planner) だけ frontier を割り当てる。
MODEL_MAP = {
    "sonnet": "gpt-5.6-luna",
    "opus": "gpt-5.6-sol",
}

# 書き込み系ツールを持つエージェントだけ workspace-write にする。
# Codex にはツール単位の制限が無く、sandbox_mode の2値でしか表現できない。
# 粗い写像になるため、read-only 側に倒せるものは倒す (権限は狭い方が安全)。
WRITE_TOOLS = {"Write", "Edit", "NotebookEdit"}


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

    model = MODEL_MAP.get(meta.get("model", ""))
    if model:
        lines.append(f"model = {toml_literal(model)}")
    if meta.get("effort"):
        lines.append(f"model_reasoning_effort = {toml_literal(meta['effort'])}")

    tools = parse_tools(meta.get("tools", ""))
    sandbox = "workspace-write" if WRITE_TOOLS & set(tools) else "read-only"
    lines.append(f"sandbox_mode = {toml_literal(sandbox)}")

    lines.append(f"developer_instructions = {toml_literal(body)}")
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
