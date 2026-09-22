#!/usr/bin/env python3
"""Codex のサブエージェント既定ペア設定を検証する。"""
import importlib.util
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "configure_codex_agent_defaults.py"
sys.path.insert(0, str(SCRIPT.parent))


def load_module():
    spec = importlib.util.spec_from_file_location("configure_codex_agent_defaults", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"failed to load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CodexAgentDefaultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.defaults = load_module()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.config = self.base / "config.toml"

    def tearDown(self):
        self.temporary.cleanup()

    def test_creates_missing_config_with_private_permissions(self):
        outcome = self.defaults.configure(self.config)

        self.assertEqual(outcome, "updated")
        with self.config.open("rb") as config_file:
            agents = tomllib.load(config_file)["agents"]
        self.assertEqual(agents, self.defaults.DEFAULTS)
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)

    def test_updates_only_target_keys_and_preserves_comments_and_secrets(self):
        self.config.write_text(
            'model_provider = "private-gateway" # keep provider comment\n'
            '[private]\n'
            'token = "must-stay-local"\n'
            '[agents]\n'
            'max_concurrent_threads_per_session = 4\n'
            'default_subagent_model = "old-model" # keep model comment\n'
            'default_subagent_reasoning_effort = "xhigh"\n',
            encoding="utf-8",
        )
        os.chmod(self.config, 0o600)

        outcome = self.defaults.configure(self.config)

        self.assertEqual(outcome, "updated")
        updated = self.config.read_text(encoding="utf-8")
        self.assertIn('token = "must-stay-local"', updated)
        self.assertIn('# keep provider comment', updated)
        self.assertIn('# keep model comment', updated)
        parsed = tomllib.loads(updated)
        self.assertEqual(parsed["private"]["token"], "must-stay-local")
        self.assertEqual(parsed["agents"]["max_concurrent_threads_per_session"], 4)
        for key, value in self.defaults.DEFAULTS.items():
            self.assertEqual(parsed["agents"][key], value)

    def test_adds_defaults_to_existing_agents_table(self):
        self.config.write_text(
            '[agents]\nmax_concurrent_threads_per_session = 3\n',
            encoding="utf-8",
        )
        os.chmod(self.config, 0o600)

        self.assertEqual(self.defaults.configure(self.config), "updated")

        parsed = tomllib.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual(parsed["agents"]["max_concurrent_threads_per_session"], 3)
        for key, value in self.defaults.DEFAULTS.items():
            self.assertEqual(parsed["agents"][key], value)

    def test_ignores_table_syntax_inside_multiline_strings(self):
        original_note = (
            'note = """\n'
            '[agents]\n'
            'default_subagent_model = "not-a-table"\n'
            '[[other]]\n'
            '"""\n'
        )
        self.config.write_text(
            original_note + '[agents]\nmax_concurrent_threads_per_session = 3\n',
            encoding="utf-8",
        )
        os.chmod(self.config, 0o600)

        self.assertEqual(self.defaults.configure(self.config), "updated")

        updated = self.config.read_text(encoding="utf-8")
        self.assertIn(original_note, updated)
        parsed = tomllib.loads(updated)
        self.assertEqual(parsed["note"], "[agents]\ndefault_subagent_model = \"not-a-table\"\n[[other]]\n")
        self.assertEqual(parsed["agents"]["max_concurrent_threads_per_session"], 3)
        for key, value in self.defaults.DEFAULTS.items():
            self.assertEqual(parsed["agents"][key], value)

    def test_second_run_is_byte_and_mtime_idempotent(self):
        self.assertEqual(self.defaults.configure(self.config), "updated")
        first_bytes = self.config.read_bytes()
        first_stat = self.config.stat()

        self.assertEqual(self.defaults.configure(self.config), "unchanged")

        self.assertEqual(self.config.read_bytes(), first_bytes)
        self.assertEqual(self.config.stat().st_mtime_ns, first_stat.st_mtime_ns)

    def test_successful_update_advances_mtime_on_macos(self):
        if sys.platform != "darwin":
            self.skipTest("macOSのmetadata copy検査ではない")
        self.config.write_text('model = "test"\n', encoding="utf-8")
        os.chmod(self.config, 0o600)
        old_time_ns = 946_684_800_000_000_000
        os.utime(self.config, ns=(old_time_ns, old_time_ns))

        self.assertEqual(self.defaults.configure(self.config), "updated")

        self.assertGreater(self.config.stat().st_mtime_ns, old_time_ns)

    def test_rejects_symlink_and_unsupported_agents_shape_without_mutation(self):
        target = self.base / "target.toml"
        target.write_text('model = "keep"\n', encoding="utf-8")
        self.config.symlink_to(target)
        with self.assertRaises(self.defaults.ConfigurationError):
            self.defaults.configure(self.config)
        self.assertEqual(target.read_text(encoding="utf-8"), 'model = "keep"\n')

        self.config.unlink()
        fixture = 'agents = { default_subagent_model = "old" }\n'
        self.config.write_text(fixture, encoding="utf-8")
        os.chmod(self.config, 0o600)
        with self.assertRaises(self.defaults.ConfigurationError):
            self.defaults.configure(self.config)
        self.assertEqual(self.config.read_text(encoding="utf-8"), fixture)

    def test_preserves_existing_file_mode(self):
        self.config.write_text('model = "test"\n', encoding="utf-8")
        os.chmod(self.config, 0o600)

        self.defaults.configure(self.config)

        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)

    def test_preserves_existing_file_group(self):
        alternate_groups = [group for group in os.getgroups() if group != os.getgid()]
        if not alternate_groups:
            self.skipTest("別groupを利用できないためgroup保持を検証できない")
        self.config.write_text('model = "test"\n', encoding="utf-8")
        os.chmod(self.config, 0o600)
        try:
            os.chown(self.config, -1, alternate_groups[0])
        except PermissionError:
            self.skipTest("別groupへ変更する権限がないためgroup保持を検証できない")

        self.defaults.configure(self.config)

        self.assertEqual(self.config.stat().st_gid, alternate_groups[0])

    def test_preserves_existing_extended_attributes_on_macos(self):
        xattr = shutil.which("xattr")
        if sys.platform != "darwin" or xattr is None:
            self.skipTest("macOSのxattr検査ではない")
        self.config.write_text('model = "test"\n', encoding="utf-8")
        os.chmod(self.config, 0o600)
        subprocess.run(
            [xattr, "-w", "com.example.codex-test", "preserve-me", self.config],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        self.defaults.configure(self.config)

        result = subprocess.run(
            [xattr, "-p", "com.example.codex-test", self.config],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout.rstrip("\n"), "preserve-me")

    def test_preserves_existing_acl_on_macos(self):
        chmod = shutil.which("chmod")
        ls = shutil.which("ls")
        if sys.platform != "darwin" or chmod is None or ls is None:
            self.skipTest("macOSのACL検査ではない")
        self.config.write_text('model = "test"\n', encoding="utf-8")
        os.chmod(self.config, 0o600)
        subprocess.run(
            [chmod, "+a", "everyone deny write", self.config],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        self.defaults.configure(self.config)

        result = subprocess.run(
            [ls, "-le", self.config],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("deny write", result.stdout)

    def test_rejects_group_writable_config_without_mutation(self):
        original = b'model = "test"\n'
        self.config.write_bytes(original)
        self.config.chmod(0o660)

        with self.assertRaises(self.defaults.ConfigurationError):
            self.defaults.configure(self.config)

        self.assertEqual(self.config.read_bytes(), original)

    def test_rejects_group_readable_config_without_mutation(self):
        original = b'model = "test"\n'
        self.config.write_bytes(original)
        self.config.chmod(0o640)

        with self.assertRaises(self.defaults.ConfigurationError):
            self.defaults.configure(self.config)

        self.assertEqual(self.config.read_bytes(), original)

    def test_rejects_execute_and_special_mode_bits_without_mutation(self):
        original = b'model = "test"\n'
        for index, mode in enumerate((0o700, 0o610, 0o1600)):
            with self.subTest(mode=oct(mode)):
                config = self.base / f"unsafe-mode-{index}.toml"
                config.write_bytes(original)
                config.chmod(mode)
                if stat.S_IMODE(config.stat().st_mode) != mode:
                    self.skipTest(f"{oct(mode)}をfixtureへ設定できない")

                with self.assertRaises(self.defaults.ConfigurationError):
                    self.defaults.configure(config)

                self.assertEqual(config.read_bytes(), original)
                self.assertEqual(stat.S_IMODE(config.stat().st_mode), mode)

    def test_rejects_config_with_read_acl_without_mutation(self):
        chmod = shutil.which("chmod")
        if sys.platform != "darwin" or chmod is None:
            self.skipTest("macOSのACL検査ではない")
        original = b'model = "test"\n'
        self.config.write_bytes(original)
        subprocess.run(
            [chmod, "+a", "everyone allow read", self.config],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        with self.assertRaises(self.defaults.ConfigurationError):
            self.defaults.configure(self.config)

        self.assertEqual(self.config.read_bytes(), original)

    def test_rejects_config_with_mutating_acl_without_mutation(self):
        chmod = shutil.which("chmod")
        if sys.platform != "darwin" or chmod is None:
            self.skipTest("macOSのACL検査ではない")
        for index, permission in enumerate(("write", "delete")):
            with self.subTest(permission=permission):
                config = self.base / f"acl-config-{index}.toml"
                original = b'model = "test"\n'
                config.write_bytes(original)
                os.chmod(config, 0o600)
                subprocess.run(
                    [chmod, "+a", f"everyone allow {permission}", config],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

                with self.assertRaises(self.defaults.ConfigurationError):
                    self.defaults.configure(config)

                self.assertEqual(config.read_bytes(), original)

    def test_inspects_mutating_allow_acl_after_deny_entry(self):
        chmod = shutil.which("chmod")
        if sys.platform != "darwin" or chmod is None:
            self.skipTest("macOSのACL検査ではない")
        original = b'model = "test"\n'
        self.config.write_bytes(original)
        os.chmod(self.config, 0o600)
        subprocess.run(
            [chmod, "+a", "everyone allow write", self.config],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [chmod, "+a#", "0", "everyone deny write", self.config],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        with self.assertRaises(self.defaults.ConfigurationError):
            self.defaults.configure(self.config)

        self.assertEqual(self.config.read_bytes(), original)

    def test_acl_inspector_finds_mutating_allow_after_deny_entry(self):
        chmod = shutil.which("chmod")
        if sys.platform != "darwin" or chmod is None:
            self.skipTest("macOSのACL検査ではない")
        self.config.write_text('model = "test"\n', encoding="utf-8")
        subprocess.run(
            [chmod, "+a", "everyone allow write", self.config],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [chmod, "+a#", "0", "everyone deny write", self.config],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        descriptor = os.open(self.config, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            self.assertTrue(self.defaults._extended_acl_allows_mutation(descriptor))
        finally:
            os.close(descriptor)

    def test_rejects_symlink_parent_without_creating_config(self):
        real_parent = self.base / "real-codex"
        real_parent.mkdir(mode=0o700)
        linked_parent = self.base / "linked-codex"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        config = linked_parent / "config.toml"

        with self.assertRaises(self.defaults.ConfigurationError):
            self.defaults.configure(config)

        self.assertFalse((real_parent / "config.toml").exists())

    def test_rejects_group_writable_parent_without_creating_config(self):
        unsafe_parent = self.base / "unsafe-codex"
        unsafe_parent.mkdir(mode=0o700)
        unsafe_parent.chmod(0o770)
        config = unsafe_parent / "config.toml"

        with self.assertRaises(self.defaults.ConfigurationError):
            self.defaults.configure(config)

        self.assertFalse(config.exists())

    def test_rejects_parent_with_mutating_acl_without_creating_config(self):
        chmod = shutil.which("chmod")
        if sys.platform != "darwin" or chmod is None:
            self.skipTest("macOSのACL検査ではない")
        for index, permission in enumerate(("add_file", "delete_child")):
            with self.subTest(permission=permission):
                unsafe_parent = self.base / f"acl-codex-{index}"
                unsafe_parent.mkdir(mode=0o700)
                subprocess.run(
                    [chmod, "+a", f"everyone allow {permission}", unsafe_parent],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                config = unsafe_parent / "config.toml"

                with self.assertRaises(self.defaults.ConfigurationError):
                    self.defaults.configure(config)

                self.assertFalse(config.exists())

    def test_metadata_copy_failure_leaves_original_unchanged(self):
        original = b'model = "test"\n'
        self.config.write_bytes(original)
        os.chmod(self.config, 0o600)

        with mock.patch.object(
            self.defaults.safe_config,
            "_copy_extended_metadata",
            side_effect=OSError("metadata copy failed"),
        ) as copy_metadata:
            with self.assertRaises(self.defaults.ConfigurationError):
                self.defaults.configure(self.config)

        copy_metadata.assert_called_once()
        self.assertEqual(self.config.read_bytes(), original)

    def test_source_metadata_change_during_update_fails_without_replacement(self):
        original = b'model = "test"\n'
        self.config.write_bytes(original)
        os.chmod(self.config, 0o600)
        original_inode = self.config.stat().st_ino
        real_copy = self.defaults.safe_config._copy_extended_metadata

        def change_source_then_copy(source, destination):
            os.fchmod(source, 0o640)
            real_copy(source, destination)

        with mock.patch.object(
            self.defaults.safe_config,
            "_copy_extended_metadata",
            side_effect=change_source_then_copy,
        ):
            with self.assertRaises(self.defaults.ConfigurationError):
                self.defaults.configure(self.config)

        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(self.config.stat().st_ino, original_inode)
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o640)

    def test_path_replacement_during_update_preserves_competing_update(self):
        original = b'model = "test"\n'
        competing = b'model = "changed-elsewhere"\n'
        self.config.write_bytes(original)
        os.chmod(self.config, 0o600)
        real_copy = self.defaults.safe_config._copy_extended_metadata

        def replace_path_then_copy(source, destination):
            replacement = self.base / "replacement.toml"
            replacement.write_bytes(competing)
            replacement.chmod(0o600)
            os.replace(replacement, self.config)
            real_copy(source, destination)

        with mock.patch.object(
            self.defaults.safe_config,
            "_copy_extended_metadata",
            side_effect=replace_path_then_copy,
        ):
            with self.assertRaises(self.defaults.ConfigurationError):
                self.defaults.configure(self.config)

        self.assertEqual(self.config.read_bytes(), competing)
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)

    def test_unsafe_temporary_inode_is_rejected_before_creating_config(self):
        real_temporary_file = self.defaults.safe_config._temporary_file
        created_name = None

        def create_group_readable_temporary(parent_descriptor, name):
            nonlocal created_name
            descriptor, created_name = real_temporary_file(parent_descriptor, name)
            os.fchmod(descriptor, 0o640)
            return descriptor, created_name

        with mock.patch.object(
            self.defaults.safe_config,
            "_temporary_file",
            side_effect=create_group_readable_temporary,
        ):
            with self.assertRaises(self.defaults.ConfigurationError):
                self.defaults.configure(self.config)

        self.assertFalse(self.config.exists())
        self.assertIsNotNone(created_name)
        self.assertFalse((self.base / created_name).exists())

    def test_final_rename_is_scoped_to_the_validated_directory(self):
        self.config.write_text('model = "test"\n', encoding="utf-8")
        os.chmod(self.config, 0o600)
        real_rename = os.rename

        with mock.patch.object(self.defaults.safe_config.os, "rename", wraps=real_rename) as rename:
            self.defaults.configure(self.config)

        self.assertEqual(rename.call_count, 1)
        _, kwargs = rename.call_args
        self.assertIsInstance(kwargs.get("src_dir_fd"), int)
        self.assertEqual(kwargs.get("src_dir_fd"), kwargs.get("dst_dir_fd"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
