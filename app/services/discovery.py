"""在线虚拟机自动发现（阶段五，决策 D-018）。

## 这个模块解决什么

用户要在 AWFM 里连一台虚拟机，得先自己查出它的 IP 和端口。本模块把这件事变成
「点一下扫描」，但**只做到「提供候选」为止**：不自动创建连接，不自动信任主机指纹，
不猜用户名密码。发现结果只是把用户在别处要翻的东西摆到眼前。

## 为什么只读本地信息 + 有限探测

「扫一遍 192.168.0.0/16 找 22 端口」能发现更多机器，但它同时也是端口扫描器的行为：
越界访问未授权网络、给别人的网络留日志、还可能触发对方的入侵检测。所以范围被钉死在
「本机虚拟化软件自己记录的网段」。五层取材，每层都带来源与状态：

1. **VMware 清单**（inventory.vmls）—— 有哪些虚拟机。可能指向已删除的 .vmx。
2. **vmrun list** —— 哪些真正在运行。**可选依赖**：没有 vmrun 时运行状态显示「未知」
   并写明原因，而不是猜。
3. **.vmx 配置** —— 名称、客户机系统、内存、网卡 MAC、网络类型。
4. **vmnetdhcp.conf / vmnetdhcp.leases** —— 已知虚拟网段、地址池、历史租约。
   租约是**历史**不是现状（实测本机 4 条租约全部过期），所以它只作为地址线索。
5. **系统邻居表 + 仅限已知网段的 TCP 22 探测** —— 地址是否在线、SSH 是否可用。

关于「读进程命令行」这条路：``vmware-vmx.exe`` 的命令行里带着 .vmx 路径，看起来是
最直接的运行状态来源，但实测（非管理员）读出来是空的。需要更高权限的来源一律跳过
并解释原因，所以这里把这件事记进 sources，界面上能看见「为什么这条来源没有数据」。

## 三种状态必须分开（任务书明确要求）

- **发现了虚拟机**：清单/.vmx 里有这条记录 —— ``vms``。
- **地址在线**：探测到对方主机有响应（连接被拒绝也算：内核回了 RST，说明主机在）。
- **SSH 可用**：22 端口真的接受连接。

一台虚拟机可以有地址但没 SSH（最常见的「还没装 openssh-server」），
也可以完全没有地址（关机、或没有 DHCP 租约、也没进邻居表）。这三件事在数据里是
三个独立字段，界面分三列显示，不允许合并成一个「可用/不可用」。
"""

from __future__ import annotations

import csv
import datetime
import errno
import io
import ipaddress
import logging
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.core.config import AppConfig, DiscoveryConfig
from app.core.errors import AwfmError, DiscoveryBusy, PathNotFound, ValidationError
from app.utils.paths import safe_for_log

logger = logging.getLogger("awfm")

#: SSH 默认端口。发现只探测这一个端口，不做端口扫描。
SSH_PORT = 22

#: 读 vmrun 输出的上限。vmrun list 通常几百毫秒返回。
VMRUN_TIMEOUT = 20.0

#: 查客户机 IP 的超时。vmrun getGuestIPAddress 在装了 VMware Tools 时约 0.5 秒返回，
#: 没装 Tools 时会挂很久，所以必须自己掐表。
GUEST_IP_TIMEOUT = 5.0

#: 「其它地址」最多列多少条。邻居表里常有几十条历史记录，全列出来只会淹没有用信息。
MAX_OTHER_ADDRESSES = 20

#: 邻居表里视为「最近见过」的状态。Permanent 多为组播/广播条目，靠地址过滤掉。
NEIGHBOR_ALIVE_STATES = frozenset({"Reachable", "Stale", "Delay", "Probe", "Permanent"})
NEIGHBOR_DEAD_STATES = frozenset({"Unreachable", "Incomplete"})

_NEIGHBOR_COMMAND = (
    "Get-NetNeighbor -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
    "Select-Object IPAddress,LinkLayerAddress,State | ConvertTo-Csv -NoTypeInformation"
)

_INVENTORY_RE = re.compile(r'^(vmlist\d+)\.([A-Za-z]+)\s*=\s*"(.*)"\s*$')
_VMX_RE = re.compile(r'^([A-Za-z0-9_.\-]+)\s*=\s*"(.*)"\s*$')
_VMX_NIC_RE = re.compile(r"^ethernet(\d+)\.(.+)$")
_LEASE_OPEN_RE = re.compile(r"^lease\s+(\d{1,3}(?:\.\d{1,3}){3})\s*\{")
_LEASE_TIME_RE = re.compile(r"^(starts|ends)\s+\d\s+(\d{4})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})\s*;")
_LEASE_MAC_RE = re.compile(r"^hardware\s+ethernet\s+([0-9a-fA-F:]{17})\s*;")
_LEASE_HOST_RE = re.compile(r'^client-hostname\s+"?([^";]*)"?\s*;')
_SUBNET_RE = re.compile(r"^subnet\s+(\d{1,3}(?:\.\d{1,3}){3})\s+netmask\s+(\d{1,3}(?:\.\d{1,3}){3})\s*\{")
_RANGE_RE = re.compile(r"^range\s+(\S+)\s+(\S+)\s*;")
_DNS_RE = re.compile(r"^option\s+domain-name-servers\s+([^;]+);")
_SEGMENT_RE = re.compile(r"^#\s*Virtual ethernet segment\s+(\d+)", re.IGNORECASE)
_VMNET_HOST_RE = re.compile(r"^host\s+(\S+)\s*\{")
_FIXED_ADDRESS_RE = re.compile(r"^fixed-address\s+(\S+)\s*;")
_ARP_RE = re.compile(
    r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9a-fA-F]{2}(?:-[0-9a-fA-F]{2}){5})\s+(\S+)\s*$"
)


# --------------------------------------------------------------------- 小工具


def _is_file(path: str) -> bool:
    if not path:
        return False
    try:
        return Path(path).is_file()
    except OSError:  # pragma: no cover - 路径里有非法字符等
        return False


def _as_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _normalize_mac(value: str) -> str:
    """统一成小写的 aa:bb:cc:dd:ee:ff。邻居表用 -，.vmx 与租约用 :。"""
    text = (value or "").strip().lower().replace("-", ":").replace(".", ":")
    parts = [part for part in text.split(":") if part]
    if len(parts) != 6:
        return ""
    return ":".join(part.rjust(2, "0") for part in parts)


def _normalize_path(value: str) -> str:
    """用于比较「同一个 .vmx」：Windows 大小写不敏感，斜杠与反斜杠都可能出现。"""
    if not value:
        return ""
    return os.path.normcase(os.path.normpath(value.replace("/", os.sep)))


def _is_usable_host_address(ip: str) -> bool:
    """过滤掉组播、广播、回环与「全零」这类不可能是虚拟机的地址。"""
    try:
        address = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    if address.is_multicast or address.is_loopback or address.is_unspecified:
        return False
    if str(address).endswith(".255") or str(address).endswith(".0"):
        return False
    return True


def _source(name: str, label: str) -> dict[str, Any]:
    return {"name": name, "label": label, "state": "ok", "count": 0, "detail": ""}


