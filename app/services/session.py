"""一条远程会话：连接、状态与客户端句柄。

一次「连接」= 一个 `ssh -s sftp` 子进程 + 一条 SFTP 通道。
会话对象是它的所有者，负责在**任何**退出路径上关掉它（验收项 T-013）。

## 状态机

```
disconnected --connect()--> connecting --成功--> connected
                                 |                    |
                                 +--失败--> error     +--disconnect()--> disconnected
```

`error` 与 `disconnected` 分开是有意义的：前者带一条「为什么失败」的信息，
界面要能把它显示出来；后者是用户主动断开的正常状态。

## 主机密钥的两次机会（验收项 T-005）

1. **信任库里有该主机的密钥** → 直接连，交给 `ssh` 的 `StrictHostKeyChecking` 判定。
   若失败且 stderr 表明是主机密钥问题，再采集一次当前密钥，
   给出**新旧指纹对照**后报 `HostKeyMismatch`。**绝不自动覆盖。**
2. **信任库里没有** → 先采集候选密钥并报 `HostKeyUnknown`（带指纹），
   等用户在界面上确认后再写入信任库。**绝不静默接受。**
"""

from __future__ import annotations

import logging
import threading
import time

from app.core.errors import (
    AuthFailed,
    AwfmError,
    HostKeyMismatch,
    HostKeyUnknown,
    NotConnected,
    SessionNotConnected,
)
from app.models.connection import Connection
from app.ssh import known_hosts
from app.ssh.askpass import prepare_askpass
from app.ssh.known_hosts import collect_host_keys, find_trusted_keys
from app.ssh.sftp_client import SftpClient
from app.ssh.sftp_transport import SftpTransport
from app.ssh.ssh_launcher import (
    SshTarget,
    build_environment,
    build_sftp_command,
    find_ssh_executable,
)
from app.utils.paths import safe_for_log

logger = logging.getLogger(__name__)

STATE_DISCONNECTED = "disconnected"
STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"
STATE_ERROR = "error"


