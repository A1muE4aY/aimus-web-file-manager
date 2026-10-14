"""上传与下载（流式，决策 D-007）。

## 为什么两端都不整份入内存

下载走 `SftpClient.download_chunks` 生成器，每 64 KiB 往 HTTP 响应写一次；
上传从请求体按 64 KiB 读出、直接写进 SFTP 写句柄。
整个过程中内存里最多只有一个块 —— 传一个 8 GB 的镜像时，进程占用不会变。

## 新建文件用「临时名 + 改名」

直接往目标名写，中途断线（拔网线、目标机重启、用户关浏览器）会**留下一个半截文件**，
而它看起来和真文件没有区别。所以新建走：写 `<名字>.awfm-part-<随机>` → `RENAME` 到目标名。
SFTP v3 的 `RENAME` 在目标已存在时会失败，这恰好保证了我们不会覆盖任何东西。

## 覆盖已存在文件是**另一条路径**

SFTP v3 的 `RENAME` 不能替换已存在的目标，所以覆盖只能直接写（`TRUNC`）。
代价是：覆盖过程中断会留下一个被截断的文件。这是这一版接受的取舍，
并且覆盖**必须由调用方显式声明**（`overwrite=True`），不是默认行为。
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Iterable, Iterator

from app.core.errors import PayloadTooLarge, RemoteError, ValidationError
from app.services.filesystem import resolve_path, require_write_permission
from app.services.session import RemoteSession
from app.utils.paths import (
    encode_content_disposition,
    join_remote_path,
    validate_remote_name,
)

logger = logging.getLogger(__name__)

#: 上传时使用的临时文件名后缀。
PART_SUFFIX = ".awfm-part-"


def prepare_download(session: RemoteSession, raw_path: str, *, max_bytes: int = 0) -> dict:
    """校验并准备一次下载。

    Args:
        max_bytes: 大小上限，0 表示不限制。

    Returns:
        含 `path` / `name` / `size` / `content_disposition` / `chunks` 的字典。
        `chunks` 是一个**惰性**生成器工厂 —— 在真正开始写响应体之前不碰文件。
    """
    canonical = resolve_path(session, raw_path)
    client = session.client
    attrs = client.stat(canonical)
    if attrs.is_dir:
        raise ValidationError(
            "目录不能直接下载。",
            detail=f"{canonical}。如需打包下载，请使用压缩功能（P2）。",
        )
    if not attrs.is_link and attrs.type != "file":
        raise ValidationError(
            "只有普通文件可以被下载。",
            detail=f"{canonical} 的类型是 {attrs.type}。",
        )
    size = attrs.size or 0
    if max_bytes and size > max_bytes:
        raise PayloadTooLarge(
            "该文件超过了配置的下载大小上限。",
            detail=f"文件 {size} 字节，上限 {max_bytes} 字节（security.max_download_bytes）。",
            extra={"path": canonical, "size": size, "limit": max_bytes},
        )
    name = canonical.rstrip("/").rpartition("/")[2] or "download"
    return {
        "path": canonical,
        "name": name,
        "size": size,
        "content_disposition": encode_content_disposition(name),
        "chunks": lambda: client.download_chunks(canonical),
    }


def _read_exact(rfile, length: int, chunk_size: int = 65536) -> Iterator[bytes]:
    """从请求体精确读出 `length` 字节。少了就是客户端提前断开。

    不用 `rfile.read(length)` 一次读完：那会把整个上传放进内存，
    正是 D-007 要避免的事。
    """
    remaining = length
    while remaining > 0:
        piece = rfile.read(min(chunk_size, remaining))
        if not piece:
            raise ValidationError(
                "上传数据不完整：请求提前结束。",
                detail=f"声明 {length} 字节，实际只收到 {length - remaining} 字节。",
            )
        remaining -= len(piece)
        yield piece


def receive_upload(
    session: RemoteSession,
    raw_directory: str,
    filename: str,
    rfile,
    *,
    content_length: int,
    max_bytes: int = 0,
    overwrite: bool = False,
    mode: int = 0o644,
) -> dict:
    """把请求体流式写入远端目录。返回结果描述。

    Args:
        rfile: 请求体的二进制流（`self.rfile`）。
        content_length: 请求声明的字节数；必须 > 0。
        max_bytes: 上限，0 表示不限制。
        overwrite: 目标已存在时是否允许覆盖。**默认不允许** ——
            覆盖是不可撤销的，规划文档 §3.2 把它列为高风险操作。
    """
    require_write_permission(session, "上传文件")

    name = validate_remote_name(filename)
    if PART_SUFFIX in name:
        # 否则用户可以直接上传一个「临时文件」去干扰别人的上传。
        raise ValidationError(f"文件名不能包含 {PART_SUFFIX}。")
    if content_length <= 0:
        raise ValidationError(
            "上传需要 Content-Length，且不能为 0。",
            detail="本服务不支持分块传输编码（chunked），请让客户端提供 Content-Length。",
        )
    if max_bytes and content_length > max_bytes:
        raise PayloadTooLarge(
            "上传的文件超过了配置的大小上限。",
            detail=f"声明 {content_length} 字节，上限 {max_bytes} 字节（security.max_upload_bytes）。",
            extra={"limit": max_bytes},
        )

    directory = resolve_path(session, raw_directory)
    client = session.client
    target = join_remote_path(directory, name)

    exists = True
    try:
        existing = client.stat(target)
        if existing.is_dir:
            raise ValidationError("同名目录已存在，无法上传文件。", detail=target)
    except Exception as exc:
        from app.core.errors import PathNotFound

        if isinstance(exc, PathNotFound):
            exists = False
        else:
            raise
    if exists and not overwrite:
        raise ValidationError(
            "目标位置已存在同名文件。",
            detail=f"{target}。如需覆盖，请在界面上显式确认「覆盖」。",
            extra={"path": target, "exists": True},
        )

    written = 0
    temp_path = ""
    if exists:
        # 覆盖：只能直接写（v3 的 RENAME 不能替换已存在目标）。
        written = client.upload_stream(
            target, _read_exact(rfile, content_length), expected_size=content_length, mode=mode
        )
    else:
        temp_path = target + PART_SUFFIX + uuid.uuid4().hex[:8]
        try:
            written = client.upload_stream(
                temp_path, _read_exact(rfile, content_length), expected_size=content_length, mode=mode
            )
            client.rename(temp_path, target)
            temp_path = ""
        finally:
            if temp_path:
                # 失败时清掉半截的临时文件。删不掉也无所谓 —— 它的名字里带 .awfm-part-
                # 与随机后缀，不会与用户的文件混淆，且下次上传不会复用。
                try:
                    client.remove(temp_path)
                except Exception:
                    logger.warning("清理未完成的上传临时文件失败：%s", temp_path)
    logger.info("上传完成 %s（%d 字节，覆盖=%s）", target, written, exists)
    return {"path": target, "name": name, "size": written, "overwritten": exists}


def check_upload_target(session: RemoteSession, raw_directory: str, filename: str) -> dict:
    """上传前的预检：目标是否已存在。界面用它决定要不要弹「确认覆盖」。"""
    name = validate_remote_name(filename)
    directory = resolve_path(session, raw_directory)
    target = join_remote_path(directory, name)
    client = session.client
    try:
        attrs = client.stat(target)
    except Exception as exc:
        from app.core.errors import PathNotFound

        if isinstance(exc, PathNotFound):
            return {"path": target, "exists": False, "type": None, "size": None, "mtime": None}
        raise
    return {
        "path": target,
        "exists": True,
        "type": attrs.type,
        "size": attrs.size,
        "mtime": attrs.mtime,
    }


def _unused(_: Iterable) -> None:  # pragma: no cover
    """占位，保持 import 稳定性。"""
