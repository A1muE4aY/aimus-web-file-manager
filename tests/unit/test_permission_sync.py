"""写权限同步的单元测试（任务书 2.md 阶段一缺陷①）。

缺陷的现象是「界面开了写权限，上传仍被拒，必须断开重连」。根因在会话与配置之间：
会话建好时把 Connection 存成属性，之后 PATCH 只换了管理器里的那个对象，活动会话还
攥着旧的一份。

这里用鸭子类型的假连接把这一层单独钉住：不启动 SSH，也不碰真实文件系统。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.core.errors import Unauthorized
from app.services.connection_manager import ConnectionManager, _session_identity
from app.services.filesystem import require_write_permission
from app.services.session import RemoteSession
from tests.integration.support import make_config, testbed_connection


def fake_connection(*, allow_write: bool = False, **fields) -> SimpleNamespace:
    """RemoteSession 与权限判定只用到 connection 上的少数字段。"""
    payload = {
        "id": "fake",
        "allow_write": allow_write,
        "host": "127.0.0.1",
        "port": 22,
        "username": "aimu",
        "auth_method": "key",
        "identity_file": "k",
    }
    payload.update(fields)
    return SimpleNamespace(**payload)


class SessionBindingTests(unittest.TestCase):
    def test_session_exposes_the_current_binding(self):
        session = RemoteSession(fake_connection(allow_write=False))
        self.assertFalse(session.allow_write)

        session.bind_connection(fake_connection(allow_write=True))

        self.assertTrue(session.allow_write)
        self.assertTrue(session.connection.allow_write)

    def test_write_gate_rereads_the_binding_every_time(self):
        session = RemoteSession(fake_connection(allow_write=True))
        require_write_permission(session, "上传文件")  # 开着的时候不该抛

        session.bind_connection(fake_connection(allow_write=False))

        with self.assertRaises(Unauthorized) as raised:
            require_write_permission(session, "上传文件")
        self.assertIn("未开启写权限", str(raised.exception))
        self.assertEqual(raised.exception.extra.get("connection_id"), "fake")

    def test_identity_tuple_notices_every_field_change(self):
        base = fake_connection()
        self.assertEqual(_session_identity(base), _session_identity(fake_connection()))

        for field, value in (
            ("host", "127.0.0.2"),
            ("port", 2222),
            ("username", "other"),
            ("auth_method", "password"),
            ("identity_file", "other-key"),
        ):
            changed = fake_connection(**{field: value})
            self.assertNotEqual(_session_identity(base), _session_identity(changed), field)

        # 行为开关与显示名不参与身份：这两种改动必须热更新，而不是把 SSH 拆掉。
        self.assertEqual(_session_identity(base), _session_identity(fake_connection(allow_write=True)))
        self.assertEqual(_session_identity(base), _session_identity(fake_connection(id="renamed")))


class _StubSession:
    """只实现 _sync_live_session 用到的成员，并记录它被怎么处理。"""

    def __init__(self, connection):
        self.connection = connection
        self.bindings = []
        self.disconnects = 0

    def bind_connection(self, connection):
        self.bindings.append(connection)
        self.connection = connection

    def disconnect(self):
        self.disconnects += 1


class LiveSessionSyncTests(unittest.TestCase):
    """白盒验证分流：新的连接对象该热更新，还是该丢弃会话。

    真走 SSH 的那一面在 tests/integration/test_write_permission_sync.py。
    """

    def setUp(self):
        self.known_hosts = Path(tempfile.mkdtemp(prefix="awfm-unit-")) / "known_hosts"
        self.config = make_config(self.known_hosts, connections=[testbed_connection()])
        self.manager = ConnectionManager(self.config)
        self.original = self.config.connections[0]

    def _replacement(self, **overrides):
        config = make_config(self.known_hosts, connections=[testbed_connection(**overrides)])
        return config.connections[0]

    def _attach(self, session):
        # 白盒：直接塞进会话表，避免为了同步逻辑起一条真 SSH。
        self.manager._sessions[self.original.id] = session
        return session

    def test_write_flag_change_hot_updates_the_session(self):
        stub = self._attach(_StubSession(self.original))
        updated = self._replacement(allow_write=True)

        self.manager._sync_live_session(updated)

        self.assertEqual(stub.disconnects, 0, "只改行为开关不该断开 SSH")
        self.assertIs(stub.connection, updated)
        self.assertIs(self.manager._sessions[self.original.id], stub)

    def test_identity_change_drops_the_session(self):
        stub = self._attach(_StubSession(self.original))
        updated = self._replacement(port=2223)

        self.manager._sync_live_session(updated)

        self.assertEqual(stub.disconnects, 1, "连接参数变了就必须丢弃旧会话")
        self.assertNotIn(self.original.id, self.manager._sessions)

    def test_missing_session_is_not_an_error(self):
        self.manager._sync_live_session(self._replacement(allow_write=True))  # 静默返回

        self.assertNotIn(self.original.id, self.manager._sessions)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
