#!/usr/bin/env python3
"""构建前的静态校验（把规划文档 §11 发行验收里能自动化的部分做成一条命令）。

    python scripts/build.py                 # 控制台报告；全部通过退出码 0
    python scripts/build.py --json out.json # 另存机器可读结果（scripts/package.py 也调它）

八项检查，每项都对应一条**可核实的规则**，不做「看起来没问题」这种判断：

1. Python 版本    —— 项目要求 3.10+（README「系统要求」；app/main.py 用到 3.10 的语法）。
2. 语法校验       —— python -W error::SyntaxWarning -m compileall -q app tests scripts。
3. 零第三方依赖   —— 用 ast 扫描 app/ 与 scripts/ 的 import，逐个比对 sys.stdlib_module_names（需求 N-02）。
4. 前端离线       —— frontend/ 里不得出现 http(s)://，唯一放行 xmlns="http://www.w3.org/2000/svg"（验收项 T-002）。
5. 凭据纪律       —— config/ docs/ frontend/ tests/fixtures/ 里不得出现私钥标记或填了值的 password 字段（AGENTS.md §3.4）。
6. 错误模型回归   —— app/ 下不得再出现 http_status=<值> 的关键字参数写法（2026-10-15 的真实缺陷，见 docs/reports/PHASE-05）。
7. 版本一致性     —— app/__init__.py 的 __version__ 必须同时出现在 README.md 与 docs/CHANGELOG.md 中。
8. 测试包结构     —— tests/unit、integration、security、e2e 四个目录都要有 __init__.py（少一个 discover 直接报错）。

退出码：0 全部通过；1 有检查失败；2 用法错误。
"""
from __future__ import annotations

import argparse
import ast
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: frontend 里唯一放行的 URL —— SVG 命名空间是格式要求，不是网络请求。
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
FRONTEND_SUFFIXES = {".html", ".css", ".js", ".svg", ".json"}
FRONTEND_URL_RE = re.compile(r"https?://[^\s\"'<>()]+")
OFFLINE_EXCEPTIONS = {SVG_NAMESPACE, SVG_NAMESPACE + "/"}

CREDENTIAL_DIRS = ("config", "docs", "frontend", "tests/fixtures")
CREDENTIAL_SUFFIXES = {".md", ".json", ".py", ".js", ".html", ".css", ".txt", ".sh", ".cmd", ".example"}
PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
PASSWORD_VALUE_RE = re.compile(r'"password"\s*:\s*"([^"]*)"', re.IGNORECASE)
#: 文档示例里的占位写法（docs/API.md:319 写的 "…"）。真密码不长这样，所以放行；
#: 一旦有人把真密码填进示例，值不匹配这里，检查照样失败。
PASSWORD_PLACEHOLDER_RE = re.compile(
    r"^(?:|…+|\.{2,}|\*+|<[^>]*>|密码|x{3,}|\$\{[^}]*\}|[A-Z_ ]*PASSWORD[A-Z_ ]*|[A-Za-z ]*placeholder[A-Za-z ]*)$",
    re.IGNORECASE,
)

#: 类属性写成 "http_status = 500"（等号两侧有空格），这里只找关键字参数写法。
HTTP_STATUS_KWARG = "http_status="

VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)

TEST_LAYERS = ("unit", "integration", "security", "e2e")


def read_version(root: Path = ROOT) -> str:
    text = (root / "app" / "__init__.py").read_text(encoding="utf-8")
    match = VERSION_RE.search(text)
    return match.group(1) if match else ""


def check_python_version() -> dict:
    ok = sys.version_info >= (3, 10)
    current = ".".join(str(part) for part in sys.version_info[:3])
    return {
        "name": "Python 版本",
        "ok": ok,
        "detail": "当前 " + current + "（" + sys.executable + "）" + ("" if ok else "，低于要求的 3.10"),
    }


