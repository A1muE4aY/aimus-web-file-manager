"""API 处理函数。

约定：处理函数**自己负责把响应写出去**（而不是 return 一个对象让框架去序列化）。
原因是下载与上传是流式的 —— 它们必须在响应已经开始之后继续从 SFTP 读数据，
一个「先构造完整响应再发送」的框架结构在这里放不下。
"""

from __future__ import annotations

import logging
from typing import Any

from app import __version__
from app.api.request import ApiRequest
from app.api.responses import begin_stream, send_ok
from app.core.errors import AwfmError, Unauthorized, ValidationError
from app.models.connection import Connection
from app.services import filesystem, search as search_service, transfer

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------- 服务与元信息


def health(ctx, req: ApiRequest) -> None:
    """健康检查。**免令牌**，便于用 curl 确认服务活着。不返回任何敏感信息。"""
    send_ok(
        req.handler,
        {
            "status": "ok",
            "version": __version__,
            "connections": len(ctx.config.connections),
        },
    )


def session_info(ctx, req: ApiRequest) -> None:
    """前端启动时拉一次，拿到版本与服务端能力开关。"""
    send_ok(
        req.handler,
        {
            "version": __version__,
            "host_key_policy": ctx.config.security.host_key_policy,
            "max_upload_bytes": ctx.config.security.max_upload_bytes,
            "max_download_bytes": ctx.config.security.max_download_bytes,
            "allow_lan": ctx.config.security.allow_lan,
        # 主机密钥变化时界面要明确告诉用户去改哪个文件（不提供一键接受）。
        "known_hosts_path": ctx.config.known_hosts_path,
        },
    )


# --------------------------------------------------------------------- 连接管理


def list_connections(ctx, req: ApiRequest) -> None:
    send_ok(req.handler, {"connections": ctx.manager.list_connections()})


def get_connection(ctx, req: ApiRequest, connection_id: str) -> None:
    # 必须走 connection_detail：get_connection 返回的是 Connection 对象，
    # 交给 json.dumps(default=str) 会被序列化成 repr 字符串。
    send_ok(req.handler, {"connection": ctx.manager.connection_detail(connection_id)})


def create_connection(ctx, req: ApiRequest) -> None:
    payload = req.json()
    if not isinstance(payload, dict):
        raise ValidationError("请求体必须是一个 JSON 对象。")
    result = ctx.manager.create_connection(payload)
    send_ok(req.handler, {"connection": result}, status=201)


def update_connection(ctx, req: ApiRequest, connection_id: str) -> None:
    payload = req.json()
    result = ctx.manager.update_connection(connection_id, payload)
    send_ok(req.handler, {"connection": result})


def delete_connection(ctx, req: ApiRequest, connection_id: str) -> None:
    ctx.searches.cancel_for_connection(connection_id)
    result = ctx.manager.delete_connection(connection_id)
    send_ok(req.handler, {"deleted": result})


def connect(ctx, req: ApiRequest, connection_id: str) -> None:
    payload = req.json()
    password = payload.get("password", "")
    if password is None:
        password = ""
    if not isinstance(password, str):
        raise ValidationError("password 必须是字符串。")
    result = ctx.manager.connect(connection_id, password)
    # 密码只在这里被使用一次，之后仅存在于 ssh 子进程的认证阶段。
    # 不写进日志（日志过滤器还会再过一道，见 utils/redact.py）。
    del payload
    send_ok(req.handler, {"connection": result})


def disconnect(ctx, req: ApiRequest, connection_id: str) -> None:
    # 断开之前先停掉这条连接上还在跑的搜索：否则工作线程会一直撞在
    # 「连接未建立」上，用户看到的失败原因也不是他刚做的那个动作。
    ctx.searches.cancel_for_connection(connection_id)
    result = ctx.manager.disconnect(connection_id)
    send_ok(req.handler, {"connection": result})


def connection_status(ctx, req: ApiRequest, connection_id: str) -> None:
    send_ok(req.handler, {"connection": ctx.manager.session_status(connection_id)})


def list_host_keys(ctx, req: ApiRequest, connection_id: str) -> None:
    keys = ctx.manager.trusted_keys(connection_id)
    send_ok(req.handler, {"keys": keys, "policy": ctx.config.security.host_key_policy})


