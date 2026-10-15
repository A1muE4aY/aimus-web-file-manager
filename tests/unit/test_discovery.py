"""发现服务的单元测试。

三样东西各测一层：

- **纯解析函数**用本机真实文件格式的样本驱动（清单、.vmx、租约、vmnetdhcp.conf、
  邻居表 CSV、arp -a）。样本里的字段名与取值都来自这台机器上真实存在的文件。
- **探测**用假 socket 驱动，四种结局（open / refused / timeout / unreachable）逐一定死。
- **融合与状态机**用临时目录里的一整套假环境 + 注入的探测函数驱动 collect，再用它
  验证「发现虚拟机 / 地址在线 / SSH 可用」这三种状态确实分得开。

**不连网、不起进程、不碰真实 SSH** —— 唯一会碰操作系统的入口（read_neighbors 要起
PowerShell、read_running_vms 要起 vmrun）在这类用例里被替换掉，真实链路在
tests/integration/test_discovery_api.py 里覆盖。
"""

import copy
import errno
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from app.core import config as cfg
from app.core.errors import DiscoveryBusy, PathNotFound, ValidationError
from app.services import discovery as svc


# --------------------------------------------------------------------- 样本

#: 本机清单 C:\Users\Aimu2\AppData\Roaming\VMware\inventory.vmls 的形态。
#: 注意段号顺序是 2、3、1 —— 「不能假设序号连续或有序」就是这么来的。
INVENTORY = r'''.encoding = "UTF-8"
vmlist2.config = "E:\Virtual Machines\Ubuntu x64\Ubuntu x64.vmx"
vmlist2.DisplayName = "Ubuntu x64"
vmlist2.UUID = "56 4d 43 c5 25 c5 1c b9-0a f3 47 b0 79 62 01 4d"
vmlist2.State = "normal"
vmlist3.config = "E:\Virtual Machines\CentOS 10\CentOS version 5 and earlier 64-bit.vmx"
vmlist3.DisplayName = "CentOS Stream 10"
vmlist3.UUID = "56 4d 00 13 53 67 b0 1a-ee 52 98 5a a3 57 cf b0"
vmlist3.State = "normal"
vmlist1.config = "E:\Virtual Machines\CentOS 10\CentOS Stream 10.vmx"
vmlist1.DisplayName = "CentOS Stream 10"
vmlist1.UUID = "56 4d b1 45 70 cc 40 db-af 01 78 e2 4e 58 7b 2a"
vmlist1.State = "normal"
index.count = "3"
index0.field0.name = "guest"
index0.id = "E:\Virtual Machines\Ubuntu x64\Ubuntu x64.vmx"
'''

#: 本机 E:\Virtual Machines\CentOS 10\CentOS Stream 10.vmx 的关键行。
#: 为测试另外补了两处：一张 present = FALSE 的网卡（过滤规则）、一行 firmware。
VMX_CENTOS = r'''.encoding = "UTF-8"
config.version = "8"
virtualHW.version = "22"
displayName = "CentOS Stream 10"
guestOS = "centos-64"
memsize = "8192"
numvcpus = "2"
uuid.bios = "56 4d b1 45 70 cc 40 db-af 01 78 e2 4e 58 7b 2a"
firmware = "efi"
ethernet0.present = "TRUE"
ethernet0.connectionType = "nat"
ethernet0.addressType = "generated"
ethernet0.virtualDev = "e1000"
ethernet0.generatedAddress = "00:0c:29:58:7b:2a"
ethernet1.present = "FALSE"
ethernet1.connectionType = "hostonly"
ethernet1.virtualDev = "e1000"
ethernet1.generatedAddress = "00:0c:29:58:7b:2b"
scsi0.present = "TRUE"
scsi0:0.present = "TRUE"
scsi0:0.fileName = "CentOS Stream 10.vmdk"
usb:0.present = "TRUE"
pciBridge0.present = "TRUE"
svga.autodetect = "TRUE"
floppy0.present = "FALSE"
cleanShutdown = "FALSE"
'''

#: 合成的 Ubuntu x64.vmx（这台机器上的那份没有读过，字段形态照 CentOS 的来）。
#: MAC 取自本机租约文件：它确实属于这台 Ubuntu，只是现在已经不在那个地址上了。
VMX_UBUNTU = r'''.encoding = "UTF-8"
displayName = "Ubuntu x64"
guestOS = "ubuntu-64"
memsize = "4096"
numvcpus = "2"
uuid.bios = "56 4d 43 c5 25 c5 1c b9-0a f3 47 b0 79 62 01 4d"
ethernet0.present = "TRUE"
ethernet0.connectionType = "nat"
ethernet0.virtualDev = "e1000"
ethernet0.generatedAddress = "00:0c:29:62:01:4d"
'''

