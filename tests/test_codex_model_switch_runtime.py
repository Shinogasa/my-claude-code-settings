#!/usr/bin/env python3
"""Codex App Serverの実hook配送とmodel switch状態遷移を検証する。"""
import json
import os
import queue
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


from tests.model_switch_fixtures import seed_legacy_preparing


ROOT = Path(__file__).resolve().parents[1]
SWITCH = ROOT / "bin" / "codex-model-switch.py"
VALIDATOR = ROOT / "bin" / "validate-codex-handoff.py"
CODEX = shutil.which("codex")


def response(model, response_id, status, output):
    return {
        "id": response_id,
        "object": "response",
        "created_at": int(time.time()),
        "status": status,
        "error": None,
        "incomplete_details": None,
        "model": model,
        "output": output,
        "parallel_tool_calls": True,
        "reasoning": {"effort": "medium", "summary": None},
        "store": False,
        "text": {"format": {"type": "text"}},
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 1,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 1,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 2,
        },
    }


def function_call_events(model, command):
    response_id = "resp_" + uuid.uuid4().hex
    item_id = "fc_" + uuid.uuid4().hex
    call_id = "call_" + uuid.uuid4().hex
    arguments = json.dumps({"cmd": command}, separators=(",", ":"))
    item = {
        "id": item_id,
        "type": "function_call",
        "status": "completed",
        "arguments": arguments,
        "call_id": call_id,
        "name": "exec_command",
    }
    return call_id, [
        {"type": "response.created", "response": response(model, response_id, "in_progress", [])},
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {**item, "status": "in_progress", "arguments": ""},
        },
        {
            "type": "response.function_call_arguments.delta",
            "item_id": item_id,
            "output_index": 0,
            "delta": arguments,
        },
        {
            "type": "response.function_call_arguments.done",
            "item_id": item_id,
            "output_index": 0,
            "arguments": arguments,
        },
        {"type": "response.output_item.done", "output_index": 0, "item": item},
        {
            "type": "response.completed",
            "response": response(model, response_id, "completed", [item]),
        },
    ]


def text_events(model, text="DONE"):
    response_id = "resp_" + uuid.uuid4().hex
    item_id = "msg_" + uuid.uuid4().hex
    content = {"type": "output_text", "text": text, "annotations": [], "logprobs": []}
    item = {
        "id": item_id,
        "type": "message",
        "status": "completed",
        "role": "assistant",
        "content": [content],
    }
    return [
        {"type": "response.created", "response": response(model, response_id, "in_progress", [])},
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {**item, "status": "in_progress", "content": []},
        },
        {
            "type": "response.content_part.added",
            "item_id": item_id,
            "output_index": 0,
            "content_index": 0,
            "part": {**content, "text": ""},
        },
        {
            "type": "response.output_text.delta",
            "item_id": item_id,
            "output_index": 0,
            "content_index": 0,
            "delta": text,
            "logprobs": [],
        },
        {
            "type": "response.output_text.done",
            "item_id": item_id,
            "output_index": 0,
            "content_index": 0,
            "text": text,
            "logprobs": [],
        },
        {
            "type": "response.content_part.done",
            "item_id": item_id,
            "output_index": 0,
            "content_index": 0,
            "part": content,
        },
        {"type": "response.output_item.done", "output_index": 0, "item": item},
        {
            "type": "response.completed",
            "response": response(model, response_id, "completed", [item]),
        },
    ]


class ProbeHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(size))
        probe = self.server.probe
        with probe.lock:
            probe.requests.append(body)
        model = body.get("model", "gpt-5.6-luna")
        if probe.commands:
            command = probe.commands.pop(0)
            call_id, events = function_call_events(model, command)
            probe.call_ids.append(call_id)
        else:
            events = text_events(model)
        payload = "".join(
            f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
            for event in events
        ) + "data: [DONE]\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(payload.encode("utf-8"))
        self.wfile.flush()

    def log_message(self, _format, *_arguments):
        return


