"""敏感信息脱敏。

规划文档 §10.6 要求日志不记录密码、私钥、令牌与完整敏感配置。

做法是**在日志格式化阶段统一过一道正则**，而不是要求每个调用点自己小心。
理由：调用点会漏 —— 一条 `logger.debug("ssh 命令：%s", cmd)` 就足以把
`-o ProxyCommand=...` 之类的串漏出去，而漏掉的日志没人会回头检查。
统一入口至少保证「即使调用点疏忽，也不会原样落盘」。
"""

from __future__ import annotations

import re

PLACEHOLDER = "***已脱敏***"

#: 参数键名里出现这些词时，对应参数值整体替换（用于 `%(password)s` 风格的记录）。
#: 这是唯一能救回这类记录的地方：格式化之后键名就消失了，
#: 而 `redact()` 对孤零零的值 `"hunter2"` 无从判断它是不是密码。
_SENSITIVE_KEY_RE = re.compile(r"(?i)pass(word|wd|phrase)?|token|secret|apikey|api_key|credential|private")

#: 需要替换的模式。顺序有意义：越具体的越先跑。
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # PEM 私钥块（含 OPENSSH PRIVATE KEY / RSA PRIVATE KEY 等）
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), PLACEHOLDER),
    # 命令行里的 -i <私钥路径>
    (re.compile(r"(-i\s+)(\S+)"), r"\1" + PLACEHOLDER),
    # password= / passwd= / token= / secret= 之类的键值
    (
        # 键名可能带引号（JSON 风格日志："api_key": "..."），所以两侧都允许引号。
        # \b 仍然必须有，否则 mypassword= 这类无关字段会一起被替换掉。
        re.compile(
            r"(?i)(?P<key>[\"']?\b(?:password|passwd|passphrase|token|secret|apikey|api_key)\b[\"']?)"
            r"\s*[=:]\s*(?:\"[^\"]*\"|'[^']*'|\S+)"
        ),
        r"\g<key>=" + PLACEHOLDER,
    ),
    # 密码模式下的 askpass 环境变量值指向的文件路径不算秘密，但 DISPLAY 之类无需处理。
)


def redact(text: str) -> str:
    """把敏感片段替换成占位符。输入不是字符串时原样返回。"""
    if not isinstance(text, str):
        return text
    result = text
    for pattern, replacement in _PATTERNS:
        result = pattern.sub(replacement, result)
    return result


class RedactingFilter:
    """`logging.Filter`：在记录被格式化前做脱敏。顺序是固定的三步，每一步都必要：

    1. **先脱敏参数值。** `%(password)s` 这种风格的记录，格式化之后键名就没了 ——
       消息变成「配置 hunter2」，此时再也无从判断 hunter2 是密码。只有在下标替换
       发生之前动手，才留得住这个上下文。字典风格的参数按**键名**判定
       （见 `_SENSITIVE_KEY_RE`），元组风格没有键名可用，只能对值本身跑一遍
       `redact()` —— 这是这类记录的固有缺口，所以给日志传参时优先用字典风格。
    2. **再格式化。** 参数值此时已经是占位符，格式化结果自然干净。
    3. **最后整体脱敏成品字符串，并清空 `args`。** 模板里可以内联秘密
       （`logger.info("password=hunter2")`），这一步负责收尾。清空 `args` 是必须的：
       消息已经是成品，若留着 `args` 而模板里的 `%s` 被第 3 步吃掉了，
       格式化器会再插值一次并抛
       `TypeError: not all arguments converted during string formatting`，
       日志里就会出现一条异常堆栈 —— 脱敏反倒把日志弄坏了。
    """

    def filter(self, record) -> bool:  # noqa: ANN001 - logging.Filter 的签名
        try:
            self._redact_args(record)
            message = record.getMessage()
            record.msg = redact(message) if isinstance(message, str) else message
        except Exception:
            # 连格式化都失败的记录（例如 %(key)s 缺键）也要保证不含秘密。
            try:
                if isinstance(record.msg, str):
                    record.msg = redact(record.msg)
            except Exception:  # pragma: no cover - 日志过滤器绝不能抛异常
                pass
        finally:
            try:
                record.args = ()
            except Exception:  # pragma: no cover
                pass
        return True

    @staticmethod
    def _redact_args(record) -> None:  # noqa: ANN001
        args = getattr(record, "args", None)
        if not args:
            return
        if isinstance(args, dict):
            record.args = {
                key: (
                    PLACEHOLDER
                    if isinstance(key, str) and _SENSITIVE_KEY_RE.search(key)
                    else (redact(value) if isinstance(value, str) else value)
                )
                for key, value in args.items()
            }
        elif isinstance(args, tuple):
            record.args = tuple(redact(value) if isinstance(value, str) else value for value in args)
        elif isinstance(args, str):
            record.args = redact(args)
