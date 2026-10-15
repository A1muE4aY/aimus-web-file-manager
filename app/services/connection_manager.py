"""连接配置与会话的集中管理。

这是服务层里**唯一**持有 `RemoteSession` 的地方。API 层只能通过它取会话，
不能自己 new 一个 —— 否则「会话有几条、谁负责关」就没有单一答案了。

## 上限与回收

`ssh.max_sessions` 限制的是**同时活动的 SSH 子进程数**。
每个会话背后是一个真实的 ssh 进程（在目标机上还对应一个 sftp-server），
不设上限的话，界面上多点几次「连接」就能把目标机的 `MaxSessions` 占满，
表现是后面所有连接都莫名其妙地失败。
"""

from __future__ import annotations

import logging
import re
import threading
import unicodedata
import uuid
from datetime import datetime, timezone

from app.core.config import AppConfig, save_config
from app.core.errors import (
    ConnectionNotFound,
    SessionNotConnected,
    ValidationError,
)
from app.models.connection import Connection, validate_connection_id
from app.services.session import RemoteSession, require_session
from app.ssh.known_hosts import append_trusted_key, collect_host_keys, find_trusted_keys
from app.ssh.ssh_launcher import find_ssh_executable
from app.utils.paths import safe_for_log

logger = logging.getLogger(__name__)

#: 决定「这条会话连的是哪台机器、用什么身份」的字段。
#: 其中任何一个变了，现有会话就指向了另一个目标，不能继续用；其余字段
#: （名称、备注、允许写操作开关）只是行为开关，热更新到现有会话即可。
_SESSION_IDENTITY_FIELDS = ("host", "port", "username", "auth_method", "identity_file")


def _session_identity(connection: Connection) -> tuple:
    return tuple(getattr(connection, name, None) for name in _SESSION_IDENTITY_FIELDS)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _disconnected_status(connection_id: str) -> dict:
    """未连接（含从未连接）时的会话状态。

    home 是 None 而不是 "/"：没连上就不存在"登录后的起始目录"，谎报成
    根目录会让界面把用户带进 / 并看起来像真读到了。
    """
    return {
        "connection_id": connection_id,
        "state": "disconnected",
        "connected": False,
        "connected_at": None,
        "duration_seconds": None,
        "home": None,
        "server_version": None,
        "last_error": None,
    }


