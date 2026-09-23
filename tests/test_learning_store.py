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
FRONTMATTER_KEYS = (
    "schema_version", "id", "event_id", "observed_at", "kind", "mode",
    "capability_id", "scope", "initial_result", "retry_result",
    "transfer_result", "supersedes",
)


class LearningStoreCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.home = self.base / "home"
        self.home.mkdir()
        self.env = os.environ.copy()
        self.env.update(HOME=str(self.home), XDG_CONFIG_HOME=str(self.base / "xdg"))
        self.event_id = str(uuid.uuid4())

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

    def make_prepared_store(self):
        self.store = self.init_store()
        return self.store

    def marker(self):
        return json.loads((self.store / ".learning-store.json").read_text(encoding="utf-8"))

    def make_active_store(self):
        self.make_prepared_store()
        marker = self.marker()
        marker["state"] = "active"
        (self.store / ".learning-store.json").write_text(
            json.dumps(marker, sort_keys=True) + "\n", encoding="utf-8"
        )
        return self.store

    def record_payload(self, *, record_id=None, event_id=None, supersedes=(),
                       body="## 担当範囲\n仮説を区別する", capability_id=None,
                       scope="競合する仮説を観測で区別する"):
        return {
            "schema_version": 1,
            "id": record_id or str(uuid.uuid4()),
            "event_id": event_id or self.event_id,
            "observed_at": "2026-09-23T00:00:00+00:00",
            "kind": "code",
            "mode": "investigate",
            "capability_id": capability_id or "diagnosis.distinguish-competing-hypotheses",
            "scope": scope,
            "initial_result": "unverified",
            "retry_result": "not_attempted",
            "transfer_result": "not_attempted",
            "supersedes": list(supersedes),
            "body": body,
        }

    def write_record_fixture(self, value, *, filename_id=None):
        target_id = filename_id or value["id"]
        target = self.store / "records" / value["kind"] / "2026" / f"2026-09-23-{target_id}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = ["---"]
        lines.extend(
            f"{key}: {json.dumps(value[key], ensure_ascii=False)}"
            for key in FRONTMATTER_KEYS
        )
        lines.extend(["---", "", value["body"], ""])
        target.write_text("\n".join(lines), encoding="utf-8")
        return target

    def branch_fixture(self):
        self.make_active_store()
        first = self.record_payload()
        left = self.record_payload(event_id=first["event_id"], supersedes=[first["id"]])
        right = self.record_payload(event_id=first["event_id"], supersedes=[first["id"]])
        for value in (first, left, right):
            self.write_record_fixture(value)
        return first, left, right

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

    def test_list_distinguishes_empty_store_and_returns_capability_scope(self):
        self.make_active_store()
        empty = self.cli("list")
        self.assertEqual(empty.returncode, 0, empty.stderr)
        self.assertEqual(json.loads(empty.stdout), {"ok": True, "capabilities": [], "count": 0})

        first = self.record_payload(scope="仮説Aと仮説Bを観測で区別する")
        self.write_record_fixture(first)
        listed = self.cli("list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(json.loads(listed.stdout)["capabilities"], [{
            "capability_id": first["capability_id"],
            "count": 1,
            "scopes": [first["scope"]],
        }])

    def test_list_returns_only_the_effective_correction(self):
        self.make_active_store()
        first = self.record_payload(body="初版")
        corrected = self.record_payload(
            event_id=first["event_id"], supersedes=[first["id"]], body="訂正版"
        )
        self.write_record_fixture(first)
        self.write_record_fixture(corrected)

        result = self.cli("list", "--capability", first["capability_id"])

        self.assertEqual(result.returncode, 0, result.stderr)
        records = json.loads(result.stdout)["records"]
        self.assertEqual([item["id"] for item in records], [corrected["id"]])
        self.assertEqual(records[0]["observed_at"], "2026-09-23T00:00:00+00:00")

    def test_branch_is_an_explicit_event_conflict(self):
        first, left, right = self.branch_fixture()

        result = self.cli("list", "--capability", first["capability_id"])

        self.assertEqual(self.error_code(result), "EVENT_CONFLICT")
        detail = json.loads(result.stderr)["error"]["conflicts"]
        self.assertEqual(set(detail[first["event_id"]]), {left["id"], right["id"]})

    def test_invalid_history_rejects_missing_parent(self):
        self.make_active_store()
        self.write_record_fixture(self.record_payload(supersedes=[str(uuid.uuid4())]))
        self.assertEqual(self.error_code(self.cli("list")), "INVALID_HISTORY")

    def test_invalid_history_rejects_cross_event_parent(self):
        self.make_active_store()
        first = self.record_payload()
        cross = self.record_payload(event_id=str(uuid.uuid4()), supersedes=[first["id"]])
        self.write_record_fixture(first)
        self.write_record_fixture(cross)
        self.assertEqual(self.error_code(self.cli("list")), "INVALID_HISTORY")

    def test_invalid_history_rejects_cycle(self):
        self.make_active_store()
        left_id = str(uuid.uuid4())
        right_id = str(uuid.uuid4())
        self.write_record_fixture(self.record_payload(record_id=left_id, supersedes=[right_id]))
        self.write_record_fixture(self.record_payload(record_id=right_id, supersedes=[left_id]))
        self.assertEqual(self.error_code(self.cli("list")), "INVALID_HISTORY")

    def test_list_rejects_malformed_record(self):
        self.make_active_store()
        target = self.store / "records/code/2026/broken.md"
        target.parent.mkdir(parents=True)
        target.write_text("---\nid: not-json\n---\n", encoding="utf-8")
        self.assertEqual(self.error_code(self.cli("list")), "INVALID_RECORD")

    def test_list_rejects_unknown_record_schema(self):
        self.make_active_store()
        value = self.record_payload()
        value["schema_version"] = 2
        self.write_record_fixture(value)
        self.assertEqual(self.error_code(self.cli("list")), "INVALID_RECORD")

    def test_list_rejects_record_filename_id_mismatch(self):
        self.make_active_store()
        self.write_record_fixture(self.record_payload(), filename_id=str(uuid.uuid4()))
        self.assertEqual(self.error_code(self.cli("list")), "INVALID_RECORD")

    def test_list_rejects_symlinked_record_tree_and_broken_operation(self):
        self.make_active_store()
        outside = self.base / "outside"
        outside.mkdir()
        records = self.store / "records"
        records.symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.error_code(self.cli("list")), "UNSAFE_PATH")

        records.unlink()
        operation = self.store / "operations/2026/broken.json"
        operation.parent.mkdir(parents=True)
        operation.write_text("{broken", encoding="utf-8")
        self.assertEqual(self.error_code(self.cli("list")), "INVALID_OPERATION")


if __name__ == "__main__":
    unittest.main()
