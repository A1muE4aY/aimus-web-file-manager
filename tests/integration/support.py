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
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

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

    def put(self, path, body=None, **kwargs):
        return self.request("PUT", path, body=body, **kwargs)

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


# --------------------------------------------------------------------- 测试床造景
#
# 应用本身**不在远端执行任何命令**（T-013 的正面要求，见 app/services/search.py 的
# 模块说明）。但摆测试数据需要建目录、造符号链接、摘掉某个目录的权限位，这些动作
# 应用当前还没有入口（写操作只到上传为止）。所以这里直接调 ssh CLI 造场景：
# 被测的是「读」，造景的是测试自己，两者不混淆。

#: 「按文件名搜索」用的小树。刻意覆盖中文名、大小写、嵌套、符号链接、无权限目录。
SEARCH_FIXTURE_ROOT = "/tmp/awfm-search-fixture"

#: 给「中止搜索」用的大树：150 个目录 × 30 个文件。太小的话搜索在中止请求到达前
#: 就已经跑完了，中止路径根本测不到。
SEARCH_BULK_ROOT = "/tmp/awfm-search-bulk"

#: 摆在小树**之外**、只通过符号链接可达的目录：用来证明搜索不跟着链接跑出搜索根。
SEARCH_OUTSIDE_ROOT = "/tmp/awfm-search-outside"

_SEARCH_FIXTURE_SCRIPT = """
set -e
root='%(root)s'
bulk='%(bulk)s'
out='%(outside)s'
chmod -R u+rwX "$root" 2>/dev/null || true
rm -rf "$root" "$bulk" "$out"
mkdir -p "$root/子目录/深层" "$root/Case" "$root/locked" "$root/many" "$root/循环目录" "$bulk" "$out"
# 根外的一个文件：只有顺着 link-to-outside 才够得着。
printf 'outside\n' > "$out/only-here.txt"
printf 'hello-world-search\\n' > "$root/报告.txt"
printf 'draft\\n' > "$root/报告-草稿.txt"
: > "$root/Report.md"
: > "$root/report-final.txt"
: > "$root/many-report.txt"
printf 'deep-report\\n' > "$root/子目录/深层/报告.txt"
: > "$root/子目录/深层/notes.txt"
: > "$root/Case/REPORT.TXT"
: > "$root/locked/报告.txt"
i=0
while [ "$i" -lt 20 ]; do : > "$root/many/file-$(printf '%%02d' "$i").txt"; i=$((i+1)); done
ln -s "$root/报告.txt" "$root/link-to-report"
ln -s "$root/子目录" "$root/link-to-dir"
ln -s "$out" "$root/link-to-outside"
# 目录环：回环指回搜索根。搜索不跟随符号链接，所以这棵树不会把它卡住。
ln -s "$root" "$root/循环目录/回环"
# 无权限目录：测试床是 uid=1000 的非 root 用户，chmod 000 后 listdir 真的会失败。
chmod 000 "$root/locked"
j=0
while [ "$j" -lt %(dirs)d ]; do
  d="$bulk/d$j"
  mkdir -p "$d"
  k=0
  while [ "$k" -lt %(files)d ]; do : > "$d/f$k.txt"; k=$((k+1)); done
  j=$((j+1))
done
echo READY
"""


