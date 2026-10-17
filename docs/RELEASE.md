# AWFM 发行说明（v0.1.3）

> v0.1.0 / v0.1.1 / v0.1.2 的发行记录见各自的阶段报告（`docs/reports/PHASE-*/`）；本文只描述当前版本。

> 本文对应规划文档 §11「发行方式」与发行验收清单（§11 八项）。**只写实际做到的事**，
> 做不到的写在 §9，不以「已支持」表述。

## 1. 发行概览

| 项目 | 内容 |
|---|---|
| 版本 | `0.1.3`（`app/__init__.py:7`） |
| 发行日期 | 2026-10-17 |
| 产物形态 | **开发版**（本仓库：源码 + 测试 + 配置模板 + 完整文档）与 **便携版**（`dist/AWFM-0.1.3-windows-x64.zip`；v0.1.0 / v0.1.1 / v0.1.2 的 zip 仍保留，未覆盖） |
| 启动入口 | **普通** `run.bat` / `run.sh`：不带参数即启动，服务就绪后自动用系统默认浏览器打开地址（v0.1.3 新增）；**高级** `run-advanced.bat` / `run-advanced.sh`：不带参数进交互菜单（启动 / 状态 / 停止 / 日志 / 自检）。四者只有一份实现 `scripts/launcher.py` |
| 包校验和 | `dist/SHA256SUMS.txt`（**不在包内**，原因见 §4）：zip 的 SHA-256 由 `Get-FileHash` 与 `certutil` 两种方式独立复核，两次结果一致 |
| 平台 | Windows x64（宿主机）；目标机要求 Linux 且启用 SFTP 子系统 |
| 许可 | MIT，见 `LICENSE` |
| 运行时依赖 | **0 个第三方 Python 包**；需要系统 `ssh`（OpenSSH 客户端） |
| 打包方式 | `python scripts/package.py`（打包前自动跑 `scripts/build.py` 的 8 项静态校验） |

## 2. 便携包内容

解压后的目录结构：

