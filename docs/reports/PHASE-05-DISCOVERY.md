# 阶段 05 报告：在线虚拟机自动发现（v0.1.1）

## 1. 报告信息

| 项目 | 内容 |
|---|---|
| 项目版本 | v0.1.0（v0.1.1 开发中，版本号在阶段六统一提升） |
| 报告日期 | 2026-10-16 |
| 开发阶段 | 阶段 05 —— 自动发现在线虚拟机（任务书 `2.md` §六，`2.md:152-190`） |
| 对应 Git 提交或标签 | `7a31fe2`（2026-10-16，「阶段 05（v0.1.1）：在线虚拟机自动发现」）。阶段五单独一次提交 |

## 2. 阶段目标

任务书 §六（`2.md:152-190`）要求：

1. **先调查再实现**：先检查当前 Windows 环境及现有依赖，确定可用且安全的发现方式，再选择实现方案（`2.md:156`）。阶段五因此先做了本机实测，并把取舍落成决策 **D-018**（`docs/DECISIONS.md`）。
2. **发现范围**（五条）：优先发现本机可见、运行中且网络可达的虚拟机；优先用 VMware 清单、虚拟机运行状态、虚拟网络信息与可获得的 DHCP 租约等**本地信息**；存在其它虚拟化平台时先评估是否确实需要，**不擅自扩展**；「发现了虚拟机」「检测到某个 IP 在线」「确认该主机提供 SSH 服务」**三种状态不能混为一谈**；结果要给可验证信息（名称、IP、SSH 端口状态、信息来源），未知就明确显示未知。
3. **用户交互**（八条）：有「扫描虚拟机」或同等入口；显示扫描状态、发现数量、失败原因与可用结果；支持重新扫描、取消扫描、从结果创建连接；创建连接时允许用户检查并修改地址、端口、用户名与认证方式；不凭 IP 自动建可信连接、不自动信任主机指纹；首次连接与指纹变化仍走既有确认；**扫描失败时手动添加连接必须仍然可用**。
4. **网络与权限边界**（七条）：只用本机虚拟化管理信息加有限范围的网络发现，不做无边界全网扫描；不扫未授权网络；不得为发现而修改防火墙、路由、网卡、DHCP 或虚拟机网络配置；不要求管理员权限，需要更高权限才能读的来源就跳过并解释原因；不依赖固定 IP、固定网卡名、固定虚拟机名；不尝试用户名、不猜密码、不遍历凭据登录；发现只提供候选，不绕过身份认证。
5. **测试要求**（八类场景 + 一条纪律）：运行且 SSH 可达 / 运行但 SSH 不可达 / 已关闭 / 多台 / IP 变化 / 重复结果 / 取消 / 失败；环境无法真实验证某场景时**必须标记未验证**，不得用模拟结果冒充真实测试。

## 3. 实际完成情况

**已完成**

- **环境调查与决策**：实测本机 VMware Workstation 26 的注册表 `InstallPath`、`vmrun list`、清单 `inventory.vmls`、`vmnetdhcp.conf` 与 `vmnetdhcp.leases`、`Get-NetNeighbor` 邻居表，并把可用来源、不可用来源与否决掉的备选写进 `docs/DECISIONS.md` 的 D-018（五层取材、三种状态分开建模、探测上限；否决 `vmrest` 与「读进程命令行」，后者在非管理员下实测读不到）。
- **服务层** `app/services/discovery.py`（新增）：五层读取 + 纯解析函数（`parse_inventory` `:221`、`parse_vmx` `:256`、`parse_leases` `:307`、`latest_by_mac` `:371`、`parse_vmnet_conf` `:381`、`parse_neighbors_csv` `:448`、`parse_arp` `:475`）、探测（`probe_address` `:707`）、融合（`_pick_primary` `:811`、`_vm_state` `:827`、`_any_ssh_open` `:841`、`_vm_record` `:852`）、环境概览（`environment_summary` `:909`）、纯函数扫描入口（`collect` `:983`）与扫描注册处（`Discovery` `:1393`、`DiscoveryRegistry` `:1523`）。
- **四个 HTTP 端点**（编号第 29~32）：`GET /api/discovery`（`app/api/handlers.py:199`）、`POST /api/discovery/scan`（202，`:209`）、`GET /api/discovery/scans/{scan_id}`（`:220`）、`DELETE` 同路径（`:224`）；路由表在 `app/api/handlers.py:472-506`。发现端点不挂在任何连接之下，也不需要已连接。
- **配置段** `discovery`（9 个键）：`app/core/config.py` 的 `DEFAULTS` `:47`、`DiscoveryConfig` `:162`、`_DISCOVERY_KEYS` `:340`、`parse_config`，以及 `config/config.example.json`。
- **错误模型**：`DiscoveryBusy`（`code=discovery_busy`，409，`app/core/errors.py:225`），同一时刻只允许一个扫描。
- **前端**：`frontend/assets/js/discovery.js`（新增：入口、环境六来源状态、阶段与进度、中止、结果三张表、从结果创建连接）、`frontend/assets/js/api.js` 四个方法、`frontend/index.html` 侧栏「扫描」按钮（`#btn-scan-vms`）、`frontend/assets/css/app.css` 样式、`frontend/assets/js/app.js` 接线、`frontend/assets/js/connections.js` 的 `openConnectionForm(existing, options)` 支持草稿预填与提示语。
- **四层测试**：单元 49 项（`tests/unit/test_discovery.py`）、集成 10 项（`tests/integration/test_discovery_api.py`）、安全 11 项（`tests/security/test_discovery_paths.py`）、端到端 4 项（`tests/e2e/test_browser_discovery.py`）；另在 `tests/unit/test_config.py` 补了 discovery 段与模板加载的用例。
- **文档**：`docs/API.md` 扩到 32 个端点并新增 §5.29–5.32 与 §7.4、`docs/USER_GUIDE.md` 新增 §4.4 与 §10.2 的 discovery 段、`docs/CHANGELOG.md` v0.1.1 段、本报告与各层 `_index.md` 登记。

