"""在线虚拟机发现的端到端验证（任务书 2.md 阶段五）。

阶段五要求：能自动找出本机上「现在能连」的虚拟机，并且把「发现了虚拟机」「地址在线」
「SSH 可用」三件事分开说；用户挑中一台机器后，地址能直接喂给「新增连接」表单，而保存
与连接仍然由用户点。

这些结论只有在真实浏览器里才说得清：面板什么时候出现、状态药丸写什么、中止按钮什么
时候才出现、点「创建连接」之后模态里填进去的是什么 —— 都是渲染出来才有的东西。

浏览器是真实 Edge：无头 + --inprivate + 全新临时配置目录（与其它 e2e 用例同一口径）。

**不与测试床绑死**：发现读的是宿主机自己（VMware 清单 / 虚拟机配置 / DHCP 租约 /
系统邻居表 / 本机虚拟网段的少量探测），跟 WSL 测试床无关，所以这里不挂 require_testbed，
配置也不填任何连接。机器上确实没有 VMware 时，用例会说清原因并跳过 —— 那不是失败。
"""

from __future__ import annotations

import contextlib
import json
import re
import sys
import unittest
import uuid
from pathlib import Path

from tests.e2e.support import browser_session
from tests.integration.support import running_server, testbed_environment

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
RUN_TAG = uuid.uuid4().hex[:8]

#: 面板上的三个关键节点。状态药丸的 data-state 是判定的唯一依据（文案可能改，状态名不会）。
STATUS_STATE = "document.getElementById('discovery-status').dataset.state"
TERMINAL_STATE = "['done', 'failed', 'cancelled'].indexOf(" + STATUS_STATE + ") >= 0"

#: 环境来源表：每行是 来源 / 状态 / 说明。
ENV_ROWS = (
    "Array.from(document.querySelectorAll('#discovery-env-body .discovery-sources tbody tr'))"
    ".map(function (row) {"
    " var cells = row.querySelectorAll('td');"
    " return { label: cells[0] ? cells[0].textContent : '',"
    "          state: cells[1] ? cells[1].textContent : '',"
    "          stateClass: cells[1] ? cells[1].className : '',"
    "          detail: cells[2] ? cells[2].textContent : '' }; })"
)

#: 虚拟机结果表：名称 / 状态 / 地址 / 能不能连 / 操作。
#: 「操作」列里的按钮带 data-ip，用它交叉核对地址列显示的就是要填进表单的那个地址。
VM_ROWS = (
    "Array.from(document.querySelectorAll('#discovery-vm-body tr'))"
    ".map(function (row) {"
    " var cells = row.querySelectorAll('td');"
    " var ipNode = cells[2] ? cells[2].querySelector('.discovery-ip') : null;"
    " var answer = cells[3] ? cells[3].querySelector('.discovery-answer') : null;"
    " var button = row.querySelector('button');"
    " return {"
    "   name: cells[0] && cells[0].querySelector('.discovery-name') ? cells[0].querySelector('.discovery-name').textContent : '',"
    "   state: cells[1] ? cells[1].innerText : '',"
    "   ip: ipNode ? ipNode.textContent : '',"
    "   stateLine: cells[2] ? cells[2].innerText : '',"
    "   answer: answer ? answer.textContent : '',"
    "   answerState: answer ? answer.dataset.state : '',"
    "   answerLine: cells[3] ? cells[3].innerText : '',"
    "   buttonIp: button ? button.dataset.ip : null,"
    "   buttonText: button ? button.textContent : '' }; })"
)

#: 点第一行有「创建连接」的按钮，并把它的 data-ip 带回来（返回值经 CDP 回到 Python）。
CLICK_FIRST_CREATE = (
    "(function () {"
    " var rows = document.querySelectorAll('#discovery-vm-body tr');"
    " for (var i = 0; i < rows.length; i += 1) {"
    "   var button = rows[i].querySelector('button');"
    "   if (button) { var ip = button.dataset.ip; button.click(); return ip; }"
    " }"
    " return null; })()"
)

