"""远端文本文件的读取与保存（阶段四）。

## 为什么单独一个模块

filesystem.py 只管「看」：列目录、取属性、读一段预览。这里管「改」，而「改」必须
回答一个浏览路径不需要回答的问题 —— 我读到的那份内容，还是不是现在远端的那份？
保存还要处理编码、换行、BOM 三件事，混进浏览模块会让那个模块一半只读、一半可写，
两种纪律互相打架。

## 三件必须显式处理的事（任务书阶段四「数据安全」）

1. 编码：只接受 UTF-8（可选带 BOM）。其它编码不猜 —— 猜错一次就是整份文件在
   用户下次打开时变成乱码，而用户往往几天后才发现。解不出来就报错，并说明是
   第几字节出的问题，让用户用别的工具处理。
2. 换行符：读的时候统一折叠成 LF 交给浏览器（textarea 只认 LF），同时记住原来的
   风格（lf / crlf / cr）与「末尾有没有换行」，保存时原样还原。混合换行的文件会被
   标出来，界面必须提示「保存后会统一」，而不是悄悄改掉。
3. 冲突：请求里带上读到的 sha256 与 mtime，保存前比对当前值。不一致就拒绝
   （409 edit_conflict），由用户决定放弃还是重新加载 —— 不默认覆盖别人刚写的内容。

## 保存为什么要「改名两次」

远端没有原子替换（SFTP v3 的 RENAME 不覆盖已存在目标，这份协议也没有实现
posix-rename 扩展），所以顺序是：写临时名 → 把原文件改成备份名 → 临时名改成
正式名 → 删备份。中途任何一步失败都会把手上的残留清掉，并把原文件改回去。
代价是极端情况下可能留下一个 .awfm-bak- 备份文件（日志里有记录），
换来的是「不会出现一个半截的正式文件」。
"""

from __future__ import annotations

import hashlib
import logging
import uuid

from app.core.errors import (
    AwfmError,
    EditConflict,
    PayloadTooLarge,
    PermissionDenied,
    RemoteError,
    ValidationError,
)
from app.core.errors import PathNotFound
from app.services.filesystem import require_write_permission, resolve_path
from app.services.session import RemoteSession
from app.services.transfer import PART_SUFFIX
from app.ssh.sftp_client import DEFAULT_CHUNK_SIZE
from app.utils.paths import validate_remote_path

logger = logging.getLogger(__name__)

#: 在线编辑默认允许的最大文件字节数。配置文件里的 security.max_edit_bytes 覆盖它。
DEFAULT_MAX_EDIT_BYTES = 2 * 1024 * 1024

#: 保存时给原文件留的备份名后缀。带随机后缀，不会与用户的文件重名。
BACKUP_SUFFIX = ".awfm-bak-"

#: UTF-8 BOM。带 BOM 的文件在 Windows 上很常见（记事本另存为 UTF-8 就是它）。
_BOM = b"\xef\xbb\xbf"

#: 二进制嗅探窗口：真正的二进制文件在前几百字节就会露馅。
_SNIFF_BYTES = 8 * 1024

#: 允许的换行风格。
_NEWLINE_STYLES = ("lf", "crlf", "cr")

#: 文本里允许出现的控制字符（制表符与换行）。
_TEXT_CONTROLS = (0x09, 0x0A, 0x0D)


def _name_of(path: str) -> str:
    return path.rstrip("/").rpartition("/")[2] or "/"


def _looks_binary(raw: bytes) -> bool:
    """按「有没有 NUL」加「控制字符比例」判断是不是二进制。

    只嗅探开头若干字节：可执行文件、图片、压缩包都会在前几百字节里出现 NUL
    或成片的控制字符，而中文、制表符、换行都不该被误判。
    """
    sample = raw[:_SNIFF_BYTES]
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    control = sum(1 for byte in sample if byte < 0x20 and byte not in _TEXT_CONTROLS)
    return control * 100 > len(sample) * 3