**部分完成**

- **只支持 VMware Workstation**：任务书要求「如果存在其它虚拟化平台，应先评估现有环境是否确实需要支持」，调查确认本机只有 VMware（v0.1.0 的 T-003 也是按 VMware 记录的），因此不擅自扩到 VirtualBox / Hyper-V / 远程 ESXi，写进已知限制。
- **「SSH 可用」的判据是 22 端口一次 TCP 连接成功**，不是完整 SSH 握手：这是 AWFM 自己的语义（它只做 SSH 文件管理），不登录、不试凭据、不派生 `ssh.exe`（安全层用例断言进程数不变）。
- **邻居表只有 Windows 读得到**：`read_neighbors`（`:681`）在非 win32 直接返回 `unavailable`，其它平台地址只能来自租约与清单，界面上会如实显示该来源不可用。
- **非管理员读不到 VMware 进程命令行**：`environment_summary` 把 `process` 这一来源固定标成 `denied`，并写明「读取 VMware 进程的命令行需要管理员权限，已跳过；运行状态改由 vmrun 判断。」运行状态完全由 `vmrun` 决定。
- **取消是「请求已受理」而不是「已经停下」**：读清单 / 跑 `vmrun` / 查邻居表这些子进程打断不了，实测从 DELETE 到真正停下用 3.74 s。`DELETE` 的返回里 `running` 仍可能为 `true`，集成用例断言的是终态与 `interrupted`，不假定它立刻停下。
- **「运行但 SSH 不可达」与「IP 变化」只用模拟覆盖**——见下。

**未完成及原因**

- 真实桌面 CU 验收（任务书阶段六）未执行；本阶段证据全部来自自动化测试。
- 版本号仍是 `0.1.0`，便携发行包与校验和仍是 v0.1.0 的那一份（阶段六统一处理）。
- 按任务书第 190 行的纪律，以下场景**标记为未验证**（模拟覆盖，不是真实观测）：
  1. **虚拟机运行但 SSH 不可达**：本机真实环境里没有这样一台虚拟机（运行中的 CentOS Stream 10 的 22 端口是通的，已关机的 Ubuntu 不可达）。这条由单元测试的注入探测覆盖（`refused` → 地址级 `ssh_state=refused`、虚拟机级 `answer_state=online`、`ssh_open=False`），以及前端三态渲染的 e2e 用例。
  2. **扫描期间虚拟机 IP 变化**：真实证据只到「同一个 MAC 的历史租约曾指向另一个地址（`.130`）而当前地址是客户机自报的 `.128`」——地址会变这件事是真的，但扫描进行中地址发生变化没有被真实观测到。重复地址的处理由 `latest_by_mac`（同 MAC 取最后一条）与 `_pick_primary`（来源优先级 guest > neighbor > lease > arp > vmnet）的单元测试覆盖。
  3. **扫描失败**：单元测试用 `mock.patch` 让 `collect` 抛 `RuntimeError` 验证 `status=failed` 与 `error` 的结构，真实环境没有失败过一次。