#: 本机 C:\ProgramData\VMware\vmnetdhcp.leases 的 4 条租约（行首是制表符）。
#: 同一个 MAC（00:0c:29:62:01:4d）出现两次：追加日志，最后一条才算数。
LEASES = '''# All times in this file are in UTC (GMT), not your local timezone.
lease 192.168.170.129 {
\tstarts 4 2026/10/15 08:50:20;
\tends 4 2026/10/15 09:20:20;
\thardware ethernet 00:0c:29:62:01:4d;
\tuid 00:0c:29:62:01:4d;
\tclient-hostname "aimu0721-VMware-Virtual-Platform";
}
lease 192.168.170.130 {
\tstarts 6 2026/10/10 07:38:05;
\tends 6 2026/10/10 08:08:05;
\thardware ethernet 00:0c:29:58:7b:2a;
\tclient-hostname "hadoop01";
}
lease 192.168.170.128 {
\tstarts 1 2026/10/05 12:32:00;
\tends 1 2026/10/05 13:02:00;
\thardware ethernet 00:0c:29:57:cf:b0;
\tclient-hostname "hadoop01";
}
lease 192.168.170.129 {
\tstarts 4 2026/10/15 08:53:51;
\tends 4 2026/10/15 09:23:51;
\thardware ethernet 00:0c:29:62:01:4d;
\tclient-hostname "aimu0721-VMware-Virtual-Platform";
}
'''

#: 本机 C:\ProgramData\VMware\vmnetdhcp.conf 的两个网段与两个 host 块。
#: host 块里的 option domain-name-servers 是 0.0.0.0 —— 它绝不能覆盖网段网关。
VMNET_CONF = '''# Configuration file for VMware Workstation DHCP service.
# Virtual ethernet segment 1
subnet 192.168.11.0 netmask 255.255.255.0 {
\trange 192.168.11.128 192.168.11.254;
\toption broadcast-address 192.168.11.255;
\toption domain-name-servers 192.168.11.1;
\toption domain-name "localdomain";
\tdefault-lease-time 1800;
\tmax-lease-time 7200;
}
host VMnet1 {
\thardware ethernet 00:50:56:C0:00:01;
\tfixed-address 192.168.11.1;
\toption domain-name-servers 0.0.0.0;
}
# Virtual ethernet segment 8
subnet 192.168.170.0 netmask 255.255.255.0 {
\trange 192.168.170.128 192.168.170.254;
\toption broadcast-address 192.168.170.255;
\toption domain-name-servers 192.168.170.2;
\toption netbios-name-servers 192.168.170.2;
\toption routers 192.168.170.2;
\tdefault-lease-time 1800;
\tmax-lease-time 7200;
}
host VMnet8 {
\thardware ethernet 00:50:56:C0:00:08;
\tfixed-address 192.168.170.1;
\toption domain-name-servers 0.0.0.0;
}
allow unknown-clients;
default-lease-time 1800;
max-lease-time 7200;
'''

#: Get-NetNeighbor | ConvertTo-Csv 的形态（带状态列，MAC 用短横线）。
NEIGHBORS_CSV = '''"IPAddress","LinkLayerAddress","State"
"192.168.170.128","00-0C-29-58-7B-2A","Reachable"
"192.168.170.130","00-0C-29-58-7B-2A","Stale"
"224.0.0.251","01-00-5E-00-00-FB","Permanent"
"192.168.170.9","00-0C-29-11-22-33","Unreachable"
'''

#: Windows 中文版 arp -a 的形态（没有状态列，只能当线索）。
ARP = '''接口: 192.168.170.1 --- 0x8
  Internet 地址          物理地址              类型
  192.168.170.128         00-0c-29-58-7b-2a     动态
  192.168.170.255         ff-ff-ff-ff-ff-ff     静态
'''

CENTOS_VMX_NAME = "CentOS Stream 10.vmx"
GONE_VMX_NAME = "CentOS version 5 and earlier 64-bit.vmx"
UBUNTU_VMX_NAME = "Ubuntu x64.vmx"


def inventory_text(base: Path) -> str:
    """把上面那份真实清单的三条记录指向临时目录（形态与取值都不变，只有路径）。"""
    centos = base / "CentOS 10"
    ubuntu = base / "Ubuntu x64"
    return "\n".join(
        [
            '.encoding = "UTF-8"',
            f'vmlist2.config = "{ubuntu / UBUNTU_VMX_NAME}"',
            'vmlist2.DisplayName = "Ubuntu x64"',
            'vmlist2.UUID = "56 4d 43 c5 25 c5 1c b9-0a f3 47 b0 79 62 01 4d"',
            'vmlist2.State = "normal"',
            f'vmlist3.config = "{centos / GONE_VMX_NAME}"',
            'vmlist3.DisplayName = "CentOS Stream 10"',
            'vmlist3.UUID = "56 4d 00 13 53 67 b0 1a-ee 52 98 5a a3 57 cf b0"',
            'vmlist3.State = "normal"',
            f'vmlist1.config = "{centos / CENTOS_VMX_NAME}"',
            'vmlist1.DisplayName = "CentOS Stream 10"',
            'vmlist1.UUID = "56 4d b1 45 70 cc 40 db-af 01 78 e2 4e 58 7b 2a"',
            'vmlist1.State = "normal"',
            'index.count = "3"',
            "",
        ]
    )


def make_config(**discovery_overrides):
    """一份可用的配置。要改发现那一段就传关键字参数。"""
    data = copy.deepcopy(cfg.DEFAULTS)
    data["discovery"].update(discovery_overrides)
    return cfg.parse_config(data)


def neighbor_report(count: int, state: str = "ok") -> dict[str, object]:
    return {
        "name": "neighbor",
        "label": "系统邻居表",
        "state": state,
        "count": count,
        "detail": "",
    }


