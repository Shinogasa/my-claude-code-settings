#!/usr/bin/env python3
""".githooks/pre-commit のパターン評価を検証する。

このファイルは PUBLIC なリポジトリに含まれるため、実際の禁止語は一切書かない。
検証はすべてプレースホルダ（foo-stg / アクメ 等）で行う。

主眼は「和文に隣接したときに一致するか」。既定の Unicode 基準では \\b が
日本語文字を単語文字として扱うため境界が成立せず、journal のような日本語の
文章中でパターンが素通りする。この失敗は静かに起きる（設定は存在し、
コミットも通り、誰も気付かない）ため、回帰テストで固定する。

実行: python3 tests/test_patterns.py
"""
import importlib.machinery
import importlib.util
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / ".githooks" / "pre-commit"
COMMON = REPO_ROOT / ".githooks" / "patterns-common.txt"


def load_hook_module():
    """拡張子を持たないフック本体を、モジュールとして読み込む。"""
    loader = importlib.machinery.SourceFileLoader("precommit_hook", str(HOOK))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


hook = load_hook_module()


def compile_patterns(lines):
    """パターン文字列のリストを、フックと同じ経路でコンパイルする。"""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                     encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
        path = Path(handle.name)
    try:
        return hook.load_patterns(path)
    finally:
        path.unlink()


def matches(patterns, text):
    return any(regex.search(text) for _, regex in patterns)


def fixture(*parts):
    """検出対象の形をした検証用文字列を、ソース上では分割して保持する。

    このテストの期待値は「漏洩に見える文字列」そのものなので、ソースへ連続した形で
    書くと pre-commit フック（まさにここで検証している当人）が自分自身のテストを
    ブロックする。実行時に結合することで、フック側の除外規則を緩めずに済ませる。
    除外規則を増やすと、そのディレクトリに本物が紛れ込んだとき検出できなくなる。
    """
    return "".join(parts)


class TestWordBoundaryWithJapanese(unittest.TestCase):
    """\\b と日本語の相互作用。ここが壊れると検査全体が静かに素通りする。"""

    def test_ascii_pattern_matches_when_japanese_follows(self):
        patterns = compile_patterns([r"\bfoo[-_]?stg\b"])
        self.assertTrue(matches(patterns, "foo-stg環境で確認した"))

    def test_ascii_pattern_matches_when_japanese_precedes(self):
        patterns = compile_patterns([r"\bfoo[-_]?stg\b"])
        self.assertTrue(matches(patterns, "検証はfoo-stgで行う"))

    def test_ascii_pattern_matches_with_ascii_delimiters(self):
        patterns = compile_patterns([r"\bfoo[-_]?stg\b"])
        self.assertTrue(matches(patterns, "https://api.foo-stg.example/v1"))

    def test_japanese_literal_without_boundary_matches_in_prose(self):
        patterns = compile_patterns(["アクメ"])
        self.assertTrue(matches(patterns, "株式会社アクメです"))

    def test_japanese_literal_with_boundary_does_not_match(self):
        # \\b を付けると和文中で一致しなくなる。この挙動を明示的に固定し、
        # patterns-local.txt.example の「和文に境界を付けない」指針の根拠とする。
        patterns = compile_patterns([r"\bアクメ\b"])
        self.assertFalse(matches(patterns, "株式会社アクメです"))

    def test_case_is_ignored(self):
        patterns = compile_patterns([r"\bfoo-stg\b"])
        self.assertTrue(matches(patterns, "FOO-STG"))


class TestApexDomainCoversSubdomains(unittest.TestCase):
    """ホスト名は頂点側1本で全サブドメインを捕捉できる（列挙しない）。"""

    def setUp(self):
        self.patterns = compile_patterns([r"\bfoo[-_]?stg\b"])

    def test_apex_domain(self):
        self.assertTrue(matches(self.patterns, "foo-stg.example"))

    def test_single_level_subdomain(self):
        self.assertTrue(matches(self.patterns, "api.foo-stg.example"))

    def test_deeply_nested_subdomain(self):
        self.assertTrue(matches(self.patterns, "mobileapp-api.stg1.foo-stg.example"))

    def test_underscore_variant(self):
        self.assertTrue(matches(self.patterns, "foo_stg"))

    def test_unrelated_token_is_not_matched(self):
        self.assertFalse(matches(self.patterns, "stg1"))
        self.assertFalse(matches(self.patterns, "foo"))


class TestCommonPatterns(unittest.TestCase):
    """追跡している構造的パターンの検出と、意図的な除外。"""

    @classmethod
    def setUpClass(cls):
        cls.patterns = hook.load_patterns(COMMON)

    def test_private_ip_adjacent_to_japanese(self):
        self.assertTrue(matches(self.patterns, fixture("接続先は10.", "20.30.40だった")))

    def test_cidr_notation_is_excluded(self):
        self.assertFalse(matches(self.patterns, fixture("cidr_blocks = 10.", "0.0.0/16")))

    def test_internal_hostname_adjacent_to_japanese(self):
        self.assertTrue(matches(self.patterns, fixture("billing-api.inter", "nalへ接続する")))

    def test_home_path_adjacent_to_japanese(self):
        self.assertTrue(matches(self.patterns, fixture("出力先は/Users/", "someone/.claude/です")))

    def test_rest_example_path_is_excluded(self):
        # 大文字小文字を区別するため、REST の例示パスは誤検知しない
        self.assertFalse(matches(self.patterns, "GET /api/v1/users/123/orders"))

    def test_url_credentials_are_detected(self):
        self.assertTrue(
            matches(self.patterns, fixture("DATABASE_URL=postgres://admin", ":secret@db:5432/x")))

    def test_documentation_placeholder_credentials_are_excluded(self):
        self.assertFalse(matches(self.patterns, "postgres://user:pass@host:5432/db"))

    def test_clean_japanese_prose_is_not_matched(self):
        self.assertFalse(matches(self.patterns, "技術的本質のみを一般化して記録する。"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