class ConnectionManager:
    """连接配置的增删改查 + 会话生命周期。线程安全。"""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._lock = threading.RLock()
        self._sessions: dict[str, RemoteSession] = {}

    # -- 配置访问 ---------------------------------------------------------

    @property
    def config(self) -> AppConfig:
        return self._config

    def reload(self, config: AppConfig) -> None:
        """换一份配置（`--init-config` 之后或用户在文件里改了配置时用）。

        **不动已存在的会话** —— 正在浏览的目录不该因为有人编辑了配置文件而断掉。
        """
        with self._lock:
            self._config = config
            known = {c.id for c in config.connections}
            for stale_id in [cid for cid in self._sessions if cid not in known]:
                self._sessions.pop(stale_id).disconnect()
            # 配置文件里的值可能变了（用户手工改过、或 --init-config 重新生成过），
            # 同样要让活动会话跟上，否则权限判断会一直用旧值。
            for connection in config.connections:
                self._sync_live_session(connection)

    def list_connections(self) -> list[dict]:
        """列出全部连接配置，附带各自的会话状态。"""
        with self._lock:
            result = []
            for connection in self._config.connections:
                item = connection.to_public_dict()
                session = self._sessions.get(connection.id)
                item["session"] = (
                    session.status() if session is not None else _disconnected_status(connection.id)
                )
                result.append(item)
            return result

    def get_connection(self, connection_id: str) -> Connection:
        cid = validate_connection_id(connection_id)
        with self._lock:
            for connection in self._config.connections:
                if connection.id == cid:
                    return connection
        raise ConnectionNotFound("找不到该连接配置。", extra={"connection_id": cid})

    def connection_detail(self, connection_id: str) -> dict:
        """单条连接配置 + 它的会话状态，与 list_connections 的每一项同形。

        API 层必须用这个方法，而不是 get_connection —— 后者返回的是
        Connection 对象，直接交给 json.dumps 会被 default=str 变成 repr 字符串。
        """
        connection = self.get_connection(connection_id)
        with self._lock:
            session = self._sessions.get(connection.id)
        item = connection.to_public_dict()
        item["session"] = (
            session.status() if session is not None else _disconnected_status(connection.id)
        )
        return item

    def _index_of(self, connection_id: str) -> int:
        for index, connection in enumerate(self._config.connections):
            if connection.id == connection_id:
                return index
        raise ConnectionNotFound("找不到该连接配置。", extra={"connection_id": connection_id})

    # -- 增删改 -----------------------------------------------------------

    def create_connection(self, payload: dict) -> dict:
        """新增一条连接。id 可由调用方给出，否则自动生成。"""
        data = dict(payload or {})
        with self._lock:
            if not data.get("id"):
                data["id"] = self._generate_id(data.get("name") or data.get("host") or "conn")
            data["created_at"] = data.get("created_at") or _now_iso()
            data["updated_at"] = data["created_at"]
            connection = Connection.from_dict(data)
            if any(c.id == connection.id for c in self._config.connections):
                raise ValidationError("该连接 id 已存在。", extra={"connection_id": connection.id})
            self._config.connections.append(connection)
            save_config(self._config)
            logger.info("新增连接 %s（%s）", connection.id, safe_for_log(connection.target_label))
            return connection.to_public_dict()

    def update_connection(self, connection_id: str, payload: dict) -> dict:
        """局部更新。未出现的字段保持不变。

        **不允许改 id** —— id 是会话、URL 与前端状态之间的关联键，
        改它等同于换一条连接，而那应该表现为「删除 + 新建」。
        改 id 会留下一个指向旧 id 的悬挂会话。
        """
        data = dict(payload or {})
        with self._lock:
            index = self._index_of(validate_connection_id(connection_id))
            current = self._config.connections[index]
            if "id" in data and data["id"] != current.id:
                raise ValidationError("连接 id 不可修改。")
            merged = current.to_dict()
            merged.update({k: v for k, v in data.items() if k != "id"})
            merged["created_at"] = current.created_at
            merged["updated_at"] = _now_iso()
            updated = Connection.from_dict(merged)
            self._config.connections[index] = updated
            save_config(self._config)
            # 关键：配置一改就要同步到活动会话。漏掉这一步的后果是「界面开了写
            # 操作，服务端仍按旧配置拒绝上传」，只能断开重连才好。
            self._sync_live_session(updated)
            logger.info("更新连接 %s", updated.id)
            return updated.to_public_dict()

    def _sync_live_session(self, connection: Connection) -> None:
        """把一条刚被改过的配置同步到它的活动会话上。调用方需持有 self._lock。

        两种行为，取决于改了什么：

        * **只改了行为开关**（名称、备注、允许写操作）→ 会话保持连接，重新绑定到新
          配置。写权限判断每次都读当前绑定，所以开关立即生效。
        * **改了身份字段**（主机、端口、用户名、认证方式、私钥）→ 现有会话连的还是
          老目标，留着它只会让用户在一条「不存在」的会话上操作。直接断开并从表中
          移除，状态回到未连接，由用户自己决定何时按新配置重连。
        """
        session = self._sessions.get(connection.id)
        if session is None:
            return
        if _session_identity(session.connection) != _session_identity(connection):
            logger.info("连接 %s 的连接参数已变更，断开其现有会话。", connection.id)
            self._sessions.pop(connection.id, None)
            session.disconnect()
            return
        session.bind_connection(connection)

    def delete_connection(self, connection_id: str) -> dict:
        """删除连接，并**先断开**它的会话。返回被删掉的那条配置（公开形态）。"""
        cid = validate_connection_id(connection_id)
        with self._lock:
            index = self._index_of(cid)
            session = self._sessions.pop(cid, None)
            if session is not None:
                session.disconnect()
            removed = self._config.connections.pop(index)
            save_config(self._config)
            logger.info("删除连接 %s", cid)
            return removed.to_public_dict()

    def _generate_id(self, hint: str) -> str:
        """由显示名派生一个 ASCII 的 id。

        id 会进 URL 路径分量与配置文件的键，所以只保留小写字母与数字，
        与 validate_connection_id 用的是同一套规则。必须先剥掉非 ASCII
        字符：Python 里 "临".isalnum() 为真，只按 isalnum 过滤会把中文名
        原样留在 id 里，随后被自己的校验器拒绝（用中文命名连接必然 400）。
        中文名派生不出 ASCII 字符，于是回退成 conn —— 显示名不受影响。
        """
        ascii_hint = unicodedata.normalize("NFKD", hint).encode("ascii", "ignore").decode("ascii")
        base = re.sub(r"[^a-z0-9]+", "-", ascii_hint.lower()).strip("-")[:24] or "conn"
        while True:
            candidate = f"{base}-{uuid.uuid4().hex[:6]}"
            if not any(c.id == candidate for c in self._config.connections):
                return candidate

    # -- 会话 -------------------------------------------------------------

    def connect(self, connection_id: str, password: str = "") -> dict:
        """建立（或重建）会话。

        重复调用会**先断开旧会话**再建新的：ssh 子进程绑定的是进程内的管道，
        复用已退出进程的管道只会得到一个"看起来连着但什么都读不到"的假会话。
        """
        connection = self.get_connection(connection_id)
        with self._lock:
            if connection.auth_method == "password" and not password:
                raise ValidationError("该连接使用密码认证，请在连接时提供密码。")
            if connection.auth_method == "key" and password:
                # 不报错但忽略：界面上切换认证方式时可能残留密码框内容。
                logger.debug("连接 %s 使用密钥认证，忽略提交的密码。", connection.id)
                password = ""
            self._enforce_session_limit(exclude=connection.id)
            session = self._sessions.get(connection.id)
            if session is None:
                session = RemoteSession(connection)
                self._sessions[connection.id] = session
            elif session.connection is not connection:
                # 配置被改过，会话还绑着旧配置 —— 换掉它。
                session.disconnect()
                session = RemoteSession(connection)
                self._sessions[connection.id] = session
        return session.connect(password, settings=self._config)

    def disconnect(self, connection_id: str) -> dict:
        cid = validate_connection_id(connection_id)
        with self._lock:
            session = self._sessions.get(cid)
        if session is None:
            # 断开一个本来就没连的连接不是错误 —— 幂等对重试友好。
            self.get_connection(cid)
            return _disconnected_status(cid)
        return session.disconnect()

    def session(self, connection_id: str) -> RemoteSession:
        """取一条**已连接**的会话，否则抛错。"""
        cid = validate_connection_id(connection_id)
        with self._lock:
            session = self._sessions.get(cid)
        connected = session is not None and session.is_connected
        if not connected:
            # 区分"没有这条连接"与"有这条连接但还没连上"：前者多半是配置被删了，
            # 后者只是操作顺序问题，界面该给出的下一步完全不同。
            self.get_connection(cid)
        return require_session(session if connected else None, cid)

    def session_status(self, connection_id: str) -> dict:
        cid = validate_connection_id(connection_id)
        with self._lock:
            session = self._sessions.get(cid)
        if session is None:
            self.get_connection(cid)
            return _disconnected_status(cid)
        return session.status()

    def disconnect_all(self) -> None:
        """进程退出前调用：关掉全部会话与子进程（验收项 T-013）。"""
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            try:
                session.disconnect()
            except Exception:  # pragma: no cover
                logger.debug("退出时关闭会话失败", exc_info=True)

    def _enforce_session_limit(self, *, exclude: str) -> None:
        """活动会话数达到上限时，回收**最久未活动**的那条。

        选择回收而不是拒绝：用户点第 5 条连接时，期望的是「连上」，
        而最先连接的那条通常早就没人看了。直接报错会让人以为程序坏了。
        """
        limit = self._config.ssh.max_sessions
        active = [
            (cid, s) for cid, s in self._sessions.items()
            if cid != exclude and s.is_connected
        ]
        if len(active) < limit:
            return
        active.sort(key=lambda item: item[1].status().get("connected_at") or 0)
        while len(active) >= limit:
            cid, session = active.pop(0)
            logger.info("活动会话数达到上限 %d，回收最早的会话 %s", limit, cid)
            session.disconnect()

    # -- 主机密钥 ---------------------------------------------------------

    def trust_host_key(self, connection_id: str, key_type: str, fingerprint: str) -> dict:
        """把用户**刚刚确认过**的主机密钥写入项目信任库。

        安全要点：这里**重新采集一次**目标机当前的密钥，并要求它包含用户确认过的
        那个指纹。如果两次采集之间密钥变了（可能是中间人，也可能是目标机正好在此时
        重装/换钥），则拒绝写入 —— 否则「用户确认」这件事就只是走个形式。
        """
        connection = self.get_connection(connection_id)
        executable = find_ssh_executable(self._config.ssh.ssh_executable)
        candidates = collect_host_keys(
            ssh_executable=executable,
            host=connection.host,
            port=connection.port,
            connect_timeout=self._config.ssh.connect_timeout_seconds,
        )
        matches = [k for k in candidates if k.key_type == key_type and k.fingerprint == fingerprint]
        if not matches:
            raise ValidationError(
                "目标机当前提供的主机指纹与用户确认的不一致，已拒绝写入信任库。",
                detail=(
                    "可能是目标机在此期间更换了密钥。请重新连接并重新核对指纹。"
                    f"当前提供的指纹：{', '.join(k.fingerprint for k in candidates) or '（无）'}"
                ),
            )
        known_hosts_path = self._config.known_hosts_path
        before = find_trusted_keys(known_hosts_path, connection.host, connection.port)
        if any(k.fingerprint == fingerprint and k.key_type == key_type for k in before):
            return {"added": False, "fingerprint": fingerprint, "key_type": key_type}
        append_trusted_key(known_hosts_path, connection.host, connection.port, matches[0])
        logger.info(
            "用户确认并写入主机密钥 %s:%s %s %s",
            connection.host, connection.port, key_type, fingerprint,
        )
        return {"added": True, "fingerprint": fingerprint, "key_type": key_type}

    def trusted_keys(self, connection_id: str) -> list[dict]:
        """当前信任库里该主机的全部密钥指纹（界面上展示用）。"""
        connection = self.get_connection(connection_id)
        keys = find_trusted_keys(self._config.known_hosts_path, connection.host, connection.port)
        return [k.to_dict() for k in keys]
