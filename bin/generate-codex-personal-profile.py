#!/usr/bin/env python3
"""個人 ChatGPT アカウント用の Codex プロファイルを生成する。

Codex のプロファイルは base 設定を「置き換える」のではなく「重ねる」。
プロファイルに書いていない ``[mcp_servers.*]`` は個人セッションでもそのまま起動するため、
会社のゲートウェイ上にあるサーバや会社アカウントで認証するサーバが残ると、
個人作業が会社インフラを会社の鍵で叩く。エラーも通知も出ないので気づけない。

そのため無効化リストを手書きせず、``~/.codex/config.toml`` から導出する。
向きは deny by default で、有効にするサーバだけを allowlist に列挙する。

setup が所有するのは ``model_provider`` と ``mcp_servers`` だけ。Codex は起動中の
プロファイルへ設定保存（モデル既定、project の信頼、hook の信頼など）を書き込むため、
それ以外のキーは既存のプロファイルから引き継ぐ。

実行: python3 bin/generate-codex-personal-profile.py <config.toml> <allowlist> <dest> [existing]
existing を省略したときは dest 自身を既存のプロファイルとして読む。
"""
import json
import math
import os
import re
import sys
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

# setup が値を決めるキー。これ以外は Codex の所有として引き継ぐ。
OWNED_KEYS = ("model_provider", "mcp_servers")
# 所有キーに触れずに接続先や有効な設定を差し替えうるキー。引き継がずに生成を止める。
# Codex がプロファイル内でこれらを解釈するかは未確認だが、止める側に倒す（ADR 0023）。
REDIRECTING_KEYS = (
    "openai_base_url", "chatgpt_base_url", "model_providers", "profiles", "profile",
)
BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")


class PreserveError(ValueError):
    """Codex 側の設定を引き継げないときの失敗。MCP 定義の不正とは区別して報告する。"""

# 個人セッションで有効にしても、外部へ出ていくサーバかどうかの判定に使うキー。
# config.toml にある remote サーバは会社のゲートウェイ上にある可能性が高い。
NETWORK_FACING_KEYS = ("url", "http_headers", "bearer_token_env_var")

HEADER = [
    "# model_provider と mcp_servers は setup.sh が生成し、手で編集すると次回の setup.sh で競合になる。",
    "# それ以外の設定（Codex が保存したモデル既定や信頼設定など）は次回の setup.sh でも引き継ぐ。",
    "# 有効にする MCP サーバは codex/personal-mcp-allowlist.txt で管理する。",
    "",
    "# 会社の LLM gateway ではなく個人の ChatGPT アカウントを使う。",
    'model_provider = "openai"',
    "",
]


def read_allowlist(path: Path) -> set[str]:
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def read_mcp_servers(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f).get("mcp_servers", {})


def quote_toml_string(value: str) -> str:
    """TOML の基本文字列として値をクォートする。"""
    return json.dumps(value, ensure_ascii=False)


def quote_key(name: str) -> str:
    """TOML の quoted key としてサーバ名をクォートする。

    エスケープせずに埋め込むと、`"` や `\\` を含む名前で生成物が壊れる。
    壊れた場合 cxp 側の tomllib が落ちて起動は止まる(fail closed)が、
    原因が生成側だと分かりにくいため、ここで正しく出す。
    """
    return quote_toml_string(name)


def mcp_transport(name: str, definition) -> tuple[str, str]:
    """MCP 定義から単一の transport discriminator を取得する。"""
    if not isinstance(definition, dict):
        raise ValueError(f"MCP サーバ {name!r} の定義がテーブルではありません")

    keys = [key for key in ("command", "url") if key in definition]
    if len(keys) != 1:
        raise ValueError(
            f"MCP サーバ {name!r} の transport は "
            "command または url のどちらか一方である必要があります"
        )

    key = keys[0]
    value = definition[key]
    if not isinstance(value, str) or not value:
        raise ValueError(
            f"MCP サーバ {name!r} の {key} は空でない文字列である必要があります"
        )
    if key == "url":
        try:
            parsed = urlsplit(value)
        except ValueError as error:
            raise ValueError(f"MCP サーバ {name!r} の url が不正です") from error
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                f"MCP サーバ {name!r} の url に個人プロファイルへ複写できない要素があります"
            )
    return key, value


def is_network_facing(definition) -> bool:
    if not isinstance(definition, dict):
        return False
    return any(key in definition for key in NETWORK_FACING_KEYS)


def read_preserved(path: Path) -> dict:
    """既存プロファイルから setup の所有外のキーを読む。

    読めないファイルを空とみなすと Codex 側の設定を黙って捨てるため、例外のまま上げる。
    """
    if not path.exists():
        return {}
    with path.open("rb") as f:
        document = tomllib.load(f)
    redirecting = sorted(key for key in document if key in REDIRECTING_KEYS)
    if redirecting:
        raise PreserveError(
            "接続先を変えうるキーが含まれています（"
            + ", ".join(redirecting)
            + "）。削除してから setup.sh を再実行してください"
        )
    return {key: value for key, value in document.items() if key not in OWNED_KEYS}


