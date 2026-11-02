#!/usr/bin/env python3
"""Markdown の下書きを、Confluence の updateConfluencePage / createConfluencePage に送る HTML に変換する。

書式は getContentFormatGuide（toolName: updateConfluencePage、2026-11-02取得）に合わせる。
扱う要素: 見出し、段落、表、入れ子のリスト（箇条書き・番号付き・タスク）、コードブロック、引用、区切り線、
インラインのコード・太字・リンク。
Confluence 固有の要素は次の書き方で付ける。
- info パネル: 引用の1行目を `> [!INFO]` にする（NOTE / WARNING / SUCCESS / ERROR / TIP も使える）
- 折りたたみ: `<details>` と `<summary>…</summary>` の行で囲む。中身は Markdown として変換する
- 目次: `--toc` オプションで先頭に付ける

それ以外の生の HTML は、文字としてエスケープする。斜体・取り消し線・画像・リストの中のコードブロックには対応せず、
見つけたら標準エラーに行番号つきで警告する（変換結果は変えない）。
既存ページのマクロは変換結果に含まれないので、送る前に既存ページの HTML から戻す（ADR 0046）。

使い方: python3 md-to-confluence-html.py [--toc] [--toc-max-level N] [下書き.md]（省略すると標準入力）
"""
import argparse
import html
import json
import re
import sys
from typing import List, Optional, Tuple

FENCE = re.compile(r"^\s*```\s*([\w+-]*)\s*$")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
RULE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
LIST_ITEM = re.compile(r"^(\s*)([-*+]|(\d+)[.)])\s+(.*)$")
TASK = re.compile(r"^\[([ xX])\]\s+(.*)$")
TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")
SUMMARY = re.compile(r"^\s*<summary>(.*)</summary>\s*$")
ALERT = re.compile(r"^\[!([A-Z]+)\]\s*$")
CODE_SPAN = re.compile(r"(`+)(.+?)\1")
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
BOLD = re.compile(r"\*\*(.+?)\*\*")
# ガイドの panel の種類。tip は info として受け付けられる
PANEL_TYPES = {"INFO": "info", "NOTE": "note", "WARNING": "warning", "SUCCESS": "success", "ERROR": "error", "TIP": "info"}
DETAILS_OPEN = "<details>"
DETAILS_CLOSE = "</details>"


# ---- インライン ----

LINK_MARK = ""  # リンクの仮置き。私用領域の文字なので、下書きの本文には現れない


def _format_text(text: str) -> str:
    """コードスパンの外側の文字列を、エスケープしてからリンクと太字に変える。

    リンクを仮置きの印に置き換えてから太字を処理し、最後に戻す。先にリンクで文字列を切ると、
    `**[a](b)**` の ** がリンクの前後に分かれて太字にならない。
    """
    links: List[str] = []

    def stash(match: "re.Match[str]") -> str:
        href = html.escape(match.group(2), quote=True)
        links.append(f'<a href="{href}">{_emphasis(match.group(1))}</a>')
        return f"{LINK_MARK}{len(links) - 1}{LINK_MARK}"

    formatted = _emphasis(LINK.sub(stash, text))
    return re.sub(f"{LINK_MARK}(\\d+){LINK_MARK}", lambda m: links[int(m.group(1))], formatted)


def _emphasis(text: str) -> str:
    return BOLD.sub(r"<strong>\1</strong>", html.escape(text, quote=False))


def inline(text: str) -> str:
    out, last = [], 0
    for match in CODE_SPAN.finditer(text):
        out.append(_format_text(text[last:match.start()]))
        out.append(f"<code>{html.escape(match.group(2).strip(), quote=False)}</code>")
        last = match.end()
    out.append(_format_text(text[last:]))
    return "".join(out)


def join_lines(lines: List[str]) -> str:
    """改行を詰める。日本語どうしの境目では空白を入れない（Markdown の既定だと空白が入る）。"""
    result = ""
    for line in (line.strip() for line in lines):
        if not line:
            continue
        if result and not (ord(result[-1]) > 127 and ord(line[0]) > 127):
            result += " "
        result += line
    return result


# ---- ブロック ----

def _is_table_start(lines: List[str], i: int) -> bool:
    return lines[i].lstrip().startswith("|") and i + 1 < len(lines) and bool(TABLE_SEPARATOR.match(lines[i + 1]))


