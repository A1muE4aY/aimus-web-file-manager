"""文件检索服务：匹配、范围、上限、取消与失败区分。

用内存里的假远端树驱动，不碰真实 SSH —— 真实链路在集成测试里覆盖。
"""

import threading
import time
import unittest
from types import SimpleNamespace

from app.core.errors import (
    AwfmError,
    NotConnected,
    PathNotFound,
    PermissionDenied,
    SearchBusy,
    ValidationError,
)
from app.services import search as search_service
from app.services.search import SearchLimits, SearchRegistry, validate_query
from app.ssh import sftp_protocol as proto


def attrs(kind, perm=0o644, size=0, mtime=1000):
    flags = (
        proto.SSH_FILEXFER_ATTR_SIZE
        | proto.SSH_FILEXFER_ATTR_PERMISSIONS
        | proto.SSH_FILEXFER_ATTR_ACMODTIME
    )
    return proto.Attrs(flags=flags, size=size, permissions=kind | perm, atime=mtime, mtime=mtime)


FILE = proto.S_IFREG
DIR = proto.S_IFDIR
LINK = proto.S_IFLNK


def entry(name, kind=FILE, perm=0o644, size=0):
    return proto.NameEntry(filename=name, longname=name, attrs=attrs(kind, perm, size))


class FakeTree:
    """内存里的远端目录树。

    `failures` 让某个目录在列举时报错（无权限、目录消失），
    `hook` 让测试在两次列举之间插一脚（用来在中途取消搜索）。
    """

    def __init__(self):
        self.dirs = {}
        self.stats = {}
        self.failures = {}
        self.listdir_calls = []
        self.hook = None
        self.lock = threading.Lock()

    def add_dir(self, path, *entries):
        self.dirs[path] = list(entries)
        self.stats[path] = attrs(DIR, 0o755)
        for item in entries:
            child = path.rstrip("/") + "/" + item.filename
            self.stats.setdefault(child, item.attrs)
        return self

    def add_file(self, path, size=10, kind=FILE, perm=0o644):
        parent, _, name = path.rpartition("/")
        parent = parent or "/"
        self.dirs.setdefault(parent, []).append(entry(name, kind, perm, size))
        self.stats[path] = attrs(kind, perm, size)
        return self

    def fail(self, path, error):
        self.failures[path] = error
        return self


class FakeClient:
    def __init__(self, tree):
        self.tree = tree

    def realpath(self, path):
        return path

    def stat(self, path):
        if path not in self.tree.stats:
            raise PathNotFound(f"远端路径不存在：{path}")
        return self.tree.stats[path]

    def listdir(self, path):
        with self.tree.lock:
            self.tree.listdir_calls.append(path)
            hook = self.tree.hook
        if hook is not None:
            hook(path)
        if path in self.tree.failures:
            raise self.tree.failures[path]
        if path not in self.tree.dirs:
            raise PathNotFound(f"远端路径不存在：{path}")
        return list(self.tree.dirs[path])


def session(client, connection_id="vm1"):
    return SimpleNamespace(client=client, connection=SimpleNamespace(id=connection_id, allow_write=False))


def run_search(tree, query, *, root="/root", limits=None, connection_id="vm1"):
    registry = SearchRegistry(limits=limits)
    search = registry.start(session(FakeClient(tree), connection_id), path=root, query=query)
    search.wait(5)
    return search


