"""在线虚拟机发现的端到端接口测试（决策 D-018；任务书 2.md 阶段五）。

这一层和别的集成测试**不一样**：它不连 WSL 测试床，读的是**这台机器自己**的 VMware
状态（清单、.vmx、vmnetdhcp.conf/.leases、系统邻居表、vmrun）。所以：

- **不挂 require_testbed**：发现功能与测试床无关，测试床没起来时这些用例照样该跑。
- 没装 VMware 的机器上整类跳过，并把原因说清楚（发现没有可读的来源）。
- 断言分两类：一类是「无论这台机器怎么变都必须成立」的（扫描能跑完、计数自洽、
  被探测的地址都在已知虚拟网段里、并发 409、未知 id 404）；另一类是「这台机器上
  确实如此」的（vmrun 报在跑的那台虚拟机必须被认出来并带上地址），后者在前提不成立
  时跳过并说明。
- 用的都是默认配置，跑的就是真实行为；把上限调小的用例在安全层。
"""

from __future__ import annotations

import contextlib
import sys
import unittest

from app.services import discovery as svc
from tests.integration.support import (
    running_server,
    scan_and_wait,
    start_discovery_scan,
    testbed_environment,
    wait_discovery_scan,
)

SCAN = "/api/discovery/scan"


class DiscoveryApiTests(unittest.TestCase):
    """真机上的四个端点。整类共用一次扫描，另外几个用例自己起扫描。"""

    @classmethod
    def setUpClass(cls):
        cls._stack = contextlib.ExitStack()
        config, _keys = cls._stack.enter_context(testbed_environment(connections=[], trust=False))
        cls.config = config
        cls.env = svc.resolve_environment(config)
        if not cls.env.install_path and not cls.env.inventory_path:
            cls._stack.close()
            raise unittest.SkipTest("这台机器上没有找到 VMware（既没有安装路径也没有清单），发现功能没有可读的来源。")
        cls.client = cls._stack.enter_context(running_server(config))
        cls.snapshot = scan_and_wait(cls.client)

    @classmethod
    def tearDownClass(cls):
        cls._stack.close()

    # ------------------------------------------------------------- 环境概览

    def test_environment_endpoint_describes_this_machine(self):
        """GET /api/discovery 说的必须是这台机器的事实。"""
        response = self.client.get("/api/discovery")
        self.assertEqual(response.status, 200, repr(response))
        environment = response.data["environment"]
        self.assertTrue(environment["enabled"])
        self.assertEqual(environment["platform"], sys.platform)
        self.assertEqual(
            [item["name"] for item in environment["sources"]],
            ["inventory", "vmrun", "vmnet", "lease", "neighbor", "process"],
        )
        # 读进程命令行需要管理员权限：这一条永远是「已跳过」，而且要说得出原因。
        process = [item for item in environment["sources"] if item["name"] == "process"][0]
        self.assertEqual(process["state"], "denied")
        self.assertIn("管理员权限", process["detail"])
        self.assertEqual(environment["limits"]["max_probes"], 512)
        self.assertEqual(environment["limits"]["probe_timeout_seconds"], 1.0)

    def test_unknown_scan_id_is_404(self):
        response = self.client.get("/api/discovery/scans/deadbeef")
        self.assertEqual((response.status, response.code), (404, "path_not_found"), repr(response))
        response = self.client.delete("/api/discovery/scans/deadbeef")
        self.assertEqual((response.status, response.code), (404, "path_not_found"), repr(response))

    # --------------------------------------------------------------- 一次扫描

    def test_scan_finished_and_counts_are_consistent(self):
        snapshot = self.snapshot
        self.assertEqual(snapshot["status"], "done", repr(snapshot))
        self.assertFalse(snapshot["running"])
        self.assertFalse(snapshot["interrupted"])
        self.assertIsNone(snapshot["error"])
        self.assertGreater(snapshot["duration_seconds"], 0)

        counts = snapshot["counts"]
        vms = snapshot["vms"]
        self.assertEqual(counts["vms"], len(vms))
        self.assertEqual(counts["running"] + counts["stopped"] + counts["unknown_state"], counts["vms"])
        self.assertEqual(counts["with_address"], sum(1 for vm in vms if vm["ip"]))
        self.assertLessEqual(counts["ssh_open"], counts["with_address"])
        self.assertLessEqual(counts["online"], counts["with_address"])
        self.assertEqual(counts["other_addresses"], len(snapshot["addresses"]))

        probes = snapshot["probes"]
        self.assertTrue(probes["enabled"])
        self.assertLessEqual(probes["done"], probes["planned"])
        self.assertLessEqual(probes["open"], probes["responded"])
        self.assertLessEqual(probes["responded"], probes["done"])
        self.assertEqual(probes["timeout_seconds"], 1.0)
        # 扫描用时不该超过时间预算（读来源 + 探测 + 收尾的一点余量）。
        self.assertLess(snapshot["duration_seconds"], snapshot["limits"]["time_budget_seconds"] + 30)

    def test_every_probed_address_is_inside_a_known_virtual_subnet(self):
        """这条是发现功能的安全底线：不能把探测撒到别的网段去。"""
        snapshot = self.snapshot
        probed = [item for item in snapshot["addresses_all"] if item.get("probed")]
        self.assertEqual(len(probed), snapshot["probes"]["done"])
        # 响应里的网段标号就是 VMnnet 配置里读出来的那个网段（network/prefix）。
        known = {f"{item['network']}/{item['prefix']}" for item in snapshot["subnets"]}
        self.assertTrue(known, "这台机器上应该读得到虚拟网段")
        for item in probed:
            self.assertTrue(item["in_known_subnet"], f"{item['ip']} 不在已知虚拟网段里，却被探测了")
            self.assertIn(item["subnet"], known, f"{item['ip']} 的网段标号 {item['subnet']} 不是读出来的网段")
            self.assertEqual(item["port"], svc.SSH_PORT, "只探 SSH 端口")

    def test_host_and_gateway_addresses_are_never_probed(self):
        """本机虚拟网卡与网关不是「待连接的机器」，既不进候选也不被探测。"""
        snapshot = self.snapshot
        host_addresses = {item.get("host_address") for item in snapshot["subnets"]} | {
            item.get("gateway") for item in snapshot["subnets"]
        }
        host_addresses.discard(None)
        self.assertTrue(host_addresses, "这台机器上应该至少有一个本机虚拟网卡地址")
        listed = {item["ip"] for item in snapshot["addresses_all"]}
        for ip in host_addresses:
            self.assertNotIn(ip, listed)
        probed = {item["ip"] for item in snapshot["addresses_all"] if item.get("probed")}
        self.assertFalse(probed & host_addresses)

    def test_notes_say_what_was_left_out(self):
        notes = self.snapshot["notes"]
        self.assertTrue(any("过滤" in note for note in notes), notes)

    # ------------------------------------------------------- 这台机器上的事实

    def test_a_vm_that_vmrun_reports_running_is_found_with_an_address(self):
        running, report = svc.read_running_vms(self.env)
        if not running:
            self.skipTest("这台机器上现在没有正在运行的虚拟机：" + (report["detail"] or report["state"]))

        snapshot = self.snapshot
        by_path = {svc._normalize_path(vm["vmx"]): vm for vm in snapshot["vms"]}
        for path in running:
            key = svc._normalize_path(path)
            self.assertIn(key, by_path, f"vmrun 说这台在跑，扫描却没找到：{path}")
            vm = by_path[key]
            self.assertEqual(vm["state"], "running")
            self.assertTrue(vm["running"])
            self.assertEqual(vm["running_source"], "vmrun")

        with_address = [
            by_path[svc._normalize_path(path)] for path in running if by_path[svc._normalize_path(path)]["ip"]
        ]
        if not with_address:
            self.skipTest("正在运行的虚拟机都没报出地址（没装 VMware Tools，也没有 DHCP 租约）")
        for vm in with_address:
            self.assertTrue(vm["ip"], vm["name"])
            self.assertTrue(vm["ip_source"], "地址必须说得出是从哪里来的")

    def test_a_running_vm_that_answers_on_ssh_is_marked_as_such(self):
        """这台机器上的 CentOS 装了 sshd：能连上的那一台必须报 ssh_open，而不是只报「在线」。"""
        snapshot = self.snapshot
        open_vms = [vm for vm in snapshot["vms"] if vm["ssh_open"]]
        if not open_vms:
            self.skipTest("这次扫描没有发现能连 SSH 的虚拟机（可能都关机了，或 sshd 没起来）")
        for vm in open_vms:
            self.assertEqual(vm["answer_state"], "ssh_open")
            self.assertTrue(vm["ip"], "报了能连 SSH 就必须有地址")

    # ----------------------------------------------------------- 并发与中止

    def test_a_second_scan_while_one_is_running_is_refused(self):
        """同时只允许一个扫描：第二次必须 409，而不是悄悄排队或并行跑。"""
        first = start_discovery_scan(self.client)
        try:
            response = self.client.post(SCAN)
            self.assertEqual((response.status, response.code), (409, "discovery_busy"), repr(response))
            self.assertIn("中止", response.error["detail"])
        finally:
            self.client.delete(f"/api/discovery/scans/{first}")
            wait_discovery_scan(self.client, first)

    def test_cancel_is_reported_and_frees_the_slot(self):
        scan_id = start_discovery_scan(self.client)
        cancelled = self.client.delete(f"/api/discovery/scans/{scan_id}")
        self.assertEqual(cancelled.status, 200, repr(cancelled))
        self.assertEqual(cancelled.data["scan"]["id"], scan_id)
        snapshot = wait_discovery_scan(self.client, scan_id)
        self.assertIn(snapshot["status"], ("cancelled", "done"))
        if snapshot["status"] == "cancelled":
            self.assertTrue(snapshot["interrupted"])
            self.assertIn("已中止", "".join(snapshot["notes"]))
        # 不管那次是中止还是已经跑完，槽位都必须空出来：紧接着再扫一次要能跑完。
        again = scan_and_wait(self.client)
        self.assertEqual(again["status"], "done", repr(again))
