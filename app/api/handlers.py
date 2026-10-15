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
from app.services import (
    editor,
    fileops,
    filesystem,
    search as search_service,
    transfer,
)

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
            "max_edit_bytes": ctx.config.security.max_edit_bytes,
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


# --------------------------------------------------------------- 虚拟机发现


def discovery_environment(ctx, req: ApiRequest) -> None:
    """发现能力的**只读概览**：有哪些来源可用、读不到的原因是什么。

    不读大文件、不探测任何地址，所以页面加载时就可以调它来决定扫描入口是否可用。
    发现功能整体关闭时这里返回 enabled=false，前端据此把入口藏起来（服务端仍然
    会拒绝启动扫描 —— 界面只是提示，判断在服务端）。
    """
    send_ok(req.handler, {"environment": ctx.discovery.environment()})


def start_discovery(ctx, req: ApiRequest) -> None:
    """发起一次扫描。

    扫描只读本机虚拟化软件留下的信息与有限范围内的地址探测（见
    app/services/discovery.py 与决策 D-018），**不会**创建连接、不会信任主机指纹、
    也不会修改任何系统网络配置。202 表示「已受理、尚未完成」。
    """
    started = ctx.discovery.start()
    send_ok(req.handler, {"scan": started.snapshot()}, status=202)


def discovery_status(ctx, req: ApiRequest, scan_id: str) -> None:
    send_ok(req.handler, {"scan": ctx.discovery.snapshot(scan_id)})


def cancel_discovery(ctx, req: ApiRequest, scan_id: str) -> None:
    send_ok(req.handler, {"scan": ctx.discovery.cancel(scan_id)})


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


# --------------------------------------------------------------------- 在线编辑


def _edit_limit(ctx) -> int:
    """在线编辑的单次字节上限（security.max_edit_bytes）。"""
    return ctx.config.security.max_edit_bytes


def read_text(ctx, req: ApiRequest, connection_id: str) -> None:
    """读取远端文本文件，连同冲突检测的基线（sha256 / mtime）一起交给前端。"""
    session = _session(ctx, connection_id)
    path = req.require_query("path")
    limit = _edit_limit(ctx)
    send_ok(
        req.handler,
        {
            "file": editor.read_text_file(session, path, max_bytes=limit),
            "limits": editor.describe_limits(limit),
        },
    )


def save_text(ctx, req: ApiRequest, connection_id: str) -> None:
    """把编辑器里的内容写回远端。

    写权限与内容冲突都在服务端重新确认（见 app/services/editor.py）：
    前端按钮是否可用只是提示，不能当成授权。
    """
    payload = req.json()
    if not isinstance(payload, dict):
        raise ValidationError("请求体必须是一个 JSON 对象。")
    path = payload.get("path")
    text = payload.get("text")
    base_sha256 = payload.get("base_sha256", "")
    base_mtime = payload.get("base_mtime")
    newline = payload.get("newline", "")
    keep_bom = payload.get("keep_bom", False)
    # 与 start_search 同一条纪律：形状检查先于找会话，畸形请求的错误不该随连接状态变化。
    if not isinstance(path, str) or not path:
        raise ValidationError("缺少 path。")
    if not isinstance(text, str):
        raise ValidationError("缺少 text（要保存的内容），或它不是字符串。")
    if not isinstance(base_sha256, str):
        raise ValidationError("base_sha256 必须是字符串。")
    if base_mtime is not None and (isinstance(base_mtime, bool) or not isinstance(base_mtime, int)):
        raise ValidationError("base_mtime 必须是整数。")
    if newline not in ("", "lf", "crlf", "cr"):
        raise ValidationError(
            "newline 取值非法。",
            detail="只允许 lf、crlf、cr，或留空表示沿用文件当前的换行风格。",
        )
    if not isinstance(keep_bom, bool):
        raise ValidationError("keep_bom 必须是布尔值。")
    session = _session(ctx, connection_id)
    result = editor.save_text_file(
        session,
        path,
        text,
        base_sha256=base_sha256,
        base_mtime=base_mtime,
        newline=newline,
        keep_bom=keep_bom,
        max_bytes=_edit_limit(ctx),
    )
    send_ok(req.handler, {"file": result})


