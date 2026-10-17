#!/bin/sh
# AWFM 普通启动入口（Linux / macOS）—— 真正的逻辑都在 scripts/launcher.py
# 用法：./run.sh（不带参数 = 普通启动：查环境、起服务、就绪后自动开浏览器）。
# 带参数时按高级用法透传：./run.sh status / stop / restart / logs / check / help / menu。
# 需要完整菜单和诊断请用 ./run-advanced.sh，两者行为一致，只是默认动作不同。
# 退出码：0 成功 / 1 失败 / 2 用法错误 / 3 已经在跑或没在跑（未做改动）。
set -u

# 1) 切到本脚本所在目录：路径里有空格或符号链接都没关系（全程加引号，cd -P 解析真实路径）。
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P) || {
    echo "[失败] 无法切换到脚本所在目录：$(dirname -- "$0")" >&2
    exit 1
}
cd "$SCRIPT_DIR" || exit 1

# 2) 找 Python：python3 优先，其次 python。只用 POSIX 内建命令，不依赖任何第三方工具。
PYTHON_BIN=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON_BIN=$(command -v "$candidate")
        break
    fi
done
if [ -z "$PYTHON_BIN" ]; then
    echo "[失败] 找不到 python3。" >&2
    echo "        Debian / Ubuntu：sudo apt install python3" >&2
    echo "        RHEL / CentOS：  sudo dnf install python3" >&2
    echo "        macOS：          brew install python3" >&2
    exit 1
fi

# 3) UTF-8：远程主机上的文件名可能有 emoji 或非本机语言（决策 D-013）。
PYTHONUTF8=1
PYTHONIOENCODING=utf-8
export PYTHONUTF8 PYTHONIOENCODING

# 4) 转交启动器：参数原样转发；exec 让退出码与信号原样传给调用者
#    （systemd 或 Ctrl+C 都能正确到达服务进程）。
exec "$PYTHON_BIN" "$SCRIPT_DIR/scripts/launcher.py" "$@"
