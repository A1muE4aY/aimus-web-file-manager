"""远程文件条目模型。

API 返回的每个目录项都长这样。设计约束：

1. **只放事实，不做格式化。** 大小是字节整数、时间是 epoch 秒 ——
   人类可读形式（`1.2 MiB`、`3 分钟前`）由前端按用户所在时区渲染。
   服务端做格式化会强迫所有用户接受服务端的时区与语言。
2. **权限位原样保留。** 这是选原生 SFTP 协议的直接收益（D-011）——
   `sftp` CLI 的 `ls -l` 会把权限位显示成 `-rw-******`，信息源本身已丢失。
3. **不跟随符号链接。** `lstat` 的结果决定类型；`link_target` 单独给出。
   跟随会让「这个条目是链接」这一事实消失。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.ssh.sftp_protocol import Attrs, S_IFMT, S_IFREG


@dataclass
class FileEntry:
    """目录中的一个条目。"""

    name: str
    path: str
    type: str
    size: int | None
    mtime: int | None
    atime: int | None
    mode: str | None
    permissions: int | None
    uid: int | None
    gid: int | None
    #: 符号链接的目标（仅当 type == "symlink" 时有值）。
    link_target: str | None = None
    #: 链接目标是否可解析（`stat` 成功）。断链在文件管理器里很常见，必须能表达。
    link_broken: bool | None = None

    @property
    def is_dir(self) -> bool:
        return self.type == "directory"

    def to_dict(self, *, include_path: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "size": self.size,
            "mtime": self.mtime,
            "mode": self.mode,
        }
        if include_path:
            payload["path"] = self.path
        # 可选字段只在有值时出现：让前端可以用 `if (entry.link_target)` 判断，
        # 而不是去比较 null 与空串两种「没有」的表示。
        if self.atime is not None:
            payload["atime"] = self.atime
        if self.permissions is not None:
            payload["permissions"] = self.permissions
        if self.uid is not None:
            payload["uid"] = self.uid
        if self.gid is not None:
            payload["gid"] = self.gid
        if self.link_target is not None:
            payload["link_target"] = self.link_target
            payload["link_broken"] = bool(self.link_broken)
        return payload

    @classmethod
    def from_attrs(cls, name: str, path: str, attrs: Attrs) -> "FileEntry":
        return cls(
            name=name,
            path=path,
            type=attrs.type,
            size=attrs.size,
            mtime=attrs.mtime,
            atime=attrs.atime,
            mode=attrs.mode_octal,
            permissions=attrs.permissions,
            uid=attrs.uid,
            gid=attrs.gid,
        )

    def is_regular_file(self) -> bool:
        """是否是可下载的普通文件。目录、符号链接、设备文件都不应走下载路径。"""
        return self.permissions is not None and (self.permissions & S_IFMT) == S_IFREG
