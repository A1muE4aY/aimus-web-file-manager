"""远端文本编辑与文件操作的端到端验证（任务书 2.md 阶段四）。

阶段四要求：文件能在线打开、改、保存；保存前要能发现「远端已经变了」而不是默默
覆盖；取消要问一句且不落盘；重命名 / 压缩 / 解压 / 删除要能从列表里直接做到；
没开写权限时写操作要挡住。这些都要在真实浏览器里走一遍才算数 —— 按钮在不在、
灰没灰、对话框里留了什么，都是渲染出来才有的东西。

浏览器是真实 Edge：无头 + --inprivate + 全新临时配置目录（与其它 e2e 用例同一口径）。
夹具摆在家目录下，测试像用户那样点着进去，不直接改前端 state。
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
    require_testbed,
    running_server,
    testbed_command,
    testbed_connection,
    testbed_environment,
    upload_bytes,
)

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
RUN_TAG = uuid.uuid4().hex[:8]
CONNECTION_ID = "e2e-edit"
CONNECTION_NAME = "编辑测试床"
READONLY_ID = "e2e-edit-ro"
READONLY_NAME = "编辑测试床（只读）"

HOME_DIR = "/home/aimu"
FIXTURE_DIR = "awfm-e2e-edit-" + RUN_TAG
FIXTURE_PATH = HOME_DIR + "/" + FIXTURE_DIR

EDIT_FILE = "edit-me.txt"
CONFLICT_FILE = "conflict.txt"
CANCEL_FILE = "keep.txt"
RENAME_FILE = "rename-me.txt"
RENAMED_FILE = "renamed-by-e2e.txt"
DELETE_FILE = "delete-me.txt"
PACK_FILE = "pack-me.txt"
ARCHIVE_FILE = PACK_FILE + ".tar.gz"
UNPACK_DIR = "unpacked"

EDIT_TEXT = "hello e2e\n"
EDITED_TEXT = "edited in the browser\n"
CONFLICT_SEED = "conflict seed\n"
OTHER_TEXT = "someone else wrote this\n"
KEPT_TEXT = "keep me\n"
RENAME_TEXT = "rename me\n"
PACK_TEXT = "pack me\n"

#: 摆场景用的是测试自己的一次性 shell（应用本身不在远端执行任何命令，T-013）。
FIXTURE_SCRIPT = """set -e
d="$HOME/{fixture}"
chmod -R u+rwX "$d" 2>/dev/null || true
rm -rf "$d"
mkdir -p "$d/tree/inner"
printf 'hello e2e\\n' > "$d/{edit}"
printf 'conflict seed\\n' > "$d/{conflict}"
printf 'keep me\\n' > "$d/{cancel}"
printf 'rename me\\n' > "$d/{rename}"
printf 'delete me\\n' > "$d/{delete}"
printf 'pack me\\n' > "$d/{pack}"
printf 'leaf\\n' > "$d/tree/inner/leaf.txt"
echo READY
"""


def js(value: str) -> str:
    """把 Python 字符串写成 JS 字面量（省得手工拼引号，中文也不用转义）。"""
    return json.dumps(value, ensure_ascii=False)


def click_connect_expr(connection_id: str = CONNECTION_ID) -> str:
    selector = '#conn-list .conn-item[data-id="' + connection_id + '"] .conn-actions button'
    return "window.__awfm.clickByText(" + js(selector) + ", '连接')"


MODAL_OPEN = "!document.getElementById('modal-root').hidden"
MODAL_CLOSED = "document.getElementById('modal-root').hidden === true"
EDITOR_TEXT_VALUE = "document.getElementById('editor-text').value"
EDITOR_NOTICE_KIND = "document.getElementById('editor-notice').getAttribute('data-kind')"
EDITOR_SAVE_DISABLED = "document.getElementById('btn-editor-save').disabled"


def row_names_expr(name: str) -> str:
    return "window.__awfm.rowNames().indexOf(" + js(name) + ") >= 0"


def row_button_expr(name: str, classes: str) -> str:
    """点某一行的操作按钮（按钮没有 id，按行的 data-name 找）。"""
    return (
        "(function () {"
        "  var row = document.querySelector(" + js('#file-body tr[data-name="' + name + '"]') + ");"
        "  if (!row) { return false; }"
        "  var button = row.querySelector(" + js("." + classes) + ");"
        "  if (!button || button.disabled) { return false; }"
        "  button.click();"
        "  return true;"
        "})()"
    )


def row_button_state_expr(name: str, classes: str) -> str:
    """返回 enabled / disabled / no-button / no-row —— 只看状态，不点。"""
    return (
        "(function () {"
        "  var row = document.querySelector(" + js('#file-body tr[data-name="' + name + '"]') + ");"
        "  if (!row) { return 'no-row'; }"
        "  var button = row.querySelector(" + js("." + classes) + ");"
        "  if (!button) { return 'no-button'; }"
        "  return button.disabled ? 'disabled' : 'enabled';"
        "})()"
    )


def row_cell_text_expr(name: str, cell: str) -> str:
    return (
        "(function () {"
        "  var row = document.querySelector(" + js('#file-body tr[data-name="' + name + '"]') + ");"
        "  if (!row) { return ''; }"
        "  var node = row.querySelector(" + js("." + cell) + ");"
        "  return node ? node.innerText : '';"
        "})()"
    )


def set_editor_text_expr(text: str) -> str:
    """像用户那样改内容：改 value 并派发 input（编辑器靠 input 事件算「已修改」）。"""
    return (
        "(function () {"
        "  var area = document.getElementById('editor-text');"
        "  area.value = " + js(text) + ";"
        "  area.dispatchEvent(new Event('input', {bubbles: true}));"
        "  return true;"
        "})()"
    )


def set_value_expr(element_id: str, value: str) -> str:
    return (
        "(function () {"
        "  var input = document.getElementById(" + js(element_id) + ");"
        "  if (!input) { return false; }"
        "  input.value = " + js(value) + ";"
        "  input.dispatchEvent(new Event('input', {bubbles: true}));"
        "  return true;"
        "})()"
    )


@require_testbed
class BrowserEditTests(unittest.TestCase):
    """需要真实测试床：在浏览器里编辑真实的远程文件。"""

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.config, _keys = self.stack.enter_context(
            testbed_environment(
                connections=[
                    testbed_connection(id=CONNECTION_ID, name=CONNECTION_NAME),
                    testbed_connection(
                        id=READONLY_ID, name=READONLY_NAME, allow_write=False
                    ),
                ]
            )
        )
        self.client = self.stack.enter_context(running_server(self.config))
        self.base_url = self.client.base
        testbed_command(
            FIXTURE_SCRIPT.format(
                fixture=FIXTURE_DIR,
                edit=EDIT_FILE,
                conflict=CONFLICT_FILE,
                cancel=CANCEL_FILE,
                rename=RENAME_FILE,
                delete=DELETE_FILE,
                pack=PACK_FILE,
            ),
            timeout=120,
        )
        self.addCleanup(
            lambda: testbed_command('rm -rf "$HOME/%s"' % FIXTURE_DIR, check=False, timeout=120)
        )
        self.addCleanup(
            lambda: self.client.post("/api/connections/%s/disconnect" % CONNECTION_ID, {})
        )

    # ------------------------------------------------------------------ 助手
    def text_url(self, name: str) -> str:
        return "/api/connections/%s/text?path=%s" % (
            CONNECTION_ID,
            quote(FIXTURE_PATH + "/" + name, safe=""),
        )

    def remote_text(self, name: str) -> str:
        """绕过界面直接核对远端内容 —— 界面说保存了，远端得真有那个字节。"""
        response = self.client.get(self.text_url(name))
        self.assertEqual(response.status, 200, response.raw)
        return response.data["file"]["text"]

    def open_fixture_in_browser(
        self, page, *, connection_id: str = CONNECTION_ID, connection_count: int = 2
    ):
        """从空白页开始：连上测试床，点进夹具目录 —— 走的是用户那条路。"""
        page.navigate(self.base_url + "/")
        page.wait_for("!document.getElementById('app').hidden", message="页面外壳没有显示出来")
        page.install_helpers()
        page.wait_for(
            "document.querySelectorAll('#conn-list .conn-item').length === %d" % connection_count,
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
        page.wait_for(
            row_names_expr(FIXTURE_DIR), timeout=60, message="家目录里没有出现夹具目录"
        )
        self.assertTrue(page.evaluate("window.__awfm.openRow(" + js(FIXTURE_DIR) + ")"))
        page.wait_for(
            "document.getElementById('crumbs').innerText.indexOf(" + js(FIXTURE_DIR) + ") >= 0",
            message="没有进入夹具目录",
        )

    def open_editor(self, page, name: str):
        self.assertTrue(
            page.evaluate(row_button_expr(name, "btn-edit-entry")),
            "操作列里没有可用的「编辑」按钮：" + name,
        )
        page.wait_for(MODAL_OPEN, message="编辑器没有打开")
        page.wait_for(
            "document.getElementById('editor-text') !== null",
            message="编辑器里没有文本区",
        )

    # ------------------------------------------------------------------ 用例
    def wait_for_toast(self, page, needle: str, *, timeout: int = 30) -> str:
        """等一条包含指定文字的轻提示，并顺手钉住「提示里不能出现 undefined」。

        这条断言有来历：文件操作成功之后，界面曾把响应里并不存在的字段直接拼进
        提示，屏幕上出现「已删除「undefined」」—— (远端状态是对的，只有提示是错的)。
        所以核对远端之余，还要核对界面把结果说成了什么。
        """
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

    def test_editor_saves_an_edited_file(self):
        with browser_session() as page:
            self.open_fixture_in_browser(page)
            self.assertEqual(self.remote_text(EDIT_FILE), EDIT_TEXT)
            size_before = page.evaluate(row_cell_text_expr(EDIT_FILE, "col-size"))

            self.open_editor(page, EDIT_FILE)
            self.assertEqual(page.evaluate(EDITOR_TEXT_VALUE), EDIT_TEXT)
            self.assertIn(
                "edit-me.txt", page.evaluate("document.getElementById('modal-title').innerText")
            )

            page.evaluate(set_editor_text_expr(EDITED_TEXT))
            page.wait_for(
                "document.getElementById('editor-dirty').getAttribute('data-dirty') === 'true'",
                message="改了内容之后界面没有标成「已修改」",
            )
            self.assertFalse(
                page.evaluate(EDITOR_SAVE_DISABLED), "有改动之后保存按钮不该是灰的"
            )
            page.evaluate("document.getElementById('btn-editor-save').click()")
            page.wait_for(MODAL_CLOSED, timeout=60, message="保存之后对话框没有关掉")
            self.assertIn(EDIT_FILE, self.wait_for_toast(page, "已保存", timeout=60))

            # 界面说保存了，远端必须真有这个字节。
            self.assertEqual(self.remote_text(EDIT_FILE), EDITED_TEXT)
            # 列表里的大小与修改时间要跟着刷新，否则用户以为没保存成功。
            page.wait_for(
                row_cell_text_expr(EDIT_FILE, "col-size") + " !== " + js(size_before),
                timeout=60,
                message="保存之后文件列表里的大小没有更新",
            )

            page.screenshot(ARTIFACTS_DIR / ("browser-edit-saved-" + RUN_TAG + ".png"))

    def test_conflict_is_reported_and_remote_content_is_kept(self):
        with browser_session() as page:
            self.open_fixture_in_browser(page)
            self.open_editor(page, CONFLICT_FILE)
            self.assertEqual(page.evaluate(EDITOR_TEXT_VALUE), CONFLICT_SEED)
            page.evaluate(set_editor_text_expr("my own version\n"))

            # 用户还在编辑器里的时候，别人把远端文件改了（这里用 HTTP 客户端扮演别人）。
            upload_bytes(
                self.client,
                FIXTURE_PATH,
                CONFLICT_FILE,
                OTHER_TEXT.encode("utf-8"),
                overwrite=True,
                connection_id=CONNECTION_ID,
            )

            page.evaluate("document.getElementById('btn-editor-save').click()")
            page.wait_for(
                EDITOR_NOTICE_KIND + " === 'warn'", timeout=60, message="保存冲突没有给出提示"
            )
            self.assertIn(
                "没有写入", page.evaluate("document.getElementById('editor-notice').innerText")
            )
            # 冲突之后要给出「重新加载远端内容」的入口。
            self.assertFalse(
                page.evaluate("document.getElementById('btn-editor-reload').hidden"),
                "冲突之后没有给出重新加载的入口",
            )
            # 用户敲进去的内容还在，远端还是别人写的那份。
            self.assertEqual(page.evaluate(EDITOR_TEXT_VALUE), "my own version\n")
            self.assertEqual(self.remote_text(CONFLICT_FILE), OTHER_TEXT)
            self.assertTrue(page.evaluate(MODAL_OPEN), "冲突之后对话框不该关掉")

            page.screenshot(ARTIFACTS_DIR / ("browser-edit-conflict-" + RUN_TAG + ".png"))

            page.evaluate("document.getElementById('btn-editor-reload').click()")
            page.wait_for(
                EDITOR_TEXT_VALUE + " === " + js(OTHER_TEXT),
                timeout=60,
                message="重新加载之后编辑器里不是远端的内容",
            )
            self.assertTrue(page.evaluate("document.getElementById('btn-editor-reload').hidden"))

            page.evaluate("document.getElementById('btn-editor-cancel').click()")
            page.wait_for(MODAL_CLOSED)

    def test_cancel_asks_before_discarding_modifications(self):
        with browser_session() as page:
            self.open_fixture_in_browser(page)
            self.open_editor(page, CANCEL_FILE)
            self.assertEqual(page.evaluate(EDITOR_TEXT_VALUE), KEPT_TEXT)
            page.evaluate(set_editor_text_expr("throw me away\n"))
            self.assertFalse(page.evaluate(EDITOR_SAVE_DISABLED))

            page.evaluate("document.getElementById('btn-editor-cancel').click()")
            page.wait_for(
                "!document.getElementById('editor-ask').hidden",
                message="有未保存的修改时，取消没有先问一句",
            )
            self.assertEqual(
                page.evaluate("document.getElementById('editor-ask-yes').innerText"),
                "放弃修改并关闭",
            )

            # 先选「继续编辑」：对话框留着，内容不动。
            page.evaluate("document.getElementById('editor-ask-no').click()")
            page.wait_for("document.getElementById('editor-ask').hidden === true")
            self.assertTrue(page.evaluate(MODAL_OPEN))
            self.assertEqual(page.evaluate(EDITOR_TEXT_VALUE), "throw me away\n")

            page.evaluate("document.getElementById('btn-editor-cancel').click()")
            page.wait_for("!document.getElementById('editor-ask').hidden")
            page.evaluate("document.getElementById('editor-ask-yes').click()")
            page.wait_for(MODAL_CLOSED, timeout=60, message="放弃修改之后对话框没有关掉")

            # 取消就是取消：远端一个字节都不该动。
            self.assertEqual(self.remote_text(CANCEL_FILE), KEPT_TEXT)

            page.screenshot(ARTIFACTS_DIR / ("browser-edit-cancel-" + RUN_TAG + ".png"))

    def test_file_operations_from_the_action_column(self):
        with browser_session() as page:
            self.open_fixture_in_browser(page)

            # 重命名：对话框里预填原名，改完点确定。
            self.assertTrue(page.evaluate(row_button_expr(RENAME_FILE, "btn-rename-entry")))
            page.wait_for(
                "document.getElementById('rename-input') !== null", message="重命名对话框没有打开"
            )
            self.assertEqual(
                page.evaluate("document.getElementById('rename-input').value"), RENAME_FILE
            )
            page.evaluate(set_value_expr("rename-input", RENAMED_FILE))
            page.evaluate("document.getElementById('btn-rename-ok').click()")
            self.assertIn(RENAMED_FILE, self.wait_for_toast(page, "已重命名"))
            page.wait_for(
                row_names_expr(RENAMED_FILE), timeout=60, message="重命名之后列表里没有出现新名字"
            )
            self.assertNotIn(RENAME_FILE, page.evaluate("window.__awfm.rowNames()"))
            self.assertEqual(self.remote_text(RENAMED_FILE), RENAME_TEXT)

            # 压缩：默认名字就是「原名 + .tar.gz」。
            self.assertTrue(page.evaluate(row_button_expr(PACK_FILE, "btn-compress-entry")))
            page.wait_for(
                "document.getElementById('compress-name') !== null", message="压缩对话框没有打开"
            )
            self.assertEqual(
                page.evaluate("document.getElementById('compress-name').value"), ARCHIVE_FILE
            )
            page.evaluate("document.getElementById('btn-compress-ok').click()")
            compressed = self.wait_for_toast(page, "已生成", timeout=90)
            self.assertIn(ARCHIVE_FILE, compressed)
            self.assertIn("个条目", compressed)
            page.wait_for(
                row_names_expr(ARCHIVE_FILE), timeout=90, message="压缩之后列表里没有出现压缩包"
            )

            # 解压：预填的是压缩包所在的目录（也就是当前目录）。
            self.assertTrue(page.evaluate(row_button_expr(ARCHIVE_FILE, "btn-extract-entry")))
            page.wait_for(
                "document.getElementById('extract-into') !== null", message="解压对话框没有打开"
            )
            self.assertEqual(
                page.evaluate("document.getElementById('extract-into').value"), FIXTURE_PATH
            )
            page.evaluate(set_value_expr("extract-into", FIXTURE_PATH + "/" + UNPACK_DIR))
            page.evaluate("document.getElementById('btn-extract-ok').click()")
            self.assertIn(UNPACK_DIR, self.wait_for_toast(page, "已解压", timeout=90))
            page.wait_for(
                row_names_expr(UNPACK_DIR), timeout=90, message="解压之后列表里没有出现目标目录"
            )
            self.assertEqual(self.remote_text(UNPACK_DIR + "/" + PACK_FILE), PACK_TEXT)

            # 删除：先点「删除」，再在确认框里确认一次。
            self.assertTrue(page.evaluate(row_button_expr(DELETE_FILE, "btn-delete-entry")))
            page.wait_for(MODAL_OPEN, message="删除没有弹出确认框")
            self.assertEqual(
                page.evaluate("document.getElementById('modal-title').innerText"), "删除条目"
            )
            self.assertIn(
                DELETE_FILE, page.evaluate("document.querySelector('.confirm-body').innerText")
            )
            self.assertTrue(
                page.evaluate(
                    "window.__awfm.clickByText('#modal-foot button', '删除')"
                ),
                "确认框里没有「删除」按钮",
            )
            self.assertIn(DELETE_FILE, self.wait_for_toast(page, "已删除"))
            page.wait_for(
                "window.__awfm.rowNames().indexOf(" + js(DELETE_FILE) + ") < 0",
                timeout=60,
                message="删除之后列表里还有这个文件",
            )
            self.assertEqual(self.client.get(self.text_url(DELETE_FILE)).status, 404)

            page.screenshot(ARTIFACTS_DIR / ("browser-edit-ops-" + RUN_TAG + ".png"))

    def test_write_buttons_follow_the_write_toggle(self):
        with browser_session() as page:
            self.open_fixture_in_browser(page, connection_id=READONLY_ID)

            # 编辑内容不需要写权限；改名 / 压缩 / 删除需要，没开就要灰着。
            self.assertEqual(
                page.evaluate(row_button_state_expr(EDIT_FILE, "btn-edit-entry")), "enabled"
            )
            for classes in ("btn-rename-entry", "btn-compress-entry", "btn-delete-entry"):
                self.assertEqual(
                    page.evaluate(row_button_state_expr(EDIT_FILE, classes)),
                    "disabled",
                    "没开写权限时 " + classes + " 应该是灰的",
                )

            self.open_editor(page, EDIT_FILE)
            self.assertEqual(page.evaluate(EDITOR_TEXT_VALUE), EDIT_TEXT)
            self.assertEqual(page.evaluate(EDITOR_NOTICE_KIND), "warn")
            self.assertIn(
                "写权限", page.evaluate("document.getElementById('editor-notice').innerText")
            )
            page.evaluate(set_editor_text_expr("cannot save this\n"))
            self.assertTrue(
                page.evaluate(EDITOR_SAVE_DISABLED),
                "只读连接上保存按钮不该可以点",
            )

            page.screenshot(ARTIFACTS_DIR / ("browser-edit-readonly-" + RUN_TAG + ".png"))

            # 只读连接也能在本地放弃这次编辑（内容本来就写不出去）。
            page.evaluate("document.getElementById('btn-editor-cancel').click()")
            page.wait_for("!document.getElementById('editor-ask').hidden")
            page.evaluate("document.getElementById('editor-ask-yes').click()")
            page.wait_for(MODAL_CLOSED)


if __name__ == "__main__":
    unittest.main()
