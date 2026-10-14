"""凭据保护测试（规划文档 §10.2 / §10.6，验收项 T-011）。

要证明三件事：

1. 密码**进不了配置文件** —— API 直接拒绝 password 字段，落盘配置里没有它；
2. 密码**不回显到前端** —— 连接失败的错误响应里没有它，任何 GET 响应里也没有；
3. 密码**不写日志、不进命令行** —— 真实连接尝试走完之后日志里找不到它，
   ssh 进程的 argv 里没有它（密码只经由 askpass 的临时文件传递）。
"""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path

from app.ssh.askpass import ASKPASS_FILE_ENV, prepare_askpass
from app.ssh.ssh_launcher import (
    SshTarget,
    build_environment,
    build_sftp_command,
    find_ssh_executable,
)
from app.utils.logging_setup import reset_for_tests, setup_logging
from app.utils.redact import PLACEHOLDER
from tests.security.support import DEAD_CONNECTION, local_server

#: 哨兵值：任何响应、任何日志里出现它就说明凭据泄漏了。
SENTINEL = "awfm-sentinel-password-6d1f"
#: 私钥路径标记：脱敏正则要把命令行里 -i 后面的整段路径换掉。
KEY_MARKER = "id_ed25519_awfm_marker"
CONNECTION_URL = "/api/connections/dead-host"


class ConfigNeverStoresPasswords(unittest.TestCase):
    def test_api_rejects_a_password_field(self):
        with local_server(connections=[]) as harness:
            response = harness.client.post(
                "/api/connections",
                {
                    "name": "带密码的连接",
                    "host": "127.0.0.1",
                    "port": 22,
                    "username": "aimu",
                    "password": SENTINEL,
                },
            )
            self.assertEqual(response.status, 400, response)
            self.assertEqual(response.code, "invalid_request", response)
            self.assertNotIn(SENTINEL, response.raw.decode("utf-8"))

    def test_written_config_contains_no_password_key(self):
        with local_server(connections=[]) as harness:
            created = harness.client.post(
                "/api/connections",
                {
                    "name": "无密码连接",
                    "host": "127.0.0.1",
                    "port": 22,
                    "username": "aimu",
                    "auth_method": "key",
                    "identity_file": "C:/keys/id_ed25519",
                },
            )
            self.assertEqual(created.status, 201, created)
            config_file = harness.tmp / "config.json"
            self.assertTrue(config_file.is_file(), "配置未落盘：" + str(config_file))
            text = config_file.read_text(encoding="utf-8")
            self.assertNotIn("password", text.lower())
            self.assertNotIn(SENTINEL, text)
            self.assertEqual(len(json.loads(text)["connections"]), 1)


class PasswordIsNeverEchoed(unittest.TestCase):
    def test_failed_connect_does_not_echo_the_password(self):
        with local_server(connections=[DEAD_CONNECTION]) as harness:
            client = harness.client
            response = client.post(CONNECTION_URL + "/connect", {"password": SENTINEL})
            self.assertNotEqual(response.status, 200, response)
            self.assertNotIn(SENTINEL, response.raw.decode("utf-8"))
            for path in (
                "/api/health",
                "/api/session",
                "/api/connections",
                CONNECTION_URL,
                CONNECTION_URL + "/status",
                CONNECTION_URL + "/host-keys",
                "/",
                "/assets/js/connections.js",
            ):
                with self.subTest(path=path):
                    scanned = client.get(path)
                    self.assertNotIn(
                        SENTINEL, scanned.raw.decode("utf-8", errors="replace"), path
                    )

    def test_ssh_argv_and_environment_carry_no_password(self):
        target = SshTarget(host="127.0.0.1", port=2222, username="aimu")
        command = build_sftp_command(
            target,
            ssh_executable=find_ssh_executable(""),
            known_hosts_file="data/known_hosts",
            host_key_policy="strict",
            connect_timeout=10,
            keepalive_interval=30,
            use_password=True,
        )
        self.assertNotIn(SENTINEL, " ".join(command))

        bundle = prepare_askpass(SENTINEL)
        secret_path = Path(bundle.payload[ASKPASS_FILE_ENV])
        try:
            env = build_environment(
                None, askpass_command=bundle.command, askpass_payload=bundle.payload
            )
            for key, value in env.items():
                self.assertNotIn(SENTINEL, str(value), key)
            self.assertEqual(env["SSH_ASKPASS"], bundle.command)
            self.assertEqual(env["SSH_ASKPASS_REQUIRE"], "force")
            # 密码**只**存在于 askpass 的临时文件里，而那个文件是可销毁的。
            self.assertEqual(secret_path.read_text(encoding="utf-8"), SENTINEL)
            self.assertTrue(Path(bundle.command).is_file())
        finally:
            bundle.cleanup()
        self.assertFalse(secret_path.exists(), "认证结束后密码文件必须被销毁")
        self.assertFalse(Path(bundle.command).exists())


class LoggingRedactionTests(unittest.TestCase):
    """日志必须脱敏：即使调用点疏忽，也不该有密码落盘（§10.6）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="awfm-log-")
        reset_for_tests()
        setup_logging(self._tmp.name, level="DEBUG", to_stderr=False)

    def tearDown(self):
        reset_for_tests()
        self._tmp.cleanup()

    def _log_text(self) -> str:
        path = Path(self._tmp.name) / "awfm.log"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def test_password_and_key_path_never_reach_the_log_file(self):
        logger = logging.getLogger("awfm.test")
        logger.info("连接参数 password=%s", SENTINEL)
        logger.info('{"api_key": "%s"}', SENTINEL)
        logger.info("ssh -i /home/aimu/.ssh/%s ...", KEY_MARKER)
        text = self._log_text()
        self.assertNotIn(SENTINEL, text)
        self.assertNotIn(KEY_MARKER, text)
        self.assertIn(PLACEHOLDER, text)

    def test_a_real_failed_connect_leaves_no_password_in_the_log(self):
        with local_server(connections=[DEAD_CONNECTION]) as harness:
            harness.client.post(CONNECTION_URL + "/connect", {"password": SENTINEL})
        text = self._log_text()
        self.assertTrue(text, "一次连接尝试至少应该留下一条日志")
        self.assertNotIn(SENTINEL, text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
