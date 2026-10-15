"""文件检索的攻击面测试（规划文档 §10；任务书 2.md 阶段三）。

搜索是第二个「由远端目录内容驱动」的入口（第一个是列目录），但它比列目录多两件
危险的事：它**递归**，而且**在后台线程里跑**。所以这里钉三条边界：

1. **畸形参数必须在建任务之前被拒** —— 不许变成一个后台任务，更不许先碰远端。
   被拒之后连接上的活动槽必须还是空的：同一条连接只允许一个在跑的搜索
   （`SearchRegistry.start`），一个坏请求要是占住了槽，这条连接就废了。
   参数形状检查排在「找会话」之前（app/api/handlers.py:start_search），
   所以「缺 path / path 不是字符串」这一类在没连接的机器上也能复现。
2. **搜索不派生任何远端进程**（验收项 T-013）：它只在已建立的 SFTP 通道上列目录。
   用例数测试床 ssh 进程数前后不变，而不是相信实现说明；再加一条「远端文件树
   在搜索前后逐字节不变」，证明搜索是只读的。
3. **结果不许跑出搜索根**：符号链接（含指向根外的链接与目录环）只作为结果行报出，
   绝不跟着走 —— 这条用真实文件树在 tests/integration/test_search_api.py 里覆盖
   （`test_symlink_pointing_outside_the_root_is_not_walked_into`）。

「一条连接同时只跑一个搜索」的 409 需要真在跑的搜索，在集成测试里覆盖，这里不重复。
"""

from __future__ import annotations

import contextlib
import os
import sys
import unittest

from tests.integration.support import (
    count_testbed_ssh_processes,
    require_testbed,
    running_server,
    search_and_wait,
    search_fixture,
    start_search,
    testbed_connection,
    testbed_environment,
    wait_for_search,
)
from tests.security.support import local_server

CONNECTION = "wsl-testbed"
DEAD_CONNECTION_ID = "dead-host"
DEAD_SEARCH_PATH = "/api/connections/" + DEAD_CONNECTION_ID + "/search"
UNKNOWN_SEARCH_ID = "0123456789abcdef"


class SearchRouteBoundaryTests(unittest.TestCase):
    """不需要测试床：路由层与登记处的边界。

    这台机器上一条连接都没有连上过（连接表里只有一个永远连不上的地址），
    因此这里能跑到的东西，全部是不依赖远端状态的判断。
    """

    @classmethod
    def setUpClass(cls):
        cls._stack = contextlib.ExitStack()
        cls.client = cls._stack.enter_context(local_server()).client

    @classmethod
    def tearDownClass(cls):
        cls._stack.close()

    def test_search_endpoints_require_a_token(self):
        cases = [
            ("发起搜索", "post", DEAD_SEARCH_PATH, {"path": "/tmp", "query": "报告"}),
            ("查询进度", "get", "/api/searches/" + UNKNOWN_SEARCH_ID, None),
            ("中止搜索", "delete", "/api/searches/" + UNKNOWN_SEARCH_ID, None),
        ]
        for label, method, path, body in cases:
            with self.subTest(case=label):
                call = getattr(self.client, method)
                response = call(path, body, token=False) if body is not None else call(path, token=False)
                self.assertEqual(
                    (response.status, response.code), (401, "unauthorized"), repr(response)
                )

    def test_unknown_search_id_is_not_found(self):
        for method in (self.client.get, self.client.delete):
            with self.subTest(method=method.__name__):
                response = method("/api/searches/" + UNKNOWN_SEARCH_ID)
                self.assertEqual(
                    (response.status, response.code), (404, "path_not_found"), repr(response)
                )

    def test_search_id_must_be_lowercase_hex(self):
        """id 由应用生成，一律小写十六进制；不匹配的请求连处理器都到不了。"""
        for bad in ("not-a-hex-id", "0123456789ABCDEF", "..%2F..%2Fetc%2Fpasswd", "0x1f"):
            with self.subTest(search_id=bad):
                response = self.client.get("/api/searches/" + bad)
                self.assertEqual(response.status, 404, repr(response))

    def test_malformed_body_is_rejected_without_a_live_session(self):
        """形状检查排在找会话之前：没连接的机器上也该先说参数有问题。

        如果哪一天有人把它们调回去，「连不上的主机」会先报 not_connected（409），
        这几条就会红 —— 那正是这个用例要守住的顺序。
        """
        cases = [
            ("缺 path", {"query": "报告"}),
            ("缺 query", {"path": "/tmp"}),
            ("path 不是字符串", {"path": 123, "query": "报告"}),
            ("query 不是字符串", {"path": "/tmp", "query": ["报告"]}),
            ("两者都是 null", {"path": None, "query": None}),
            ("path 是空串", {"path": "", "query": "报告"}),
            ("query 是空串", {"path": "/tmp", "query": ""}),
        ]
        for label, payload in cases:
            with self.subTest(case=label):
                response = self.client.post(DEAD_SEARCH_PATH, body=payload)
                self.assertEqual(
                    (response.status, response.code), (400, "invalid_request"), repr(response)
                )

    def test_empty_body_is_rejected(self):
        # 空请求体按 {} 处理（app/api/request.py:json），于是缺 path/query —— 而不是 500。
        response = self.client.post(DEAD_SEARCH_PATH)
        self.assertEqual((response.status, response.code), (400, "invalid_request"), repr(response))

    def test_parameters_are_checked_before_the_connection_exists(self):
        # 连接 id 根本不存在，但请求体是畸形的：报参数错误，不报 connection_not_found。
        response = self.client.post("/api/connections/no-such-host/search", body={"query": "报告"})
        self.assertEqual((response.status, response.code), (400, "invalid_request"), repr(response))


