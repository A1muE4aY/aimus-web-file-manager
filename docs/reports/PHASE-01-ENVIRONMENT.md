# 阶段 01 报告：需求分析与环境调查

## 1. 报告信息

| 项 | 值 |
|---|---|
| 项目 | Aimu's Web File Manager (AWFM) |
| 版本 | v0.1.0（开发版） |
| 报告日期 | 2026-10-15 |
| 阶段 | 阶段 01 / 需求分析与环境调查 |
| Git commit | 首次提交之前（本报告随首个提交入库） |
| 依据 | 规划文档 §6.1 阶段 01、§13 开工前四问 |

## 2. 阶段目标

按规划文档 §6.1，阶段 01 只做两件事，不写业务代码：

1. **需求分析** —— 把规划文档的功能分级（§3.1 P0/P1/P2、§3.2 首版不做）落成可追溯的需求编号。
2. **环境调查** —— 回答 §13 的「开工前四问」，确认技术路线在本机真的可行。

**进入阶段 02 的验收条件**：四问都有确定答案，且选定路线所需的每个外部组件都经实测确认存在。

## 3. 实际完成情况

### 3.1 已完成

| 项 | 产物 | 状态 |
|---|---|---|
| 开工前四问 | 与用户逐项确认，见 §4 决策表 | 已完成 |
| 需求编号化 | `docs/REQUIREMENTS.md`（F-P0-01..07、F-P1-01..07、N-01..N-07） | 已完成 |
| 宿主机环境调查 | 本文 §4.1 | 已完成 |
| 技术选型记录 | `docs/DECISIONS.md` D-001..D-010 | 已完成 |
| 目录结构规范 | `docs/PROJECT_STRUCTURE.md` | 已完成 |
| 配置模板 | `config/config.example.json` | 已完成 |
| 工作区基线 | `README.md`、`AGENTS.md`、`.gitignore`、`.git` | 已完成 |
| 测试床可行性 | **超出阶段 01 范围**，因阻塞而提前在阶段 02 SPIKE 解决 | 见 PHASE-02-SPIKE |

### 3.2 部分完成

| 项 | 缺口 | 原因 |
|---|---|---|
| 目标虚拟机环境调查 | 只查到 VMX 路径与静态信息，未取得目标机运行时事实 | CentOS 虚拟机当前**未开机**（192.168.170.128 ping 不通、22 端口不通），且无免密途径开机 |
| 本机 SSH 服务端 | 不可用 | 无 `sshd.exe`；安装 Windows OpenSSH Server 需管理员权限，当前会话无提权 |

### 3.3 未完成

无。

## 4. 技术实现（本阶段为调查，非实现）

### 4.1 宿主机实测环境（2026-10-15）

