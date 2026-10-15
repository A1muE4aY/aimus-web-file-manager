"""写权限同步的集成测试（任务书 2.md 阶段一缺陷①）。

v0.1.0 的 CU 验收里出现过这条：界面打开「允许写操作」后立刻上传，服务端仍按建连时
的旧配置拒绝，必须先断开、再连接才好。这一组用例走真实 SSH/SFTP（WSL 测试床，
决策 D-012），并且**每一步都从 HTTP API 进入** —— 缺陷正好出在「配置改了、活动会话
不知道」这道缝里。
"""

from __future__ import annotations

import contextlib
import unittest
from urllib.parse import quote

from app.core.errors import SessionNotConnected
from tests.integration.support import (
    make_config,
    require_testbed,
    running_server,
    testbed_connection,
    testbed_environment,
)

CONNECTION = "wsl-testbed"
SCRATCH = "/home/aimu/awfm-wp-sync"


def api(path: str) -> str:
    return "/api/connections/" + CONNECTION + path


def upload_url(directory: str, name: str) -> str:
    return api("/upload?path=" + quote(directory, safe="") + "&name=" + quote(name, safe=""))


@require_testbed
class WritePermissionSyncTests(unittest.TestCase):
    """开工时连接是**关着写权限**的 —— 与验收现场一致。"""

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.config, _keys = self.stack.enter_context(
            testbed_environment(connections=[testbed_connection(allow_write=False)])
        )
        self.client = self.stack.enter_context(running_server(self.config))
        self.session = None
        self.addCleanup(self._teardown)

    # -- 夹具与辅助 ------------------------------------------------------

    def _teardown(self):
        if self.session is not None:
            with contextlib.suppress(Exception):
                for entry in self.session.client.listdir(SCRATCH):
                    with contextlib.suppress(Exception):
                        self.session.client.remove(SCRATCH + "/" + entry.filename)
                self.session.client.rmdir(SCRATCH)
        with contextlib.suppress(Exception):
            self.client.post(api("/disconnect"))

    def connect(self):
        response = self.client.post(api("/connect"))
        self.assertEqual(response.status, 200, response)
        self.session = self.client.manager.session(CONNECTION)
        with contextlib.suppress(Exception):
            self.session.client.mkdir(SCRATCH)
        return self.session

    def upload(self, name: str, body: bytes):
        return self.client.post(upload_url(SCRATCH, name), body=body)

    def remote_names(self):
        return sorted(entry.filename for entry in self.session.client.listdir(SCRATCH))

    def read_remote(self, name: str) -> bytes:
        return b"".join(self.session.client.download_chunks(SCRATCH + "/" + name))

    def session_state(self) -> str:
        response = self.client.get(api("/status"))
        self.assertTrue(response.ok, response)
        return response.data["connection"]["state"]

    def set_write(self, value: bool):
        response = self.client.patch(api(""), {"allow_write": value})
        self.assertTrue(response.ok, response)
        return response

    # -- 用例 ------------------------------------------------------------

    def test_write_permission_takes_effect_without_reconnecting(self):
        session = self.connect()

        denied = self.upload("blocked.txt", b"blocked\n")
        self.assertEqual(denied.status, 401, denied)
        self.assertEqual(denied.code, "unauthorized", denied)
        self.assertEqual(self.remote_names(), [], "被拒的上传不该在远端留下任何东西")

        self.set_write(True)

        # 关键：还是同一条会话（没有断开重连），上传立刻就能过。
        self.assertIs(self.client.manager.session(CONNECTION), session)
        self.assertEqual(self.session_state(), "connected")
        allowed = self.upload("allowed.txt", b"AWFM write permission\n")
        self.assertEqual(allowed.status, 201, allowed)
        self.assertEqual(self.read_remote("allowed.txt"), b"AWFM write permission\n")

    def test_revoking_write_permission_is_effective_immediately(self):
        session = self.connect()
        self.set_write(True)
        first = self.upload("on.txt", b"on\n")
        self.assertEqual(first.status, 201, first)

        self.set_write(False)

        denied = self.upload("off.txt", b"off\n")
        self.assertEqual(denied.status, 401, denied)
        self.assertEqual(denied.code, "unauthorized", denied)
        self.assertEqual(self.session_state(), "connected", "关写权限不该顺手把会话断掉")
        self.assertIs(self.client.manager.session(CONNECTION), session)
        self.assertEqual(self.remote_names(), ["on.txt"])

    def test_changing_connection_identity_drops_the_live_session(self):
        self.connect()
        self.assertEqual(self.session_state(), "connected")

        changed = self.client.patch(api(""), {"port": 2223})

        self.assertTrue(changed.ok, changed)
        self.assertEqual(self.session_state(), "disconnected", "连接参数变了，旧会话必须作废")
        with self.assertRaises(SessionNotConnected):
            self.client.manager.session(CONNECTION)

    def test_reload_applies_new_config_to_the_live_session(self):
        session = self.connect()
        denied = self.upload("before-reload.txt", b"nope\n")
        self.assertEqual(denied.code, "unauthorized", denied)

        # 模拟「配置文件被改过」：重新解析一份配置再 reload。
        reloaded = make_config(
            self.config.known_hosts_path,
            connections=[testbed_connection(allow_write=True)],
        )
        self.client.manager.reload(reloaded)

        self.assertIs(
            self.client.manager.session(CONNECTION), session, "只改行为开关不该重建会话"
        )
        allowed = self.upload("after-reload.txt", b"reloaded\n")
        self.assertEqual(allowed.status, 201, allowed)
        self.assertEqual(self.read_remote("after-reload.txt"), b"reloaded\n")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
