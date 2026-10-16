"""端到端测试：真实浏览器 → 本机服务 → SSH/SFTP → 真实远程目录。

覆盖规划文档 §7.2 的端到端层级，以及 T-002（页面离线加载）、T-006（目录浏览）、
T-007（中文与空格文件名）、T-005（主机密钥确认）与 T-012（无外部请求）。

浏览器是真实的 Edge：无头 + --inprivate + 全新临时配置目录。需要 WSL 测试床
（决策 D-012）；测试床不可用时跳过而不是失败，与集成测试同一口径。
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
from tests.security.support import DEAD_CONNECTION, local_server

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
RUN_TAG = uuid.uuid4().hex[:8]
CONNECTION_ID = "e2e"
CONNECTION_NAME = "端到端测试床"
FIXTURE_DIR = "awfm-e2e-" + RUN_TAG
SPACED_NAME = "标记 名称 " + RUN_TAG + ".txt"
PLAIN_NAME = "plain-" + RUN_TAG + ".txt"
BODY_TEXT = "awfm end to end 内容\n"
PASSWORD_SENTINEL = "awfm-e2e-password-sentinel-3f91"

LOCAL_SCHEMES = ("http://", "https://")


def click_connect_button(connection_id: str = CONNECTION_ID) -> str:
    selector = "#conn-list .conn-item[data-id=\"" + connection_id + "\"] .conn-actions button"
    return "window.__awfm.clickByText('" + selector + "', '连接')"


@require_testbed
class BrowserJourneyTests(unittest.TestCase):
    """需要真实测试床：浏览器里真的走一遍 SSH 连接与目录浏览。"""

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
        self._connect_backend()

    # ------------------------------------------------------------------ 夹具
    def _connect_backend(self):
        response = self.client.post("/api/connections/" + CONNECTION_ID + "/connect", {})
        self.assertEqual(response.status, 200, response)
        self.addCleanup(
            lambda: self.client.post("/api/connections/" + CONNECTION_ID + "/disconnect", {})
        )
        session = self.client.manager.session(CONNECTION_ID)
        self.home = session.home
        self.assertTrue(self.home, "连接成功却没有家目录")
        self.remote_dir = self.home.rstrip("/") + "/" + FIXTURE_DIR
        session.client.mkdir(self.remote_dir)
        self.addCleanup(self._remove_fixture)
        for name, text in ((SPACED_NAME, BODY_TEXT), (PLAIN_NAME, "plain\n")):
            upload = self.client.request(
                "POST",
                "/api/connections/" + CONNECTION_ID
                + "/upload?path=" + urllib.parse.quote(self.remote_dir)
                + "&name=" + urllib.parse.quote(name),
                body=text.encode("utf-8"),
                headers={"Content-Type": "application/octet-stream"},
            )
            self.assertEqual(upload.status, 201, upload)
        # 夹具建好后立刻断开：让浏览器从「未连接」开始，才走得到用户点「连接」
        # 这条路（后端仍连着的话，页面启动时会自动回到那条连接）。
        disconnect = self.client.post("/api/connections/" + CONNECTION_ID + "/disconnect", {})
        self.assertEqual(disconnect.status, 200, disconnect)

    def _remove_fixture(self):
        # 清理时可能已经断开（主机密钥那条用例会主动断开），先按需重连一次。
        with contextlib.suppress(Exception):
            self.client.post("/api/connections/" + CONNECTION_ID + "/connect", {})
        with contextlib.suppress(Exception):
            client = self.client.manager.session(CONNECTION_ID).client
            for name in (SPACED_NAME, PLAIN_NAME):
                with contextlib.suppress(Exception):
                    client.remove(self.remote_dir + "/" + name)
            with contextlib.suppress(Exception):
                client.rmdir(self.remote_dir)

    # ------------------------------------------------------------------ 用例
    def test_browser_can_connect_and_browse_a_real_remote_directory(self):
        with browser_session() as page:
            page.navigate(self.base_url + "/")

            # 令牌由后端注入 index.html；页面外壳必须显示出来（T-002）。
            page.wait_for(
                "!!document.getElementById('app') && !document.getElementById('app').hidden", message="页面外壳没有显示出来"
            )
            page.install_helpers()
            token = page.evaluate("document.querySelector('meta[name=\"awfm-token\"]').content")
            self.assertEqual(token, self.client.token)
            self.assertFalse(page.evaluate("document.getElementById('placeholder').hidden"))

            # 连接列表来自后端配置（GET /api/connections）。
            page.wait_for(
                "document.querySelectorAll('#conn-list .conn-item').length === 1",
                message="连接列表没有渲染出唯一的测试连接",
            )
            self.assertIn(CONNECTION_NAME, page.evaluate("document.getElementById('conn-list').innerText"))

            # 用户点「连接」：真实 SSH 建连（T-003）。
            self.assertTrue(page.evaluate(click_connect_button()), "没有找到连接按钮")
            page.wait_for(
                "document.querySelector('#conn-list .conn-item[data-state=\"connected\"]') !== null",
                timeout=90,
                message="浏览器里没有出现已连接状态",
            )

            # 家目录列表里应当有夹具目录（T-006）。
            page.wait_for(
                "window.__awfm.rowNames().indexOf('" + FIXTURE_DIR + "') >= 0",
                timeout=90,
                message="家目录列表里没有夹具目录",
            )

            # 双击进入目录：中文与空格文件名必须原样显示（T-007）。
            self.assertTrue(page.evaluate("window.__awfm.openRow('" + FIXTURE_DIR + "')"))
            page.wait_for(
                "window.__awfm.rowNames().indexOf('" + SPACED_NAME + "') >= 0",
                timeout=90,
                message="夹具目录里没有中文与空格文件名",
            )
            names = page.evaluate("window.__awfm.rowNames()")
            self.assertIn(PLAIN_NAME, names)
            self.assertIn(FIXTURE_DIR, page.evaluate("document.getElementById('crumbs').innerText"))
            self.assertRegex(
                page.evaluate("document.getElementById('entry-count').innerText") or "",
                r"[0-9]",
                "状态栏应当报告条目数",
            )

            # 回到上一级（T-006 的返回上级）。
            page.evaluate("document.getElementById('btn-up').click()")
            page.wait_for(
                "window.__awfm.rowNames().indexOf('" + FIXTURE_DIR + "') >= 0",
                timeout=90,
                message="返回上一级后没有回到家目录",
            )

            # 页面运行期间不得对外发起任何请求（T-002 / T-012）。
            external = [
                url
                for url in page.requests()
                if url.startswith(LOCAL_SCHEMES) and not url.startswith(self.base_url)
            ]
            self.assertEqual(external, [], "页面发起了对外部地址的请求")
            self.assertTrue(
                [url for url in page.requests() if url.startswith(self.base_url)],
                "没有观察到任何本地 API 请求",
            )

            # 凭据纪律：令牌只在 meta 里，不进 cookie、不进任何浏览器存储（T-011）。
            self.assertNotIn(self.client.token, page.evaluate("document.cookie"))
            self.assertEqual(page.evaluate("Object.keys(window.localStorage).length"), 0)
            self.assertEqual(page.evaluate("Object.keys(window.sessionStorage).length"), 0)

            # 证据：截图落到 tests/e2e/artifacts/（运行产物）。
            shot = page.screenshot(ARTIFACTS_DIR / ("browser-journey-" + RUN_TAG + ".png"))
            self.assertGreater(shot.stat().st_size, 4096)
            print("证据截图：" + str(shot))

    def test_browser_confirms_first_time_host_key(self):
        # 这一条要的是「首次连接」：把信任库换成空的（T-005）。
        self.client.post("/api/connections/" + CONNECTION_ID + "/disconnect", {})
        self.config.known_hosts_path.unlink()
        with browser_session() as page:
            page.navigate(self.base_url + "/")
            page.wait_for("!!document.getElementById('app') && !document.getElementById('app').hidden", message="页面外壳没有显示出来")
            page.install_helpers()
            self.assertTrue(page.evaluate(click_connect_button()), "没有找到连接按钮")

            # 后端拒绝静默信任：浏览器必须先看到指纹确认框。
            page.wait_for(
                "document.getElementById('modal-root').hidden === false",
                timeout=90,
                message="首次连接没有弹出主机密钥确认框",
            )
            self.assertEqual(
                page.evaluate("document.getElementById('modal-title').innerText"),
                "首次连接，请核对主机指纹",
            )
            modal_text = page.evaluate("document.getElementById('modal-body').innerText")
            self.assertIn("SHA256:", modal_text)
            self.assertIn("ssh-keygen -lf", modal_text)

            # 点「指纹一致，信任并继续」后必须真的连上。
            self.assertTrue(
                page.evaluate("window.__awfm.clickByText('#modal-foot button', '指纹一致，信任并继续')")
            )
            page.wait_for(
                "document.querySelector('#conn-list .conn-item[data-state=\"connected\"]') !== null",
                timeout=90,
                message="信任指纹之后没有连上",
            )
            page.wait_for(
                "window.__awfm.rowNames().indexOf('" + FIXTURE_DIR + "') >= 0",
                timeout=90,
                message="信任指纹之后没有列出家目录",
            )
            self.assertTrue(self.config.known_hosts_path.is_file(), "信任结果没有落到信任库")


class BrowserPasswordPromptTests(unittest.TestCase):
    """不需要测试床：只看「连不上」时浏览器怎么表现，以及密码去了哪里。"""

    def test_password_is_asked_then_failure_is_shown_and_not_persisted(self):
        with local_server() as harness:
            with browser_session() as page:
                page.navigate(harness.client.base + "/")
                page.wait_for("!!document.getElementById('app') && !document.getElementById('app').hidden", message="页面外壳没有显示出来")
                page.install_helpers()
                page.wait_for(
                    "document.querySelectorAll('#conn-list .conn-item').length === 1",
                    message="连接列表没有渲染出连接",
                )

                # 密码认证必须先弹对话框（密码不落配置，D-014）。
                page.evaluate(
                    "window.__awfm.clickByText('#conn-list .conn-item .conn-actions button', '连接')"
                )
                page.wait_for(
                    "document.getElementById('modal-root').hidden === false",
                    message="密码认证没有弹出密码对话框",
                )
                self.assertIn("密码", page.evaluate("document.getElementById('modal-title').innerText"))

                # 端口 9 是 discard，连接必然失败；失败必须在页面上报出来。
                page.evaluate(
                    "document.getElementById('conn-password').value = '" + PASSWORD_SENTINEL + "'"
                )
                page.evaluate("window.__awfm.clickByText('#modal-foot button', '连接')")
                page.wait_for(
                    "document.getElementById('toasts').innerText.trim().length > 0",
                    timeout=120,
                    message="连接失败没有在页面上报错",
                )
                self.assertFalse(
                    page.evaluate(
                        "document.querySelector('#conn-list .conn-item[data-state=\"connected\"]') !== null"
                    ),
                    "端口 9 上不可能连上",
                )

                # 失败必须是结构化错误（502/504），不能是 500「未预期异常」。
                # 2026-10-15 的真实缺陷：known_hosts 里把 http_status 当构造参数传，
                # 连不上的主机会抛 TypeError，对外变成 internal_error/500。
                # 注意用 endswith："/api/connections" 里也含 "/connect" 子串。
                connect_statuses = [
                    status for status, url in page.responses() if url.endswith("/connect")
                ]
                self.assertTrue(connect_statuses, "没有观察到连接请求的响应")
                self.assertIn(
                    connect_statuses[-1],
                    (502, 504),
                    "连不上的主机应当报 remote_error/timeout，而不是 " + str(connect_statuses[-1]),
                )

                # 密码既不在页面里，也不在磁盘上。
                self.assertNotIn(PASSWORD_SENTINEL, page.evaluate("document.cookie"))
                self.assertEqual(page.evaluate("Object.keys(window.localStorage).length"), 0)
                # 配置由 make_config 在内存里构造、未必落盘，所以直接扫整个夹具
                # 目录：任何文件都不该出现密码。
                leaked = []
                for path in Path(harness.tmp).rglob("*"):
                    if not path.is_file():
                        continue
                    try:
                        text = path.read_text(encoding="utf-8", errors="ignore")
                    except OSError:
                        continue
                    if PASSWORD_SENTINEL in text:
                        leaked.append(str(path))
                self.assertEqual(leaked, [], "密码被写进了磁盘文件")
                self.assertEqual(DEAD_CONNECTION["port"], 9)
