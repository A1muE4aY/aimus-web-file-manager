"""文件列表布局与自定义右键菜单的端到端验证（任务书 0.1.2 阶段二 2.2~2.5）。

阶段二要的是三件事，都不是从 CSS 里读出来的结论：

* 操作按钮在任何一行都落在同一格 —— 目录行少了「编辑」、压缩包行多了「解压」，
  「重命名」的横坐标都必须是同一个数；
* 名字放不下时可以截断，但必须留一条看到完整名字的路（悬浮、键盘焦点、复制），
  而且截断只影响显示：请求里带的仍旧是真实名字；
* 右键要出我们自己的菜单，并且在输入框、编辑器里把原生菜单原样让回去。

真实浏览器：无头 Edge + --inprivate + 全新临时配置目录（与其它 e2e 同一口径）。
夹具摆在家目录下，像用户那样点进去，不直接改前端 state。
"""

from __future__ import annotations

import contextlib
import json
import unittest
import uuid
from pathlib import Path
from urllib.parse import quote

from tests.e2e.support import browser_session
from tests.integration.support import (
    LAYOUT_ARCHIVE,
    LAYOUT_BIG,
    LAYOUT_BROKEN_LINK,
    LAYOUT_LINK,
    LAYOUT_LONG_DIR,
    LAYOUT_LONG_EN,
    LAYOUT_LONG_ZH,
    LAYOUT_ODD_NAME,
    LAYOUT_OLD,
    LAYOUT_PERMS,
    LAYOUT_SHORT,
    LAYOUT_ZERO,
    layout_fixture,
    require_testbed,
    running_server,
    testbed_connection,
    testbed_environment,
)

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
RUN_TAG = uuid.uuid4().hex[:8]
CONNECTION_ID = "e2e-layout"
CONNECTION_NAME = "布局测试床"
READONLY_ID = "e2e-layout-ro"
READONLY_NAME = "布局测试床（只读）"

HOME_DIR = "/home/aimu"
FIXTURE_DIR = "awfm-e2e-layout-" + RUN_TAG
FIXTURE_ROOT = HOME_DIR + "/" + FIXTURE_DIR

MODAL_OPEN = "!document.getElementById('modal-root').hidden"
MODAL_CLOSED = "document.getElementById('modal-root').hidden === true"

#: 「操作」列固定七个槽位（v0.1.3 §1），顺序即 DOM 顺序：
#: 编辑→复制→剪切→重命名→删除→压缩→解压。不适用的动作仍然渲染成 disabled 按钮，
#: 所以每一行的七个槽位都在，位置不会因为文件类型不同而跳动。
WIDE_SLOTS = ("edit", "copy", "cut", "rename", "delete", "compress", "extract")

#: 右键菜单应有的项目（顺序即渲染顺序）。
PLAIN_FILE_MENU = ["预览", "编辑", "下载", "重命名", "压缩成 .tar.gz", "删除", "复制名称", "复制完整路径"]
ARCHIVE_MENU = ["预览", "编辑", "下载", "解压", "重命名", "压缩成 .tar.gz", "删除", "复制名称", "复制完整路径"]
DIR_MENU = ["打开目录", "重命名", "压缩成 .tar.gz", "删除", "复制名称", "复制完整路径"]
SYMLINK_MENU = ["打开（跟随符号链接）", "重命名", "压缩成 .tar.gz", "删除", "复制名称", "复制完整路径"]
READONLY_HINT = "需要先打开「允许写操作」"

KEY_CODES = {
    "Escape": ("Escape", 27),
    "Tab": ("Tab", 9),
    "Enter": ("Enter", 13),
    "Home": ("Home", 36),
    "End": ("End", 35),
    "ArrowDown": ("ArrowDown", 40),
    "ArrowUp": ("ArrowUp", 38),
}


def js(value: str) -> str:
    """把 Python 字符串写成 JS 字面量（中文与引号都不用手工转义）。"""
    return json.dumps(value, ensure_ascii=False)


def row_selector(name: str) -> str:
    return '#file-body tr[data-name="' + name + '"]'


def row_name_expr(name: str) -> str:
    return (
        "(function () {"
        "  var node = document.querySelector(" + js(row_selector(name) + " .entry-name") + ");"
        "  if (!node) { return null; }"
        "  return { truncated: node.getAttribute('data-truncated') === 'true',"
        "    tabindex: node.getAttribute('tabindex'),"
        "    text: node.textContent,"
        "    title: node.getAttribute('title'),"
        "    ariaLabel: node.getAttribute('aria-label'),"
        "    fullName: node.getAttribute('data-full-name'),"
        "    clientWidth: node.clientWidth, scrollWidth: node.scrollWidth };"
        "})()"
    )


def row_names_expr(name: str) -> str:
    return "window.__awfm.rowNames().indexOf(" + js(name) + ") >= 0"


def rect_expr(selector: str) -> str:
    return (
        "(function () {"
        "  var node = document.querySelector(" + js(selector) + ");"
        "  if (!node) { return null; }"
        "  var r = node.getBoundingClientRect();"
        "  return { left: r.left, top: r.top, right: r.right, bottom: r.bottom,"
        "    width: r.width, height: r.height,"
        "    cx: r.left + r.width / 2, cy: r.top + r.height / 2 };"
        "})()"
    )


def click_connect_expr(connection_id: str) -> str:
    selector = '#conn-list .conn-item[data-id="' + connection_id + '"] .conn-actions button'
    return "window.__awfm.clickByText(" + js(selector) + ", '连接')"


def click_menu_item_expr(label: str) -> str:
    """点菜单里某一项；禁用项返回 'disabled'（按钮被禁用时根本不会派发 click）。"""
    return (
        "(function () {"
        "  var menu = document.querySelector('.overlay-menu');"
        "  if (!menu) { return 'no-menu'; }"
        "  var items = menu.querySelectorAll('.overlay-menu-item');"
        "  for (var i = 0; i < items.length; i++) {"
        "    var node = items[i].querySelector('.overlay-menu-label');"
        "    if (!node || node.textContent !== " + js(label) + ") { continue; }"
        "    if (items[i].disabled) { return 'disabled'; }"
        "    items[i].click();"
        "    return 'clicked';"
        "  }"
        "  return 'missing';"
        "})()"
    )
    

