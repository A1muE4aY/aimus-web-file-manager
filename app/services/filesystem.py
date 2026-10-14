"""目录浏览与文件元数据。

## 路径怎么被规范化

一律先 `realpath` 再使用（`app/utils/paths.py` 的说明解释了为什么不在客户端做
词法折叠）。这样做的两个后果都是想要的：

1. 客户端看到的路径与目标机上真实存在的路径**完全一致**，
   不会出现「`/a/b/../c` 点进去之后面包屑和实际目录对不上」。
2. 符号链接按目标机的语义解析 —— 那才是用户用 shell 时看到的行为。

## 为什么列目录不解析符号链接目标

`/usr/bin` 这类目录里有几百个符号链接。每个 `readlink` 都是一次完整的
请求/响应往返，几百次串起来能让一次列目录慢到秒级。所以列表里只标出
「这是链接」，目标留给 `stat_path` 按需查询（用户点进去时才需要）。
"""

from __future__ import annotations

import logging

from app.core.errors import AwfmError, Unauthorized, ValidationError
from app.models.entry import FileEntry
from app.services.session import RemoteSession
from app.utils.paths import (
    join_remote_path,
    normalize_unicode,
    parent_remote_path,
    validate_remote_name,
    validate_remote_path,
)

logger = logging.getLogger(__name__)

#: 文本预览的默认上限。超过这个大小就不做预览 ——
#: 把一个 2 GB 的日志文件读进内存再把浏览器卡死，对谁都没有好处。
DEFAULT_PREVIEW_BYTES = 256 * 1024

#: 目录列表的条目上限。超过就截断并**明确告知**（见 `list_directory` 的返回）。
MAX_LIST_ENTRIES = 5000

#: 类型排序权重：目录在前，然后是普通文件，最后是其余（设备、套接字等）。
_TYPE_ORDER = {"directory": 0, "symlink": 1, "file": 2}


def resolve_path(session: RemoteSession, raw_path: str) -> str:
    """校验并规范化一个远程路径。返回服务端给出的规范形式。"""
    path = validate_remote_path(raw_path)
    return session.client.realpath(path)


def list_directory(session: RemoteSession, raw_path: str) -> dict:
    """列出一个目录。

    Returns:
        `{"path": 规范路径, "parent": 上级或 None, "entries": [...],
        "truncated": bool, "total": int}`
    """
    canonical = resolve_path(session, raw_path)
    client = session.client

    # 先确认它确实是个目录：对文件调用 OPENDIR 会得到一条语义模糊的失败，
    # 而这里可以给出「这是一个文件，不是目录」这种能直接指导用户的错误。
    attrs = client.stat(canonical)
    if not attrs.is_dir:
        raise ValidationError(
            "该路径不是一个目录。",
            detail=f"{canonical} 的类型是 {attrs.type}。",
        )

    raw_entries = client.listdir(canonical)

    entries: list[FileEntry] = []
    for item in raw_entries:
        full_path = join_remote_path(canonical, item.filename)
        entries.append(FileEntry.from_attrs(item.filename, full_path, item.attrs))

    # 先排序再截断：先截断的话，返回的是「服务端列举顺序里的前 N 个」，
    # 用户看到的就不再是「按名称排列的前 N 个」，目录列表会显得莫名其妙。
    entries.sort(key=_sort_key)
    total = len(entries)
    truncated = total > MAX_LIST_ENTRIES
    if truncated:
        entries = entries[:MAX_LIST_ENTRIES]

    return {
        "path": canonical,
        "parent": parent_remote_path(canonical),
        "entries": [entry.to_dict() for entry in entries],
        "truncated": truncated,
        "total": total,
    }


