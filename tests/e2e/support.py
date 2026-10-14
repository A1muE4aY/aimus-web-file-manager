"""端到端测试的支撑：用标准库驱动真实 Edge（CDP over WebSocket）。

为什么不用 Selenium / Playwright：项目的运行时依赖数必须是 0（需求 N-02），
测试栈也不引入第三方包。CDP 传的就是 JSON over WebSocket，标准库足够。

浏览器以「无头 + 全新临时配置目录 + --inprivate」启动，测试因此跑在一个干净
的浏览器会话里，既不读也不写用户日常浏览器的任何状态 —— 这正是规划文档
§7.2 对端到端测试的要求（用 Edge 无痕模式验证真实页面）。
"""

import base64
import contextlib
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from tests.integration.support import free_port

EDGE_PATHS = (
    Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
    / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("ProgramFiles", "C:/Program Files"))
    / "Microsoft/Edge/Application/msedge.exe",
    Path(os.environ.get("LOCALAPPDATA", "C:/Users/Default/AppData/Local"))
    / "Microsoft/Edge/Application/msedge.exe",
)


def find_edge_executable() -> str:
    """返回 msedge.exe 的绝对路径；找不到返回空串，由调用方决定是否跳过。"""
    for candidate in EDGE_PATHS:
        if candidate.is_file():
            return str(candidate)
    return ""


# 注入到页面里的测试辅助函数：全部基于 DOM 事件，不碰应用内部对象。
JS_HELPERS = """
window.__awfm = {
  clickByText: function (selector, text) {
    const nodes = document.querySelectorAll(selector);
    for (const node of nodes) {
      if (node.textContent.trim().indexOf(text) === 0) { node.click(); return true; }
    }
    return false;
  },
  openRow: function (name) {
    const rows = document.querySelectorAll('#file-body tr');
    for (const row of rows) {
      if (row.getAttribute('data-name') === name) {
        row.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, cancelable: true, view: window }));
        return true;
      }
    }
    return false;
  },
  rowNames: function () {
    return Array.from(document.querySelectorAll('#file-body tr')).map(function (row) {
      return row.getAttribute('data-name');
    });
  },
  bodyText: function () { return document.body.innerText; },
};
true;
"""


class _BufferedSocket:
    """带缓冲的 socket 读，WebSocket 分帧需要精确读 n 字节。"""

    def __init__(self, sock):
        self._sock = sock
        self._buffer = bytearray()

    def read_exact(self, size: int) -> bytes:
        while len(self._buffer) < size:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ConnectionError("CDP 连接被对端关闭。")
            self._buffer.extend(chunk)
        out = bytes(self._buffer[:size])
        del self._buffer[:size]
        return out

    def read_until(self, marker: bytes) -> bytes:
        while marker not in self._buffer:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ConnectionError("CDP 握手期间连接被关闭。")
            self._buffer.extend(chunk)
        end = self._buffer.index(marker) + len(marker)
        out = bytes(self._buffer[:end])
        del self._buffer[:end]
        return out


