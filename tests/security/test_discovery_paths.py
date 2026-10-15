"""在线虚拟机发现的攻击面测试（决策 D-018；任务书 2.md 阶段五）。

「发现」是 AWFM 里唯一会自己往外连的入口：要连的地址不是用户填的，而是它从 VMware
清单、.vmx、DHCP 租约和系统邻居表里读出来的。所以这一层钉的不是功能，而是**范围**：

1. 必须带令牌：四个端点无令牌一律 401（结果里有本机内网地址与主机名，不该被无令牌读走）。
2. 只在已知虚拟网段里探测，而且只探 22 端口。
3. 本机虚拟网卡与网关地址永远不是候选，也永远不被探测。
4. 关掉探测就一个包都不发（discovery.probe_ssh = false）。
5. 上限是真的上限：max_probes 调成 1，被探测的地址最多一个。
6. 只读：扫描前后 VMware 的清单 / vmnetdhcp.conf / 租约文件内容不变。
7. 不派生远端进程：扫描前后本机 ssh.exe 进程数不变 —— 「SSH 可用」是直接试 22 端口
   试出来的，不是登录上去看的。
8. 结果只是候选：扫描不会往连接表里添任何东西。

探测的频率、并发与超时上限由注入假件在单元测试里钉；这里跑的是真机上的真扫描。
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.core import config as cfg
from app.services import discovery as svc
from tests.integration.support import make_config, running_server, scan_and_wait
from tests.security.support import DEAD_CONNECTION, local_server

DISCOVERY = "/api/discovery"
SCAN = "/api/discovery/scan"
#: 语法上就不像扫描 id 的几串（扫描 id 是 12 位小写十六进制）。
MALFORMED_IDS = ("zzzz", "0123456789ABCDEF", "0" * 40, "%20")


def count_ssh_processes() -> int:
    """本机所有 ssh.exe 进程数（发现功能一次都不该让它变多）。"""
    if sys.platform != "win32":
        return 0
    # 必须用 @() 把结果包成数组：只剩一个进程时 PowerShell 5.1 把它当标量，
    # 标量的 .Count 是空字符串，于是这里会读成 0 —— 断言就会在「真的有一个」时失败。
    script = "@(Get-CimInstance Win32_Process -Filter \"Name='ssh.exe'\").Count"
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    text = (result.stdout or "").strip()
    return int(text) if text.isdigit() else 0


def read_vmware_files(env) -> dict:
    """VMware 那三个只读文件的原文（清单 / vmnetdhcp.conf / 租约）。"""
    snapshot = {}
    for name in ("inventory_path", "dhcp_conf_path", "dhcp_leases_path"):
        path = Path(getattr(env, name))
        if path.is_file():
            snapshot[str(path)] = path.read_bytes()
    return snapshot


@contextlib.contextmanager
def discovery_server(**overrides):
    """一个真服务器：只把「发现」那一段换成用例需要的样子，其余走最小配置。

    连接表里放的是永远连不上的 dead-host —— 于是「扫描有没有偷偷建连接」是可判定的。
    """
    with tempfile.TemporaryDirectory(prefix="awfm-sec-discovery-") as tmp:
        known_hosts = Path(tmp) / "known_hosts"
        config = make_config(known_hosts, connections=[DEAD_CONNECTION])
        data = config.to_dict()
        data["discovery"].update(overrides)
        config = cfg.parse_config(data, path=str(Path(tmp) / "config.json"))
        with running_server(config) as client:
            yield config, client


class DiscoveryRouteBoundaryTests(unittest.TestCase):
    """不需要 VMware、也不需要测试床：令牌与路由的边界。"""

    @classmethod
    def setUpClass(cls):
        cls._stack = contextlib.ExitStack()
        cls.harness = cls._stack.enter_context(local_server(connections=()))
        cls.client = cls.harness.client

    @classmethod
    def tearDownClass(cls):
        cls._stack.close()

    def test_every_endpoint_requires_the_token(self):
        cases = (
            ("get", DISCOVERY),
            ("post", SCAN),
            ("get", DISCOVERY + "/scans/deadbeef"),
            ("delete", DISCOVERY + "/scans/deadbeef"),
        )
        for method, path in cases:
            with self.subTest(method=method, path=path):
                response = getattr(self.client, method)(path, token=False)
                self.assertEqual(
                    (response.status, response.code), (401, "unauthorized"), repr(response)
                )

    def test_malformed_scan_ids_are_not_found(self):
        for scan_id in MALFORMED_IDS:
            with self.subTest(scan_id=scan_id):
                response = self.client.get(DISCOVERY + "/scans/" + scan_id)
                self.assertEqual(response.status, 404, repr(response))

    def test_scan_cannot_be_started_from_the_environment_path(self):
        response = self.client.post(DISCOVERY)
        self.assertEqual(
            (response.status, response.code), (400, "invalid_request"), repr(response)
        )

    def test_reading_environment_does_not_leave_a_scan_behind(self):
        """看一眼环境不该顺手起一次扫描（那是 POST 的事）。"""
        self.assertEqual(self.client.get(DISCOVERY).status, 200)
        self.assertEqual(self.client.get(DISCOVERY + "/scans/deadbeef").status, 404)


class DiscoveryProbeBoundaryTests(unittest.TestCase):
    """真机上的真扫描：探测范围、上限、以及「只读」。"""

    @classmethod
    def setUpClass(cls):
        cls._stack = contextlib.ExitStack()
        cls.config, cls.client = cls._stack.enter_context(discovery_server())
        cls.env = svc.resolve_environment(cls.config)
        if not cls.env.install_path and not cls.env.inventory_path:
            cls._stack.close()
            raise unittest.SkipTest("这台机器上没有找到 VMware，发现功能没有可读的来源。")
        cls.snapshot = scan_and_wait(cls.client)

    @classmethod
    def tearDownClass(cls):
        cls._stack.close()

    def test_probing_is_confined_to_known_virtual_subnets_and_port_22(self):
        known = {
            "%s/%s" % (item["network"], item["prefix"]) for item in self.snapshot["subnets"]
        }
        self.assertTrue(known, "这台机器上应该读得到虚拟网段")
        probed = [item for item in self.snapshot["addresses_all"] if item.get("probed")]
        self.assertEqual(len(probed), self.snapshot["probes"]["done"])
        for item in probed:
            self.assertTrue(item["in_known_subnet"], "%s 不在读出来的虚拟网段里却探测了" % item["ip"])
            self.assertIn(item["subnet"], known, "%s 的网段标号不在读出来的网段里" % item["ip"])
            self.assertEqual(item["port"], svc.SSH_PORT, "只允许探 SSH 端口")

    def test_host_and_gateway_addresses_are_never_candidates(self):
        reserved = set()
        for item in self.snapshot["subnets"]:
            for key in ("host_address", "gateway"):
                if item.get(key):
                    reserved.add(item[key])
        self.assertTrue(reserved, "这台机器上应该读得到本机虚拟网卡与网关地址")
        listed = {item["ip"] for item in self.snapshot["addresses_all"]}
        self.assertFalse(reserved & listed, "本机网卡与网关出现在候选地址里：%r" % (reserved & listed))
        probed = {item["ip"] for item in self.snapshot["addresses_all"] if item.get("probed")}
        self.assertFalse(reserved & probed, "本机网卡与网关被探测了：%r" % (reserved & probed))

    def test_switching_probing_off_sends_nothing(self):
        with discovery_server(probe_ssh=False) as (_config, client):
            snapshot = scan_and_wait(client)
        self.assertFalse(snapshot["probes"]["enabled"])
        self.assertEqual(snapshot["probes"]["done"], 0, "关掉探测后不应该有任何一次连接尝试")
        self.assertFalse(
            [item for item in snapshot["addresses_all"] if item.get("probed")],
            "关掉探测后不应该有地址被标记成探过",
        )
        self.assertTrue(
            any("probe_ssh" in note for note in snapshot["notes"]),
            "关掉探测时应该在说明里讲清楚：%r" % snapshot["notes"],
        )

    def test_max_probes_is_a_real_limit(self):
        with discovery_server(max_probes=1) as (_config, client):
            snapshot = scan_and_wait(client)
        self.assertLessEqual(snapshot["probes"]["planned"], 1, "planned 超过配置上限")
        self.assertLessEqual(snapshot["probes"]["done"], 1, "done 超过配置上限")

    def test_scan_does_not_touch_the_vmware_files(self):
        with discovery_server() as (config, client):
            env = svc.resolve_environment(config)
            before = read_vmware_files(env)
            self.assertTrue(before, "这台机器上应该读得到 VMware 的文件")
            scan_and_wait(client)
            after = read_vmware_files(env)
        for path, original in before.items():
            self.assertIn(path, after, path + " 在扫描后不见了")
            if after[path] != original:
                # 唯一可以接受的变化：VMware 自己的 DHCP 服务往租约文件里追加了一条。
                # 扫描本身只读，不得改写/截断这些文件。
                self.assertTrue(after[path].startswith(original), path + " 的内容被改写了")

    def test_scan_does_not_start_ssh(self):
        before = count_ssh_processes()
        with discovery_server() as (_config, client):
            scan_and_wait(client)
        after = count_ssh_processes()
        self.assertEqual(after, before, "扫描过程中起了 ssh 进程：%d → %d" % (before, after))

    def test_scan_does_not_create_connections(self):
        """发现的结果只是候选：连接表在扫描前后一模一样。"""
        with discovery_server() as (_config, client):
            before = client.get("/api/connections").data["connections"]
            snapshot = scan_and_wait(client)
            after = client.get("/api/connections").data["connections"]
        self.assertEqual([item["id"] for item in before], ["dead-host"])
        self.assertEqual([item["id"] for item in after], ["dead-host"], "扫描往连接表里加了东西")
        discovered = {item["ip"] for item in snapshot["addresses_all"]}
        hosts = {item["host"] for item in after}
        self.assertFalse(discovered & hosts, "发现到的地址被自动写成了连接：%r" % (discovered & hosts))


if __name__ == "__main__":
    unittest.main()
