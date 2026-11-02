#!/usr/bin/env python3
"""bin/md-to-confluence-html.py の変換を検証する。

出力は getContentFormatGuide（toolName: updateConfluencePage、2026-11-02取得）の HTML の書式に合わせる。
トップレベルのブロックは改行で区切り、ブロックの中には改行を入れない（コードブロックの中身を除く）。

実行: python3 -m unittest tests.test_md_to_confluence_html
"""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "bin" / "md-to-confluence-html.py"


def load():
    spec = importlib.util.spec_from_file_location("md_to_confluence_html", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConvertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.convert = staticmethod(load().convert)

    def check(self, markdown, expected, **options):
        self.assertEqual(self.convert(markdown, **options), expected)

    def test_heading_and_paragraph(self):
        self.check("# 見出し\n\n本文", "<h1>見出し</h1>\n<p>本文</p>")
        self.check("### 小見出し", "<h3>小見出し</h3>")

    def test_text_is_escaped(self):
        self.check("a < b & c > d", "<p>a &lt; b &amp; c &gt; d</p>")

    def test_inline_code_bold_and_link(self):
        self.check(
            "`x<y>` と **太字** と [リンク](https://e.com/?a=1&b=2)",
            '<p><code>x&lt;y&gt;</code> と <strong>太字</strong> と <a href="https://e.com/?a=1&amp;b=2">リンク</a></p>',
        )

    def test_inline_code_is_not_formatted(self):
        self.check("`**a**` と `[x](y)`", "<p><code>**a**</code> と <code>[x](y)</code></p>")

    def test_line_breaks_join_without_space_between_japanese(self):
        self.check("一行目\n二行目", "<p>一行目二行目</p>")
        self.check("one\ntwo", "<p>one two</p>")

    def test_fenced_code_block_keeps_content(self):
        self.check(
            "```python\nif a < b:\n    **x**\n```",
            '<pre><code class="language-python">if a &lt; b:\n    **x**</code></pre>',
        )
        self.check("```\nplain\n```", "<pre><code>plain</code></pre>")

    def test_table(self):
        self.check(
            "| A | B |\n|---|:-:|\n| `x` | **y** |\n| 1 | 2 |",
            "<table><thead><tr><th>A</th><th>B</th></tr></thead>"
            "<tbody><tr><td><code>x</code></td><td><strong>y</strong></td></tr>"
            "<tr><td>1</td><td>2</td></tr></tbody></table>",
        )

    def test_nested_bullet_list(self):
        self.check("- a\n  - b\n    - c\n- d",
                   "<ul><li>a<ul><li>b<ul><li>c</li></ul></li></ul></li><li>d</li></ul>")

    def test_ordered_list_and_mixed_nesting(self):
        self.check("1. a\n2. b", '<ol start="1"><li>a</li><li>b</li></ol>')
        self.check("1. a\n   - b", '<ol start="1"><li>a<ul><li>b</li></ul></li></ol>')

    def test_task_list(self):
        self.check(
            "- [ ] a\n- [x] **b**",
            '<ul data-type="task-list"><li data-type="task-item"><input type="checkbox"> a</li>'
            '<li data-type="task-item"><input type="checkbox" checked> <strong>b</strong></li></ul>',
        )

    def test_nested_task_list_follows_parent_item(self):
        # ガイドの指定: 入れ子のタスクリストは、親の <li> の中ではなく直後に置く
        self.check(
            "- [ ] a\n  - [x] b",
            '<ul data-type="task-list"><li data-type="task-item"><input type="checkbox"> a</li>'
            '<ul data-type="task-list"><li data-type="task-item"><input type="checkbox" checked> b</li></ul></ul>',
        )

    def test_list_item_continuation_line(self):
        self.check("- 一行目\n  二行目\n- b", "<ul><li>一行目二行目</li><li>b</li></ul>")

    def test_horizontal_rule(self):
        self.check("a\n\n---\n\nb", "<p>a</p>\n<hr>\n<p>b</p>")

    def test_blockquote(self):
        self.check("> 引用\n> 続き", "<blockquote><p>引用続き</p></blockquote>")

    def test_panel_from_alert_syntax(self):
        self.check("> [!INFO]\n> 注意して", '<div data-type="panel-info"><p>注意して</p></div>')
        self.check("> [!WARNING]\n> - a\n> - b", '<div data-type="panel-warning"><ul><li>a</li><li>b</li></ul></div>')

    def test_unknown_alert_type_stays_blockquote(self):
        self.check("> [!FOO]\n> x", "<blockquote><p>[!FOO] x</p></blockquote>")

    def test_details_becomes_expand(self):
        self.check(
            "<details>\n<summary>詳細 & 補足</summary>\n\n本文\n\n- a\n\n</details>",
            "<details><summary>詳細 &amp; 補足</summary><p>本文</p><ul><li>a</li></ul></details>",
        )

    def test_toc_option_prepends_extension(self):
        html = self.convert("# a", toc=True)
        first, rest = html.split("\n", 1)
        self.assertIn('data-type="extension"', first)
        self.assertIn('data-extension-key="toc"', first)
        self.assertIn('data-extension-type="com.atlassian.confluence.macro.core"', first)
        self.assertIn('"maxLevel":{"value":"3"}', first)
        self.assertEqual(rest, "<h1>a</h1>")

    def test_raw_html_outside_details_is_escaped(self):
        self.check("<script>x</script>", "<p>&lt;script&gt;x&lt;/script&gt;</p>")


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)

    def test_reads_file_and_writes_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "draft.md"
            path.write_text("# 見出し\n", encoding="utf-8")
            result = self.run_cli("--toc", str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.rstrip("\n").endswith("<h1>見出し</h1>"), result.stdout)
        self.assertIn('data-extension-key="toc"', result.stdout)

    def test_missing_file_fails_loudly(self):
        result = self.run_cli("/nonexistent/draft.md")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("draft.md", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
