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

    def cli_with_json(self, value, *record_arguments):
        input_path = self.base / f"input-{uuid.uuid4()}.json"
        input_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return self.cli("record", *record_arguments, "--input", str(input_path))

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
        source = self.make_legacy_source(with_records=False)
        result = self.cli("import", "--source", str(source))
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.store

    def force_active_marker(self):
        marker = self.marker()
        marker["state"] = "active"
        (self.store / ".learning-store.json").write_text(
            json.dumps(marker, sort_keys=True) + "\n", encoding="utf-8"
        )

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

    def list_event(self, event_id):
        result = self.cli("list", "--capability", "diagnosis.distinguish-competing-hypotheses")
        self.assertEqual(result.returncode, 0, result.stderr)
        return [item for item in json.loads(result.stdout)["records"] if item["event_id"] == event_id]

    def operation_payload(self, *, record_id=None, event_id=None):
        return {
            "schema_version": 1,
            "id": record_id or str(uuid.uuid4()),
            "event_id": event_id or self.event_id,
            "observed_at": "2026-09-23T00:00:00+00:00",
            "kind": "operation",
            "capability_id": "diagnosis.distinguish-competing-hypotheses",
            "end_reason": "completed",
            "wait_count": 1,
        }

    def make_legacy_source(self, *, with_records=True):
        source = self.base / "settings"
        source.mkdir()
        if with_records:
            decision = source / "learning/entries/decision.md"
            code = source / "learning/code/entries/code.md"
            decision.parent.mkdir(parents=True)
            code.parent.mkdir(parents=True)
            decision.write_bytes(b"decision original\n")
            code.write_bytes(b"code original\n")
        empty_hooks = self.base / "empty-hooks"
        empty_hooks.mkdir(exist_ok=True)
        subprocess.run(["git", "init", "-b", "main", str(source)], check=True, capture_output=True, env=self.env)
        subprocess.run(["git", "-C", str(source), "config", "user.name", "Fixture"], check=True, env=self.env)
        subprocess.run(["git", "-C", str(source), "config", "user.email", "fixture@example.invalid"], check=True, env=self.env)
        subprocess.run(["git", "-C", str(source), "add", "."], check=True, env=self.env)
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={empty_hooks}",
             "-C", str(source), "commit", "--allow-empty", "-m", "fixture"],
            check=True, capture_output=True, env=self.env,
        )
        return source

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

    def test_active_marker_requires_one_verified_import_manifest(self):
        self.make_prepared_store()
        self.force_active_marker()

        self.assertEqual(self.error_code(self.cli("status")), "INCOMPLETE_IMPORT")
        self.assertEqual(
            self.error_code(self.cli_with_json(self.record_payload())),
            "INCOMPLETE_IMPORT",
        )

        marker = self.marker()
        marker["state"] = "prepared"
        (self.store / ".learning-store.json").write_text(
            json.dumps(marker, sort_keys=True) + "\n", encoding="utf-8"
        )
        source = self.make_legacy_source()
        imported = self.cli("import", "--source", str(source))
        self.assertEqual(imported.returncode, 0, imported.stderr)
        (self.store / "legacy/decision/decision.md").write_bytes(b"tampered\n")
        self.assertEqual(self.error_code(self.cli("status")), "INCOMPLETE_IMPORT")

    def test_active_store_rejects_legacy_file_missing_from_manifest(self):
        self.make_active_store()
        extra = self.store / "legacy/decision/extra.md"
        extra.parent.mkdir(parents=True)
        extra.write_bytes(b"not imported\n")

        self.assertEqual(self.error_code(self.cli("status")), "INCOMPLETE_IMPORT")

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

    def test_git_calls_ignore_poisoned_path_and_git_environment(self):
        self.make_active_store()
        fake_bin = self.base / "fake-bin"
        fake_bin.mkdir()
        sentinel = self.base / "fake-git-ran"
        fake_git = fake_bin / "git"
        fake_git.write_text(
            "#!/bin/sh\nprintf invoked > \"$FAKE_GIT_SENTINEL\"\nexit 91\n",
            encoding="utf-8",
        )
        fake_git.chmod(0o755)
        poisoned = self.env.copy()
        poisoned.update(
            PATH=f"{fake_bin}{os.pathsep}{poisoned['PATH']}",
            GIT_DIR=str(self.base / "attacker-git-dir"),
            GIT_WORK_TREE=str(self.base / "attacker-work-tree"),
            FAKE_GIT_SENTINEL=str(sentinel),
        )

        result = self.cli("status", env=poisoned)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["root"], str(self.store))
        self.assertFalse(sentinel.exists())

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

    def test_record_is_exclusive_and_idempotent_by_generated_bytes(self):
        self.make_active_store()
        value = self.record_payload()

        first = self.cli_with_json(value)
        repeated = self.cli_with_json(value)
        changed = dict(value, body="異なる本文")
        conflict = self.cli_with_json(changed)

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue(json.loads(first.stdout)["created"])
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertFalse(json.loads(repeated.stdout)["created"])
        self.assertEqual(json.loads(first.stdout)["path"], json.loads(repeated.stdout)["path"])
        self.assertEqual(self.error_code(conflict), "RECORD_ID_CONFLICT")
        self.assertEqual(len(tuple((self.store / "records").rglob("*.md"))), 1)

    def test_record_rejects_prepared_store_and_duplicate_initial_event(self):
        self.make_prepared_store()
        self.assertEqual(self.error_code(self.cli_with_json(self.record_payload())), "STORE_NOT_ACTIVE")

        source = self.make_legacy_source(with_records=False)
        activated = self.cli("import", "--source", str(source))
        self.assertEqual(activated.returncode, 0, activated.stderr)
        first = self.record_payload()
        self.assertEqual(self.cli_with_json(first).returncode, 0)
        duplicate = self.record_payload(event_id=first["event_id"])
        self.assertEqual(self.error_code(self.cli_with_json(duplicate)), "INVALID_SUPERSEDES")

    def test_record_allows_idempotent_resend_of_non_head_revision(self):
        self.make_active_store()
        first = self.record_payload(body="初版")
        corrected = self.record_payload(
            event_id=first["event_id"], supersedes=[first["id"]], body="訂正版"
        )
        self.assertEqual(self.cli_with_json(first).returncode, 0)
        self.assertEqual(self.cli_with_json(corrected).returncode, 0)

        repeated = self.cli_with_json(first)

        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertFalse(json.loads(repeated.stdout)["created"])
        self.assertEqual([item["id"] for item in self.list_event(first["event_id"])], [corrected["id"]])

    def test_branch_requires_all_current_heads_and_integration_reason(self):
        first, left, right = self.branch_fixture()
        incomplete = self.record_payload(
            event_id=first["event_id"], supersedes=[left["id"]],
            body="## 統合理由\n一方だけを採用",
        )
        self.assertEqual(
            self.error_code(self.cli_with_json(incomplete, "--resolve-conflict")),
            "INVALID_SUPERSEDES",
        )
        no_reason = self.record_payload(
            event_id=first["event_id"], supersedes=[left["id"], right["id"]],
            body="理由見出しなし",
        )
        self.assertEqual(
            self.error_code(self.cli_with_json(no_reason, "--resolve-conflict")),
            "INVALID_SUPERSEDES",
        )
        complete = self.record_payload(
            event_id=first["event_id"], supersedes=[left["id"], right["id"]],
            body="## 統合理由\n両枝の証拠を照合し未確定はunverified",
        )

        result = self.cli_with_json(complete, "--resolve-conflict")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([item["id"] for item in self.list_event(first["event_id"])], [complete["id"]])

    def test_normal_record_rejects_branch_and_resolve_rejects_single_head(self):
        first, left, right = self.branch_fixture()
        correction = self.record_payload(
            event_id=first["event_id"], supersedes=[left["id"], right["id"]],
            body="## 統合理由\n統合する",
        )
        self.assertEqual(self.error_code(self.cli_with_json(correction)), "EVENT_CONFLICT")

        fresh_event = self.record_payload(event_id=str(uuid.uuid4()))
        self.assertEqual(self.error_code(self.cli_with_json(fresh_event, "--resolve-conflict")), "INVALID_SUPERSEDES")

    def test_operation_is_idempotent_and_excluded_from_capability_list(self):
        self.make_active_store()
        operation = self.operation_payload()
        first = self.cli_with_json(operation)
        repeated = self.cli_with_json(operation)

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue(json.loads(first.stdout)["created"])
        self.assertFalse(json.loads(repeated.stdout)["created"])
        listed = self.cli("list")
        self.assertEqual(json.loads(listed.stdout)["count"], 0)
        self.assertEqual(len(tuple((self.store / "operations").rglob("*.json"))), 1)

    def test_two_processes_publish_one_record(self):
        self.make_active_store()
        value = self.record_payload()
        input_path = self.base / "concurrent.json"
        input_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        command = [sys.executable, str(CLI), "record", "--input", str(input_path)]
        processes = [
            subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
            for _ in range(2)
        ]
        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr)
            results.append(json.loads(stdout))
        self.assertEqual(sorted(item["created"] for item in results), [False, True])
        self.assertEqual(len(tuple((self.store / "records").rglob("*.md"))), 1)

    def test_save_record_rechecks_the_store_binding_not_process_environment(self):
        self.make_active_store()
        sys.path.insert(0, str(ROOT / "bin"))
        try:
            from learning_store.store import load_store, save_record

            store = load_store(self.env)
            result = save_record(store, self.record_payload())
        finally:
            sys.path.remove(str(ROOT / "bin"))

        self.assertTrue(result["created"])
        self.assertEqual(result["event_id"], self.event_id)

    def test_record_rejects_symlink_input_and_symlinked_destination(self):
        self.make_active_store()
        value = self.record_payload()
        real_input = self.base / "real-input.json"
        real_input.write_text(json.dumps(value), encoding="utf-8")
        input_link = self.base / "input-link.json"
        input_link.symlink_to(real_input)
        self.assertEqual(
            self.error_code(self.cli("record", "--input", str(input_link))),
            "INVALID_INPUT",
        )

        outside = self.base / "outside-records"
        outside.mkdir()
        (self.store / "records").symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.error_code(self.cli_with_json(value)), "UNSAFE_PATH")

    def test_record_rejects_oversized_input_before_json_decode(self):
        input_path = self.base / "oversized-input.json"
        input_path.write_bytes(b" " * (1024 * 1024 + 1))

        result = self.cli("record", "--input", str(input_path))

        self.assertEqual(self.error_code(result), "INVALID_INPUT")
        self.assertIn("size上限", json.loads(result.stderr)["error"]["message"])

    def test_list_rejects_oversized_record_before_parse(self):
        self.make_active_store()
        value = self.record_payload()
        target = self.write_record_fixture(value)
        target.write_bytes(b"x" * (1024 * 1024 + 1))

        result = self.cli("list")
        self.assertEqual(self.error_code(result), "INVALID_RECORD")
        self.assertIn("size上限", json.loads(result.stderr)["error"]["message"])

    def test_active_store_rejects_oversized_manifest_and_legacy(self):
        self.make_prepared_store()
        source = self.make_legacy_source()
        imported = self.cli("import", "--source", str(source))
        self.assertEqual(imported.returncode, 0, imported.stderr)
        manifest = next((self.store / "imports").glob("*.json"))
        manifest.write_bytes(manifest.read_bytes() + b" " * (1024 * 1024))
        oversized_manifest = self.cli("status")
        self.assertEqual(self.error_code(oversized_manifest), "IMPORT_CONFLICT")
        self.assertIn(
            "size上限",
            json.loads(oversized_manifest.stderr)["error"]["message"],
        )

        manifest.write_text(
            json.dumps(json.loads(manifest.read_text(encoding="utf-8")), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        legacy = self.store / "legacy/decision/decision.md"
        legacy.write_bytes(b"x" * (8 * 1024 * 1024 + 1))
        oversized_legacy = self.cli("status")
        self.assertEqual(self.error_code(oversized_legacy), "INCOMPLETE_IMPORT")
        self.assertIn(
            "size上限",
            json.loads(oversized_legacy.stderr)["error"]["message"],
        )

    def test_store_and_write_directories_reject_group_or_other_writes(self):
        self.make_active_store()
        original_root_mode = self.store.stat().st_mode & 0o777
        self.store.chmod(0o777)
        try:
            self.assertEqual(
                self.error_code(self.cli("status")),
                "UNSAFE_PERMISSIONS",
            )
        finally:
            self.store.chmod(original_root_mode)

        records = self.store / "records"
        records.mkdir()
        records.chmod(0o777)
        self.assertEqual(
            self.error_code(self.cli("status")),
            "UNSAFE_PERMISSIONS",
        )
        self.assertEqual(
            self.error_code(self.cli_with_json(self.record_payload())),
            "UNSAFE_PERMISSIONS",
        )

    def test_import_copies_tracked_legacy_bytes_and_activates_after_manifest(self):
        self.make_prepared_store()
        source = self.make_legacy_source()
        source_commit = subprocess.check_output(
            ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
        ).strip()

        result = self.cli("import", "--source", str(source))

        self.assertEqual(result.returncode, 0, result.stderr)
        response = json.loads(result.stdout)
        self.assertTrue(response["created"])
        self.assertEqual(response["count"], 2)
        self.assertEqual(self.marker()["state"], "active")
        self.assertEqual(
            (self.store / "legacy/decision/decision.md").read_bytes(),
            (source / "learning/entries/decision.md").read_bytes(),
        )
        self.assertEqual(
            (self.store / "legacy/code/code.md").read_bytes(),
            (source / "learning/code/entries/code.md").read_bytes(),
        )
        manifests = tuple((self.store / "imports").glob("*.json"))
        self.assertEqual(len(manifests), 1)
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        self.assertEqual(manifest["source_commit"], source_commit)
        self.assertEqual(manifest["count"], 2)
        self.assertEqual(
            {item["source_path"] for item in manifest["files"]},
            {"learning/entries/decision.md", "learning/code/entries/code.md"},
        )
        for item in manifest["files"]:
            source_bytes = (source / item["source_path"]).read_bytes()
            self.assertEqual(item["sha256"], hashlib.sha256(source_bytes).hexdigest())

    def test_partial_import_conflict_never_activates_and_can_resume(self):
        self.make_prepared_store()
        source = self.make_legacy_source()
        decision = source / "learning/entries/decision.md"
        code = source / "learning/code/entries/code.md"
        legacy_decision = self.store / "legacy/decision/decision.md"
        legacy_code = self.store / "legacy/code/code.md"
        legacy_decision.parent.mkdir(parents=True)
        legacy_code.parent.mkdir(parents=True)
        legacy_decision.write_bytes(decision.read_bytes())
        legacy_code.write_bytes(b"conflicting existing bytes\n")

        failed = self.cli("import", "--source", str(source))

        self.assertEqual(self.error_code(failed), "LEGACY_CONFLICT")
        self.assertEqual(self.marker()["state"], "prepared")
        self.assertEqual(legacy_decision.read_bytes(), decision.read_bytes())
        self.assertFalse((self.store / "imports").exists())

        legacy_code.write_bytes(code.read_bytes())
        resumed = self.cli("import", "--source", str(source))
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(self.marker()["state"], "active")
        self.assertEqual(legacy_code.read_bytes(), code.read_bytes())

    def test_empty_import_writes_manifest_and_is_idempotent(self):
        self.make_prepared_store()
        source = self.make_legacy_source(with_records=False)

        first = self.cli("import", "--source", str(source))
        repeated = self.cli("import", "--source", str(source))

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue(json.loads(first.stdout)["created"])
        self.assertEqual(json.loads(first.stdout)["count"], 0)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertFalse(json.loads(repeated.stdout)["created"])
        self.assertEqual(len(tuple((self.store / "imports").glob("*.json"))), 1)
        self.assertEqual(self.marker()["state"], "active")
        status = self.cli("status")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertTrue(json.loads(status.stdout)["writable"])

    def test_import_rejects_symlink_source_and_uncommitted_target_changes(self):
        self.make_prepared_store()
        source = self.make_legacy_source()
        source_link = self.base / "settings-link"
        source_link.symlink_to(source, target_is_directory=True)
        self.assertEqual(
            self.error_code(self.cli("import", "--source", str(source_link))),
            "INVALID_SOURCE",
        )
        (source / "learning/entries/decision.md").write_bytes(b"dirty change\n")
        failed = self.cli("import", "--source", str(source))
        self.assertEqual(self.error_code(failed), "SOURCE_NOT_CLEAN")
        self.assertEqual(self.marker()["state"], "prepared")

    def test_active_import_rejects_changed_source(self):
        self.make_prepared_store()
        source = self.make_legacy_source()
        first = self.cli("import", "--source", str(source))
        self.assertEqual(first.returncode, 0, first.stderr)
        (source / "learning/entries/new.md").write_bytes(b"new legacy\n")
        subprocess.run(["git", "-C", str(source), "add", "."], check=True, env=self.env)
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={self.base / 'empty-hooks'}",
             "-C", str(source), "commit", "-m", "changed"],
            check=True, capture_output=True, env=self.env,
        )

        changed = self.cli("import", "--source", str(source))

        self.assertEqual(self.error_code(changed), "IMPORT_CONFLICT")
        self.assertEqual(len(tuple((self.store / "imports").glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
