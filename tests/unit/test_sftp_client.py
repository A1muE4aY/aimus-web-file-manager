"""写入分块：一次 WRITE 帧必须留在服务端能接受的长度以内（v0.1.2 缺陷 D1 的第二层）。

在线编辑保存 1.9 MiB 文件时，`upload_stream` 把整份内容当成**一个** WRITE 帧发出去；
OpenSSH 的 sftp-server 判定这个包太长（> 256 KiB）就直接结束连接，客户端只看到
`NotConnected`：写入远端失败：连接已断开 —— 现象是「文件能打开，保存却总说网络断了」。
实测边界：261120 字节正常，262144 字节断。
"""

import struct
import unittest

from app.ssh import sftp_protocol as proto
from app.ssh.sftp_client import SftpClient


def decode_write(payload):
    """把 WRITE 的负载拆回 (handle, offset, data)。"""
    (handle_length,) = struct.unpack(">I", payload[:4])
    handle = payload[4 : 4 + handle_length]
    position = 4 + handle_length
    (offset,) = struct.unpack(">Q", payload[position : position + 8])
    position += 8
    (data_length,) = struct.unpack(">I", payload[position : position + 4])
    data = payload[position + 4 : position + 4 + data_length]
    return handle, offset, data


def packet_length(payload) -> int:
    """服务端看到的整包长度：长度字段 + 类型 + request-id + 负载。"""
    return 4 + 1 + 4 + len(payload)


class RecordingTransport:
    """只记录请求的传输层替身。"""

    def __init__(self):
        self.requests = []

    def transact(self, frame_type, payload, *, expect, context, accept_status=(), timeout=None):
        self.requests.append((frame_type, payload, context))
        return None

    def writes(self):
        return [decode_write(payload) for frame_type, payload, _ in self.requests if frame_type == proto.SSH_FXP_WRITE]


class WriteChunkTests(unittest.TestCase):
    def setUp(self):
        self.transport = RecordingTransport()
        self.client = SftpClient(self.transport)

    def test_small_write_stays_in_one_frame(self):
        self.client.write_chunk(b"h", 7, b"x" * 1000)
        self.assertEqual(self.transport.writes(), [(b"h", 7, b"x" * 1000)])

    def test_empty_write_sends_no_frame(self):
        self.client.write_chunk(b"h", 0, b"")
        self.assertEqual(self.transport.requests, [])

    def test_large_write_is_split_into_bounded_frames(self):
        size = proto.MAX_WRITE_CHUNK * 3 + 5
        data = bytes(range(256)) * (size // 256) + b"\x00" * (size % 256)
        self.assertEqual(len(data), size)

        self.client.write_chunk(b"handle", 10, data)

        frames = self.transport.writes()
        self.assertEqual(len(frames), 4)
        self.assertEqual([offset for _, offset, _ in frames], [10, 10 + proto.MAX_WRITE_CHUNK, 10 + 2 * proto.MAX_WRITE_CHUNK, 10 + 3 * proto.MAX_WRITE_CHUNK])
        self.assertEqual(b"".join(piece for _, _, piece in frames), data)
        for frame_type, payload, _ in self.transport.requests:
            self.assertLessEqual(packet_length(payload), proto.OPENSSH_MAX_PACKET_BYTES)

    def test_each_frame_stays_under_the_server_limit(self):
        # 块大小 + 帧头（长度字段、类型、request-id、handle、偏移、数据长度）。
        overhead = 4 + 1 + 4 + 4 + 8 + 4 + len(b"0123456789abcdef")
        self.assertLessEqual(proto.MAX_WRITE_CHUNK + overhead, proto.OPENSSH_MAX_PACKET_BYTES)
        self.assertLess(proto.MAX_WRITE_CHUNK, proto.MAX_FRAME_BYTES)

    def test_a_write_of_the_observed_failure_size_survives(self):
        # 262144 字节曾经把连接写死，现在被拆成 4 帧。
        self.client.write_chunk(b"h", 0, b"z" * 262144)
        frames = self.transport.writes()
        self.assertEqual(sum(len(piece) for _, _, piece in frames), 262144)
        self.assertTrue(all(packet_length(payload) <= proto.OPENSSH_MAX_PACKET_BYTES for _, payload, _ in self.transport.requests))


if __name__ == "__main__":
    unittest.main()