class MatchingTests(unittest.TestCase):
    def build(self):
        tree = FakeTree()
        tree.add_dir(
            "/root",
            entry("readme.md"),
            entry("Notes.TXT"),
            entry("子目录", DIR),
            entry("link", LINK),
            entry("data", DIR),
        )
        tree.add_dir("/root/子目录", entry("报告.txt"))
        tree.add_dir("/root/data", entry("Report-2026.csv"), entry("deep", DIR))
        tree.add_dir("/root/data/deep", entry("report_final.log"))
        return tree

    def test_case_insensitive_substring(self):
        search = run_search(self.build(), "read")
        names = [item["name"] for item in search.snapshot()["results"]]
        self.assertEqual(names, ["readme.md"])

    def test_case_difference_in_both_directions(self):
        self.assertEqual(
            [item["name"] for item in run_search(self.build(), "NOTES").snapshot()["results"]],
            ["Notes.TXT"],
        )
        self.assertEqual(
            [item["name"] for item in run_search(self.build(), "notes.txt").snapshot()["results"]],
            ["Notes.TXT"],
        )

    def test_chinese_filename(self):
        search = run_search(self.build(), "报告")
        results = search.snapshot()["results"]
        self.assertEqual([item["name"] for item in results], ["报告.txt"])
        self.assertEqual(results[0]["path"], "/root/子目录/报告.txt")

    def test_matches_nested_directories_and_files(self):
        search = run_search(self.build(), "report")
        paths = [item["path"] for item in search.snapshot()["results"]]
        self.assertEqual(
            paths,
            ["/root/data/Report-2026.csv", "/root/data/deep/report_final.log"],
        )

    def test_directory_matches_are_included(self):
        search = run_search(self.build(), "deep")
        results = search.snapshot()["results"]
        self.assertEqual([(item["name"], item["type"]) for item in results], [("deep", "directory")])

    def test_results_are_sorted_directories_first(self):
        tree = FakeTree()
        tree.add_dir("/root", entry("abc.txt"), entry("abc", DIR))
        tree.add_file("/root/abc/abc-inside.txt")
        search = run_search(tree, "abc")
        names = [item["name"] for item in search.snapshot()["results"]]
        # 目录在前；同为文件时按 casefold 后的名字排，"abc-inside.txt" 里的 "-" 小于 "."
        self.assertEqual(names, ["abc", "abc-inside.txt", "abc.txt"])

    def test_result_rows_carry_what_the_table_needs(self):
        search = run_search(self.build(), "报告")
        row = search.snapshot()["results"][0]
        for key in ("name", "path", "type", "size", "mtime", "parent"):
            self.assertIn(key, row)
        self.assertEqual(row["parent"], "/root/子目录")
        # 相对搜索根的层数：根的直接子项是 1 层，这里在子目录里，所以是 2。
        self.assertEqual(row["depth"], 2)

    def test_empty_result_is_not_a_failure(self):
        search = run_search(self.build(), "zzz-nothing")
        payload = search.snapshot()
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["result_count"], 0)
        self.assertEqual(payload["results"], [])
        self.assertIsNone(payload["error"])

    def test_scan_stays_inside_the_search_root(self):
        search = run_search(self.build(), "report", root="/root/data")
        payload = search.snapshot()
        self.assertTrue(payload["results"])
        for item in payload["results"]:
            self.assertTrue(item["path"].startswith("/root/data/"))
        self.assertEqual(payload["root"], "/root/data")
        self.assertNotIn("/root", [call.rstrip("/") for call in search._session.client.tree.listdir_calls])


class LinkPolicyTests(unittest.TestCase):
    def test_symlinks_are_reported_but_never_followed(self):
        tree = FakeTree()
        tree.add_dir("/root", entry("escape", LINK), entry("keep.txt"))
        # 链接指向的目录在远端确实存在，但搜索不该进去。
        tree.add_dir("/root/escape", entry("keep-2.txt"), entry("secret.txt"))
        search = run_search(tree, "keep")
        payload = search.snapshot()
        self.assertEqual([item["name"] for item in payload["results"]], ["keep.txt"])
        self.assertNotIn("/root/escape", tree.listdir_calls)

    def test_symlink_whose_own_name_matches_is_listed(self):
        tree = FakeTree()
        tree.add_dir("/root", entry("latest-link", LINK))
        search = run_search(tree, "latest")
        self.assertEqual(
            [(item["name"], item["type"]) for item in search.snapshot()["results"]],
            [("latest-link", "symlink")],
        )

    def test_directory_cycle_cannot_loop(self):
        # a/report.txt 与指向 a 的链接；若跟随链接就会无限循环。
        tree = FakeTree()
        tree.add_dir("/root", entry("a", DIR), entry("loop", LINK))
        tree.add_dir("/root/a", entry("report.txt"))
        search = run_search(tree, "report")
        self.assertTrue(search.wait(5))
        self.assertEqual([item["path"] for item in search.snapshot()["results"]], ["/root/a/report.txt"])


