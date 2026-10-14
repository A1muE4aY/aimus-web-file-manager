"""API 安全：只监听回环本身不是安全边界。"""

import unittest

from app.api.security import (
    ALLOWED_HOSTS,
    OPEN_PATHS,
    check_fetch_metadata,
    check_host_header,
    check_token,
    new_session_token,
    verify_api_request,
)
from app.core.errors import Unauthorized, ValidationError


class FakeHandler:
    def __init__(self, headers=None):
        self.headers = dict(headers or {})


class TokenTests(unittest.TestCase):
    def test_tokens_are_unique_and_long(self):
        tokens = {new_session_token() for _ in range(20)}
        self.assertEqual(len(tokens), 20)
        self.assertTrue(all(len(t) >= 32 for t in tokens))

    def test_missing_token_is_refused(self):
        with self.assertRaises(Unauthorized) as ctx:
            check_token(None, "expected")
        self.assertEqual(ctx.exception.code, "unauthorized")

    def test_wrong_token_is_refused(self):
        with self.assertRaises(Unauthorized):
            check_token("guess", "expected")

    def test_correct_token_passes(self):
        check_token("expected", "expected")


class HostHeaderTests(unittest.TestCase):
    def test_loopback_forms_pass(self):
        for value in ("127.0.0.1", "127.0.0.1:8760", "localhost:8760", "LOCALHOST", "[::1]", "[::1]:8760"):
            check_host_header(value, allow_lan=False)

    def test_missing_host_passes_for_old_clients(self):
        check_host_header(None)
        check_host_header("")

    def test_unbracketed_ipv6_is_refused(self):
        # RFC 7230 要求 IPv6 字面量带方括号；不带括号的写法还有歧义
        # （::1:8760 分不清主机与端口），按 fail-closed 拒绝。
        with self.assertRaises(ValidationError):
            check_host_header("::1")

    def test_foreign_host_is_refused(self):
        # DNS 重绑定：攻击者域名解析到 127.0.0.1，浏览器视为同源。
        for value in ("evil.example.com", "192.168.1.5:8760", "127.0.0.1.evil.com", "0.0.0.0"):
            with self.assertRaises(ValidationError, msg=value):
                check_host_header(value)

    def test_allow_lan_disables_the_check(self):
        check_host_header("192.168.1.5:8760", allow_lan=True)

    def test_error_carries_the_offending_host(self):
        with self.assertRaises(ValidationError) as ctx:
            check_host_header("evil.example.com")
        self.assertEqual(ctx.exception.extra["host"], "evil.example.com")


class FetchMetadataTests(unittest.TestCase):
    def test_same_origin_and_direct_navigation_pass(self):
        check_fetch_metadata(None, None)
        check_fetch_metadata(None, "same-origin")
        check_fetch_metadata(None, "none")
        check_fetch_metadata("http://127.0.0.1:8760", None)
        check_fetch_metadata("http://localhost:8760", "same-origin")

    def test_cross_site_is_refused(self):
        for value in ("cross-site", "same-site"):
            with self.assertRaises(Unauthorized, msg=value):
                check_fetch_metadata(None, value)

    def test_foreign_origin_is_refused(self):
        for value in ("http://evil.example.com", "https://evil.example.com:443", "null", "file://x", "127.0.0.1"):
            with self.assertRaises(Unauthorized, msg=value):
                check_fetch_metadata(value, None)


class VerifyRequestTests(unittest.TestCase):
    def test_health_needs_no_token(self):
        handler = FakeHandler({"Host": "127.0.0.1:8760"})
        verify_api_request(handler, token="t", path="/api/health")

    def test_open_paths_are_exactly_the_documented_set(self):
        self.assertEqual(OPEN_PATHS, frozenset({"/api/health"}))

    def test_normal_path_needs_token(self):
        handler = FakeHandler({"Host": "127.0.0.1:8760"})
        with self.assertRaises(Unauthorized):
            verify_api_request(handler, token="t", path="/api/connections")
        handler.headers["X-AWFM-Token"] = "t"
        verify_api_request(handler, token="t", path="/api/connections")

    def test_ticket_skips_the_token_but_not_the_host_check(self):
        handler = FakeHandler({"Host": "evil.example.com"})
        with self.assertRaises(ValidationError):
            verify_api_request(handler, token="t", path="/api/connections/vm1/download", ticket_ok=True)
        handler.headers["Host"] = "127.0.0.1:8760"
        verify_api_request(handler, token="t", path="/api/connections/vm1/download", ticket_ok=True)

    def test_host_check_runs_before_token_check(self):
        # 顺序有意义：Host 不对时不该因为顺带漏了令牌而报出误导性的错误码。
        handler = FakeHandler({"Host": "evil.example.com"})
        with self.assertRaises(ValidationError):
            verify_api_request(handler, token="t", path="/api/connections")

    def test_allowed_hosts_are_literals_only(self):
        # 白名单里必须是字面量：放进去一个主机名，DNS 重绑定防护就交还给 DNS 了。
        self.assertEqual(ALLOWED_HOSTS, frozenset({"127.0.0.1", "localhost", "[::1]"}))
        for name in ALLOWED_HOSTS:
            self.assertNotIn("*", name, name)
            self.assertFalse(name.endswith("."), name)


if __name__ == "__main__":
    unittest.main()
