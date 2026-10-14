"""远程路径与名称校验（安全关键，验收项 T-008）。"""

import unittest

from app.core.errors import ValidationError
from app.utils import paths


class ValidateRemotePathTests(unittest.TestCase):
    def test_accepts_absolute_paths(self):
        for value in ("/", "/etc", "/etc/hosts", "/a b/中文 名.txt", "/with'quote"):
            self.assertEqual(paths.validate_remote_path(value), value)

    def test_returns_input_unchanged(self):
        # 不做词法归一：/a/./b 与 /a/b 在服务端语义下可能不同（符号链接）。
        raw = "/a/./b/../c"
        self.assertEqual(paths.validate_remote_path(raw), raw)

    def test_rejects_non_string(self):
        for value in (None, 1, b"/etc", ["/etc"]):
            with self.assertRaises(ValidationError):
                paths.validate_remote_path(value)

    def test_rejects_empty(self):
        with self.assertRaises(ValidationError):
            paths.validate_remote_path("")

    def test_rejects_relative(self):
        for value in ("etc", "./etc", "../etc", "~", "C:/Windows"):
            with self.assertRaises(ValidationError):
                paths.validate_remote_path(value)

    def test_rejects_nul(self):
        with self.assertRaises(ValidationError):
            paths.validate_remote_path("/etc/\x00evil")

    def test_rejects_overlong_path_by_bytes(self):
        with self.assertRaises(ValidationError):
            paths.validate_remote_path("/" + "a" * paths.MAX_PATH_BYTES)
        # 按 UTF-8 字节算长度：1334 个汉字 = 4002 字节，加上前导 / 未超限
        ok = "/" + "汉" * 1334
        self.assertEqual(paths.validate_remote_path(ok), ok)

    def test_allows_control_characters_other_than_nul(self):
        # 控制字符不能一律拒绝：协议用长度前缀字符串承载，拒绝会让这类文件永远无法管理。
        # 真实风险在日志注入与 HTTP 头注入，由 safe_for_log / encode_content_disposition 处理。
        raw = "/tmp/a\nb\tc"
        self.assertEqual(paths.validate_remote_path(raw), raw)


class ValidateRemoteNameTests(unittest.TestCase):
    def test_accepts_plain_names(self):
        for value in ("a.txt", "中文", "..a", "a..", ".hidden", "a b", "a\nb"):
            self.assertEqual(paths.validate_remote_name(value), value)

    def test_rejects_traversal_components(self):
        for value in ("", ".", "..", "a/b", "/etc/passwd", "../etc"):
            with self.assertRaises(ValidationError):
                paths.validate_remote_name(value)

    def test_rejects_nul_and_overlong(self):
        with self.assertRaises(ValidationError):
            paths.validate_remote_name("a\x00b")
        with self.assertRaises(ValidationError):
            paths.validate_remote_name("a" * (paths.MAX_NAME_BYTES + 1))

    def test_rejects_non_string(self):
        with self.assertRaises(ValidationError):
            paths.validate_remote_name(None)


class ParentPathTests(unittest.TestCase):
    def test_root_has_no_parent(self):
        self.assertIsNone(paths.parent_remote_path("/"))
        self.assertIsNone(paths.parent_remote_path(""))

    def test_top_level_parent_is_root(self):
        self.assertEqual(paths.parent_remote_path("/etc"), "/")
        self.assertEqual(paths.parent_remote_path("/etc/"), "/")

    def test_nested(self):
        self.assertEqual(paths.parent_remote_path("/etc/nginx/nginx.conf"), "/etc/nginx")
        self.assertEqual(paths.parent_remote_path("/a/b"), "/a")


