"""在线编辑接口的集成测试（真实 WSL 测试床 + 真实 HTTP 服务）。

覆盖任务书阶段四对文本编辑的要求：正常保存、中文内容、换行符与末尾换行、
空文件、只读文件、文件已被删除、保存冲突、二进制与大文件拒绝、写权限关闭。

这里全部走 HTTP 接口 —— 界面上点得到的东西，接口层必须能独立复现。
每个用例都先用上传接口放一个内容已知的文件，用例之间不共享可变状态。
"""

import contextlib
import hashlib
import time
import unittest
from urllib.parse import quote

from tests.integration.support import (
    download_bytes,
    edit_fixture,
    require_testbed,
    running_server,
    testbed_command,
    testbed_connection,
    testbed_environment,
    upload_bytes,
)

CONNECTION = "wsl-testbed"
READONLY_CONNECTION = "wsl-readonly"

REAL = "real.txt"
LINK = "link.txt"
SUB = "sub"
EIGHT_K = "eight-k.txt"

DEFAULT_EDIT_LIMIT = 2 * 1024 * 1024


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@require_testbed
class EditApiTests(unittest.TestCase):
    """在线编辑端点在真实测试床上的行为。"""

    @classmethod
    def setUpClass(cls):
        cls._stack = contextlib.ExitStack()
        config, _keys = cls._stack.enter_context(
            testbed_environment(
                connections=[
                    testbed_connection(id=CONNECTION, allow_write=True),
                    testbed_connection(
                        id=READONLY_CONNECTION, name="只读测试床", allow_write=False
                    ),
                ]
            )
        )
        cls.client = cls._stack.enter_context(running_server(config))
        cls.root = cls._stack.enter_context(edit_fixture())
        for connection in (CONNECTION, READONLY_CONNECTION):
            response = cls.client.post("/api/connections/%s/connect" % connection, {})
            assert response.status == 200, response

    @classmethod
    def tearDownClass(cls):
        cls._stack.close()

    # ------------------------------------------------------------- 助手

    def path(self, name):
        if name.startswith("/"):
            return name
        return "%s/%s" % (self.root, name)

    def text_url(self, name, *, connection=CONNECTION, path=None):
        target = path if path is not None else self.path(name)
        return "/api/connections/%s/text?path=%s" % (connection, quote(target, safe=""))

    def read(self, name, *, connection=CONNECTION, path=None):
        return self.client.get(self.text_url(name, connection=connection, path=path))

    def file_of(self, name, *, connection=CONNECTION):
        response = self.read(name, connection=connection)
        self.assertEqual(response.status, 200, response)
        return response.data["file"]

    def save(self, name, text, *, connection=CONNECTION, path=None, **body):
        target = path if path is not None else self.path(name)
        payload = {"path": target, "text": text}
        payload.update(body)
        return self.client.put("/api/connections/%s/text" % connection, payload)

    def saved_file(self, response):
        self.assertEqual(response.status, 200, response)
        return response.data["file"]

    def upload(self, name, data, *, mode=None):
        """用上传接口放一个文件（不读它 —— 二进制文件本来就该读失败）。"""
        if isinstance(data, str):
            data = data.encode("utf-8")
        response = upload_bytes(self.client, self.root, name, data)
        self.assertIn(response.status, (200, 201), response)
        if mode is not None:
            testbed_command('chmod %04o "%s"' % (mode, self.path(name)))
        return response

    def fresh(self, name, data, *, mode=None):
        """放一个内容已知的文本文件，返回接口读出来的基线。"""
        self.upload(name, data, mode=mode)
        return self.file_of(name)

    def remote_bytes(self, name):
        return download_bytes(self.client, self.path(name))

    def assert_refused(self, response, status, code):
        self.assertEqual(response.status, status, response)
        self.assertEqual(response.code, code, response)

    # ------------------------------------------------------------- 读取

    def test_read_returns_text_and_metadata(self):
        info = self.fresh("read-meta.txt", "hello\nworld\n")
        self.assertEqual(info["name"], "read-meta.txt")
        self.assertEqual(info["path"], self.path("read-meta.txt"))
        self.assertEqual(info["text"], "hello\nworld\n")
        self.assertEqual(info["encoding"], "utf-8")
        self.assertEqual(info["newline"], "lf")
        self.assertEqual(info["size"], 12)
        self.assertEqual(info["sha256"], sha256(b"hello\nworld\n"))
        self.assertFalse(info["bom"])
        self.assertTrue(info["final_newline"])
        self.assertFalse(info["mixed_newlines"])
        self.assertIsInstance(info["mtime"], int)

    def test_read_limits_travel_with_the_file(self):
        response = self.read(REAL)
        limits = response.data["limits"]
        self.assertEqual(limits["max_edit_bytes"], DEFAULT_EDIT_LIMIT)
        self.assertEqual(limits["encodings"], ["utf-8"])
        self.assertEqual(limits["newlines"], ["lf", "crlf", "cr"])
        self.assertEqual(response.data["file"]["limit"], DEFAULT_EDIT_LIMIT)

    def test_crlf_is_reported_and_normalised_in_the_text(self):
        info = self.fresh("read-crlf.txt", b"a\r\nb\r\n")
        self.assertEqual(info["newline"], "crlf")
        self.assertEqual(info["text"], "a\nb\n")
        self.assertEqual(info["size"], 6)

    def test_mixed_newlines_are_reported(self):
        info = self.fresh("read-mixed.txt", b"a\r\nb\nc")
        # 两种换行数量相同：实现偏向 LF（见 app/services/editor.py:_detect_newline）。
        self.assertEqual(info["newline"], "lf")
        self.assertTrue(info["mixed_newlines"])
        self.assertEqual(info["text"], "a\nb\nc")
        self.assertFalse(info["final_newline"])

    def test_empty_file_reads_as_empty_text(self):
        # 上传接口不接受 0 字节的请求体，空文件由夹具的 shell 造出来。
        info = self.file_of("empty.txt")
        self.assertEqual(info["text"], "")
        self.assertEqual(info["size"], 0)
        self.assertEqual(info["sha256"], sha256(b""))
        self.assertEqual(info["newline"], "none")

    def test_missing_final_newline_is_reported(self):
        info = self.fresh("read-nonl.txt", b"no final newline")
        self.assertFalse(info["final_newline"])
        self.assertEqual(info["text"], "no final newline")

    def test_bom_is_reported_and_stripped_from_the_text(self):
        info = self.fresh("read-bom.txt", b"\xef\xbb\xbfwith bom\n")
        self.assertTrue(info["bom"])
        self.assertEqual(info["text"], "with bom\n")

    def test_chinese_text_round_trips(self):
        info = self.fresh("read-chinese.txt", "你好，世界\n")
        self.assertEqual(info["text"], "你好，世界\n")
        updated = self.saved_file(
            self.save("read-chinese.txt", "改过的中文内容\n", base_sha256=info["sha256"])
        )
        self.assertEqual(updated["size"], len("改过的中文内容\n".encode("utf-8")))
        self.assertEqual(self.remote_bytes("read-chinese.txt"), "改过的中文内容\n".encode("utf-8"))
        self.assertEqual(self.file_of("read-chinese.txt")["text"], "改过的中文内容\n")

    def test_symlink_edits_the_target_file(self):
        info = self.file_of(LINK)
        self.assertEqual(info["path"], self.path(REAL))
        self.saved_file(self.save(LINK, "link target\n", base_sha256=info["sha256"]))
        # 链接仍然是链接，没有被替换成普通文件。
        listing = testbed_command('test -L "%s" && echo LINK' % self.path(LINK))
        self.assertIn("LINK", listing)

    # ------------------------------------------------------------- 拒绝读取

    def test_binary_file_is_refused(self):
        name = "read-binary.bin"
        self.upload(name, bytes(range(256)) * 16)
        response = self.read(name)
        self.assert_refused(response, 400, "invalid_request")
        self.assertIn("文本", response.error["message"])
        self.assertEqual(response.error["path"], self.path(name))

    def test_directory_cannot_be_edited(self):
        response = self.read(SUB)
        self.assert_refused(response, 400, "invalid_request")

    def test_missing_file_is_not_found(self):
        response = self.read("read-nope.txt")
        self.assert_refused(response, 404, "path_not_found")

    def test_relative_path_is_refused(self):
        response = self.read("whatever.txt", path="relative.txt")
        self.assert_refused(response, 400, "invalid_request")

    def test_readonly_file_reports_permission_denied(self):
        name = "read-only-mode.txt"
        info = self.fresh(name, "read only\n", mode=0o444)
        response = self.save(name, "x\n", base_sha256=info["sha256"])
        self.assert_refused(response, 403, "permission_denied")
        self.assertEqual(response.error["mode"], "0444")
        self.assertEqual(self.file_of(name)["text"], "read only\n")

    # ------------------------------------------------------------- 保存

    def test_save_updates_size_and_sha(self):
        name = "save-basic.txt"
        before = self.fresh(name, "hello\nworld\n")
        info = self.saved_file(
            self.save(name, "changed\n", base_sha256=before["sha256"], base_mtime=before["mtime"])
        )
        self.assertEqual(info["size"], 8)
        self.assertEqual(info["sha256"], sha256(b"changed\n"))
        self.assertEqual(info["bytes_written"], 8)
        self.assertTrue(info["saved"])
        self.assertEqual(self.remote_bytes(name), b"changed\n")
        again = self.file_of(name)
        self.assertEqual(again["text"], "changed\n")
        self.assertEqual(again["sha256"], info["sha256"])
        self.assertEqual(again["mtime"], info["mtime"])

    def test_crlf_style_is_kept_by_default(self):
        name = "save-crlf.txt"
        before = self.fresh(name, b"a\r\nb\r\n")
        info = self.saved_file(self.save(name, "x\ny\n", base_sha256=before["sha256"]))
        self.assertEqual(info["newline"], "crlf")
        self.assertEqual(self.remote_bytes(name), b"x\r\ny\r\n")
        self.assertEqual(self.file_of(name)["text"], "x\ny\n")

    def test_explicit_lf_style_can_be_forced(self):
        name = "save-lf.txt"
        before = self.fresh(name, b"a\r\nb\r\n")
        info = self.saved_file(self.save(name, "x\ny\n", base_sha256=before["sha256"], newline="lf"))
        self.assertEqual(info["newline"], "lf")
        self.assertEqual(self.remote_bytes(name), b"x\ny\n")

    def test_missing_final_newline_is_preserved_on_save(self):
        name = "save-nonl.txt"
        before = self.fresh(name, b"no final newline")
        self.saved_file(self.save(name, "abc", base_sha256=before["sha256"]))
        self.assertEqual(self.remote_bytes(name), b"abc")
        self.assertFalse(self.file_of(name)["final_newline"])

    def test_bom_is_only_written_back_when_asked(self):
        name = "save-bom.txt"
        before = self.fresh(name, b"\xef\xbb\xbfwith bom\n")
        kept = self.saved_file(
            self.save(name, "with bom\n", base_sha256=before["sha256"], keep_bom=True)
        )
        self.assertTrue(kept["bom"])
        self.assertTrue(self.remote_bytes(name).startswith(b"\xef\xbb\xbf"))

        current = self.file_of(name)
        dropped = self.saved_file(
            self.save(name, "with bom\n", base_sha256=current["sha256"], keep_bom=False)
        )
        self.assertFalse(dropped["bom"])
        self.assertEqual(self.remote_bytes(name), b"with bom\n")

    def test_save_leaves_no_temporary_files(self):
        name = "save-clean.txt"
        before = self.fresh(name, "clean\n")
        self.saved_file(self.save(name, "no leftovers\n", base_sha256=before["sha256"]))
        listing = testbed_command('ls -a "%s"' % self.root)
        self.assertNotIn("awfm-part", listing)
        self.assertNotIn("awfm-bak", listing)

    # ------------------------------------------------------------- 冲突与失败

    def test_conflict_is_refused_and_the_other_change_survives(self):
        name = "conflict-content.txt"
        baseline = self.fresh(name, "original\n")
        # 别人（另一个客户端）先改了一次。
        first = self.saved_file(self.save(name, "first writer\n", base_sha256=baseline["sha256"]))
        self.assertEqual(first["sha256"], sha256(b"first writer\n"))
        # 我拿着过期的基线保存 —— 必须被拒，而且不能覆盖别人写的内容。
        response = self.save(name, "second writer\n", base_sha256=baseline["sha256"])
        self.assert_refused(response, 409, "edit_conflict")
        self.assertEqual(response.error["reason"], "content")
        self.assertEqual(self.remote_bytes(name), b"first writer\n")

    def test_conflict_by_mtime_is_refused(self):
        name = "conflict-mtime.txt"
        baseline = self.fresh(name, "before\n")
        time.sleep(1.1)
        testbed_command('touch "%s"' % self.path(name))
        response = self.save(name, "too late\n", base_mtime=baseline["mtime"])
        self.assert_refused(response, 409, "edit_conflict")
        self.assertEqual(response.error["reason"], "mtime")
        self.assertEqual(self.remote_bytes(name), b"before\n")

    def test_save_without_baseline_is_refused(self):
        name = "save-nobase.txt"
        self.fresh(name, "base\n")
        response = self.save(name, "no baseline\n")
        self.assert_refused(response, 400, "invalid_request")
        self.assertIn("base_", response.error["message"])
        self.assertEqual(self.remote_bytes(name), b"base\n")

    def test_bad_parameter_shapes_are_refused(self):
        name = "save-shapes.txt"
        self.fresh(name, "shapes\n")
        good = {"path": self.path(name), "base_sha256": "0" * 64, "text": "x"}
        cases = [
            {"text": 123},
            {"base_sha256": 456},
            {"base_mtime": "1000"},
            {"base_mtime": True},
            {"newline": "git"},
            {"keep_bom": "yes"},
        ]
        for case in cases:
            payload = dict(good)
            payload.update(case)
            response = self.client.put("/api/connections/%s/text" % CONNECTION, payload)
            self.assert_refused(response, 400, "invalid_request")
        missing_path = dict(good)
        missing_path.pop("path")
        self.assert_refused(
            self.client.put("/api/connections/%s/text" % CONNECTION, missing_path),
            400,
            "invalid_request",
        )

    def test_deleted_file_is_reported_on_save(self):
        name = "save-deleted.txt"
        baseline = self.fresh(name, "temp\n")
        testbed_command('rm -f "%s"' % self.path(name))
        response = self.save(name, "back\n", base_sha256=baseline["sha256"])
        self.assert_refused(response, 404, "path_not_found")
        self.assertIn("不存在", response.error["message"])

    def test_target_became_a_directory_is_reported(self):
        name = "save-became-dir.txt"
        baseline = self.fresh(name, "was a file\n")
        testbed_command('rm -f "%s" && mkdir "%s"' % (self.path(name), self.path(name)))
        response = self.save(name, "text\n", base_sha256=baseline["sha256"])
        self.assert_refused(response, 400, "invalid_request")
        self.assertIn("目录", response.error["message"])

    # ------------------------------------------------------------- 写权限

    def test_read_only_connection_can_read_but_not_save(self):
        name = "readonly-connection.txt"
        baseline = self.fresh(name, "readable\n")
        response = self.read(name, connection=READONLY_CONNECTION)
        self.assertEqual(response.status, 200, response)
        self.assertEqual(response.data["file"]["text"], "readable\n")

        denied = self.save(
            name, "should not land\n", connection=READONLY_CONNECTION, base_sha256=baseline["sha256"]
        )
        self.assert_refused(denied, 401, "unauthorized")
        self.assertEqual(denied.error["connection_id"], READONLY_CONNECTION)
        self.assertEqual(self.remote_bytes(name), b"readable\n")


