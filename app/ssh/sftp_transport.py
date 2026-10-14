"""SFTP 传输通道：管理 `ssh -s sftp` 子进程与协议帧收发。

本模块是整个连接层的**唯一**子进程持有者。职责边界：

- 启动/关闭 `ssh` 子进程，并保证任何异常路径上都不留下孤儿进程（验收项 T-013）。
- 帧的读写、request-id 配对、超时。
- 把 `SSH_FXP_STATUS` 的数值码翻译成 `app.core.errors` 中的异常。

它**不理解**文件和目录的概念 —— 那是 `sftp_client.py` 的事。

## 为什么超时要用看门狗线程

Windows 的 `select()` **不支持管道**（只支持套接字），所以没法用 `select` 给
`proc.stdout.read()` 加超时。用带超时的读线程再配队列也可以，但会引入「杀线程」问题。
这里选择：**一个看门狗线程 + 一个共享 deadline**。超时后直接终止子进程，
被阻塞的 `read()` 随即返回空字节，调用方据此抛出超时错误。副作用是「超时即断连」，
对 SFTP 来说这是可接受的语义 —— 卡住的通道本来也不该继续复用。
"""

from __future__ import annotations

import struct
import subprocess
import threading
import time
from collections import deque
from typing import Iterable, Sequence

from app.core.errors import (
    AwfmError,
    ConfigError,
    NotConnected,
    OperationTimeout,
    PathNotFound,
    PermissionDenied,
    ProtocolError,
    RemoteError,
)
from app.ssh import sftp_protocol as proto
from app.utils.paths import safe_for_log

#: 看门狗的检查间隔。太小会浪费 CPU，太大会让超时误差明显。
_WATCHDOG_INTERVAL = 0.1

#: stderr 保留的行数上限。ssh 在 -v 模式下可以刷出大量内容；
#: 我们只需要最后的诊断信息，无上限保留等于给自己制造内存泄漏。
_STDERR_HISTORY = 200


def map_status_error(code: int, message: str, *, context: str) -> AwfmError:
    """把 `SSH_FXP_STATUS` 的数值码翻译成项目错误。

    规划文档 §7.2 要求测试「错误映射」。结构化的数值码正是选原生协议的理由之一（D-011）：
    不必去匹配英文错误串，而那些串在不同 OpenSSH 版本与不同 `LC_*` 下会变。
    """
    detail = f"远端返回 {proto.status_text(code)}"
    if message:
        detail += f"：{safe_for_log(message)}"
    if code == proto.SSH_FX_NO_SUCH_FILE:
        return PathNotFound(f"{context}：路径不存在。", detail=detail)
    if code == proto.SSH_FX_PERMISSION_DENIED:
        return PermissionDenied(f"{context}：远端拒绝访问。", detail=detail)
    if code == proto.SSH_FX_OP_UNSUPPORTED:
        return RemoteError(f"{context}：远端 SFTP 服务不支持该操作。", detail=detail)
    if code in (proto.SSH_FX_NO_CONNECTION, proto.SSH_FX_CONNECTION_LOST):
        return NotConnected(f"{context}：与远端的连接已断开。", detail=detail)
    if code == proto.SSH_FX_BAD_MESSAGE:
        return ProtocolError(f"{context}：远端认为请求格式非法。", detail=detail)
    return RemoteError(f"{context}：远端操作失败。", detail=detail)


