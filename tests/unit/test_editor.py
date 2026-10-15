"""在线编辑服务（app/services/editor.py）的单元测试。

后端用 tests/unit/fake_sftp.py 的内存 SFTP：它按协议语义处理权限位、符号链接和
「rename 不覆盖已有目标」，所以这里断言的是真实副作用（远端字节、残留文件、错误码），
而不是「调用了哪些方法」。
"""

import hashlib
import unittest
from types import SimpleNamespace

from app.core.errors import (
    EditConflict,
    NotConnected,
    PathNotFound,
    PayloadTooLarge,
    PermissionDenied,
    RemoteError,
    Unauthorized,
    ValidationError,
)
from app.services import editor
from tests.unit.fake_sftp import FakeSFTPClient

HOME = "/home/aimu"
A_TXT = HOME + "/a.txt"
PART_SUFFIX = ".awfm-part-"
BACKUP_SUFFIX = ".awfm-bak-"


def make_session(client, *, allow_write=True, connection_id="vm1"):
    """服务层实际用到的 session 形状：一个 client 加一个 connection。"""
    connection = SimpleNamespace(allow_write=allow_write, id=connection_id)
    return SimpleNamespace(client=client, connection=connection)


def leftovers(client):
    return [name for name in client.names() if PART_SUFFIX in name or BACKUP_SUFFIX in name]


class RenameFailingClient(FakeSFTPClient):
    """rename 在第 fail_at 次调用时失败，用来验证保存失败时的放弃与回滚。"""

    def __init__(self, *, fail_at=1, **kwargs):
        super().__init__(**kwargs)
        self.fail_at = fail_at
        self.rename_calls = 0

    def rename(self, old, new):
        self.rename_calls += 1
        if self.rename_calls == self.fail_at:
            raise RemoteError("模拟的 rename 失败。")
        return super().rename(old, new)


class EditorTestCase(unittest.TestCase):
    """公共脚手架：一个内存 SFTP 客户端 + 一个允许写的会话。"""

    def setUp(self):
        self.client = FakeSFTPClient()
        self.session = make_session(self.client)

    def open_file(self, path=A_TXT, data="hello\n", **kwargs):
        self.client.add_file(path, data, **kwargs)
        return editor.read_text_file(self.session, path)

    def failure(self, exc_type, func, *args, **kwargs):
        with self.assertRaises(exc_type) as caught:
            func(*args, **kwargs)
        return caught.exception