@require_testbed
class SearchParameterValidationTests(unittest.TestCase):
    """畸形参数必须在建任务之前被拒，而且不能占住连接上的活动槽。"""

    @classmethod
    def setUpClass(cls):
        cls._stack = contextlib.ExitStack()
        config, _keys = cls._stack.enter_context(
            testbed_environment(connections=[testbed_connection(allow_write=True)])
        )
        cls.client = cls._stack.enter_context(running_server(config))
        cls.fixture = cls._stack.enter_context(search_fixture(dirs=2, files=2))
        cls.root = cls.fixture["root"]
        response = cls.client.post("/api/connections/" + CONNECTION + "/connect")
        if not response.ok:
            cls._stack.close()
            raise AssertionError("测试床连接失败：" + repr(response))

    @classmethod
    def tearDownClass(cls):
        cls._stack.close()

    # -- 辅助 ------------------------------------------------------------

    def start(self, *, path=None, query="报告"):
        return start_search(self.client, path=self.root if path is None else path, query=query)

    def assert_rejected(self, response, status=400, code="invalid_request"):
        self.assertEqual((response.status, response.code), (status, code), repr(response))

    def listing(self):
        """根目录的列表快照，用于证明搜索没改动远端。"""
        response = self.client.get(
            "/api/connections/" + CONNECTION + "/files?path=" + self.root
        )
        self.assertTrue(response.ok, repr(response))
        return [
            (entry["name"], entry["type"], entry.get("size"), entry.get("mtime"))
            for entry in response.data["entries"]
        ]

    # -- path -------------------------------------------------------------

    def test_relative_path_is_rejected(self):
        self.assert_rejected(self.start(path="home/aimu"))

    def test_empty_path_is_rejected(self):
        self.assert_rejected(self.start(path=""))

    def test_null_byte_in_path_is_rejected(self):
        self.assert_rejected(self.start(path="/tmp/\x00etc"))

    def test_overlong_path_is_rejected(self):
        # 上限是 4096 **字节**（app/utils/paths.py:MAX_PATH_BYTES）。
        self.assert_rejected(self.start(path="/" + "a" * 4096))

    def test_path_to_a_file_is_rejected(self):
        self.assert_rejected(self.start(path=self.root + "/报告.txt"))

    def test_missing_path_is_not_found(self):
        self.assert_rejected(
            self.start(path="/tmp/awfm-no-such-dir-%d" % os.getpid()),
            status=404,
            code="path_not_found",
        )

    def test_dotdot_is_resolved_by_the_server_not_rejected(self):
        """客户端不折叠 `..`（见 app/utils/paths.py 的模块说明）：交给服务端 REALPATH。

        这里顺带钉住「`..` 既不是错误、也不是绕过」：搜索根是 REALPATH 之后的结果。
        """
        snapshot = search_and_wait(
            self.client, path=self.root + "/../" + self.root.rsplit("/", 1)[-1], query="报告"
        )
        self.assertEqual(snapshot["root"], self.root)
        self.assertGreaterEqual(snapshot["result_count"], 1)

    # -- query ------------------------------------------------------------

    def test_malformed_query_is_rejected(self):
        cases = [
            ("不是字符串", 123),
            ("是列表", ["报告"]),
            ("空串", ""),
            ("全是空白", "   "),
            ("超过 128 个字符", "x" * 129),
            ("含 NUL", "报告\x00"),
            ("含控制字符", "报告\x01"),
            ("含换行", "报告\n草稿"),
        ]
        for label, query in cases:
            with self.subTest(case=label):
                self.assert_rejected(self.start(query=query))

    def test_a_tab_is_not_a_forbidden_control_character(self):
        """`validate_query` 只拦 \t 以外的控制字符 —— 文件名里带制表符是合法的。

        这条是刻意的：把制表符也拦掉，只会让这类文件永远搜不到。
        """
        response = self.start(query="报告\t.txt")
        self.assertEqual(response.status, 202, repr(response))
        snapshot = wait_for_search(self.client, response.data["search"]["id"])
        self.assertEqual(snapshot["status"], "done")

    # -- 被拒之后不留副作用 -------------------------------------------------

    def test_rejections_do_not_occupy_the_connection_slot(self):
        """一串被拒的请求之后，连接上必须没有留下任何活动任务。

        同一条连接只允许一个在跑的搜索：要是畸形请求建了任务又没结束，
        紧接着的合法搜索就会拿到 409 search_busy。
        """
        bad = [
            {"path": "home/aimu", "query": "报告"},
            {"path": "", "query": "报告"},
            {"path": "/tmp/\x00etc", "query": "报告"},
            {"path": self.root + "/报告.txt", "query": "报告"},
            {"path": self.root, "query": ""},
            {"path": self.root, "query": "x" * 129},
            {"path": self.root, "query": "报告\x01"},
        ]
        for payload in bad:
            with self.subTest(payload=payload):
                self.assert_rejected(
                    start_search(self.client, path=payload["path"], query=payload["query"])
                )
        snapshot = search_and_wait(self.client, path=self.root, query="报告")
        self.assertEqual(snapshot["status"], "done")
        self.assertGreaterEqual(snapshot["result_count"], 1)


