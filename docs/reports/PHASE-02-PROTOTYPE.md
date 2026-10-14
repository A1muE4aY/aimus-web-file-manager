# 阶段 02 报告：最小原型

## 1. 报告信息
| 项 | 值 |
|---|---|
| 项目 | Aimu's Web File Manager (AWFM) |
| 版本 | v0.1.0（开发版） |
| 报告日期 | 2026-10-15 |
| 阶段 | 阶段 02 / 最小原型 |
| 对应 Git 提交或标签 | 无（阶段 02 前置产物为 `d2f94e0`；原型代码与阶段 03 产物为未提交的工作区状态） |
| 依据 | 规划文档 §6.1 阶段 02；`docs/reports/PHASE-02-SPIKE.md`（219 行）；`docs/DECISIONS.md` D-011 / D-012 / D-013 |

## 2. 阶段目标
**计划完成事项**（规划文档 §6.1 阶段 02，产物 = 可启动服务 / SSH 连接验证 / 首份测试记录）：
1. 本地页面可打开，全部资源离线加载（T-002）。
2. `GET /api/health` 可用，默认只监听 `127.0.0.1`（N-03）。
3. 用系统 OpenSSH 子进程建立 SSH/SFTP 连接（T-003）。
4. 读出目标机目录列表并渲染（T-006）。
5. 首次连接必须报主机密钥未知，不静默接受（T-005 前置）。
6. 留下首份可复现的测试记录。

**验收标准**：服务启动并写明监听地址（`logs/awfm.log:1-2`）；主机密钥两阶段确认——未确认前信任库必须为空、错误指纹必须被拒；后端运行时第三方依赖数 = 0（N-02）；前端无任何外部 URL（T-002）。上传下载、预览、安全测试套件与打包不在本阶段范围（分属阶段 03/04/05）。

## 3. 实际完成情况
**已完成**（除注明「未提交」者外均已入库于 `d2f94e0`；下列行数均为该提交时的状态，后续阶段扩充后已变）：
| 项 | 产物 |
|---|---|
| 连接层路线验证 | `docs/reports/PHASE-02-SPIKE.md`（219 行）；D-004 作废，新增 D-011 / D-012 / D-013 |
| 需求与决策基线 | `docs/REQUIREMENTS.md`（84 行）、`docs/DECISIONS.md`（201 行，D-001..D-013） |
| 结构与索引 | `docs/PROJECT_STRUCTURE.md`（98 行）、`docs/_index.md`（11 行）、`docs/reports/_index.md`（20 行） |
| 配置模板 | `config/config.example.json`（29 行，`config_version: 1`）、`config/.gitignore`（3 行） |
| 工作区基线 | `README.md`（86 行）、`AGENTS.md`（46 行）、`.gitignore`（53 行）、`.md`（503 行，规划文档原件） |
| 可启动服务（未提交） | `app/main.py`（273 行，`--init-config` / `--check` / 默认启动）；`logs/awfm.log:1` 首条「AWFM 0.1.0 已启动：http://127.0.0.1:8760/」（2026-10-15 00:27:42） |
| 本地页面与目录列表（未提交） | `frontend/index.html`（110 行）、`frontend/assets/css/app.css`（561 行）、`app/api/`、`app/ssh/`、`app/services/` |

**部分完成 / 未完成**：
| 项 | 缺口或原因 |
|---|---|
| 首份测试记录 | SPIKE 实测表已归档（`PHASE-02-SPIKE.md` §5.4）；端到端冒烟脚本 `.temp/smoke_client.py`（305 行、19 组断言）留在 `.temp/` 草稿区而非稳定产物——阶段 02 时 `tests/` 目录尚未建立 |
| 目录列表读取 | 在 WSL 测试床上通；真实 CentOS 目标机（R-01）未开机，未验证 |
| D-012 声明的配套脚本 `scripts/testbed_wsl.sh` | 阶段 02 时 `scripts/` 目录尚不存在；测试床重建步骤只在 `.temp/wsl_*.sh` 与 SPIKE 报告 §3 正文中 |
| 目标 CentOS 虚拟机的端到端验证 | R-01：虚拟机未开机、无免密开机途径（沿用 `PHASE-01-ENVIRONMENT.md` 结论） |

