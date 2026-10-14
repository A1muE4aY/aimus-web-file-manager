"""下载票据。

## 为什么需要它

下载必须由**浏览器自己**发起（`<a href>` 或 `window.location`），只有这样才有
原生进度、断点提示和「另存为」对话框。用 `fetch` 拉完整份再交给 `Blob` 是另一条路，
但它会把整个文件读进浏览器内存 —— 传一个 4 GB 的镜像时这条路根本走不通，
而这正是决策 D-007（流式传输）要避免的事。

可是浏览器自己发起的导航请求**带不了自定义头**，也就带不了 `X-AWFM-Token`。
把令牌直接放进 URL 是能工作，但那样令牌会留在浏览器历史里，而它能调用全部接口。

所以：先用一次带令牌的 POST 换一张**只能用于这一次下载**的票据，
再把票据放进 URL。票据的性质是：

- 随机（`secrets.token_urlsafe`），猜不到；
- **绑定到具体的连接与路径**，拿到也只能下这一个文件；
- **有有效期**，默认 120 秒；
- 存在内存里，进程重启即全部失效。

## 为什么不设成「一次性」

票据在真正开始传数据时才被消费。如果标成一次性，用户在「另存为」对话框里点了取消、
或者浏览器因为别的原因重试一次，URL 就已经失效了，用户看到的是一个莫名其妙的错误。
代价是这张票据在 120 秒内可以被重复使用 —— 而它本来只能下那一个文件，
所以这个取舍是划算的。
"""

from __future__ import annotations

import logging
import secrets
import threading
import time

logger = logging.getLogger(__name__)

#: 票据有效期（秒）。
DEFAULT_TTL = 120.0

#: 最多同时存在的票据数。正常使用下不会超过个位数；
#: 这个上限是为了防止某个脚本反复申请票据把内存吃光。
MAX_TICKETS = 256


class DownloadTickets:
    """内存里的票据表。线程安全 —— Web 服务是多线程的。"""

    def __init__(self, ttl: float = DEFAULT_TTL) -> None:
        self._lock = threading.Lock()
        self._ttl = ttl
        self._items: dict[str, tuple[float, str, str]] = {}

    def issue(self, connection_id: str, path: str) -> str:
        ticket = secrets.token_urlsafe(24)
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            if len(self._items) >= MAX_TICKETS:
                # 最旧的一张先走。丢掉的票据只影响一次尚未开始的下载。
                oldest = min(self._items, key=lambda k: self._items[k][0])
                self._items.pop(oldest, None)
                logger.warning("下载票据数量达到上限，已回收最早的一张。")
            self._items[ticket] = (now + self._ttl, connection_id, path)
        return ticket

    def verify(self, ticket: str | None, connection_id: str, path: str) -> bool:
        """票据是否有效，且确实属于这个连接的这个路径。"""
        if not ticket:
            return False
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            item = self._items.get(ticket)
        if item is None:
            return False
        _, bound_connection, bound_path = item
        if bound_connection != connection_id:
            logger.warning("下载票据与连接不匹配，已拒绝。")
            return False
        if bound_path != path:
            logger.warning("下载票据与路径不匹配，已拒绝。")
            return False
        return True

    def peek(self, ticket: str | None) -> bool:
        """票据是否存在且未过期（不看绑定）。路由层用它决定要不要跳过令牌校验。

        真正的绑定校验发生在处理函数里 —— 路由层此时还不知道 URL 里的
        connection_id 与 path 是什么。
        """
        if not ticket:
            return False
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            return ticket in self._items

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    @property
    def count(self) -> int:
        with self._lock:
            self._purge(time.monotonic())
            return len(self._items)

    def _purge(self, now: float) -> None:
        """清掉过期项。调用方必须已持锁。"""
        expired = [key for key, (deadline, _, _) in self._items.items() if deadline <= now]
        for key in expired:
            self._items.pop(key, None)
