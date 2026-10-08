#!/usr/bin/env python3
"""setup.sh が管理する生成物と退避先を判定する小さな状態管理モジュール。"""
import argparse
import hashlib
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


DEFAULT_STATE = {"version": 1, "generated": {}}
# 生成物の一部だけを setup が所有する場合の記録形式。
# 例: "owned-sha256:model_provider,mcp_servers:<hex>"。所有外のキーの変更は競合にしない。


def is_legacy_skills_parent(parent, repo_skills, repo_root):
    """parent が移行対象の旧親リンクかを、配置を変えずに判定する。

    事前検査は移行より前に走るため、判定と実行を分けておく（ADR 0022）。
    途中の移行状態が残っていれば、判定もせずに止める。
    """
    parent = Path(parent).absolute()
    repo_root = Path(repo_root).resolve(strict=True)
    repo_skills = Path(repo_skills).resolve(strict=True)
    leftovers = sorted(parent.parent.glob(f"{parent.name}.migrating.*"))
    if leftovers:
        raise RuntimeError("途中の移行状態が残っています: " + ", ".join(map(str, leftovers)))
    if not parent.is_symlink():
        return False
    try:
        resolved = parent.resolve(strict=True)
        host_root = parent.parent.resolve(strict=True)
    except (OSError, RuntimeError):
        # 由来を確定できないリンクは外さず、既存preflightで拒否する。
        return False
    return resolved == repo_skills and not host_root.is_relative_to(repo_root)


def migrate_legacy_skills_parent(parent, repo_skills, repo_root):
    """このrepoを指す旧親リンクだけを移行し、移した項目名を返す。"""
    if not is_legacy_skills_parent(parent, repo_skills, repo_root):
        return None
    parent = Path(parent).absolute()
    repo_root = Path(repo_root).resolve(strict=True)
    repo_skills = Path(repo_skills).resolve(strict=True)

    untracked = []
    for item in sorted(repo_skills.iterdir()):
        tracked = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "--", f"skills/{item.name}"],
            check=True, capture_output=True,
            # 項目名をpathspecのpatternへ展開せず、その名前の追跡だけを検査する。
            env={**os.environ, "GIT_LITERAL_PATHSPECS": "1"},
        )
        if not tracked.stdout:
            untracked.append(item)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    temporary = parent.with_name(f"{parent.name}.migrating.{timestamp}")
    temporary.mkdir()
    moved = []
    try:
        for item in untracked:
            target = temporary / item.name
            os.rename(item, target)
            moved.append((item, target))
        parent.unlink()
    except OSError as error:
        unrestored = []
        for original, target in reversed(moved):
            try:
                if original.exists() or original.is_symlink():
                    raise FileExistsError(f"巻き戻し先が既に存在します: {original}")
                os.rename(target, original)
            except OSError as rollback_error:
                unrestored.append(f"{target} → {original}: {rollback_error}")
        if not unrestored:
            try:
                temporary.rmdir()
            except OSError as cleanup_error:
                unrestored.append(f"{temporary}: {cleanup_error}")
        details = "\n戻せなかった項目: " + "; ".join(unrestored) if unrestored else ""
        raise RuntimeError(f"旧形式skillsの移行に失敗しました: {error}{details}") from error

    # unlink後はデータを戻す先が親リンク経由で見えないため、完成側へ再試行する。
    try:
        os.rename(temporary, parent)
    except OSError:
        try:
            os.rename(temporary, parent)
        except OSError as error:
            recovery = f"mv {shlex.quote(str(temporary))} {shlex.quote(str(parent))}"
            raise RuntimeError(
                f"親リンク差し替えに失敗しました: {error}\n"
                f"移行データの保存先: {temporary}\n手で戻す手順: {recovery}"
            ) from error
    return [item.name for item in untracked]


def sha256_file(path):
    """ファイル内容の SHA-256 を16進数で返す。"""
    digest = hashlib.sha256()
    with Path(path).open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def matches_recorded(path, recorded):
    """destination が前回 setup の生成内容から変わっていないかを返す。"""
    return sha256_file(path) == recorded


