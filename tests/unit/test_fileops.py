"""远端文件操作服务（app/services/fileops.py）的单元测试。

压缩包字节是真的（tarfile / zipfile 在内存里现造），远端是内存 SFTP
（tests/unit/fake_sftp.py）。所以这里检查的是真实产物与真实副作用：
包里的成员、解压落地后的字节、失败之后远端有没有留下垃圾文件。
"""

import io
import tarfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest import mock

from app.core.errors import (
    NotConnected,
    PathNotFound,
    PermissionDenied,
    Unauthorized,
    ValidationError,
)
from app.services import fileops
from tests.unit.fake_sftp import FakeSFTPClient

HOME = "/home/aimu"
A_TXT = HOME + "/a.txt"
PART_SUFFIX = ".awfm-part-"


def make_session(client, *, allow_write=True, connection_id="vm1"):
    """服务层实际用到的 session 形状：一个 client 加一个 connection。"""
    connection = SimpleNamespace(allow_write=allow_write, id=connection_id)
    return SimpleNamespace(client=client, connection=connection)


def leftovers(client):
    return [name for name in client.names() if PART_SUFFIX in name]


def build_tar_gz(items):
    """items 里每一项是 (名字, bytes)，(名字, None) 表示目录，(名字, None, 目标) 表示符号链接。"""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.GNU_FORMAT) as tar:
        for item in items:
            name = item[0]
            data = item[1]
            link = item[2] if len(item) > 2 else None
            info = tarfile.TarInfo(name)
            if link is not None:
                info.type = tarfile.SYMTYPE
                info.linkname = link
                tar.addfile(info)
            elif data is None:
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            else:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def build_zip(items, *, symlinks=()):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in items:
            archive.writestr(name, data)
        for name, target in symlinks:
            info = zipfile.ZipInfo(name)
            info.external_attr = 0o120777 << 16
            archive.writestr(info, target)
    return buffer.getvalue()


class FileOpsTestCase(unittest.TestCase):
    """公共脚手架：一个内存 SFTP 客户端 + 一个允许写的会话。"""

    def setUp(self):
        self.client = FakeSFTPClient()
        self.session = make_session(self.client)

    def put(self, name, data, *, mode=0o644):
        path = HOME + "/" + name
        self.client.add_file(path, data, mode=mode)
        return path

    def failure(self, exc_type, func, *args, **kwargs):
        with self.assertRaises(exc_type) as caught:
            func(*args, **kwargs)
        return caught.exception

    def archive_members(self, path):
        with tarfile.open(fileobj=io.BytesIO(self.client.read(path)), mode="r:gz") as tar:
            return {member.name: member for member in tar.getmembers()}


