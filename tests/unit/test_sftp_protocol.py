"""SFTP v3 协议编解码。这里的每个断言都对应一次真实踩坑。"""

import struct
import unittest

from app.core.errors import ProtocolError
from app.ssh import sftp_protocol as proto


def frame(frame_type: int, payload: bytes = b"") -> bytes:
    return bytes([frame_type]) + payload


def attrs_body(flags: int, *, size=None, uid=None, gid=None, permissions=None, atime=None, mtime=None) -> bytes:
    body = proto.encode_uint32(flags)
    if size is not None:
        body += proto.encode_uint64(size)
    if uid is not None:
        body += proto.encode_uint32(uid)
    if gid is not None:
        body += proto.encode_uint32(gid)
    if permissions is not None:
        body += proto.encode_uint32(permissions)
    if atime is not None:
        body += proto.encode_uint32(atime)
    if mtime is not None:
        body += proto.encode_uint32(mtime)
    return body


class EncodeTests(unittest.TestCase):
    def test_string_is_length_prefixed_utf8(self):
        encoded = proto.encode_string("abc")
        self.assertEqual(encoded, b"\x00\x00\x00\x03abc")
        self.assertEqual(proto.encode_string("中"), b"\x00\x00\x00\x03" + "中".encode("utf-8"))

    def test_string_accepts_bytes_and_keeps_them_raw(self):
        self.assertEqual(proto.encode_string(b"\x00\xff"), b"\x00\x00\x00\x02\x00\xff")

    def test_empty_string(self):
        self.assertEqual(proto.encode_string(""), b"\x00\x00\x00\x00")

    def test_uint_widths(self):
        self.assertEqual(proto.encode_uint32(1), b"\x00\x00\x00\x01")
        self.assertEqual(proto.encode_uint64(1), b"\x00\x00\x00\x00\x00\x00\x00\x01")

    def test_attrs_permissions_is_a_full_attrs_block(self):
        # MKDIR/SETSTAT 的第三个字段是完整 ATTRS。只发一个裸 uint32 会让
        # sftp-server fatal() 退出，客户端只看到「EOF poll=None」。
        encoded = proto.encode_attrs_permissions(0o755)
        self.assertEqual(len(encoded), 8)
        flags, mode = struct.unpack(">II", encoded)
        self.assertEqual(flags, proto.SSH_FILEXFER_ATTR_PERMISSIONS)
        self.assertEqual(mode, 0o755)

    def test_attrs_permissions_drops_type_bits(self):
        _, mode = struct.unpack(">II", proto.encode_attrs_permissions(proto.S_IFDIR | 0o750))
        self.assertEqual(mode, 0o750)

    def test_attrs_permissions_keeps_setuid(self):
        _, mode = struct.unpack(">II", proto.encode_attrs_permissions(proto.S_IFREG | 0o4755))
        self.assertEqual(mode, 0o4755)


class FileTypeTests(unittest.TestCase):
    def test_all_types(self):
        cases = {
            proto.S_IFREG: "file", proto.S_IFDIR: "directory", proto.S_IFLNK: "symlink",
            proto.S_IFSOCK: "socket", proto.S_IFIFO: "fifo",
            proto.S_IFBLK: "block", proto.S_IFCHR: "char",
        }
        for bits, expected in cases.items():
            self.assertEqual(proto.file_type_from_permissions(bits | 0o644), expected, expected)

    def test_missing_permissions_is_unknown(self):
        self.assertEqual(proto.file_type_from_permissions(None), "unknown")

    def test_unknown_bits(self):
        # 0o10000 恰好等于 S_IFIFO，所以「未知类型」得用一个真正没被占用的位型：
        # 0o120000 是链接、0o140000 是 socket，0o130000 空着。
        self.assertEqual(proto.file_type_from_permissions(0o10000), "fifo")
        self.assertEqual(proto.file_type_from_permissions(0o130000), "unknown")