#: 「新增连接」表单：按类型取输入框（表单里的输入框没有 id）。
FORM_VALUES = (
    "(function () {"
    " var texts = document.querySelectorAll('#modal-body input[type=\"text\"]');"
    " var number = document.querySelector('#modal-body input[type=\"number\"]');"
    " var note = document.querySelector('#modal-body input[maxlength=\"200\"]');"
    " var notice = document.querySelector('#modal-body .form-notice');"
    " return { title: document.getElementById('modal-title').textContent,"
    "          name: texts[0] ? texts[0].value : null,"
    "          host: texts[1] ? texts[1].value : null,"
    "          port: number ? number.value : null,"
    "          note: note ? note.value : null,"
    "          notice: notice ? notice.textContent : '',"
    "          foot: document.getElementById('modal-foot').innerText,"
    "          modals: document.querySelectorAll('#modal-root .modal').length,"
    "          discoveryGone: document.getElementById('discovery-status') === null }; })()"
)


def js(value: str) -> str:
    """把 Python 字符串写成 JS 字面量（中文不用转义）。"""
    return json.dumps(value, ensure_ascii=False)


def count_in_title(text: str) -> int:
    """从「发现的虚拟机（3 台）」里取出台数。"""
    match = re.search(r"（(\d+) 台）", text)
    if not match:
        raise AssertionError("结果标题里没有台数：" + text)
    return int(match.group(1))


