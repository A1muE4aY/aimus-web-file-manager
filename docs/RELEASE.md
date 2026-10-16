# AWFM 发行说明（v0.1.2）

> 本文对应规划文档 §11「发行方式」与发行验收清单（§11 八项）。**只写实际做到的事**，
> 做不到的写在 §9，不以「已支持」表述。

## 1. 发行概览

| 项目 | 内容 |
|---|---|
| 版本 | `0.1.2`（`app/__init__.py:7`） |
| 发行日期 | 2026-10-17 |
| 产物形态 | **开发版**（本仓库：源码 + 测试 + 配置模板 + 完整文档）与 **便携版**（`dist/AWFM-0.1.2-windows-x64.zip`；v0.1.0 与 v0.1.1 的 zip 仍保留，未覆盖） |
| 包校验和 | `dist/SHA256SUMS.txt`（**不在包内**，原因见 §4）：zip 的 SHA-256 由 `Get-FileHash` 与 `certutil` 两种方式独立复核，两次结果一致 |
| 平台 | Windows x64（宿主机）；目标机要求 Linux 且启用 SFTP 子系统 |
| 许可 | MIT，见 `LICENSE` |
| 运行时依赖 | **0 个第三方 Python 包**；需要系统 `ssh`（OpenSSH 客户端） |
| 打包方式 | `python scripts/package.py`（打包前自动跑 `scripts/build.py` 的 8 项静态校验） |

## 2. 便携包内容

解压后的目录结构：

```
AWFM-<版本>-windows-x64/
├── run.bat              统一入口（双击进交互菜单；自动找 py -3 / python，设置 UTF-8，再调 scripts/launcher.py）
├── run.sh               Linux / macOS 的统一入口（同一个启动器，只是外壳不同）
├── VERSION              版本、构建时间、平台、构建主机 Python 版本、源仓库说明
├── MANIFEST.json        包内**每个文件**的 SHA-256、大小与文件总数
├── README.md            项目说明
├── LICENSE              MIT 许可证
├── app/                 后端（Python 标准库）
├── frontend/            前端静态资源（离线可用，无构建步骤）
├── scripts/launcher.py  统一启动器：启动 / 状态 / 停止 / 日志 / 自检（v0.1.2 阶段三新增）
├── scripts/start.py     前台启动的兼容入口（等价 run.bat start --foreground）
├── config/config.example.json  配置模板
└── docs/                全部交付文档（含本文件）
```

必需文件由打包脚本逐个校验（缺任何一个就判定打包失败）：
`app/main.py`、`app/__init__.py`、`frontend/index.html`、`config/config.example.json`、
`scripts/launcher.py`、`scripts/start.py`、`run.bat`、`run.sh`、`README.md`、`LICENSE`、`VERSION`、`MANIFEST.json`。

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

打包脚本自己会做这些事：复制白名单文件（含 `run.bat`、`run.sh`、`scripts/launcher.py`；v0.1.2 阶段三起**不再生成** `start.cmd`/`stop.cmd`）→ 生成 `VERSION` 与 `MANIFEST.json`
→ 以**固定时间戳**（1980-01-01）压缩成 zip（所以同样的输入能产出同样的字节）→ 用 `testzip()` 校验 CRC
→ 逐个文件比对其 SHA-256 与清单一致 → 检查有无清单外的成员。

> **数字口径**：本节与下一节的数字来自 **v0.1.2 阶段七的构建记录**（2026-10-17，构建主机 Python 3.12.10）；
脚本引用（`run.bat` / `run.sh` / `scripts/launcher.py`）与仓库当前结构一致。

压缩包内共 **104 个文件**：清单 `MANIFEST.json` 的 `file_count` 是 **103**（清单不登记自身），加上 `MANIFEST.json` 自身正好 104；zip 成员数同为 104。
目录树合计 **1,519,434 字节**（约 1.45 MiB），zip 压缩后 **631,659 字节**（616.9 KB）。
所有成员名统一带一层 `AWFM-0.1.2-windows-x64/` 前缀——解压时不会把 `app/`、`frontend/`、`docs/` 散落到当前目录，目录结构与本文第 2 节的树完全一致。
（v0.1.1 的包是 95 个文件 / 588.8 KB；增量来自 v0.1.2 新增的 `scripts/launcher.py`、`run.bat`、`run.sh`、`docs/SSH_SETUP_GUIDE.md` 与七份阶段报告。）