## 4. 技术实现

- **五层取材，每层只回答它能回答的问题**：① `inventory.vmls`（有哪些虚拟机、叫什么）② `vmrun list`（**哪些在运行**，唯一权威来源，是**可选依赖**）③ `.vmx`（客户机类型、内存、CPU、网卡 MAC 与网络类型）④ `vmnetdhcp.conf` 与 `vmnetdhcp.leases`（虚拟网段、地址池、网关与地址历史）⑤ 系统邻居表（最近谁在线）+ 仅限已知虚拟网段的 22 端口探测；装了 VMware Tools 时再用 `vmrun getGuestIPAddress` 问客户机自报的地址（实测 487 ms 返回，超时 5 秒）。理由：任务书要求「优先使用本机已有的虚拟化管理信息」，而单一来源都不足以同时回答「有哪台机器」与「现在能不能连」。
- **三种状态是三个独立字段，不是一个状态机**：`answer_state`（`unknown_address` / `not_probed` / `ssh_open` / `online` / `no_answer`）回答「发现到什么程度」，地址级 `ssh_state` 保留探测原始结论（`open` / `refused` / `timeout` / `unreachable` / `not_probed` / `error`）。虚拟机级 `ssh_open` 是布尔或 `null`——`null` 表示「一个地址都没探测过」，**不是**「确定连不上」。理由：任务书第 163 行明令三者不得混为一谈，而「没探过」与「探了没通」在界面上必须分得开。
- **`collect` 是纯函数、不起线程、不碰时钟**：它接受 `env` / `probe` / `guest_ip` / `is_cancelled` / `on_stage` 注入，所以单元测试可以完全不连网地断言融合结果；真正起线程的只有 `Discovery._run`。理由：把「取材与判断」和「并发与生命周期」分开，才有可断言的中间层。
- **探测就是一次 `socket.connect`**（`probe_address` `:707`）：`open` / `refused`（对端回 RST，说明**主机在线但没有 SSH**）/ `timeout` / `unreachable` 四态分开。理由：任务书要求「确认该主机提供 SSH 服务」，而 AWFM 的用途本身就是 SSH；直接连 22 端口既能回答这个问题，又不需要凭据、不会留登录记录。
- **四道上限同时生效**：单地址 `probe_timeout_seconds`（默认 1 秒，范围 0.1~5.0）、每网段 `max_addresses_per_subnet`（254）、整轮 `max_probes`（512）、总时长 `time_budget_seconds`（60 秒）；探测按批起 daemon 线程（每批 `max_probe_workers×2`）。碰到上限记 `truncated` 与 `truncated_reason`，用户中止记 `interrupted`，两者可以同时为真。理由：任务书禁止无边界全网扫描，上限必须是配置项并且要在结果里说清楚。
- **本机虚拟网卡与网关地址既不是候选也不被探测**：`host_addresses` 取自每个网段的本机地址与网关，在「其它地址」循环里就跳过并单独计数（本机实测跳过 1 条），并让说明真的出现在 `notes` 里。理由：这两个地址不是「另一台能连的机器」，列出来只会误导（这条是本阶段修掉的第 3 个真实缺陷）。
- **`vmrun` 缺席时状态是「未知」而不是「已关机」**：`state = "running" if key in running_set else ("stopped" if environment.vmrun_path else "unknown")`（`app/services/discovery.py:1122`）。理由：读不到运行状态就说「已关机」是在编事实。
- **过期租约只当线索**：`.leases` 是追加日志，`ends` 是 UTC，过期条目进候选但带一句「租约地址 X 已过期，只能当作线索。」；同一 MAC 多条租约只取最后一条。理由：租约是历史，不是现状。
- **注册处与生命周期**：`DiscoveryRegistry.start()` 先查 `enabled`（关掉时抛 `ValidationError`）再查「是否已有扫描在跑」（抛 `DiscoveryBusy`，409），最后 `_prune_locked()` 只保留最近 10 次已结束的扫描；`shutdown(timeout=5.0)` 在 `app/main.py` 的退出路径里逐个取消并等待。取消用**每次扫描新建**的 `threading.Event`，`Discovery._run` 结束时若「活儿干完了但用户点过中止」仍报 `done`（谎报中止会让人以为结果是残缺的），只把 `interrupted` 置真。
- **阶段收尾写 `done`**：`collect` 内部的 `on_stage` 只报 `inventory` / `running` / `vmx` / `leases` / `neighbors` / `probe`，结束时由 `Discovery._run` 明确收成 `stage="done"`；失败时保留当时那一步，好看出卡在哪里。
- **前端把「三种状态」变成三张表**：虚拟机表（名称 / 状态 / 地址 / 结论 / 操作）、「地址在线但没有 SSH」与「SSH 可用」两张互斥的其它地址表（判据分别是 `responded===true && ssh_open!==true` 与 `ssh_open===true`）。结果行上的「创建连接」生成一份**草稿**（`name/host/port/username/auth_method/identity_file/note/allow_write`）交给既有表单预填：因为 `connections.js` 原先用 `Boolean(existing)` 判断编辑模式，本阶段改成 `Boolean(existing && existing.id)`，否则草稿会被当成「编辑已有连接」并在保存时拿一个不存在的 id 去 PATCH。
- **模态只有一个**：`modal.js` 复用唯一模态 DOM，所以「从结果创建连接」必须先 `closeModal` 再 `openModal`（`onClose` 在清空之后才调用，因此不会把新开的内容抹掉）；关闭发现面板时若扫描还在跑，自动发一次中止请求（后端同时只允许一个扫描，留着会让下次「开始扫描」直接吃 409）。
- **轮询作废机制**：`pollToken` 与 `envToken` 与 `search.js` 同款——每次发起自增，回调里比对，过期响应直接丢弃，避免「两次扫描的结果互相覆盖」。
- **请求形状与鉴权**：四个端点全部先过令牌（无令牌 401），扫描 id 只接受 `[0-9a-f]+`（畸形一律 404，不做「猜测式匹配」），`POST /api/discovery` 这种错方法返回 400。