def check_compile(root: Path = ROOT) -> dict:
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
    proc = subprocess.run(
        command,
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (proc.stdout or "").strip()
    return {
        "name": "语法校验（SyntaxWarning 视为错误）",
        "ok": proc.returncode == 0,
        "detail": "app/ tests/ scripts/ 编译通过" if proc.returncode == 0 else output[-600:],
    }


def _local_modules(root: Path) -> set:
    local = {path.stem for path in (root / "scripts").glob("*.py")}
    local |= {
        child.name
        for child in root.iterdir()
        if child.is_dir() and (child / "__init__.py").is_file()
    }
    local |= {"app", "tests", "scripts", "build", "package", "start", "test"}
    return local


def check_stdlib_only(root: Path = ROOT) -> dict:
    files = sorted((root / "app").rglob("*.py")) + sorted((root / "scripts").glob("*.py"))
    stdlib = set(sys.stdlib_module_names)
    local = _local_modules(root)
    imported = set()
    outside = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            outside.append(str(path.relative_to(root)) + " 无法解析：" + str(exc))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
    for name in sorted(imported):
        if name not in stdlib and name not in local:
            outside.append(name)
    ok = not outside
    detail = (
        "扫描 " + str(len(files)) + " 个源文件，导入 " + str(len(imported)) + " 个顶层模块，全部来自标准库"
        if ok
        else "发现非标准库依赖：" + "、".join(outside)
    )
    return {"name": "零第三方依赖（import 扫描）", "ok": ok, "detail": detail}


def check_frontend_offline(root: Path = ROOT) -> dict:
    offenders = []
    scanned = 0
    for path in sorted((root / "frontend").rglob("*")):
        if not path.is_file() or path.suffix.lower() not in FRONTEND_SUFFIXES:
            continue
        scanned += 1
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for url in FRONTEND_URL_RE.findall(line):
                if url in OFFLINE_EXCEPTIONS:
                    continue
                offenders.append(str(path.relative_to(root)) + ":" + str(number) + " " + url)
    ok = not offenders
    detail = (
        "扫描 " + str(scanned) + " 个前端文件，未发现任何外部 URL（SVG 命名空间除外）"
        if ok
        else "发现外部 URL：" + "；".join(offenders[:6])
    )
    return {"name": "前端离线（无 CDN / 在线字体）", "ok": ok, "detail": detail}


def check_credentials(root: Path = ROOT) -> dict:
    offenders = []
    placeholders = []
    scanned = 0
    for directory in CREDENTIAL_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in CREDENTIAL_SUFFIXES:
                continue
            scanned += 1
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                where = str(path.relative_to(root)) + ":" + str(number)
                if PRIVATE_KEY_RE.search(line):
                    offenders.append(where + " 私钥标记")
                match = PASSWORD_VALUE_RE.search(line)
                if not match:
                    continue
                value = match.group(1).strip()
                if PASSWORD_PLACEHOLDER_RE.match(value):
                    placeholders.append(where + " 写的是 " + (value or "空串"))
                else:
                    offenders.append(where + " 填了值的 password 字段")
    ok = not offenders
    if ok:
        detail = "扫描 " + str(scanned) + " 个可能被提交的文件，未发现私钥内容或明文密码"
        if placeholders:
            detail += "（" + str(len(placeholders)) + " 处示例占位符已放行：" + "；".join(placeholders[:3]) + "）"
    else:
        detail = "发现可疑内容：" + "；".join(offenders[:6])
    return {"name": "凭据纪律（无私钥 / 无明文密码）", "ok": ok, "detail": detail}


def check_error_model(root: Path = ROOT) -> dict:
    offenders = []
    for path in sorted((root / "app").rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if HTTP_STATUS_KWARG in line:
                offenders.append(str(path.relative_to(root)) + ":" + str(number))
    ok = not offenders
    detail = (
        "app/ 下没有把 http_status 当构造参数传的写法（状态码只来自错误子类的类属性）"
        if ok
        else "发现关键字参数写法：" + "、".join(offenders[:6])
    )
    return {"name": "错误模型回归（http_status 不是构造参数）", "ok": ok, "detail": detail}


def check_version_consistency(root: Path = ROOT) -> dict:
    version = read_version(root)
    if not version:
        return {"name": "版本一致性", "ok": False, "detail": "app/__init__.py 里找不到 __version__"}
    readme = (root / "README.md")
    changelog = (root / "docs" / "CHANGELOG.md")
    missing = []
    if not readme.is_file() or version not in readme.read_text(encoding="utf-8"):
        missing.append("README.md")
    if not changelog.is_file() or version not in changelog.read_text(encoding="utf-8"):
        missing.append("docs/CHANGELOG.md")
    ok = not missing
    detail = (
        "__version__ = " + version + "，README.md 与 docs/CHANGELOG.md 均已提到该版本"
        if ok
        else "版本 " + version + " 未出现在：" + "、".join(missing)
    )
    return {"name": "版本一致性", "ok": ok, "detail": detail}


def check_test_packages(root: Path = ROOT) -> dict:
    missing = [
        layer
        for layer in TEST_LAYERS
        if not (root / "tests" / layer / "__init__.py").is_file()
    ]
    ok = not missing
    detail = (
        "tests/ 四层都有 __init__.py：" + " ".join(TEST_LAYERS)
        if ok
        else "缺少 __init__.py：" + "、".join(missing) + "（unittest discover 会直接报不可导入）"
    )
    return {"name": "测试包结构", "ok": ok, "detail": detail}


def run_checks(root: Path = ROOT) -> list:
    return [
        check_python_version(),
        check_compile(root),
        check_stdlib_only(root),
        check_frontend_offline(root),
        check_credentials(root),
        check_error_model(root),
        check_version_consistency(root),
        check_test_packages(root),
    ]


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(prog="build", description="AWFM 静态校验与构建前检查。")
    parser.add_argument("--json", metavar="PATH", help="把结果另存为 JSON")
    args = parser.parse_args(argv)

    version = read_version()
    print("AWFM 构建前检查")
    print("项目根目录：" + str(ROOT))
    print("版本：" + (version or "未知") + "；Python：" + sys.version.split()[0])
    print()

    checks = run_checks()
    for item in checks:
        print(("[ 通过 ] " if item["ok"] else "[ 失败 ] ") + item["name"])
        print("          " + item["detail"])

    failures = [item for item in checks if not item["ok"]]
    print()
    if failures:
        print("未通过 " + str(len(failures)) + " / " + str(len(checks)) + " 项。")
    else:
        print("全部 " + str(len(checks)) + " 项通过。")

    if args.json:
        payload = {
            "project": "AWFM",
            "version": version,
            "root": str(ROOT),
            "python": sys.version.split()[0],
            "checked_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "ok": not failures,
            "checks": checks,
        }
        target = Path(args.json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("结果已写入：" + str(target))

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
