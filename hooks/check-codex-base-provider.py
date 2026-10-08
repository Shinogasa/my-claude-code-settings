#!/usr/bin/env python3
"""SessionStart フック: 会社用の CODEX_HOME が個人アカウントへ倒れうる状態を検査する。

会社PCでは ~/.codex/config.toml の [model_providers.<name>] に LLM gateway を定義し、
トップレベルの model_provider で選ぶ。外部ツールの書き換えなどで model_provider だけが
消えると、codex は既定の openai に倒れ、同じ CODEX_HOME の auth.json で認証する。
ADR 0026 で個人用の CODEX_HOME を分けたので、会社用に auth.json が無ければ 401 で止まる。
事故になるのは「model_provider の欠落」と「会社用に auth.json がある」が重なったときなので、
両方を検査して UI に警告する。

自前 provider を定義している CODEX_HOME を会社用とみなす。ただし config.toml ごと書き換えられて
provider の定義も消えることがあるので、~/.codex-personal がある（分けて運用している）マシンでは、
~/.codex を provider の有無と関係なく会社用とみなす。個人用は provider を定義しないので、
auth.json があっても警告しない。auth.json の代わりに OS の keyring へ保存する設定
(cli_auth_credentials_store) では、ファイルが無いので検知できない。

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


def is_separated_company_home(codex_home: Path) -> bool:
    home = Path.home()
    if not (home / ".codex-personal").is_dir():
        return False
    try:
        return codex_home.resolve() == (home / ".codex").resolve()
    except OSError:
        return False


def find_auth_problem(codex_home: Path) -> str | None:
    auth_path = codex_home / "auth.json"
    # 壊れた symlink も「置かれている」側に数える
    if auth_path.is_symlink() or auth_path.exists():
        return (
            f"会社用の {auth_path} があります。model_provider が消えると、"
            "このアカウントで動きます。個人用の CODEX_HOME へ移してください (ADR 0026)。"
        )
    return None


def find_problems(codex_home: Path) -> list[str]:
    config_path = codex_home / "config.toml"
    separated = is_separated_company_home(codex_home)
    if not config_path.exists():
        auth_problem = find_auth_problem(codex_home) if separated else None
        return [auth_problem] if auth_problem else []
    try:
        with config_path.open("rb") as f:
            config = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return [f"{config_path} を読めないため、Codex の provider を検査できません。"]

    providers = config.get("model_providers", {})
    if not isinstance(providers, dict):
        return [f"{config_path} の model_providers がテーブルではないため、provider を検査できません。"]
    if not providers and not separated:
        # 自前 provider を定義しない構成 (既定の openai を使う個人用) は対象外
        return []

    problems = []
    if providers:
        provider_problem = find_provider_problem(config_path, config, providers)
        if provider_problem:
            problems.append(provider_problem)
    auth_problem = find_auth_problem(codex_home)
    if auth_problem:
        problems.append(auth_problem)
    return problems


def find_provider_problem(config_path: Path, config: dict, providers: dict) -> str | None:

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
    problems = find_problems(codex_home)
    if problems:
        warn("警告: " + " ".join(problems))


if __name__ == "__main__":
    main()
