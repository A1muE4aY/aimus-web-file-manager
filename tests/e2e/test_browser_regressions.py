"""浏览器回归测试（任务书 2.md 阶段一缺陷②③）。

两条都是 v0.1.0 的 Computer Use 验收里真实撞到的界面缺陷，必须在**真实浏览器**里钉住：

* 缺陷②：远端目录被删掉之后点「刷新」，页面报错却把上一次的列表留在屏幕上，看起来
  像它就是当前内容。修好之后这份列表必须被明确标成「已过期」，并给出重试入口。
* 缺陷③：已经有活动连接时新建一条连接，文件区会塌回占位页。修好之后新建连接不得
  影响正在浏览的那条连接。

浏览器是真实的 Edge：无头 + --inprivate + 全新临时配置目录，与端到端测试同一口径。
"""

import contextlib
import unittest
import urllib.parse
import uuid
from pathlib import Path

from tests.e2e.support import browser_session
from tests.integration.support import (
    require_testbed,
    running_server,
    testbed_connection,
    testbed_environment,
)

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
RUN_TAG = uuid.uuid4().hex[:8]
CONNECTION_ID = "e2e-regression"
CONNECTION_NAME = "回归测试床"
FIXTURE_DIR = "awfm-e2e-stale-" + RUN_TAG
FILE_NAME = "stale-" + RUN_TAG + ".txt"
# TEST-NET-1：写进配置但永远不会真的去连。
NEW_CONNECTION_HOST = "192.0.2.55"


def api(path: str) -> str:
    return "/api/connections/" + CONNECTION_ID + path


def row_expr(name: str) -> str:
    return "window.__awfm.rowNames().indexOf('" + name + "') >= 0"


def submit_new_connection_expr() -> str:
    """把「新增连接」表单填好并提交（表单输入没有 id，只能按在模态框里的顺序取）。"""
    return (
        "(function(){"
        "var boxes = document.querySelectorAll('#modal-body input[type=\"text\"]');"
        "boxes[0].value = '回归新增连接';"
        "boxes[1].value = '" + NEW_CONNECTION_HOST + "';"
        "boxes[2].value = 'nobody';"
        "document.querySelector('#modal-body input[type=\"number\"]').value = '22';"
        "document.querySelector('#modal-foot .btn-primary').click();"
        "return true;"
        "})()"
    )


