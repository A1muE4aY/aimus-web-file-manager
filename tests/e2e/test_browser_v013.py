"""v0.1.3 新增界面能力的端到端验证：新建、多选、复制粘贴、预览独立框（任务书 §3/§4）。

这一组要证明的是「远端真的变了」，而不是「JS 里有个函数」：

* 点「新建文件」建出来的是远端同一目录下一个 0 字节的真实文件；
* 同名再建一次被服务端拒绝，原文件一个字节都没变；
* 勾选两行 → 复制 → 进另一个目录 → 粘贴，目标目录里真的多了两个文件；
* 长文本预览进的是自己的框，滚动发生在框里，弹窗没有被撑破。

真实浏览器：无头 Edge + --inprivate + 全新临时配置目录（与其它 e2e 同一口径）。
夹具摆在家目录下，像用户那样点进去，不直接改前端 state。
"""

from __future__ import annotations

import contextlib
import json
import shlex
import unittest
import uuid
from pathlib import Path

from tests.e2e.support import browser_session
from tests.integration.support import (
    LAYOUT_BIG,
    LAYOUT_LONG_DIR,
    LAYOUT_OLD,
    LAYOUT_SHORT,
    connection_url,
    layout_fixture,
    require_testbed,
    running_server,
    testbed_command,
    testbed_connection,
    testbed_environment,
)

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
RUN_TAG = uuid.uuid4().hex[:8]
CONNECTION_ID = "e2e-v013"
CONNECTION_NAME = "v0.1.3 测试床"
READONLY_ID = "e2e-v013-ro"
READONLY_NAME = "v0.1.3 测试床（只读）"

HOME_DIR = "/home/aimu"
FIXTURE_DIR = "awfm-e2e-v013-" + RUN_TAG
FIXTURE_ROOT = HOME_DIR + "/" + FIXTURE_DIR

#: 长文本预览的素材：行数够多，58vh 的正文框一定装不下。
LONG_TEXT_NAME = "long-preview.txt"
LONG_TEXT_LINES = 400

#: 在测试床上现生成长文本（rw 字符串：\n 要原样交给 awk 的 printf）。
_LONG_TEXT_SCRIPT = r"""
set -e
awk 'BEGIN { for (i = 1; i <= __LINES__; i++) printf "第 %03d 行：这是一段用来把预览框撑长一点的中文内容。\n", i }' > __TARGET__
echo READY
"""

MODAL_OPEN = "!document.getElementById('modal-root').hidden"
MODAL_CLOSED = "document.getElementById('modal-root').hidden === true"


def js(value: str) -> str:
    """把 Python 字符串写成 JS 字面量（中文与引号都不用手工转义）。"""
    return json.dumps(value, ensure_ascii=False)


def row_names_expr(name: str) -> str:
    return "window.__awfm.rowNames().indexOf(" + js(name) + ") >= 0"


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


def set_create_name_expr(name: str) -> str:
    return (
        "(function () {"
        "  var input = document.getElementById('create-name');"
        "  if (!input) { return false; }"
        "  input.value = " + js(name) + ";"
        "  return true;"
        "})()"
    )


def status_text_expr(status_id: str) -> str:
    return (
        "(function () {"
        "  var node = document.getElementById(" + js(status_id) + ");"
        "  return node ? node.textContent : null;"
        "})()"
    )