class MockProvider:
    def __init__(self):
        self.lock = threading.Lock()
        self.requests = []
        self.commands = []
        self.call_ids = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ProbeHandler)
        self.server.probe = self
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def port(self):
        return self.server.server_port

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class AppServer:
    def __init__(self, cwd, environment, sqlite_home):
        self.stderr = []
        self.process = subprocess.Popen(
            [
                CODEX, "app-server", "--strict-config", "--stdio",
                "-c", f'sqlite_home="{sqlite_home}"',
            ],
            cwd=cwd,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.messages = queue.Queue()
        self.stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self.stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self.stdout_thread.start()
        self.stderr_thread.start()

    def _read_stdout(self):
        for line in self.process.stdout:
            self.messages.put(json.loads(line))

    def _read_stderr(self):
        for line in self.process.stderr:
            self.stderr.append(line)

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def wait_for(self, predicate, timeout=30):
        seen = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise AssertionError(
                    "App Server exited: " + "".join(self.stderr)
                )
            try:
                message = self.messages.get(timeout=0.5)
            except queue.Empty:
                continue
            seen.append(message)
            if predicate(message):
                return message, seen
        raise TimeoutError(json.dumps({"messages": seen, "stderr": self.stderr}, ensure_ascii=False))

    def request(self, request_id, method, params):
        self.send({"id": request_id, "method": method, "params": params})
        return self.wait_for(lambda message: message.get("id") == request_id)

    def initialize(self):
        response_message, _seen = self.request(1, "initialize", {
            "clientInfo": {"name": "model-switch-runtime-test", "version": "1.0.0"},
            "capabilities": {"experimentalApi": True},
        })
        if "error" in response_message:
            raise AssertionError(response_message)
        self.send({"method": "initialized", "params": {}})

    def close(self):
        try:
            if self.process.poll() is None:
                try:
                    self.process.stdin.close()
                    self.process.wait(timeout=10)
                except (BrokenPipeError, subprocess.TimeoutExpired):
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=5)
        finally:
            try:
                self.process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            self.stdout_thread.join(timeout=5)
            self.stderr_thread.join(timeout=5)
            self.process.stdout.close()
            self.process.stderr.close()