## 4. 技术实现
**修改的模块**：`git show --stat d2f94e0` = 13 个文件 / 1534 行 —— `.md` 503、`docs/reports/PHASE-02-SPIKE.md` 219、`docs/DECISIONS.md` 201、`docs/reports/PHASE-01-ENVIRONMENT.md` 181、`docs/PROJECT_STRUCTURE.md` 98、`README.md` 86、`docs/REQUIREMENTS.md` 84、`.gitignore` 53、`AGENTS.md` 46、`config/config.example.json` 29、`docs/reports/_index.md` 20、`docs/_index.md` 11、`config/.gitignore` 3。原型的可运行代码（`app/`、`frontend/`）不在该提交内。
**关键实现方案**：
1. **连接层 = 原生 SFTP v3（D-011）**：用 `ssh <opts> <user>@<host> -s sftp` 取得二进制协议通道，帧 = `uint32` 长度 + `byte` 类型 + 负载。两个高危错误点：响应包第一个字段是**请求 id**；`MKDIR`/`SETSTAT` 的属性字段是**完整 ATTRS**（正确写法 `struct.pack(">II", 4, 0o755)`，发错会让 `sftp-server` `fatal()` 退出、客户端只看到 `EOF poll=None`）。
2. **主机指纹采集绕开 `ssh-keyscan`（P-005 / R-04）**：临时 `UserKnownHostsFile` + `StrictHostKeyChecking=no` 连一次让 ssh 自己写入，再读出指纹交用户确认；确认前不得写入 `data/known_hosts`，也不得用于任何文件操作——与 T-005 禁止的「静默接受新密钥」有本质区别。
3. **测试床与默认值（D-012）**：WSL2 Ubuntu 上非 root `sshd`，`127.0.0.1:2222`，用 `dpkg -x` 解包 Ubuntu pool 的 `openssh-server_9.6p1-3ubuntu13.20_amd64.deb`，全程零提权；`config/config.example.json` 钉死 `server.host=127.0.0.1`、`server.port=8760`、`security.allow_lan=false`、`security.host_key_policy=strict`、`ssh.known_hosts_file=data/known_hosts`、`ssh.max_sessions=4`。
**与原设计的差异**：
| 原设计的设想 | 阶段 02 的实际 | 原因 |
|---|---|---|
| 目录列举走 `sftp` 批处理 + 解析 `ls -l`（D-004） | 原生 SFTP v3 协议（D-011） | CLI 把权限位遮蔽成 `-rw-******`、`nlink` 是 `?`，信息源已丢失 |
| 用 `ssh-keyscan` 采集主机密钥 | 临时 `known_hosts` + `StrictHostKeyChecking=no` 连一次读回（P-005） | Windows OpenSSH 9.5p2 没有 `ssh-keyscan`，且本机 `ssh -Q kex` 不含服务端首选 KEX |
| 集成测试目标 = CentOS 虚拟机 | WSL 非 root sshd 测试床（D-012） | CentOS 未开机，实测需要可复现环境 |
| 文本编码沿用系统默认 | Windows 下一切文本 I/O 显式钉 UTF-8（D-013） | 控制台 GBK 打印 emoji 文件名抛 `UnicodeEncodeError: 'gbk' codec can't encode character '\U0001f389'` 并终止程序 |

## 5. 测试结果
**测试环境**：宿主机 Windows 11 家庭版 26300 / PowerShell 5.1（不是 pwsh 7）/ Python 3.12.10（`E:\Software\Python 3.12\python.exe`，无 `python3`）/ OpenSSH_for_Windows 9.5p2（有 `ssh` `sftp` `scp` `ssh-keygen`，**无 `ssh-keyscan`**）。测试床：WSL2 Ubuntu 24.04.2 上非 root `sshd`，`127.0.0.1:2222`，用户 `aimu`，家目录 `/home/aimu`。
**执行命令**（阶段 02 期间实际运行的探针，不是测试套件）：
```powershell
python .temp\probe_binary_stdio.py   # SSH 管道二进制安全性
python .temp\probe_sftp_full.py      # SFTP v3 全项操作
python .temp\smoke_client.py         # 端到端冒烟（阶段 02/03 共用）
```
| 类别 | 数量 | 结果 |
|---|---|---|
| SPIKE 协议实测（`PHASE-02-SPIKE.md` §5.4） | 14 项 | 全部通过 |
| 端到端冒烟 `.temp/smoke_client.py` | 19 组断言 | 以 `PASS=n FAIL=m` 汇总、退出码区分成败（`.temp/smoke_client.py:303-305`）；逐项结果未归档 |
| 单元 / 集成测试 | 0 | **未建立**——`tests/` 目录在阶段 02 时不存在 |
| 规划文档 §7.1 验收矩阵 T-001..T-014 | 14 项 | **全部未执行**（`docs/REQUIREMENTS.md:68-71`） |
**如实声明**：阶段 02 结束时不存在正式测试套件，本阶段的「测试」是 SPIKE 实测表加一个落在 `.temp/` 的冒烟脚本。四层测试与静态校验是后续阶段的产物，最终口径以 `docs/TEST_REPORT.md` 为准。
**关键测试证据**：
- 二进制安全：`bytes(range(256)) * 4` 经 `ssh ... cat` 往返 1024 字节逐字节相同，无 CRLF 或编码转换（SPIKE §5.1）——这是「用子进程承载二进制协议」成立的前提。
- 协议能力：权限位未被遮蔽（返回 `0o100644` 而非 `******`）、58 MB 文件 `size=58435601`、符号链接 `0o120777`、`READDIR` 终点 `STATUS code=1`、`WRITE` 256000 字节后 `STAT` 校验一致（SPIKE §5.4）。
- 服务启动：`logs/awfm.log:1-2` 记录 2026-10-15 00:27:42 启动，并写明「监听 127.0.0.1:8760；主机密钥策略 strict」。
- 冒烟脚本覆盖首次连接报 `host_key_unknown` 且信任库为空、错误指纹被拒、确认后可连接、断开后 `session_not_found` 等 19 组（`.temp/smoke_client.py`）。

