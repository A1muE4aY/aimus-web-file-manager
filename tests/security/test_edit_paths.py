"""在线编辑与文件操作接口的安全边界（阶段四）。

三类用例：

* 不需要测试床：未授权调用、畸形请求体、未知连接。畸形请求必须与连接状态无关
  —— 否则「参数错」会被误报成「没连接」，客户端分不清该改请求还是该先连上。
* 需要测试床：路径形状、写权限关闭时的服务端拒绝、压缩包里的越界成员名。
  界面上的按钮禁用只是提示，真正的防线在服务端：写权限关掉之后直接用 HTTP
  打进来必须还是 401，而且远端一个字节都不能变。
* 被拒绝的解压不能留下任何痕迹（临时文件、越界文件）。
"""

import contextlib
import io
import tarfile
import unittest
import zipfile

from tests.integration.support import (
    connection_url,
    edit_fixture,
    ops_fixture,
    require_testbed,
    running_server,
    testbed_connection,
    testbed_environment,
    upload_bytes,
)
from tests.security.support import DEAD_CONNECTION, local_server

CONNECTION = "wsl-testbed"
READONLY_CONNECTION = "wsl-readonly"
DEAD = DEAD_CONNECTION["id"]

WRITE_ENDPOINTS = ("rename", "delete", "compress", "extract")

OVERLONG_PATH = "/" + "a" * 4096


def build_tar_gz(members):
    """members 里每项是 (名字, bytes)，名字保持原样写入（可以带 .. 或前导斜杠）。"""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.GNU_FORMAT) as tar:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class RouteBoundaryTests(unittest.TestCase):
    """不需要测试床：接口边界与请求体形状。"""

    def setUp(self):
        self._stack = contextlib.ExitStack()
        self.harness = self._stack.enter_context(local_server())
        self.client = self.harness.client
        self.addCleanup(self._stack.close)

    def url(self, suffix, *, connection=DEAD):
        return "/api/connections/%s/%s" % (connection, suffix)

    def test_write_endpoints_require_a_token(self):
        calls = [
            ("GET", self.url("text") + "?path=/tmp", None),
            ("PUT", self.url("text"), {}),
            ("POST", self.url("rename"), {}),
            ("POST", self.url("delete"), {}),
            ("POST", self.url("compress"), {}),
            ("POST", self.url("extract"), {}),
        ]
        for method, path, body in calls:
            with self.subTest(method=method, path=path):
                response = self.client.request(method, path, body=body, token=False)
                self.assertEqual(response.status, 401, response)
                self.assertEqual(response.code, "unauthorized", response)

    def test_malformed_bodies_are_rejected_without_a_live_session(self):
        """形状检查先于找会话：畸形请求不该因为「没连上」变成 404。"""
        cases = [
            ("PUT", "text", {"text": "x"}),
            ("PUT", "text", {"path": "", "text": "x"}),
            ("PUT", "text", {"path": 5, "text": "x"}),
            ("PUT", "text", {"path": "/tmp/x"}),
            ("PUT", "text", {"path": "/tmp/x", "text": 123}),
            ("PUT", "text", {"path": "/tmp/x", "text": "x", "base_sha256": 5}),
            ("PUT", "text", {"path": "/tmp/x", "text": "x", "base_mtime": "y"}),
            ("PUT", "text", {"path": "/tmp/x", "text": "x", "base_mtime": True}),
            ("PUT", "text", {"path": "/tmp/x", "text": "x", "newline": "git"}),
            ("PUT", "text", {"path": "/tmp/x", "text": "x", "keep_bom": "yes"}),
            ("POST", "rename", {"path": "/tmp/x"}),
            ("POST", "rename", {"path": "/tmp/x", "new_name": 5}),
            ("POST", "rename", {}),
            ("POST", "delete", {}),
            ("POST", "delete", {"path": "/tmp/x", "recursive": "yes"}),
            ("POST", "compress", {}),
            ("POST", "compress", {"path": "/tmp/x", "name": 5}),
            ("POST", "extract", {}),
            ("POST", "extract", {"path": "/tmp/x", "into": 5}),
            ("POST", "extract", {"path": "/tmp/x", "overwrite": "yes"}),
        ]
        for method, suffix, body in cases:
            with self.subTest(method=method, suffix=suffix, body=body):
                response = self.client.request(method, self.url(suffix), body=body)
                self.assertEqual(response.status, 400, response)
                self.assertEqual(response.code, "invalid_request", response)

    def test_unknown_connection_is_not_found(self):
        for method, suffix, body in (
            ("GET", "text?path=/tmp", None),
            ("PUT", "text", {"path": "/tmp/x", "text": "x", "base_mtime": 1}),
            ("POST", "rename", {"path": "/tmp/x", "new_name": "y"}),
            ("POST", "delete", {"path": "/tmp/x"}),
            ("POST", "compress", {"path": "/tmp/x"}),
            ("POST", "extract", {"path": "/tmp/x.tar.gz"}),
        ):
            with self.subTest(method=method, suffix=suffix):
                response = self.client.request(
                    method, self.url(suffix, connection="no-such-host"), body=body
                )
                self.assertEqual(response.status, 404, response)
                self.assertEqual(response.code, "connection_not_found", response)


