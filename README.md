# Aimu's Web File Manager (AWFM)

> 本地部署的 SSH Web 文件管理工具 · 离线可用 · 轻依赖 · 开箱即用 · 过程透明

AWFM 运行在你的 Windows 宿主机上，通过 **系统 OpenSSH 客户端**连接 VMware 虚拟机，
把目标虚拟机的文件系统以浏览器界面呈现出来。服务端**只用 Python 3 标准库**，
前端是**原生 HTML/CSS/JS**，不联网、不装数据库、不装容器。

当前版本：`v0.1.0`（阶段 02 最小原型开发中）

---

## 功能摘要

| 分级 | 功能 | 状态 |
|---|---|---|
| P0 | SSH 主机/端口/用户名/认证方式配置 | 计划中 |
| P0 | 连接、断开、重连与连接状态展示 | 计划中 |
| P0 | 浏览远程目录、进入子目录、返回上级 | 计划中 |
| P0 | 显示文件名、类型、大小、修改时间 | 计划中 |
| P0 | 连接错误 / 权限错误 / 目录不存在提示 | 计划中 |
| P0 | 本地配置保存与读取 | 计划中 |
| P0 | 基础日志、健康检查、离线运行 | 计划中 |
| P1 | 文件下载 / 上传、文本预览、排序、进度与取消 | 计划中 |

功能分级的完整定义见 [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md)。

## 快速开始

```powershell
# 1. 生成一份本地配置（首次运行会自动创建 data/config.json）
python app\main.py --init-config

# 2. 启动本地服务（默认只监听 127.0.0.1:8760）
python scripts\start.py

# 3. 浏览器打开
#    http://127.0.0.1:8760/
```

> 服务**默认只绑定回环地址**。若要开放局域网访问，必须先启用身份验证，
> 详见 [docs/SECURITY.md](docs/SECURITY.md)。

## 系统要求

- **宿主机**：Windows 10/11 x64，Python 3.10+（实测 3.12.10）
- **OpenSSH 客户端**：Windows 自带 `ssh.exe` / `sftp.exe`（实测 OpenSSH_for_Windows 9.5p2）
- **目标虚拟机**：Linux，启用 `sshd` 与 SFTP 子系统（实测 CentOS Stream 10）
- **网络**：宿主机与目标机互通即可，**全程不需要互联网**

## 文档索引

| 文档 | 内容 |
|---|---|
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | 功能/非功能需求、优先级、验收条件 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系统架构、模块划分、数据流、设计取舍 |
| [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) | 目录用途、命名规范、文件归属 |
| [docs/API.md](docs/API.md) | HTTP API 定义、参数、响应、错误码 |
| [docs/SECURITY.md](docs/SECURITY.md) | 威胁模型、认证、密钥保护、路径校验 |
| [docs/DECISIONS.md](docs/DECISIONS.md) | 技术选型、替代方案、决策理由 |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | 开发环境、调试方法、代码规范 |
| [docs/TEST_PLAN.md](docs/TEST_PLAN.md) | 测试范围、环境、用例、验收门槛 |
| [docs/TEST_REPORT.md](docs/TEST_REPORT.md) | **实际**测试执行记录与证据 |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | 版本变更记录 |
| [docs/RELEASE.md](docs/RELEASE.md) | 构建步骤、发行包内容、校验和 |
| [docs/reports/](docs/reports/) | 阶段报告与故障分析 |
| [.md](.md) | 原始规划文档（用户提供，只读输入） |

## 目录结构

```
aimus-web-file-manager/
├── app/         后端源码（Python 标准库）
├── frontend/    前端资源（原生 HTML/CSS/JS，离线）
├── config/      配置模板
├── tests/       自动化测试
├── scripts/     开发/启动/打包脚本
├── docs/        项目文档
├── data/        运行时配置与数据（不提交）
├── logs/        运行日志（不提交）
└── dist/        发行包产物（不提交）
```

## 许可证

见 [LICENSE](LICENSE)。
