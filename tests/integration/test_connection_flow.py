"""连接层端到端：真实 ssh/sftp 子进程 + 真实 sshd（T-003 / T-006 / T-009 / T-013）。"""

import contextlib
import os
import sys
import unittest

from app.core.errors import AwfmError, HostKeyUnknown, NotConnected
from app.services import filesystem
from app.services.connection_manager import ConnectionManager
from app.services.session import RemoteSession
from app.ssh.known_hosts import find_trusted_keys
from tests.integration.support import (
    TESTBED_HOME,
    count_testbed_ssh_processes,
    require_testbed,
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


if __name__ == "__main__":
    unittest.main()