def _source_ok(report: dict[str, Any], count: int, detail: str) -> dict[str, Any]:
    report.update(
        state="ok" if count else "empty",
        count=count,
        detail=detail,
    )
    return report


def _source_fail(report: dict[str, Any], state: str, detail: str) -> dict[str, Any]:
    report.update(state=state, count=0, detail=detail)
    return report


def _read_text(path: str) -> tuple[str | None, str, str]:
    """读一个本地文本文件。vmx 与清单是 UTF-8，但可能有坏字节，所以用 replace。"""
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as handle:
            return handle.read(), "ok", ""
    except FileNotFoundError:
        return None, "missing", f"文件不存在：{path}"
    except PermissionError:
        return None, "denied", f"没有权限读取：{path}"
    except OSError as exc:
        return None, "error", f"读取失败：{path}（{exc}）"


def _run(command: list[str], *, timeout: float) -> tuple[str | None, str]:
    """跑一个本地命令并取回 stdout。

    这个模块**只在本地**执行两类命令：vmrun（VMware 自带）与 powershell/arp（读邻居表）。
    没有任何一条会连到远端，也没有任何一条会修改系统状态（不碰防火墙、路由、网卡、DHCP）。
    """
    flags = 0
    if sys.platform == "win32":
        # 每次扫描都弹一个黑窗口是不可接受的；CREATE_NO_WINDOW 让它安静地跑。
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            creationflags=flags,
            check=False,
        )
    except FileNotFoundError:
        return None, f"找不到可执行文件：{command[0]}"
    except subprocess.TimeoutExpired:
        return None, f"命令超时（{timeout:g} 秒）：{os.path.basename(command[0])}"
    except OSError as exc:  # pragma: no cover - 极少见
        return None, f"无法执行命令：{exc}"
    output = (completed.stdout or b"").decode("utf-8", errors="replace")
    if completed.returncode != 0 and not output.strip():
        error = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
        return None, f"命令返回 {completed.returncode}：{error[:200] or '没有输出'}"
    return output, ""


# ------------------------------------------------------------------ 解析函数
#
# 下面这一组都是纯函数：输入是文件内容，输出是结构化数据。这样单元测试可以用
# 真实格式的样本字符串覆盖每一处边角，而不必在测试机上装一套 VMware。


def parse_inventory(text: str) -> list[dict[str, Any]]:
    """解析 VMware 清单。

    格式是 INI 风格，但段名是 ``vmlist1``、``vmlist2``…… 而且**不保证连续或有序**
    （实测本机顺序是 2、3、1）。所以按出现顺序收集，不做「序号必须是 1..n」的假设。
    """
    records: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for raw in text.splitlines():
        match = _INVENTORY_RE.match(raw.strip())
        if match is None:
            continue
        key, name, value = match.group(1), match.group(2), match.group(3)
        if key not in records:
            records[key] = {}
            order.append(key)
        records[key][name] = value
    entries: list[dict[str, Any]] = []
    for key in order:
        fields = records[key]
        config_path = (fields.get("config") or "").strip()
        if not config_path:
            continue
        entries.append(
            {
                "vmx": config_path,
                "display_name": (fields.get("DisplayName") or "").strip(),
                "uuid": (fields.get("UUID") or "").strip(),
                "state": (fields.get("State") or "").strip(),
                "source": "inventory",
            }
        )
    return entries


def parse_vmx(text: str) -> dict[str, Any]:
    """解析 .vmx。只取发现要用的字段：名称、客户机系统、规格、网卡。"""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _VMX_RE.match(line)
        if match is not None:
            values[match.group(1)] = match.group(2)

    nics: dict[int, dict[str, Any]] = {}
    for key, value in values.items():
        match = _VMX_NIC_RE.match(key)
        if match is None:
            continue
        index = int(match.group(1))
        nic = nics.setdefault(
            index,
            {
                "index": index,
                "mac": "",
                "connection_type": "",
                "vnet": "",
                "virtual_dev": "",
                "present": True,
            },
        )
        field = match.group(2)
        if field == "present":
            nic["present"] = value.strip().upper() != "FALSE"
        elif field in ("generatedAddress", "address"):
            nic["mac"] = _normalize_mac(value)
        elif field == "connectionType":
            nic["connection_type"] = value.strip().lower()
        elif field == "vnet":
            nic["vnet"] = value.strip()
        elif field == "virtualDev":
            nic["virtual_dev"] = value.strip()

    return {
        "display_name": (values.get("displayName") or "").strip(),
        "guest_os": (values.get("guestOS") or "").strip(),
        "memory_mb": _as_int(values.get("memsize")),
        "cpus": _as_int(values.get("numvcpus")),
        "uuid": (values.get("uuid.bios") or "").strip(),
        "firmware": (values.get("firmware") or "").strip(),
        "nics": [nic for nic in (nics[key] for key in sorted(nics)) if nic["present"]],
    }


def parse_leases(text: str, *, now: float | None = None) -> list[dict[str, Any]]:
    """解析 vmnetdhcp.leases。

    这是 dhcpd 的**追加日志**：同一个 IP 会出现多次，最后一条才是当前状态。
    ``ends`` 全部过期说明这台虚拟机现在可能已经不在那个地址上了（实测全部过期），
    所以调用方只把它当线索，不当结论。文件里的时间都是 UTC。
    """
    current_clock = time.time() if now is None else now
    entries: list[dict[str, Any]] = []
    record: dict[str, Any] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if record is None:
            match = _LEASE_OPEN_RE.match(line)
            if match is not None:
                record = {
                    "ip": match.group(1),
                    "mac": "",
                    "hostname": "",
                    "starts": "",
                    "ends": "",
                    "ends_at": None,
                    "expired": None,
                    "source": "lease",
                }
            continue
        if line == "}":
            record["expired"] = (
                None if record["ends_at"] is None else bool(record["ends_at"] < current_clock)
            )
            entries.append(record)
            record = None
            continue
        match = _LEASE_TIME_RE.match(line)
        if match is not None:
            _, year, month, day, hour, minute, second = match.groups()
            stamp = f"{year}/{month}/{day} {hour}:{minute}:{second}"
            if match.group(1) == "starts":
                record["starts"] = stamp
            else:
                record["ends"] = stamp
                try:
                    # 租约文件里的时间一律是 UTC（文件头的注释专门强调了这一点），
                    # 所以必须用带时区的 datetime，不能用 mktime 加本地偏移 ——
                    # 后者在夏令时期间会差一小时，让「过期」判断出错。
                    record["ends_at"] = datetime.datetime(
                        int(year), int(month), int(day), int(hour), int(minute), int(second),
                        tzinfo=datetime.timezone.utc,
                    ).timestamp()
                except (ValueError, OverflowError):  # pragma: no cover - 畸形时间
                    record["ends_at"] = None
            continue
        match = _LEASE_MAC_RE.match(line)
        if match is not None:
            record["mac"] = _normalize_mac(match.group(1))
            continue
        match = _LEASE_HOST_RE.match(line)
        if match is not None:
            record["hostname"] = match.group(1).strip()
    return entries