@require_testbed
class SearchCommandDisciplineTests(unittest.TestCase):
    """T-013：搜索只在已建立的通道上列目录，远端不跑我们派的命令、也不落下文件。"""

    @classmethod
    def setUpClass(cls):
        cls._stack = contextlib.ExitStack()
        config, _keys = cls._stack.enter_context(
            testbed_environment(connections=[testbed_connection(allow_write=True)])
        )
        cls.client = cls._stack.enter_context(running_server(config))
        cls.fixture = cls._stack.enter_context(search_fixture(dirs=3, files=3))
        cls.root = cls.fixture["root"]
        response = cls.client.post("/api/connections/" + CONNECTION + "/connect")
        if not response.ok:
            cls._stack.close()
            raise AssertionError("测试床连接失败：" + repr(response))

    @classmethod
    def tearDownClass(cls):
        cls._stack.close()

    def listing(self):
        response = self.client.get("/api/connections/" + CONNECTION + "/files?path=" + self.root)
        self.assertTrue(response.ok, repr(response))
        return [
            (entry["name"], entry["type"], entry.get("size"), entry.get("mtime"))
            for entry in response.data["entries"]
        ]

    def test_search_does_not_spawn_ssh_processes(self):
        if sys.platform != "win32":
            self.skipTest("只有 Windows 宿主能数 ssh.exe 进程")
        before = count_testbed_ssh_processes()
        self.assertGreaterEqual(
            before, 1, "已连接的会话本身就该有一个 ssh 子进程，数到 0 说明测量方法失效了"
        )
        snapshot = search_and_wait(self.client, path=self.root, query="file-")
        self.assertGreater(snapshot["result_count"], 0, "先确认这次搜索真的干活了")
        after = count_testbed_ssh_processes()
        self.assertEqual(after, before, "搜索期间 ssh 进程数变了：远端可能被执行了命令")

    def test_search_leaves_the_remote_tree_untouched(self):
        before = self.listing()
        snapshot = search_and_wait(self.client, path=self.root, query="报告")
        self.assertEqual(snapshot["status"], "done")
        self.assertEqual(self.listing(), before, "搜索改动了远端目录")
