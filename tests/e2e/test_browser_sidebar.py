"""侧边栏布局与状态展示回归（任务书 2.md 阶段二）。

阶段二要求：暗色简洁风格下适度加宽左侧连接栏；卡片把「名称 / 用户名+主机+端口 /
认证方式 / 远端家目录 / 连接状态」和必要按钮都摆清楚；长名称与长路径要换行、限行或
悬浮提示，并且相互之间不能重叠；已连接 / 连接中 / 连接失败 / 已断开 四种状态要能一眼
分开；窄窗口不能让文件表格变得不可用。

这些都是「量元素盒子」才说得清的约束，所以放在真实浏览器里测：无头 Edge +
--inprivate + 全新临时配置目录，与其它 e2e 用例同一口径。
"""

import contextlib
import json
import unittest
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
CONNECTION_ID = "e2e-sidebar"
CONNECTION_NAME = "侧栏布局测试床"
# 故意造超长名称与超长主机名：长文本排版正是这一阶段要钉住的东西。
LONG_ID = "e2e-sidebar-long"
LONG_NAME = "名称特别长的一条连接用来检查侧边栏换行与省略是否会挤坏状态药丸-" + RUN_TAG
LONG_HOST = "very-long-hostname-for-sidebar-layout-check.example.internal"
DEAD_ID = "e2e-sidebar-dead"
DEAD_NAME = "连不上的测试目标"


def js(value: str) -> str:
    """把 Python 字符串写成 JS 字面量（省得手工拼引号）。"""
    return json.dumps(value, ensure_ascii=False)


def card_selector(connection_id: str) -> str:
    return "document.querySelector('#conn-list .conn-item[data-id=" + js(connection_id) + "]')"


def state_expr(connection_id: str) -> str:
    return card_selector(connection_id) + '.getAttribute("data-state")'


def metrics_expr(connection_id: str) -> str:
    """把一张卡片里所有要看的东西量成 JSON：盒子、文案、属性、按钮。"""
    return (
        "(function(){"
        "var card = " + card_selector(connection_id) + ";"
        "if (!card) { return JSON.stringify({missing: true}); }"
        "function box(el) { if (!el) { return null; } var r = el.getBoundingClientRect();"
        " return {left: r.left, top: r.top, right: r.right, bottom: r.bottom,"
        " width: r.width, height: r.height}; }"
        "var name = card.querySelector('.conn-name');"
        "var pill = card.querySelector('.pill');"
        "var target = card.querySelector('.conn-target');"
        "var home = card.querySelector('.conn-home-path');"
        "var note = card.querySelector('.conn-note');"
        "var buttons = Array.prototype.map.call(card.querySelectorAll('.conn-actions button'),"
        " function (b) { return {text: b.innerText.trim(), disabled: b.disabled, box: box(b),"
        ' title: b.getAttribute("title") || ""}; });'
        "return JSON.stringify({"
        " missing: false,"
        " card: box(card), name: box(name), pill: box(pill), target: box(target), home: box(home),"
        " buttons: buttons,"
        ' nameText: name.innerText.trim(), nameTitle: name.getAttribute("title") || "",'
        " nameLineHeight: parseFloat(getComputedStyle(name).lineHeight),"
        " pillText: pill.innerText.trim(), pillState: pill.getAttribute('data-state'),"
        " pillColor: getComputedStyle(pill).color,"
        ' pillTitle: pill.getAttribute("title") || "",'
        ' targetText: target.innerText.trim(), targetTitle: target.getAttribute("title") || "",'
        " metaText: card.querySelector('.conn-meta').innerText.trim(),"
        " homeText: home ? home.innerText.trim() : '',"
        " noteText: note ? note.innerText.trim() : ''"
        "});"
        "})()"
    )


def layout_expr() -> str:
    return (
        "(function(){"
        "var sidebar = document.querySelector('.sidebar');"
        "var wrap = document.querySelector('.table-wrap');"
        "var perm = document.querySelector('.col-perm');"
        "return JSON.stringify({"
        " sidebarWidth: sidebar.getBoundingClientRect().width,"
        " expectedWidth: Math.min(320, 0.42 * window.innerWidth),"
        " innerWidth: window.innerWidth,"
        " pageScrollWidth: document.documentElement.scrollWidth,"
        " tableClientWidth: wrap ? wrap.clientWidth : 0,"
        " permDisplay: perm ? getComputedStyle(perm).display : '',"
        " rows: document.querySelectorAll('#file-body tr').length,"
        " entryCount: document.getElementById('entry-count').innerText.trim(),"
        " contentHidden: document.getElementById('content').hidden"
        "});"
        "})()"
    )


