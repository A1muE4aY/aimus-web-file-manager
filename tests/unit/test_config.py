"""配置解析：用户手写 JSON，因此每个字段都要显式校验（决策 D-006、D-009）。"""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from app.core import config as cfg
from app.core.errors import ConfigError


def base_data():
    return copy.deepcopy(cfg.DEFAULTS)


class DefaultsTests(unittest.TestCase):
    #: 随包发布的模板。用户「照抄一份改字段」是常规操作，所以它既要比默认值一致，
    #: 也要真的能通过解析 —— 多出一个键，照抄的人就直接启动不了。
    EXAMPLE_PATH = cfg.project_root() / "config" / "config.example.json"

    def test_defaults_match_example_file_on_disk(self):
        # 读磁盘上的模板真比对。以前这条比的是 example_config_text() 自己刚生成的
        # 字符串，模板少一整段也照样通过（自己证自己）。
        on_disk = json.loads(self.EXAMPLE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(on_disk, cfg.DEFAULTS)

    def test_example_file_can_be_loaded(self):
        data = json.loads(self.EXAMPLE_PATH.read_text(encoding="utf-8"))
        config = cfg.parse_config(data, path=str(self.EXAMPLE_PATH))
        self.assertTrue(config.discovery.enabled)

    def test_example_config_text_is_that_file(self):
        self.assertEqual(cfg.example_config_text(), self.EXAMPLE_PATH.read_text(encoding="utf-8"))

    def test_defaults_bind_loopback(self):
        config = cfg.parse_config(base_data())
        self.assertEqual(config.server.host, "127.0.0.1")
        self.assertEqual(config.server.port, 32579)
        self.assertFalse(config.security.allow_lan)
        self.assertEqual(config.security.host_key_policy, "strict")

    def test_example_text_is_utf8_and_readable(self):
        self.assertIn("127.0.0.1", cfg.example_config_text())


class ParseTests(unittest.TestCase):
    def test_unknown_top_level_key_is_rejected(self):
        with self.assertRaises(ConfigError):
            cfg.parse_config({"server": {}, "nope": 1})

    def test_unknown_nested_key_is_rejected(self):
        with self.assertRaises(ConfigError):
            cfg.parse_config({"server": {"host": "127.0.0.1", "nope": 1}})

    def test_version_must_be_integer(self):
        with self.assertRaises(ConfigError):
            cfg.parse_config({"config_version": "1"})

    def test_future_version_is_refused(self):
        data = base_data()
        data["config_version"] = cfg.CONFIG_VERSION + 1
        with self.assertRaises(ConfigError):
            cfg.parse_config(data)

    def test_port_range(self):
        for port in (0, -1, 65536, 99999):
            data = base_data()
            data["server"]["port"] = port
            with self.assertRaises(ConfigError, msg=str(port)):
                cfg.parse_config(data)

    def test_bool_must_be_bool(self):
        data = base_data()
        data["security"]["allow_lan"] = "true"
        with self.assertRaises(ConfigError):
            cfg.parse_config(data)

    def test_host_key_policy_options(self):
        data = base_data()
        data["security"]["host_key_policy"] = "accept-new"
        self.assertEqual(cfg.parse_config(data).security.host_key_policy, "accept-new")
        for value in ("off", "no", "auto", "YES"):
            bad = base_data()
            bad["security"]["host_key_policy"] = value
            with self.assertRaises(ConfigError, msg=value):
                cfg.parse_config(bad)

    def test_log_level_options(self):
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            data = base_data()
            data["security"]["log_level"] = level
            self.assertEqual(cfg.parse_config(data).security.log_level, level)
        bad = base_data()
        bad["security"]["log_level"] = "TRACE"
        with self.assertRaises(ConfigError):
            cfg.parse_config(bad)

    def test_negative_sizes_rejected(self):
        for field in ("max_upload_bytes", "max_download_bytes"):
            data = base_data()
            data["security"][field] = -1
            with self.assertRaises(ConfigError, msg=field):
                cfg.parse_config(data)

    def test_max_download_zero_means_unlimited(self):
        config = cfg.parse_config(base_data())
        self.assertEqual(config.security.max_download_bytes, 0)

    def test_connection_ids_must_be_unique(self):
        data = base_data()
        data["connections"] = [
            {"id": "a", "host": "h1", "username": "u"},
            {"id": "a", "host": "h2", "username": "u"},
        ]
        with self.assertRaises(ConfigError):
            cfg.parse_config(data)

    def test_connection_error_names_the_index(self):
        data = base_data()
        data["connections"] = [
            {"id": "ok", "host": "127.0.0.1", "username": "u"},
            {"id": "bad id", "host": "127.0.0.1", "username": "u"},
        ]
        with self.assertRaises(ConfigError) as ctx:
            cfg.parse_config(data)
        # 用户看到的是「第几条」，所以必须是 1 起算的第 2 条，而不是下标 1。
        self.assertIn("第 2 条", str(ctx.exception))

    def test_unknown_key_is_not_silently_ignored(self):
        # 一个拼错的字段名必须报错，否则用户以为自己设的限额生效了。
        data = base_data()
        data["security"]["max_upload_btyes"] = 1024
        with self.assertRaises(ConfigError) as ctx:
            cfg.parse_config(data)
        self.assertIn("max_upload_btyes", str(ctx.exception.detail))

    def test_connections_are_parsed_into_objects(self):
        data = base_data()
        data["connections"] = [{"id": "vm1", "name": "测试机", "host": "192.168.1.9", "port": 2222, "username": "aimu"}]
        config = cfg.parse_config(data)
        self.assertEqual(len(config.connections), 1)
        self.assertEqual(config.connections[0].name, "测试机")
        self.assertEqual(config.connections[0].target_label, "aimu@192.168.1.9:2222")


class BindingTests(unittest.TestCase):
    def test_loopback_allowed(self):
        for host in ("127.0.0.1", "localhost", "::1"):
            data = base_data()
            data["server"]["host"] = host
            self.assertEqual(cfg.parse_config(data).server.host, host)

    def test_wildcard_refused_without_allow_lan(self):
        # 绑错地址的后果是整台机器的文件对局域网可见，所以必须显式拒绝而不是静默纠正。
        for host in ("0.0.0.0", "::", "192.168.1.5"):
            data = base_data()
            data["server"]["host"] = host
            with self.assertRaises(ConfigError, msg=host):
                cfg.parse_config(data)

    def test_wildcard_allowed_with_allow_lan(self):
        data = base_data()
        data["server"]["host"] = "0.0.0.0"
        data["security"]["allow_lan"] = True
        self.assertEqual(cfg.parse_config(data).server.host, "0.0.0.0")

    def test_empty_host_refused(self):
        data = base_data()
        data["server"]["host"] = "   "
        with self.assertRaises(ConfigError):
            cfg.parse_config(data)


class PathTests(unittest.TestCase):
    def test_project_root_contains_app(self):
        root = cfg.project_root()
        self.assertTrue((root / "app" / "main.py").is_file(), str(root))

    def test_resolve_is_relative_to_project_root_not_cwd(self):
        config = cfg.parse_config(base_data())
        resolved = config.resolve("data/config.json")
        self.assertTrue(resolved.is_absolute())
        self.assertEqual(resolved, cfg.project_root() / "data" / "config.json")

    def test_resolve_keeps_absolute_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "known_hosts"
            config = cfg.parse_config(base_data())
            self.assertEqual(config.resolve(str(target)), target)

    def test_runtime_paths(self):
        config = cfg.parse_config(base_data())
        self.assertEqual(config.known_hosts_path, cfg.project_root() / "data" / "known_hosts")
        self.assertEqual(config.logs_dir, cfg.project_root() / "logs")
        self.assertEqual(config.frontend_dir, cfg.project_root() / "frontend")

    def test_default_config_path_is_under_data(self):
        self.assertEqual(cfg.DEFAULT_CONFIG_PATH, cfg.project_root() / "data" / "config.json")


class LoadTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_raises_instead_of_defaulting(self):
        with self.assertRaises(ConfigError):
            cfg.load_config(self.dir / "nope.json")

    def test_broken_json_reports_position_and_forbids_rebuild(self):
        path = self.dir / "config.json"
        path.write_text('{\n  "server": {\n    "port": 8760,\n  }\n}\n', encoding="utf-8")
        with self.assertRaises(ConfigError) as ctx:
            cfg.load_config(path)
        # 行号与「不会自动重建」的说明在 detail 里（message 是给用户看的一句话）。
        self.assertIn("4", ctx.exception.detail)  # 行号
        self.assertIn("不会自动重建", ctx.exception.detail)

    def test_non_object_root(self):
        path = self.dir / "config.json"
        path.write_text("[1, 2]", encoding="utf-8")
        with self.assertRaises(ConfigError):
            cfg.load_config(path)

    def test_round_trip_save_and_load(self):
        path = self.dir / "config.json"
        data = base_data()
        data["connections"] = [{"id": "vm1", "host": "10.0.0.1", "username": "aimu"}]
        config = cfg.parse_config(data, path=str(path))
        cfg.save_config(config)
        loaded = cfg.load_config(path)
        self.assertEqual(loaded.connections[0].id, "vm1")
        # 与默认值比对，而不是写死端口号：往返测试要证明的是「没丢字段」，
        # 不是「默认端口永远是某个数字」（默认端口另有 test_launcher.py 钉住）。
        self.assertEqual(loaded.server.port, cfg.DEFAULTS["server"]["port"])

    def test_saved_file_is_unicode_readable(self):
        path = self.dir / "config.json"
        data = base_data()
        data["connections"] = [{"id": "vm1", "host": "10.0.0.1", "name": "虚拟机一", "username": "aimu"}]
        cfg.save_config(cfg.parse_config(data, path=str(path)))
        self.assertIn("虚拟机一", path.read_text(encoding="utf-8"))

    def test_init_config_refuses_to_overwrite(self):
        path = self.dir / "config.json"
        cfg.init_config(str(path))
        with self.assertRaises(ConfigError):
            cfg.init_config(str(path))

    def test_init_config_force_overwrites(self):
        path = self.dir / "config.json"
        cfg.init_config(str(path))
        cfg.save_config(cfg.parse_config({**base_data(), "server": {**base_data()["server"], "port": 9000}}, path=str(path)))
        path.write_text("{ broken", encoding="utf-8")
        cfg.init_config(str(path), overwrite=True)
        # 覆盖重建后应回到默认端口（同上：比默认值，不写死数字）。
        self.assertEqual(cfg.load_config(path).server.port, cfg.DEFAULTS["server"]["port"])

    def test_init_config_result_is_loadable(self):
        path = self.dir / "config.json"
        result = cfg.init_config(str(path))
        self.assertTrue(Path(result).is_file())
        cfg.load_config(path)


class DiscoveryConfigTests(unittest.TestCase):
    """在线虚拟机发现那一段（v0.1.1 阶段五）。

    它的每个上限都会变成真实的探测行为，所以取值范围要在这里钉死；另外这一段
    每次写配置都会跟着走一趟 to_dict，不能丢。
    """

    def test_defaults_stay_gentle(self):
        config = cfg.parse_config(base_data())
        self.assertTrue(config.discovery.enabled)
        self.assertTrue(config.discovery.probe_ssh)
        self.assertEqual(config.discovery.probe_timeout_seconds, 1.0)
        self.assertEqual(config.discovery.max_probes, 512)

    def test_limits_are_range_checked(self):
        for key, value in (
            ("probe_timeout_seconds", 0.05),
            ("probe_timeout_seconds", 5.5),
            ("max_probe_workers", 0),
            ("max_probe_workers", 65),
            ("max_addresses_per_subnet", 4097),
            ("max_probes", 0),
            ("max_probes", 65537),
            ("time_budget_seconds", 0),
        ):
            data = base_data()
            data["discovery"][key] = value
            with self.assertRaises(ConfigError, msg=f"{key}={value}"):
                cfg.parse_config(data)

    def test_switches_must_be_booleans(self):
        for key in ("enabled", "probe_ssh"):
            data = base_data()
            data["discovery"][key] = "yes"
            with self.assertRaises(ConfigError, msg=key):
                cfg.parse_config(data)

    def test_custom_vmware_paths_are_kept(self):
        data = base_data()
        data["discovery"]["vmware_root"] = "D:\\VMware"
        data["discovery"]["vmware_data_dir"] = "D:\\ProgramData\\VMware"
        config = cfg.parse_config(data)
        self.assertEqual(config.discovery.vmware_root, "D:\\VMware")
        self.assertEqual(config.discovery.vmware_data_dir, "D:\\ProgramData\\VMware")

    def test_round_trip_keeps_every_value(self):
        """to_dict 走一趟不能丢字段：连接管理器每次增删改连接都会写一遍配置。"""
        data = base_data()
        data["security"]["max_edit_bytes"] = 123456
        data["discovery"]["max_probes"] = 64
        config = cfg.parse_config(data)
        again = cfg.parse_config(config.to_dict())
        self.assertEqual(again.security.max_edit_bytes, 123456, "security.max_edit_bytes 曾经在这一步被静默丢掉")
        self.assertEqual(again.discovery.max_probes, 64)
        self.assertEqual(again.to_dict(), config.to_dict())


if __name__ == "__main__":
    unittest.main()
