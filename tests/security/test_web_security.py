"""Web 层安全测试（不需要测试床）。

依据规划文档 §7.1 的 T-008、§7.2 的安全测试层与 §10。

覆盖四类：

1. 未授权调用：除 /api/health 外，所有 API 都必须带会话令牌。
2. CSRF 与 DNS 重绑定：预检一律拒绝且不发 CORS 头；Host / Origin / Sec-Fetch-Site 校验。
3. 静态资源边界：任何形式的目录穿越都不得读到 frontend/ 之外的文件。
4. 响应头策略：CSP、nosniff、no-store，且 Server 头不泄漏解释器版本。

为什么值得单列：只监听回环地址不是安全边界 —— 上面四类攻击都发生在浏览器里，
不需要攻击者能连上我们的端口（见 app/api/security.py 的模块说明）。
"""

from __future__ import annotations

import unittest

from app import __version__
from app.core.config import project_root
from tests.security.support import DEAD_CONNECTION, header, local_server

#: 全部 API 端点（连接 id 用不存在的值）。不带令牌时必须一律 401。
API_ENDPOINTS = [
    ("GET", "/api/session"),
    ("GET", "/api/connections"),
    ("POST", "/api/connections"),
    ("GET", "/api/connections/nope"),
    ("PATCH", "/api/connections/nope"),
    ("DELETE", "/api/connections/nope"),
    ("POST", "/api/connections/nope/connect"),
    ("POST", "/api/connections/nope/disconnect"),
    ("GET", "/api/connections/nope/status"),
    ("GET", "/api/connections/nope/host-keys"),
    ("POST", "/api/connections/nope/host-keys/trust"),
    ("GET", "/api/connections/nope/files?path=/"),
    ("GET", "/api/connections/nope/stat?path=/"),
    ("GET", "/api/connections/nope/preview?path=/"),
    ("POST", "/api/connections/nope/download-ticket"),
    ("GET", "/api/connections/nope/download?path=/"),
    ("POST", "/api/connections/nope/upload?path=/&name=x"),
    ("GET", "/api/connections/nope/upload-check?path=/&name=x"),
]


class UnauthenticatedAccessTests(unittest.TestCase):
    def test_every_api_endpoint_requires_the_token(self):
        with local_server(connections=[DEAD_CONNECTION]) as harness:
            for method, path in API_ENDPOINTS:
                with self.subTest(method=method, path=path):
                    response = harness.client.request(method, path, token=False)
                    self.assertEqual(response.status, 401, response)
                    self.assertEqual(response.code, "unauthorized", response)

    def test_health_is_open_and_carries_no_secrets(self):
        with local_server(connections=[DEAD_CONNECTION]) as harness:
            response = harness.client.get("/api/health", token=False)
            self.assertEqual(response.status, 200, response)
            self.assertEqual(response.data["status"], "ok")
            self.assertNotIn("token", response.raw.decode("utf-8"))

    def test_wrong_token_is_rejected(self):
        with local_server(connections=[DEAD_CONNECTION]) as harness:
            real = harness.client.token
            for fake in ("", "x", real[:-1], real + "x", "0" * len(real)):
                with self.subTest(token=fake[:8]):
                    response = harness.client.get(
                        "/api/session", token=False, headers={"X-AWFM-Token": fake}
                    )
                    self.assertEqual(response.status, 401, response)

    def test_preflight_is_refused_and_no_cors_headers_are_ever_sent(self):
        with local_server(connections=[DEAD_CONNECTION]) as harness:
            preflight = harness.client.request("OPTIONS", "/api/connections", token=False)
            self.assertEqual(preflight.status, 403, preflight)
            self.assertEqual(header(preflight, "Access-Control-Allow-Origin"), "")
            for path in ("/api/health", "/api/session", "/"):
                with self.subTest(path=path):
                    response = harness.client.get(path, token=False)
                    self.assertEqual(header(response, "Access-Control-Allow-Origin"), "", path)
                    self.assertEqual(
                        header(response, "Access-Control-Allow-Credentials"), "", path
                    )


class HostAndOriginTests(unittest.TestCase):
    def test_host_header_must_be_a_loopback_name(self):
        with local_server(connections=[DEAD_CONNECTION]) as harness:
            port = harness.client.port
            hostile = ("evil.example", "evil.example:1234", "::1:" + str(port),
                       "127.0.0.1.evil.example", "localhost.evil.example")
            for host in hostile:
                with self.subTest(host=host):
                    response = harness.client.get(
                        "/api/health", token=False, headers={"Host": host}
                    )
                    self.assertEqual(response.status, 400, response)
                    self.assertEqual(response.code, "invalid_request", response)
            for host in ("127.0.0.1:" + str(port), "localhost:" + str(port)):
                with self.subTest(host=host):
                    response = harness.client.get(
                        "/api/health", token=False, headers={"Host": host}
                    )
                    self.assertEqual(response.status, 200, response)

    def test_cross_site_fetch_metadata_is_refused(self):
        with local_server(connections=[DEAD_CONNECTION]) as harness:
            port = harness.client.port
            hostile = (
                {"Sec-Fetch-Site": "cross-site"},
                {"Sec-Fetch-Site": "same-site"},
                {"Origin": "http://evil.example"},
                {"Origin": "null"},
                {"Origin": "file://"},
            )
            for headers in hostile:
                with self.subTest(headers=headers):
                    response = harness.client.get("/api/session", headers=headers)
                    self.assertEqual(response.status, 401, response)
                    self.assertEqual(response.code, "unauthorized", response)
            accepted = harness.client.get(
                "/api/session",
                headers={
                    "Sec-Fetch-Site": "same-origin",
                    "Origin": "http://127.0.0.1:" + str(port),
                },
            )
            self.assertEqual(accepted.status, 200, accepted)