def snapshot_path(path):
    """競合検査後の変更検知に使う、path自身のfingerprintを返す。"""
    path = Path(path)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return {"kind": "missing"}
    snapshot = {
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
        "mode": metadata.st_mode,
        "size": metadata.st_size,
        "mtime_ns": metadata.st_mtime_ns,
        "links": metadata.st_nlink,
    }
    if stat.S_ISLNK(metadata.st_mode):
        snapshot.update(kind="symlink", target=os.readlink(path))
    elif stat.S_ISREG(metadata.st_mode):
        snapshot.update(kind="file", sha256=sha256_file(path))
    elif stat.S_ISDIR(metadata.st_mode):
        snapshot["kind"] = "directory"
    else:
        snapshot["kind"] = "other"
    return snapshot


def _restore_quarantined_file(quarantined, destination, remove_parent=False):
    """regular fileを既存destinationへ上書きせず隔離先から戻す。"""
    quarantined_path = Path(quarantined)
    destination_path = Path(destination)
    try:
        if not stat.S_ISREG(quarantined_path.lstat().st_mode):
            return False
        os.link(quarantined_path, destination_path)
    except (FileExistsError, FileNotFoundError):
        return False
    quarantined_path.unlink()
    if remove_parent:
        quarantined_path.parent.rmdir()
    return True


def install_generated_file(staged, destination, expected_snapshot):
    """staged生成物を、検査後の更新を上書きせずdestinationへ配置する。"""
    staged_path = Path(staged)
    destination_path = Path(destination)
    if expected_snapshot == {"kind": "missing"}:
        if snapshot_path(destination_path) != expected_snapshot:
            raise RuntimeError(f"target changed after preflight: {destination_path}")
        try:
            os.link(staged_path, destination_path)
        except FileExistsError as error:
            raise RuntimeError(
                f"target appeared during generated apply: {destination_path}"
            ) from error
        staged_path.unlink()
        return

    quarantine_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{destination_path.name}.setup-quarantine.",
            dir=destination_path.parent,
        )
    )
    quarantined = quarantine_dir / destination_path.name
    try:
        os.rename(destination_path, quarantined)
    except FileNotFoundError as error:
        quarantine_dir.rmdir()
        raise RuntimeError(
            f"target changed after preflight: {destination_path}"
        ) from error

    actual_snapshot = snapshot_path(quarantined)
    if actual_snapshot != expected_snapshot:
        if _restore_quarantined_file(
            quarantined,
            destination_path,
            remove_parent=True,
        ):
            raise RuntimeError(
                f"target changed after preflight; restored at {destination_path}"
            )
        raise RuntimeError(
            f"target changed after preflight; preserved at {quarantined}"
        )
    try:
        os.link(staged_path, destination_path)
    except FileExistsError as error:
        raise RuntimeError(
            f"target appeared during generated apply; previous file preserved at {quarantined}"
        ) from error
    staged_path.unlink()
    quarantined.unlink()
    quarantine_dir.rmdir()


def backup_conflict(source, backup, expected_snapshot):
    """競合pathを差し替え競合から守りながらbackupへ移す。"""
    source_path = Path(source)
    backup_path = Path(backup)
    try:
        os.rename(source_path, backup_path)
    except FileNotFoundError as error:
        raise RuntimeError(f"target changed after preflight: {source_path}") from error

    actual_snapshot = snapshot_path(backup_path)
    if actual_snapshot != expected_snapshot:
        if _restore_quarantined_file(backup_path, source_path):
            raise RuntimeError(
                f"target changed after preflight; restored at {source_path}"
            )
        raise RuntimeError(
            f"target changed after preflight; preserved at {backup_path}"
        )

    if actual_snapshot["kind"] == "file" and actual_snapshot["links"] > 1:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{backup_path.name}.setup-copy.",
            dir=backup_path.parent,
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            shutil.copy2(backup_path, temporary, follow_symlinks=False)
            if (
                snapshot_path(backup_path) != expected_snapshot
                or sha256_file(temporary) != expected_snapshot["sha256"]
            ):
                if _restore_quarantined_file(backup_path, source_path):
                    raise RuntimeError(
                        f"target changed during backup; restored at {source_path}"
                    )
                raise RuntimeError(
                    f"target changed during backup; preserved at {backup_path}"
                )
            os.replace(temporary, backup_path)
        finally:
            temporary.unlink(missing_ok=True)

    if source_path.exists() or source_path.is_symlink():
        raise RuntimeError(
            f"target appeared while backing up conflict: {source_path}; "
            f"previous file preserved at {backup_path}"
        )