#: 预览框的实际几何：正文框自己滚、弹窗没被撑破。
PREVIEW_METRICS = (
    "(function () {"
    "  var root = document.getElementById('modal-root');"
    "  var box = root.querySelector('.preview-box');"
    "  var body = root.querySelector('.preview-box-body');"
    "  var head = root.querySelector('.preview-box-head');"
    "  var pre = root.querySelector('.preview-text');"
    "  var modal = root.querySelector('.modal');"
    "  if (!box || !body || !head || !pre || !modal) { return null; }"
    "  var bodyRect = body.getBoundingClientRect();"
    "  var headRect = head.getBoundingClientRect();"
    "  var modalRect = modal.getBoundingClientRect();"
    "  return { overflowY: getComputedStyle(body).overflowY,"
    "    scrollHeight: body.scrollHeight, clientHeight: body.clientHeight,"
    "    bodyWidth: body.clientWidth, preWidth: pre.getBoundingClientRect().width,"
    "    preScrollWidth: pre.scrollWidth,"
    "    headBottom: headRect.bottom, bodyTop: bodyRect.top,"
    "    insideModal: bodyRect.right <= modalRect.right + 1"
    "      && bodyRect.bottom <= modalRect.bottom + 1,"
    "    modalRight: modalRect.right, bodyRight: bodyRect.right,"
    "    bodyBottom: bodyRect.bottom, modalBottom: modalRect.bottom,"
    "    textLength: pre.textContent.length };"
    "})()"
)

TOAST_TEXT = (
    "(function () {"
    "  var nodes = document.querySelectorAll('#toasts .toast');"
    "  var out = [];"
    "  for (var i = 0; i < nodes.length; i++) { out.push(nodes[i].textContent); }"
    "  return out.join(String.fromCharCode(10));"
    "})()"
)


