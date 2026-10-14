"""远程路径校验与运算（安全关键模块）。

## 为什么这里**不做**词法 `..` 折叠

一个看似合理但**语义错误**的做法是把 `/home/a/link/../x` 词法折叠成 `/home/a/x`。
若 `link` 是指向 `/etc` 的符号链接，POSIX 的真实解析结果是 `/x` 而不是 `/home/a/x`。

SFTP v3 的路径由**服务端**按目标机文件系统语义解析（规划文档 §10.4 要求「正确处理
符号链接与远程 FS 路径语义」）。因此在客户端词法折叠 `..` 会**改变语义**，属于把
安全表演当成了安全。

本模块因此采取的策略是：

1. **只校验形式**，不改写语义（`validate_remote_path`）。
2. **需要规范形态时向服务端要** —— `REALPATH` 会返回服务端解析后的规范路径，
   它才是「当前目录」的真实身份（见 `app/ssh/sftp_client.py:realpath`）。
3. **需要做目录限制时，比较的是服务端返回的规范路径**，而不是客户端拼出来的字符串
   （`is_within_root`）。

## 字符集策略

除 `\\x00`（POSIX 路径中不合法）外，**不拒绝任何字符**，包括换行与其它控制字符。
理由：SFTP 协议用长度前缀字符串传输路径，能原样承载它们；把它们拒掉只会让这些文件
**永远无法被管理**，而不会带来任何安全收益（本项目从不把远程路径交给 shell —— 连接层
只用 `subprocess` 的 argv 列表，不经 `shell=True`）。

控制字符的真实风险在**日志注入**与 **HTTP 头注入**，因此分别由
`safe_for_log()` 与 `encode_content_disposition()` 处理，而不是在这里一刀切。
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote

from app.core.errors import ValidationError

#: 远程路径的最大字节长度。POSIX 未规定上限，Linux 的 PATH_MAX 是 4096。
MAX_PATH_BYTES = 4096

#: 单个路径分量（文件名）的最大字节长度。Linux NAME_MAX 是 255。
MAX_NAME_BYTES = 255

#: 日志中需要转义的控制字符（含 DEL）。用于防日志注入。
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _byte_len(value: str) -> int:
    """按 UTF-8 字节数计算长度。

    不能用 `len(str)`：`'中'` 的字符数是 1，字节数是 3。目标机的 NAME_MAX/PATH_MAX
    都是**字节**限制，按字符判断会放过超长名字、并让远端返回一个难以理解的 ERANGE/ENAMETOOLONG。
    """
    return len(value.encode("utf-8", errors="surrogatepass"))


def validate_remote_path(raw: object) -> str:
    """校验一个远程绝对路径的**形式**，返回原字符串（不做语义改写）。

    Raises:
        ValidationError: 不是字符串、为空、不是绝对路径、含 NUL、超长。
    """
    if not isinstance(raw, str):
        raise ValidationError("路径必须是字符串。")
    path = raw
    if path == "":
        raise ValidationError("路径不能为空。")
    if "\x00" in path:
        raise ValidationError("路径不能包含 NUL 字符。")
    if not path.startswith("/"):
        # 相对路径会让「当前目录」变成隐式状态，服务端与客户端可能对它有不同理解，
        # 从而产生难以复现的行为。一律要求绝对路径，由服务端 REALPATH 给出规范形态。
        raise ValidationError("路径必须是绝对路径（以 / 开头）。")
    if _byte_len(path) > MAX_PATH_BYTES:
        raise ValidationError(f"路径过长（超过 {MAX_PATH_BYTES} 字节）。")
    return path


def validate_remote_name(raw: object) -> str:
    """校验一个**文件名分量**（用于新建目录、重命名）。

    与 `validate_remote_path` 的区别：这里禁止 `/` 与 `..`，
    因为它们会让「一个新名字」变成「一次目录穿越」。

    Raises:
        ValidationError
    """
    if not isinstance(raw, str):
        raise ValidationError("名称必须是字符串。")
    name = raw
    if name == "":
        raise ValidationError("名称不能为空。")
    if name in (".", ".."):
        raise ValidationError("名称不能是 . 或 ..。")
    if "/" in name:
        raise ValidationError("名称不能包含 /（它必须是一个单独的分量，不能是路径）。")
    if "\x00" in name:
        raise ValidationError("名称不能包含 NUL 字符。")
    if _byte_len(name) > MAX_NAME_BYTES:
        raise ValidationError(f"名称过长（超过 {MAX_NAME_BYTES} 字节）。")
    return name


def parent_remote_path(path: str) -> str | None:
    """返回父目录；已在根目录时返回 `None`。

    只能对**服务端 REALPATH 返回的规范路径**使用 —— 对含 `..` 或符号链接的原始
    输入做字符串截断会得到错误的父目录。
    """
    if not path or path == "/":
        return None
    trimmed = path.rstrip("/")
    if trimmed == "":
        return None
    idx = trimmed.rfind("/")
    if idx <= 0:
        return "/"
    return trimmed[:idx]


def join_remote_path(base: str, name: str) -> str:
    """把文件名拼到目录路径上。`name` 必须是单个分量（先经 `validate_remote_name`）。"""
    if base == "" or base == "/":
        return "/" + name
    return base.rstrip("/") + "/" + name


def split_remote_path(path: str) -> list[str]:
    """把规范路径拆成非空分量列表。`/` → `[]`。"""
    return [part for part in path.split("/") if part]


def is_within_root(root: str, path: str) -> bool:
    """判断 `path` 是否位于 `root` 之内（含 `root` 自身）。

    **必须传入服务端 REALPATH 的结果**：只有符号链接已被解析的规范路径，
    这个比较才有意义。对客户端原始字符串比较会漏掉「root 内某个符号链接指向 root 外」
    这一类逃逸。
    """
    # 含 .. 分量的路径一律判 False（fail-closed）。调用方本应传 REALPATH 结果，
    # 但真出现 .. 时说明规范化那一步被漏掉了 —— 此时按字符串前缀比较会放行
    # /home/a/../b 这类看起来在 root 内、实际在 root 外的路径。
    if any(part == ".." for part in path.split("/")):
        return False
    if root in ("", "/"):
        return path.startswith("/")
    r = root.rstrip("/")
    if path == r:
        return True
    return path.startswith(r + "/")


def safe_for_log(value: str, *, limit: int = 300) -> str:
    """把任意字符串转成可安全写入单行日志的形式。

    攻击场景：远程文件名可以是 `evil\\n2026-01-01 ERROR 认证成功`。
    直接插进日志会**伪造出一条不存在的日志行**，让故障排查时看到假象。
    这里把控制字符转义成 `\\xNN`，并截断超长值。
    """
    text = _CONTROL_RE.sub(lambda m: "\\x%02x" % ord(m.group()), value)
    if len(text) > limit:
        text = text[:limit] + f"...(+{len(text) - limit})"
    return text


def percent_encode_segment(value: str) -> str:
    """把文件名编码成可放进 URL 路径的形式（保留 `/` 作为分隔符的版本见下）。"""
    return quote(value, safe="")


def encode_content_disposition(filename: str) -> str:
    """构造 `Content-Disposition` 头，同时兼容 RFC 5987 与老客户端。

    两段式的原因：`filename=` 只允许 ASCII，非 ASCII 文件名必须走
    `filename*=`（RFC 5987 的 `UTF-8''<百分号编码>`）。只发后者会让老浏览器拿到
    乱码文件名；只发前者则中文名直接丢字。两段都发，现代浏览器优先取 `filename*`。

    换行必须被百分号编码 —— 否则会构成 **HTTP 响应头注入**（响应拆分的经典入口）。
    `quote()` 默认就把控制字符编码掉，这里额外把 ASCII 回退名里的引号与反斜杠剔除。
    """
    ascii_fallback = filename.encode("ascii", errors="replace").decode("ascii")
    ascii_fallback = ascii_fallback.replace("\\", "_").replace('"', "_")
    ascii_fallback = _CONTROL_RE.sub("_", ascii_fallback) or "download"
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"


def normalize_unicode(name: str) -> str:
    """NFC 规范化，**仅用于比较与显示**，绝不用于改写实际路径。

    同一个视觉文件名在 macOS(HFS+) 上是 NFD、在 Linux 上是 NFC，逐字节比较会不相等。
    搜索/去重时用本函数归一，实际访问远端时仍用原始字节序列。
    """
    return unicodedata.normalize("NFC", name)