def trust_host_key(ctx, req: ApiRequest, connection_id: str) -> None:
    payload = req.json()
    key_type = payload.get("key_type")
    fingerprint = payload.get("fingerprint")
    if not isinstance(key_type, str) or not key_type:
        raise ValidationError("缺少 key_type。")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise ValidationError("缺少 fingerprint。")
    result = ctx.manager.trust_host_key(connection_id, key_type, fingerprint)
    send_ok(req.handler, result)


# --------------------------------------------------------------------- 文件浏览


def _session(ctx, connection_id: str):
    return ctx.manager.session(connection_id)


def list_files(ctx, req: ApiRequest, connection_id: str) -> None:
    session = _session(ctx, connection_id)
    path = req.require_query("path")
    send_ok(req.handler, filesystem.list_directory(session, path))


def stat_file(ctx, req: ApiRequest, connection_id: str) -> None:
    session = _session(ctx, connection_id)
    path = req.require_query("path")
    follow = req.query_bool("follow", True)
    send_ok(req.handler, filesystem.stat_path(session, path, follow=follow))


def preview_file(ctx, req: ApiRequest, connection_id: str) -> None:
    session = _session(ctx, connection_id)
    path = req.require_query("path")
    max_bytes = req.query_int("max_bytes", filesystem.DEFAULT_PREVIEW_BYTES)
    max_bytes = max(1, min(max_bytes, filesystem.DEFAULT_PREVIEW_BYTES))
    send_ok(req.handler, filesystem.read_text_preview(session, path, max_bytes=max_bytes))


# --------------------------------------------------------------------- 文件检索


def start_search(ctx, req: ApiRequest, connection_id: str) -> None:
    """在当前目录及其子目录里按名称检索。

    搜索在服务端后台线程里跑（见 app/services/search.py），这里立刻返回初始快照，
    前端按 `GET /api/searches/<id>` 轮询进度。用 202 表示「已受理、尚未完成」。
    """
    payload = req.json()
    path = payload.get("path")
    query = payload.get("query")
    # 形状检查放在找会话之前：参数缺胳膊少腿是调用方自己的问题，不该先去看连接
    # 状态 —— 否则同一个畸形请求会在「没连接」和「有连接」时给出两个不同的错误。
    if not isinstance(path, str) or not path:
        raise ValidationError("缺少 path。")
    if not isinstance(query, str) or not query:
        raise ValidationError("缺少 query。")
    session = _session(ctx, connection_id)
    started = ctx.searches.start(session, path=path, query=query)
    send_ok(req.handler, {"search": started.snapshot()}, status=202)


def search_status(ctx, req: ApiRequest, search_id: str) -> None:
    send_ok(req.handler, {"search": ctx.searches.snapshot(search_id)})


def cancel_search(ctx, req: ApiRequest, search_id: str) -> None:
    send_ok(req.handler, {"search": ctx.searches.cancel(search_id)})


# --------------------------------------------------------------------- 传输


def download_ticket(ctx, req: ApiRequest, connection_id: str) -> None:
    """用一次带令牌的 POST 换一张只能下这一个文件的票据。"""
    ctx.manager.get_connection(connection_id)  # 连接不存在就直接报错
    payload = req.json()
    path = payload.get("path")
    if not isinstance(path, str) or not path:
        raise ValidationError("缺少 path。")
    ticket = ctx.tickets.issue(connection_id, path)
    from urllib.parse import quote

    send_ok(
        req.handler,
        {
            "ticket": ticket,
            "url": (
                f"/api/connections/{quote(connection_id, safe='')}/download"
                f"?ticket={quote(ticket, safe='')}&path={quote(path, safe='')}"
            ),
            "expires_in": 120,
        },
    )


