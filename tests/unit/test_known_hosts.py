"""主机密钥信任库：解析、指纹格式、写入（决策 D-010）。"""

import base64
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from app.core.errors import AwfmError
from app.ssh import known_hosts as kh


def sample_key(key_type="ssh-ed25519", blob=b"this-is-a-fake-key-blob", comment="test"):
    return kh.HostKey(key_type=key_type, key_b64=base64.b64encode(blob).decode("ascii"), comment=comment)


class FingerprintTests(unittest.TestCase):
    def test_matches_openssh_format(self):
        # 用户会拿这个指纹与终端里 ssh-keygen -lf 的输出逐字符对照，格式必须一致。
        blob = bytes(range(32))
        b64 = base64.b64encode(blob).decode("ascii")
        expected = "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")
        self.assertEqual(kh.fingerprint_of("ssh-ed25519", b64), expected)
        self.assertNotIn("=", kh.fingerprint_of("ssh-ed25519", b64))

    def test_stable_and_input_dependent(self):
        first = kh.fingerprint_of("ssh-ed25519", sample_key().key_b64)
        second = kh.fingerprint_of("ssh-ed25519", sample_key().key_b64)
        other = kh.fingerprint_of("ssh-ed25519", sample_key(blob=b"another").key_b64)
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)

    def test_host_key_carries_fingerprint_and_line(self):
        key = sample_key()
        self.assertTrue(key.fingerprint.startswith("SHA256:"))
        line = key.to_line()
        self.assertTrue(line.startswith("ssh-ed25519 "))
        self.assertIn(key.key_b64, line)
        self.assertIn("test", line)


class PatternTests(unittest.TestCase):
    def test_default_port_has_no_brackets(self):
        self.assertEqual(kh.host_key_pattern("192.168.1.5", 22), "192.168.1.5")

    def test_non_default_port_uses_brackets(self):
        # 写成 host:port 会被 ssh 静默忽略 —— 信任库看着有记录，实际每次都当首次连接。
        self.assertEqual(kh.host_key_pattern("192.168.1.5", 2222), "[192.168.1.5]:2222")


class ParseTests(unittest.TestCase):
    def test_parses_plain_entries(self):
        text = "\n".join(
            [
                "# 注释行",
                "",
                "host1 ssh-ed25519 AAAABBBB comment one",
                "[host2]:2222 ssh-rsa CCCCDDDD",
                "|1|aGFzaA=|aGFzaA= ssh-ed25519 HASHED",
                "host3 ssh-unknown-type EEEE",
                "host4 ssh-ed25519",
            ]
        )
        entries = kh.parse_known_hosts_text(text)
        patterns = [patterns for patterns, _ in entries]
        self.assertIn(["host1"], patterns)
        self.assertIn(["[host2]:2222"], patterns)
        self.assertNotIn(["host3"], patterns)  # 未知密钥类型
        self.assertNotIn(["host4"], patterns)  # 缺少密钥本体
        self.assertTrue(all(not p[0].startswith("|1|") for p in patterns))  # 哈希主机名行跳过

    def test_keeps_supported_key_types(self):
        for key_type in ("ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256"):
            entries = kh.parse_known_hosts_text("host " + key_type + " AAAA comment")
            self.assertEqual(len(entries), 1, key_type)
            self.assertEqual(entries[0][1].key_type, key_type)


class TrustStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "known_hosts"

    def tearDown(self):
        self._tmp.cleanup()

    def test_ensure_creates_file_and_parent(self):
        kh.ensure_known_hosts_file(self.path)
        self.assertTrue(self.path.is_file())
        kh.ensure_known_hosts_file(self.path)  # 幂等

    def test_append_then_find(self):
        key = sample_key()
        kh.append_trusted_key(self.path, "127.0.0.1", 2222, key)
        found = kh.find_trusted_keys(self.path, "127.0.0.1", 2222)
        self.assertEqual([k.fingerprint for k in found], [key.fingerprint])

    def test_port_is_part_of_identity(self):
        kh.append_trusted_key(self.path, "127.0.0.1", 2222, sample_key())
        self.assertEqual(kh.find_trusted_keys(self.path, "127.0.0.1", 22), [])

    def test_multiple_key_types_for_one_host(self):
        kh.append_trusted_key(self.path, "h", 22, sample_key("ssh-ed25519"))
        kh.append_trusted_key(self.path, "h", 22, sample_key("ssh-rsa", blob=b"rsa-blob"))
        found = kh.find_trusted_keys(self.path, "h", 22)
        self.assertEqual({k.key_type for k in found}, {"ssh-ed25519", "ssh-rsa"})

    def test_append_is_atomic_and_keeps_existing(self):
        first = sample_key()
        second = sample_key("ssh-rsa", blob=b"rsa")
        kh.append_trusted_key(self.path, "a", 22, first)
        kh.append_trusted_key(self.path, "b", 22, second)
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("a ssh-ed25519", text)
        self.assertIn("b ssh-rsa", text)
        self.assertIn("AWFM", text)  # 标注来源与时间，用户手工排查时知道这行是谁写的

    def test_missing_file_yields_no_keys(self):
        self.assertEqual(kh.find_trusted_keys(self.path, "h", 22), [])

    def test_hashed_hosts_detection(self):
        self.path.write_text("|1|aGFzaA=|aGFzaA= ssh-ed25519 AAAA\n", encoding="utf-8")
        self.assertTrue(kh.looks_like_hashed_hosts(self.path))
        self.path.write_text("h ssh-ed25519 AAAA\n", encoding="utf-8")
        self.assertFalse(kh.looks_like_hashed_hosts(self.path))


class CollectFailureTests(unittest.TestCase):
    """采集失败必须报成结构化错误，而不是内部 TypeError。

    127.0.0.1:9 是 discard 端口，本机不会有人监听 —— ssh 立刻失败，
    所以这条用例不需要测试床、也几乎不花时间。
    """

    def test_dead_port_raises_a_structured_error(self):
        ssh = shutil.which("ssh")
        if not ssh:
            self.skipTest("本机没有 ssh 客户端")
        with self.assertRaises(AwfmError) as caught:
            kh.collect_host_keys(ssh_executable=ssh, host="127.0.0.1", port=9, connect_timeout=3)
        error = caught.exception
        # 关键断言：错误码与状态码来自错误模型（502/504），不是 500 internal_error。
        self.assertIn(error.code, {"remote_error", "timeout"})
        self.assertIn(error.http_status, {502, 504})
        self.assertTrue(error.detail, "结构化错误必须给出可排查的 detail")


if __name__ == "__main__":
    unittest.main()
