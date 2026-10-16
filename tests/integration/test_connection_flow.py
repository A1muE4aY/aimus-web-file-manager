"""连接层端到端：真实 ssh/sftp 子进程 + 真实 sshd（T-003 / T-006 / T-009 / T-013）。"""

import contextlib
import os
import sys
import unittest
from urllib.parse import quote

from app.core.errors import AwfmError, HostKeyUnknown, NotConnected
from app.services import filesystem
from app.services.connection_manager import ConnectionManager
from app.services.session import RemoteSession
from app.ssh.known_hosts import find_trusted_keys
from tests.integration.support import (
    TESTBED_HOME,
    count_testbed_ssh_processes,
    require_testbed,
    running_server,
    testbed_connection,
    testbed_environment,
)


@require_testbed
class SshFlowTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.config, self.host_keys = self.stack.enter_context(testbed_environment())
        self.session = RemoteSession(self.config.connections[0])
        self.addCleanup(self.stack.close)
        self.addCleanup(self._disconnect)

    def _disconnect(self):
        with contextlib.suppress(Exception):
            self.session.disconnect()

    def test_connect_reports_home_and_server_version(self):
        status = self.session.connect("", settings=self.config)
        self.assertTrue(status["connected"])
        self.assertEqual(status["state"], "connected")
        self.assertEqual(status["home"], TESTBED_HOME)
        self.assertEqual(status["server_version"], 3)

    def test_unknown_host_key_is_refused_then_trusted_after_confirmation(self):
        config, _ = self.stack.enter_context(testbed_environment(trust=False))
        manager = ConnectionManager(config)
        self.addCleanup(manager.disconnect_all)
        with self.assertRaises(HostKeyUnknown) as ctx:
            manager.connect("wsl-testbed")
        fingerprints = ctx.exception.extra["fingerprints"]
        self.assertTrue(fingerprints)
        self.assertTrue(fingerprints[0]["fingerprint"].startswith("SHA256:"))
        # 首次连接**不写**信任库：写不写由用户确认决定。
        self.assertEqual(find_trusted_keys(config.known_hosts_path, "127.0.0.1", 2222), [])
        result = manager.trust_host_key(
            "wsl-testbed", fingerprints[0]["key_type"], fingerprints[0]["fingerprint"]
        )
        self.assertTrue(result["added"])
        self.assertTrue(manager.connect("wsl-testbed")["connected"])

    def test_wrong_fingerprint_is_refused_and_nothing_is_written(self):
        config, _ = self.stack.enter_context(testbed_environment(trust=False))
        manager = ConnectionManager(config)
        self.addCleanup(manager.disconnect_all)
        with self.assertRaises(AwfmError):
            manager.trust_host_key(
                "wsl-testbed", "ssh-ed25519", "SHA256:" + "A" * 43
            )
        self.assertEqual(find_trusted_keys(config.known_hosts_path, "127.0.0.1", 2222), [])

    def test_listing_a_real_directory(self):
        self.session.connect("", settings=self.config)
        result = filesystem.list_directory(self.session, "/etc")
        self.assertEqual(result["path"], "/etc")
        names = [entry["name"] for entry in result["entries"]]
        self.assertIn("hostname", names)
        self.assertTrue(all(entry["path"].startswith("/etc/") for entry in result["entries"]))
        order = {"directory": 0, "symlink": 1, "file": 2}
        types = [entry["type"] for entry in result["entries"]]
        self.assertEqual(types, sorted(types, key=lambda kind: order.get(kind, 3)))

    def test_symlink_stat_both_ways(self):
        self.session.connect("", settings=self.config)
        followed = filesystem.stat_path(self.session, "/bin")
        self.assertEqual(followed["type"], "directory")
        self.assertEqual(followed["path"], "/usr/bin")
        raw = filesystem.stat_path(self.session, "/bin", follow=False)
        self.assertEqual(raw["type"], "symlink")
        self.assertIn("link_target", raw)

    def test_round_trip_mkdir_upload_download_rename_remove(self):
        self.session.connect("", settings=self.config)
        client = self.session.client
        directory = f"/tmp/awfm-it-{os.getpid()}-{id(self) % 100000}"
        payload = "第一行\n第二行\nemoji 😀\n".encode("utf-8")
        target = f"{directory}/样本 文件.txt"
        renamed = f"{directory}/改名后.txt"
        try:
            client.mkdir(directory, 0o700)
            listing = filesystem.list_directory(self.session, "/tmp")
            mode = [
                entry for entry in listing["entries"]
                if entry["name"] == os.path.basename(directory)
            ][0]["mode"]
            self.assertEqual(mode, "0700")

            written = client.upload_stream(target, [payload], expected_size=len(payload))
            self.assertEqual(written, len(payload))

            info = filesystem.stat_path(self.session, target)
            self.assertEqual(info["size"], len(payload))
            self.assertEqual(info["name"], "样本 文件.txt")

            self.assertEqual(b"".join(client.download_chunks(target)), payload)
            self.assertEqual(
                filesystem.read_text_preview(self.session, target)["text"],
                payload.decode("utf-8"),
            )

            client.rename(target, renamed)
            # SftpClient.listdir 返回的是 NameEntry 对象，不是字典。
            self.assertEqual([entry.filename for entry in client.listdir(directory)], ["改名后.txt"])
            client.remove(renamed)
            self.assertEqual(client.listdir(directory), [])
        finally:
            for path in (target, renamed):
                with contextlib.suppress(AwfmError):
                    client.remove(path)
            with contextlib.suppress(AwfmError):
                client.rmdir(directory)

    def test_disconnect_releases_the_child_process(self):
        before = count_testbed_ssh_processes()
        self.session.connect("", settings=self.config)
        self.assertGreaterEqual(count_testbed_ssh_processes(), before + 1)
        self.session.disconnect()
        self.assertEqual(self.session.state, "disconnected")
        with self.assertRaises(NotConnected):
            self.session.client
        if sys.platform == "win32":
            self.assertEqual(count_testbed_ssh_processes(), before)

    def test_status_before_connecting(self):
        status = self.session.status()
        self.assertEqual(status["state"], "disconnected")
        self.assertFalse(status["connected"])
        self.assertIsNone(status["home"])


