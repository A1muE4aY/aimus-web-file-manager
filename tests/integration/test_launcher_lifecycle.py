"""统一启动器的真实生命周期测试（子进程，不是线程内服务）。

run.bat / run.sh 只是外壳，真正干活的是 scripts/launcher.py。这里的每个用例
都真的把服务当子进程起起来，因为「会不会起第二个实例」「停止是否干净」「端口冲突
怎么报」这几件事只有在真实进程上才验证得了。
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.integration import support

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts" / "launcher.py"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_STATE = 3


def run_launcher(*args: str, timeout: float = 90.0, cwd: str | None = None):
    """跑一次启动器，返回 (退出码, 输出)。stdin 是管道，所以不会进交互菜单。

    cwd 默认项目根；传别的目录用来验证「从不同工作目录执行脚本」——启动器的 ROOT 由
    __file__ 推导，不该依赖调用者的当前目录。
    """
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, str(LAUNCHER), *args],
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=environment,
    )
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


class LauncherLifecycleTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="awfm-launcher-it-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.port = support.free_port()
        self.config = self.root / "config.json"
        self.config.write_text(
            json.dumps(self._config_payload(self.port), ensure_ascii=False), encoding="utf-8"
        )
        self.pid_file = self.root / "awfm.pid"
        self.console = self.root / "console.log"

    @staticmethod
    def _config_payload(port: int) -> dict:
        # open_browser 显式关掉：测试不该在别人桌面上弹浏览器。
        return {
            "config_version": 1,
            "server": {"host": "127.0.0.1", "port": port, "open_browser": False},
            "connections": [],
        }

    def _run(self, *args: str, timeout: float = 90.0):
        return run_launcher(
            *args,
            "--config", str(self.config),
            "--pid-file", str(self.pid_file),
            "--console-log", str(self.console),
            timeout=timeout,
        )

    def _read_pid_file(self) -> dict:
        return json.loads(self.pid_file.read_text(encoding="utf-8"))

    def _wait_closed(self, timeout: float = 15.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not support.port_open("127.0.0.1", self.port):
                return True
            time.sleep(0.2)
        return not support.port_open("127.0.0.1", self.port)

    def tearDown(self):
        # 断言失败也不能把服务留在机器上。
        if self.pid_file.exists():
            run_launcher(
                "stop", "--force", "--yes",
                "--config", str(self.config), "--pid-file", str(self.pid_file),
                "--console-log", str(self.console), timeout=60.0,
            )

    def test_full_lifecycle(self):
        # 0) 自检：不启动任何东西，只报告环境（Windows 缺 ssh 客户端时会如实报失败，但不出 traceback）
        code, out = self._run("check", timeout=60.0)
        self.assertNotIn("Traceback", out, out)
        self.assertIn("Python", out, out)

        # 1) 启动：健康检查通过才允许报成功
        code, out = self._run("start", "--no-browser", timeout=60.0)
        self.assertEqual(code, EXIT_OK, out)
        self.assertIn("已启动", out)
        self.assertTrue(support.port_open("127.0.0.1", self.port), "启动成功后端口应当可连")
        payload = self._read_pid_file()
        self.assertGreater(payload["pid"], 0)
        self.assertEqual(payload["port"], self.port)
        self.assertEqual(payload["url"], "http://127.0.0.1:" + str(self.port) + "/")
        started_pid = payload["pid"]
        self.assertTrue(self.console.exists(), "后台运行应当把控制台输出写进日志文件")

        # 2) 重复启动：拒绝起第二个实例，PID 不变
        code, out = self._run("start", "--no-browser", timeout=40.0)
        self.assertEqual(code, EXIT_STATE, out)
        self.assertIn("已经在运行", out)
        self.assertEqual(self._read_pid_file()["pid"], started_pid, "重复 start 不该换进程")

        # 3) 状态：报告运行中与实际地址
        code, out = self._run("status")
        self.assertEqual(code, EXIT_OK, out)
        self.assertIn("运行中", out)
        self.assertIn(str(self.port), out)

        # 4) 日志：能看到后台进程的输出
        code, out = self._run("logs", "--log-file", str(self.console), "-n", "20")
        self.assertEqual(code, EXIT_OK, out)
        self.assertIn("AWFM", out)

        # 5) 不带确认的 stop：任务书要求「不得未经确认就强制终止」
        code, out = self._run("stop", timeout=40.0)
        if code == EXIT_OK:
            self.assertFalse(support.port_open("127.0.0.1", self.port), out)
        else:
            self.assertEqual(code, EXIT_FAILED, out)
            self.assertIn("已放弃", out)
            self.assertTrue(support.port_open("127.0.0.1", self.port), "没有确认就不该强制终止进程")

        # 6) 显式确认的强制停止：进程消失、端口释放、PID 文件清理
        code, out = self._run("stop", "--force", "--yes", timeout=40.0)
        self.assertIn(code, (EXIT_OK, EXIT_STATE), out)
        self.assertTrue(self._wait_closed(), "停止之后端口应当释放：" + out)
        self.assertFalse(self.pid_file.exists(), "停止之后不该留下 PID 文件")

        # 7) 再停一次：如实报告没在运行（且什么都没做），而不是谎报成功
        code, out = self._run("stop", timeout=30.0)
        self.assertEqual(code, EXIT_STATE, out)
        self.assertIn("没有在运行", out)
        self.assertIn("什么都没做", out)

        # 8) restart 能从停止状态重新起来
        code, out = self._run("restart", "--force", "--yes", "--no-browser", timeout=60.0)
        self.assertEqual(code, EXIT_OK, out)
        self.assertTrue(support.port_open("127.0.0.1", self.port), out)
        code, out = self._run("stop", "--force", "--yes", timeout=40.0)
        self.assertEqual(code, EXIT_OK, out)
        self.assertTrue(self._wait_closed(), out)

    def test_port_conflict_is_refused(self):
        occupied = support.free_port()
        conflict_config = self.root / "conflict.json"
        conflict_config.write_text(
            json.dumps(self._config_payload(occupied), ensure_ascii=False), encoding="utf-8"
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", occupied))
            sock.listen(1)
            code, out = run_launcher(
                "start", "--no-browser",
                "--config", str(conflict_config),
                "--pid-file", str(self.pid_file),
                "--console-log", str(self.console),
                timeout=60.0,
            )
        self.assertEqual(code, EXIT_FAILED, out)
        self.assertIn("已经被占用", out)
        self.assertNotIn("Traceback", out, out)
        self.assertFalse(self.pid_file.exists(), "端口冲突时不该留下 PID 文件")

    def test_stale_pid_file_is_reported_and_replaced(self):
        finished = subprocess.Popen([sys.executable, "-c", "pass"])
        finished.wait()
        dead_pid = finished.pid
        self.pid_file.write_text(
            json.dumps({"pid": dead_pid, "host": "127.0.0.1", "port": self.port}), encoding="utf-8"
        )

        # 陈旧 PID 文件：状态如实说明那个 PID 已经不存在
        code, out = self._run("status")
        self.assertEqual(code, EXIT_STATE, out)
        self.assertIn("没有运行", out)
        self.assertIn(str(dead_pid), out)

        # start 会先清理陈旧文件再启动
        code, out = self._run("start", "--no-browser", timeout=60.0)
        self.assertEqual(code, EXIT_OK, out)
        self.assertNotEqual(self._read_pid_file()["pid"], dead_pid)
        code, out = self._run("stop", "--force", "--yes", timeout=40.0)
        self.assertEqual(code, EXIT_OK, out)

    def test_stop_does_not_touch_unrelated_processes(self):
        """任务书 §5.2「停止操作是否只影响 AWFM 管理的进程」。

        旁边放一个同样是 python 的无关进程：如果停止逻辑按映像名或端口扫射，它就会一起死。
        """
        decoy = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(180)"])
        self.addCleanup(decoy.kill)
        try:
            # 没在跑时 stop 什么都不该做
            code, out = self._run("stop", "--force", "--yes", timeout=40.0)
            self.assertEqual(code, EXIT_STATE, out)
            self.assertIsNone(decoy.poll(), "AWFM 没在运行时，停止不该动任何无关进程")

            # AWFM 在跑时也只停 PID 文件里那一个进程
            code, out = self._run("start", "--no-browser", timeout=60.0)
            self.assertEqual(code, EXIT_OK, out)
            self.assertTrue(support.port_open("127.0.0.1", self.port), out)
            code, out = self._run("stop", "--force", "--yes", timeout=40.0)
            self.assertEqual(code, EXIT_OK, out)
            self.assertTrue(self._wait_closed(), out)
            self.assertIsNone(decoy.poll(), "停止 AWFM 不该动无关的 Python 进程")
        finally:
            if decoy.poll() is None:
                decoy.kill()
                decoy.wait(timeout=10)

    def test_menu_without_tty_returns_immediately(self):
        # 非交互（管道 / 计划任务）：给说明与状态就退出，绝不挂着等输入
        code, out = self._run("menu", timeout=30.0)
        self.assertEqual(code, EXIT_OK, out)
        self.assertIn("不是交互终端", out)
        self.assertIn("状态", out)

    def test_start_refuses_when_ssh_client_is_missing(self):
        """任务书 §5.2「OpenSSH 不存在」：缺 ssh 客户端时只能拒绝启动。

        配置里把 ssh.ssh_executable 指到一个不存在的绝对路径，这个分支以前只有函数级
        单测（find_ssh_client）覆盖，没人验证过「真的不会把服务起起来」。
        """
        config = self.root / "no-ssh-client.json"
        payload = self._config_payload(self.port)
        payload["ssh"] = {"ssh_executable": str(self.root / "awfm-no-such-ssh.exe")}
        config.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        code, out = run_launcher(
            "start", "--no-browser",
            "--config", str(config),
            "--pid-file", str(self.pid_file),
            "--console-log", str(self.console),
            timeout=60.0,
        )
        self.assertEqual(code, EXIT_FAILED, out)
        self.assertIn("找不到系统 ssh 客户端", out)
        self.assertNotIn("Traceback", out, out)
        self.assertFalse(self.pid_file.exists(), "拒绝启动时不该留下 PID 文件")
        self.assertFalse(support.port_open("127.0.0.1", self.port), "拒绝启动时端口不该被占用")

        # 自检同样要如实报告，而不是崩掉
        code, out = run_launcher(
            "check", "--config", str(config), "--pid-file", str(self.pid_file),
            "--console-log", str(self.console), timeout=60.0,
        )
        self.assertIn(code, (EXIT_OK, EXIT_FAILED), out)
        self.assertNotIn("Traceback", out, out)

    def test_corrupt_config_is_refused_with_a_readable_message(self):
        """任务书 §5.2「配置文件损坏」：给人话 + 出路，不给 traceback。"""
        broken = self.root / "broken.json"
        broken.write_text('{"config_version": 1, "server": {"port": ', encoding="utf-8")

        common = (
            "--config", str(broken),
            "--pid-file", str(self.pid_file),
            "--console-log", str(self.console),
        )

        # status 只读状态，读不到配置就降级成一句警告（退出码 3 = 状态与请求不一致）
        code, out = run_launcher("status", *common, timeout=60.0)
        self.assertEqual(code, EXIT_STATE, out)
        self.assertIn("读不到配置", out)
        self.assertIn("配置文件无法使用", out)
        self.assertNotIn("Traceback", out, out)

        # start 必须拒绝，并把「怎么修」一起说出来
        code, out = run_launcher("start", "--no-browser", *common, timeout=60.0)
        self.assertEqual(code, EXIT_FAILED, out)
        self.assertIn("配置文件无法使用", out)
        self.assertIn("--init-config", out)
        self.assertNotIn("Traceback", out, out)

        # 顺带确认「坏配置不豁免」：坏配置下也不会偷偷启动
        self.assertFalse(self.pid_file.exists())
        self.assertFalse(support.port_open("127.0.0.1", self.port))

    def test_runs_from_a_different_working_directory(self):
        """任务书 §5.2「从不同工作目录执行脚本」：路径不能锚在 cwd 上。"""
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        common = (
            "--config", str(self.config),
            "--pid-file", str(self.pid_file),
            "--console-log", str(self.console),
        )

        code, out = run_launcher("status", *common, cwd=str(elsewhere))
        self.assertEqual(code, EXIT_STATE, out)  # 没在跑
        self.assertIn("AWFM", out)
        self.assertNotIn("Traceback", out, out)

        code, out = run_launcher("check", *common, cwd=str(elsewhere), timeout=60.0)
        self.assertIn(code, (EXIT_OK, EXIT_FAILED), out)
        self.assertIn("Python", out)
        self.assertNotIn("Traceback", out, out)

        # 从无关目录启动、访问、再停掉：PID 文件与日志仍落在命令行给的路径上
        code, out = run_launcher("start", "--no-browser", *common, cwd=str(elsewhere), timeout=60.0)
        self.assertEqual(code, EXIT_OK, out)
        self.assertTrue(support.port_open("127.0.0.1", self.port), out)
        self.assertTrue(self.pid_file.exists(), "PID 文件应当写在 --pid-file 指定的位置")
        code, out = run_launcher("stop", "--force", "--yes", *common, cwd=str(elsewhere), timeout=40.0)
        self.assertEqual(code, EXIT_OK, out)
        self.assertTrue(self._wait_closed(), out)


class WrapperExitCodeTest(unittest.TestCase):
    """run.bat / run.sh 的外壳契约：找 Python、转发参数、原样传递退出码。

    外壳自己不实现任何业务逻辑，所以这里只需要 scripts/launcher.py 就能测——把三个文件
    复制到一个空目录，让 ROOT 指向它。回归点：退出码 3（「已经在跑或没在跑」）曾经在
    run.bat 里被批处理的括号块吃掉，变成 0，自动化脚本据此会误判成功。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="awfm-wrapper-it-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "scripts").mkdir()
        shutil.copy2(ROOT / "scripts" / "launcher.py", self.root / "scripts" / "launcher.py")
        for name in ("run.bat", "run.sh"):
            shutil.copy2(ROOT / name, self.root / name)

    def _run_wrapper(self, *args: str, timeout: float = 60.0, cwd: str | None = None, root: Path | None = None):
        shell_root = root or self.root
        # 用绝对路径调用外壳：这样 cwd 传给谁都行（相对路径会先按 cwd 解析，找不到文件）
        if os.name == "nt":
            argv = ["cmd", "/c", str(shell_root / "run.bat"), *args]
        else:
            argv = ["/bin/sh", str(shell_root / "run.sh"), *args]
        environment = dict(os.environ)
        environment["AWFM_NO_PAUSE"] = "1"  # 外壳出错时会 pause，自动化必须跳过
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        completed = subprocess.run(
            argv, cwd=str(cwd or self.root), capture_output=True, timeout=timeout, check=False, env=environment
        )
        text = (completed.stdout or b"").decode("utf-8", "replace") + (completed.stderr or b"").decode("utf-8", "replace")
        return completed.returncode, text

    def test_status_when_idle_returns_state_exit_code(self):
        code, out = self._run_wrapper("status", "--pid-file", "absent.pid")
        self.assertEqual(code, EXIT_STATE, out)
        self.assertIn("AWFM", out)
        self.assertNotIn("Traceback", out)

    def test_stop_when_idle_returns_state_exit_code(self):
        code, out = self._run_wrapper("stop", "--pid-file", "absent.pid")
        self.assertEqual(code, EXIT_STATE, out)
        self.assertNotIn("Traceback", out)

    def test_wrapper_runs_from_an_unrelated_working_directory(self):
        # run.bat 里的 cd /d "%~dp0" 就是为这条存在的：双击、快捷方式、别的目录调用都要找对根。
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        code, out = self._run_wrapper("status", "--pid-file", "absent.pid", cwd=str(elsewhere))
        self.assertEqual(code, EXIT_STATE, out)
        self.assertIn("AWFM", out)
        self.assertNotIn("Traceback", out)

    def test_spaces_in_the_script_path(self):
        # 任务书 §5.2「脚本路径包含空格」：把外壳搬到带空格的目录，仍要能找到同级 launcher.py。
        spaced = self.root / "accept space" / "AWFM test"
        (spaced / "scripts").mkdir(parents=True)
        shutil.copy2(ROOT / "scripts" / "launcher.py", spaced / "scripts" / "launcher.py")
        for name in ("run.bat", "run.sh"):
            shutil.copy2(ROOT / name, spaced / name)

        code, out = self._run_wrapper("status", "--pid-file", "absent.pid", root=spaced)
        self.assertEqual(code, EXIT_STATE, out)
        self.assertIn("AWFM", out)
        self.assertNotIn("Traceback", out, out)

        code, out = self._run_wrapper("check", "--pid-file", "absent.pid", root=spaced, timeout=90.0)
        self.assertIn(code, (EXIT_OK, EXIT_FAILED), out)
        self.assertNotIn("Traceback", out, out)

    def test_wrapper_forwards_arguments_and_usage_errors(self):
        code, out = self._run_wrapper("nosuchcommand")
        self.assertEqual(code, 2, out)  # argparse 用法错误
        code, out = self._run_wrapper("logs", "-n", "-1", "--pid-file", "absent.pid")
        self.assertEqual(code, 2, out)


if __name__ == "__main__":
    unittest.main()
