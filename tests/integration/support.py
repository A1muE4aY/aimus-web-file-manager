"""集成测试的公共支撑：真实 WSL 测试床 + 真实 HTTP 服务。

测试床是决策 D-012 的产物 —— WSL 里的非 root sshd 监听 127.0.0.1:2222，
客户端密钥在 data/testbed/id_ed25519。data/ 不进仓库，所以**测试床不存在时
整个集成测试被跳过而不是失败**：别人机器上没装 WSL 不该让测试套件变红。
"""

import contextlib
import json
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app.api.http_server import create_server
from app.core.config import parse_config, project_root
from app.services.connection_manager import ConnectionManager
from app.ssh.known_hosts import append_trusted_key, collect_host_keys
from app.ssh.ssh_launcher import find_ssh_executable

TESTBED_HOST = "127.0.0.1"
TESTBED_PORT = 2222
TESTBED_USER = "aimu"
TESTBED_KEY = project_root() / "data" / "testbed" / "id_ed25519"
TESTBED_HOME = "/home/aimu"


def port_open(host: str, port: int, *, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def testbed_available() -> bool:
    return TESTBED_KEY.is_file() and port_open(TESTBED_HOST, TESTBED_PORT)


require_testbed = unittest.skipUnless(
    testbed_available(),
    "WSL 测试床不可用（需要 data/testbed/id_ed25519 与 127.0.0.1:2222 上的 sshd）",
)


def free_port() -> int:
    """让内核分配一个空闲端口。

    `ServerConfig.port` 的校验范围是 1..65535（0 会被拒），所以不能直接绑 0，
    只能先问内核要一个再立刻释放 —— 中间那一小段窗口对测试来说足够安全。
    """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def testbed_connection(**overrides) -> dict:
    entry = {
        "id": "wsl-testbed",
        "name": "WSL 测试床",
        "host": TESTBED_HOST,
        "port": TESTBED_PORT,
        "username": TESTBED_USER,
        "auth_method": "key",
        "identity_file": str(TESTBED_KEY),
        "allow_write": True,
    }
    entry.update(overrides)
    return entry


def make_config(known_hosts, *, connections=None, security=None, ssh=None, port=None):
    """从最小字典构造一份通过校验的 AppConfig（与真实配置走同一条解析路径）。"""
    data = {
        "config_version": 1,
        "server": {"host": "127.0.0.1", "port": port or free_port()},
        "security": dict(security or {}),
        "ssh": dict(ssh or {}),
        "connections": connections if connections is not None else [testbed_connection()],
    }
    data["ssh"]["known_hosts_file"] = str(known_hosts)
    return parse_config(data, path=str(Path(known_hosts).parent / "config.json"))


@contextlib.contextmanager
def testbed_environment(*, security=None, ssh=None, connections=None, trust=True):
    """临时目录 + known_hosts + AppConfig。

    `trust=False` 时故意留下**空的** known_hosts，用来复现「首次连接要看指纹」。
    """
    with tempfile.TemporaryDirectory(prefix="awfm-it-") as tmp:
        known_hosts = Path(tmp) / "known_hosts"
        keys = []
        if trust:
            keys = collect_host_keys(
                ssh_executable=find_ssh_executable(""),
                host=TESTBED_HOST,
                port=TESTBED_PORT,
            )
            for key in keys:
                append_trusted_key(known_hosts, TESTBED_HOST, TESTBED_PORT, key)
        yield make_config(known_hosts, connections=connections, security=security, ssh=ssh), keys


class Response:
    def __init__(self, status: int, json_body, raw: bytes, headers: dict):
        self.status = status
        self.json = json_body
        self.raw = raw
        self.headers = headers

    @property
    def ok(self) -> bool:
        return bool(self.json and self.json.get("ok") is True)

    @property
    def data(self):
        return (self.json or {}).get("data")

    @property
    def error(self) -> dict:
        return (self.json or {}).get("error", {})

    @property
    def code(self):
        return self.error.get("code")

    def __repr__(self) -> str:
        shown = self.json if self.json is not None else repr(self.raw[:80])
        return f"<Response {self.status} {shown}>"


class Client:
    """极简 HTTP 客户端。

    不抛 HTTPError：测试要断言状态码与错误体，异常会把两者都藏起来。
    默认带上会话令牌，`token=False` 用于复现未授权调用。
    """

    def __init__(self, server, manager):
        self.token = server.context.token
        self.manager = manager
        self.port = server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"

    def request(self, method, path, *, body=None, headers=None, token=True, timeout=30.0):
        url = self.base + path
        sent = {"X-AWFM-Token": self.token} if token else {}
        sent.update(headers or {})
        payload = None
        if body is not None:
            # 上传要发原始字节，不能一律走 JSON 序列化。
            if isinstance(body, bytes):
                payload = body
            elif isinstance(body, str):
                payload = body.encode("utf-8")
            else:
                payload = json.dumps(body).encode("utf-8")
                sent.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(url, data=payload, headers=sent, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                status = response.status
                head = dict(response.headers)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
            head = dict(exc.headers)
        parsed = None
        if raw:
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                parsed = None
        return Response(status, parsed, raw, head)

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, body=None, **kwargs):
        return self.request("POST", path, body=body, **kwargs)

    def patch(self, path, body=None, **kwargs):
        return self.request("PATCH", path, body=body, **kwargs)

    def delete(self, path, **kwargs):
        return self.request("DELETE", path, **kwargs)


@contextlib.contextmanager
def running_server(config):
    """在后台线程里跑真实 HTTP 服务，结束时连会话一起收干净。"""
    manager = ConnectionManager(config)
    server = create_server(config, manager)
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.05},
        name="awfm-test-server",
        daemon=True,
    )
    thread.start()
    try:
        yield Client(server, manager)
    finally:
        server.shutdown()
        server.server_close()
        manager.disconnect_all()
        thread.join(timeout=5)


def count_testbed_ssh_processes() -> int:
    """统计命令行里带 `-p 2222` 的 ssh 进程（T-013：不留孤儿进程）。"""
    if sys.platform != "win32":
        return 0
    # 必须用 @() 把管道结果包成数组：只剩一个 ssh 进程时 PowerShell 5.1 把它当标量，
    # 标量的 .Count 返回空字符串，于是这里会读成 0 —— 断言就会在「真的只有一个子进程」时失败。
    script = (
        "@(Get-CimInstance Win32_Process -Filter \"Name='ssh.exe'\" | "
        "Where-Object { $_.CommandLine -like '*-p 2222*' }).Count"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    text = (result.stdout or "").strip()
    return int(text) if text.isdigit() else 0
