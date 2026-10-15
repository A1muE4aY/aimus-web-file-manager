"""远端文件检索的集成测试（规划文档 §5 阶段三、§7.2）。

跑在真实 WSL 测试床 + 真实 HTTP 服务上，验证「浏览器点一次搜索 → 服务端真的按名字
找出了文件」这条完整路径。目录树由 tests.integration.support 的 search_fixture() 摆好，
刻意覆盖中文名、大小写、嵌套、符号链接、无权限目录、目录环，另有一棵只给「中止」用的大树。

单元测试（tests/unit/test_search.py）用假树覆盖边界条件，这里覆盖「真实 SFTP 会返回什么」：
属性字段是否齐全、无权限目录报什么错、符号链接的真实类型、广度优先的顺序。
"""

from __future__ import annotations

import contextlib
import time
import unittest
from urllib.parse import quote

from tests.integration.support import (
    require_testbed,
    running_server,
    search_and_wait,
    search_fixture,
    start_search,
    testbed_connection,
    testbed_environment,
    wait_for_search,
)

CONNECTION = "wsl-testbed"


def api(path: str) -> str:
    return "/api/connections/" + CONNECTION + path


def files_url(path: str) -> str:
    return api("/files?path=" + quote(path, safe=""))


def rows(snapshot: dict) -> list:
    return list(snapshot.get("results") or [])


def located(snapshot: dict) -> set:
    """把结果转成「(名字, 所在目录)」集合 —— 比整行比对更抗字段增删。"""
    return {(row["name"], row["parent"]) for row in rows(snapshot)}