class AttrsTests(unittest.TestCase):
    def test_mode_octal_keeps_special_bits(self):
        attrs = proto.Attrs(flags=proto.SSH_FILEXFER_ATTR_PERMISSIONS, permissions=proto.S_IFREG | 0o4755)
        self.assertEqual(attrs.mode_octal, "4755")
        self.assertEqual(attrs.type, "file")
        self.assertFalse(attrs.is_dir)
        self.assertFalse(attrs.is_link)

    def test_directory_flags(self):
        attrs = proto.Attrs(flags=0, permissions=proto.S_IFDIR | 0o755)
        self.assertTrue(attrs.is_dir)

    def test_missing_permissions_yields_no_mode(self):
        # 返回 None 而不是 "0000"：权限位缺失是「不知道」，而 "0000" 是一个具体的
        # 权限值（谁都读写执行不了），把未知渲染成它等于凭空断言。
        self.assertIsNone(proto.Attrs(flags=0).mode_octal)

    def test_to_dict_exposes_facts_not_prose(self):
        attrs = proto.Attrs(
            flags=0, size=10, uid=1000, gid=1000,
            permissions=proto.S_IFREG | 0o644, atime=1, mtime=2,
        )
        data = attrs.to_dict()
        self.assertEqual(data["size"], 10)
        self.assertEqual(data["type"], "file")
        self.assertNotIn("权限", str(data))


class ReaderTests(unittest.TestCase):
    def test_sequential_reads(self):
        reader = proto.Reader(proto.encode_uint32(7) + proto.encode_uint64(8) + b"\x09" + proto.encode_string("x"))
        self.assertEqual(reader.u32(), 7)
        self.assertEqual(reader.u64(), 8)
        self.assertEqual(reader.u8(), 9)
        self.assertEqual(reader.string(), "x")
        self.assertEqual(reader.remaining, 0)

    def test_short_read_raises_protocol_error_not_struct_error(self):
        with self.assertRaises(ProtocolError):
            proto.Reader(b"\x00\x00").u32()

    def test_raw_string_beyond_end(self):
        with self.assertRaises(ProtocolError):
            proto.Reader(proto.encode_uint32(5) + b"ab").raw_string()

    def test_invalid_utf8_is_an_error(self):
        # errors="replace" 会把可诊断的协议问题变成「文件名里莫名多了问号」的幽灵故障。
        reader = proto.Reader(proto.encode_uint32(2) + b"\xff\xfe")
        with self.assertRaises(ProtocolError):
            reader.string()

    def test_attrs_parses_present_fields_only(self):
        flags = proto.SSH_FILEXFER_ATTR_SIZE | proto.SSH_FILEXFER_ATTR_UIDGID | \
            proto.SSH_FILEXFER_ATTR_PERMISSIONS | proto.SSH_FILEXFER_ATTR_ACMODTIME
        body = attrs_body(flags, size=5, uid=7, gid=8, permissions=proto.S_IFREG | 0o600, atime=11, mtime=12)
        attrs = proto.Reader(body).attrs()
        self.assertEqual((attrs.size, attrs.uid, attrs.gid, attrs.atime, attrs.mtime), (5, 7, 8, 11, 12))
        self.assertEqual(attrs.permissions, proto.S_IFREG | 0o600)

    def test_attrs_skips_absent_fields(self):
        attrs = proto.Reader(attrs_body(0)).attrs()
        self.assertIsNone(attrs.size)
        self.assertIsNone(attrs.permissions)
        self.assertEqual(attrs.type, "unknown")

    def test_attrs_consumes_extended_pairs(self):
        body = proto.encode_uint32(proto.SSH_FILEXFER_ATTR_EXTENDED) + proto.encode_uint32(1) + \
            proto.encode_string("k") + proto.encode_string("v") + proto.encode_uint32(42)
        reader = proto.Reader(body)
        reader.attrs()
        self.assertEqual(reader.u32(), 42)  # 扩展字段必须被完整跳过

    def test_incomplete_attrs_raises(self):
        body = proto.encode_uint32(proto.SSH_FILEXFER_ATTR_SIZE) + proto.encode_uint32(1)
        with self.assertRaises(ProtocolError):
            proto.Reader(body).attrs()