class BrowserDiscoveryTests(unittest.TestCase):
    """不需要测试床：发现功能读的就是跑着服务器的这台机器。"""

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        # trust=False：不连任何测试床，也就不会因为 WSL 没起来而失败。
        self.config, _keys = self.stack.enter_context(
            testbed_environment(connections=[], trust=False)
        )
        self.client = self.stack.enter_context(running_server(self.config))
        self.base_url = self.client.base

    # ------------------------------------------------------------------ 夹具
    def open_panel(self, page):
        """像用户那样从首页点开侧栏的「扫描」。"""
        page.navigate(self.base_url + "/")
        page.wait_for("!document.getElementById('app').hidden", message="页面外壳没有显示出来")
        page.install_helpers()
        page.evaluate("document.getElementById('btn-scan-vms').click()")
        page.wait_for("!!document.getElementById('discovery-status')", message="发现面板没有打开")
        # 环境信息是异步取的：等来源表（或明确的一句读不到）落下来再断言。
        page.wait_for(
            "!!document.querySelector('#discovery-env-body .discovery-sources')"
            " || !!document.querySelector('#discovery-env-body .is-warn')",
            timeout=30,
            message="本机环境信息没有渲染出来",
        )

    def start_scan(self, page):
        """点「开始扫描 / 重新扫描」，并等状态真的翻到「运行中」。

        点了之后 DOM 里还留着上一次的结论（药丸上写着「已中止」或「已完成」），而 POST
        是异步的：不等它翻页就接着判「结束了没有」，会把上一次的结论当成这一次的。
        """
        before = self.scan_state(page)
        page.evaluate("document.getElementById('btn-discovery-start').click()")
        page.wait_for(
            STATUS_STATE + " === 'running'",
            timeout=30,
            message="点了开始扫描，状态却还停在 " + before,
        )

    def wait_terminal(self, page, *, timeout: float = 180.0):
        page.wait_for(TERMINAL_STATE, timeout=timeout, message="扫描没有结束")
        return self.scan_state(page)

    def scan_state(self, page) -> str:
        return page.evaluate(STATUS_STATE)

    def status_text(self, page) -> str:
        return page.evaluate("document.getElementById('discovery-status').textContent")

    def progress_text(self, page) -> str:
        return page.evaluate("document.getElementById('discovery-progress').textContent")

    def hint_text(self, page) -> str:
        return page.evaluate(
            "(function () { var h = document.getElementById('discovery-hint');"
            " return h.hidden ? '' : h.textContent; })()"
        )

    def cancel_hidden(self, page) -> bool:
        return page.evaluate("document.getElementById('btn-discovery-cancel').hidden")

    def start_button(self, page) -> dict:
        return page.evaluate(
            "(function () { var b = document.getElementById('btn-discovery-start');"
            " return { text: b.textContent, disabled: b.disabled }; })()"
        )

    def env_rows(self, page):
        return page.evaluate(ENV_ROWS)

    def vm_rows(self, page):
        return page.evaluate(VM_ROWS)

    def scan_to_done(self, page):
        """扫到结束；失败时把界面上的原因带进断言消息，省得再猜。"""
        self.start_scan(page)
        state = self.wait_terminal(page)
        if state != "done":
            self.fail(
                "扫描没有正常结束：state=" + state + "，提示=" + (self.hint_text(page) or "（无）")
            )
        return self.vm_rows(page)

    def require_vms(self, page, rows):
        """本机没有 VMware（或清单为空）时跳过 —— 说清原因，不把红色当失败。"""
        if not rows:
            raise unittest.SkipTest(
                "本机的 VMware 清单里没有虚拟机，跳过与具体机器有关的断言："
                + (self.hint_text(page) or "（界面没有给出说明）")
            )

    # ------------------------------------------------------------------ 用例
    def test_panel_says_what_this_machine_can_read(self):
        """打开面板先说清「我能读到什么」，读不到的也要说清为什么。"""
        with browser_session() as page:
            self.open_panel(page)

            self.assertEqual(self.scan_state(page), "idle")
            self.assertEqual(self.status_text(page), "还没有扫描")
            self.assertTrue(self.cancel_hidden(page), "还没开始扫就把中止按钮摆出来了")
            self.assertIn("开始扫描", self.start_button(page)["text"])

            rows = self.env_rows(page)
            self.assertTrue(rows, "环境来源表是空的")
            for row in rows:
                self.assertTrue(row["label"], "来源行没有名字：" + repr(row))
                self.assertTrue(row["state"], "来源行没有状态：" + repr(row))
            if sys.platform == "win32":
                # 读 VMware 进程的命令行需要管理员权限，这条来源必须如实说「需要管理员权限」，
                # 而不是悄悄留空 —— 少一条来源就等于少一个判断「虚拟机在不在跑」的依据。
                denied = [row for row in rows if row["state"] == "需要管理员权限"]
                self.assertTrue(denied, "没有如实说明读不到的来源：" + repr(rows))
                self.assertIn("is-warn", " ".join(row["stateClass"] for row in denied))

            # 来源详情默认收着（模态里不占地方），展开后要能看到探测上限。
            self.assertFalse(
                page.evaluate("document.getElementById('discovery-env').open"),
                "来源详情默认是展开的，模态里太占地方",
            )
            env_box = "(function () { var d = document.getElementById('discovery-env');"
            page.evaluate(env_box + " d.open = true; return true; })()")
            details = page.evaluate("document.getElementById('discovery-env-body').innerText")
            self.assertIn("探测上限", details)
            self.assertIn("单地址超时", details)
            self.assertIn("每网段最多", details)
            # 还没扫之前，界面要告诉用户点下去会发生什么。
            self.assertIn("开始扫描", self.hint_text(page))

            page.screenshot(ARTIFACTS_DIR / ("browser-discovery-panel-" + RUN_TAG + ".png"))

    def test_scan_lists_vms_and_keeps_the_three_states_apart(self):
        """扫完的结果：台数与行数一致，「发现了什么」和「能不能连」分开说。"""
        with browser_session() as page:
            self.open_panel(page)
            rows = self.scan_to_done(page)
            self.require_vms(page, rows)

            # 标题里的台数、progress 里的台数、表里的行数，三处必须是同一个数。
            self.assertEqual(
                count_in_title(page.evaluate("document.getElementById('discovery-vms-title').textContent")),
                len(rows),
            )
            progress = self.progress_text(page)
            match = re.search(r"虚拟机 (\d+) 台（运行中 (\d+)）", progress)
            self.assertIsNotNone(match, "进度里没有台数：" + progress)
            self.assertEqual(int(match.group(1)), len(rows))
            self.assertIn("用时", progress)
            self.assertFalse(
                page.evaluate("document.getElementById('discovery-vms').hidden"),
                "有结果却把结果表收起来了",
            )

            running_rows = 0
            ssh_rows = 0
            for row in rows:
                self.assertTrue(row["name"], "结果行没有名称：" + repr(row))
                self.assertIn(row["state"].split("\n")[0], ("运行中", "已关机", "未知"))
                if row["state"].startswith("运行中"):
                    running_rows += 1
                if row["state"].startswith("未知"):
                    # 读不到运行状态时必须承认，不能替用户写成「已关机」。
                    self.assertIn("读不到运行状态", row["state"])
                if row["answerState"] == "ssh_open":
                    ssh_rows += 1
                    self.assertEqual(row["answer"], "SSH 可用")
                    self.assertEqual(row["buttonIp"], row["ip"].split(":")[0])
                    self.assertEqual(row["buttonText"], "创建连接")
                elif row["answerState"] == "unknown_address":
                    self.assertEqual(row["answer"], "没有地址")
                    self.assertIsNone(row["buttonIp"], "没有地址却给了「创建连接」：" + repr(row))
                else:
                    # 探测过但没有 SSH：结论归结论，还要说清「可以自己再试一次」。
                    self.assertIn("再试一次", row["answerLine"])
            self.assertEqual(int(match.group(2)), running_rows, "运行中的台数与行里的状态不一致")
            if ssh_rows:
                self.assertIn("能连 SSH", progress)

            page.screenshot(ARTIFACTS_DIR / ("browser-discovery-scan-" + RUN_TAG + ".png"))

    def test_cancel_stops_the_scan_and_frees_the_activity_slot(self):
        """中止：状态要变成「已中止」、要留下已经拿到的部分，槽位还要能再扫一次。"""
        with browser_session() as page:
            self.open_panel(page)
            self.start_scan(page)
            self.assertFalse(self.cancel_hidden(page), "扫描在跑，却没有给出中止按钮")
            page.evaluate("document.getElementById('btn-discovery-cancel').click()")

            state = self.wait_terminal(page, timeout=120)
            # 后端的语义：活儿干完了就是 done（谎报中止会让用户以为结果是残缺的）。
            self.assertEqual(state, "cancelled", "中止之后状态是 " + state + "：" + self.hint_text(page))
            self.assertEqual(self.status_text(page), "已中止")
            self.assertTrue(self.cancel_hidden(page))
            self.assertFalse(self.start_button(page)["disabled"], "中止之后不能重新扫描")
            self.assertIn("重新扫描", self.start_button(page)["text"])
            self.assertIn("已中止", self.hint_text(page))

            page.screenshot(ARTIFACTS_DIR / ("browser-discovery-cancelled-" + RUN_TAG + ".png"))

            # 槽位真的空出来了：紧接着的一次扫描必须能跑完（否则后端会回 409）。
            self.scan_to_done(page)

    def test_create_connection_fills_the_form_but_saves_nothing(self):
        """挑中一台机器：地址只进表单，不保存、不连接、不算编辑。"""
        with browser_session() as page:
            self.open_panel(page)
            rows = self.scan_to_done(page)
            self.require_vms(page, rows)
            candidates = [row for row in rows if row["buttonIp"]]
            if not candidates:
                raise unittest.SkipTest("这次扫描没有拿到任何地址，跳过预填表单的断言。")

            clicked = page.evaluate(CLICK_FIRST_CREATE)
            self.assertIsNotNone(clicked, "结果表里没有可点的「创建连接」")
            page.wait_for(
                "document.getElementById('modal-title').textContent === " + js("新增连接"),
                message="没有打开新增连接表单",
            )

            form = page.evaluate(FORM_VALUES)
            self.assertEqual(form["host"], clicked)
            self.assertEqual(form["port"], "22")
            self.assertEqual(form["title"], "新增连接")
            # 草稿不是「已有连接」：底部按钮必须是「新增」，不能是「保存」（那会去 PATCH 一个不存在的 id）。
            self.assertIn("新增", form["foot"])
            self.assertNotIn("保存", form["foot"])
            self.assertIn("扫描本机虚拟机", form["note"])
            self.assertIn("候选地址", form["notice"])
            # 模态只有一个：发现面板已经让位，不是叠在上面。
            self.assertEqual(form["modals"], 1)
            self.assertTrue(form["discoveryGone"], "发现面板还留在 DOM 里")

            page.screenshot(ARTIFACTS_DIR / ("browser-discovery-connection-" + RUN_TAG + ".png"))


if __name__ == "__main__":
    unittest.main()