class RenameTests(FileOpsTestCase):
    def test_renames_a_file(self):
        self.put("a.txt", "hello\n")
        result = fileops.rename_entry(self.session, A_TXT, "b.txt")
        self.assertEqual(result["name"], "a.txt")
        self.assertEqual(result["new_name"], "b.txt")
        self.assertEqual(result["new_path"], HOME + "/b.txt")
        self.assertEqual(result["type"], "file")
        self.assertEqual(result["size"], 6)
        self.assertFalse(self.client.exists(A_TXT))
        self.assertEqual(self.client.text(result["new_path"]), "hello\n")

    def test_renames_a_directory_with_its_content(self):
        self.client.add_dir(HOME + "/d")
        self.put("d/x.txt", "x")
        fileops.rename_entry(self.session, HOME + "/d", "e")
        self.assertFalse(self.client.exists(HOME + "/d/x.txt"))
        self.assertEqual(self.client.text(HOME + "/e/x.txt"), "x")

    def test_refuses_to_overwrite_an_existing_entry(self):
        self.put("a.txt", "hello\n")
        self.put("b.txt", "keep me\n")
        error = self.failure(ValidationError, fileops.rename_entry, self.session, A_TXT, "b.txt")
        self.assertEqual(error.code, "invalid_request")
        self.assertTrue(error.extra["exists"])
        self.assertEqual(error.extra["type"], "file")
        self.assertEqual(self.client.text(HOME + "/b.txt"), "keep me\n")
        self.assertEqual(self.client.text(A_TXT), "hello\n")

    def test_the_same_name_is_refused(self):
        self.put("a.txt", "hello\n")
        error = self.failure(ValidationError, fileops.rename_entry, self.session, A_TXT, "a.txt")
        self.assertEqual(error.code, "invalid_request")

    def test_invalid_names_are_refused(self):
        self.put("a.txt", "hello\n")
        for bad in ["", ".", "..", "sub/b.txt", "x" * 256, "with\x00nul"]:
            error = self.failure(ValidationError, fileops.rename_entry, self.session, A_TXT, bad)
            self.assertEqual(error.code, "invalid_request", bad)
        self.assertTrue(self.client.exists(A_TXT))

    def test_root_cannot_be_renamed(self):
        error = self.failure(ValidationError, fileops.rename_entry, self.session, "/", "root2")
        self.assertEqual(error.code, "invalid_request")

    def test_relative_path_is_refused(self):
        self.put("a.txt", "hello\n")
        error = self.failure(ValidationError, fileops.rename_entry, self.session, "a.txt", "b.txt")
        self.assertEqual(error.code, "invalid_request")

    def test_missing_source_is_not_found(self):
        # 源不存在由远端的 RENAME 报错（映射成 404），不是参数校验失败。
        error = self.failure(PathNotFound, fileops.rename_entry, self.session, HOME + "/nope", "x")
        self.assertEqual(error.code, "path_not_found")

    def test_renaming_a_symlink_renames_the_link_not_the_target(self):
        self.put("a.txt", "hello\n")
        self.client.add_link(HOME + "/link.txt", A_TXT)
        result = fileops.rename_entry(self.session, HOME + "/link.txt", "renamed.txt")
        self.assertEqual(result["type"], "symlink")
        self.assertTrue(self.client.exists(HOME + "/renamed.txt"))
        self.assertFalse(self.client.exists(HOME + "/link.txt"))
        # 目标文件的名字与内容都没动。
        self.assertTrue(self.client.exists(A_TXT))
        self.assertEqual(self.client.text(A_TXT), "hello\n")

    def test_write_permission_is_required(self):
        self.put("a.txt", "hello\n")
        session = make_session(self.client, allow_write=False)
        error = self.failure(Unauthorized, fileops.rename_entry, session, A_TXT, "b.txt")
        self.assertEqual(error.code, "unauthorized")
        self.assertTrue(self.client.exists(A_TXT))

    def test_disconnected_session_cannot_rename(self):
        self.put("a.txt", "hello\n")
        self.client.offline = True
        error = self.failure(NotConnected, fileops.rename_entry, self.session, A_TXT, "b.txt")
        self.assertEqual(error.code, "not_connected")