## 4. 校验和

`dist/SHA256SUMS.txt`（**不在包内**）记录本次构建的：

- 便携包 `AWFM-0.1.2-windows-x64.zip` 的 SHA-256；
- 清单 `MANIFEST.json` 的 SHA-256；
- 两种校验方式：`certutil -hashfile <文件> SHA256` 或 `Get-FileHash -Algorithm SHA256`。

包内 `MANIFEST.json` 另有**每个文件**的 SHA-256，可用于校验解压后的内容是否被改动。

```powershell
certutil -hashfile dist\AWFM-0.1.2-windows-x64.zip SHA256
```

> **为什么不把包自身的哈希写进包内文档**：`docs/` 是便携包的一部分，把哈希写进 `docs/RELEASE.md`
> 就会改变包内容 → 哈希立刻失效，永远对不上。因此包哈希只存在于 `dist/SHA256SUMS.txt` 与提交信息中；
> 包内只放**逐文件**哈希（`MANIFEST.json`），它是自洽的。同理，`VERSION` 里的构建时间会让每次重打包的
> 哈希都不同——这是刻意的，哈希的用途是「校验这一份拷贝」，不是「标识这一个版本」。

## 5. 安装与运行

**便携版**（目标机无需 Python 之外的任何安装）：

1. 解压 zip 到任意可写目录（路径**可以含空格**：v0.1.2 阶段三按含空格目录做过真实验收；仍建议避开中文路径）；
2. 双击 `run.bat` 进交互菜单（启动 / 状态 / 停止 / 日志 / 自检），或直接命令行 `run.bat start`；
   Linux / macOS 把 `run.bat` 换成 `./run.sh`；
3. 浏览器访问 `http://127.0.0.1:32579/`（v0.1.2 起的默认端口；默认只监听回环地址）；
4. 停止：**同一个入口** `run.bat stop`（Linux / macOS：`./run.sh stop`）——只停 AWFM 自己的进程，未经确认不做强制终止。

**开发版**（本仓库）：