def _starts_block(lines: List[str], i: int) -> bool:
    line = lines[i]
    return bool(
        not line.strip() or FENCE.match(line) or HEADING.match(line) or RULE.match(line)
        or LIST_ITEM.match(line) or line.lstrip().startswith(">") or line.strip() == DETAILS_OPEN
        or _is_table_start(lines, i)
    )


def parse_blocks(lines: List[str]) -> List[str]:
    blocks, i = [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        for reader in (_fence, _heading, _rule, _details, _quote, _table, _list):
            result = reader(lines, i)
            if result is not None:
                block, i = result
                blocks.append(block)
                break
        else:
            start = i
            i += 1
            while i < len(lines) and not _starts_block(lines, i):
                i += 1
            blocks.append(f"<p>{inline(join_lines(lines[start:i]))}</p>")
    return blocks


Read = Optional[Tuple[str, int]]


def _fence(lines: List[str], i: int) -> Read:
    match = FENCE.match(lines[i])
    if not match:
        return None
    end = i + 1
    while end < len(lines) and not FENCE.match(lines[end]):
        end += 1
    code = html.escape("\n".join(lines[i + 1:end]), quote=False)
    lang = match.group(1)
    attr = f' class="language-{html.escape(lang, quote=True)}"' if lang else ""
    return f"<pre><code{attr}>{code}</code></pre>", end + 1


def _heading(lines: List[str], i: int) -> Read:
    match = HEADING.match(lines[i])
    if not match:
        return None
    level = len(match.group(1))
    return f"<h{level}>{inline(match.group(2))}</h{level}>", i + 1


def _rule(lines: List[str], i: int) -> Read:
    return ("<hr>", i + 1) if RULE.match(lines[i]) else None


def _details(lines: List[str], i: int) -> Read:
    if lines[i].strip() != DETAILS_OPEN:
        return None
    depth, end = 1, i + 1
    while end < len(lines):
        stripped = lines[end].strip()
        depth += (stripped == DETAILS_OPEN) - (stripped == DETAILS_CLOSE)
        if depth == 0:
            break
        end += 1
    body = lines[i + 1:end]
    summary = ""
    for index, line in enumerate(body):
        if not line.strip():
            continue
        match = SUMMARY.match(line)
        if match:
            summary = inline(match.group(1))
            body = body[index + 1:]
        break
    inner = "".join(parse_blocks(body))
    return f"<details><summary>{summary}</summary>{inner}</details>", end + 1


def _quote(lines: List[str], i: int) -> Read:
    if not lines[i].lstrip().startswith(">"):
        return None
    end, body = i, []
    while end < len(lines) and lines[end].lstrip().startswith(">"):
        body.append(re.sub(r"^\s*> ?", "", lines[end]))
        end += 1
    match = ALERT.match(body[0].strip())
    if match and match.group(1) in PANEL_TYPES:
        inner = "".join(parse_blocks(body[1:]))
        return f'<div data-type="panel-{PANEL_TYPES[match.group(1)]}">{inner}</div>', end
    return f"<blockquote>{''.join(parse_blocks(body))}</blockquote>", end


def _cells(row: str) -> List[str]:
    row = row.strip().replace("\\|", "\0")
    row = row[1:] if row.startswith("|") else row
    row = row[:-1] if row.endswith("|") else row
    return [inline(cell.strip().replace("\0", "|")) for cell in row.split("|")]


def _table(lines: List[str], i: int) -> Read:
    if not _is_table_start(lines, i):
        return None
    head = "".join(f"<th>{cell}</th>" for cell in _cells(lines[i]))
    end, rows = i + 2, []
    while end < len(lines) and lines[end].lstrip().startswith("|"):
        rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in _cells(lines[end])) + "</tr>")
        end += 1
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>", end


# ---- リスト ----

Item = Tuple[int, Optional[str], List[str]]  # 字下げ、番号（箇条書きは None）、本文の行


def _list(lines: List[str], i: int) -> Read:
    if not LIST_ITEM.match(lines[i]):
        return None
    items: List[Item] = []
    end = i
    while end < len(lines):
        line = lines[end]
        match = LIST_ITEM.match(line)
        if match:
            items.append((len(match.group(1)), match.group(3), [match.group(4)]))
        elif line.strip() and line[:1] in (" ", "\t") and items:
            items[-1][2].append(line)  # 字下げした続きの行
        elif not line.strip() and end + 1 < len(lines) and LIST_ITEM.match(lines[end + 1]):
            pass  # 項目の間の空行
        else:
            break
        end += 1
    return _render_list(items), end


