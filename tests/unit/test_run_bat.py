"""run.bat 的编码引导段回归测试。

背景（v0.1.2 阶段六真实桌面验收发现）：cmd.exe 按「控制台代码页」逐行读取批处理文件。
run.bat 是 UTF-8，当控制台还是默认的 GBK(936) 时，读到中文字节会把行从中间截断，后半截
被当成命令执行——用户双击后先看到一串「'...' 不是内部或外部命令」。

修法：文件开头放一段**纯 ASCII** 的引导段（此时按 GBK 读也无所谓），它把代码页切到 UTF-8、
用一个环境变量防重入，然后用子进程重新执行自己；第二遍整份文件都在 UTF-8 下读取，不会再
错位。这些断言只在字节层面钉住这个结构，不启动任何进程（真实控制台的行为在
tests/integration/test_launcher_lifecycle.py 的 WrapperExitCodeTest 里验证）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BAT = ROOT / "run.bat"
GITATTRIBUTES = ROOT / ".gitattributes"

GUARD = "if defined AWFM_UTF8_READY goto :awfm_utf8_ready"
REEXEC = '"%COMSPEC%" /c ""%~f0" %*"'
CHINESE_HEADER = "rem AWFM 统一入口（Windows）".encode("utf-8")


class BootstrapTests(unittest.TestCase):
    """引导段必须出现在任何非 ASCII 字节之前，并且只把代码页切一次。"""

    def setUp(self):
        self.raw = BAT.read_bytes()
        self.text = self.raw.decode("utf-8")  # 文件本身必须是合法 UTF-8

    def test_uses_crlf_line_endings(self):
        # .gitattributes 里 *.bat 是 eol=crlf：cmd 对 LF 结尾的 .bat 在 goto / 续行时行为不稳。
        self.assertEqual(self.raw.count(b"\n"), self.raw.count(b"\r\n"), "run.bat 必须是 CRLF")

    def test_bootstrap_block_is_pure_ascii(self):
        # 第一遍就是按控制台代码页读这段的：里面出现一个中文字节，错位照旧发生。
        prefix = self.raw[: self.raw.index(CHINESE_HEADER)]
        offenders = sorted({byte for byte in prefix if byte > 0x7F})
        self.assertEqual(offenders, [], "引导段必须保持纯 ASCII")

    def test_bootstrap_switches_code_page_and_restarts_itself_once(self):
        for marker in (
            GUARD,
            "chcp 65001 >nul 2>nul",
            'set "AWFM_UTF8_READY=1"',
            REEXEC,
            "exit /b %ERRORLEVEL%",
        ):
            self.assertIn(marker, self.text)

    def test_guard_is_checked_before_the_restart(self):
        self.assertLess(self.text.index(GUARD), self.text.index(REEXEC))

    def test_bootstrap_is_not_a_parenthesised_block(self):
        # 括号块里的 %ERRORLEVEL% 在解析时就展开，子进程的退出码会被吃成 0
        # （v0.1.2 阶段六的集成测试抓到过：status 该返回 3，实际返回 0）。
        self.assertNotIn("if not defined AWFM_UTF8_READY (", self.text)
        self.assertIn("goto :awfm_utf8_ready", self.text)

    def test_code_page_is_switched_before_the_chinese_part(self):
        self.assertLess(self.raw.index(b"chcp 65001"), self.raw.index(CHINESE_HEADER))

    def test_guard_variable_is_not_forwarded_to_the_launcher(self):
        # 用环境变量而不是命令行标记做防重入：%* 必须原样转发给 launcher.py，
        # 不能多出一个 argparse 不认识的参数。
        self.assertIn('scripts\\launcher.py" %*', self.text)

    def test_chinese_messages_survive_the_bootstrap(self):
        # 引导段是为了让中文正常显示，不是把中文删掉。
        self.assertIn("AWFM 统一入口", self.text)
        self.assertIn("[失败] 找不到 Python 解释器。", self.text)

    def test_gitattributes_keeps_bat_files_on_crlf(self):
        self.assertIn("*.bat text eol=crlf", GITATTRIBUTES.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