## 5. 测试结果

命令（工作目录 `E:/Project/aimus-web-file-manager`）：

```
python scripts/test.py
```

实际输出（2026-10-16，测试床 127.0.0.1:2222 在线，Edge 可用）：

```
== 语法校验：python -W error::SyntaxWarning -m compileall -q app tests scripts ==
通过（0.30s）

== 汇总 ==
unit           505 用例    0 失败    0 错误    0 跳过    3.03s  OK
integration    108 用例    0 失败    0 错误    0 跳过   44.27s  OK
security        82 用例    0 失败    0 错误    0 跳过   46.71s  OK
e2e             22 用例    0 失败    0 错误    0 跳过  122.45s  OK
合计             717 用例    0 失败    0 错误    0 跳过  216.45s

全部通过。
```

本阶段新增用例分布：

| 层 | 文件 | 用例数 | 覆盖点 |
|---|---|---|---|
| 单元 | `tests/unit/test_discovery.py` | 49 | 真实格式样本驱动的解析（清单出现顺序、`.vmx` 的 `addressType` 不是 MAC、禁用网卡被丢弃、带冒号的键被忽略、租约时间是 UTC 与过期边界、同 MAC 取最后一条、`VMnet` 编号来自注释而非地址、host 块不污染网段网关、邻居表列序无关）；假 socket 驱动的探测四态与「没探过是 unknown 而不是 False」；注入探测与环境后的三态融合（`ssh_open` / `online` / `unknown_address`）、只探预期地址、本机与网关不作候选、清单重复条目合并并说明、`counts` 与已知事实一致、缺 `vmrun` 时全部「未知」、关掉探测一个包都不发、取消与上限截断、单个探测抛错不影响整轮；注册处的忙 / 取消 / 保留上限 / 失败 / 关闭 / 环境概览 |
| 集成 | `tests/integration/test_discovery_api.py` | 10 | 真机上的四个端点：环境概览六来源与 `process` 恒为 denied、未知扫描 id 404、扫描完成且 `counts` 自洽、被探测地址都落在已知虚拟网段且只探 22、本机与网关永不被探测、`notes` 说明过滤、`vmrun` 报运行中的虚拟机能被找到并带地址、能连 SSH 的那台被标成 `ssh_open`、并发第二次 409、取消后槽位真的空出来（能再扫一次） |
| 安全 | `tests/security/test_discovery_paths.py` | 11 | 四个端点无令牌 401、畸形扫描 id 404、`POST /api/discovery` 400、读环境不会留下扫描；探测只在已知网段且只探 22、本机与网关既不是候选也不被探测、`probe_ssh=false` 一个包都不发、`max_probes=1` 是真上限、扫描前后 VMware 三个文件**内容逐字节不变**、扫描前后 `ssh.exe` 进程数不变、扫描不往连接表里加任何东西 |
| 端到端 | `tests/e2e/test_browser_discovery.py` | 4 | 真实无头 Edge：面板说出这台机器能读什么（含「需要管理员权限」那一行）、扫描结果三态分开且标题台数 = 行数 = 进度台数、中止后终态 `cancelled` 且能立刻重扫、从结果「创建连接」预填表单且**保存不了**（走新增分支、只有一个模态、发现面板已让位） |