class DeleteTests(FileOpsTestCase):
    def test_deletes_a_file(self):
        self.put("a.txt", "hello\n")
        result = fileops.delete_entry(self.session, A_TXT)
        self.assertEqual(result["type"], "file")
        self.assertEqual(result["removed"], {"files": 1, "directories": 0})
        self.assertEqual(result["entries"], 1)
        self.assertFalse(self.client.exists(A_TXT))

    def test_deletes_a_symlink_without_touching_its_target(self):
        self.put("a.txt", "hello\n")
        self.client.add_link(HOME + "/link.txt", A_TXT)
        result = fileops.delete_entry(self.session, HOME + "/link.txt")
        self.assertEqual(result["type"], "symlink")
        self.assertEqual(result["removed"]["files"], 1)
        self.assertEqual(self.client.text(A_TXT), "hello\n")

    def test_deleting_a_symlink_to_a_directory_keeps_the_directory(self):
        self.client.add_dir(HOME + "/target")
        self.put("target/keep.txt", "keep\n")
        self.client.add_link(HOME + "/dir-link", HOME + "/target")
        result = fileops.delete_entry(self.session, HOME + "/dir-link")
        self.assertEqual(result["type"], "symlink")
        self.assertEqual(result["removed"], {"files": 1, "directories": 0})
        self.assertTrue(self.client.exists(HOME + "/target/keep.txt"))
        self.assertFalse(self.client.exists(HOME + "/dir-link"))

    def test_empty_directory_is_removed_without_recursive(self):
        self.client.add_dir(HOME + "/d")
        result = fileops.delete_entry(self.session, HOME + "/d")
        self.assertEqual(result["removed"], {"files": 0, "directories": 1})
        self.assertFalse(self.client.exists(HOME + "/d"))

    def test_non_empty_directory_needs_recursive(self):
        self.client.add_dir(HOME + "/d")
        self.put("d/x.txt", "x")
        error = self.failure(ValidationError, fileops.delete_entry, self.session, HOME + "/d")
        self.assertEqual(error.code, "invalid_request")
        self.assertEqual(error.extra["entries"], 1)
        self.assertFalse(error.extra["recursive"])
        self.assertTrue(self.client.exists(HOME + "/d/x.txt"))

    def test_recursive_delete_counts_everything(self):
        self.client.add_dir(HOME + "/d")
        self.put("d/x.txt", "x")
        self.client.add_dir(HOME + "/d/sub")
        self.put("d/sub/y.txt", "y")
        self.client.add_dir(HOME + "/d/sub/deep")
        self.put("d/sub/deep/z.txt", "z")
        result = fileops.delete_entry(self.session, HOME + "/d", recursive=True)
        self.assertEqual(result["removed"], {"files": 3, "directories": 3})
        self.assertEqual(result["entries"], 6)
        self.assertFalse(self.client.exists(HOME + "/d"))

    def test_recursive_delete_does_not_follow_symlinks(self):
        self.put("a.txt", "hello\n")
        self.client.add_dir(HOME + "/target-dir")
        self.put("target-dir/keep.txt", "keep\n")
        self.client.add_dir(HOME + "/d")
        self.client.add_link(HOME + "/d/file-link", A_TXT)
        self.client.add_link(HOME + "/d/dir-link", HOME + "/target-dir")
        result = fileops.delete_entry(self.session, HOME + "/d", recursive=True)
        self.assertEqual(result["removed"], {"files": 2, "directories": 1})
        self.assertFalse(self.client.exists(HOME + "/d"))
        # 链接指向的文件与目录都还在：删的是链接本身。
        self.assertEqual(self.client.text(A_TXT), "hello\n")
        self.assertEqual(self.client.text(HOME + "/target-dir/keep.txt"), "keep\n")

    def test_root_cannot_be_deleted(self):
        error = self.failure(ValidationError, fileops.delete_entry, self.session, "/", recursive=True)
        self.assertEqual(error.code, "invalid_request")
        self.assertTrue(self.client.exists(HOME))

    def test_delete_budget_stops_a_huge_tree(self):
        self.client.add_dir(HOME + "/d")
        for index in range(4):
            self.put("d/f%d.txt" % index, "x")
        with mock.patch.object(fileops, "MAX_DELETE_ENTRIES", 1):
            error = self.failure(
                ValidationError, fileops.delete_entry, self.session, HOME + "/d", recursive=True
            )
        self.assertEqual(error.extra["limit"], 1)
        self.assertEqual(error.extra["removed"]["files"], 2)
        self.assertTrue(self.client.exists(HOME + "/d"))

    def test_depth_limit_stops_a_deep_tree(self):
        self.client.add_dir(HOME + "/d")
        self.client.add_dir(HOME + "/d/sub")
        self.client.add_dir(HOME + "/d/sub/deep")
        self.put("d/sub/deep/z.txt", "z")
        with mock.patch.object(fileops, "MAX_TREE_DEPTH", 1):
            error = self.failure(
                ValidationError, fileops.delete_entry, self.session, HOME + "/d", recursive=True
            )
        self.assertEqual(error.code, "invalid_request")

    def test_write_permission_is_required(self):
        self.put("a.txt", "hello\n")
        session = make_session(self.client, allow_write=False)
        error = self.failure(Unauthorized, fileops.delete_entry, session, A_TXT)
        self.assertEqual(error.code, "unauthorized")
        self.assertTrue(self.client.exists(A_TXT))

    def test_disconnected_session_cannot_delete(self):
        self.put("a.txt", "hello\n")
        self.client.offline = True
        error = self.failure(NotConnected, fileops.delete_entry, self.session, A_TXT)
        self.assertEqual(error.code, "not_connected")


