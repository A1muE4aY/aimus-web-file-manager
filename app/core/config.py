"""配置的加载、校验与原子保存。

决策 D-006：`data/config.json`，原子写入。**损坏必须显式报错，禁止静默重置** ——
静默重置会丢掉用户手工维护的连接列表，而用户往往在下次打开界面时才发现。

配置的权威结构定义在 `config/config.example.json`（模板）与本文的 `DEFAULTS`。
两者必须同步；`tests/unit/test_config.py` 会断言这一点。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.errors import ConfigError, ValidationError
from app.models.connection import Connection
from app.utils.atomic import write_json_atomic

#: 支持的配置版本。读到更高版本时**拒绝启动**：
#: 用旧代码去跑新格式配置，最可能的结果是「某些字段被静默忽略」，
#: 而用户以为设置生效了。宁可报错。
CONFIG_VERSION = 1

#: 回环地址集合。`security.allow_lan` 为假时，server.host 必须是其中之一。
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

#: 允许绑定的地址。`0.0.0.0` 表示「所有网卡」，需要 allow_lan 才放行。
ANY_HOSTS = frozenset({"0.0.0.0", "::", "[::]", "*"})


def project_root() -> Path:
    """项目根目录（`app/core/config.py` 的上三级）。

    返回 `Path` 而不是字符串：这个值会一路拼成配置文件、日志目录、前端目录的路径，
    调用方到处做 `os.path.join` 与字符串相加只会把「用错基准」的 bug 藏得更深。
    """
    return Path(__file__).resolve().parent.parent.parent

#: 默认配置文件位置。相对项目根，与启动时的工作目录无关。
DEFAULT_CONFIG_PATH = project_root() / "data" / "config.json"


#: 默认配置。`config/config.example.json` 必须与它保持一致（有单元测试钉死）。
DEFAULTS: dict[str, Any] = {
    "config_version": CONFIG_VERSION,
    "server": {
        "host": "127.0.0.1",
        "port": 32579,
        "open_browser": False,
        "request_timeout_seconds": 60,
    },
    "security": {
        "allow_lan": False,
        "host_key_policy": "strict",
        "session_token_ttl_seconds": 43200,
        "max_upload_bytes": 2147483648,
        "max_download_bytes": 0,
        "max_edit_bytes": 2097152,
        "log_level": "INFO",
        "redact_secrets": True,
    },
    "ssh": {
        "connect_timeout_seconds": 15,
        "command_timeout_seconds": 60,
        "keepalive_interval_seconds": 30,
        "max_sessions": 4,
        "known_hosts_file": "data/known_hosts",
        "ssh_executable": "",
        "sftp_executable": "",
    },
    "discovery": {
        "enabled": True,
        "probe_ssh": True,
        "probe_timeout_seconds": 1.0,
        "max_probe_workers": 16,
        "max_addresses_per_subnet": 254,
        "max_probes": 512,
        "time_budget_seconds": 60,
        "vmware_root": "",
        "vmware_data_dir": "",
    },
    "connections": [],
}


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"配置项 {name} 必须是一个对象。", detail=f"实际类型：{type(value).__name__}")
    return value


def _require_int(value: Any, name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"配置项 {name} 必须是整数。", detail=f"实际值：{value!r}")
    if not (minimum <= value <= maximum):
        raise ConfigError(f"配置项 {name} 超出允许范围。", detail=f"要求 {minimum}..{maximum}，实际 {value}")
    return value


def _require_number(value: Any, name: str, *, minimum: float, maximum: float) -> float:
    """接受 int 或 float，但**拒绝 bool**（bool 是 int 的子类，True 会变成 1.0 秒）。

    解析成 float 是刻意的：写成 1 与写成 1.0 是同一件事，让用户为小数点纠结没有意义。
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"配置项 {name} 必须是数字。", detail=f"实际值：{value!r}")
    result = float(value)
    if not (minimum <= result <= maximum):
        raise ConfigError(f"配置项 {name} 超出允许范围。", detail=f"要求 {minimum}..{maximum}，实际 {value}")
    return result


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"配置项 {name} 必须是布尔值。", detail=f"实际值：{value!r}")
    return value


def _require_str(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"配置项 {name} 必须是字符串。", detail=f"实际值：{value!r}")
    return value


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 32579
    open_browser: bool = False
    request_timeout_seconds: int = 60


