"""远端文件检索：在当前目录及其子目录里按名称找文件或目录。

## 为什么放在服务端

搜索要走 SFTP，而 SFTP 客户端只在服务端（浏览器拿不到通道）。所以搜索是一个
**服务端后台任务**：`POST` 启动 → 前端轮询进度 → 拿到结果或中止。附带的好处是
页面刷新、切到别的连接都不会让已经跑起来的搜索凭空消失。

## 数据量与资源（对应 2.md 阶段三的性能要求）

- 队列里放的是**目录路径字符串**，一次只列举一个目录，从不把整棵远端树读进内存。
- 结果数、扫描目录数、扫描条目数、总时长都有硬上限；命中上限就停下并标明「结果被
  截断」，而不是无声地继续跑。
- **一条连接同时只允许一个搜索**（`SearchRegistry` 强制），避免多条搜索把 SSH 通道占满、
  让同一台机器上的浏览与传输跟着卡住。
- 只在单次 `listdir` 的粒度上持有传输锁（锁在 `SftpTransport` 里），所以搜索与
  「刷新目录」这类操作可以交替进行，而不是一个饿死另一个。

## 符号链接（明确策略）

`listdir` 拿到的符号链接**只作为结果呈现，绝不跟进去**。跟进去会同时遇到两类麻烦：
目录环（a → b → a）与跨出搜索根（软链到 / 或别处）。不跟随从构造上消除了这两个
问题；代价是「符号链接指向的目录内部搜不到」，这一点写在界面上的搜索结果说明里，
不做隐藏。

## 不越界、不执行命令

每一次下钻都是 `join_remote_path(当前目录, readdir 返回的名字)`，名字再用
`validate_remote_name` 校验一次（拒绝空、`.`、`..`、含 `/`）。搜索路径因此永远是
搜索根的子路径，不存在拼接越界。整个模块**只调用 `SftpClient.listdir`**，没有任何
地方会在远端执行 Shell 命令。
"""

from __future__ import annotations

import bisect
import logging
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable

from app.core.errors import (
    AwfmError,
    NotConnected,
    PathNotFound,
    SearchBusy,
    SessionNotConnected,
    ValidationError,
)
from app.models.entry import FileEntry
from app.services import filesystem
from app.utils.paths import (
    join_remote_path,
    normalize_unicode,
    parent_remote_path,
    safe_for_log,
    validate_remote_name,
)

logger = logging.getLogger(__name__)

STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_FAILED = "failed"
STATE_CANCELLED = "cancelled"

#: 搜索范围的说明。前端把它显示在结果区标题旁 —— 「当前目录及其子目录」是默认行为，
#: 不做「只搜当前目录」的降级（那会把局部搜索宣传成整棵树）。
SCOPE_SUBTREE = "subtree"

#: 关键词长度上限（字符）。文件名长度上限是 255 字节，关键词比它长就没意义了。
MAX_QUERY_CHARS = 128

#: 连续失败多少个目录就认为「这条通道已经不能用了」并提前结束。
#: 一次失败（无权限、目录被删）是正常情况，连着失败则基本是连接坏了。
MAX_CONSECUTIVE_FAILURES = 10

#: 在快照里最多回传多少条「跳过的目录」明细（计数仍然完整）。
MAX_PROGRESS_DETAIL = 20


@dataclass(frozen=True)
class SearchLimits:
    """一次搜索的资源上限。默认值按「个人机器上的家目录」这个量级定。"""

    max_results: int = 500
    max_dirs: int = 2000
    max_entries: int = 100000
    time_budget_seconds: float = 45.0


def validate_query(raw: Any) -> str:
    """校验搜索关键词。返回去掉首尾空白后的关键词。"""
    if not isinstance(raw, str):
        raise ValidationError("搜索关键词必须是字符串。")
    query = raw.strip()
    if not query:
        raise ValidationError("搜索关键词不能为空。")
    if len(query) > MAX_QUERY_CHARS:
        raise ValidationError(
            f"搜索关键词过长（上限 {MAX_QUERY_CHARS} 个字符）。",
            detail=f"收到 {len(query)} 个字符。",
        )
    for char in query:
        if char == "\x00" or (ord(char) < 32 and char not in "\t"):
            raise ValidationError("搜索关键词包含不允许的控制字符。")
    return query