class SftpTransport:
    """一个 `ssh -s sftp` 通道。

    **线程安全（串行化）**：所有帧的「发送 + 等待配对响应」在一把可重入锁内完成。
    必须这样做 —— SFTP 协议本身没有多路复用，两个线程交错写帧会让 request-id
    与响应错配，而错配之后没有任何办法恢复（协议已经错位）。
    Web 服务是多线程的（`ThreadingHTTPServer`），所以这把锁不是可选项。
    """
    def __init__(
        self,
        command: Sequence[str],
        *,
        env: dict[str, str] | None = None,
        operation_timeout: float = 30.0,
    ) -> None:
        self._command = list(command)
        self._env = env
        self._operation_timeout = operation_timeout
        self._proc: subprocess.Popen[bytes] | None = None
        self._next_id = 1
        self._io_lock = threading.RLock()
        self._deadline: float | None = None
        self._watchdog: threading.Thread | None = None
        self._stop_watchdog = threading.Event()
        self._stderr_lines: deque[str] = deque(maxlen=_STDERR_HISTORY)
        self._stderr_thread: threading.Thread | None = None
        self._closed = False
        self.server_version: int | None = None

    # -- 生命周期 ---------------------------------------------------------

    def open(self, *, connect_timeout: float | None = None) -> None:
        """启动子进程并完成 SFTP 版本协商。"""
        if self._proc is not None:
            raise ProtocolError("传输通道已经打开，不能重复打开。")
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            # 不弹控制台窗口。若省略，服务在后台运行时每个连接都会闪一个黑框。
            creationflags = subprocess.CREATE_NO_WINDOW
        try:
            self._proc = subprocess.Popen(  # noqa: S603 - argv 列表，不经 shell
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,  # 0 = 无缓冲，协议帧必须原样过管道（D-011 实测二进制安全）
                env=self._env,
                creationflags=creationflags,
            )
        except FileNotFoundError as exc:
            raise ConfigError(
                "找不到 SSH 客户端程序。",
                detail=f"尝试执行：{self._command[0]!r}",
            ) from exc

        self._start_stderr_drain()
        self._start_watchdog()
        self._handshake(connect_timeout or self._operation_timeout)

    def _start_stderr_drain(self) -> None:
        """持续排空 stderr。

        必须排空而不是「需要时再读」：ssh 在握手阶段可能输出超过管道缓冲区
        （通常 64 KiB）的内容，写不进去就会**阻塞 ssh 自身**，表现为神秘挂起。
        """
        assert self._proc is not None
        stream = self._proc.stderr

        def drain() -> None:
            if stream is None:
                return
            try:
                for raw in iter(stream.readline, b""):
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                    if line:
                        self._stderr_lines.append(line)
            except (ValueError, OSError):
                pass  # 进程关闭时管道会突然失效，这不是错误。

        self._stderr_thread = threading.Thread(target=drain, name="awfm-ssh-stderr", daemon=True)
        self._stderr_thread.start()

    def _start_watchdog(self) -> None:
        def watch() -> None:
            while not self._stop_watchdog.wait(_WATCHDOG_INTERVAL):
                deadline = self._deadline
                if deadline is not None and time.monotonic() > deadline:
                    self._kill_process()
                    return

        self._watchdog = threading.Thread(target=watch, name="awfm-ssh-watchdog", daemon=True)
        self._watchdog.start()

    def _handshake(self, timeout: float) -> None:
        """发 `SSH_FXP_INIT`，收 `SSH_FXP_VERSION`。

        INIT 是唯一**不带** request-id 的请求（见 proto.parse_response 的注释）。
        """
        payload = proto.encode_uint32(3)
        self._write_frame(proto.SSH_FXP_INIT, payload, include_request_id=False)
        self._deadline = time.monotonic() + timeout
        try:
            frame = self._read_frame()
        finally:
            self._deadline = None
        response = proto.parse_response(frame)
        if response.type != proto.SSH_FXP_VERSION:
            raise ProtocolError(
                "SFTP 版本协商失败。",
                detail=f"期望 VERSION 包，收到 {response.type_name}。{self.diagnostics()}",
            )
        self.server_version = response.body.u32()

    def close(self) -> None:
        """幂等关闭。先关管道再等进程，最后兜底 kill。"""
        with self._io_lock:
            if self._closed:
                return
            self._closed = True
        self._stop_watchdog.set()
        proc = self._proc
        if proc is None:
            return
        # 关闭 stdin 会让 sftp-server 读到 EOF 后自行退出 —— 正常的退出路径。
        for stream in (proc.stdin,):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._kill_process()
        for stream in (proc.stdout, proc.stderr):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass

    def _kill_process(self) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.kill()
        except OSError:
            pass

    # -- 帧 I/O -----------------------------------------------------------

    def _write_frame(self, frame_type: int, payload: bytes, *, include_request_id: bool) -> None:
        if include_request_id:
            raise ProtocolError("内部错误：_write_frame 不应自行拼接 request-id。")
        body = bytes([frame_type]) + payload
        self._write_all(struct.pack(">I", len(body)) + body)

    def _write_all(self, data: bytes) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise NotConnected("连接通道尚未建立。")
        sink = proc.stdin
        view = memoryview(data)
        sent = 0
        while sent < len(view):
            try:
                written = sink.write(view[sent:])
            except (BrokenPipeError, OSError) as exc:
                raise NotConnected(
                    "写入远端失败：连接已断开。", detail=f"{exc}; {self.diagnostics()}"
                ) from exc
            if written is None:  # 某些 raw 流可能返回 None
                raise NotConnected("写入远端失败：管道不可写。", detail=self.diagnostics())
            if written <= 0:
                raise NotConnected("写入远端失败：管道提前关闭。", detail=self.diagnostics())
            sent += written
        try:
            sink.flush()
        except (BrokenPipeError, OSError):
            pass  # bufsize=0 时本就没有缓冲，flush 失败不代表数据没发出去。

    def _read_exact(self, count: int) -> bytes:
        proc = self._proc
        if proc is None or proc.stdout is None:
            raise NotConnected("连接通道尚未建立。")
        source = proc.stdout
        chunks: list[bytes] = []
        got = 0
        while got < count:
            try:
                chunk = source.read(count - got)
            except (OSError, ValueError) as exc:
                raise NotConnected(
                    "读取远端失败：连接已断开。", detail=f"{exc}; {self.diagnostics()}"
                ) from exc
            if not chunk:
                raise self._channel_closed_error()
            chunks.append(chunk)
            got += len(chunk)
        return chunks[0] if len(chunks) == 1 else b"".join(chunks)

    def _channel_closed_error(self) -> AwfmError:
        if self._timed_out():
            return OperationTimeout(
                f"操作超时（超过 {self._operation_timeout:g} 秒），连接已终止。",
                detail=self.diagnostics(),
            )
        return NotConnected(
            "与远端的连接已关闭。",
            detail=self.diagnostics(),
        )

    def _timed_out(self) -> bool:
        return self._deadline is not None and time.monotonic() > self._deadline

    def _read_frame(self) -> bytes:
        header = self._read_exact(4)
        (length,) = struct.unpack(">I", header)
        if length == 0 or length > proto.MAX_FRAME_BYTES:
            raise ProtocolError(
                "SFTP 帧长度不合法，通道可能已错位。",
                detail=f"长度字段={length}（上限 {proto.MAX_FRAME_BYTES}）。{self.diagnostics()}",
            )
        return self._read_exact(length)

    def stderr_text(self) -> str:
        """返回 ssh 最近输出的**原始**文本（未截断）。

        与 `diagnostics()` 的区别：后者是给人看的摘要，这个是给判定逻辑用的
        （例如识别「主机密钥校验失败」）。之所以需要它，是因为 ssh 在
        `LogLevel=ERROR` 下仍会输出主机密钥不匹配的警告块 —— 那是 `logit()`，
        不受日志级别过滤。
        """
        return "\n".join(self._stderr_lines)

    def diagnostics(self) -> str:
        """组装 ssh 侧的最后若干行输出，供错误 detail 使用。

        不返回完整 stderr —— 它可能包含主机名、用户名等；这里只取尾部若干行，
        且 `ssh` 的 `LogLevel=ERROR` 已经保证了正常情况下它是空的。
        """
        lines = list(self._stderr_lines)[-6:]
        proc = self._proc
        code = proc.poll() if proc is not None else None
        parts = []
        if code is not None:
            parts.append(f"ssh 退出码={code}")
        if lines:
            parts.append("ssh 输出：" + " | ".join(safe_for_log(line, limit=200) for line in lines))
        return "；".join(parts) if parts else "ssh 未输出诊断信息"

    # -- 请求/响应 --------------------------------------------------------

    def transact(
        self,
        frame_type: int,
        payload: bytes,
        *,
        expect: Iterable[int],
        context: str,
        accept_status: Iterable[int] = (),
        timeout: float | None = None,
    ) -> proto.Response:
        """发一个请求并等它的响应。

        Args:
            payload: 不含 request-id 的负载。
            expect: 可接受的响应类型（如 `(SSH_FXP_HANDLE,)`）。
            accept_status: 可接受的 STATUS 码（`0`=OK 通常需要显式列出；
                READDIR 的终点是 `1`=EOF）。其余先到达的 STATUS 一律转成异常。
            timeout: 覆盖默认超时。

        Raises:
            AwfmError: 状态码错误、协议错位、超时或断连。
        """
        if self._closed:
            raise NotConnected("连接通道已关闭。")
        expect_set = set(expect)
        accept_set = set(accept_status)
        # 锁的范围必须覆盖「选 id → 写帧 → 读到配对响应」的全过程：
        # 只锁 id 分配或只锁写都不够，交错读写会让协议错位且无法恢复。
        with self._io_lock:
            if self._closed:
                raise NotConnected("连接通道已关闭。")
            request_id = self._next_id
            self._next_id += 1

            body = struct.pack(">I", request_id) + payload
            frame = struct.pack(">I", 1 + len(body)) + bytes([frame_type]) + body

            self._deadline = time.monotonic() + (timeout or self._operation_timeout)
            try:
                self._write_all(frame)
                while True:
                    raw = self._read_frame()
                    response = proto.parse_response(raw)
                    if response.request_id != request_id:
                        raise ProtocolError(
                            "SFTP 响应与请求不匹配，协议已错位。",
                            detail=(
                                f"期望 id={request_id}，收到 id={response.request_id}"
                                f"（{response.type_name}）。{self.diagnostics()}"
                            ),
                        )
                    if response.type == proto.SSH_FXP_STATUS:
                        code, message = proto.parse_status(response)
                        if code in accept_set:
                            return response
                        raise map_status_error(code, message, context=context)
                    if response.type in expect_set:
                        return response
                    raise ProtocolError(
                        f"{context}：收到了非预期的响应类型。",
                        detail=f"{response.type_name}（期望 {sorted(expect_set)} 或 STATUS）。",
                    )
            finally:
                self._deadline = None