@require_testbed
class ParameterValidationTests(unittest.TestCase):
    """需要测试床：路径形状与写权限的服务端门禁。"""

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

    def path(self, name):
        if name.startswith("/"):
            return name
        return "%s/%s" % (self.root, name)

    def bad_paths(self):
        return ["home/aimu/plain.txt", self.root + "/sub/../plain.txt\x00x", OVERLONG_PATH]

    def test_read_path_shapes_are_refused(self):
        for bad in self.bad_paths():
            with self.subTest(path=bad[:40]):
                response = self.client.get(
                    connection_url(CONNECTION, "text", path=bad)
                )
                self.assertEqual(response.status, 400, response)
                self.assertEqual(response.code, "invalid_request", response)

    def test_read_without_a_path_is_refused(self):
        response = self.client.get(connection_url(CONNECTION, "text"))
        self.assertEqual(response.status, 400, response)
        self.assertEqual(response.code, "invalid_request", response)

    def test_read_refuses_a_directory_and_a_missing_file(self):
        directory = self.client.get(connection_url(CONNECTION, "text", path=self.root))
        self.assertEqual(directory.status, 400, directory)
        missing = self.client.get(
            connection_url(CONNECTION, "text", path=self.path("no-such-file.txt"))
        )
        self.assertEqual(missing.status, 404, missing)
        self.assertEqual(missing.code, "path_not_found", missing)

    def test_save_path_shapes_are_refused(self):
        for bad in self.bad_paths():
            with self.subTest(path=bad[:40]):
                response = self.client.put(
                    "/api/connections/%s/text" % CONNECTION,
                    {"path": bad, "text": "x", "base_mtime": 1},
                )
                self.assertEqual(response.status, 400, response)
                self.assertEqual(response.code, "invalid_request", response)

    def test_operation_path_shapes_are_refused(self):
        for suffix in WRITE_ENDPOINTS:
            for bad in self.bad_paths():
                body = {"path": bad}
                if suffix == "rename":
                    body["new_name"] = "renamed.txt"
                with self.subTest(endpoint=suffix, path=bad[:40]):
                    response = self.client.post(
                        "/api/connections/%s/%s" % (CONNECTION, suffix), body
                    )
                    self.assertEqual(response.status, 400, response)
                    self.assertEqual(response.code, "invalid_request", response)

    def test_write_endpoints_are_refused_when_the_toggle_is_off(self):
        """界面禁用只是提示：写权限关掉后，直接打接口也必须被服务端拒绝。"""
        calls = [
            ("PUT", "text", {"path": self.path("plain.txt"), "text": "x", "base_mtime": 1}),
            ("POST", "rename", {"path": self.path("plain.txt"), "new_name": "renamed.txt"}),
            ("POST", "delete", {"path": self.path("plain.txt")}),
            ("POST", "compress", {"path": self.path("plain.txt")}),
            ("POST", "extract", {"path": self.path("plain.txt.tar.gz")}),
        ]
        for method, suffix, body in calls:
            with self.subTest(endpoint=suffix):
                response = self.client.request(
                    method,
                    "/api/connections/%s/%s" % (READONLY_CONNECTION, suffix),
                    body=body,
                )
                self.assertEqual(response.status, 401, response)
                self.assertEqual(response.code, "unauthorized", response)
                self.assertEqual(response.error["connection_id"], READONLY_CONNECTION)
        # 每一次拒绝都发生在服务端，远端文件必须原样。
        listing = self.client.get(connection_url(CONNECTION, "files", path=self.root))
        names = [item["name"] for item in listing.data["entries"]]
        self.assertIn("plain.txt", names)
        self.assertNotIn("renamed.txt", names)
        self.assertNotIn("plain.txt.tar.gz", names)


