"""SFTP v3 协议编解码（纯标准库）。

依据：draft-ietf-secsh-filexfer-02（SFTP 协议版本 3）。选 v3 而不是 v4/v5/v6 的理由：
v3 是 OpenSSH 的 `sftp-server` 稳定支持的版本，也是所有客户端的最大公约数。

## 帧格式

    uint32  length      -- 长度包含 type 字节，不包含 length 字段自身
    byte    type
    byte[]  payload

## 两个必须钉死的点（阶段 02 SPIKE 实测踩过）

**1. 服务端响应包的第一个字段是请求 id。**
初版实现漏读 id，导致 `REALPATH`/`STAT` 全部解析错位，且错得很隐蔽（字段还在，
只是整体偏移了 4 字节）。见 `parse_response()`。

**2. `MKDIR`/`SETSTAT` 的属性字段是完整 ATTRS 结构，不是裸 uint32。**
发错会让 `sftp-server` 直接 `fatal()` 退出，客户端只看到一个「管道 EOF」，
错误现象与真实原因相距极远。见 `encode_attrs_permissions()`。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterator

from app.core.errors import ProtocolError

# --------------------------------------------------------------------------
# 帧类型
# --------------------------------------------------------------------------

SSH_FXP_INIT = 1
SSH_FXP_VERSION = 2
SSH_FXP_OPEN = 3
SSH_FXP_CLOSE = 4
SSH_FXP_READ = 5
SSH_FXP_WRITE = 6
SSH_FXP_LSTAT = 7
SSH_FXP_FSTAT = 8
SSH_FXP_SETSTAT = 9
SSH_FXP_FSETSTAT = 10
SSH_FXP_OPENDIR = 11
SSH_FXP_READDIR = 12
SSH_FXP_REMOVE = 13
SSH_FXP_MKDIR = 14
SSH_FXP_RMDIR = 15
SSH_FXP_REALPATH = 16
SSH_FXP_STAT = 17
SSH_FXP_RENAME = 18
SSH_FXP_READLINK = 19
SSH_FXP_SYMLINK = 20

SSH_FXP_NAMES: dict[int, str] = {
    SSH_FXP_INIT: "INIT", SSH_FXP_VERSION: "VERSION", SSH_FXP_OPEN: "OPEN",
    SSH_FXP_CLOSE: "CLOSE", SSH_FXP_READ: "READ", SSH_FXP_WRITE: "WRITE",
    SSH_FXP_LSTAT: "LSTAT", SSH_FXP_FSTAT: "FSTAT", SSH_FXP_SETSTAT: "SETSTAT",
    SSH_FXP_FSETSTAT: "FSETSTAT", SSH_FXP_OPENDIR: "OPENDIR", SSH_FXP_READDIR: "READDIR",
    SSH_FXP_REMOVE: "REMOVE", SSH_FXP_MKDIR: "MKDIR", SSH_FXP_RMDIR: "RMDIR",
    SSH_FXP_REALPATH: "REALPATH", SSH_FXP_STAT: "STAT", SSH_FXP_RENAME: "RENAME",
    SSH_FXP_READLINK: "READLINK", SSH_FXP_SYMLINK: "SYMLINK",
}

SSH_FXP_STATUS = 101
SSH_FXP_HANDLE = 102
SSH_FXP_DATA = 103
SSH_FXP_NAME = 104
SSH_FXP_ATTRS = 105

SSH_FXP_RESPONSE_NAMES: dict[int, str] = {
    SSH_FXP_STATUS: "STATUS", SSH_FXP_HANDLE: "HANDLE", SSH_FXP_DATA: "DATA",
    SSH_FXP_NAME: "NAME", SSH_FXP_ATTRS: "ATTRS", SSH_FXP_VERSION: "VERSION",
}

STATUS_NAMES: dict[int, str] = {
    0: "OK", 1: "EOF", 2: "NO_SUCH_FILE", 3: "PERMISSION_DENIED", 4: "FAILURE",
    5: "BAD_MESSAGE", 6: "NO_CONNECTION", 7: "CONNECTION_LOST", 8: "OP_UNSUPPORTED",
    9: "INVALID_HANDLE",
}

SSH_FX_OK = 0
SSH_FX_EOF = 1
SSH_FX_NO_SUCH_FILE = 2
SSH_FX_PERMISSION_DENIED = 3
SSH_FX_FAILURE = 4
SSH_FX_BAD_MESSAGE = 5
SSH_FX_NO_CONNECTION = 6
SSH_FX_CONNECTION_LOST = 7
SSH_FX_OP_UNSUPPORTED = 8
SSH_FX_INVALID_HANDLE = 9

# --------------------------------------------------------------------------
# ATTRS 标志位
# --------------------------------------------------------------------------

SSH_FILEXFER_ATTR_SIZE = 0x00000001
SSH_FILEXFER_ATTR_UIDGID = 0x00000002
SSH_FILEXFER_ATTR_PERMISSIONS = 0x00000004
SSH_FILEXFER_ATTR_ACMODTIME = 0x00000008
SSH_FILEXFER_ATTR_EXTENDED = 0x80000000

# --------------------------------------------------------------------------
# OPEN 的 pflags
# --------------------------------------------------------------------------

SSH_FXF_READ = 0x00000001
SSH_FXF_WRITE = 0x00000002
SSH_FXF_APPEND = 0x00000004
SSH_FXF_CREAT = 0x00000008
SSH_FXF_TRUNC = 0x00000010
SSH_FXF_EXCL = 0x00000020

# --------------------------------------------------------------------------
# 文件类型（取自 permissions 的高 4 位）
# --------------------------------------------------------------------------

S_IFMT = 0o170000
S_IFSOCK = 0o140000
S_IFLNK = 0o120000
S_IFREG = 0o100000
S_IFBLK = 0o060000
S_IFDIR = 0o040000
S_IFCHR = 0o020000
S_IFIFO = 0o010000

#: 协议中 `uint32` 的上限。一次 READ 请求的 len 字段是 uint32，
#: 但服务端实际能返回的块远小于此；64 KiB 是 OpenSSH 的常见内部块大小（决策 D-007）。
MAX_READ_CHUNK = 64 * 1024

#: 服务端（OpenSSH 的 sftp-server）对**整包**长度（4 字节长度字段的值）的硬上限。
#: 这个值不来自协议文档，而是实现细节：sftp-server 收到超长的包时直接判定
#: 「bad message from ...」并结束连接，客户端只能看到管道断开
#: （在本项目里表现为 `NotConnected`：写入远端失败：连接已断开）。
#: 实测：一次 WRITE 携带 261120 字节正文可以，262144 字节就把连接写死。
OPENSSH_MAX_PACKET_BYTES = 256 * 1024

#: 一次 WRITE 帧最多携带的数据量。整包长度 = 4（长度字段）+ 1（类型）+ 4（request-id）
#: + 4 + len(handle) + 8（偏移）+ 4（数据长度）+ 数据，取 64 KiB 留足余量，
#: 也与读取块大小保持一致（决策 D-007）。超过它的数据由 `SftpClient.write_chunk`
#: 自动拆成多帧 —— 否则写一个大于 256 KiB 的文件就会把整条通道写死。
MAX_WRITE_CHUNK = 64 * 1024

#: 单个协议帧的合理上限，用于发现明显错位的长度字段。
#: 4 MiB 足够容纳任何合法的 READDIR 响应（一页目录项）与 WRITE 请求，
#: 又能让「把 ASCII 当成长度」这类错误立刻暴露，而不是试图分配几个 GB。
MAX_FRAME_BYTES = 4 * 1024 * 1024


def encode_string(value: str | bytes) -> bytes:
    """`string` = uint32 长度 + 原始字节（UTF-8）。"""
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return struct.pack(">I", len(raw)) + raw


def encode_uint32(value: int) -> bytes:
    return struct.pack(">I", value)


def encode_uint64(value: int) -> bytes:
    return struct.pack(">Q", value)


def encode_attrs_permissions(mode: int) -> bytes:
    """构造只带 PERMISSIONS 位的 ATTRS。

    `MKDIR` 与 `SETSTAT` 的第三个字段是**完整 ATTRS**（`uint32 flags` + 按 flags
    出现的字段），不是裸模式值。这里 `flags = SSH_FILEXFER_ATTR_PERMISSIONS`，
    紧跟一个 `uint32` 模式。

    错误写法 `struct.pack(">I", 0o755)` 会让服务端读到 `flags=0o755`，
    其中 `0x80000000` 位未置位但其它位组合出的字段长度与服务端预期不符，
    结果是 `sftp-server` `fatal()` 退出、客户端看到「EOF poll=None」。
    """
    return struct.pack(">II", SSH_FILEXFER_ATTR_PERMISSIONS, mode & 0o7777)


def file_type_from_permissions(permissions: int | None) -> str:
    """把 `st_mode` 的高 4 位映射成可读类型。

    返回 `"file" | "directory" | "symlink" | "socket" | "fifo" | "block" | "char" | "unknown"`。
    """
    if permissions is None:
        return "unknown"
    return {
        S_IFREG: "file", S_IFDIR: "directory", S_IFLNK: "symlink",
        S_IFSOCK: "socket", S_IFIFO: "fifo", S_IFBLK: "block", S_IFCHR: "char",
    }.get(permissions & S_IFMT, "unknown")


@dataclass(frozen=True)
class Attrs:
    """SFTP 的 `ATTRS` 结构解出的结果。未出现的字段为 `None`。"""

    flags: int
    size: int | None = None
    uid: int | None = None
    gid: int | None = None
    permissions: int | None = None
    atime: int | None = None
    mtime: int | None = None

    @property
    def type(self) -> str:
        return file_type_from_permissions(self.permissions)

    @property
    def is_dir(self) -> bool:
        return self.permissions is not None and (self.permissions & S_IFMT) == S_IFDIR

    @property
    def is_link(self) -> bool:
        return self.permissions is not None and (self.permissions & S_IFMT) == S_IFLNK

    @property
    def mode_octal(self) -> str | None:
        """权限位（不含文件类型），形如 `"644"`。"""
        if self.permissions is None:
            return None
        return format(self.permissions & 0o7777, "04o")

    def to_dict(self) -> dict[str, object]:
        return {
            "size": self.size,
            "uid": self.uid,
            "gid": self.gid,
            "permissions": self.permissions,
            "mode": self.mode_octal,
            "atime": self.atime,
            "mtime": self.mtime,
            "type": self.type,
        }


class Reader:
    """带边界检查的顺序读取器。

    每个方法在数据不足时抛 `ProtocolError` 而不是 `struct.error` ——
    后者是一个没有上下文的报错，排查时看不出是哪一个包、哪一个字段出了问题。
    """

    __slots__ = ("_data", "_pos")

    def __init__(self, data: bytes, pos: int = 0) -> None:
        self._data = data
        self._pos = pos

    @property
    def remaining(self) -> int:
        return len(self._data) - self._pos

    def _take(self, count: int) -> bytes:
        if count < 0 or self.remaining < count:
            raise ProtocolError(
                "SFTP 包长度不足，无法解析字段。",
                detail=f"需要 {count} 字节，剩余 {self.remaining} 字节（已解析到偏移 {self._pos}）。",
            )
        chunk = self._data[self._pos:self._pos + count]
        self._pos += count
        return chunk

    def u8(self) -> int:
        return self._take(1)[0]

    def u32(self) -> int:
        return struct.unpack(">I", self._take(4))[0]

    def u64(self) -> int:
        return struct.unpack(">Q", self._take(8))[0]

    def raw_string(self) -> bytes:
        return self._take(self.u32())

    def string(self) -> str:
        raw = self.raw_string()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            # 服务端理论上总是发 UTF-8。若出现非法序列，宁可报错也不要 `errors="replace"` ——
            # 替换会把一个可诊断的协议问题变成一个「文件名里莫名多了问号」的幽灵故障，
            # 而且让用户无法访问这个文件却不知道为什么。
            raise ProtocolError(
                "远端返回的文件名不是合法的 UTF-8。",
                detail=f"{exc}; 原始字节={raw[:64]!r}",
            ) from exc

    def attrs(self) -> Attrs:
        flags = self.u32()
        size = uid = gid = permissions = atime = mtime = None
        if flags & SSH_FILEXFER_ATTR_SIZE:
            size = self.u64()
        if flags & SSH_FILEXFER_ATTR_UIDGID:
            uid = self.u32()
            gid = self.u32()
        if flags & SSH_FILEXFER_ATTR_PERMISSIONS:
            permissions = self.u32()
        if flags & SSH_FILEXFER_ATTR_ACMODTIME:
            atime = self.u32()
            mtime = self.u32()
        if flags & SSH_FILEXFER_ATTR_EXTENDED:
            count = self.u32()
            for _ in range(count):
                self.raw_string()
                self.raw_string()
        return Attrs(
            flags=flags, size=size, uid=uid, gid=gid,
            permissions=permissions, atime=atime, mtime=mtime,
        )


@dataclass(frozen=True)
class NameEntry:
    """`SSH_FXP_NAME` 中的一个条目。

    `filename` 是裸名字（READDIR 场景）或完整路径（REALPATH 场景）；
    `longname` 是服务端给的人类可读串，**本项目不解析它** —— 它只是为了排查时能打印出来。
    """

    filename: str
    longname: str
    attrs: Attrs


@dataclass(frozen=True)
class Response:
    """一个已解出请求 id 的响应包。"""

    type: int
    request_id: int
    body: Reader

    @property
    def type_name(self) -> str:
        return SSH_FXP_RESPONSE_NAMES.get(self.type, f"UNKNOWN({self.type})")


def parse_response(frame: bytes) -> Response:
    """拆解一个响应帧。

    **关键点：所有 SFTP 响应包都以 `uint32 request-id` 开头**（唯一的例外是服务端
    主动发的 `SSH_FXP_VERSION`，它只在对 `INIT` 的应答中出现，且有 type 可区分）。
    漏读这 4 个字节会让后续所有字段整体错位，而 `struct` 往往仍能「成功」解析出
    一组看似合理的数字 —— 这是本项目最难定位的一类 bug，因此在单元测试中被显式钉死。
    """
    if not frame:
        raise ProtocolError("收到空的 SFTP 帧。")
    frame_type = frame[0]
    rest = frame[1:]
    body = Reader(rest)
    if frame_type == SSH_FXP_VERSION:
        # VERSION 是 INIT 的应答，没有 request-id，直接跟 uint32 version。
        return Response(type=frame_type, request_id=0, body=body)
    if len(rest) < 4:
        raise ProtocolError(
            "SFTP 响应包缺少 request-id 字段。",
            detail=f"type={SSH_FXP_RESPONSE_NAMES.get(frame_type, frame_type)} 载荷仅 {len(rest)} 字节。",
        )
    request_id = body.u32()
    return Response(type=frame_type, request_id=request_id, body=body)


def iter_name_entries(response: Response) -> Iterator[NameEntry]:
    """从 `SSH_FXP_NAME` 响应中迭代条目。"""
    if response.type != SSH_FXP_NAME:
        raise ProtocolError(f"期望 NAME 包，实际收到 {response.type_name}。")
    count = response.body.u32()
    for _ in range(count):
        filename = response.body.string()
        longname = response.body.string()
        attrs = response.body.attrs()
        yield NameEntry(filename=filename, longname=longname, attrs=attrs)


def parse_status(response: Response) -> tuple[int, str]:
    """解出 `SSH_FXP_STATUS` 的 `(code, message)`。`lang` 字段被丢弃（从不为中文）。"""
    if response.type != SSH_FXP_STATUS:
        raise ProtocolError(f"期望 STATUS 包，实际收到 {response.type_name}。")
    code = response.body.u32()
    message = response.body.string() if response.body.remaining >= 4 else ""
    return code, message


def status_text(code: int) -> str:
    return STATUS_NAMES.get(code, f"UNKNOWN_STATUS({code})")
