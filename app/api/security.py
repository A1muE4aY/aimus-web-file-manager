"""请求侧的安全校验。

这个服务只监听回环地址，但**「只监听 127.0.0.1」本身不是一道安全边界**。
以下三种攻击都发生在浏览器里，不需要攻击者能连上我们的端口：

## 1. 跨站请求伪造（CSRF）

你没有打开我们的界面，但你打开了另一个网页。那个网页可以往
`http://127.0.0.1:32579/api/...` 发一个请求。带自定义头的请求会先触发 CORS 预检，
而我们对预检一律拒绝；但 `<form>` 提交和 `fetch` 的**简单请求**
（GET / POST + `text/plain`）**不发预检，请求会真的到达服务端并被执行**。

对策：所有 `/api/` 请求（健康检查除外）都必须带 `X-AWFM-Token` 头，
值是这个进程启动时随机生成的。攻击者的网页读不到我们的 HTML，也就拿不到这个值；
而只要它想带上这个头，浏览器就会先发预检，预检被拒，请求根本不会发出去。

## 2. DNS 重绑定

攻击者把自己的域名解析到 127.0.0.1。浏览器认为 `http://evil.example` 与
`http://127.0.0.1:32579` 之间没有跨域问题之外的差别……实际上它认为
请求是**同源**的，于是可以读响应、可以带自定义头。

对策：校验 `Host` 头必须是回环地址之一。浏览器发的 `Host` 是
`evil.example`，直接拒掉。

## 3. 来源伪装

`Origin` 头与 `Sec-Fetch-Site` 由浏览器填充，页面脚本改不了。
非 `same-origin` / `none` 的一律拒绝，作为上面两条的冗余防线。
"""

from __future__ import annotations

import logging
import secrets

from app.core.errors import Unauthorized
from app.core.errors import ValidationError

logger = logging.getLogger(__name__)

#: 允许的 Host 头主机名（不含端口）。必须是字面量 —— 用主机名做白名单
#: 就绕过了 DNS 重绑定防护本身。
#:
#: 这里**不含**裸写的 `::1`：RFC 7230 要求 IPv6 字面量带方括号，浏览器一律发
#: `[::1]:port`。不带括号的写法本身还有歧义（`::1:32579` 无法判定主机与端口），
#: 收到它说明对方不是正常浏览器，按 fail-closed 拒绝。
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})

#: 免鉴权的路径。只有健康检查 —— 它不返回任何敏感信息，
#: 保留它无鉴权是为了能用 curl 直接确认服务活着。
OPEN_PATHS = frozenset({"/api/health"})


def new_session_token() -> str:
    """生成进程级会话令牌。每次启动都换一个新的。"""
    return secrets.token_urlsafe(32)


def check_host_header(host_header: str | None, *, allow_lan: bool = False) -> None:
    """校验 `Host`。DNS 重绑定攻击在这里被挡住。"""
    if not host_header:
        # HTTP/1.0 的客户端可以不发 Host。此时没有重绑定的可能（浏览器必定会发），
        # 放行以免破坏老客户端。
        return
    host = host_header.strip()
    if host.startswith("["):  # IPv6 字面量
        name, _, _ = host.partition("]")
        name += "]"
    else:
        name = host.split(":", 1)[0]
    if allow_lan:
        # 显式开放局域网时，本机不再限制 Host —— 用户会用机器名或 IP 访问。
        # 但这时必须已经在别处（配置与文档）说明了风险。
        return
    if name.lower() not in ALLOWED_HOSTS:
        raise ValidationError(
            "请求的 Host 头不是本机地址，已拒绝。",
            detail=(
                f"收到 Host: {host!r}。本服务默认只接受 "
                "127.0.0.1 / localhost / [::1]。"
                "若确实需要通过其它地址访问，请在配置中设置 security.allow_lan。"
            ),
            extra={"host": host},
        )


def check_fetch_metadata(origin: str | None, sec_fetch_site: str | None) -> None:
    """校验 `Origin` 与 `Sec-Fetch-Site`。"""
    if sec_fetch_site:
        value = sec_fetch_site.strip().lower()
        # none：地址栏直接输入 / 书签；same-origin：我们自己的页面。
        if value not in ("none", "same-origin"):
            raise Unauthorized(
                "跨站请求已被拒绝。",
                detail=f"Sec-Fetch-Site: {value}",
            )
    if origin:
        # Origin 只在跨源请求与预检里出现。同源请求不带 Origin，
        # 所以这里出现任何值都值得检查。
        lowered = origin.strip().lower()
        if not _is_loopback_origin(lowered):
            raise Unauthorized("跨站请求已被拒绝。", detail=f"Origin: {origin}")


def _is_loopback_origin(origin: str) -> bool:
    if origin in ("null",):
        return False
    if not origin.startswith(("http://", "https://")):
        return False
    rest = origin.split("://", 1)[1]
    if rest.startswith("["):
        name = rest.partition("]")[0] + "]"
    else:
        name = rest.split(":", 1)[0]
    return name.lower() in ALLOWED_HOSTS


def check_token(provided: str | None, expected: str) -> None:
    """校验 `X-AWFM-Token`。用 `compare_digest` 做常数时间比较。"""
    if not provided:
        raise Unauthorized(
            "缺少会话令牌，已拒绝。",
            detail=(
                "所有 API 请求都必须带 X-AWFM-Token 头。"
                "该令牌在每次启动服务时重新生成，由首页 HTML 注入给前端。"
            ),
        )
    if not secrets.compare_digest(provided, expected):
        raise Unauthorized(
            "会话令牌不正确，已拒绝。",
            detail="服务可能已重启，请刷新页面。",
        )


def verify_api_request(
    handler, *, token: str, path: str, allow_lan: bool = False, ticket_ok: bool = False
) -> None:
    """对一个 `/api/` 请求做完所有校验。

    Args:
        ticket_ok: 调用方已经确认这个请求带了一张有效的下载票据。
            只有下载路径可以这样（见 `app/api/tickets.py`）；票据本身与具体文件绑定，
            处理函数还会再校验一次绑定关系。
    """
    check_host_header(handler.headers.get("Host"), allow_lan=allow_lan)
    check_fetch_metadata(handler.headers.get("Origin"), handler.headers.get("Sec-Fetch-Site"))
    if path in OPEN_PATHS or ticket_ok:
        return
    check_token(handler.headers.get("X-AWFM-Token"), token)