@dataclass
class SecurityConfig:
    allow_lan: bool = False
    host_key_policy: str = "strict"
    session_token_ttl_seconds: int = 43200
    max_upload_bytes: int = 2147483648
    max_download_bytes: int = 0
    #: 在线编辑单次读写的字节上限（默认 2 MiB）。比上传上限小得多：
    #: 编辑要把内容整体放进浏览器的一个 textarea，几十 MB 的「文本」不是给编辑器用的。
    max_edit_bytes: int = 2097152
    log_level: str = "INFO"
    redact_secrets: bool = True


@dataclass
class SshConfig:
    connect_timeout_seconds: int = 15
    command_timeout_seconds: int = 60
    keepalive_interval_seconds: int = 30
    max_sessions: int = 4
    known_hosts_file: str = "data/known_hosts"
    ssh_executable: str = ""
    sftp_executable: str = ""


@dataclass
class DiscoveryConfig:
    """在线虚拟机自动发现（阶段五，决策 D-018）。

    这一组全是「做多少」的旋钮，不是「能不能连」的开关：发现只产出候选，
    创建连接仍然要用户自己确认，主机指纹仍然走既有的首次确认。
    """

    #: 关掉之后界面上不出现扫描入口，服务端也拒绝启动扫描。
    enabled: bool = True
    #: 是否对已知虚拟网段里的地址做 TCP 22 探测。关掉就只报告「地址从哪来」。
    probe_ssh: bool = True
    #: 单个地址的探测超时（秒）。上限 5 秒：一台有 254 个地址的网段，超时再长
    #: 就会把一次扫描拖成几分钟。
    probe_timeout_seconds: float = 1.0
    max_probe_workers: int = 16
    max_addresses_per_subnet: int = 254
    max_probes: int = 512
    time_budget_seconds: int = 60
    #: VMware 安装目录。留空表示自动探测（Windows 上读注册表）。
    vmware_root: str = ""
    #: VMware 的配置数据目录（放 inventory.vmls）。留空表示自动探测（%APPDATA%\\VMware）。
    vmware_data_dir: str = ""


@dataclass
class AppConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    ssh: SshConfig = field(default_factory=SshConfig)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    connections: list[Connection] = field(default_factory=list)
    #: 配置文件自身的绝对路径。
    path: str = ""
    config_version: int = CONFIG_VERSION

    # -- 派生路径 ---------------------------------------------------------

    @property
    def root(self) -> Path:
        return project_root()

    def resolve(self, relative: str) -> Path:
        """把配置中的相对路径解析成绝对路径（基准是项目根，不是当前工作目录）。

        基准必须是项目根：用户用 `scripts/start.py` 还是 `python app/main.py` 启动，
        当前工作目录不同，用 cwd 做基准会让「同一个配置」指向两个不同的文件。
        """
        candidate = Path(relative)
        if candidate.is_absolute():
            return Path(os.path.normpath(str(candidate)))
        return Path(os.path.normpath(str(self.root / candidate)))

    @property
    def known_hosts_path(self) -> Path:
        return self.resolve(self.ssh.known_hosts_file)

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def frontend_dir(self) -> Path:
        return self.root / "frontend"

    # -- 安全校验 ---------------------------------------------------------

    def validate_binding(self) -> None:
        """校验监听地址与 `security.allow_lan` 是否自洽。

        决策 D-009：默认只监听回环；`allow_lan` 为假时**拒绝**非回环绑定。

        为什么是拒绝而不是自动改回 127.0.0.1：对一个「把虚拟机文件系统端上网页」的
        工具来说，绑错地址的后果是整台机器的文件可被局域网任意读取。静默纠正会
        让这件事变得不可见，用户下次照样会把配置改成 0.0.0.0。宁可启动失败并要求
        用户明确写下 `allow_lan: true` —— 那一下是需要他意识到风险的一下。

        规划文档 §10.3 只说「开放局域网必须单独增加身份验证与 Web 安全防护」，
        本版还没有实现那套防护，所以这里只放行显式声明的绑定，并在启动日志里
        把「当前允许局域网访问」这句话打出来。
        """
        host = (self.server.host or "").strip()
        if not host:
            raise ConfigError("配置项 server.host 不能为空。")
        if self.security.allow_lan:
            return
        normalized = host.lower()
        if normalized in LOOPBACK_HOSTS:
            return
        raise ConfigError(
            "拒绝绑定到非回环地址，因为 security.allow_lan 未开启。",
            detail=(
                f"server.host = {host!r}。"
                "本服务默认只允许本机访问；如果你确实需要从局域网内的其它机器访问，"
                "请先把配置中的 security.allow_lan 改成 true（这意味着"
                "本机文件会暴露给局域网，请确认你了解后果），或把 server.host 改回 127.0.0.1。"
            ),
        )

    # -- 序列化 -----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_version": self.config_version,
            "server": {
                "host": self.server.host,
                "port": self.server.port,
                "open_browser": self.server.open_browser,
                "request_timeout_seconds": self.server.request_timeout_seconds,
            },
            "security": {
                "allow_lan": self.security.allow_lan,
                "host_key_policy": self.security.host_key_policy,
                "session_token_ttl_seconds": self.security.session_token_ttl_seconds,
                "max_upload_bytes": self.security.max_upload_bytes,
                "max_download_bytes": self.security.max_download_bytes,
                "max_edit_bytes": self.security.max_edit_bytes,
                "log_level": self.security.log_level,
                "redact_secrets": self.security.redact_secrets,
            },
            "ssh": {
                "connect_timeout_seconds": self.ssh.connect_timeout_seconds,
                "command_timeout_seconds": self.ssh.command_timeout_seconds,
                "keepalive_interval_seconds": self.ssh.keepalive_interval_seconds,
                "max_sessions": self.ssh.max_sessions,
                "known_hosts_file": self.ssh.known_hosts_file,
                "ssh_executable": self.ssh.ssh_executable,
                "sftp_executable": self.ssh.sftp_executable,
            },
            "discovery": {
                "enabled": self.discovery.enabled,
                "probe_ssh": self.discovery.probe_ssh,
                "probe_timeout_seconds": self.discovery.probe_timeout_seconds,
                "max_probe_workers": self.discovery.max_probe_workers,
                "max_addresses_per_subnet": self.discovery.max_addresses_per_subnet,
                "max_probes": self.discovery.max_probes,
                "time_budget_seconds": self.discovery.time_budget_seconds,
                "vmware_root": self.discovery.vmware_root,
                "vmware_data_dir": self.discovery.vmware_data_dir,
            },
            "connections": [c.to_dict() for c in self.connections],
        }


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    raw = data.get(name, {})
    return _require_mapping(raw, name) if raw is not None else {}


