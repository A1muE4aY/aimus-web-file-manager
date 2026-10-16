"""请求包装。

把 `http.server` 那套「自己解 URL、自己读 body、自己判 Content-Type」的琐事
收在一处，处理函数只面对一个干净的接口。
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from app.core.errors import PayloadTooLarge, ValidationError

logger = logging.getLogger(__name__)

#: JSON 请求体的上限。配置与连接信息都是小对象，
#: 给到 1 MiB 已经远超实际需要 —— 上限存在的意义是「不给一个坏客户端
#: 无限读内存的机会」，而不是精确够用。
#:
#: 在线编辑（PUT .../text）那条路径不适用这个数字，改用 `text_body_limit()`：
#: 它的正文长度由 security.max_edit_bytes 决定，两处必须一致。
MAX_JSON_BODY = 1024 * 1024

#: JSON 转义的最坏情况：一个 1 字节的 UTF-8 字符（控制字符）写成 `\u00XX`
#: 是 6 个字节。所以「正文字节数 × 6」是任何合法请求体的硬上界。
JSON_ESCAPE_WORST_CASE = 6

#: 除正文以外那些零碎字段（path / base_sha256 / newline / keep_bom…）的余量。
JSON_TEXT_SLACK = 64 * 1024


def text_body_limit(max_edit_bytes: int) -> int:
    """在线编辑这条路径允许的请求体上限。

    传输层的上限必须**跟着业务上限走**：能打开多大的文件由
    `security.max_edit_bytes`（默认 2 MiB）决定，而 JSON 传输层原来固定
    1 MiB —— 于是 1~2 MiB 的文件「打得开、存不回去」，保存时被判成请求体过大
    （验收遗留事项③，v0.1.2 缺陷 D1）。这里按正文上限反推传输层上限，
    两者不会再打架。
    """
    return max(MAX_JSON_BODY, int(max_edit_bytes) * JSON_ESCAPE_WORST_CASE + JSON_TEXT_SLACK)


class ApiRequest:
    """一次 API 请求。"""

    def __init__(self, handler) -> None:
        self.handler = handler
        self.method: str = handler.command.upper()
        raw = handler.path or "/"
        parts = urlsplit(raw)
        # 路径是 UTF-8 百分号编码的。http.server 用 latin-1 解过一遍原始字节，
        # 这里先还原字节再按 UTF-8 解 —— 否则含中文的路径会变成乱码。
        self.path: str = unquote(parts.path, encoding="utf-8", errors="replace")
        self._query = parse_qs(parts.query, keep_blank_values=True)
        self._json_cache: dict[str, Any] | None = None
        self._json_loaded = False

    # ------------------------------------------------------------------ 查询参数

    def query(self, name: str, default: str | None = None) -> str | None:
        values = self._query.get(name)
        if not values:
            return default
        return values[0]

    def require_query(self, name: str) -> str:
        value = self.query(name)
        if value is None or value == "":
            raise ValidationError(f"缺少必需的查询参数 {name}。")
        return value

    def query_bool(self, name: str, default: bool = False) -> bool:
        raw = self.query(name)
        if raw is None or raw == "":
            return default
        lowered = raw.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
        raise ValidationError(f"查询参数 {name} 的值不是布尔值。", detail=f"收到 {raw!r}。")

    def query_int(self, name: str, default: int = 0) -> int:
        raw = self.query(name)
        if raw is None or raw == "":
            return default
        try:
            return int(raw, 10)
        except ValueError:
            raise ValidationError(f"查询参数 {name} 的值不是整数。", detail=f"收到 {raw!r}。") from None

    # ------------------------------------------------------------------ 请求体

    @property
    def content_length(self) -> int:
        raw = self.handler.headers.get("Content-Length")
        if raw is None:
            return 0
        try:
            value = int(raw, 10)
        except ValueError:
            raise ValidationError("Content-Length 不是合法整数。", detail=repr(raw)) from None
        if value < 0:
            raise ValidationError("Content-Length 不能为负数。")
        return value

    @property
    def rfile(self):
        return self.handler.rfile

    def discard(self, limit: int) -> bool:
        """把没读完的请求体读掉并丢弃，为**回错误响应**让路。

        拒绝一个带着请求体的请求时，如果我们直接回错误再关连接，客户端还在
        上传当中：连接一关，刚写出去的响应会被一起冲掉，浏览器只会报
        「Failed to fetch」，界面上看不到任何原因（v0.1.2 缺陷 D1 的另一半）。
        所以先尽力把请求体丢干净，再回错误。

        Args:
            limit: 最多愿意丢弃多少字节。声明的请求体比它还大时不读 —— 那是
                坏客户端，与其为它读无限多的字节，不如按老办法关掉连接。

        Returns:
            是否丢弃干净。False 表示调用方应当关闭这条连接。
        """
        length = self.content_length
        if length <= 0:
            return True
        if length > limit:
            return False
        return len(self.rfile.read(length)) == length

    def json(self, *, max_bytes: int | None = None) -> dict[str, Any]:
        """读取并解析 JSON 请求体。空请求体视为 `{}`。

        Args:
            max_bytes: 这次请求允许的请求体上限，默认 `MAX_JSON_BODY`。
                在线编辑那条路径要传 `text_body_limit(...)`：它的正文本来就
                比普通 JSON 大得多。
        """
        if self._json_loaded:
            assert self._json_cache is not None
            return self._json_cache
        limit = MAX_JSON_BODY if max_bytes is None else int(max_bytes)
        length = self.content_length
        if length == 0:
            self._json_cache = {}
            self._json_loaded = True
            return self._json_cache
        if length > limit:
            raise PayloadTooLarge(
                "请求体过大。",
                detail=f"{length} 字节，上限 {limit} 字节。",
            )
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ValidationError("请求体不完整：请求提前结束。")
        if not raw.strip():
            self._json_cache = {}
            self._json_loaded = True
            return self._json_cache
        try:
            data = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError:
            raise ValidationError("请求体不是合法的 UTF-8 文本。") from None
        except json.JSONDecodeError as exc:
            raise ValidationError(
                "请求体不是合法的 JSON。",
                detail=f"第 {exc.lineno} 行第 {exc.colno} 列：{exc.msg}",
            ) from None
        if not isinstance(data, dict):
            raise ValidationError("请求体必须是一个 JSON 对象。", detail=f"收到 {type(data).__name__}。")
        self._json_cache = data
        self._json_loaded = True
        return data
