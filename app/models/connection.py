"""连接配置模型。

## 密码不落盘（决策 D-014）

规划文档 §10.2 要求「避免明文保存密码」。本项目的选择是**从不持久化密码**：

- 配置文件中**没有**密码字段，因此不可能因为疏忽而把它写进 `data/config.json`。
- 密码在 `POST /api/connections/{id}/connect` 的请求体里传入，只存在于**内存中的会话对象**里，
  会话断开即丢弃。
- 需要免交互的场景由密钥 / `ssh-agent` 承担（D-008 也把密钥列为优先路径）。

代价是每次重新连接都要重新输入密码。这是**刻意付出的成本**：
把密码写进一个本地 JSON 文件，其安全性完全依赖于该文件的 ACL，
而本项目默认运行在非管理员账户下，无法保证 ACL 一定正确 ——
与其提供一个「看起来安全」的选项，不如不提供。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.core.errors import ValidationError

#: 认证方式。首版只支持这两种（规划文档 §3.1 P0-01）。
AUTH_METHODS = ("key", "password")

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_HOST_RE = re.compile(r"^[A-Za-z0-9._:\[\]-]{1,255}$")


def validate_connection_id(value: object) -> str:
    """连接 id 会被用作 URL 路径分量与配置字典的键，因此必须收窄字符集。

    尤其禁止 `/` 与 `..`：它们会让 `/api/connections/<id>/files` 这种路由
    被解析成别的资源。
    """
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise ValidationError("连接 id 只能包含字母、数字、下划线和连字符，且不能以连字符开头。")
    return value


def validate_host(value: object) -> str:
    """校验主机名或 IP。

    不做 DNS 解析 —— 解析会把「主机名写错」变成一个延迟到连接时才出现的错误。
    这里只排除明显非法的字符（空白、斜杠、控制字符），把判断留给 ssh。
    """
    if not isinstance(value, str):
        raise ValidationError("主机必须是字符串。")
    host = value.strip()
    if not host:
        raise ValidationError("主机不能为空。")
    if not _HOST_RE.match(host):
        raise ValidationError("主机名包含非法字符。")
    return host


def validate_port(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, str) and value.strip().isdigit():
            value = int(value.strip())
        else:
            raise ValidationError("端口必须是整数。")
    port = int(value)
    if not (1 <= port <= 65535):
        raise ValidationError("端口必须在 1 到 65535 之间。")
    return port


def validate_username(value: object) -> str:
    if not isinstance(value, str):
        raise ValidationError("用户名必须是字符串。")
    username = value.strip()
    if not username:
        raise ValidationError("用户名不能为空。")
    if len(username) > 128 or any(ch in username for ch in "\x00\r\n"):
        raise ValidationError("用户名包含非法字符。")
    return username


@dataclass
class Connection:
    """一条保存的连接配置。**不含密码**（见模块文档）。"""

    id: str
    name: str
    host: str
    port: int = 22
    username: str = ""
    auth_method: str = "key"
    identity_file: str = ""
    #: 备注，给用户自己看
    note: str = ""
    #: 是否允许这条连接执行写操作（P2 的建目录/重命名/删除）。
    #: 默认关闭 —— 规划文档 §3.2 要求高风险操作在只读浏览稳定后单独设计。
    allow_write: bool = False
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        self.id = validate_connection_id(self.id)
        self.host = validate_host(self.host)
        self.port = validate_port(self.port)
        self.username = validate_username(self.username)
        if self.auth_method not in AUTH_METHODS:
            raise ValidationError(f"认证方式只能是 {' 或 '.join(AUTH_METHODS)}。")
        if not isinstance(self.name, str) or not self.name.strip():
            self.name = f"{self.username}@{self.host}" if self.username else self.host
        if self.auth_method == "key" and self.identity_file:
            # 只做形式检查：真实存在性在连接时由 ssh 判断（用户可能用 `~` 或 agent）。
            if any(ch in self.identity_file for ch in "\x00\r\n"):
                raise ValidationError("私钥路径包含非法字符。")

    @property
    def target_label(self) -> str:
        return f"{self.username}@{self.host}:{self.port}"

    def to_dict(self) -> dict[str, Any]:
        """完整序列化（用于写入配置文件）。不含任何凭据。"""
        return {
            "id": self.id,
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "auth_method": self.auth_method,
            "identity_file": self.identity_file,
            "note": self.note,
            "allow_write": self.allow_write,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def to_public_dict(self) -> dict[str, Any]:
        """对外（API 响应）序列化。

        当前与 `to_dict` 相同，**但两者被刻意分开**：将来若加入任何敏感字段，
        只需要改 `to_public_dict`，所有 API 出口自动安全；
        若只写一个方法，就必须逐个检查每个响应构造点 —— 那是会漏的。
        验收项 T-011 要求「密码/私钥不出现在前端响应中」。
        """
        return self.to_dict()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Connection":
        if not isinstance(data, dict):
            raise ValidationError("连接条目必须是对象。")
        unknown = set(data) - {
            "id", "name", "host", "port", "username", "auth_method",
            "identity_file", "note", "allow_write", "created_at", "updated_at",
        }
        if unknown:
            raise ValidationError(f"连接条目包含未知字段：{', '.join(sorted(unknown))}。")
        try:
            return cls(
                id=data["id"],
                name=data.get("name") or "",
                host=data["host"],
                port=data.get("port", 22),
                username=data.get("username", ""),
                auth_method=data.get("auth_method", "key"),
                identity_file=data.get("identity_file", "") or "",
                note=data.get("note", "") or "",
                allow_write=bool(data.get("allow_write", False)),
                created_at=data.get("created_at", "") or "",
                updated_at=data.get("updated_at", "") or "",
            )
        except KeyError as exc:
            raise ValidationError(f"连接条目缺少必需字段：{exc.args[0]}。") from exc