测试基建：

- 集成层`tests/integration/support.py`新增 `start_discovery_scan` / `wait_discovery_scan` / `scan_and_wait`；这一层**不依赖 WSL 测试床**（发现读的是宿主机自己的 VMware 状态），没有 VMware 的机器整类跳过。
- 安全层自带 `count_ssh_processes()` 与 `read_vmware_files()`，前者在 Windows 上用 `Get-CimInstance` 数 `ssh.exe`（必须用 `@()` 包成数组，否则只剩一个进程时 PowerShell 5.1 把 `.Count` 当空串），后者按三个路径读原文做前后比对。
- 端到端夹具沿用 `tests/e2e/support.py` 的无头 Edge（`--headless=new --inprivate` + 全新临时 profile + CDP），截图落在 `tests/e2e/artifacts/browser-discovery-{panel,scan,connection}-<RUN_TAG>.png`。

真机实测数字（阶段五的三份真实证据之一，另两份是决策 D-018 的调查记录与本报告 §6 的缺陷复验）：

- 本机 3 台虚拟机（其中 1 台在运行）、探测 3/3 个地址、1 个地址 SSH 可用，整轮 **4.2~5.1 秒**；
- 运行中的 CentOS Stream 10：地址来自客户机自报（`vmrun getGuestIPAddress`）`192.168.170.128`，22 端口 **14 ms** 连上；同一 MAC 的过期租约 `.130` 作为线索列出；
- 已关机的 Ubuntu x64：地址来自邻居表（`Stale`）`192.168.170.129`，探测无响应 1014 ms；
- 清单里有 1 条指向已不在磁盘上的 `.vmx`：状态「已关机」、无地址、带一句「配置文件不在磁盘上（可能已被删除或移动）。」

## 6. 问题与风险

本阶段发现并修掉 **3 处真实缺陷**（都不在阶段五的新功能里，而是被阶段五的测试与阅读照出来的）：

1. **随包发布的配置模板根本加载不了**（`config/config.example.json`）：第 2 行写着 `"$schema": "./config.schema.json"`，而 `config/` 下没有这个文件、全仓库也没有第二处引用；`parse_config` 又会因未知根字段直接抛 `ConfigError`（「配置里含无法识别的字段」），于是「照抄随包模板」的结果是程序启动不了。修复为删掉该行（模板现与 `DEFAULTS` 逐字段相等），并把 `example_config_text()`（`app/core/config.py:541`）由 `json.dumps(DEFAULTS)` 改为**真的读磁盘模板**——原来那条「模板与默认值一致」的单元测试比的是「自己刚生成的字符串」，模板少一整段也照样通过，属于自证。
2. **用户自定义的 `security.max_edit_bytes` 会被静默丢掉**（`app/core/config.py` 的 `to_dict`）：`to_dict` 的 `security` 段漏了这个键，而连接管理每次增删改连接都会 `save_config()`，于是用户把它调大之后，只要在界面上动一次连接，设置就被写回默认的 2 MiB。修复为补上该键，并加了一条 `parse_config(to_dict())` 的往返用例（自定义值 123456 与 `discovery.max_probes=64` 都不丢）。
3. **本机虚拟网卡与网关地址既是候选又永远不会被探测**（`app/services/discovery.py`）：`targets` 已经排除了它们，但「其它地址」列表没有排除，于是 `192.168.170.1`/`.2` 这类地址会出现在结果里永远标着「未探测」；而那句解释「本机虚拟网卡与网关地址不做探测。」写在 `if host_addresses & set(targets)` 里——这个条件恒为假，**是一句永远不会出现的死代码**。修复为在「其它地址」循环里就跳过并单独计数，让说明真的会出现在 `notes` 里；本机复验：跳过 1 条，与既有的「过滤 172 条」相加仍是 173，没有重复计数。

另有一处**收尾语义**（不是缺陷，是打磨）：扫描结束后 `stage` 原本停在最后一个动作（通常是 `probe`）上，界面看起来像卡住了；现在结束（含用户中止）时明确收成 `done`，失败时保留当时那一步。