@require_testbed
class SearchApiTests(unittest.TestCase):
    """真实测试床上的搜索接口。"""

    @classmethod
    def setUpClass(cls):
        cls._stack = contextlib.ExitStack()
        config, _keys = cls._stack.enter_context(
            testbed_environment(connections=[testbed_connection(allow_write=True)])
        )
        cls.client = cls._stack.enter_context(running_server(config))
        cls.fixture = cls._stack.enter_context(search_fixture())
        cls.root = cls.fixture["root"]
        cls.bulk = cls.fixture["bulk"]
        response = cls.client.post(api("/connect"))
        if not response.ok:
            cls._stack.close()
            raise AssertionError("测试床连接失败：" + repr(response))

    @classmethod
    def tearDownClass(cls):
        cls._stack.close()

    def setUp(self):
        self.ensure_connected()

    # ------------------------------------------------------------------ 助手

    def ensure_connected(self) -> None:
        """有连接就复用；断连测试留下的断口在这里补回来。"""
        probe = self.client.get(files_url(self.root))
        if probe.ok:
            return
        reconnect = self.client.post(api("/connect"))
        self.assertTrue(reconnect.ok, "重新连接测试床失败：" + repr(reconnect))

    def search(self, query: str, *, path: str | None = None) -> dict:
        snapshot = search_and_wait(self.client, path=path or self.root, query=query)
        self.assertEqual(snapshot["status"], "done", "搜索没有正常结束：" + repr(snapshot))
        self.assertEqual(snapshot["root"], path or self.root)
        self.assertEqual(snapshot["query"], query)
        return snapshot

    # ------------------------------------------------------------------ 命中

    def test_finds_chinese_names_at_every_depth(self):
        """中文名、嵌套目录里的中文名都要能找到。"""
        snapshot = self.search("报告")
        self.assertEqual(
            located(snapshot),
            {
                ("报告.txt", self.root),
                ("报告-草稿.txt", self.root),
                ("报告.txt", self.root + "/子目录/深层"),
            },
        )

    def test_match_ignores_case(self):
        """大小写不敏感：小写 report 要命中 Report.md 与 Case/REPORT.TXT。"""
        snapshot = self.search("report")
        self.assertEqual(
            located(snapshot),
            {
                ("link-to-report", self.root),
                ("many-report.txt", self.root),
                ("report-final.txt", self.root),
                ("Report.md", self.root),
                ("REPORT.TXT", self.root + "/Case"),
            },
        )
        # 顺序：目录 → 符号链接 → 文件（_result_key 的排序契约）。
        self.assertEqual(
            [row["type"] for row in rows(snapshot)],
            ["symlink", "file", "file", "file", "file"],
        )
        self.assertEqual(
            [row["name"] for row in rows(snapshot)],
            ["link-to-report", "many-report.txt", "report-final.txt", "Report.md", "REPORT.TXT"],
        )

    def test_directories_come_before_files(self):
        """同一个关键词同时命中目录与文件时，目录排前面。"""
        snapshot = self.search("many")
        self.assertEqual([row["name"] for row in rows(snapshot)], ["many", "many-report.txt"])
        self.assertEqual(rows(snapshot)[0]["type"], "directory")

    def test_nested_result_reports_parent_and_depth(self):
        """depth 是「相对搜索根往下第几层」，根的直接子项是 1。"""
        deep = self.search("深层")
        self.assertEqual(len(rows(deep)), 1)
        row = rows(deep)[0]
        self.assertEqual(row["type"], "directory")
        self.assertEqual(row["parent"], self.root + "/子目录")
        self.assertEqual(row["depth"], 2)

        named = self.search("报告.txt")
        by_parent = {row["parent"]: row for row in rows(named)}
        self.assertEqual(set(by_parent), {self.root, self.root + "/子目录/深层"})
        self.assertEqual(by_parent[self.root]["depth"], 1)
        self.assertEqual(by_parent[self.root + "/子目录/深层"]["depth"], 3)

    def test_rows_carry_the_fields_the_table_needs(self):
        """结果行要能直接渲染表格：名字、路径、所在目录、类型、大小、时间、层数。"""
        snapshot = self.search("报告.txt")
        required = {"name", "path", "parent", "type", "size", "mtime", "depth", "mode"}
        for row in rows(snapshot):
            self.assertTrue(required.issubset(row.keys()), "结果行缺字段：" + repr(sorted(row)))
            self.assertEqual(row["path"], self.root + "/" + row["name"] if row["parent"] == self.root else row["parent"] + "/" + row["name"])
            self.assertIsInstance(row["size"], int)
            self.assertIsInstance(row["mtime"], int)
            self.assertGreater(row["mtime"], 0)
        root_row = [row for row in rows(snapshot) if row["parent"] == self.root][0]
        self.assertEqual(root_row["size"], len("hello-world-search\n"))

    # ------------------------------------------------------------------ 空结果与上限

    def test_no_match_is_a_normal_finished_search(self):
        """搜不到不是错误：状态仍是 done，只是 0 条结果。"""
        snapshot = self.search("绝不存在的名字-zzz")
        self.assertEqual(snapshot["result_count"], 0)
        self.assertEqual(rows(snapshot), [])
        self.assertFalse(snapshot["truncated"])
        self.assertIsNone(snapshot["truncated_reason"])
        self.assertIsNone(snapshot["error"])

    def test_unreadable_directory_is_skipped_and_reported(self):
        """无权限目录要跳过并计数 —— 界面据此提示「有 N 个目录读不到」。"""
        snapshot = self.search("报告")
        self.assertEqual(snapshot["skipped_dirs"], 1)
        self.assertEqual(snapshot["skipped"][0]["path"], self.root + "/locked")
        self.assertEqual(snapshot["skipped"][0]["code"], "permission_denied")
        # 里面那个文件不该出现在结果里：它不是「搜不到」，是根本没读进去。
        self.assertNotIn(self.root + "/locked", {row["parent"] for row in rows(snapshot)})

    def test_limits_travel_with_the_result(self):
        """上限随结果一起回传，界面才能解释「为什么提前结束」。"""
        snapshot = self.search("报告")
        self.assertEqual(
            snapshot["limits"],
            {
                "max_results": 500,
                "max_dirs": 2000,
                "max_entries": 100000,
                "time_budget_seconds": 45.0,
            },
        )
        self.assertLessEqual(snapshot["result_count"], snapshot["limits"]["max_results"])

    # ------------------------------------------------------------------ 符号链接与环

    def test_symlinks_are_reported_but_not_followed(self):
        """符号链接只作为结果出现；指回搜索根的环不能让搜索转个不停。"""
        started = time.time()
        snapshot = self.search("回环")
        elapsed = time.time() - started
        self.assertEqual(len(rows(snapshot)), 1)
        self.assertEqual(rows(snapshot)[0]["type"], "symlink")
        self.assertEqual(rows(snapshot)[0]["parent"], self.root + "/循环目录")
        # 小树只有 6 个可读目录；要是跟着环走进去，这个数字会一路涨上去。
        self.assertLessEqual(snapshot["scanned_dirs"], 12)
        self.assertLess(elapsed, 20.0)

    def test_symlink_pointing_outside_the_root_is_not_walked_into(self):
        """跟着链接下钻会跑出搜索根；只在根内走，是「不越界」的正面证明。

        测试床在小树之外摆了一个只通过 link-to-outside 可达的目录
        （/tmp/awfm-search-outside/only-here.txt）。结果里出现 only-here.txt
        就说明搜索顺着链接跑出了用户选定的范围。
        """
        outside = self.search("only-here")
        self.assertEqual(rows(outside), [])
        self.assertEqual(outside["status"], "done")

        # 链接自己仍然是根里的一条普通条目：它该被列出来，只是不该被走进去。
        link = self.search("link-to-outside")
        self.assertEqual(len(rows(link)), 1)
        self.assertEqual(rows(link)[0]["type"], "symlink")

    # ------------------------------------------------------------------ 中止与并发

    def test_cancel_stops_a_running_search(self):
        """中止要真的停下（不是等它自己跑完），并且不留下「截断」的假象。"""
        started = start_search(self.client, path=self.bulk, query="zzz-没有这个文件")
        self.assertEqual(started.status, 202)
        search_id = started.data["search"]["id"]
        self.assertTrue(started.data["search"]["running"])

        cancelled = self.client.delete("/api/searches/" + search_id)
        self.assertEqual(cancelled.status, 200)

        final = wait_for_search(self.client, search_id)
        self.assertEqual(final["status"], "cancelled")
        self.assertFalse(final["running"])
        self.assertLess(final["scanned_dirs"], self.fixture["dirs"] + 1)
        self.assertFalse(final["truncated"], "中止不是截断，两者不能混为一谈")
        self.assertIsNone(final["error"], "中止不是失败")

    def test_cancelled_search_frees_the_connection_slot(self):
        """中止之后这条连接必须能立刻再搜一次。"""
        started = start_search(self.client, path=self.bulk, query="zzz-没有这个文件")
        search_id = started.data["search"]["id"]
        self.client.delete("/api/searches/" + search_id)
        wait_for_search(self.client, search_id)
        again = self.search("报告")
        self.assertEqual(again["result_count"], 3)

    def test_second_search_on_the_same_connection_is_refused(self):
        """一条连接同时只允许一个搜索，否则 SSH 通道会被占满。"""
        started = start_search(self.client, path=self.bulk, query="zzz-没有这个文件")
        search_id = started.data["search"]["id"]
        try:
            busy = start_search(self.client, path=self.root, query="报告")
            self.assertEqual(busy.status, 409)
            self.assertEqual(busy.code, "search_busy")
        finally:
            self.client.delete("/api/searches/" + search_id)
            wait_for_search(self.client, search_id)

    def test_listing_keeps_working_while_a_search_runs(self):
        """搜索只在单次 listdir 的粒度上持锁，浏览不应该被饿死。"""
        started = start_search(self.client, path=self.bulk, query="zzz-没有这个文件")
        search_id = started.data["search"]["id"]
        try:
            listing = self.client.get(files_url(self.root))
            self.assertTrue(listing.ok, "搜索进行中列目录失败：" + repr(listing))
            names = {entry["name"] for entry in listing.data["entries"]}
            self.assertIn("报告.txt", names)
        finally:
            self.client.delete("/api/searches/" + search_id)
            wait_for_search(self.client, search_id)

    # ------------------------------------------------------------------ 断连

    def test_disconnect_mid_search_ends_it_with_a_real_reason(self):
        """搜索途中断开连接：不能停在 running，也不能假装"搜完了"。"""
        started = start_search(self.client, path=self.bulk, query="zzz-没有这个文件")
        search_id = started.data["search"]["id"]
        try:
            self.assertTrue(self.client.post(api("/disconnect")).ok)
            # 断连与中止在服务端是两个并发信号，谁先落地都可能：关键是终态要诚实。
            final = wait_for_search(self.client, search_id)
            self.assertIn(final["status"], ("failed", "cancelled"))
            self.assertFalse(final["running"])
            if final["status"] == "failed":
                self.assertEqual(final["error"]["code"], "not_connected")
        finally:
            self.client.post(api("/connect"))
            self.ensure_connected()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
