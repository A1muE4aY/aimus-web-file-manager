"""ssh 命令行构造。这里每一条选项都对应一个已发生过的真实故障。"""

import unittest

from app.core.errors import ConfigError
from app.ssh import ssh_launcher as launcher


class ExecutableTests(unittest.TestCase):
    def test_finds_ssh(self):
        path = launcher.find_ssh_executable()
        self.assertTrue(path)
        self.assertIn("ssh", path.lower())

    def test_explicit_config_is_used_verbatim(self):
        found = launcher.find_ssh_executable()
        self.assertEqual(launcher.find_ssh_executable(found), found)

    def test_missing_explicit_config_raises_instead_of_falling_back(self):
        # 静默回退会让用户以为跑的是自己指定的 ssh —— 安全假设不再成立。
        with self.assertRaises(ConfigError):
            launcher.find_ssh_executable(r"Z:\definitely\not\here\ssh.exe")


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.target = launcher.SshTarget(host="127.0.0.1", port=2222, username="aimu")
        self.base = dict(
            ssh_executable="ssh",
            known_hosts_file=r"C:\proj\data\known_hosts",
            connect_timeout=15,
            keepalive_interval=30,
        )

    def command(self, **overrides):
        return launcher.build_sftp_command(self.target, **{**self.base, **overrides})

    def test_uses_sftp_subsystem(self):
        command = self.command()
        self.assertEqual(command[-2:], ["-s", "sftp"])
        self.assertEqual(command[0], "ssh")
        self.assertEqual(command[-3], "aimu@127.0.0.1")
        self.assertIn("-p", command)
        self.assertEqual(command[command.index("-p") + 1], "2222")

    def test_strict_policy_is_translated_to_yes(self):
        # 内部策略名 strict 不是 ssh 的合法取值，直接透传会让 ssh 在解析命令行时就退出
        # （现象是「连不上」，与协议层无关）。
        command = self.command(host_key_policy="strict")
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertNotIn("StrictHostKeyChecking=strict", command)

    def test_accept_new_is_translated(self):
        self.assertIn("StrictHostKeyChecking=accept-new", self.command(host_key_policy="accept-new"))

    def test_unknown_policy_rejected(self):
        with self.assertRaises(ConfigError):
            self.command(host_key_policy="off")

    def test_project_known_hosts_replaces_both_files(self):
        # 只覆盖 UserKnownHostsFile 时，用户 ~/.ssh/known_hosts 里的旧记录会让
        # 「首次确认」被跳过（D-010 的意图落空）。
        command = self.command()
        self.assertIn(r"UserKnownHostsFile=C:\proj\data\known_hosts", command)
        self.assertIn(r"GlobalKnownHostsFile=C:\proj\data\known_hosts", command)

    def test_key_mode_batch_mode_and_publickey_only(self):
        command = self.command(use_password=False)
        self.assertIn("BatchMode=yes", command)
        self.assertIn("PreferredAuthentications=publickey", command)

    def test_password_mode_enables_prompts(self):
        # BatchMode=yes 会让 OpenSSH 直接摘掉 password 认证方法（auth2-passwd.c 的
        # userauth_passwd() 开头就是 if (options.batch_mode) return 0;）。
        command = self.command(use_password=True)
        self.assertIn("BatchMode=no", command)
        self.assertIn("NumberOfPasswordPrompts=1", command)
        self.assertNotIn("BatchMode=yes", command)
        methods = [c for c in command if c.startswith("PreferredAuthentications=")][0]
        self.assertIn("password", methods)
        self.assertIn("keyboard-interactive", methods)

    def test_identity_file_locks_identity(self):
        # 不锁身份时 ssh 会先试 agent 里其它密钥，有登录次数限制的目标机会被锁号。
        command = self.command(identity_file=r"C:\keys\id_ed25519")
        self.assertIn(r"C:\keys\id_ed25519", command)
        self.assertIn("IdentitiesOnly=yes", command)
        self.assertIn("-i", command)

    def test_no_identity_options_without_file(self):
        command = self.command()
        self.assertNotIn("-i", command)
        self.assertNotIn("IdentitiesOnly=yes", command)

    def test_timeouts_present(self):
        command = self.command()
        self.assertIn("ConnectTimeout=15", command)
        self.assertIn("ServerAliveInterval=30", command)
        self.assertIn("ServerAliveCountMax=3", command)

    def test_quiet_by_default(self):
        self.assertIn("LogLevel=ERROR", self.command())

    def test_no_shell_interpolation(self):
        # 命令必须是列表，由 subprocess 直接 exec，不经过 shell。
        self.assertIsInstance(self.command(), list)
        self.assertTrue(all(isinstance(part, str) for part in self.command()))


class EnvironmentTests(unittest.TestCase):
    def test_askpass_is_forced(self):
        env = launcher.build_environment({}, askpass_command="C:/tmp/askpass.cmd")
        # 不加 SSH_ASKPASS_REQUIRE=force 时，ssh 在有终端的情况下会忽略 askpass。
        self.assertEqual(env["SSH_ASKPASS"], "C:/tmp/askpass.cmd")
        self.assertEqual(env["SSH_ASKPASS_REQUIRE"], "force")
        self.assertTrue(env.get("DISPLAY"))

    def test_utf8_is_pinned(self):
        # 决策 D-013：Windows 默认代码页会让中文路径解密失败。
        self.assertEqual(launcher.build_environment({})["PYTHONUTF8"], "1")

    def test_password_never_travels_in_environment(self):
        env = launcher.build_environment({}, askpass_command="x.cmd", askpass_payload={"AWFM_ASKPASS_FILE": "C:/tmp/secret"})
        self.assertNotIn("hunter2", str(env))
        self.assertEqual(env["AWFM_ASKPASS_FILE"], "C:/tmp/secret")

    def test_askpass_variables_are_dropped_when_unused(self):
        # 继承来的 askpass 会被 ssh 当作真的辅助程序去执行：轻则认证行为莫名改变，
        # 重则它等待输入而把连接挂死。不用 askpass 时必须摘掉。
        env = launcher.build_environment({"SSH_ASKPASS": "old", "SSH_ASKPASS_REQUIRE": "old", "DISPLAY": "old"})
        self.assertNotIn("SSH_ASKPASS", env)
        self.assertNotIn("SSH_ASKPASS_REQUIRE", env)
        self.assertEqual(env["DISPLAY"], "old")  # 与 askpass 无关的变量原样保留


class TargetTests(unittest.TestCase):
    def test_destination(self):
        self.assertEqual(launcher.SshTarget("h", 22, "u").destination, "u@h")
        self.assertEqual(launcher.SshTarget("h", 22, "").destination, "h")


if __name__ == "__main__":
    unittest.main()
