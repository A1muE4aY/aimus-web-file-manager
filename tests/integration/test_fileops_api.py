"""文件操作接口的集成测试（真实 WSL 测试床 + 真实 HTTP 服务）。

覆盖任务书阶段四对文件操作的要求：重命名、删除（含递归确认）、压缩、解压。
几条刻意的纪律：

- 破坏性操作只作用于用户点中的那个条目：删除一个符号链接不能删到它指向的
  文件，重命名链接不能改到目标名字。服务层的单元测试已覆盖一次，这里在 HTTP
  层再复现一次 —— 界面能点到的路径必须独立成立。
- 压缩包的内容通过下载票据取回本地，用 tarfile / zipfile 真的打开逐项核对，
  不只相信响应里的计数。
- 目录穿越的压缩包必须整包拒绝，且不能在远端落下任何文件。
"""

import contextlib
import io
import sys
import tarfile
import unittest
import zipfile

from tests.integration.support import (
    connection_url,
    count_testbed_ssh_processes,
    download_bytes,
    ops_fixture,
    require_testbed,
    running_server,
    testbed_command,
    testbed_connection,
    testbed_environment,
    upload_bytes,
)

CONNECTION = "wsl-testbed"
READONLY_CONNECTION = "wsl-readonly"

OTHER = "other.txt"
TARGET = "target.txt"


def build_tar_gz(items):
    """在本地造一个 tar.gz。items 里每项是 (名字, bytes) 或 (名字, None)（目录）。"""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.GNU_FORMAT) as tar:
        for name, data in items:
            info = tarfile.TarInfo(name)
            if data is None:
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tar.addfile(info)
            else:
                info.size = len(data)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def build_zip(items):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in items:
            archive.writestr(name, data)
    return buffer.getvalue()