def classify(source, destination, recorded, generated=False):
    """destination の所有状態を missing/linked/managed-update/conflict に分類する。"""
    source_path = Path(source).resolve()
    destination_path = Path(destination)
    if not destination_path.exists() and not destination_path.is_symlink():
        return "missing"
    if generated:
        if destination_path.is_symlink():
            return "conflict"
        try:
            if destination_path.is_file() and destination_path.stat().st_nlink > 1:
                return "conflict"
        except OSError:
            return "conflict"
    if destination_path.is_symlink():
        try:
            if destination_path.resolve() == source_path:
                return "linked"
        except OSError:
            pass
        return "conflict"
    if (
        recorded
        and destination_path.is_file()
        and matches_recorded(destination_path, recorded)
    ):
        return "managed-update"
    return "conflict"


def backup_path(host_root, destination, timestamp, home_root=None):
    """host別backup配下の衝突退避先を返す。"""
    host_path = Path(host_root).absolute()
    destination_path = Path(destination).absolute()
    try:
        relative = destination_path.relative_to(host_path)
    except ValueError:
        if home_root is None:
            raise ValueError("destination must be inside host_root") from None
        try:
            relative = destination_path.relative_to(Path(home_root).absolute())
        except ValueError as error:
            raise ValueError("destination must be inside home_root") from error
    return host_path / "backups" / timestamp / relative


def load_state(path):
    """ownership state を読み、欠損・不正形式なら空の安全な状態を返す。"""
    state_path = Path(path)
    if not state_path.is_file():
        return {"version": 1, "generated": {}}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "generated": {}}
    if not isinstance(state, dict) or state.get("version") != 1:
        return {"version": 1, "generated": {}}
    generated = state.get("generated")
    if not isinstance(generated, dict) or not all(
        isinstance(path_name, str) and isinstance(checksum, str)
        for path_name, checksum in generated.items()
    ):
        return {"version": 1, "generated": {}}
    return {"version": 1, "generated": dict(generated)}