@require_testbed
class BrowserV013Tests(unittest.TestCase):
    """需要真实测试床：真的点下去、真的去远端核对。"""

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
        self.stack.enter_context(self.long_text_fixture())
        self.addCleanup(
            lambda: self.client.post("/api/connections/%s/disconnect" % CONNECTION_ID, {})
        )

    # ------------------------------------------------------------------ 夹具
    @contextlib.contextmanager
    def long_text_fixture(self):
        """往夹具目录里放一个四百行的长文本 —— 预览框会不会溢出全看它。"""
        # 内容在测试床上用 awk 现生成：HTTP 上传要求连接已经建立，而「先连上再点」
        # 正是浏览器用例要走的路；把几十 KB 的正文塞进 ssh 命令行又会超长（WinError 206）。
        target = FIXTURE_ROOT + "/" + LONG_TEXT_NAME
        testbed_command(
            _LONG_TEXT_SCRIPT.replace("__LINES__", str(LONG_TEXT_LINES)).replace(
                "__TARGET__", shlex.quote(target)
            )
        )
        yield target
        testbed_command("rm -f " + shlex.quote(target), check=False)

    def listing(self, directory: str) -> dict:
        response = self.client.get(connection_url(CONNECTION_ID, "files", path=directory))
        self.assertEqual(response.status, 200, "取目录列表失败：%r" % (response,))
        return {item["name"]: item for item in response.data["entries"]}

    # ------------------------------------------------------------------ 助手
    def snap(self, page, name: str) -> Path:
        shot = page.screenshot(ARTIFACTS_DIR / ("browser-v013-" + name + "-" + RUN_TAG + ".png"))
        self.assertGreater(shot.stat().st_size, 4096, "截图太小，可能没画出来：" + str(shot))
        print("证据截图：" + str(shot))
        return shot

    def open_fixture_in_browser(self, page, *, connection_id: str = CONNECTION_ID):
        """从空白页开始：连上测试床，点进夹具目录 —— 走的是用户那条路。"""
        page.navigate(self.base_url + "/")
        page.wait_for(
            "!!document.getElementById('app') && !document.getElementById('app').hidden",
            message="页面外壳没有显示出来",
        )
        page.install_helpers()
        page.wait_for(
            "document.querySelectorAll('#conn-list .conn-item').length === 2",
            message="连接列表没有渲染出来",
        )
        self.assertTrue(
            page.evaluate(
                "window.__awfm.clickByText("
                + js('#conn-list .conn-item[data-id="' + connection_id + '"] .conn-actions button')
                + ", '连接')"
            ),
            "没有找到连接按钮",
        )
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

    def click_row(self, page, name: str) -> None:
        """点一下某一行（选中它，工具栏按钮随之可用）。"""
        ok = page.evaluate(
            "(function () {"
            "  var row = document.querySelector(" + js('#file-body tr[data-name="' + name + '"]') + ");"
            "  if (!row) { return false; }"
            "  row.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));"
            "  return true;"
            "})()"
        )
        self.assertTrue(ok, "列表里没有这一行：" + name)

    def click_toolbar(self, page, button_id: str) -> str:
        return page.evaluate(
            "(function () {"
            "  var node = document.getElementById(" + js(button_id) + ");"
            "  if (!node) { return 'missing'; }"
            "  if (node.disabled) { return 'disabled'; }"
            "  node.click();"
            "  return 'clicked';"
            "})()"
        )

    def fill_create_name(self, page, name: str) -> None:
        page.wait_for("!!document.getElementById('create-name')", message="新建对话框没有出现")
        self.assertTrue(page.evaluate(set_create_name_expr(name)), "没有找到名称输入框")

    def submit_create(self, page) -> str:
        outcome = page.evaluate(click_dialog_button_expr("创建"))
        self.assertNotEqual(outcome, "missing", "新建对话框里没有「创建」按钮")
        return outcome

    # ---------------------------------------------------------------- 用例一
    def test_create_empty_file_and_folder_land_on_the_remote(self):
        """§4 验收：普通空文件、中文名带空格与括号、创建后刷新确认真实存在且 0 字节。"""
        with browser_session() as page:
            self.open_fixture_in_browser(page)
            before = self.listing(FIXTURE_ROOT)

            file_name = "新建 空文件 (v0.1.3).txt"
            self.assertEqual(self.click_toolbar(page, "btn-new-file"), "clicked", "「新建文件」按不动")
            self.fill_create_name(page, file_name)
            self.assertEqual(self.submit_create(page), "clicked")
            page.wait_for(MODAL_CLOSED, message="创建成功后对话框没有关掉")
            page.wait_for(row_names_expr(file_name), timeout=30, message="新建的文件没有出现在列表里")

            listing = self.listing(FIXTURE_ROOT)
            self.assertIn(file_name, listing, "远端没有这个文件")
            self.assertEqual(listing[file_name]["size"], 0, "新建出来不是 0 字节")
            self.assertEqual(listing[file_name]["type"], "file")
            self.assertEqual(len(listing), len(before) + 1)

            folder_name = "新建 文件夹 (v0.1.3)"
            self.assertEqual(
                self.click_toolbar(page, "btn-new-folder"), "clicked", "「新建文件夹」按不动"
            )
            self.fill_create_name(page, folder_name)
            self.assertEqual(self.submit_create(page), "clicked")
            page.wait_for(MODAL_CLOSED, message="建完文件夹对话框没有关掉")
            page.wait_for(row_names_expr(folder_name), timeout=30, message="新建的文件夹没有出现在列表里")
            listing = self.listing(FIXTURE_ROOT)
            self.assertEqual(listing[folder_name]["type"], "directory", "建出来的不是目录")
            # 创建后停在这个目录里，不自动跳进去 —— 面包屑仍旧是夹具目录。
            self.assertTrue(
                page.evaluate(
                    "document.getElementById('crumbs').innerText.indexOf("
                    + js(FIXTURE_DIR)
                    + ") >= 0"
                ),
                "新建之后界面擅自跳走了",
            )
            self.snap(page, "create")

    # ---------------------------------------------------------------- 用例二
    def test_create_refuses_duplicates_and_paths_in_the_name(self):
        """§4 验收：已存在默认拒绝、含分隔符的名字拒绝，且原文件一个字节都不变。"""
        with browser_session() as page:
            self.open_fixture_in_browser(page)
            name = "dup-" + RUN_TAG + ".txt"
            self.click_toolbar(page, "btn-new-file")
            self.fill_create_name(page, name)
            self.submit_create(page)
            page.wait_for(MODAL_CLOSED, message="第一次创建没有成功")
            page.wait_for(row_names_expr(name), timeout=30, message="第一次创建的文件没有出现")
            original = self.listing(FIXTURE_ROOT)[name]
            self.assertEqual(original["size"], 0)

            # 同名再建一次：服务端拒绝，对话框留着，提示要说清是「已经存在」。
            self.click_toolbar(page, "btn-new-file")
            self.fill_create_name(page, name)
            self.submit_create(page)
            page.wait_for(
                "(" + status_text_expr("create-status") + " || '').indexOf('已经存在') >= 0",
                timeout=30,
                message="同名再建没有给出「已经存在」提示："
                + str(page.evaluate(status_text_expr("create-status"))),
            )
            self.assertTrue(page.evaluate(MODAL_OPEN), "同名被拒后对话框不该关掉")
            after = self.listing(FIXTURE_ROOT)[name]
            self.assertEqual(after["size"], original["size"], "被拒绝的创建改动了原文件")
            self.assertEqual(after["mtime"], original["mtime"], "被拒绝的创建碰了原文件")

            # 名字里带分隔符：前端先拦下，不发请求。
            self.fill_create_name(page, "sub/dir.txt")
            self.submit_create(page)
            page.wait_for(
                "(" + status_text_expr("create-status") + " || '').indexOf('不能有 /') >= 0",
                timeout=30,
                message="含分隔符的名字没有被拦下："
                + str(page.evaluate(status_text_expr("create-status"))),
            )
            self.assertTrue(page.evaluate(MODAL_OPEN), "非法名字不该关掉对话框")
            self.assertNotIn("sub/dir.txt", self.listing(FIXTURE_ROOT))
            page.evaluate("document.getElementById('modal-close').click()")
            page.wait_for(MODAL_CLOSED, message="对话框没有关掉")

    # ---------------------------------------------------------------- 用例三
    def test_multi_select_shows_checkboxes_and_counts_the_selection(self):
        """§4 验收：多选在行最左显示复选框，计数、全选、清空都对得上。"""
        with browser_session() as page:
            self.open_fixture_in_browser(page)
            total = page.evaluate("document.querySelectorAll('#file-body tr[data-name]').length")
            self.assertGreaterEqual(total, 14)

            self.assertFalse(
                page.evaluate("document.getElementById('file-table').classList.contains('has-select')"),
                "没有进多选模式就显示复选框了",
            )
            self.assertEqual(self.click_toolbar(page, "btn-select-mode"), "clicked")
            page.wait_for(
                "document.getElementById('file-table').classList.contains('has-select')",
                message="多选模式没有打开",
            )
            self.assertTrue(
                page.evaluate(
                    "getComputedStyle(document.querySelector('#file-table col.col-select')).display"
                    " !== 'none'"
                ),
                "进了多选模式却没显示复选框列",
            )
            self.assertTrue(
                page.evaluate("document.getElementById('btn-select-mode').textContent.indexOf('退出') === 0"),
                "多选按钮没有变成退出态",
            )

            for name in (LAYOUT_SHORT, LAYOUT_OLD):
                self.assertTrue(
                    page.evaluate(
                        "(function () {"
                        "  var node = document.querySelector("
                        + js('#file-body tr[data-name="' + name + '"] .row-check')
                        + ");"
                        "  if (!node) { return false; }"
                        "  node.click();"
                        "  return true;"
                        "})()"
                    ),
                    "没有找到这一行的复选框：" + name,
                )
            page.wait_for(
                "(document.getElementById('sel-count') || {}).textContent.indexOf('已选 2 项') >= 0",
                timeout=15,
                message="勾选两行后计数不对：" + str(page.evaluate(status_text_expr("sel-count"))),
            )
            # 勾选之后删除/压缩这些批量动作才可以点。
            self.assertFalse(
                page.evaluate("document.getElementById('btn-sel-delete').disabled"),
                "勾选了条目，「删除」还是灰的",
            )

            self.assertEqual(self.click_toolbar(page, "btn-sel-all"), "clicked")
            expected_total = "已选 " + str(total) + " 项"
            page.wait_for(
                "(document.getElementById('sel-count') || {}).textContent.indexOf("
                + js(expected_total) + ") >= 0",
                timeout=15,
                message="全选后计数不对：" + str(page.evaluate(status_text_expr("sel-count"))),
            )
            self.assertEqual(self.click_toolbar(page, "btn-sel-clear"), "clicked")
            page.wait_for(
                "(document.getElementById('sel-count') || {}).textContent.indexOf('已选 0 项') >= 0",
                timeout=15,
                message="清空后计数不对：" + str(page.evaluate(status_text_expr("sel-count"))),
            )
            self.snap(page, "multiselect")

    # ---------------------------------------------------------------- 用例四
    def test_copy_then_paste_puts_the_files_where_the_user_looks(self):
        """§4 验收：多选复制 → 进另一个目录 → 粘贴，目标目录里真的多了两个文件。"""
        with browser_session() as page:
            self.open_fixture_in_browser(page)
            self.click_toolbar(page, "btn-select-mode")
            page.wait_for(
                "document.getElementById('file-table').classList.contains('has-select')",
                message="多选模式没有打开",
            )
            for name in (LAYOUT_SHORT, LAYOUT_OLD):
                page.evaluate(
                    "document.querySelector("
                    + js('#file-body tr[data-name="' + name + '"] .row-check')
                    + ").click()"
                )
            page.wait_for(
                "(document.getElementById('sel-count') || {}).textContent.indexOf('已选 2 项') >= 0",
                message="没有勾上两行",
            )
            self.assertEqual(self.click_toolbar(page, "btn-sel-copy"), "clicked")
            page.wait_for(
                "document.getElementById('btn-paste').disabled === false",
                timeout=15,
                message="复制之后「粘贴」还是灰的",
            )

            # 退出多选再进目标目录：多选模式下双击是勾选，不是打开。
            self.click_toolbar(page, "btn-select-mode")
            page.wait_for(
                "document.getElementById('file-table').classList.contains('has-select') === false",
                message="没有退出多选模式",
            )
            self.assertTrue(page.evaluate("window.__awfm.openRow(" + js(LAYOUT_LONG_DIR) + ")"))
            page.wait_for(
                "document.getElementById('crumbs').innerText.indexOf("
                + js(LAYOUT_LONG_DIR)
                + ") >= 0",
                message="没有进入目标目录",
            )
            self.assertEqual(self.click_toolbar(page, "btn-paste"), "clicked")
            page.wait_for(row_names_expr(LAYOUT_SHORT), timeout=30, message="粘贴后没有出现文件")
            page.wait_for(row_names_expr(LAYOUT_OLD), timeout=30, message="粘贴后只到了一个文件")

            copied = self.listing(FIXTURE_ROOT + "/" + LAYOUT_LONG_DIR)
            self.assertEqual(sorted(copied), sorted([LAYOUT_SHORT, LAYOUT_OLD]))
            source = self.listing(FIXTURE_ROOT)
            self.assertEqual(copied[LAYOUT_SHORT]["size"], source[LAYOUT_SHORT]["size"])
            self.assertIn(LAYOUT_SHORT, source, "复制把源文件弄丢了")
            self.snap(page, "paste")

    # ---------------------------------------------------------------- 用例五
    def test_preview_long_text_scrolls_inside_its_own_box(self):
        """§3 验收：长文本进独立预览框，滚动发生在框内，弹窗不被撑破。"""
        with browser_session() as page:
            self.open_fixture_in_browser(page)
            self.click_row(page, LONG_TEXT_NAME)
            page.wait_for(
                "document.getElementById('btn-preview').disabled === false",
                message="选中文件后「预览」还是灰的",
            )
            self.assertEqual(self.click_toolbar(page, "btn-preview"), "clicked")
            page.wait_for("!!document.querySelector('#modal-root .preview-box')", timeout=30,
                          message="预览没有独立的框")
            metrics = page.evaluate(PREVIEW_METRICS)
            self.assertIsNotNone(metrics, "预览框结构不全")
            self.assertEqual(metrics["overflowY"], "auto", "正文框没有自己滚")
            self.assertGreater(
                metrics["scrollHeight"],
                metrics["clientHeight"] + 100,
                "长文本没有把正文框撑出可滚动的高度：%r" % (metrics,),
            )
            self.assertGreaterEqual(
                metrics["bodyTop"], metrics["headBottom"] - 1, "正文压住了标题栏"
            )
            self.assertTrue(metrics["insideModal"], "预览框超出了弹窗边界：%r" % (metrics,))
            self.assertLessEqual(
                metrics["preWidth"], metrics["bodyWidth"] + 1, "正文把框撑宽了（该换行）"
            )
            # 真的能在框里滚起来，而不是滚了整个网页。
            scrolled = page.evaluate(
                "(function () {"
                "  var body = document.querySelector('#modal-root .preview-box-body');"
                "  var before = window.scrollY;"
                "  body.scrollTop = body.scrollHeight;"
                "  return { scrollTop: body.scrollTop, pageMoved: window.scrollY !== before };"
                "})()"
            )
            self.assertGreater(scrolled["scrollTop"], 0, "预览框滚不动")
            self.assertFalse(scrolled["pageMoved"], "滚的是整个页面而不是预览框")
            self.snap(page, "preview")
            page.evaluate("document.getElementById('modal-close').click()")
            page.wait_for(MODAL_CLOSED, message="预览关不掉")

            # 关掉再开别的：第二个文件不该带着上一个文件的内容。
            self.click_row(page, LAYOUT_SHORT)
            self.assertEqual(self.click_toolbar(page, "btn-preview"), "clicked")
            page.wait_for("!!document.querySelector('#modal-root .preview-box')", timeout=30,
                          message="第二次预览没有打开")
            text = page.evaluate(
                "(document.querySelector('#modal-root .preview-text') || {}).textContent || ''"
            )
            self.assertNotIn("第 001 行", text, "第二次预览里还是上一个文件的内容")
            page.evaluate("document.getElementById('modal-close').click()")
            page.wait_for(MODAL_CLOSED, message="第二次预览关不掉")

    # ---------------------------------------------------------------- 用例六
    def test_preview_of_a_big_file_uses_the_normal_error_path(self):
        """§3 验收：二进制/超大文件走现有的错误机制，不留半截预览框。"""
        with browser_session() as page:
            self.open_fixture_in_browser(page)
            self.click_row(page, LAYOUT_BIG)
            self.assertEqual(self.click_toolbar(page, "btn-preview"), "clicked")
            # 12 MiB 的 .bin 先撞上「读到 NUL 就按二进制处理」，比「太大」更早；
            # 两种提示都算走了现有的错误机制（§3 验收：二进制用现有错误机制）。
            page.wait_for(
                "(function () {"
                "  var text = " + TOAST_TEXT + ";"
                "  return text.indexOf('二进制') >= 0 || text.indexOf('太大') >= 0;"
                "})()",
                timeout=30,
                message="超大文件预览没有给出提示："
                + str(page.evaluate(TOAST_TEXT)),
            )
            self.assertTrue(page.evaluate(MODAL_CLOSED), "预览失败却留下了弹窗")
            self.assertFalse(
                page.evaluate("!!document.querySelector('#modal-root .preview-box')"),
                "预览失败却留下了预览框",
            )

    # ---------------------------------------------------------------- 用例七
    def test_readonly_connection_disables_creating(self):
        """§4 验收：连接不允许写时，「新建文件/文件夹」在建之前就是灰的。"""
        with browser_session() as page:
            self.open_fixture_in_browser(page, connection_id=READONLY_ID)
            for button_id in ("btn-new-file", "btn-new-folder"):
                self.assertTrue(
                    page.evaluate("document.getElementById(%s).disabled === true" % js(button_id)),
                    "只读连接上「%s」居然可点" % button_id,
                )
                self.assertEqual(
                    self.click_toolbar(page, button_id), "disabled", "只读连接上还是点下去了"
                )
            self.assertTrue(page.evaluate(MODAL_CLOSED), "只读连接上居然弹出了新建对话框")
            # 多选只是本地勾选，不需要写权限。
            self.assertFalse(
                page.evaluate("document.getElementById('btn-select-mode').disabled"),
                "只读连接上「多选」不该被禁用",
            )


if __name__ == "__main__":
    unittest.main()
