"""构造 `ssh` 命令行与运行环境。

决策 D-003/D-011：连接层是**系统 OpenSSH 子进程**，不引入 SSH 协议库。
本模块负责把配置翻译成一组安全的命令行选项 —— 这是安全边界的一部分，
选项写错可能让主机密钥校验形同虚设。

## 必选的选项及其理由

| 选项 | 值 | 理由 |
|---|---|---|
| `UserKnownHostsFile` | 项目自有 `data/known_hosts` | D-010：不污染用户信任库，且「首次确认」在应用内可表达 |
| `GlobalKnownHostsFile` | **同一个项目自有文件** | 否则用户 `~/.ssh/known_hosts` 里的旧记录会让「首次确认」被跳过 |
| `StrictHostKeyChecking` | `yes` / `accept-new` | 规划文档 §10.1；默认 `yes`，见 `host_key_policy` |
| `BatchMode` | 见下 | **密码模式必须为 `no`**，否则密码认证会被整体跳过 |
| `ConnectTimeout` | 配置值 | 目标机不在线时不要无限挂起 |
| `ServerAliveInterval` | 配置值 | 让 NAT 掉线可被周期性探测到 |
| `LogLevel` | `ERROR` | 正常路径下 stderr 必须为空，否则错误诊断里全是噪音 |

## ★ `BatchMode=yes` 会**彻底禁用密码认证**

这不是文档里的显式说明，而是 OpenSSH 源码 `auth2-passwd.c` 的行为：
`userauth_passwd()` 开头就是 `if (options.batch_mode) return 0;` —— 直接把
password 方法从可选方法里摘掉。

因此：**密钥模式用 `BatchMode=yes`**（避免任何交互式挂起），
**密码模式必须用 `BatchMode=no` + `NumberOfPasswordPrompts=1`**，
靠 `SSH_ASKPASS` + `SSH_ASKPASS_REQUIRE=force` 提供密码（决策 D-008），
再靠 `NumberOfPasswordPrompts=1` 防止密码错误时被反复索要而挂住。
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass

from app.core.errors import ConfigError

#: 主机密钥策略。
#: - `strict`：只接受 known_hosts 里已有的密钥（默认，D-010）。
#: - `accept-new`：接受**新**主机，但**拒绝变化过的**密钥。
#:   提供它是为了兼容「非交互环境」的需求；默认不启用，因为规划文档 §10.1 要求首次连接显式确认。
HOST_KEY_POLICIES = ("strict", "accept-new")

#: 内部策略名 → OpenSSH 的 `StrictHostKeyChecking` 取值。
#:
#: 内部用 `strict` 是为了描述意图（严格校验），而 ssh 只认
#: `yes` / `no` / `ask` / `accept-new` / `off`。
#: 把内部名直接传给 ssh 会让它在**解析命令行**阶段就退出，报
#: `command-line line 0: unsupported option "strict"` —— 现象是「连不上」，
#: 而原因在参数拼装里，不修的话永远查不到协议层。
_STRICT_HOST_KEY_OPTION = {"strict": "yes", "accept-new": "accept-new"}


@dataclass(frozen=True)
class SshTarget:
    host: str
    port: int
    username: str

    @property
    def destination(self) -> str:
        # 空用户名的兜底：`"@host"` 会被 ssh 当成一个奇怪的用户名，报出与真实
        # 原因无关的认证错误。Connection 现在要求用户名非空，这里是第二道保险。
        return f"{self.username}@{self.host}" if self.username else self.host


def find_ssh_executable(configured: str = "") -> str:
    """定位 `ssh` 可执行文件。

    查找顺序：显式配置 > `PATH` > Windows 系统自带位置。
    显式配置存在但不可用时报错，**不静默回退** —— 否则用户以为自己指定了一个
    受控的 ssh，实际跑的是另一个，安全假设就不成立了。
    """
    if configured:
        if os.path.isfile(configured):
            return configured
        raise ConfigError(
            "配置中指定的 ssh 可执行文件不存在。",
            detail=f"ssh.ssh_executable={configured!r}",
        )
    found = shutil.which("ssh")
    if found:
        return found
    if sys.platform == "win32":
        candidate = os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"), "System32", "OpenSSH", "ssh.exe"
        )
        if os.path.isfile(candidate):
            return candidate
    raise ConfigError(
        "找不到 ssh 客户端程序。",
        detail="请安装 OpenSSH 客户端，或在配置的 ssh.ssh_executable 中指定完整路径。",
    )


def build_sftp_command(
    target: SshTarget,
    *,
    ssh_executable: str,
    known_hosts_file: str,
    host_key_policy: str = "strict",
    identity_file: str | None = None,
    connect_timeout: int = 15,
    keepalive_interval: int = 30,
    use_password: bool = False,
) -> list[str]:
    """构造启动 SFTP 子系统的 `ssh` 命令行。

    Args:
        known_hosts_file: 项目自有的 known_hosts 路径。父目录必须已存在。
        identity_file: 私钥路径；`None` 表示交给 ssh 自己找（agent / 默认密钥）。
        use_password: 为 `True` 时启用 `SSH_ASKPASS` 路径（见模块文档说明）。
    """
    if host_key_policy not in HOST_KEY_POLICIES:
        raise ConfigError(
            "security.host_key_policy 取值非法。",
            detail=f"期望 {HOST_KEY_POLICIES} 之一，实际 {host_key_policy!r}。",
        )

    command = [ssh_executable]
    command += ["-p", str(target.port)]
    command += ["-o", f"UserKnownHostsFile={known_hosts_file}"]
    # 让「全局」known_hosts 也指向项目自有文件：否则用户在 ~/.ssh/known_hosts 里的
    # 既有记录会让 ssh 直接通过校验，我们会**跳过首次确认**，D-010 的设计意图就落空了。
    command += ["-o", f"GlobalKnownHostsFile={known_hosts_file}"]
    command += ["-o", f"StrictHostKeyChecking={_STRICT_HOST_KEY_OPTION[host_key_policy]}"]
    command += ["-o", f"ConnectTimeout={int(connect_timeout)}"]
    command += ["-o", f"ServerAliveInterval={int(keepalive_interval)}"]
    command += ["-o", "ServerAliveCountMax=3"]
    command += ["-o", "LogLevel=ERROR"]

    if use_password:
        # ★ 绝不能是 yes —— 那会禁用密码认证（见模块文档）。
        command += ["-o", "BatchMode=no"]
        command += ["-o", "NumberOfPasswordPrompts=1"]
        command += ["-o", "PreferredAuthentications=password,keyboard-interactive,publickey"]
    else:
        command += ["-o", "BatchMode=yes"]
        command += ["-o", "PreferredAuthentications=publickey"]

    if identity_file:
        command += ["-i", identity_file]
        # 只在用户显式指定了密钥时收窄身份：否则 ssh-agent 里的其它密钥会先被试一遍，
        # 在某些有登录失败次数限制的目标机上会造成账号被锁。
        command += ["-o", "IdentitiesOnly=yes"]

    command.append(target.destination)
    command.append("-s")
    command.append("sftp")
    return command


def build_environment(
    base: dict[str, str] | None,
    *,
    askpass_command: str | None = None,
    askpass_payload: dict[str, str] | None = None,
) -> dict[str, str]:
    """构造子进程环境变量。

    默认**继承当前环境**（需要 `SystemRoot`、`PATH` 等才能正常启动 ssh），
    在此之上叠加 askpass 相关变量。

    安全说明（登记在 docs/SECURITY.md）：密码**不通过环境变量传递** ——
    环境变量在 Windows 上可被同用户的其它进程读取。这里只设置「运行哪个辅助程序」
    与「从哪里读密码」的**路径**，密码本身由辅助程序从一个只读的临时文件读取，
    且该文件在子进程退出后立即删除。
    """
    env = dict(os.environ if base is None else base)
    env.setdefault("PYTHONUTF8", "1")
    if askpass_command:
        env["SSH_ASKPASS"] = askpass_command
        # SSH_ASKPASS_REQUIRE=force 是 OpenSSH 8.4+ 的选项：不加它，ssh 在有终端时
        # 会忽略 SSH_ASKPASS；加了它则**无条件**走 askpass，与是否有终端无关。
        env["SSH_ASKPASS_REQUIRE"] = "force"
        # DISPLAY 非空是部分 OpenSSH 版本使用 askpass 的额外前提。
        env["DISPLAY"] = env.get("DISPLAY") or "awfm-local"
    else:
        # 不用 askpass 时必须把父进程环境里的同名变量摘掉：否则 ssh 可能去执行
        # 一个与本程序无关的辅助程序 —— 轻则认证行为莫名改变，重则它等待输入
        # 而把连接挂死在这里。
        env.pop("SSH_ASKPASS", None)
        env.pop("SSH_ASKPASS_REQUIRE", None)
    for key, value in (askpass_payload or {}).items():
        env[key] = value
    return env