def fake_probe(ip, *, port=svc.SSH_PORT, timeout=1.0):
    """假的单地址探测：按预置表回答，绝不碰网络。"""
    return {
        "ip": ip,
        "port": port,
        "state": "timeout",
        "probed": True,
        "responded": False,
        "ssh_open": None,
        "elapsed_ms": 0,
    }


class TempEnvironmentMixin:
    """给测试造一套临时 VMware 文件；一份都不来自真实机器。"""

    def make_environment(self, *, with_vmrun=False, tmp_suffix="") -> svc.VmwareEnvironment:
        tmp = tempfile.TemporaryDirectory(prefix=f"awfm-discovery{tmp_suffix}-")
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        (base / "CentOS 10").mkdir()
        (base / "Ubuntu x64").mkdir()
        (base / "inventory.vmls").write_text(inventory_text(base), encoding="utf-8")
        (base / "vmnetdhcp.conf").write_text(VMNET_CONF, encoding="utf-8")
        (base / "vmnetdhcp.leases").write_text(LEASES, encoding="utf-8")
        (base / "CentOS 10" / CENTOS_VMX_NAME).write_text(VMX_CENTOS, encoding="utf-8")
        (base / "Ubuntu x64" / UBUNTU_VMX_NAME).write_text(VMX_UBUNTU, encoding="utf-8")
        self.base = base
        return svc.VmwareEnvironment(
            install_path="C:\\Program Files (x86)\\VMware\\VMware Workstation",
            vmrun_path=str(base / "vmrun.exe") if with_vmrun else "",
            inventory_path=str(base / "inventory.vmls"),
            dhcp_conf_path=str(base / "vmnetdhcp.conf"),
            dhcp_leases_path=str(base / "vmnetdhcp.leases"),
            notes=[],
        )


# ----------------------------------------------------------------- 纯解析


class InventoryTests(unittest.TestCase):
    def test_records_come_back_in_file_order_not_numbered_order(self):
        """段号是 2、3、1：结果必须按文件里的出现顺序，不能按序号排。"""
        entries = svc.parse_inventory(INVENTORY)
        self.assertEqual([item["display_name"] for item in entries], ["Ubuntu x64", "CentOS Stream 10", "CentOS Stream 10"])
        self.assertTrue(entries[0]["vmx"].endswith("Ubuntu x64.vmx"))
        self.assertTrue(entries[2]["vmx"].endswith("CentOS Stream 10.vmx"))

    def test_fields_other_than_the_four_we_use_are_ignored(self):
        """index0.* 与 .encoding 这类行不该变成虚拟机。"""
        entries = svc.parse_inventory(INVENTORY)
        self.assertEqual(len(entries), 3)
        for entry in entries:
            self.assertEqual(set(entry), {"vmx", "display_name", "uuid", "state", "source"})
            self.assertEqual(entry["source"], "inventory")

    def test_segment_without_a_config_file_is_skipped(self):
        """只有名字没有 config 的段没有可用的东西，跳过而不是造一条空记录。"""
        entries = svc.parse_inventory('vmlist1.DisplayName = "x"\nvmlist2.config = "a.vmx"\n')
        self.assertEqual([item["vmx"] for item in entries], ["a.vmx"])

    def test_empty_text_is_not_an_error(self):
        self.assertEqual(svc.parse_inventory(""), [])


class VmxTests(unittest.TestCase):
    def test_the_fields_we_display(self):
        info = svc.parse_vmx(VMX_CENTOS)
        self.assertEqual(info["display_name"], "CentOS Stream 10")
        self.assertEqual(info["guest_os"], "centos-64")
        self.assertEqual(info["memory_mb"], 8192)
        self.assertEqual(info["cpus"], 2)
        self.assertEqual(info["uuid"], "56 4d b1 45 70 cc 40 db-af 01 78 e2 4e 58 7b 2a")
        self.assertEqual(info["firmware"], "efi")

    def test_address_type_is_not_the_mac(self):
        """ethernet0.addressType 的值是 "generated" —— 它不是地址，不能被当成地址。"""
        nic = svc.parse_vmx(VMX_CENTOS)["nics"][0]
        self.assertEqual(nic["mac"], "00:0c:29:58:7b:2a")
        self.assertEqual(nic["connection_type"], "nat")
        self.assertEqual(nic["virtual_dev"], "e1000")

    def test_disabled_nic_is_dropped(self):
        """present = FALSE 的网卡（样本里的 ethernet1）不该出现在结果里。"""
        nics = svc.parse_vmx(VMX_CENTOS)["nics"]
        self.assertEqual([nic["index"] for nic in nics], [0])

    def test_device_keys_with_a_colon_are_ignored(self):
        """scsi0:0.present 这类带冒号的键不会被当成设置（正则的键名里没有冒号）。"""
        info = svc.parse_vmx('displayName = "x"\nscsi0:0.displayName = "假的"\n')
        self.assertEqual(info["display_name"], "x")

    def test_missing_numbers_are_none_not_zero(self):
        """规格读不出来就是「不知道」（None），不能假装是 0 核 0 内存。"""
        info = svc.parse_vmx('displayName = "x"\nmemsize = "abc"\n')
        self.assertIsNone(info["memory_mb"])
        self.assertIsNone(info["cpus"])