@require_testbed
class FileOpsApiTests(unittest.TestCase):
    """四个文件操作端点在真实测试床上的行为。"""

    @classmethod
    def setUpClass(cls):
        cls._stack = contextlib.ExitStack()
        config, _keys = cls._stack.enter_context(
            testbed_environment(
                connections=[
                    testbed_connection(id=CONNECTION, allow_write=True),
                    testbed_connection(
                        id=READONLY_CONNECTION, name="只读测试床", allow_write=False
                    ),
                ]
            )
        )
        cls.client = cls._stack.enter_context(running_server(config))
        cls.root = cls._stack.enter_context(ops_fixture())
        for connection in (CONNECTION, READONLY_CONNECTION):
            response = cls.client.post("/api/connections/%s/connect" % connection, {})
            assert response.status == 200, response

    @classmethod
    def tearDownClass(cls):
        cls._stack.close()

    # ------------------------------------------------------------- 助手

    def path(self, name):
        if name.startswith("/"):
            return name
        return "%s/%s" % (self.root, name)

    def post(self, suffix, body, *, connection=CONNECTION):
        return self.client.post("/api/connections/%s/%s" % (connection, suffix), body)

    def rename(self, target, new_name, *, connection=CONNECTION):
        return self.post(
            "rename", {"path": self.path(target), "new_name": new_name}, connection=connection
        )

    def delete(self, target, *, recursive=False, connection=CONNECTION):
        return self.post(
            "delete", {"path": self.path(target), "recursive": recursive}, connection=connection
        )

    def compress(self, target, name="", *, connection=CONNECTION):
        return self.post(
            "compress", {"path": self.path(target), "name": name}, connection=connection
        )

    def extract(self, target, into="", *, overwrite=False, connection=CONNECTION):
        return self.post(
            "extract",
            {"path": self.path(target), "into": into, "overwrite": overwrite},
            connection=connection,
        )

    def put(self, name, data, *, directory=None):
        """用上传接口放一个有内容的文件，返回它的绝对路径。"""
        if isinstance(data, str):
            data = data.encode("utf-8")
        where = directory or self.root
        response = upload_bytes(self.client, where, name, data)
        self.assertIn(response.status, (200, 201), response)
        return "%s/%s" % (where, name)

    def mkdirs(self, *names):
        absolute = [self.path(name) for name in names]
        testbed_command("mkdir -p %s" % " ".join('"%s"' % item for item in absolute))
        return absolute[0]

    def symlink(self, name, target):
        testbed_command('ln -sf "%s" "%s"' % (target, self.path(name)))
        return self.path(name)

    def names(self, directory):
        """列出远端目录里的名字（走文件列表接口）。"""
        response = self.client.get(connection_url(CONNECTION, "files", path=directory))
        self.assertEqual(response.status, 200, response)
        return [item["name"] for item in response.data["entries"]]

    def remote_bytes(self, name):
        return download_bytes(self.client, self.path(name))

    def fetch_archive(self, name):
        """把远端压缩包取回本地并打开（tar.gz 用 tarfile，zip 用 zipfile）。"""
        raw = download_bytes(self.client, self.path(name))
        if name.endswith(".zip"):
            return zipfile.ZipFile(io.BytesIO(raw))
        return tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz")

    def ok(self, response, key, status=200):
        self.assertEqual(response.status, status, response)
        return response.data[key]

    def assert_refused(self, response, status, code):
        self.assertEqual(response.status, status, response)
        self.assertEqual(response.code, code, response)

    # ------------------------------------------------------------- 重命名

    def test_rename_moves_a_file(self):
        self.put("rn-src.txt", "rename me\n")
        entry = self.ok(self.rename("rn-src.txt", "rn-dst.txt"), "entry")
        self.assertEqual(entry["path"], self.path("rn-src.txt"))
        self.assertEqual(entry["name"], "rn-src.txt")
        self.assertEqual(entry["new_path"], self.path("rn-dst.txt"))
        self.assertEqual(entry["new_name"], "rn-dst.txt")
        self.assertEqual(entry["type"], "file")
        self.assertEqual(entry["size"], len("rename me\n"))
        listing = self.names(self.root)
        self.assertIn("rn-dst.txt", listing)
        self.assertNotIn("rn-src.txt", listing)
        self.assertEqual(self.remote_bytes("rn-dst.txt"), b"rename me\n")

    def test_rename_a_directory_keeps_its_contents(self):
        self.mkdirs("rn-tree/inner")
        self.put("leaf.txt", "leaf\n", directory=self.path("rn-tree/inner"))
        entry = self.ok(self.rename("rn-tree", "rn-tree-moved"), "entry")
        self.assertEqual(entry["type"], "directory")
        self.assertIn("rn-tree-moved", self.names(self.root))
        self.assertNotIn("rn-tree", self.names(self.root))
        self.assertEqual(self.names(self.path("rn-tree-moved/inner")), ["leaf.txt"])

    def test_rename_refuses_an_existing_target(self):
        self.put("rn-keep.txt", "keep\n")
        self.put("rn-busy.txt", "busy\n")
        response = self.rename("rn-keep.txt", "rn-busy.txt")
        self.assert_refused(response, 400, "invalid_request")
        self.assertEqual(response.error["path"], self.path("rn-busy.txt"))
        self.assertTrue(response.error["exists"])
        self.assertEqual(response.error["type"], "file")
        self.assertIn("rn-keep.txt", self.names(self.root))

    def test_rename_rejects_a_name_with_a_slash(self):
        self.put("rn-slash.txt", "x\n")
        self.assert_refused(self.rename("rn-slash.txt", "sub/x.txt"), 400, "invalid_request")
        self.assertIn("rn-slash.txt", self.names(self.root))

    def test_rename_rejects_the_root(self):
        self.assert_refused(self.rename("/", "root-renamed"), 400, "invalid_request")

    def test_rename_missing_source_is_not_found(self):
        self.assert_refused(
            self.rename("no-such-entry.txt", "whatever.txt"), 404, "path_not_found"
        )

    def test_renaming_a_symlink_keeps_the_target(self):
        self.put("rn-target.txt", "target\n")
        self.symlink("rn-link.txt", self.path("rn-target.txt"))
        entry = self.ok(self.rename("rn-link.txt", "rn-moved-link.txt"), "entry")
        self.assertEqual(entry["type"], "symlink")
        listing = self.names(self.root)
        self.assertIn("rn-moved-link.txt", listing)
        self.assertNotIn("rn-link.txt", listing)
        self.assertEqual(self.remote_bytes("rn-target.txt"), b"target\n")

    # ------------------------------------------------------------- 删除

    def test_delete_a_file(self):
        self.put("del-file.txt", "gone\n")
        deleted = self.ok(self.delete("del-file.txt"), "deleted")
        self.assertEqual(deleted["type"], "file")
        self.assertFalse(deleted["recursive"])
        self.assertEqual(deleted["removed"], {"files": 1, "directories": 0})
        self.assertEqual(deleted["entries"], 1)
        self.assertNotIn("del-file.txt", self.names(self.root))

    def test_delete_an_empty_directory(self):
        self.mkdirs("del-empty")
        deleted = self.ok(self.delete("del-empty"), "deleted")
        self.assertEqual(deleted["type"], "directory")
        self.assertEqual(deleted["removed"], {"files": 0, "directories": 1})
        self.assertNotIn("del-empty", self.names(self.root))

    def test_delete_a_non_empty_directory_needs_confirmation(self):
        self.mkdirs("del-tree/inner")
        self.put("a.txt", "a\n", directory=self.path("del-tree"))
        response = self.delete("del-tree")
        self.assert_refused(response, 400, "invalid_request")
        self.assertEqual(response.error["path"], self.path("del-tree"))
        self.assertGreaterEqual(response.error["entries"], 1)
        self.assertFalse(response.error["recursive"])
        self.assertIn("del-tree", self.names(self.root))

    def test_recursive_delete_reports_counts(self):
        self.mkdirs("del-rec/inner")
        self.put("a.txt", "a\n", directory=self.path("del-rec"))
        self.put("b.txt", "b\n", directory=self.path("del-rec/inner"))
        deleted = self.ok(self.delete("del-rec", recursive=True), "deleted")
        self.assertTrue(deleted["recursive"])
        self.assertEqual(deleted["removed"], {"files": 2, "directories": 2})
        self.assertEqual(deleted["entries"], 4)
        self.assertNotIn("del-rec", self.names(self.root))

    def test_delete_rejects_the_root(self):
        self.assert_refused(self.delete("/"), 400, "invalid_request")

    def test_delete_missing_path_is_not_found(self):
        self.assert_refused(self.delete("no-such-entry.txt"), 404, "path_not_found")

    def test_deleting_a_symlink_keeps_the_target_file(self):
        self.put("del-target.txt", "target\n")
        self.symlink("del-link.txt", self.path("del-target.txt"))
        deleted = self.ok(self.delete("del-link.txt"), "deleted")
        self.assertEqual(deleted["type"], "symlink")
        self.assertEqual(deleted["removed"], {"files": 1, "directories": 0})
        self.assertNotIn("del-link.txt", self.names(self.root))
        # 关键断言：链接指向的文件必须还在（曾经这里会连带删掉真实文件）。
        self.assertIn("del-target.txt", self.names(self.root))
        self.assertEqual(self.remote_bytes("del-target.txt"), b"target\n")

    def test_deleting_a_symlink_to_a_directory_keeps_the_directory(self):
        self.mkdirs("del-target-dir")
        self.put("kept.txt", "kept\n", directory=self.path("del-target-dir"))
        self.symlink("del-dir-link", self.path("del-target-dir"))
        deleted = self.ok(self.delete("del-dir-link"), "deleted")
        self.assertEqual(deleted["type"], "symlink")
        self.assertEqual(deleted["removed"], {"files": 1, "directories": 0})
        self.assertEqual(self.names(self.path("del-target-dir")), ["kept.txt"])
        self.assertEqual(self.remote_bytes("del-target-dir/kept.txt"), b"kept\n")

    # ------------------------------------------------------------- 压缩

    def test_compress_a_file_makes_a_tarball_with_the_payload(self):
        self.put("pack-me.txt", "pack me\n")
        archive = self.ok(self.compress("pack-me.txt"), "archive", status=201)
        self.assertEqual(archive["name"], "pack-me.txt.tar.gz")
        self.assertEqual(archive["path"], self.path("pack-me.txt.tar.gz"))
        self.assertEqual(archive["format"], "tar.gz")
        self.assertEqual(archive["entries"], 1)
        self.assertEqual(archive["bytes"], len("pack me\n"))
        self.assertEqual(archive["skipped"], [])
        self.assertGreater(archive["size"], 0)
        with self.fetch_archive("pack-me.txt.tar.gz") as tar:
            members = tar.getmembers()
            self.assertEqual([item.name for item in members], ["pack-me.txt"])
            self.assertEqual(tar.extractfile(members[0]).read(), b"pack me\n")

    def test_compress_a_directory_includes_nested_entries(self):
        self.mkdirs("pack-tree/inner")
        self.put("mid.txt", "mid\n", directory=self.path("pack-tree"))
        self.put("leaf.txt", "leaf\n", directory=self.path("pack-tree/inner"))
        archive = self.ok(self.compress("pack-tree"), "archive", status=201)
        self.assertEqual(archive["name"], "pack-tree.tar.gz")
        self.assertEqual(archive["entries"], 4)
        self.assertEqual(archive["bytes"], len("mid\n") + len("leaf\n"))
        with self.fetch_archive("pack-tree.tar.gz") as tar:
            names = [item.name for item in tar.getmembers()]
            self.assertEqual(
                sorted(names),
                ["pack-tree", "pack-tree/inner", "pack-tree/inner/leaf.txt", "pack-tree/mid.txt"],
            )
            leaf = tar.extractfile("pack-tree/inner/leaf.txt").read()
            self.assertEqual(leaf, b"leaf\n")

    def test_compress_keeps_a_symlink_as_a_symlink(self):
        self.put("pack-target.txt", "target\n")
        self.symlink("pack-link.txt", self.path("pack-target.txt"))
        archive = self.ok(self.compress("pack-link.txt"), "archive", status=201)
        self.assertEqual(archive["bytes"], 0)
        with self.fetch_archive("pack-link.txt.tar.gz") as tar:
            members = tar.getmembers()
            self.assertEqual([item.name for item in members], ["pack-link.txt"])
            self.assertTrue(members[0].issym())
            self.assertEqual(members[0].linkname, self.path("pack-target.txt"))

    def test_compress_refuses_an_existing_target(self):
        self.put("pack-a.txt", "a\n")
        self.put("pack-a.txt.tar.gz", "not really an archive\n")
        response = self.compress("pack-a.txt")
        self.assert_refused(response, 400, "invalid_request")
        self.assertTrue(response.error["exists"])
        self.assertEqual(response.error["path"], self.path("pack-a.txt.tar.gz"))

    def test_compress_adds_the_suffix_when_missing(self):
        self.put("pack-b.txt", "b\n")
        archive = self.ok(self.compress("pack-b.txt", name="bundle"), "archive", status=201)
        self.assertEqual(archive["name"], "bundle.tar.gz")
        self.assertEqual(archive["path"], self.path("bundle.tar.gz"))
        with self.fetch_archive("bundle.tar.gz") as tar:
            self.assertEqual([item.name for item in tar.getmembers()], ["pack-b.txt"])

    def test_compress_missing_source_is_not_found(self):
        self.assert_refused(self.compress("no-such-entry.txt"), 404, "path_not_found")

    # ------------------------------------------------------------- 解压

    def test_extract_into_a_new_directory(self):
        # 压缩包里带一个目录条目，用来验证 directories 计数与逐级建目录。
        payload = build_tar_gz([("nested/", None), ("nested/hello.txt", b"hello\n")])
        self.put("unpack.tar.gz", payload)
        result = self.ok(
            self.extract("unpack.tar.gz", into=self.path("unpacked")), "extract", status=201
        )
        self.assertEqual(result["destination"], self.path("unpacked"))
        self.assertEqual(result["format"], "tar.gz")
        self.assertEqual(result["files"], 1)
        self.assertEqual(result["directories"], 1)
        self.assertEqual(result["existing"], [])
        self.assertEqual(result["skipped"], [])
        self.assertIsNone(result["stopped"])
        self.assertFalse(result["overwrite"])
        self.assertEqual(self.names(self.path("unpacked")), ["nested"])
        self.assertEqual(self.names(self.path("unpacked/nested")), ["hello.txt"])
        self.assertEqual(self.remote_bytes("unpacked/nested/hello.txt"), b"hello\n")

    def test_extract_skips_existing_files_unless_overwritten(self):
        first = build_tar_gz([("x.txt", b"one\n")])
        second = build_tar_gz([("x.txt", b"two\n")])
        self.put("over-one.tar.gz", first)
        self.put("over-two.tar.gz", second)
        self.ok(self.extract("over-one.tar.gz", into=self.path("over")), "extract", status=201)
        self.assertEqual(self.remote_bytes("over/x.txt"), b"one\n")
        skipped = self.ok(
            self.extract("over-two.tar.gz", into=self.path("over")), "extract", status=201
        )
        self.assertEqual(skipped["existing"], ["x.txt"])
        self.assertEqual(skipped["files"], 0)
        self.assertEqual(self.remote_bytes("over/x.txt"), b"one\n")
        replaced = self.ok(
            self.extract("over-two.tar.gz", into=self.path("over"), overwrite=True),
            "extract",
            status=201,
        )
        self.assertEqual(replaced["existing"], [])
        self.assertEqual(replaced["files"], 1)
        self.assertTrue(replaced["overwrite"])
        self.assertEqual(self.remote_bytes("over/x.txt"), b"two\n")

    def test_extract_a_zip_archive(self):
        self.put("zipped.zip", build_zip([("zip-hello.txt", b"zip hello\n")]))
        result = self.ok(self.extract("zipped.zip"), "extract", status=201)
        self.assertEqual(result["format"], "zip")
        self.assertEqual(result["files"], 1)
        self.assertEqual(result["destination"], self.root)
        self.assertEqual(self.remote_bytes("zip-hello.txt"), b"zip hello\n")

    def test_extract_rejects_an_unsupported_suffix(self):
        self.put("plain-archive.txt", "not an archive\n")
        response = self.extract("plain-archive.txt")
        self.assert_refused(response, 400, "invalid_request")
        self.assertIn("压缩包", response.error["message"])

    def test_extract_refuses_a_traversal_member(self):
        payload = build_tar_gz([("../evil.txt", b"boom\n")])
        self.put("evil.tar.gz", payload)
        response = self.extract("evil.tar.gz")
        self.assert_refused(response, 400, "invalid_request")
        self.assertIn("..", response.error["message"])
        # 关键断言：越界的文件一个字节都没落下。
        self.assertNotIn("evil.txt", self.names("/tmp"))
        self.assertNotIn("evil.txt", self.names(self.root))

    def test_extract_refuses_a_directory(self):
        self.mkdirs("dir-archive.tgz")
        response = self.extract("dir-archive.tgz")
        self.assert_refused(response, 400, "invalid_request")
        self.assertIn("目录", response.error["message"])

    def test_extract_into_an_existing_file_is_refused(self):
        self.put("into-file.txt", "x\n")
        self.put("into-src.tar.gz", build_tar_gz([("into.txt", b"y\n")]))
        response = self.extract("into-src.tar.gz", into=self.path("into-file.txt"))
        self.assert_refused(response, 400, "invalid_request")
        self.assertIn("目录", response.error["message"])

    # ------------------------------------------------------------- 新建 / 复制 / 移动 / 批量

    def create(self, name, *, kind="file", directory=None, connection=CONNECTION):
        return self.post(
            "create",
            {"path": directory or self.root, "name": name, "kind": kind},
            connection=connection,
        )

    def copy(self, targets, into, *, overwrite=False, connection=CONNECTION):
        return self.post(
            "copy",
            {"paths": [self.path(item) for item in targets], "to": into, "overwrite": overwrite},
            connection=connection,
        )

    def move(self, targets, into, *, connection=CONNECTION):
        return self.post(
            "move",
            {"paths": [self.path(item) for item in targets], "to": into},
            connection=connection,
        )

    def test_create_an_empty_file(self):
        entry = self.ok(self.create("new-empty.txt"), "entry", status=201)
        self.assertEqual(entry["name"], "new-empty.txt")
        self.assertEqual(entry["path"], self.path("new-empty.txt"))
        self.assertEqual(entry["kind"], "file")
        self.assertEqual(entry["type"], "file")
        self.assertEqual(entry["size"], 0)
        self.assertIn("new-empty.txt", self.names(self.root))
        # 关键断言：远端真的是 0 字节文件，不只是响应这么说。
        self.assertEqual(self.remote_bytes("new-empty.txt"), b"")
        listing = self.client.get(connection_url(CONNECTION, "files", path=self.root))
        self.assertEqual(listing.status, 200, listing)
        listed = {item["name"]: item for item in listing.data["entries"]}
        self.assertEqual(listed["new-empty.txt"]["size"], 0)
        self.assertEqual(listed["new-empty.txt"]["type"], "file")

    def test_create_a_directory(self):
        entry = self.ok(self.create("new-folder", kind="directory"), "entry", status=201)
        self.assertEqual(entry["kind"], "directory")
        self.assertEqual(entry["type"], "directory")
        self.assertIn("new-folder", self.names(self.root))
        # 新目录能继续放东西，说明权限位对得上。
        self.put("inside.txt", "inside\n", directory=self.path("new-folder"))
        self.assertEqual(self.remote_bytes("new-folder/inside.txt"), b"inside\n")

    def test_create_accepts_chinese_and_spaces(self):
        for name in ("中文文件.txt", "with space.txt", "逗号,括号(1).txt"):
            with self.subTest(name=name):
                entry = self.ok(self.create(name), "entry", status=201)
                self.assertEqual(entry["name"], name)
                self.assertIn(name, self.names(self.root))
                self.assertEqual(self.remote_bytes(name), b"")

    def test_create_refuses_an_existing_name(self):
        self.put("taken.txt", "taken\n")
        response = self.create("taken.txt")
        self.assert_refused(response, 400, "invalid_request")
        self.assertTrue(response.error["exists"])
        self.assertEqual(response.error["path"], self.path("taken.txt"))
        # 关键断言：没有静默覆盖已有内容。
        self.assertEqual(self.remote_bytes("taken.txt"), b"taken\n")

    def test_create_refuses_an_existing_directory_name(self):
        self.mkdirs("taken-dir")
        response = self.create("taken-dir", kind="directory")
        self.assert_refused(response, 400, "invalid_request")

    def test_create_rejects_invalid_names(self):
        for name in ("", ".", "..", "sub/x.txt", "a" * 300):
            with self.subTest(name=name[:12]):
                self.assert_refused(self.create(name), 400, "invalid_request")

    def test_create_missing_directory_is_not_found(self):
        response = self.create("orphan.txt", directory=self.path("no-such-dir"))
        self.assert_refused(response, 404, "path_not_found")

    def test_create_requires_the_write_toggle(self):
        response = self.create("denied.txt", connection=READONLY_CONNECTION)
        self.assert_refused(response, 401, "unauthorized")
        self.assertNotIn("denied.txt", self.names(self.root))

    def test_copy_a_file_keeps_the_source(self):
        self.put("cp-src.txt", "copy me\n")
        self.mkdirs("cp-out")
        copied = self.ok(self.copy(["cp-src.txt"], self.path("cp-out")), "copy", status=201)
        self.assertEqual(copied["destination"], self.path("cp-out"))
        self.assertEqual(copied["files"], 1)
        self.assertEqual(copied["directories"], 0)
        self.assertEqual(copied["bytes"], len("copy me\n"))
        self.assertEqual(copied["skipped"], [])
        self.assertEqual(self.names(self.path("cp-out")), ["cp-src.txt"])
        # 关键断言：字节一致，且源文件还在。
        self.assertEqual(self.remote_bytes("cp-out/cp-src.txt"), b"copy me\n")
        self.assertEqual(self.remote_bytes("cp-src.txt"), b"copy me\n")

    def test_copy_a_directory_tree(self):
        self.mkdirs("cp-tree/inner")
        self.put("mid.txt", "mid\n", directory=self.path("cp-tree"))
        self.put("leaf.txt", "leaf\n", directory=self.path("cp-tree/inner"))
        self.mkdirs("cp-tree-out")
        copied = self.ok(
            self.copy(["cp-tree"], self.path("cp-tree-out")), "copy", status=201
        )
        self.assertEqual(copied["files"], 2)
        self.assertEqual(copied["directories"], 2)
        self.assertEqual(copied["bytes"], len("mid\n") + len("leaf\n"))
        self.assertEqual(self.names(self.path("cp-tree-out/cp-tree/inner")), ["leaf.txt"])
        self.assertEqual(self.remote_bytes("cp-tree-out/cp-tree/inner/leaf.txt"), b"leaf\n")

    def test_copy_refuses_an_existing_target(self):
        self.put("cp-busy.txt", "new\n")
        self.mkdirs("cp-busy-out")
        self.put("cp-busy.txt", "old\n", directory=self.path("cp-busy-out"))
        response = self.copy(["cp-busy.txt"], self.path("cp-busy-out"))
        self.assert_refused(response, 400, "invalid_request")
        self.assertEqual(
            response.error["conflicts"][0]["target"], self.path("cp-busy-out/cp-busy.txt")
        )
        self.assertEqual(self.remote_bytes("cp-busy-out/cp-busy.txt"), b"old\n")

    def test_copy_with_overwrite_replaces_the_target(self):
        self.put("cp-over.txt", "new\n")
        self.mkdirs("cp-over-out")
        self.put("cp-over.txt", "old\n", directory=self.path("cp-over-out"))
        copied = self.ok(
            self.copy(["cp-over.txt"], self.path("cp-over-out"), overwrite=True),
            "copy",
            status=201,
        )
        self.assertTrue(copied["overwrite"])
        self.assertEqual(self.remote_bytes("cp-over-out/cp-over.txt"), b"new\n")

    def test_copy_into_itself_is_refused(self):
        self.mkdirs("cp-loop/inner")
        response = self.copy(["cp-loop"], self.path("cp-loop/inner"))
        self.assert_refused(response, 400, "invalid_request")
        self.assertIn("自己", response.error["message"])

    def test_move_a_file(self):
        self.put("mv-src.txt", "move me\n")
        self.mkdirs("mv-out")
        moved = self.ok(self.move(["mv-src.txt"], self.path("mv-out")), "move")
        self.assertEqual(moved["count"], 1)
        self.assertEqual(moved["moved"][0]["path"], self.path("mv-out/mv-src.txt"))
        self.assertNotIn("mv-src.txt", self.names(self.root))
        self.assertEqual(self.remote_bytes("mv-out/mv-src.txt"), b"move me\n")

    def test_move_refuses_an_existing_target_and_keeps_the_source(self):
        self.put("mv-busy.txt", "new\n")
        self.mkdirs("mv-busy-out")
        self.put("mv-busy.txt", "old\n", directory=self.path("mv-busy-out"))
        response = self.move(["mv-busy.txt"], self.path("mv-busy-out"))
        self.assert_refused(response, 400, "invalid_request")
        self.assertIn("mv-busy.txt", self.names(self.root))
        self.assertEqual(self.remote_bytes("mv-busy.txt"), b"new\n")
        self.assertEqual(self.remote_bytes("mv-busy-out/mv-busy.txt"), b"old\n")

    def test_batch_delete(self):
        self.put("bd-a.txt", "a\n")
        self.mkdirs("bd-dir")
        self.put("x.txt", "x\n", directory=self.path("bd-dir"))
        response = self.post(
            "delete",
            {"paths": [self.path("bd-a.txt"), self.path("bd-dir")], "recursive": True},
        )
        deleted = self.ok(response, "deleted")
        self.assertEqual(deleted["count"], 2)
        self.assertEqual(deleted["files"], 2)
        self.assertEqual(deleted["directories"], 1)
        self.assertEqual(deleted["entries"], 3)
        listing = self.names(self.root)
        self.assertNotIn("bd-a.txt", listing)
        self.assertNotIn("bd-dir", listing)

    def test_batch_compress_makes_one_archive(self):
        self.put("bc-a.txt", "abcde\n")
        self.put("bc-b.txt", "fg\n")
        archive = self.ok(
            self.post(
                "compress",
                {"paths": [self.path("bc-a.txt"), self.path("bc-b.txt")], "name": "batch-pack"},
            ),
            "archive",
            status=201,
        )
        self.assertEqual(archive["name"], "batch-pack.tar.gz")
        self.assertEqual(archive["entries"], 2)
        self.assertEqual(archive["bytes"], len("abcde\n") + len("fg\n"))
        self.assertEqual(len(archive["sources"]), 2)
        with self.fetch_archive("batch-pack.tar.gz") as tar:
            members = sorted(item.name for item in tar.getmembers())
            self.assertEqual(members, ["bc-a.txt", "bc-b.txt"])
            self.assertEqual(tar.extractfile("bc-a.txt").read(), b"abcde\n")

    def test_batch_extract_summarises_every_archive(self):
        self.put("bx-one.tar.gz", build_tar_gz([("bx-one.txt", b"one\n")]))
        self.put("bx-two.tar.gz", build_tar_gz([("bx-two.txt", b"two\n")]))
        self.mkdirs("bx-out")
        result = self.ok(
            self.post(
                "extract",
                {
                    "paths": [self.path("bx-one.tar.gz"), self.path("bx-two.tar.gz")],
                    "into": self.path("bx-out"),
                },
            ),
            "extract",
            status=201,
        )
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["files"], 2)
        self.assertEqual(result["bytes"], len("one\n") + len("two\n"))
        self.assertEqual(len(result["archives"]), 2)
        self.assertEqual(self.remote_bytes("bx-out/bx-one.txt"), b"one\n")
        self.assertEqual(self.remote_bytes("bx-out/bx-two.txt"), b"two\n")

    # ------------------------------------------------------------- 写权限与命令纪律

    def test_write_endpoints_require_the_write_toggle(self):
        self.put("guard.txt", "guard\n")
        responses = {
            "rename": self.rename("guard.txt", "guard2.txt", connection=READONLY_CONNECTION),
            "delete": self.delete("guard.txt", connection=READONLY_CONNECTION),
            "compress": self.compress("guard.txt", connection=READONLY_CONNECTION),
            "extract": self.extract("guard.txt", connection=READONLY_CONNECTION),
        }
        for name, response in responses.items():
            with self.subTest(operation=name):
                self.assertEqual(response.status, 401, response)
                self.assertEqual(response.code, "unauthorized", response)
                self.assertEqual(response.error["connection_id"], READONLY_CONNECTION)
        # 被拒绝的四次操作都没能改动远端。
        self.assertIn("guard.txt", self.names(self.root))
        self.assertEqual(self.remote_bytes("guard.txt"), b"guard\n")

    @unittest.skipUnless(sys.platform == "win32", "只在 Windows 上数 ssh.exe 进程")
    def test_file_operations_do_not_spawn_ssh_processes(self):
        """任务书 T-013：压缩与解压全程走既有的 SFTP 会话，不额外起 ssh 命令。"""
        before = count_testbed_ssh_processes()
        self.assertGreaterEqual(before, 1)
        self.put("quiet.txt", "quiet\n")
        self.ok(self.compress("quiet.txt"), "archive", status=201)
        self.ok(self.extract("quiet.txt.tar.gz"), "extract", status=201)
        self.assertEqual(count_testbed_ssh_processes(), before)


if __name__ == "__main__":
    unittest.main()