class ReadTextTests(EditorTestCase):
    def test_reads_utf8_text_with_metadata(self):
        info = self.open_file()
        self.assertEqual(info["path"], A_TXT)
        self.assertEqual(info["name"], "a.txt")
        self.assertEqual(info["text"], "hello\n")
        self.assertEqual(info["size"], 6)
        self.assertEqual(info["encoding"], "utf-8")
        self.assertEqual(info["sha256"], hashlib.sha256(b"hello\n").hexdigest())
        self.assertEqual(info["limit"], editor.DEFAULT_MAX_EDIT_BYTES)
        self.assertFalse(info["bom"])
        self.assertEqual(info["newline"], "lf")
        self.assertFalse(info["mixed_newlines"])
        self.assertTrue(info["final_newline"])

    def test_reports_mode_and_honours_the_configured_limit(self):
        info = self.open_file(data="abc\n", mode=0o640)
        self.assertEqual(int(info["mode"], 8) & 0o777, 0o640)
        info = editor.read_text_file(self.session, A_TXT, max_bytes=1024)
        self.assertEqual(info["limit"], 1024)

    def test_chinese_content_round_trip(self):
        text = "第一行：中文\n第二行：带标点，句号。\n"
        info = self.open_file(data=text)
        self.assertEqual(info["text"], text)
        saved = editor.save_text_file(
            self.session, A_TXT, text.replace("第一行", "改过的第一行"), base_sha256=info["sha256"]
        )
        self.assertTrue(saved["saved"])
        self.assertEqual(self.client.text(A_TXT), "改过的第一行：中文\n第二行：带标点，句号。\n")

    def test_empty_file_can_be_opened_and_filled(self):
        info = self.open_file(data=b"")
        self.assertEqual(info["text"], "")
        self.assertEqual(info["size"], 0)
        self.assertFalse(info["final_newline"])
        saved = editor.save_text_file(self.session, A_TXT, "写点东西\n", base_sha256=info["sha256"])
        self.assertEqual(saved["size"], len("写点东西\n".encode("utf-8")))
        self.assertEqual(self.client.text(A_TXT), "写点东西\n")

    def test_crlf_file_reports_style_and_normalises_text(self):
        info = self.open_file(data=b"one\r\ntwo\r\n")
        self.assertEqual(info["newline"], "crlf")
        self.assertEqual(info["text"], "one\ntwo\n")
        self.assertFalse(info["mixed_newlines"])
        self.assertTrue(info["final_newline"])

    def test_missing_final_newline_is_reported(self):
        info = self.open_file(data=b"one\r\ntwo")
        self.assertFalse(info["final_newline"])
        self.assertEqual(info["text"], "one\ntwo")

    def test_mixed_newlines_are_flagged(self):
        info = self.open_file(data=b"a\nb\r\nc\n")
        self.assertTrue(info["mixed_newlines"])

    def test_lone_cr_is_recognised(self):
        info = self.open_file(data=b"a\rb\rc\r")
        self.assertEqual(info["newline"], "cr")
        self.assertEqual(info["text"], "a\nb\nc\n")
        self.assertTrue(info["final_newline"])

    def test_file_without_any_newline(self):
        info = self.open_file(data=b"single line")
        self.assertEqual(info["newline"], "none")
        self.assertFalse(info["final_newline"])

    def test_bom_is_stripped_and_flagged(self):
        info = self.open_file(data=b"\xef\xbb\xbfhi\n")
        self.assertTrue(info["bom"])
        self.assertEqual(info["text"], "hi\n")
        self.assertEqual(info["size"], 6)

    def test_tab_is_not_treated_as_binary(self):
        info = self.open_file(data=b"a\tb\tc\n")
        self.assertEqual(info["text"], "a\tb\tc\n")

    def test_binary_file_is_refused(self):
        self.client.add_file(A_TXT, b"\x00\x01hello\n")
        error = self.failure(ValidationError, editor.read_text_file, self.session, A_TXT)
        self.assertEqual(error.code, "invalid_request")
        self.assertEqual(error.extra["size"], 8)

    def test_control_heavy_file_is_refused(self):
        self.client.add_file(A_TXT, bytes(range(1, 32)) * 8)
        error = self.failure(ValidationError, editor.read_text_file, self.session, A_TXT)
        self.assertEqual(error.code, "invalid_request")

    def test_non_utf8_file_is_refused(self):
        self.client.add_file(A_TXT, "中文内容\n".encode("gbk"))
        error = self.failure(ValidationError, editor.read_text_file, self.session, A_TXT)
        self.assertEqual(error.code, "invalid_request")
        self.assertIn("offset", error.extra)

    def test_directory_is_refused(self):
        self.client.add_dir(HOME + "/sub")
        error = self.failure(ValidationError, editor.read_text_file, self.session, HOME + "/sub")
        self.assertEqual(error.code, "invalid_request")

    def test_symlink_to_a_file_is_read(self):
        self.client.add_file(A_TXT, "hello\n")
        self.client.add_link(HOME + "/link.txt", A_TXT)
        info = editor.read_text_file(self.session, HOME + "/link.txt")
        self.assertEqual(info["path"], A_TXT)
        self.assertEqual(info["text"], "hello\n")

    def test_symlink_to_a_directory_is_refused(self):
        self.client.add_dir(HOME + "/sub")
        self.client.add_link(HOME + "/link", HOME + "/sub")
        error = self.failure(ValidationError, editor.read_text_file, self.session, HOME + "/link")
        self.assertEqual(error.code, "invalid_request")

    def test_dangling_symlink_is_not_found(self):
        self.client.add_link(HOME + "/gone.txt", HOME + "/never.txt")
        error = self.failure(PathNotFound, editor.read_text_file, self.session, HOME + "/gone.txt")
        self.assertEqual(error.code, "path_not_found")

    def test_size_limit_is_checked_before_reading(self):
        self.client.add_file(A_TXT, b"12345")
        error = self.failure(PayloadTooLarge, editor.read_text_file, self.session, A_TXT, max_bytes=4)
        self.assertEqual(error.code, "payload_too_large")
        self.assertEqual(error.extra["limit"], 4)

    def test_relative_path_is_rejected(self):
        self.client.add_file(A_TXT, b"x")
        error = self.failure(ValidationError, editor.read_text_file, self.session, "a.txt")
        self.assertEqual(error.code, "invalid_request")

    def test_disconnected_session_cannot_read(self):
        self.client.add_file(A_TXT, "hello\n")
        self.client.offline = True
        error = self.failure(NotConnected, editor.read_text_file, self.session, A_TXT)
        self.assertEqual(error.code, "not_connected")


