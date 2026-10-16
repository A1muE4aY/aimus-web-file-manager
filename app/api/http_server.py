"""HTTP 服务。

用标准库的 `ThreadingHTTPServer`。多线程不是「顺手」，而是必需的：
一次目录列举或一次下载会长时间占住连接，单线程服务会让界面在传输期间完全失去响应。
`SftpTransport` 内部有串行化锁，所以多线程不会让 SFTP 协议错位（见该模块的说明）。

## 静态资源与 MIME 类型

MIME 类型**手工列表**而不是 `mimetypes.guess_type`：后者在 Windows 上会读注册表，
某些装了开发工具的机器上会把 `.js` 映射成 `text/plain`。我们的响应带
`X-Content-Type-Options: nosniff`，浏览器会严格按声明的类型处理 ——
类型错了界面就整个不工作，而症状（脚本不执行）与原因（注册表）离得很远。
"""

from __future__ import annotations

import logging
import re
import socket
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from app import __version__
from app.api import handlers
from app.api.request import ApiRequest, text_body_limit
from app.api.responses import send_error, send_html, send_text
from app.api.security import new_session_token, verify_api_request
from app.api.tickets import DownloadTickets
from app.core.errors import AwfmError, InternalError, NotConnected, PathNotFound, ValidationError
from app.core.config import AppConfig
from app.services.connection_manager import ConnectionManager
from app.services.discovery import DiscoveryRegistry
from app.services.search import SearchRegistry

logger = logging.getLogger(__name__)

#: 手工维护的 MIME 表。见模块 docstring。
MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".map": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
}

#: 首页里注入令牌的锚点。
TOKEN_PLACEHOLDER = "<!--AWFM_TOKEN-->"

#: 唯一允许用「下载票据」代替会话令牌的路径（见 app/api/tickets.py）。
TICKET_PATH_RE = re.compile(r"^/api/connections/[^/]+/download$")

#: 回错误响应前最多花多久去丢弃没读完的请求体（见 _discard_request_body）。
DRAIN_TIMEOUT_SECONDS = 5.0


@dataclass
class AppContext:
    """一次服务运行期间共享的东西。"""

    config: AppConfig
    manager: ConnectionManager
    #: 在线虚拟机扫描。它要读配置（开关与各项上限），所以在 create_server 里
    #: 显式构造，而不是像搜索那样给一个无参默认值 —— 忘传会立刻报错，
    #: 不会悄悄跑在一个默认配置上。扫描同样跨请求存活（一个请求启动、
    #: 若干个请求轮询），所以和搜索一样挂在上下文里。
    discovery: DiscoveryRegistry
    token: str = field(default_factory=new_session_token)
    tickets: DownloadTickets = field(default_factory=DownloadTickets)
    #: 正在跑与刚跑完的文件检索。搜索要跨请求存活（启动一个请求、轮询若干请求），
    #: 所以登记处挂在这里，而不是放在某个处理函数的局部变量里。
    searches: SearchRegistry = field(default_factory=SearchRegistry)
    router: Any = None

    @property
    def static_dir(self) -> Path:
        return self.config.frontend_dir


class AwfmHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler_class, *, context: AppContext) -> None:
        self.context = context
        super().__init__(address, handler_class)

    def handle_error(self, request, client_address) -> None:  # pragma: no cover - 兜底
        # 默认实现会把整段 traceback 打到 stderr。对一个「过程透明」的工具来说
        # 这不是坏事，但走日志系统才能被写进 logs/awfm.log 并受脱敏过滤约束。
        logger.exception("处理请求时发生未捕获的异常（来自 %s）", client_address)


class AwfmRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"AWFM/{__version__}"
    sys_version = ""  # 不把 Python 版本写进 Server 头

    def version_string(self) -> str:
        """Server 头的值。

        基类实现是 server_version + " " + sys_version，留空 sys_version 会得到
        一个带尾随空格的 "AWFM/0.1.2 "；这里直接返回版本号本身。
        """
        return self.server_version

    def handle_one_request(self) -> None:
        """读取请求行并分发。

        浏览器关掉页面时留下的 keep-alive 连接会被对端重置，标准库此时从
        rfile.readline 抛 ConnectionResetError，socketserver 再打一整段
        traceback。这不是服务端错误，按正常断开处理即可（客户端提前走了）。
        """
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            self.close_connection = True

    # ------------------------------------------------------------------ 基础

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - 覆盖标准库签名
        logger.debug("%s - %s", self.address_string(), format % args)

    def log_error(self, format: str, *args) -> None:  # noqa: A002
        logger.warning("%s - %s", self.address_string(), format % args)

    @property
    def ctx(self) -> AppContext:
        return self.server.context  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ 方法分发

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_HEAD(self) -> None:
        self._dispatch("HEAD")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PATCH(self) -> None:
        self._dispatch("PATCH")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def do_OPTIONS(self) -> None:
        """一律拒绝预检。

        这是 CSRF 防线的一部分（见 `app/api/security.py`）：带自定义头的跨源请求
        会先发预检，预检失败浏览器就不会把真正的请求发出去。我们**故意**
        不返回任何 `Access-Control-Allow-*` 头。
        """
        logger.debug("拒绝一个 CORS 预检请求：%s", self.path)
        send_text(self, "本服务不接受跨源请求。\n", status=403)

    # ------------------------------------------------------------------ 主流程

    def _dispatch(self, method: str) -> None:
        req = ApiRequest(self)
        body_consumed = False
        try:
            if req.path.startswith("/api/"):
                # 浏览器自己发起的下载导航带不了自定义头，所以下载这一条路径
                # 允许用票据代替令牌。票据只能下它绑定的那一个文件，见 tickets.py。
                ticket_ok = bool(
                    TICKET_PATH_RE.match(req.path) and self.ctx.tickets.peek(req.query("ticket"))
                )
                verify_api_request(
                    self,
                    token=self.ctx.token,
                    path=req.path,
                    allow_lan=self.ctx.config.security.allow_lan,
                    ticket_ok=ticket_ok,
                )
                body_consumed = self._dispatch_api(req)
            else:
                self._dispatch_static(req)
        except AwfmError as exc:
            logger.info("%s %s -> %s（%s）", method, req.path, exc.code, exc.message)
            # 回错误之前先把没读完的请求体丢掉。客户端还在上传时直接关连接，
            # 刚写出去的响应会被一起冲掉，浏览器只会报「Failed to fetch」——
            # 用户看不到任何原因（v0.1.2 缺陷 D1）。丢不干净才关连接（finally）。
            if not body_consumed:
                body_consumed = self._discard_request_body(req)
            send_error(self, exc)
        except (BrokenPipeError, ConnectionResetError):
            logger.debug("客户端在响应前断开：%s %s", method, req.path)
            self.close_connection = True
        except Exception as exc:  # pragma: no cover - 兜底
            logger.exception("处理 %s %s 时发生未预期的异常", method, req.path)
            send_error(self, InternalError("服务内部错误。", detail=str(exc)))
        finally:
            # 没读完的请求体会让下一个请求从中间开始解析（keep-alive 错位）。
            # 与其去猜该丢多少字节，不如直接关掉这条连接。
            if not body_consumed and req.content_length > 0:
                self.close_connection = True

    def _discard_request_body(self, req: ApiRequest) -> bool:
        """把没读完的请求体读掉丢弃，好让错误响应顺利写出去。

        Returns:
            请求体是否已经处理干净（读完或本来就没有）。False 表示这条连接
            不能再复用，调用方应当关掉它。
        """
        if req.content_length <= 0:
            return True
        limit = text_body_limit(self.ctx.config.security.max_edit_bytes)
        try:
            sock = self.connection
            previous_timeout = sock.gettimeout()
            sock.settimeout(DRAIN_TIMEOUT_SECONDS)
        except OSError:  # pragma: no cover - 连接已经不可用
            return False
        try:
            return req.discard(limit)
        except OSError:
            # 客户端停止上传（或读超时）：与其一直等它，不如关掉这条连接。
            return False
        finally:
            try:
                sock.settimeout(previous_timeout)
            except OSError:  # pragma: no cover - 连接已经不可用
                pass

    def _dispatch_api(self, req: ApiRequest) -> bool:
        if req.method == "HEAD":
            method = "GET"
        else:
            method = req.method
        handler, params = self.ctx.router.match(method, req.path)
        if handler is None:
            if params:
                raise ValidationError(
                    "该路径不支持这个请求方法。",
                    detail=f"{req.method} {req.path}；允许的方法：{', '.join(params)}。",
                )
            from app.core.errors import PathNotFound

            raise PathNotFound("接口不存在。", detail=f"{req.method} {req.path}")
        try:
            result = handler(self.ctx, req, **params)
        except NotConnected as exc:
            # 传输层说「连接已断开」时，会话还停在 connected：不标死的话界面会
            # 一直显示「已连接」，用户点「重试」也只是对着同一个死会话重发
            # （v0.1.2 缺陷 D2）。路由的具名组是唯一同时知道 connection_id 的
            # 地方 —— sftp_transport 抛的 NotConnected 自己不带连接标识。
            self.ctx.manager.mark_broken(params.get("connection_id"), exc)
            raise
        del result
        # 处理函数要么自己写出了响应，要么走流式（也已开始写）。
        # 两种情况都把请求体读干净了（除了不需要读的 GET）。
        return True

    # ------------------------------------------------------------------ 静态资源

    def _dispatch_static(self, req: ApiRequest) -> None:
        if req.method not in ("GET", "HEAD"):
            raise ValidationError("静态资源只支持 GET。", detail=req.method)
        relative = req.path.lstrip("/")
        if not relative:
            relative = "index.html"
        self._serve_static(relative)

    def _serve_static(self, relative: str) -> None:
        base = self.ctx.static_dir
        if not base.is_dir():
            raise InternalError(
                "前端资源目录不存在。",
                detail=(
                    f"期望目录：{base}。"
                    "请确认 frontend/ 目录与程序一起被完整复制（便携版需要整个目录）。"
                ),
            )
        if "\\" in relative or "\x00" in relative:
            raise ValidationError("非法路径。")
        segments = relative.split("/")
        if any(seg in ("", ".", "..") for seg in segments):
            raise ValidationError("非法路径。", detail="路径中不允许出现 . 或 .. 分量。")

        candidate = base.joinpath(*segments)
        try:
            resolved = candidate.resolve(strict=True)
            base_resolved = base.resolve(strict=True)
        except OSError:
            # 文件不存在是 404 而不是 400：浏览器请求一个已经改名的 js 文件，
            # 返回 400 会让人以为是「请求格式不对」，而真正的原因是资源不在。
            raise PathNotFound("资源不存在。", detail=relative) from None
        # 第二道：即使符号链接把路径指到外面，也要挡住。
        if not _is_within(base_resolved, resolved):
            raise ValidationError("资源不在允许的目录内。", detail=relative)
        if not resolved.is_file():
            raise PathNotFound("资源不存在。", detail=relative)

        suffix = resolved.suffix.lower()
        content_type = MIME_TYPES.get(suffix)
        if content_type is None:
            raise ValidationError("不支持的文件类型。", detail=suffix or "(无扩展名)")

        if resolved.name == "index.html":
            text = resolved.read_text(encoding="utf-8")
            if TOKEN_PLACEHOLDER in text:
                meta = (
                    f'<meta name="awfm-token" content="{self.ctx.token}">'
                    f'<meta name="awfm-version" content="{__version__}">'
                )
                text = text.replace(TOKEN_PLACEHOLDER, meta)
            else:
                logger.warning(
                    "index.html 中没有找到 %s 占位符，前端将拿不到会话令牌。",
                    TOKEN_PLACEHOLDER,
                )
            send_html(self, text)
            return

        data = resolved.read_bytes()
        from app.api.responses import send_bytes

        send_bytes(self, data, content_type=content_type)


