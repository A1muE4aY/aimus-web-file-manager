"""文件条目模型：元数据转换与「不跟随符号链接」的约定。"""

import unittest

from app.models.entry import FileEntry
from app.ssh import sftp_protocol as proto


def attrs(mode, size=1234, mtime=1700000000, atime=1700000001, uid=1000, gid=1000):
    return proto.Attrs(
        flags=proto.SSH_FILEXFER_ATTR_SIZE | proto.SSH_FILEXFER_ATTR_ACMODTIME | proto.SSH_FILEXFER_ATTR_PERMISSIONS,
        size=size,
        uid=uid,
        gid=gid,
        permissions=mode,
        atime=atime,
        mtime=mtime,
    )


class FromAttrsTests(unittest.TestCase):
    def test_regular_file(self):
        entry = FileEntry.from_attrs("a.txt", "/tmp/a.txt", attrs(0o100644))
        self.assertEqual(entry.type, "file")
        self.assertEqual(entry.mode, "0644")
        self.assertEqual(entry.size, 1234)
        self.assertEqual(entry.mtime, 1700000000)
        self.assertTrue(entry.is_regular_file())
        self.assertFalse(entry.is_dir)

    def test_directory(self):
        entry = FileEntry.from_attrs("sub", "/tmp/sub", attrs(0o040755, size=4096))
        self.assertEqual(entry.type, "directory")
        self.assertTrue(entry.is_dir)
        self.assertFalse(entry.is_regular_file())

    def test_symlink_is_not_a_regular_file(self):
        entry = FileEntry.from_attrs("link", "/tmp/link", attrs(0o120777))
        self.assertEqual(entry.type, "symlink")
        self.assertFalse(entry.is_regular_file())

    def test_setuid_bits_survive(self):
        # 4755 与 0755 必须在界面上看得出区别 —— 这是选原生 SFTP 协议的直接收益（D-011）。
        entry = FileEntry.from_attrs("sudo", "/usr/bin/sudo", attrs(0o104755))
        self.assertEqual(entry.mode, "4755")

    def test_device_and_fifo_types(self):
        self.assertEqual(FileEntry.from_attrs("null", "/dev/null", attrs(0o020666)).type, "char")
        self.assertEqual(FileEntry.from_attrs("sda", "/dev/sda", attrs(0o060660)).type, "block")
        self.assertEqual(FileEntry.from_attrs("fifo", "/tmp/fifo", attrs(0o010644)).type, "fifo")
        self.assertEqual(FileEntry.from_attrs("sock", "/tmp/sock", attrs(0o140755)).type, "socket")


class ToDictTests(unittest.TestCase):
    def test_core_fields_present(self):
        payload = FileEntry.from_attrs("a.txt", "/tmp/a.txt", attrs(0o100644)).to_dict()
        for key in ("name", "type", "size", "mtime", "mode", "path", "atime", "permissions", "uid", "gid"):
            self.assertIn(key, payload)
        self.assertEqual(payload["path"], "/tmp/a.txt")

    def test_include_path_false(self):
        payload = FileEntry.from_attrs("a.txt", "/tmp/a.txt", attrs(0o100644)).to_dict(include_path=False)
        self.assertNotIn("path", payload)

    def test_optional_fields_only_when_present(self):
        entry = FileEntry(
            name="a", path="/a", type="file", size=None, mtime=None, atime=None,
            mode=None, permissions=None, uid=None, gid=None,
        )
        payload = entry.to_dict()
        self.assertNotIn("atime", payload)
        self.assertNotIn("permissions", payload)
        self.assertNotIn("link_target", payload)

    def test_link_fields_appear_together(self):
        entry = FileEntry.from_attrs("link", "/tmp/link", attrs(0o120777))
        entry.link_target = "nowhere"
        entry.link_broken = True
        payload = entry.to_dict()
        self.assertEqual(payload["link_target"], "nowhere")
        self.assertIs(payload["link_broken"], True)

    def test_broken_link_flag_is_boolean_even_when_none(self):
        entry = FileEntry.from_attrs("link", "/tmp/link", attrs(0o120777))
        entry.link_target = "somewhere"
        self.assertIs(entry.to_dict()["link_broken"], False)

    def test_is_json_serializable(self):
        import json

        payload = FileEntry.from_attrs("中文 名.txt", "/tmp/中文 名.txt", attrs(0o100644)).to_dict()
        json.dumps(payload, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
