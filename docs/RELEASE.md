# AWFM 发行说明（v0.1.0）

> 本文对应规划文档 §11「发行方式」与发行验收清单（§11 八项）。**只写实际做到的事**，
> 做不到的写在 §9，不以「已支持」表述。

## 1. 发行概览

| 项目 | 内容 |
|---|---|
| 版本 | `0.1.0`（`app/__init__.py`） |
| 发行日期 | 2026-10-15 |
| 产物形态 | **开发版**（本仓库：源码 + 测试 + 配置模板 + 完整文档）与 **便携版**（`dist/AWFM-0.1.0-windows-x64.zip`） |
| 平台 | Windows x64（宿主机）；目标机要求 Linux 且启用 SFTP 子系统 |
| 许可 | MIT，见 `LICENSE` |
| 运行时依赖 | **0 个第三方 Python 包**；需要系统 `ssh`（OpenSSH 客户端） |
| 打包方式 | `python scripts/package.py`（打包前自动跑 `scripts/build.py` 的 8 项静态校验） |

## 2. 便携包内容

解压后的目录结构：

```
AWFM-0.1.0-windows-x64/
├── start.cmd            启动（自动找 py -3 / python，设置 UTF-8，再调 scripts/start.py）
├── stop.cmd             停止（参数为端口，默认 8760；先确认 PID 是 python 进程再终止）
├── VERSION              版本、构建时间、平台、构建主机 Python 版本、源仓库说明
├── MANIFEST.json        包内**每个文件**的 SHA-256、大小与文件总数
├── README.md            项目说明
├── LICENSE              MIT 许可证
├── app/                 后端（Python 标准库）
├── frontend/            前端静态资源（离线可用，无构建步骤）
├── scripts/start.py     启动入口（薄包装）
├── config/config.example.json  配置模板
└── docs/                全部交付文档（含本文件）
```

必需文件由打包脚本逐个校验（缺任何一个就判定打包失败）：
`app/main.py`、`app/__init__.py`、`frontend/index.html`、`config/config.example.json`、
`scripts/start.py`、`README.md`、`LICENSE`、`VERSION`、`MANIFEST.json`、`start.cmd`、`stop.cmd`。

**包内不含**：`tests/`（属开发版）、`data/`、`logs/`（运行时生成）、`dist/`（包自身），
以及 `__pycache__`、`.pyc`、`.log` 等中间产物。

## 3. 构建与打包步骤

```powershell
# 1) 构建前静态校验（8 项；发行门禁，失败则退出码 1）
python scripts\build.py

# 2) 打包（默认先跑上面的校验，再暂存、压缩、生成清单、自检）
python scripts\package.py
# 可选：--out <目录>  --platform <平台标签>  --skip-checks
```

打包脚本自己会做这些事：复制白名单文件 → 生成 `VERSION` 与 `MANIFEST.json` → 写 `start.cmd`/`stop.cmd`（CRLF）
→ 以**固定时间戳**（1980-01-01）压缩成 zip（所以同样的输入能产出同样的字节）→ 用 `testzip()` 校验 CRC
→ 逐个文件比对其 SHA-256 与清单一致 → 检查有无清单外的成员。

压缩包内共 **82 个文件**：清单 `MANIFEST.json` 的 `file_count` 是 **81**（清单不登记自身），加上 `MANIFEST.json` 自身正好 82；zip 成员数同为 82。
所有成员名统一带一层 `AWFM-0.1.0-windows-x64/` 前缀——解压时不会把 `app/`、`frontend/`、`docs/` 散落到当前目录，目录结构与本文第 2 节的树完全一致。

## 4. 校验和

`dist/SHA256SUMS.txt`（**不在包内**）记录本次构建的：

- 便携包 `AWFM-0.1.0-windows-x64.zip` 的 SHA-256；
- 清单 `MANIFEST.json` 的 SHA-256；
- 两种校验方式：`certutil -hashfile <文件> SHA256` 或 `Get-FileHash -Algorithm SHA256`。

包内 `MANIFEST.json` 另有**每个文件**的 SHA-256，可用于校验解压后的内容是否被改动。

```powershell
certutil -hashfile dist\AWFM-0.1.0-windows-x64.zip SHA256
```

> **为什么不把包自身的哈希写进包内文档**：`docs/` 是便携包的一部分，把哈希写进 `docs/RELEASE.md`
> 就会改变包内容 → 哈希立刻失效，永远对不上。因此包哈希只存在于 `dist/SHA256SUMS.txt` 与提交信息中；
> 包内只放**逐文件**哈希（`MANIFEST.json`），它是自洽的。同理，`VERSION` 里的构建时间会让每次重打包的
> 哈希都不同——这是刻意的，哈希的用途是「校验这一份拷贝」，不是「标识这一个版本」。

