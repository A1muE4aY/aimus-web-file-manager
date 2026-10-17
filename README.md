# Aimu's Web File Manager (AWFM)

> 本地部署的 SSH Web 文件管理工具 · 离线可用 · 零第三方依赖 · 开箱即用 · 过程透明

AWFM 运行在你的 Windows 宿主机上，通过 **系统 OpenSSH 客户端**连接 Linux 目标机（虚拟机或服务器），
把目标机的文件系统以浏览器界面呈现出来。服务端**只用 Python 3 标准库**，前端是**原生 HTML/CSS/JS**，
不联网、不装数据库、不装容器。

| | |
|---|---|
| 当前版本 | `v0.1.3`（在 v0.1.2 基础上完成五项需求：行内操作区独立容器与固定顺序、文件信息列独立布局、预览独立框、新建文件/文件夹与多选批量（含复制/剪切/粘贴）、启动脚本拆普通与高级且就绪后自动开浏览器） |
| 运行时依赖 | **0 个第三方 Python 包**（系统 OpenSSH 客户端视为环境前提） |
| 测试状态 | 单元 680 / 集成 147 / 安全 82 / 端到端 39，合计 **948 项全部通过**（0 失败 / 0 错误 / 1 跳过为 Windows 平台跳过；见 [docs/reports/PHASE-D-RELEASE-v013.md](docs/reports/PHASE-D-RELEASE-v013.md)） |
| 发行包 | `python scripts/package.py` → `dist/AWFM-0.1.3-windows-x64.zip`（见 [docs/RELEASE.md](docs/RELEASE.md)） |

---

## 功能摘要

| 分级 | 功能 | 状态 |
|---|---|---|
| P0 | 配置 SSH 主机/端口/用户名/认证方式（密钥文件、ssh-agent、密码） | 已实现 |
| P0 | 连接、断开、重连与连接状态展示 | 已实现 |
| P0 | 浏览远程目录、进入子目录、返回上级、刷新 | 已实现 |
| P0 | 显示文件名、类型、大小、权限、属主、修改时间 | 已实现 |
| P0 | 连接错误 / 权限错误 / 目录不存在的可理解提示 | 已实现 |
| P0 | 本地配置保存与读取（原子写入，损坏时报错而非静默重置） | 已实现 |
| P0 | 基础日志、健康检查、离线运行 | 已实现 |
| P1 | 文件与目录下载（流式，不整份读入内存） | 已实现（浏览器原生下载） |
| P1 | 文件上传（流式、有大小上限、覆盖二次确认、进度、取消） | 已实现 |
| P1 | 文本文件预览（编码探测 + 大小上限） | 已实现 |
| P1 | 文件名排序、路径导航与刷新 | 已实现 |
| P1 | 大文件下载进度与传输取消 | 部分实现：上传有进度与取消；下载由浏览器下载栏承载 |
| P1 | 多虚拟机配置管理 | 已实现 |
| P2 | 权限与属主展示 | 已实现（改用原生 SFTP v3 后信息不再丢失） |
| P1 | 远端文件检索（按文件名与内容、范围与深度可控、可中止） | 已实现（v0.1.1） |
| P1 | 文本文件在线编辑（编码探测、大小上限、保存冲突检测） | 已实现（v0.1.1） |
| P1 | 重命名 / 压缩成 `.tar.gz` / 解压 / 删除 | 已实现（v0.1.1） |
| P2 | 在线虚拟机发现（只读 VMware 状态，产出候选连接） | 已实现（v0.1.1，仅 VMware Workstation） |
| P1 | 新建空文件 / 新建空目录（排他创建，同名拒绝、绝不静默覆盖） | 已实现（v0.1.3） |
| P1 | 复制 / 剪切 / 粘贴（整棵目录树、冲突整批拒绝并二次确认、符号链接跳过并报告） | 已实现（v0.1.3） |
| P2 | 多选与批量操作（复制 / 剪切 / 删除 / 压缩 / 解压） | 已实现（v0.1.3） |
| P2 | 行内操作区独立容器、固定七槽位顺序与文件信息列独立布局 | 已实现（v0.1.3） |
| P2 | 预览独立框（框内滚动，长文本不撑破模态框） | 已实现（v0.1.3） |

功能分级与非功能门槛的完整定义见 [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md)。

## 快速开始

```powershell
# 1. 启动本地服务（默认只监听 127.0.0.1:32579，首次运行使用内置默认配置）
run.bat                     # 不带参数 = 交互菜单：启动 / 状态 / 停止 / 日志 / 自检
run.bat start               # 直接后台启动（Linux / macOS 用 ./run.sh start）

# 2. 浏览器打开
#    http://127.0.0.1:32579/

# 3. 其它常用命令（实现都在 scripts/launcher.py，Windows 与 Linux 行为一致）
run.bat status              # 运行状态、地址与进程号
run.bat stop                # 停止（只停 AWFM 自己的进程，未确认不强制终止）
run.bat logs                # 看服务日志

# 4.（可选）生成一份可手工编辑的配置文件 data/config.json
python app\main.py --init-config
```

便携版：解压发行包后双击 `run.bat`（Linux / macOS 用 `./run.sh`）即可启动，停止用同一个入口（见 [docs/RELEASE.md](docs/RELEASE.md)）。

