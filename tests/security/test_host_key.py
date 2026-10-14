"""主机密钥验证（规划文档 §10.1、验收项 T-005）。

T-005 的要求是「主机密钥变化时不得静默接受新密钥」。拆成可断言的四件事：

1. 首次连接必须停下来要人工确认，且在确认之前信任库里不留任何记录；
2. 确认流程走通之后连接成功，信任库里出现那条记录；
3. 确认的指纹与目标机实际指纹不符时，拒绝写入；
4. 目标机密钥变了（信任库里是另一把钥匙）时连接是硬失败，
   错误里同时给出「库里的指纹」与「现在的指纹」供人比对，且**不覆盖**信任库。
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.ssh.known_hosts import collect_host_keys
from app.ssh.ssh_launcher import SshTarget, build_sftp_command, find_ssh_executable
from tests.integration.support import (
    TESTBED_HOST,
    TESTBED_PORT,
    require_testbed,
    running_server,
    testbed_connection,
    testbed_environment,
)

CONNECTION = "wsl-testbed"


def ssh_keygen() -> str:
    """ssh-keygen 的位置。测试用的「另一把钥匙」由它生成，不自己拼 base64。"""
    found = shutil.which("ssh-keygen")
    if found:
        return found
    system_root = os.environ.get("SystemRoot", "C:/Windows")
    return str(Path(system_root) / "System32" / "OpenSSH" / "ssh-keygen.exe")


def key_lines(path) -> list:
    """known_hosts 里的有效行（忽略注释与空行）。

    文件不存在 = 一个密钥都没信任过，返回空列表 —— 这正是首次连接时的状态。
    """
    file_path = Path(path)
    if not file_path.is_file():
        return []
    text = file_path.read_text(encoding="utf-8")
    return [
        line for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


class CommandNeverDisablesVerificationTests(unittest.TestCase):
    """不需要测试床：命令行里不允许出现 StrictHostKeyChecking=no。"""

    def _joined(self, policy: str) -> str:
        target = SshTarget(host=TESTBED_HOST, port=TESTBED_PORT, username="aimu")
        command = build_sftp_command(
            target,
            ssh_executable=find_ssh_executable(""),
            known_hosts_file="data/known_hosts",
            host_key_policy=policy,
            connect_timeout=10,
            keepalive_interval=30,
        )
        return " ".join(command)

    def test_strict_policy_verifies(self):
        joined = self._joined("strict")
        self.assertIn("StrictHostKeyChecking=yes", joined)
        self.assertNotIn("StrictHostKeyChecking=no", joined)

    def test_accept_new_policy_still_records_the_key(self):
        joined = self._joined("accept-new")
        self.assertIn("StrictHostKeyChecking=accept-new", joined)
        self.assertNotIn("StrictHostKeyChecking=no", joined)


@require_testbed
class HostKeyFlowTests(unittest.TestCase):
    @contextlib.contextmanager
    def _server(self, *, trust: bool = False, security=None):
        with testbed_environment(
            connections=[testbed_connection()], trust=trust, security=security
        ) as (config, keys):
            with running_server(config) as client:
                yield client, config, keys

    def test_first_connect_demands_confirmation_and_writes_nothing(self):
        with self._server() as (client, config, _keys):
            response = client.post("/api/connections/" + CONNECTION + "/connect")
            self.assertEqual(response.status, 409, response)
            self.assertEqual(response.code, "host_key_unknown", response)
            self.assertTrue(response.error.get("fingerprints"), response)
            self.assertEqual(key_lines(config.known_hosts_path), [])

    def test_confirmed_fingerprint_is_recorded_then_connect_succeeds(self):
        with self._server() as (client, config, _keys):
            first = client.post("/api/connections/" + CONNECTION + "/connect")
            self.assertEqual(first.code, "host_key_unknown", first)
            key = first.error["fingerprints"][0]
            trusted = client.post(
                "/api/connections/" + CONNECTION + "/host-keys/trust",
                {"key_type": key["key_type"], "fingerprint": key["fingerprint"]},
            )
            self.assertTrue(trusted.ok, trusted)
            listed = client.get("/api/connections/" + CONNECTION + "/host-keys")
            self.assertTrue(listed.ok, listed)
            self.assertIn(
                key["fingerprint"], [item["fingerprint"] for item in listed.data["keys"]]
            )
            self.assertTrue(key_lines(config.known_hosts_path))
            connected = client.post("/api/connections/" + CONNECTION + "/connect")
            self.assertTrue(connected.ok, connected)
            self.assertTrue(connected.data["connection"]["connected"])

    def test_a_fingerprint_that_does_not_match_is_refused(self):
        with self._server() as (client, config, _keys):
            before = key_lines(config.known_hosts_path)
            response = client.post(
                "/api/connections/" + CONNECTION + "/host-keys/trust",
                {"key_type": "ssh-ed25519", "fingerprint": "SHA256:" + "A" * 43},
            )
            self.assertFalse(response.ok, response)
            self.assertEqual(key_lines(config.known_hosts_path), before)

    def test_collecting_keys_does_not_touch_our_trust_store(self):
        with self._server() as (client, config, _keys):
            collected = collect_host_keys(
                ssh_executable=find_ssh_executable(""),
                host=TESTBED_HOST,
                port=TESTBED_PORT,
            )
            self.assertTrue(collected)
            self.assertEqual(key_lines(config.known_hosts_path), [])

    def test_a_changed_host_key_is_a_hard_failure(self):
        with self._server(trust=True) as (client, config, keys):
            self.assertTrue(keys, "测试床密钥未采集到，无法构造密钥变化场景")
            planted = self._plant_foreign_key(config.known_hosts_path)
            response = client.post("/api/connections/" + CONNECTION + "/connect")
            self.assertEqual(response.status, 409, response)
            self.assertEqual(response.code, "host_key_mismatch", response)
            self.assertTrue(response.error.get("trusted_fingerprints"), response)
            self.assertTrue(response.error.get("current_fingerprints"), response)
            # 信任库必须保持原样：错误里给的指纹是给人看的，不是让程序自己改。
            self.assertIn(
                planted.split()[1], Path(config.known_hosts_path).read_text(encoding="utf-8")
            )

    def _plant_foreign_key(self, known_hosts_path) -> str:
        """把信任库换成另一把钥匙 —— 模拟「目标机被重装」这一类密钥变化。"""
        with tempfile.TemporaryDirectory(prefix="awfm-key-") as tmp:
            key_path = Path(tmp) / "foreign"
            subprocess.run(
                [ssh_keygen(), "-t", "ed25519", "-N", "", "-q", "-f", str(key_path)],
                check=True,
                capture_output=True,
                timeout=120,
            )
            public = Path(str(key_path) + ".pub").read_text(encoding="ascii").split()
        line = "[" + TESTBED_HOST + "]:" + str(TESTBED_PORT) + " " + public[0] + " " + public[1]
        Path(known_hosts_path).write_text(line + "\n", encoding="utf-8")
        return line


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
