"""程序入口。

    python app/main.py                 # 用默认配置启动
    python app/main.py --init-config   # 先在 data/config.json 生成一份可编辑的配置
    python app/main.py --check         # 只做环境和配置自检，不启动服务

## 配置文件「不存在」与「损坏」是两回事

- **不存在**（首次运行、还没跑过 --init-config）：用内置默认值启动，并把这件事
  明确写进日志和终端。开箱即用是本项目的四原则之一，要求用户先跑一条命令才能启动
  会把「解压即可用」变成「解压后先读文档」。
- **存在但有语法错误或字段非法**：**拒绝启动**，并指出行号列号。这是决策 D-006 ——
  一份被改写坏的配置里可能存着用户所有的连接信息，程序绝不能拿默认值把它盖掉。

只有当使用**默认配置路径**时才允许「不存在 → 用默认值」；用户显式 --config 指定的
文件找不到就报错，否则打错一个路径会让人以为自己的配置生效了。
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import threading
import webbrowser
from pathlib import Path

if __package__ in (None, ""):  # 支持 python app/main.py 直接运行
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import __version__  # noqa: E402
from app.api.http_server import create_server  # noqa: E402
from app.core.config import (  # noqa: E402
    DEFAULT_CONFIG_PATH,
    AppConfig,
    ConfigError,
    init_config,
    load_config,
    parse_config,
)
from app.core.errors import AwfmError  # noqa: E402
from app.services.connection_manager import ConnectionManager  # noqa: E402
from app.utils.logging_setup import pin_stdio_encoding, setup_logging  # noqa: E402

logger = logging.getLogger("awfm")

_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="awfm",
        description="Aimu's Web File Manager —— 通过 SSH/SFTP 在浏览器里浏览远程文件系统。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python app/main.py --init-config       生成配置文件后退出\n"
            "  python app/main.py --check             自检环境与配置\n"
            "  python app/main.py --port 9000         换端口启动\n"
        ),
    )
    parser.add_argument("--config", metavar="PATH", help="配置文件路径（默认 data/config.json）")
    parser.add_argument("--init-config", action="store_true", help="生成配置文件后退出")
    parser.add_argument("--force", action="store_true",
                        help="与 --init-config 连用：覆盖已存在的配置文件")
    parser.add_argument("--check", action="store_true", help="自检环境与配置，不启动服务")
    parser.add_argument("--host", metavar="ADDR", help="覆盖 server.host")
    parser.add_argument("--port", type=int, metavar="PORT", help="覆盖 server.port")
    parser.add_argument("--log-level", metavar="LEVEL", help="覆盖 security.log_level")
    parser.add_argument("--open-browser", action="store_true", default=None,
                        help="启动后自动打开浏览器")
    parser.add_argument("--no-browser", action="store_true", help="启动后不打开浏览器")
    parser.add_argument("--version", action="version", version=f"AWFM {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    pin_stdio_encoding()

    config_path = Path(args.config).resolve() if args.config else Path(DEFAULT_CONFIG_PATH)

    if args.init_config:
        return _do_init_config(config_path, overwrite=args.force)

    try:
        config = _load_or_default(config_path, explicit=bool(args.config))
        _apply_overrides(config, args)
    except AwfmError as exc:
        # 启动前的错误没有日志系统可用（日志级别就写在配置里），所以直接打到 stderr。
        print(f"启动失败：{exc.message}", file=sys.stderr)
        if exc.detail:
            print(f"  {exc.detail}", file=sys.stderr)
        return 2

    setup_logging(config.logs_dir, level=config.security.log_level,
                  redact_secrets=config.security.redact_secrets)

    if args.check:
        return _run_checks(config, config_path)

    return _serve(config)


# --------------------------------------------------------------------- 子命令


def _do_init_config(config_path: Path, *, overwrite: bool) -> int:
    try:
        written = init_config(config_path, overwrite=overwrite)
    except AwfmError as exc:
        print(f"生成配置失败：{exc.message}", file=sys.stderr)
        if exc.detail:
            print(f"  {exc.detail}", file=sys.stderr)
        return 2
    print(f"已生成配置文件：{written}")
    print("请编辑该文件，填入你的虚拟机地址与登录信息。")
    print("提示：私钥认证需要 identity_file 指向私钥文件；密码不会也不应写入这个文件。")
    return 0


def _load_or_default(config_path: Path, *, explicit: bool) -> AppConfig:
    if config_path.exists():
        return load_config(config_path)
    if explicit:
        raise ConfigError(
            f"指定的配置文件不存在：{config_path}",
            detail="请检查 --config 的路径，或先运行 --init-config 生成一份。",
        )
    config = parse_config({}, path=str(config_path))
    logger.warning("未找到配置文件 %s，本次将使用内置默认值。", config_path)
    print(f"提示：未找到 {config_path}，本次使用内置默认值。")
    print("      运行 python app/main.py --init-config 可生成一份可编辑的配置。")
    return config


def _apply_overrides(config: AppConfig, args: argparse.Namespace) -> None:
    """命令行覆盖。只覆盖显式给出的项。"""
    if args.host:
        config.server.host = args.host
    if args.port is not None:
        if not (1 <= args.port <= 65535):
            raise ConfigError("端口号必须在 1..65535 之间。", detail=f"收到 {args.port}。")
        config.server.port = args.port
    if args.log_level:
        level = args.log_level.upper()
        if level not in _LOG_LEVELS:
            raise ConfigError("日志级别无效。", detail=f"收到 {args.log_level!r}。")
        config.security.log_level = level
    if args.no_browser:
        config.server.open_browser = False
    elif args.open_browser:
        config.server.open_browser = True
    # 覆盖之后必须重新走一遍安全校验：先用 --host 0.0.0.0 把服务开到局域网上，
    # 再来问「要不要开 allow_lan」就太晚了。
    config.validate_binding()


def _run_checks(config: AppConfig, config_path: Path) -> int:
    """--check：把「能不能跑起来」这件事在启动之前回答清楚。

    对应验收项 T-012（离线部署）与规划文档 §11 的发行验收清单 ——
    用户拿到便携版后第一条该跑的命令。
    """
    from app.ssh.ssh_launcher import find_ssh_executable

    failures = 0
    warnings = 0

    def line(status: str, label: str, detail: str = "") -> None:
        marker = {"ok": "[ 通过 ]", "warn": "[ 警告 ]", "fail": "[ 失败 ]"}[status]
        print(f"{marker} {label}" + (f"\n          {detail}" if detail else ""))

    print(f"AWFM {__version__} 自检")
    exists_note = "" if config_path.exists() else "（不存在，使用内置默认值）"
    print(f"配置文件：{config_path}{exists_note}")
    print(f"项目根目录：{config.root}")
    print()

    line("ok", f"Python {sys.version.split()[0]}", sys.executable)

    try:
        executable = find_ssh_executable(config.ssh.ssh_executable)
        if os.path.isfile(executable) or shutil.which(executable):
            line("ok", "ssh 可执行文件", executable)
        else:
            line("warn", "ssh 路径看起来不寻常", f"{executable} 不是一个已存在的文件")
            warnings += 1
    except AwfmError as exc:
        detail = f"{exc.message} {exc.detail or ''}".strip()
        line("fail", "找不到 ssh 可执行文件", detail)
        failures += 1

    index = config.frontend_dir / "index.html"
    if index.is_file():
        line("ok", "前端资源", str(config.frontend_dir))
    elif config.frontend_dir.is_dir():
        line("fail", "前端缺少 index.html", str(index))
        failures += 1
    else:
        line("fail", "前端资源目录不存在", str(config.frontend_dir))
        failures += 1

    for label, path in (("数据目录", config.data_dir), ("日志目录", config.logs_dir)):
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".awfm-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            line("ok", f"{label}可写", str(path))
        except OSError as exc:
            line("fail", f"{label}不可写", f"{path}：{exc}")
            failures += 1

    known_hosts = config.known_hosts_path
    if known_hosts.exists():
        line("ok", "主机密钥信任库", str(known_hosts))
    else:
        line("warn", "主机密钥信任库尚未建立",
             f"{known_hosts} 会在首次确认主机指纹后创建")
        warnings += 1

    line("ok", f"主机密钥策略：{config.security.host_key_policy}")
    lan_note = "（允许局域网访问）" if config.security.allow_lan else "（仅本机）"
    line("ok", f"监听地址：{config.server.host}:{config.server.port}{lan_note}")
    line("ok", f"已配置连接：{len(config.connections)} 个")

    print()
    if failures:
        print(f"自检未通过：{failures} 项失败，{warnings} 项警告。")
        return 1
    print(f"自检通过（{warnings} 项警告）。")
    return 0


# --------------------------------------------------------------------- 启动


def _serve(config: AppConfig) -> int:
    # 运行期依赖的目录在这里一次性建好（AGENTS.md §3.5：不在仓库里预建空目录）。
    config.logs_dir.mkdir(parents=True, exist_ok=True)
    config.data_dir.mkdir(parents=True, exist_ok=True)

    manager = ConnectionManager(config)
    try:
        server = create_server(config, manager)
    except AwfmError as exc:
        logger.error("%s", exc.message)
        if exc.detail:
            logger.error("  %s", exc.detail)
        print(f"启动失败：{exc.message}", file=sys.stderr)
        if exc.detail:
            print(f"  {exc.detail}", file=sys.stderr)
        return 2

    host, port = server.server_address[0], server.server_address[1]
    url = f"http://{_url_host(host)}:{port}/"
    logger.info("AWFM %s 已启动：%s", __version__, url)
    logger.info("监听 %s:%s；主机密钥策略 %s", host, port, config.security.host_key_policy)
    print()
    print(f"  AWFM {__version__} 已启动")
    print(f"  请在浏览器打开：{url}")
    if not config.security.allow_lan:
        print("  （仅本机可访问。需要局域网访问请修改配置中的 security.allow_lan）")
    print("  按 Ctrl+C 停止")
    print()

    if config.server.open_browser:
        # 延时一点再开：浏览器可能在服务真正 accept 之前就发起请求。
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\n正在停止……")
    finally:
        server.shutdown()
        server.server_close()
        # 验收项 T-013：不留孤儿 ssh 进程。
        manager.disconnect_all()
        logger.info("已停止，所有会话已断开。")
    return 0


def _url_host(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


if __name__ == "__main__":
    raise SystemExit(main())
