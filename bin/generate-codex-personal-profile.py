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
import sys
import tomllib
from pathlib import Path

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


def render(servers: dict, allowed: set[str]) -> str:
    lines = list(HEADER)
    # config.toml にある全サーバを明示的に列挙する。無効なものだけ書くと、cxp の未反映検査が
    # 「許可済みで省略した」と「そもそも反映していない」を区別できなくなる。
    for name in sorted(servers):
        lines.append(f'[mcp_servers."{name}"]')
        lines.append(f"enabled = {'true' if name in allowed else 'false'}")
        lines.append("")
    return "\n".join(lines)


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

    dest.write_text(render(servers, allowed), encoding="utf-8")

    enabled = sorted(n for n in servers if n in allowed)
    disabled = sorted(n for n in servers if n not in allowed)
    print(f"  MCP 有効: {', '.join(enabled) or 'なし'}")
    print(f"  MCP 無効: {', '.join(disabled) or 'なし'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