class ParseResponseTests(unittest.TestCase):
    def test_status_carries_request_id(self):
        # 漏读这 4 个字节会让后面所有字段整体错位，而 struct 仍能「成功」解出
        # 一组看似合理的数字 —— 这类 bug 最难定位，所以这里显式钉死。
        response = proto.parse_response(frame(proto.SSH_FXP_STATUS, proto.encode_uint32(3) + proto.encode_uint32(0)))
        self.assertEqual(response.request_id, 3)
        self.assertEqual(response.type, proto.SSH_FXP_STATUS)
        # type_name 用短名：它只出现在 ProtocolError 的「期望 X 包，实际收到 Y。」里。
        self.assertEqual(response.type_name, "STATUS")

    def test_version_has_no_request_id(self):
        response = proto.parse_response(frame(proto.SSH_FXP_VERSION, proto.encode_uint32(3)))
        self.assertEqual(response.request_id, 0)
        self.assertEqual(response.body.u32(), 3)

    def test_missing_request_id_is_reported(self):
        with self.assertRaises(ProtocolError):
            proto.parse_response(frame(proto.SSH_FXP_STATUS, b"\x01"))

    def test_empty_frame(self):
        with self.assertRaises(ProtocolError):
            proto.parse_response(b"")

    def test_attrs_response(self):
        body = proto.encode_uint32(9) + attrs_body(proto.SSH_FILEXFER_ATTR_PERMISSIONS, permissions=proto.S_IFDIR | 0o755)
        response = proto.parse_response(frame(proto.SSH_FXP_ATTRS, body))
        self.assertEqual(response.request_id, 9)
        self.assertTrue(response.body.attrs().is_dir)


class NameFrameTests(unittest.TestCase):
    def build_name_frame(self, entries):
        body = proto.encode_uint32(len(entries))
        for filename, longname, permissions, size in entries:
            body += proto.encode_string(filename) + proto.encode_string(longname)
            body += attrs_body(
                proto.SSH_FILEXFER_ATTR_SIZE | proto.SSH_FILEXFER_ATTR_PERMISSIONS,
                size=size, permissions=permissions,
            )
        return proto.parse_response(frame(proto.SSH_FXP_NAME, proto.encode_uint32(1) + body))

    def test_iterates_entries(self):
        response = self.build_name_frame([
            ("a.txt", "-rw-r--r-- 1 u g 3 a.txt", proto.S_IFREG | 0o644, 3),
            ("dir", "drwxr-xr-x 2 u g 0 dir", proto.S_IFDIR | 0o755, 0),
        ])
        entries = list(proto.iter_name_entries(response))
        self.assertEqual([e.filename for e in entries], ["a.txt", "dir"])
        self.assertEqual(entries[0].attrs.size, 3)
        self.assertTrue(entries[1].attrs.is_dir)

    def test_unicode_filename(self):
        response = self.build_name_frame([("中文 空格😀.txt", "", proto.S_IFREG | 0o644, 0)])
        entries = list(proto.iter_name_entries(response))
        self.assertEqual(entries[0].filename, "中文 空格😀.txt")

    def test_wrong_frame_type(self):
        with self.assertRaises(ProtocolError):
            list(proto.iter_name_entries(proto.parse_response(frame(proto.SSH_FXP_STATUS, proto.encode_uint32(0) + proto.encode_uint32(0)))))


class StatusTests(unittest.TestCase):
    def test_parses_code_and_message(self):
        body = proto.encode_uint32(4) + proto.encode_uint32(proto.SSH_FX_NO_SUCH_FILE) + proto.encode_string("No such file")
        code, message = proto.parse_status(proto.parse_response(frame(proto.SSH_FXP_STATUS, body)))
        self.assertEqual(code, proto.SSH_FX_NO_SUCH_FILE)
        self.assertEqual(message, "No such file")

    def test_message_is_optional(self):
        body = proto.encode_uint32(5) + proto.encode_uint32(proto.SSH_FX_OK)
        code, message = proto.parse_status(proto.parse_response(frame(proto.SSH_FXP_STATUS, body)))
        self.assertEqual(code, proto.SSH_FX_OK)
        self.assertEqual(message, "")

    def test_wrong_frame_type(self):
        with self.assertRaises(ProtocolError):
            proto.parse_status(proto.parse_response(frame(proto.SSH_FXP_HANDLE, proto.encode_uint32(1) + proto.encode_string(b"h"))))

    def test_status_text(self):
        self.assertEqual(proto.status_text(proto.SSH_FX_PERMISSION_DENIED), "PERMISSION_DENIED")
        self.assertIn("99", proto.status_text(99))


class ConstantTests(unittest.TestCase):
    def test_request_types_are_unique(self):
        names = list(proto.SSH_FXP_NAMES)
        self.assertEqual(len(names), len(set(names)))

    def test_read_chunk_within_frame_limit(self):
        self.assertLessEqual(proto.MAX_READ_CHUNK, proto.MAX_FRAME_BYTES)

    def test_status_names_cover_every_declared_code(self):
        for code in range(10):
            self.assertIn(code, proto.STATUS_NAMES, code)


if __name__ == "__main__":
    unittest.main()
