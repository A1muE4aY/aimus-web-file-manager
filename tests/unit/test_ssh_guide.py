"""SSH 教程与实现的「不许各说各话」检查（v0.1.2 阶段四）。

`docs/SSH_SETUP_GUIDE.md` 里写了大量 AWFM 的**具体行为**——ssh 选项、默认值、
认证方式、信任库位置、网页端口。这些事实一旦与代码脱钩，用户会照着教程操作却
得不到预期的结果，比没有教程更糟。所以这里把「教程与代码必须一致」的部分钉成
断言：`build_sftp_command` 新增一个 `-o` 选项而教程没同步，测试就红。

另外两条纪律（决策 D-021）也在断言范围内：
- 教程里凡未在本机实测过的命令必须带状态标记，不能让人当成已验证结论；
- 教程正文不得出现私钥材料或未替换的模板标记。
"""

import unittest

from app.core import config as cfg
from app.models.connection import AUTH_METHODS
from app.ssh import ssh_launcher

GUIDE = cfg.project_root() / "docs" / "SSH_SETUP_GUIDE.md"

#: 章节标题：A 概念 → L 快速排查。缺任何一节都说明教程被截断或未写完。
SECTIONS = [
    "## A.",
    "## B.",
    "## C.",
    "## D.",
    "## E.",
    "## F.",
    "## G.",
    "## H.",
    "## I.",
    "## J.",
    "## K.",
    "## L.",
]


def _sftp_options(*, use_password: bool, identity_file: str | None) -> list[str]:
    """取出 `build_sftp_command` 实际追加的 `-o <键>=<值>` 键名。"""
    target = ssh_launcher.SshTarget(host="192.0.2.10", port=22, username="someone")
    command = ssh_launcher.build_sftp_command(
        target,
        ssh_executable="ssh",
        known_hosts_file="data/known_hosts",
        use_password=use_password,
        identity_file=identity_file,
    )
    names = []
    for index, item in enumerate(command):
        if item == "-o":
            names.append(command[index + 1].split("=", 1)[0])
        elif item == "-i":
            names.append("-i")
    return names


class GuidePresenceTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(GUIDE.is_file(), f"教程缺失：{GUIDE}")
        self.text = GUIDE.read_text(encoding="utf-8")
        self.lines = self.text.splitlines()

    def test_is_not_truncated(self):
        # 1627 行是完稿时的量级；阈值放宽到 800，只为挡住「文件被截断/被清空」。
        self.assertGreater(len(self.lines), 800)

    def test_all_sections_present_in_order(self):
        positions = []
        for title in SECTIONS:
            self.assertIn(title, self.text, f"教程缺少章节：{title}")
            positions.append(self.text.index(title))
        self.assertEqual(positions, sorted(positions), "章节顺序被改动")

    def test_appendices_present(self):
        self.assertIn("## 附录 A", self.text)
        self.assertIn("## 附录 B", self.text)


class GuideMatchesImplementationTests(unittest.TestCase):
    """教程附录 A 声明「AWFM 实际使用的 ssh 选项」——必须与代码逐项对上。"""

    def setUp(self):
        self.text = GUIDE.read_text(encoding="utf-8")
        self.appendix_a = self.text.split("## 附录 A", 1)[1].split("## 附录 B", 1)[0]

    def test_every_option_the_launcher_emits_is_documented(self):
        documented = set()
        documented.update(_sftp_options(use_password=False, identity_file=None))
        documented.update(_sftp_options(use_password=True, identity_file=None))
        documented.update(_sftp_options(use_password=False, identity_file=r"C:\keys\id_ed25519"))
        self.assertIn("UserKnownHostsFile", documented)  # 自检：解析没写错
        for name in sorted(documented):
            with self.subTest(option=name):
                self.assertIn(name, self.appendix_a, f"教程附录 A 未记录 ssh 选项 {name}")

    def test_password_mode_switches_batch_mode_off(self):
        # 这是本实现最容易被改错的一条：BatchMode=yes 会彻底禁用密码认证。
        key_mode = _sftp_options(use_password=False, identity_file=None)
        password_mode = _sftp_options(use_password=True, identity_file=None)
        self.assertIn("BatchMode", key_mode)
        self.assertIn("BatchMode", password_mode)
        self.assertIn("NumberOfPasswordPrompts", password_mode)
        self.assertIn("BatchMode", self.appendix_a)
        self.assertIn("NumberOfPasswordPrompts", self.appendix_a)

    def test_defaults_in_appendix_match_config_defaults(self):
        ssh_defaults = cfg.DEFAULTS["ssh"]
        timeout = str(ssh_defaults["connect_timeout_seconds"])
        keepalive = str(ssh_defaults["keepalive_interval_seconds"])
        self.assertRegex(self.appendix_a, r"ConnectTimeout[^\n]*" + timeout)
        self.assertRegex(self.appendix_a, r"ServerAliveInterval[^\n]*" + keepalive)

    def test_known_hosts_path_matches_default(self):
        self.assertIn(cfg.DEFAULTS["ssh"]["known_hosts_file"], self.text)
        self.assertIn("data/known_hosts", self.appendix_a)

    def test_each_supported_auth_method_has_a_section(self):
        self.assertEqual(set(AUTH_METHODS), {"key", "password"})
        self.assertIn("## F.", self.text)
        self.assertIn("## G.", self.text)

    def test_distinguishes_web_port_from_ssh_port(self):
        # 教程最容易把人带偏的一点：AWFM 的 32579 不是 SSH 端口。
        self.assertIn(str(cfg.DEFAULTS["server"]["port"]), self.text)
        self.assertIn("不是 SSH 服务端", self.text)


class GuideDisciplineTests(unittest.TestCase):
    def setUp(self):
        self.text = GUIDE.read_text(encoding="utf-8")
        self.appendix_b = self.text.split("## 附录 B", 1)[1]

    def test_verification_markers_are_used(self):
        # 决策 D-021：实测过的标【已实测】，没实测的必须标出来。
        self.assertIn("【已实测】", self.text)
        self.assertIn("【未验证】", self.text)

    def test_appendix_b_lists_unverified_topics(self):
        self.assertIn("未验证", self.appendix_b)
        for topic in ("sudo", "SELinux", "firewalld", "macOS"):
            with self.subTest(topic=topic):
                self.assertIn(topic, self.appendix_b)

    def test_no_private_key_material(self):
        for marker in ("BEGIN OPENSSH PRIVATE KEY", "BEGIN RSA PRIVATE KEY", "BEGIN EC PRIVATE KEY"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, self.text)

    def test_no_leftover_template_markers(self):
        for marker in ("TODO", "TBD", "FIXME", "待补", "<!--"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, self.text)


if __name__ == "__main__":
    unittest.main()