class LeaseTests(unittest.TestCase):
    def test_all_four_records_in_file_order(self):
        entries = svc.parse_leases(LEASES)
        self.assertEqual([item["ip"] for item in entries], [
            "192.168.170.129", "192.168.170.130", "192.168.170.128", "192.168.170.129",
        ])
        self.assertEqual(entries[1]["hostname"], "hadoop01")
        self.assertEqual(entries[0]["hostname"], "aimu0721-VMware-Virtual-Platform")
        self.assertEqual(entries[2]["mac"], "00:0c:29:57:cf:b0")

    def test_times_in_the_file_are_utc(self):
        """租约文件头写明时间都是 UTC。判断过期必须按 UTC，否则夏令时会差一小时。"""
        entry = svc.parse_leases(LEASES)[0]
        self.assertEqual(entry["starts"], "2026/10/15 08:50:20")
        self.assertEqual(entry["ends"], "2026/10/15 09:20:20")
        expected = svc.datetime.datetime(2026, 10, 15, 9, 20, 20, tzinfo=svc.datetime.timezone.utc).timestamp()
        self.assertEqual(entry["ends_at"], expected)
        # 同一时刻的两种判断：早一秒没过期，晚一秒过期。
        self.assertFalse(svc.parse_leases(LEASES, now=expected - 1)[0]["expired"])
        self.assertTrue(svc.parse_leases(LEASES, now=expected + 1)[0]["expired"])

    def test_expired_is_none_when_there_is_no_end_time(self):
        """没有 ends 就说「不知道」，不能说「已过期」。"""
        entry = svc.parse_leases('lease 10.0.0.1 {\n\thardware ethernet 00:0c:29:00:00:01;\n}\n')[0]
        self.assertIsNone(entry["ends_at"])
        self.assertIsNone(entry["expired"])

    def test_latest_by_mac_keeps_the_last_record(self):
        """追加日志：同一个 MAC 出现两次，只有最后一条算数。"""
        latest = svc.latest_by_mac(svc.parse_leases(LEASES))
        self.assertEqual(len(latest), 3)
        self.assertEqual(latest["00:0c:29:62:01:4d"]["ip"], "192.168.170.129")
        self.assertEqual(latest["00:0c:29:62:01:4d"]["ends"], "2026/10/15 09:23:51")


class VmnetConfTests(unittest.TestCase):
    def test_two_subnets_with_pool_and_gateway(self):
        parsed = svc.parse_vmnet_conf(VMNET_CONF)
        by_name = {item["vmnet"]: item for item in parsed["subnets"]}
        self.assertEqual(set(by_name), {"VMnet1", "VMnet8"})
        vmnet8 = by_name["VMnet8"]
        self.assertEqual((vmnet8["network"], vmnet8["prefix"]), ("192.168.170.0", 24))
        self.assertEqual((vmnet8["range_start"], vmnet8["range_end"]), ("192.168.170.128", "192.168.170.254"))
        self.assertEqual(vmnet8["gateway"], "192.168.170.2")

    def test_host_block_does_not_overwrite_the_subnet_gateway(self):
        """host VMnet8 块里也有 option domain-name-servers，值是 0.0.0.0。"""
        parsed = svc.parse_vmnet_conf(VMNET_CONF)
        by_name = {item["vmnet"]: item for item in parsed["subnets"]}
        self.assertEqual(by_name["VMnet1"]["gateway"], "192.168.11.1")
        self.assertEqual(parsed["hosts"]["VMnet1"], "192.168.11.1")
        self.assertEqual(parsed["hosts"]["VMnet8"], "192.168.170.1")

    def test_host_address_comes_from_the_host_block(self):
        """本机网卡地址来自 host 块，不是网段里的第一个地址。"""
        parsed = svc.parse_vmnet_conf(VMNET_CONF)
        for item in parsed["subnets"]:
            self.assertEqual(item["host_address"], parsed["hosts"][item["vmnet"]])

    def test_vmnet_number_comes_from_the_comment_not_the_address(self):
        """用户可以把 VMnet8 改成别的网段，所以编号只认注释里的段号。"""
        text = "# Virtual ethernet segment 3\nsubnet 192.168.170.0 netmask 255.255.255.0 {\n\toption domain-name-servers 192.168.170.2;\n}\n"
        subnets = svc.parse_vmnet_conf(text)["subnets"]
        self.assertEqual(subnets[0]["vmnet"], "VMnet3")


class NeighborParsingTests(unittest.TestCase):
    def test_csv_uses_the_header_names_so_column_order_does_not_matter(self):
        shuffled = '"State","IPAddress","LinkLayerAddress"\n"Reachable","192.168.170.128","00-0C-29-58-7B-2A"\n'
        entries = svc.parse_neighbors_csv(shuffled)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["ip"], "192.168.170.128")
        self.assertEqual(entries[0]["mac"], "00:0c:29:58:7b:2a")
        self.assertEqual(entries[0]["state"], "Reachable")

    def test_plain_neighbor_output_keeps_states(self):
        entries = svc.parse_neighbors_csv(NEIGHBORS_CSV)
        self.assertEqual([item["state"] for item in entries], ["Reachable", "Stale", "Permanent", "Unreachable"])
        self.assertEqual(entries[0]["source"], "neighbor")

    def test_csv_without_the_three_columns_is_not_usable(self):
        """表头认不出来就返回空表 —— 宁可没有，也不要编一份出来。"""
        self.assertEqual(svc.parse_neighbors_csv('"a","b"\n"1","2"\n'), [])
        self.assertEqual(svc.parse_neighbors_csv(""), [])

    def test_arp_fallback_has_no_states(self):
        entries = svc.parse_arp(ARP)
        self.assertEqual([item["ip"] for item in entries], ["192.168.170.128", "192.168.170.255"])
        for entry in entries:
            self.assertEqual(entry["state"], "Unknown")
            self.assertEqual(entry["source"], "arp")


