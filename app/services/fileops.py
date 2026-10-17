"""文件操作：新建、复制、移动、重命名、删除、压缩、解压。

## 为什么压缩与解压在本地做

远端只跑 SFTP 服务（验收项 T-013：不为文件操作在远端执行命令）。所以：

- 压缩 = 本地用 tarfile 顺序读远端文件，把压缩流写回远端的一个新文件；
- 解压 = 本地读远端压缩包，逐条把内容写回远端目录。

整个过程内存里只有一个块（决策 D-007），压缩一个几百 MB 的目录不会让进程占用跟着涨。

## 破坏性操作的三条纪律

1. 写权限必须在服务端查（require_write_permission）。前端把按钮变灰只是提示，
   绕过界面直接打接口一样会被拒。
2. 删除要先看清楚删的是什么。目录默认不递归；递归必须由调用方显式声明，
   而且**不跟随符号链接**：链接本身被删掉，它指向的目录不动。
3. 压缩包里的名字一律当不可信输入。绝对路径、含 .. 的成员名直接拒绝解压；
   符号链接、硬链接、设备文件跳过并如实报告 —— 否则一个构造过的 tar 就能
   往远端任意位置写文件。跳过的条目会在响应里列出来，不静默吞掉。

## 新建为什么用 EXCL 而不是「先查再建」

v0.1.3 §4 明确要求排他创建语义。「先 stat 确认不存在，再 create」在两个人同时
新建同名文件时会双双通过检查、后到的那个静默覆盖先到的 —— 这正是任务书禁止的
「静默覆盖」。所以新建文件走 `CREAT|EXCL`（服务端原子地拒绝已存在的目标），
新建目录走 `MKDIR`（POSIX 语义本身就是排他的）。前置的 `lstat` 只为把「已存在」
翻译成人话，不承担互斥职责。

复制不用远端命令（T-013），走 SFTP 读 + 写：内存里只有一个块（决策 D-007），
符号链接不在复制范围内（我们的 SFTP 客户端没有创建链接的能力），跳过并如实报告。
"""

from __future__ import annotations

import gzip
import logging
import tarfile
import uuid
import zipfile
from typing import Any

from app.core.errors import (
    AwfmError,
    NotConnected,
    PathNotFound,
    PermissionDenied,
    ProtocolError,
    ValidationError,
)
from app.services.filesystem import require_write_permission, resolve_path
from app.services.session import RemoteSession
from app.services.transfer import PART_SUFFIX
from app.ssh import sftp_protocol as proto
from app.ssh.sftp_client import ChunkWriter, RandomReader
from app.utils.paths import (
    join_remote_path,
    parent_remote_path,
    validate_remote_name,
    validate_remote_path,
)

logger = logging.getLogger(__name__)

#: 支持的压缩包后缀。按长后缀优先判断（.tar.gz 不能落到 .tar 那一支）。
ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".tar", ".zip")

#: 一次压缩最多打包多少个条目。超过就整体拒绝：半截的压缩包比没有更糟。
MAX_ARCHIVE_ENTRIES = 10000

#: 一次压缩读取的原始字节上限。
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024

#: 一次解压最多写出多少个条目。
MAX_EXTRACT_ENTRIES = 10000

#: 一次解压写出的原始字节上限。
MAX_EXTRACT_BYTES = 512 * 1024 * 1024

#: 一次递归删除最多删多少个条目。
MAX_DELETE_ENTRIES = 10000

#: 目录层级上限。防的是「结构异常深」的树，不是正常的项目目录。
MAX_TREE_DEPTH = 64

#: 一次复制最多处理多少个条目（与删除、压缩同一量级）。
MAX_COPY_ENTRIES = 10000

#: 一次复制搬运的原始字节上限。
MAX_COPY_BYTES = 512 * 1024 * 1024


