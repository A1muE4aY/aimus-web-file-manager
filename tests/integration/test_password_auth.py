"""密码认证链路（决策 D-008、待决策项 P-002）的真实链路测试。

要回答的具体问题：Windows 上没有 `#!/bin/sh`，我们生成的 `askpass.cmd` 能否被
`CreateProcess` 执行、能否把密码交给 ssh 并送达服务端。两类证据：

1. 以 ssh 相同的方式执行包装脚本（`subprocess`、`shell=False`、走 CreateProcess），
   断言标准输出**恰好是密码本身**（多一个换行都会让密码错）。
2. 让真实 ssh 用密码认证连测试床，密码故意给错值，然后读服务端 sshd 日志，
   断言这段时间里出现了一条新的「Failed password for <user>」。
   只有 askpass 真被调用、密码真被送到服务端，服务端才可能记录密码尝试。

## 测试床的已知限制（必须知道，否则会误读结果）

测试床的 sshd 是**非 root** 运行的（见 docs/DECISIONS.md 的 D-012），日志里会出现
`Could not get shadow information for aimu` —— 它读不到 `/etc/shadow`，因此密码认证
**在这个测试床上永远不可能成功**。本测试只验证客户端到服务端的密码传递链路，
不验证「正确密码能登录」（那要求以 root 安装 sshd，属于阶段 05 的真机验证）。
"""

import os
import subprocess
import tempfile
import unittest

from app.ssh.askpass import prepare_askpass
from app.ssh.ssh_launcher import (
    SshTarget,
    build_environment,
    build_sftp_command,
    find_ssh_executable,
)
from tests.integration.support import (
    TESTBED_HOST,
    TESTBED_PORT,
    TESTBED_USER,
    require_testbed,
)

#: 故意的错密码。测试只关心它是否被送达，不关心是否正确。
WRONG_PASSWORD = "awfm-not-the-real-password"

_SSHD_LOG = "/home/aimu/.awfm-testbed/sshd/var/sshd.log"


def _wsl(command: str) -> str | None:
    """在 WSL 里跑一条命令；不可用时返回 None（调用方据此跳过）。"""
    try:
        done = subprocess.run(
            ["wsl.exe", "-e", "bash", "-c", command],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout


def _sshd_log_lines() -> int | None:
    out = _wsl("wc -l < " + _SSHD_LOG)
    if out is None:
        return None
    try:
        return int(out.strip())
    except ValueError:
        return None


def _sshd_log_since(lines: int) -> list[str]:
    out = _wsl("tail -n +" + str(lines + 1) + " " + _SSHD_LOG)
    return [line for line in (out or "").splitlines() if line.strip()]


@require_testbed
class PasswordAuthTests(unittest.TestCase):
    def _bundle(self):
        bundle = prepare_askpass(WRONG_PASSWORD)
        self.addCleanup(bundle.cleanup)
        env = build_environment(
            os.environ,
            askpass_command=bundle.command,
            askpass_payload=bundle.payload,
        )
        return bundle, env

    def test_wrapper_is_executable_and_prints_the_password(self):
        """直接执行包装脚本 —— 这正是 ssh 通过 CreateProcess 做的事。"""
        bundle, env = self._bundle()
        done = subprocess.run(
            [bundle.command, TESTBED_USER + "@" + TESTBED_HOST + " password:"],
            capture_output=True, text=True, env=env, timeout=60,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        # 一个字节都不能多：ssh 只去掉一个尾随换行，多出的空格会让密码错。
        self.assertEqual(done.stdout, WRONG_PASSWORD)

    def test_ssh_delivers_the_password_to_the_server(self):
        bundle, env = self._bundle()
        before = _sshd_log_lines()
        target = SshTarget(host=TESTBED_HOST, port=TESTBED_PORT, username=TESTBED_USER)
        with tempfile.TemporaryDirectory() as tmp:
            command = build_sftp_command(
                target,
                ssh_executable=find_ssh_executable(""),
                known_hosts_file=os.path.join(tmp, "known_hosts"),
                host_key_policy="accept-new",
                connect_timeout=10,
                keepalive_interval=30,
                use_password=True,
            )
            done = subprocess.run(
                command, capture_output=True, text=True, env=env,
                stdin=subprocess.DEVNULL, timeout=120,
            )
        lowered = (done.stderr or "").lower()
        # 密码模式必须真的允许交互式认证：BatchMode=yes 会把密码方法整条摘掉。
        self.assertEqual(done.returncode, 255, done.stderr)
        self.assertIn("permission denied", lowered)
        self.assertNotIn("no askpass program specified", lowered)
        self.assertNotIn("batch mode", lowered)

        if before is None:
            self.skipTest("读不到测试床的 sshd 日志，跳过服务端证据")
        after = _sshd_log_lines()
        if after is None or after <= before:
            self.skipTest("sshd 日志没有增长，跳过服务端证据")
        fresh = _sshd_log_since(before)
        self.assertTrue(
            any(("failed password for " + TESTBED_USER) in line.lower() for line in fresh),
            "服务端没有记录到密码尝试，说明 askpass 没有把密码交给 ssh：\n" + "\n".join(fresh),
        )