def menu_item_state_expr(label: str) -> str:
    return (
        "(function () {"
        "  var menu = document.querySelector('.overlay-menu');"
        "  if (!menu) { return null; }"
        "  var items = menu.querySelectorAll('.overlay-menu-item');"
        "  for (var i = 0; i < items.length; i++) {"
        "    var node = items[i].querySelector('.overlay-menu-label');"
        "    if (!node || node.textContent !== " + js(label) + ") { continue; }"
        "    var hint = items[i].querySelector('.overlay-menu-hint');"
        "    var r = items[i].getBoundingClientRect();"
        "    return { disabled: items[i].disabled,"
        "      danger: items[i].classList.contains('is-danger'),"
        "      hint: hint ? hint.textContent : '',"
        "      left: Math.round(r.left), top: Math.round(r.top),"
        "      right: Math.round(r.right) };"
        "  }"
        "  return null;"
        "})()"
    )


def click_dialog_button_expr(text: str) -> str:
    return (
        "(function () {"
        "  var buttons = document.querySelectorAll('#modal-root button');"
        "  for (var i = 0; i < buttons.length; i++) {"
        "    if (buttons[i].textContent.trim() === " + js(text) + ") {"
        "      if (buttons[i].disabled) { return 'disabled'; }"
        "      buttons[i].click();"
        "      return 'clicked';"
        "    }"
        "  }"
        "  return 'missing';"
        "})()"
    )


#: 行内七个按钮的实际位置：同一个动作在所有行上必须落同一个数。
#: disabled 一起采集：不适用 ≠ 不存在，v0.1.3 起它们必须占着原来的格子。
SLOT_METRICS = (
    "(function () {"
    "  var out = [];"
    "  var rows = document.querySelectorAll('#file-body tr[data-name]');"
    "  for (var i = 0; i < rows.length; i++) {"
    "    var row = rows[i];"
    "    var box = row.querySelector('.file-actions-box');"
    "    if (!box) { continue; }"
    "    var actions = {};"
    "    var buttons = box.querySelectorAll('button[data-action]');"
    "    for (var j = 0; j < buttons.length; j++) {"
    "      var r = buttons[j].getBoundingClientRect();"
    "      actions[buttons[j].getAttribute('data-action')] = {"
    "        left: Math.round(r.left), right: Math.round(r.right),"
    "        top: Math.round(r.top), height: Math.round(r.height),"
    "        width: Math.round(r.width), disabled: buttons[j].disabled === true,"
    "        text: (buttons[j].textContent || '').trim() };"
    "    }"
    "    var nameRect = row.querySelector('.entry-name').getBoundingClientRect();"
    "    var boxRect = box.getBoundingClientRect();"
    "    out.push({ name: row.getAttribute('data-name'), type: row.getAttribute('data-type'),"
    "      actions: actions, nameRight: Math.round(nameRect.right),"
    "      actionsLeft: Math.round(boxRect.left), actionsRight: Math.round(boxRect.right),"
    "      rowHeight: Math.round(row.getBoundingClientRect().height) });"
    "  }"
    "  return out;"
    "})()"
)

TABLE_OVERFLOW = (
    "(function () {"
    "  var wrap = document.querySelector('.table-wrap');"
    "  if (!wrap) { return null; }"
    "  return { scrollWidth: wrap.scrollWidth, clientWidth: wrap.clientWidth,"
    "    bodyScrollWidth: document.body.scrollWidth, bodyClientWidth: document.body.clientWidth };"
    "})()"
)

MENU_BOX = (
    "(function () {"
    "  var menu = document.querySelector('.overlay-menu');"
    "  if (!menu) { return null; }"
    "  var r = menu.getBoundingClientRect();"
    "  return { left: r.left, top: r.top, right: r.right, bottom: r.bottom,"
    "    width: Math.round(r.width), height: Math.round(r.height),"
    "    count: document.querySelectorAll('.overlay-menu').length,"
    "    label: menu.getAttribute('aria-label'), role: menu.getAttribute('role'),"
    "    viewportWidth: window.innerWidth, viewportHeight: window.innerHeight };"
    "})()"
)

MENU_LABELS = (
    "(function () {"
    "  var menu = document.querySelector('.overlay-menu');"
    "  if (!menu) { return null; }"
    "  return Array.prototype.map.call("
    "    menu.querySelectorAll('.overlay-menu-item .overlay-menu-label'),"
    "    function (node) { return node.textContent; });"
    "})()"
)

TOOLTIP_STATE = (
    "(function () {"
    "  var node = document.querySelector('.overlay-tooltip');"
    "  if (!node) { return null; }"
    "  var r = node.getBoundingClientRect();"
    "  return { text: node.textContent, role: node.getAttribute('role'),"
    "    count: document.querySelectorAll('.overlay-tooltip').length,"
    "    left: Math.round(r.left), top: Math.round(r.top),"
    "    right: Math.round(r.right), bottom: Math.round(r.bottom),"
    "    viewportWidth: window.innerWidth, viewportHeight: window.innerHeight };"
    "})()"
)

#: 应用拦原生菜单时会 stopPropagation（overlay.js:245），冒泡阶段根本收不到事件。
#: 所以捕获阶段先把事件对象本身存下来 —— preventDefault 改的是这个对象上的标志，
#: 等事件派发完再读 defaultPrevented，一样能说明它到底拦没拦。
PROBE_CONTEXT_MENU = (
    "window.__awfmMenuProbe = [];"
    "window.addEventListener('contextmenu', function (event) {"
    "  window.__awfmMenuProbe.push(event);"
    "}, true);"
    "true"
)

PROBE_LAST_PREVENTED = (
    "(function () {"
    "  var event = window.__awfmMenuProbe[window.__awfmMenuProbe.length - 1];"
    "  return event ? event.defaultPrevented : null;"
    "})()"
)


#: 列表里「不属于任何条目」的一个点：表格下方优先，整张表铺满时退到表头那一行
#: （表头也不带 data-name，走的是同一套列表操作菜单）。
LIST_BACKGROUND_POINT = (
    "(function () {"
    "  var wrap = document.querySelector('.table-wrap');"
    "  if (!wrap) { return null; }"
    # 先把列表滚回顶部：表格铺满可视区时，只有表头那一行确定不属于任何条目，
    # 而表头会随滚动移出 wrap；不归位的话采样点会全部落在行上。
    "  wrap.scrollTop = 0;"
    "  var wr = wrap.getBoundingClientRect();"
    "  for (var k = 0; k < 24; k++) {"
    "    var y = wr.top + 3 + (wr.height - 6) * k / 23;"
    "    var node = document.elementFromPoint(wr.left + 14, y);"
    "    if (node && !(node.closest && node.closest('tr[data-name]'))) {"
    "      return { x: wr.left + 14, y: y };"
    "    }"
    "  }"
    "  return null;"
    "})()"
)