> 服务**默认只绑定回环地址**。若要开放局域网访问，必须先理解风险并修改配置，
> 详见 [docs/SECURITY.md](docs/SECURITY.md)。

## 系统要求

- **宿主机**：Windows 10/11 x64，Python 3.10+（实测 3.12.10）
- **OpenSSH 客户端**：Windows 自带的 `ssh.exe` / `sftp.exe` / `ssh-keygen.exe`（实测 OpenSSH_for_Windows 9.5p2）
- **目标机**：Linux，启用 `sshd` 与 SFTP 子系统（集成测试实测环境为 Ubuntu 24.04.2 上的非 root `sshd`）
- **网络**：宿主机与目标机互通即可，**全程不需要互联网**

## 文档索引

| 文档 | 内容 |
|---|---|
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | 功能/非功能需求、优先级、验收条件 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系统架构、模块划分、数据流、设计取舍 |
| [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) | 目录用途、命名规范、文件归属 |
| [docs/API.md](docs/API.md) | HTTP API 定义、参数、响应、错误码（35 个端点） |
| [docs/SECURITY.md](docs/SECURITY.md) | 威胁模型、认证、密钥保护、路径校验、残余风险 |
| [docs/DECISIONS.md](docs/DECISIONS.md) | 技术选型、替代方案、决策理由（D-001 ~ D-021） |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | 开发环境、调试方法、代码规范 |
| [docs/TEST_PLAN.md](docs/TEST_PLAN.md) | 测试范围、分层、环境、用例设计原则、验收门槛 |
| [docs/TEST_REPORT.md](docs/TEST_REPORT.md) | **实际**测试执行记录、验收项结论与证据 |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | 版本变更记录 |
| [docs/RELEASE.md](docs/RELEASE.md) | 发行说明、构建步骤、发行包内容、校验和 |
| [docs/reports/](docs/reports/) | 阶段报告（v0.1.2 为 01~07；v0.1.3 见 `PHASE-A~D`）与最终开发报告 |
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | 面向使用者的操作说明 |
| [dev_guide/](dev_guide/) | 规划文档与接力任务书（用户提供，只读输入） |

## 开发与测试

```powershell
# 跑全部四层测试（unit / integration / security / e2e）+ 语法校验
python scripts\test.py

# 只跑不依赖测试床与浏览器的两层
python scripts\test.py --fast

# 构建前静态校验（8 项：版本一致性、零依赖、离线、凭据纪律等）
python scripts\build.py

# 打包便携版（默认先跑上面的 8 项校验）
python scripts\package.py
```

集成与端到端测试需要一台 Linux 目标机：仓库自带 WSL 测试床脚本
（`wsl -d Ubuntu bash scripts/testbed_wsl.sh up`，幂等、不需要 root）。
测试床、浏览器或 Edge 缺失时相关用例**跳过并在报告里显示跳过数**，不会被当成通过。

## 目录结构

```
aimus-web-file-manager/
├── app/         后端源码（Python 标准库，零第三方依赖）
├── frontend/    前端资源（原生 HTML/CSS/JS，离线，无构建步骤）
├── config/      配置模板
├── tests/       自动化测试（unit / integration / security / e2e）
├── scripts/     启动、测试、构建、打包脚本
├── docs/        项目文档与阶段报告（reports/）
├── data/        运行时配置与数据（不提交）
├── logs/        运行日志（不提交）
├── dist/        发行包产物（不提交）
├── LICENSE      MIT 许可证
└── README.md
```

## 安全要点（详见 [docs/SECURITY.md](docs/SECURITY.md)）

- 会话令牌 `X-AWFM-Token` 在进程启动时随机生成，除健康检查外所有 `/api/` 请求强制校验。
- `Host` 头只接受字面量回环地址（防 DNS 重绑定）；跨站来源与 CORS 预检一律拒绝。
- 主机密钥策略默认 `strict`：首次连接必须人工核对指纹；指纹变化时**不提供一键接受**。
- **私钥永远不进入浏览器**；密码不写配置文件、不进日志、不进命令行，只经一次性 `SSH_ASKPASS` 交给 `ssh`。
- 远程路径全部校验（必须绝对路径、拒绝控制字符、长度上限）；文件传输按 64 KiB 分块流式转发。
- 日志在格式化阶段统一脱敏（私钥块、`-i <私钥路径>`、`password=`/`token=`/`secret=`）。

## 已知限制

- 只管理 **Linux** 目标机（POSIX 路径语义）；Windows 目标机的路径方言只在设计上预留。
- HTTP 层开放的写操作有：**上传、在线编辑保存、重命名、压缩、解压、删除**；创建目录属 P2，已在连接层实现但未暴露。
- **覆盖上传中断会在目标路径留下被截断的文件**（SFTP v3 的 `RENAME` 不能替换已存在目标），
  这是本版明确接受的取舍；新建上传走「临时名 + 改名」，不会留下半成品。
- **自动化**的集成与端到端测试跑在 WSL 测试床上；**真实 CentOS Stream 10** 由各阶段的人工 CU 验收覆盖
  （v0.1.2 阶段一、二、三、六；见 [docs/reports/](docs/reports/) 的 v0.1.2 报告）。
- 未做系统级断网验证（只有静态扫描、零依赖与「端到端对外请求为空」的间接证据）。

## 许可证

本项目使用 MIT 许可证，见 [LICENSE](LICENSE)。
