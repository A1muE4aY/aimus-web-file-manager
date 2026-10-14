"""请求包装：百分号解码、查询参数、JSON 请求体。"""

import io
import json
import unittest

from app.api.request import MAX_JSON_BODY, ApiRequest
from app.core.errors import PayloadTooLarge, ValidationError


class FakeHandler:
    def __init__(self, path="/api/x", method="GET", headers=None, body=b""):
        self.command = method
        self.path = path
        self.headers = dict(headers or {})
        self.rfile = io.BytesIO(body)


def make(path="/api/x", method="GET", headers=None, body=b""):
    return ApiRequest(FakeHandler(path=path, method=method, headers=headers, body=body))


class PathTests(unittest.TestCase):
    def test_method_is_uppercased(self):
        self.assertEqual(make(method="get").method, "GET")

    def test_query_string_is_stripped_from_path(self):
        self.assertEqual(make(path="/api/files?path=/a").path, "/api/files")

    def test_percent_encoded_utf8_path_is_decoded(self):
        # http.server 用 latin-1 解过一遍原始字节；不还原字节再按 UTF-8 解，
        # 含中文的路径会变成乱码。
        request = make(path="/api/files?path=%2F%E4%B8%AD%E6%96%87%2F%E6%96%87%E4%BB%B6.txt")
        self.assertEqual(request.query("path"), "/中文/文件.txt")

    def test_plus_is_not_a_space_in_paths(self):
        request = make(path="/api/files?path=/a+b")
        self.assertEqual(request.query("path"), "/a b")  # 查询串里 + 就是空格（表单编码）


class QueryTests(unittest.TestCase):
    def test_missing_and_default(self):
        request = make(path="/api/x")
        self.assertIsNone(request.query("path"))
        self.assertEqual(request.query("path", "/"), "/")

    def test_blank_value_is_kept(self):
        request = make(path="/api/x?path=")
        self.assertEqual(request.query("path"), "")
        with self.assertRaises(ValidationError):
            request.require_query("path")

    def test_require_query(self):
        request = make(path="/api/x?path=/a")
        self.assertEqual(request.require_query("path"), "/a")

    def test_query_bool(self):
        for raw in ("1", "true", "TRUE", "yes", "on"):
            self.assertTrue(make(path="/api/x?flag=" + raw).query_bool("flag"), raw)
        for raw in ("0", "false", "no", "off"):
            self.assertFalse(make(path="/api/x?flag=" + raw).query_bool("flag"), raw)

    def test_query_bool_default_and_junk(self):
        self.assertTrue(make(path="/api/x").query_bool("flag", True))
        with self.assertRaises(ValidationError):
            make(path="/api/x?flag=maybe").query_bool("flag")

    def test_query_int(self):
        self.assertEqual(make(path="/api/x?n=42").query_int("n"), 42)
        self.assertEqual(make(path="/api/x").query_int("n", 7), 7)
        with self.assertRaises(ValidationError):
            make(path="/api/x?n=abc").query_int("n")


class ContentLengthTests(unittest.TestCase):
    def test_absent_is_zero(self):
        self.assertEqual(make().content_length, 0)

    def test_parsed(self):
        self.assertEqual(make(headers={"Content-Length": "5"}, body=b"12345").content_length, 5)

    def test_junk_and_negative_are_refused(self):
        for raw in ("abc", "-1", "1.5"):
            with self.assertRaises(ValidationError, msg=raw):
                make(headers={"Content-Length": raw}).content_length


class JsonTests(unittest.TestCase):
    def body(self, payload: bytes, length=None):
        headers = {"Content-Length": str(len(payload) if length is None else length)}
        return make(method="POST", headers=headers, body=payload)

    def test_empty_body_is_empty_object(self):
        self.assertEqual(make().json(), {})

    def test_valid_object(self):
        self.assertEqual(self.body(b'{"a": 1}').json(), {"a": 1})

    def test_result_is_cached(self):
        request = self.body(b'{"a": 1}')
        self.assertIs(request.json(), request.json())

    def test_invalid_utf8(self):
        with self.assertRaises(ValidationError) as ctx:
            self.body(b"\xff\xfe").json()
        self.assertIn("UTF-8", str(ctx.exception))

    def test_syntax_error_reports_position(self):
        with self.assertRaises(ValidationError) as ctx:
            self.body(b'{\n  "a": 1,\n}').json()
        self.assertIn("3", ctx.exception.detail)  # 行号

    def test_non_object_root(self):
        for payload in (b"[1, 2]", b'"x"', b"3"):
            with self.assertRaises(ValidationError, msg=payload):
                self.body(payload).json()

    def test_oversized_body_is_refused_before_reading(self):
        request = make(method="POST", headers={"Content-Length": str(MAX_JSON_BODY + 1)}, body=b"")
        with self.assertRaises(PayloadTooLarge):
            request.json()

    def test_short_body_is_reported(self):
        request = make(method="POST", headers={"Content-Length": "10"}, body=b"abc")
        with self.assertRaises(ValidationError) as ctx:
            request.json()
        self.assertIn("不完整", str(ctx.exception))

    def test_unicode_is_preserved(self):
        payload = json.dumps({"name": "中文"}, ensure_ascii=False).encode("utf-8")
        self.assertEqual(self.body(payload).json()["name"], "中文")


if __name__ == "__main__":
    unittest.main()
