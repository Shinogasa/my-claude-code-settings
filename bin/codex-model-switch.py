#!/usr/bin/env python3
"""親セッションのモデル切替を開始・公開・照会するCLI。"""
import argparse
import json
import sys
from pathlib import Path

from codex_model_switch import SwitchError, begin, publish, status


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("begin", "publish", "status"):
        command = commands.add_parser(name)
        command.add_argument("--repo", type=Path, default=Path.cwd())
        command.add_argument("--session-id", required=True)
        if name == "begin":
            command.add_argument("--task-id", required=True)
            command.add_argument("--current-phase", required=True)
            command.add_argument("--next-phase", required=True)
            command.add_argument("--model", required=True)
            command.add_argument("--effort", required=True)
            command.add_argument("--handoff", type=Path, required=True)
    return parser


def main():
    arguments = build_parser().parse_args()
    try:
        if arguments.command == "begin":
            result = begin(
                arguments.repo, arguments.session_id, arguments.task_id,
                arguments.current_phase, arguments.next_phase,
                arguments.model, arguments.effort, arguments.handoff,
            )
        elif arguments.command == "publish":
            result = publish(arguments.repo, arguments.session_id)
        else:
            result = status(arguments.repo, arguments.session_id)
    except (SwitchError, OSError, ValueError) as error:
        print(f"MODEL_SWITCH_ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
