"""被动掉线的会话标记（v0.1.2 阶段一缺陷 D2）。

通道断掉时，会话必须真的变成 error，并把原因留下来 —— 否则连接卡片一直显示
「已连接」，界面上那个「重试」只是对着同一个死会话重发。

这和「用户主动点断开」是两回事：那条路径是 disconnected，且不留错误。

这一层不启动 SSH：用真实 Connection 对象喂 RemoteSession，再白盒塞进管理器，
只为钉住状态机本身。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.errors import NotConnected, SessionNotConnected
from app.services.connection_manager import ConnectionManager
from app.services.session import RemoteSession
from tests.integration.support import make_config, testbed_connection

MESSAGE = "写入远端失败：与远端的连接已断开。"


class SessionMarkBrokenTests(unittest.TestCase):
    def setUp(self):
        self.known_hosts = Path(tempfile.mkdtemp(prefix="awfm-unit-")) / "known_hosts"
        self.config = make_config(
            self.known_hosts, connections=[testbed_connection(id="fake-broken")]
        )
        self.connection = self.config.connections[0]
        self.session = RemoteSession(self.connection)

    def test_state_becomes_error_and_the_reason_is_kept(self):
        status = self.session.mark_broken(MESSAGE)

        self.assertEqual(status["state"], "error")
        self.assertFalse(status["connected"])
        self.assertEqual(status["last_error"], MESSAGE)
        self.assertEqual(status, self.session.status())
        self.assertFalse(self.session.is_connected)

    def test_the_first_reason_wins(self):
        self.session.mark_broken(MESSAGE)

        self.session.mark_broken("后面那条只是同一个断链的余波。")

        self.assertEqual(self.session.status()["last_error"], MESSAGE)

    def test_client_is_refused_with_the_reason(self):
        self.session.mark_broken(MESSAGE)

        with self.assertRaises(NotConnected) as ctx:
            self.session.client
        self.assertEqual(ctx.exception.http_status, 409)
        self.assertEqual(ctx.exception.extra["connection_id"], self.connection.id)
        self.assertEqual(ctx.exception.detail, MESSAGE)

    def test_user_disconnect_still_clears_the_reason(self):
        self.session.mark_broken(MESSAGE)

        status = self.session.disconnect()

        self.assertEqual(status["state"], "disconnected")
        self.assertIsNone(status["last_error"])


class ManagerMarkBrokenTests(unittest.TestCase):
    def setUp(self):
        self.known_hosts = Path(tempfile.mkdtemp(prefix="awfm-unit-")) / "known_hosts"
        self.config = make_config(
            self.known_hosts,
            connections=[
                testbed_connection(id="fake-a"),
                testbed_connection(id="fake-b", port=2223),
            ],
        )
        self.manager = ConnectionManager(self.config)
        self.session = RemoteSession(self.config.connections[0])
        # 白盒：不为「标记」这点逻辑起一条真 SSH。
        self.manager._sessions["fake-a"] = self.session

    def test_marks_the_matching_session(self):
        self.manager.mark_broken("fake-a", NotConnected(MESSAGE))

        status = self.manager.session_status("fake-a")
        self.assertEqual(status["state"], "error")
        self.assertEqual(status["last_error"], MESSAGE)
        listing = {item["id"]: item["session"] for item in self.manager.list_connections()}
        self.assertEqual(listing["fake-a"]["state"], "error")
        self.assertEqual(listing["fake-b"]["state"], "disconnected")

    def test_unknown_or_blank_id_is_ignored(self):
        self.manager.mark_broken("nope", NotConnected(MESSAGE))
        self.manager.mark_broken(None, NotConnected(MESSAGE))

        self.assertEqual(self.manager.session_status("fake-a")["state"], "disconnected")

    def test_a_broken_session_is_no_longer_handed_out(self):
        self.manager.mark_broken("fake-a", NotConnected(MESSAGE))

        with self.assertRaises(SessionNotConnected) as ctx:
            self.manager.session("fake-a")
        self.assertEqual(ctx.exception.http_status, 404)
        self.assertEqual(ctx.exception.extra["connection_id"], "fake-a")


if __name__ == "__main__":
    unittest.main()
