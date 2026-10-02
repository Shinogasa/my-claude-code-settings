#!/usr/bin/env python3
"""hooks/skill-read-check.py と manifests/skill-required-reads.json を検証する。

実行: python3 -m unittest tests.test_skill_read_check
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "skill-read-check.py"
MANIFEST = REPO_ROOT / "manifests" / "skill-required-reads.json"
COMPACT = {"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted"}


def prompt(text="go"):
    return {"type": "user", "message": {"role": "user", "content": text}}


def call(name, **tool_input):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": tool_input}]}}


def skill_body(base_dir, as_list=False):
    """スラッシュコマンドでスキルを呼んだときに残る、isMetaのuserの行。"""
    text = f"Base directory for this skill: {base_dir}\n\n# demo"
    content = [{"type": "text", "text": text}] if as_list else text
    return {"type": "user", "isMeta": True, "message": {"role": "user", "content": content}}


class SkillReadCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "skills" / "demo"
        for relative in ("SKILL.md", "references/a.md", "references/b.md",
                         "references/domains/x.md", "references/domains/y.md"):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")
            copy = self.base / "copy" / "skills" / "demo" / relative
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_text("x", encoding="utf-8")
        self.copy = self.base / "copy" / "skills" / "demo"
        self.alias = self.base / "alias-demo"
        self.alias.symlink_to(self.root)
        self.manifest = self.base / "manifest.json"
        self.manifest.write_text(json.dumps({"schemaVersion": 1, "skills": {"demo": {
            "root": str(self.alias),
            "alternateRoots": [str(self.copy)],
            "allOf": ["references/a.md", "references/b.md"],
            "anyOf": [["references/domains/x.md", "references/domains/y.md"]],
        }}}), encoding="utf-8")
        self.transcript_path = self.base / "t.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def transcript(self, *entries):
        with self.transcript_path.open("a", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def reads(self, *relatives, root=None):
        return [call("Read", file_path=str((root or self.root) / relative)) for relative in relatives]

    def run_hook(self, event="stop", active=False, agent_type="general-purpose"):
        key = "agent_transcript_path" if event == "subagent-stop" else "transcript_path"
        payload = {"session_id": "s1", key: str(self.transcript_path), "stop_hook_active": active}
        if event == "subagent-stop" and agent_type is not None:
            payload["agent_type"] = agent_type
        env = {**os.environ, "SKILL_READ_CHECK_MANIFEST": str(self.manifest)}
        env.pop("FORCE_COLOR", None)
        result = subprocess.run([sys.executable, str(HOOK), event], input=json.dumps(payload),
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def test_not_invoked_is_silent(self):
        self.transcript(prompt(), *self.reads("references/a.md"))
        self.assertEqual(self.run_hook(), {})

    def test_all_required_reads_present_is_silent(self):
        self.transcript(prompt(), call("Skill", skill="demo"),
                        *self.reads("references/a.md", "references/b.md", "references/domains/y.md"))
        self.assertEqual(self.run_hook(), {})

    def test_missing_read_blocks_with_full_path(self):
        self.transcript(prompt(), call("Skill", skill="demo"), *self.reads("references/a.md", "references/domains/x.md"))
        output = self.run_hook()
        self.assertEqual(output["decision"], "block")
        self.assertIn(str(self.root / "references" / "b.md"), output["reason"])
        self.assertNotIn("a.md", output["reason"].replace("b.md", ""))

    def test_missing_any_of_group_is_reported_once(self):
        self.transcript(prompt(), call("Skill", skill="demo"), *self.reads("references/a.md", "references/b.md"))
        reason = self.run_hook()["reason"]
        self.assertIn("x.md", reason)
        self.assertIn("y.md", reason)
        self.assertIn("のうち1つ", reason)

    def test_plugin_style_skill_name_counts(self):
        self.transcript(prompt(), call("Skill", skill="plugin:demo"))
        self.assertEqual(self.run_hook()["decision"], "block")

    def test_reading_skill_md_through_symlink_counts_as_invocation(self):
        self.transcript(prompt(), *self.reads("SKILL.md", root=self.alias))
        self.assertEqual(self.run_hook()["decision"], "block")

    def test_reads_through_symlink_satisfy_requirements(self):
        self.transcript(prompt(), call("Skill", skill="demo"),
                        *self.reads("references/a.md", "references/b.md", "references/domains/x.md", root=self.alias))
        self.assertEqual(self.run_hook(), {})

    def test_reads_before_compact_do_not_count(self):
        self.transcript(*self.reads("references/a.md", "references/b.md", "references/domains/x.md"),
                        COMPACT, prompt(), call("Skill", skill="demo"))
        self.assertEqual(self.run_hook()["decision"], "block")

    def test_reads_from_earlier_turn_after_compact_count(self):
        self.transcript(prompt("1"), *self.reads("references/a.md", "references/b.md", "references/domains/x.md"),
                        prompt("2"), call("Skill", skill="demo"))
        self.assertEqual(self.run_hook(), {})

    def test_invocation_in_earlier_turn_is_not_checked_on_main_stop(self):
        self.transcript(prompt("1"), call("Skill", skill="demo"), prompt("2"))
        self.assertEqual(self.run_hook(), {})

    def test_second_stop_passes_with_message(self):
        self.transcript(prompt(), call("Skill", skill="demo"))
        output = self.run_hook(active=True)
        self.assertNotIn("decision", output)
        self.assertIn("読まれないまま", output["systemMessage"])

    def test_subagent_stop_checks_whole_subagent_transcript(self):
        self.transcript(prompt("task"), call("Skill", skill="demo"), prompt("follow-up"))
        self.assertEqual(self.run_hook("subagent-stop")["decision"], "block")

    def test_subagent_stop_without_agent_type_does_nothing(self):
        self.transcript(prompt("task"), call("Skill", skill="demo"))
        self.assertEqual(self.run_hook("subagent-stop", agent_type=None), {})
        self.assertEqual(self.run_hook("subagent-stop", agent_type=""), {})

    def test_bash_command_with_relative_path_counts_as_read(self):
        self.transcript(prompt(), call("Skill", skill="demo"),
                        call("Bash", command="cat ~/.claude/skills/demo/references/a.md"),
                        call("Bash", command="sed -n '1,400p' references/b.md && cat references/domains/y.md"))
        self.assertEqual(self.run_hook(), {})

    def test_bash_command_with_real_path_counts_as_read(self):
        paths = " ".join(str(self.root / relative) for relative in
                         ("references/a.md", "references/b.md", "references/domains/x.md"))
        self.transcript(prompt(), call("Skill", skill="demo"), call("Bash", command=f"cat {paths}"))
        self.assertEqual(self.run_hook(), {})

    def test_bash_command_without_required_path_does_not_count(self):
        self.transcript(prompt(), call("Skill", skill="demo"), call("Bash", command="ls references"))
        self.assertEqual(self.run_hook()["decision"], "block")

    def test_reading_skill_md_in_alternate_root_counts_as_invocation(self):
        self.transcript(prompt(), *self.reads("SKILL.md", root=self.copy))
        self.assertEqual(self.run_hook()["decision"], "block")

    def test_reads_in_alternate_root_satisfy_requirements(self):
        self.transcript(prompt(), call("Skill", skill="demo"),
                        *self.reads("references/a.md", "references/domains/y.md", root=self.copy),
                        *self.reads("references/b.md"))
        self.assertEqual(self.run_hook(), {})

    def test_slash_command_base_directory_counts_as_invocation(self):
        for base_dir, as_list in ((self.alias, False), (self.copy, True)):
            with self.subTest(base_dir=base_dir.name, as_list=as_list):
                self.transcript_path.unlink(missing_ok=True)
                self.transcript(prompt("/demo"), skill_body(base_dir, as_list))
                self.assertEqual(self.run_hook()["decision"], "block")

    def test_base_directory_of_other_skill_is_ignored(self):
        self.transcript(prompt("/other"), skill_body(self.base / "skills" / "other"))
        self.assertEqual(self.run_hook(), {})

    def test_task_notification_does_not_end_the_turn_window(self):
        notification = {"type": "user", "message": {"role": "user",
                                                    "content": "<task-notification>\n<task-id>x</task-id>"}}
        self.transcript(prompt(), call("Skill", skill="demo"), notification)
        self.assertEqual(self.run_hook()["decision"], "block")

    def test_stale_manifest_entry_is_reported(self):
        # どの置き場にも無いときだけ、対応表が古いとみなす
        (self.root / "references" / "b.md").unlink()
        (self.copy / "references" / "b.md").unlink()
        self.transcript(prompt(), call("Skill", skill="demo"),
                        *self.reads("references/a.md", "references/domains/x.md"))
        output = self.run_hook()
        self.assertNotIn("decision", output)
        self.assertIn("対応表が古い", output["systemMessage"])

    def test_unreadable_transcript_is_reported(self):
        self.transcript_path.write_text("not json\n", encoding="utf-8")
        self.assertIn("確認していない", self.run_hook()["systemMessage"])

    def test_unreadable_manifest_is_reported(self):
        self.manifest.write_text("{", encoding="utf-8")
        self.transcript(prompt())
        self.assertIn("対応表を読めなかった", self.run_hook()["systemMessage"])

    def test_second_stop_names_every_any_of_candidate(self):
        self.transcript(prompt(), call("Skill", skill="demo"),
                        *self.reads("references/a.md", "references/b.md"))
        output = self.run_hook(active=True)
        system_message = output["systemMessage"]
        self.assertIn("x.md", system_message)
        self.assertIn("y.md", system_message)
        self.assertIn("のうち1つ", system_message)


class RepositoryManifestTests(unittest.TestCase):
    def test_yomiyasu_entry_points_to_existing_files_in_submodule(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schemaVersion"], 1)
        entry = manifest["skills"]["yomiyasu"]
        self.assertEqual(entry["root"], "~/.claude/skills/yomiyasu")
        self.assertEqual(entry["alternateRoots"], ["~/.claude/skills/yomiyasu/skills/yomiyasu"])
        submodule = REPO_ROOT / "skills" / "yomiyasu"
        roots = [submodule, submodule / "skills" / "yomiyasu"]
        for root in roots:
            for relative in ["SKILL.md"] + entry["allOf"] + [item for group in entry["anyOf"] for item in group]:
                with self.subTest(root=str(root), relative=relative):
                    self.assertTrue((root / relative).is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
