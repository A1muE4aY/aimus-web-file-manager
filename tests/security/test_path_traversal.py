"""远端路径语义的安全测试（规划文档 §7.1 的 T-008、§10.4）。

这里验证的**不是**「拒绝 ..」—— AWFM 暴露的就是目标机上该 SSH 用户的文件系统，
用户本来就能读 /etc/passwd，挡住它只是安全表演。真正要证明的是：

1. 客户端**不做词法 .. 折叠**：.. 交给服务端 REALPATH 解析，
   否则 /home/a/link/../x 这类路径会被客户端改成错误的目标；
2. 百分号解码**只做一次**：%252e%252e 必须被当成字面文件名，而不是又一次 ..；
3. 反斜杠必须保持字面字符语义，不得被当成路径分隔符；
4. NUL 与超长路径必须被拒绝，不允许把畸形字符串交给子进程；
5. 上传的文件名必须是一个单独分量 —— 这是**写操作真正的边界**。
"""

from __future__ import annotations

import contextlib
import unittest
from urllib.parse import quote

from tests.integration.support import (
    require_testbed,
    running_server,
    testbed_connection,
    testbed_environment,
)

CONNECTION = "wsl-testbed"


def api(path: str) -> str:
    return "/api/connections/" + CONNECTION + path


def files_url(path: str) -> str:
    return api("/files?path=" + quote(path, safe=""))


def upload_url(directory: str, name: str) -> str:
    return (
        api("/upload?path=" + quote(directory, safe="") + "&name=" + quote(name, safe=""))
    )


