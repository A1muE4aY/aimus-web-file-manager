#!/usr/bin/env python3
"""四层测试的批量运行器。

    python scripts/test.py                     # 全部四层：unit -> integration -> security -> e2e
    python scripts/test.py unit security       # 只跑指定层（按参数顺序）
    python scripts/test.py --fast              # = unit security（不需要测试床与浏览器）
    python scripts/test.py -v                  # 打印每个用例名
    python scripts/test.py --no-compile        # 跳过语法校验

每一层就是文档里那条命令（docs/DEVELOPMENT.md 与各层 _index.md 记的一致）：

    python -m unittest discover -s tests/<层> -t .

**跳过不算失败**：没有 Edge 时 e2e 会跳过，没有测试床时 integration/e2e 会跳过。
脚本把跳过数单独列出来，避免把「没跑」误读成「跑过了」——这是本项目的记录纪律。

退出码：0 全部通过；1 有用例失败或出错；2 用法错误或语法校验失败。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAYERS = ("unit", "integration", "security", "e2e")
FAST_LAYERS = ("unit", "security")

SUMMARY_RE = re.compile(r"^Ran (\d+) tests? in ([0-9.]+)s", re.M)
STATUS_RE = re.compile(r"^(OK|FAILED[^\n]*)$", re.M)
COUNT_RE = re.compile(r"([a-z]+)=(\d+)")


def child_environment() -> dict:
    env = dict(os.environ)
    # 决策 D-013：Windows 上一切文本 I/O 显式钉 UTF-8。
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_command(command: list) -> tuple:
    started = time.monotonic()
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=child_environment(),
    )
    return proc.returncode, proc.stdout or "", time.monotonic() - started


def parse_result(output: str, seconds: float) -> dict:
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "seconds": seconds, "state": ""}
    summary = SUMMARY_RE.search(output)
    if summary:
        counts["tests"] = int(summary.group(1))
        counts["seconds"] = float(summary.group(2))
    status = STATUS_RE.search(output)
    if status:
        counts["state"] = status.group(1).strip()
        for key, value in COUNT_RE.findall(status.group(1)):
            if key in counts:
                counts[key] = int(value)
    return counts


def compile_check() -> tuple:
    command = [
        sys.executable,
        "-W",
        "error::SyntaxWarning",
        "-m",
        "compileall",
        "-q",
        "app",
        "tests",
        "scripts",
    ]
    return run_command(command)


def main(argv: list) -> int:
    verbose = False
    do_compile = True
    requested = []

    for arg in argv:
        if arg in ("-v", "--verbose"):
            verbose = True
        elif arg == "--no-compile":
            do_compile = False
        elif arg == "--fast":
            requested.extend(FAST_LAYERS)
        elif arg in ("-h", "--help"):
            print(__doc__)
            return 0
        elif arg.startswith("-"):
            print("未知参数：" + arg + "（用 --help 看用法）", file=sys.stderr)
            return 2
        elif arg in LAYERS:
            requested.append(arg)
        else:
            print("未知测试层：" + arg + "（可选 " + " / ".join(LAYERS) + "）", file=sys.stderr)
            return 2

    layers = []
    for name in (requested or LAYERS):
        if name not in layers:
            layers.append(name)

    print("AWFM 测试运行器")
    print("项目根目录：" + str(ROOT))
    print("Python：" + sys.version.split()[0] + "（" + sys.executable + "）")
    print("要跑的层：" + " ".join(layers))
    print()

    if do_compile:
        print("== 语法校验：python -W error::SyntaxWarning -m compileall -q app tests scripts ==")
        code, output, seconds = compile_check()
        if code != 0:
            print(output)
            print("语法校验未通过（退出码 " + str(code) + "），先修完再跑测试。")
            return 2
        print("通过（" + format(seconds, ".2f") + "s）")
        print()

    results = []
    failed = False
    for layer in layers:
        banner = "== tests/" + layer + " =="
        if verbose:
            command = [sys.executable, "-m", "unittest", "discover", "-s", "tests/" + layer, "-t", ".", "-v"]
        else:
            command = [sys.executable, "-m", "unittest", "discover", "-s", "tests/" + layer, "-t", "."]
        print(banner)
        code, output, seconds = run_command(command)
        print(output.rstrip())
        print()
        counts = parse_result(output, seconds)
        counts["exit"] = code
        counts["layer"] = layer
        results.append(counts)
        if code != 0:
            failed = True

    print("== 汇总 ==")
    total = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "seconds": 0.0}
    for item in results:
        for key in total:
            total[key] += item[key]
        print(
            "%-12s %5d 用例  %3d 失败  %3d 错误  %3d 跳过  %6.2fs  %s"
            % (item["layer"], item["tests"], item["failures"], item["errors"], item["skipped"], item["seconds"], item["state"] or "无结果行")
        )
    print(
        "%-12s %5d 用例  %3d 失败  %3d 错误  %3d 跳过  %6.2fs"
        % ("合计", total["tests"], total["failures"], total["errors"], total["skipped"], total["seconds"])
    )
    if total["skipped"]:
        print()
        print("注意：" + str(total["skipped"]) + " 项被跳过 —— 跳过的用例没有验证任何东西，")
        print("      要看是不是缺少 Edge 浏览器或 WSL 测试床（见各层 _index.md）。")

    if failed:
        print()
        print("有层未通过。")
        return 1
    print()
    print("全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