class Search:
    """一次搜索任务的状态与结果。线程安全：工作线程写、HTTP 线程读。"""

    def __init__(
        self,
        *,
        session,
        root: str,
        query: str,
        limits: SearchLimits,
        registry: "SearchRegistry",
    ) -> None:
        self.id = secrets.token_hex(8)
        self.connection_id = session.connection.id
        self.root = root
        self.query = query
        self.scope = SCOPE_SUBTREE
        self.limits = limits
        self.started_at = time.time()
        self.finished_at: float | None = None
        self._session = session
        self._registry = registry
        self._needle = normalize_unicode(query).casefold()
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = STATE_RUNNING
        self._results: list[dict[str, Any]] = []
        self._scanned_dirs = 0
        self._scanned_entries = 0
        self._skipped_dirs = 0
        self._skipped_names = 0
        self._skipped: list[dict[str, Any]] = []
        self._truncated = False
        self._truncated_reason: str | None = None
        self._error: AwfmError | None = None

    # ------------------------------------------------------------------ 只读属性

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    @property
    def is_running(self) -> bool:
        return self.status == STATE_RUNNING

    def wait(self, timeout: float | None = None) -> bool:
        """等工作线程结束（给测试与关停用）。返回是否已结束。"""
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def cancel(self) -> bool:
        """请求中止。返回是否是本次调用真正发出了请求。"""
        was_running = self.is_running
        self._cancel.set()
        return was_running

    # ------------------------------------------------------------------ 快照

    def snapshot(self, *, include_results: bool = True) -> dict[str, Any]:
        with self._lock:
            payload: dict[str, Any] = {
                "id": self.id,
                "connection_id": self.connection_id,
                "root": self.root,
                "query": self.query,
                "scope": self.scope,
                "status": self._status,
                "running": self._status == STATE_RUNNING,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "duration_seconds": round((self.finished_at or time.time()) - self.started_at, 3),
                "scanned_dirs": self._scanned_dirs,
                "scanned_entries": self._scanned_entries,
                "skipped_dirs": self._skipped_dirs,
                "skipped_names": self._skipped_names,
                "skipped": list(self._skipped),
                "result_count": len(self._results),
                "truncated": self._truncated,
                "truncated_reason": self._truncated_reason,
                "limits": {
                    "max_results": self.limits.max_results,
                    "max_dirs": self.limits.max_dirs,
                    "max_entries": self.limits.max_entries,
                    "time_budget_seconds": self.limits.time_budget_seconds,
                },
                "error": _error_payload(self._error),
            }
            if include_results:
                payload["results"] = list(self._results)
            return payload

    # ------------------------------------------------------------------ 工作线程

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name=f"awfm-search-{self.id}", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        try:
            self._walk()
        except AwfmError as exc:
            self._finish(STATE_FAILED, error=exc)
        except Exception as exc:  # pragma: no cover - 兜底
            logger.exception("搜索 %s 时发生未预期的异常", self.id)
            self._finish(
                STATE_FAILED,
                error=AwfmError("搜索过程中发生内部错误。", detail=str(exc)),
            )
        else:
            if self._cancel.is_set() and self._status == STATE_RUNNING:
                self._finish(STATE_CANCELLED)
            else:
                self._finish(STATE_DONE)
        finally:
            self._registry._forget_active(self)

    def _walk(self) -> None:
        session = self._session
        limits = self.limits
        deadline = self.started_at + limits.time_budget_seconds
        queue: deque[str] = deque([self.root])
        visited: set[str] = {self.root}
        consecutive_failures = 0

        while queue:
            if self._cancel.is_set():
                return
            if time.time() > deadline:
                self._truncate(f"搜索超过时间上限（{limits.time_budget_seconds:g} 秒），已提前结束。")
                return
            if self._scanned_dirs >= limits.max_dirs:
                self._truncate(f"已扫描 {limits.max_dirs} 个目录（上限），搜索提前结束。")
                return
            if self._scanned_entries >= limits.max_entries:
                self._truncate(f"已检查 {limits.max_entries} 个条目（上限），搜索提前结束。")
                return
            if len(self._results) >= limits.max_results:
                self._truncate(f"匹配结果已达 {limits.max_results} 条（上限），搜索提前结束。")
                return

            directory = queue.popleft()
            try:
                # 唯一与远端交互的调用：列举一个目录。
                entries = session.client.listdir(directory)
            except (NotConnected, SessionNotConnected):
                # 连接断了：这不是「没搜到」，必须让调用方看见真实原因。
                raise
            except AwfmError as exc:
                consecutive_failures += 1
                self._note_skipped(directory, exc)
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    raise AwfmError(
                        f"连续 {consecutive_failures} 个目录都无法访问，搜索已停止。",
                        detail=str(exc),
                    ) from exc
                continue
            consecutive_failures = 0
            with self._lock:
                self._scanned_dirs += 1

            for name_entry in entries:
                name = getattr(name_entry, "filename", None)
                attrs = getattr(name_entry, "attrs", None)
                if not isinstance(name, str):
                    continue
                try:
                    validate_remote_name(name)
                except AwfmError:
                    # readdir 返回了 . / .. / 含斜杠之类的名字：拒绝下钻与匹配。
                    with self._lock:
                        self._skipped_names += 1
                    continue
                with self._lock:
                    self._scanned_entries += 1
                    entries_seen = self._scanned_entries
                if self._cancel.is_set():
                    # 每个条目都查一次取消：相比一次 SFTP 往返，Event.is_set() 的开销
                    # 可以忽略，换来的是「点中止后立刻停下」而不是「等这一整层扫完」。
                    return

                entry_type = getattr(attrs, "type", "other") if attrs is not None else "other"
                path = join_remote_path(directory, name)
                if self._matches(name):
                    self._append(name, path, attrs, entry_type)
                    if len(self._results) >= limits.max_results:
                        self._truncate(
                            f"匹配结果已达 {limits.max_results} 条（上限），搜索提前结束。"
                        )
                        return
                if entry_type == "directory" and path not in visited:
                    if len(visited) >= limits.max_dirs:
                        # 目录预算在**发现**处也要卡一道：只在「列举」处设限的话，
                        # 一个含十万个子目录的目录会先把待办队列撑满内存。
                        self._truncate(
                            f"发现的目录已超过 {limits.max_dirs} 个（上限），搜索提前结束。"
                        )
                        return
                    visited.add(path)
                    queue.append(path)
                if entries_seen >= limits.max_entries:
                    # 条目预算必须在这里查：单个目录里的几千个条目是在这一层循环里
                    # 走完的，只在 while 顶部检查会让上限形同虚设。
                    self._truncate(
                        f"已检查 {limits.max_entries} 个条目（上限），搜索提前结束。"
                    )
                    return

    def _matches(self, name: str) -> bool:
        return self._needle in normalize_unicode(name).casefold()

    def _append(self, name: str, path: str, attrs, entry_type: str) -> None:
        if attrs is not None:
            payload = FileEntry.from_attrs(name, path, attrs).to_dict()
        else:  # pragma: no cover - 只有服务端返回畸形属性时才会走到
            payload = {
                "name": name,
                "path": path,
                "type": entry_type,
                "size": None,
                "mtime": None,
                "mode": None,
            }
        payload["type"] = entry_type
        payload["parent"] = parent_remote_path(path)
        # 「相对搜索根往下第几层」：根的直接子项是第 1 层。用的是相对根的段数，
        # 而不是绝对路径里的斜杠总数 —— 后者随根所在的深度变化，对用户没有意义。
        below = path[len(self.root):].strip("/") if path.startswith(self.root) else path
        payload["depth"] = below.count("/") + 1 if below else 0
        with self._lock:
            bisect.insort(self._results, payload, key=_result_key)

    def _note_skipped(self, directory: str, exc: AwfmError) -> None:
        with self._lock:
            self._skipped_dirs += 1
            if len(self._skipped) < MAX_PROGRESS_DETAIL:
                self._skipped.append(
                    {
                        "path": directory,
                        "code": exc.code,
                        "message": exc.message,
                    }
                )
        logger.debug("搜索跳过目录 %s：%s", safe_for_log(directory), exc.message)

    def _truncate(self, reason: str) -> None:
        with self._lock:
            self._truncated = True
            self._truncated_reason = reason

    def _finish(self, status: str, *, error: AwfmError | None = None) -> None:
        with self._lock:
            self._status = status
            self._error = error
            self.finished_at = time.time()
        if error is not None:
            logger.info("搜索 %s 失败：%s", self.id, error.message)
        else:
            logger.info(
                "搜索 %s 结束（%s）：扫描 %d 个目录 / %d 个条目，命中 %d 条",
                self.id,
                status,
                self._scanned_dirs,
                self._scanned_entries,
                len(self._results),
            )


