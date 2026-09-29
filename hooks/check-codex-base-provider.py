#!/usr/bin/env python3
"""SessionStart フック: base の config.toml が自前 provider を選んでいるか検査する。

会社PCでは ~/.codex/config.toml の [model_providers.<name>] に LLM gateway を定義し、
トップレベルの model_provider で選ぶ。外部ツールの書き換えなどで model_provider だけが
消えると、codex は既定の openai に倒れ、auth.json の個人 ChatGPT アカウントで黙って動く
(cxp と auth.json を共有しているため)。この状態を検知して UI に警告する。

検査の限界:
  provider は起動時に確定するため、このフックが警告した時点で当該セッションは既に
  その provider で動いている。止めるのではなく、次の起動前に直すための通知である。
  また Codex の hook は /hooks で承認されるまで黙ってスキップされる。

出力:
  正常時は何も出さない (モデルのコンテキストを消費しない)。
  異常時は systemMessage だけを返す。additionalContext は使わない。
  メッセージには provider 名だけを載せ、URL やヘッダ値は載せない。
"""

import json
import os
import sys
import tomllib
from pathlib import Path


def warn(message: str) -> None:
    print(json.dumps({"systemMessage": message}, ensure_ascii=False))
    sys.exit(0)


def find_problem(config_path: Path) -> str | None:
    if not config_path.exists():
        return None
    try:
        with config_path.open("rb") as f:
            config = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return f"{config_path} を読めないため、Codex の provider を検査できません。"

    providers = config.get("model_providers", {})
    if not isinstance(providers, dict):
        return f"{config_path} の model_providers がテーブルではないため、provider を検査できません。"
    if not providers:
        # 自前 provider を定義しない構成 (既定の openai を使う) は対象外
        return None

    defined = ", ".join(sorted(providers))
    selected = config.get("model_provider")
    if selected is None:
        return (
            f"{config_path} に model_provider がありません。"
            f"定義済みの provider ({defined}) は選ばれず、既定の openai "
            "(auth.json のアカウント) で動いています。"
            "model_provider を書き戻してから Codex を再起動してください。"
        )
    if selected not in providers:
        return (
            f"{config_path} の model_provider が {selected} になっています。"
            f"定義済みの provider ({defined}) が選ばれていません。"
            "意図した設定か確認してください。"
        )
    return None


def main() -> None:
    # payload は使わないが読み捨てる
    sys.stdin.read()
    codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    problem = find_problem(codex_home / "config.toml")
    if problem:
        warn("警告: " + problem)


if __name__ == "__main__":
    main()