def latest_by_mac(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """租约按 MAC 取最后一条（追加日志的语义）。"""
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        mac = entry.get("mac") or ""
        if mac:
            result[mac] = entry
    return result


def parse_vmnet_conf(text: str) -> dict[str, Any]:
    """解析 vmnetdhcp.conf：虚拟网段、地址池、网关、本机网卡地址。

    VMnet 编号来自文件里的注释（``# Virtual ethernet segment 8``），不来自网段地址 ——
    用户可以把 VMnet8 改成任何网段。
    """
    subnets: list[dict[str, Any]] = []
    hosts: dict[str, str] = {}
    segment = 0
    current: dict[str, Any] | None = None
    current_host = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            match = _SEGMENT_RE.match(line)
            if match is not None:
                segment = int(match.group(1))
            continue
        match = _SUBNET_RE.match(line)
        if match is not None:
            network, netmask = match.group(1), match.group(2)
            try:
                prefix = ipaddress.IPv4Network(f"{network}/{netmask}", strict=False).prefixlen
            except ValueError:  # pragma: no cover - 畸形网段
                prefix = None
            current = {
                "vmnet": f"VMnet{segment}" if segment else "",
                "network": network,
                "netmask": netmask,
                "prefix": prefix,
                "range_start": "",
                "range_end": "",
                "gateway": "",
                "host_address": "",
                "source": "vmnetdhcp.conf",
            }
            subnets.append(current)
            current_host = ""
            continue
        match = _VMNET_HOST_RE.match(line)
        if match is not None:
            current_host = match.group(1)
            hosts.setdefault(current_host, "")
            current = None
            continue
        match = _RANGE_RE.match(line)
        if match is not None and current is not None:
            current["range_start"], current["range_end"] = match.group(1), match.group(2)
            continue
        match = _DNS_RE.match(line)
        if match is not None and current is not None:
            current["gateway"] = match.group(1).strip()
            continue
        match = _FIXED_ADDRESS_RE.match(line)
        if match is not None and current_host:
            hosts[current_host] = match.group(1)
            continue
        if line == "}":
            current = None
            current_host = ""
    for item in subnets:
        item["host_address"] = hosts.get(item["vmnet"], "")
    return {"subnets": subnets, "hosts": hosts}


def parse_neighbors_csv(text: str) -> list[dict[str, Any]]:
    """解析 ``Get-NetNeighbor | ConvertTo-Csv`` 的输出（优先来源：带状态列）。"""
    rows = [row for row in csv.reader(io.StringIO(text)) if row]
    if len(rows) < 2:
        return []
    header = [cell.strip().lower() for cell in rows[0]]
    try:
        ip_index = header.index("ipaddress")
        mac_index = header.index("linklayeraddress")
        state_index = header.index("state")
    except ValueError:
        return []
    entries: list[dict[str, Any]] = []
    for row in rows[1:]:
        if len(row) <= max(ip_index, mac_index, state_index):
            continue
        entries.append(
            {
                "ip": row[ip_index].strip(),
                "mac": _normalize_mac(row[mac_index].strip()),
                "state": row[state_index].strip(),
                "source": "neighbor",
            }
        )
    return entries


def parse_arp(text: str) -> list[dict[str, Any]]:
    """解析 ``arp -a``（回退来源：没有状态列，只能当线索）。"""
    entries: list[dict[str, Any]] = []
    for raw in text.splitlines():
        match = _ARP_RE.match(raw)
        if match is None:
            continue
        entries.append(
            {
                "ip": match.group(1),
                "mac": _normalize_mac(match.group(2)),
                "state": "Unknown",
                "source": "arp",
            }
        )
    return entries


# ------------------------------------------------------------------ 环境定位


@dataclass
class VmwareEnvironment:
    """一台机器上 VMware 相关的路径。全部只读。"""

    install_path: str = ""
    vmrun_path: str = ""
    inventory_path: str = ""
    dhcp_conf_path: str = ""
    dhcp_leases_path: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "install_path": self.install_path,
            "vmrun_path": self.vmrun_path,
            "vmrun_available": bool(self.vmrun_path),
            "inventory_path": self.inventory_path,
            "inventory_exists": _is_file(self.inventory_path),
            "dhcp_conf_path": self.dhcp_conf_path,
            "dhcp_conf_exists": _is_file(self.dhcp_conf_path),
            "dhcp_leases_path": self.dhcp_leases_path,
            "dhcp_leases_exists": _is_file(self.dhcp_leases_path),
        }


def _vmware_install_from_registry() -> tuple[str, str]:
    """从注册表读 VMware 安装目录。读不到就返回原因，不抛异常。"""
    if sys.platform != "win32":
        return "", "当前系统不是 Windows，跳过注册表查询（可在配置里指定 discovery.vmware_root）。"
    try:
        import winreg
    except ImportError:  # pragma: no cover
        return "", "无法导入 winreg，跳过注册表查询。"
    subkeys = (
        r"SOFTWARE\VMware, Inc.\VMware Workstation",
        r"SOFTWARE\WOW6432Node\VMware, Inc.\VMware Workstation",
    )
    reason = ""
    for subkey in subkeys:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey) as key:
                value, _ = winreg.QueryValueEx(key, "InstallPath")
        except OSError as exc:
            reason = f"注册表里读不到 {subkey}：{exc.strerror or exc}"
            continue
        if isinstance(value, str) and value.strip():
            return value.strip(), ""
    return "", reason or "注册表里没有 VMware Workstation 的安装路径。"


def _find_vmrun(install_path: str) -> str:
    if not install_path:
        return ""
    for name in ("vmrun.exe", "vmrun"):
        candidate = os.path.join(install_path, name)
        if _is_file(candidate):
            return candidate
    for name in ("vmrun.exe", "vmrun"):
        candidate = os.path.join(install_path, "bin", name)
        if _is_file(candidate):
            return candidate
    return ""


def resolve_environment(config: AppConfig) -> VmwareEnvironment:
    """定位 VMware 的路径。配置里显式写了就用配置，否则自动探测。"""
    settings: DiscoveryConfig = config.discovery
    env = VmwareEnvironment()

    root = (settings.vmware_root or "").strip()
    if root:
        env.install_path = os.path.normpath(root)
        env.notes.append("VMware 安装目录来自配置 discovery.vmware_root。")
    else:
        env.install_path, reason = _vmware_install_from_registry()
        if env.install_path:
            env.notes.append("VMware 安装目录来自注册表 InstallPath。")
        elif reason:
            env.notes.append(reason)

    env.vmrun_path = _find_vmrun(env.install_path)
    if env.install_path and not env.vmrun_path:
        env.notes.append(f"{env.install_path} 下没有 vmrun，运行状态将显示为未知。")

    data_dir = (settings.vmware_data_dir or "").strip()
    if data_dir:
        base = os.path.normpath(data_dir)
        env.notes.append("VMware 数据目录来自配置 discovery.vmware_data_dir。")
    else:
        appdata = os.environ.get("APPDATA") or ""
        base = os.path.join(appdata, "VMware") if appdata else ""
        if not base:
            env.notes.append("环境变量 APPDATA 为空，找不到 VMware 清单目录。")
    if base:
        env.inventory_path = os.path.join(base, "inventory.vmls")

    program_data = os.environ.get("ProgramData") or (r"C:\ProgramData" if sys.platform == "win32" else "")
    if program_data:
        env.dhcp_conf_path = os.path.join(program_data, "VMware", "vmnetdhcp.conf")
        env.dhcp_leases_path = os.path.join(program_data, "VMware", "vmnetdhcp.leases")
    return env


