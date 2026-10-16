"""统一启动器 scripts/launcher.py 的单元测试。

这里只测纯函数与解析路径：不启动服务、不绑定端口、不碰真实 PID 文件。
真实的启动 / 停止生命周期在 tests/integration/test_launcher_lifecycle.py 里用子进程验证。
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_launcher():
    """按文件路径导入 scripts/launcher.py（它不是包，只能用 spec 加载）。"""
    spec = importlib.util.spec_from_file_location("awfm_launcher", ROOT / "scripts" / "launcher.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("找不到 scripts/launcher.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


launcher = _load_launcher()


def quiet(func, *args, **kwargs):
    """吞掉输出：被测函数本来就是写给终端看的。"""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return func(*args, **kwargs)


class DefaultsTest(unittest.TestCase):
    def test_default_port_is_32579(self):
        # 任务书 §3.6：v0.1.2 的默认端口从 8760 改成 32579，这里钉住常量。
        self.assertEqual(launcher.DEFAULT_PORT, 32579)

    def test_parser_defaults(self):
        args = launcher.build_parser().parse_args([])
        self.assertEqual(args.command, "menu")
        self.assertIsNone(args.timeout)
        self.assertEqual(args.lines, launcher.DEFAULT_LOG_LINES)
        self.assertEqual(Path(args.pid_file), launcher.DEFAULT_PID_FILE)
        self.assertEqual(Path(args.console_log), launcher.DEFAULT_CONSOLE_LOG)
        self.assertEqual(args.log_file, "")
        self.assertFalse(args.force)
        self.assertFalse(args.yes)

    def test_parser_accepts_start_options(self):
        args = launcher.build_parser().parse_args(["start", "--port", "9000", "--no-browser"])
        self.assertEqual(args.command, "start")
        self.assertEqual(args.port, 9000)
        self.assertTrue(args.no_browser)

    def test_unknown_command_is_usage_error(self):
        with self.assertRaises(SystemExit) as caught:
            quiet(launcher.build_parser().parse_args, ["bogus"])
        self.assertEqual(caught.exception.code, launcher.EXIT_USAGE)

    def test_help_returns_ok(self):
        self.assertEqual(quiet(launcher.main, ["help"]), launcher.EXIT_OK)

    def test_negative_lines_is_usage_error(self):
        self.assertEqual(quiet(launcher.main, ["logs", "-n", "-1"]), launcher.EXIT_USAGE)


class ProcessTest(unittest.TestCase):
    def test_current_process_looks_like_python(self):
        # 停止闸门依赖这个判断：只有映像名带 python 才肯停。
        image = launcher.process_image_name(os.getpid())
        self.assertTrue(image, "当前进程的映像名读不出来：" + image)
        if image != "unknown":
            self.assertTrue(launcher.looks_like_python(image), image)

    def test_invalid_pid_is_not_alive(self):
        self.assertEqual(launcher.process_image_name(0), "")
        self.assertFalse(launcher.process_alive(0))

    def test_looks_like_python_matrix(self):
        self.assertTrue(launcher.looks_like_python("python.exe"))
        self.assertTrue(launcher.looks_like_python("python3"))
        self.assertTrue(launcher.looks_like_python("Python3.12"))
        self.assertFalse(launcher.looks_like_python("sshd"))
        self.assertFalse(launcher.looks_like_python(""))
        self.assertFalse(launcher.looks_like_python("cmd.exe"))


class PidFileTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="awfm-launcher-")
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "nested" / "awfm.pid"

    def test_roundtrip(self):
        payload = {"pid": 4321, "host": "127.0.0.1", "port": 32579, "url": "http://127.0.0.1:32579/"}
        launcher.write_pid_file(self.path, payload)
        loaded = launcher.read_pid_file(self.path)
        self.assertEqual(loaded["pid"], 4321)
        self.assertEqual(loaded["port"], 32579)
        # 不能留下 .tmp 中转文件
        self.assertFalse(self.path.with_name(self.path.name + ".tmp").exists())

    def test_missing_file_is_empty_dict(self):
        self.assertEqual(launcher.read_pid_file(Path(self._tmp.name) / "nope.pid"), {})

    def test_corrupt_file_is_treated_as_stale(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{ not json", encoding="utf-8")
        self.assertEqual(launcher.read_pid_file(self.path), {"note": "内容无法解析"})

    def test_non_object_is_treated_as_stale(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(launcher.read_pid_file(self.path), {"note": "内容不是一个 JSON 对象"})

    def test_garbage_pid_becomes_zero(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"pid": "abc"}), encoding="utf-8")
        self.assertEqual(launcher.read_pid_file(self.path)["pid"], 0)

    def test_remove_is_idempotent(self):
        launcher.write_pid_file(self.path, {"pid": 1})
        launcher.remove_pid_file(self.path)
        launcher.remove_pid_file(self.path)
        self.assertFalse(self.path.exists())


class TailTextTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="awfm-launcher-")
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "console.log"

    def test_keeps_last_lines(self):
        self.path.write_text("\n".join("line-" + str(index) for index in range(1, 6)) + "\n", encoding="utf-8")
        self.assertEqual(launcher.tail_text(self.path, 2), "line-4\nline-5")

    def test_zero_or_negative_lines_returns_everything(self):
        self.path.write_text("a\nb\n", encoding="utf-8")
        self.assertEqual(launcher.tail_text(self.path, 0), "a\nb")

    def test_missing_file_is_empty(self):
        self.assertEqual(launcher.tail_text(Path(self._tmp.name) / "nope.log", 5), "")


class StateTextTest(unittest.TestCase):
    def _state(self, **overrides):
        state = {
            "stored": {}, "pid": 0, "host": "127.0.0.1", "port": 32579,
            "url": "http://127.0.0.1:32579/", "alive": False, "health": {},
            "running": False, "stale": False,
        }
        state.update(overrides)
        return state

    def test_running_mentions_pid_url_and_version(self):
        text = launcher.describe_state(self._state(pid=99, alive=True, running=True, health={"version": "0.1.2"}))
        self.assertIn("运行中", text)
        self.assertIn("99", text)
        self.assertIn("http://127.0.0.1:32579/", text)
        self.assertIn("0.1.2", text)

    def test_alive_but_unhealthy_is_not_reported_as_running(self):
        text = launcher.describe_state(self._state(pid=99, alive=True))
        self.assertIn("健康检查没有通过", text)
        self.assertNotIn("运行中", text)

    def test_stale_pid_file_is_named(self):
        text = launcher.describe_state(self._state(pid=77, stale=True))
        self.assertIn("没有运行", text)
        self.assertIn("77", text)

    def test_idle_state(self):
        self.assertEqual(launcher.describe_state(self._state()), "没有运行")


class AddressTest(unittest.TestCase):
    def test_service_url(self):
        self.assertEqual(launcher.service_url("127.0.0.1", 32579), "http://127.0.0.1:32579/")

    def test_service_url_wraps_ipv6(self):
        self.assertEqual(launcher.url_host("::1"), "[::1]")
        self.assertEqual(launcher.url_host("127.0.0.1"), "127.0.0.1")
        self.assertEqual(launcher.service_url("::1", 32579), "http://[::1]:32579/")

    def test_connect_host_maps_wildcards_to_loopback(self):
        self.assertEqual(launcher.connect_host("0.0.0.0"), "127.0.0.1")
        self.assertEqual(launcher.connect_host("::"), "127.0.0.1")
        self.assertEqual(launcher.connect_host("[::1]"), "::1")
        self.assertEqual(launcher.connect_host("192.168.170.1"), "192.168.170.1")

    def test_free_port_is_not_open(self):
        # 端口探测本身：选一个几乎不可能有服务的高位端口。
        self.assertFalse(launcher.port_busy("127.0.0.1", 1, timeout=0.2))


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="awfm-launcher-")
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _write_config(self, payload, name="config.json"):
        path = self.dir / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_explicit_missing_config_is_human_readable(self):
        with self.assertRaises(launcher.LauncherError) as caught:
            launcher.load_settings(str(self.dir / "missing.json"))
        self.assertIn("指定的配置文件不存在", caught.exception.message)
        self.assertTrue(caught.exception.hint)

    def test_corrupt_config_is_human_readable(self):
        path = self.dir / "broken.json"
        path.write_text("{ this is not json", encoding="utf-8")
        with self.assertRaises(launcher.LauncherError) as caught:
            launcher.load_settings(str(path))
        self.assertIn("配置文件无法使用", caught.exception.message)

    def test_settings_come_from_config(self):
        path = self._write_config({"config_version": 1, "server": {"host": "127.0.0.1", "port": 32579}})
        settings = launcher.load_settings(str(path))
        self.assertEqual(settings["port"], 32579)
        self.assertEqual(settings["url"], "http://127.0.0.1:32579/")
        self.assertTrue(settings["config_exists"])
        self.assertTrue(Path(settings["logs_dir"]).is_absolute())
        self.assertTrue(Path(settings["data_dir"]).is_absolute())

    def test_port_override_wins(self):
        path = self._write_config({"config_version": 1, "server": {"host": "127.0.0.1", "port": 32579}})
        settings = launcher.load_settings(str(path), 41234)
        self.assertEqual(settings["port"], 41234)
        self.assertEqual(settings["url"], "http://127.0.0.1:41234/")

    def test_port_override_out_of_range(self):
        path = self._write_config({"config_version": 1, "server": {"host": "127.0.0.1", "port": 32579}})
        with self.assertRaises(launcher.LauncherError) as caught:
            launcher.load_settings(str(path), 70000)
        self.assertIn("1..65535", caught.exception.message)
        with self.assertRaises(launcher.LauncherError):
            launcher.load_settings(str(path), 0)


class BuildArgvTest(unittest.TestCase):
    """给 app/main.py 拼命令行。

    回归：data/config.json 不存在时必须**不带** --config —— 显式指向缺失的配置文件会让
    程序直接报错退出（「指定的配置文件不存在」），而首次运行本来就该走内置默认值。
    真实验收里首次 run.bat start 起不来就是踩了这一条。
    """

    def _settings(self, **overrides):
        settings = {
            "host": "127.0.0.1",
            "port": 32579,
            "config_path": str(ROOT / "data" / "config.json"),
            "config_exists": True,
            "logs_dir": ROOT / "logs",
            "data_dir": ROOT / "data",
        }
        settings.update(overrides)
        return settings

    def test_existing_config_is_passed_to_app(self):
        argv = launcher.build_argv(self._settings(), ["--no-browser"])
        self.assertIn("--config", argv)
        self.assertEqual(argv[argv.index("--config") + 1], str(ROOT / "data" / "config.json"))

    def test_missing_config_is_not_forced_on_the_app(self):
        argv = launcher.build_argv(self._settings(config_exists=False), ["--no-browser"])
        self.assertNotIn("--config", argv)

    def test_port_override_and_extra_args_are_forwarded(self):
        argv = launcher.build_argv(self._settings(config_exists=False, port=41234), ["--no-browser", "--log-level", "DEBUG"])
        self.assertIn("41234", argv)
        self.assertTrue(argv[-2:] == ["--log-level", "DEBUG"])
        self.assertEqual(argv[1], "-u")  # 不缓冲，后台日志才能实时反映启动过程

    def test_argv_targets_repo_app_entry(self):
        argv = launcher.build_argv(self._settings(), [])
        self.assertEqual(argv[0], sys.executable)
        self.assertEqual(argv[2], str(ROOT / "app" / "main.py"))


class EnvironmentTest(unittest.TestCase):
    def test_python_is_new_enough(self):
        version = launcher.check_python()
        self.assertTrue(version.startswith("3."))

    def test_missing_ssh_executable_is_reported(self):
        self.assertEqual(launcher.find_ssh_client("awfm-no-such-ssh-binary"), "")

    def test_ensure_writable_dir_reports_launcher_error(self):
        with tempfile.TemporaryDirectory(prefix="awfm-launcher-") as tmp:
            blocker = Path(tmp) / "blocker"
            blocker.write_text("x", encoding="utf-8")
            with self.assertRaises(launcher.LauncherError) as caught:
                launcher.ensure_writable_dir(blocker / "child", "数据目录")
            self.assertIn("数据目录不可写", caught.exception.message)


class SignalTest(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "Windows 没有可用的 SIGTERM 语义")
    def test_serve_installs_sigterm_handler(self):
        # run.sh stop 走 SIGTERM → app/main.py 把它变成 KeyboardInterrupt，
        # 从而复用 _serve 的 finally 清理（验收项 T-013：不留孤儿 ssh）。
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from app import main as app_main

        previous = signal.getsignal(signal.SIGTERM)
        try:
            app_main._install_signal_handlers()
            handler = signal.getsignal(signal.SIGTERM)
            self.assertTrue(callable(handler))
            with self.assertRaises(KeyboardInterrupt):
                handler(signal.SIGTERM, None)
        finally:
            signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    unittest.main()