def save_state(path, state):
    """state を同じディレクトリで原子的に保存する。"""
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_name(f".{state_path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(state_path)


# ここから下は、setup.sh が対象ごとにPythonを起動していた処理を1回の起動へまとめる一括処理（ADR 0030）。
# 1件ずつ呼んでいたときと同じ判定・メッセージ・終了コードを保つ。


def compact_snapshot(path):
    """setup.sh が TARGET_SNAPSHOTS に保存するのと同じ形式のJSON文字列を返す。"""
    return json.dumps(snapshot_path(path), sort_keys=True, separators=(",", ":"))


def classify_targets(entries):
    """(generated, state_path, source, destination) の列を、渡された順に分類する。

    generated の対象だけ、前回の生成内容のchecksumを state から引いて判定に使う。
    """
    results = []
    for generated, state_path, source, destination in entries:
        recorded = None
        if generated:
            recorded = load_state(state_path)["generated"].get(destination) or None
        results.append(classify(source, destination, recorded, generated))
    return results


def link_topology_error(source, destination):
    """リンクの配置が危険なら理由を、問題が無ければ None を返す。"""
    source = Path(source)
    destination = Path(destination)
    # 残るskills親symlinkは、旧形式と確定できず移行しなかったもの。
    if destination.parent.name == "skills" and destination.parent.is_symlink():
        return (
            "skills parent symlink はrepo以外を指すか由来を確定できないため自動移行しない: "
            f"{destination.parent}"
        )
    try:
        source_resolved = source.resolve(strict=False)
        destination_parent = destination.parent.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        return f"link path resolution failed: {destination}: {error}"

    # 宛先の親がソース配下を指すと、ln -s がソース自身へ自己参照リンクを作る。
    candidate = destination_parent / destination.name
    if (
        candidate == source_resolved
        or candidate.is_relative_to(source_resolved)
        or source_resolved.is_relative_to(candidate)
    ):
        return (
            "link source and destination overlap after symlink resolution: "
            f"source={source} destination={destination}"
        )
    return None


def apply_links(entries):
    """(source, destination, 期待するsnapshot) の列を順にリンクし、終了コードを返す。

    対象ごとに「snapshot再検査 → mkdir -p → 既存確認 → ln -s」の順を保ち、検査とリンクの
    間を1件分に留める。mkdir と ln はPATHから呼ぶ。setup.sh と同じ外部コマンドを使い、
    失敗時の出力もそれらに任せる。最初の失敗で止まり、後続の対象には触れない。
    """
    for source, destination, expected in entries:
        if compact_snapshot(destination) != expected:
            print(f"エラー: target changed after preflight: {destination}", file=sys.stderr)
            return 1
        if subprocess.run(["mkdir", "-p", os.path.dirname(destination)]).returncode != 0:
            return 1
        if os.path.islink(destination):
            if classify(source, destination, None) == "linked":
                continue
            print(f"エラー: target changed before link apply: {destination}", file=sys.stderr)
            return 1
        if os.path.exists(destination):
            print(f"エラー: target changed before link apply: {destination}", file=sys.stderr)
            return 1
        if subprocess.run(["ln", "-s", source, destination]).returncode != 0:
            return 1
    return 0


def _groups(parser, values, size, name):
    """平らな引数列を size 個ずつの組に分ける。端数があれば使い方の誤りとして止める。"""
    if len(values) % size:
        parser.error(f"{name} の引数は {size} 個ずつの組で渡してください")
    return [tuple(values[index:index + size]) for index in range(0, len(values), size)]


def run_batch_command(parser, args):
    """一括処理サブコマンドを実行する。予期しない例外は従来どおりtracebackで落とす。"""
    if args.command == "classify-targets":
        entries = [
            (generated == "true", state_path, source, destination)
            for generated, state_path, source, destination
            in _groups(parser, args.values, 4, args.command)
        ]
        for classification in classify_targets(entries):
            print(classification)
        return 0
    if args.command == "snapshot-paths":
        for path in args.values:
            print(compact_snapshot(path))
        return 0
    if args.command == "check-link-topology":
        for source, destination in _groups(parser, args.values, 2, args.command):
            error = link_topology_error(source, destination)
            if error is not None:
                print(error, file=sys.stderr)
                return 1
        return 0
    return apply_links(_groups(parser, args.values, 3, args.command))


BATCH_COMMANDS = ("classify-targets", "snapshot-paths", "check-link-topology", "apply-links")


def main():
    """setup.sh用の移行・一括処理サブコマンドを受け付ける。"""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in BATCH_COMMANDS:
        commands.add_parser(name).add_argument("values", nargs="*")
    migration = commands.add_parser("migrate-legacy-skills-parent")
    migration.add_argument("parent")
    migration.add_argument("repo_skills")
    migration.add_argument("repo_root")
    detection = commands.add_parser("detect-legacy-skills-parent")
    detection.add_argument("parent")
    detection.add_argument("repo_skills")
    detection.add_argument("repo_root")
    args = parser.parse_args()
    if args.command in BATCH_COMMANDS:
        return run_batch_command(parser, args)
    try:
        if args.command == "detect-legacy-skills-parent":
            if is_legacy_skills_parent(args.parent, args.repo_skills, args.repo_root):
                print("legacy")
            return 0
        names = migrate_legacy_skills_parent(args.parent, args.repo_skills, args.repo_root)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1
    if names is not None:
        items = ", ".join(names) if names else "なし"
        print(f"{args.parent} を旧形式のsymlinkから実ディレクトリへ移行しました。移した追跡外項目: {items}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