def _render_list(items: List[Item]) -> str:
    base = items[0][0]
    is_task = bool(TASK.match(join_lines(items[0][2])))
    number = items[0][1]
    out, index = [], 0
    while index < len(items):
        _, _, text_lines = items[index]
        children_end = index + 1
        while children_end < len(items) and items[children_end][0] > base:
            children_end += 1
        children = _render_list(items[index + 1:children_end]) if children_end > index + 1 else ""
        out.append(_render_item(join_lines(text_lines), children, is_task))
        index = children_end
    body = "".join(out)
    if is_task:
        return f'<ul data-type="task-list">{body}</ul>'
    if number is not None:
        return f'<ol start="{int(number)}">{body}</ol>'
    return f"<ul>{body}</ul>"


def _render_item(text: str, children: str, is_task: bool) -> str:
    match = TASK.match(text) if is_task else None
    if not match:
        return f"<li>{inline(text)}{children}</li>"
    checked = " checked" if match.group(1) in "xX" else ""
    # ガイドの指定: 入れ子のタスクリストは、親の <li> の中ではなく直後に置く
    return f'<li data-type="task-item"><input type="checkbox"{checked}> {inline(match.group(2))}</li>{children}'


# ---- 未対応の記法 ----

# 変換しない記法。見つけても変換結果は変えず、記号がそのまま文字として残ることを知らせる
UNSUPPORTED_INLINE = (
    ("斜体", re.compile(r"(?<!\*)\*(?![\s*])[^*]+?(?<![\s*])\*(?!\*)")),
    ("取り消し線", re.compile(r"~~.+?~~")),
    ("画像", re.compile(r"!\[[^\]]*\]\(")),
)


def unsupported_warnings(markdown: str) -> List[Tuple[int, str]]:
    """変換しない記法を (行番号, 記法の名前) で返す。コードブロックとコードスパンの中は見ない。"""
    found: List[Tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(markdown.replace("\r\n", "\n").split("\n"), start=1):
        if FENCE.match(line):
            if not in_fence and line[:1] in (" ", "\t"):
                found.append((number, "リスト内のコードブロック"))
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        text = CODE_SPAN.sub("", line)
        found.extend((number, name) for name, pattern in UNSUPPORTED_INLINE if pattern.search(text))
    return found


# ---- 全体 ----

def toc_extension(max_level: int) -> str:
    parameters = json.dumps({
        "macroParams": {"maxLevel": {"value": str(max_level)}},
        "macroMetadata": {"schemaVersion": {"value": "1"}, "title": "Table of Contents"},
    }, separators=(",", ":"), ensure_ascii=False)
    return ('<div data-type="extension" data-extension-key="toc" '
            f"data-extension-type=\"com.atlassian.confluence.macro.core\" data-parameters='{parameters}'></div>")


def convert(markdown: str, toc: bool = False, toc_max_level: int = 3) -> str:
    blocks = parse_blocks(markdown.replace("\r\n", "\n").split("\n"))
    if toc:
        blocks.insert(0, toc_extension(toc_max_level))
    return "\n".join(blocks)


def main() -> int:
    parser = argparse.ArgumentParser(description="Markdown の下書きを Confluence の HTML に変換して標準出力に書く")
    parser.add_argument("path", nargs="?", help="Markdown のファイル。省略すると標準入力を読む")
    parser.add_argument("--toc", action="store_true", help="先頭に目次マクロを付ける")
    parser.add_argument("--toc-max-level", type=int, default=3, help="目次に載せる見出しの深さ（既定: 3）")
    args = parser.parse_args()
    try:
        source = open(args.path, encoding="utf-8").read() if args.path else sys.stdin.read()
    except OSError as error:
        print(f"md-to-confluence-html: {args.path} を読めない: {error}", file=sys.stderr)
        return 1
    for number, name in unsupported_warnings(source):
        print(f"md-to-confluence-html: {number}行目: {name}は変換しない。記号がそのまま文字として残る", file=sys.stderr)
    print(convert(source, toc=args.toc, toc_max_level=args.toc_max_level))
    return 0


if __name__ == "__main__":
    sys.exit(main())