def _detect_newline(raw: bytes) -> tuple[str, bool]:
    """返回（风格, 是否混合）。风格取值 lf / crlf / cr / none。"""
    crlf = raw.count(b"\r\n")
    cr = raw.count(b"\r") - crlf
    lf = raw.count(b"\n") - crlf
    counts = {"crlf": crlf, "cr": cr, "lf": lf}
    present = [style for style, value in counts.items() if value > 0]
    if not present:
        return "none", False
    # 数量相同时偏向 LF：Linux 上的文本文件绝大多数是 LF，而「恰好相等」的混合文件
    # 本来就少见，这时选 LF 至少与肉眼看到的一致。
    style = max(counts, key=lambda item: (counts[item], item == "lf"))
    return style, len(present) > 1


def _read_all(client, path: str, limit: int) -> bytes:
    """把整个文件读进内存，超过 limit 立刻停下。

    只用于文本编辑：上限默认 2 MiB（security.max_edit_bytes），
    不是一个「顺手读整份文件」的通用工具 —— 下载与预览各有自己的流式路径。
    """
    out = bytearray()
    with client.open_read(path) as handle:
        offset = 0
        while True:
            chunk = client.read_chunk(handle, offset, DEFAULT_CHUNK_SIZE)
            if not chunk:
                break
            offset += len(chunk)
            out += chunk
            if len(out) > limit:
                raise PayloadTooLarge(
                    "文件超过了在线编辑的大小上限。",
                    detail=f"读取超过 {limit} 字节：{path}",
                    extra={"path": path, "limit": limit},
                )
    return bytes(out)


def _peek(client, path: str, limit: int) -> bytes:
    """只读开头一小段，用来判断换行风格。

    与 `_read_all` 的区别：**不因为文件更大而报错** —— 判断换行只需要头部的一两百字节，
    一个 10 MiB 的文件不该因为这个判断被拒绝。
    """
    out = bytearray()
    with client.open_read(path) as handle:
        offset = 0
        while len(out) < limit:
            chunk = client.read_chunk(handle, offset, min(DEFAULT_CHUNK_SIZE, limit - len(out)))
            if not chunk:
                break
            offset += len(chunk)
            out += chunk
    return bytes(out)


def read_text_file(
    session: RemoteSession,
    raw_path: str,
    *,
    max_bytes: int = DEFAULT_MAX_EDIT_BYTES,
) -> dict:
    """读一个远端文本文件，返回编辑器需要的一切。

    Returns:
        含 path / name / size / mtime / sha256 / text / encoding / bom /
        newline / mixed_newlines / final_newline / limit 的字典。
        text 里的换行一律是 LF。
    """
    canonical = resolve_path(session, raw_path)
    client = session.client
    attrs = client.stat(canonical)
    if attrs.is_dir:
        raise ValidationError("目录不能作为文本编辑。", detail=canonical)
    if attrs.type != "file":
        raise ValidationError(
            "只有普通文件可以在线编辑。",
            detail=f"{canonical} 的类型是 {attrs.type}。符号链接会按它指向的文件处理。",
        )
    size = attrs.size or 0
    if size > max_bytes:
        raise PayloadTooLarge(
            "这个文件超过了在线编辑的大小上限。",
            detail=f"文件 {size} 字节，上限 {max_bytes} 字节（security.max_edit_bytes）。",
            extra={"path": canonical, "size": size, "limit": max_bytes},
        )

    data = _read_all(client, canonical, max_bytes)
    if _looks_binary(data):
        raise ValidationError(
            "这个文件看起来不是文本文件，不能在线编辑。",
            detail="内容里有 NUL 字节或成片的控制字符。请下载后用专门的工具处理。",
            extra={"path": canonical, "size": len(data)},
        )

    bom = data.startswith(_BOM)
    body = data[len(_BOM):] if bom else data
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(
            "这个文件的编码不是 UTF-8，无法安全地在线上编辑。",
            detail=(
                f"在偏移 {exc.start} 处解码失败（{exc.reason}）。"
                "为了避免保存时把整份文件写坏，编辑器只接受 UTF-8 文本。"
            ),
            extra={"path": canonical, "offset": exc.start},
        ) from exc

    newline, mixed = _detect_newline(body)
    return {
        "path": canonical,
        "name": _name_of(canonical),
        "size": len(data),
        "mtime": attrs.mtime,
        "mode": attrs.mode_octal,
        "sha256": hashlib.sha256(data).hexdigest(),
        "text": text.replace("\r\n", "\n").replace("\r", "\n"),
        "encoding": "utf-8",
        "bom": bom,
        "newline": newline,
        "mixed_newlines": mixed,
        "final_newline": body.endswith(b"\n") or body.endswith(b"\r"),
        "limit": max_bytes,
    }