class SaveTextTests(EditorTestCase):
    def test_save_writes_content_and_reports_the_new_state(self):
        info = self.open_file()
        result = editor.save_text_file(self.session, A_TXT, "hello world\n", base_sha256=info["sha256"])
        self.assertTrue(result["saved"])
        self.assertEqual(self.client.text(A_TXT), "hello world\n")
        self.assertEqual(result["size"], 12)
        self.assertEqual(result["bytes_written"], 12)
        self.assertEqual(result["sha256"], hashlib.sha256(b"hello world\n").hexdigest())
        self.assertEqual(result["encoding"], "utf-8")
        self.assertEqual(result["name"], "a.txt")
        self.assertEqual(result["mtime"], self.client.lstat(A_TXT).mtime)
        self.assertEqual(leftovers(self.client), [])

    def test_save_keeps_the_file_mode(self):
        info = self.open_file(mode=0o600)
        editor.save_text_file(self.session, A_TXT, "x\n", base_sha256=info["sha256"])
        self.assertEqual(self.client.lstat(A_TXT).permissions & 0o777, 0o600)

    def test_save_requires_a_base(self):
        self.client.add_file(A_TXT, "hello\n")
        error = self.failure(ValidationError, editor.save_text_file, self.session, A_TXT, "new\n")
        self.assertEqual(error.code, "invalid_request")

    def test_save_rejects_non_string_text(self):
        info = self.open_file()
        error = self.failure(
            ValidationError, editor.save_text_file, self.session, A_TXT, b"bytes", base_sha256=info["sha256"]
        )
        self.assertEqual(error.code, "invalid_request")

    def test_conflict_when_the_content_changed(self):
        info = self.open_file()
        self.client.add_file(A_TXT, "changed by someone else\n", mtime=info["mtime"] + 5)
        error = self.failure(
            EditConflict, editor.save_text_file, self.session, A_TXT, "mine\n", base_sha256=info["sha256"]
        )
        self.assertEqual(error.code, "edit_conflict")
        self.assertEqual(error.extra["reason"], "content")
        self.assertEqual(self.client.text(A_TXT), "changed by someone else\n")
        self.assertEqual(leftovers(self.client), [])

    def test_conflict_when_the_file_grew_past_the_limit(self):
        info = self.open_file(data=b"small\n")
        self.client.add_file(A_TXT, b"x" * 100)
        error = self.failure(
            EditConflict,
            editor.save_text_file,
            self.session,
            A_TXT,
            "mine\n",
            base_sha256=info["sha256"],
            max_bytes=64,
        )
        self.assertEqual(error.code, "edit_conflict")
        self.assertEqual(error.extra["reason"], "size")

    def test_mtime_base_is_enough_to_save(self):
        info = self.open_file(data=b"one\r\ntwo\r\n")
        result = editor.save_text_file(self.session, A_TXT, "one\ntwo\nthree\n", base_mtime=info["mtime"])
        self.assertEqual(result["newline"], "crlf")
        self.assertEqual(self.client.read(A_TXT), b"one\r\ntwo\r\nthree\r\n")

    def test_conflict_when_only_the_mtime_moved(self):
        info = self.open_file()
        self.client.add_file(A_TXT, "hello\n", mtime=info["mtime"] + 5)
        error = self.failure(
            EditConflict, editor.save_text_file, self.session, A_TXT, "mine\n", base_mtime=info["mtime"]
        )
        self.assertEqual(error.code, "edit_conflict")
        self.assertEqual(error.extra["reason"], "mtime")

    def test_save_requires_write_permission(self):
        info = self.open_file()
        session = make_session(self.client, allow_write=False)
        error = self.failure(
            Unauthorized, editor.save_text_file, session, A_TXT, "mine\n", base_sha256=info["sha256"]
        )
        self.assertEqual(error.code, "unauthorized")
        self.assertEqual(error.extra["connection_id"], "vm1")
        self.assertEqual(self.client.text(A_TXT), "hello\n")
        self.assertEqual(leftovers(self.client), [])

    def test_readonly_file_is_rejected(self):
        info = self.open_file(mode=0o444)
        error = self.failure(
            PermissionDenied, editor.save_text_file, self.session, A_TXT, "mine\n", base_sha256=info["sha256"]
        )
        self.assertEqual(error.code, "permission_denied")
        self.assertEqual(error.extra["mode"], "0444")
        self.assertEqual(self.client.text(A_TXT), "hello\n")
        self.assertEqual(leftovers(self.client), [])

    def test_save_when_the_file_vanished(self):
        info = self.open_file()
        self.client.remove(A_TXT)
        error = self.failure(
            PathNotFound, editor.save_text_file, self.session, A_TXT, "mine\n", base_sha256=info["sha256"]
        )
        self.assertEqual(error.code, "path_not_found")
        self.assertEqual(leftovers(self.client), [])

    def test_save_when_the_path_became_a_directory(self):
        info = self.open_file()
        self.client.remove(A_TXT)
        self.client.add_dir(A_TXT)
        error = self.failure(
            ValidationError, editor.save_text_file, self.session, A_TXT, "mine\n", base_sha256=info["sha256"]
        )
        self.assertEqual(error.code, "invalid_request")

    def test_disconnected_session_cannot_save(self):
        info = self.open_file()
        self.client.offline = True
        error = self.failure(
            NotConnected, editor.save_text_file, self.session, A_TXT, "mine\n", base_sha256=info["sha256"]
        )
        self.assertEqual(error.code, "not_connected")
        self.client.offline = False
        self.assertEqual(self.client.text(A_TXT), "hello\n")
        self.assertEqual(leftovers(self.client), [])

    def test_backup_rename_failure_keeps_the_original(self):
        client = RenameFailingClient(fail_at=1)
        client.add_file(A_TXT, "hello\n")
        session = make_session(client)
        info = editor.read_text_file(session, A_TXT)
        error = self.failure(
            RemoteError, editor.save_text_file, session, A_TXT, "mine\n", base_sha256=info["sha256"]
        )
        self.assertEqual(error.code, "remote_error")
        self.assertEqual(client.text(A_TXT), "hello\n")
        self.assertEqual(leftovers(client), [])

    def test_replace_failure_rolls_back_the_original(self):
        client = RenameFailingClient(fail_at=2)
        client.add_file(A_TXT, "hello\n")
        session = make_session(client)
        info = editor.read_text_file(session, A_TXT)
        error = self.failure(
            RemoteError, editor.save_text_file, session, A_TXT, "mine\n", base_sha256=info["sha256"]
        )
        self.assertEqual(error.code, "remote_error")
        self.assertEqual(client.text(A_TXT), "hello\n")
        self.assertEqual(leftovers(client), [])

    def test_save_rejects_oversized_text(self):
        info = self.open_file()
        error = self.failure(
            PayloadTooLarge,
            editor.save_text_file,
            self.session,
            A_TXT,
            "x" * 32,
            base_sha256=info["sha256"],
            max_bytes=8,
        )
        self.assertEqual(error.code, "payload_too_large")
        self.assertEqual(self.client.text(A_TXT), "hello\n")
        self.assertEqual(leftovers(self.client), [])

    def test_unencodable_text_is_rejected(self):
        info = self.open_file()
        error = self.failure(
            ValidationError,
            editor.save_text_file,
            self.session,
            A_TXT,
            "bad " + chr(0xD800) + "\n",
            base_sha256=info["sha256"],
        )
        self.assertEqual(error.code, "invalid_request")
        self.assertEqual(self.client.text(A_TXT), "hello\n")

    def test_newline_style_is_kept_by_default(self):
        info = self.open_file(data=b"one\r\ntwo\r\n")
        result = editor.save_text_file(
            self.session, A_TXT, "alpha\nbeta\ngamma\n", base_sha256=info["sha256"]
        )
        self.assertEqual(result["newline"], "crlf")
        self.assertEqual(self.client.read(A_TXT), b"alpha\r\nbeta\r\ngamma\r\n")

    def test_explicit_newline_style_wins(self):
        info = self.open_file(data=b"one\ntwo\n")
        result = editor.save_text_file(
            self.session, A_TXT, "a\nb\n", base_sha256=info["sha256"], newline="crlf"
        )
        self.assertEqual(result["newline"], "crlf")
        self.assertEqual(self.client.read(A_TXT), b"a\r\nb\r\n")
        info = editor.read_text_file(self.session, A_TXT)
        editor.save_text_file(self.session, A_TXT, "x\ny\n", base_sha256=info["sha256"], newline="cr")
        self.assertEqual(self.client.read(A_TXT), b"x\ry\r")

    def test_lf_input_is_normalised_before_encoding(self):
        info = self.open_file(data=b"a\r\nb\r\n")
        editor.save_text_file(
            self.session, A_TXT, "1\r\n2\r3\n", base_sha256=info["sha256"], newline="lf"
        )
        self.assertEqual(self.client.read(A_TXT), b"1\n2\n3\n")

    def test_bom_is_only_written_back_when_asked(self):
        info = self.open_file(data=b"\xef\xbb\xbfhello\n")
        self.assertTrue(info["bom"])
        editor.save_text_file(self.session, A_TXT, "hello\n", base_sha256=info["sha256"])
        self.assertFalse(self.client.read(A_TXT).startswith(b"\xef\xbb\xbf"))
        info = editor.read_text_file(self.session, A_TXT)
        result = editor.save_text_file(
            self.session, A_TXT, "hello\n", base_sha256=info["sha256"], keep_bom=True
        )
        self.assertTrue(result["bom"])
        self.assertTrue(self.client.read(A_TXT).startswith(b"\xef\xbb\xbf"))

    def test_describe_limits(self):
        limits = editor.describe_limits(1234)
        self.assertEqual(limits["max_edit_bytes"], 1234)
        self.assertEqual(limits["encodings"], ["utf-8"])
        self.assertEqual(limits["newlines"], ["lf", "crlf", "cr"])


if __name__ == "__main__":
    unittest.main()