def toml_key(name: str) -> str:
    return name if BARE_KEY.fullmatch(name) else quote_key(name)


def toml_value(value) -> str:
    """引き継ぐ値を TOML へ書き出す。扱えない型は落とさずに失敗させる。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return repr(value)
    if isinstance(value, str):
        return quote_toml_string(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        pairs = ", ".join(f"{toml_key(k)} = {toml_value(v)}" for k, v in value.items())
        return "{ " + pairs + " }" if pairs else "{}"
    raise PreserveError(f"引き継げない値の型です: {type(value).__name__}")


def render_table(table: dict, path: list[str], lines: list[str]) -> None:
    """テーブルを見出し付きで書き出す。空のテーブルも見出しを残して往復を保つ。"""
    lines.append("[" + ".".join(toml_key(part) for part in path) + "]")
    for key, value in table.items():
        if not isinstance(value, dict):
            lines.append(f"{toml_key(key)} = {toml_value(value)}")
    lines.append("")
    for key, value in table.items():
        if isinstance(value, dict):
            render_table(value, [*path, key], lines)


def render(servers: dict, allowed: set[str], preserved: dict | None = None) -> str:
    preserved = preserved or {}
    lines = list(HEADER)
    # TOML ではテーブル見出しより前にしかトップレベルの値を書けない。
    top_level = [(k, v) for k, v in preserved.items() if not isinstance(v, dict)]
    for key, value in top_level:
        lines.append(f"{toml_key(key)} = {toml_value(value)}")
    if top_level:
        lines.append("")
    # config.toml にある全サーバを明示的に列挙する。無効なものだけ書くと、cxp の未反映検査が
    # 「許可済みで省略した」と「そもそも反映していない」を区別できなくなる。
    for name in sorted(servers):
        transport_key, transport_value = mcp_transport(name, servers[name])
        lines.append(f"[mcp_servers.{quote_key(name)}]")
        lines.append(f"{transport_key} = {quote_toml_string(transport_value)}")
        lines.append(f"enabled = {'true' if name in allowed else 'false'}")
        lines.append("")
    for key, value in preserved.items():
        if isinstance(value, dict):
            render_table(value, [key], lines)
    return "\n".join(lines)


def verify_round_trip(content: str, preserved: dict) -> None:
    """書き出した内容を読み直し、引き継いだキーが一致しなければ書き込ませない。"""
    document = tomllib.loads(content)
    actual = {key: value for key, value in document.items() if key not in OWNED_KEYS}
    if actual != preserved or document.get("model_provider") != "openai":
        raise PreserveError("生成したプロファイルを読み直した結果が、引き継ぐ内容と一致しません")


def write_profile(dest: Path, content: str) -> None:
    """生成物を 600 で原子的に置き換える。

    生成元の config.toml は 600。生成物には transport の値と会社の MCP サーバ名が
    含まれるため、共有マシンで他ユーザーへ見せる理由がない。

    途中で落ちた生成物が残ると cxp が tomllib で落ちる(fail closed)ため実害は無いが、
    原因が読みにくいので一時ファイル経由で置き換える。
    """
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, dest)


def main(argv: list[str]) -> int:
    if len(argv) not in (3, 4):
        print(
            "usage: generate-codex-personal-profile.py <config.toml> <allowlist> <dest> [existing]",
            file=sys.stderr,
        )
        return 2

    base_config, allowlist_path, dest = (Path(p) for p in argv[:3])
    existing = Path(argv[3]) if len(argv) == 4 else dest
    allowed = read_allowlist(allowlist_path)
    servers = read_mcp_servers(base_config)

    try:
        preserved = read_preserved(existing)
        content = render(servers, allowed, preserved)
        verify_round_trip(content, preserved)
    except (OSError, tomllib.TOMLDecodeError, PreserveError) as error:
        print(f"エラー: {existing} の Codex 側の設定を引き継げません: {error}", file=sys.stderr)
        return 1

    write_profile(dest, content)
    if preserved:
        print(f"  引き継いだ Codex 側の設定: {', '.join(preserved)}")

    enabled = sorted(n for n in servers if n in allowed)
    disabled = sorted(n for n in servers if n not in allowed)
    print(f"  MCP 有効: {', '.join(enabled) or 'なし'}")
    print(f"  MCP 無効: {', '.join(disabled) or 'なし'}")

    # 許可リストは人間が書く。会社のリモートサーバを誤って足しても、
    # 生成は成功してしまい実行結果からは気づけない。判断した本人の目に入る位置で言う。
    exposed = [n for n in enabled if is_network_facing(servers[n])]
    if exposed:
        print(
            "  警告: 許可したサーバが外部へ接続します: "
            + ", ".join(exposed)
            + "\n        会社のゲートウェイ上にあるなら codex/personal-mcp-allowlist.txt から外すこと。",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
