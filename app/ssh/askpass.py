"""SSH_ASKPASS 辅助程序的准备与销毁（决策 D-008）。

## 为什么需要它

系统 `ssh` 从终端读密码。我们把它当子进程跑，**没有终端**，
因此必须借助 `SSH_ASKPASS`：ssh 在需要密码时改为执行 `SSH_ASKPASS` 指向的程序，
并把提示语作为第一个参数传进去，从该程序的**标准输出**读回密码。

## 密码怎么送到辅助程序

`SSH_ASKPASS` 只接受一个**可执行文件路径**，无法携带参数。所以这里生成两层：

```
askpass.cmd  →  "<python>" "<askpass_helper.py>"
                   ↑ 从环境变量 AWFM_ASKPASS_FILE 指向的文件里读密码
```

生成的是**不含秘密的包装脚本**（内容恒定），秘密只写在另一个临时文件里，
其路径通过环境变量传入。这样做的原因见 `ssh_launcher.build_environment` 的说明：
密码不放环境变量（Windows 上同用户的其它进程可读环境变量）。

## 生命周期

准备 → `transport.open()`（认证在此完成）→ **立刻销毁**。
密码在磁盘上的存活时间因此只有一次认证的时长（通常不足一秒）。
`SftpTransport` 之后的任何时候都不再需要它 —— 认证只发生一次。

## Windows 上的包装脚本

Windows 没有 `#!/bin/sh`。这里生成 `.cmd`，由 `CreateProcess` 经 `cmd.exe` 执行。
这一点是**实测确认**的（见 docs/reports 中的 askpass 验证记录）；
若某个环境上 `.cmd` 不可用，密码认证会明确失败并给出 stderr，而不会静默降级。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field

from app.core.errors import ConfigError

#: 密码文件路径的环境变量名。
ASKPASS_FILE_ENV = "AWFM_ASKPASS_FILE"

_HELPER_SOURCE = '''"""AWFM 的 SSH_ASKPASS 辅助程序。由 ssh 在需要密码时执行。

从环境变量 AWFM_ASKPASS_FILE 指向的文件里读取密码并写到标准输出。
不读标准输入（ssh 不会给它输入），不打印任何其它内容。
"""

import os
import sys

path = os.environ.get("AWFM_ASKPASS_FILE", "")
if not path:
    sys.exit(1)
try:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        secret = handle.read()
except OSError:
    sys.exit(1)
# ssh 会把读回的内容去掉一个尾随换行，所以这里原样打印即可。
sys.stdout.write(secret)
sys.stdout.flush()
'''

#: 包装脚本里 python 的调用形式。%* 让 ssh 传来的提示语参数原样透传
#: （辅助程序不关心它，但保留可以少一层"参数被吞掉"的意外）。
_WINDOWS_WRAPPER = '@echo off\r\n"{python}" "{helper}" %*\r\n'
_POSIX_WRAPPER = '#!/bin/sh\nexec "{python}" "{helper}" "$@"\n'


@dataclass
class AskpassBundle:
    """一次认证所需的临时资源。**用后必须 `cleanup()`**。"""

    command: str
    payload: dict[str, str] = field(default_factory=dict)
    _directory: str = ""

    def cleanup(self) -> None:
        """删除临时目录。幂等。"""
        if not self._directory:
            return
        shutil.rmtree(self._directory, ignore_errors=True)
        self._directory = ""

    def __enter__(self) -> "AskpassBundle":
        return self

    def __exit__(self, *_exc) -> None:
        self.cleanup()


def prepare_askpass(password: str) -> AskpassBundle:
    """为一个密码准备好 askpass 环境。

    Args:
        password: 明文密码。空字符串会被视为「没有密码」并报错 ——
            空密码会让 ssh 把「密码错误」和「没提供密码」混为一谈。

    Returns:
        `AskpassBundle`，其 `payload` 需要合并进子进程环境变量。
    """
    if not password:
        raise ConfigError("密码不能为空。", detail="如需免密登录，请改用密钥认证。")

    directory = tempfile.mkdtemp(prefix="awfm-askpass-")
    try:
        helper_path = os.path.join(directory, "askpass_helper.py")
        secret_path = os.path.join(directory, "secret")
        with open(helper_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(_HELPER_SOURCE)
        # newline="" + 不加换行：密码可能合法地以空格结尾，加换行不会有害
        # （ssh 会去掉一个尾随换行），但**不能**让 Python 自作主张转换行尾。
        with open(secret_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(password)
        if os.name != "nt":
            os.chmod(secret_path, 0o600)

        python = sys.executable
        if not python:
            raise ConfigError("无法确定 Python 解释器路径，密码认证不可用。")
        if os.name == "nt":
            wrapper_path = os.path.join(directory, "askpass.cmd")
            content = _WINDOWS_WRAPPER.format(python=python, helper=helper_path)
        else:
            wrapper_path = os.path.join(directory, "askpass.sh")
            content = _POSIX_WRAPPER.format(python=python, helper=helper_path)
        with open(wrapper_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        if os.name != "nt":
            os.chmod(wrapper_path, 0o700)

        return AskpassBundle(
            command=wrapper_path,
            payload={ASKPASS_FILE_ENV: secret_path},
            _directory=directory,
        )
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
