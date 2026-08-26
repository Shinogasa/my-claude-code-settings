#!/bin/bash

set -euo pipefail

python3 -c '
import json
import sys

try:
    payload = json.load(sys.stdin)
except json.JSONDecodeError:
    print("inject-superpowers: invalid JSON", file=sys.stderr)
    sys.exit(1)

if not isinstance(payload, dict):
    print("inject-superpowers: expected JSON object", file=sys.stderr)
    sys.exit(1)

if payload.get("hook_event_name") != "SessionStart":
    print("inject-superpowers: expected SessionStart payload", file=sys.stderr)
    sys.exit(1)

if "source" not in payload:
    print("inject-superpowers: missing SessionStart source", file=sys.stderr)
    sys.exit(1)

source = payload["source"]
if not isinstance(source, str):
    print("inject-superpowers: SessionStart source must be a string", file=sys.stderr)
    sys.exit(1)

if source not in {"startup", "resume", "clear", "compact"}:
    print("inject-superpowers: unsupported SessionStart source", file=sys.stderr)
    sys.exit(1)
'

printf '%s\n' \
  'Before responding, read and follow superpowers:using-superpowers from the enabled Codex plugin.'