class RemoteSession:
    """与某一条连接配置对应的一条活动会话。线程安全（内部一把可重入锁）。"""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._lock = threading.RLock()
        self._transport: SftpTransport | None = None
        self._client: SftpClient | None = None
        self._state = STATE_DISCONNECTED
        self._last_error: str | None = None
        self._connected_at: float | None = None
        self._home: str | None = None
        self._server_version: int | None = None

    # -- 绑定的配置 -------------------------------------------------------

    @property
    def connection(self) -> Connection:
        """当前生效的连接配置。

        会话建好之后配置仍可能被改（最常见的是「允许写操作」这个开关），所以这里
        读的是**当前**绑定，而不是建会话那一刻的快照 —— 否则写权限判断会一直用
        过期值，表现为「界面上开了写操作，上传仍然被拒，必须断开重连」。
        """
        with self._lock:
            return self._connection

    def bind_connection(self, connection: Connection) -> None:
        """把会话重新绑到一份新的配置上。

        只由 app.services.connection_manager.ConnectionManager 调用：它是唯一
        知道「配置刚刚被改过」的地方。绑定换的是一个引用，线程安全；权限判断每次
        都重新读它，所以开关立刻生效，不需要断开重连。
        """
        with self._lock:
            self._connection = connection

    @property
    def allow_write(self) -> bool:
        """当前配置是否允许写。每次重新读，调用方不该缓存这个判定。"""
        with self._lock:
            return bool(self._connection.allow_write)

    # -- 只读状态 ---------------------------------------------------------

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._state == STATE_CONNECTED and self._client is not None

    @property
    def home(self) -> str | None:
        """登录后的起始目录（服务端 REALPATH 的结果）；未连接时是 None。"""
        with self._lock:
            return self._home

    @property
    def client(self) -> SftpClient:
        """取客户端句柄；未连接时抛 `NotConnected`。"""
        with self._lock:
            if self._state != STATE_CONNECTED or self._client is None:
                raise NotConnected(
                    "该连接当前未建立。",
                    detail=self._last_error or "请先点击连接。",
                    extra={"connection_id": self.connection.id, "state": self._state},
                )
            return self._client

    def status(self) -> dict:
        with self._lock:
            return {
                "connection_id": self.connection.id,
                "state": self._state,
                "connected": self._state == STATE_CONNECTED,
                "connected_at": self._connected_at,
                "duration_seconds": (
                    round(time.time() - self._connected_at, 3) if self._connected_at else None
                ),
                "home": self._home,
                "server_version": self._server_version,
                "last_error": self._last_error,
            }

    # -- 连接 / 断开 ------------------------------------------------------

    def connect(self, password: str = "", *, settings) -> dict:
        """建立会话。

        Args:
            password: 密码认证用；密钥认证传空串。
            settings: `app.core.config.AppConfig` —— 只读取需要的字段，
                避免本模块 import 配置模块（那会形成环）。
        """
        with self._lock:
            self.disconnect(_internal=True)
            self._state = STATE_CONNECTING
            self._last_error = None
            try:
                self._do_connect(password, settings)
            except AwfmError as exc:
                self._teardown()
                self._state = STATE_ERROR
                self._last_error = exc.message
                logger.warning(
                    "连接失败 %s：%s", self.connection.target_label, safe_for_log(exc.message)
                )
                raise
            except Exception as exc:  # 兜底：任何未预期异常都不能留下子进程
                self._teardown()
                self._state = STATE_ERROR
                self._last_error = "连接过程中发生未预期的错误。"
                logger.exception("连接 %s 时发生未预期异常", self.connection.target_label)
                raise AwfmError("连接过程中发生未预期的错误。", detail=str(exc)) from exc
            self._state = STATE_CONNECTED
            self._connected_at = time.time()
            logger.info("已连接 %s（起始目录 %s）", self.connection.target_label, safe_for_log(self._home))
            return self.status()

    def _do_connect(self, password: str, settings) -> None:
        executable = find_ssh_executable(settings.ssh.ssh_executable)
        known_hosts_path = settings.known_hosts_path
        known_hosts.ensure_known_hosts_file(known_hosts_path)

        target = SshTarget(
            host=self.connection.host,
            port=self.connection.port,
            username=self.connection.username,
        )
        use_password = self.connection.auth_method == "password"
        trusted = find_trusted_keys(known_hosts_path, target.host, target.port)

        if not trusted and settings.security.host_key_policy != "accept-new":
            # 首次连接：采集候选密钥，交给用户确认。**不写信任库。**
            candidates = collect_host_keys(
                ssh_executable=executable,
                host=target.host,
                port=target.port,
                connect_timeout=settings.ssh.connect_timeout_seconds,
            )
            raise HostKeyUnknown(
                f"首次连接 {target.host}:{target.port}，需要确认主机指纹。",
                detail="请核对下列指纹是否与目标机一致，确认后才会写入本项目的信任库。",
                extra={
                    "connection_id": self.connection.id,
                    "host": target.host,
                    "port": target.port,
                    "fingerprints": [
                        {"key_type": key.key_type, "fingerprint": key.fingerprint}
                        for key in candidates
                    ],
                },
            )

        command = build_sftp_command(
            target,
            ssh_executable=executable,
            known_hosts_file=known_hosts_path,
            host_key_policy=settings.security.host_key_policy,
            identity_file=self.connection.identity_file or None,
            connect_timeout=settings.ssh.connect_timeout_seconds,
            keepalive_interval=settings.ssh.keepalive_interval_seconds,
            use_password=use_password,
        )

        bundle = prepare_askpass(password) if use_password else None
        try:
            env = build_environment(
                None,
                askpass_command=bundle.command if bundle else None,
                askpass_payload=bundle.payload if bundle else None,
            )
            transport = SftpTransport(
                command,
                env=env,
                operation_timeout=float(settings.ssh.command_timeout_seconds),
            )
            try:
                transport.open(connect_timeout=float(settings.ssh.connect_timeout_seconds))
            except AwfmError as exc:
                transport.close()
                raise self._translate_connect_error(exc, target, known_hosts_path, executable,
                                                    settings, trusted) from exc
        finally:
            # 认证已经结束（成功或失败），密码文件不再需要 —— 立刻销毁。
            if bundle is not None:
                bundle.cleanup()

        client = SftpClient(transport)
        try:
            home = client.realpath(".")
        except AwfmError:
            transport.close()
            raise
        self._transport = transport
        self._client = client
        self._home = home
        self._server_version = transport.server_version

    def _translate_connect_error(
        self, error: AwfmError, target: SshTarget, known_hosts_path: str,
        executable: str, settings, trusted: list,
    ) -> AwfmError:
        """把 ssh 的失败翻译成更贴近用户判断的错误。

        这里**只做诊断增强**，不改判定：主机密钥的接受与否始终由 ssh 的
        `StrictHostKeyChecking` 决定。匹配英文提示串是有意的取舍 ——
        匹配不中时退化为原始错误，不会产生错误的安全结论。
        """
        detail = error.detail or ""
        stderr = ""
        if isinstance(detail, str):
            stderr = detail
        lowered = stderr.lower()

        if "host key verification failed" in lowered or "remote host identification has changed" in lowered:
            if trusted:
                try:
                    current = collect_host_keys(
                        ssh_executable=executable,
                        host=target.host,
                        port=target.port,
                        connect_timeout=settings.ssh.connect_timeout_seconds,
                    )
                except AwfmError:
                    current = []
                return HostKeyMismatch(
                    f"{target.host}:{target.port} 的主机密钥与本项目信任库中的记录不一致。",
                    detail=(
                        "连接已被拒绝。若确认目标机被重装过或密钥被更换，"
                        "请先核对下列指纹，再手动更新信任库；本程序不会自动覆盖。"
                    ),
                    extra={
                        "connection_id": self.connection.id,
                        "host": target.host,
                        "port": target.port,
                        "trusted_fingerprints": [
                            {"key_type": k.key_type, "fingerprint": k.fingerprint} for k in trusted
                        ],
                        "current_fingerprints": [
                            {"key_type": k.key_type, "fingerprint": k.fingerprint} for k in current
                        ],
                    },
                )
            return HostKeyUnknown(
                f"{target.host}:{target.port} 的主机密钥未通过校验。",
                detail="ssh 报告主机密钥校验失败。",
                extra={
                    "connection_id": self.connection.id,
                    "host": target.host,
                    "port": target.port,
                },
            )

        if "permission denied" in lowered or "no supported authentication methods" in lowered:
            return AuthFailed(
                "认证失败：目标机拒绝了提供的凭据。",
                detail=stderr or None,
                extra={"connection_id": self.connection.id, "auth_method": self.connection.auth_method},
            )
        return error

    def disconnect(self, *, _internal: bool = False) -> dict:
        """关闭会话。幂等 —— 已断开时再调用不报错。"""
        with self._lock:
            self._teardown()
            if not _internal:
                self._state = STATE_DISCONNECTED
                self._last_error = None
            if not _internal:
                logger.info("已断开 %s", self.connection.target_label)
            return self.status()

    def _teardown(self) -> None:
        """释放子进程与句柄。**必须可重入**，任何路径上都调用它。"""
        transport, self._transport = self._transport, None
        self._client = None
        self._connected_at = None
        self._home = None
        self._server_version = None
        if transport is not None:
            try:
                transport.close()
            except Exception:  # pragma: no cover - 关闭失败不该掩盖原始错误
                logger.debug("关闭传输通道时出错", exc_info=True)

    def __enter__(self) -> "RemoteSession":
        return self

    def __exit__(self, *_exc) -> None:
        self.disconnect()


def require_session(session: RemoteSession | None, connection_id: str) -> RemoteSession:
    """取会话或抛出「未连接」。供服务层统一使用。"""
    if session is None:
        raise SessionNotConnected(
            "该连接尚未建立会话。",
            detail="请先在界面上点击「连接」。",
            extra={"connection_id": connection_id},
        )
    return session