## 5. 安装与运行

**便携版**（目标机无需 Python 之外的任何安装）：

1. 解压 zip 到任意可写目录（建议路径不含中文与空格，避免个别工具的编码问题）；
2. 双击 `start.cmd`，或命令行 `start.cmd --port 8760 --no-browser`；
3. 浏览器访问 `http://127.0.0.1:8760/`（默认只监听回环地址）；
4. 停止：`stop.cmd`（默认端口 8760；`stop.cmd 8899` 可指定端口）。

**开发版**（本仓库）：

```powershell
python scripts\start.py            # 启动
python app\main.py --init-config    # 生成可编辑的 data/config.json
python scripts\test.py              # 四层测试
```

**运行时目录**（首次运行自动创建，位置由配置路径推导，启动自检会打印）：

| 目录 | 内容 |
|---|---|
| `data/` | 真实配置 `config.json`、项目自有的 `known_hosts`。默认配置不落盘（决策 D-006） |
| `logs/` | `awfm.log`（单文件上限 2 MiB，自动轮转，日志脱敏已开启） |

便携版是**绿色**的：不改注册表、不写系统目录、不装服务；删除目录即卸载。

## 6. 版本与构建记录

`VERSION`（包内）记录：版本号、构建时间、平台标签、构建主机 Python 版本、源仓库名称，
以及「本包为便携版、无需在线安装依赖」的说明。`MANIFEST.json` 记录生成时间与文件清单。
纯源码仓库的版本号唯一来源是 `app/__init__.py:7`（`0.1.0`），并由 `scripts/build.py` 第 7 项
校验它同时出现在 `README.md` 与 `docs/CHANGELOG.md` 中。

## 7. 系统要求

- 宿主机：Windows 10/11 x64；**Python 3.10+**（便携版不捆绑解释器，这是决策 D-015 的取舍）
- 系统 OpenSSH 客户端（`ssh`，含 SFTP 子系统支持）——Windows 10 1809+ 自带
- 目标机：Linux + `sshd` + SFTP 子系统；认证用密钥（推荐）或密码
- 不需要互联网，不需要管理员权限

## 8. 发行验收对照（规划文档 §11 的 8 项）

| # | 验收项 | 结论 | 证据 |
|---|---|---|---|
| 1 | 干净环境成功启动 | 通过 | 解压到临时目录后 `start.cmd --port 8899` → `/api/health` 200；`docs/TEST_REPORT.md` §3.3 |
| 2 | 界面不依赖外部 CDN 或在线字体 | 通过 | `scripts/build.py` 第 4 项 + `tests/security` 的 `OfflineFrontendTests`；端到端断言对外请求为空 |
| 3 | 正确连接指定虚拟机并浏览文件 | **降级通过** | 连接与浏览在 WSL Ubuntu 24.04.2 测试床上端到端验证；**规划文档指定的 CentOS 虚拟机未验证** |
| 4 | 主机密钥异常与认证失败处理正确 | 通过 | `tests/security/test_host_key.py`（未知/伪造/变化三种）；端到端第 2、3 条 |
| 5 | 配置/日志/临时文件位置明确 | 通过 | 本文 §5 的表；启动自检打印位置（`app/main.py:207`） |
| 6 | 无互联网条件下完成核心测试 | **降级通过** | 静态扫描零外部 URL、零第三方依赖、端到端对外请求为空；**未做系统级断网空载** |
| 7 | 用户手册与发行包版本一致 | 通过 | 包内 `docs/USER_GUIDE.md` 与 `VERSION`/`app/__init__.py` 同源打包 |
| 8 | 版本号、构建记录和 SHA-256 校验和齐全 | 通过 | `VERSION`、`MANIFEST.json`、`dist/SHA256SUMS.txt` |

## 9. 已知限制与不适用场景

- **未在真实 CentOS 虚拟机上验证**（第 3 项）；**未做系统级断网验证**（第 6 项）。
- 只管理 **Linux** 目标机；只开放**上传**这一种写操作；覆盖上传中断会留下被截断的文件。
- 端到端只覆盖 3 条主路径（连接浏览、主机指纹确认、密码失败提示）。
- 便携包**不含测试**；用户侧如需复现测试结论，请使用开发版（本仓库）并跑 `python scripts\test.py`。

## 10. 回滚与支持

- 回滚：保留上一份 zip 即可，程序不写系统状态；换回旧目录即完成回滚。
- 本项目无远程更新机制（规划文档明确「不做在线更新」），升级 = 解压新包 + 迁移 `data/config.json`。
- 问题排查顺序：`logs/awfm.log` → `python app\main.py --check` → `docs/USER_GUIDE.md` 的排障小节。
