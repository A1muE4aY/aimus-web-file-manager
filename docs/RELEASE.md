# AWFM 发行说明（v0.1.3）

> v0.1.0 / v0.1.1 / v0.1.2 的发行记录见各自的阶段报告（`docs/reports/PHASE-*/`）；本文只描述当前版本。

> 本文对应规划文档 §11「发行方式」与发行验收清单（§11 八项）。**只写实际做到的事**，
> 做不到的写在 §9，不以「已支持」表述。

> **发行布局修订（2026-10-17）**：v0.1.3 的便携包统一改为「zip 根目录固定 `AWFM/`」+
> 「文件名只带版本号」；不再生成 `-windows-x64` 平台后缀。版本号仍是 **0.1.3**，产品代码未变，
> 只改了打包布局、包名与相关文档。

## 1. 发行概览

| 项目 | 内容 |
|---|---|
| 版本 | `0.1.3`（`app/__init__.py:7`） |
| 发行日期 | 2026-10-17 |
| 产物形态 | **开发版**（本仓库：源码 + 测试 + 配置模板 + 完整文档）与 **便携版**（`dist/AWFM-0.1.3.zip`；解压后根目录固定 `AWFM/`。v0.1.0 / v0.1.1 / v0.1.2 的旧 zip 与 v0.1.3 修订前的 `AWFM-0.1.3-windows-x64.zip` 保留，未覆盖） |
| 启动入口 | **启动** `run.bat` / `run.sh`：不带参数即启动，服务就绪后自动用系统默认浏览器打开地址；**菜单** `run-advanced.bat` / `run-advanced.sh`：不带参数进交互菜单（启动 / 状态 / 停止 / 日志 / 自检）。四者只有一份实现 `scripts/launcher.py` |
| 包校验和 | `dist/SHA256SUMS.txt`（**不在包内**，原因见 §4）：zip 的 SHA-256，以及包内 `MANIFEST.json` 的 SHA-256 |
| 运行环境 | Python 3.10+（Windows / Linux / macOS；浏览器访问）；目标机要求 Linux 且启用 SFTP 子系统 |
| 许可 | MIT，见 `LICENSE` |
| 运行时依赖 | **0 个第三方 Python 包**；需要系统 `ssh`（OpenSSH 客户端） |
| 打包方式 | `python scripts/package.py`（打包前自动跑 `scripts/build.py` 的 8 项静态校验） |

## 2. 便携包内容

解压后的目录结构（**根目录固定为 `AWFM/`，不带版本号与平台标签**）：

```
AWFM/
├── run.bat              启动入口（双击即启动，就绪后自动开浏览器；自动找 py -3 / python，设置 UTF-8，再调 scripts/launcher.py）
├── run.sh               Linux / macOS 的启动入口（同一个启动器，只是外壳不同）
├── run-advanced.bat     菜单入口（双击进交互菜单；带参数时与 run.bat 等价）
├── run-advanced.sh      Linux / macOS 的菜单入口
├── VERSION              版本、构建时间、运行环境、构建主机 Python 版本、包根目录、源仓库说明
├── MANIFEST.json        包内**每个文件**的 SHA-256、大小、文件总数、包根目录
├── README.md            项目说明
├── LICENSE              MIT 许可证
├── app/                 后端（Python 标准库）
├── frontend/            前端静态资源（离线可用，无构建步骤）
├── scripts/launcher.py  统一启动器：启动 / 状态 / 停止 / 日志 / 自检
├── scripts/start.py     前台启动的兼容入口（等价 run.bat start --foreground）
├── config/config.example.json  配置模板
└── docs/                全部交付文档（含本文件）
```

`AWFM/` 不随版本变化：解压 v0.1.4 时仍然覆盖同一个 `AWFM/`，不会出现 `AWFM-0.1.3/`、
`AWFM-0.1.4/` 并排、旧文件与新版本混在一起。升级时保留 `AWFM/data/config.json`（以及可选的
`AWFM/logs/`）即可；运行时目录首次启动会自动创建。

必需文件由打包脚本逐个校验（缺任何一个就判定打包失败）：
`app/main.py`、`app/__init__.py`、`frontend/index.html`、`config/config.example.json`、
`scripts/launcher.py`、`scripts/start.py`、`run.bat`、`run.sh`、`run-advanced.bat`、
`run-advanced.sh`、`README.md`、`LICENSE`、`VERSION`、`MANIFEST.json`。

