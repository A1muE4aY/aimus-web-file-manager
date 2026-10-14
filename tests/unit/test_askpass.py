"""SSH_ASKPASS 辅助程序：密码落在临时文件里，且只活一次认证的时长（决策 D-008）。"""

import os
import unittest

from app.core.errors import ConfigError
from app.ssh.askpass import ASKPASS_FILE_ENV, prepare_askpass


class AskpassTests(unittest.TestCase):
    def test_creates_a_wrapper_and_a_secret_file(self):
        with prepare_askpass("hunter2") as bundle:
            self.assertTrue(os.path.isfile(bundle.command))
            secret = bundle.payload[ASKPASS_FILE_ENV]
            self.assertTrue(os.path.isfile(secret))
            with open(secret, "r", encoding="utf-8", newline="") as handle:
                self.assertEqual(handle.read(), "hunter2")

    def test_wrapper_name_matches_the_platform(self):
        with prepare_askpass("pw") as bundle:
            expected = "askpass.cmd" if os.name == "nt" else "askpass.sh"
            self.assertEqual(os.path.basename(bundle.command), expected)

    def test_password_is_not_baked_into_the_script(self):
        # 密码只能存在于单独的 secret 文件里；写进脚本就等于把凭据复制到另一处。
        with prepare_askpass("s3cr3t-value") as bundle:
            for name in os.listdir(os.path.dirname(bundle.command)):
                if name == "secret":
                    continue
                with open(os.path.join(os.path.dirname(bundle.command), name), "r", encoding="utf-8") as handle:
                    self.assertNotIn("s3cr3t-value", handle.read(), name)

    def test_password_is_never_in_the_environment_payload(self):
        with prepare_askpass("hunter2") as bundle:
            self.assertNotIn("hunter2", str(bundle.payload))

    def test_trailing_space_and_special_characters_survive(self):
        # newline="" + 不加换行：密码可能合法地以空格结尾。
        for password in ("pw ", "  leading", "a b\tc", "密码123", '"quoted"'):
            with prepare_askpass(password) as bundle:
                with open(bundle.payload[ASKPASS_FILE_ENV], "r", encoding="utf-8", newline="") as handle:
                    self.assertEqual(handle.read(), password, repr(password))

    def test_cleanup_removes_everything_and_is_idempotent(self):
        bundle = prepare_askpass("pw")
        directory = os.path.dirname(bundle.command)
        self.assertTrue(os.path.isdir(directory))
        bundle.cleanup()
        self.assertFalse(os.path.exists(directory))
        bundle.cleanup()  # 幂等

    def test_context_manager_cleans_up(self):
        with prepare_askpass("pw") as bundle:
            directory = os.path.dirname(bundle.command)
        self.assertFalse(os.path.exists(directory))

    def test_empty_password_is_refused(self):
        # 空密码会让 ssh 把「密码错误」和「没提供密码」混为一谈。
        with self.assertRaises(ConfigError):
            prepare_askpass("")

    def test_each_preparation_uses_a_fresh_directory(self):
        first = prepare_askpass("a")
        second = prepare_askpass("b")
        try:
            self.assertNotEqual(first.command, second.command)
            self.assertNotEqual(first.payload[ASKPASS_FILE_ENV], second.payload[ASKPASS_FILE_ENV])
        finally:
            first.cleanup()
            second.cleanup()

    def test_wrapper_invokes_the_helper_with_the_current_interpreter(self):
        import sys

        with prepare_askpass("pw") as bundle:
            with open(bundle.command, "r", encoding="utf-8", newline="") as handle:
                content = handle.read()
            self.assertIn(sys.executable, content)
            self.assertIn("askpass_helper.py", content)


if __name__ == "__main__":
    unittest.main()