## 6. 问题与风险
**发现的问题**：
| 编号 | 问题 | 严重度 | 处置 |
|---|---|---|---|
| R-01 | 目标 CentOS 虚拟机未开机，无法做真实端到端验证 | 中 | 沿用阶段 01 结论，推迟到阶段 05 前请用户开机 |
| R-04 | Windows OpenSSH 9.5p2 没有 `ssh-keyscan`，且缺服务端首选 KEX | 中 | 已给替代方案 P-005，实现落在阶段 03 |
| R-05 | 在**目录**上设置 `icacls` 继承会让目录内文件不可读 | 低 | 已解决：`icacls <dir> /reset /T /C`；教训是私钥权限逐文件设置 |
| — | Windows 控制台 GBK 无法打印 emoji 文件名 | 中 | 已解决：D-013 全线显式 UTF-8 |
**复现步骤（R-04）**：
```powershell
ssh-keyscan -p 2222 -t ed25519 127.0.0.1
# 输出只有服务端 banner 与 choose_kex: unsupported KEX method sntrup761x25519-sha512@openssh.com
# 退出码 1，没有任何 host key 行；ssh -Q kex 的算法列表同样不含该 KEX
```
**尚存风险**：
1. 测试床是 WSL2 Ubuntu，**不等于**已验证 CentOS Stream 10；UID/GID 与真实目标机不同。
2. WSL2 的 `localhost` 转发只证明「本机回环可达」，不证明经 NAT 网段可达真实虚拟机。
3. 阶段 02 的最小原型**没有代码快照**（无提交、无归档），阶段 03 在同一批文件上继续扩展，「阶段 02 当时跑到什么程度」只能靠日志与冒烟脚本事后追溯；首份测试记录的载体又落在可整体清空的 `.temp/`，一旦清理就失去复现能力。

## 7. 文档与交付物
**新增或修改的文档**：`docs/reports/PHASE-02-SPIKE.md`（219 行，连接层路线验证）/ `docs/REQUIREMENTS.md`（84 行，编号化需求 + 验收矩阵 + 发布门槛）/ `docs/DECISIONS.md`（201 行，D-001..D-013，D-004 作废、D-011/D-012/D-013 为本阶段结论）/ `docs/PROJECT_STRUCTURE.md`（98 行）/ `docs/_index.md`（11 行）+ `docs/reports/_index.md`（20 行）/ `README.md`（86 行）+ `AGENTS.md`（46 行）+ `.gitignore`（53 行）。
**构建产物**：无。阶段 02 没有打包脚本也没有发行包（`scripts/` 与 `dist/` 中的内容属阶段 03/05）。
**依赖与运行要求**：运行时第三方依赖 = 0（N-02，后端只用 Python 3 标准库，见 `app/__init__.py:1-5`）；环境前提 = Python 3.12（实测 3.12.10）+ 系统 OpenSSH 客户端（实测 9.5p2），目标机需启用 SFTP 子系统；默认只监听 `127.0.0.1:8760`、`security.allow_lan=false`（N-03）；`frontend/` 内不得出现任何外部 URL（T-002）。

## 8. 阶段结论
**是否达到验收条件：基本达到，但范围收窄。** 规划文档 §6.1 阶段 02 的三项产物中，「SSH 连接验证」与「首份测试记录」已有可核实载体（SPIKE 实测表 + 冒烟脚本）；「可启动服务」与「本地页面」在工作区落地并留下启动日志，但未提交、未做阶段快照，测试也未按 `tests/` 归档。
**是否允许进入阶段 03：允许。** 与 `docs/reports/PHASE-02-SPIKE.md` 的结论一致；R-04 的替代方案已明确，不阻塞后续。
**后续任务：**
1. 阶段 03：把原型扩成核心功能（连接配置、目录导航、文件属性展示、错误处理、会话清理），产出 API 文档与单元测试。
2. 落地 D-012 声明的 `scripts/testbed_wsl.sh`，让测试床可重建（后续阶段已落地：`scripts/testbed_wsl.sh`，2026-10-15 01:13）。
3. 把冒烟脚本从 `.temp/` 移入 `tests/`，由四层测试承接。
4. 阶段 05 前请用户开机 CentOS 虚拟机（R-01）。