# ------------------------------------------------------------------ 各来源读取


def read_inventory(env: VmwareEnvironment) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    report = _source("inventory", "VMware 清单（inventory.vmls）")
    if not env.inventory_path:
        return [], _source_fail(report, "unavailable", "没有找到 VMware 的清单目录。")
    text, state, detail = _read_text(env.inventory_path)
    if text is None:
        return [], _source_fail(report, state, detail)
    entries = parse_inventory(text)
    return entries, _source_ok(report, len(entries), f"读到 {len(entries)} 条虚拟机记录。")


def read_running_vms(env: VmwareEnvironment) -> tuple[list[str], dict[str, Any]]:
    report = _source("vmrun", "vmrun list（运行状态）")
    if not env.vmrun_path:
        return [], _source_fail(
            report,
            "unavailable",
            "找不到 vmrun，无法判断哪些虚拟机正在运行（运行状态会显示「未知」）。",
        )
    output, error = _run([env.vmrun_path, "list"], timeout=VMRUN_TIMEOUT)
    if output is None:
        return [], _source_fail(report, "error", error)
    paths: list[str] = []
    reported = 0
    for line in output.splitlines():
        text = line.strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered.startswith("total running vms"):
            digits = re.findall(r"\d+", text)
            reported = int(digits[0]) if digits else 0
            continue
        paths.append(text)
    return paths, _source_ok(report, len(paths), f"vmrun 报告 {reported or len(paths)} 台正在运行。")


def read_guest_ip(env: VmwareEnvironment, vmx_path: str, *, timeout: float = GUEST_IP_TIMEOUT) -> tuple[str, str]:
    """问 VMware Tools 要客户机当前 IP。装了 Tools 时这是最权威的来源。"""
    if not env.vmrun_path:
        return "", "没有 vmrun，无法查询客户机 IP。"
    output, error = _run([env.vmrun_path, "getGuestIPAddress", vmx_path], timeout=timeout)
    if output is None:
        return "", error or "vmrun 查询客户机 IP 失败。"
    for line in output.splitlines():
        candidate = line.strip()
        try:
            ipaddress.IPv4Address(candidate)
        except ValueError:
            continue
        return candidate, ""
    return "", "vmrun 没有返回可用地址（客户机可能没有安装 VMware Tools）。"


def read_vmnet(env: VmwareEnvironment) -> tuple[dict[str, Any], dict[str, Any]]:
    report = _source("vmnet", "virtual network（vmnetdhcp.conf）")
    if not env.dhcp_conf_path:
        return {"subnets": [], "hosts": {}}, _source_fail(report, "unavailable", "没有找到 vmnetdhcp.conf。")
    text, state, detail = _read_text(env.dhcp_conf_path)
    if text is None:
        return {"subnets": [], "hosts": {}}, _source_fail(report, state, detail)
    parsed = parse_vmnet_conf(text)
    count = len(parsed["subnets"])
    return parsed, _source_ok(report, count, f"读到 {count} 个虚拟网段。")


def read_leases(env: VmwareEnvironment) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    report = _source("lease", "DHCP 租约（vmnetdhcp.leases）")
    if not env.dhcp_leases_path:
        return [], _source_fail(report, "unavailable", "没有找到 vmnetdhcp.leases。")
    text, state, detail = _read_text(env.dhcp_leases_path)
    if text is None:
        return [], _source_fail(report, state, detail)
    entries = parse_leases(text)
    expired = sum(1 for entry in entries if entry.get("expired"))
    detail = f"读到 {len(entries)} 条租约记录（{expired} 条已过期，只作为地址线索）。"
    return entries, _source_ok(report, len(entries), detail)


def read_neighbors(*, timeout: float = VMRUN_TIMEOUT) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """读系统邻居表。优先 Get-NetNeighbor（带状态），回退 arp -a。"""
    report = _source("neighbor", "系统邻居表")
    if sys.platform != "win32":
        return [], _source_fail(report, "unavailable", "邻居表读取目前只实现了 Windows。")
    output, error = _run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _NEIGHBOR_COMMAND],
        timeout=timeout,
    )
    if output:
        entries = parse_neighbors_csv(output)
        if entries:
            return entries, _source_ok(report, len(entries), "来自 Get-NetNeighbor，带状态列。")
    fallback, fallback_error = _run(["arp", "-a"], timeout=timeout)
    if fallback:
        entries = parse_arp(fallback)
        if entries:
            return entries, _source_ok(
                report, len(entries), "Get-NetNeighbor 不可用，改用 arp -a（没有状态列）。"
            )
    return [], _source_fail(report, "error", error or fallback_error or "邻居表为空。")


# ------------------------------------------------------------------ 受限探测


def probe_address(ip: str, *, port: int = SSH_PORT, timeout: float = 1.0) -> dict[str, Any]:
    """对**单个已知候选地址**做一次 TCP 连接尝试。

    结局分四类，其中两类都算「地址在线」：

    - ``open``：22 端口接受连接 —— SSH 可用。
    - ``refused``：对方回了 RST —— 主机在线，只是没有 SSH 服务。
    - ``timeout`` / ``unreachable``：没有响应。**这不等于机器关机**（防火墙丢包也是这个结果），
      所以界面上说的是「探测无响应」而不是「离线」。
    """
    started = time.monotonic()
    state = "unreachable"
    sock: socket.socket | None = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(max(0.1, float(timeout)))
        sock.connect((ip, port))
        state = "open"
    except (socket.timeout, TimeoutError):
        state = "timeout"
    except OSError as exc:
        if exc.errno == errno.ECONNREFUSED:
            state = "refused"
        elif exc.errno in (errno.EHOSTUNREACH, errno.ENETUNREACH, errno.EHOSTDOWN, errno.ENETDOWN):
            state = "unreachable"
        else:
            state = "timeout"
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:  # pragma: no cover
                pass
    elapsed = int((time.monotonic() - started) * 1000)
    return {
        "ip": ip,
        "port": port,
        "state": state,
        "probed": True,
        "responded": state in ("open", "refused"),
        "ssh_open": state == "open",
        "elapsed_ms": elapsed,
    }


def _not_probed(ip: str, port: int = SSH_PORT) -> dict[str, Any]:
    return {
        "ip": ip,
        "port": port,
        "state": "not_probed",
        "probed": False,
        "responded": None,
        "ssh_open": None,
        "elapsed_ms": None,
    }


# -------------------------------------------------------------------- 数据融合


def _subnet_label(ip: str, subnets: list[dict[str, Any]]) -> tuple[str, bool | None]:
    """这个地址是否落在已知虚拟网段里。返回（网段标签，是否已知）。"""
    try:
        address = ipaddress.IPv4Address(ip)
    except ValueError:
        return "", None
    for item in subnets:
        prefix = item.get("prefix")
        network = item.get("network") or ""
        if prefix is None or not network:
            continue
        try:
            if address in ipaddress.IPv4Network(f"{network}/{prefix}", strict=False):
                return f"{network}/{prefix}", True
        except ValueError:  # pragma: no cover
            continue
    return "", False


