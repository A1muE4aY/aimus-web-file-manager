"""文件检索的端到端验证（任务书 2.md 阶段三）。

阶段三要求：能按文件名检索「当前目录及其子目录」，结果显示在列表里、能一键定位到
那个文件；搜索期间界面照常能用，能中止、能清空；没有匹配时要说清「没有匹配」，
而不是让用户对着空白猜。这些只有在真实浏览器里才说得清 —— 面板什么时候出现、
状态药丸是哪个状态、点「定位」之后文件表格跳到哪一级，都是渲染出来才有的东西。

浏览器是真实 Edge：无头 + --inprivate + 全新临时配置目录（与其它 e2e 用例同一口径）。
夹具摆在家目录下，测试像用户那样点着进去，而不是直接改前端的 state。
"""

from __future__ import annotations

import contextlib
import json
import re
import unittest
import uuid
from pathlib import Path

from tests.e2e.support import browser_session
from tests.integration.support import (
    require_testbed,
    running_server,
    testbed_command,
    testbed_connection,
    testbed_environment,
)

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
RUN_TAG = uuid.uuid4().hex[:8]
CONNECTION_ID = "e2e-search"
CONNECTION_NAME = "检索测试床"

FIXTURE_DIR = "awfm-e2e-search-" + RUN_TAG
NESTED_DIR = "子目录"
BULK_DIR = "bulk"
#: 中止用例要有足够长的扫描时间，中止点击才落得到「运行中」这段窗口里。
#: 实测（.temp/probe_scan_rate.py）：空目录 ≈ 2.8ms/个，500 个 1.4s、1500 个约 4s。
#: 上限压在 max_dirs=2000 之下：一个平铺目录里超过 2000 个子目录会先撞上目录预算被截断。
BULK_DIRS = 1500
REPORT = "报告.txt"
DRAFT = "报告-草稿.txt"
DEEP_REPORT = "深层报告.txt"
OTHER = "别的东西.txt"
MISSING_QUERY = "绝不存在的名字-zzz"

#: 摆场景用的是测试自己的一次性 shell（应用本身不在远端执行任何命令，T-013）。
#: 目录摆在家目录下：浏览器要能像用户那样一层层点进去。
FIXTURE_SCRIPT = """set -e
d="$HOME/{fixture}"
chmod -R u+rwX "$d" 2>/dev/null || true
rm -rf "$d"
mkdir -p "$d/{nested}" "$d/{bulk}"
printf 'hello search\\n' > "$d/{report}"
printf 'draft\\n' > "$d/{draft}"
printf '' > "$d/Report.md"
printf 'x\\n' > "$d/{other}"
printf 'deep\\n' > "$d/{nested}/{deep}"
mkdir -p "$d/{bulk}"/d{{0000..{last}}}
echo READY
"""


def js(value: str) -> str:
    """把 Python 字符串写成 JS 字面量（省得手工拼引号，中文也不用转义）。"""
    return json.dumps(value, ensure_ascii=False)


def click_connect_expr(connection_id: str = CONNECTION_ID) -> str:
    selector = '#conn-list .conn-item[data-id="' + connection_id + '"] .conn-actions button'
    return "window.__awfm.clickByText(" + js(selector) + ", '连接')"


SEARCH_ROW_NAMES = (
    "Array.from(document.querySelectorAll('#search-body tr')).map(function (row) {"
    " return row.getAttribute('data-name'); })"
)
SEARCH_STATE = "document.getElementById('search-status').dataset.state"
TERMINAL_QUERY_STATE = (
    "['done', 'failed', 'cancelled'].indexOf(" + SEARCH_STATE + ") >= 0"
)


def locate_expr(name: str) -> str:
    """点结果行里的「定位」按钮（按钮没有 id，按行的 data-name 找）。"""
    return (
        "(function () {"
        "  var rows = document.querySelectorAll('#search-body tr');"
        "  for (var i = 0; i < rows.length; i += 1) {"
        "    if (rows[i].getAttribute('data-name') === " + js(name) + ") {"
        "      var button = rows[i].querySelector('button');"
        "      if (button) { button.click(); return true; }"
        "    }"
        "  }"
        "  return false;"
        "})()"
    )


def located_expr(name: str) -> str:
    """文件表格里那一行是否已被「定位」标出来。"""
    return (
        "!!document.querySelector("
        + js('#file-body tr.is-located[data-name="' + name + '"]')
        + ")"
    )