class CompressTests(FileOpsTestCase):
    def test_compresses_a_file_next_to_it(self):
        self.put("a.txt", "hello\n")
        result = fileops.compress_entry(self.session, A_TXT)
        self.assertEqual(result["name"], "a.txt.tar.gz")
        self.assertEqual(result["path"], HOME + "/a.txt.tar.gz")
        self.assertEqual(result["format"], "tar.gz")
        self.assertEqual(result["entries"], 1)
        self.assertEqual(result["bytes"], 6)
        self.assertEqual(result["skipped"], [])
        self.assertEqual(result["size"], len(self.client.read(result["path"])))
        members = self.archive_members(result["path"])
        self.assertEqual(list(members), ["a.txt"])
        with tarfile.open(fileobj=io.BytesIO(self.client.read(result["path"])), mode="r:gz") as tar:
            self.assertEqual(tar.extractfile("a.txt").read(), b"hello\n")
        self.assertEqual(leftovers(self.client), [])

    def test_compresses_a_tree_with_directories(self):
        self.client.add_dir(HOME + "/d")
        self.put("d/x.txt", "x")
        self.client.add_dir(HOME + "/d/sub")
        self.put("d/sub/y.txt", "yy")
        result = fileops.compress_entry(self.session, HOME + "/d")
        self.assertEqual(result["name"], "d.tar.gz")
        members = self.archive_members(result["path"])
        self.assertEqual(sorted(members), ["d", "d/sub", "d/sub/y.txt", "d/x.txt"])
        self.assertTrue(members["d"].isdir())
        self.assertEqual(result["bytes"], 3)

    def test_symlinks_are_stored_as_links(self):
        self.client.add_dir(HOME + "/d")
        self.put("d/x.txt", "x")
        self.client.add_link(HOME + "/d/link.txt", HOME + "/d/x.txt")
        result = fileops.compress_entry(self.session, HOME + "/d")
        members = self.archive_members(result["path"])
        self.assertTrue(members["d/link.txt"].issym())
        self.assertEqual(members["d/link.txt"].linkname, HOME + "/d/x.txt")
        self.assertEqual(members["d/x.txt"].size, 1)

    def test_permissions_are_kept_in_the_archive(self):
        self.put("secret.txt", "s", mode=0o600)
        result = fileops.compress_entry(self.session, HOME + "/secret.txt")
        members = self.archive_members(result["path"])
        self.assertEqual(members["secret.txt"].mode & 0o777, 0o600)

    def test_custom_name_is_used_and_gets_the_suffix(self):
        self.put("a.txt", "hello\n")
        result = fileops.compress_entry(self.session, A_TXT, name="backup")
        self.assertEqual(result["name"], "backup.tar.gz")
        self.assertTrue(self.client.exists(HOME + "/backup.tar.gz"))

    def test_existing_archive_is_not_overwritten(self):
        self.put("a.txt", "hello\n")
        self.put("a.txt.tar.gz", "already here")
        error = self.failure(ValidationError, fileops.compress_entry, self.session, A_TXT)
        self.assertEqual(error.code, "invalid_request")
        self.assertEqual(error.extra["path"], HOME + "/a.txt.tar.gz")
        self.assertEqual(self.client.text(HOME + "/a.txt.tar.gz"), "already here")

    def test_root_cannot_be_compressed(self):
        error = self.failure(ValidationError, fileops.compress_entry, self.session, "/")
        self.assertEqual(error.code, "invalid_request")

    def test_missing_source_is_not_found(self):
        error = self.failure(PathNotFound, fileops.compress_entry, self.session, HOME + "/nope.txt")
        self.assertEqual(error.code, "path_not_found")

    def test_compressing_a_symlink_archives_the_link_itself(self):
        self.put("a.txt", "hello\n")
        self.client.add_link(HOME + "/link.txt", A_TXT)
        result = fileops.compress_entry(self.session, HOME + "/link.txt")
        self.assertEqual(result["name"], "link.txt.tar.gz")
        members = self.archive_members(result["path"])
        self.assertEqual(list(members), ["link.txt"])
        # 包里是链接本身，不是它指向的内容。
        self.assertTrue(members["link.txt"].issym())
        self.assertEqual(members["link.txt"].linkname, A_TXT)
        self.assertEqual(result["bytes"], 0)

    def test_entry_limit_stops_the_compression_and_cleans_up(self):
        self.client.add_dir(HOME + "/d")
        self.put("d/x.txt", "x")
        self.put("d/y.txt", "y")
        with mock.patch.object(fileops, "MAX_ARCHIVE_ENTRIES", 1):
            error = self.failure(ValidationError, fileops.compress_entry, self.session, HOME + "/d")
        self.assertEqual(error.extra["limit"], 1)
        self.assertFalse(self.client.exists(HOME + "/d.tar.gz"))
        self.assertEqual(leftovers(self.client), [])

    def test_byte_limit_stops_the_compression_and_cleans_up(self):
        self.put("big.txt", "0123456789")
        with mock.patch.object(fileops, "MAX_ARCHIVE_BYTES", 4):
            error = self.failure(ValidationError, fileops.compress_entry, self.session, HOME + "/big.txt")
        self.assertEqual(error.extra["limit"], 4)
        self.assertFalse(self.client.exists(HOME + "/big.txt.tar.gz"))
        self.assertEqual(leftovers(self.client), [])

    def test_write_permission_is_required(self):
        self.put("a.txt", "hello\n")
        session = make_session(self.client, allow_write=False)
        error = self.failure(Unauthorized, fileops.compress_entry, session, A_TXT)
        self.assertEqual(error.code, "unauthorized")
        self.assertFalse(self.client.exists(HOME + "/a.txt.tar.gz"))

    def test_disconnected_session_cannot_compress(self):
        self.put("a.txt", "hello\n")
        self.client.offline = True
        error = self.failure(NotConnected, fileops.compress_entry, self.session, A_TXT)
        self.assertEqual(error.code, "not_connected")
        self.assertEqual(leftovers(self.client), [])