class CdpSession:
    """一条 CDP 连接：WebSocket 文本帧 + JSON-RPC。

    只实现测试需要的最小面：发命令、等对应 id 的响应、顺手收下事件。
    """

    def __init__(self, websocket_url: str, *, timeout: float = 30.0):
        self.timeout = timeout
        self.events = []
        parsed = urllib.parse.urlsplit(websocket_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        self._socket = socket.create_connection((host, port), timeout=timeout)
        self._reader = _BufferedSocket(self._socket)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        handshake = (
            "GET " + path + " HTTP/1.1\r\n"
            "Host: " + host + ":" + str(port) + "\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: " + key + "\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._socket.sendall(handshake.encode("ascii"))
        head = self._reader.read_until(b"\r\n\r\n").decode("latin-1")
        status_line = head.split("\r\n")[0]
        if "101" not in status_line:
            raise ConnectionError("WebSocket 握手失败：" + status_line)
        self._next_id = 0

    # ------------------------------------------------------------------ 帧
    def _send_frame(self, opcode: int, payload: bytes) -> None:
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack(">H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack(">Q", length))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self._socket.sendall(bytes(header) + masked)

    def _read_message(self):
        """返回一条文本消息；连接被关闭时返回 None。"""
        fragments = []
        while True:
            first, second = self._reader.read_exact(2)
            fin = bool(first & 0x80)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._reader.read_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._reader.read_exact(8))[0]
            mask = self._reader.read_exact(4) if masked else b""
            payload = self._reader.read_exact(length) if length else b""
            if masked:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x8:
                return None
            fragments.append(payload)
            if fin:
                break
        return b"".join(fragments).decode("utf-8")

    # ------------------------------------------------------------- 命令面
    def send(self, method: str, params=None, *, timeout=None):
        self._next_id += 1
        message_id = self._next_id
        payload = {"id": message_id, "method": method}
        if params:
            payload["params"] = params
        self._send_frame(0x1, json.dumps(payload).encode("utf-8"))
        deadline = time.monotonic() + (timeout or self.timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("CDP 调用超时：" + method)
            self._socket.settimeout(max(0.1, remaining))
            raw = self._read_message()
            if raw is None:
                raise ConnectionError("CDP 连接被对端关闭：" + method)
            message = json.loads(raw)
            if message.get("id") == message_id:
                if "error" in message:
                    raise RuntimeError(
                        "CDP " + method + " 失败：" + json.dumps(message["error"], ensure_ascii=False)
                    )
                return message.get("result", {})
            if "method" in message:
                self.events.append(message)

    def evaluate(self, expression: str, *, timeout=None):
        result = self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
            timeout=timeout,
        )
        if result.get("exceptionDetails"):
            raise AssertionError(
                "页面里的表达式抛错：" + json.dumps(result["exceptionDetails"], ensure_ascii=False)[:500]
            )
        return result.get("result", {}).get("value")

    def wait_for(self, expression: str, *, timeout: float = 30.0, interval: float = 0.25, message: str = ""):
        """轮询表达式直到它返回真值；超时抛 AssertionError（带最后一次结果）。"""
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            last = self.evaluate(expression, timeout=timeout)
            if last:
                return last
            time.sleep(interval)
        raise AssertionError("等待超时（" + str(timeout) + "s）：" + (message or expression) + "；最后一次结果 = " + repr(last))

    def navigate(self, url: str, *, timeout: float = 60.0) -> None:
        self.send("Page.enable", timeout=timeout)
        self.send("Network.enable", timeout=timeout)
        self.send("Runtime.enable", timeout=timeout)
        self.send("Page.navigate", {"url": url}, timeout=timeout)

    def install_helpers(self) -> None:
        self.evaluate(JS_HELPERS)

    def screenshot(self, path) -> Path:
        result = self.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(result["data"]))
        return target

    def requests(self) -> list:
        """本次会话里页面发起的 URL 列表（按顺序）。"""
        urls = []
        for event in self.events:
            if event.get("method") == "Network.requestWillBeSent":
                url = event.get("params", {}).get("request", {}).get("url")
                if url:
                    urls.append(url)
        return urls

    def responses(self) -> list:
        """本次会话里页面收到的 (状态码, URL) 列表（按顺序）。

        失败路径要靠它判定「后端报的是结构化错误，不是 500 未预期异常」——
        只看界面文案是不够的，500 也会弹提示。
        """
        seen = []
        for event in self.events:
            if event.get("method") == "Network.responseReceived":
                response = event.get("params", {}).get("response", {})
                url = response.get("url")
                if url:
                    seen.append((response.get("status"), url))
        return seen

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._send_frame(0x8, b"")
        with contextlib.suppress(Exception):
            self._socket.close()


def _devtools_json(port: int, path: str, *, timeout: float = 5.0):
    with urllib.request.urlopen("http://127.0.0.1:" + str(port) + path, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_for_page_target(port: int, *, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    last_error = "（没有开始尝试）"
    while time.monotonic() < deadline:
        try:
            targets = _devtools_json(port, "/json/list")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last_error = repr(exc)
        else:
            for target in targets:
                if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                    return target
            last_error = "调试端口已就绪，但没有 page 目标：" + repr(targets)[:200]
        time.sleep(0.25)
    raise RuntimeError("Edge 调试端口 " + str(port) + " 在 " + str(timeout) + "s 内不可用：" + last_error)


def _terminate_tree(process) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        with contextlib.suppress(Exception):
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
            )
    else:
        with contextlib.suppress(Exception):
            process.terminate()
    with contextlib.suppress(Exception):
        process.wait(timeout=30)


@contextlib.contextmanager
def browser_session(*, width: int = 1400, height: int = 900):
    """启动一个无头 Edge（无痕 + 全新临时配置目录），yield 一条 CDP 会话。

    Edge 不在本机时抛 unittest.SkipTest —— 别人的机器没装 Edge 不该让测试变红。
    """
    executable = find_edge_executable()
    if not executable:
        raise unittest.SkipTest("没有找到 msedge.exe，端到端测试被跳过。")
    debug_port = free_port()
    with tempfile.TemporaryDirectory(prefix="awfm-e2e-profile-") as profile:
        command = [
            executable,
            "--headless=new",
            "--inprivate",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
            "--disable-extensions",
            "--window-size=" + str(width) + "," + str(height),
            "--remote-debugging-port=" + str(debug_port),
            "--user-data-dir=" + profile,
            "about:blank",
        ]
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        session = None
        try:
            target = _wait_for_page_target(debug_port)
            session = CdpSession(target["webSocketDebuggerUrl"])
            yield session
        finally:
            if session is not None:
                session.close()
            _terminate_tree(process)
