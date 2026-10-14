"""HTTP 端到端：真实服务 + 真实 sshd，覆盖 P0/P1 主链路（T-001 / T-003 / T-006 / T-009）。"""

import contextlib
import unittest

from app.core.errors import AwfmError
from tests.integration.support import require_testbed, running_server, testbed_environment


@require_testbed
class ApiFlowTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.config, _ = self.stack.enter_context(testbed_environment())
        self.client = self.stack.enter_context(running_server(self.config))

    def connect(self):
        response = self.client.post("/api/connections/wsl-testbed/connect", {})
        self.assertEqual(response.status, 200, response)
        self.assertEqual(response.data["connection"]["state"], "connected")
        return response

    def test_health_is_open_and_reports_version(self):
        response = self.client.get("/api/health", token=False)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.data["status"], "ok")
        self.assertIn("version", response.data)
        self.assertNotIn("X-AWFM-Token", str(response.headers))

    def test_session_info_exposes_the_trust_store_path(self):
        response = self.client.get("/api/session")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.data["host_key_policy"], "strict")
        self.assertTrue(response.data["known_hosts_path"].endswith("known_hosts"))

    def test_full_read_flow(self):
        self.connect()

        files = self.client.get("/api/connections/wsl-testbed/files?path=/etc")
        self.assertEqual(files.status, 200, files)
        self.assertEqual(files.data["path"], "/etc")
        self.assertIn("hostname", [entry["name"] for entry in files.data["entries"]])

        stat = self.client.get("/api/connections/wsl-testbed/stat?path=/bin&follow=0")
        self.assertEqual(stat.status, 200, stat)
        self.assertEqual(stat.data["type"], "symlink")

        preview = self.client.get("/api/connections/wsl-testbed/preview?path=/etc/hostname&max_bytes=64")
        self.assertEqual(preview.status, 200, preview)
        self.assertIn(preview.data["encoding"], ("utf-8", "latin-1"))
        self.assertLessEqual(preview.data["bytes_read"], 64)

        status = self.client.get("/api/connections/wsl-testbed/status")
        self.assertEqual(status.data["connection"]["home"], "/home/aimu")

        listing = self.client.get("/api/connections")
        entry = [item for item in listing.data["connections"] if item["id"] == "wsl-testbed"][0]
        self.assertEqual(entry["session"]["state"], "connected")

        keys = self.client.get("/api/connections/wsl-testbed/host-keys")
        self.assertEqual(keys.status, 200, keys)
        self.assertTrue(keys.data["keys"])
        self.assertTrue(keys.data["keys"][0]["fingerprint"].startswith("SHA256:"))

        self.client.post("/api/connections/wsl-testbed/disconnect", {})
        after = self.client.get("/api/connections/wsl-testbed/status")
        self.assertEqual(after.data["connection"]["state"], "disconnected")

    def test_upload_download_round_trip(self):
        self.connect()
        directory = "/tmp"
        name = f"awfm-api-{id(self) % 100000}.txt"
        payload = "上传内容 upload 😀\n".encode("utf-8")
        path = f"{directory}/{name}"
        try:
            first = self.client.request(
                "POST",
                f"/api/connections/wsl-testbed/upload?path={directory}&name={name}",
                body=payload,
                headers={"Content-Type": "application/octet-stream"},
            )
            self.assertEqual(first.status, 201, first)
            self.assertEqual(first.data["size"], len(payload))
            self.assertFalse(first.data["overwritten"])

            check = self.client.get(f"/api/connections/wsl-testbed/upload-check?path={directory}&name={name}")
            self.assertEqual(check.status, 200, check)
            self.assertTrue(check.data["exists"])

            second = self.client.request(
                "POST",
                f"/api/connections/wsl-testbed/upload?path={directory}&name={name}&overwrite=1",
                body=payload,
                headers={"Content-Type": "application/octet-stream"},
            )
            self.assertEqual(second.status, 200, second)
            self.assertTrue(second.data["overwritten"])

            duplicate = self.client.request(
                "POST",
                f"/api/connections/wsl-testbed/upload?path={directory}&name={name}",
                body=payload,
                headers={"Content-Type": "application/octet-stream"},
            )
            self.assertEqual(duplicate.status, 400, duplicate)
            self.assertEqual(duplicate.code, "invalid_request")

            ticket = self.client.post("/api/connections/wsl-testbed/download-ticket", {"path": path})
            self.assertEqual(ticket.status, 200, ticket)
            download = self.client.get(ticket.data["url"], token=False)
            self.assertEqual(download.status, 200, download)
            self.assertEqual(download.raw, payload)
            self.assertIn("attachment;", download.headers.get("Content-Disposition", ""))

            # 票据绑定到具体路径：换成 /etc/hostname 必须被拒。
            stolen = self.client.get(
                f"/api/connections/wsl-testbed/download?ticket={ticket.data['ticket']}&path=/etc/hostname",
                token=False,
            )
            self.assertEqual(stolen.status, 401, stolen)
            self.assertEqual(stolen.code, "unauthorized")
        finally:
            # 写操作没有对外暴露删除端点（属 P2），清理时直接驱动连接层。
            with contextlib.suppress(AwfmError, Exception):
                self.client.manager.session("wsl-testbed").client.remove(path)

    def test_errors_are_structured(self):
        missing = self.client.get("/api/connections/nope/files?path=/")
        self.assertEqual(missing.status, 404)
        self.assertEqual(missing.code, "connection_not_found")

        # 处理函数先取会话再校验路径，所以要先连上才观察得到 400。
        self.connect()

        relative = self.client.get("/api/connections/wsl-testbed/files?path=etc")
        self.assertEqual(relative.status, 400)
        self.assertEqual(relative.code, "invalid_request")

        no_path = self.client.get("/api/connections/wsl-testbed/files")
        self.assertEqual(no_path.status, 400)

        self.client.post("/api/connections/wsl-testbed/disconnect", {})

        not_connected = self.client.get("/api/connections/wsl-testbed/files?path=/")
        self.assertEqual(not_connected.status, 404)
        self.assertEqual(not_connected.code, "session_not_found")

        wrong_method = self.client.delete("/api/health")
        self.assertEqual(wrong_method.status, 400)
        self.assertEqual(wrong_method.code, "invalid_request")

        unknown_api = self.client.get("/api/nope")
        self.assertEqual(unknown_api.status, 404)

    def test_unauthorized_requests(self):
        self.assertEqual(self.client.get("/api/connections", token=False).status, 401)
        self.assertEqual(self.client.get("/api/connections", headers={"Host": "evil.example.com"}).status, 400)
        self.assertEqual(self.client.request("OPTIONS", "/api/connections").status, 403)
        self.assertEqual(
            self.client.post("/api/connections", {}, headers={"Origin": "http://evil.example.com"}).status, 401
        )
        self.assertEqual(
            self.client.post("/api/connections", {}, headers={"Sec-Fetch-Site": "cross-site"}).status, 401
        )

    def test_static_files_are_served_with_a_csp(self):
        page = self.client.get("/", token=False)
        self.assertEqual(page.status, 200)
        self.assertIn("awfm-token", page.raw.decode("utf-8"))
        csp = page.headers.get("Content-Security-Policy", "")
        self.assertIn("default-src 'self'", csp)
        self.assertNotIn("http://", page.raw.decode("utf-8").replace("http://www.w3.org", ""))

        missing = self.client.get("/assets/js/nope.js", token=False)
        self.assertEqual(missing.status, 404)

        traversal = self.client.get("/assets/../app/main.py", token=False)
        self.assertIn(traversal.status, (400, 404))

    def test_crud_over_the_api(self):
        created = self.client.post(
            "/api/connections",
            {
                "name": "临时连接",
                "host": "192.168.170.128",
                "port": 22,
                "username": "root",
                "auth_method": "key",
            },
        )
        self.assertEqual(created.status, 201, created)
        new_id = created.data["connection"]["id"]

        patched = self.client.patch(f"/api/connections/{new_id}", {"note": "改过了"})
        self.assertEqual(patched.data["connection"]["note"], "改过了")
        self.assertEqual(patched.data["connection"]["id"], new_id)

        listed = self.client.get("/api/connections")
        self.assertIn(new_id, [item["id"] for item in listed.data["connections"]])

        self.assertEqual(self.client.delete(f"/api/connections/{new_id}").status, 200)
        self.assertEqual(self.client.get(f"/api/connections/{new_id}").status, 404)


if __name__ == "__main__":
    unittest.main()
