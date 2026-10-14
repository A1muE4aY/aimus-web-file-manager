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
MAX_JSON_BODY = 1024 * 1024


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

    def json(self) -> dict[str, Any]:
        """读取并解析 JSON 请求体。空请求体视为 `{}`。"""
        if self._json_loaded:
            assert self._json_cache is not None
            return self._json_cache
        length = self.content_length
        if length == 0:
            self._json_cache = {}
            self._json_loaded = True
            return self._json_cache
        if length > MAX_JSON_BODY:
            raise PayloadTooLarge(
                "请求体过大。",
                detail=f"{length} 字节，上限 {MAX_JSON_BODY} 字节。",
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