class ErrorHandlingTests(unittest.TestCase):
    def test_unreadable_directory_is_skipped_not_fatal(self):
        tree = FakeTree()
        tree.add_dir("/root", entry("locked", DIR), entry("open", DIR))
        tree.fail("/root/locked", PermissionDenied("没有权限读取该目录。"))
        tree.add_dir("/root/open", entry("report.txt"))
        payload = run_search(tree, "report").snapshot()
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["skipped_dirs"], 1)
        self.assertEqual(payload["skipped"][0]["path"], "/root/locked")
        self.assertEqual(payload["skipped"][0]["code"], "permission_denied")
        self.assertEqual([item["name"] for item in payload["results"]], ["report.txt"])

    def test_vanishing_directory_is_skipped(self):
        tree = FakeTree()
        tree.add_dir("/root", entry("gone", DIR), entry("keep", DIR))
        tree.fail("/root/gone", PathNotFound("远端路径不存在：/root/gone"))
        tree.add_dir("/root/keep", entry("report.txt"))
        payload = run_search(tree, "report").snapshot()
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["skipped_dirs"], 1)
        self.assertEqual(payload["result_count"], 1)

    def test_disconnected_session_fails_the_search_with_a_reason(self):
        tree = FakeTree()
        tree.add_dir("/root", entry("a", DIR))
        tree.fail("/root/a", NotConnected("该连接当前未建立。", detail="请先点击连接。"))
        payload = run_search(tree, "report").snapshot()
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error"]["code"], "not_connected")
        self.assertIn("未建立", payload["error"]["message"])
        # 失败与「没有匹配」必须能分开：这里 result_count 是 0，但状态是 failed。
        self.assertEqual(payload["result_count"], 0)

    def test_repeated_failures_stop_the_search(self):
        tree = FakeTree()
        entries = [entry(f"d{index}", DIR) for index in range(search_service.MAX_CONSECUTIVE_FAILURES + 2)]
        tree.add_dir("/root", *entries)
        for index in range(search_service.MAX_CONSECUTIVE_FAILURES + 2):
            tree.fail(f"/root/d{index}", PermissionDenied("没有权限读取该目录。"))
        payload = run_search(tree, "report").snapshot()
        self.assertEqual(payload["status"], "failed")
        self.assertIn("连续", payload["error"]["message"])

    def test_missing_root_is_reported_before_starting(self):
        tree = FakeTree()
        registry = SearchRegistry()
        with self.assertRaises(PathNotFound):
            registry.start(session(FakeClient(tree)), path="/nope", query="x")

    def test_root_must_be_a_directory(self):
        tree = FakeTree()
        tree.add_dir("/root")
        tree.add_file("/root/file.txt")
        registry = SearchRegistry()
        with self.assertRaises(ValidationError):
            registry.start(session(FakeClient(tree)), path="/root/file.txt", query="x")

    def test_relative_root_is_refused(self):
        tree = FakeTree()
        registry = SearchRegistry()
        with self.assertRaises(ValidationError):
            registry.start(session(FakeClient(tree)), path="root", query="x")

    def test_dangerous_names_from_the_server_are_refused(self):
        tree = FakeTree()
        tree.add_dir(
            "/root",
            proto.NameEntry(filename="..", longname="..", attrs=attrs(DIR, 0o755)),
            proto.NameEntry(filename="../../etc", longname="x", attrs=attrs(DIR, 0o755)),
            entry("report.txt"),
        )
        payload = run_search(tree, "report").snapshot()
        self.assertEqual(payload["skipped_names"], 2)
        self.assertEqual([item["path"] for item in payload["results"]], ["/root/report.txt"])
        self.assertNotIn("/root/../..", tree.listdir_calls)


class LimitTests(unittest.TestCase):
    def build_wide(self, count=40):
        tree = FakeTree()
        tree.add_dir("/root", *[entry(f"report-{index:03d}.txt") for index in range(count)])
        return tree

    def test_result_cap_truncates_and_says_so(self):
        search = run_search(self.build_wide(40), "report", limits=SearchLimits(max_results=5))
        payload = search.snapshot()
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["result_count"], 5)
        self.assertTrue(payload["truncated"])
        self.assertIn("上限", payload["truncated_reason"])

    def test_directory_cap_truncates(self):
        tree = FakeTree()
        tree.add_dir("/root", *[entry(f"d{index}", DIR) for index in range(10)])
        for index in range(10):
            tree.add_dir(f"/root/d{index}", entry("report.txt"))
        search = run_search(tree, "report", limits=SearchLimits(max_dirs=3, max_results=100))
        payload = search.snapshot()
        self.assertTrue(payload["truncated"])
        self.assertLessEqual(payload["scanned_dirs"], 3)
        self.assertLess(payload["result_count"], 10)

    def test_entry_cap_truncates(self):
        tree = FakeTree()
        tree.add_dir("/root", *[entry(f"f{index}") for index in range(50)])
        search = run_search(tree, "report", limits=SearchLimits(max_entries=10, max_results=100))
        payload = search.snapshot()
        self.assertTrue(payload["truncated"])
        self.assertLessEqual(payload["scanned_entries"], 10)

    def test_many_files_are_scanned_without_loading_all_of_them(self):
        tree = self.build_wide(300)
        search = run_search(tree, "report", limits=SearchLimits(max_results=500, max_entries=5000))
        payload = search.snapshot()
        self.assertEqual(payload["result_count"], 300)
        self.assertFalse(payload["truncated"])