def _reject_unknown(mapping: dict[str, Any], allowed: frozenset[str], label: str) -> None:
    """拒绝不认识的键。

    配置文件是**用户手工编辑**的：把 `max_upload_bytes` 打成
    `max_upload_btyes` 时，静默忽略会让用户以为自己设的限额已经生效 ——
    一个「看起来配好了」的假象比直接报错危险得多。
    """
    unknown = sorted(set(mapping) - set(allowed))
    if unknown:
        raise ConfigError(
            f"配置项 {label} 里有无法识别的字段。",
            detail="、".join(unknown) + "。请检查拼写；若这些字段来自更新版本的配置模板，请升级程序。",
        )


#: 各层允许出现的键。新增配置项时必须同步这里，否则新字段会被自己的校验拒绝。
_ROOT_KEYS = frozenset({"config_version", "server", "security", "ssh", "discovery", "connections"})
_SERVER_KEYS = frozenset({"host", "port", "open_browser", "request_timeout_seconds"})
_SECURITY_KEYS = frozenset({
    "allow_lan", "host_key_policy", "session_token_ttl_seconds",
    "max_upload_bytes", "max_download_bytes", "max_edit_bytes", "log_level", "redact_secrets",
})
_SSH_KEYS = frozenset({
    "connect_timeout_seconds", "command_timeout_seconds", "keepalive_interval_seconds",
    "max_sessions", "known_hosts_file", "ssh_executable", "sftp_executable",
})
_DISCOVERY_KEYS = frozenset({
    "enabled", "probe_ssh", "probe_timeout_seconds", "max_probe_workers",
    "max_addresses_per_subnet", "max_probes", "time_budget_seconds",
    "vmware_root", "vmware_data_dir",
})