class HelperTests(unittest.TestCase):
    def test_mac_is_normalized_from_both_separators(self):
        self.assertEqual(svc._normalize_mac("00-0C-29-58-7B-2A"), "00:0c:29:58:7b:2a")
        self.assertEqual(svc._normalize_mac("0:c:29:58:7b:2a"), "00:0c:29:58:7b:2a")
        self.assertEqual(svc._normalize_mac(""), "")
        self.assertEqual(svc._normalize_mac("不是 MAC"), "")

    def test_unusable_addresses(self):
        for ip in ("224.0.0.251", "127.0.0.1", "0.0.0.0", "192.168.11.0", "192.168.11.255", "fe80::1", ""):
            self.assertFalse(svc._is_usable_host_address(ip), ip)
        self.assertTrue(svc._is_usable_host_address("192.168.170.128"))


class ProbeTests(unittest.TestCase):
    """探测的四种结局。用假 socket 驱动，一次也不真的连出去。"""

    def probe_with(self, behaviour):
        class FakeSocket:
            def __init__(self, family, kind):
                self.family, self.kind = family, kind
                self.timeout = None
                self.closed = False

            def settimeout(self, value):
                self.timeout = value

            def connect(self, address):
                behaviour(address)

            def close(self):
                self.closed = True

        fake_module = mock.MagicMock()
        fake_module.socket = FakeSocket
        fake_module.AF_INET = 2
        fake_module.SOCK_STREAM = 1
        fake_module.timeout = TimeoutError
        with mock.patch.object(svc, "socket", fake_module):
            return svc.probe_address("192.168.170.128", timeout=0.4)

    def test_open(self):
        result = self.probe_with(lambda address: None)
        self.assertEqual(result["state"], "open")
        self.assertTrue(result["ssh_open"])
        self.assertTrue(result["responded"])
        self.assertTrue(result["probed"])
        self.assertEqual(result["port"], 22)

    def test_refused_means_online_without_ssh(self):
        def refuse(address):
            raise OSError(errno.ECONNREFUSED, "Connection refused")

        result = self.probe_with(refuse)
        self.assertEqual(result["state"], "refused")
        self.assertFalse(result["ssh_open"])
        self.assertTrue(result["responded"], "回了 RST 就说明这台机器是活的")

    def test_timeout_is_not_offline(self):
        def timed_out(address):
            raise TimeoutError("timed out")

        result = self.probe_with(timed_out)
        self.assertEqual(result["state"], "timeout")
        self.assertFalse(result["responded"])
        # 地址一级的 ssh_open 只回答「SSH 通不通」，是确定的 False（确实没通）。
        # 「不知道有没有 SSH」是 _not_probed 与虚拟机一级的 ssh_open 才表达的东西。
        self.assertFalse(result["ssh_open"])

    def test_address_that_was_never_probed_is_unknown_not_false(self):
        """没探测过就是「不知道」——这一点与「探测了没通」必须分开。"""
        result = svc._not_probed("192.168.170.128")
        self.assertFalse(result["probed"])
        self.assertEqual(result["state"], "not_probed")
        self.assertIsNone(result["responded"])
        self.assertIsNone(result["ssh_open"], "没探测过就必须是「不知道」")
        self.assertIsNone(result["elapsed_ms"])

    def test_unreachable_is_distinguished_from_timeout(self):
        """网络不可达与「对方不吭声」是两件事：前者是路由问题，后者可能是防火墙。"""

        def unreachable(address):
            raise OSError(errno.EHOSTUNREACH, "No route to host")

        self.assertEqual(self.probe_with(unreachable)["state"], "unreachable")

    def test_other_os_errors_count_as_no_answer(self):
        def other(address):
            raise OSError(errno.ENETRESET, "reset")

        self.assertEqual(self.probe_with(other)["state"], "timeout")


# ----------------------------------------------------------- collect 的融合


