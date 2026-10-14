"""文件系统服务：排序、截断、符号链接、预览与写入门禁。

用假的 session/client 驱动，不需要真实 SSH —— 真实链路已在集成测试里覆盖。
"""

import unittest
from contextlib import contextmanager
from types import SimpleNamespace

from app.core.errors import PathNotFound, Unauthorized, ValidationError
from app.services import filesystem
from app.ssh import sftp_protocol as proto


def attrs(kind, perm=0o644, size=0, mtime=1000):
    flags = proto.SSH_FILEXFER_ATTR_SIZE | proto.SSH_FILEXFER_ATTR_PERMISSIONS | proto.SSH_FILEXFER_ATTR_ACMODTIME
    return proto.Attrs(flags=flags, size=size, permissions=kind | perm, atime=mtime, mtime=mtime)


FILE = proto.S_IFREG
DIR = proto.S_IFDIR
LINK = proto.S_IFLNK


class FakeClient:
    def __init__(self, *, realpath=None, stats=None, lstats=None, listings=None, links=None, files=None):
        self._realpath = realpath or {}
        self._stats = stats or {}
        self._lstats = lstats or {}
        self._listings = listings or {}
        self._links = links or {}
        self._files = files or {}
        self.closed_handles = []

    def realpath(self, path):
        return self._realpath.get(path, path)

    def stat(self, path):
        if path not in self._stats:
            raise PathNotFound(f"远端路径不存在：{path}")
        return self._stats[path]

    def lstat(self, path):
        if path not in self._lstats:
            raise PathNotFound(f"远端路径不存在：{path}")
        return self._lstats[path]

    def readlink(self, path):
        if path not in self._links:
            raise PathNotFound(f"读不到链接目标：{path}")
        return self._links[path]

    def listdir(self, path):
        if path not in self._listings:
            raise PathNotFound(f"远端路径不存在：{path}")
        return self._listings[path]

    @contextmanager
    def open_read(self, path):
        if path not in self._files:
            raise PathNotFound(f"远端路径不存在：{path}")
        yield path

    def read_chunk(self, handle, offset, length):
        return self._files[handle][offset:offset + length]

    def close(self, handle):
        self.closed_handles.append(handle)


def session(client, *, allow_write=False, connection_id="vm1"):
    return SimpleNamespace(client=client, connection=SimpleNamespace(allow_write=allow_write, id=connection_id))


def entry(name, kind=FILE, perm=0o644, size=0):
    return proto.NameEntry(filename=name, longname=name, attrs=attrs(kind, perm, size))


class ResolveTests(unittest.TestCase):
    def test_realpath_is_authoritative(self):
        client = FakeClient(realpath={"/bin": "/usr/bin"})
        self.assertEqual(filesystem.resolve_path(session(client), "/bin"), "/usr/bin")

    def test_relative_path_is_refused_before_touching_the_server(self):
        client = FakeClient()
        with self.assertRaises(ValidationError):
            filesystem.resolve_path(session(client), "etc/passwd")


class ListTests(unittest.TestCase):
    def build(self, entries, path="/"):
        client = FakeClient(
            stats={path: attrs(DIR, 0o755)},
            listings={path: entries},
        )
        return filesystem.list_directory(session(client), path)

    def test_sorts_directory_symlink_then_file(self):
        result = self.build([entry("z.txt"), entry("b", DIR), entry("a", LINK), entry("a.txt")])
        self.assertEqual([e["name"] for e in result["entries"]], ["b", "a", "a.txt", "z.txt"])

    def test_sort_is_case_insensitive_and_stable(self):
        result = self.build([entry("Beta.txt"), entry("alpha.txt"), entry("ALPHA2.txt")])
        names = [e["name"] for e in result["entries"]]
        self.assertEqual(names[0].lower(), "alpha.txt")
        self.assertEqual(names[1].lower(), "alpha2.txt")

    def test_full_paths_are_joined(self):
        result = self.build([entry("x.txt")], path="/home/aimu")
        self.assertEqual(result["entries"][0]["path"], "/home/aimu/x.txt")
        self.assertEqual(result["path"], "/home/aimu")

    def test_parent_of_root_is_none(self):
        self.assertIsNone(self.build([entry("x.txt")], path="/")["parent"])

    def test_parent_of_subdirectory(self):
        self.assertEqual(self.build([], path="/home")["parent"], "/")

    def test_totals_and_truncation_flag(self):
        result = self.build([entry("a"), entry("b")])
        self.assertEqual(result["total"], 2)
        self.assertFalse(result["truncated"])

    def test_truncates_after_sorting(self):
        many = [entry(f"f{index:05d}.txt") for index in range(filesystem.MAX_LIST_ENTRIES + 1)]
        result = self.build(many)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["total"], filesystem.MAX_LIST_ENTRIES + 1)
        self.assertEqual(len(result["entries"]), filesystem.MAX_LIST_ENTRIES)
        # 先排序再截断：保留的必须是按名称排列的前 N 个。
        self.assertEqual(result["entries"][0]["name"], "f00000.txt")
        self.assertEqual(result["entries"][-1]["name"], "f04999.txt")

    def test_file_instead_of_directory_is_explained(self):
        client = FakeClient(stats={"/etc/hostname": attrs(FILE, size=5)})
        with self.assertRaises(ValidationError) as ctx:
            filesystem.list_directory(session(client), "/etc/hostname")
        self.assertIn("不是一个目录", str(ctx.exception))

    def test_missing_directory(self):
        with self.assertRaises(PathNotFound):
            filesystem.list_directory(session(FakeClient()), "/nope")

    def test_dot_entries_are_already_filtered_by_the_client(self):
        # 列表里出现 "." / ".." 会在界面上产生两个无意义且能点出循环的行。
        result = self.build([entry("real.txt")])
        self.assertNotIn(".", [e["name"] for e in result["entries"]])