def _is_within(base: Path, target: Path) -> bool:
    try:
        target.relative_to(base)
    except ValueError:
        return False
    return True


def create_server(config: AppConfig, manager: ConnectionManager) -> AwfmHTTPServer:
    """按配置建好服务器（尚未开始监听）。"""
    context = AppContext(
        config=config,
        manager=manager,
        discovery=DiscoveryRegistry(config),
    )
    context.router = handlers.build_router()
    host = config.server.host
    port = config.server.port
    try:
        server = AwfmHTTPServer((host, port), AwfmRequestHandler, context=context)
    except OSError as exc:
        if getattr(exc, "errno", None) in (10048, 98, 48):  # WSAEADDRINUSE / EADDRINUSE
            raise InternalError(
                f"端口 {port} 已被占用。",
                detail=(
                    "可能是上一次的 AWFM 还在运行。请先关闭它，"
                    "或在配置中改用其它端口（server.port）。"
                ),
            ) from exc
        if getattr(exc, "errno", None) in (10049, 99, 49):  # 地址不可用
            raise InternalError(
                f"无法绑定到地址 {host}。",
                detail="请确认该地址属于本机，或把 server.host 改回 127.0.0.1。",
            ) from exc
        raise InternalError("启动 HTTP 服务失败。", detail=str(exc)) from exc
    server.timeout = 1.0
    return server


def serve(server: AwfmHTTPServer) -> None:  # pragma: no cover - 由 main 驱动
    server.serve_forever(poll_interval=0.5)