class CollectTests(TempEnvironmentMixin, unittest.TestCase):
    """一整套假环境 + 注入的探测函数，看三种状态能不能分开。"""

    NEIGHBORS = [
        {"ip": "192.168.170.128", "mac": "00:0c:29:58:7b:2a", "state": "Reachable", "source": "neighbor"},
        {"ip": "192.168.170.129", "mac": "00:0c:29:62:01:4d", "state": "Stale", "source": "neighbor"},
        {"ip": "192.168.170.2", "mac": "", "state": "Unreachable", "source": "neighbor"},
        {"ip": "192.168.170.50", "mac": "00:0c:29:aa:bb:cc", "state": "Reachable", "source": "neighbor"},
        {"ip": "224.0.0.251", "mac": "01:00:5e:00:00:fb", "state": "Permanent", "source": "neighbor"},
    ]
    #: 每个地址的探测结论：.128 能连、.129 在线但没 SSH、.130 与 .50 无响应。
    PROBES = {
        "192.168.170.128": ("open", True, True),
        "192.168.170.129": ("refused", True, False),
        "192.168.170.130": ("timeout", False, None),
        "192.168.170.50": ("timeout", False, None),
    }

    def setUp(self):
        super().setUp()
        self.probed: list[str] = []
        self.env = self.make_environment(with_vmrun=True)
        self.patch = mock.patch.object(
            svc, "read_neighbors", lambda **kwargs: (copy.deepcopy(self.NEIGHBORS), neighbor_report(len(self.NEIGHBORS)))
        )
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def run_collect(self, *, vmrun=True, **overrides):
        config = make_config(**overrides)

        def probe(ip, *, port=svc.SSH_PORT, timeout=1.0):
            self.probed.append(ip)
            state, responded, ssh_open = self.PROBES.get(ip, ("timeout", False, None))
            return {
                "ip": ip,
                "port": port,
                "state": state,
                "probed": True,
                "responded": responded,
                "ssh_open": ssh_open,
                "elapsed_ms": 1,
            }

        def guest_ip(path):
            if path.endswith(CENTOS_VMX_NAME):
                return "192.168.170.128", ""
            return "", "没有取到客户机自报的 IP。"

        env = self.env if vmrun else self.make_environment(with_vmrun=False, tmp_suffix="-novmrun")
        running = [str(self.base / "CentOS 10" / CENTOS_VMX_NAME)] if vmrun else []
        with mock.patch.object(svc, "read_running_vms", lambda environment: (list(running), {
            "name": "vmrun", "label": "vmrun", "state": "ok", "count": len(running),
            "detail": "来自 vmrun list。",
        })):
            return svc.collect(config, env=env, probe=probe, guest_ip=guest_ip)

    @staticmethod
    def by_file(result, filename):
        for vm in result["vms"]:
            if str(vm["vmx"]).endswith(filename):
                return vm
        raise AssertionError(f"结果里没有 {filename}：" + json.dumps([vm["vmx"] for vm in result["vms"]], ensure_ascii=False))

    def test_three_states_are_kept_apart(self):
        result = self.run_collect()

        running_vm = self.by_file(result, CENTOS_VMX_NAME)
        self.assertEqual(running_vm["state"], "running")
        self.assertTrue(running_vm["running"])
        self.assertEqual(running_vm["running_source"], "vmrun")
        # ① SSH 可用：地址是自己报的，端口开着
        self.assertEqual(running_vm["ip"], "192.168.170.128")
        self.assertEqual(running_vm["ip_source"], "guest")
        self.assertEqual(running_vm["answer_state"], "ssh_open")
        self.assertIs(running_vm["ssh_open"], True)

        stopped_vm = self.by_file(result, UBUNTU_VMX_NAME)
        self.assertEqual(stopped_vm["state"], "stopped")
        self.assertFalse(stopped_vm["running"])
        # ② 地址在线但没有 SSH：探测被拒绝，结论必须是 online，而不是 ssh_open
        self.assertEqual(stopped_vm["answer_state"], "online")
        self.assertIs(stopped_vm["ssh_open"], False, "探测过了、没连上，才是确定的 False")
        self.assertTrue(any(item["ssh_state"] == "refused" for item in stopped_vm["addresses"]))

        gone_vm = self.by_file(result, GONE_VMX_NAME)
        self.assertFalse(gone_vm["vmx_exists"])
        self.assertEqual(gone_vm["state"], "stopped")
        # ③ 一个地址都没有：不知道，不是「连不上」
        self.assertEqual(gone_vm["answer_state"], "unknown_address")
        self.assertIsNone(gone_vm["ssh_open"], "没有地址可探测时必须是「不知道」")
        self.assertEqual(gone_vm["addresses"], [])
        self.assertIn("配置文件不在磁盘上（可能已被删除或移动）。", gone_vm["notes"])

    def test_only_the_expected_addresses_are_probed(self):
        """探测目标必须落在已知网段里，且跳过本机网卡与网关。"""
        result = self.run_collect()
        self.assertEqual(sorted(self.probed), ["192.168.170.128", "192.168.170.129", "192.168.170.130", "192.168.170.50"])
        self.assertEqual(result["probes"]["planned"], 4)
        self.assertEqual(result["probes"]["done"], 4)
        self.assertEqual(result["probes"]["open"], 1)
        self.assertEqual(result["probes"]["responded"], 2)

    def test_host_and_gateway_addresses_are_not_candidates(self):
        """本机网卡 192.168.170.1 与网关 192.168.170.2 不该被列成候选。"""
        result = self.run_collect()
        listed = {item["ip"] for item in result["addresses"]}
        self.assertEqual(listed, {"192.168.170.50"})
        for ip in ("192.168.170.1", "192.168.170.2", "192.168.11.1"):
            self.assertNotIn(ip, self.probed)
            self.assertNotIn(ip, {item["ip"] for item in result["addresses_all"]})

    def test_the_same_vmx_twice_in_the_inventory_is_merged_and_said_so(self):
        """清单里同一个 .vmx 出现两次（实测发生过）：只能算一台，而且要说出来。"""
        centos = self.base / "CentOS 10" / CENTOS_VMX_NAME
        inventory = self.base / "inventory.vmls"
        inventory.write_text(
            inventory_text(self.base).replace(
                'index.count = "3"',
                f'vmlist4.config = "{centos}"\nvmlist4.DisplayName = "CentOS Stream 10"\nindex.count = "4"',
            ),
            encoding="utf-8",
        )
        result = self.run_collect()
        same = [vm for vm in result["vms"] if str(vm["vmx"]).endswith(CENTOS_VMX_NAME)]
        self.assertEqual(len(same), 1, "同一个配置文件只能出一条记录")
        self.assertEqual(len(result["vms"]), 3)
        self.assertIn("清单里有 2 条记录指向同一个配置文件，已合并。", same[0]["notes"])

    def test_notes_explain_what_was_left_out(self):
        """过滤掉了什么必须说出来，而且同一条不能算两次。"""
        result = self.run_collect()
        notes = result["notes"]
        self.assertIn("邻居表里有 1 条记录被过滤（不可达、组播或广播地址）。", notes)
        self.assertIn("邻居表里有 1 条是本机虚拟网卡或网关的地址，已跳过（它们不是待连接的机器）。", notes)
        # 过期租约的提醒挂在对应那台虚拟机下面，不在整轮扫描的 notes 里。
        self.assertIn("租约地址 192.168.170.130 已过期，只能当作线索。", self.by_file(result, CENTOS_VMX_NAME)["notes"])
        self.assertIn("租约地址 192.168.170.129 已过期，只能当作线索。", self.by_file(result, UBUNTU_VMX_NAME)["notes"])

    def test_counts_match_the_machine_we_know(self):
        """这台机器上已知的事实：3 台虚拟机、1 台在跑、1 台能连 SSH。"""
        counts = self.run_collect()["counts"]
        self.assertEqual(counts["vms"], 3)
        self.assertEqual(counts["running"], 1)
        self.assertEqual(counts["stopped"], 2)
        self.assertEqual(counts["unknown_state"], 0)
        self.assertEqual(counts["with_address"], 2)
        self.assertEqual(counts["ssh_open"], 1)
        self.assertEqual(counts["online"], 2, "能连 SSH 的那台加上「在线但没 SSH」的那台")
        self.assertEqual(counts["other_addresses"], 1)

    def test_without_vmrun_every_state_is_unknown(self):
        """读不到运行状态时说「未知」，不能说「已关机」——这两件事完全不同。"""
        result = self.run_collect(vmrun=False)
        self.assertEqual([vm["state"] for vm in result["vms"]], ["unknown", "unknown", "unknown"])
        for vm in result["vms"]:
            self.assertIsNone(vm["running"])
        self.assertEqual(result["counts"]["stopped"], 0)
        self.assertEqual(result["counts"]["unknown_state"], 3)
        self.assertIn("没有 vmrun，所有虚拟机的运行状态都是「未知」——不是「已关机」。", result["notes"])

    def test_probing_can_be_switched_off(self):
        """关掉探测之后，地址是「未探测」（不知道），不能变成「连不上」。"""
        result = self.run_collect(probe_ssh=False)
        self.assertEqual(self.probed, [])
        self.assertFalse(result["probes"]["enabled"])
        self.assertEqual(result["probes"]["done"], 0)
        for vm in result["vms"]:
            for address in vm["addresses"]:
                self.assertEqual(address["ssh_state"], "not_probed")
                self.assertIsNone(address["ssh_open"])
        running_vm = self.by_file(result, CENTOS_VMX_NAME)
        self.assertEqual(running_vm["answer_state"], "not_probed")
        self.assertIsNone(running_vm["ssh_open"])
        self.assertIn("探测已在配置里关闭（discovery.probe_ssh），只报告地址来自哪里。", result["notes"])

    def test_cancelled_before_probing_reports_interrupted(self):
        """用户点了中止：状态是 interrupted，而且一个地址都不该被探测。"""
        config = make_config()
        result = svc.collect(config, env=self.env, probe=lambda ip, **kwargs: fake_probe(ip), is_cancelled=lambda: True)
        self.assertTrue(result["interrupted"])
        self.assertEqual(result["probes"]["done"], 0)
        self.assertIn("扫描已中止（用户取消），没有探测任何地址。", result["notes"])

    def test_limits_are_reported(self):
        result = self.run_collect()
        self.assertEqual(result["limits"]["probe_timeout_seconds"], 1.0)
        self.assertEqual(result["limits"]["max_probes"], 512)
        self.assertTrue(result["limits"]["enabled"])

    def test_max_probes_truncates_and_says_so(self):
        result = self.run_collect(max_probes=2)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["probes"]["done"], 2)
        self.assertIn("地址太多，只探测了前 2 个（上限 discovery.max_probes）。", result["truncated_reason"])

    def test_probe_that_raises_does_not_break_the_whole_scan(self):
        """单个地址探测出错只影响那一个地址。"""

        def broken(ip, *, port=svc.SSH_PORT, timeout=1.0):
            if ip.endswith(".129"):
                raise OSError("boom")
            return fake_probe(ip)

        result = svc.collect(make_config(), env=self.env, probe=broken)
        # done 记的是「试过的地址数」，不是「成功的地址数」：出错的那一个也算试过。
        self.assertEqual(result["probes"]["done"], 4)
        online = [item for item in result["addresses_all"] if item["ip"].endswith(".129")]
        self.assertEqual(online[0]["ssh_state"], "error")


