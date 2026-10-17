"""前端布局与新建/多选逻辑的静态检查（v0.1.3 §1~§4）。

这些用例读的是真实文件（index.html / files.js / app.css / fileops.js），断言的是
「结构约定」：列定义与表头同序、七个动作槽位的顺序与禁用语义、断点里先收哪一列、
预览框的滚动落在哪一层、新建名校验与「不做先查再建」。

为什么用静态检查而不是全部走浏览器：这些约定一旦被改坏，浏览器里只表现为
「位置偏了一点」或「偶尔覆盖了同名文件」，e2e 里很难稳定复现；而它们本身是
结构性的，直接对着源码断言反而更严格，也更快。真正的像素位置由
tests/e2e/test_browser_layout.py 在真实浏览器里量。
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
INDEX = FRONTEND / "index.html"
CSS = FRONTEND / "assets" / "css" / "app.css"
JS = FRONTEND / "assets" / "js"

#: 表格的列定义（v0.1.3 §2）：表头与每一行都必须按这个顺序排列。
COLUMNS = (
    "col-select",
    "col-name",
    "col-size",
    "col-type",
    "col-perm",
    "col-time",
    "col-action",
)

#: 行内七个动作的固定顺序（v0.1.3 §1）。
ACTIONS = ("edit", "copy", "cut", "rename", "delete", "compress", "extract")
ACTION_LABELS = ("编辑", "复制", "剪切", "重命名", "删除", "压缩", "解压")


def read(path):
    return path.read_text(encoding="utf-8")


def locate(text, start, end, label):
    """截出 start 与 end 之间的源码，用来把断言限定在一个函数/一段规则里。"""
    begin = text.find(start)
    if begin < 0:
        raise AssertionError("源码里找不到 %s 的起点：%r" % (label, start))
    finish = text.find(end, begin + len(start))
    if finish < 0:
        raise AssertionError("源码里找不到 %s 的终点：%r" % (label, end))
    return text[begin:finish]


def css_block(css, selector):
    """取某个选择器展开后的第一条规则正文（够用即可，不做完整 CSS 解析）。"""
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    if match is None:
        raise AssertionError("CSS 里找不到 %s 的规则" % selector)
    return match.group(1)


class TableStructureTests(unittest.TestCase):
    """§2：表头、列定义、行内单元格用的是同一套列定义。"""

    def setUp(self):
        self.html = read(INDEX)
        self.table = locate(self.html, '<table class="file-table" id="file-table"', "</table>", "文件表格")

    def test_colgroup_declares_the_same_columns_as_the_header(self):
        cols = re.findall(r'<col[^>]*class="([^"]+)"', self.table)
        self.assertEqual(tuple(cols), COLUMNS, "colgroup 的列定义与设计不一致：%r" % (cols,))
        header = re.search(r"<thead.*?</thead>", self.table, re.S).group(0)
        ths = [item.split()[0] for item in re.findall(r'<th[^>]*class="([^"]*)"', header)]
        self.assertEqual(tuple(ths), COLUMNS, "表头列顺序与 colgroup 不一致：%r" % (ths,))

    def test_every_row_builds_the_same_cells_in_the_same_order(self):
        source = read(JS / "files.js")
        row = locate(source, "function rowNode(entry)", "function actionCell(entry)", "rowNode")
        positions = [row.find('class: "%s"' % column) for column in COLUMNS if column != "col-action"]
        self.assertNotIn(-1, positions, "rowNode 少造了某一列：%r" % (positions,))
        self.assertEqual(positions, sorted(positions), "rowNode 的单元格顺序与表头不一致：%r" % (positions,))
        self.assertIn("actionCell(entry)", row, "操作列不是由 actionCell 生成的")

    def test_header_row_carries_the_select_all_checkbox(self):
        header = re.search(r"<thead.*?</thead>", self.table, re.S).group(0)
        self.assertIn('id="chk-select-all"', header, "表头缺少全选复选框")
        self.assertIn('type="checkbox"', header)

    def test_action_header_is_centred(self):
        css = read(CSS)
        self.assertIn("text-align: center", css_block(css, "#file-table th.col-action"),
                      "表头「操作」没有整列居中")

    def test_size_header_follows_the_numbers_to_the_right_edge(self):
        # 「对不准」的主因（v0.1.3 发布后实测）：.file-table thead th 的 text-align:left
        # 会盖掉 .col-size 的 right，于是「大小」表头贴左、数值贴右，一眼看着是两列。
        css = read(CSS)
        self.assertIn("text-align: right", css_block(css, "#file-table thead th.col-size"),
                      "表头「大小」没有跟着数值一起右对齐")

    def test_wide_screens_get_wider_information_columns(self):
        # 用户要求「信息栏可以多给一些位置」：宽屏上一律 96px 会把大小/时间挤成最短的一行。
        css = read(CSS)
        # 注意：文件里另有一处注释也提到 "@media (min-width: 1600px)"，
        # 所以起点带上左花括号，才不会从那条注释开始截。
        block = locate(css, "@media (min-width: 1600px) {", "在线虚拟机发现", "宽屏档")
        for column, width in (("col-size", 120), ("col-type", 108), ("col-perm", 136), ("col-time", 190)):
            rule = re.search(r"\.%s\s*\{\s*width:\s*(\d+)px" % column, block)
            self.assertIsNotNone(rule, "宽屏档里没有 %s 的列宽" % column)
            self.assertEqual(int(rule.group(1)), width, "宽屏档里 %s 的列宽与设计不一致" % column)


class ActionSlotTests(unittest.TestCase):
    """§1：七个槽位恒常存在、顺序固定、不适用者禁用而不是隐藏。"""

    def setUp(self):
        self.source = read(JS / "files.js")
        self.css = read(CSS)

    def test_action_order_matches_the_specification(self):
        match = re.search(r"export const ACTION_ORDER = \[([^\]]*)\]", self.source)
        self.assertIsNotNone(match, "files.js 里没有 ACTION_ORDER")
        order = tuple(re.findall(r'"([a-z]+)"', match.group(1)))
        self.assertEqual(order, ACTIONS, "动作顺序与 §1 要求的顺序不一致：%r" % (order,))

    def test_buttons_are_rendered_from_the_order_array(self):
        cell = locate(self.source, "function actionCell(entry)", "const cell = h(", "actionCell")
        self.assertIn('class: "file-actions-box"', cell, "操作按钮没有独立容器")
        self.assertIn("for (const key of ACTION_ORDER)", cell, "按钮不是按 ACTION_ORDER 顺序渲染的")
        self.assertIn('"data-action": key', cell)
        self.assertIn('class: "btn btn-small btn-" + key + "-entry"', cell)

    def test_labels_follow_the_same_order(self):
        slots = locate(self.source, "const slots = {", "const box = h(", "动作表")
        labels = tuple(re.findall(r'label: "([^"]+)"', slots))
        self.assertEqual(labels, ACTION_LABELS, "按钮文字或顺序不对：%r" % (labels,))

    def test_each_action_is_enabled_for_the_right_entry_types(self):
        slots = locate(self.source, "const slots = {", "const box = h(", "动作表")
        enabled = dict(
            re.findall(r"(\w+): \{.*?enabled: ([^,]+),", slots, re.S)
        )
        self.assertEqual(enabled.get("edit"), "connected && isFile", "只有文件能编辑")
        self.assertEqual(enabled.get("copy"), "connected", "复制只写本地剪贴板，不需要写权限")
        for key in ("cut", "rename", "delete", "compress"):
            self.assertEqual(enabled.get(key), "connected && writable", "%s 需要写权限" % key)
        self.assertEqual(enabled.get("extract"), "connected && writable && archive",
                         "解压需要写权限，且只有压缩包能解")

    def test_disabled_buttons_still_explain_themselves(self):
        cell = locate(self.source, "function actionCell(entry)", "const cell = h(", "actionCell")
        self.assertIn("disabled: !slot.enabled", cell)
        self.assertIn("title: slot.enabled ? slot.label : slot.reason", cell,
                      "禁用时要把原因写进 title，光灰掉等于没说")
        self.assertIn("目录不能编辑。", cell)
        self.assertIn("符号链接不能直接编辑。", cell)
        self.assertIn("只有压缩包才能解压。", cell)
        self.assertIn('const WRITE_HINT = "需要先打开「允许写操作」"', self.source)

    def test_the_action_box_reserves_seven_slots_at_every_breakpoint(self):
        box = css_block(self.css, "#file-table .file-actions-box")
        self.assertIn("repeat(7, 44px)", box, "基准断点没有给足七个槽位：%r" % box)
        self.assertIn("justify-content: center", box, "按钮没有整列居中")
        # 每次收窄都只改槽位宽度，槽位数始终是 7：一改数量，位置就会跳。
        self.assertIn("repeat(7, 40px)", self.css, "≤1280 断点没有保持七个槽位")
        self.assertIn("repeat(7, 38px)", self.css, "≤1120 断点没有保持七个槽位")
        self.assertIn("repeat(4, 52px)", self.css, "≤880 断点应当折成 4 + 3 两行")

    def test_all_seven_buttons_share_one_box_size(self):
        button = css_block(self.css, "#file-table .file-actions-box .btn")
        self.assertIn("height: 24px", button, "七个按钮高度不一致：%r" % button)
        self.assertIn("line-height: 22px", button, "按钮文字没有统一基线")
        self.assertIn("text-align: center", button)
        self.assertIn("padding: 0", button, "按钮内边距不统一就会有的高一点")

    def test_old_five_slot_layout_is_gone(self):
        for path in (CSS, JS / "files.js"):
            self.assertNotIn("row-actions", read(path), "v0.1.2 的五槽位布局还留着：%s" % path.name)


class BreakpointTests(unittest.TestCase):
    """§1/§2：窗口变窄时先收整列、再收槽位，收的顺序写死并被测到。"""

    def setUp(self):
        self.css = read(CSS)

    def hidden_at(self, width, column):
        match = re.search(r"@media \(max-width: %dpx\) \{(.*?)\n\}" % width, self.css, re.S)
        self.assertIsNotNone(match, "找不到 %dpx 的断点" % width)
        body = match.group(1)
        return (
            "col.%s" % column in body
            and "th.%s" % column in body
            and "td.%s" % column in body
        )

    def test_columns_are_dropped_in_the_documented_order(self):
        # 门槛按「收起后名字列还剩多少」定：信息列加宽后，1121~1239 这一带同时放
        # 名称 + 大小 + 类型 + 权限 + 时间 + 七格按钮已经会横向滚动（v0.1.3 实测），
        # 所以权限列从 1120 提前到 1240 收，类型列从 1020 提前到 1120 收。
        self.assertTrue(self.hidden_at(1240, "col-perm"), "≤1240 没有收起权限列")
        self.assertTrue(self.hidden_at(1120, "col-type"), "≤1120 没有收起类型列")
        self.assertTrue(self.hidden_at(1000, "col-time"), "≤1000 没有收起修改时间列")
        self.assertTrue(self.hidden_at(740, "col-size"), "≤740 没有收起大小列")

    def test_the_select_column_only_takes_width_in_multi_select_mode(self):
        self.assertIn(
            "#file-table:not(.has-select) .col-select { display: none; }",
            self.css,
            "非多选模式下复选框列应当整列不占宽度",
        )
        self.assertIn("col.col-select { width: 36px; }", self.css)


class PreviewBoxTests(unittest.TestCase):
    """§3：预览内容装进独立容器，标题/状态与正文分开，超长内容在框内滚动。"""

    def setUp(self):
        self.source = read(JS / "preview.js")
        self.css = read(CSS)

    def test_preview_content_lives_in_its_own_box(self):
        for cls in ("preview-box", "preview-box-head", "preview-box-title", "preview-box-meta",
                    "preview-box-body"):
            self.assertIn('"%s"' % cls, self.source, "预览没有用到 %s" % cls)
        body_at = self.source.find('"preview-box-body"')
        text_at = self.source.find('"preview-text"')
        self.assertGreater(body_at, -1, "预览正文没有独立容器")
        self.assertGreater(text_at, body_at, "正文没有放进框身里")

    def test_title_and_meta_are_separated_from_the_text(self):
        head_at = self.source.find('"preview-box-head"')
        text_at = self.source.find('"preview-text"')
        self.assertLess(head_at, text_at, "框头应当在正文之前")

    def test_scrolling_happens_inside_the_box_not_the_modal(self):
        body = css_block(self.css, ".preview-box-body")
        self.assertIn("overflow: auto", body, "框身没有自己滚动：%r" % body)
        self.assertIn("max-height", body, "框身没有高度上限，长文本会把模态框撑高")
        text = css_block(self.css, ".preview-text")
        self.assertNotIn("max-height", text, "滚动还是落在 pre 上，标题会跟着滚走")
        self.assertIn("white-space: pre-wrap", text, "预览要保留换行与缩进")
        self.assertIn("word-break: break-word", text, "长行不许撑破框")

    def test_existing_error_reporting_is_reused(self):
        # 二进制/超大文件仍然走原来的提示，不另造一套「成功但空白」的路径。
        self.assertIn("payload_too_large", self.source)
        self.assertIn("toastError", self.source)


class CreateAndClipboardTests(unittest.TestCase):
    """§4：新建的界面侧校验、粘贴的冲突处理与跨连接拒绝。"""

    def setUp(self):
        self.source = read(JS / "fileops.js")
        self.api = read(JS / "api.js")
        self.state = read(JS / "state.js")
        self.app = read(JS / "app.js")

    def test_name_validation_rejects_everything_the_server_would_reject(self):
        rule = locate(self.source, "function nameProblem(raw)", "export async function createEntry",
                      "nameProblem")
        self.assertIn('=== ""', rule, "空名字没有被拒")
        self.assertIn('=== "."', rule)
        self.assertIn('=== ".."', rule)
        self.assertIn('indexOf("/")', rule, "含分隔符的名字没有被拒")
        self.assertIn("String.fromCharCode(0)", rule, "含控制字符的名字没有被拒")
        self.assertGreaterEqual(len(re.findall(r"255", rule)), 1, "超长名字没有被拒")

    def test_create_goes_straight_to_the_server_without_a_pre_flight_check(self):
        create = locate(self.source, "export async function createEntry", "function rememberClipboard",
                        "createEntry")
        self.assertIn("api.createEntry(", create)
        self.assertNotIn("listFiles", create, "不许先查再建：并发下会变成静默覆盖")
        self.assertIn("state.path", create, "新建要落在当前目录")
        self.assertIn('kind', create)

    def test_created_entry_is_confirmed_against_the_refreshed_list(self):
        create = locate(self.source, "export async function createEntry", "function rememberClipboard",
                        "createEntry")
        self.assertIn("refreshList", create, "创建后必须刷新列表")
        self.assertIn("(state.entries || []).some", create, "刷新后要确认条目真的出现了")
        self.assertIn("列表没能刷新", create, "刷新失败要与「创建失败」区分开")

    def test_api_posts_the_documented_payloads(self):
        self.assertIn('"/create"', self.api)
        self.assertIn('"/copy"', self.api)
        self.assertIn('"/move"', self.api)
        create = locate(self.api, "export function createEntry", "export function copyEntries", "api.createEntry")
        self.assertIn("{ path: directory, name: name, kind: kind }", create)

    def test_paste_refuses_a_clipboard_from_another_connection(self):
        paste = locate(self.source, "export async function paste()", "function reportFailure", "paste")
        self.assertIn("clip.connectionId !== conn.id", paste, "跨连接的剪贴板必须拒绝")
        self.assertIn("api.moveEntries(", paste, "剪切走 move")
        self.assertIn(
            "api.copyEntries(conn.id, clip.paths, into, true)", paste, "同名冲突确认后要能覆盖"
        )

    def test_clipboard_state_is_kept_with_its_connection(self):
        self.assertIn("clipboard: null", self.state)
        self.assertIn("export function hasClipboard()", self.state)
        self.assertIn("export function checkedEntries()", self.state)
        self.assertIn("connectionId", self.state, "剪贴板要记住自己来自哪条连接")

    def test_toolbar_paste_button_follows_the_clipboard(self):
        toolbar = locate(self.app, "function updateToolbar()", "function handleSaved()", "updateToolbar")
        self.assertIn('"#btn-paste"', toolbar)
        self.assertIn("hasClipboard()", toolbar)
        self.assertIn("clip.connectionId === conn.id", toolbar)


class MultiSelectTests(unittest.TestCase):
    """§4：多选是界面状态，勾选结果要能一路传到批量动作。"""

    def setUp(self):
        self.source = read(JS / "files.js")
        self.css = read(CSS)

    def test_every_row_gets_a_checkbox_bound_to_its_path(self):
        row = locate(self.source, "function rowNode(entry)", "function actionCell(entry)", "rowNode")
        self.assertIn('class: "row-check"', row)
        self.assertIn('"data-path": entry.path', row)
        self.assertIn("toggleChecked(entry.path)", row)

    def test_multi_select_toggles_one_class_on_the_table(self):
        source = read(JS / "files.js")
        self.assertIn('export function setMultiSelect(', source)
        self.assertIn('"has-select"', source, "多选只改表格上的一个类，不重绘列表")
        self.assertIn('id="btn-select-mode"', read(INDEX))

    def test_selection_bar_exposes_the_batch_actions(self):
        html = read(INDEX)
        bar = locate(html, 'id="sel-bar"', "</div>", "多选操作条")
        for button in ("btn-sel-all", "btn-sel-copy", "btn-sel-cut", "btn-sel-delete",
                       "btn-sel-compress", "btn-sel-extract", "btn-sel-clear"):
            self.assertIn('id="%s"' % button, bar, "多选操作条缺少 %s" % button)
        self.assertIn('id="sel-count"', bar)

    def test_selection_bar_is_hidden_until_multi_select_is_on(self):
        html = read(INDEX)
        self.assertIn('id="sel-bar" hidden', html, "操作条默认应当隐藏")
        self.assertIn('const bar = $("#sel-bar");', read(JS / "files.js"))


class ToolbarTests(unittest.TestCase):
    """§4：工具栏入口本身（按钮存在、文案正确、初始状态正确）。"""

    def setUp(self):
        self.html = read(INDEX)

    def test_new_entry_buttons_exist(self):
        toolbar = locate(self.html, 'class="toolbar-right"', "</div>", "工具栏")
        for button_id, text in (("btn-new-file", "新建文件"), ("btn-new-folder", "新建文件夹"),
                                ("btn-paste", "粘贴"), ("btn-select-mode", "多选")):
            pattern = r'<button[^>]*id="%s"[^>]*>([^<]*)</button>' % button_id
            match = re.search(pattern, toolbar)
            self.assertIsNotNone(match, "工具栏缺少 %s" % button_id)
            self.assertEqual(match.group(1).strip(), text, "%s 的文案不对" % button_id)


if __name__ == "__main__":
    unittest.main()