def _encode_text(text: str, *, newline: str, keep_bom: bool) -> bytes:
    """把编辑器交回来的文本编码成要写出去的字节。

    textarea 只会给出 LF，所以先把两种 CR 折成 LF 再统一替换 ——
    否则一个「原文是 CRLF」的文件保存两次就会变成 CRCRLF。
    """
    if not isinstance(text, str):
        raise ValidationError("text 必须是字符串。")
    style = newline if newline in _NEWLINE_STYLES else "lf"
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    if style == "crlf":
        body = body.replace("\n", "\r\n")
    elif style == "cr":
        body = body.replace("\n", "\r")
    try:
        data = body.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValidationError(
            "内容里有无法用 UTF-8 表示的字符，保存会破坏文件，已放弃。",
            detail=f"位置 {exc.start}：{exc.reason}。",
        ) from exc
    return (_BOM + data) if keep_bom else data


def save_text_file(
    session: RemoteSession,
    raw_path: str,
    text: str,
    *,
    base_sha256: str = "",
    base_mtime: int | None = None,
    newline: str = "",
    keep_bom: bool = False,
    max_bytes: int = DEFAULT_MAX_EDIT_BYTES,
) -> dict:
    """把编辑器里的内容写回远端文件，写之前先确认它没被别人改过。

    Args:
        base_sha256: 读取时拿到的内容哈希。带上它就能发现「内容变了」。
        base_mtime: 读取时拿到的修改时间。没有哈希时退而求其次用时间戳。
        newline: 保存时使用的换行风格（lf / crlf / cr）。留空表示**沿用文件当前的风格** ——
            把 CRLF 文件悄悄改成 LF 属于「保存成功了但内容变了」，比报错更难发现。
        keep_bom: 是否在文件开头写回 UTF-8 BOM。

    Raises:
        EditConflict: 远端内容与读取时不一致。
        PermissionDenied: 连接未开写权限，或文件本身没有写位。
    """
    require_write_permission(session, "保存文件")
    if not isinstance(text, str):
        raise ValidationError("text 必须是字符串。")
    if not base_sha256 and base_mtime is None:
        raise ValidationError(
            "保存时必须带上 base_sha256 或 base_mtime。",
            detail="界面在打开编辑器时拿到这两个值并在保存时回传；没有它们，服务端无法判断文件是否被改过。",
        )
    canonical = resolve_path(session, raw_path)
    client = session.client
    try:
        attrs = client.stat(canonical)
    except PathNotFound:
        raise PathNotFound(
            "文件已不存在，无法保存。",
            detail=f"{canonical}。它可能在编辑期间被删除或改名。可以把内容另存为新文件。",
        ) from None
    if attrs.is_dir:
        raise ValidationError("目标是一个目录，无法保存文件。", detail=canonical)
    if attrs.permissions is not None and not (attrs.permissions & 0o222):
        raise PermissionDenied(
            "这个文件没有写权限，无法保存。",
            detail=f"{canonical} 的权限是 {attrs.mode_octal}。请先在远端调整权限。",
            extra={"path": canonical, "mode": attrs.mode_octal},
        )

    current: bytes | None = None
    if base_sha256:
        try:
            current = _read_all(client, canonical, max_bytes)
        except PayloadTooLarge:
            raise EditConflict(
                "文件在你编辑期间变大，已超过在线编辑上限，保存被拒绝。",
                detail=f"{canonical}。请重新打开编辑器确认内容。",
                extra={"path": canonical, "reason": "size"},
            ) from None
        current_sha = hashlib.sha256(current).hexdigest()
        if current_sha != base_sha256:
            raise EditConflict(
                "文件在你编辑期间被改动过，保存被拒绝。",
                detail=(
                    "远端内容的哈希与打开编辑器时不一致，可能有人（或另一个程序）改了它。"
                    "请重新加载后再决定要不要保存你的修改。"
                ),
                extra={"path": canonical, "reason": "content", "mtime": attrs.mtime},
            )
    elif base_mtime is not None and attrs.mtime != base_mtime:
        raise EditConflict(
            "文件在你编辑期间被改动过，保存被拒绝。",
            detail=f"远端修改时间 {attrs.mtime} 与打开编辑器时的 {base_mtime} 不一致。",
            extra={"path": canonical, "reason": "mtime", "mtime": attrs.mtime},
        )

    if newline in _NEWLINE_STYLES:
        style = newline
    elif current is not None:
        style = _detect_newline(current)[0] or "lf"
    else:
        # 没读全文（只给了 base_mtime）时也得知道原来是哪种换行，抽头部一小段足够。
        style = _detect_newline(_peek(client, canonical, _SNIFF_BYTES))[0] or "lf"

    data = _encode_text(text, newline=style, keep_bom=keep_bom)
    if len(data) > max_bytes:
        raise PayloadTooLarge(
            "保存后的内容超过了在线编辑的大小上限。",
            detail=f"编码后 {len(data)} 字节，上限 {max_bytes} 字节。",
            extra={"path": canonical, "size": len(data), "limit": max_bytes},
        )

    mode = (attrs.permissions or 0o644) & 0o777
    temp = canonical + PART_SUFFIX + uuid.uuid4().hex[:8]
    backup = canonical + BACKUP_SUFFIX + uuid.uuid4().hex[:8]
    written = 0
    backup_pending = False
    try:
        written = client.upload_stream(temp, [data], expected_size=len(data), mode=mode)
        try:
            client.rename(canonical, backup)
        except AwfmError as exc:
            raise RemoteError(
                "保存失败：无法给原文件改名备份，已放弃这次保存（远端文件没有被改动）。",
                detail=f"{canonical} 改成 {backup} 失败：{exc.message}",
                extra={"path": canonical},
            ) from exc
        backup_pending = True
        try:
            client.rename(temp, canonical)
            temp = ""
        except AwfmError as exc:
            # 替换失败：先把备份改回原名，尽量让远端回到保存前的状态。
            try:
                client.rename(backup, canonical)
                backup_pending = False
            except AwfmError as rollback:
                logger.error(
                    "保存失败后回滚也没成功：原内容仍在 %s（%s）", backup, rollback.message
                )
            raise RemoteError(
                "保存失败：新内容没能替换原文件（已尝试回滚）。",
                detail=f"{temp} 改成 {canonical} 失败：{exc.message}",
                extra={"path": canonical},
            ) from exc
    finally:
        if temp:
            try:
                client.remove(temp)
            except Exception:
                logger.warning("清理未完成的保存临时文件失败：%s", temp)

    if backup_pending:
        try:
            client.remove(backup)
        except Exception:
            logger.warning("未能删除保存备份 %s；它带 %s 后缀，可以手工清理。", backup, BACKUP_SUFFIX)

    updated = client.stat(canonical)
    logger.info("保存文本文件 %s（%d 字节）", canonical, written)
    return {
        "path": canonical,
        "name": _name_of(canonical),
        "size": updated.size if updated.size is not None else written,
        "mtime": updated.mtime,
        "mode": updated.mode_octal,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes_written": written,
        "encoding": "utf-8",
        "bom": bool(keep_bom),
        "newline": style,
        "saved": True,
    }


def describe_limits(max_bytes: int) -> dict:
    """给界面用的编辑能力说明（不需要连接）。"""
    return {"max_edit_bytes": max_bytes, "encodings": ["utf-8"], "newlines": list(_NEWLINE_STYLES)}


__all__ = [
    "BACKUP_SUFFIX",
    "DEFAULT_MAX_EDIT_BYTES",
    "describe_limits",
    "read_text_file",
    "save_text_file",
]
