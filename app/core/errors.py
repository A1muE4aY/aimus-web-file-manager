"""AWFM 错误模型。

设计目标（规划文档 §4.2 要求「固定错误码」）：

1. **每个错误都有稳定的字符串 code**，前端按 code 分支，不解析 message。
   message 是给人看的，code 是给程序看的 —— 两者分离后，文案可以改而契约不变。
2. **每个错误都携带 HTTP 状态码**，由错误类型自身决定，而不是在 API 层写
   `if isinstance(...)` 链。新增错误类型时不需要改路由代码。
3. **对外消息不得泄漏内部细节**：SFTP 的原始 `STATUS` 数值与英文串放在
   `detail` 字段，`message` 用中文写清楚发生了什么。

错误码表（API 契约的一部分，变更需同步 docs/API.md）：

    invalid_request        400  请求参数不合法（路径、主机名、端口、JSON 结构）
    payload_too_large      413  请求体超过 max_upload_bytes
    unauthorized           401  会话令牌缺失或失效
    connection_not_found   404  配置里没有这个连接 id
    session_not_found      404  该连接当前没有活动会话（未连接）
    path_not_found         404  远程路径不存在（SFTP STATUS 2）
    permission_denied      403  远程拒绝访问（SFTP STATUS 3）
    auth_failed            401  SSH 认证失败
    host_key_unknown       409  首次连接，主机密钥未经用户确认（T-005）
    host_key_mismatch      409  主机密钥与已信任记录不符（T-005，必须人工介入）
    not_connected          409  会话存在但底层通道已断开
    remote_error           502  远端返回了其他错误（SFTP STATUS 4/其他）
    protocol_error         502  SFTP 协议层异常（帧格式错误、通道提前关闭）
    timeout                504  操作超时
    config_error           500  配置文件损坏或不可读
    internal_error         500  未预期的内部异常
"""

from __future__ import annotations

from typing import Any


class AwfmError(Exception):
    """所有 AWFM 错误的基类。

    子类通过类属性覆盖 `code` / `http_status`；实例只携带数据。
    """

    code: str = "internal_error"
    http_status: int = 500

    def __init__(
        self,
        message: str,
        *,
        detail: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        # detail 面向排查：可以含远端原始错误串。不得含凭据。
        self.detail = detail
        self.extra = extra or {}

    def to_dict(self) -> dict[str, Any]:
        # extra 先合并、核心字段后覆盖：extra 常来自底层异常或远端返回，
        # 若允许它盖掉 code/message，一个构造失误就能让前端收到伪造的错误码。
        error: dict[str, Any] = dict(self.extra) if self.extra else {}
        error["code"] = self.code
        error["message"] = self.message
        if self.detail:
            error["detail"] = self.detail
        else:
            error.pop("detail", None)
        return {"ok": False, "error": error}

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"{type(self).__name__}(code={self.code!r}, message={self.message!r})"


# --------------------------------------------------------------------------
# 请求与配置
# --------------------------------------------------------------------------

class ValidationError(AwfmError):
    """请求参数不合法。由输入校验层抛出，绝不携带用户输入的原样回显以外的信息。"""

    code = "invalid_request"
    http_status = 400


class PayloadTooLarge(AwfmError):
    """请求体超过配置上限。对应验收项 N-07（传输限额）。"""

    code = "payload_too_large"
    http_status = 413


class ConfigError(AwfmError):
    """配置文件损坏或不可读。

    决策 D-006：**绝不静默重置** —— 损坏必须显式报错，否则会丢失用户配置。
    """

    code = "config_error"
    http_status = 500


class Unauthorized(AwfmError):
    """会话令牌缺失或失效。"""

    code = "unauthorized"
    http_status = 401


# --------------------------------------------------------------------------
# 连接与会话
# --------------------------------------------------------------------------

class ConnectionNotFound(AwfmError):
    code = "connection_not_found"
    http_status = 404


class SessionNotConnected(AwfmError):
    """会话不存在或尚未建立。"""

    code = "session_not_found"
    http_status = 404


class NotConnected(AwfmError):
    """会话存在但底层 SFTP 通道已断开（网络中断、远端重启等）。"""

    code = "not_connected"
    http_status = 409


class AuthFailed(AwfmError):
    """SSH 认证失败：用户名/密钥/密码不被接受。"""

    code = "auth_failed"
    http_status = 401


class HostKeyUnknown(AwfmError):
    """首次连接某主机，其主机密钥尚未被用户确认。

    验收项 T-005 明确禁止静默接受。本错误携带候选指纹供用户确认，
    `extra` 中的 `fingerprints` 是**公钥指纹**，不是敏感信息。
    """

    code = "host_key_unknown"
    http_status = 409


class HostKeyMismatch(AwfmError):
    """主机密钥与已信任的值不一致 —— 可能是中间人攻击，也可能是目标机重装。

    无论哪种情况都必须由人判断，程序不得自动覆盖（规划文档 §10.1）。
    """

    code = "host_key_mismatch"
    http_status = 409


# --------------------------------------------------------------------------
# 远程文件系统
# --------------------------------------------------------------------------

class PathNotFound(AwfmError):
    """远程路径不存在（SFTP STATUS code=2）。"""

    code = "path_not_found"
    http_status = 404


class PermissionDenied(AwfmError):
    """远程拒绝访问（SFTP STATUS code=3）。"""

    code = "permission_denied"
    http_status = 403


class RemoteError(AwfmError):
    """远端返回了其他错误（SFTP STATUS code=4 或未映射的码）。"""

    code = "remote_error"
    http_status = 502


class ProtocolError(AwfmError):
    """SFTP 协议层异常：帧不合法、序列错位、通道在请求未完成时关闭。"""

    code = "protocol_error"
    http_status = 502


class OperationTimeout(AwfmError):
    code = "timeout"
    http_status = 504


class InternalError(AwfmError):
    code = "internal_error"
    http_status = 500