@require_testbed
class BrokenChannelTests(unittest.TestCase):
    """通道被动断开后的状态与恢复路径（v0.1.2 缺陷 D2）。

    真杀掉 ssh 子进程，而不是伪造一个 NotConnected：接口层必须如实报错，把会话
    标成 error（旧版一直是「已连接」，卡片状态与实情不符），并且重新连接真的能救
    回来（旧版的「重试」只是对着同一个死会话重发）。
    """

    CONNECTION = "wsl-broken"

    def setUp(self):
        self.stack = contextlib.ExitStack()
        config, _keys = self.stack.enter_context(
            testbed_environment(
                connections=[testbed_connection(id=self.CONNECTION, allow_write=True)]
            )
        )
        self.client = self.stack.enter_context(running_server(config))
        self.addCleanup(self.stack.close)
        self.expect(self.client.post("/api/connections/%s/connect" % self.CONNECTION, {}), 200)

    def expect(self, response, status):
        self.assertEqual(response.status, status, response)
        return response

    def files(self):
        url = "/api/connections/%s/files?path=%s" % (self.CONNECTION, quote(TESTBED_HOME, safe=""))
        return self.client.get(url)

    def kill_channel(self):
        """把通道真的弄断：杀掉这条会话的 ssh 子进程。"""
        session = self.client.manager._sessions[self.CONNECTION]
        process = session._transport._proc
        process.kill()
        process.wait(timeout=10)

    def test_broken_channel_is_marked_and_can_be_reconnected(self):
        self.expect(self.files(), 200)

        self.kill_channel()
        failed = self.files()
        self.expect(failed, 409)
        self.assertEqual(failed.code, "not_connected")
        self.assertTrue(failed.error["message"])

        # 会话状态要跟着变 —— 界面的连接卡片靠它决定显示什么。
        status = self.client.get(
            "/api/connections/%s/status" % self.CONNECTION
        ).data["connection"]
        self.assertEqual(status["state"], "error", status)
        self.assertFalse(status["connected"])
        self.assertTrue(status["last_error"], status)
        listing = {
            item["id"]: item["session"]
            for item in self.client.get("/api/connections").data["connections"]
        }
        self.assertEqual(listing[self.CONNECTION]["state"], "error")

        # 恢复路径：重新连接（界面上那个入口）必须真的能用。
        self.expect(self.client.post("/api/connections/%s/connect" % self.CONNECTION, {}), 200)
        self.expect(self.files(), 200)

    def test_a_second_request_after_the_loss_is_refused_not_retried(self):
        self.kill_channel()
        self.expect(self.files(), 409)

        # 标成 error 之后会话不再被交出去：界面据此把「重试」换成「重新连接」。
        again = self.files()
        self.expect(again, 404)
        self.assertEqual(again.code, "session_not_found")


if __name__ == "__main__":
    unittest.main()