class _ExtractStop(Exception):
    """解压中途触到上限。

    不向上抛成错误：已经解出来的部分是真的，用户需要知道「解到哪儿停了」，
    而不是收到一个「什么都不算数」的失败。
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def name_of(path: str) -> str:
    """取路径的最后一段（根目录返回 /）。"""
    return path.rstrip("/").rpartition("/")[2] or "/"


def archive_format(path: str) -> str:
    """按后缀判断压缩包格式，返回 tar.gz / tar / zip，都不是则返回空串。"""
    lowered = path.lower()
    if lowered.endswith(".tar.gz") or lowered.endswith(".tgz"):
        return "tar.gz"
    if lowered.endswith(".tar"):
        return "tar"
    if lowered.endswith(".zip"):
        return "zip"
    return ""


def _exists(client, path: str):
    """存在就返回属性，不存在返回 None（别的错误照旧抛出）。"""
    try:
        return client.lstat(path)
    except PathNotFound:
        return None


def _canonical_entry_path(session: RemoteSession, raw_path: str) -> str:
    """把路径规范化成「父目录的 REALPATH + 原样的最后一段」。

    只解析父目录的符号链接，**故意不解析最后一段**：重命名、删除、压缩针对的是
    用户在列表里点中的那个条目。如果整条路径都交给 realpath，点「删除」一个
    指向 /etc/passwd 的链接就会去删 /etc/passwd —— 链接本身反而留着。

    父目录仍要 realpath，是为了让 .. 和重复斜杠得到服务端的权威结果；
    最后一段的名字由 validate_remote_path 保证非空且不含 NUL。
    """
    validated = validate_remote_path(raw_path)
    trimmed = validated.rstrip("/") or "/"
    if trimmed == "/":
        return "/"
    parent = parent_remote_path(trimmed)
    name = trimmed.rsplit("/", 1)[1]
    if parent is None:
        return "/" + name
    return join_remote_path(session.client.realpath(parent), name)


# --------------------------------------------------------------------- 重命名


def rename_entry(session: RemoteSession, raw_path: str, new_name: str) -> dict:
    """把远端的一个条目改名（同一目录内）。移动目录树不在本阶段范围内。"""
    require_write_permission(session, "重命名")
    name = validate_remote_name(new_name)
    canonical = _canonical_entry_path(session, raw_path)
    parent = parent_remote_path(canonical)
    if parent is None or canonical == "/":
        raise ValidationError("不能重命名根目录。")
    client = session.client
    target = join_remote_path(parent, name)
    if target == canonical:
        raise ValidationError("新名称与原名相同。", detail=canonical)
    existing = _exists(client, target)
    if existing is not None:
        raise ValidationError(
            "目标位置已经存在同名条目。",
            detail=f"{target}（{existing.type}）。请换一个名称，或先处理掉那个条目。",
            extra={"path": target, "exists": True, "type": existing.type},
        )
    client.rename(canonical, target)
    attrs = client.lstat(target)
    logger.info("重命名 %s -> %s", canonical, target)
    return {
        "path": canonical,
        "name": name_of(canonical),
        "new_path": target,
        "new_name": name,
        "type": attrs.type,
        "size": attrs.size,
        "mtime": attrs.mtime,
    }


# --------------------------------------------------------------------- 新建


def _directory_target(session: RemoteSession, raw_dir: str, *, action: str) -> str:
    """把「目标目录」解析成 REALPATH，并确认它真的是目录。

    写入发生在目录内部，所以这里可以整条路径交给 realpath（与删除、重命名
    只解析父目录不同）：用户选中的是「往哪个目录里写」，不是某个条目本身。
    """
    validated = validate_remote_path(raw_dir)
    client = session.client
    resolved = client.realpath(validated)
    attrs = client.stat(resolved)
    if not attrs.is_dir:
        raise ValidationError(
            f"{action}的目标不是目录。",
            detail=f"{resolved}（{attrs.type}）。",
            extra={"path": resolved},
        )
    return resolved


def _already_exists(target: str, attrs) -> ValidationError:
    """「同名条目已存在」的统一说法：拒绝创建，绝不静默覆盖。"""
    return ValidationError(
        "同名条目已经存在。",
        detail=f"{target}（{attrs.type}）。请换一个名称。",
        extra={"path": target, "exists": True, "type": attrs.type},
    )


def create_entry(session: RemoteSession, raw_directory: str, name: str, *, kind: str) -> dict:
    """在远端目录里新建一个空文件或一个空目录。

    排他语义（v0.1.3 §4）：
    - 文件走 `CREAT|EXCL`，已存在由服务端原子的拒绝，检查与创建之间没有窗口；
    - 目录走 `MKDIR`，POSIX 语义本身就不覆盖已存在的路径。
    前面的 `lstat` 只负责把失败翻译成「同名条目已经存在」，不承担互斥职责。
    """
    if kind not in ("file", "directory"):
        raise ValidationError("kind 只允许 file 或 directory。", detail=str(kind))
    require_write_permission(session, "新建文件" if kind == "file" else "新建文件夹")
    valid_name = validate_remote_name(name)
    client = session.client
    directory = _directory_target(session, raw_directory, action="新建")
    target = join_remote_path(directory, valid_name)
    existing = _exists(client, target)
    if existing is not None:
        raise _already_exists(target, existing)

    if kind == "directory":
        try:
            client.mkdir(target, 0o755)
        except (PathNotFound, PermissionDenied, NotConnected):
            raise
        except AwfmError:
            existing = _exists(client, target)
            if existing is not None:
                raise _already_exists(target, existing)
            raise
    else:
        handle = None
        try:
            handle = client.open(
                target,
                proto.SSH_FXF_WRITE | proto.SSH_FXF_CREAT | proto.SSH_FXF_EXCL,
                0o644,
            )
        except (PathNotFound, PermissionDenied, NotConnected):
            raise
        except AwfmError:
            existing = _exists(client, target)
            if existing is not None:
                raise _already_exists(target, existing)
            raise
        finally:
            if handle is not None:
                client.close(handle)

    attrs = client.lstat(target)
    logger.info("新建%s %s", "文件" if kind == "file" else "文件夹", target)
    return {
        "path": target,
        "name": valid_name,
        "kind": kind,
        "type": attrs.type,
        "size": attrs.size,
        "mtime": attrs.mtime,
    }


# --------------------------------------------------------------------- 复制与移动


def _batch_sources(
    session: RemoteSession,
    raw_paths: Any,
    raw_directory: str,
    *,
    action: str,
) -> tuple[str, list[tuple[str, str]]]:
    """把「一串源路径 + 一个目标目录」规范成 [(源, 目标)]，并挡掉自指与越界。

    源条目按「父目录 REALPATH + 原样最后一段」规范化（与删除、压缩一致）：
    移动一个符号链接要移动链接本身，不能解析成它指向的东西。
    """
    if not isinstance(raw_paths, (list, tuple)) or not raw_paths:
        raise ValidationError(f"请至少选择一个要{action}的条目。")
    if len(raw_paths) > MAX_COPY_ENTRIES:
        raise ValidationError(
            f"一次{action}的条目太多。",
            detail=f"最多 {MAX_COPY_ENTRIES} 项，收到 {len(raw_paths)} 项。",
        )
    client = session.client
    directory = _directory_target(session, raw_directory, action=action)
    pairs: list[tuple[str, str]] = []
    for raw in raw_paths:
        if not isinstance(raw, str) or not raw:
            raise ValidationError(f"要{action}的路径必须是字符串。")
        canonical = _canonical_entry_path(session, raw)
        if canonical == "/":
            raise ValidationError(f"不能{action}根目录。")
        client.lstat(canonical)  # 源不存在时按 path_not_found 上报
        target = join_remote_path(directory, name_of(canonical))
        if target == canonical:
            raise ValidationError(f"源和目标在同一个位置，不需要{action}。", detail=canonical)
        if target.startswith(canonical + "/"):
            raise ValidationError(
                f"不能把目录{action}到它自己里面。",
                detail=f"{canonical} -> {directory}",
            )
        pairs.append((canonical, target))
    return directory, pairs


def _target_conflicts(client, pairs: list[tuple[str, str]]) -> list[dict]:
    found = []
    for source, target in pairs:
        attrs = _exists(client, target)
        if attrs is not None:
            found.append({"source": source, "target": target, "type": attrs.type})
    return found


def _describe_conflicts(conflicts: list[dict]) -> str:
    names = [item["source"].rpartition("/")[2] for item in conflicts]
    return "、".join(names)


def _copy_tree(client, source: str, target: str, stats: dict, *, depth: int) -> None:
    """把 source 复制到 target（目录则递归）。

    符号链接与设备文件跳过并报告：SFTP v3 没有创建链接的请求，
    假装复制成功会在目标端留下一个空文件，那比明确说「没复制」更糟。
    """
    attrs = client.lstat(source)
    stats["entries"] += 1
    if stats["entries"] > MAX_COPY_ENTRIES:
        raise ValidationError(
            "要复制的条目太多，已停止。",
            detail=f"超过 {MAX_COPY_ENTRIES} 个条目。请分几次复制，或先整理源目录。",
            extra={"path": source, "limit": MAX_COPY_ENTRIES},
        )
    if attrs.is_link:
        stats["skipped"].append(
            {
                "name": name_of(source),
                "path": source,
                "type": "symlink",
                "code": "symlink_skipped",
                "message": "符号链接不在复制范围内，已跳过。",
            }
        )
        return
    if attrs.is_dir:
        mode = (attrs.permissions or 0o755) & 0o777
        existing = _exists(client, target)
        if existing is None:
            client.mkdir(target, mode)
            stats["directories"] += 1
        elif not existing.is_dir:
            raise ValidationError(
                "目标位置有同名文件，无法把目录复制进去。",
                detail=f"{target}（{existing.type}）。请先处理掉它。",
                extra={"path": target, "exists": True, "type": existing.type},
            )
        if depth >= MAX_TREE_DEPTH:
            raise ValidationError(
                "目录层级过深，已停止复制。",
                detail=f"{source} 超过 {MAX_TREE_DEPTH} 层。",
                extra={"path": source},
            )
        for child in client.listdir(source):
            _copy_tree(
                client,
                join_remote_path(source, child.filename),
                join_remote_path(target, child.filename),
                stats,
                depth=depth + 1,
            )
        return
    if attrs.type != "file":
        stats["skipped"].append(
            {
                "name": name_of(source),
                "path": source,
                "type": attrs.type,
                "code": "unsupported_type",
                "message": "只复制普通文件、目录，这个条目已跳过。",
            }
        )
        return
    size = attrs.size or 0
    stats["bytes"] += size
    if stats["bytes"] > MAX_COPY_BYTES:
        raise ValidationError(
            "要复制的内容太大，已停止。",
            detail=f"累计超过 {MAX_COPY_BYTES} 字节。",
            extra={"path": source, "limit": MAX_COPY_BYTES},
        )
    client.upload_stream(
        target,
        client.download_chunks(source),
        expected_size=size,
        mode=(attrs.permissions or 0o644) & 0o777,
    )
    stats["files"] += 1


def copy_entries(
    session: RemoteSession,
    raw_paths: Any,
    raw_directory: str,
    *,
    overwrite: bool = False,
) -> dict:
    """把若干条目复制到目标目录里（同名即拒绝，除非显式 overwrite）。"""
    require_write_permission(session, "复制")
    client = session.client
    directory, pairs = _batch_sources(session, raw_paths, raw_directory, action="复制")
    conflicts = _target_conflicts(client, pairs)
    if conflicts and not overwrite:
        raise ValidationError(
            "目标位置已经有同名条目。",
            detail=f"{_describe_conflicts(conflicts)}。请换一个目录，或确认覆盖。",
            extra={"conflicts": conflicts, "exists": True},
        )
    stats: dict[str, Any] = {"entries": 0, "files": 0, "directories": 0, "bytes": 0, "skipped": []}
    copied = []
    for source, target in pairs:
        _copy_tree(client, source, target, stats, depth=0)
        copied.append({"source": source, "path": target, "name": name_of(target)})
    logger.info("复制 %d 项 -> %s", len(copied), directory)
    return {
        "destination": directory,
        "copied": copied,
        "files": stats["files"],
        "directories": stats["directories"],
        "bytes": stats["bytes"],
        "skipped": stats["skipped"],
        "overwrite": bool(overwrite),
    }


def move_entries(session: RemoteSession, raw_paths: Any, raw_directory: str) -> dict:
    """把若干条目移动到目标目录里。

    移动不做「先复制再删除」：SFTP 的 RENAME 在同一个服务端内完成，
    中途失败不会出现「源没了、目标只有一半」的状态。目标已存在一律拒绝
    （SFTP v3 的 RENAME 本来也不覆盖），不提供覆盖选项。
    """
    require_write_permission(session, "移动")
    client = session.client
    directory, pairs = _batch_sources(session, raw_paths, raw_directory, action="移动")
    conflicts = _target_conflicts(client, pairs)
    if conflicts:
        raise ValidationError(
            "目标位置已经有同名条目。",
            detail=f"{_describe_conflicts(conflicts)}。请换一个目录，或先处理掉同名条目。",
            extra={"conflicts": conflicts, "exists": True},
        )
    moved = []
    for source, target in pairs:
        try:
            client.rename(source, target)
        except AwfmError as exc:
            # 逐项记账：前面的已经移走了，界面要说清「哪几项成了、哪一项没成」。
            exc.extra = dict(
                exc.extra or {},
                done=[item["path"] for item in moved],
                failed=source,
            )
            raise
        moved.append({"source": source, "path": target, "name": name_of(target)})
    logger.info("移动 %d 项 -> %s", len(moved), directory)
    return {"destination": directory, "moved": moved, "count": len(moved)}


# --------------------------------------------------------------------- 删除


def _check_delete_budget(removed: dict, path: str) -> None:
    total = removed["files"] + removed["directories"]
    if total > MAX_DELETE_ENTRIES:
        raise ValidationError(
            "要删除的条目太多，已经停下。",
            detail=(
                f"已删除 {total} 个条目，单次上限 {MAX_DELETE_ENTRIES}。"
                "远端目录里剩下的内容需要再确认一次才会继续删除。"
            ),
            extra={
                "path": path,
                "limit": MAX_DELETE_ENTRIES,
                "removed": dict(removed),
            },
        )


def _remove_tree(client, path: str, removed: dict, *, depth: int) -> None:
    """深度优先删掉一棵子树，不跟随符号链接。"""
    if depth > MAX_TREE_DEPTH:
        raise ValidationError(
            "目录层级过深，已停止删除。",
            detail=f"{path} 超过 {MAX_TREE_DEPTH} 层。",
            extra={"path": path, "removed": dict(removed)},
        )
    for child_entry in client.listdir(path):
        child = join_remote_path(path, child_entry.filename)
        # READDIR 返回的属性是 lstat 语义：符号链接不会被当成目录，于是不会被跟随。
        if child_entry.attrs.is_dir:
            _remove_tree(client, child, removed, depth=depth + 1)
        else:
            client.remove(child)
            removed["files"] += 1
        _check_delete_budget(removed, child)
    client.rmdir(path)
    removed["directories"] += 1


def delete_entry(session: RemoteSession, raw_path: str, *, recursive: bool = False) -> dict:
    """删除一个文件、符号链接或目录。

    Args:
        recursive: 目录非空时是否连同内容一起删除。默认 False ——
            递归删除是不可撤销的，必须由调用方显式要求（界面会二次确认）。
    """
    require_write_permission(session, "删除")
    canonical = _canonical_entry_path(session, raw_path)
    if canonical == "/":
        raise ValidationError("不能删除根目录。")
    client = session.client
    attrs = client.lstat(canonical)
    removed = {"files": 0, "directories": 0}
    if attrs.is_dir:
        children = client.listdir(canonical)
        if children and not recursive:
            raise ValidationError(
                "目录不是空的，需要显式确认递归删除。",
                detail=f"{canonical} 里有 {len(children)} 个条目。",
                extra={"path": canonical, "entries": len(children), "recursive": False},
            )
        if recursive:
            _remove_tree(client, canonical, removed, depth=0)
        else:
            client.rmdir(canonical)
            removed["directories"] = 1
    else:
        client.remove(canonical)
        removed["files"] = 1
    logger.info("删除 %s（文件 %d，目录 %d）", canonical, removed["files"], removed["directories"])
    return {
        "path": canonical,
        "name": name_of(canonical),
        "type": attrs.type,
        "recursive": bool(recursive),
        "removed": removed,
        "entries": removed["files"] + removed["directories"],
    }


def delete_entries(session: RemoteSession, raw_paths: Any, *, recursive: bool = False) -> dict:
    """批量删除。

    逐项删除、逐项记账：某一项失败时把已删掉的清单留在错误的 extra 里再抛出，
    界面才能如实说「这 3 个删了、第 4 个没删掉」，而不是含糊地说「删除失败」。
    递归确认（recursive）由调用方显式给出，和单项删除同一条纪律。
    """
    if not isinstance(raw_paths, (list, tuple)) or not raw_paths:
        raise ValidationError("请至少选择一个要删除的条目。")
    if len(raw_paths) > MAX_DELETE_ENTRIES:
        raise ValidationError(
            "一次删除的条目太多。",
            detail=f"最多 {MAX_DELETE_ENTRIES} 项，收到 {len(raw_paths)} 项。",
        )
    results = []
    for raw in raw_paths:
        if not isinstance(raw, str) or not raw:
            raise ValidationError("要删除的路径必须是字符串。")
        try:
            results.append(delete_entry(session, raw, recursive=recursive))
        except AwfmError as exc:
            exc.extra = dict(
                exc.extra or {},
                done=[item["path"] for item in results],
                failed=raw,
            )
            raise
    files = sum(item["removed"]["files"] for item in results)
    directories = sum(item["removed"]["directories"] for item in results)
    return {
        "deleted": results,
        "count": len(results),
        "files": files,
        "directories": directories,
        "entries": files + directories,
        "recursive": bool(recursive),
    }


# --------------------------------------------------------------------- 压缩


def _archive_name(name: str) -> str:
    """压缩包的名字：用户没指定就用源条目名，并补上 .tar.gz。"""
    lowered = name.lower()
    if lowered.endswith(ARCHIVE_SUFFIXES):
        return name
    return name + ".tar.gz"


def _add_to_tar(client, tar, path: str, arcname: str, stats: dict, *, depth: int) -> None:
    """把一个条目（必要时递归）写进 tar 流。"""
    attrs = client.lstat(path)
    stats["entries"] += 1
    if stats["entries"] > MAX_ARCHIVE_ENTRIES:
        raise ValidationError(
            "要打包的条目太多，已停止压缩。",
            detail=f"超过 {MAX_ARCHIVE_ENTRIES} 个条目。请分几次压缩，或先删掉不需要的内容。",
            extra={"path": path, "limit": MAX_ARCHIVE_ENTRIES},
        )
    info = tarfile.TarInfo(arcname)
    info.mode = (attrs.permissions or 0o644) & 0o7777
    info.mtime = attrs.mtime or 0
    info.uid = attrs.uid or 0
    info.gid = attrs.gid or 0

    if attrs.is_link:
        # 只记链接本身，不跟进去 —— 跟进去就可能把搜索根之外的东西打进包里。
        info.type = tarfile.SYMTYPE
        info.linkname = client.readlink(path)
        info.size = 0
        tar.addfile(info)
        return

    if attrs.is_dir:
        info.type = tarfile.DIRTYPE
        info.size = 0
        tar.addfile(info)
        if depth >= MAX_TREE_DEPTH:
            raise ValidationError(
                "目录层级过深，已停止压缩。",
                detail=f"{path} 超过 {MAX_TREE_DEPTH} 层。",
                extra={"path": path},
            )
        for child_entry in client.listdir(path):
            _add_to_tar(
                client,
                tar,
                join_remote_path(path, child_entry.filename),
                arcname + "/" + child_entry.filename,
                stats,
                depth=depth + 1,
            )
        return

    if attrs.type != "file":
        stats["skipped"].append({
            "name": name_of(path),
            "path": path,
            "type": attrs.type,
            "code": "unsupported_type",
            "message": "只打包普通文件、目录与符号链接，这个条目已跳过。",
        })
        return

    size = attrs.size or 0
    stats["bytes"] += size
    if stats["bytes"] > MAX_ARCHIVE_BYTES:
        raise ValidationError(
            "要压缩的内容太大，已停止。",
            detail=f"累计超过 {MAX_ARCHIVE_BYTES} 字节。",
            extra={"path": path, "limit": MAX_ARCHIVE_BYTES},
        )
    info.type = tarfile.REGTYPE
    info.size = size
    if size == 0:
        tar.addfile(info)
        return
    with client.open_read(path) as handle:
        tar.addfile(info, RandomReader(client, handle, size=size))


def compress_entries(
    session: RemoteSession,
    raw_paths: Any,
    *,
    name: str = "",
    into: str = "",
) -> dict:
    """把若干远端条目打包成一个 .tar.gz。

    Args:
        raw_paths: 要打包的条目（至少一个）。
        name: 压缩包名字；留空时单个条目用条目名、多个条目用 archive。
        into: 压缩包放在哪个目录；留空时放在第一个源条目所在的目录。

    先写成临时名，成功后再改名过来：中途失败（断线、超上限）不会在远端
    留下一个看起来正常、其实不完整的压缩包。
    """
    require_write_permission(session, "压缩")
    if not isinstance(raw_paths, (list, tuple)) or not raw_paths:
        raise ValidationError("请至少选择一个要压缩的条目。")
    client = session.client
    members: list[tuple[str, str]] = []
    for raw in raw_paths:
        if not isinstance(raw, str) or not raw:
            raise ValidationError("要压缩的路径必须是字符串。")
        canonical = _canonical_entry_path(session, raw)
        if canonical == "/":
            raise ValidationError("不能压缩根目录。", detail="请进入某个目录，再选择要压缩的条目。")
        client.lstat(canonical)
        members.append((canonical, name_of(canonical)))
    canonical = members[0][0]
    base = members[0][1] if len(members) == 1 else "archive"
    archive_name = _archive_name(validate_remote_name(name) if name else base)
    parent = _directory_target(session, into, action="压缩") if into else (
        parent_remote_path(canonical) or "/"
    )
    target = join_remote_path(parent, archive_name)
    if _exists(client, target) is not None:
        raise ValidationError(
            "目标位置已经存在同名压缩包。",
            detail=f"{target}。请换一个名称，或先删掉它。",
            extra={"path": target, "exists": True},
        )

    temp = target + PART_SUFFIX + uuid.uuid4().hex[:8]
    stats: dict[str, Any] = {"entries": 0, "bytes": 0, "skipped": []}
    try:
        with client.open_write(temp, mode=0o644) as handle:
            writer = ChunkWriter(client, handle)
            # mtime=0：同一个目录压两次得到同样的字节，便于核对与去重。
            with gzip.GzipFile(fileobj=writer, mode="wb", mtime=0) as gz:
                with tarfile.open(fileobj=gz, mode="w|", format=tarfile.GNU_FORMAT) as tar:
                    for member, arcname in members:
                        _add_to_tar(client, tar, member, arcname, stats, depth=0)
        client.rename(temp, target)
        temp = ""
    finally:
        if temp:
            try:
                client.remove(temp)
            except Exception:
                logger.warning("清理未完成的压缩临时文件失败：%s", temp)

    attrs = client.lstat(target)
    logger.info("压缩完成 %s -> %s（%d 个条目）", "、".join(item[0] for item in members), target, stats["entries"])
    return {
        "source": canonical,
        "sources": [item[0] for item in members],
        "path": target,
        "name": archive_name,
        "format": "tar.gz",
        "size": attrs.size,
        "mtime": attrs.mtime,
        "entries": stats["entries"],
        "bytes": stats["bytes"],
        "skipped": stats["skipped"],
    }


def compress_entry(session: RemoteSession, raw_path: str, *, name: str = "") -> dict:
    """兼容旧调用：压缩单个条目（放进它所在的目录）。"""
    return compress_entries(session, [raw_path], name=name)


# --------------------------------------------------------------------- 解压


def _member_target(destination: str, member_name: str) -> str:
    """把压缩包里的名字翻译成远端绝对路径，顺便挡掉目录穿越。

    压缩包里的名字是**外部输入**：一个 ../../etc/cron.d/x 的成员名足以让
    「解压」变成「往任意位置写文件」。这里只做纯词法检查，不做 REALPATH ——
    目标目录还不存在的东西没法 REALPATH，而拒绝越界只需要词法判断。
    """
    raw = member_name.replace("\\", "/").strip()
    while raw.startswith("./"):
        raw = raw[2:]
    if "\x00" in raw:
        raise ValidationError("压缩包里的条目名含 NUL 字符，拒绝解压。")
    if raw.startswith("/"):
        raise ValidationError("压缩包里的条目名是绝对路径，拒绝解压。", detail=member_name)
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if not parts:
        return ""
    if ".." in parts:
        raise ValidationError("压缩包里的条目名含 ..，拒绝解压。", detail=member_name)
    for part in parts:
        validate_remote_name(part)
    joined = "/".join(parts)
    if destination == "/":
        return "/" + joined
    return destination.rstrip("/") + "/" + joined


def _count_entry(stats: dict, name: str) -> None:
    stats["entries"] += 1
    if stats["entries"] > MAX_EXTRACT_ENTRIES:
        raise _ExtractStop(f"已达到条目上限 {MAX_EXTRACT_ENTRIES}，停止解压。")


def _reserve_bytes(stats: dict, size: int, name: str) -> None:
    stats["bytes"] += size
    if stats["bytes"] > MAX_EXTRACT_BYTES:
        raise _ExtractStop(f"解出的内容超过 {MAX_EXTRACT_BYTES} 字节上限，停止解压。")


def _ensure_directory(client, target: str, stats: dict) -> None:
    existing = _exists(client, target)
    if existing is None:
        client.mkdir(target, 0o755)
        stats["directories"] += 1
        return
    if not existing.is_dir:
        raise ValidationError(
            "压缩包里的目录与远端已有的文件同名。",
            detail=f"{target} 已存在，且不是目录。",
            extra={"path": target},
        )


def _ensure_parents(client, target: str, destination: str, stats: dict) -> None:
    """保证 target 的各级父目录存在（有些 zip 根本不写目录条目）。"""
    parent = parent_remote_path(target)
    if parent is None or parent == destination or parent == destination.rstrip("/"):
        return
    _ensure_parents(client, parent, destination, stats)
    _ensure_directory(client, parent, stats)


def _skip_existing(client, target: str, name: str, stats: dict, *, overwrite: bool) -> bool:
    """目标已存在时决定跳过还是覆盖。返回 True 表示这个成员要跳过。"""
    existing = _exists(client, target)
    if existing is None:
        return False
    if existing.is_dir:
        raise ValidationError(
            "压缩包里的文件与远端已有的目录同名。",
            detail=f"{target} 是一个目录，无法用文件覆盖。",
            extra={"path": target},
        )
    if overwrite:
        return False
    stats["existing"].append(name)
    return True


def _write_member(client, target: str, source, size: int, name: str, stats: dict, *, mode: int) -> None:
    """把一个成员的内容写成远端文件（临时名 + 改名，写完校验字节数）。"""
    temp = target + PART_SUFFIX + uuid.uuid4().hex[:8]
    written = 0
    try:
        with client.open_write(temp, mode=mode) as handle:
            writer = ChunkWriter(client, handle)
            while True:
                chunk = source.read(64 * 1024)
                if not chunk:
                    break
                writer.write(chunk)
                written += len(chunk)
        if size is not None and written != size:
            raise ProtocolError(
                "解压写出的字节数与压缩包记录不一致。",
                detail=f"{name}：压缩包记录 {size} 字节，实际写出 {written} 字节。",
            )
        # SFTP v3 的 RENAME 不覆盖已存在的目标，所以覆盖写要先删掉旧的。
        existing = _exists(client, target)
        if existing is not None and not existing.is_dir:
            client.remove(target)
        client.rename(temp, target)
        temp = ""
    finally:
        if temp:
            try:
                client.remove(temp)
            except Exception:
                logger.warning("清理未完成的解压临时文件失败：%s", temp)
    stats["files"] += 1


def _extract_tar_member(client, archive, member, destination: str, stats: dict, *, overwrite: bool) -> None:
    target = _member_target(destination, member.name)
    if not target:
        return
    if member.issym() or member.islnk():
        stats["skipped"].append({
            "name": member.name,
            "code": "symlink_skipped",
            "message": "符号链接与硬链接不在解压范围内，已跳过。",
        })
        return
    if member.isdir():
        _count_entry(stats, member.name)
        _ensure_parents(client, target, destination, stats)
        _ensure_directory(client, target, stats)
        return
    if not member.isfile():
        stats["skipped"].append({
            "name": member.name,
            "code": "unsupported_type",
            "message": "只解出普通文件与目录，这个条目已跳过。",
        })
        return
    _count_entry(stats, member.name)
    size = member.size or 0
    _reserve_bytes(stats, size, member.name)
    if _skip_existing(client, target, member.name, stats, overwrite=overwrite):
        return
    _ensure_parents(client, target, destination, stats)
    source = archive.extractfile(member)
    if source is None:
        raise ProtocolError("无法读取压缩包中的条目内容。", detail=member.name)
    with source:
        _write_member(
            client, target, source, size, member.name, stats, mode=(member.mode & 0o777) or 0o644
        )


def _extract_zip_member(client, archive, member, destination: str, stats: dict, *, overwrite: bool) -> None:
    target = _member_target(destination, member.filename)
    if not target:
        return
    kind = (member.external_attr >> 16) & 0o170000
    if kind == 0o120000:
        stats["skipped"].append({
            "name": member.filename,
            "code": "symlink_skipped",
            "message": "符号链接不在解压范围内，已跳过。",
        })
        return
    if member.is_dir():
        _count_entry(stats, member.filename)
        _ensure_parents(client, target, destination, stats)
        _ensure_directory(client, target, stats)
        return
    _count_entry(stats, member.filename)
    size = member.file_size or 0
    _reserve_bytes(stats, size, member.filename)
    if _skip_existing(client, target, member.filename, stats, overwrite=overwrite):
        return
    _ensure_parents(client, target, destination, stats)
    mode = ((member.external_attr >> 16) & 0o777) or 0o644
    with archive.open(member) as source:
        _write_member(client, target, source, size, member.filename, stats, mode=mode)


def extract_entry(
    session: RemoteSession,
    raw_path: str,
    *,
    into: str = "",
    overwrite: bool = False,
) -> dict:
    """把一个远端压缩包解到远端目录里。

    Args:
        into: 目标目录；留空表示压缩包自己所在的目录。目标必须已存在。
        overwrite: 目标文件已存在时是否覆盖。默认跳过并在响应里列出。
    """
    require_write_permission(session, "解压")
    canonical = resolve_path(session, raw_path)
    fmt = archive_format(canonical)
    if not fmt:
        raise ValidationError(
            "这个文件不是支持的压缩包。",
            detail=f"{canonical}。只支持 .tar.gz / .tgz / .tar / .zip。",
        )
    client = session.client
    attrs = client.stat(canonical)
    if attrs.is_dir:
        raise ValidationError("目录不能解压。", detail=canonical)
    if attrs.type != "file":
        raise ValidationError(
            "只有普通文件可以解压。", detail=f"{canonical} 的类型是 {attrs.type}。"
        )
    size = attrs.size or 0
    if size > MAX_EXTRACT_BYTES:
        raise ValidationError(
            "这个压缩包太大，无法解压。",
            detail=f"{size} 字节，上限 {MAX_EXTRACT_BYTES} 字节。",
            extra={"path": canonical, "size": size, "limit": MAX_EXTRACT_BYTES},
        )
    destination = resolve_path(session, into) if into else (parent_remote_path(canonical) or "/")
    try:
        destination_attrs = client.stat(destination)
    except PathNotFound:
        # 用户明确说了「解压到这里」，这里就把它建出来 —— 多数压缩工具也是这个行为
        # （解压到一个新目录），比回一句「目标不存在」更符合预期。
        # 只建最后一级：多级路径写错时应该报错，而不是默默造出一串空目录。
        client.mkdir(destination, 0o755)
    else:
        if not destination_attrs.is_dir:
            raise ValidationError("解压目标不是目录。", detail=destination)

    stats: dict[str, Any] = {
        "entries": 0,
        "files": 0,
        "directories": 0,
        "bytes": 0,
        "skipped": [],
        "existing": [],
        "stopped": None,
    }
    try:
        with client.open_read(canonical) as handle:
            reader = RandomReader(client, handle, size=size)
            if fmt == "zip":
                with zipfile.ZipFile(reader) as archive:
                    for member in archive.infolist():
                        _extract_zip_member(
                            client, archive, member, destination, stats, overwrite=overwrite
                        )
            else:
                mode = "r|gz" if fmt == "tar.gz" else "r|"
                with tarfile.open(fileobj=reader, mode=mode) as archive:
                    for member in archive:
                        _extract_tar_member(
                            client, archive, member, destination, stats, overwrite=overwrite
                        )
    except _ExtractStop as stop:
        stats["stopped"] = stop.reason
        logger.warning("解压被上限中断：%s（%s）", canonical, stop.reason)

    logger.info(
        "解压 %s -> %s（文件 %d，目录 %d%s）",
        canonical, destination, stats["files"], stats["directories"],
        "，被中断" if stats["stopped"] else "",
    )
    return {
        "path": canonical,
        "name": name_of(canonical),
        "format": fmt,
        "destination": destination,
        "entries": stats["entries"],
        "files": stats["files"],
        "directories": stats["directories"],
        "bytes": stats["bytes"],
        "skipped": stats["skipped"],
        "existing": stats["existing"],
        "stopped": stats["stopped"],
        "overwrite": bool(overwrite),
    }

def extract_entries(
    session: RemoteSession,
    raw_paths: Any,
    *,
    into: str = "",
    overwrite: bool = False,
) -> dict:
    """批量解压：逐个压缩包调用 extract_entry。

    单个压缩包时**原样返回那一份结果**（保持 v0.1.2 的响应形状不变），
    多个时才多一层 archives 汇总。
    """
    if not isinstance(raw_paths, (list, tuple)) or not raw_paths:
        raise ValidationError("请至少选择一个要解压的压缩包。")
    results = []
    for raw in raw_paths:
        if not isinstance(raw, str) or not raw:
            raise ValidationError("要解压的路径必须是字符串。")
        try:
            results.append(extract_entry(session, raw, into=into, overwrite=overwrite))
        except AwfmError as exc:
            # 已解开的包不回滚，但必须如实报告：哪些包成了、哪一包挡住了。
            exc.extra = dict(
                exc.extra or {},
                done=[item["path"] for item in results],
                failed=raw,
            )
            raise
    if len(results) == 1:
        return results[0]
    return {
        "archives": results,
        "count": len(results),
        "entries": sum(item["entries"] for item in results),
        "files": sum(item["files"] for item in results),
        "directories": sum(item["directories"] for item in results),
        "bytes": sum(item["bytes"] for item in results),
        "stopped": next((item["stopped"] for item in results if item["stopped"]), None),
    }



__all__ = [
    "ARCHIVE_SUFFIXES",
    "archive_format",
    "compress_entries",
    "compress_entry",
    "copy_entries",
    "create_entry",
    "delete_entries",
    "delete_entry",
    "extract_entries",
    "extract_entry",
    "move_entries",
    "name_of",
    "rename_entry",
]