def _address_entry(
    ip: str,
    *,
    mac: str,
    source: str,
    subnets: list[dict[str, Any]],
    probe_result: dict[str, Any] | None,
) -> dict[str, Any]:
    label, known = _subnet_label(ip, subnets)
    payload = probe_result or _not_probed(ip)
    return {
        "ip": ip,
        "mac": mac,
        "source": source,
        "subnet": label,
        "in_known_subnet": known,
        "port": payload.get("port", SSH_PORT),
        "probed": bool(payload.get("probed")),
        "responded": payload.get("responded"),
        "ssh_open": payload.get("ssh_open"),
        "ssh_state": payload.get("state") or "not_probed",
        "elapsed_ms": payload.get("elapsed_ms"),
    }


def _pick_primary(addresses: list[dict[str, Any]]) -> dict[str, Any] | None:
    """挑一个「主地址」给用户看。顺序：客户机自报 > 邻居表 > 租约；同级里优先能连 SSH 的。"""
    if not addresses:
        return None
    priority = {"guest": 0, "neighbor": 1, "lease": 2, "arp": 3, "vmnet": 4}
    ordered = sorted(
        addresses,
        key=lambda item: (
            priority.get(item.get("source") or "", 9),
            0 if item.get("ssh_open") else (1 if item.get("responded") else 2),
            item.get("ip") or "",
        ),
    )
    return ordered[0]


def _vm_state(addresses: list[dict[str, Any]]) -> str:
    """把若干地址的探测结果收敛成一句话，供界面显示。"""
    if not addresses:
        return "unknown_address"
    probed = [item for item in addresses if item.get("probed")]
    if not probed:
        return "not_probed"
    if any(item.get("ssh_open") for item in addresses):
        return "ssh_open"
    if any(item.get("responded") for item in addresses):
        return "online"
    return "no_answer"


def _any_ssh_open(addresses: list[dict[str, Any]]) -> bool | None:
    """整台机器「能不能连」的结论。

    没有任何地址被探测过时返回 None（不知道），而不是 False（确定连不上）——
    这两件事在界面上必须分得开：前者是「没探测」，后者是「探了，连不上」。
    """
    if not addresses or not any(item.get("probed") for item in addresses):
        return None
    return any(bool(item.get("ssh_open")) for item in addresses)


def _vm_record(
    *,
    vmx_path: str,
    display_name: str,
    uuid: str,
    in_inventory: bool,
    exists: bool,
    info: dict[str, Any],
    state: str,
    running_source: str,
    addresses: list[dict[str, Any]],
    notes: list[str],
    sources: list[str],
) -> dict[str, Any]:
    primary = _pick_primary(addresses)
    return {
        "name": display_name or os.path.splitext(os.path.basename(vmx_path))[0],
        "vmx": vmx_path,
        "vmx_exists": exists,
        "in_inventory": in_inventory,
        "uuid": uuid or info.get("uuid") or "",
        "guest_os": info.get("guest_os") or "",
        "memory_mb": info.get("memory_mb"),
        "cpus": info.get("cpus"),
        "nics": info.get("nics") or [],
        "state": state,
        "running": None if state == "unknown" else state == "running",
        "running_source": running_source,
        "addresses": addresses,
        "ip": (primary or {}).get("ip") or "",
        "ip_source": (primary or {}).get("source") or "",
        # 整台机器的汇总结论（取值 unknown_address / not_probed / ssh_open /
        # online / no_answer），与每个地址自己的 ssh_state（open / refused /
        # timeout / unreachable / not_probed，是探测的原始结论）不是一回事。
        "answer_state": _vm_state(addresses),
        "ssh_open": _any_ssh_open(addresses),
        "ssh_port": SSH_PORT,
        "sources": sources,
        "notes": notes,
    }


# ---------------------------------------------------------------------- 扫描


def describe_limits(settings: DiscoveryConfig) -> dict[str, Any]:
    return {
        "enabled": settings.enabled,
        "probe_ssh": settings.probe_ssh,
        "probe_timeout_seconds": settings.probe_timeout_seconds,
        "max_probe_workers": settings.max_probe_workers,
        "max_addresses_per_subnet": settings.max_addresses_per_subnet,
        "max_probes": settings.max_probes,
        "time_budget_seconds": settings.time_budget_seconds,
    }


def environment_summary(config: AppConfig, *, env: VmwareEnvironment | None = None) -> dict[str, Any]:
    """扫描前的环境概览：有哪些来源可用、哪些读不到以及为什么。

    这个接口**不读大文件也不探测**，只回答「这台机器上能做什么」，
    因此可以在页面加载时直接调用，用来决定扫描入口是否可用。
    """
    environment = env or resolve_environment(config)
    settings = config.discovery
    sources: list[dict[str, Any]] = []
    inventory_path = environment.inventory_path
    if inventory_path:
        state = "ok" if _is_file(inventory_path) else "missing"
        detail = "清单文件存在。" if state == "ok" else f"找不到清单文件：{inventory_path}"
        sources.append({"name": "inventory", "label": "VMware 清单", "state": state, "detail": detail, "count": 0})
    else:
        sources.append(
            {
                "name": "inventory",
                "label": "VMware 清单",
                "state": "unavailable",
                "detail": "没有定位到 VMware 的清单目录。",
                "count": 0,
            }
        )
    sources.append(
        {
            "name": "vmrun",
            "label": "vmrun（运行状态）",
            "state": "ok" if environment.vmrun_path else "unavailable",
            "detail": environment.vmrun_path or "找不到 vmrun，运行状态会显示为未知。",
            "count": 0,
        }
    )
    for name, label, path in (
        ("vmnet", "虚拟网段配置", environment.dhcp_conf_path),
        ("lease", "DHCP 租约", environment.dhcp_leases_path),
    ):
        sources.append(
            {
                "name": name,
                "label": label,
                "state": "ok" if _is_file(path) else ("missing" if path else "unavailable"),
                "detail": path or "没有定位到文件。",
                "count": 0,
            }
        )
    sources.append(
        {
            "name": "neighbor",
            "label": "系统邻居表",
            "state": "ok" if sys.platform == "win32" else "unavailable",
            "detail": "Get-NetNeighbor（失败时回退 arp -a）。" if sys.platform == "win32" else "只实现了 Windows。",
            "count": 0,
        }
    )
    sources.append(
        {
            "name": "process",
            "label": "VMware 进程命令行",
            "state": "denied",
            "detail": "读取 VMware 进程的命令行需要管理员权限，已跳过；运行状态改由 vmrun 判断。",
            "count": 0,
        }
    )
    return {
        "enabled": settings.enabled,
        "platform": sys.platform,
        "vmware": environment.to_dict(),
        "sources": sources,
        "limits": describe_limits(settings),
        "notes": list(environment.notes),
    }


