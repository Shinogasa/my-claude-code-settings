#!/usr/bin/env python3
"""学習記録store CLIの境界を実Gitと一時HOMEで検証する。"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "learning-store.py"


class LearningStoreCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.home = self.base / "home"
        self.home.mkdir()
        self.env = os.environ.copy()
        self.env.update(HOME=str(self.home), XDG_CONFIG_HOME=str(self.base / "xdg"))

    def tearDown(self):
        self.temporary.cleanup()

    def cli(self, *arguments, env=None):
        return subprocess.run(
            [sys.executable, str(CLI), *arguments],
            text=True,
            capture_output=True,
            env=env or self.env,
            check=False,
        )

    def error_code(self, result):
        self.assertEqual(result.returncode, 2, result.stdout)
        return json.loads(result.stderr)["error"]["code"]

    def binding_path(self):
        return Path(self.env["XDG_CONFIG_HOME"]) / "agent-learning" / "config.json"

    def init_store(self, name="store"):
        repo = self.base / name
        repo.mkdir()
        result = self.cli("init", "--repo", str(repo))
        self.assertEqual(result.returncode, 0, result.stderr)
        return repo

    def file_hash(self, path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_init_creates_prepared_git_store_and_binding(self):
        repo = self.init_store()

        marker = json.loads((repo / ".learning-store.json").read_text(encoding="utf-8"))
        binding = json.loads(self.binding_path().read_text(encoding="utf-8"))
        self.assertEqual(marker["schema_version"], 1)
        self.assertEqual(marker["state"], "prepared")
        self.assertEqual(uuid.UUID(marker["store_id"]).version, 4)
        self.assertEqual(binding, {
            "schema_version": 1,
            "store_id": marker["store_id"],
            "store_root": str(repo),
        })
        branch = subprocess.check_output(
            ["git", "-C", str(repo), "branch", "--show-current"], text=True
        ).strip()
        self.assertEqual(branch, "learning-records")

        status = self.cli("status")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(json.loads(status.stdout), {
            "ok": True,
            "root": str(repo),
            "state": "prepared",
            "store_id": marker["store_id"],
            "writable": False,
        })

    def test_init_requires_empty_real_canonical_absolute_directory(self):
        missing = self.base / "missing"
        self.assertEqual(self.error_code(self.cli("init", "--repo", str(missing))), "INVALID_REPO")

        nonempty = self.base / "nonempty"
        nonempty.mkdir()
        (nonempty / "keep").write_text("unchanged", encoding="utf-8")
        before = self.file_hash(nonempty / "keep")
        self.assertEqual(self.error_code(self.cli("init", "--repo", str(nonempty))), "REPO_NOT_EMPTY")
        self.assertEqual(self.file_hash(nonempty / "keep"), before)

        relative = self.cli("init", "--repo", "relative-store")
        self.assertEqual(self.error_code(relative), "INVALID_REPO")

        target = self.base / "target"
        target.mkdir()
        link = self.base / "store-link"
        link.symlink_to(target, target_is_directory=True)
        self.assertEqual(self.error_code(self.cli("init", "--repo", str(link))), "INVALID_REPO")

    def test_existing_binding_blocks_other_init_without_mutating_target(self):
        first = self.init_store("first")
        binding_hash = self.file_hash(self.binding_path())
        marker_hash = self.file_hash(first / ".learning-store.json")
        other = self.base / "other"
        other.mkdir()

        result = self.cli("init", "--repo", str(other))

        self.assertEqual(self.error_code(result), "BINDING_CONFLICT")
        self.assertEqual(list(other.iterdir()), [])
        self.assertEqual(self.file_hash(self.binding_path()), binding_hash)
        self.assertEqual(self.file_hash(first / ".learning-store.json"), marker_hash)

    def test_bind_is_idempotent_and_replace_is_explicit(self):
        first = self.init_store("first")
        same = self.cli("bind", "--repo", str(first))
        self.assertEqual(same.returncode, 0, same.stderr)
        self.assertFalse(json.loads(same.stdout)["binding_changed"])

        second = self.base / "second"
        second.mkdir()
        subprocess.run(["git", "init", "-b", "learning-records", str(second)], check=True, capture_output=True)
        second_id = str(uuid.uuid4())
        (second / ".learning-store.json").write_text(
            json.dumps({"schema_version": 1, "state": "prepared", "store_id": second_id}) + "\n",
            encoding="utf-8",
        )
        binding_hash = self.file_hash(self.binding_path())

        refused = self.cli("bind", "--repo", str(second))
        self.assertEqual(self.error_code(refused), "BINDING_CONFLICT")
        self.assertEqual(self.file_hash(self.binding_path()), binding_hash)

        replaced = self.cli("bind", "--repo", str(second), "--replace-binding")
        self.assertEqual(replaced.returncode, 0, replaced.stderr)
        self.assertTrue(json.loads(replaced.stdout)["binding_changed"])
        self.assertEqual(json.loads(self.binding_path().read_text())["store_id"], second_id)

    def test_bind_rejects_git_child_and_marker_mismatch(self):
        outer = self.base / "outer"
        outer.mkdir()
        subprocess.run(["git", "init", "-b", "learning-records", str(outer)], check=True, capture_output=True)
        child = outer / "child"
        child.mkdir()
        (child / ".learning-store.json").write_text(
            json.dumps({"schema_version": 1, "state": "prepared", "store_id": str(uuid.uuid4())}) + "\n",
            encoding="utf-8",
        )
        self.assertEqual(self.error_code(self.cli("bind", "--repo", str(child))), "GIT_ROOT_MISMATCH")

        valid = self.init_store("valid")
        binding = json.loads(self.binding_path().read_text())
        marker = json.loads((valid / ".learning-store.json").read_text())
        marker["store_id"] = str(uuid.uuid4())
        (valid / ".learning-store.json").write_text(json.dumps(marker) + "\n", encoding="utf-8")
        self.assertNotEqual(binding["store_id"], marker["store_id"])
        self.assertEqual(self.error_code(self.cli("status")), "STORE_ID_MISMATCH")

    def test_status_distinguishes_unconfigured_unreadable_and_moved_store(self):
        self.assertEqual(self.error_code(self.cli("status")), "NOT_CONFIGURED")

        self.binding_path().parent.mkdir(parents=True)
        self.binding_path().write_text("not json\n", encoding="utf-8")
        self.assertEqual(self.error_code(self.cli("status")), "INVALID_BINDING")

        self.binding_path().write_text(
            json.dumps({
                "schema_version": 1,
                "store_id": str(uuid.uuid4()),
                "store_root": str(self.base / "moved"),
            }) + "\n",
            encoding="utf-8",
        )
        self.assertEqual(self.error_code(self.cli("status")), "STORE_NOT_FOUND")

    def test_binding_uses_home_fallback_without_xdg(self):
        env = self.env.copy()
        env.pop("XDG_CONFIG_HOME")
        repo = self.base / "fallback-store"
        repo.mkdir()

        result = self.cli("init", "--repo", str(repo), env=env)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.home / ".config/agent-learning/config.json").is_file())


if __name__ == "__main__":
    unittest.main()
