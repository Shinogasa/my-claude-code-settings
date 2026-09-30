"""通常fixtureのGit操作を個人設定・署名agent・外部hookから隔離する。"""
import os
import subprocess
import tempfile


def git(cwd, *arguments):
    """一時HOMEと環境変数だけで隔離し、Gitの実行結果を返す。

    hookの存在や設定を検査する本体プロセスには、この環境を渡さない。
    リポジトリ内の設定やhookファイルも書き換えない。
    """
    with tempfile.TemporaryDirectory(prefix="git-fixture-home-") as home:
        # GIT_DIR等が残ると-Cより優先され、fixture外のリポジトリを操作する。
        environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }
        environment.update({
            "HOME": home,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "commit.gpgSign",
            "GIT_CONFIG_VALUE_0": "false",
            "GIT_CONFIG_KEY_1": "core.hooksPath",
            "GIT_CONFIG_VALUE_1": os.devnull,
        })
        return subprocess.run(
            ["git", "-C", str(cwd), *arguments],
            env=environment, check=True, capture_output=True, text=True,
        )