@require_testbed
class BrowserSearchTests(unittest.TestCase):
    """需要真实测试床：在浏览器里搜真实的远程目录。"""

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.config, _keys = self.stack.enter_context(
            testbed_environment(
                connections=[testbed_connection(id=CONNECTION_ID, name=CONNECTION_NAME)]
            )
        )
        self.client = self.stack.enter_context(running_server(self.config))
        self.base_url = self.client.base
        testbed_command(
            FIXTURE_SCRIPT.format(
                fixture=FIXTURE_DIR,
                nested=NESTED_DIR,
                bulk=BULK_DIR,
                report=REPORT,
                draft=DRAFT,
                other=OTHER,
                deep=DEEP_REPORT,
                last="%04d" % (BULK_DIRS - 1),
            ),
            timeout=180,
        )
        self.addCleanup(
            lambda: testbed_command('rm -rf "$HOME/%s"' % FIXTURE_DIR, check=False, timeout=180)
        )
        self.addCleanup(
            lambda: self.client.post("/api/connections/%s/disconnect" % CONNECTION_ID, {})
        )

    # ------------------------------------------------------------------ 夹具
    def open_fixture_in_browser(self, page):
        """从空白页开始：连上测试床，点进夹具目录 —— 走的是用户那条路。"""
        page.navigate(self.base_url + "/")
        page.wait_for("!document.getElementById('app').hidden", message="页面外壳没有显示出来")
        page.install_helpers()
        page.wait_for(
            "document.querySelectorAll('#conn-list .conn-item').length === 1",
            message="连接列表没有渲染出来",
        )
        self.assertTrue(page.evaluate(click_connect_expr()), "没有找到连接按钮")
        page.wait_for(
            "!!document.querySelector("
            + js('#conn-list .conn-item[data-state="connected"]')
            + ")",
            timeout=90,
            message="浏览器里没有出现已连接状态",
        )
        page.wait_for(
            "window.__awfm.rowNames().indexOf(" + js(FIXTURE_DIR) + ") >= 0",
            timeout=60,
            message="家目录里没有出现夹具目录",
        )
        self.assertTrue(page.evaluate("window.__awfm.openRow(" + js(FIXTURE_DIR) + ")"))
        page.wait_for(
            "document.getElementById('crumbs').innerText.indexOf(" + js(FIXTURE_DIR) + ") >= 0",
            message="没有进入夹具目录",
        )

    def enter_subdirectory(self, page, name: str):
        self.assertTrue(page.evaluate("window.__awfm.openRow(" + js(name) + ")"))
        page.wait_for(
            "document.getElementById('crumbs').innerText.indexOf(" + js(name) + ") >= 0",
            message="没有进入 " + name,
        )

    def submit_search(self, page, query: str, *, via: str = "button"):
        """只发起搜索，不等它结束 —— 要观察「运行中」就得留出这段窗口。"""
        if via == "enter":
            # 真实浏览器里在输入框按回车就是提交表单，这里复现同一个事件。
            submit = "document.getElementById('searchbar').dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}))"
        else:
            submit = "document.getElementById('btn-search').click()"
        page.evaluate(
            "(function () {"
            "  document.getElementById('search-input').value = " + js(query) + ";"
            "  " + submit + ";"
            "})()"
        )

    def run_search(self, page, query: str, *, via: str = "button"):
        """填关键词、发起搜索、等它结束（完成/中止/失败都算结束）。"""
        self.submit_search(page, query, via=via)
        page.wait_for(TERMINAL_QUERY_STATE, timeout=120, message="搜索没有结束：" + query)

    def search_state(self, page) -> str:
        return page.evaluate(SEARCH_STATE)

    def search_row_names(self, page):
        return page.evaluate(SEARCH_ROW_NAMES)

    def search_row_text(self, page, name: str) -> str:
        return page.evaluate(
            "(function () { var rows = document.querySelectorAll('#search-body tr');"
            " for (var i = 0; i < rows.length; i += 1) {"
            "   if (rows[i].getAttribute('data-name') === " + js(name) + ") {"
            "     return rows[i].innerText; } } return ''; })()"
        )

    def search_row_type(self, page, name: str) -> str:
        return page.evaluate(
            "(function () { var rows = document.querySelectorAll('#search-body tr');"
            " for (var i = 0; i < rows.length; i += 1) {"
            "   if (rows[i].getAttribute('data-name') === " + js(name) + ") {"
            "     var cell = rows[i].querySelector('.col-type');"
            "     return cell ? cell.textContent : ''; } } return ''; })()"
        )

    def hint_text(self, page) -> str:
        return page.evaluate(
            "(function () { var h = document.getElementById('search-hint');"
            " return h.hidden ? '' : h.textContent; })()"
        )

    def progress_text(self, page) -> str:
        return page.evaluate("document.getElementById('search-progress').textContent")

    # ------------------------------------------------------------------ 用例
    def test_search_lists_results_and_locate_jumps_to_the_file(self):
        with browser_session() as page:
            self.open_fixture_in_browser(page)

            # 还没搜时范围只写「当前目录」；搜完要落到真实起点上，用户才知道搜的是哪一级。
            self.assertIn(
                "当前目录", page.evaluate("document.getElementById('search-scope').textContent")
            )

            self.run_search(page, "报告")
            self.assertEqual(self.search_state(page), "done")
            self.assertIn(
                FIXTURE_DIR, page.evaluate("document.getElementById('search-scope').textContent")
            )
            self.assertEqual(
                page.evaluate("document.getElementById('search-status').textContent"), "已完成"
            )
            self.assertEqual(
                sorted(self.search_row_names(page)), sorted([REPORT, DRAFT, DEEP_REPORT])
            )
            # 深层命中的那一行要写清「所在目录」，否则用户不知道它在哪一层。
            self.assertIn(NESTED_DIR, self.search_row_text(page, DEEP_REPORT))
            # 类型也要看得见（图标之外给文字，别让用户猜）。
            self.assertEqual(self.search_row_type(page, DEEP_REPORT), "文件")

            # 目录同样能搜到，并且标明是目录。
            self.run_search(page, NESTED_DIR)
            self.assertEqual(self.search_row_names(page), [NESTED_DIR])
            self.assertEqual(self.search_row_type(page, NESTED_DIR), "目录")
            self.run_search(page, "报告")

            # 点「定位」：文件表格要跳到它所在的目录，并选中这一行。
            self.assertTrue(page.evaluate(locate_expr(DEEP_REPORT)), "结果行里没有「定位」按钮")
            page.wait_for(located_expr(DEEP_REPORT), message="定位之后目标行没有被标出来")
            self.assertIn(DEEP_REPORT, page.evaluate("window.__awfm.rowNames()"))
            self.assertIn(NESTED_DIR, page.evaluate("document.getElementById('crumbs').innerText"))
            # 面板不关：用户还要接着点下一条结果。
            self.assertFalse(
                page.evaluate("document.getElementById('search-panel').hidden"),
                "定位之后结果面板不该收起来",
            )

            page.screenshot(ARTIFACTS_DIR / ("browser-search-locate-" + RUN_TAG + ".png"))

    def test_search_ignores_case_and_says_so_when_nothing_matches(self):
        with browser_session() as page:
            self.open_fixture_in_browser(page)

            # 回车发起（表单提交路径），关键词大小写不敏感。
            self.run_search(page, "report", via="enter")
            self.assertEqual(self.search_state(page), "done")
            self.assertEqual(self.search_row_names(page), ["Report.md"])

            self.run_search(page, MISSING_QUERY)
            self.assertEqual(self.search_state(page), "done")
            self.assertEqual(self.search_row_names(page), [])
            self.assertIn("没有匹配", self.hint_text(page))
            # 零结果时连表头一起收起来 —— 一个空表头看起来像加载失败。
            self.assertTrue(page.evaluate("document.getElementById('search-rows').hidden"))

            page.screenshot(ARTIFACTS_DIR / ("browser-search-no-match-" + RUN_TAG + ".png"))

    def test_clear_button_returns_the_panel_to_idle(self):
        with browser_session() as page:
            self.open_fixture_in_browser(page)

            self.run_search(page, "报告")
            self.assertTrue(self.search_row_names(page))
            page.evaluate("document.getElementById('btn-search-clear').click()")
            page.wait_for(
                "document.getElementById('search-panel').hidden === true",
                message="清空之后面板没有收起来",
            )
            self.assertEqual(page.evaluate("document.getElementById('search-input').value"), "")
            self.assertEqual(
                page.evaluate("document.querySelectorAll('#search-body tr').length"), 0
            )
            # 连接还在，搜索框立刻可以再搜。
            self.assertFalse(page.evaluate("document.getElementById('search-input').disabled"))

    def test_cancel_stops_a_running_search_and_frees_the_connection(self):
        with browser_session() as page:
            self.open_fixture_in_browser(page)
            self.enter_subdirectory(page, BULK_DIR)

            self.submit_search(page, MISSING_QUERY, via="enter")
            # 搜索在跑的时候必须有中止入口（按钮只在 running 时出现）。
            page.wait_for(
                SEARCH_STATE + " === 'running'", timeout=30, message="搜索没有进入运行状态"
            )
            self.assertFalse(
                page.evaluate("document.getElementById('btn-search-cancel').hidden"),
                "搜索在跑，却没有给出中止按钮",
            )
            page.evaluate("document.getElementById('btn-search-cancel').click()")
            page.wait_for(SEARCH_STATE + " === 'cancelled'", timeout=90, message="中止没有生效")
            self.assertEqual(
                page.evaluate("document.getElementById('search-status').textContent"), "已中止"
            )
            self.assertIn("已扫描", self.progress_text(page))
            scanned = int(re.search(r"已扫描 (\d+) 个目录", self.progress_text(page)).group(1))
            self.assertLess(scanned, BULK_DIRS + 1, "中止时已经扫完了，这个用例没测到东西")
            self.assertTrue(page.evaluate("document.getElementById('btn-search-cancel').hidden"))

            page.screenshot(ARTIFACTS_DIR / ("browser-search-cancelled-" + RUN_TAG + ".png"))

            # 中止之后活动槽要空出来：紧接着的一条搜索必须能正常跑完（否则是 409）。
            self.run_search(page, "报告")
            self.assertEqual(self.search_state(page), "done")


if __name__ == "__main__":
    unittest.main()
