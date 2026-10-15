"""内存版 SFTP 客户端：给真正读写字节的服务层做单测。

为什么不用「只记录调用」的假件：在线编辑要处理 BOM、换行与哈希，压缩解压要
真正走 tar/zip 的字节流。只回放调用的假件测不出这些逻辑，只能测「调了哪个
方法」。所以这里把整棵远端树放进内存，行为尽量贴近 app/ssh/sftp_client.py：

- stat 跟随符号链接，lstat 不跟随；listdir 的 attrs 是 lstat 语义。
- 权限位是真的：读没有读位的文件、列没有读位的目录、写只读文件都会失败。
- rename 不覆盖已存在的目标（SFTP v3 的语义，服务层依赖这一点）。
- offline 打开后所有调用抛 NotConnected，用来测断线中途保存。
"""

from contextlib import contextmanager

from app.core.errors import NotConnected, PathNotFound, PermissionDenied, ProtocolError, RemoteError
from app.ssh import sftp_protocol as proto

_FILE = proto.S_IFREG
_DIR = proto.S_IFDIR
_LINK = proto.S_IFLNK
_KIND_BITS = {"file": _FILE, "directory": _DIR, "symlink": _LINK}


class FakeNode:
    def __init__(self, path, kind, *, data=b"", target="", mode=None, mtime=1700000000):
        self.path = path
        self.kind = kind
        self.data = bytearray(data)
        self.target = target
        if mode is None:
            mode = 0o755 if kind == "directory" else (0o777 if kind == "symlink" else 0o644)
        self.mode = mode
        self.mtime = mtime

    def attrs(self):
        flags = (
            proto.SSH_FILEXFER_ATTR_SIZE
            | proto.SSH_FILEXFER_ATTR_PERMISSIONS
            | proto.SSH_FILEXFER_ATTR_ACMODTIME
        )
        return proto.Attrs(
            flags=flags,
            size=len(self.data),
            permissions=_KIND_BITS[self.kind] | self.mode,
            atime=self.mtime,
            mtime=self.mtime,
        )


class FakeHandle:
    def __init__(self, node, writable):
        self.node = node
        self.writable = writable
        self.closed = False


def normalize(path):
    """把路径折成规范形式（只做词法处理，不解析符号链接）。"""
    parts = []
    for piece in str(path).split("/"):
        if piece in ("", "."):
            continue
        if piece == "..":
            if parts:
                parts.pop()
            continue
        parts.append(piece)
    return "/" + "/".join(parts)


