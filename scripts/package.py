#!/usr/bin/env python3
"""打包便携版（规划文档 §11 便携版 + §11 发行验收第 ⑧ 条）。

    python scripts/package.py                  # 先跑静态校验，再暂存 → 打 zip → 生成校验和
    python scripts/package.py --skip-checks    # 跳过静态校验（仅在你已单独跑过 build.py 时用）
    python scripts/package.py --out D:\\awfm-dist

产出（全部在 dist/ 下，该目录在 .gitignore 中，不提交）：

    dist/AWFM-0.1.0-windows-x64/          暂存目录树（就是解压后看到的样子）
      ├─ app/ frontend/ docs/             源码、静态资源、完整文档
      ├─ scripts/launcher.py              统一启动器：启动/状态/停止/日志/自检
      ├─ scripts/start.py                 前台启动的兼容入口（等价 run.bat start --foreground）
      ├─ run.bat  run.sh                  Windows / Linux 统一入口（双击 run.bat 出菜单）
      ├─ config/config.example.json       配置模板（真实配置仍写到 data/）
      ├─ README.md  LICENSE
      ├─ VERSION                          版本与构建记录
      └─ MANIFEST.json                    文件清单（逐个文件的 SHA-256）
    dist/AWFM-0.1.0-windows-x64.zip       便携包
    dist/SHA256SUMS.txt                   校验和

两处设计取舍，写在这里省得以后猜：

* **不捆绑 Python 运行时**：包内零第三方依赖（scripts/build.py 的 import 扫描检查这一条），
  静态资源全部自带（前端离线检查这一条），所以「解压后运行启动脚本、不要求在线安装依赖」
  由「一个 Python 3.10+ 解释器 + 本包」满足，不需要把解释器打进包里。
* **不含 tests/**：便携版是给最终用户运行用的；测试与开发脚本属于开发版（也就是仓库本身）。
  这一点在 docs/RELEASE.md 里对用户写明。

退出码：0 成功；1 静态校验未通过或打包后自检失败；2 用法/前置条件错误（缺文件、缺目录）。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import platform as platform_module
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build as build_checks  # noqa: E402  （同目录的静态校验，打包前必须先过）

#: 进包的项目目录与文件（tests/、data/、logs/、.temp/、.archive/ 一律不进）
STAGE_DIRS = ("app", "frontend", "docs")
STAGE_SCRIPTS = ("start.py", "launcher.py")
STAGE_FILES = ("README.md", "LICENSE", "config/config.example.json", "VERSION",
               "run.bat", "run.sh", "run-advanced.bat", "run-advanced.sh")

EXCLUDE_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".idea", ".vscode"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log", ".zip", ".tmp"}

#: zip 内的固定时间戳 —— 让「同一份源码 + 同一次生成时间」的包可复现
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

VERSION_TEMPLATE = """AWFM {version}
构建时间：{built_at}
目标平台：{platform}
构建主机 Python：{python}
源仓库：{root}