@require_testbed
class BrowserLayoutTests(unittest.TestCase):
    """需要真实测试床：真的渲染出来、真的点下去。"""

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.config, _keys = self.stack.enter_context(
            testbed_environment(
                connections=[
                    testbed_connection(id=CONNECTION_ID, name=CONNECTION_NAME),
                    testbed_connection(id=READONLY_ID, name=READONLY_NAME, allow_write=False),
                ]
            )
        )
        self.client = self.stack.enter_context(running_server(self.config))
        self.base_url = self.client.base
        self.stack.enter_context(layout_fixture(FIXTURE_ROOT))
        self.addCleanup(
            lambda: self.client.post("/api/connections/%s/disconnect" % CONNECTION_ID, {})
        )

    # ------------------------------------------------------------------ 助手
    def snap(self, page, name: str) -> Path:
        shot = page.screenshot(ARTIFACTS_DIR / ("browser-layout-" + name + "-" + RUN_TAG + ".png"))
        self.assertGreater(shot.stat().st_size, 4096, "截图太小，可能没画出来：" + str(shot))
        print("证据截图：" + str(shot))
        return shot

    def open_fixture_in_browser(self, page, *, connection_id: str = CONNECTION_ID):
        """从空白页开始：连上测试床，点进夹具目录 —— 走的是用户那条路。"""
        page.navigate(self.base_url + "/")
        page.wait_for("!!document.getElementById('app') && !document.getElementById('app').hidden", message="页面外壳没有显示出来")
        page.install_helpers()
        page.wait_for(
            "document.querySelectorAll('#conn-list .conn-item').length === 2",
            message="连接列表没有渲染出来",
        )
        self.assertTrue(page.evaluate(click_connect_expr(connection_id)), "没有找到连接按钮")
        page.wait_for(
            "!!document.querySelector("
            + js('#conn-list .conn-item[data-id="' + connection_id + '"][data-state="connected"]')
            + ")",
            timeout=90,
            message="浏览器里没有出现已连接状态",
        )
        page.wait_for(row_names_expr(FIXTURE_DIR), timeout=90, message="家目录里没有出现夹具目录")
        self.assertTrue(page.evaluate("window.__awfm.openRow(" + js(FIXTURE_DIR) + ")"))
        page.wait_for(
            "document.getElementById('crumbs').innerText.indexOf(" + js(FIXTURE_DIR) + ") >= 0",
            message="没有进入夹具目录",
        )
        page.wait_for(
            "document.querySelectorAll('#file-body tr[data-name]').length >= 14",
            timeout=60,
            message="夹具目录的条目没有渲染全",
        )

    def set_viewport(self, page, width: int, height: int = 900) -> None:
        page.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
        )
        page.evaluate("window.dispatchEvent(new Event('resize'))")
        page.wait_for(
            "window.innerWidth === %d" % width, timeout=15, message="视口宽度没有变成 %d" % width
        )

    def scroll_into_view(self, page, selector: str) -> None:
        """把目标滚进视野 —— 列表自己会滚，视口外面的点根本点不到。"""
        ok = page.evaluate(
            "(function () {"
            "  var node = document.querySelector(" + js(selector) + ");"
            "  if (!node) { return false; }"
            "  node.scrollIntoView({ block: 'center', inline: 'nearest' });"
            "  return true;"
            "})()"
        )
        self.assertTrue(ok, "没有找到要滚进视野的元素：" + selector)

    def list_background_point(self, page):
        """列表里不属于任何条目的一个点。"""
        point = page.evaluate(LIST_BACKGROUND_POINT)
        self.assertIsNotNone(point, "列表里找不到不属于条目的空白位置")
        return point

    def mouse(self, page, kind: str, x: float, y: float, *, button: str = "left", click_count: int = 1):
        page.send(
            "Input.dispatchMouseEvent",
            {
                "type": kind,
                "x": round(x),
                "y": round(y),
                "button": button,
                "buttons": 2 if button == "right" else (1 if kind == "mousePressed" else 0),
                "clickCount": click_count,
            },
        )

    def right_click(self, page, x: float, y: float):
        """真实右键：先移过去再按下、抬起（Chromium 会在抬起前派发 contextmenu）。"""
        self.mouse(page, "mouseMoved", x, y)
        self.mouse(page, "mousePressed", x, y, button="right")
        self.mouse(page, "mouseReleased", x, y, button="right")

    def left_click(self, page, x: float, y: float):
        self.mouse(page, "mouseMoved", x, y)
        self.mouse(page, "mousePressed", x, y)
        self.mouse(page, "mouseReleased", x, y)

    def move_mouse(self, page, x: float, y: float):
        self.mouse(page, "mouseMoved", x, y)

    def press_key(self, page, key: str):
        code, vk = KEY_CODES[key]
        params = {"key": key, "code": code, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
        page.send("Input.dispatchKeyEvent", dict(params, type="keyDown", text="\r" if key == "Enter" else ""))
        page.send("Input.dispatchKeyEvent", dict(params, type="keyUp"))

    def right_click_name(self, page, name: str):
        self.scroll_into_view(page, row_selector(name) + " .entry-name")
        box = page.evaluate(rect_expr(row_selector(name) + " .entry-name"))
        self.assertIsNotNone(box, "列表里没有这一行：" + name)
        self.right_click(page, box["cx"], box["cy"])
        return box

    def wait_for_toast(self, page, needle: str, *, timeout: int = 30) -> str:
        """等一条含指定文字的提示，并顺手钉住「提示里不能出现 undefined」。"""
        page.wait_for(
            "Array.prototype.some.call(document.querySelectorAll('#toasts .toast .toast-text'),"
            " function (n) { return n.textContent.indexOf(" + js(needle) + ") >= 0; })",
            timeout=timeout,
            message="没有出现包含「%s」的提示" % needle,
        )
        text = page.evaluate(
            "(function () {"
            "  var nodes = document.querySelectorAll('#toasts .toast .toast-text');"
            "  return nodes.length ? nodes[nodes.length - 1].textContent : '';"
            "})()"
        )
        self.assertNotIn("undefined", text, "界面提示里出现了 undefined：" + text)
        return text

    # ---------------------------------------------------------------- 用例一
    def test_action_buttons_sit_in_the_same_slot_on_every_row(self):
        """2.2：同一列的按钮在任何一行、任何类型下都落在同一个横坐标，且不压住名字。"""
        with browser_session() as page:
            self.open_fixture_in_browser(page)
            slots = page.evaluate(SLOT_METRICS)
            names = [row["name"] for row in slots]
            for expected in (LAYOUT_LONG_EN, LAYOUT_LONG_ZH, LAYOUT_ODD_NAME, LAYOUT_ARCHIVE,
                             LAYOUT_LONG_DIR, LAYOUT_LINK, LAYOUT_BROKEN_LINK, LAYOUT_BIG,
                             LAYOUT_ZERO, LAYOUT_OLD, *LAYOUT_PERMS):
                self.assertIn(expected, names, "夹具行没有渲染出来：" + expected)

            labels = {
                "edit": "编辑", "copy": "复制", "cut": "剪切", "rename": "重命名",
                "delete": "删除", "compress": "压缩", "extract": "解压",
            }
            # 每一行都必须是完整的七个槽位：不适用的动作禁用，但绝不消失 ——
            # 一消失，后面的按钮就往左跳，同屏里「删除」就会落在两个位置。
            for row in slots:
                self.assertEqual(
                    list(row["actions"].keys()),
                    list(WIDE_SLOTS),
                    "%s 的按钮顺序/数量不对：%r" % (row["name"], list(row["actions"].keys())),
                )
                for action in WIDE_SLOTS:
                    self.assertEqual(
                        row["actions"][action]["text"],
                        labels[action],
                        "%s 的「%s」槽位文字不对" % (row["name"], action),
                    )

            for action in WIDE_SLOTS:
                rows = [row for row in slots if action in row["actions"]]
                self.assertTrue(rows, "没有任何一行带「%s」按钮" % action)
                lefts = sorted({row["actions"][action]["left"] for row in rows})
                self.assertEqual(
                    len(lefts),
                    1,
                    "「%s」在不同行上横坐标不一致：%r（行数 %d）" % (action, lefts, len(rows)),
                )
                widths = sorted({row["actions"][action]["width"] for row in rows})
                self.assertEqual(len(widths), 1, "「%s」按钮宽度不一致：%r" % (action, widths))
                heights = sorted({row["actions"][action]["height"] for row in rows})
                self.assertEqual(len(heights), 1, "「%s」按钮高度不一致：%r" % (action, heights))

            # 七个槽位排在同一行：同一条记录里，七个按钮的纵向位置必须一致
            # （跨记录比 top 没有意义，每条记录本来就在不同的行上）。
            for row in slots:
                row_tops = sorted({row["actions"][action]["top"] for action in WIDE_SLOTS})
                self.assertEqual(
                    len(row_tops), 1, "%s 的七个按钮不在同一行：%r" % (row["name"], row_tops)
                )

            # 不适用 ≠ 不存在：目录/符号链接的「编辑」、普通文件的「解压」都在，只是禁用。
            by_name = {row["name"]: row for row in slots}
            self.assertTrue(
                by_name[LAYOUT_LONG_DIR]["actions"]["edit"]["disabled"], "目录行的「编辑」应当禁用"
            )
            self.assertTrue(
                by_name[LAYOUT_LINK]["actions"]["edit"]["disabled"], "符号链接行的「编辑」应当禁用"
            )
            self.assertFalse(
                by_name[LAYOUT_SHORT]["actions"]["edit"]["disabled"], "普通文件的「编辑」应当可点"
            )
            self.assertTrue(
                by_name[LAYOUT_SHORT]["actions"]["extract"]["disabled"], "普通文件的「解压」应当禁用"
            )
            self.assertFalse(
                by_name[LAYOUT_ARCHIVE]["actions"]["extract"]["disabled"],
                "压缩包行的「解压」应当可点",
            )
            for other in (LAYOUT_LONG_DIR, LAYOUT_LINK, LAYOUT_ARCHIVE, LAYOUT_BIG):
                self.assertEqual(
                    by_name[other]["actions"]["rename"]["left"],
                    by_name[LAYOUT_SHORT]["actions"]["rename"]["left"],
                    "「重命名」在 %s 与普通文件上不在同一格" % other,
                )

            # 宽窗下七个动作按设计顺序排开（编辑→复制→剪切→重命名→删除→压缩→解压）。
            archive = by_name[LAYOUT_ARCHIVE]["actions"]
            order = [archive[key]["left"] for key in WIDE_SLOTS]
            self.assertEqual(order, sorted(order), "七个槽位的左右顺序不对：%r" % order)

            # 按钮不许压住名字列：每一行名字的右边界都要在按钮组左边之内。
            for row in slots:
                self.assertLessEqual(
                    row["nameRight"],
                    row["actionsLeft"],
                    "按钮压住了名称列：" + row["name"],
                )

            overflow = page.evaluate(TABLE_OVERFLOW)
            self.assertLessEqual(
                overflow["scrollWidth"],
                overflow["clientWidth"] + 1,
                "宽窗下表格出现了横向溢出：%r" % overflow,
            )
            self.snap(page, "slots")

    # ---------------------------------------------------------------- 用例二
    def test_long_names_truncate_but_keep_a_way_to_read_them(self):
        """2.3：截断只发生在显示层；悬浮、键盘焦点、title/aria-label 都拿得到全名。"""
        with browser_session() as page:
            self.open_fixture_in_browser(page)
            # 缩到 CU 证据里那个窄窗（1240 物理 ÷ 1.25 = 992 CSS）再来验截断。
            self.set_viewport(page, 992, 700)
            page.wait_for(
                "document.querySelectorAll('#file-body tr[data-name]').length >= 14",
                timeout=30,
                message="窄窗下条目没有渲染全",
            )

            for name in (LAYOUT_LONG_EN, LAYOUT_LONG_ZH):
                state = page.evaluate(row_name_expr(name))
                self.assertTrue(state["truncated"], "窄窗下这个长名字没有被标记为截断：" + name)
                self.assertGreater(
                    state["scrollWidth"], state["clientWidth"], "名字并没有真的溢出：" + name
                )
                self.assertEqual(state["text"], name, "显示层的文本被改过了：" + name)
                self.assertEqual(state["title"], name, "title 不是完整名字：" + name)
                self.assertEqual(state["ariaLabel"], name, "aria-label 不是完整名字：" + name)
                self.assertEqual(state["fullName"], name, "data-full-name 不是完整名字：" + name)
                self.assertEqual(state["tabindex"], "0", "被截断的名字应该可以 Tab 到：" + name)

            # 没被截断的名字不该多出一个 Tab 停留点。
            short = page.evaluate(row_name_expr(LAYOUT_SHORT))
            self.assertFalse(short["truncated"], "短名字不该被标记为截断")
            self.assertIsNone(short["tabindex"], "没截断的名字不该有 tabindex")

            # 键鼠两条路都要能看到完整名字：先鼠标悬浮。
            self.scroll_into_view(page, row_selector(LAYOUT_LONG_EN) + " .entry-name")
            box = page.evaluate(rect_expr(row_selector(LAYOUT_LONG_EN) + " .entry-name"))
            self.move_mouse(page, box["cx"], box["cy"])
            page.wait_for("!!document.querySelector('.overlay-tooltip')", message="悬浮没有出现完整名称提示")
            tip = page.evaluate(TOOLTIP_STATE)
            self.assertEqual(tip["text"], LAYOUT_LONG_EN, "提示里的名字不是完整的")
            self.assertEqual(tip["role"], "tooltip", "完整名称提示缺少 tooltip 角色")
            self.assertEqual(tip["count"], 1, "同时出现了多个完整名称提示")
            self.assertGreaterEqual(tip["left"], 0, "提示跑到了视口左边之外")
            self.assertLessEqual(tip["right"], tip["viewportWidth"], "提示跑到了视口右边之外")
            self.assertLessEqual(tip["bottom"], tip["viewportHeight"], "提示跑到了视口下边之外")
            self.snap(page, "tooltip-hover")

            self.move_mouse(page, 6, 6)  # 挪到页面角上，既不在名字上也不在提示上
            page.wait_for("!document.querySelector('.overlay-tooltip')", message="鼠标移开后提示没有消失")

            # 再看键盘：焦点进名字显示，焦点离开就收掉（不依赖鼠标）。
            page.evaluate("document.querySelector(" + js(row_selector(LAYOUT_LONG_ZH) + " .entry-name") + ").focus()")
            page.wait_for("!!document.querySelector('.overlay-tooltip')", message="键盘聚焦没有出现完整名称提示")
            self.assertEqual(page.evaluate(TOOLTIP_STATE)["text"], LAYOUT_LONG_ZH, "键盘路径拿到的不是全名")
            page.evaluate(
                "document.querySelector("
                + js(row_selector(LAYOUT_LONG_ZH) + " .entry-name")
                + ").blur()"
            )
            page.wait_for("!document.querySelector('.overlay-tooltip')", message="焦点离开后提示没有消失")

            # 完整名字在菜单里也拿得到，而且文件名与完整路径分得清。
            self.right_click_name(page, LAYOUT_LONG_ZH)
            page.wait_for("!!document.querySelector('.overlay-menu')", message="长名字行右键没有出菜单")
            copy_name = page.evaluate(menu_item_state_expr("复制名称"))
            copy_path = page.evaluate(menu_item_state_expr("复制完整路径"))
            self.assertEqual(copy_name["hint"], "只复制文件名", "「复制名称」的说明不对")
            self.assertEqual(
                copy_path["hint"],
                FIXTURE_ROOT + "/" + LAYOUT_LONG_ZH,
                "「复制完整路径」的说明里不是条目的真实路径",
            )
            self.snap(page, "menu-long-name")

    # ---------------------------------------------------------------- 用例三
    def test_truncated_name_still_travels_as_the_real_name(self):
        """2.3：截断只影响显示 —— 请求参数里带的必须是完整名字（含中文）。"""
        with browser_session() as page:
            self.open_fixture_in_browser(page)
            self.set_viewport(page, 992, 700)

            # 中文名的预览：请求路径里应当出现完整的（编码后的）中文文件名。
            self.right_click_name(page, LAYOUT_LONG_ZH)
            page.wait_for("!!document.querySelector('.overlay-menu')", message="右键没有出菜单")
            self.assertEqual(page.evaluate(click_menu_item_expr("预览")), "clicked")
            page.wait_for(MODAL_OPEN, timeout=60, message="预览对话框没有打开")
            quoted = quote(LAYOUT_LONG_ZH, safe="")
            self.assertTrue(
                any(quoted in url for url in page.requests()),
                "预览请求里没有出现完整的中文文件名：" + quoted,
            )
            self.assertEqual(page.evaluate(click_dialog_button_expr("关闭")), "clicked", "预览框没有「关闭」按钮")
            page.wait_for(MODAL_CLOSED)

            # 英文名的编辑：这个请求走的是同一套「真实名字」参数。
            self.assertTrue(
                page.evaluate(
                    "(function () {"
                    "  var row = document.querySelector(" + js(row_selector(LAYOUT_LONG_EN)) + ");"
                    "  if (!row) { return false; }"
                    "  var button = row.querySelector('.btn-edit-entry');"
                    "  if (!button) { return false; }"
                    "  button.click();"
                    "  return true;"
                    "})()"
                ),
                "长英文名行没有「编辑」按钮",
            )
            page.wait_for(
                "document.getElementById('editor-text') !== null",
                timeout=60,
                message="编辑器没有打开",
            )
            self.assertEqual(
                page.evaluate("document.getElementById('editor-text').value"),
                "x\n",
                "打开的并不是那个长名字文件的内容",
            )
            self.assertTrue(
                any(quote(LAYOUT_LONG_EN, safe="") in url for url in page.requests()),
                "编辑请求里没有出现完整的长英文文件名",
            )
            self.snap(page, "editor-long-name")
            self.assertTrue(page.evaluate(click_dialog_button_expr("取消")))
            page.wait_for(MODAL_CLOSED)

            # 右键菜单里的「重命名」也必须带着真实名字（不是相邻那一行）。
            self.right_click_name(page, LAYOUT_LONG_EN)
            page.wait_for("!!document.querySelector('.overlay-menu')", message="右键没有出菜单")
            self.assertEqual(page.evaluate(click_menu_item_expr("重命名")), "clicked")
            page.wait_for(
                "document.getElementById('rename-input') !== null",
                timeout=30,
                message="重命名对话框没有打开",
            )
            self.assertEqual(
                page.evaluate("document.getElementById('rename-input').value"),
                LAYOUT_LONG_EN,
                "重命名对话框里没有带上完整的真实名字",
            )
            self.snap(page, "rename-long-name")
            self.assertEqual(page.evaluate(click_dialog_button_expr("取消")), "clicked")
            page.wait_for(MODAL_CLOSED)

    # ---------------------------------------------------------------- 用例四
    def test_context_menu_replaces_the_native_one_and_targets_the_row(self):
        """2.5①②：行上右键出的是我们自己的菜单，而且认得出是哪一条目。"""
        with browser_session() as page:
            self.open_fixture_in_browser(page)
            page.evaluate(PROBE_CONTEXT_MENU)

            cases = (
                (LAYOUT_SHORT, PLAIN_FILE_MENU),
                (LAYOUT_ARCHIVE, ARCHIVE_MENU),
                (LAYOUT_LONG_DIR, DIR_MENU),
                (LAYOUT_BROKEN_LINK, SYMLINK_MENU),
            )
            for name, expected in cases:
                box = self.right_click_name(page, name)
                page.wait_for("!!document.querySelector('.overlay-menu')", message="右键没有出菜单：" + name)
                self.assertEqual(page.evaluate(MENU_LABELS), expected, "菜单项目不对：" + name)
                self.assertEqual(
                    page.evaluate(PROBE_LAST_PREVENTED),
                    True,
                    "原生右键菜单没有被拦下来：" + name,
                )
                menu = page.evaluate(MENU_BOX)
                self.assertEqual(menu["count"], 1, "同时出现了多个菜单")
                self.assertEqual(menu["role"], "menu", "菜单缺少 menu 角色")
                self.assertEqual(menu["label"], "文件操作", "菜单没有标明它管的是文件操作")
                self.assertGreaterEqual(menu["left"], 0, "菜单左侧超出视口")
                self.assertGreaterEqual(menu["top"], 0, "菜单上侧超出视口")
                self.assertLessEqual(menu["right"], menu["viewportWidth"], "菜单右侧被裁切：" + name)
                self.assertLessEqual(menu["bottom"], menu["viewportHeight"], "菜单下侧被裁切：" + name)
                self.assertLessEqual(
                    abs(menu["left"] - box["cx"]),
                    40,
                    "菜单没有出现在鼠标附近：" + name,
                )
                self.press_key(page, "Escape")
                page.wait_for("!document.querySelector('.overlay-menu')", message="Escape 没有关掉菜单")

            # 菜单项走的还是既有业务：重命名对话框里预填的就是刚才右键的那一行。
            self.right_click_name(page, LAYOUT_ARCHIVE)
            page.wait_for("!!document.querySelector('.overlay-menu')", message="右键没有出菜单")
            self.assertEqual(page.evaluate(click_menu_item_expr("重命名")), "clicked")
            page.wait_for("document.getElementById('rename-input') !== null", message="重命名对话框没有打开")
            self.assertEqual(
                page.evaluate("document.getElementById('rename-input').value"),
                LAYOUT_ARCHIVE,
                "菜单认错了目标：重命名对话框里的名字不是右键的那一条",
            )
            self.snap(page, "menu-target")
            self.assertEqual(page.evaluate(click_dialog_button_expr("取消")), "clicked")
            page.wait_for(MODAL_CLOSED)

            # 空白处的右键给的是列表自己的操作，不是某一条目的。
            counter = page.evaluate(rect_expr("#entry-count"))
            self.left_click(page, counter["cx"], counter["cy"])  # 先把焦点从菜单上挪开
            blank = self.list_background_point(page)
            self.right_click(page, blank["x"], blank["y"])
            page.wait_for("!!document.querySelector('.overlay-menu')", message="空白处右键没有出菜单")
            labels = page.evaluate(MENU_LABELS)
            self.assertIn("刷新列表", labels, "空白处菜单里没有「刷新列表」：%r" % labels)
            self.assertNotIn("复制名称", labels, "空白处菜单冒充了某个条目：%r" % labels)
            self.assertEqual(page.evaluate(MENU_BOX)["label"], "列表操作", "空白处菜单的角色标错了")
            self.snap(page, "menu-blank")
            self.press_key(page, "Escape")

    # ---------------------------------------------------------------- 用例五
    def test_menu_closes_on_escape_outside_click_and_directory_change(self):
        """2.5④ + 键盘：三种关闭路径都要真的关掉，菜单也要能用键盘走。"""
        with browser_session() as page:
            self.open_fixture_in_browser(page)

            # Escape
            self.right_click_name(page, LAYOUT_SHORT)
            page.wait_for("!!document.querySelector('.overlay-menu')", message="右键没有出菜单")
            self.press_key(page, "Escape")
            page.wait_for("!document.querySelector('.overlay-menu')", message="Escape 没有关掉菜单")
            self.assertIsNone(page.evaluate(MENU_BOX))

            # 点外部：点的是列表下方的条目计数，既不该导航也不该开新对话框。
            self.right_click_name(page, LAYOUT_SHORT)
            page.wait_for("!!document.querySelector('.overlay-menu')", message="右键没有出菜单")
            crumbs_before = page.evaluate("document.getElementById('crumbs').innerText")
            counter = page.evaluate(rect_expr("#entry-count"))
            self.left_click(page, counter["cx"], counter["cy"])
            page.wait_for("!document.querySelector('.overlay-menu')", message="点外部没有关掉菜单")
            self.assertEqual(
                page.evaluate("document.getElementById('crumbs').innerText"),
                crumbs_before,
                "点外部那一下不该改变当前目录",
            )
            self.assertTrue(page.evaluate(MODAL_CLOSED), "点外部不该弹出对话框")

            # 键盘：End 走到最后一项（复制完整路径），回车执行，提示里要带上真实路径。
            self.right_click_name(page, LAYOUT_LONG_EN)
            page.wait_for("!!document.querySelector('.overlay-menu')", message="右键没有出菜单")
            self.press_key(page, "End")
            self.press_key(page, "Enter")
            page.wait_for("!document.querySelector('.overlay-menu')", message="回车没有关掉菜单")
            text = self.wait_for_toast(page, FIXTURE_ROOT + "/" + LAYOUT_LONG_EN)
            self.assertTrue(
                text.startswith("已复制路径") or "不允许自动复制" in text,
                "复制完整路径的提示不对劲：" + text,
            )

            # 切换目录：菜单与提示都要收掉（阶段二 2.5 明写的一条）。
            self.right_click_name(page, LAYOUT_LONG_EN)
            page.wait_for("!!document.querySelector('.overlay-menu')", message="右键没有出菜单")
            self.assertTrue(page.evaluate("window.__awfm.openRow(" + js(LAYOUT_LONG_DIR) + ")"))
            page.wait_for(
                "document.getElementById('crumbs').innerText.indexOf(" + js(LAYOUT_LONG_DIR) + ") >= 0",
                timeout=60,
                message="没有进入子目录",
            )
            self.assertEqual(
                page.evaluate("document.querySelectorAll('.overlay-menu').length"),
                0,
                "切换目录之后菜单还挂在屏幕上",
            )
            self.assertEqual(
                page.evaluate("document.querySelectorAll('.overlay-tooltip').length"),
                0,
                "切换目录之后完整名称提示还挂在屏幕上",
            )
            self.snap(page, "closed-after-navigation")

    # ---------------------------------------------------------------- 用例六
    def test_inputs_and_editor_keep_the_native_context_menu(self):
        """2.5⑤：搜索框与编辑器里必须把原生菜单让回去，一个自绘菜单也不能冒出来。"""
        with browser_session() as page:
            self.open_fixture_in_browser(page)
            page.evaluate(PROBE_CONTEXT_MENU)

            search = page.evaluate(rect_expr("#search-input"))
            self.right_click(page, search["cx"], search["cy"])
            page.wait_for(
                "window.__awfmMenuProbe.length === 1", timeout=15, message="搜索框右键没有派发 contextmenu"
            )
            self.assertFalse(
                page.evaluate("window.__awfmMenuProbe[0].defaultPrevented"),
                "搜索框里原生右键菜单被拦掉了",
            )
            self.assertEqual(
                page.evaluate("document.querySelectorAll('.overlay-menu').length"),
                0,
                "搜索框上冒出了自绘菜单",
            )
            self.assertEqual(
                page.evaluate("document.activeElement.id"), "search-input", "右键没有落在搜索框上"
            )

            # 编辑器：打开一个文件，在文本域里右键，同样要保留原生菜单。
            self.assertTrue(
                page.evaluate(
                    "(function () {"
                    "  var row = document.querySelector(" + js(row_selector(LAYOUT_SHORT)) + ");"
                    "  if (!row) { return false; }"
                    "  var button = row.querySelector('.btn-edit-entry');"
                    "  if (!button) { return false; }"
                    "  button.click();"
                    "  return true;"
                    "})()"
                )
            )
            page.wait_for(
                "document.getElementById('editor-text') !== null", timeout=60, message="编辑器没有打开"
            )
            area = page.evaluate(rect_expr("#editor-text"))
            self.right_click(page, area["cx"], area["cy"])
            page.wait_for(
                "window.__awfmMenuProbe.length === 2", timeout=15, message="编辑器里右键没有派发 contextmenu"
            )
            self.assertFalse(
                page.evaluate("window.__awfmMenuProbe[1].defaultPrevented"),
                "编辑器文本区里原生右键菜单被拦掉了",
            )
            self.assertEqual(
                page.evaluate("document.querySelectorAll('.overlay-menu').length"),
                0,
                "编辑器里冒出了自绘菜单",
            )
            self.snap(page, "native-in-editor")

            # 内容没改过，取消应当直接关掉，不该再问一句。
            self.assertTrue(page.evaluate(click_dialog_button_expr("取消")))
            page.wait_for(MODAL_CLOSED, timeout=15, message="取消没有关掉编辑器")

    # ---------------------------------------------------------------- 用例七
    def test_readonly_connection_disables_write_items_with_a_reason(self):
        """2.5⑥：只读连接上写操作灰掉并说明原因；点了也不会真的动远端。"""
        with browser_session() as page:
            self.open_fixture_in_browser(page, connection_id=READONLY_ID)
            self.right_click_name(page, LAYOUT_SHORT)
            page.wait_for("!!document.querySelector('.overlay-menu')", message="右键没有出菜单")

            for label in ("预览", "编辑", "下载", "复制名称", "复制完整路径"):
                state = page.evaluate(menu_item_state_expr(label))
                self.assertFalse(state["disabled"], "只读连接上「%s」不该被禁用" % label)
            for label in ("重命名", "压缩成 .tar.gz", "删除"):
                state = page.evaluate(menu_item_state_expr(label))
                self.assertTrue(state["disabled"], "只读连接上「%s」应当灰掉" % label)
                self.assertEqual(state["hint"], READONLY_HINT, "「%s」没有说明为什么不能点" % label)
            self.assertTrue(page.evaluate(menu_item_state_expr("删除"))["danger"], "删除项应当是危险样式")

            # 禁用项点不动：菜单还开着，也没有弹出任何对话框。
            self.assertEqual(page.evaluate(click_menu_item_expr("删除")), "disabled")
            self.assertTrue(page.evaluate("!!document.querySelector('.overlay-menu')"), "禁用项不该关掉菜单")
            self.assertTrue(page.evaluate(MODAL_CLOSED), "禁用项不该弹出删除确认框")
            self.press_key(page, "Escape")
            page.wait_for("!document.querySelector('.overlay-menu')")

            # 列表空白处也一样：只读连接不能上传。
            blank = self.list_background_point(page)
            self.right_click(page, blank["x"], blank["y"])
            page.wait_for("!!document.querySelector('.overlay-menu')", message="空白处右键没有出菜单")
            upload = page.evaluate(menu_item_state_expr("上传文件…"))
            self.assertTrue(upload["disabled"], "只读连接上「上传文件…」应当灰掉")
            self.assertEqual(upload["hint"], READONLY_HINT)
            self.snap(page, "readonly-menu")

    # ---------------------------------------------------------------- 用例八
    def test_narrow_window_and_zoom_keep_the_actions_inside(self):
        """2.4：窄窗与浏览器缩放（150%）下按断点收列，按钮仍留在视口里。"""
        with browser_session() as page:
            self.open_fixture_in_browser(page)

            # 1240x900 物理窗口（截图 1238x898）在 1.25 缩放下等于 992 CSS 宽。
            self.set_viewport(page, 992, 700)
            self.assertEqual(
                page.evaluate(
                    "(function () {"
                    "  var th = document.querySelector('#file-table thead th.col-perm');"
                    "  return th ? getComputedStyle(th).display : 'missing';"
                    "})()"
                ),
                "none",
                "窄窗下权限列没有收起来",
            )
            self.assertEqual(
                page.evaluate(
                    "(function () {"
                    "  var th = document.querySelector('#file-table thead th.col-type');"
                    "  return th ? getComputedStyle(th).display : 'missing';"
                    "})()"
                ),
                "none",
                "窄窗下类型列没有收起来",
            )
            self.assertEqual(
                page.evaluate(
                    "(function () {"
                    "  var th = document.querySelector('#file-table thead th.col-time');"
                    "  return th ? getComputedStyle(th).display : 'missing';"
                    "})()"
                ),
                "none",
                "窄窗下修改时间列没有收起来",
            )
            slots = page.evaluate(SLOT_METRICS)
            # 992 CSS 宽只收起三列（权限/类型/修改时间），七个槽位仍然一行放得下：
            # 折行会改变行高，同屏里就能看出「有的行高一点」。
            for action in WIDE_SLOTS:
                rows = [row for row in slots if action in row["actions"]]
                lefts = sorted({row["actions"][action]["left"] for row in rows})
                self.assertEqual(len(lefts), 1, "窄窗下「%s」横坐标不一致：%r" % (action, lefts))
            for row in slots:
                row_tops = sorted({row["actions"][action]["top"] for action in WIDE_SLOTS})
                self.assertEqual(
                    len(row_tops), 1, "窄窗下 %s 的七个按钮不在同一行：%r" % (row["name"], row_tops)
                )
                self.assertEqual(
                    list(row["actions"].keys()),
                    list(WIDE_SLOTS),
                    "窄窗下 %s 的槽位不全：%r" % (row["name"], list(row["actions"].keys())),
                )
                self.assertLessEqual(
                    row["actionsRight"],
                    page.evaluate("window.innerWidth"),
                    "窄窗下按钮跑出了视口：" + row["name"],
                )
            overflow = page.evaluate(TABLE_OVERFLOW)
            self.assertLessEqual(
                overflow["scrollWidth"],
                overflow["clientWidth"] + 1,
                "窄窗下表格出现了横向滚动：%r" % overflow,
            )
            self.snap(page, "narrow")

            # 页面放大 150%（编辑器缩放到 150%）后 CSS 视口只剩约 660px。
            self.set_viewport(page, 661, 500)
            page.wait_for(
                "document.querySelectorAll('#file-body tr[data-name]').length >= 14",
                timeout=30,
                message="缩放后条目没有渲染全",
            )
            self.assertEqual(
                page.evaluate(
                    "(function () {"
                    "  var th = document.querySelector('#file-table thead th.col-time');"
                    "  return th ? getComputedStyle(th).display : 'missing';"
                    "})()"
                ),
                "none",
                "150% 缩放下修改时间列没有收起来",
            )
            self.assertEqual(
                page.evaluate(
                    "(function () {"
                    "  var th = document.querySelector('#file-table thead th.col-size');"
                    "  return th ? getComputedStyle(th).display : 'missing';"
                    "})()"
                ),
                "none",
                "150% 缩放下大小列没有收起来",
            )
            name_width = page.evaluate(
                "document.querySelector('#file-body .col-name').getBoundingClientRect().width"
            )
            # 661 CSS 视口下表格只剩「名称 / 操作」两列，名字列仍要够读出开头几个字
            # （实测约 110px = 图标 + 约 8 个字符），而不是被压缩到看不见。
            self.assertGreaterEqual(name_width, 88, "150%% 缩放下名字列被压得只剩 %r" % name_width)

            # 七个槽位这时折成 4 + 3 两行，块级网格里每一行仍是固定槽位：
            # 同一个动作在所有行上落同样的 (left, top)，第二行与第一行逐列对齐。
            zoom_slots = page.evaluate(SLOT_METRICS)
            for action in WIDE_SLOTS:
                lefts = sorted({row["actions"][action]["left"] for row in zoom_slots})
                self.assertEqual(len(lefts), 1, "150%% 缩放下「%s」横坐标不一致：%r" % (action, lefts))
                # 行的绝对纵向位置随记录变化，能比的是「相对本行第一格偏了多少」。
                offsets = sorted({
                    row["actions"][action]["top"] - row["actions"]["edit"]["top"]
                    for row in zoom_slots
                })
                self.assertEqual(
                    len(offsets),
                    1,
                    "150%% 缩放下「%s」相对行首的纵向偏移不一致：%r" % (action, offsets),
                )
            for row in zoom_slots:
                acts = row["actions"]
                row_tops = sorted({acts[key]["top"] for key in WIDE_SLOTS})
                self.assertEqual(
                    len(row_tops), 2, "150%% 缩放下 %s 的槽位没有折成两行：%r" % (row["name"], row_tops)
                )
                # 7 个槽位按顺序填满 4 列：第二行从「删除」起，逐格与第一行对齐。
                self.assertEqual(acts["delete"]["left"], acts["edit"]["left"], "第二行第一格没对齐")
                self.assertEqual(acts["compress"]["left"], acts["copy"]["left"], "第二行第二格没对齐")
                self.assertEqual(acts["extract"]["left"], acts["cut"]["left"], "第二行第三格没对齐")
            for row in zoom_slots:
                self.assertLessEqual(
                    row["actionsRight"],
                    page.evaluate("window.innerWidth"),
                    "150% 缩放下按钮跑出了视口：" + row["name"],
                )
            overflow = page.evaluate(TABLE_OVERFLOW)
            self.assertLessEqual(
                overflow["scrollWidth"],
                overflow["clientWidth"] + 1,
                "150%% 缩放下表格出现了横向滚动：%r" % overflow,
            )
            state = page.evaluate(row_name_expr(LAYOUT_LONG_EN))
            self.assertTrue(state["truncated"], "150% 缩放下长名字应当被截断")
            self.snap(page, "zoom150")
            page.send("Emulation.clearDeviceMetricsOverride")


if __name__ == "__main__":
    unittest.main()
