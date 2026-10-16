#!/usr/bin/env python3
"""AWFM 统一启动器 —— run.bat / run.sh 背后的实际实现（v0.1.2 阶段三）。

    run.bat                  # 双击：显示交互菜单
    run.bat start            # 后台启动服务，等到健康检查通过才报成功
    run.bat status           # 查看运行状态
    run.bat stop             # 停止服务（先试优雅停止，强杀必须确认）
    run.bat restart
    run.bat logs -n 80       # 看日志尾部
    run.bat check            # 启动前自检（等价 app/main.py --check）
    run.bat --port 9000      # 省略命令 = start，兼容旧的 start.cmd --port

设计要点（对应任务书 §3.2/§3.5）：

1. 一个入口：Windows run.bat、Linux run.sh，两者都只做「找到 Python → 转交本脚本」，
   进程管理、端口检查、PID 文件、日志、菜单全部在这一个文件里，不存在两份互相矛盾的行为。
2. 后台运行 + PID 文件：data/awfm.pid 记录 pid/host/port/url/启动时间。关掉终端窗口不会
   停服务（Windows 用 DETACHED_PROCESS，POSIX 用 start_new_session）。
3. 不误杀：停止只认 PID 文件里的 pid，且先确认它确实是 python 进程；找不到 PID 文件时
   只报告、不动手。强制终止必须先得到确认（交互输入 y，或显式 --force --yes）。
4. 不谎报：start 等到 /api/health 真的返回 ok 才说启动成功；进程提前退出时把日志尾部
   贴出来并给出退出码。stop 等到进程真的消失才说停止成功。

退出码：0 成功；1 失败；2 用法/前置条件错误；3 状态与请求不符（已经在跑 / 没在跑，未改动任何东西）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_PYTHON = (3, 10)
MIN_PYTHON_TEXT = "3.10"
#: 出厂默认端口（任务书 §3.6 要求从 8760 改到 32579，避免与常用端口撞车）。
DEFAULT_PORT = 32579
DEFAULT_PID_FILE = ROOT / "data" / "awfm.pid"
DEFAULT_CONSOLE_LOG = ROOT / "logs" / "awfm-console.log"
DEFAULT_APP_LOG = ROOT / "logs" / "awfm.log"
DEFAULT_START_TIMEOUT = 20.0
DEFAULT_STOP_TIMEOUT = 10.0
DEFAULT_LOG_LINES = 40
DEFAULT_SSH_EXECUTABLE = "ssh"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_STATE = 3


# --------------------------------------------------------------------- 输出


def pin_console_encoding() -> None:
    """重定向到文件/管道时按 UTF-8 写：Windows 控制台默认 GBK，带 emoji 的文件名会直接崩（决策 D-013）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            if not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def say(text: str = "") -> None:
    print(text)


def ok(text: str) -> None:
    print("[ OK ] " + text)


def info(text: str) -> None:
    print("[信息] " + text)


def warn(text: str) -> None:
    print("[警告] " + text)


def fail(text: str) -> None:
    print("[失败] " + text)


class LauncherError(Exception):
    """带「原因 + 建议」的错误；主流程统一打印，绝不把 traceback 甩给用户。"""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


# --------------------------------------------------------------------- 进程与端口


def process_image_name(pid: int) -> str:
    """返回进程映像名（如 python.exe / python3）；进程不存在返回空串，查不动返回 unknown。"""
    if pid <= 0:
        return ""
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["tasklist", "/FI", "PID eq " + str(pid), "/NH", "/FO", "CSV"],
                capture_output=True, text=True, timeout=20, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return "unknown"
        rows = completed.stdout.strip().splitlines()
        first = rows[0].strip() if rows else ""
        # 本地化输出：中文「信息: 没有运行的任务匹配指定标准。」/ 英文 "INFO: No tasks are running..."
        if not first.startswith('"'):
            return ""
        return first.split(",")[0].strip().strip('"')
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return ""
    except PermissionError:
        return "unknown"
    except OSError:
        return ""
    try:
        return Path("/proc/" + str(pid) + "/comm").read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


def process_alive(pid: int) -> bool:
    return process_image_name(pid) != ""


def looks_like_python(image_name: str) -> bool:
    """停止前的安全闸门：只肯停 python 进程，别的进程一律拒绝。"""
    return "python" in image_name.lower()


