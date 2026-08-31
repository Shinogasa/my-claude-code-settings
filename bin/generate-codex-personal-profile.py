#!/usr/bin/env python3
"""個人 ChatGPT アカウント用の Codex プロファイルを生成する。

Codex のプロファイルは base 設定を「置き換える」のではなく「重ねる」。
プロファイルに書いていない ``[mcp_servers.*]`` は個人セッションでもそのまま起動するため、
会社のゲートウェイ上にあるサーバや会社アカウントで認証するサーバが残ると、
個人作業が会社インフラを会社の鍵で叩く。エラーも通知も出ないので気づけない。

そのため無効化リストを手書きせず、``~/.codex/config.toml`` から導出する。
向きは deny by default で、有効にするサーバだけを allowlist に列挙する。

実行: python3 bin/generate-codex-personal-profile.py <config.toml> <allowlist> <dest>
"""
import os
import sys
import tomllib
from pathlib import Path

# 個人セッションで有効にしても、外部へ出ていくサーバかどうかの判定に使うキー。
# config.toml にある remote サーバは会社のゲートウェイ上にある可能性が高い。
NETWORK_FACING_KEYS = ("url", "http_headers", "bearer_token_env_var")

HEADER = [
    "# setup.sh が生成する。手で編集しても次回の setup.sh 実行で上書きされる。",
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


def quote_key(name: str) -> str:
    """TOML の基本文字列としてサーバ名をクォートする。

    エスケープせずに埋め込むと、`"` や `\\` を含む名前で生成物が壊れる。
    壊れた場合 cxp 側の tomllib が落ちて起動は止まる(fail closed)が、
    原因が生成側だと分かりにくいため、ここで正しく出す。
    """
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def is_network_facing(definition) -> bool:
    if not isinstance(definition, dict):
        return False
    return any(key in definition for key in NETWORK_FACING_KEYS)


def render(servers: dict, allowed: set[str]) -> str:
    lines = list(HEADER)
    # config.toml にある全サーバを明示的に列挙する。無効なものだけ書くと、cxp の未反映検査が
    # 「許可済みで省略した」と「そもそも反映していない」を区別できなくなる。
    for name in sorted(servers):
        lines.append(f"[mcp_servers.{quote_key(name)}]")
        lines.append(f"enabled = {'true' if name in allowed else 'false'}")
        lines.append("")
    return "\n".join(lines)


def write_profile(dest: Path, content: str) -> None:
    """生成物を 600 で原子的に置き換える。

    生成元の config.toml は 600。生成物は値を転記しないが、会社の MCP サーバ名は
    社内トポロジの情報なので、共有マシンで他ユーザーへ見せる理由がない。

    途中で落ちた生成物が残ると cxp が tomllib で落ちる(fail closed)ため実害は無いが、
    原因が読みにくいので一時ファイル経由で置き換える。
    """
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, dest)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "usage: generate-codex-personal-profile.py <config.toml> <allowlist> <dest>",
            file=sys.stderr,
        )
        return 2

    base_config, allowlist_path, dest = (Path(p) for p in argv)
    allowed = read_allowlist(allowlist_path)
    servers = read_mcp_servers(base_config)

    write_profile(dest, render(servers, allowed))

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
