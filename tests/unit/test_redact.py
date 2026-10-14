"""日志脱敏（验收项 T-011：密码、私钥不得出现在普通日志里）。"""

import logging
import unittest

from app.utils.redact import PLACEHOLDER, RedactingFilter, redact


class RedactTextTests(unittest.TestCase):
    def test_private_key_block(self):
        text = (
            "key:\n-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n"
            "-----END OPENSSH PRIVATE KEY-----\ndone"
        )
        result = redact(text)
        self.assertIn(PLACEHOLDER, result)
        self.assertNotIn("b3BlbnNzaC1rZXktdjEAAAAA", result)

    def test_identity_file_argument(self):
        result = redact("命令：ssh -i C:/Users/aimu/.ssh/id_ed25519 host -s sftp")
        self.assertNotIn("id_ed25519", result)
        self.assertIn(PLACEHOLDER, result)

    def test_password_assignments(self):
        for text in ('password="hunter2"', "password: hunter2", "passwd=hunter2", "PASSWORD = 'hunter2'"):
            self.assertNotIn("hunter2", redact(text), text)

    def test_token_and_secret_keys(self):
        self.assertNotIn("abc123", redact("token=abc123"))
        self.assertNotIn("abc123", redact('"api_key": "abc123"'))

    def test_keeps_ordinary_text(self):
        text = "已连接 aimu@127.0.0.1:2222，主目录 /home/aimu"
        self.assertEqual(redact(text), text)

    def test_non_string_is_returned_unchanged(self):
        self.assertEqual(redact(42), 42)
        self.assertIsNone(redact(None))


class RedactingFilterTests(unittest.TestCase):
    def setUp(self):
        self.filter = RedactingFilter()

    def _record(self, msg, args):
        return logging.LogRecord("t", logging.WARNING, __file__, 1, msg, args, None)

    def test_filters_formatted_arguments(self):
        record = self._record("连接参数 password=%s", ("hunter2",))
        self.filter.filter(record)
        self.assertNotIn("hunter2", record.getMessage())

    def test_filters_message_without_args(self):
        record = self._record("password=hunter2", ())
        self.filter.filter(record)
        self.assertNotIn("hunter2", record.getMessage())

    def test_filters_dict_arguments(self):
        record = self._record("配置 %(password)s", ({"password": "hunter2"},))
        self.filter.filter(record)
        self.assertNotIn("hunter2", record.getMessage())

    def test_must_not_raise_on_weird_input(self):
        class Bad:
            def __repr__(self):
                raise RuntimeError("boom")

        record = logging.LogRecord("t", logging.INFO, __file__, 1, "x=%s", (Bad(),), None)
        # 过滤器绝不抛异常：日志本身不能把程序弄崩。
        self.assertTrue(self.filter.filter(record))

    def test_returns_true_so_records_are_kept(self):
        record = self._record("普通消息", ())
        self.assertTrue(self.filter.filter(record))


if __name__ == "__main__":
    unittest.main()
