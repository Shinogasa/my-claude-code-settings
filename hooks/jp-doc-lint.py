#!/usr/bin/env python3
"""jp-doc-reviewerが使う、yomiyasuリンターのラッパー。

yomiyasu_lint.py は < で始まる行を地の文から外すので、HTMLの下書きを渡すと文字数0で PASS になる。
このラッパーは、呼ばれるたびに現在のファイルからHTMLをテキストに直してリンターへ渡す。
写しのファイルは作らない。レビュワーが下書きを直した後の本文を、そのまま検査するため。

リンターが数えた文字数が0のとき、リンターが失敗したときは、「問題なし」にせず終了コード2で止める。

使い方: python3 ~/.claude/hooks/jp-doc-lint.py '<ファイル>'
"""
import json
import os
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import List

HTML_SUFFIXES = {".html", ".htm"}
LINTER_RELATIVE_PATHS = ("scripts/yomiyasu_lint.py", "skills/yomiyasu/scripts/yomiyasu_lint.py")
LINTER_TIMEOUT_SECONDS = 20
EXIT_CANNOT_CHECK = 2
# この要素の始まりと終わりで行を分ける。1行のHTMLでも、文の区切りを崩さないため
BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt", "figcaption", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section",
    "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
}
SKIPPED_TAGS = {"script", "style"}


class CannotCheck(Exception):
    """検査できなかった。呼び出し側は「問題なし」と区別して扱う。"""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIPPED_TAGS:
            self.skipping += 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIPPED_TAGS:
            self.skipping = max(0, self.skipping - 1)
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skipping:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    if extractor.skipping:
        raise CannotCheck("閉じていない script か style がある。その後ろの本文を検査できない")
    lines = (line.strip() for line in "".join(extractor.parts).splitlines())
    return "\n".join(line for line in lines if line) + "\n"


def find_linter() -> Path:
    override = os.environ.get("JP_DOC_REVIEW_YOMIYASU_SKILL")
    skill = Path(override) if override else Path.home() / ".claude" / "skills" / "yomiyasu" / "SKILL.md"
    for relative in LINTER_RELATIVE_PATHS:
        candidate = skill.parent / relative
        if candidate.is_file():
            return candidate
    raise CannotCheck(f"yomiyasuのリンターが {skill.parent} に見つからない")


def run_linter(text: str) -> dict:
    try:
        completed = subprocess.run(
            [sys.executable, str(find_linter()), "--json"],
            input=text, capture_output=True, text=True, timeout=LINTER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise CannotCheck(f"リンターが{LINTER_TIMEOUT_SECONDS}秒で終わらなかった") from error
    if completed.returncode != 0:
        raise CannotCheck(f"リンターが終了コード{completed.returncode}で終わった: {completed.stderr.strip()}")
    try:
        result = json.loads(completed.stdout)
        char_count = result["metrics"]["char_count"]
        result["findings"], result["score"]
    except (ValueError, KeyError, TypeError) as error:
        raise CannotCheck(f"リンターの出力を読めなかった（{type(error).__name__}）") from error
    if char_count == 0:
        raise CannotCheck("リンターが本文を0文字と数えた。地の文として読める行が無い")
    return result


def render(result: dict, converted: bool) -> str:
    lines = []
    if converted:
        lines.append("HTMLをテキストに直して検査した。行番号は直した後のテキストの行で、下書きの行とは一致しない。")
    metrics = result["metrics"]
    lines.append(f"スコア: {result['score']}/100 ・文字数: {metrics['char_count']}")
    findings = result["findings"]
    if not findings:
        lines.append("[PASS] 指摘なし")
    for finding in findings:
        lines.append(f"L{finding.get('line')} [{str(finding.get('severity', '')).upper()}] {finding.get('message')}")
        lines.append(f"  > {finding.get('snippet')}")
    return "\n".join(lines)


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print(f"使い方: {Path(argv[0]).name} <ファイル>", file=sys.stderr)
        return EXIT_CANNOT_CHECK
    path = Path(argv[1])
    try:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise CannotCheck(f"{path} を読めなかった（{type(error).__name__}）") from error
        converted = path.suffix.lower() in HTML_SUFFIXES
        result = run_linter(html_to_text(content) if converted else content)
    except CannotCheck as error:
        print(f"[ERROR] 検査できなかった: {error}。「指摘なし」として扱わず、報告に書くこと。")
        return EXIT_CANNOT_CHECK
    print(render(result, converted))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
