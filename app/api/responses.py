"""HTTP 响应构造。

所有响应都经这里发出，好处是**错误格式只有一处定义**：
`{"ok": false, "error": {"code", "message", "detail"?}}`。
前端因此只需要实现一套错误处理，而不是每个接口猜一次。

## 响应头是安全边界的一部分

- `Content-Security-Policy`：本项目的界面完全离线，不需要加载任何外部资源，
  所以 CSP 可以收得很紧（`default-src 'self'`）。这是「前端不含在线资源」
  这条设计约束在浏览器侧的**强制**执行，而不只是靠代码审查。
- `X-Content-Type-Options: nosniff`：防止浏览器把上传的文本文件当脚本执行。
- `Cache-Control: no-store`：文件列表与配置属敏感内容，不进浏览器缓存。
"""

from __future__ import annotations

import json
import logging
import socket
from http import HTTPStatus
from typing import Any

from app.core.errors import AwfmError

logger = logging.getLogger(__name__)

#: 允许的响应体最大长度（仅用于内存里的 JSON 响应；文件走流式）。
MAX_JSON_BYTES = 8 * 1024 * 1024


def security_headers(*, is_html: bool = False) -> list[tuple[str, str]]:
    headers = [
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "no-referrer"),
        ("X-Frame-Options", "DENY"),
        ("Cache-Control", "no-store"),
    ]
    if is_html:
        headers.append((
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "font-src 'self'; connect-src 'self'; form-action 'none'; frame-ancestors 'none'; "
            "base-uri 'none'; object-src 'none'",
        ))
    else:
        headers.append(("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"))
    return headers


def _send_common(handler, status: int, headers: list[tuple[str, str]], *, body: bytes = b"",
                 content_type: str | None = None, extra: list[tuple[str, str]] | None = None) -> None:
    handler.send_response(status)
    for key, value in headers:
        handler.send_header(key, value)
    if content_type:
        handler.send_header("Content-Type", content_type)
    for key, value in (extra or []):
        handler.send_header(key, value)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    if body:
        try:
            handler.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            # 客户端在响应写完前就断了（例如用户取消了下载）。
            # 这不是服务端错误，记一条 debug 即可。
            logger.debug("客户端提前断开，响应未写完")


def send_json(handler, payload: Any, *, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    if len(body) > MAX_JSON_BYTES:  # pragma: no cover - 防御性
        send_error(handler, AwfmError("响应体过大。", detail=f"{len(body)} 字节"))
        return
    _send_common(handler, status, security_headers(), body=body,
                 content_type="application/json; charset=utf-8")


def send_ok(handler, data: Any = None, *, status: int = 200, **extra: Any) -> None:
    payload: dict[str, Any] = {"ok": True}
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    send_json(handler, payload, status=status)


def send_error(handler, error: AwfmError) -> None:
    status = error.http_status
    try:
        HTTPStatus(status)
    except ValueError:  # pragma: no cover - 防御性
        status = 500
    send_json(handler, error.to_dict(), status=status)


def send_text(handler, text: str, *, status: int = 200, content_type: str = "text/plain; charset=utf-8",
              extra: list[tuple[str, str]] | None = None) -> None:
    _send_common(handler, status, security_headers(), body=text.encode("utf-8"),
                 content_type=content_type, extra=extra)


def send_html(handler, html: str, *, status: int = 200) -> None:
    _send_common(handler, status, security_headers(is_html=True), body=html.encode("utf-8"),
                 content_type="text/html; charset=utf-8")


def send_bytes(handler, data: bytes, *, status: int = 200, content_type: str = "application/octet-stream",
               extra: list[tuple[str, str]] | None = None) -> None:
    _send_common(handler, status, security_headers(), body=data, content_type=content_type, extra=extra)


def begin_stream(handler, *, content_type: str, content_length: int | None,
                 extra: list[tuple[str, str]] | None = None) -> None:
    """开始一个流式响应体。

    `Content-Length` 已知时必须给出：否则浏览器只能靠连接关闭判断结束，
    下载进度条也就没有总数可显示。
    """
    handler.send_response(200)
    for key, value in security_headers():
        handler.send_header(key, value)
    handler.send_header("Content-Type", content_type)
    if content_length is not None:
        handler.send_header("Content-Length", str(content_length))
    else:
        handler.send_header("Connection", "close")
    for key, value in (extra or []):
        handler.send_header(key, value)
    handler.end_headers()
