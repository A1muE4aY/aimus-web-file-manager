"""安全测试的公共支撑。

与 tests/integration/support.py 的分工：

* 这里搭出的服务**不需要测试床**：连接表可以为空，或只含一个永远连不上的地址。
  因此 Web 层安全测试（未授权调用、CSRF、Host 头、静态资源边界、响应头策略）
  在任何机器上都能跑，不会因为「本机没装 WSL」而被整类跳过。
* 需要真实远端文件系统的用例（路径穿越、主机密钥、覆盖确认）从
  tests.integration.support 借测试床与 require_testbed。
"""

from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path

from tests.integration.support import Client, make_config, running_server

#: 一个**永远连不上**的连接：127.0.0.1:9 是 discard 端口，本机不会有人监听它。
#: 用它来复现「连接失败」路径，而不依赖测试床。
DEAD_CONNECTION = {
    "id": "dead-host",
    "name": "连不上的主机",
    "host": "127.0.0.1",
    "port": 9,
    "username": "nobody",
    "auth_method": "password",
    "identity_file": "",
    "allow_write": False,
}


class Harness:
    """一次真实 HTTP 服务运行的句柄。"""

    def __init__(self, client: Client, config, tmp: str) -> None:
        self.client = client
        self.config = config
        self.tmp = Path(tmp)

    @property
    def known_hosts(self) -> Path:
        return Path(self.config.known_hosts_path)


@contextlib.contextmanager
def local_server(*, connections=(DEAD_CONNECTION,), security=None, ssh=None):
    """临时目录 + 临时 known_hosts + 真实 HTTP 服务（不依赖测试床）。"""
    with tempfile.TemporaryDirectory(prefix="awfm-sec-") as tmp:
        known_hosts = Path(tmp) / "known_hosts"
        config = make_config(
            known_hosts, connections=list(connections), security=security, ssh=ssh
        )
        with running_server(config) as client:
            yield Harness(client, config, tmp)


def header(response, name: str) -> str:
    """大小写无关地取一个响应头（服务端发什么大小写都算）。"""
    wanted = name.lower()
    for key, value in (response.headers or {}).items():
        if key.lower() == wanted:
            return value
    return ""