```
AWFM-<版本>-windows-x64/
├── run.bat              普通启动入口（双击即启动，就绪后自动开浏览器；自动找 py -3 / python，设置 UTF-8，再调 scripts/launcher.py）
├── run.sh               Linux / macOS 的普通启动入口（同一个启动器，只是外壳不同）
├── run-advanced.bat     高级启动入口（双击进交互菜单；带参数时与 run.bat 等价）
├── run-advanced.sh      Linux / macOS 的高级启动入口
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
`scripts/launcher.py`、`scripts/start.py`、`run.bat`、`run.sh`、`run-advanced.bat`、`run-advanced.sh`、
`README.md`、`LICENSE`、`VERSION`、`MANIFEST.json`。

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

打包脚本自己会做这些事：复制白名单文件（含 `run.bat`、`run.sh`、`run-advanced.bat`、`run-advanced.sh`、`scripts/launcher.py`；v0.1.2 阶段三起**不再生成** `start.cmd`/`stop.cmd`）→ 生成 `VERSION` 与 `MANIFEST.json`
→ 以**固定时间戳**（1980-01-01）压缩成 zip（所以同样的输入能产出同样的字节）→ 用 `testzip()` 校验 CRC
→ 逐个文件比对其 SHA-256 与清单一致 → 检查有无清单外的成员。

> **数字口径**：本节与下一节的数字来自 **v0.1.3 交付后的最终构建记录**（2026-10-17 15:18，构建主机 Python 3.12.10；同一交付内先后构建过多次，每次的数字与哈希差异见 `docs/CHANGELOG.md` 的 v0.1.3 段）。本节记录的是**产出这份 zip 的那次构建**；由于 `docs/` 本身也在包里，文档要记录包自身的字节数与哈希就无法与自身完全闭合——最新一次构建的哈希以**包外**的 `dist/SHA256SUMS.txt` 为准；
脚本引用（`run.bat` / `run.sh` / `run-advanced.bat` / `run-advanced.sh` / `scripts/launcher.py`）与仓库当前结构一致。

压缩包内共 **111 个文件**：清单 `MANIFEST.json` 的 `file_count` 是 **110**（清单不登记自身），加上 `MANIFEST.json` 自身正好 111；zip 成员数同为 111。包内没有 `data/`、`logs/`、`dist/`：它们是运行时目录，只在首次启动后由程序自己创建。
目录树合计 **1,740,808 字节**（约 1.66 MiB），zip 压缩后 **719,611 字节**（702.7 KB）。
所有成员名统一带一层 `AWFM-0.1.3-windows-x64/` 前缀——解压时不会把 `app/`、`frontend/`、`docs/` 散落到当前目录，目录结构与本文第 2 节的树完全一致。
（v0.1.2 的包是 104 个文件 / 1,519,434 字节 / zip 631,659 字节；v0.1.3 的增量来自新增的 `run-advanced.bat`、`run-advanced.sh`、`tests/unit/test_frontend_layout.py` 与界面/接口改动带来的源码增长——测试文件本身不进包，进包增长主要来自 `frontend/`、`app/` 与 `docs/`。第二次构建相对第一次多了 `docs/reports/PHASE-D-RELEASE-v013.md`（18 KB）与 `frontend/assets/css/app.css` 的对齐修复注释。）

## 4. 校验和

`dist/SHA256SUMS.txt`（**不在包内**）记录本次构建的：

- 便携包 `AWFM-0.1.3-windows-x64.zip` 的 SHA-256（本次构建：`ca235f4922b7f5afee3534d71962971b05cd60bb68d1eab2b4cd1ae031730641`；`Get-FileHash` 得 `CA235F49…30641`、`certutil` 得小写同值，双工具一致）；
- 清单 `MANIFEST.json` 的 SHA-256；
- 两种校验方式：`certutil -hashfile <文件> SHA256` 或 `Get-FileHash -Algorithm SHA256`。

包内 `MANIFEST.json` 另有**每个文件**的 SHA-256，可用于校验解压后的内容是否被改动。

```powershell
certutil -hashfile dist\AWFM-0.1.3-windows-x64.zip SHA256
```

> **为什么不把包自身的哈希写进包内文档**：`docs/` 是便携包的一部分，把哈希写进 `docs/RELEASE.md`
> 就会改变包内容 → 哈希立刻失效，永远对不上。因此包哈希只存在于 `dist/SHA256SUMS.txt` 与提交信息中；
> 包内只放**逐文件**哈希（`MANIFEST.json`），它是自洽的。同理，`VERSION` 里的构建时间会让每次重打包的
> 哈希都不同——这是刻意的，哈希的用途是「校验这一份拷贝」，不是「标识这一个版本」。

## 5. 安装与运行

**便携版**（目标机无需 Python 之外的任何安装）：

1. 解压 zip 到任意可写目录（路径**可以含空格**：v0.1.3 阶段 D 按含空格目录做过真实验收；仍建议避开中文路径）；
2. 双击 `run.bat` 即普通启动：查环境 → 起服务 → 等 `/api/health` 通过 → **就绪后**用系统默认浏览器打开地址 →
   打印地址、日志位置与停止方法，最后按一次回车关掉窗口（关窗口不影响后台服务）。
   Linux / macOS 把 `run.bat` 换成 `./run.sh`；
3. 想用交互菜单（启动 / 状态 / 停止 / 日志 / 自检）就双击 `run-advanced.bat`（Linux / macOS：`./run-advanced.sh`）；
   带参数时两个入口完全等价，例如 `run.bat status`、`run-advanced.bat start --port 32611`；
4. 浏览器访问 `http://127.0.0.1:32579/`（v0.1.2 起的默认端口；默认只监听回环地址）——普通启动成功时它已经自己打开了；
   自动打开失败（无图形环境、没有浏览器关联）只提示地址，**不算启动失败**，把地址复制到浏览器即可；