@require_testbed
class EditLimitTests(unittest.TestCase):
    """上限生效时，读与写都要给出可理解的 413，而不是把内存吃掉。"""

    LIMIT = 2048

    @classmethod
    def setUpClass(cls):
        cls._stack = contextlib.ExitStack()
        config, _keys = cls._stack.enter_context(
            testbed_environment(
                connections=[testbed_connection(id=CONNECTION, allow_write=True)],
                security={"max_edit_bytes": cls.LIMIT},
            )
        )
        cls.client = cls._stack.enter_context(running_server(config))
        cls.root = cls._stack.enter_context(edit_fixture())
        assert cls.client.post("/api/connections/%s/connect" % CONNECTION, {}).status == 200

    @classmethod
    def tearDownClass(cls):
        cls._stack.close()

    def path(self, name):
        return "%s/%s" % (self.root, name)

    def text_url(self, name):
        return "/api/connections/%s/text?path=%s" % (CONNECTION, quote(self.path(name), safe=""))

    def test_session_reports_the_configured_limit(self):
        response = self.client.get("/api/session")
        self.assertEqual(response.status, 200, response)
        self.assertEqual(response.data["max_edit_bytes"], self.LIMIT)

    def test_oversized_file_is_refused_before_reading(self):
        response = self.client.get(self.text_url(EIGHT_K))
        self.assert_refused(response, 413, "payload_too_large")
        self.assertEqual(response.error["limit"], self.LIMIT)

    def test_oversized_save_is_refused(self):
        name = "limit-oversize.txt"
        upload_bytes(self.client, self.root, name, b"seed\n")
        baseline = self.client.get(self.text_url(name)).data["file"]
        response = self.client.put(
            "/api/connections/%s/text" % CONNECTION,
            {"path": self.path(name), "text": "a" * (self.LIMIT * 2), "base_sha256": baseline["sha256"]},
        )
        self.assert_refused(response, 413, "payload_too_large")
        # 尺寸检查发生在冲突检查之后，但内容没被改动过。
        self.assertEqual(self.client.get(self.text_url(name)).data["file"]["text"], "seed\n")

    def test_within_the_limit_still_saves(self):
        name = "limit-ok.txt"
        upload_bytes(self.client, self.root, name, b"seed\n")
        baseline = self.client.get(self.text_url(name)).data["file"]
        saved = self.client.put(
            "/api/connections/%s/text" % CONNECTION,
            {"path": self.path(name), "text": "b" * 100, "base_sha256": baseline["sha256"]},
        )
        self.assertEqual(saved.status, 200, saved)
        self.assertEqual(saved.data["file"]["size"], 100)

    def assert_refused(self, response, status, code):
        self.assertEqual(response.status, status, response)
        self.assertEqual(response.code, code, response)


if __name__ == "__main__":
    unittest.main()