class JoinAndSplitTests(unittest.TestCase):
    def test_join(self):
        self.assertEqual(paths.join_remote_path("/", "x"), "/x")
        self.assertEqual(paths.join_remote_path("", "x"), "/x")
        self.assertEqual(paths.join_remote_path("/etc", "x"), "/etc/x")
        self.assertEqual(paths.join_remote_path("/etc/", "x"), "/etc/x")

    def test_split(self):
        self.assertEqual(paths.split_remote_path("/"), [])
        self.assertEqual(paths.split_remote_path("/a/b/"), ["a", "b"])
        self.assertEqual(paths.split_remote_path("/a//b"), ["a", "b"])


class WithinRootTests(unittest.TestCase):
    def test_inside(self):
        self.assertTrue(paths.is_within_root("/home/a", "/home/a"))
        self.assertTrue(paths.is_within_root("/home/a", "/home/a/b"))

    def test_sibling_prefix_is_not_inside(self):
        # 字符串前缀比较的经典漏洞：/home/ab 以 /home/a 开头，但它不在 /home/a 内。
        self.assertFalse(paths.is_within_root("/home/a", "/home/ab"))
        self.assertFalse(paths.is_within_root("/home/a", "/home/a/../b"))
        self.assertFalse(paths.is_within_root("/home/a", "/etc/passwd"))

    def test_root_contains_everything(self):
        self.assertTrue(paths.is_within_root("/", "/anything"))
        self.assertTrue(paths.is_within_root("", "/anything"))


class SafeForLogTests(unittest.TestCase):
    def test_escapes_control_characters(self):
        # 攻击场景：文件名里塞进换行 + 伪造的日志行。
        self.assertEqual(paths.safe_for_log("evil\nERROR ok"), "evil\\x0aERROR ok")
        self.assertEqual(paths.safe_for_log("a\rb"), "a\\x0db")
        self.assertEqual(paths.safe_for_log("a\tb"), "a\\x09b")

    def test_truncates_long_values(self):
        result = paths.safe_for_log("a" * 400, limit=10)
        self.assertTrue(result.startswith("a" * 10))
        self.assertTrue(result.endswith("...(+390)"))

    def test_keeps_normal_text(self):
        self.assertEqual(paths.safe_for_log("/etc/hosts"), "/etc/hosts")


class ContentDispositionTests(unittest.TestCase):
    def test_ascii_name_has_both_forms(self):
        header = paths.encode_content_disposition("report.txt")
        self.assertIn('filename="report.txt"', header)
        self.assertIn("filename*=UTF-8''report.txt", header)
        self.assertTrue(header.startswith("attachment;"))

    def test_unicode_name_uses_rfc5987(self):
        header = paths.encode_content_disposition("中文.txt")
        self.assertIn("filename*=UTF-8''%E4%B8%AD%E6%96%87.txt", header)

    def test_newline_is_encoded_not_emitted(self):
        # 未编码的换行 = HTTP 响应头注入（响应拆分）。
        header = paths.encode_content_disposition("a\r\nX-Evil: 1.txt")
        self.assertNotIn("\r", header)
        self.assertNotIn("\n", header)
        self.assertIn("%0D%0A", header)

    def test_quotes_and_backslashes_removed_from_fallback(self):
        header = paths.encode_content_disposition('a"b\\c.txt')
        self.assertIn('filename="a_b_c.txt"', header)

    def test_empty_name_falls_back(self):
        self.assertIn('filename="download"', paths.encode_content_disposition(""))


class PercentEncodeTests(unittest.TestCase):
    def test_slash_is_encoded(self):
        self.assertEqual(paths.percent_encode_segment("/etc"), "%2Fetc")
        self.assertEqual(paths.percent_encode_segment("中文"), "%E4%B8%AD%E6%96%87")


class NormalizeUnicodeTests(unittest.TestCase):
    def test_nfd_becomes_nfc_for_comparison(self):
        import unicodedata

        nfd = unicodedata.normalize("NFD", "café")
        nfc = unicodedata.normalize("NFC", "café")
        self.assertNotEqual(nfd, nfc)
        self.assertEqual(paths.normalize_unicode(nfd), nfc)


if __name__ == "__main__":
    unittest.main()
