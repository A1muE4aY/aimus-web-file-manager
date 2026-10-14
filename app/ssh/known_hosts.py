"""主机密钥的采集、指纹计算与信任存储（安全关键模块）。

对应规划文档 §10.1：「SSH 主机密钥验证，首次提供可信指纹确认，变更时不得自动覆盖或忽略」，
以及验收项 T-005。

## ★ 为什么不能用 `ssh-keyscan`

原设计想用 `ssh-keyscan -p <port> -t ed25519 <host>` 取指纹。**阶段 02 实测它在本机不可用**：

```
# 127.0.0.1:2222 SSH-2.0-OpenSSH_9.6p1 Ubuntu-3ubuntu13.20
debug1: kex: algorithm: sntrup761x25519-sha512@openssh.com
choose_kex: unsupported KEX method sntrup761x25519-sha512@openssh.com
```

退出码 1，**没有产出任何 host key 行**。原因是该 OpenSSH 版本
（`OpenSSH_for_Windows_9.5p2`）的算法列表里没有 `sntrup761x25519-sha512@openssh.com`，
而这恰是现代服务端的首选 KEX，并且 `ssh-keyscan` 没有降级协商。

## 采用的替代方案（与本机 OpenSSH 版本无关）

用一个**临时 `known_hosts`** + `StrictHostKeyChecking=no` 连一次，
让 `ssh` 自己完成算法协商并把服务端密钥写进临时文件，然后读回。

之所以安全，是因为：

1. 主机密钥校验发生在**认证之前**，所以即使没有可用凭据，ssh 也已经写完密钥。
2. 临时文件是**一次性**的，用完即删；采集到的密钥在用户确认前**不写入**项目信任库。
3. 采集阶段用的是 `BatchMode=yes`，不可能因为等待密码输入而挂住。

这与「静默接受新密钥」有本质区别：`StrictHostKeyChecking=no` 在采集流程里
**只作用于那个临时文件**，项目真正的信任库 `data/known_hosts` 只接受用户显式确认过的密钥。
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from app.core.errors import ConfigError, OperationTimeout, RemoteError
from app.utils.atomic import write_text_atomic

#: 已知的密钥类型。用列表而不是「接受任意字符串」，因为 known_hosts 的第一列
#: 必须与 ssh 的预期完全一致，拼错的类型名会让 ssh 静默忽略整行。
KNOWN_KEY_TYPES = (
    "ssh-ed25519",
    "ssh-rsa",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "ssh-dss",
    "sk-ssh-ed25519@openssh.com",
    "sk-ecdsa-sha2-nistp256@openssh.com",
)

#: 主机名中需要被 known_hosts 的方括号语法包裹的字符。含 `:` 时无法用裸写法，
#: 非 22 端口必须写成 `[host]:port`。
_HASHED_PREFIX = "|1|"


@dataclass(frozen=True)
class HostKey:
    """一条主机公钥记录。"""

    key_type: str
    key_b64: str
    comment: str = ""

    @property
    def fingerprint(self) -> str:
        """`SHA256:...` 形式的指纹，与 `ssh-keygen -lf` 的输出一致。"""
        return fingerprint_of(self.key_type, self.key_b64)

    def to_dict(self) -> dict[str, str]:
        return {"key_type": self.key_type, "fingerprint": self.fingerprint}

    def to_line(self) -> str:
        return f"{self.key_type} {self.key_b64}" + (f" {self.comment}" if self.comment else "")


def fingerprint_of(key_type: str, key_b64: str) -> str:
    """计算 OpenSSH 的 `SHA256` 指纹。

    算法：对**解码后的密钥二进制**做 SHA-256，再做 base64（去掉尾部 `=` 填充），
    前缀 `SHA256:`。与 `ssh-keygen -lf known_hosts` 的输出逐字符相同 ——
    这一点很重要：用户会拿它和自己终端里看到的指纹对照。
    """
    try:
        blob = base64.b64decode(key_b64, validate=True)
    except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        raise ConfigError(
            "known_hosts 中的公钥不是合法的 base64。",
            detail=f"密钥类型={key_type}",
        ) from exc
    digest = hashlib.sha256(blob).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def host_key_pattern(host: str, port: int) -> str:
    """构造 known_hosts 第一列的主机模式。

    非标准端口必须写成 `[host]:port` —— 这与 `ssh` 内部的写法一致，
    写成 `host:port` 会被当成「主机名里含冒号」而被静默忽略。
    """
    if port == 22:
        return host
    return f"[{host}]:{port}"


def parse_known_hosts_text(text: str) -> list[tuple[list[str], HostKey]]:
    """解析 known_hosts 内容为 `(主机模式列表, 密钥)`。

    只处理明文行。**哈希行（`|1|...`）被跳过并在调用方告知用户** ——
    哈希化是已知主机的隐私保护特性，我们无法（也不该）从哈希反推主机名。
    """
    results: list[tuple[list[str], HostKey]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        patterns_field, key_type, key_b64 = parts[0], parts[1], parts[2]
        if patterns_field.startswith(_HASHED_PREFIX):
            continue
        if key_type not in KNOWN_KEY_TYPES:
            continue
        comment = parts[3] if len(parts) > 3 else ""
        patterns = [p for p in patterns_field.split(",") if p]
        results.append((patterns, HostKey(key_type=key_type, key_b64=key_b64, comment=comment)))
    return results


def find_trusted_keys(known_hosts_path: str, host: str, port: int) -> list[HostKey]:
    """读出项目信任库中该主机的全部公钥。

    返回**列表**而不是单个：同一主机可以同时有 ed25519 与 rsa 两把钥匙，
    ssh 会挑一把可用的。只保留一把会让另一条合法连接被误判为「密钥变化」。
    """
    if not os.path.isfile(known_hosts_path):
        return []
    with open(known_hosts_path, "r", encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    wanted = host_key_pattern(host, port)
    matched: list[HostKey] = []
    for patterns, key in parse_known_hosts_text(text):
        if wanted in patterns or host in patterns:
            matched.append(key)
    return matched


def append_trusted_key(known_hosts_path: str, host: str, port: int, key: HostKey) -> None:
    """把一条公钥写入项目信任库（原子追加）。

    **调用方必须已经在用户层完成了确认**（见 `HostKeyUnknown` 的处理流程）。
    本函数不做任何确认 —— 它只负责写，把「谁有权写」的判断留在上层，
    这样「确认」这件事只有一个发生地点，可被审计。
    """
    directory = os.path.dirname(os.path.abspath(known_hosts_path))
    os.makedirs(directory, exist_ok=True)
    existing = ""
    if os.path.isfile(known_hosts_path):
        with open(known_hosts_path, "r", encoding="utf-8", errors="replace") as handle:
            existing = handle.read()
    if existing and not existing.endswith("\n"):
        existing += "\n"
    pattern = host_key_pattern(host, port)
    marker = f"# AWFM 于 {_now_iso()} 由用户确认后加入"
    new_content = existing + f"{marker}\n{pattern} {key.to_line()}\n"
    # 原子覆盖而不是 append 模式：append 在崩溃时会留下半行，
    # 而半行的 known_hosts 会让 ssh 报出与真实原因无关的解析错误。
    write_text_atomic(known_hosts_path, new_content)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_known_hosts_file(known_hosts_path: str) -> None:
    """确保信任库文件存在（空文件也算存在）。"""
    directory = os.path.dirname(os.path.abspath(known_hosts_path))
    os.makedirs(directory, exist_ok=True)
    if not os.path.isfile(known_hosts_path):
        write_text_atomic(known_hosts_path, "")


def collect_host_keys(
    *,
    ssh_executable: str,
    host: str,
    port: int,
    connect_timeout: int = 15,
) -> list[HostKey]:
    """连一次目标机，把它提供的主机公钥采集回来（P-005 方案）。

    **不写项目信任库**。返回值是「候选」，必须由用户确认后才可写入。

    Raises:
        AwfmError: ssh 可执行文件不存在，或连不上目标机。
    """
    from app.core.errors import AwfmError  # 局部导入避免循环

    tmp_dir = tempfile.mkdtemp(prefix="awfm-hostkey-")
    tmp_known_hosts = os.path.join(tmp_dir, "known_hosts")
    try:
        command = [
            ssh_executable,
            "-p", str(port),
            "-o", f"UserKnownHostsFile={tmp_known_hosts}",
            "-o", f"GlobalKnownHostsFile={tmp_known_hosts}",
            # ★ 只对这一个临时文件生效。项目信任库不受影响。
            "-o", "StrictHostKeyChecking=no",
            "-o", f"ConnectTimeout={int(connect_timeout)}",
            # 主机密钥校验发生在认证之前，所以这里认证必然失败 —— 那没关系，
            # 我们要的是 ssh 在此之前已经写好的密钥。BatchMode 同时保证不会挂住。
            "-o", "BatchMode=yes",
            "-o", "PreferredAuthentications=publickey",
            "-o", "LogLevel=ERROR",
            host,
            "-s", "sftp",
        ]
        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        # 清掉可能存在的 askpass 设置，避免采集阶段弹出任何提示。
        env.pop("SSH_ASKPASS", None)
        env.pop("SSH_ASKPASS_REQUIRE", None)
        try:
            completed = subprocess.run(  # noqa: S603 - argv 列表，不经 shell
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=max(connect_timeout + 10, 20),
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise OperationTimeout(
                f"连接 {host}:{port} 超时，无法获取主机密钥。",
                detail="目标机可能未开机、端口未开放或被防火墙拦截。",
            ) from exc
        except FileNotFoundError as exc:
            raise ConfigError("找不到 ssh 客户端程序。", detail=str(exc)) from exc

        if not os.path.isfile(tmp_known_hosts):
            stderr = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
            raise RemoteError(
                f"无法从 {host}:{port} 获取主机密钥。",
                detail=stderr.splitlines()[-1] if stderr else "ssh 未写入任何主机密钥。",
            )
        with open(tmp_known_hosts, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        keys = [key for _patterns, key in parse_known_hosts_text(text)]
        if not keys:
            raise RemoteError(
                f"无法从 {host}:{port} 获取主机密钥。",
                detail="ssh 报告连接成功但没有记录任何可用的主机密钥。",
            )
        return keys
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def looks_like_hashed_hosts(known_hosts_path: str) -> bool:
    """信任库里是否存在哈希化的主机行。用于在 UI 上给出「看不到某些主机」的解释。"""
    if not os.path.isfile(known_hosts_path):
        return False
    with open(known_hosts_path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith(_HASHED_PREFIX) or re.match(r"^\s*\|1\|", line):
                return True
    return False