@require_testbed
class RemotePathSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._stack = contextlib.ExitStack()
        config, _keys = cls._stack.enter_context(
            testbed_environment(connections=[testbed_connection(allow_write=True)])
        )
        cls.client = cls._stack.enter_context(running_server(config))
        response = cls.client.post(api("/connect"))
        if not response.ok:
            cls._stack.close()
            raise AssertionError("测试床连接失败：" + repr(response))

    @classmethod
    def tearDownClass(cls):
        cls._stack.close()

    def _remove(self, path: str) -> None:
        try:
            self.client.manager.session(CONNECTION).client.remove(path)
        except Exception:
            pass

    def test_relative_paths_are_rejected_outright(self):
        # 相对路径会让「当前目录」变成隐式状态，API 一律要求绝对路径
        # （app/utils/paths.py:71-74）。这一条同时是「.. 不会被当成相对路径处理」的证明。
        for raw in ("../..", "home/aimu", "./", ".."):
            with self.subTest(path=raw):
                response = self.client.get(files_url(raw))
                self.assertEqual(response.status, 400, response)
                self.assertEqual(response.code, "invalid_request", response)

    def test_parent_segments_are_resolved_by_the_server(self):
        for raw in ("/home/aimu/../..", "/home/aimu/./../.."):
            with self.subTest(path=raw):
                response = self.client.get(files_url(raw))
                self.assertTrue(response.ok, response)
                self.assertEqual(response.data["path"], "/")

    def test_percent_decoding_happens_exactly_once(self):
        plain = self.client.get(files_url("/home/aimu/../.."))
        self.assertTrue(plain.ok, plain)
        self.assertEqual(plain.data["path"], "/")
        # %2e%2e 与 %2f 都要被解成 .. 与 /（只解一次），结果必须与明文写法一致。
        encoded = self.client.get(api("/files?path=%2fhome%2faimu%2f%2e%2e%2f%2e%2e"))
        self.assertTrue(encoded.ok, encoded)
        self.assertEqual(encoded.data["path"], plain.data["path"])
        # 双重编码必须被当作**字面文件名**：解一次后剩下 %2e%2e，那不是 ..
        double = self.client.get(api("/files?path=%2fhome%2faimu%2f%252e%252e"))
        self.assertFalse(double.ok, double)
        self.assertEqual(double.code, "path_not_found", double)

    def test_null_bytes_and_overlong_paths_are_rejected(self):
        for raw, label in (("/home/aimu\u0000", "NUL"), ("/" + "a" * 5000, "超长")):
            with self.subTest(case=label):
                response = self.client.get(files_url(raw))
                self.assertEqual(response.status, 400, response)
                self.assertEqual(response.code, "invalid_request", response)

    def test_backslash_is_a_literal_filename_character(self):
        response = self.client.get(files_url("/home/aimu" + chr(92) + ".." + chr(92) + ".."))
        self.assertFalse(response.ok, response)
        self.assertEqual(response.code, "path_not_found", response)

    def test_hostile_names_are_never_interpreted_by_a_shell(self):
        hostile = (
            "/home/aimu/$(id)",
            "/home/aimu/; rm -rf /",
            "/home/aimu/*",
            "/home/aimu/" + chr(96) + "id" + chr(96),
        )
        for raw in hostile:
            with self.subTest(path=raw):
                response = self.client.get(files_url(raw))
                self.assertEqual(response.status, 404, response)
                self.assertEqual(response.code, "path_not_found", response)
        self.assertEqual(self.client.get("/api/health").status, 200)

    def test_upload_rejects_names_that_escape_the_directory(self):
        directory = "/home/aimu"
        for name in ("../evil.txt", "a/evil.txt", "/tmp/evil.txt", "..", ".", ".awfm-part-1"):
            with self.subTest(name=name):
                response = self.client.post(upload_url(directory, name), body=b"x")
                self.assertEqual(response.status, 400, response)
                self.assertEqual(response.code, "invalid_request", response)
        listing = self.client.get(files_url(directory))
        self.assertTrue(listing.ok, listing)
        self.assertEqual(
            [entry["name"] for entry in listing.data["entries"] if "evil" in entry["name"]],
            [],
        )

    def test_upload_never_overwrites_without_an_explicit_flag(self):
        directory = "/home/aimu"
        name = "awfm-security-overwrite.txt"
        target = directory + "/" + name
        self.addCleanup(self._remove, target)
        first = self.client.post(upload_url(directory, name), body="第一版".encode("utf-8"))
        self.assertEqual(first.status, 201, first)
        again = self.client.post(upload_url(directory, name), body="第二版".encode("utf-8"))
        self.assertEqual(again.status, 400, again)
        preview = self.client.get(api("/preview?path=" + quote(target, safe="")))
        self.assertTrue(preview.ok, preview)
        self.assertEqual(preview.data["text"], "第一版")
        forced = self.client.post(
            upload_url(directory, name) + "&overwrite=1", body="第二版".encode("utf-8")
        )
        self.assertEqual(forced.status, 200, forced)

    def test_download_ticket_is_bound_to_one_file(self):
        directory = "/home/aimu"
        name = "awfm-security-ticket.txt"
        target = directory + "/" + name
        payload = "票据内容 ticket test".encode("utf-8")
        self.addCleanup(self._remove, target)
        uploaded = self.client.post(upload_url(directory, name), body=payload)
        self.assertEqual(uploaded.status, 201, uploaded)
        issued = self.client.post(api("/download-ticket"), {"path": target})
        self.assertTrue(issued.ok, issued)
        url = issued.data["url"]
        # 浏览器直接导航下载时带不了自定义头，票据必须能单独成立。
        downloaded = self.client.get(url, token=False)
        self.assertEqual(downloaded.status, 200, downloaded)
        self.assertEqual(downloaded.raw, payload)
        # 换一个文件：票据与路径绑定，必须被拒。
        tampered = url.split("&path=")[0] + "&path=" + quote(directory + "/.bashrc", safe="")
        rejected = self.client.get(tampered, token=False)
        self.assertEqual(rejected.status, 401, rejected)
        # 伪造票据同样被拒。
        forged = url.replace(issued.data["ticket"], "0" * 32)
        self.assertEqual(self.client.get(forged, token=False).status, 401)

    def test_hostile_paths_never_produce_a_server_error(self):
        hostile = (
            "/home/aimu/\n",
            "/home/aimu/\u0001\u0002",
            "/home/aimu/" + "中" * 200,
            "~",
            "/home/aimu/-rf",
            "/" + "/".join(["x"] * 200),
        )
        for raw in hostile:
            with self.subTest(path=raw[:40]):
                response = self.client.get(files_url(raw))
                self.assertNotEqual(response.status, 500, response)
                self.assertIn(
                    response.status, (200, 400, 403, 404, 409, 413, 502, 504), response
                )
        self.assertEqual(self.client.get("/api/health").status, 200)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