def parse_config(data: Any, *, path: str = "") -> AppConfig:
    """把已解析的 JSON 校验成 `AppConfig`。

    每个字段都显式校验类型与范围。理由：配置文件是**用户手工编辑**的，
    而 `json.load` 只保证语法正确。一个字符串形式的端口号会在 socket 绑定时
    才炸，那时错误信息与真实原因已经隔了好几层。
    """
    root = _require_mapping(data, "根")
    _reject_unknown(root, _ROOT_KEYS, "根")
    version = root.get("config_version", CONFIG_VERSION)
    if not isinstance(version, int) or isinstance(version, bool):
        raise ConfigError("配置项 config_version 必须是整数。", detail=f"实际值：{version!r}")
    if version > CONFIG_VERSION:
        raise ConfigError(
            "配置文件的版本高于本程序支持的版本。",
            detail=f"文件版本 {version} > 程序支持 {CONFIG_VERSION}。请升级程序，或改用旧版配置。",
        )

    server_raw = _section(root, "server")
    _reject_unknown(server_raw, _SERVER_KEYS, "server")
    server = ServerConfig(
        host=_require_str(server_raw.get("host", "127.0.0.1"), "server.host"),
        port=_require_int(server_raw.get("port", 32579), "server.port", minimum=1, maximum=65535),
        open_browser=_require_bool(server_raw.get("open_browser", False), "server.open_browser"),
        request_timeout_seconds=_require_int(
            server_raw.get("request_timeout_seconds", 60),
            "server.request_timeout_seconds", minimum=5, maximum=3600,
        ),
    )

    security_raw = _section(root, "security")
    _reject_unknown(security_raw, _SECURITY_KEYS, "security")
    policy = _require_str(security_raw.get("host_key_policy", "strict"), "security.host_key_policy")
    if policy not in ("strict", "accept-new"):
        raise ConfigError(
            "配置项 security.host_key_policy 取值非法。",
            detail=f"只允许 'strict' 或 'accept-new'，实际 {policy!r}。",
        )
    log_level = _require_str(security_raw.get("log_level", "INFO"), "security.log_level").upper()
    if log_level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        raise ConfigError("配置项 security.log_level 取值非法。", detail=f"实际 {log_level!r}")
    security = SecurityConfig(
        allow_lan=_require_bool(security_raw.get("allow_lan", False), "security.allow_lan"),
        host_key_policy=policy,
        session_token_ttl_seconds=_require_int(
            security_raw.get("session_token_ttl_seconds", 43200),
            "security.session_token_ttl_seconds", minimum=60, maximum=604800,
        ),
        max_upload_bytes=_require_int(
            security_raw.get("max_upload_bytes", 2147483648),
            "security.max_upload_bytes", minimum=0, maximum=10 * 1024**4,
        ),
        max_download_bytes=_require_int(
            security_raw.get("max_download_bytes", 0),
            "security.max_download_bytes", minimum=0, maximum=10 * 1024**4,
        ),
        # 下限 1 KiB：真正的下限由编辑器自己定，配置层只需要挡住 0 与负数，
        # 否则「所有文件都不能编辑」会被当成程序坏了。
        max_edit_bytes=_require_int(
            security_raw.get("max_edit_bytes", 2097152),
            "security.max_edit_bytes", minimum=1024, maximum=64 * 1024 * 1024,
        ),
        log_level=log_level,
        redact_secrets=_require_bool(security_raw.get("redact_secrets", True), "security.redact_secrets"),
    )

    ssh_raw = _section(root, "ssh")
    _reject_unknown(ssh_raw, _SSH_KEYS, "ssh")
    ssh = SshConfig(
        connect_timeout_seconds=_require_int(
            ssh_raw.get("connect_timeout_seconds", 15),
            "ssh.connect_timeout_seconds", minimum=1, maximum=600,
        ),
        command_timeout_seconds=_require_int(
            ssh_raw.get("command_timeout_seconds", 60),
            "ssh.command_timeout_seconds", minimum=1, maximum=3600,
        ),
        keepalive_interval_seconds=_require_int(
            ssh_raw.get("keepalive_interval_seconds", 30),
            "ssh.keepalive_interval_seconds", minimum=0, maximum=3600,
        ),
        max_sessions=_require_int(ssh_raw.get("max_sessions", 4), "ssh.max_sessions", minimum=1, maximum=64),
        known_hosts_file=_require_str(ssh_raw.get("known_hosts_file", "data/known_hosts"), "ssh.known_hosts_file"),
        ssh_executable=_require_str(ssh_raw.get("ssh_executable", ""), "ssh.ssh_executable"),
        sftp_executable=_require_str(ssh_raw.get("sftp_executable", ""), "ssh.sftp_executable"),
    )

    discovery_raw = _section(root, "discovery")
    _reject_unknown(discovery_raw, _DISCOVERY_KEYS, "discovery")
    discovery = DiscoveryConfig(
        enabled=_require_bool(discovery_raw.get("enabled", True), "discovery.enabled"),
        probe_ssh=_require_bool(discovery_raw.get("probe_ssh", True), "discovery.probe_ssh"),
        # 下限 0.1 秒：0 会让每个地址都立刻超时，扫描结果永远是「无响应」，
        # 而用户会以为「网段里什么都没有」。上限 5 秒见 DiscoveryConfig 的注释。
        probe_timeout_seconds=_require_number(
            discovery_raw.get("probe_timeout_seconds", 1.0),
            "discovery.probe_timeout_seconds", minimum=0.1, maximum=5.0,
        ),
        max_probe_workers=_require_int(
            discovery_raw.get("max_probe_workers", 16),
            "discovery.max_probe_workers", minimum=1, maximum=64,
        ),
        max_addresses_per_subnet=_require_int(
            discovery_raw.get("max_addresses_per_subnet", 254),
            "discovery.max_addresses_per_subnet", minimum=1, maximum=4096,
        ),
        max_probes=_require_int(
            discovery_raw.get("max_probes", 512),
            "discovery.max_probes", minimum=1, maximum=65536,
        ),
        time_budget_seconds=_require_int(
            discovery_raw.get("time_budget_seconds", 60),
            "discovery.time_budget_seconds", minimum=1, maximum=3600,
        ),
        vmware_root=_require_str(discovery_raw.get("vmware_root", ""), "discovery.vmware_root"),
        vmware_data_dir=_require_str(discovery_raw.get("vmware_data_dir", ""), "discovery.vmware_data_dir"),
    )

    connections_raw = root.get("connections", [])
    if not isinstance(connections_raw, list):
        raise ConfigError("配置项 connections 必须是数组。", detail=f"实际类型：{type(connections_raw).__name__}")
    connections: list[Connection] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(connections_raw):
        try:
            connection = Connection.from_dict(item)
        except ValidationError as exc:
            raise ConfigError(f"第 {index + 1} 条连接配置不合法。", detail=exc.message) from exc
        if connection.id in seen_ids:
            raise ConfigError(f"连接 id 重复：{connection.id!r}。", detail="每条连接的 id 必须唯一。")
        seen_ids.add(connection.id)
        connections.append(connection)

    config = AppConfig(
        server=server, security=security, ssh=ssh, discovery=discovery,
        connections=connections, path=path, config_version=version,
    )
    # D-009 在解析阶段就生效：任何入口（main、测试、将来的其它前端）拿到配置时
    # 都不可能是一份「绑定地址与 allow_lan 相互矛盾」的配置。
    config.validate_binding()
    return config