def download_file(ctx, req: ApiRequest, connection_id: str) -> None:
    # 票据路径：路由层已经确认票据存在，这里再确认它确实绑定了这个连接与这个路径。
    ticket = req.query("ticket")
    if ticket is not None and not ctx.tickets.verify(ticket, connection_id, req.query("path") or ""):
        raise Unauthorized(
            "下载票据无效、已过期，或与请求的文件不匹配。",
            detail="请回到界面重新点击下载。",
        )
    session = _session(ctx, connection_id)
    path = req.require_query("path")
    prepared = transfer.prepare_download(
        session, path, max_bytes=ctx.config.security.max_download_bytes
    )
    handler = req.handler
    begin_stream(
        handler,
        content_type="application/octet-stream",
        content_length=prepared["size"],
        extra=[
            ("Content-Disposition", prepared["content_disposition"]),
            ("X-AWFM-Path", _ascii_header_value(prepared["path"])),
        ],
    )
    sent = 0
    try:
        for chunk in prepared["chunks"]():
            handler.wfile.write(chunk)
            sent += len(chunk)
    except (BrokenPipeError, ConnectionResetError):
        # 用户取消了下载。这不是错误，但必须让 SFTP 句柄被关掉 ——
        # 生成器的 finally 会在 GC 时执行；显式关闭更及时。
        logger.info("下载被客户端中断：%s（已发送 %d 字节）", prepared["path"], sent)
        handler.close_connection = True
    else:
        logger.info("下载完成 %s（%d 字节）", prepared["path"], sent)
        if sent != prepared["size"]:
            # 目标机上的文件在传输过程中被改小了。响应头里的 Content-Length
            # 是当初 stat 出来的值，此刻已经对不上 —— 只能断开连接让浏览器
            # 知道「这次下载不完整」，而不是安静地交出一个截断的文件。
            logger.warning(
                "下载字节数与 stat 结果不一致：%s（声明 %d，实际 %d）",
                prepared["path"], prepared["size"], sent,
            )
            handler.close_connection = True


def upload_file(ctx, req: ApiRequest, connection_id: str) -> None:
    session = _session(ctx, connection_id)
    directory = req.require_query("path")
    filename = req.require_query("name")
    overwrite = req.query_bool("overwrite", False)
    result = transfer.receive_upload(
        session,
        directory,
        filename,
        req.rfile,
        content_length=req.content_length,
        max_bytes=ctx.config.security.max_upload_bytes,
        overwrite=overwrite,
    )
    send_ok(req.handler, result, status=201 if not result["overwritten"] else 200)


def check_upload(ctx, req: ApiRequest, connection_id: str) -> None:
    session = _session(ctx, connection_id)
    directory = req.require_query("path")
    filename = req.require_query("name")
    send_ok(req.handler, transfer.check_upload_target(session, directory, filename))


def _ascii_header_value(value: str) -> str:
    """HTTP 头只能是 latin-1 字节。含非 ASCII 的路径要百分号编码，
    否则 `send_header` 会直接抛 `UnicodeEncodeError`。"""
    from urllib.parse import quote

    return quote(value, safe="/")


#: 处理函数签名 `(ctx, req, **params)`。`AwfmError` 由服务器统一转成错误响应。
ENDPOINTS: list[tuple[str, str, Any]] = [
    ("GET", r"/api/health", health),
    ("GET", r"/api/session", session_info),
    ("GET", r"/api/connections", list_connections),
    ("POST", r"/api/connections", create_connection),
    ("GET", r"/api/connections/(?P<connection_id>[^/]+)", get_connection),
    ("PATCH", r"/api/connections/(?P<connection_id>[^/]+)", update_connection),
    ("DELETE", r"/api/connections/(?P<connection_id>[^/]+)", delete_connection),
    ("POST", r"/api/connections/(?P<connection_id>[^/]+)/connect", connect),
    ("POST", r"/api/connections/(?P<connection_id>[^/]+)/disconnect", disconnect),
    ("GET", r"/api/connections/(?P<connection_id>[^/]+)/status", connection_status),
    ("GET", r"/api/connections/(?P<connection_id>[^/]+)/host-keys", list_host_keys),
    ("POST", r"/api/connections/(?P<connection_id>[^/]+)/host-keys/trust", trust_host_key),
    ("GET", r"/api/connections/(?P<connection_id>[^/]+)/files", list_files),
    ("GET", r"/api/connections/(?P<connection_id>[^/]+)/stat", stat_file),
    ("GET", r"/api/connections/(?P<connection_id>[^/]+)/preview", preview_file),
    ("POST", r"/api/connections/(?P<connection_id>[^/]+)/download-ticket", download_ticket),
    ("GET", r"/api/connections/(?P<connection_id>[^/]+)/download", download_file),
    ("POST", r"/api/connections/(?P<connection_id>[^/]+)/upload", upload_file),
    ("GET", r"/api/connections/(?P<connection_id>[^/]+)/upload-check", check_upload),
    ("POST", r"/api/connections/(?P<connection_id>[^/]+)/search", start_search),
    ("GET", r"/api/searches/(?P<search_id>[0-9a-f]+)", search_status),
    ("DELETE", r"/api/searches/(?P<search_id>[0-9a-f]+)", cancel_search),
]


def build_router():
    from app.api.router import Router

    router = Router()
    for method, pattern, func in ENDPOINTS:
        router.add(method, pattern, func)
    return router


__all__ = ["ENDPOINTS", "build_router"]