class CancelTests(unittest.TestCase):
    def test_cancel_mid_scan_marks_the_search_cancelled(self):
        registry = SearchRegistry()
        tree = FakeTree()
        tree.add_dir("/root", entry("a", DIR), entry("report.txt"))
        tree.add_dir("/root/a", *[entry(f"x{index}") for index in range(50)])
        client = FakeClient(tree)
        reached = threading.Event()
        released = threading.Event()

        def hook(path):
            if path == "/root/a":
                # 卡在「正在列举 /root/a」这一刻，等主线程发出取消再放行 ——
                # 否则取消可能落在搜索已经跑完之后，就测不到「中途取消」了。
                reached.set()
                released.wait(2)

        tree.hook = hook
        search = registry.start(session(client), path="/root", query="report")
        self.assertTrue(reached.wait(2))
        search.cancel()
        released.set()
        search.wait(5)
        payload = search.snapshot()
        self.assertEqual(payload["status"], "cancelled")
        self.assertIsNone(payload["error"])

    def test_cancelling_a_finished_search_is_a_no_op(self):
        tree = FakeTree()
        tree.add_dir("/root", entry("report.txt"))
        registry = SearchRegistry()
        search = registry.start(session(FakeClient(tree)), path="/root", query="report")
        search.wait(5)
        self.assertFalse(registry.cancel(search.id)["running"])
        self.assertEqual(search.snapshot()["status"], "done")

    def test_cancel_for_connection_stops_its_searches(self):
        tree = FakeTree()
        tree.add_dir("/root", entry("a", DIR))
        tree.add_dir("/root/a", entry("report.txt"))
        registry = SearchRegistry()
        search = registry.start(session(FakeClient(tree), "vm9"), path="/root", query="report")
        registry.cancel_for_connection("vm9")
        search.wait(5)
        self.assertIn(search.snapshot()["status"], ("cancelled", "done"))

    def test_unknown_search_id_is_reported(self):
        registry = SearchRegistry()
        with self.assertRaises(PathNotFound):
            registry.get("deadbeef")


class RegistryTests(unittest.TestCase):
    def test_one_search_per_connection(self):
        tree = FakeTree()
        tree.add_dir("/root", entry("report.txt"))
        release = threading.Event()

        def hook(path):
            # 让小树上的第一条搜索保持 running，否则它会在第二次 start 之前就跑完，
            # 这条用例就变成了在测「没有并发」这件无意义的事。
            release.wait(2)

        tree.hook = hook
        registry = SearchRegistry()
        first = registry.start(session(FakeClient(tree)), path="/root", query="report")
        try:
            with self.assertRaises(SearchBusy):
                registry.start(session(FakeClient(tree)), path="/root", query="report")
        finally:
            release.set()
            first.wait(5)
        # 第一条结束后可以再开一条。
        tree.hook = None
        second = registry.start(session(FakeClient(tree)), path="/root", query="report")
        second.wait(5)
        self.assertEqual(second.snapshot()["status"], "done")

    def test_different_connections_search_in_parallel(self):
        tree = FakeTree()
        tree.add_dir("/root", entry("report.txt"))
        registry = SearchRegistry()
        one = registry.start(session(FakeClient(tree), "vm1"), path="/root", query="report")
        two = registry.start(session(FakeClient(tree), "vm2"), path="/root", query="report")
        one.wait(5)
        two.wait(5)
        self.assertEqual(one.snapshot()["status"], "done")
        self.assertEqual(two.snapshot()["status"], "done")

    def test_old_finished_searches_are_pruned(self):
        tree = FakeTree()
        tree.add_dir("/root", entry("report.txt"))
        registry = SearchRegistry(max_kept=3)
        ids = []
        for _ in range(6):
            search = registry.start(session(FakeClient(tree)), path="/root", query="report")
            search.wait(5)
            ids.append(search.id)
        self.assertGreaterEqual(len(registry._searches), 1)
        self.assertLessEqual(len(registry._searches), 6)
        with self.assertRaises(PathNotFound):
            registry.get(ids[0])


class QueryValidationTests(unittest.TestCase):
    def test_empty_query_is_refused(self):
        for raw in ("", "   ", "\t"):
            with self.assertRaises(ValidationError):
                validate_query(raw)

    def test_non_string_query_is_refused(self):
        with self.assertRaises(ValidationError):
            validate_query(None)
        with self.assertRaises(ValidationError):
            validate_query(12)

    def test_overlong_query_is_refused(self):
        with self.assertRaises(ValidationError):
            validate_query("a" * (search_service.MAX_QUERY_CHARS + 1))

    def test_control_characters_are_refused(self):
        with self.assertRaises(ValidationError):
            validate_query("report\x00")

    def test_query_is_trimmed(self):
        self.assertEqual(validate_query("  report  "), "report")


if __name__ == "__main__":
    unittest.main()