def connect_host(host: str) -> str:
    """0.0.0.0 / :: 这类「所有地址」不能直接连，探活与健康检查改用回环地址。"""
    bare = host.strip().strip("[]")
    if bare in ("0.0.0.0", "::", ""):
        return "127.0.0.1"
    return bare


def url_host(host: str) -> str:
    bare = host.strip()
    if ":" in bare and not bare.startswith("["):
        return "[" + bare + "]"
    return bare


def service_url(host: str, port: int) -> str:
    return "http://" + url_host(host) + ":" + str(port) + "/"


def port_busy(host: str, port: int, *, timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection((connect_host(host), port), timeout=timeout):
            return True
    except OSError:
        return False


def http_health(host: str, port: int, *, timeout: float = 1.5) -> dict:
    """GET /api/health；通了返回 data 字典（含 version），没通返回空字典。"""
    url = service_url(host, port) + "api/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return {}
    if isinstance(payload, dict) and payload.get("ok") and isinstance(payload.get("data"), dict):
        return payload["data"]
    return {}


# --------------------------------------------------------------------- PID 文件


def read_pid_file(path: Path) -> dict:
    """读 PID 文件。不存在返回空字典；内容坏了也返回空字典并带 note（当作陈旧文件处理）。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise LauncherError("无法读取 PID 文件：" + str(path), str(exc))
    try:
        payload = json.loads(raw)
    except ValueError:
        return {"note": "内容无法解析"}
    if not isinstance(payload, dict):
        return {"note": "内容不是一个 JSON 对象"}
    try:
        payload["pid"] = int(payload.get("pid") or 0)
    except (TypeError, ValueError):
        payload["pid"] = 0
    return payload


def write_pid_file(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    body = json.dumps(payload, ensure_ascii=False, indent=2) + chr(10)
    temporary.write_text(body, encoding="utf-8")
    os.replace(temporary, path)


def remove_pid_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        warn("PID 文件删不掉：" + str(path) + "（" + str(exc) + "）")


def tail_text(path: Path, lines: int) -> str:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    except OSError as exc:
        return "（读日志失败：" + str(exc) + "）"
    rows = raw.splitlines()
    return chr(10).join(rows[-lines:]) if lines > 0 else chr(10).join(rows)


# --------------------------------------------------------------------- 环境与配置


def check_python() -> str:
    version = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info < MIN_PYTHON:
        raise LauncherError(
            "需要 Python " + MIN_PYTHON_TEXT + " 或更高版本，当前是 " + version + "。",
            "当前解释器：" + sys.executable + "。装好新版 Python 后重新运行本脚本。",
        )
    return version


def find_ssh_client(explicit: str = "") -> str:
    candidate = (explicit or DEFAULT_SSH_EXECUTABLE).strip() or DEFAULT_SSH_EXECUTABLE
    if os.path.isabs(candidate) or os.sep in candidate:
        return candidate if os.path.isfile(candidate) else ""
    return shutil.which(candidate) or ""


def ensure_writable_dir(path: Path, label: str) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".awfm-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise LauncherError(label + "不可写：" + str(path), str(exc))


def load_settings(config_path: str = "", port_override: int | None = None) -> dict:
    """读配置得到 host/port/目录/ssh 可执行文件。配置缺失用内置默认值，损坏则报人话错误。"""
    root_text = str(ROOT)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    try:
        from app.core import config as app_config
    except Exception as exc:  # 源码缺失或语法错误都要变成人话
        raise LauncherError(
            "无法加载 app/core/config.py，源码可能不完整。",
            type(exc).__name__ + ": " + str(exc),
        )
    path = Path(config_path).expanduser().resolve() if config_path else Path(app_config.DEFAULT_CONFIG_PATH)
    explicit = bool(config_path)
    try:
        if path.exists():
            config = app_config.load_config(path)
        elif explicit:
            raise LauncherError(
                "指定的配置文件不存在：" + str(path),
                "去掉 --config 就用 data/config.json；或先运行 python app/main.py --init-config 生成一份。",
            )
        else:
            config = app_config.parse_config({}, path=str(path))
    except LauncherError:
        raise
    except Exception as exc:  # ConfigError 等一律转成「原因 + 建议」
        message = getattr(exc, "message", "") or str(exc)
        detail = getattr(exc, "detail", "") or ""
        raise LauncherError(
            "配置文件无法使用：" + message,
            (detail + " " if detail else "") + "请修好它，或用 python app/main.py --init-config 重新生成一份。",
        )
    settings = {
        "host": str(config.server.host),
        "port": int(config.server.port),
        "open_browser": bool(config.server.open_browser),
        "allow_lan": bool(config.security.allow_lan),
        "config_path": str(path),
        "config_exists": path.exists(),
        "logs_dir": Path(config.logs_dir),
        "data_dir": Path(config.data_dir),
        "ssh_executable": str(getattr(config.ssh, "ssh_executable", "") or ""),
    }
    if port_override is not None:
        if not 1 <= int(port_override) <= 65535:
            raise LauncherError("端口号必须在 1..65535 之间。", "收到：" + str(port_override))
        settings["port"] = int(port_override)
    settings["url"] = service_url(settings["host"], settings["port"])
    return settings


def current_state(pid_file: Path) -> dict:
    """把「PID 文件 + 进程是否活着 + 健康检查」合成一份状态快照。"""
    stored = read_pid_file(pid_file)
    pid = int(stored.get("pid") or 0)
    host = str(stored.get("host") or "127.0.0.1")
    port = int(stored.get("port") or DEFAULT_PORT)
    alive = bool(pid) and process_alive(pid)
    health = http_health(host, port) if alive else {}
    return {
        "stored": stored,
        "pid": pid,
        "host": host,
        "port": port,
        "url": str(stored.get("url") or service_url(host, port)),
        "alive": alive,
        "health": health,
        "running": bool(alive and health),
        "stale": bool(pid) and not alive,
    }


def describe_state(state: dict) -> str:
    if state["running"]:
        version = str(state["health"].get("version") or "")
        suffix = "，版本 " + version if version else ""
        return "运行中（PID " + str(state["pid"]) + "，" + state["url"] + suffix + "）"
    if state["alive"]:
        return "进程还在（PID " + str(state["pid"]) + "），但健康检查没有通过"
    if state["stale"]:
        return "没有运行（PID 文件里的 PID " + str(state["pid"]) + " 已经不存在）"
    return "没有运行"


# --------------------------------------------------------------------- start


def build_argv(settings: dict, extra_args: list) -> list:
    argv = [sys.executable, "-u", str(ROOT / "app" / "main.py"), "--port", str(settings["port"])]
    # 配置文件「不存在」和「不能用」是两回事（见 app/main.py 开头的说明）：
    # 默认路径缺失时程序会退回内置默认值启动，而显式 --config 指向不存在的文件会直接报错退出。
    # 所以只有文件真的在，才把 --config 传下去 —— 否则第一次运行（还没 init-config）根本起不来。
    if settings.get("config_path") and settings.get("config_exists"):
        argv += ["--config", str(settings["config_path"])]
    argv += extra_args
    return argv


def child_env() -> dict:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def append_console_log(path: Path, argv: list, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    banner = chr(10) + "===== " + stamp + " " + label + "：" + " ".join(argv) + " =====" + chr(10)
    with path.open("ab") as handle:
        handle.write(banner.encode("utf-8"))
        handle.flush()


def spawn_service(settings: dict, *, console_log: Path, extra_args: list) -> subprocess.Popen:
    argv = build_argv(settings, extra_args)
    append_console_log(console_log, argv, "由 run 后台启动")
    kwargs: dict = {}
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    with console_log.open("ab") as handle:
        return subprocess.Popen(
            argv,
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            env=child_env(),
            creationflags=creationflags,
            **kwargs,
        )


def build_pid_payload(pid: int, settings: dict, console_log: Path) -> dict:
    return {
        "pid": pid,
        "host": settings["host"],
        "port": settings["port"],
        "url": settings["url"],
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "python": sys.executable,
        "root": str(ROOT),
        "config": settings["config_path"],
        "console_log": str(console_log),
        "allow_lan": settings["allow_lan"],
    }


def print_console_tail(console_log: Path, lines: int) -> None:
    text = tail_text(console_log, lines)
    if text.strip():
        say("  ---- 控制台日志（" + str(console_log) + "）最后 " + str(lines) + " 行 ----")
        for row in text.splitlines():
            say("  " + row)
    else:
        say("  （控制台日志还是空的：" + str(console_log) + "）")


def runner_name() -> str:
    return "run.bat" if os.name == "nt" else "run.sh"


def report_started(settings: dict, pid: int, console_log: Path, version: str) -> None:
    ok("AWFM 已启动" + ("（版本 " + version + "）" if version else ""))
    say("  地址：" + settings["url"])
    say("  进程：PID " + str(pid) + "（后台运行，关掉本窗口不会停服务）")
    if settings["config_exists"]:
        say("  配置：" + settings["config_path"])
    else:
        say("  配置：" + settings["config_path"] + "（不存在，本次使用内置默认值）")
    if not settings["allow_lan"]:
        say("  访问范围：仅本机（security.allow_lan=false）")
    say("  日志：" + str(DEFAULT_APP_LOG) + "（控制台输出：" + str(console_log) + "）")
    say("  停止：" + runner_name() + " stop      查看状态：" + runner_name() + " status")


def cmd_start(args: argparse.Namespace) -> int:
    settings = load_settings(args.config, args.port)
    ensure_writable_dir(settings["logs_dir"], "日志目录")
    ensure_writable_dir(settings["data_dir"], "数据目录")
    pid_file = Path(args.pid_file)
    console_log = Path(args.console_log)

    state = current_state(pid_file)
    if state["running"]:
        info("AWFM 已经在运行，本次不会重复启动。")
        say("  " + describe_state(state))
        say("  停止：" + runner_name() + " stop")
        return EXIT_STATE
    if state["alive"]:
        warn("PID " + str(state["pid"]) + " 还在，但健康检查没有通过 —— 可能是上次启动没成功。")
        say("  先看日志：" + runner_name() + " logs")
        return EXIT_STATE
    if state["stale"]:
        info("清理陈旧的 PID 文件（PID " + str(state["pid"]) + " 已不存在）。")
        remove_pid_file(pid_file)

    if port_busy(settings["host"], settings["port"]):
        manual = ("netstat -ano | findstr :" + str(settings["port"])) if os.name == "nt" else ("ss -ltnp | grep :" + str(settings["port"]))
        raise LauncherError(
            "启动失败：" + settings["host"] + ":" + str(settings["port"]) + " 已经被占用。",
            "占用者不是 AWFM（没有对应的 PID 文件）。请用 --port 换一个端口，或先确认是谁在占用：" + manual,
        )

    check_python()
    ssh_client = find_ssh_client(settings.get("ssh_executable", ""))
    if not ssh_client:
        raise LauncherError(
            "找不到系统 ssh 客户端，AWFM 没有它就登不上远程主机。",
            "Windows：设置 → 系统 → 可选功能 → 添加「OpenSSH 客户端」；"\
            "Debian/Ubuntu：sudo apt install openssh-client。",
        )

    # 这条提示只在真的要继续启动时才打印：放在所有「拒绝启动」的分支之后，
    # 否则用户会先看到「本次用内置默认值启动」、紧接着又被告知本次不会启动。
    if not settings["config_exists"]:
        info("配置文件还不存在：" + settings["config_path"])
        say("  本次用内置默认值启动；要改配置请先运行 python app/main.py --init-config 生成一份。")

    extra_args = ["--no-browser"]
    if args.foreground:
        return run_foreground(settings, console_log, extra_args, pid_file)

    process = spawn_service(settings, console_log=console_log, extra_args=extra_args)
    write_pid_file(pid_file, build_pid_payload(process.pid, settings, console_log))

    deadline = time.monotonic() + float(args.timeout)
    health: dict = {}
    started = False
    while time.monotonic() < deadline:
        if process.poll() is not None:
            remove_pid_file(pid_file)
            fail("启动失败：服务进程已经退出（退出码 " + str(process.returncode) + "）。")
            print_console_tail(console_log, 25)
            return EXIT_FAILED
        health = http_health(settings["host"], settings["port"])
        if health:
            started = True
            break
        time.sleep(0.25)

    if not started:
        warn("启动超时：" + str(args.timeout) + " 秒内健康检查一直没有通过。")
        say("  进程仍在运行（PID " + str(process.pid) + "），也许只是启动得慢。")
        print_console_tail(console_log, 25)
        say("  停止它：" + runner_name() + " stop")
        return EXIT_FAILED

    payload = build_pid_payload(process.pid, settings, console_log)
    payload["version"] = str(health.get("version") or "")
    write_pid_file(pid_file, payload)
    report_started(settings, process.pid, console_log, str(health.get("version") or ""))
    if (settings["open_browser"] or args.open_browser) and not args.no_browser:
        try:
            webbrowser.open(settings["url"])
        except Exception:  # 打不开浏览器不是启动失败
            warn("没能自动打开浏览器，请手动访问 " + settings["url"])
    return EXIT_OK


def run_foreground(settings: dict, console_log: Path, extra_args: list, pid_file: Path) -> int:
    argv = build_argv(settings, extra_args)
    info("前台运行：输出同时写入 " + str(console_log) + "；按 Ctrl+C 停止。")
    append_console_log(console_log, argv, "由 run 前台启动")
    with console_log.open("ab") as handle:
        process = subprocess.Popen(argv, cwd=str(ROOT), env=child_env(),
                                   stdout=handle, stderr=subprocess.STDOUT)
        write_pid_file(pid_file, build_pid_payload(process.pid, settings, console_log))
        try:
            code = process.wait()
        except KeyboardInterrupt:
            info("收到 Ctrl+C，正在停止……")
            process.terminate()
            try:
                code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                warn("进程没有在 10 秒内退出，请再按一次 Ctrl+C，或手动结束 PID " + str(process.pid) + "。")
                code = EXIT_FAILED
        finally:
            remove_pid_file(pid_file)
    if code == 0:
        ok("AWFM 已停止（退出码 0）。")
        return EXIT_OK
    fail("服务退出，退出码 " + str(code) + "。日志尾部：")
    print_console_tail(console_log, 20)
    return EXIT_FAILED


# --------------------------------------------------------------------- status


def cmd_status(args: argparse.Namespace) -> int:
    state = current_state(Path(args.pid_file))
    stored = state["stored"]
    say("AWFM 运行状态")
    say("  状态：" + describe_state(state))
    if state["pid"]:
        say("  地址：" + state["url"])
        say("  进程：PID " + str(state["pid"]) + "，映像名 " + (process_image_name(state["pid"]) or "?"))
        if stored.get("started_at"):
            say("  启动时间：" + str(stored["started_at"]))
    else:
        try:
            settings = load_settings(args.config, args.port)
            say("  地址：" + settings["url"] + "（按当前配置，未在运行）")
            say("  端口：" + ("被占用" if port_busy(settings["host"], settings["port"]) else "空闲"))
        except LauncherError as exc:
            warn("读不到配置，无法显示预期地址：" + exc.message)
    if state["running"]:
        say("  提示：" + runner_name() + " stop 停止；" + runner_name() + " logs 看日志")
        return EXIT_OK
    return EXIT_STATE


# --------------------------------------------------------------------- stop


def graceful_stop(pid: int) -> str:
    """尝试优雅停止；返回一段说明（成功，或为什么没做到）。"""
    if os.name == "nt":
        completed = subprocess.run(["taskkill", "/PID", str(pid), "/T"],
                                   capture_output=True, text=True, check=False)
        if completed.returncode == 0:
            return "已发送停止请求（taskkill /PID " + str(pid) + " /T，未使用 /F）"
        return "Windows 拒绝了优雅停止（该进程没有窗口，通常只能在确认后强制终止）"
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return "进程已经不在了"
    except OSError as exc:
        return "发送 SIGTERM 失败：" + str(exc)
    return "已发送 SIGTERM"


def force_stop(pid: int) -> str:
    if os.name == "nt":
        completed = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                   capture_output=True, text=True, check=False)
        if completed.returncode == 0:
            return "已强制终止（taskkill /F，含子进程）"
        return "taskkill /F 失败：" + (completed.stderr.strip() or completed.stdout.strip())
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return "进程已经不在了"
    except OSError as exc:
        return "发送 SIGKILL 失败：" + str(exc)
    return "已强制终止（SIGKILL）"


def wait_process_gone(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_alive(pid):
            return True
        time.sleep(0.25)
    return not process_alive(pid)


def confirm(question: str, *, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin or not sys.stdin.isatty():
        return False
    try:
        answer = input(question + " [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        say("")
        return False
    return answer in ("y", "yes")


def cmd_stop(args: argparse.Namespace) -> int:
    pid_file = Path(args.pid_file)
    state = current_state(pid_file)

    if not state["pid"] and not state["alive"]:
        settings = None
        try:
            settings = load_settings(args.config, args.port)
        except LauncherError:
            settings = None
        if settings and port_busy(settings["host"], settings["port"]):
            warn("AWFM 没有在运行（没有 PID 文件），但 " + settings["host"] + ":" + str(settings["port"])
                 + " 上有别的程序在监听。")
            say("  停止只作用于 AWFM 自己记录的进程，这里不会去动它。")
            return EXIT_FAILED
        info("AWFM 没有在运行，什么都没做。")
        return EXIT_STATE

    if state["stale"]:
        info("没有在运行：PID 文件里的 PID " + str(state["pid"]) + " 已经不存在，清理这个陈旧文件。")
        remove_pid_file(pid_file)
        return EXIT_STATE

    pid = state["pid"]
    image = process_image_name(pid)
    if not looks_like_python(image):
        fail("拒绝停止：PID " + str(pid) + " 的映像名是 " + (image or "?") + "，不是 python 进程。")
        manual = ("tasklist /FI " + chr(34) + "PID eq " + str(pid) + chr(34)) if os.name == "nt" \
            else ("ps -p " + str(pid) + " -o pid,comm,args")
        say("  停止操作只肯停 AWFM 记录的 python 进程。请手动确认：" + manual)
        return EXIT_FAILED

    say("正在停止 AWFM（PID " + str(pid) + "，" + state["url"] + "）……")
    say("  " + graceful_stop(pid))
    if wait_process_gone(pid, float(args.timeout)):
        remove_pid_file(pid_file)
        if port_busy(state["host"], state["port"]):
            warn("进程已经退出，但端口 " + str(state["port"]) + " 还在被占用（可能是别的程序）。")
        ok("AWFM 已停止。")
        return EXIT_OK

    warn("进程没有在 " + str(args.timeout) + " 秒内退出。")
    allowed = args.force or confirm(
        "是否强制终止 PID " + str(pid) + "（会连同它的子进程一起结束）？", assume_yes=args.yes)
    if not allowed:
        fail("已放弃：没有做任何强制操作。")
        say("  稍后重试：" + runner_name() + " stop；确实要强杀时用：" + runner_name() + " stop --force --yes")
        if os.name == "nt":
            say("  手动处理：tasklist /FI " + chr(34) + "PID eq " + str(pid) + chr(34)
                + "，再用 taskkill /PID " + str(pid) + " /T /F")
        else:
            say("  手动处理：ps -p " + str(pid) + " -o pid,comm,args，再用 kill -9 " + str(pid))
        return EXIT_FAILED

    say("  " + force_stop(pid))
    if wait_process_gone(pid, 5.0):
        remove_pid_file(pid_file)
        ok("AWFM 已停止（强制终止）。")
        return EXIT_OK
    fail("强制终止后进程仍然存在，请手动检查 PID " + str(pid) + "。")
    return EXIT_FAILED


# --------------------------------------------------------------------- logs / restart / check


def cmd_logs(args: argparse.Namespace) -> int:
    path = Path(args.log_file) if args.log_file else DEFAULT_APP_LOG
    if not path.exists():
        try:
            settings = load_settings(args.config, args.port)
            candidate = Path(settings["logs_dir"]) / "awfm.log"
            if candidate.exists():
                path = candidate
        except LauncherError:
            pass
    if not path.exists():
        info("还没有日志文件：" + str(path))
        say("  服务启动后会写这里；后台运行的控制台输出见 " + str(DEFAULT_CONSOLE_LOG))
        return EXIT_STATE
    say("日志：" + str(path) + "（最后 " + str(args.lines) + " 行）")
    say("")
    text = tail_text(path, int(args.lines))
    say(text if text.strip() else "（日志是空的）")
    if args.follow:
        return follow_log(path)
    return EXIT_OK


def follow_log(path: Path) -> int:
    say("")
    info("正在跟随日志（Ctrl+C 退出）……")
    try:
        position = path.stat().st_size
        while True:
            time.sleep(0.5)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size < position:
                position = 0
            if size == position:
                continue
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(position)
                chunk = handle.read()
                position = handle.tell()
            sys.stdout.write(chunk)
            sys.stdout.flush()
    except KeyboardInterrupt:
        say("")
        return EXIT_OK


def cmd_restart(args: argparse.Namespace) -> int:
    stop_code = cmd_stop(args)
    if stop_code == EXIT_FAILED:
        fail("停止没有成功，重启中止（不会去启动第二个实例）。")
        return EXIT_FAILED
    return cmd_start(args)


def cmd_check(args: argparse.Namespace) -> int:
    """启动前自检：本脚本先检查环境，再复用 app/main.py --check 的配置与资源检查。"""
    say("AWFM 启动前自检")
    say("  项目根目录：" + str(ROOT))
    failures = 0

    try:
        version = check_python()
        ok("Python " + version + "  " + sys.executable)
    except LauncherError as exc:
        fail(exc.message)
        if exc.hint:
            say("          " + exc.hint)
        failures += 1

    settings: dict = {}
    try:
        settings = load_settings(args.config, args.port)
        suffix = "" if settings["config_exists"] else "（不存在，将使用内置默认值）"
        ok("配置文件：" + settings["config_path"] + suffix)
    except LauncherError as exc:
        fail(exc.message)
        if exc.hint:
            say("          " + exc.hint)
        failures += 1

    if settings:
        ssh_client = find_ssh_client(settings.get("ssh_executable", ""))
        if ssh_client:
            ok("ssh 客户端：" + ssh_client)
        else:
            fail("找不到系统 ssh 客户端")
            say("          Windows：可选功能里添加「OpenSSH 客户端」；Debian/Ubuntu：sudo apt install openssh-client")
            failures += 1
        for label, key in (("数据目录", "data_dir"), ("日志目录", "logs_dir")):
            try:
                ensure_writable_dir(Path(settings[key]), label)
                ok(label + "可写：" + str(settings[key]))
            except LauncherError as exc:
                fail(exc.message)
                failures += 1
        state = current_state(Path(args.pid_file))
        if state["running"]:
            info("服务已经在运行：" + describe_state(state) + "（重复 start 会被拒绝，不会起第二个实例）")
        elif port_busy(settings["host"], settings["port"]):
            fail("端口已被占用：" + settings["host"] + ":" + str(settings["port"]))
            failures += 1
        else:
            ok("端口空闲：" + settings["host"] + ":" + str(settings["port"]))

    say("")
    say("  接着运行 app/main.py --check（配置项、前端资源、主机密钥策略等）：")
    argv = [sys.executable, str(ROOT / "app" / "main.py"), "--check"]
    if args.config:
        argv += ["--config", str(args.config)]
    if args.port is not None:
        argv += ["--port", str(args.port)]
    completed = subprocess.run(argv, cwd=str(ROOT))

    say("")
    if completed.returncode != 0 or failures:
        fail("自检未通过：" + str(failures) + " 项前置检查失败"
             + ("，app/main.py --check 退出码 " + str(completed.returncode) if completed.returncode else "") + "。")
        return EXIT_FAILED
    ok("自检通过。")
    return EXIT_OK


# --------------------------------------------------------------------- 菜单


def print_usage() -> None:
    say("AWFM 统一启动器 —— " + str(ROOT))
    say("")
    say("用法：" + runner_name() + " [命令] [选项]")
    say("")
    say("命令：")
    say("  start        后台启动服务（默认；不带命令直接给 --port 等选项也按 start 处理）")
    say("  status       查看运行状态")
    say("  stop         停止服务")
    say("  restart      先停再启动")
    say("  logs         看日志尾部（-n 行数，--follow 持续跟随）")
    say("  check        启动前自检（环境 + 配置）")
    say("  menu         交互菜单（不带任何参数时的默认行为）")
    say("")
    say("选项：")
    say("  --port N           覆盖监听端口（默认取配置，出厂默认 " + str(DEFAULT_PORT) + "）")
    say("  --config PATH      指定配置文件（默认 data/config.json）")
    say("  --foreground       start 时前台运行，Ctrl+C 停止")
    say("  --no-browser       start 时不打开浏览器")
    say("  --open-browser     start 时打开浏览器")
    say("  --force            stop/restart 时允许强制终止（仍需 --yes 或交互确认）")
    say("  --yes              不询问、直接确认（配合 --force，脚本化场景用）")
    say("  --timeout N        start 等待健康检查的秒数（默认 " + str(int(DEFAULT_START_TIMEOUT))
        + "）/ stop 等待退出的秒数（默认 " + str(int(DEFAULT_STOP_TIMEOUT)) + "）")
    say("  --pid-file PATH    PID 文件位置（默认 data/awfm.pid）")
    say("  --log-file PATH    logs 命令要看的日志（默认 logs/awfm.log）")
    say("  --console-log PATH 后台运行时的控制台输出（默认 logs/awfm-console.log）")
    say("  -h, --help         显示本说明")
    say("")
    say("退出码：0 成功 / 1 失败 / 2 用法错误 / 3 已经在跑或没在跑（未做改动）")


def cmd_menu(args: argparse.Namespace) -> int:
    if not sys.stdin or not sys.stdin.isatty() or not sys.stdout.isatty():
        # 非交互（管道、计划任务、输出被重定向）：给说明与状态，绝不挂着等输入。
        info("当前不是交互终端，不显示菜单。")
        print_usage()
        cmd_status(args)
        return EXIT_OK
    while True:
        state = current_state(Path(args.pid_file))
        try:
            address = load_settings(args.config, args.port)["url"]
        except LauncherError as exc:
            address = "读不到配置：" + exc.message
        say("")
        say("============================================================")
        say(" AWFM —— Aimu's Web File Manager   统一启动器")
        say(" 目录：" + str(ROOT))
        say(" 地址：" + address)
        say(" 状态：" + describe_state(state))
        say("============================================================")
        say(" 1) 启动服务（后台运行，关掉本窗口不影响）")
        say(" 2) 前台启动（Ctrl+C 停止，直接看输出）")
        say(" 3) 查看运行状态")
        say(" 4) 停止服务")
        say(" 5) 查看日志（最后 " + str(DEFAULT_LOG_LINES) + " 行）")
        say(" 6) 启动前自检")
        say(" 7) 退出")
        try:
            choice = input("请选择 [1-7]: ").strip()
        except (EOFError, KeyboardInterrupt):
            say("")
            return EXIT_OK
        if choice in ("7", "q", "quit", "exit"):
            info("已退出。服务状态：" + describe_state(current_state(Path(args.pid_file))))
            return EXIT_OK
        if choice == "1":
            args.foreground = False
            cmd_start(args)
        elif choice == "2":
            args.foreground = True
            try:
                cmd_start(args)
            finally:
                args.foreground = False
        elif choice == "3":
            cmd_status(args)
        elif choice == "4":
            cmd_stop(args)
        elif choice == "5":
            cmd_logs(args)
        elif choice == "6":
            cmd_check(args)
        else:
            warn("请输入 1-7。")


# --------------------------------------------------------------------- 命令行


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run",
        description="AWFM 统一启动器：启动 / 状态 / 停止 / 日志 / 自检。",
    )
    parser.add_argument("command", nargs="?", default="menu",
                        choices=("menu", "start", "status", "stop", "restart", "logs", "check", "help"),
                        help="要执行的动作（默认 menu：交互菜单）")
    parser.add_argument("--port", type=int, metavar="N", help="覆盖监听端口（默认取配置）")
    parser.add_argument("--config", metavar="PATH", help="配置文件路径（默认 data/config.json）")
    parser.add_argument("--foreground", action="store_true", help="start 时前台运行")
    parser.add_argument("--no-browser", action="store_true", help="start 时不打开浏览器（即使配置里开着）")
    parser.add_argument("--open-browser", action="store_true", help="start 时打开浏览器")
    parser.add_argument("--force", action="store_true", help="stop/restart 时允许强制终止")
    parser.add_argument("--yes", action="store_true", help="不询问、直接确认（配合 --force）")
    parser.add_argument("--timeout", type=float, default=None, help="等待秒数（start 就绪 / stop 退出）")
    parser.add_argument("--pid-file", metavar="PATH", default=str(DEFAULT_PID_FILE), help="PID 文件位置")
    parser.add_argument("--log-file", metavar="PATH", default="", help="logs 命令要看的日志")
    parser.add_argument("--console-log", metavar="PATH", default=str(DEFAULT_CONSOLE_LOG),
                        help="后台运行时的控制台输出文件")
    parser.add_argument("-n", "--lines", type=int, default=DEFAULT_LOG_LINES, help="logs 显示的行数")
    parser.add_argument("--follow", action="store_true", help="logs 持续跟随")
    return parser


def main(argv: list | None = None) -> int:
    pin_console_encoding()
    raw = list(sys.argv[1:] if argv is None else argv)
    # 兼容旧习惯：run.bat --port 9000 等价于 run.bat start --port 9000
    if raw and raw[0].startswith("-"):
        raw = ["start"] + raw
    parser = build_parser()
    args = parser.parse_args(raw)
    if args.timeout is None:
        args.timeout = DEFAULT_START_TIMEOUT if args.command in ("start", "restart", "menu") else DEFAULT_STOP_TIMEOUT
    if args.lines < 0:
        say("logs 的行数不能是负数。")
        return EXIT_USAGE

    handlers = {
        "menu": cmd_menu,
        "start": cmd_start,
        "status": cmd_status,
        "stop": cmd_stop,
        "restart": cmd_restart,
        "logs": cmd_logs,
        "check": cmd_check,
    }
    if args.command == "help":
        print_usage()
        return EXIT_OK
    try:
        return handlers[args.command](args)
    except LauncherError as exc:
        fail(exc.message)
        if exc.hint:
            say("  " + exc.hint)
        return EXIT_FAILED
    except KeyboardInterrupt:
        say("")
        info("已中断。")
        return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
