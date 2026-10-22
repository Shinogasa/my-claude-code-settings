"""jp-doc-reviewer に渡す原文の写し。jp-doc-review.py（写しを取る・消す）と jp-doc-lint.py（差分の検査に使う）が共有する。

写しは状態の置き場（~/.claude/state/jp-doc-review/sources/<セッション>/）に置き、作業repoには置かない。
社内文書の写しなので、ディレクトリは0700、ファイルは0600にする。
"""
import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional


def state_dir() -> Path:
    override = os.environ.get("JP_DOC_REVIEW_STATE_DIR")
    return Path(override) if override else Path.home() / ".claude" / "state" / "jp-doc-review"


def sources_dir() -> Path:
    return state_dir() / "sources"


def snapshot_path(session: str, real_path: str) -> Path:
    """写しの置き場。名前は実体のパスのハッシュにする（パスをそのまま名前にすると、区切りや長さで壊れる）。"""
    digest = hashlib.sha256(real_path.encode("utf-8")).hexdigest()[:16]
    return sources_dir() / session / digest


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def write_snapshot(session: str, real_path: str) -> None:
    """依頼の時点の本文を写す。同じファイルの写しがあれば上書きする（依頼のたびに、その時点の本文を原文とする）。"""
    target = snapshot_path(session, real_path)
    _ensure_private_dir(sources_dir())
    _ensure_private_dir(target.parent)
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")  # 0600で作られる
    try:
        with os.fdopen(fd, "wb") as handle, open(real_path, "rb") as source:
            shutil.copyfileobj(source, handle)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def find_snapshot(real_path: str, session: str) -> Optional[Path]:
    path = snapshot_path(session, real_path)
    return path if path.is_file() else None


def remove_session(session: str) -> None:
    shutil.rmtree(sources_dir() / session, ignore_errors=True)


def _active_path(session: str) -> Path:
    return sources_dir() / session / ".active"


def _read_active(session: str) -> int:
    try:
        return max(0, int(_active_path(session).read_text(encoding="ascii").strip() or 0))
    except (OSError, ValueError):
        return 0


def acquire(session: str) -> None:
    """レビュワーを1つ起動したことを数える。呼び出し側がセッションのロックを持っていること。"""
    path = _active_path(session)
    _ensure_private_dir(path.parent)
    path.write_text(str(_read_active(session) + 1), encoding="ascii")
    os.chmod(path, 0o600)


def release(session: str) -> None:
    """レビュワーが1つ終わったことを数え、動いているものが無くなったら写しを消す。

    同じセッションで並行するレビュワーの写しを、先に終わった側が消さないため。呼び出し側がセッションのロックを持っていること。
    """
    remaining = _read_active(session) - 1
    if remaining > 0:
        _active_path(session).write_text(str(remaining), encoding="ascii")
        return
    remove_session(session)