def stat_path(session: RemoteSession, raw_path: str, *, follow: bool = True) -> dict:
    """查询单个路径的元数据。

    Args:
        follow: 为 `False` 时不跟随符号链接（`lstat`），并且会额外读取链接目标。
    """
    path = validate_remote_path(raw_path)
    client = session.client
    if follow:
        canonical = client.realpath(path)
        attrs = client.stat(canonical)
        entry = FileEntry.from_attrs(_basename(canonical), canonical, attrs)
        return entry.to_dict()

    attrs = client.lstat(path)
    entry = FileEntry.from_attrs(_basename(path), path, attrs)
    if attrs.is_link:
        try:
            entry.link_target = client.readlink(path)
        except AwfmError:
            # 读不到链接目标不是致命错误：目标机上可能存在无法 readlink 的对象。
            # 保留「这是一个链接」这个事实即可，不因此让整个请求失败。
            entry.link_target = None
        if entry.link_target is not None:
            try:
                client.stat(path)
                entry.link_broken = False
            except AwfmError:
                # 断链：指向的目标不存在。文件管理器必须能表达这个状态 ——
                # 断链在 /etc 与 /usr/lib 里非常常见。
                entry.link_broken = True
    return entry.to_dict()


def read_text_preview(
    session: RemoteSession, raw_path: str, *, max_bytes: int = DEFAULT_PREVIEW_BYTES
) -> dict:
    """读取文本文件的前若干字节用于预览（P1 功能）。

    **不是「打开文件」**，规划文档 §3.2 明确首版不做在线编辑器。
    这里只做只读预览，且有硬上限。
    """
    canonical = resolve_path(session, raw_path)
    client = session.client
    attrs = client.stat(canonical)
    if attrs.is_dir:
        raise ValidationError("目录不能作为文本预览。", detail=canonical)

    size = attrs.size or 0
    limit = min(max_bytes, size) if size else max_bytes
    chunks: list[bytes] = []
    read = 0
    with client.open_read(canonical) as handle:
        while read < limit:
            piece = client.read_chunk(handle, read, min(65536, limit - read))
            if not piece:
                break
            chunks.append(piece)
            read += len(piece)
    raw = b"".join(chunks)
    if b"\x00" in raw:
        raise ValidationError(
            "该文件看起来是二进制文件，无法作为文本预览。",
            detail=f"{canonical}（前 {len(raw)} 字节中含 NUL 字节）",
        )
    try:
        text = raw.decode("utf-8")
        encoding = "utf-8"
    except UnicodeDecodeError:
        # 回退到 latin-1 而不是 errors="replace"：替换会产生大量 U+FFFD，
        # 让用户以为文件本身损坏了。latin-1 至少是双射的，能原样还原字节。
        text = raw.decode("latin-1")
        encoding = "latin-1"
    return {
        "path": canonical,
        "text": text,
        "encoding": encoding,
        "truncated": size > len(raw),
        "bytes_read": len(raw),
        "size": size,
    }


def require_write_permission(session: RemoteSession, what: str) -> None:
    """写操作的门禁。

    规划文档 §3.2 要求建目录/重命名/删除这类高风险操作在只读浏览稳定后单独设计，
    并加二次确认。这里是最内层的一道：即使上层漏了，未开启 `allow_write` 的连接
    依然写不动。
    """
    if not session.connection.allow_write:
        raise Unauthorized(
            f"该连接未开启写权限，无法{what}。",
            detail="请在连接配置中显式勾选「允许写操作」后重试。",
            extra={"connection_id": session.connection.id},
        )


def _sort_key(entry: FileEntry):
    """目录优先，然后按名称。用 `normalize_unicode` 做比较键，
    让「é」的两种 Unicode 表示排在一起（它们在文件系统里是两个不同的名字）。"""
    return (_TYPE_ORDER.get(entry.type, 3), normalize_unicode(entry.name).casefold(), entry.name)


def _basename(path: str) -> str:
    if path == "/":
        return "/"
    return path.rstrip("/").rpartition("/")[2] or "/"


__all__ = [
    "DEFAULT_PREVIEW_BYTES",
    "MAX_LIST_ENTRIES",
    "list_directory",
    "read_text_preview",
    "require_write_permission",
    "resolve_path",
    "stat_path",
    "validate_remote_name",
]
