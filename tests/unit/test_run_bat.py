"""启动脚本外壳的回归测试：run.bat / run-advanced.bat / run.sh / run-advanced.sh。

背景（v0.1.2 阶段六真实桌面验收发现）：cmd.exe 按「控制台代码页」逐行读取批处理文件。
run.bat 是 UTF-8，当控制台还是默认的 GBK(936) 时，读到中文字节会把行从中间截断，后半截
被当成命令执行——用户双击后先看到一串「'...' 不是内部或外部命令」。

修法：文件开头放一段**纯 ASCII** 的引导段（此时按 GBK 读也无所谓），它把代码页切到 UTF-8、
用一个环境变量防重入，然后用子进程重新执行自己；第二遍整份文件都在 UTF-8 下读取，不会再
错位。这些断言只在字节层面钉住这个结构，不启动任何进程（真实控制台的行为在
tests/integration/test_launcher_lifecycle.py 的 WrapperExitCodeTest 里验证）。

v0.1.3 §5 把入口拆成两个（行为一致，只是不带参数时的默认动作不同）：

- `run.bat` / `run.sh`：**普通启动**。不带参数时什么都不补，交给 launcher 自己走 quick
  （查环境 → 起服务 → 就绪后打开默认浏览器）；带参数时原样透传。
- `run-advanced.bat` / `run-advanced.sh`：**高级启动**。不带参数时补 `menu`（交互菜单，
  端口/参数/诊断/状态/日志/停止都在里面），带参数时同样原样透传。

「不带参数补什么」这条规则只写在两份外壳里，所以必须在这里钉住：写反了，
普通用户双击一下就掉进菜单，高级用户双击 run-advanced 就直接起服务，两边都不对。
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BATS = {"run.bat": "普通启动入口", "run-advanced.bat": "高级启动入口"}
SHELLS = ("run.sh", "run-advanced.sh")
GITATTRIBUTES = ROOT / ".gitattributes"

GUARD = "if defined AWFM_UTF8_READY goto :awfm_utf8_ready"
REEXEC = '"%COMSPEC%" /c ""%~f0" %*"'
LAUNCHER = 'scripts\\launcher.py'  # Windows 外壳里的写法（反斜杠）
SH_LAUNCHER = 'scripts/launcher.py'  # POSIX 外壳里的写法（正斜杠）


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


class BatBootstrapTests(unittest.TestCase):
    """引导段必须出现在任何非 ASCII 字节之前，并且只把代码页切一次。"""

    def test_uses_crlf_line_endings(self):
        # .gitattributes 里 *.bat 是 eol=crlf：cmd 对 LF 结尾的 .bat 在 goto / 续行时行为不稳。
        for name in BATS:
            with self.subTest(name=name):
                raw = (ROOT / name).read_bytes()
                self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), name + " 必须是 CRLF")

    def test_file_is_valid_utf8(self):
        for name in BATS:
            with self.subTest(name=name):
                (ROOT / name).read_bytes().decode("utf-8")

    def test_bootstrap_block_is_pure_ascii(self):
        # 第一遍就是按控制台代码页读这段的：里面出现一个中文字节，错位照旧发生。
        for name in BATS:
            with self.subTest(name=name):
                raw = (ROOT / name).read_bytes()
                head = raw[: min(index for index, byte in enumerate(raw) if byte > 0x7F)]
                offenders = sorted({byte for byte in head if byte > 0x7F})
                self.assertEqual(offenders, [], name + " 的引导段必须保持纯 ASCII")

    def test_bootstrap_switches_code_page_and_restarts_itself_once(self):
        for name in BATS:
            text = _text(name)
            with self.subTest(name=name):
                for marker in (GUARD, "chcp 65001 >nul 2>nul", 'set "AWFM_UTF8_READY=1"', REEXEC, "exit /b %ERRORLEVEL%"):
                    self.assertIn(marker, text)

    def test_guard_is_checked_before_the_restart(self):
        for name in BATS:
            text = _text(name)
            with self.subTest(name=name):
                self.assertLess(text.index(GUARD), text.index(REEXEC))

    def test_bootstrap_is_not_a_parenthesised_block(self):
        # 括号块里的 %ERRORLEVEL% 在解析时就展开，子进程的退出码会被吃成 0
        # （v0.1.2 阶段六的集成测试抓到过：status 该返回 3，实际返回 0）。
        for name in BATS:
            text = _text(name)
            with self.subTest(name=name):
                self.assertNotIn("if not defined AWFM_UTF8_READY (", text)
                self.assertIn("goto :awfm_utf8_ready", text)

    def test_code_page_is_switched_before_the_chinese_part(self):
        for name in BATS:
            with self.subTest(name=name):
                raw = (ROOT / name).read_bytes()
                first_chinese = min(index for index, byte in enumerate(raw) if byte > 0x7F)
                self.assertLess(raw.index(b"chcp 65001"), first_chinese)

    def test_guard_variable_is_not_forwarded_to_the_launcher(self):
        # 用环境变量而不是命令行标记做防重入：%* 必须原样转发给 launcher.py，
        # 不能多出一个 argparse 不认识的参数。
        for name in BATS:
            with self.subTest(name=name):
                self.assertIn(LAUNCHER + '" %*', _text(name))

    def test_exit_code_is_taken_outside_the_parentheses(self):
        # 同样的坑：启动器的退出码必须在括号块外面取，否则自动化脚本会误判成功。
        for name in BATS:
            text = _text(name)
            with self.subTest(name=name):
                self.assertIn('set "AWFM_CODE=%ERRORLEVEL%"', text)

    def test_chinese_messages_survive_the_bootstrap(self):
        # 引导段是为了让中文正常显示，不是把中文删掉；两份外壳的头一行也要能分辨身份。
        for name, header in BATS.items():
            text = _text(name)
            with self.subTest(name=name):
                self.assertIn(header, text)
                self.assertIn("[失败] 找不到 Python 解释器。", text)

    def test_gitattributes_keeps_bat_files_on_crlf(self):
        self.assertIn("*.bat text eol=crlf", GITATTRIBUTES.read_text(encoding="utf-8"))


class EntryDefaultTests(unittest.TestCase):
    """不带参数时走哪条路：普通入口=quick（launcher 默认），高级入口=菜单。"""

    def test_plain_bat_leaves_the_default_to_the_launcher(self):
        text = _text("run.bat")
        # 普通入口不能自己补 menu —— 补了就掉进菜单，双击不再是「打开就能用」。
        self.assertNotIn(LAUNCHER + '" menu', text)
        self.assertIn(LAUNCHER + '" %*', text)

    def test_advanced_bat_falls_back_to_the_menu(self):
        text = _text("run-advanced.bat")
        self.assertIn(LAUNCHER + '" menu', text)
        self.assertIn('if not "%~1"=="" goto :awfm_with_args', text)
        self.assertIn(LAUNCHER + '" %*', text)
        # 默认动作要挂在「没有参数」那条路线上：先判空、再给默认命令，最后才是透传。
        self.assertLess(text.index('if not "%~1"=="" goto :awfm_with_args'), text.index(LAUNCHER + '" menu'))
        self.assertLess(text.index(LAUNCHER + '" menu'), text.index(LAUNCHER + '" %*'))

    def test_plain_sh_leaves_the_default_to_the_launcher(self):
        text = _text("run.sh")
        self.assertNotIn(SH_LAUNCHER + '" menu', text)
        self.assertIn('exec "$PYTHON_BIN" "$SCRIPT_DIR/' + SH_LAUNCHER + '" "$@"', text)

    def test_advanced_sh_falls_back_to_the_menu(self):
        text = _text("run-advanced.sh")
        self.assertIn('[ "$#" -eq 0 ]', text)
        self.assertIn(SH_LAUNCHER + '" menu', text)
        self.assertIn('exec "$PYTHON_BIN" "$SCRIPT_DIR/' + SH_LAUNCHER + '" "$@"', text)
        self.assertLess(text.index('[ "$#" -eq 0 ]'), text.index(SH_LAUNCHER + '" menu'))


class ShellScriptTests(unittest.TestCase):
    """两份 .sh 要能在 WSL / Linux 里直接执行：LF 行尾 + 从自身目录找 launcher。"""

    def test_shell_scripts_use_lf_and_keep_the_shebang(self):
        for name in SHELLS:
            raw = (ROOT / name).read_bytes()
            with self.subTest(name=name):
                self.assertNotIn(b"\r", raw, name + " 必须是 LF：CRLF 会让 shebang 报 \\r: command not found")
                self.assertTrue(raw.startswith(b"#!/bin/sh\n"))
                self.assertIn('cd "$SCRIPT_DIR" || exit 1', raw.decode("utf-8"))

    def test_shell_scripts_find_python_before_launching(self):
        for name in SHELLS:
            text = _text(name)
            with self.subTest(name=name):
                self.assertIn("PYTHONUTF8=1", text)
                self.assertIn("command -v", text)


if __name__ == "__main__":
    unittest.main()
