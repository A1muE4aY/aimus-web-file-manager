"""写权限门禁的对抗性测试（规划文档 §10；任务书 2.md 阶段一）。

缺陷① 的修复把「会话持有的连接」从快照改成了可热更新的绑定。这个改动**不能**变成
「缓存里的开关是 true 就放行」：依据必须始终是当前配置，并且每一次写操作都重新取。

这里故意绕过界面与 HTTP 层，直接对着服务层的写入口打：先拿到一条已连接会话的引用，
再撤掉写权限，然后让那个**旧引用**继续尝试写。期望是越权路径全部抛 Unauthorized，
并且远端一个字节都不落 —— 连临时件（<名字>.awfm-part-*）都不许出现。
"""

from __future__ import annotations

import contextlib
import io
import unittest
from urllib.parse import quote

from app.core.errors import Unauthorized
from app.services.filesystem import require_write_permission
from app.services.transfer import receive_upload
from tests.integration.support import (
    require_testbed,
    running_server,
    testbed_connection,
    testbed_environment,
)

CONNECTION = "wsl-testbed"
SCRATCH = "/home/aimu/awfm-wp-security"


def api(path: str) -> str:
    return "/api/connections/" + CONNECTION + path


def upload_url(directory: str, name: str) -> str:
    return api("/upload?path=" + quote(directory, safe="") + "&name=" + quote(name, safe=""))


@require_testbed
class WriteGateHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._stack = contextlib.ExitStack()
        config, _keys = cls._stack.enter_context(
            testbed_environment(connections=[testbed_connection(allow_write=True)])
        )
        cls.client = cls._stack.enter_context(running_server(config))
        response = cls.client.post(api("/connect"))
        if not response.ok:
            cls._stack.close()
            raise AssertionError("测试床连接失败：" + repr(response))
        cls.session = cls.client.manager.session(CONNECTION)
        with contextlib.suppress(Exception):
            cls.session.client.mkdir(SCRATCH)

    @classmethod
    def tearDownClass(cls):
        with contextlib.suppress(Exception):
            for entry in cls.session.client.listdir(SCRATCH):
                with contextlib.suppress(Exception):
                    cls.session.client.remove(SCRATCH + "/" + entry.filename)
            cls.session.client.rmdir(SCRATCH)
        cls._stack.close()

    # -- 辅助 ------------------------------------------------------------

    def setUp(self):
        self.set_write(True)

    def set_write(self, value: bool) -> None:
        response = self.client.patch(api(""), {"allow_write": value})
        self.assertTrue(response.ok, response)

    def names(self):
        return sorted(entry.filename for entry in self.session.client.listdir(SCRATCH))

    def _remove(self, path: str) -> None:
        with contextlib.suppress(Exception):
            self.session.client.remove(path)

    # -- 用例 ------------------------------------------------------------

    def test_revoked_permission_blocks_the_old_session_reference(self):
        session = self.client.manager.session(CONNECTION)  # 故意先拿到「旧」引用
        self.set_write(False)

        with self.assertRaises(Unauthorized) as raised:
            require_write_permission(session, "上传文件")
        self.assertIn("未开启写权限", str(raised.exception))
        self.assertEqual(raised.exception.http_status, 401)

        # 上层 API 也必须一起被挡住（前端可用与否不构成授权）。
        denied = self.client.post(upload_url(SCRATCH, "escape.txt"), body=b"x")
        self.assertEqual(denied.status, 401, denied)
        self.assertEqual(denied.code, "unauthorized", denied)
        self.assertEqual(self.names(), [])

    def test_direct_upload_call_cannot_bypass_the_gate(self):
        session = self.client.manager.session(CONNECTION)
        self.set_write(False)
        payload = b"bypass" * 4

        with self.assertRaises(Unauthorized):
            receive_upload(
                session,
                SCRATCH,
                "bypass.txt",
                io.BytesIO(payload),
                content_length=len(payload),
            )

        self.assertEqual(self.names(), [], "越权上传必须连临时文件都不留")

    def test_granting_permission_reaches_an_already_open_session(self):
        session = self.client.manager.session(CONNECTION)
        self.set_write(False)
        with self.assertRaises(Unauthorized):
            require_write_permission(session, "上传文件")

        self.set_write(True)

        # 同一条会话、没有重连，权限必须已经生效。
        require_write_permission(session, "上传文件")
        target = SCRATCH + "/granted.txt"
        self.addCleanup(self._remove, target)
        uploaded = self.client.post(upload_url(SCRATCH, "granted.txt"), body=b"granted")
        self.assertEqual(uploaded.status, 201, uploaded)
        self.assertEqual(b"".join(session.client.download_chunks(target)), b"granted")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