def load_config(path: str) -> AppConfig:
    """从磁盘加载配置。

    Raises:
        ConfigError: 文件不存在、不是合法 JSON、或字段校验失败。
            **任何情况下都不会返回一份默认配置来「兜底」。**
    """
    full = os.path.abspath(path)
    if not os.path.isfile(full):
        raise ConfigError(
            "找不到配置文件。",
            detail=(
                f"期望路径：{full}。"
                "请先运行 `python app/main.py --init-config` 生成一份默认配置。"
            ),
        )
    try:
        with open(full, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            "配置文件不是合法的 JSON，已停止启动。",
            detail=(
                f"{full} 第 {exc.lineno} 行第 {exc.colno} 列：{exc.msg}。"
                "为避免丢失你的连接配置，程序不会自动重建该文件；请修复语法后重试。"
            ),
        ) from exc
    except OSError as exc:
        raise ConfigError("无法读取配置文件。", detail=f"{full}：{exc}") from exc
    return parse_config(raw, path=full)


def save_config(config: AppConfig) -> None:
    """原子保存。目标是 `config.path`（加载时记录），未设置则拒绝写入。"""
    if not config.path:
        raise ConfigError("无法保存配置：没有记录配置文件的路径。")
    write_json_atomic(config.path, config.to_dict())


def init_config(target_path: str, *, overwrite: bool = False) -> str:
    """生成默认配置文件。已存在且未指定 `overwrite` 时报错而不是覆盖。"""
    full = os.path.abspath(target_path)
    if os.path.exists(full) and not overwrite:
        raise ConfigError(
            "配置文件已存在，未做任何修改。",
            detail=f"{full}。如需强制重建，请显式加 --force（会丢失既有连接配置）。",
        )
    write_json_atomic(full, DEFAULTS)
    return full


def example_config_text() -> str:
    """磁盘上 `config/config.example.json` 的原文。

    以前这里是 `json.dumps(DEFAULTS)` —— 于是「模板与默认值一致」的单元测试变成了
    自证：拿 DEFAULTS 生成字符串再和 DEFAULTS 比，模板里少一段也照样绿（阶段五实测
    发现模板多了一行 `$schema` 时就是这么漏过去的）。读磁盘上的那一份才有意义。
    """
    return (project_root() / "config" / "config.example.json").read_text(encoding="utf-8")