**包内不含**：`tests/`（属开发版）、`data/`、`logs/`（运行时生成）、`dist/`（包自身），
以及 `__pycache__`、`.pyc`、`.log` 等中间产物。

## 3. 构建与打包步骤

```powershell
# 1) 构建前静态校验（8 项；发行门禁，失败则退出码 1）
python scripts\build.py

# 2) 打包（默认先跑上面的校验，再暂存、压缩、生成清单、自检）
python scripts\package.py
# 可选：--out <目录>  --skip-checks
```

打包脚本自己会做这些事：

1. 把白名单文件复制到 `dist/AWFM/`（含四个启动外壳、`scripts/launcher.py`；不含 `tests/`、`data/`、`logs/`）；
2. 生成 `VERSION` 与 `MANIFEST.json`；
3. 以**固定时间戳**（1980-01-01）压缩成 `dist/AWFM-<version>.zip`，所有成员统一带 `AWFM/` 前缀；
4. 用 `testzip()` 校验 CRC，逐个文件比对 `MANIFEST.json` 的 SHA-256，并检查有无 `AWFM/` 之外的成员；
5. 写包外的 `dist/SHA256SUMS.txt`。

> **暂存目录保护**：如果 `dist/AWFM/` 里存在 `data/` 或 `logs/`（说明有人直接从这个暂存目录运行过），
> 打包脚本会拒绝覆盖并提示先停止服务、移走运行数据，避免误删配置和日志。

> **数字口径**：zip 的文件数与字节数会随文档改动而变，本文**不写死**包自身的哈希与字节数，
> 以免「改文档 → 包哈希失效」的自指。需要核对时看包外的 `dist/SHA256SUMS.txt` 与包内
> `MANIFEST.json`；两者由同一次 `python scripts/package.py` 生成。

## 4. 校验和

`dist/SHA256SUMS.txt`（**不在包内**）记录本次构建的：

- 便携包 `AWFM-0.1.3.zip` 的 SHA-256；
- 包内 `AWFM/MANIFEST.json` 的 SHA-256；
- 跨平台校验方式：Windows 用 `Get-FileHash` / `certutil`，Linux / macOS 用 `sha256sum`。

```powershell
# Windows（两种工具应得到同一个值）
Get-FileHash -Algorithm SHA256 dist\AWFM-0.1.3.zip
certutil -hashfile dist\AWFM-0.1.3.zip SHA256
```

```bash
# Linux / macOS
sha256sum dist/AWFM-0.1.3.zip
```

包内 `MANIFEST.json` 另有**每个文件**的 SHA-256，可用于校验解压后的内容是否被改动。

> **为什么不把包自身的哈希写进包内文档**：`docs/` 是便携包的一部分，把哈希写进 `docs/RELEASE.md`
> 就会改变包内容 → 哈希立刻失效，永远对不上。因此包哈希只存在于 `dist/SHA256SUMS.txt` 与
> 提交信息 / GitHub Release 说明中；包内只放**逐文件**哈希（`MANIFEST.json`），它是自洽的。
> 同理，`VERSION` 里的构建时间会让每次重打包的哈希都不同——这是刻意的，哈希的用途是
> 「校验这一份拷贝」，不是「标识这一个版本」。

## 5. 安装与运行

**便携版**（宿主机无需 Python 之外的任何安装）：

1. 解压 zip，得到 `AWFM/` 目录（可以放在任意可写目录；路径**可以含空格**，仍建议避开中文路径）；
2. 双击 `run.bat` 即启动：查环境 → 起服务 → 等 `/api/health` 通过 → **就绪后**用系统默认浏览器打开地址 →
   打印地址、日志位置与停止方法，然后**停在窗口里**：按 Ctrl+C 停止服务，直接关窗口则服务继续在后台跑。
   Linux / macOS 把 `run.bat` 换成 `./run.sh`；
3. 想用交互菜单（启动 / 状态 / 停止 / 日志 / 自检）就双击 `run-advanced.bat`（Linux / macOS：`./run-advanced.sh`）；
   带参数时两个入口完全等价，例如 `run.bat status`、`run-advanced.bat start --port 32611`；
4. 浏览器访问 `http://127.0.0.1:32579/`（默认只监听回环地址）——启动成功时它已经自己打开了；
   自动打开失败（无图形环境、没有浏览器关联）只提示地址，**不算启动失败**；
