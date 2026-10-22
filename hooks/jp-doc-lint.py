#!/usr/bin/env python3
"""jp-doc-reviewerが使う、yomiyasuリンターのラッパー。

yomiyasu_lint.py は < で始まる行を地の文から外すので、HTMLの下書きを渡すと文字数0で PASS になる。
このラッパーは、呼ばれるたびに現在のファイルからHTMLをテキストに直してリンターへ渡す。
写しのファイルは作らない。レビュワーが下書きを直した後の本文を、そのまま検査するため。

リンターが数えた文字数が0のとき、リンターが失敗したときは、「問題なし」にせず終了コード2で止める。

続けて、レビュワーの起動時にフックが取った原文の写し（jp_doc_sources.py）と今のファイルで、
yomiyasu_check.py run --no-record を実行する（差分の検査）。作業repoに記録を残さないよう、一時ディレクトリで動かす。
写しが無いとき、検査が失敗したときも、「問題なし」にせず終了コード2で止める。

使い方: python3 ~/.claude/hooks/jp-doc-lint.py '<ファイル>'
（--session <ID> は、jp-doc-review.py のフックが足す。レビュワーは書かない）
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Optional

HTML_SUFFIXES = {".html", ".htm"}
# スキル本体の隣だけを探す。v2のsubmoduleのルートにも古い版が残るので、そちらは見ない
LINTER_RELATIVE_PATHS = ("scripts/yomiyasu_lint.py",)
CHECK_RELATIVE_PATH = "scripts/yomiyasu_check.py"
LINTER_TIMEOUT_SECONDS = 20
CHECK_TIMEOUT_SECONDS = 60
SESSION_ID = re.compile(r"[A-Za-z0-9_-]+")  # jp-doc-review.py の session_key が返す文字だけ
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


def yomiyasu_skill() -> Path:
    override = os.environ.get("JP_DOC_REVIEW_YOMIYASU_SKILL")
    return Path(override) if override else Path.home() / ".claude" / "skills" / "yomiyasu" / "SKILL.md"


def find_linter() -> Path:
    skill = yomiyasu_skill()
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
        result["findings"], result["rule_penalty_score"]  # v2で score から改名された
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
    lines.append(f"スコア: {result['rule_penalty_score']}/100 ・文字数: {metrics['char_count']}")
    findings = result["findings"]
    if not findings:
        lines.append("[PASS] 指摘なし")
    for finding in findings:
        lines.append(f"L{finding.get('line')} [{str(finding.get('severity', '')).upper()}] {finding.get('message')}")
        lines.append(f"  > {finding.get('snippet')}")
    return "\n".join(lines)


def _sources():
    spec = importlib.util.spec_from_file_location("jp_doc_sources", Path(__file__).resolve().parent / "jp_doc_sources.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_diff_check(path: Path, converted: bool, session: Optional[str]) -> str:
    """原文の写しと今のファイルで yomiyasu_check.py run --no-record を実行し、その出力を返す。"""
    if session is None:
        raise CannotCheck("セッションが渡されていない（フックを通さずに呼ばれた）")
    sources = _sources()
    snapshot = sources.find_snapshot(os.path.realpath(path), session)
    if snapshot is None:
        raise CannotCheck("原文の写しが無い（レビュワーの起動時に写しを取れなかったか、依頼文にこのファイルが無い）")
    check = yomiyasu_skill().parent / CHECK_RELATIVE_PATH
    if not check.is_file():
        raise CannotCheck(f"yomiyasuの検査スクリプトが {check.parent} に見つからない")
    sources.sources_dir().mkdir(mode=0o700, parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=sources.sources_dir(), prefix=".check-"))  # 0700で作られる
    try:
        suffix = ".txt" if converted else path.suffix
        texts = {"source": snapshot.read_text(encoding="utf-8"), "final": path.read_text(encoding="utf-8")}
        files = {}
        for name, text in texts.items():
            files[name] = work / f"{name}{suffix}"
            files[name].write_text(html_to_text(text) if converted else text, encoding="utf-8")
        try:
            completed = subprocess.run(
                [sys.executable, str(check), "run", "--no-record", "--source", str(files["source"]),
                 "--final", str(files["final"])],
                capture_output=True, text=True, timeout=CHECK_TIMEOUT_SECONDS, cwd=work,
            )
        except subprocess.TimeoutExpired as error:
            raise CannotCheck(f"検査スクリプトが{CHECK_TIMEOUT_SECONDS}秒で終わらなかった") from error
    except (OSError, UnicodeDecodeError) as error:
        raise CannotCheck(f"原文の写しか今のファイルを読めなかった（{type(error).__name__}）") from error
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if completed.returncode not in (0, 1):  # 1は --fail-on に当たったとき。ここでは付けないが、実行はできている
        raise CannotCheck(f"検査スクリプトが終了コード{completed.returncode}で終わった: {completed.stderr.strip()[-300:]}")
    return completed.stdout.rstrip()


def parse_args(argv: List[str]) -> Optional[tuple]:
    """<ファイル> か <ファイル> --session <ID> を受け取る。それ以外は None。"""
    if len(argv) == 2:
        return Path(argv[1]), None
    if len(argv) == 4 and argv[2] == "--session" and SESSION_ID.fullmatch(argv[3]):
        return Path(argv[1]), argv[3]
    return None


def main(argv: List[str]) -> int:
    parsed = parse_args(argv)
    if parsed is None:
        print(f"使い方: {Path(argv[0]).name} <ファイル>", file=sys.stderr)
        return EXIT_CANNOT_CHECK
    path, session = parsed
    status = 0
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
    print("\n## 差分の検査")
    try:
        print(run_diff_check(path, converted, session))
    except CannotCheck as error:
        print(f"[ERROR] 差分の検査を実行できなかった: {error}。「指摘なし」として扱わず、報告に書くこと。")
        status = EXIT_CANNOT_CHECK
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