class FakeSFTPClient:
    def __init__(self, *, home="/home/aimu"):
        self.nodes = {}
        self.log = []
        self.offline = False
        self.home = normalize(home)
        self._mkdir("/", 0o755)
        self._mkdir("/home", 0o755)
        self._mkdir(self.home, 0o755)
        self._mkdir("/tmp", 0o1777)

    # ------------------------------------------------------------ 测试用摆树

    def add_dir(self, path, mode=0o755):
        return self._mkdir(normalize(path), mode)

    def add_file(self, path, data=b"", *, mode=0o644, mtime=1700000000):
        if isinstance(data, str):
            data = data.encode("utf-8")
        target = normalize(path)
        self._require_parent(target)
        node = FakeNode(target, "file", data=data, mode=mode, mtime=mtime)
        self.nodes[target] = node
        return node

    def add_link(self, path, target, *, mode=0o777):
        link = normalize(path)
        self._require_parent(link)
        node = FakeNode(link, "symlink", target=target, mode=mode)
        self.nodes[link] = node
        return node

    def read(self, path):
        return bytes(self._node(normalize(path)).data)

    def text(self, path):
        return self.read(path).decode("utf-8")

    def exists(self, path):
        return normalize(path) in self.nodes

    def names(self):
        return sorted(self.nodes)

    # ------------------------------------------------------------ 内部

    def _mkdir(self, path, mode):
        if path != "/":
            self._require_parent(path)
        node = FakeNode(path, "directory", mode=mode)
        self.nodes[path] = node
        return node

    def _require_parent(self, path):
        parent = path.rsplit("/", 1)[0] or "/"
        node = self.nodes.get(parent)
        if node is None or node.kind != "directory":
            raise PathNotFound("远端路径不存在：" + path)

    def _guard(self):
        if self.offline:
            raise NotConnected("SSH 会话已断开。")

    def _node(self, path):
        node = self.nodes.get(path)
        if node is None:
            raise PathNotFound("远端路径不存在：" + path)
        return node

    def _resolve(self, path, *, depth=0):
        """整条路径逐段解析符号链接，和真实客户端依赖 REALPATH 的做法一致。"""
        if depth > 10:
            raise RemoteError("符号链接形成了环。")
        current = normalize(path)
        if current == "/":
            return "/"
        parts = current.strip("/").split("/")
        walked = ""
        for index, piece in enumerate(parts):
            walked = walked + "/" + piece
            node = self.nodes.get(walked)
            if node is None:
                return current
            if node.kind == "symlink":
                rest = parts[index + 1 :]
                target = node.target if node.target.startswith("/") else walked.rsplit("/", 1)[0] + "/" + node.target
                joined = normalize(target) + ("/" + "/".join(rest) if rest else "")
                return self._resolve(joined, depth=depth + 1)
        return current

    # ------------------------------------------------------------ 客户端协议

    def realpath(self, path):
        self._guard()
        self.log.append(("realpath", normalize(path)))
        return self._resolve(path)

    def stat(self, path):
        self._guard()
        resolved = self._resolve(path)
        self.log.append(("stat", resolved))
        node = self._node(resolved)
        if node.kind == "directory" and not node.mode & 0o400:
            raise PermissionDenied("没有权限读取：" + resolved)
        return node.attrs()

    def lstat(self, path):
        self._guard()
        target = normalize(path)
        self.log.append(("lstat", target))
        return self._node(target).attrs()

    def readlink(self, path):
        self._guard()
        target = normalize(path)
        node = self._node(target)
        if node.kind != "symlink":
            raise RemoteError("不是符号链接：" + target)
        return node.target

    def listdir(self, path):
        self._guard()
        resolved = self._resolve(path)
        self.log.append(("listdir", resolved))
        node = self._node(resolved)
        if node.kind != "directory":
            raise PathNotFound("不是目录：" + resolved)
        if not node.mode & 0o400:
            raise PermissionDenied("没有权限列出目录：" + resolved)
        prefix = "" if resolved == "/" else resolved + "/"
        entries = []
        for name in sorted(self.nodes):
            if not name.startswith(prefix) or name == resolved:
                continue
            rest = name[len(prefix) :]
            if "/" in rest or not rest:
                continue
            child = self.nodes[name]
            entries.append(proto.NameEntry(filename=rest, longname=rest, attrs=child.attrs()))
        return entries

    def open(self, path, pflags, mode=0o644):
        self._guard()
        resolved = self._resolve(path)
        self.log.append(("open", resolved, pflags))
        writing = bool(pflags & proto.SSH_FXF_WRITE)
        node = self.nodes.get(resolved)
        if node is None:
            if not (writing and pflags & proto.SSH_FXF_CREAT):
                raise PathNotFound("远端路径不存在：" + resolved)
            self._require_parent(resolved)
            node = self.nodes[resolved] = FakeNode(resolved, "file", mode=mode & 0o777)
        if node.kind == "directory":
            raise RemoteError("不能把目录当文件打开：" + resolved)
        if writing:
            if not node.mode & 0o200:
                raise PermissionDenied("这个文件没有写权限：" + resolved)
            if pflags & proto.SSH_FXF_TRUNC:
                node.data = bytearray()
        else:
            if not node.mode & 0o400:
                raise PermissionDenied("没有权限读取：" + resolved)
        return FakeHandle(node, writing)

    def close(self, handle):
        if isinstance(handle, FakeHandle):
            handle.closed = True

    @contextmanager
    def open_read(self, path):
        handle = self.open(path, proto.SSH_FXF_READ)
        try:
            yield handle
        finally:
            self.close(handle)

    @contextmanager
    def open_write(self, path, *, mode=0o644):
        handle = self.open(
            path, proto.SSH_FXF_WRITE | proto.SSH_FXF_CREAT | proto.SSH_FXF_TRUNC, mode
        )
        try:
            yield handle
        finally:
            self.close(handle)

    def read_chunk(self, handle, offset, length):
        self._guard()
        if not isinstance(handle, FakeHandle) or handle.closed:
            raise RemoteError("句柄已经关闭。")
        self.log.append(("read", handle.node.path, offset, length))
        data = bytes(handle.node.data)
        if offset >= len(data):
            return b""
        return data[offset : offset + length]

    def write_chunk(self, handle, offset, data):
        self._guard()
        if not isinstance(handle, FakeHandle) or handle.closed:
            raise RemoteError("句柄已经关闭。")
        if not handle.writable:
            raise RemoteError("这个句柄不是用来写的。")
        self.log.append(("write", handle.node.path, offset, len(data)))
        node = handle.node
        payload = bytes(data)
        if offset > len(node.data):
            node.data.extend(b"\x00" * (offset - len(node.data)))
        node.data[offset : offset + len(payload)] = payload
        return len(payload)

    def upload_stream(self, path, chunks, *, expected_size=None, mode=0o644):
        self._guard()
        resolved = self._resolve(path)
        self.log.append(("upload", resolved))
        node = self.nodes.get(resolved)
        if node is None:
            self._require_parent(resolved)
            node = self.nodes[resolved] = FakeNode(resolved, "file", mode=mode & 0o777)
        if node.kind != "file":
            raise RemoteError("目标不是普通文件：" + resolved)
        if not node.mode & 0o200:
            raise PermissionDenied("这个文件没有写权限：" + resolved)
        written = 0
        node.data = bytearray()
        for chunk in chunks:
            if not chunk:
                continue
            node.data.extend(chunk)
            written += len(chunk)
        if expected_size is not None and written != expected_size:
            raise ProtocolError("上传的字节数与预期不一致：%d != %d" % (written, expected_size))
        node.mtime = node.mtime + 1
        return written

    def mkdir(self, path, mode=0o755):
        self._guard()
        resolved = normalize(path)
        if resolved in self.nodes:
            raise RemoteError("路径已经存在：" + resolved)
        parent = self._resolve(resolved.rsplit("/", 1)[0] or "/")
        parent_node = self._node(parent)
        if parent_node.kind != "directory":
            raise RemoteError("父路径不是目录：" + parent)
        if not parent_node.mode & 0o200:
            raise PermissionDenied("父目录没有写权限：" + parent)
        return self._mkdir(resolved, mode)

    def rmdir(self, path):
        # 不解析最后一段：POSIX rmdir 作用于条目本身，对符号链接要报「不是目录」。
        self._guard()
        resolved = normalize(path)
        node = self._node(resolved)
        if node.kind != "directory":
            raise RemoteError("不是目录：" + resolved)
        for name in self.nodes:
            if name != resolved and name.startswith(resolved + "/"):
                raise RemoteError("目录不是空的：" + resolved)
        del self.nodes[resolved]

    def remove(self, path):
        # 不解析最后一段：POSIX unlink 删的是链接本身，不碰它指向的文件。
        self._guard()
        resolved = normalize(path)
        node = self._node(resolved)
        if node.kind == "directory":
            raise RemoteError("remove 不能删目录：" + resolved)
        del self.nodes[resolved]

    def rename(self, old, new):
        self._guard()
        source = normalize(old)
        target = normalize(new)
        self.log.append(("rename", source, target))
        node = self._node(source)
        if target in self.nodes:
            raise RemoteError("目标已经存在：" + target)
        self._require_parent(target)
        if node.kind == "directory":
            for name in sorted(self.nodes):
                if name == source or name.startswith(source + "/"):
                    moved = target + name[len(source) :]
                    self.nodes[moved] = self.nodes.pop(name)
                    self.nodes[moved].path = moved
            return
        del self.nodes[source]
        node.path = target
        self.nodes[target] = node
