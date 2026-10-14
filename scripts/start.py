#!/usr/bin/env python3
"""AWFM 启动脚本（薄包装）。

    python scripts/start.py                  # 用默认配置启动（data/config.json）
    python scripts/start.py --init-config    # 先在 data/config.json 生成一份可编辑的配置
    python scripts/start.py --check          # 自检环境与配置，不启动服务
    python scripts/start.py --port 9000      # 换端口

参数原样转交给 app/main.py（--help 打出来的也是它的说明）。这个脚本额外做三件事：

1. 把工作目录切到项目根：从任意位置调用，data/、logs/、frontend/ 的解析都不漂移；
2. 检查 Python 版本：低于 3.10 时给人话提示，而不是抛一堆语法错误；
3. 显式钉 UTF-8（决策 D-013）：Windows 控制台默认 GBK，含 emoji 的文件名会直接崩。

退出码与 app/main.py 一致：0 正常结束、1 自检未通过、2 启动前失败。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_PYTHON = (3, 10)
MIN_PYTHON_TEXT = "3.10"


def main(argv: list) -> int:
    if sys.version_info < MIN_PYTHON:
        current = ".".join(str(part) for part in sys.version_info[:3])
        print("AWFM 需要 Python " + MIN_PYTHON_TEXT + " 或更高版本，当前是 " + current + "。", file=sys.stderr)
        print("  当前解释器：" + sys.executable, file=sys.stderr)
        print("  安装好新版 Python 后重试，或换成 scripts/start.py 所在的正确解释器。", file=sys.stderr)
        return 2

    # setdefault：显式设过就让调用方说了算，不去覆盖。
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    # 先切目录再导入 app.*：配置里的相对路径（data/known_hosts 等）以项目根为基准。
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from app.main import main as awfm_main

    return awfm_main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
