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
            index = len(probe.requests)
        model = body.get("model", "gpt-5.6-luna")
        if index == 1:
            call_id, events = function_call_events(model, probe.begin_command)
            probe.begin_call_id = call_id
        elif index == 2:
            call_id, events = function_call_events(model, "touch forbidden-by-pretool.txt")
            probe.forbidden_call_id = call_id
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
        self.begin_command = ""
        self.begin_call_id = None
        self.forbidden_call_id = None
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

    def test_fresh_thread_delivers_prompt_and_tool_hooks(self):
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
        self.provider.begin_command = shlex.join([
            "python3", str(SWITCH), "begin",
            "--repo", str(self.repo),
            "--session-id", session_id,
            "--task-id", "runtime-probe",
            "--current-phase", "design",
            "--next-phase", "implementation",
            "--model", "gpt-5.6-sol",
            "--effort", "high",
            "--handoff", ".superpowers/handoffs/runtime-probe.md",
        ])

        turn_started, initial_messages = server.request(4, "turn/start", {
            "threadId": thread["id"],
            "input": [{"type": "text", "text": "Run the runtime preflight."}],
        })
        turn_id = turn_started["result"]["turn"]["id"]
        _completed, remaining = server.wait_for(
            lambda message: message.get("method") == "turn/completed"
            and message.get("params", {}).get("turn", {}).get("id") == turn_id,
        )
        initial_messages.extend(remaining)
        prompt_runs = self.hook_runs(initial_messages, "userPromptSubmit")
        pretool_runs = [
            run for run in self.hook_runs(initial_messages, "preToolUse")
            if run.get("displayOrder") == 0
        ]
        self.assertEqual(prompt_runs[-1]["status"], "completed")
        self.assertEqual(pretool_runs[0]["status"], "completed")
        self.assertEqual(pretool_runs[1]["status"], "blocked")
        self.assertIn(self.provider.begin_call_id, pretool_runs[0]["id"])
        self.assertIn(self.provider.forbidden_call_id, pretool_runs[1]["id"])
        model_switch_completions = [
            message for message in initial_messages
            if message.get("method") == "hook/completed"
            and message.get("params", {}).get("run", {}).get("displayOrder") in {0, 6}
        ]
        self.assertTrue(all(
            message["params"]["threadId"] == thread["id"]
            and message["params"]["turnId"] == turn_id
            for message in model_switch_completions
        ))
        started_run_ids = {
            message["params"]["run"]["id"]
            for message in initial_messages
            if message.get("method") == "hook/started"
        }
        self.assertTrue({run["id"] for run in pretool_runs} <= started_run_ids)
        self.assertFalse((self.repo / "forbidden-by-pretool.txt").exists())
        preparing = self.switch("status", "--session-id", session_id)
        self.assertEqual(preparing["state"], "PREPARING")
        self.assertEqual(preparing["session_id"], session_id)

        self.write_handoff()
        pending = self.switch("publish", "--session-id", session_id)
        self.assertEqual(pending["state"], "SWITCH_PENDING")
        requests_before_block = len(self.provider.requests)

        normal_started, normal_messages = server.request(5, "turn/start", {
            "threadId": thread["id"],
            "input": [{"type": "text", "text": "This prompt must be blocked."}],
        })
        normal_turn_id = normal_started["result"]["turn"]["id"]
        _normal_completed, remaining = server.wait_for(
            lambda message: message.get("method") == "turn/completed"
            and message.get("params", {}).get("turn", {}).get("id") == normal_turn_id,
        )
        normal_messages.extend(remaining)
        normal_prompt_runs = self.hook_runs(normal_messages, "userPromptSubmit")
        self.assertEqual(normal_prompt_runs[-1]["status"], "blocked")
        self.assertTrue(any(
            message.get("method") == "hook/completed"
            and message.get("params", {}).get("turnId") == normal_turn_id
            and message.get("params", {}).get("run", {}).get("id") == normal_prompt_runs[-1]["id"]
            for message in normal_messages
        ))
        self.assertEqual(len(self.provider.requests), requests_before_block)
        self.assertEqual(self.switch("status", "--session-id", session_id)["state"], "SWITCH_PENDING")

        resume_text = (
            f"MODEL_SWITCH_RESUME {pending['transition_id']} gpt-5.6-sol high"
        )
        resume_started, resume_messages = server.request(6, "turn/start", {
            "threadId": thread["id"],
            "input": [{"type": "text", "text": resume_text}],
            "model": "gpt-5.6-sol",
            "effort": "high",
        })
        resume_turn_id = resume_started["result"]["turn"]["id"]
        _resume_completed, remaining = server.wait_for(
            lambda message: message.get("method") == "turn/completed"
            and message.get("params", {}).get("turn", {}).get("id") == resume_turn_id,
        )
        resume_messages.extend(remaining)
        resume_runs = self.hook_runs(resume_messages, "userPromptSubmit")
        self.assertEqual(resume_runs[-1]["status"], "completed")
        self.assertTrue(any(
            message.get("method") == "hook/completed"
            and message.get("params", {}).get("turnId") == resume_turn_id
            and message.get("params", {}).get("run", {}).get("id") == resume_runs[-1]["id"]
            for message in resume_messages
        ))
        active = self.switch("status", "--session-id", session_id)
        self.assertEqual(active["state"], "ACTIVE")
        self.assertEqual(active["session_id"], session_id)
        self.assertEqual(active["target_model"], "gpt-5.6-sol")
        self.assertEqual(active["target_effort"], "high")
        self.assertEqual(active["model_evidence"], "hook-observed")
        self.assertEqual(active["effort_evidence"], "user-attested")
        self.assertEqual(active["verification_tier"], "user-attested")
        self.assertEqual(self.provider.requests[-1]["model"], "gpt-5.6-sol")


if __name__ == "__main__":
    unittest.main(verbosity=2)
