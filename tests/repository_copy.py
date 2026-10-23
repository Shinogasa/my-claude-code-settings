"""setup 系のテストが使う、リポジトリの写しを作る。

作業ツリーからテストに要るパスだけを写し、元のリポジトリで ignore された未追跡ファイルを除く。
ignore された生成物（rules/persona.md など）がリポジトリ直下にだけあると、
写し漏れが隠れてworktreeでだけテストが落ちるため（PR #98）。git add 前の新しいファイルは写す。

macOS では APFS の clonefile（cp -c）で写す。copy-on-write なので、写しへの書き込みは元を変えない。
shutil.copytree だと並列実行のときにファイルの書き込みが一列に並び、setup 系のテストの大半を占めていた。
"""
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from git_fixture import git  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_PATHS = (
    ".gitmodules", "CLAUDE.md", "README.md", "settings.json.template",
    "env.json.template", "setup.sh", "statusline.js",
    ".githooks", "agents", "bin", "codex", "commands", "hooks", "manifests",
    "output-styles", "personas", "rules", "skills",
)
CAN_CLONE = sys.platform == "darwin"


def copy_repository(base: Path, root: Path = ROOT, paths=REPOSITORY_PATHS,
                    use_clone: bool = CAN_CLONE) -> Path:
    repository = base / "repository"
    repository.mkdir()
    for relative in paths:
        copy_path(root / relative, repository / relative, use_clone)
    for relative in ignored_untracked(root, paths):
        remove_path(repository / relative)
    return repository


def copy_path(source: Path, target: Path, use_clone: bool) -> None:
    if use_clone:
        result = subprocess.run(["cp", "-c", "-p", "-R", "-P", str(source), str(target)],
                                capture_output=True)
        if result.returncode == 0:
            return
        # 一時ディレクトリが別のボリュームにあるなど、clone できないときは通常のコピーに戻す
        remove_path(target)
    if source.is_dir() and not source.is_symlink():
        shutil.copytree(source, target, symlinks=True)
    else:
        shutil.copy2(source, target, follow_symlinks=False)


def ignored_untracked(root: Path, paths) -> list:
    """root で ignore されている未追跡のパス。ディレクトリごと ignore されていれば、そのディレクトリを返す。

    利用者のグローバルな ignore を持ち込まないよう、fixture の git で調べる。
    持ち込むと、マシンによって写しの中身が変わる。
    """
    output = git(root, "ls-files", "--others", "--ignored", "--exclude-standard",
                 "--directory", "-z", "--", *paths).stdout
    return [entry.rstrip("/") for entry in output.split("\0") if entry]


def remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()