```powershell
run.bat                            # 统一入口（交互菜单）
run.bat start                      # 后台启动；前台运行用 run.bat start --foreground
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
纯源码仓库的版本号唯一来源是 `app/__init__.py:7`（`0.1.2`），并由 `scripts/build.py` 第 7 项
校验它同时出现在 `README.md` 与 `docs/CHANGELOG.md` 中。

## 7. 系统要求

- 宿主机：Windows 10/11 x64；**Python 3.10+**（便携版不捆绑解释器，这是决策 D-015 的取舍）
- 系统 OpenSSH 客户端（`ssh`，含 SFTP 子系统支持）——Windows 10 1809+ 自带
- 目标机：Linux + `sshd` + SFTP 子系统；认证用密钥（推荐）或密码
- 不需要互联网，不需要管理员权限

## 8. 发行验收对照（规划文档 §11 的 8 项）

| # | 验收项 | 结论 | 证据 |
|---|---|---|---|
| 1 | 干净环境成功启动 | 通过 | v0.1.2 阶段七把 **v0.1.2 的 zip** 解压到独立目录（路径含空格：`.temp/pkg-run-012/AWFM test dir/`）后跑完整流程：`run.bat check` 退出码 0（9 项自检通过、1 项警告：信任库尚未建立）→ `run.bat start --no-browser --port 32611` 退出码 0（版本 0.1.2）→ `GET /` 200（7399 字节，标题正确，页面内外网 URL 数 0）→ `GET /api/health` 200 `{"status":"ok","version":"0.1.2"}` → `run.bat status` 退出码 0 → `run.bat stop --force --yes` 退出码 0，端口 32611 监听数归 0、PID 文件已删（证据 `.temp/pkg-run-012/evidence.txt`，报告 `docs/reports/PHASE-07-RELEASE-v012.md` §十）。v0.1.2 阶段三另有含空格目录的真实验收（`docs/reports/PHASE-03-LAUNCHER-v012.md` §5），v0.1.0/v0.1.1 的旧证据见 `docs/TEST_REPORT.md` §3.3（当时的 `start.cmd` 已在阶段三从发行包移除） |
| 2 | 界面不依赖外部 CDN 或在线字体 | 通过 | `scripts/build.py` 第 4 项 + `tests/security` 的 `OfflineFrontendTests`；端到端断言对外请求为空 |
| 3 | 正确连接指定虚拟机并浏览文件 | 通过 | v0.1.1 阶段六真实桌面 CU 用**真机 CentOS Stream 10**（`192.168.170.128`）验证连接、指纹确认、浏览、检索、编辑与哈希核对（`docs/reports/PHASE-06-CU-ACCEPTANCE.md`）；v0.1.0 时此项在 WSL 测试床上验证 |
| 4 | 主机密钥异常与认证失败处理正确 | 通过 | `tests/security/test_host_key.py`（未知/伪造/变化三种）；端到端第 2、3 条 |
| 5 | 配置/日志/临时文件位置明确 | 通过 | 本文 §5 的表；启动自检打印位置（`app/main.py:207`） |
| 6 | 无互联网条件下完成核心测试 | **降级通过** | 静态扫描零外部 URL、零第三方依赖、端到端对外请求为空；**未做系统级断网空载** |
| 7 | 用户手册与发行包版本一致 | 通过 | 包内 `docs/USER_GUIDE.md`（头部版本 v0.1.2）、`docs/SSH_SETUP_GUIDE.md`（适用版本 v0.1.2）、`VERSION` 与 `app/__init__.py` 同源打包；界面徽标与启动横幅显示 `0.1.2`（阶段七解压验收的 `GET /` 与 `run.bat status` 实测） |
| 8 | 版本号、构建记录和 SHA-256 校验和齐全 | 通过 | `VERSION`（0.1.2 / 2026-10-17T05:21:39 / windows-x64 / Python 3.12.10）、`MANIFEST.json`（103 项逐文件哈希）、`dist/SHA256SUMS.txt`；zip 的 SHA-256 用 `Get-FileHash` 与 `certutil` 独立复核一致（报告 §十） |

## 9. 已知限制与不适用场景

- **未做系统级断网验证**（第 6 项）：只做了静态扫描、零依赖与端到端「对外请求为空」的间接验证。（第 3 项已在 v0.1.1 阶段六与 v0.1.2 阶段六用真机 CentOS Stream 10 覆盖。）
- Windows 上后台服务收不到温和停止信号：`run.bat stop` 会先尝试优雅停止、被系统拒绝后再询问确认，非交互终端用 `--force --yes`；解压验收里走的正是这条路径（这是平台行为，不是缺陷）。
- `run.bat` 在 **GBK（936）控制台**下曾把中文行截断并打印假错误，v0.1.2 阶段六已修（文件开头的纯 ASCII 引导段），并补了 9 项静态单测与 1 项 `chcp 936` 集成用例。
- v0.1.2 的 7 项未在本机实测的 SSH 教程步骤（sudo/SELinux/firewalld/macOS 等）已逐条标注，见 `docs/SSH_SETUP_GUIDE.md` 附录 B 与 `docs/reports/PHASE-04-SSH-GUIDE-v012.md` §6.2。
- 只管理 **Linux** 目标机；只开放**上传**这一种写操作；覆盖上传中断会留下被截断的文件。
- 端到端（无头 Edge）覆盖 **32 条**用例，含连接浏览、主机指纹确认、密码失败提示、检索、在线编辑与文件操作、写权限热同步、侧边栏、发现、布局固定化与回归修复；其余场景仍依赖自动化测试。真实桌面 CU 在 v0.1.2 阶段六按任务书 §6 覆盖 **12 条**场景（证据 `.temp/cu-v012-stage6/`）。
- 便携包**不含测试**；用户侧如需复现测试结论，请使用开发版（本仓库）并跑 `python scripts\test.py`。

## 10. 回滚与支持

- 回滚：保留上一份 zip 即可，程序不写系统状态；换回旧目录即完成回滚。
- 本项目无远程更新机制（规划文档明确「不做在线更新」），升级 = 解压新包 + 迁移 `data/config.json`。
- 问题排查顺序：`logs/awfm.log` → `python app\main.py --check` → `docs/USER_GUIDE.md` 的排障小节。
