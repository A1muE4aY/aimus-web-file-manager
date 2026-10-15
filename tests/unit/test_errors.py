"""错误模型：每个错误自带 HTTP 状态码，序列化格式就是 API 契约。"""

import unittest
from pathlib import Path

from app.core import errors


class ErrorCodeTests(unittest.TestCase):
    EXPECTED = {
        "ValidationError": ("invalid_request", 400),
        "PayloadTooLarge": ("payload_too_large", 413),
        "ConfigError": ("config_error", 500),
        "Unauthorized": ("unauthorized", 401),
        "ConnectionNotFound": ("connection_not_found", 404),
        "SessionNotConnected": ("session_not_found", 404),
        "NotConnected": ("not_connected", 409),
        "AuthFailed": ("auth_failed", 401),
        "HostKeyUnknown": ("host_key_unknown", 409),
        "HostKeyMismatch": ("host_key_mismatch", 409),
        "PathNotFound": ("path_not_found", 404),
        "PermissionDenied": ("permission_denied", 403),
        "SearchBusy": ("search_busy", 409),
        "RemoteError": ("remote_error", 502),
        "ProtocolError": ("protocol_error", 502),
        "OperationTimeout": ("timeout", 504),
        "InternalError": ("internal_error", 500),
    }

    def test_every_subclass_has_a_distinct_code_and_status(self):
        for name, (code, status) in self.EXPECTED.items():
            cls = getattr(errors, name)
            self.assertTrue(issubclass(cls, errors.AwfmError), name)
            self.assertEqual(cls.code, code, name)
            self.assertEqual(cls.http_status, status, name)

    def test_codes_are_unique(self):
        codes = [code for code, _ in self.EXPECTED.values()]
        self.assertEqual(len(codes), len(set(codes)))

    def test_all_subclasses_are_covered_by_this_test(self):
        found = {
            obj.__name__
            for obj in vars(errors).values()
            if isinstance(obj, type) and issubclass(obj, errors.AwfmError) and obj is not errors.AwfmError
        }
        self.assertEqual(found, set(self.EXPECTED))


class ErrorSerializationTests(unittest.TestCase):
    def test_minimal(self):
        payload = errors.ValidationError("路径不对。").to_dict()
        self.assertEqual(payload, {"ok": False, "error": {"code": "invalid_request", "message": "路径不对。"}})

    def test_detail_is_included_when_present(self):
        payload = errors.RemoteError("远端操作失败。", detail="NO_SUCH_FILE").to_dict()
        self.assertEqual(payload["error"]["detail"], "NO_SUCH_FILE")

    def test_extra_fields_are_merged_into_error(self):
        error = errors.HostKeyUnknown(
            "首次连接需要确认主机指纹。",
            extra={"connection_id": "c1", "fingerprints": [{"key_type": "ssh-ed25519", "fingerprint": "SHA256:x"}]},
        )
        payload = error.to_dict()["error"]
        self.assertEqual(payload["connection_id"], "c1")
        self.assertEqual(payload["fingerprints"][0]["fingerprint"], "SHA256:x")

    def test_extra_does_not_override_core_fields(self):
        payload = errors.ValidationError("原始消息。", extra={"code": "evil", "message": "evil"}).to_dict()
        self.assertEqual(payload["error"]["code"], "invalid_request")
        self.assertEqual(payload["error"]["message"], "原始消息。")

    def test_extra_is_not_shared_between_instances(self):
        first = errors.ValidationError("a", extra={"x": 1})
        second = errors.ValidationError("b")
        first.to_dict()
        self.assertNotIn("x", second.to_dict()["error"])


class StatusCodeIsNotAConstructorArgumentTests(unittest.TestCase):
    """HTTP 状态码只能来自错误子类的类属性，不能当构造参数传。

    2026-10-15 的真实缺陷：app/ssh/known_hosts.py 有三处写成
    AwfmError(..., http_status=502)，而 AwfmError.__init__ 只接受
    message/detail/extra —— 于是「目标机连不上」变成 TypeError，
    对外报成 500「未预期异常」（tests/e2e 跑真实浏览器时抓到）。
    """

    def test_constructor_rejects_http_status_keyword(self):
        with self.assertRaises(TypeError):
            errors.AwfmError("状态码不是构造参数。", http_status=502)

    def test_no_source_file_passes_http_status_as_a_keyword(self):
        root = Path(__file__).resolve().parents[2] / "app"
        offenders = []
        for path in sorted(root.rglob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                # 类属性写成 "http_status = 500"（等号两侧有空格）；
                # 关键字参数写成 "http_status=500" —— 后者一律是缺陷。
                if "http_status=" in line:
                    offenders.append(str(path.relative_to(root)) + ":" + str(number) + ": " + line.strip())
        self.assertEqual(
            offenders,
            [],
            "状态码由错误子类的类属性决定，不能作为构造参数：\n" + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
