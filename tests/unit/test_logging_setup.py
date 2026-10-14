"""日志：轮转、UTF-8、以及格式化阶段的脱敏（T-011 的一半）。"""

import logging
import tempfile
import unittest
from pathlib import Path

from app.utils import logging_setup
from app.utils.redact import PLACEHOLDER


class LoggingTests(unittest.TestCase):
    def setUp(self):
        logging_setup.reset_for_tests()
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        logging_setup.reset_for_tests()
        self._tmp.cleanup()

    def read_log(self):
        path = self.dir / "awfm.log"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def test_writes_utf8_log_file(self):
        logging_setup.setup_logging(str(self.dir), to_stderr=False)
        logging.getLogger("awfm.test").info("中文日志 与 emoji 😀")
        logging.shutdown()
        logging_setup.reset_for_tests()
        self.assertIn("中文日志 与 emoji 😀", self.read_log())

    def test_credentials_in_dict_args_are_redacted(self):
        logging_setup.setup_logging(str(self.dir), to_stderr=False)
        logging.getLogger("awfm.test").info("连接 %s", {"password": "hunter2", "host": "127.0.0.1"})
        logging.shutdown()
        logging_setup.reset_for_tests()
        text = self.read_log()
        self.assertNotIn("hunter2", text)
        self.assertIn(PLACEHOLDER, text)
        self.assertIn("127.0.0.1", text)  # 非敏感字段保留

    def test_credentials_in_the_message_are_redacted(self):
        logging_setup.setup_logging(str(self.dir), to_stderr=False)
        logging.getLogger("awfm.test").info("使用密码 password=hunter2 连接")
        logging.shutdown()
        logging_setup.reset_for_tests()
        self.assertNotIn("hunter2", self.read_log())

    def test_redaction_can_be_turned_off(self):
        # 关闭脱敏是显式选择，此时日志里能看到原文 —— 这条测试确认开关真的连着。
        logging_setup.setup_logging(str(self.dir), redact_secrets=False, to_stderr=False)
        logging.getLogger("awfm.test").info("密码是 hunter2")
        logging.shutdown()
        logging_setup.reset_for_tests()
        self.assertIn("hunter2", self.read_log())

    def test_percent_style_args_do_not_break_formatting(self):
        # 脱敏若发生在格式化之前又没清空 args，日志里会出现 TypeError 堆栈。
        logging_setup.setup_logging(str(self.dir), to_stderr=False)
        logging.getLogger("awfm.test").info("用户 %s 连接 %s", "aimu", "127.0.0.1")
        logging.shutdown()
        logging_setup.reset_for_tests()
        text = self.read_log()
        self.assertIn("用户 aimu 连接 127.0.0.1", text)
        self.assertNotIn("Traceback", text)

    def test_level_is_applied(self):
        logging_setup.setup_logging(str(self.dir), level="WARNING", to_stderr=False)
        logger = logging.getLogger("awfm.test")
        logger.info("不应出现")
        logger.warning("应出现")
        logging.shutdown()
        logging_setup.reset_for_tests()
        text = self.read_log()
        self.assertNotIn("不应出现", text)
        self.assertIn("应出现", text)

    def test_unwritable_directory_does_not_prevent_startup(self):
        # 日志目录建不出来只警告，不阻止启动。
        target = self.dir / "afile"
        target.write_text("x", encoding="utf-8")
        logging_setup.setup_logging(str(target / "sub"), to_stderr=False)
        logging.getLogger("awfm.test").info("仍然可以记录")
        logging.shutdown()
        logging_setup.reset_for_tests()

    def test_second_call_is_a_no_op(self):
        first = logging_setup.setup_logging(str(self.dir), to_stderr=False)
        handlers = list(first.handlers)
        second = logging_setup.setup_logging(str(self.dir), level="DEBUG", to_stderr=True)
        self.assertIs(first, second)
        self.assertEqual(list(second.handlers), handlers)

    def test_pin_stdio_encoding(self):
        logging_setup.pin_stdio_encoding()  # 不应抛异常


if __name__ == "__main__":
    unittest.main()