@unittest.skipUnless(CODEX, "codex CLI is unavailable")
class CodexModelSwitchRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        temporary = Path(self.temporary.name).resolve()
        self.home = temporary / "home"
        self.codex_home = self.home / ".codex"
        self.repo = temporary / "repo"
        self.sqlite_discovery = temporary / "sqlite-discovery"
        self.sqlite_runtime = temporary / "sqlite-runtime"
        for directory in (
            self.codex_home, self.repo, self.sqlite_discovery, self.sqlite_runtime,
        ):
            directory.mkdir(parents=True)
        (self.codex_home / "hooks.json").symlink_to(ROOT / "codex" / "hooks.json")
        (self.codex_home / "hooks").symlink_to(ROOT / "hooks", target_is_directory=True)

        self.environment = {
            key: value for key, value in os.environ.items()
            if not any(secret in key.upper() for secret in (
                "KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL",
            ))
        }
        self.environment.update({
            "HOME": str(self.home),
            "CODEX_HOME": str(self.codex_home),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        })
        self.run_command(["git", "init", "-b", "main"])
        self.run_command(["git", "config", "user.email", "probe@example.invalid"])
        self.run_command(["git", "config", "user.name", "Runtime Probe"])
        (self.repo / "tracked.txt").write_text("initial\n", encoding="utf-8")
        self.run_command(["git", "add", "tracked.txt"])
        self.run_command(["git", "commit", "-m", "initial"])

        self.provider = MockProvider()
        self.provider.start()
        self.addCleanup(self.provider.stop)

    def run_command(self, arguments, check=True):
        return subprocess.run(
            arguments,
            cwd=self.repo,
            env=self.environment,
            text=True,
            capture_output=True,
            check=check,
        )

    def write_config(self, trust=None):
        lines = [
            'model_provider = "probe"',
            'model = "gpt-5.6-luna"',
            'model_reasoning_effort = "medium"',
            'approval_policy = "never"',
            'sandbox_mode = "workspace-write"',
            '',
            '[features]',
            'hooks = true',
            'plugins = false',
            'apps = false',
            'shell_tool = true',
            '',
            '[analytics]',
            'enabled = false',
            '',
            '[model_providers.probe]',
            'name = "Probe"',
            f'base_url = "http://127.0.0.1:{self.provider.port}/v1"',
            'wire_api = "responses"',
            'requires_openai_auth = false',
            'request_max_retries = 0',
            'stream_max_retries = 0',
            'supports_websockets = false',
            '',
        ]
        for hook in trust or []:
            lines.extend([
                f'[hooks.state.{json.dumps(hook["key"])}]',
                f'trusted_hash = {json.dumps(hook["currentHash"])}',
                '',
            ])
        (self.codex_home / "config.toml").write_text("\n".join(lines), encoding="utf-8")

    def discover_and_trust_hooks(self):
        self.write_config()
        server = AppServer(self.repo, self.environment, self.sqlite_discovery)
        try:
            server.initialize()
            response_message, _seen = server.request(2, "hooks/list", {"cwds": [str(self.repo)]})
            hooks = response_message["result"]["data"][0]["hooks"]
        finally:
            server.close()
        self.write_config(hooks)

    def switch(self, command, *arguments):
        result = self.run_command([
            sys.executable, str(SWITCH), command, "--repo", str(self.repo), *arguments,
        ], check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def write_handoff(self):
        state_result = self.run_command([
            sys.executable, str(VALIDATOR), "state", "--repo", str(self.repo),
        ])
        state = json.loads(state_result.stdout)
        handoff = self.repo / ".superpowers" / "handoffs" / "runtime-probe.md"
        handoff.parent.mkdir(parents=True, exist_ok=True)
        handoff.write_text(f"""---
handoff_schema: 1
task_id: runtime-probe
branch: {state['branch']}
head: {state['head']}
worktree_fingerprint: {state['worktree_fingerprint']}
target_model: gpt-5.6-sol
target_reasoning_effort: high
requirements_path: none
requirements_sha256: none
review_package_path: none
review_package_sha256: none
---
# Runtime probe

## 目的と対象外
実hook配送を検証する。

## Git状態
一時repoの状態を使う。

## 確定済み設計判断と根拠
実eventとmanifestを照合する。

## 対象ファイルと作業所有範囲
一時repoだけを扱う。

## 受入条件と検証コマンド
runtime testを成功させる。

## 制約
credentialを使わない。

## 未解決事項
なし。

## 実行モデル
gpt-5.6-sol / highを使う。

## 返却レポート契約
eventと状態を返す。
""", encoding="utf-8")

    @staticmethod
    def hook_runs(messages, event_name):
        return [
            message["params"]["run"]
            for message in messages
            if message.get("method") == "hook/completed"
            and message.get("params", {}).get("run", {}).get("eventName") == event_name
        ]

    def start_runtime(self):
        self.discover_and_trust_hooks()
        server = AppServer(self.repo, self.environment, self.sqlite_runtime)
        self.addCleanup(server.close)
        server.initialize()

        listed, _seen = server.request(2, "hooks/list", {"cwds": [str(self.repo)]})
        model_switch_hooks = [
            hook for hook in listed["result"]["data"][0]["hooks"]
            if "codex-model-switch-hook.py" in (hook.get("command") or "")
        ]
        self.assertEqual({hook["eventName"] for hook in model_switch_hooks}, {
            "preToolUse", "sessionStart", "userPromptSubmit",
        })
        self.assertTrue(all(hook["enabled"] for hook in model_switch_hooks))
        self.assertTrue(all(hook["trustStatus"] == "trusted" for hook in model_switch_hooks))
        self.assertTrue(all(
            hook["sourcePath"] == str(self.codex_home / "hooks.json")
            for hook in model_switch_hooks
        ))
        self.assertTrue(all(
            hook["currentHash"].startswith("sha256:") for hook in model_switch_hooks
        ))

        started, _seen = server.request(3, "thread/start", {
            "cwd": str(self.repo),
            "ephemeral": True,
            "approvalPolicy": "never",
            "sandbox": "workspace-write",
            "sessionStartSource": "startup",
            "model": "gpt-5.6-luna",
        })
        thread = started["result"]["thread"]
        self.assertEqual(thread["id"], thread["sessionId"])
        session_id = thread["sessionId"]
        return server, thread

    def run_turn(self, server, thread, request_id, prompt, **options):
        started, messages = server.request(request_id, "turn/start", {
            "threadId": thread["id"],
            "input": [{"type": "text", "text": prompt}], **options,
        })
        turn_id = started["result"]["turn"]["id"]
        completed, remaining = server.wait_for(
            lambda message: message.get("method") == "turn/completed"
            and message.get("params", {}).get("turn", {}).get("id") == turn_id,
        )
        messages.extend(remaining)
        self.assertEqual(completed["params"]["turn"]["status"], "completed")
        completions = [m["params"] for m in messages if m.get("method") == "hook/completed"]
        starts = {m["params"]["run"]["id"] for m in messages if m.get("method") == "hook/started"}
        self.assertTrue(completions)
        for event in completions:
            self.assertEqual(event["threadId"], thread["id"])
            self.assertEqual(event["turnId"], turn_id)
            self.assertIn(event["run"]["id"], starts)
        return turn_id, messages

    def assert_tool_statuses(self, messages, expected):
        runs = [run for run in self.hook_runs(messages, "preToolUse") if run.get("displayOrder") == 0]
        self.assertEqual([run["status"] for run in runs], expected)
        for call_id, run in zip(self.provider.call_ids, runs):
            self.assertIn(call_id, run["id"])

    def test_new_begin_is_disabled_after_real_hook_delivery(self):
        server, thread = self.start_runtime()
        session_id = thread["sessionId"]
        command = shlex.join([
            "python3", str(SWITCH), "begin", "--repo", str(self.repo),
            "--session-id", session_id, "--task-id", "runtime-probe",
            "--current-phase", "design", "--next-phase", "implementation",
            "--model", "gpt-5.6-sol", "--effort", "high",
            "--handoff", ".superpowers/handoffs/runtime-probe.md",
        ])
        self.provider.commands = [command, "touch allowed-after-refusal.txt"]
        turn_id, messages = self.run_turn(server, thread, 4, "新規切替の拒否を検証する")
        self.assertEqual(self.hook_runs(messages, "userPromptSubmit")[-1]["status"], "completed")
        self.assert_tool_statuses(messages, ["completed", "completed"])
        tool_results = [m["params"]["item"] for m in messages
                        if m.get("method") == "item/completed" and m["params"]["item"].get("type") == "commandExecution"]
        self.assertEqual(tool_results[0]["exitCode"], 2)
        self.assertIn("begin is disabled", tool_results[0]["aggregatedOutput"])
        self.assertTrue((self.repo / "allowed-after-refusal.txt").exists())
        self.assertIsNone(self.switch("status", "--session-id", session_id))
        diagnosed = self.switch("diagnose", "--session-id", session_id)
        self.assertIsNone(diagnosed["bound_repo"])
        self.assertFalse(diagnosed["same_thread_begin_enabled"])
        self.assertFalse(diagnosed["preflight"]["grant_pending"])
        self.assertEqual(diagnosed["preflight"]["turn_id"], turn_id)
        self.assertTrue(diagnosed["preflight"]["current_hook"])

    def seed_pending(self, session_id):
        preparing = seed_legacy_preparing(
            self.repo, self.environment, session_id, task_id="runtime-probe",
            model="gpt-5.6-sol", effort="high",
        )
        self.assertEqual(self.switch("status", "--session-id", session_id), preparing)
        self.write_handoff()
        pending = self.switch("publish", "--session-id", session_id)
        self.assertEqual(pending["state"], "SWITCH_PENDING")
        return pending

    def test_legacy_pending_allows_diagnose_cancel_and_then_normal_tools(self):
        server, thread = self.start_runtime()
        session_id = thread["sessionId"]
        pending = self.seed_pending(session_id)
        flags = ["--repo", str(self.repo), "--session-id", session_id]
        self.provider.commands = [
            "touch forbidden-by-pretool.txt",
            shlex.join(["python3", str(SWITCH), "diagnose", *flags]),
            shlex.join(["python3", str(SWITCH), "cancel", *flags, "--transition-id", pending["transition_id"]]),
            "touch recovered.txt",
        ]
        _turn_id, messages = self.run_turn(server, thread, 4, "切替待ちを診断して取り消して")
        self.assertEqual(self.hook_runs(messages, "userPromptSubmit")[-1]["status"], "completed")
        self.assert_tool_statuses(messages, ["blocked", "completed", "completed", "completed"])
        self.assertFalse((self.repo / "forbidden-by-pretool.txt").exists())
        self.assertTrue((self.repo / "recovered.txt").exists())
        outputs = [m["params"]["item"].get("aggregatedOutput", "") for m in messages if m.get("method") == "item/completed"]
        self.assertTrue(any('"state": "SWITCH_PENDING"' in output for output in outputs))
        diagnosed = self.switch("diagnose", "--session-id", session_id)
        self.assertIsNone(diagnosed["bound_repo"])
        self.assertEqual(diagnosed["manifest"]["state"], "CANCELLED")

    def test_legacy_resume_model_observed_effort_user_attested(self):
        server, thread = self.start_runtime()
        session_id = thread["sessionId"]
        pending = self.seed_pending(session_id)
        _turn_id, messages = self.run_turn(
            server, thread, 4, f"MODEL_SWITCH_RESUME {pending['transition_id']} gpt-5.6-sol high",
            model="gpt-5.6-sol", effort="high",
        )
        self.assertEqual(self.hook_runs(messages, "userPromptSubmit")[-1]["status"], "completed")
        active = self.switch("status", "--session-id", session_id)
        self.assertEqual(active["state"], "ACTIVE")
        self.assertEqual(active["session_id"], session_id)
        self.assertEqual(active["target_model"], "gpt-5.6-sol")
        self.assertEqual(active["target_effort"], "high")
        self.assertEqual(active["model_evidence"], "hook-observed")
        self.assertEqual(active["effort_evidence"], "user-attested")
        self.assertEqual(active["verification_tier"], "user-attested")
        self.assertEqual(self.provider.requests[-1]["model"], "gpt-5.6-sol")

    @unittest.skipUnless(Path("/usr/bin/python3").exists(), "system Python unavailable")
    def test_system_python_deep_receipt_blocks_before_provider(self):
        # hook定義を隔離HOME内でsystem Pythonへ変え、その定義のhashをtrustする。
        path = self.codex_home / "hooks.json"
        content = path.read_text().replace("python3 ", "/usr/bin/python3 ")
        path.unlink()
        path.write_text(content)
        server, thread = self.start_runtime()
        session_id = thread["sessionId"]
        self.seed_pending(session_id)
        self.run_turn(server, thread, 4, "配送記録を作る")
        receipt = next((self.codex_home / "model-switch-preflight").glob("*.json"))
        receipt.write_text("[" * 1500 + "0" + "]" * 1500)
        requests_before = len(self.provider.requests)
        _turn_id, messages = self.run_turn(server, thread, 5, "不正JSONはproviderへ配送しない")
        self.assertEqual(self.hook_runs(messages, "userPromptSubmit")[-1]["status"], "blocked")
        self.assertEqual(len(self.provider.requests), requests_before)
        self.assertEqual(self.switch("status", "--session-id", session_id)["state"], "SWITCH_PENDING")


if __name__ == "__main__":
    unittest.main(verbosity=2)