便携版说明：
* 运行只需要 Python 3.10 或更高版本，包内不含任何第三方依赖。
* 双击 run.bat（Linux/macOS 用 ./run.sh）即普通启动：查环境、起服务、就绪后自动打开浏览器。
* 要看菜单、换端口、看诊断时用 run-advanced.bat（Linux/macOS 用 ./run-advanced.sh）。
* 命令行等价写法：run.bat start / run.bat status / run.bat stop / run.bat logs。
* 真实配置写在 data/config.json（首次启动自动生成），日志写在 logs/。
* 校验和见同目录的 SHA256SUMS.txt。
"""


def default_platform() -> str:
    system = platform_module.system().lower()
    machine = platform_module.machine().lower()
    machine = {
        "amd64": "x64",
        "x86_64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(machine, machine)
    return system + "-" + machine


def _excluded(path: Path) -> bool:
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return True
    return any(part in EXCLUDE_DIR_NAMES for part in path.parts)


def iter_sources():
    """按 (绝对路径, 包内相对路径) 产出要进包的文件。"""
    for name in STAGE_DIRS:
        base = ROOT / name
        for path in sorted(base.rglob("*")):
            if path.is_file() and not _excluded(path):
                yield path, path.relative_to(ROOT)
    for name in STAGE_SCRIPTS:
        path = ROOT / "scripts" / name
        if path.is_file():
            yield path, Path("scripts") / name
    for name in STAGE_FILES:
        if name == "VERSION":
            continue
        path = ROOT / name
        if path.is_file():
            yield path, Path(name)


def copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 256), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text(path: Path, text: str, *, newline: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline=newline)


def build_stage(stage: Path, version: str, target_platform: str, built_at: datetime.datetime) -> int:
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    count = 0
    for source, relative in iter_sources():
        copy_file(source, stage / relative)
        count += 1

    write_text(
        stage / "VERSION",
        VERSION_TEMPLATE.format(
            version=version,
            built_at=built_at.isoformat(timespec="seconds"),
            platform=target_platform,
            python=sys.version.split()[0],
            root=str(ROOT),
        ),
        newline="\n",
    )
    return count + 1


def write_manifest(stage: Path, version: str, target_platform: str, built_at: datetime.datetime) -> list:
    entries = []
    for path in sorted(stage.rglob("*")):
        if not path.is_file() or path.name == "MANIFEST.json":
            continue
        relative = path.relative_to(stage).as_posix()
        entries.append({"path": relative, "size": path.stat().st_size, "sha256": sha256_file(path)})
    manifest = {
        "project": "AWFM",
        "version": version,
        "platform": target_platform,
        "generated_at": built_at.isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "note": "便携版只含运行所需文件：不含 tests/、data/、logs/；零第三方依赖。",
        "file_count": len(entries),
        "files": entries,
    }
    write_text(
        stage / "MANIFEST.json",
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        newline="\n",
    )
    return entries


def write_zip(stage: Path, zip_path: Path) -> int:
    """把暂存目录压成 zip；成员名统一带一层 <包名>/ 前缀。

    带前缀的理由：用户解压时不会把 app/ frontend/ docs/ 等目录散落到当前目录里，
    目录结构也与 docs/RELEASE.md 第 2 节画的树完全一致。
    """
    if zip_path.exists():
        zip_path.unlink()
    members = sorted(path for path in stage.rglob("*") if path.is_file())
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in members:
            relative = path.relative_to(stage).as_posix()
            member = stage.name + "/" + relative
            info = zipfile.ZipInfo(member, date_time=ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if relative.endswith(".sh") else 0o644) << 16
            archive.writestr(info, path.read_bytes())
    return len(members)


def verify_zip(zip_path: Path, entries: list) -> list:
    problems = []
    prefix = zip_path.stem + "/"
    expected = {prefix + item["path"]: item["sha256"] for item in entries}
    with zipfile.ZipFile(zip_path) as archive:
        broken = archive.testzip()
        actual = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()}
    if broken:
        problems.append("压缩包内有损坏成员：" + str(broken))
    for path, digest in sorted(expected.items()):
        if path not in actual:
            problems.append("压缩包缺少成员：" + path)
        elif actual[path] != digest:
            problems.append("内容与清单不一致：" + path)
    for path in sorted(set(actual) - set(expected) - {prefix + "MANIFEST.json"}):
        problems.append("清单外的成员：" + path)
    return problems


def check_required(stage: Path) -> list:
    required = (
        "app/main.py",
        "app/__init__.py",
        "frontend/index.html",
        "config/config.example.json",
        "scripts/start.py",
        "scripts/launcher.py",
        "README.md",
        "LICENSE",
        "VERSION",
        "MANIFEST.json",
        "run.bat",
        "run.sh",
    )
    return [name for name in required if not (stage / name).is_file()]


def write_sums(dist: Path, version: str, target_platform: str, built_at: datetime.datetime, zip_name: str, zip_digest: str, manifest_digest: str, manifest_name: str) -> Path:
    lines = [
        "# AWFM " + version + "（" + target_platform + "）发行校验和",
        "# 生成时间：" + built_at.isoformat(timespec="seconds"),
        "# 校验方式：certutil -hashfile <文件> SHA256   或   Get-FileHash -Algorithm SHA256 <文件>",
        "# 说明：便携包内每个文件的 SHA-256 见 " + manifest_name,
        "# 说明：VERSION 里带构建时间，所以重新打包时该文件与压缩包哈希会变；其余文件只随源码变化。",
        "",
        zip_digest + "  " + zip_name,
        manifest_digest + "  " + manifest_name,
        "",
    ]
    path = dist / "SHA256SUMS.txt"
    write_text(path, "\n".join(lines), newline="\n")
    return path


def human_size(size: int) -> str:
    if size >= 1024 * 1024:
        return str(round(size / (1024 * 1024), 2)) + " MB"
    if size >= 1024:
        return str(round(size / 1024, 1)) + " KB"
    return str(size) + " B"


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(prog="package", description="打包 AWFM 便携版发行包。")
    parser.add_argument("--out", metavar="DIR", help="输出目录（默认 dist/）")
    parser.add_argument("--platform", metavar="TAG", help="平台标签（默认按当前主机推断，如 windows-x64）")
    parser.add_argument("--skip-checks", action="store_true", help="跳过静态校验")
    args = parser.parse_args(argv)

    version = build_checks.read_version()
    if not version:
        print("[失败] 无法从 app/__init__.py 读出 __version__。", file=sys.stderr)
        return 2
    target_platform = args.platform or default_platform()
    dist = Path(args.out).resolve() if args.out else ROOT / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    stage = dist / ("AWFM-" + version + "-" + target_platform)
    zip_path = dist / (stage.name + ".zip")

    print("AWFM 便携版打包")
    print("项目根目录：" + str(ROOT))
    print("版本：" + version + "；平台标签：" + target_platform)
    print("输出目录：" + str(dist))
    print()

    if not args.skip_checks:
        print("第 1 步：静态校验（scripts/build.py）")
        checks = build_checks.run_checks()
        failed = [item for item in checks if not item["ok"]]
        for item in checks:
            print(("  [ 通过 ] " if item["ok"] else "  [ 失败 ] ") + item["name"])
        if failed:
            print()
            print("[失败] 静态校验未通过 " + str(len(failed)) + " 项，已中止打包。")
            for item in failed:
                print("       " + item["name"] + "：" + item["detail"])
            return 1
        print("  全部 " + str(len(checks)) + " 项通过。")
        print()

    built_at = datetime.datetime.now()
    print("第 2 步：暂存目录树 -> " + stage.name)
    copied = build_stage(stage, version, target_platform, built_at)
    entries = write_manifest(stage, version, target_platform, built_at)
    print("  复制 " + str(copied) + " 个文件（含 run.bat / run.sh / VERSION），清单 " + str(len(entries)) + " 项。")

    missing = check_required(stage)
    if missing:
        print("[失败] 暂存目录缺少必需文件：" + "、".join(missing))
        return 2

    print("第 3 步：压缩 -> " + zip_path.name)
    members = write_zip(stage, zip_path)
    print("  成员 " + str(members) + " 个，压缩包 " + human_size(zip_path.stat().st_size) + "。")

    print("第 4 步：自检（CRC + 逐个文件比对清单）")
    problems = verify_zip(zip_path, entries)
    if problems:
        for item in problems:
            print("  [ 失败 ] " + item)
        print("[失败] 打包后自检未通过。")
        return 1
    print("  [ 通过 ] 压缩包完整，且包内每个文件与 MANIFEST.json 的 SHA-256 一致。")

    zip_digest = sha256_file(zip_path)
    manifest_digest = sha256_file(stage / "MANIFEST.json")
    sums = write_sums(
        dist,
        version,
        target_platform,
        built_at,
        zip_path.name,
        zip_digest,
        manifest_digest,
        stage.name + "/MANIFEST.json",
    )

    total = sum(item["size"] for item in entries)
    print()
    print("打包完成")
    print("  目录树：" + str(stage) + "（" + str(len(entries)) + " 个文件，" + human_size(total) + "）")
    print("  便携包：" + str(zip_path) + "（" + human_size(zip_path.stat().st_size) + "）")
    print("  SHA-256：" + zip_digest)
    print("  校验和：" + str(sums))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
