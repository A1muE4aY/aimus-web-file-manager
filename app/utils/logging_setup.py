"""日志配置。

决策 D-013：Windows 上一切文本 I/O 显式钉 UTF-8。

日志同时写文件与标准错误：文件给用户事后排查（规划文档 §11 要求便携版
「明确日志位置」），标准错误给前台运行时直接看见。**不写 `data/`，
写 `logs/`** —— 日志是运行时产物，不该与配置混在一起。
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from app.utils.redact import RedactingFilter

#: 单个日志文件上限与保留份数。设上限的理由：这个程序可能连续跑几个月，
#: 不轮转的日志最终会把磁盘写满，而用户不会想到去清它。
MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 3

_LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging(logs_dir: str, *, level: str = "INFO", redact_secrets: bool = True,
                  to_stderr: bool = True) -> logging.Logger:
    """配置根日志器。重复调用是幂等的（只生效一次）。

    Args:
        logs_dir: 日志目录；为空则只输出到标准错误。
        level: 日志级别名。
        redact_secrets: 是否挂脱敏过滤器。
        to_stderr: 是否同时输出到标准错误。
    """
    global _configured
    root = logging.getLogger()
    if _configured:
        return root

    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
    filters = [RedactingFilter()] if redact_secrets else []

    if logs_dir:
        try:
            os.makedirs(logs_dir, exist_ok=True)
            handler = RotatingFileHandler(
                os.path.join(logs_dir, "awfm.log"),
                maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8",
            )
            handler.setFormatter(formatter)
            for flt in filters:
                handler.addFilter(flt)
            root.addHandler(handler)
        except OSError as exc:
            # 日志目录建不出来不该阻止程序启动，但必须说出来。
            print(f"警告：无法创建日志目录 {logs_dir}：{exc}", file=sys.stderr)

    if to_stderr:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(formatter)
        for flt in filters:
            stream.addFilter(flt)
        root.addHandler(stream)

    if not root.handlers:  # pragma: no cover - 兜底，正常不会发生
        root.addHandler(logging.NullHandler())

    _configured = True
    return root


def reset_for_tests() -> None:
    """仅供测试：清掉已配置标记与所有处理器，让下一次 setup_logging 重新生效。"""
    global _configured
    _configured = False
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass


def pin_stdio_encoding() -> None:
    """把标准输出/错误钉成 UTF-8（决策 D-013）。

    Windows 控制台的默认编码是 GBK，中文日志会直接抛 `UnicodeEncodeError`。
    只在本进程的流对象上改，不动系统设置。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