# ------------------------------------------------------------- 注册处与状态机


class RegistryTests(TempEnvironmentMixin, unittest.TestCase):
    """扫描状态机：并发、取消、保留策略、失败。全在内存里。"""

    def setUp(self):
        super().setUp()
        self.env = self.make_environment()
        self.patch = mock.patch.object(svc, "read_neighbors", lambda **kwargs: ([], neighbor_report(0, "empty")))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        running = mock.patch.object(svc, "read_running_vms", lambda environment: ([], {
            "name": "vmrun", "label": "vmrun", "state": "unavailable", "count": 0, "detail": "",
        }))
        running.start()
        self.addCleanup(running.stop)

    def registry(self, **kwargs):
        kwargs.setdefault("environment", self.env)
        kwargs.setdefault("probe", fake_probe)
        return svc.DiscoveryRegistry(make_config(), **kwargs)

    def test_busy_while_one_is_running(self):
        entered = threading.Event()
        release = threading.Event()

        def blocking(**kwargs):
            entered.set()
            release.wait(10.0)
            return [], neighbor_report(0, "empty")

        with mock.patch.object(svc, "read_neighbors", blocking):
            registry = self.registry()
            first = registry.start()
            self.addCleanup(lambda: (release.set(), first.wait(10.0)))
            self.assertTrue(entered.wait(10.0), "扫描没有走到邻居表这一步")
            with self.assertRaises(DiscoveryBusy) as caught:
                registry.start()
        self.assertEqual(caught.exception.code, "discovery_busy")
        self.assertEqual(caught.exception.http_status, 409)
        self.assertEqual(registry.active_count(), 1)

    def test_cancel_from_a_running_stage_is_reported_as_cancelled(self):
        entered = threading.Event()
        release = threading.Event()

        def blocking(**kwargs):
            entered.set()
            release.wait(10.0)
            return [], neighbor_report(0, "empty")

        with mock.patch.object(svc, "read_neighbors", blocking):
            registry = self.registry()
            scan = registry.start()
            self.addCleanup(lambda: (release.set(), scan.wait(10.0)))
            self.assertTrue(entered.wait(10.0), "扫描没有走到邻居表这一步")
            self.assertTrue(scan.cancel(), "正在跑的扫描必须接受取消")
            release.set()
            scan.wait(10.0)

        snapshot = scan.snapshot()
        self.assertEqual(snapshot["status"], "cancelled")
        # 阶段在收尾时明确收成 done，否则会停在最后一个动作（probe / neighbors）上，
        # 界面上看起来像卡住了。
        self.assertEqual(snapshot["stage"], "done")
        self.assertTrue(snapshot["interrupted"])
        self.assertEqual(snapshot["probes"]["done"], 0)
        self.assertIn("扫描已中止（用户取消），没有探测任何地址。", snapshot["notes"])
        self.assertEqual(registry.active_count(), 0)
        # 槽位要真的空出来：下一次扫描不能因为上一次取消而吃 409
        again = registry.start()
        again.wait(10.0)
        self.assertEqual(again.snapshot()["status"], "done")

    def test_start_is_refused_when_discovery_is_disabled(self):
        registry = svc.DiscoveryRegistry(make_config(enabled=False), environment=self.env, probe=fake_probe)
        with self.assertRaises(ValidationError) as caught:
            registry.start()
        self.assertIn("在线虚拟机发现在配置里是关闭的", str(caught.exception))

    def test_unknown_scan_id(self):
        registry = self.registry()
        with self.assertRaises(PathNotFound) as caught:
            registry.get("0123456789abcdef")
        self.assertEqual(caught.exception.code, "path_not_found")

    def test_only_the_most_recent_scans_are_kept(self):
        registry = self.registry(max_kept=2)
        scans = []
        for _ in range(3):
            scan = registry.start()
            scan.wait(10.0)
            scans.append(scan)
        self.assertEqual(scans[0].snapshot()["status"], "done")
        self.assertEqual(scans[0].snapshot()["stage"], "done")
        with self.assertRaises(PathNotFound):
            registry.get(scans[0].id)
        registry.get(scans[1].id)
        registry.get(scans[2].id)

    def test_a_failed_scan_keeps_its_error(self):
        with mock.patch.object(svc, "collect", side_effect=RuntimeError("boom")):
            registry = self.registry()
            scan = registry.start()
            scan.wait(10.0)
        snapshot = scan.snapshot()
        self.assertEqual(snapshot["status"], "failed")
        # 失败时故意不把阶段收成 done：留在当时那一步，好看出是卡在哪。
        self.assertEqual(snapshot["stage"], "starting")
        # error 是一个结构（code/message/detail），不是一句话。
        self.assertEqual(snapshot["error"]["code"], "internal_error")
        self.assertIn("boom", snapshot["error"]["message"])
        self.assertFalse(snapshot["running"])

    def test_shutdown_cancels_everything(self):
        registry = self.registry()
        scan = registry.start()
        registry.shutdown(timeout=10.0)
        self.assertFalse(scan.is_running)

    def test_environment_summary_lists_every_source(self):
        summary = self.registry().environment()
        self.assertEqual(
            [item["name"] for item in summary["sources"]],
            ["inventory", "vmrun", "vmnet", "lease", "neighbor", "process"],
        )
        self.assertTrue(summary["enabled"])
        process = [item for item in summary["sources"] if item["name"] == "process"][0]
        self.assertEqual(process["state"], "denied", "读 VMware 进程命令行需要管理员权限，这一条永远是「已跳过」")
        self.assertEqual(summary["limits"]["max_probes"], 512)