还有 **2 处测试自身的缺陷**（不是产品缺陷，写下来是因为教训值钱）：

- 端到端「中止后再扫一次」用例第一版把上一次的结论当成了这一次的：`start_scan` 点击后 POST 是异步的，DOM 里药丸还写着上一次的「已中止」，紧接着的等待条件立刻为真。修复为点击后先等状态变成 `running`（后端新扫描的初始快照就是 `running`，因此等待是确定性的）。
- 「环境详情里有探测上限」断言失败是因为 `<details>` 收起时内部内容不渲染，`innerText` 返回空串（`textContent` 才拿得到）。修复为先断言默认收起，再置 `open` 取文本。

风险与已知限制：

- **探测范围取决于 `vmnetdhcp.conf`**：本机两个网段（`192.168.11.0/24` 与 `192.168.170.0/24`）各最多 254 个地址、整轮最多 512 次、总时长 60 秒。超过就截断并说明，不会静默少探。
- **只判断 22 端口通不通**：不识别机器上跑的其它服务，也不区分「机器没开」与「防火墙拦了」（两者都表现为 `timeout`）。
- **邻居表是缓存**：`Stale` / `Reachable` 只说明最近见过，不能当作「此刻在线」；因此地址的最终结论以探测为准，`answer_state` 与 `ip_source` 都带来源字段。
- **只认 VMware Workstation**：不认 VirtualBox、Hyper-V，也不认远程 ESXi；`vmrun` 缺失时运行状态只能标「未知」。
- **取消不保证立刻停**：读清单 / 跑 `vmrun` / 查邻居表打断不了，实测 3.74 s 才真正停下；`DELETE` 返回时 `running` 可能仍为 `true`。
- **结果只是候选**：不写连接表、不自动信任主机指纹、不自动连接；从结果「创建连接」只是预填表单，保存后点「连接」仍要过指纹确认。
- **扫描失败不影响既有功能**：`DiscoveryBusy` / 失败快照都只作用在发现面板上，手动添加连接不受影响（安全层的 401 与 400 用例在无 VMware 的临时配置下也全套通过）。
- 端到端依赖本机 Edge，缺 Edge 时该层跳过——本项目纪律是**跳过不算通过**，运行器会单独列出跳过数。

## 7. 文档与交付物

- 代码：`app/services/discovery.py`（新增）、`app/api/handlers.py`（四个处理器与路由表）、`app/api/http_server.py`（`AppContext.discovery`）、`app/main.py`（退出时 `shutdown`）、`app/core/config.py`、`app/core/errors.py`、`config/config.example.json`、`frontend/assets/js/discovery.js`（新增）、`frontend/assets/js/api.js`、`frontend/assets/js/app.js`、`frontend/assets/js/connections.js`、`frontend/index.html`、`frontend/assets/css/app.css`。
- 测试：上表 4 个文件，另加 `tests/unit/test_config.py`（模板加载与 discovery 段）、`tests/unit/test_errors.py`（登记 `DiscoveryBusy`）、`tests/integration/support.py`（三个扫描辅助）、`tests/e2e/artifacts/` 截图。
- 文档：`docs/DECISIONS.md`（D-018）、`docs/API.md`（32 个端点、§5.29–5.32、§6 错误码、§7.4）、`docs/USER_GUIDE.md`（§4.4 与 §10.2 的 discovery 段）、`docs/CHANGELOG.md`（v0.1.1 段）、本报告、`app/services/_index.md` 与 `tests/{unit,integration,security,e2e}/_index.md`、`frontend/assets/js/_index.md` 登记。
- 未产出：打包产物与校验和仍是 v0.1.0 的那一份（任务书阶段六要求重新构建）。

## 8. 阶段结论

阶段五（在线虚拟机自动发现）**功能与测试已完成**：五层取材的发现服务、四个端点、配置段与错误模型、前端入口与三态结果表全部落地，四层测试全绿（本阶段新增 74 项），任务书 §六的四组要求逐条有实现与测试证据。

允许进入阶段六（回归、CU 验收与交付）。遗留事项：真实桌面 CU 验收、版本号提升与重新打包属阶段六；**「运行但 SSH 不可达」「扫描期间 IP 变化」「扫描失败」三个场景只有模拟覆盖，已按任务书要求在上文标记未验证**；非 VMware 平台、非 Windows 邻居表、可配置的探测上限留待后续版本。