class ExtractTests(FileOpsTestCase):
    def test_extracts_a_tar_gz_next_to_the_archive(self):
        path = self.put(
            "pack.tar.gz",
            build_tar_gz([("one.txt", b"1"), ("sub/two.txt", b"22")]),
        )
        result = fileops.extract_entry(self.session, path)
        self.assertEqual(result["destination"], HOME)
        self.assertEqual(result["format"], "tar.gz")
        self.assertEqual(result["files"], 2)
        self.assertEqual(result["existing"], [])
        self.assertEqual(result["stopped"], None)
        self.assertEqual(self.client.text(HOME + "/one.txt"), "1")
        self.assertEqual(self.client.text(HOME + "/sub/two.txt"), "22")
        self.assertEqual(leftovers(self.client), [])

    def test_extracts_a_zip_and_creates_missing_parents(self):
        path = self.put("pack.zip", build_zip([("top.txt", b"t"), ("nested/deep.txt", b"d")]))
        result = fileops.extract_entry(self.session, path)
        self.assertEqual(result["format"], "zip")
        self.assertEqual(result["files"], 2)
        self.assertEqual(self.client.text(HOME + "/nested/deep.txt"), "d")

    def test_plain_tar_is_supported(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            info = tarfile.TarInfo("plain.txt")
            info.size = 5
            tar.addfile(info, io.BytesIO(b"plain"))
        path = self.put("plain.tar", buffer.getvalue())
        result = fileops.extract_entry(self.session, path)
        self.assertEqual(result["format"], "tar")
        self.assertEqual(self.client.text(HOME + "/plain.txt"), "plain")

    def test_extracts_into_an_explicit_directory(self):
        path = self.put("pack.tar.gz", build_tar_gz([("one.txt", b"1")]))
        result = fileops.extract_entry(self.session, path, into=HOME + "/out")
        self.assertEqual(result["destination"], HOME + "/out")
        self.assertTrue(self.client.exists(HOME + "/out"))
        self.assertEqual(self.client.text(HOME + "/out/one.txt"), "1")

    def test_missing_multi_level_destination_is_not_invented(self):
        path = self.put("pack.tar.gz", build_tar_gz([("one.txt", b"1")]))
        self.failure(PathNotFound, fileops.extract_entry, self.session, path, into=HOME + "/no/such")

    def test_destination_must_be_a_directory(self):
        self.put("a.txt", "x")
        path = self.put("pack.tar.gz", build_tar_gz([("one.txt", b"1")]))
        error = self.failure(ValidationError, fileops.extract_entry, self.session, path, into=A_TXT)
        self.assertEqual(error.code, "invalid_request")

    def test_directory_entries_are_created(self):
        path = self.put("pack.tar.gz", build_tar_gz([("sub/", None), ("sub/two.txt", b"22")]))
        result = fileops.extract_entry(self.session, path)
        self.assertTrue(self.client.exists(HOME + "/sub"))
        self.assertEqual(result["files"], 1)

    def test_traversal_members_are_refused(self):
        cases = [
            [("../evil.txt", b"x")],
            [("/abs.txt", b"y")],
            [("a/../../b.txt", b"z")],
            [("..\\evil.txt", b"w")],
        ]
        for items in cases:
            path = self.put("pack.tar.gz", build_tar_gz(items))
            error = self.failure(ValidationError, fileops.extract_entry, self.session, path)
            self.assertEqual(error.code, "invalid_request", items)
        self.assertFalse(self.client.exists(HOME + "/evil.txt"))
        self.assertFalse(self.client.exists("/evil.txt"))
        self.assertFalse(self.client.exists("/abs.txt"))
        self.assertFalse(self.client.exists(HOME + "/b.txt"))

    def test_zip_traversal_members_are_refused(self):
        path = self.put("pack.zip", build_zip([("../evil.txt", b"x"), ("/abs.txt", b"y")]))
        self.failure(ValidationError, fileops.extract_entry, self.session, path)
        self.assertFalse(self.client.exists(HOME + "/evil.txt"))
        self.assertFalse(self.client.exists("/abs.txt"))

    def test_symlink_members_are_skipped(self):
        path = self.put(
            "pack.tar.gz",
            build_tar_gz([("one.txt", b"1"), ("link.txt", None, "one.txt")]),
        )
        result = fileops.extract_entry(self.session, path)
        self.assertEqual([item["code"] for item in result["skipped"]], ["symlink_skipped"])
        self.assertEqual(result["skipped"][0]["name"], "link.txt")
        self.assertFalse(self.client.exists(HOME + "/link.txt"))
        self.assertEqual(self.client.text(HOME + "/one.txt"), "1")

    def test_zip_symlink_members_are_skipped(self):
        path = self.put("pack.zip", build_zip([("one.txt", b"1")], symlinks=[("link.txt", "one.txt")]))
        result = fileops.extract_entry(self.session, path)
        self.assertEqual([item["code"] for item in result["skipped"]], ["symlink_skipped"])
        self.assertFalse(self.client.exists(HOME + "/link.txt"))

    def test_existing_files_are_skipped_by_default(self):
        self.put("one.txt", "old")
        path = self.put("pack.tar.gz", build_tar_gz([("one.txt", b"new")]))
        result = fileops.extract_entry(self.session, path)
        self.assertEqual(result["existing"], ["one.txt"])
        self.assertEqual(result["files"], 0)
        self.assertEqual(self.client.text(HOME + "/one.txt"), "old")

    def test_overwrite_replaces_existing_files(self):
        self.put("one.txt", "old")
        path = self.put("pack.tar.gz", build_tar_gz([("one.txt", b"new")]))
        result = fileops.extract_entry(self.session, path, overwrite=True)
        self.assertEqual(result["existing"], [])
        self.assertEqual(result["files"], 1)
        self.assertEqual(self.client.text(HOME + "/one.txt"), "new")
        self.assertEqual(leftovers(self.client), [])

    def test_file_member_colliding_with_a_directory_is_refused(self):
        self.client.add_dir(HOME + "/one.txt")
        path = self.put("pack.tar.gz", build_tar_gz([("one.txt", b"new")]))
        error = self.failure(ValidationError, fileops.extract_entry, self.session, path)
        self.assertEqual(error.code, "invalid_request")
        self.assertEqual(error.extra["path"], HOME + "/one.txt")

    def test_unsupported_suffix_is_refused(self):
        path = self.put("note.txt", "not an archive")
        error = self.failure(ValidationError, fileops.extract_entry, self.session, path)
        self.assertEqual(error.code, "invalid_request")

    def test_directory_cannot_be_extracted(self):
        self.client.add_dir(HOME + "/d.tar.gz")
        error = self.failure(ValidationError, fileops.extract_entry, self.session, HOME + "/d.tar.gz")
        self.assertEqual(error.code, "invalid_request")

    def test_archive_over_the_byte_limit_is_refused(self):
        path = self.put("pack.tar.gz", build_tar_gz([("one.txt", b"1")]))
        with mock.patch.object(fileops, "MAX_EXTRACT_BYTES", 2):
            error = self.failure(ValidationError, fileops.extract_entry, self.session, path)
        self.assertEqual(error.extra["limit"], 2)

    def test_entry_limit_stops_the_extraction(self):
        path = self.put(
            "pack.tar.gz",
            build_tar_gz([("a.txt", b"a"), ("b.txt", b"b"), ("c.txt", b"c")]),
        )
        with mock.patch.object(fileops, "MAX_EXTRACT_ENTRIES", 1):
            result = fileops.extract_entry(self.session, path)
        self.assertTrue(result["stopped"])
        self.assertEqual(result["files"], 1)

    def test_size_limit_stops_the_extraction(self):
        path = self.put("pack.tar.gz", build_tar_gz([("big.txt", b"a" * 5000)]))
        with mock.patch.object(fileops, "MAX_EXTRACT_BYTES", 1000):
            result = fileops.extract_entry(self.session, path)
        self.assertTrue(result["stopped"])
        self.assertEqual(result["files"], 0)

    def test_round_trip_keeps_the_bytes(self):
        payload = bytes(range(256)) * 8
        self.put("blob.bin", payload)
        compressed = fileops.compress_entry(self.session, HOME + "/blob.bin")
        self.client.remove(HOME + "/blob.bin")
        fileops.extract_entry(self.session, compressed["path"])
        self.assertEqual(self.client.read(HOME + "/blob.bin"), payload)

    def test_write_permission_is_required(self):
        path = self.put("pack.tar.gz", build_tar_gz([("one.txt", b"1")]))
        session = make_session(self.client, allow_write=False)
        error = self.failure(Unauthorized, fileops.extract_entry, session, path)
        self.assertEqual(error.code, "unauthorized")
        self.assertFalse(self.client.exists(HOME + "/one.txt"))

    def test_disconnected_session_cannot_extract(self):
        path = self.put("pack.tar.gz", build_tar_gz([("one.txt", b"1")]))
        self.client.offline = True
        error = self.failure(NotConnected, fileops.extract_entry, self.session, path)
        self.assertEqual(error.code, "not_connected")


class HelperTests(unittest.TestCase):
    def test_archive_format(self):
        self.assertEqual(fileops.archive_format("/a/b.tar.gz"), "tar.gz")
        self.assertEqual(fileops.archive_format("/a/b.TGZ"), "tar.gz")
        self.assertEqual(fileops.archive_format("/a/b.tar"), "tar")
        self.assertEqual(fileops.archive_format("/a/b.zip"), "zip")
        self.assertEqual(fileops.archive_format("/a/b.txt"), "")

    def test_name_of(self):
        self.assertEqual(fileops.name_of("/a/b/c.txt"), "c.txt")
        self.assertEqual(fileops.name_of("/"), "/")


if __name__ == "__main__":
    unittest.main()