@require_testbed
class ArchiveSafetyTests(unittest.TestCase):
    """需要测试床：解压的越界成员名必须在服务端被挡住。"""

    @classmethod
    def setUpClass(cls):
        cls._stack = contextlib.ExitStack()
        config, _keys = cls._stack.enter_context(
            testbed_environment(connections=[testbed_connection(id=CONNECTION, allow_write=True)])
        )
        cls.client = cls._stack.enter_context(running_server(config))
        cls.root = cls._stack.enter_context(ops_fixture())
        response = cls.client.post("/api/connections/%s/connect" % CONNECTION, {})
        assert response.status == 200, response

    @classmethod
    def tearDownClass(cls):
        cls._stack.close()

    def path(self, name):
        if name.startswith("/"):
            return name
        return "%s/%s" % (self.root, name)

    def names(self, directory):
        response = self.client.get(connection_url(CONNECTION, "files", path=directory))
        self.assertEqual(response.status, 200, response)
        return [item["name"] for item in response.data["entries"]]

    def put(self, name, data):
        response = upload_bytes(self.client, self.root, name, data)
        self.assertIn(response.status, (200, 201), response)
        return name

    def extract(self, name):
        return self.client.post(
            "/api/connections/%s/extract" % CONNECTION, {"path": self.path(name)}
        )

    def test_traversal_members_are_refused(self):
        archives = {
            "up.tar.gz": build_tar_gz([("../evil.txt", b"boom\n")]),
            "deep.tar.gz": build_tar_gz([("a/../../evil.txt", b"boom\n")]),
            "absolute.tar.gz": build_tar_gz([("/etc/evil.txt", b"boom\n")]),
            "backslash.tar.gz": build_tar_gz([("..\\evil.txt", b"boom\n")]),
        }
        for name, payload in archives.items():
            self.put(name, payload)
            with self.subTest(archive=name):
                response = self.extract(name)
                self.assertEqual(response.status, 400, response)
                self.assertEqual(response.code, "invalid_request", response)
        # 越界的文件一个都没落下，临时文件也没留。
        tmp_names = self.names("/tmp")
        self.assertNotIn("evil.txt", tmp_names)
        root_names = self.names(self.root)
        self.assertNotIn("evil.txt", root_names)
        self.assertEqual([n for n in root_names if ".awfm-part-" in n], [])

    def test_zip_traversal_is_refused(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("../evil.txt", b"boom\n")
        self.put("zip-evil.zip", buffer.getvalue())
        response = self.extract("zip-evil.zip")
        self.assertEqual(response.status, 400, response)
        self.assertEqual(response.code, "invalid_request", response)
        self.assertNotIn("evil.txt", self.names("/tmp"))

    def test_a_good_archive_still_works_after_the_rejections(self):
        """拒绝越界之后，正常的压缩包必须照常能解（拒绝没有把连接搞坏）。"""
        good = build_tar_gz([("fine.txt", b"fine\n")])
        self.put("fine.tar.gz", good)
        response = self.client.post(
            "/api/connections/%s/extract" % CONNECTION, {"path": self.path("fine.tar.gz")}
        )
        self.assertEqual(response.status, 201, response)
        self.assertEqual(response.data["extract"]["files"], 1)
        self.assertIn("fine.txt", self.names(self.root))


if __name__ == "__main__":
    unittest.main()
