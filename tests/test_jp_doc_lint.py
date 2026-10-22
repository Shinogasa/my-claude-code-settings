#!/usr/bin/env python3
"""hooks/jp-doc-lint.py（jp-doc-reviewerが使うyomiyasuリンターのラッパー）を検証する。

本物のリンターはsubmodule（skills/yomiyasu）のものを使う。リンターが失敗する場面だけ偽物に差し替える。

実行: python3 -m unittest tests.test_jp_doc_lint
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WRAPPER = REPO_ROOT / "hooks" / "jp-doc-lint.py"
REAL_SKILL = REPO_ROOT / "skills" / "yomiyasu" / "SKILL.md"
# yomiyasuのSlop語彙「手触り」を含む文。Markdownでは警告が出る
SLOP_SENTENCE = "この設計には独特の手触りがあり、使っていて楽しい。"
CANNOT_CHECK = "検査できなかった"


class WrapperCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.skill = REAL_SKILL

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = self.base / name
        path.write_text(text, encoding="utf-8")
        return path

    def snapshot(self, path, text=None, session="t"):
        """フックが依頼の時点で取る原文の写しを置く。text を省くと、今の中身をそのまま写す。"""
        digest = hashlib.sha256(os.path.realpath(path).encode("utf-8")).hexdigest()[:16]
        target = self.base / "state" / "sources" / session / digest
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(Path(path).read_text(encoding="utf-8") if text is None else text, encoding="utf-8")
        return target

    def run_wrapper(self, *args, session="t", with_snapshot=True):
        """フックを通したときと同じく --session を足して呼ぶ。原文の写しは、既定で今の中身と同じものを置く。"""
        if args and session and with_snapshot and Path(args[0]).is_file() and not self.snapshot_exists(args[0], session):
            self.snapshot(args[0], session=session)
        extra = ["--session", session] if args and session else []
        env = {**os.environ, "JP_DOC_REVIEW_YOMIYASU_SKILL": str(self.skill),
               "JP_DOC_REVIEW_STATE_DIR": str(self.base / "state")}
        return subprocess.run([sys.executable, str(WRAPPER), *map(str, args), *extra],
                              capture_output=True, text=True, env=env, timeout=60, cwd=self.base)

    def snapshot_exists(self, path, session):
        digest = hashlib.sha256(os.path.realpath(path).encode("utf-8")).hexdigest()[:16]
        return (self.base / "state" / "sources" / session / digest).is_file()

    def fake_check(self, body):
        """本物のスクリプトを写した置き場の yomiyasu_check.py だけを偽物にし、そのSKILL.mdを指す。"""
        fake = self.base / "fake-skill"
        shutil.copytree(REAL_SKILL.parent / "scripts", fake / "scripts")
        (fake / "scripts" / "yomiyasu_check.py").write_text(body, encoding="utf-8")
        self.skill = fake / "SKILL.md"
        self.skill.write_text("", encoding="utf-8")

    def fake_linter(self, body):
        """scripts/yomiyasu_lint.py に偽物を置き、そのSKILL.mdを指す。"""
        script = self.base / "fake" / "scripts" / "yomiyasu_lint.py"
        script.parent.mkdir(parents=True)
        script.write_text(body, encoding="utf-8")
        self.skill = self.base / "fake" / "SKILL.md"
        self.skill.write_text("", encoding="utf-8")


class LinterLocationTests(WrapperCase):
    def test_nested_linter_path_is_not_searched(self):
        # v2のsubmoduleのルートには古い版のリンターも残る。スキル本体の隣の scripts/ だけを探す
        script = self.base / "fake" / "skills" / "yomiyasu" / "scripts" / "yomiyasu_lint.py"
        script.parent.mkdir(parents=True)
        script.write_text("print('{}')", encoding="utf-8")
        self.skill = self.base / "fake" / "SKILL.md"
        self.skill.write_text("", encoding="utf-8")
        result = self.run_wrapper(self.write("a.md", SLOP_SENTENCE + "\n"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("見つからない", result.stdout)


class HtmlTests(WrapperCase):
    def test_html_paragraph_is_checked_as_text(self):
        draft = self.write("d.html", f"<p>{SLOP_SENTENCE}</p>\n")
        result = self.run_wrapper(draft)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("手触り", result.stdout)

    def test_single_line_html_is_split_into_blocks(self):
        # 10/13の下書きは1行のHTMLだった。ブロックごとに行を分けて、文の数え方を崩さない
        draft = self.write("d.html", f"<h1>見出し</h1><p>{SLOP_SENTENCE}</p><ul><li>項目です。</li></ul>")
        result = self.run_wrapper(draft)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("手触り", result.stdout)

    def test_script_and_style_are_not_text(self):
        draft = self.write("d.html", f"<style>p{{color:red}}</style><script>var a='手触り';</script><p>普通の文です。</p>")
        result = self.run_wrapper(draft)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("手触り", result.stdout)

    def test_unclosed_script_cannot_be_checked(self):
        # 閉じていない script の後ろの本文は検査されない。前半だけで PASS にしない
        draft = self.write("d.html", f"<p>前半の普通の文です。</p><script>var a=1;<p>{SLOP_SENTENCE}</p>")
        result = self.run_wrapper(draft)
        self.assertEqual(result.returncode, 2)
        self.assertIn(CANNOT_CHECK, result.stdout + result.stderr)

    def test_html_without_text_cannot_be_checked(self):
        draft = self.write("d.html", '<ac:structured-macro ac:name="toc"/>\n')
        result = self.run_wrapper(draft)
        self.assertEqual(result.returncode, 2)
        self.assertIn(CANNOT_CHECK, result.stdout + result.stderr)


class MarkdownTests(WrapperCase):
    def test_markdown_is_checked_as_is(self):
        result = self.run_wrapper(self.write("a.md", SLOP_SENTENCE + "\n"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("手触り", result.stdout)

    def test_markdown_made_only_of_tags_cannot_be_checked(self):
        # リンターは < で始まる行を外す。形式を問わず、0文字は「問題なし」にしない
        result = self.run_wrapper(self.write("a.md", f"<p>{SLOP_SENTENCE}</p>\n"))
        self.assertEqual(result.returncode, 2)
        self.assertIn(CANNOT_CHECK, result.stdout + result.stderr)


class DiffCheckTests(WrapperCase):
    RECORD_ARGS = ("import json, os, sys\n"
                   "out = os.environ['JP_DOC_REVIEW_STATE_DIR'] + '/args.json'\n"
                   "files = {a: open(a, encoding='utf-8').read() for a in sys.argv[1:] if os.path.isfile(a)}\n"
                   "json.dump({'argv': sys.argv[1:], 'cwd': os.getcwd(), 'files': files}, open(out, 'w'))\n"
                   "print('偽の検査')\n")

    def recorded(self):
        return json.loads((self.base / "state" / "args.json").read_text(encoding="utf-8"))

    def test_diff_check_runs_with_snapshot(self):
        doc = self.write("a.md", "新しい設定は来月から有効になる。\n")
        self.snapshot(doc, "新しい設定は来月から有効になるとされる。\n", session="s1")
        result = self.run_wrapper(doc, session="s1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("## 差分の検査", result.stdout)
        self.assertIn("伝聞（とされる）", result.stdout)

    def test_diff_check_without_snapshot_cannot_check(self):
        result = self.run_wrapper(self.write("a.md", SLOP_SENTENCE + "\n"), with_snapshot=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("手触り", result.stdout)  # lint の結果は出す
        self.assertIn("差分の検査を実行できなかった", result.stdout)

    def test_diff_check_without_session_cannot_check(self):
        doc = self.write("a.md", SLOP_SENTENCE + "\n")
        self.snapshot(doc)
        result = self.run_wrapper(doc, session=None)
        self.assertEqual(result.returncode, 2)
        self.assertIn("差分の検査を実行できなかった", result.stdout)

    def test_other_session_snapshot_is_not_used(self):
        doc = self.write("a.md", SLOP_SENTENCE + "\n")
        self.snapshot(doc, session="s2")
        result = self.run_wrapper(doc, session="s1", with_snapshot=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("差分の検査を実行できなかった", result.stdout)

    def test_unsafe_session_is_rejected(self):
        doc = self.write("a.md", SLOP_SENTENCE + "\n")
        result = self.run_wrapper(doc, session="../x", with_snapshot=False)
        self.assertEqual(result.returncode, 2)

    def test_diff_check_passes_no_record(self):
        self.fake_check(self.RECORD_ARGS)
        doc = self.write("a.md", SLOP_SENTENCE + "\n")
        result = self.run_wrapper(doc)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        argv = self.recorded()["argv"]
        self.assertEqual(argv[0], "run")
        for flag in ("--no-record", "--source", "--final"):
            self.assertIn(flag, argv)
        self.assertNotIn("verify", argv)
        self.assertNotEqual(os.path.realpath(self.recorded()["cwd"]), os.path.realpath(self.base))
        self.assertFalse((self.base / ".yomiyasu").exists())

    def test_html_draft_is_converted_for_diff(self):
        self.fake_check(self.RECORD_ARGS)
        draft = self.write("d.html", f"<p>{SLOP_SENTENCE}</p>\n")
        self.snapshot(draft, "<p>元の文です。</p>\n")
        result = self.run_wrapper(draft)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        files = self.recorded()["files"]
        self.assertEqual(len(files), 2)
        for path, text in files.items():
            with self.subTest(path=path):
                self.assertNotIn("<p>", text)
                self.assertFalse(Path(path).exists())  # 直したテキストの一時ファイルは残さない

    def test_diff_check_failure_is_cannot_check(self):
        self.fake_check("import sys\nsys.exit(3)\n")
        result = self.run_wrapper(self.write("a.md", SLOP_SENTENCE + "\n"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("差分の検査を実行できなかった", result.stdout)


class FailureTests(WrapperCase):
    def test_linter_failure_cannot_be_checked(self):
        self.fake_linter("import sys\nsys.exit(3)\n")
        result = self.run_wrapper(self.write("a.md", SLOP_SENTENCE))
        self.assertEqual(result.returncode, 2)
        self.assertIn(CANNOT_CHECK, result.stdout + result.stderr)

    def test_unexpected_linter_output_cannot_be_checked(self):
        self.fake_linter("print('not json')\n")
        result = self.run_wrapper(self.write("a.md", SLOP_SENTENCE))
        self.assertEqual(result.returncode, 2)
        self.assertIn(CANNOT_CHECK, result.stdout + result.stderr)

    def test_missing_linter_cannot_be_checked(self):
        self.skill = self.base / "nowhere" / "SKILL.md"
        result = self.run_wrapper(self.write("a.md", SLOP_SENTENCE))
        self.assertEqual(result.returncode, 2)
        self.assertIn(CANNOT_CHECK, result.stdout + result.stderr)

    def test_missing_file_cannot_be_checked(self):
        result = self.run_wrapper(self.base / "missing.md")
        self.assertEqual(result.returncode, 2)
        self.assertIn(CANNOT_CHECK, result.stdout + result.stderr)

    def test_wrong_number_of_arguments_is_usage_error(self):
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
