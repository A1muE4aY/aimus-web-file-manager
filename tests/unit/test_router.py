"""正则路由器：零第三方依赖下的路径分发。"""

import unittest

from app.api.router import Router


def handler_a():
    return "a"


def handler_b():
    return "b"


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.router = Router()
        self.router.get(r"/api/connections", handler_a)
        self.router.get(r"/api/connections/(?P<connection_id>[^/]+)", handler_b)
        self.router.post(r"/api/connections", handler_b)

    def test_static_match(self):
        found, params = self.router.match("GET", "/api/connections")
        self.assertIs(found, handler_a)
        self.assertEqual(params, {})

    def test_named_parameter(self):
        found, params = self.router.match("GET", "/api/connections/vm1")
        self.assertIs(found, handler_b)
        self.assertEqual(params, {"connection_id": "vm1"})

    def test_method_is_part_of_the_key(self):
        found, _ = self.router.match("POST", "/api/connections")
        self.assertIs(found, handler_b)

    def test_unknown_path_returns_no_handler(self):
        found, allowed = self.router.match("GET", "/api/nope")
        self.assertIsNone(found)
        self.assertEqual(allowed, [])

    def test_wrong_method_reports_allowed_methods(self):
        found, allowed = self.router.match("DELETE", "/api/connections")
        self.assertIsNone(found)
        self.assertEqual(allowed, ["GET", "POST"])

    def test_patterns_are_anchored(self):
        # 不锚定的话 /api/connectionsX 会命中 /api/connections。
        found, _ = self.router.match("GET", "/api/connectionsX")
        self.assertIsNone(found)

    def test_parameter_does_not_swallow_slashes(self):
        found, _ = self.router.match("GET", "/api/connections/a/b")
        self.assertIsNone(found)

    def test_first_registered_route_wins(self):
        router = Router()
        router.get(r"/x/(?P<a>[^/]+)", handler_a)
        router.get(r"/x/(?P<b>[^/]+)", handler_b)
        found, params = router.match("GET", "/x/1")
        self.assertIs(found, handler_a)
        self.assertEqual(params, {"a": "1"})

    def test_routes_are_listed(self):
        self.assertEqual(len(self.router.routes), 3)
        self.assertEqual(self.router.routes[0].name, "GET /api/connections")


class RealRouterTests(unittest.TestCase):
    def test_project_router_builds_and_matches_every_documented_endpoint(self):
        from app.api.handlers import build_router

        router = build_router()
        expected = [
            ("GET", "/api/health"),
            ("GET", "/api/session"),
            ("GET", "/api/connections"),
            ("POST", "/api/connections"),
            ("GET", "/api/connections/vm1"),
            ("PATCH", "/api/connections/vm1"),
            ("DELETE", "/api/connections/vm1"),
            ("POST", "/api/connections/vm1/connect"),
            ("POST", "/api/connections/vm1/disconnect"),
            ("GET", "/api/connections/vm1/status"),
            ("GET", "/api/connections/vm1/host-keys"),
            ("POST", "/api/connections/vm1/host-keys/trust"),
            ("GET", "/api/connections/vm1/files"),
            ("GET", "/api/connections/vm1/stat"),
            ("GET", "/api/connections/vm1/preview"),
            ("GET", "/api/connections/vm1/download"),
            ("POST", "/api/connections/vm1/download-ticket"),
            ("POST", "/api/connections/vm1/upload"),
            ("GET", "/api/connections/vm1/upload-check"),
        ]
        for method, path in expected:
            found, params = router.match(method, path)
            self.assertIsNotNone(found, f"{method} {path}")
            self.assertIn("connection_id", params) if "connections/" in path else None

    def test_connection_id_cannot_contain_slash(self):
        from app.api.handlers import build_router

        router = build_router()
        found, _ = router.match("GET", "/api/connections/a/b/files")
        self.assertIsNone(found)


if __name__ == "__main__":
    unittest.main()
