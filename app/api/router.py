"""极简路由表。

用正则而不是路径模板匹配。之所以自己写而不是上框架：规划文档 §2.1 钉死了
「后端只用 Python 标准库、零第三方依赖」，而标准库的 `http.server` 不带路由。
正则足够表达本项目全部路径，且**匹配失败时的行为完全由我们决定**。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Route:
    method: str
    pattern: re.Pattern
    handler: Callable
    name: str


class Router:
    def __init__(self) -> None:
        self._routes: list[Route] = []

    def add(self, method: str, pattern: str, handler: Callable) -> None:
        self._routes.append(
            Route(
                method=method.upper(),
                pattern=re.compile("^" + pattern + "$"),
                handler=handler,
                name=f"{method.upper()} {pattern}",
            )
        )

    def get(self, pattern: str, handler: Callable) -> None:
        self.add("GET", pattern, handler)

    def post(self, pattern: str, handler: Callable) -> None:
        self.add("POST", pattern, handler)

    def patch(self, pattern: str, handler: Callable) -> None:
        self.add("PATCH", pattern, handler)

    def delete(self, pattern: str, handler: Callable) -> None:
        self.add("DELETE", pattern, handler)

    def match(self, method: str, path: str):
        """返回 `(handler, params)` 或 `(None, allowed_methods)`。"""
        allowed: list[str] = []
        for route in self._routes:
            matched = route.pattern.match(path)
            if not matched:
                continue
            if route.method == method:
                return route.handler, matched.groupdict()
            allowed.append(route.method)
        return None, sorted(set(allowed))

    @property
    def routes(self) -> list[Route]:
        return list(self._routes)
