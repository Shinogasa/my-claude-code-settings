#!/usr/bin/env python3
"""専用学習記録storeを安全に操作するCLI。"""

import argparse
import json
import os
from pathlib import Path
import sys

from learning_store.store import StoreError, bind_store, init_store, status


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="専用学習記録storeを操作します")
    subcommands = result.add_subparsers(dest="command", required=True)
    init = subcommands.add_parser("init")
    init.add_argument("--repo", required=True)
    bind = subcommands.add_parser("bind")
    bind.add_argument("--repo", required=True)
    bind.add_argument("--replace-binding", action="store_true")
    subcommands.add_parser("status")
    return result


def main() -> int:
    arguments = parser().parse_args()
    try:
        if arguments.command == "init":
            response = init_store(Path(arguments.repo), os.environ)
        elif arguments.command == "bind":
            response = bind_store(Path(arguments.repo), arguments.replace_binding, os.environ)
        else:
            response = status(os.environ)
    except StoreError as error:
        json.dump(
            {"ok": False, "error": {"code": error.code, "message": error.message}},
            sys.stderr,
            ensure_ascii=False,
            sort_keys=True,
        )
        sys.stderr.write("\n")
        return 2
    json.dump(response, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