@require_testbed
class BrowserRegressionTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.config, _ = self.stack.enter_context(
            testbed_environment(
                connections=[testbed_connection(id=CONNECTION_ID, name=CONNECTION_NAME)]
            )
        )
        self.client = self.stack.enter_context(running_server(self.config))
        self.base_url = self.client.base
        self.addCleanup(self._disconnect)
        response = self.client.post(api("/connect"), {})
        self.assertEqual(response.status, 200, response)
        session = self.client.manager.session(CONNECTION_ID)
        self.home = session.home
        self.remote_dir = self.home.rstrip("/") + "/" + FIXTURE_DIR
        with contextlib.suppress(Exception):
            session.client.mkdir(self.remote_dir)
        upload = self.client.request(
            "POST",
            api("/upload?path=" + urllib.parse.quote(self.remote_dir)
                + "&name=" + urllib.parse.quote(FILE_NAME)),
            body=b"stale list regression\n",
            headers={"Content-Type": "application/octet-stream"},
        )
        self.assertEqual(upload.status, 201, upload)
        self.addCleanup(self._remove_fixture)

    def _disconnect(self):
        with contextlib.suppress(Exception):
            self.client.post(api("/disconnect"), {})

    def _remove_fixture(self):
        with contextlib.suppress(Exception):
            client = self.client.manager.session(CONNECTION_ID).client
            with contextlib.suppress(Exception):
                client.remove(self.remote_dir + "/" + FILE_NAME)
            with contextlib.suppress(Exception):
                client.rmdir(self.remote_dir)

    def _drop_remote_dir(self):
        """模拟「页面背后远端目录被删掉」——不是页面自己能控制的动作。"""
        client = self.client.manager.session(CONNECTION_ID).client
        client.remove(self.remote_dir + "/" + FILE_NAME)
        client.rmdir(self.remote_dir)

    def _open_fixture_dir(self, page):
        page.navigate(self.base_url + "/")
        page.wait_for("!!document.getElementById('app') && !document.getElementById('app').hidden", message="页面外壳没有显示出来")
        page.install_helpers()
        # 后端已连接：页面启动时应当自动回到那条连接并列出家目录。
        page.wait_for(
            "document.querySelector('#conn-list .conn-item[data-state=\"connected\"]') !== null",
            timeout=90,
            message="页面没有恢复已连接的会话",
        )
        page.wait_for(row_expr(FIXTURE_DIR), timeout=90, message="家目录列表里没有夹具目录")
        self.assertTrue(page.evaluate("window.__awfm.openRow('" + FIXTURE_DIR + "')"))
        page.wait_for(row_expr(FILE_NAME), timeout=90, message="夹具目录里没有测试文件")

    def test_refresh_after_remote_deletion_marks_the_list_stale(self):
        with browser_session() as page:
            self._open_fixture_dir(page)

            self._drop_remote_dir()
            page.evaluate("document.getElementById('btn-refresh').click()")
            page.wait_for(
                "document.getElementById('list-stale').hidden === false",
                timeout=90,
                message="刷新失败之后没有出现过期提示",
            )

            # 过期必须看得出来：横幅、表格标记、计数后缀、错误提示。
            self.assertEqual(
                page.evaluate(
                    "document.querySelector('.table-wrap').getAttribute('data-stale')"
                ),
                "true",
            )
            self.assertIn("已过期", page.evaluate("document.getElementById('entry-count').innerText"))
            self.assertIn("路径不存在", page.evaluate("document.getElementById('notice').innerText"))
            # 但旧条目仍然在：既不假装读到了新内容，也不把用户看到的东西抹掉。
            self.assertTrue(page.evaluate(row_expr(FILE_NAME)))
            # 连接、当前路径、文件区都不能因为一次失败被清掉。
            self.assertTrue(
                page.evaluate(
                    "document.querySelector('#conn-list .conn-item[data-state=\"connected\"]') !== null"
                )
            )
            self.assertIn(FIXTURE_DIR, page.evaluate("document.getElementById('crumbs').innerText"))
            self.assertFalse(page.evaluate("document.getElementById('content').hidden"))

            shot = page.screenshot(ARTIFACTS_DIR / ("browser-stale-list-" + RUN_TAG + ".png"))
            self.assertGreater(shot.stat().st_size, 4096)

            # 回到上一级即可恢复：过期标记必须自己消失。
            page.evaluate("document.getElementById('btn-up').click()")
            page.wait_for(
                "document.getElementById('list-stale').hidden === true",
                timeout=90,
                message="回到有效目录后过期提示没有消失",
            )
            self.assertNotIn(
                "已过期", page.evaluate("document.getElementById('entry-count').innerText")
            )

    def test_new_connection_does_not_collapse_the_active_browsing_view(self):
        with browser_session() as page:
            self._open_fixture_dir(page)
            self.assertFalse(page.evaluate("document.getElementById('content').hidden"))
            self.assertTrue(page.evaluate("document.getElementById('placeholder').hidden"))

            page.evaluate("document.getElementById('btn-new-connection').click()")
            page.wait_for(
                "document.getElementById('modal-root').hidden === false",
                message="没有弹出新增连接表单",
            )
            self.assertEqual(
                page.evaluate("document.getElementById('modal-title').innerText"), "新增连接"
            )
            self.assertTrue(page.evaluate(submit_new_connection_expr()))

            page.wait_for(
                "document.querySelectorAll('#conn-list .conn-item').length === 2",
                timeout=90,
                message="新连接没有被加进列表",
            )
            # 文件区、活动连接、当前目录都必须原样留着（这就是缺陷③）。
            self.assertFalse(page.evaluate("document.getElementById('content').hidden"))
            self.assertTrue(page.evaluate("document.getElementById('placeholder').hidden"))
            self.assertEqual(
                page.evaluate(
                    "document.querySelector('#conn-list .conn-item[data-active=\"true\"]')"
                    ".getAttribute('data-id')"
                ),
                CONNECTION_ID,
            )
            self.assertTrue(page.evaluate(row_expr(FILE_NAME)))
            self.assertIn(FIXTURE_DIR, page.evaluate("document.getElementById('crumbs').innerText"))

            # 工具栏刷新 —— 当年正是这一步触发塌陷。
            page.evaluate("document.getElementById('btn-refresh').click()")
            page.wait_for(row_expr(FILE_NAME), timeout=90, message="刷新之后夹具文件不见了")

            # 连接状态轮询（窗口重新获得焦点时触发）不得改变上面的结论。
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            page.wait_for(
                "document.querySelectorAll('#conn-list .conn-item').length === 2",
                message="轮询之后连接列表变了",
            )
            self.assertFalse(page.evaluate("document.getElementById('content').hidden"))
            self.assertTrue(page.evaluate("document.getElementById('placeholder').hidden"))
            self.assertTrue(page.evaluate(row_expr(FILE_NAME)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