def click_card_button_expr(connection_id: str, label: str) -> str:
    return (
        "(function(){"
        "var card = " + card_selector(connection_id) + ";"
        "if (!card) { return false; }"
        "var bs = card.querySelectorAll('.conn-actions button');"
        "for (var i = 0; i < bs.length; i += 1) {"
        " if (bs[i].innerText.trim() === " + js(label) + ") { bs[i].click(); return true; } }"
        "return false;"
        "})()"
    )


def overlaps(first, second, tolerance=1.0) -> bool:
    """两个盒子是否有实质重叠（给亚像素留一点余量）。"""
    if first is None or second is None:
        return False
    return (
        min(first["right"], second["right"]) - max(first["left"], second["left"]) > tolerance
        and min(first["bottom"], second["bottom"]) - max(first["top"], second["top"]) > tolerance
    )


def contained(inner, outer, tolerance=1.5) -> bool:
    """inner 是否整个落在 outer 里（同样留一点余量）。"""
    return (
        inner["left"] >= outer["left"] - tolerance
        and inner["right"] <= outer["right"] + tolerance
        and inner["top"] >= outer["top"] - tolerance
        and inner["bottom"] <= outer["bottom"] + tolerance
    )


@require_testbed
class BrowserSidebarTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.config, _ = self.stack.enter_context(
            testbed_environment(
                connections=[
                    testbed_connection(id=CONNECTION_ID, name=CONNECTION_NAME),
                    testbed_connection(id=LONG_ID, name=LONG_NAME, host=LONG_HOST),
                    testbed_connection(
                        id=DEAD_ID, name=DEAD_NAME, host="127.0.0.1", port=9, username="nobody"
                    ),
                ]
            )
        )
        self.client = self.stack.enter_context(running_server(self.config))
        self.base_url = self.client.base
        self.addCleanup(self._disconnect)
        response = self.client.post("/api/connections/" + CONNECTION_ID + "/connect", {})
        self.assertEqual(response.status, 200, response)
        self.home = self.client.manager.session(CONNECTION_ID).home

    def _disconnect(self):
        with contextlib.suppress(Exception):
            self.client.post("/api/connections/" + CONNECTION_ID + "/disconnect", {})

    def _open_page(self, page):
        page.navigate(self.base_url + "/")
        page.wait_for("!document.getElementById('app').hidden", message="页面外壳没有显示出来")
        page.install_helpers()
        page.wait_for(
            "document.querySelectorAll('#conn-list .conn-item').length === 3",
            timeout=90,
            message="侧栏没有列出三条连接",
        )
        page.wait_for(
            state_expr(CONNECTION_ID) + ' === "connected"',
            timeout=90,
            message="页面没有恢复已连接的会话",
        )
        page.wait_for(
            "document.querySelectorAll('#file-body tr').length > 0",
            timeout=90,
            message="文件表格没有列出任何条目",
        )

    def _metrics(self, page, connection_id):
        return json.loads(page.evaluate(metrics_expr(connection_id)))

    def _layout(self, page):
        return json.loads(page.evaluate(layout_expr()))

    def test_sidebar_cards_show_every_fact_and_keep_the_table_usable(self):
        """宽窗口：卡片摆全事实、按钮都在卡片里、文件表格照样宽裕。"""
        with browser_session(width=1400, height=900) as page:
            self._open_page(page)

            layout = self._layout(page)
            self.assertAlmostEqual(layout["sidebarWidth"], layout["expectedWidth"], delta=1.5)
            self.assertEqual(round(layout["sidebarWidth"]), 320)
            self.assertLessEqual(layout["pageScrollWidth"], layout["innerWidth"] + 1)
            self.assertGreaterEqual(layout["tableClientWidth"], 600)
            self.assertEqual(layout["permDisplay"], "table-cell")
            self.assertGreater(layout["rows"], 0)
            self.assertFalse(layout["contentHidden"])

            card = self._metrics(page, CONNECTION_ID)
            self.assertFalse(card["missing"])
            self.assertEqual(card["nameText"], CONNECTION_NAME)
            self.assertEqual(card["targetText"], "aimu@127.0.0.1:2222")
            self.assertEqual(card["targetTitle"], "aimu@127.0.0.1:2222")
            self.assertEqual(card["pillText"], "已连接")
            self.assertEqual(card["pillState"], "connected")
            self.assertIn("已连接", card["pillTitle"])
            self.assertIn("密钥认证", card["metaText"])
            self.assertEqual(card["homeText"], self.home)
            self.assertEqual(
                [button["text"] for button in card["buttons"]], ["浏览", "断开", "编辑", "删除"]
            )
            for button in card["buttons"]:
                self.assertFalse(button["disabled"], button)
                self.assertGreater(button["box"]["width"], 0, button)
                self.assertTrue(contained(button["box"], card["card"]), button)
                self.assertTrue(button["title"], button)
            # 名称与状态各占各的位置：长名称不得把药丸挤到卡片外面。
            self.assertFalse(overlaps(card["name"], card["pill"]))
            for key in ("name", "pill", "target", "home"):
                self.assertTrue(contained(card[key], card["card"]), key)

            shot = page.screenshot(ARTIFACTS_DIR / ("browser-sidebar-wide-" + RUN_TAG + ".png"))
            self.assertGreater(shot.stat().st_size, 4096)

    def test_long_name_and_host_wrap_without_overlapping(self):
        """超长名称与超长主机名：限行 + 折行 + 悬浮提示，谁也不压谁。"""
        with browser_session(width=1400, height=900) as page:
            self._open_page(page)

            card = self._metrics(page, LONG_ID)
            self.assertFalse(card["missing"])
            self.assertEqual(card["nameText"], LONG_NAME)
            self.assertEqual(card["nameTitle"], LONG_NAME)
            self.assertEqual(card["pillText"], "已断开")
            self.assertEqual(card["pillState"], "disconnected")
            self.assertIn(LONG_HOST, card["targetText"])
            self.assertEqual(card["targetTitle"], "aimu@" + LONG_HOST + ":2222")
            lines = card["name"]["height"] / card["nameLineHeight"]
            self.assertLessEqual(lines, 2.05, lines)
            self.assertGreaterEqual(lines, 1.0, lines)
            self.assertFalse(overlaps(card["name"], card["pill"]))
            self.assertFalse(overlaps(card["target"], card["pill"]))
            for key in ("name", "pill", "target"):
                self.assertTrue(contained(card[key], card["card"]), key)
            self.assertEqual(
                [button["text"] for button in card["buttons"]], ["连接", "编辑", "删除"]
            )
            for button in card["buttons"]:
                self.assertTrue(contained(button["box"], card["card"]), button)
            # 两种状态的药丸颜色必须真的不同，不能只差一个词。
            connected = self._metrics(page, CONNECTION_ID)
            self.assertNotEqual(card["pillColor"], connected["pillColor"])

            shot = page.screenshot(ARTIFACTS_DIR / ("browser-sidebar-longname-" + RUN_TAG + ".png"))
            self.assertGreater(shot.stat().st_size, 4096)

    def test_narrow_window_shrinks_the_sidebar_and_keeps_the_table_usable(self):
        """窄窗口：侧栏自己收窄、收起次要列，表格与按钮仍然可用。"""
        with browser_session(width=700, height=760) as page:
            self._open_page(page)

            layout = self._layout(page)
            self.assertAlmostEqual(layout["sidebarWidth"], layout["expectedWidth"], delta=1.5)
            self.assertLess(layout["sidebarWidth"], 320)
            self.assertGreaterEqual(layout["sidebarWidth"], 240)
            self.assertLessEqual(layout["pageScrollWidth"], layout["innerWidth"] + 1)
            # 窄窗口下权限/类型两列收起，但名称列与表格本身必须还在。
            self.assertEqual(layout["permDisplay"], "none")
            self.assertGreaterEqual(layout["tableClientWidth"], 300)
            self.assertGreater(layout["rows"], 0)
            self.assertFalse(layout["contentHidden"])

            card = self._metrics(page, CONNECTION_ID)
            for button in card["buttons"]:
                self.assertFalse(button["disabled"], button)
                self.assertTrue(contained(button["box"], card["card"]), button)
            self.assertFalse(overlaps(card["name"], card["pill"]))

            shot = page.screenshot(ARTIFACTS_DIR / ("browser-sidebar-narrow-" + RUN_TAG + ".png"))
            self.assertGreater(shot.stat().st_size, 4096)

    def test_failed_connection_shows_the_error_state_and_keeps_the_layout(self):
        """连接失败是第四种状态：必须显示成「连接失败」并带上具体错误。"""
        with browser_session(width=1400, height=900) as page:
            self._open_page(page)
            before = self._metrics(page, DEAD_ID)
            self.assertEqual(before["pillState"], "disconnected")

            self.assertTrue(page.evaluate(click_card_button_expr(DEAD_ID, "连接")))
            page.wait_for(
                state_expr(DEAD_ID) + ' === "error"',
                timeout=90,
                message="连不上的目标没有进入连接失败状态",
            )

            card = self._metrics(page, DEAD_ID)
            self.assertEqual(card["pillText"], "连接失败")
            self.assertIn("连接失败", card["pillTitle"])
            self.assertTrue(card["noteText"], "卡片刻没有留下具体错误信息")
            self.assertFalse(overlaps(card["name"], card["pill"]))
            for key in ("name", "pill", "target"):
                self.assertTrue(contained(card[key], card["card"]), key)
            for button in card["buttons"]:
                self.assertTrue(contained(button["box"], card["card"]), button)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
