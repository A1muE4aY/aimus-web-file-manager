"""连接模型：id/主机/端口/用户名的校验，以及「密码从不持久化」（决策 D-014）。"""

import unittest

from app.core.errors import ValidationError
from app.models.connection import Connection, validate_connection_id, validate_host, validate_port, validate_username


class ConnectionIdTests(unittest.TestCase):
    def test_accepts_slug(self):
        for value in ("a", "vm1", "wsl-testbed", "A_1", "0" * 64):
            self.assertEqual(validate_connection_id(value), value)

    def test_rejects_traversal_and_separators(self):
        # id 会进 URL 路径分量与配置字典键，所以 / 与 .. 必须挡住。
        for value in ("", "a/b", "..", "../x", ".hidden", "a b", "a" * 65, "-leading", "_leading"):
            with self.assertRaises(ValidationError, msg=value):
                validate_connection_id(value)

    def test_rejects_non_string(self):
        with self.assertRaises(ValidationError):
            validate_connection_id(None)


class HostTests(unittest.TestCase):
    def test_accepts_common_forms(self):
        for value in ("127.0.0.1", "localhost", "192.168.170.128", "vm.example.com", "fe80::1", "[::1]", "host-1"):
            self.assertEqual(validate_host(value), value.strip())

    def test_rejects_empty_and_arguments(self):
        # 主机名会进 ssh 命令行，所以不能含空格或选项前缀。
        for value in ("", "   ", "-oProxyCommand=x", "host name", "host;rm -rf /", "a" * 256):
            with self.assertRaises(ValidationError, msg=value):
                validate_host(value)


class PortTests(unittest.TestCase):
    def test_accepts_int_and_numeric_string(self):
        self.assertEqual(validate_port(22), 22)
        self.assertEqual(validate_port("2222"), 2222)
        self.assertEqual(validate_port(65535), 65535)
        self.assertEqual(validate_port(1), 1)

    def test_rejects_out_of_range_and_junk(self):
        for value in (0, -1, 65536, "abc", "22.5", None, True):
            with self.assertRaises(ValidationError, msg=repr(value)):
                validate_port(value)


class UsernameTests(unittest.TestCase):
    def test_accepts(self):
        self.assertEqual(validate_username("aimu"), "aimu")
        self.assertEqual(validate_username("root"), "root")

    def test_rejects_empty_controls_and_overlong(self):
        for value in ("", "   ", "a\x00b", "a\nb", "a\rb", "a" * 129, None):
            with self.assertRaises(ValidationError, msg=repr(value)):
                validate_username(value)


class ConnectionTests(unittest.TestCase):
    def test_minimal_connection(self):
        conn = Connection(id="vm1", name="", host="127.0.0.1", username="aimu")
        self.assertEqual(conn.port, 22)
        self.assertEqual(conn.auth_method, "key")
        self.assertEqual(conn.target_label, "aimu@127.0.0.1:22")
        self.assertFalse(conn.allow_write)

    def test_name_falls_back_to_target(self):
        conn = Connection(id="vm1", name="", host="127.0.0.1", username="aimu", port=2222)
        self.assertEqual(conn.name, "aimu@127.0.0.1")

    def test_auth_method_is_validated(self):
        with self.assertRaises(ValidationError):
            Connection(id="vm1", name="x", host="h", username="u", auth_method="agent")

    def test_allow_write_defaults_to_false(self):
        # 规划文档 §3.2：写操作必须在只读浏览稳定之后单独设计。
        conn = Connection(id="vm1", name="x", host="h", username="u")
        self.assertFalse(conn.allow_write)
        self.assertFalse(Connection.from_dict({"id": "vm1", "host": "h", "username": "u"}).allow_write)

    def test_public_dict_drops_nothing_today_but_is_a_separate_exit(self):
        conn = Connection(id="vm1", name="x", host="h", username="u", identity_file="/k")
        self.assertEqual(conn.to_public_dict(), conn.to_dict())

    def test_password_is_not_a_field(self):
        # D-014：配置里没有密码字段，密码只存在于内存会话中。
        conn = Connection(id="vm1", name="x", host="h", username="u")
        self.assertNotIn("password", conn.to_dict())
        with self.assertRaises(ValidationError):
            Connection.from_dict({"id": "vm1", "host": "h", "username": "u", "password": "hunter2"})

    def test_from_dict_rejects_unknown_fields(self):
        with self.assertRaises(ValidationError):
            Connection.from_dict({"id": "vm1", "host": "h", "username": "u", "identiy_file": "/typo"})

    def test_round_trip(self):
        data = {
            "id": "vm1",
            "name": "测试机",
            "host": "192.168.170.128",
            "port": 2222,
            "username": "aimu",
            "auth_method": "password",
            "identity_file": "",
            "note": "备注",
            "allow_write": True,
            "created_at": "2026-10-15T00:00:00Z",
            "updated_at": "2026-10-15T00:00:00Z",
        }
        conn = Connection.from_dict(data)
        self.assertEqual(conn.to_dict(), data)

    def test_identity_file_is_kept_verbatim(self):
        # 路径由 ssh 解释；这里不做归一化，否则 Windows 的反斜杠会被改掉。
        raw = r"C:\Users\aimu\.ssh\id_ed25519"
        conn = Connection(id="vm1", name="x", host="h", username="u", identity_file=raw)
        self.assertEqual(conn.to_dict()["identity_file"], raw)


if __name__ == "__main__":
    unittest.main()