class StatTests(unittest.TestCase):
    def test_follow_default_uses_canonical_path(self):
        client = FakeClient(
            realpath={"/bin": "/usr/bin"},
            stats={"/usr/bin": attrs(DIR, 0o755)},
        )
        info = filesystem.stat_path(session(client), "/bin")
        # 路径与名称都取自 REALPATH 的结果 —— /usr/bin 的 basename 是 bin。
        self.assertEqual(info["path"], "/usr/bin")
        self.assertEqual(info["name"], "bin")
        self.assertEqual(info["type"], "directory")

    def test_root_name_is_slash(self):
        client = FakeClient(stats={"/": attrs(DIR, 0o755)})
        self.assertEqual(filesystem.stat_path(session(client), "/")["name"], "/")

    def test_no_follow_reports_symlink(self):
        client = FakeClient(
            lstats={"/bin": attrs(LINK, 0o777)},
            links={"/bin": "usr/bin"},
            stats={"/bin": attrs(DIR, 0o755)},
        )
        info = filesystem.stat_path(session(client), "/bin", follow=False)
        self.assertEqual(info["type"], "symlink")
        self.assertEqual(info["link_target"], "usr/bin")
        self.assertFalse(info["link_broken"])

    def test_broken_symlink_is_reported_not_fatal(self):
        client = FakeClient(lstats={"/gone": attrs(LINK, 0o777)}, links={"/gone": "/nowhere"})
        info = filesystem.stat_path(session(client), "/gone", follow=False)
        self.assertEqual(info["link_target"], "/nowhere")
        self.assertTrue(info["link_broken"])

    def test_unreadable_link_target_is_not_fatal(self):
        client = FakeClient(lstats={"/odd": attrs(LINK, 0o777)})
        info = filesystem.stat_path(session(client), "/odd", follow=False)
        # to_dict 只在有值时才带可选字段：「读不到链接目标」表现为键不存在，而不是 null。
        # 前端用 if (entry.link_target) 判断，没必要区分两种「没有」。
        self.assertNotIn("link_target", info)
        self.assertNotIn("link_broken", info)


class PreviewTests(unittest.TestCase):
    def client_for(self, payload, *, path="/a.txt", kind=FILE, size=None):
        return FakeClient(
            stats={path: attrs(kind, size=len(payload) if size is None else size)},
            files={path: payload},
        )

    def test_utf8_text(self):
        client = self.client_for("你好\n世界\n".encode("utf-8"))
        result = filesystem.read_text_preview(session(client), "/a.txt")
        self.assertEqual(result["text"], "你好\n世界\n")
        self.assertEqual(result["encoding"], "utf-8")
        self.assertFalse(result["truncated"])
        self.assertEqual(result["bytes_read"], len("你好\n世界\n".encode("utf-8")))

    def test_truncation_by_max_bytes(self):
        client = self.client_for(b"0123456789")
        result = filesystem.read_text_preview(session(client), "/a.txt", max_bytes=4)
        self.assertEqual(result["text"], "0123")
        self.assertTrue(result["truncated"])
        self.assertEqual(result["bytes_read"], 4)
        self.assertEqual(result["size"], 10)

    def test_binary_is_refused(self):
        client = self.client_for(b"abc\x00def")
        with self.assertRaises(ValidationError) as ctx:
            filesystem.read_text_preview(session(client), "/a.txt")
        self.assertIn("二进制", str(ctx.exception))

    def test_invalid_utf8_falls_back_to_latin1(self):
        # 不用 errors="replace"：大量 U+FFFD 会让用户以为文件本身损坏了。
        client = self.client_for(b"caf\xe9")
        result = filesystem.read_text_preview(session(client), "/a.txt")
        self.assertEqual(result["encoding"], "latin-1")
        self.assertEqual(result["text"], "café")

    def test_directory_is_refused(self):
        client = FakeClient(stats={"/d": attrs(DIR, 0o755)})
        with self.assertRaises(ValidationError) as ctx:
            filesystem.read_text_preview(session(client), "/d")
        self.assertIn("目录", str(ctx.exception))

    def test_empty_file(self):
        client = self.client_for(b"")
        result = filesystem.read_text_preview(session(client), "/a.txt")
        self.assertEqual(result["text"], "")
        self.assertFalse(result["truncated"])


class WriteGateTests(unittest.TestCase):
    def test_closed_by_default(self):
        with self.assertRaises(Unauthorized) as ctx:
            filesystem.require_write_permission(session(FakeClient()), "上传文件")
        self.assertEqual(ctx.exception.extra["connection_id"], "vm1")

    def test_open_when_enabled(self):
        filesystem.require_write_permission(session(FakeClient(), allow_write=True), "上传文件")

    def test_message_names_the_action(self):
        with self.assertRaises(Unauthorized) as ctx:
            filesystem.require_write_permission(session(FakeClient()), "删除文件")
        self.assertIn("删除文件", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