# --------------------------------------------------------------------- 文件操作


def rename_entry(ctx, req: ApiRequest, connection_id: str) -> None:
    """重命名：只改同一目录内的名字，不做跨目录移动。"""
    payload = req.json()
    path = payload.get("path")
    new_name = payload.get("new_name")
    if not isinstance(path, str) or not path:
        raise ValidationError("缺少 path。")
    if not isinstance(new_name, str) or not new_name:
        raise ValidationError("缺少 new_name。")
    session = _session(ctx, connection_id)
    send_ok(req.handler, {"entry": fileops.rename_entry(session, path, new_name)})


def delete_entry(ctx, req: ApiRequest, connection_id: str) -> None:
    """删除文件、符号链接或目录。

    recursive 必须由调用方显式给出 —— 目录非空而没带它时服务端拒绝执行：
    这是删除这类不可撤销操作的兜底，界面上漏了一次确认，服务端还有一道。
    """
    payload = req.json()
    path = payload.get("path")
    recursive = payload.get("recursive", False)
    if not isinstance(path, str) or not path:
        raise ValidationError("缺少 path。")
    if not isinstance(recursive, bool):
        raise ValidationError("recursive 必须是布尔值。")
    session = _session(ctx, connection_id)
    send_ok(req.handler, {"deleted": fileops.delete_entry(session, path, recursive=recursive)})


def compress_entry(ctx, req: ApiRequest, connection_id: str) -> None:
    """把远端条目打包成 .tar.gz。

    压缩在 AWFM 进程里做、字节流走 SFTP 写回，不为它在远端执行任何命令（T-013）。
    """
    payload = req.json()
    path = payload.get("path")
    name = payload.get("name", "")
    if not isinstance(path, str) or not path:
        raise ValidationError("缺少 path。")
    if not isinstance(name, str):
        raise ValidationError("name 必须是字符串。")
    session = _session(ctx, connection_id)
    send_ok(req.handler, {"archive": fileops.compress_entry(session, path, name=name)}, status=201)


def extract_entry(ctx, req: ApiRequest, connection_id: str) -> None:
    """把远端压缩包解开到远端目录。

    tar.gz / tar / zip 都在 Python 侧解析与写出，同样不碰远端命令。
    """
    payload = req.json()
    path = payload.get("path")
    into = payload.get("into", "")
    overwrite = payload.get("overwrite", False)
    if not isinstance(path, str) or not path:
        raise ValidationError("缺少 path。")
    if not isinstance(into, str):
        raise ValidationError("into 必须是字符串。")
    if not isinstance(overwrite, bool):
        raise ValidationError("overwrite 必须是布尔值。")
    session = _session(ctx, connection_id)
    send_ok(
        req.handler,
        {"extract": fileops.extract_entry(session, path, into=into, overwrite=overwrite)},
        status=201,
    )


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
    ("GET", r"/api/connections/(?P<connection_id>[^/]+)/text", read_text),
    ("PUT", r"/api/connections/(?P<connection_id>[^/]+)/text", save_text),
    ("POST", r"/api/connections/(?P<connection_id>[^/]+)/rename", rename_entry),
    ("POST", r"/api/connections/(?P<connection_id>[^/]+)/delete", delete_entry),
    ("POST", r"/api/connections/(?P<connection_id>[^/]+)/compress", compress_entry),
    ("POST", r"/api/connections/(?P<connection_id>[^/]+)/extract", extract_entry),
    # 发现级：与具体连接无关，所以排在所有连接级端点之后（编号第 29~32，见 docs/API.md §4）。
    ("GET", r"/api/discovery", discovery_environment),
    ("POST", r"/api/discovery/scan", start_discovery),
    ("GET", r"/api/discovery/scans/(?P<scan_id>[0-9a-f]+)", discovery_status),
    ("DELETE", r"/api/discovery/scans/(?P<scan_id>[0-9a-f]+)", cancel_discovery),
]


def build_router():
    from app.api.router import Router

    router = Router()
    for method, pattern, func in ENDPOINTS:
        router.add(method, pattern, func)
    return router


__all__ = ["ENDPOINTS", "build_router"]