class StaticFileBoundaryTests(unittest.TestCase):
    HOSTILE = [
        "/../README.md",
        "/%2e%2e/README.md",
        "/assets/../../README.md",
        "/assets/js/../../../../app/main.py",
        "/assets/js/..%2f..%2f..%2f..%2fapp%2fmain.py",
        "/assets/%00.js",
        "/app/main.py",
        "/config/config.example.json",
        "/nope.js",
    ]

    def test_positive_control_static_assets_are_served(self):
        with local_server(connections=[DEAD_CONNECTION]) as harness:
            for path in ("/", "/index.html", "/assets/css/app.css", "/assets/js/app.js"):
                with self.subTest(path=path):
                    self.assertEqual(harness.client.get(path).status, 200, path)

    def test_traversal_attempts_never_read_project_files(self):
        with local_server(connections=[DEAD_CONNECTION]) as harness:
            for path in self.HOSTILE:
                with self.subTest(path=path):
                    response = harness.client.get(path)
                    self.assertIn(response.status, (400, 404), response)
                    text = response.raw.decode("utf-8", errors="replace")
                    for marker in ("__version__", "aimus-web-file-manager", "[server]"):
                        self.assertNotIn(marker, text, path)

    def test_index_html_injects_a_fresh_token(self):
        with local_server(connections=[DEAD_CONNECTION]) as harness:
            response = harness.client.get("/")
            text = response.raw.decode("utf-8")
            self.assertNotIn("<!--AWFM_TOKEN-->", text)
            self.assertIn(harness.client.token, text)


class ResponseHeaderPolicyTests(unittest.TestCase):
    def test_security_headers_on_success_and_error(self):
        with local_server(connections=[DEAD_CONNECTION]) as harness:
            responses = {
                "html": harness.client.get("/"),
                "json": harness.client.get("/api/health", token=False),
                "error": harness.client.get("/api/session", token=False),
                "static": harness.client.get("/assets/css/app.css"),
            }
            for kind, response in responses.items():
                with self.subTest(kind=kind):
                    self.assertEqual(header(response, "X-Content-Type-Options"), "nosniff")
                    self.assertEqual(header(response, "Referrer-Policy"), "no-referrer")
                    self.assertEqual(header(response, "X-Frame-Options"), "DENY")
                    self.assertEqual(header(response, "Cache-Control"), "no-store")
                    self.assertTrue(header(response, "Content-Security-Policy"), kind)
            self.assertIn(
                "script-src 'self'",
                header(responses["html"], "Content-Security-Policy"),
            )
            self.assertEqual(
                header(responses["json"], "Content-Security-Policy"),
                "default-src 'none'; frame-ancestors 'none'",
            )

    def test_server_header_does_not_leak_the_interpreter(self):
        with local_server(connections=[DEAD_CONNECTION]) as harness:
            server = header(harness.client.get("/"), "Server")
            self.assertEqual(server, "AWFM/" + __version__)
            self.assertNotIn("Python", server)
            self.assertNotIn("BaseHTTP", server)


class MethodPolicyTests(unittest.TestCase):
    def test_unsupported_method_lists_the_allowed_ones(self):
        with local_server(connections=[DEAD_CONNECTION]) as harness:
            response = harness.client.request("PUT", "/api/health")
            self.assertEqual(response.status, 400, response)
            self.assertEqual(response.code, "invalid_request", response)
            detail = response.error.get("detail", "")
            self.assertIn("允许的方法", detail)
            self.assertIn("GET", detail)

    def test_unknown_api_path_is_404(self):
        with local_server(connections=[DEAD_CONNECTION]) as harness:
            response = harness.client.get("/api/nope")
            self.assertEqual(response.status, 404, response)
            self.assertEqual(response.code, "path_not_found", response)

    def test_static_responses_only_allow_get(self):
        with local_server(connections=[DEAD_CONNECTION]) as harness:
            response = harness.client.request("POST", "/index.html")
            self.assertEqual(response.status, 400, response)
            self.assertEqual(response.code, "invalid_request", response)


class OfflineFrontendTests(unittest.TestCase):
    """T-002 的自动化部分：前端资源里不得出现任何在线地址。

    唯一例外是 xmlns="http://www.w3.org/2000/svg"：它是命名空间标识符，
    不是网络请求，浏览器不会去取它。
    """

    ALLOWED = ("http://www.w3.org/2000/svg",)

    def test_frontend_has_no_remote_resources(self):
        root = project_root() / "frontend"
        self.assertTrue(root.is_dir(), "找不到 frontend/ 目录：" + str(root))
        offenders = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for needle in ("http://", "https://"):
                index = text.find(needle)
                while index >= 0:
                    snippet = " ".join(text[index:index + 80].split())
                    if not any(snippet.startswith(allowed) for allowed in self.ALLOWED):
                        offenders.append(path.name + ": " + snippet)
                    index = text.find(needle, index + 1)
        self.assertEqual(offenders, [], "前端出现了在线地址：\n" + "\n".join(offenders))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