def testbed_command(script: str, *, timeout: float = 120.0, check: bool = True) -> str:
    """在测试床上执行一段 shell（**只给测试造景用**）。"""
    sink = "NUL" if sys.platform == "win32" else "/dev/null"
    result = subprocess.run(
        [
            find_ssh_executable(""),
            "-i",
            str(TESTBED_KEY),
            "-p",
            str(TESTBED_PORT),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=" + sink,
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "LogLevel=ERROR",
            f"{TESTBED_USER}@{TESTBED_HOST}",
            script,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            "测试床命令失败（退出码 %s）：\n%s\n%s"
            % (result.returncode, result.stdout, result.stderr)
        )
    return result.stdout or ""


@contextlib.contextmanager
def search_fixture(*, dirs: int = 150, files: int = 30):
    """摆好搜索用的小树与大树，结束后删掉。yield {"root": ..., "bulk": ...}。"""
    testbed_command(
        _SEARCH_FIXTURE_SCRIPT
        % {
            "root": SEARCH_FIXTURE_ROOT,
            "bulk": SEARCH_BULK_ROOT,
            "outside": SEARCH_OUTSIDE_ROOT,
            "dirs": dirs,
            "files": files,
        }
    )
    try:
        yield {
            "root": SEARCH_FIXTURE_ROOT,
            "bulk": SEARCH_BULK_ROOT,
            "outside": SEARCH_OUTSIDE_ROOT,
            "dirs": dirs,
            "files": files,
        }
    finally:
        # 清理要先把 locked 的权限还回来，否则 rm -rf 删不掉里面的文件。
        testbed_command(
            "chmod -R u+rwX %s %s %s 2>/dev/null || true; rm -rf %s %s %s"
            % (
                SEARCH_FIXTURE_ROOT,
                SEARCH_BULK_ROOT,
                SEARCH_OUTSIDE_ROOT,
                SEARCH_FIXTURE_ROOT,
                SEARCH_BULK_ROOT,
                SEARCH_OUTSIDE_ROOT,
            ),
            check=False,
        )


def start_search(client, *, path: str, query: str, connection_id: str = "wsl-testbed"):
    """发起一次搜索（成功时是 202）。"""
    return client.post(
        "/api/connections/%s/search" % connection_id, body={"path": path, "query": query}
    )


def wait_for_search(client, search_id: str, *, timeout: float = 30.0, interval: float = 0.05) -> dict:
    """轮询到搜索结束，返回快照。超时抛断言错误（而不是让用例静静地过）。"""
    deadline = time.time() + timeout
    last = None
    while True:
        response = client.get("/api/searches/" + search_id)
        if not response.ok:
            raise AssertionError("查询搜索状态失败：%r" % (response,))
        last = response.data["search"]
        if not last.get("running"):
            return last
        if time.time() > deadline:
            raise AssertionError("搜索 %s 在 %s 秒内没有结束：%r" % (search_id, timeout, last))
        time.sleep(interval)


def search_and_wait(
    client, *, path: str, query: str, connection_id: str = "wsl-testbed", timeout: float = 30.0
) -> dict:
    """发起 + 等结束，返回最终快照。"""
    response = start_search(client, path=path, query=query, connection_id=connection_id)
    if response.status != 202:
        raise AssertionError("启动搜索失败：%r" % (response,))
    return wait_for_search(client, response.data["search"]["id"], timeout=timeout)


# --------------------------------------------------------- 在线虚拟机发现

DISCOVERY_SCAN_PATH = "/api/discovery/scan"

#: 扫描的终态。中止之后也可能是 done（活儿已经干完了），所以两种都算结束。
DISCOVERY_TERMINAL = ("done", "cancelled", "failed")


def start_discovery_scan(client) -> str:
    """开始一次在线虚拟机扫描（成功时是 202），返回 scan_id。"""
    response = client.post(DISCOVERY_SCAN_PATH)
    if response.status != 202:
        raise AssertionError("开始扫描失败：%r" % (response,))
    return response.data["scan"]["id"]


def wait_discovery_scan(client, scan_id: str, *, timeout: float = 180.0, interval: float = 0.2) -> dict:
    """轮询到扫描结束，返回快照。超时抛断言错误（而不是让用例静静地过）。"""
    deadline = time.time() + timeout
    while True:
        response = client.get("/api/discovery/scans/" + scan_id)
        if not response.ok:
            raise AssertionError("查询扫描状态失败：%r" % (response,))
        snapshot = response.data["scan"]
        if snapshot["status"] in DISCOVERY_TERMINAL:
            return snapshot
        if time.time() > deadline:
            raise AssertionError("扫描 %s 在 %s 秒内没有结束：%r" % (scan_id, timeout, snapshot))
        time.sleep(interval)


def scan_and_wait(client, *, timeout: float = 180.0) -> dict:
    """发起 + 等结束，返回最终快照。"""
    return wait_discovery_scan(client, start_discovery_scan(client), timeout=timeout)


# ----------------------------------------------------------------- 阶段四造景


EDIT_FIXTURE_ROOT = "/tmp/awfm-edit-fixture"

OPS_FIXTURE_ROOT = "/tmp/awfm-ops-fixture"

#: 在线编辑用的小夹具。__ROOT__ 会被替换成实际根目录（不用 % 格式化，
#: 免得脚本里的 printf 格式符被 Python 提前吃掉）。
_EDIT_FIXTURE_SCRIPT = r"""
set -e
root=__ROOT__
chmod -R u+rwX "$root" 2>/dev/null || true
rm -rf "$root"
mkdir -p "$root/sub"
printf 'hello\nworld\n' > "$root/plain.txt"
printf 'a\r\nb\r\n' > "$root/crlf.txt"
: > "$root/empty.txt"
printf 'no final newline' > "$root/nonl.txt"
printf '\357\273\277with bom\n' > "$root/bom.txt"
printf 'read only\n' > "$root/readonly.txt"
chmod 0444 "$root/readonly.txt"
printf 'link target\n' > "$root/real.txt"
ln -sf "$root/real.txt" "$root/link.txt"
printf 'inside\n' > "$root/sub/nested.txt"
head -c 4096 /dev/zero > "$root/zeros.bin"
head -c 8192 /dev/zero | tr '\0' 'a' > "$root/eight-k.txt"
echo READY
"""

#: 文件操作用的夹具：要改名/删除/压缩/解压的素材都摆在这里。
_OPS_FIXTURE_SCRIPT = r"""
set -e
root=__ROOT__
chmod -R u+rwX "$root" 2>/dev/null || true
rm -rf "$root"
mkdir -p "$root/tree/a/b" "$root/emptydir" "$root/target-dir"
printf 'rename me\n' > "$root/rename-me.txt"
printf 'keep\n' > "$root/existing.txt"
printf 'other\n' > "$root/other.txt"
printf 'leaf\n' > "$root/tree/a/b/leaf.txt"
printf 'mid\n' > "$root/tree/a/mid.txt"
printf 'archive payload\n' > "$root/pack.txt"
printf 'target\n' > "$root/target.txt"
printf 'kept\n' > "$root/target-dir/kept.txt"
ln -sf "$root/target.txt" "$root/link.txt"
ln -sf "$root/target-dir" "$root/dir-link"
echo READY
"""


@contextlib.contextmanager
def _testbed_fixture(script: str, root: str):
    """摆好夹具，结束后整棵删掉（先放开权限，否则删不掉只读条目）。"""
    testbed_command(script.replace("__ROOT__", root))
    try:
        yield root
    finally:
        testbed_command(
            'chmod -R u+rwX "%s" 2>/dev/null || true; rm -rf "%s"' % (root, root),
            check=False,
        )


def edit_fixture():
    """在线编辑用的夹具。yield 根目录。"""
    return _testbed_fixture(_EDIT_FIXTURE_SCRIPT, EDIT_FIXTURE_ROOT)


def ops_fixture():
    """文件操作用的夹具。yield 根目录。"""
    return _testbed_fixture(_OPS_FIXTURE_SCRIPT, OPS_FIXTURE_ROOT)


def connection_url(connection_id: str, suffix: str, *, path: str = "") -> str:
    """拼一个带 path 查询参数的连接级接口地址（路径按 URL 规则编码）。"""
    url = "/api/connections/%s/%s" % (quote(connection_id, safe=""), suffix)
    if path:
        url += "?path=" + quote(path, safe="")
    return url


def upload_bytes(client, directory: str, name: str, data: bytes, *, overwrite: bool = True,
                 connection_id: str = "wsl-testbed"):
    """用 AWFM 自己的上传接口往测试床放一个文件（造夹具时比 shell 更可控）。"""
    query = "?path=%s&name=%s" % (quote(directory, safe=""), quote(name, safe=""))
    if overwrite:
        query += "&overwrite=1"
    return client.request(
        "POST",
        "/api/connections/%s/upload%s" % (connection_id, query),
        body=data,
        headers={"Content-Type": "application/octet-stream"},
    )


def download_bytes(client, path: str, *, connection_id: str = "wsl-testbed") -> bytes:
    """走票据流程把远端文件完整取回本地（用于核对压缩包内容）。"""
    ticket = client.post("/api/connections/%s/download-ticket" % connection_id, {"path": path})
    if ticket.status != 200:
        raise AssertionError("取下载票据失败：%r" % (ticket,))
    response = client.get(ticket.data["url"], token=False)
    if response.status != 200:
        raise AssertionError("下载失败：%r" % (response,))
    return response.raw