def _result_key(payload: dict[str, Any]) -> tuple[int, str, str]:
    order = {"directory": 0, "symlink": 1, "file": 2}.get(payload.get("type") or "", 3)
    return (order, normalize_unicode(payload.get("name") or "").casefold(), payload.get("path") or "")


def _error_payload(error: AwfmError | None) -> dict[str, Any] | None:
    if error is None:
        return None
    return {"code": error.code, "message": error.message, "detail": error.detail}


class SearchRegistry:
    """进程内所有搜索任务的登记处。一条连接同时只允许一个搜索。"""

    def __init__(self, *, limits: SearchLimits | None = None, max_kept: int = 20) -> None:
        self._lock = threading.RLock()
        self._searches: dict[str, Search] = {}
        self._active: dict[str, str] = {}
        self._limits = limits or SearchLimits()
        self._max_kept = max_kept

    # ------------------------------------------------------------------ 生命周期

    def start(self, session, *, path: str, query: str) -> Search:
        """在 `session` 上启动一次搜索。路径与关键词在这里就校验完。"""
        keyword = validate_query(query)
        # 立刻解析并确认根目录：路径写错、不是目录，都要马上报错，
        # 而不是先返回一个「已启动」再让用户去看一个失败的搜索。
        root = filesystem.resolve_path(session, path)
        info = filesystem.stat_path(session, root)
        if info.get("type") != "directory":
            raise ValidationError(
                "该路径不是一个目录。",
                detail="搜索只支持从目录开始。",
            )
        root = info.get("path") or root

        with self._lock:
            existing_id = self._active.get(session.connection.id)
            existing = self._searches.get(existing_id) if existing_id else None
            if existing is not None and existing.is_running:
                raise SearchBusy(
                    "这条连接上已经有一个正在进行的搜索。",
                    detail="请等它结束，或在结果区点「中止」。",
                )
            self._prune_locked()
            search = Search(
                session=session,
                root=root,
                query=keyword,
                limits=self._limits,
                registry=self,
            )
            self._searches[search.id] = search
            self._active[session.connection.id] = search.id
        logger.info(
            "开始搜索：connection=%s root=%s query=%r",
            session.connection.id,
            safe_for_log(root),
            keyword,
        )
        search.start()
        return search

    def get(self, search_id: str) -> Search:
        with self._lock:
            search = self._searches.get(search_id)
        if search is None:
            raise PathNotFound(
                "搜索不存在或已过期。",
                detail="搜索结果只保留最近若干次，请重新发起搜索。",
            )
        return search

    def snapshot(self, search_id: str) -> dict[str, Any]:
        return self.get(search_id).snapshot()

    def cancel(self, search_id: str) -> dict[str, Any]:
        search = self.get(search_id)
        search.cancel()
        return search.snapshot()

    def cancel_for_connection(self, connection_id: str) -> int:
        """连接断开/删除时调用：把它上面还在跑的搜索停掉。"""
        with self._lock:
            ids = [sid for sid, s in self._searches.items() if s.connection_id == connection_id]
        stopped = 0
        for sid in ids:
            search = self._searches.get(sid)
            if search is not None and search.cancel():
                stopped += 1
        return stopped

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for s in self._searches.values() if s.is_running)

    def shutdown(self, timeout: float = 5.0) -> None:
        """服务关停：请求所有搜索停下并等一小会儿。"""
        with self._lock:
            searches = list(self._searches.values())
        for search in searches:
            search.cancel()
        deadline = time.time() + timeout
        for search in searches:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            search.wait(remaining)

    # ------------------------------------------------------------------ 内部

    def _forget_active(self, search: Search) -> None:
        with self._lock:
            if self._active.get(search.connection_id) == search.id:
                self._active.pop(search.connection_id, None)

    def _prune_locked(self) -> None:
        """只保留最近若干次**已结束**的搜索；正在跑的一个都不动。"""
        finished = [
            (s.finished_at or s.started_at, sid)
            for sid, s in self._searches.items()
            if not s.is_running
        ]
        if len(self._searches) < self._max_kept:
            return
        finished.sort()
        for _, sid in finished[: max(0, len(self._searches) - self._max_kept + 1)]:
            self._searches.pop(sid, None)


__all__ = [
    "MAX_QUERY_CHARS",
    "SCOPE_SUBTREE",
    "STATE_CANCELLED",
    "STATE_DONE",
    "STATE_FAILED",
    "STATE_RUNNING",
    "Search",
    "SearchLimits",
    "SearchRegistry",
    "validate_query",
]