| 组件 | 实测结果 |
|---|---|
| 操作系统 | Microsoft Windows 11 家庭版，Version 10.0.26300，Build 26300，AMD64 |
| 用户权限 | `LAPTOP-SB2OIK3D\Aimu2`，**IsAdmin=False** |
| PowerShell | **5.1.26100.9444（不是 PowerShell 7）** —— 脚本不得使用 PS7 专属语法 |
| Python | `python` → `E:\Software\Python 3.12\python.exe`（**3.12.10**）；**无 `python3`**；`py` 启动器存在；另有 `E:\Software\Python 3.13` |
| OpenSSH 客户端 | `C:\Windows\System32\OpenSSH\`，`OpenSSH_for_Windows_9.5p2, LibreSSL 3.8.2`；ssh / sftp / scp / ssh-keygen / ssh-add / ssh-agent / ssh-keyscan 均在 |
| OpenSSH 服务端 | **不存在 `sshd.exe`**，无法在本机搭建 SSH 目标 |
| 本机 22 端口 | 关闭 |
| git | `C:\Program Files\Git\cmd\git.exe` |
| node | `E:\Software\.nodejs\node.exe` |
| VMware Workstation | **26.0.0 (build 25388281)**，安装于 `E:\VMware Workstation Pro\`，`vmrun.exe` 存在 |
| VMware 网络 | VMnet8 = `192.168.170.1/24`（NAT）；VMnet1 = `192.168.11.1/24`（Host-only） |
| VMware 服务 | VMnetDHCP 运行中；VMware NAT Service 运行中；VmwareAutostartService 已停止 |
| 虚拟机清单 | `E:\Virtual Machines\CentOS 10\CentOS Stream 10.vmx`、`...\CentOS version 5 and earlier 64-bit.vmx`、`E:\Virtual Machines\Ubuntu x64\Ubuntu x64.vmx` |
| `~/.ssh` | 只有 `known_hosts`(923 B) 与 `known_hosts.old`(91 B)，**无 config 文件**；条目主机名为 `hadoop01`(×3) 与 `192.168.170.128` |
| 目标机连通性 | `192.168.170.128`：PingSucceeded=**False**，TcpTestSucceeded=**False**；ARP 中 MAC `00-0C-29-58-7B-2A`（VMware OUI）但状态 Stale → **虚拟机未开机** |
| WSL2 | 可用。发行版 `Ubuntu`（Version 2，默认）。用户 `aimu`(uid=1000)，属组含 `sudo`，但 `sudo -n true` 报「需要密码」→ **无免密 sudo** |

**调查方法**：全部结论来自实际执行的命令输出（`Get-ComputerInfo`、`ssh -V`、`Test-NetConnection`、
`Get-ChildItem`、`wsl.exe --list --verbose` 等），未采信任何文档或记忆中的说法。

### 4.2 开工前四问的答案

| 问 | 用户确认的答案 |
|---|---|
| ① 宿主机环境 | **Windows 本机** |
| ② 目标虚拟机系统 | **Linux 优先**；集成测试目标为 `CentOS Stream 10.vmx` |
| ③ 交付方式 | **两者都要**：源码开发版 + 便携发行版 |
| ④ SSH 认证方式 | **密钥优先，同时支持密码** |

规划文档 §13 建议的第一版目标为「Windows 宿主机 + Linux 虚拟机 + 本地浏览器 +
SSH 密钥认证 + 便携式发行包」—— 四问答案与之**完全一致**，无偏离。

### 4.3 与规划文档的差异

| 规划文档的设想 | 实测后的调整 | 原因 |
|---|---|---|
| 目标虚拟机随时可用 | 需用户手动开机 | 当前无法在无人值守下启动虚拟机，且无免密途径 |
| 用 `ls -l` 文本或 `sftp` CLI 获取目录 | **改为原生 SFTP v3 协议**（D-011） | 见 `docs/reports/PHASE-02-SPIKE.md` |
| 集成测试目标 = CentOS 虚拟机 | 阶段 02/03 另用 **WSL 非 root sshd 测试床**（D-012），CentOS 留待阶段 05 | CentOS 未开机；WSL 测试床零提权、可脚本化复现 |

## 5. 测试结果

### 5.1 测试环境

- 宿主机：Windows 11 build 26300，PowerShell 5.1.26100.9444
- Python：3.12.10（`E:\Software\Python 3.12\python.exe`）
- 测试床：WSL2 Ubuntu + 用户态 sshd，监听 `127.0.0.1:2222`

### 5.2 本阶段的验证

阶段 01 是调查阶段，规划文档 §7.1 的 T-001..T-014 测试矩阵**全部处于 NOT RUN 状态**
（被测系统尚未存在）。本阶段执行的是**环境前提验证**：

| 检查 | 命令 | 结果 |
|---|---|---|
| 宿主 OS 与架构 | `Get-ComputerInfo` | PASS |
| Python 版本与路径 | `python -V` / `Get-Command python` | PASS（3.12.10） |
| OpenSSH 客户端版本 | `ssh -V` | PASS（9.5p2） |
| OpenSSH 服务端存在性 | `Get-ChildItem C:\Windows\System32\OpenSSH\sshd.exe` | **不可用**（文件不存在） |
| VMware 与 vmrun | `Test-Path` | PASS |
| 目标机可达性 | `Test-NetConnection 192.168.170.128 -Port 22` | **FAIL**（虚拟机未开机） |
| WSL2 可用性 | `wsl.exe --list --verbose` | PASS |

### 5.3 统计

| 类别 | 数量 |
|---|---|
| 检查总数 | 7 |
| PASS | 5 |
| FAIL（环境限制，非产品缺陷） | 2 |
| 规划测试矩阵 T-001..T-014 | 14 项，全部 **NOT RUN** |

**如实声明**：两项 FAIL 是**环境限制**，不是本项目代码的缺陷 —— 此时尚无任何项目代码。
但它们构成真实风险，已登记在 §6。

## 6. 问题与风险

### 6.1 已发现

| 编号 | 问题 | 严重度 | 处置 |
|---|---|---|---|
| R-01 | 目标 CentOS 虚拟机未开机，无法做端到端验证 | 中 | 阶段 05 前由用户开机；阶段 02/03 先用 WSL 测试床替代 |
| R-02 | 本机无 SSH 服务端且无提权，无法在本机验证「服务端」相关行为 | 低 | 由 WSL 测试床覆盖；不在 Windows 上验证服务端行为 |
| R-03 | PowerShell 5.1（非 7） | 低 | 所有脚本避免 PS7 专属语法；脚本以 Python 为主 |
| R-04 | `ssh-keyscan` 在 Windows OpenSSH 9.5p2 上不可用 | 中 | 已找到替代方案（P-005），阶段 03 实现 |

### 6.2 复现步骤（R-04）

```powershell
ssh-keyscan -p 2222 -t ed25519 127.0.0.1
# 输出：
#   # 127.0.0.1:2222 SSH-2.0-OpenSSH_9.6p1 Ubuntu-3ubuntu13.20
#   debug1: kex: algorithm: sntrup761x25519-sha512@openssh.com
#   choose_kex: unsupported KEX method sntrup761x25519-sha512@openssh.com
# 退出码 1，未产出任何 host key 行。
```

### 6.3 尚存风险

- **无法验证真实 CentOS 目标的路径语义**（符号链接策略、挂载点、`/proc` 等伪文件系统行为）。
  测试床是 Ubuntu，与 CentOS 同为 Linux，但**不等于**已验证。
- 集成测试的真实性受限于 WSL2 的 `localhost` 转发特性：它证明了「本机回环可达」，
  **不证明**「经 NAT 网段可达真实虚拟机」。

## 7. 文档与交付物

| 文件 | 说明 |
|---|---|
| `docs/REQUIREMENTS.md` | 需求编号表（P0/P1/P2/不做 + 非功能需求） |
| `docs/DECISIONS.md` | D-001..D-010 决策记录 |
| `docs/PROJECT_STRUCTURE.md` | 目录结构与命名规范（规划文档 §5.1 要求，作为验收标准） |
| `docs/_index.md` | docs/ 索引 |
| `docs/reports/_index.md` | 报告索引 |
| `config/config.example.json` | 配置模板 |
| `README.md` | 项目简介与文档入口 |
| `AGENTS.md` | 工作区顶层白名单与环境事实 |
| `.gitignore` | 忽略运行时目录与密钥 |

## 8. 阶段结论

- **是否达到验收条件：是。** 四问全部有确定答案；选定路线的外部组件（Python 3.12、
  OpenSSH 客户端、VMware、WSL2）全部经实测确认存在。
- **是否允许进入阶段 02：允许。**
- **后续任务**：
  1. 阶段 02 最小原型：本地 HTTP 服务 + 健康检查 + SFTP 连接 + 远程目录读取 + JSON 响应。
  2. 阶段 02 SPIKE 已完成（见 `PHASE-02-SPIKE.md`），连接层基线确定为原生 SFTP v3 协议。
  3. 阶段 05 前需用户开机 CentOS 虚拟机以补齐端到端验证（R-01）。