5. 停止：**同一个入口** `run.bat stop`（Linux / macOS：`./run.sh stop`）——只停 AWFM 自己的进程，未经确认不做强制终止。

**开发版**（本仓库）：

```powershell
run.bat                            # 普通启动（就绪后自动开浏览器）
run-advanced.bat                   # 高级入口：交互菜单
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

`VERSION`（包内）记录：版本号、构建时间、平台标签、构建主机 Python 版本、源仓库名称，
以及「本包为便携版、无需在线安装依赖」的说明。`MANIFEST.json` 记录生成时间与文件清单。
纯源码仓库的版本号唯一来源是 `app/__init__.py:7`（`0.1.3`），并由 `scripts/build.py` 第 7 项
校验它同时出现在 `README.md` 与 `docs/CHANGELOG.md` 中。

## 7. 系统要求

- 宿主机：Windows 10/11 x64；**Python 3.10+**（便携版不捆绑解释器，这是决策 D-015 的取舍）
- 系统 OpenSSH 客户端（`ssh`，含 SFTP 子系统支持）——Windows 10 1809+ 自带
- 目标机：Linux + `sshd` + SFTP 子系统；认证用密钥（推荐）或密码
- 不需要互联网，不需要管理员权限

## 8. 发行验收对照（规划文档 §11 的 8 项）

| # | 验收项 | 结论 | 证据 |
|---|---|---|---|
| 1 | 干净环境成功启动 | 通过 | v0.1.3 阶段 D 把 **v0.1.3 的 zip** 解压到独立目录（路径含空格：`.temp/pkg-test/AWFM 0.1.3 四次验收/`）后跑完整流程：`run.bat check` 退出码 0（8 项自检通过、1 项警告：信任库尚未建立）→ `run.bat start --port 8794 --no-browser` 退出码 0（版本 0.1.3，PID 9092）→ `GET /` 200（9371 字节）→ `GET /api/health` 200 `{"ok":true,"data":{"status":"ok","version":"0.1.3","connections":0}}`，响应头 `Server: AWFM/0.1.3` → `run.bat status` 退出码 0 → `run.bat stop --force --yes` 退出码 0，端口 8794 监听数归 0（报告 `docs/reports/PHASE-D-RELEASE-v013.md` §8）。v0.1.2 的旧证据见 `docs/reports/PHASE-07-RELEASE-v012.md` §十 |
| 2 | 界面不依赖外部 CDN 或在线字体 | 通过 | `scripts/build.py` 第 4 项 + `tests/security` 的 `OfflineFrontendTests`；端到端断言对外请求为空 |
| 3 | 正确连接指定虚拟机并浏览文件 | 通过 | v0.1.1 阶段六真实桌面 CU 用**真机 CentOS Stream 10**（`192.168.170.128`）验证连接、指纹确认、浏览、检索、编辑与哈希核对（`docs/reports/PHASE-06-CU-ACCEPTANCE.md`）；v0.1.0 时此项在 WSL 测试床上验证 |
| 4 | 主机密钥异常与认证失败处理正确 | 通过 | `tests/security/test_host_key.py`（未知/伪造/变化三种）；端到端第 2、3 条 |
| 5 | 配置/日志/临时文件位置明确 | 通过 | 本文 §5 的表；启动自检打印位置（`app/main.py:207`） |
| 6 | 无互联网条件下完成核心测试 | **降级通过** | 静态扫描零外部 URL、零第三方依赖、端到端对外请求为空；**未做系统级断网空载** |
| 7 | 用户手册与发行包版本一致 | 通过 | 包内 `docs/USER_GUIDE.md`（头部版本 v0.1.3）、`docs/SSH_SETUP_GUIDE.md`、`VERSION` 与 `app/__init__.py` 同源打包；界面右上徽标、启动横幅与 `run.bat status` 均显示 `0.1.3`（阶段 D 独立目录验收实测：`AWFM 已启动（版本 0.1.3）`、`GET /` 页面状态条同版本） |
| 8 | 版本号、构建记录和 SHA-256 校验和齐全 | 通过 | `VERSION`（0.1.3 / 2026-10-17T15:18:44 / windows-x64 / Python 3.12.10）、`MANIFEST.json`（110 项逐文件哈希）、`dist/SHA256SUMS.txt`；zip 的 SHA-256 `ca235f4922b7f5afee3534d71962971b05cd60bb68d1eab2b4cd1ae031730641` 用 `Get-FileHash` 与 `certutil` 独立复核一致 |

## 9. 已知限制与不适用场景

- **未做系统级断网验证**（第 6 项）：只做了静态扫描、零依赖与端到端「对外请求为空」的间接验证。（第 3 项已在 v0.1.1 阶段六与 v0.1.2 阶段六用真机 CentOS Stream 10 覆盖。）
- Windows 上后台服务收不到温和停止信号：`run.bat stop` 会先尝试优雅停止、被系统拒绝后再询问确认，非交互终端用 `--force --yes`；解压验收里走的正是这条路径（这是平台行为，不是缺陷）。
- `run.bat` 在 **GBK（936）控制台**下曾把中文行截断并打印假错误，v0.1.2 阶段六已修（文件开头的纯 ASCII 引导段），并补了 9 项静态单测与 1 项 `chcp 936` 集成用例。
- v0.1.2 的 7 项未在本机实测的 SSH 教程步骤（sudo/SELinux/firewalld/macOS 等）已逐条标注，见 `docs/SSH_SETUP_GUIDE.md` 附录 B 与 `docs/reports/PHASE-04-SSH-GUIDE-v012.md` §6.2。
- 只管理 **Linux** 目标机；覆盖上传中断会留下被截断的文件。v0.1.3 起写操作不再只有上传：还开放了新建、复制、
  移动、重命名、删除、压缩与解压，全部受「允许写操作」开关与服务端双重校验。
- **浏览器自动打开可能失败**：无图形环境（纯 SSH 会话、Windows Server Core、容器）或系统没有关联浏览器时，
  普通启动只打印地址并提示手动打开，退出码仍为 0——按设计「打不开浏览器」不等于「启动失败」。
- 复制大目录是逐文件流式搬运（`download_chunks` → `upload_stream`），没有并发；512 MiB / 10000 条目是硬上限。
- 批量操作（多选删除 / 压缩 / 解压 / 移动 / 复制）以整体遮罩呈现进度，没有逐文件进度条；中途失败会保留已完成的部分，
  并在错误里如实报告 `done` 与 `failed`。
- 复制/剪切的剪贴板只存在页面内存里，刷新页面或切换连接就丢失，不做持久化。
- 端到端（无头 Edge）覆盖 **39 条**用例，含连接浏览、主机指纹确认、密码失败提示、检索、在线编辑与文件操作、写权限热同步、侧边栏、发现、布局固定化，以及 v0.1.3 新增的七槽位操作区、预览框、新建文件、多选批量（`tests/e2e/test_browser_v013.py`）；其余场景仍依赖自动化测试。真实桌面 CU 在 v0.1.3 阶段 D 按任务书 §6.2 覆盖 **14 条**场景（证据 `.temp/cu-v013/`，报告 `docs/reports/PHASE-D-RELEASE-v013.md` §3）。
- 便携包**不含测试**；用户侧如需复现测试结论，请使用开发版（本仓库）并跑 `python scripts\test.py`。

## 10. 回滚与支持

- 回滚：保留上一份 zip 即可，程序不写系统状态；换回旧目录即完成回滚。
- 本项目无远程更新机制（规划文档明确「不做在线更新」），升级 = 解压新包 + 迁移 `data/config.json`。
- 问题排查顺序：`logs/awfm.log` → `python app\main.py --check` → `docs/USER_GUIDE.md` 的排障小节。
