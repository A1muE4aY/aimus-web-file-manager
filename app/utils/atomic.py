"""原子文件写入。

决策 D-006 要求配置写入必须是原子的：崩在半路不能留下一个被截断的 JSON，
否则下次启动会因为「配置损坏」而拒绝服务，而用户其实什么都没做错。

做法是教科书式的 temp + `os.replace`：

1. 在**同一目录**下创建临时文件（跨卷 rename 不是原子的，所以不能放临时目录）。
2. 写入并 `flush` + `os.fsync` —— 少了 fsync，掉电后可能得到一个长度正确但内容全零的文件。
3. `os.replace` 覆盖目标 —— 在 POSIX 与 Windows 上都保证原子替换。
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any


def write_text_atomic(path: str, text: str, *, encoding: str = "utf-8") -> None:
    """把 `text` 原子地写入 `path`（必要时创建父目录）。"""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".awfm-tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        # 任何失败都不留残骸 —— 尤其是 mkstemp 创建出来的空临时文件。
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def write_json_atomic(path: str, data: Any, *, indent: int = 2) -> None:
    """原子写入 JSON。`ensure_ascii=False` 让连接名里的中文可读，`encoding=utf-8` 由调用方保证。"""
    text = json.dumps(data, ensure_ascii=False, indent=indent) + "\n"
    write_text_atomic(path, text)