5. 停止：**同一个入口** `run.bat stop`（Linux / macOS：`./run.sh stop`）——只停 AWFM 自己的进程，未经确认不做强制终止。

**从旧包升级**：用新 zip 解压覆盖 `AWFM/`，保留 `AWFM/data/config.json`（如已生成）与
`AWFM/logs/`；旧版 `AWFM-0.1.3-windows-x64/` 之类的目录可以直接删除，程序不依赖它们。

**开发版**（本仓库）：

```powershell
run.bat                            # 启动（就绪后自动开浏览器）
run-advanced.bat                   # 菜单入口：交互菜单
run.bat start                      # 后台启动；前台运行用 run.bat start --foreground
run.bat start --no-browser         # 启动了但不要自动开浏览器（唯一关闭开关）
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

`VERSION`（包内）记录：版本号、构建时间、运行环境（Python 3.10+；Windows / Linux / macOS）、
包根目录 `AWFM/`、构建主机 Python 版本、源仓库名称，以及「本包为便携版、无需在线安装依赖」的说明。
`MANIFEST.json` 记录生成时间、运行环境、`package_root` 与逐文件清单。纯源码仓库的版本号唯一来源是
`app/__init__.py:7`（`0.1.3`），并由 `scripts/build.py` 第 7 项校验它同时出现在 `README.md` 与
`docs/CHANGELOG.md` 中。

## 7. 系统要求

- 宿主机：Windows / Linux / macOS；**Python 3.10+**（便携版不捆绑解释器，这是决策 D-015 的取舍）。
  Windows 11 + Python 3.12.10 与 WSL2 Ubuntu 24.04 已实测；macOS 走同一条启动器分支，未在本机实测。
- 系统 OpenSSH 客户端（`ssh`，含 SFTP 子系统支持）——Windows 10 1809+ 自带，Linux / macOS 通常预装。
- 目标机：Linux + `sshd` + SFTP 子系统；认证用密钥（推荐）或密码。
- 不需要互联网，不需要管理员权限。

## 8. 发行验收对照（规划文档 §11 的 8 项）

| # | 验收项 | 结论 | 证据 |
|---|---|---|---|
| 1 | 干净环境成功启动 | 通过 | v0.1.3 阶段 D 把当时的 zip 解压到独立目录（路径含空格：`.temp/pkg-test/AWFM 0.1.3 六次验收/`）后跑完整流程：`run.bat check` 退出码 0 → `run.bat start --port 8796 --no-browser` 退出码 0 → `GET /` 200 → `GET /api/health` 200 `{"ok":true,"data":{"status":"ok","version":"0.1.3","connections":0}}` → `run.bat status` 退出码 0 → `run.bat stop --force --yes` 退出码 0，端口监听数归 0（`docs/reports/PHASE-D-RELEASE-v013.md` §8）。**发行布局修订后按同一流程重跑，见 §8.1** |
| 2 | 界面不依赖外部 CDN 或在线字体 | 通过 | `scripts/build.py` 第 4 项 + `tests/security` 的 `OfflineFrontendTests`；端到端断言对外请求为空 |
| 3 | 正确连接指定虚拟机并浏览文件 | 通过 | v0.1.1 阶段六真实桌面 CU 用**真机 CentOS Stream 10**（`192.168.170.128`）验证连接、指纹确认、浏览、检索、编辑与哈希核对（`docs/reports/PHASE-06-CU-ACCEPTANCE.md`） |
| 4 | 主机密钥异常与认证失败处理正确 | 通过 | `tests/security/test_host_key.py`（未知/伪造/变化三种）；端到端第 2、3 条 |
| 5 | 配置/日志/临时文件位置明确 | 通过 | 本文 §5 的表；启动自检打印位置（`app/main.py:207`） |
| 6 | 无互联网条件下完成核心测试 | **降级通过** | 静态扫描零外部 URL、零第三方依赖、端到端对外请求为空；**未做系统级断网空载** |
| 7 | 用户手册与发行包版本一致 | 通过 | 包内 `docs/USER_GUIDE.md`（头部版本 v0.1.3）、`docs/SSH_SETUP_GUIDE.md`、`VERSION` 与 `app/__init__.py` 同源打包；界面右上徽标、启动横幅与 `run.bat status` 均显示 `0.1.3` |
| 8 | 版本号、构建记录和 SHA-256 校验和齐全 | 通过 | `VERSION`（0.1.3 / 构建时间 / 运行环境 Python 3.10+ / 包根目录 `AWFM/` / Python 3.12.10）、`MANIFEST.json`（逐文件哈希 + `package_root`）、`dist/SHA256SUMS.txt`；zip 的 SHA-256 在包外登记，避免包内文档自指 |

### 8.1 发行布局修订后的复验（2026-10-17）

- **解压布局**：把 `dist/AWFM-0.1.3.zip` 解压到含空格的独立目录
  `.temp/pkg-test/AWFM 0.1.3 布局修订/`，顶层**只有 `AWFM/`**（没有带版本号的目录），
  `run.bat` / `run.sh` / `run-advanced.bat` / `run-advanced.sh` / `app/` / `docs/` / `VERSION` /
  `MANIFEST.json` 齐全。
- **自检**：在解压目录运行 `run.bat check`，退出码 0；启动前 6 项检查通过，应用自检 8 项通过、
  1 项警告（主机密钥信任库尚未建立，首次确认指纹后才创建）。
- **启动与访问**：`run.bat start --port 8798 --no-browser` 退出码 0，报告 `AWFM 0.1.3 已启动`；
  `GET /api/health` 返回 200 `{"ok": true, "data": {"status": "ok", "version": "0.1.3", "connections": 0}}`；
  `GET /` 返回 200（9371 字节）。
- **`status` / `stop` 未能在本次执行环境复验（环境限制，不是回归）**：本次执行环境的沙箱里
  `tasklist /FI "PID eq <pid>"` 返回 `ERROR: Access denied`，启动器据此把仍然活着的进程判为
  「已退出」，于是 `status` 退出码 3、`stop` 只清理陈旧 PID 文件。**启动器代码本轮未改**
  （`scripts/package.py` 与文档是唯一改动），停止流程的既有真实桌面证据见
  `docs/reports/PHASE-D-RELEASE-v013.md` §8；测试进程由执行器直接终止，端口 8798 已释放。

## 9. 已知限制与不适用场景

- **未做系统级断网验证**（第 6 项）：只做了静态扫描、零依赖与端到端「对外请求为空」的间接验证。
- Windows 上后台服务收不到温和停止信号：`run.bat stop` 会先尝试优雅停止、被系统拒绝后再询问确认，
  非交互终端用 `--force --yes`。这是平台行为，不是缺陷。
- `run.bat` 在 **GBK（936）控制台**下曾把中文行截断并打印假错误，v0.1.2 阶段六已修（文件开头的
  纯 ASCII 引导段），并补了 9 项静态单测与 1 项 `chcp 936` 集成用例。
- 只管理 **Linux** 目标机；Windows 目标机的路径方言只在设计上预留。覆盖上传中断会留下被截断的文件。
- **浏览器自动打开可能失败**：无图形环境（纯 SSH 会话、Windows Server Core、容器）或系统没有关联
  浏览器时，启动脚本只打印地址并提示手动打开，退出码仍为 0——按设计「打不开浏览器」不等于「启动失败」。
- 复制大目录是逐文件流式搬运（`download_chunks` → `upload_stream`），没有并发；512 MiB / 10000 条目是硬上限。
- 批量操作（多选删除 / 压缩 / 解压 / 移动 / 复制）以整体遮罩呈现进度，没有逐文件进度条；中途失败会保留
  已完成的部分，并在错误里如实报告 `done` 与 `failed`。
- 复制/剪切的剪贴板只存在页面内存里，刷新页面或切换连接就丢失，不做持久化。
- 便携包**不含测试**；用户侧如需复现测试结论，请使用开发版（本仓库）并跑 `python scripts\test.py`。
- **同一父目录不能并排解压两个版本**：包根目录固定为 `AWFM/`，这是「升级覆盖」的设计目标；
  需要同时保留两个版本时，把它们解压到不同父目录。
- 旧包名 `AWFM-0.1.3-windows-x64/` 不再生成；已解压的旧目录可删除，不参与升级。

## 10. 回滚与支持

- 回滚：保留上一份 zip 即可，程序不写系统状态；把旧 zip 解压覆盖 `AWFM/`（保留 `data/config.json`）即完成回滚。
- 本项目无远程更新机制（规划文档明确「不做在线更新」），升级 = 解压新包 + 迁移 `data/config.json`。
- 问题排查顺序：`logs/awfm.log` → `python app\main.py --check` → `docs/USER_GUIDE.md` 的排障小节。