def collect(
    config: AppConfig,
    *,
    env: VmwareEnvironment | None = None,
    probe: Callable[..., dict[str, Any]] | None = None,
    guest_ip: Callable[[str], tuple[str, str]] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    on_stage: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """跑一次发现。**不做任何后台线程的事** —— 线程在 Discovery 里。

    返回值里的字段全部是可序列化的普通类型，前端拿到就能画表格。
    """
    settings = config.discovery
    environment = env or resolve_environment(config)
    probe_fn = probe or probe_address
    cancelled = is_cancelled or (lambda: False)

    def stage(name: str) -> None:
        if on_stage is not None:
            on_stage(name)

    sources: list[dict[str, Any]] = []
    notes: list[str] = [*environment.notes]
    truncated = False
    truncated_reason = ""
    #: 是否因为用户点了「中止」而**提前收手**（而不是把该做的都做完了）。
    #: 有了它，扫描状态里的 cancelled 才是诚实的：取消来晚了、活儿已经干完的
    #: 那一次仍然报 done。
    interrupted = False

    stage("inventory")
    inventory, report = read_inventory(environment)
    sources.append(report)

    stage("running")
    running_paths, report = read_running_vms(environment)
    sources.append(report)
    if not environment.vmrun_path:
        notes.append("没有 vmrun，所有虚拟机的运行状态都是「未知」——不是「已关机」。")
    running_set = {_normalize_path(path) for path in running_paths if path.strip()}

    stage("vmx")
    vmnet, report = read_vmnet(environment)
    sources.append(report)
    subnets = vmnet.get("subnets") or []
    # 本机在两个虚拟网段上的网卡地址、以及网关（NAT 设备）都不是「另一台能连的机器」：
    # 前者就是这台机器自己，后者是 VMware 自己的虚拟路由器。它们照样会出现在系统邻居表
    # 里，既不该列成候选，也不该算进「被过滤的邻居记录」——单独说一句更清楚。
    host_addresses = {item.get("host_address") for item in subnets if item.get("host_address")}
    host_addresses |= {item.get("gateway") for item in subnets if item.get("gateway")}

    stage("leases")
    lease_entries, report = read_leases(environment)
    sources.append(report)
    leases_by_mac = latest_by_mac(lease_entries)

    stage("neighbors")
    neighbor_entries, report = read_neighbors()
    sources.append(report)
    neighbors_by_mac: dict[str, dict[str, Any]] = {}
    for entry in neighbor_entries:
        ip = entry.get("ip") or ""
        mac = entry.get("mac") or ""
        if not mac or not _is_usable_host_address(ip):
            continue
        if entry.get("state") in NEIGHBOR_DEAD_STATES:
            continue
        if entry.get("state") not in NEIGHBOR_ALIVE_STATES and entry.get("state") != "Unknown":
            continue
        neighbors_by_mac.setdefault(mac, entry)
    # 本机/网关地址有自己的一句说明（见「其它地址」那一段），这里不重复计数：
    # 否则同一行会在两条说明里各算一次，读起来像是丢了两条。
    dropped = sum(
        1
        for entry in neighbor_entries
        if ((entry.get("state") in NEIGHBOR_DEAD_STATES) or not _is_usable_host_address(entry.get("ip") or ""))
        and (entry.get("ip") or "") not in host_addresses
    )
    if dropped:
        notes.append(f"邻居表里有 {dropped} 条记录被过滤（不可达、组播或广播地址）。")

    # -- 虚拟机清单：清单 + vmrun 里出现但不在清单里的 -----------------------
    ordered_paths: list[str] = []
    seen: dict[str, dict[str, Any]] = {}
    for entry in inventory:
        key = _normalize_path(entry["vmx"])
        if key in seen:
            # 清单里同一个 .vmx 出现两次（实测发生过：vmlist1 与 vmlist3 名字相同）
            seen[key]["duplicate"] += 1
            continue
        record = {
            "vmx": entry["vmx"],
            "display_name": entry["display_name"],
            "uuid": entry["uuid"],
            "in_inventory": True,
            "duplicate": 0,
        }
        seen[key] = record
        ordered_paths.append(key)
    for path in running_paths:
        key = _normalize_path(path)
        if key in seen:
            continue
        seen[key] = {
            "vmx": path,
            "display_name": "",
            "uuid": "",
            "in_inventory": False,
            "duplicate": 0,
        }
        ordered_paths.append(key)

    stage("probe")
    vms: list[dict[str, Any]] = []
    claimed: set[str] = set()
    planned: dict[str, str] = {}
    for key in ordered_paths:
        record = seen[key]
        vmx_path = record["vmx"]
        exists = _is_file(vmx_path)
        info: dict[str, Any] = {}
        vm_notes: list[str] = []
        vm_sources: list[str] = []
        if record["in_inventory"]:
            vm_sources.append("inventory")
        if not exists:
            vm_notes.append("配置文件不在磁盘上（可能已被删除或移动）。")
        else:
            text, _, detail = _read_text(vmx_path)
            if text is None:
                vm_notes.append(detail)
            else:
                info = parse_vmx(text)
                vm_sources.append("vmx")
        if record["duplicate"]:
            vm_notes.append(f"清单里有 {record['duplicate'] + 1} 条记录指向同一个配置文件，已合并。")

        if record["in_inventory"]:
            state = "running" if key in running_set else ("stopped" if environment.vmrun_path else "unknown")
            running_source = "vmrun" if environment.vmrun_path else "unavailable"
        else:
            state = "running"
            running_source = "vmrun"
        if state == "running":
            vm_sources.append("vmrun")

        addresses: list[dict[str, Any]] = []
        guest = ""
        if state == "running":
            lookup = guest_ip or (lambda path: read_guest_ip(environment, path))
            guest, guest_error = lookup(vmx_path)
            if guest:
                addresses.append({"ip": guest, "mac": "", "source": "guest"})
                vm_sources.append("guest-ip")
            else:
                vm_notes.append(guest_error or "没有取到客户机自报的 IP。")
        for nic in info.get("nics") or []:
            mac = nic.get("mac") or ""
            if not mac:
                continue
            neighbor = neighbors_by_mac.get(mac)
            if neighbor is not None:
                candidate = neighbor["ip"]
                if not any(item["ip"] == candidate for item in addresses):
                    addresses.append({"ip": candidate, "mac": mac, "source": "neighbor"})
                if "neighbor" not in vm_sources:
                    vm_sources.append("neighbor")
            lease = leases_by_mac.get(mac)
            if lease is not None:
                candidate = lease["ip"]
                if not any(item["ip"] == candidate for item in addresses):
                    addresses.append({"ip": candidate, "mac": mac, "source": "lease"})
                if "lease" not in vm_sources:
                    vm_sources.append("lease")
                if lease.get("expired"):
                    vm_notes.append(f"租约地址 {candidate} 已过期，只能当作线索。")

        for item in addresses:
            claimed.add(item["ip"])

        vms.append(
            {
                "name": record["display_name"] or "",
                "vmx": vmx_path,
                "vmx_exists": exists,
                "in_inventory": record["in_inventory"],
                "uuid": record["uuid"],
                "info": info,
                "state": state,
                "running_source": running_source,
                "addresses": addresses,
                "notes": vm_notes,
                "sources": vm_sources,
            }
        )

    # -- 其它在线地址（同一虚拟网段里，不属于任何已知虚拟机） ----------------
    # host_addresses（本机网卡与网关）在 vmnet 阶段之后就算好了，这里直接排除。
    subnet_addresses: list[dict[str, Any]] = []
    skipped_host = 0
    for entry in neighbor_entries:
        ip = entry.get("ip") or ""
        mac = entry.get("mac") or ""
        if not _is_usable_host_address(ip) or ip in claimed:
            continue
        if ip in host_addresses:
            skipped_host += 1
            continue
        if entry.get("state") in NEIGHBOR_DEAD_STATES:
            continue
        if not _subnet_label(ip, subnets)[1]:
            continue
        if any(item["ip"] == ip for item in subnet_addresses):
            continue
        subnet_addresses.append({"ip": ip, "mac": mac, "source": "neighbor"})
    if skipped_host:
        notes.append(
            f"邻居表里有 {skipped_host} 条是本机虚拟网卡或网关的地址，已跳过"
            "（它们不是待连接的机器）。"
        )
    if len(subnet_addresses) > MAX_OTHER_ADDRESSES:
        notes.append(
            f"同一虚拟网段上还有 {len(subnet_addresses)} 个地址，只列出前 {MAX_OTHER_ADDRESSES} 个。"
        )
        subnet_addresses = subnet_addresses[:MAX_OTHER_ADDRESSES]

    # -- 探测（可选，且必须有上限） -----------------------------------------
    targets: list[str] = []
    for ip in [item["ip"] for vm in vms for item in vm["addresses"]] + [item["ip"] for item in subnet_addresses]:
        if ip in targets:
            continue
        if ip in host_addresses:
            # 上面已经排除了它们，这里再挡一次：探测目标必须有上限、也必须有边界，
            # 不能让将来新加的地址来源绕过这条规则。
            continue
        targets.append(ip)

    if settings.probe_ssh and targets:
        limit = min(len(targets), settings.max_probes)
        if limit < len(targets):
            truncated = True
            truncated_reason = f"地址太多，只探测了前 {limit} 个（上限 discovery.max_probes）。"
            notes.append(truncated_reason)
        per_subnet: dict[str, int] = {}
        allowed: list[str] = []
        for ip in targets[:limit]:
            label = _subnet_label(ip, subnets)[0] or "unknown"
            used = per_subnet.get(label, 0)
            if used >= settings.max_addresses_per_subnet:
                truncated = True
                truncated_reason = (
                    f"网段 {label} 的地址超过 {settings.max_addresses_per_subnet} 个，已停止探测该网段。"
                )
                continue
            per_subnet[label] = used + 1
            allowed.append(ip)
        targets = allowed

    probes: dict[str, dict[str, Any]] = {}
    done = 0
    deadline = time.monotonic() + float(settings.time_budget_seconds)
    if cancelled():
        # 取消要立刻生效。读清单、跑 vmrun、查邻居表这些几十毫秒到几秒的活儿
        # 打断不了（子进程就那个长度），但探测可以不要白跑。
        interrupted = True
        notes.append("扫描已中止（用户取消），没有探测任何地址。")
    if settings.probe_ssh and targets and not interrupted:
        workers = max(1, min(settings.max_probe_workers, len(targets)))
        pending = list(targets)
        while pending and not cancelled():
            if time.monotonic() > deadline:
                truncated = True
                truncated_reason = (
                    f"已达到扫描时间上限（{settings.time_budget_seconds} 秒），还有 {len(pending)} 个地址没有探测。"
                )
                break
            batch = pending[: workers * 2]
            del pending[: len(batch)]
            threads: list[threading.Thread] = []

            def worker(address: str) -> None:
                try:
                    probes[address] = probe_fn(
                        address, port=SSH_PORT, timeout=settings.probe_timeout_seconds
                    )
                except Exception as exc:  # pragma: no cover - 探测本身不该抛
                    probes[address] = {
                        "ip": address,
                        "port": SSH_PORT,
                        "state": "error",
                        "probed": True,
                        "responded": None,
                        "ssh_open": None,
                        "elapsed_ms": None,
                        "error": str(exc),
                    }
                finally:
                    nonlocal done
                    done += 1

            for address in batch:
                thread = threading.Thread(target=worker, args=(address,), daemon=True)
                thread.start()
                threads.append(thread)
            for thread in threads:
                thread.join(timeout=float(settings.probe_timeout_seconds) + 5.0)
        if pending and cancelled():
            interrupted = True
            truncated = True
            truncated_reason = f"扫描已中止（用户取消），还有 {len(pending)} 个地址没有探测。"
            notes.append(truncated_reason)
    elif targets and not settings.probe_ssh:
        notes.append("探测已在配置里关闭（discovery.probe_ssh），只报告地址来自哪里。")

    def decorate(item: dict[str, Any]) -> dict[str, Any]:
        return _address_entry(
            item["ip"],
            mac=item.get("mac") or "",
            source=item.get("source") or "",
            subnets=subnets,
            probe_result=probes.get(item["ip"]),
        )

    final_vms: list[dict[str, Any]] = []
    for vm in vms:
        addresses = [decorate(item) for item in vm["addresses"]]
        final_vms.append(
            _vm_record(
                vmx_path=vm["vmx"],
                display_name=vm["name"],
                uuid=vm["uuid"],
                in_inventory=vm["in_inventory"],
                exists=vm["vmx_exists"],
                info=vm["info"],
                state=vm["state"],
                running_source=vm["running_source"],
                addresses=addresses,
                notes=vm["notes"],
                sources=vm["sources"],
            )
        )
    final_others = [decorate(item) for item in subnet_addresses]

    all_addresses = [item for vm in final_vms for item in vm["addresses"]] + final_others
    counts = {
        "vms": len(final_vms),
        "running": sum(1 for vm in final_vms if vm["state"] == "running"),
        "stopped": sum(1 for vm in final_vms if vm["state"] == "stopped"),
        "unknown_state": sum(1 for vm in final_vms if vm["state"] == "unknown"),
        "with_address": sum(1 for vm in final_vms if vm["ip"]),
        "ssh_open": sum(1 for vm in final_vms if vm["ssh_open"]),
        "online": sum(1 for vm in final_vms if vm["answer_state"] in ("online", "ssh_open")),
        "other_addresses": len(final_others),
    }
    return {
        "vmware": environment.to_dict(),
        "sources": sources,
        "subnets": subnets,
        "vms": final_vms,
        "addresses": final_others,
        "counts": counts,
        "probes": {
            "enabled": bool(settings.probe_ssh),
            "planned": len(targets),
            "done": done,
            "open": sum(1 for item in probes.values() if item.get("ssh_open")),
            "responded": sum(1 for item in probes.values() if item.get("responded")),
            "timeout_seconds": settings.probe_timeout_seconds,
        },
        "addresses_all": all_addresses,
        "notes": notes,
        "interrupted": interrupted,
        "truncated": truncated,
        "truncated_reason": truncated_reason,
        "limits": describe_limits(settings),
    }


def empty_result() -> dict[str, Any]:
    """扫描还没产出任何东西时的骨架，保证前端拿到的字段集合始终一致。"""
    return {
        "vmware": {},
        "sources": [],
        "subnets": [],
        "vms": [],
        "addresses": [],
        "counts": {
            "vms": 0,
            "running": 0,
            "stopped": 0,
            "unknown_state": 0,
            "with_address": 0,
            "ssh_open": 0,
            "online": 0,
            "other_addresses": 0,
        },
        "probes": {"enabled": False, "planned": 0, "done": 0, "open": 0, "responded": 0, "timeout_seconds": 0.0},
        "addresses_all": [],
        "notes": [],
        "interrupted": False,
        "truncated": False,
        "truncated_reason": "",
        "limits": {},
    }


# ------------------------------------------------------------------ 扫描任务


class Discovery:
    """一次扫描。跑在后台线程里，前端轮询它的 snapshot()。"""

    def __init__(
        self,
        config: AppConfig,
        *,
        scan_id: str | None = None,
        probe: Callable[..., dict[str, Any]] | None = None,
        guest_ip: Callable[[str], tuple[str, str]] | None = None,
        environment: VmwareEnvironment | None = None,
    ) -> None:
        self.id = scan_id or secrets.token_hex(6)
        self._config = config
        self._probe = probe
        self._guest_ip = guest_ip
        self._environment = environment
        self._lock = threading.RLock()
        self._status = "running"
        self._stage = "starting"
        self._error: AwfmError | None = None
        self._result = empty_result()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self.started_at = time.time()
        self.finished_at: float | None = None

    # -- 状态 --------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._status == "running"

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    def _set_stage(self, stage: str) -> None:
        with self._lock:
            self._stage = stage

    def start(self) -> None:
        thread = threading.Thread(target=self._run, name=f"awfm-discovery-{self.id}", daemon=True)
        self._thread = thread
        thread.start()

    def _run(self) -> None:
        status = "done"
        try:
            result = collect(
                self._config,
                env=self._environment,
                probe=self._probe,
                guest_ip=self._guest_ip,
                is_cancelled=self._cancel.is_set,
                on_stage=self._set_stage,
            )
        except AwfmError as exc:
            result = empty_result()
            self._error = exc
            status = "failed"
        except Exception as exc:  # pragma: no cover - 兜底，不能让线程静默死掉
            result = empty_result()
            self._error = AwfmError(f"扫描过程中出现未预料的错误：{exc}")
            status = "failed"
            logger.exception("扫描在线虚拟机失败：scan=%s", self.id)
        if status == "done" and result.get("interrupted"):
            # 只有真的提前收手才算「已中止」；取消来晚了、活儿已经干完的那次
            # 仍然报 done —— 谎报中止会让用户以为结果是残缺的。
            status = "cancelled"
        if status in ("done", "cancelled"):
            # 收尾时明确写 done：否则 stage 会停在最后一个动作（通常是 probe）上，
            # 「阶段」这一列在扫描结束后看起来像卡住了。失败时保留当时那一阶段，
            # 好让人看出是卡在哪一步。
            self._set_stage("done")
        with self._lock:
            self._result = result
            self._status = status
            self.finished_at = time.time()
        if self._error is not None:
            logger.info("扫描 %s 失败：%s", self.id, self._error.message)
        else:
            counts = result.get("counts") or {}
            logger.info(
                "扫描 %s 结束（%s）：发现 %s 台虚拟机，其中 %s 台在运行，%s 台可 SSH",
                self.id,
                status,
                counts.get("vms"),
                counts.get("running"),
                counts.get("ssh_open"),
            )

    def cancel(self) -> bool:
        with self._lock:
            if self._status != "running":
                return False
            self._cancel.set()
            return True

    def wait(self, timeout: float | None = None) -> bool:
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            payload: dict[str, Any] = {
                "id": self.id,
                "status": self._status,
                "running": self._status == "running",
                "stage": self._stage,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "duration_seconds": (
                    None if self.finished_at is None else round(self.finished_at - self.started_at, 3)
                ),
                "error": None if self._error is None else _error_payload(self._error),
            }
            payload.update(self._result)
            return payload


def _error_payload(error: AwfmError) -> dict[str, Any]:
    return {"code": error.code, "message": error.message, "detail": error.detail}


class DiscoveryRegistry:
    """进程内所有扫描的登记处。同一时刻只允许一个扫描。"""

    def __init__(
        self,
        config: AppConfig,
        *,
        max_kept: int = 10,
        probe: Callable[..., dict[str, Any]] | None = None,
        guest_ip: Callable[[str], tuple[str, str]] | None = None,
        environment: VmwareEnvironment | None = None,
    ) -> None:
        self._config = config
        self._lock = threading.RLock()
        self._scans: dict[str, Discovery] = {}
        self._current: str | None = None
        self._max_kept = max_kept
        self._probe = probe
        self._guest_ip = guest_ip
        self._environment = environment

    # -- 生命周期 ----------------------------------------------------------

    def start(self) -> Discovery:
        if not self._config.discovery.enabled:
            raise ValidationError(
                "在线虚拟机发现在配置里是关闭的。",
                detail="把配置里的 discovery.enabled 改成 true 再重启程序。",
            )
        with self._lock:
            current = self._scans.get(self._current) if self._current else None
            if current is not None and current.is_running:
                raise DiscoveryBusy(
                    "已经有一个正在进行的扫描。",
                    detail="请等它结束，或在结果区点「中止」。",
                )
            self._prune_locked()
            scan = Discovery(
                self._config,
                probe=self._probe,
                guest_ip=self._guest_ip,
                environment=self._environment,
            )
            self._scans[scan.id] = scan
            self._current = scan.id
        logger.info("开始扫描在线虚拟机：scan=%s", scan.id)
        scan.start()
        return scan

    def get(self, scan_id: str) -> Discovery:
        with self._lock:
            scan = self._scans.get(scan_id)
        if scan is None:
            raise PathNotFound(
                "扫描不存在或已过期。",
                detail="扫描结果只保留最近若干次，请重新扫描。",
            )
        return scan

    def snapshot(self, scan_id: str) -> dict[str, Any]:
        return self.get(scan_id).snapshot()

    def cancel(self, scan_id: str) -> dict[str, Any]:
        scan = self.get(scan_id)
        scan.cancel()
        return scan.snapshot()

    def environment(self) -> dict[str, Any]:
        return environment_summary(self._config, env=self._environment)

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for scan in self._scans.values() if scan.is_running)

    def shutdown(self, timeout: float = 5.0) -> None:
        with self._lock:
            scans = list(self._scans.values())
        for scan in scans:
            scan.cancel()
        deadline = time.time() + timeout
        for scan in scans:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            scan.wait(remaining)

    def _prune_locked(self) -> None:
        """只留最近若干次**已结束**的扫描；正在跑的一个永远不删。"""
        finished = [
            scan
            for scan in self._scans.values()
            if not scan.is_running
        ]
        if len(finished) < self._max_kept:
            return
        finished.sort(key=lambda scan: scan.started_at)
        for scan in finished[: max(0, len(finished) - self._max_kept + 1)]:
            self._scans.pop(scan.id, None)
            if self._current == scan.id:
                self._current = None
