"""SFTP 高层操作：把协议帧翻译成文件系统动作。

本模块只依赖 `SftpTransport` 与 `sftp_protocol`，不认识 HTTP，也不认识配置。

## 资源纪律（验收项 T-013：会话、文件句柄、临时文件必须释放）

协议里的「句柄」是服务端资源，**不会**因为连接关闭以外的原因自动回收。
因此每个 `open` 都必须与 `close` 严格配对，包括异常路径。
本模块统一用 `with` 语句 + `contextlib` 管理，不手写 `try/finally` 散落在各处。

## 数据完整性纪律（验收项 T-009：上传下载内容与大小一致）

上传的 `write` 必须在写入完成后**回读 `STAT` 校验字节数**（见 `upload_stream`）。
只相信 `WRITE` 返回 `OK` 是不够的：服务端可能因为磁盘配额、
`RLIMIT_FSIZE` 或写入错误而只写了一部分却仍返回 OK。
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager

from app.core.errors import ProtocolError
from app.ssh import sftp_protocol as proto
from app.ssh.sftp_transport import SftpTransport

#: 流式传输的块大小。64 KiB 是吞吐与内存占用之间的常用折中（决策 D-007）。
DEFAULT_CHUNK_SIZE = 64 * 1024

#: 操作"成功"在协议里用 STATUS + 码 0 表达，而 `SftpTransport.transact`
#: 要求可接受的 STATUS 码**显式列出**（它无法区分"成功的 OK"与"意料之外的 OK"）。
#: 凡是只以 STATUS 回话的请求（WRITE/CLOSE/MKDIR/RMDIR/REMOVE/RENAME）都必须带上它，
#: 否则一个完全正常的成功响应会被当错误抛出：远端返回 OK：Success。
_OK = (proto.SSH_FX_OK,)


class SftpClient:
    """一个已协商完成的 SFTP 会话之上的操作集。"""

    def __init__(self, transport: SftpTransport) -> None:
        self._t = transport

    # -- 路径与元数据 -----------------------------------------------------

    def realpath(self, path: str) -> str:
        """取服务端解析后的**规范绝对路径**。

        这是本项目唯一可信的路径规范化来源。客户端不做词法 `..` 折叠，
        因为那会改变符号链接场景下的语义（详见 `app/utils/paths.py` 的模块说明）。
        """
        response = self._t.transact(
            proto.SSH_FXP_REALPATH,
            proto.encode_string(path),
            expect=(proto.SSH_FXP_NAME,),
            context=f"解析路径 {path}",
        )
        entries = list(proto.iter_name_entries(response))
        if not entries:
            raise ProtocolError("远端返回了空的 REALPATH 结果。", detail=f"请求路径={path}")
        return entries[0].filename

    def stat(self, path: str) -> proto.Attrs:
        """跟随符号链接取属性。"""
        response = self._t.transact(
            proto.SSH_FXP_STAT,
            proto.encode_string(path),
            expect=(proto.SSH_FXP_ATTRS,),
            context=f"读取属性 {path}",
        )
        return response.body.attrs()

    def lstat(self, path: str) -> proto.Attrs:
        """不跟随符号链接 —— 用于辨认「这个条目本身是不是链接」。"""
        response = self._t.transact(
            proto.SSH_FXP_LSTAT,
            proto.encode_string(path),
            expect=(proto.SSH_FXP_ATTRS,),
            context=f"读取属性 {path}",
        )
        return response.body.attrs()

    def readlink(self, path: str) -> str:
        response = self._t.transact(
            proto.SSH_FXP_READLINK,
            proto.encode_string(path),
            expect=(proto.SSH_FXP_NAME,),
            context=f"读取链接目标 {path}",
        )
        entries = list(proto.iter_name_entries(response))
        if not entries:
            raise ProtocolError("远端返回了空的 READLINK 结果。", detail=f"请求路径={path}")
        return entries[0].filename

    # -- 目录 -------------------------------------------------------------

    def listdir(self, path: str) -> list[proto.NameEntry]:
        """列出目录条目，**不含** `.` 与 `..`。

        返回值顺序由服务端决定（协议不保证顺序），调用方必须自行排序。
        `.`/`..` 在这里被剔除：它们会让上层界面出现两个可以点出目录的幽灵条目，
        而「返回上级」应当由父路径导航实现，不是靠点击 `..`。
        """
        handle = self.opendir(path)
        try:
            entries: list[proto.NameEntry] = []
            while True:
                response = self._t.transact(
                    proto.SSH_FXP_READDIR,
                    proto.encode_string(handle),
                    expect=(proto.SSH_FXP_NAME,),
                    accept_status=(proto.SSH_FX_EOF,),
                    context=f"读取目录 {path}",
                )
                if response.type == proto.SSH_FXP_STATUS:
                    break  # EOF：目录读完了
                for entry in proto.iter_name_entries(response):
                    if entry.filename in (".", ".."):
                        continue
                    entries.append(entry)
            return entries
        finally:
            self.close(handle)

    def opendir(self, path: str) -> bytes:
        response = self._t.transact(
            proto.SSH_FXP_OPENDIR,
            proto.encode_string(path),
            expect=(proto.SSH_FXP_HANDLE,),
            context=f"打开目录 {path}",
        )
        return response.body.raw_string()

    # -- 句柄 -------------------------------------------------------------

    def open(self, path: str, pflags: int, mode: int = 0o644) -> bytes:
        """打开文件并返回句柄。

        `attrs` 参数是**完整 ATTRS**，不是裸模式值 —— 这是 SPIKE 中踩过的坑
        （见 `proto.encode_attrs_permissions` 的文档）。
        仅在带 `CREAT` 时才有意义，但始终发送是无害的，且能避免「有时发有时不发」
        的分支带来测试盲区。
        """
        payload = proto.encode_string(path) + proto.encode_uint32(pflags) + proto.encode_attrs_permissions(mode)
        response = self._t.transact(
            proto.SSH_FXP_OPEN,
            payload,
            expect=(proto.SSH_FXP_HANDLE,),
            context=f"打开文件 {path}",
        )
        return response.body.raw_string()

    def close(self, handle: bytes) -> None:
        """关闭句柄。`INVALID_HANDLE` 被容忍 —— 见下。

        容忍的原因：句柄可能在服务端因为别的原因已失效，此时再报错只会把一个
        「清理动作」变成一个掩盖原始异常的新异常。`close` 的语义是尽力而为。
        """
        self._t.transact(
            proto.SSH_FXP_CLOSE,
            proto.encode_string(handle),
            expect=(),
            accept_status=(proto.SSH_FX_OK, proto.SSH_FX_INVALID_HANDLE),
            context="关闭句柄",
        )

    def read_chunk(self, handle: bytes, offset: int, length: int) -> bytes:
        """读一块。到达文件末尾时返回 `b""`（EOF 由 STATUS 1 表达）。"""
        response = self._t.transact(
            proto.SSH_FXP_READ,
            proto.encode_string(handle) + proto.encode_uint64(offset) + proto.encode_uint32(length),
            expect=(proto.SSH_FXP_DATA,),
            accept_status=(proto.SSH_FX_EOF,),
            context="读取文件内容",
        )
        if response.type == proto.SSH_FXP_STATUS:
            return b""
        return response.body.raw_string()

    def write_chunk(self, handle: bytes, offset: int, data: bytes) -> None:
        self._t.transact(
            proto.SSH_FXP_WRITE,
            proto.encode_string(handle) + proto.encode_uint64(offset) + proto.encode_string(data),
            expect=(),
            accept_status=_OK,
            context="写入文件内容",
        )

    # -- 流式传输 ---------------------------------------------------------

    @contextmanager
    def open_read(self, path: str) -> Iterator[bytes]:
        """以上下文管理器形式打开一个只读句柄，退出时保证关闭。"""
        handle = self.open(path, proto.SSH_FXF_READ)
        try:
            yield handle
        finally:
            self.close(handle)

    @contextmanager
    def open_write(self, path: str, *, mode: int = 0o644) -> Iterator[bytes]:
        """以只写方式打开（不存在则新建、存在则截断），退出时保证关闭。

        `TRUNC` 是刻意的：压缩、解压、保存文本都是**整体重写**一个文件，
        留下旧内容的尾巴会造成「文件看起来对、内容却是两段拼的」这种最难查的错误。
        """
        pflags = proto.SSH_FXF_WRITE | proto.SSH_FXF_CREAT | proto.SSH_FXF_TRUNC
        handle = self.open(path, pflags, mode)
        try:
            yield handle
        finally:
            self.close(handle)

    def download_chunks(self, path: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Iterator[bytes]:
        """流式读取文件。**不把整个文件放进内存**（决策 D-007）。

        用生成器意味着调用方中途断开（客户端关闭连接）时，`GeneratorExit`
        会让 `finally` 正常执行、句柄被关闭。
        """
        with self.open_read(path) as handle:
            offset = 0
            while True:
                chunk = self.read_chunk(handle, offset, chunk_size)
                if not chunk:
                    return
                offset += len(chunk)
                yield chunk

    def upload_stream(
        self,
        path: str,
        chunks: Iterable[bytes],
        *,
        expected_size: int | None = None,
        mode: int = 0o644,
    ) -> int:
        """流式写入文件，返回实际写入的字节数。

        `CREAT | TRUNC | WRITE`：覆盖已存在文件并从头写。
        `EXCL` 被刻意**不**使用 —— 会让「覆盖已存在文件」变成报错，
        而覆盖行为由上层用二次确认来控制（规划文档 §3.2 把覆盖列为高风险操作）。

        Args:
            expected_size: 调用方已知的字节数（`Content-Length`）。
                用于在上传前拒绝明显超限的请求，而不是等写满了磁盘才发现。

        Returns:
            实际写入的字节数。

        Raises:
            RemoteError: 写入的字节数与 `expected_size` 不符。
        """
        pflags = proto.SSH_FXF_WRITE | proto.SSH_FXF_CREAT | proto.SSH_FXF_TRUNC
        handle = self.open(path, pflags, mode)
        written = 0
        try:
            for chunk in chunks:
                if not chunk:
                    continue
                self.write_chunk(handle, written, chunk)
                written += len(chunk)
        finally:
            # 即使中途异常也要关闭句柄；异常本身由上层传播，不在这里吞掉。
            self.close(handle)

        if expected_size is not None and written != expected_size:
            raise ProtocolError(
                "上传的字节数与声明的不一致。",
                detail=f"声明 {expected_size} 字节，实际收到 {written} 字节。",
            )
        # 回读大小校验：远端可能因为配额或写入错误而少写，且不一定报错。
        actual = self.stat(path).size
        if actual is not None and actual != written:
            raise ProtocolError(
                "上传完成后回读的文件大小与写入量不一致。",
                detail=f"写入 {written} 字节，远端报告 {actual} 字节。",
            )
        return written

    # -- 目录与条目操作（P2，仅在稳定性验证后启用） ------------------------

    def mkdir(self, path: str, mode: int = 0o755) -> None:
        self._t.transact(
            proto.SSH_FXP_MKDIR,
            proto.encode_string(path) + proto.encode_attrs_permissions(mode),
            expect=(),
            accept_status=_OK,
            context=f"创建目录 {path}",
        )

    def rmdir(self, path: str) -> None:
        self._t.transact(
            proto.SSH_FXP_RMDIR,
            proto.encode_string(path),
            expect=(),
            accept_status=_OK,
            context=f"删除目录 {path}",
        )

    def remove(self, path: str) -> None:
        self._t.transact(
            proto.SSH_FXP_REMOVE,
            proto.encode_string(path),
            expect=(),
            accept_status=_OK,
            context=f"删除文件 {path}",
        )

    def rename(self, old_path: str, new_path: str) -> None:
        """重命名。SFTP v3 的 RENAME **不覆盖**已存在的目标（失败而不是静默替换）。"""
        self._t.transact(
            proto.SSH_FXP_RENAME,
            proto.encode_string(old_path) + proto.encode_string(new_path),
            expect=(),
            accept_status=_OK,
            context=f"重命名 {old_path}",
        )


class ChunkWriter:
    """把「往文件对象里写」翻译成「按偏移写远端文件」。

    `gzip` / `tarfile` / `zipfile` 只认文件对象，它们调用 `write(data)`；
    这里负责维护偏移量并落到 SFTP 的 WRITE。内存里始终只有一个块（决策 D-007）：
    压缩一个几百 MB 的目录不会让进程占用跟着涨。
    """

    def __init__(self, client: SftpClient, handle: bytes) -> None:
        self._client = client
        self._handle = handle
        self.offset = 0

    def write(self, data: bytes) -> int:
        """从当前偏移往后追加，返回写入的字节数。"""
        if not data:
            return 0
        self._client.write_chunk(self._handle, self.offset, data)
        self.offset += len(data)
        return len(data)

    def flush(self) -> None:
        """对齐文件对象接口：每次 WRITE 都已落到远端，这里没有缓冲区可冲。"""
        return None

    def tell(self) -> int:
        return self.offset

    def seekable(self) -> bool:
        """只支持顺序追加，不支持回退（压缩流不需要）。"""
        return False

    def writable(self) -> bool:
        return True

    def close(self) -> None:
        """只标记自身。真正的句柄归 `open_write` 的上下文管理器所有。"""
        return None


class RandomReader:
    """把「按位置读」暴露成文件对象，供 `zipfile` / `tarfile` 随机读取远端文件。

    `read(-1)` 会把整份内容读进内存，只应由压缩包库在确实需要时触发
    （zipfile 读中央目录就是这样）；常规路径下这里每次只取一个
    `DEFAULT_CHUNK_SIZE` 块。
    """

    def __init__(self, client: SftpClient, handle: bytes, *, size: int | None = None) -> None:
        self._client = client
        self._handle = handle
        self._size = size
        self._offset = 0
        self._closed = False

    # -- 位置 -------------------------------------------------------------

    def tell(self) -> int:
        return self._offset

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            target = offset
        elif whence == 1:
            target = self._offset + offset
        elif whence == 2:
            if self._size is None:
                raise ProtocolError("无法从文件末尾定位：打开时没有给出文件大小。")
            target = self._size + offset
        else:
            raise ValueError(f"不支持的 whence：{whence}")
        if target < 0:
            raise ValueError("定位到了文件开头之前。")
        self._offset = target
        return target

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def writable(self) -> bool:
        return False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def name(self) -> str:
        return "remote-reader"

    # -- 读取 -------------------------------------------------------------

    def read(self, count: int = -1) -> bytes:
        """读 `count` 字节；`count` 为负表示读到文件结尾。"""
        if count is None or count < 0:
            return self.read_to_end()
        if count == 0:
            return b""
        chunks: list[bytes] = []
        remaining = count
        while remaining > 0:
            chunk = self._client.read_chunk(
                self._handle, self._offset, min(remaining, DEFAULT_CHUNK_SIZE)
            )
            if not chunk:
                break
            chunks.append(chunk)
            self._offset += len(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def read_to_end(self) -> bytes:
        chunks: list[bytes] = []
        while True:
            chunk = self._client.read_chunk(self._handle, self._offset, DEFAULT_CHUNK_SIZE)
            if not chunk:
                break
            chunks.append(chunk)
            self._offset += len(chunk)
        return b"".join(chunks)

    def readinto(self, buffer) -> int:
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        """只标记自身。真正的句柄归 `open_read` 的上下文管理器所有。"""
        self._closed = True

    def __enter__(self) -> "RandomReader":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False
