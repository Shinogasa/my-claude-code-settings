#!/usr/bin/env python3
"""setup-state.py の一括処理サブコマンドを検証する（ADR 0030）。

setup.sh は対象ごとにPythonを起動していた。一括処理は、1件ずつ呼んだときと
同じ判定・同じメッセージ・同じ終了コードを返すことを、ここで確かめる。
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE_TOOL = ROOT / "bin" / "setup-state.py"


def load_state_module():
    spec = importlib.util.spec_from_file_location("setup_state", STATE_TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_tool(*arguments, env=None):
    return subprocess.run(
        [sys.executable, str(STATE_TOOL), *arguments],
        text=True, capture_output=True, check=False, env=env,
    )


def compact(snapshot):
    """setup.sh が保存するのと同じ形式のJSON文字列にする。"""
    return json.dumps(snapshot, sort_keys=True, separators=(",", ":"))


class BatchTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = load_state_module()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.source = self.base / "source"
        self.source.write_text("source\n", encoding="utf-8")
        self.home = self.base / "home"
        self.home.mkdir()

    def tearDown(self):
        self.temporary.cleanup()


class ClassifyTargetsTests(BatchTestCase):
    def test_classifies_each_target_in_argument_order(self):
        linked = self.home / "linked"
        linked.symlink_to(self.source)
        wrong = self.home / "wrong"
        wrong.symlink_to(self.base)
        generated = self.home / "settings.json"
        generated.write_text("generated\n", encoding="utf-8")
        state_path = self.home / "state" / "ownership.json"
        self.state.save_state(
            state_path,
            {"version": 1, "generated": {str(generated): self.state.sha256_file(generated)}},
        )
        missing = self.home / "missing"

        result = run_tool(
            "classify-targets",
            "false", "", str(self.source), str(missing),
            "false", "", str(self.source), str(linked),
            "false", "", str(self.source), str(wrong),
            "true", str(state_path), str(self.source), str(generated),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["missing", "linked", "conflict", "managed-update"],
        )

    def test_generated_target_without_record_is_conflict(self):
        generated = self.home / "settings.json"
        generated.write_text("user\n", encoding="utf-8")
        result = run_tool(
            "classify-targets",
            "true", str(self.home / "absent.json"), str(self.source), str(generated),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "conflict\n")

    def test_rejects_incomplete_groups(self):
        result = run_tool("classify-targets", "false", "", str(self.source))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


class SnapshotPathsTests(BatchTestCase):
    def test_prints_one_compact_snapshot_per_line_in_order(self):
        link = self.home / "link"
        link.symlink_to(self.source)
        missing = self.home / "missing\nwith-newline"

        result = run_tool("snapshot-paths", str(self.source), str(link), str(missing))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                compact(self.state.snapshot_path(self.source)),
                compact(self.state.snapshot_path(link)),
                compact({"kind": "missing"}),
            ],
        )

    def test_no_paths_prints_nothing(self):
        result = run_tool("snapshot-paths")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")


class CheckLinkTopologyTests(BatchTestCase):
    def test_accepts_disjoint_source_and_destination(self):
        result = run_tool(
            "check-link-topology", str(self.source), str(self.home / "destination"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def test_rejects_destination_resolving_into_source(self):
        source_dir = self.base / "skills"
        source_dir.mkdir()
        parent = self.home / "parent"
        parent.symlink_to(source_dir)
        destination = parent / "skills"

        result = run_tool(
            "check-link-topology",
            str(self.source), str(self.home / "fine"),
            str(source_dir), str(destination),
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr,
            "link source and destination overlap after symlink resolution: "
            f"source={source_dir} destination={destination}\n",
        )

    def test_rejects_symlinked_skills_parent(self):
        real = self.base / "elsewhere"
        real.mkdir()
        skills = self.home / "skills"
        skills.symlink_to(real)
        destination = skills / "backend-patterns"

        result = run_tool("check-link-topology", str(self.source), str(destination))

        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            result.stderr,
            "skills parent symlink はrepo以外を指すか由来を確定できないため自動移行しない: "
            f"{skills}\n",
        )

    def test_rejects_incomplete_pairs(self):
        result = run_tool("check-link-topology", str(self.source))
        self.assertNotEqual(result.returncode, 0)


class ApplyLinksTests(BatchTestCase):
    def setUp(self):
        super().setUp()
        # mkdir と ln は PATH から呼ばれる。setup.sh と同じく差し替え可能であることを確かめる。
        self.bindir = self.base / "bin"
        self.bindir.mkdir()
        self.log = self.base / "commands.log"
        for name in ("mkdir", "ln"):
            stub = self.bindir / name
            stub.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' \"{name} $*\" >> \"$APPLY_LOG\"\n"
                f"exec /bin/{name} \"$@\"\n",
                encoding="utf-8",
            )
            stub.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{self.bindir}{os.pathsep}{os.environ['PATH']}",
            "APPLY_LOG": str(self.log),
        }

    def apply(self, *arguments):
        return run_tool("apply-links", *arguments, env=self.env)

    def test_creates_missing_links_with_mkdir_and_ln_from_path(self):
        destination = self.home / "nested" / "link"
        result = self.apply(str(self.source), str(destination), compact({"kind": "missing"}))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(destination.is_symlink())
        self.assertEqual(os.readlink(destination), str(self.source))
        self.assertEqual(
            self.log.read_text(encoding="utf-8").splitlines(),
            [f"mkdir -p {destination.parent}", f"ln -s {self.source} {destination}"],
        )

    def test_already_linked_target_is_left_alone(self):
        destination = self.home / "link"
        destination.symlink_to(self.source)
        snapshot = compact(self.state.snapshot_path(destination))

        result = self.apply(str(self.source), str(destination), snapshot)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("ln ", self.log.read_text(encoding="utf-8"))

    def test_snapshot_mismatch_stops_before_later_targets(self):
        changed = self.home / "changed"
        changed.write_text("late\n", encoding="utf-8")
        later = self.home / "later"

        result = self.apply(
            str(self.source), str(changed), compact({"kind": "missing"}),
            str(self.source), str(later), compact({"kind": "missing"}),
        )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, f"エラー: target changed after preflight: {changed}\n")
        self.assertFalse(later.exists() or later.is_symlink())

    def test_link_appearing_after_snapshot_check_is_not_replaced(self):
        destination = self.home / "late"
        wrong = self.base / "wrong"
        wrong.write_text("user\n", encoding="utf-8")
        # mkdir の直後に別プロセスがリンクを作った状況を再現する。
        (self.bindir / "mkdir").write_text(
            "#!/bin/sh\n"
            f"/bin/ln -s {wrong} {destination}\n"
            "exec /bin/mkdir \"$@\"\n",
            encoding="utf-8",
        )

        result = self.apply(str(self.source), str(destination), compact({"kind": "missing"}))

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, f"エラー: target changed before link apply: {destination}\n")
        self.assertEqual(destination.resolve(), wrong.resolve())

    def test_ln_failure_stops_with_its_status(self):
        (self.bindir / "ln").write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
        first = self.home / "first"
        second = self.home / "second"

        result = self.apply(
            str(self.source), str(first), compact({"kind": "missing"}),
            str(self.source), str(second), compact({"kind": "missing"}),
        )

        self.assertEqual(result.returncode, 1)
        self.assertFalse(second.exists() or second.is_symlink())
        self.assertEqual(
            [line.split()[0] for line in self.log.read_text(encoding="utf-8").splitlines()],
            ["mkdir"],
        )


if __name__ == "__main__":
    unittest.main()
