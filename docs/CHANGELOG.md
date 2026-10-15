# 变更记录（CHANGELOG）

## 关于本文件与记录约定

- **格式**：沿用 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 的分组习惯，固定使用
  「新增 / 变更 / 修复 / 安全 / 已知限制」五组。版本号遵循语义化版本。
- **记录口径**：条目必须落在**可核实的事实**上——能指到源码就写 `路径:行号`，能指到提交就写短哈希。
  无法核实的内容（性能数字、长时间稳定性结论、未留档的修复）**不写**，宁可留空。
- **凭据纪律**：本文件**不记录任何凭据**。不写密码、不写私钥内容、不写私钥文件路径、不写测试床账号信息
  （依据 `AGENTS.md` §3.4 与规划文档 §10）。
- **阶段透明**：规划文档 §6.1/§6.2 要求每个阶段的目标、实际改动、测试证据与未解决问题都可复查，
  因此本文按阶段列出**可核实的产物**，并把未完成的部分如实写进「已知限制」。
- **版本标识**：`v0.1.0` 是首个版本。六个阶段已全部完成，**已产出便携发行包与 SHA-256 校验和**
  （`dist/SHA256SUMS.txt`，说明见 `docs/RELEASE.md`），但**尚未打 git 标签**、未对外发布。
  打标签后需在此补上标签名与包哈希。
  `v0.1.1` 正在开发中（阶段一~三已完成，见下节），**尚未打包、尚未打标签**。
- **日期**：ISO `YYYY-MM-DD`。
- **维护方式**：**人工维护**，不自动生成。变更发生时同步写，而不是发版前一次性补记。

## [v0.1.1] — 开发中（未发布）

- **版本号**：仍是 `0.1.0`（`app/__init__.py:7`）。阶段六交付时统一改为 `0.1.1` 并重新打包，本轮不提前改号。
- **状态**：阶段一（修复已有缺陷）、阶段二（优化侧边栏）、阶段三（远端文件检索）已落地并通过测试；阶段四~六**未开始**。
- **起始日期**：2026-10-16。
- **依据**：工作区根目录的任务书 `2.md`（用户提供的第二轮验收要求）。
- **提交纪律**：阶段一~三的改动共用 `app/api/handlers.py`、`app/core/errors.py` 与前端若干文件，无法拆成互不依赖的提交，因此**合并为一次提交**（提交信息里逐阶段列明）；阶段四起每阶段单独提交。
- **行号漂移**：v0.1.1 在 `app/api/handlers.py` 里插入了三个检索处理器，本文 v0.1.0 段引用的 `app/api/handlers.py:259-279`（`ENDPOINTS`）与 `:282`（`build_router()`）**已失效**，当前分别是 `:294-317` 与 `:320`。历史条目按当时源码保留，不复改。

### 阶段进度（依据任务书 2.md 的六阶段）

| 阶段 | 名称 | 状态 | 可核实的产物 |
| --- | --- | --- | --- |
| 一 | 修复已有缺陷 | 已完成 | 写权限热同步、陈旧列表标记与重试入口、新建连接不再打回占位页；测试 `tests/unit/test_permission_sync.py`、`tests/integration/test_write_permission_sync.py`、`tests/security/test_write_permission_paths.py`、`tests/e2e/test_browser_regressions.py` |
| 二 | 优化侧边栏 | 已完成 | `frontend/assets/css/app.css`、`frontend/assets/js/connections.js`；测试 `tests/e2e/test_browser_sidebar.py` |
| 三 | 添加远端文件检索 | 已完成 | `app/services/search.py`、`app/api/handlers.py:161`（三个检索端点）、`frontend/assets/js/search.js`、`frontend/index.html:80`/`:88`；测试 unit 36 项 / integration 15 项 / security 18 项 / e2e 4 项；接口文档 `docs/API.md` §5.20–5.22；手册第 8 章；阶段报告 `docs/reports/PHASE-03-SEARCH.md` |
| 四 | 远端文本编辑与文件操作 | 未开始 | — |
| 五 | 自动发现在线虚拟机 | 未开始 | — |
| 六 | 回归、CU 验收与交付 | 未开始 | — |

### 新增

- **远端文件检索**（阶段三）：3 个新端点，编号第 20~22（路由表 `app/api/handlers.py:294-317`）——`POST /api/connections/{id}/search`（202 + 快照）、`GET /api/searches/{search_id}`、`DELETE /api/searches/{search_id}`（幂等中止）。
  - 服务层 `app/services/search.py`：后台线程 `awfm-search-<id>` 逐目录列举，**只走既有 SFTP 通道，不在远端执行任何命令**；`scope` 固定 `subtree`；按名称 `casefold` 包含匹配；排序「目录 → 符号链接 → 文件」；结果行带 `parent` 与 `depth`。
  - 四道预算（`SearchLimits`）：`max_results=500`、`max_dirs=2000`、`max_entries=100000`、`time_budget_seconds=45.0`；任一触发即 `truncated=true` 并写入中文 `truncated_reason`；读不到的目录只计入 `skipped_dirs`/`skipped`（明细上限 20 条），连续 10 个目录失败才整体失败；符号链接只报告不跟随（目录环与越界链接都不会被走进去）；同一连接同时只允许一个检索（`search_busy`）。
  - 错误模型新增 `SearchBusy`（`code=search_busy`，HTTP 409，`app/core/errors.py:193`）。
  - 前端：`frontend/assets/js/search.js`（发起 / 700 ms 轮询 / 中止 / 清空 / 结果表 / 区分「没有匹配」与「搜索失败」），搜索栏 `frontend/index.html:80`，结果面板 `frontend/index.html:88`；`frontend/assets/js/files.js` 的 `locate(parent, name)` 跳到所在目录、选中并高亮（`tests/e2e/test_browser_search.py` 断言 `.is-located`）。结果表列出名称 / 类型 / 所在目录 / 大小 / 修改时间。

### 变更

- 活动会话不再持有建连时的 `Connection` 快照，改为持有可热更新的引用，写权限开关改了立刻生效（阶段一缺陷①）。
- 侧边栏加宽并重排卡片（名称 / 用户名+主机+端口 / 认证方式 / 远端家目录 / 状态），长名称与长路径换行且不重叠（阶段二）。
- `docs/API.md` 扩到 22 个端点并新增 §5.20–5.22；`docs/USER_GUIDE.md` 新增第 8 章「文件检索」，原第 8~12 章顺延为 9~13 章。
- `tests/e2e/artifacts/*.png` 加入 `.gitignore`：截图按随机 `RUN_TAG` 每次运行生成，不逐张入库（v0.1.0 已入库的 6 张保留）。
- 仓库清理：v0.1.0 某脚本按字面量创建的 `%SystemDrive%` 目录（内含 `ProgramData/Microsoft/Windows/Caches/*.db`，0.94 MB）移入 `.archive/junk/percent-systemdrive-2026-10-16/`。

### 修复

- **缺陷①写权限状态不同步**：界面打开「允许写操作」后立刻上传仍被拒，必须断开重连。修复后写操作每次都以当前配置为准（`tests/security/test_write_permission_paths.py` 反向验证：撤权后旧会话引用写不进去，远端不落一个字节，连 `<名字>.awfm-part-*` 都不出现）。
- **缺陷②远端目录刷新后的陈旧列表**：目录被删后点「刷新」，页面报错却把上一次的列表留在屏幕上。修复后旧列表被明确标注「已过期」并给出重试入口（`tests/e2e/test_browser_regressions.py`）。
- **缺陷③新建连接后的文件区状态**：已有活动连接时新建连接会把文件区打回占位页。修复后新建不影响正在浏览的连接（同上）。
- 阶段三实现中修掉的界面缺陷：清空检索后结果表仍留着隐藏的旧行（`frontend/assets/js/search.js` 的 `render()` 先清空再判 `idle`）；空闲态与搜索后的范围文案不一致（「范围：当前目录及其子目录」→「范围：<root> 及其子目录」）。
- 参数形状检查前移：`start_search`（`app/api/handlers.py:161`）先校验 `path`/`query` 再找会话，避免「没连接」时把 400 变成 409（`tests/security/test_search_paths.py` 的 `test_malformed_body_is_rejected_without_a_live_session` 钉住）。

### 安全

- 检索的路径与关键词校验与浏览同源（`app/utils/paths.py` 的 `validate_remote_path`）：非绝对路径、含 NUL、超过 4096 字节一律 400；`..` 交给服务端 `realpath` 解析后再判定，不做调用方折叠；`query` 上限 128 字符，除制表符外的控制字符拒绝（`tests/security/test_search_paths.py`）。
- 检索不为任何请求在远端执行 shell 命令：断言检索前后命令行含 `-p 2222` 的 `ssh.exe` 进程数不变（验收项 T-013），并断言检索不改动远端目录（`tests/security/test_search_paths.py` 的 `SearchCommandDisciplineTests`）。
- 写权限门禁的对抗性验证：绕过界面直接打服务层写入口，撤权后依旧全部被拒（`tests/security/test_write_permission_paths.py`）。

### 已知限制

- 阶段四~六未开始：**没有**在线文本编辑，也没有删除 / 重命名 / 新建目录 / 压缩 / 解压入口（`ENDPOINTS` 里仍然只有上传与覆盖）。
- 检索上限是常量，暂不可配置；不跟随符号链接、不搜文件内容、不支持通配符与正则。
- 版本号仍是 `0.1.0`，便携发行包与校验和仍是 v0.1.0 的那一份，未重新构建。
- 阶段六要求的真实桌面 CU 验收**尚未执行**：阶段一~三的证据来自单元 / 集成 / 安全 / 无头 Edge e2e 测试，都不等同于 CU 验收。

---

## [v0.1.0] — 开发中（未发布）

- **版本号**：`0.1.0`（`app/__init__.py:7`），经 `Server` 响应头与 `GET /api/health`、`GET /api/session` 暴露。
- **状态**：功能、测试与文档均已落地，并已构建便携发行包；**未打标签、未对外发布**。
- **起始日期**：2026-10-15。
- **可核实的提交基线**：仓库目前**只有一个提交** `d2f94e0`（2026-10-15，「阶段01+02前置：环境调查、需求编号化、决策记录、连接层 SPIKE」，13 个文件 / 1534 行新增）。
  阶段 03~06 的源码、测试与文档**已随阶段 06 的收尾提交一次性入库**（提交短哈希见本文「待补记」）。
  在此之前它们只是未提交的工作区状态，因此本文对这一段产物的核实依据曾是工作区内容。

### 阶段进度（依据规划文档 §6.1 的六阶段）

| 阶段 | 名称 | 状态 | 可核实的产物 |
|---|---|---|---|
| 01 | 需求分析与环境调查 | 已完成 | `docs/REQUIREMENTS.md`、`docs/PROJECT_STRUCTURE.md`、`docs/DECISIONS.md`、`docs/reports/PHASE-01-ENVIRONMENT.md`（提交 `d2f94e0`） |
| 02 | 最小原型 / 连接层 SPIKE | 已完成 | `docs/reports/PHASE-02-SPIKE.md`（提交 `d2f94e0`）；决策 D-011 / D-012 / D-013 |
| 03 | 核心功能实现 | 已完成 | `app/` 全部模块、`frontend/`（11 个 JS 模块）、`tests/unit`、`tests/integration`、`docs/ARCHITECTURE.md`、`docs/API.md`、`docs/DEVELOPMENT.md`、`docs/USER_GUIDE.md`；报告 `docs/reports/PHASE-03-CORE.md` |
| 04 | 安全与传输 | 已完成 | `app/api/security.py`、`app/api/tickets.py`、`app/ssh/known_hosts.py`、`app/utils/redact.py`、`docs/SECURITY.md`；决策 D-014；报告 `docs/reports/PHASE-04-SECURITY-TRANSFER.md` |
| 05 | 离线部署与兼容性验证 | 已完成（一条限制） | `tests/security` 38 项、`tests/e2e` 3 项（真实 Edge + 手写 CDP）、`scripts/testbed_wsl.sh`；报告 `docs/reports/PHASE-05-OFFLINE-DEPLOY.md`。真实 CentOS 目标机未验证（见「已知限制」） |
| 06 | 文档验收与正式发布 | 已完成 | `scripts/` 五个脚本、`LICENSE`（MIT）、`docs/TEST_PLAN.md`、`docs/TEST_REPORT.md`、`docs/RELEASE.md`、`docs/reports/` 阶段报告与 `FINAL_REPORT.md`、便携包 `dist/AWFM-0.1.0-windows-x64.zip` + `SHA256SUMS.txt` |

### 新增

**后端（Python 3 标准库，零第三方运行时依赖 —— 决策 D-002）**

- 进程入口与配置：`app/main.py`（命令行解析、`--init-config`、`--check`、日志初始化、优雅停机）、
  `app/core/config.py`（默认值 / 校验 / 原子保存，`CONFIG_VERSION = 1`）、`app/core/errors.py`（错误码与 HTTP 状态映射）。
- HTTP 边界 `app/api/`（8 个模块）：`http_server.py`（`ThreadingHTTPServer`、HTTP/1.1、`Server: AWFM/0.1.0` 且不泄漏 Python 版本）、
  `router.py`（正则路由）、`request.py`（请求解析与限长）、`responses.py`（统一 JSON 响应信封，UTF-8）、
  `handlers.py`、`security.py`、`tickets.py`、`__init__.py`。
- **19 个 HTTP API 端点**，全部挂在 `/api/` 下（路由表 `app/api/handlers.py:259-279` 的 `ENDPOINTS`，构建于 `app/api/handlers.py:282` `build_router()`）：
  - **服务级 2 个**：`GET /api/health`、`GET /api/session`；
  - **连接级 10 个**：`GET|POST /api/connections`、`GET|PATCH|DELETE /api/connections/{id}`、
    `POST …/connect`、`POST …/disconnect`、`GET …/status`、`GET …/host-keys`、`POST …/host-keys/trust`；
  - **会话级 7 个**：`GET …/files`、`GET …/stat`、`GET …/preview`、`POST …/download-ticket`、
    `GET …/download`、`POST …/upload`、`GET …/upload-check`。

  逐条的参数、响应与错误码见 `docs/API.md` §4/§5（该文档的 5.1–5.19 与路由表一一对应）。
- 服务层：`app/services/connection_manager.py`（连接增删改查 + 会话表 + id 生成）、
  `session.py`（连接状态机、主机密钥两阶段确认）、`filesystem.py`（目录列举、条目元数据、预览、写权限开关）、
  `transfer.py`（上传 / 下载的预检与流式语义）。
- 连接层（自实现 SFTP v3 —— 决策 D-011）：`app/ssh/sftp_protocol.py`（`struct` 手写编解码）、
  `sftp_transport.py`（请求-响应配对、超时、诊断）、`sftp_client.py`（高层文件系统操作）、
  `ssh_launcher.py`（ssh 命令行构造）、`known_hosts.py`（指纹采集与信任库）、`askpass.py`（密码认证辅助程序）。
- 数据模型与工具：`app/models/connection.py`、`app/models/entry.py`；
  `app/utils/atomic.py`（临时文件 + `os.replace` 原子写）、`app/utils/paths.py`、`app/utils/redact.py`、`app/utils/logging_setup.py`。
- 前端（原生 HTML/CSS/JS，无框架、无构建、无 CDN —— 决策 D-005）：`frontend/index.html`、
  `frontend/assets/css/app.css`、`frontend/assets/icons/favicon.svg`，以及 **11 个 ES 模块**
  `frontend/assets/js/{util,toast,modal,api,state,icons,connections,files,preview,transfer,app}.js`。
- 配置模板：`config/config.example.json`、`config/.gitignore`。
- 文档：`docs/ARCHITECTURE.md`、`docs/API.md`、`docs/SECURITY.md`、`docs/DEVELOPMENT.md`、`docs/USER_GUIDE.md`。
- 测试：
  - `tests/unit/` 17 个测试模块：阶段 03 收尾时为 **301 项**，阶段 05/06 加固后又补了 3 项，**现为 304 项**（四层合计 363 项的口径见 `docs/TEST_REPORT.md`）；
  - `tests/integration/` 3 个测试模块（`test_connection_flow`、`test_api_flow`、`test_password_auth`），**18 项全部通过**。

  复现命令（在项目根执行）：
  ```powershell
  python -m unittest discover -s tests/unit -t .
  python -m unittest discover -s tests/integration -t .
  ```

**决策记录（`docs/DECISIONS.md`）**

| 编号 | 决策 | 提交 |
|---|---|---|
| D-011 | 连接层改用**原生 SFTP v3 协议**（`ssh -s sftp`），不再解析 `sftp` CLI 文本输出 | `d2f94e0` |
| D-012 | 集成测试用 **WSL 非 root sshd 测试床**（`127.0.0.1:2222`），零提权、可脚本化重建 | `d2f94e0` |
| D-013 | Windows 上一切文本 I/O **显式钉 UTF-8** | `d2f94e0` |
| D-014 | **密码从不持久化**（配置文件里没有密码字段） | 工作区 |

**阶段 05/06 新增：测试、脚本、发行物**

- **安全测试套件 `tests/security/`（5 个模块 / 38 项）**：
  `test_web_security.py`（18 个端点无令牌一律 401；`Host` 头白名单；`Sec-Fetch-Site` 与 `Origin` 校验；
  `OPTIONS` 一律 403 且永不返回 `Access-Control-*`；静态资源穿越清单；响应头策略；`frontend/` 离线扫描）、
  `test_credentials.py`（哨兵密码不进落盘配置、不进 8 个 GET 端点响应、不进 `argv`、不进日志；
  `AskpassBundle` 的秘密文件内容与 `env`；销毁后文件与包装脚本都消失）、
  `test_path_traversal.py`（相对路径 400、`..` 交服务端 REALPATH、百分号只解一次、NUL/超长路径 400、
  上传名不含路径分隔符、下载票据换路径 401）、
  `test_host_key.py`（首次连接 409 且不写信任库；伪造指纹被拒且文件不变；信任库被换 → `host_key_mismatch`）、
  `support.py`（临时目录 + 临时 `known_hosts` + 真实 HTTP 服务，**不需要测试床**）。
- **端到端测试 `tests/e2e/`（3 项，真实 Edge + 标准库手写 CDP）**：`support.py` 实现 WebSocket 客户端、
  `Runtime.evaluate` 轮询、`Network.requestWillBeSent` 事件收集与 `Page.captureScreenshot`；
  用例覆盖「连接 → 浏览 → 上传/下载夹具 → 面包屑/条目数/回上级」「首次连接的主机指纹确认真流程」
  「密码提示 → 连接失败 → 密码不落盘」。**不引入 Selenium/Playwright**（N-02 要求运行时依赖数为 0）。
- **开发脚本 `scripts/`（动词开头）**：`start.py`（薄包装，退出码与 `app/main.py` 一致）、
  `test.py`（四层批量运行 + 语法校验 + 汇总表，单独提示跳过数）、
  `build.py`（8 项静态校验，发行门禁）、`package.py`（便携版打包、清单校验与自检）、
  `testbed_wsl.sh`（WSL 非 root `sshd` 测试床，幂等、不使用 `sudo`）。
- **发行物**：`LICENSE`（MIT）、`dist/AWFM-0.1.0-windows-x64.zip` + `dist/SHA256SUMS.txt` + 包内 `VERSION`、`MANIFEST.json`、`start.cmd`、`stop.cmd`。
- **文档**：`docs/TEST_PLAN.md`、`docs/TEST_REPORT.md`、`docs/RELEASE.md`、
  `docs/reports/PHASE-02-PROTOTYPE.md`、`PHASE-03-CORE.md`、`PHASE-04-SECURITY-TRANSFER.md`、
  `PHASE-05-OFFLINE-DEPLOY.md`、`PHASE-06-RELEASE.md`、`FINAL_REPORT.md`。
- **决策**：D-015（便携版打包口径）、D-016（`scripts/build.py` 8 项作为发行门禁）、D-017（许可证 MIT）。

### 变更

- **目录列举的路线：原设计走 `sftp -b -` 批处理 + 解析 `ls -l` 文本 —— 变更，由 D-011 取代**（`docs/DECISIONS.md:45-80`）。原计划是 `sftp -b -` 批处理 + 解析 `ls -l` 文本；
  阶段 02 的 SPIKE 用实测输出推翻了它：权限位被客户端遮蔽成 `-rw-******`、nlink 字段是 `?`、
  日期依赖人类可读格式且有两套分支（半年内 `%b %e %H:%M`、超过半年 `%b %e  %Y`）、
  每条命令会以 `sftp> <命令>` 回显混入 stdout、批处理**遇错即中止**、名字含 ` -> ` 时 symlink 行不可解析。
  这些代价来自「用文本界面承载结构化数据」这一路线选择本身，改用原生协议后**五项一次性消除**。
- **连接层的数据来源从「客户端格式化的文本」改为「二进制协议帧」**：权限位 `0o100644` / `0o120777` 原样保留，
  `uid`/`gid`、字节大小、`atime`/`mtime` 均为 epoch 整数；失败返回数值 `STATUS` 码
  （`2`=No such file、`3`=Permission denied、`4`=Failure、`8`=OP_UNSUPPORTED）而不是英文错误串；
  文件名含空格、中文、emoji、` -> ` 均原样往返。直接结果是 **P1 的「权限与属主展示」从「信息已丢失、无法实现」变为可实现**。
- **不再需要 `TZ=UTC` / `LC_ALL=C` 环境变量补丁**，也不再需要为两套日期格式写容错解析（原 D-004 的代价）。
- 上传采用「**临时名 + 改名**」：先写 `<名字>.awfm-part-<随机>`，成功后 `RENAME` 到目标名（`app/services/transfer.py:9-18`）。
- Windows 文本 I/O 全面显式 UTF-8：`sys.stdout`/`sys.stderr` 调 `reconfigure(encoding="utf-8")`，
  日志文件、JSON 读写、`subprocess` 文本管道均显式传 `encoding="utf-8"`（决策 D-013）。
- 前端源码与产物同构：`frontend/assets/js/` 下是可直接加载的 ES 模块，没有构建步骤；页面资源全部本地，无任何在线 CDN / 在线字体（验收项 T-002）。
- 仓库根新增 `.gitattributes` 并列入 `AGENTS.md` §2 顶层白名单：统一 LF 行尾（`* text=auto eol=lf`），图片等标 `binary`，`tests/fixtures/**/known_hosts*` 标 `-text`。理由是 `scripts/testbed_wsl.sh` 要在 WSL 里执行，CRLF 会让 shebang 与续行报 `\r: command not found` 这类极难定位的错误。

### 修复

- **SFTP 成功响应被当作错误抛出（`STATUS` 码 `0` 必须显式接受）**。
  传输层要求可接受的 `STATUS` 码**显式列出**（它无法区分「成功的 OK」与「意料之外的 OK」），
  而协议里「成功」正是 `STATUS` + 码 `0`。凡只以 `STATUS` 回话的请求
  （`WRITE`/`CLOSE`/`MKDIR`/`RMDIR`/`REMOVE`/`RENAME`）都必须带上 `_OK = (proto.SSH_FX_OK,)`，
  否则完全正常的成功响应会被当错误抛出，现象是远端返回 `OK：Success` 却报错。
  位置：`app/ssh/sftp_client.py:30-34`（定义），`:162`、`:184`、`:272`、`:281`、`:290`、`:300`（各调用点）。
- **`StrictHostKeyChecking` 收到非法取值 `strict` 导致连接必然失败**。
  内部策略名 `strict` 是为了描述意图，而 ssh 只认 `yes`/`no`/`ask`/`accept-new`/`off`。
  把内部名直接拼进命令行会让 ssh 在**解析参数阶段**就退出，报
  `command-line line 0: unsupported option "strict"`——现象是「连不上」，根因却埋在参数拼装里，不修就永远查不到协议层。
  现在用显式映射 `_STRICT_HOST_KEY_OPTION = {"strict": "yes", "accept-new": "accept-new"}`（`app/ssh/ssh_launcher.py:46-53`，使用处 `:128`）。
- **中文连接名生成的 id 含非 ASCII 字符而被自家校验拒绝**。
  id 生成原先按 `isalnum()` 过滤，而 Python 里 `"临".isalnum()` 为**真**，中文名会原样留在 id 里，
  随后被 `validate_connection_id` 拒绝（`_ID_RE = ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`，`app/models/connection.py:29`）——
  即「用中文命名连接必然 400」。修复为先做 ASCII 归一化再过滤，派生不出 ASCII 时回退成 `conn`，**显示名不受影响**
  （`app/services/connection_manager.py:181-195`）。
- **SFTP 响应包解析错位：响应包第一字段是「请求 id」**。
  漏读该字段会导致**后续全部解析错位**。已用单元测试钉死（`tests/unit/test_sftp_protocol.py`）。
- **`MKDIR` / `SETSTAT` 的属性字段编码错误会让 `sftp-server` 直接退出**。
  这两个请求的属性字段是**完整 ATTRS 结构**（`uint32 flags` + 按 flags 出现的字段），**不是**裸 `uint32`；
  发错会让服务端 `fatal()` 退出，客户端只看到「EOF poll=None」。已用单元测试钉死（同上）。
- **Windows 控制台默认 GBK 编码导致打印非 ASCII 文件名时崩溃**。
  实测：向控制台打印一个 emoji 文件名（`🎉` U+1F389）直接抛
  `UnicodeEncodeError: 'gbk' codec can't encode character '\U0001f389'` 并终止程序。
  文件管理器**必然**要处理非 ASCII 文件名，因此这不是边角情况。修复见 D-013（启动时强制 UTF-8）。

 原本是
  `document.getElementById` 的包装，而全站 45 处（`app.js` 22、`modal.js` 11、`files.js` 7、`connections.js` 2、
  `toast.js` 2、`transfer.js` 1）一律写 `$("#某 id")`。任何一处执行都会抛
  `Error: 页面缺少元素 ##modal-backdrop`，页面停留在「外壳隐藏」状态且无明显报错。
  改为 `document.querySelector(selector)`（`util.js:13-25`）。这个缺陷只有真实浏览器能发现——
  三层后端测试看不见它。
- **连接列表恒为空**：`GET /api/connections` 的响应数据是 `{"connections":[...]}`（对象），
  而 `connections.js` 按数组使用，于是 `state.connections` 永远是 `[]`，`#conn-empty` 一直显示。
  改为取 `data.connections`（`connections.js:35-40`）；同批修正新增连接的守卫（`created.connection.id`）。
- **信任主机密钥后进入的是根目录 `/` 而不是家目录**：`doConnect` 先 `openConnection` 后 `refreshConnections`，
  而 `enterConnection` 读的是**当时还是旧数据**的 `state.connections[i].session.home`（空 → 回退 `"/"`）。
  改为先刷新列表再进入连接，并在代码里写下原因。
- **`AwfmError` 的 `http_status` 是类属性，却被当作关键字参数传（4 处）**：连接必然失败的端口只会报
  `TypeError: AwfmError.__init__() got an unexpected keyword argument 'http_status'`，被兜底成 500
  `internal_error`，真正的错误码与提示全部丢失。四处的语义按原 `http_status` 改成对应子类：
  `app/ssh/known_hosts.py:246-250` 超时 → `OperationTimeout`（504）、`:256-260` 与 `:265-269` 无主机密钥 →
  `RemoteError`（502）、`app/ssh/sftp_transport.py:120-125` 找不到 `ssh` → `ConfigError`（500）。
  回归有三道闸门：`tests/unit/test_errors.py` 的构造函数用例、`test_known_hosts.py` 的死端口用例、
  `scripts/build.py` 第 6 项（扫描 `app/` 不得出现 `http_status=`）。
- **`Server` 响应头带尾随空格**：`BaseHTTPRequestHandler.version_string()` 会拼上空的 `sys_version`，
  得到 `"AWFM/0.1.0 "`。在 `app/api/http_server.py:100-106` 覆盖为只返回 `server_version`。
- **浏览器关闭页面后服务端刷整段 traceback**：keep-alive 连接被重置时 `rfile.readline` 抛
  `ConnectionResetError: [WinError 10054]` 到 `socketserver`。在 `AwfmRequestHandler` 覆写
  `handle_one_request`，捕获 `ConnectionResetError`/`BrokenPipeError`/`ConnectionAbortedError` 并置
  `close_connection = True`；修复后端到端日志中该类噪声消失。

### 安全

以下要点集中在 `docs/SECURITY.md`（威胁模型、七条要求的逐条落实、残余风险）：

- **会话令牌**：`X-AWFM-Token`，进程启动时用 `secrets` 随机生成，比较用 `secrets.compare_digest`（定时安全）。
  除 `GET /api/health` 外**所有** `/api/` 请求强制校验（`app/api/security.py:48` `OPEN_PATHS`、`:115` `check_token`）。
- **Host 头校验（防 DNS 重绑定）**：只接受字面量 `127.0.0.1` / `localhost` / `[::1]`——用主机名做白名单就绕过了防护本身
  （`app/api/security.py:44` `ALLOWED_HOSTS`，`:56` `check_host_header`）。
- **`Origin` / `Sec-Fetch-Site` 校验**：`Sec-Fetch-Site` 只允许 `none` 与 `same-origin`；带 `Origin` 时必须是回环来源，
  否则 `401`（`app/api/security.py:84`）。三重校验的固定顺序见 `:132` `verify_api_request`。
- **预检一律拒绝**：`do_OPTIONS` 对所有 CORS 预检返回 `403`，且不返回任何 `Access-Control-Allow-*` 头——本项目没有跨源使用需求（`app/api/http_server.py:132`）。
- **CSP**：静态资源响应带内容安全策略头（集成测试 `tests/integration/test_api_flow.py:167`）。
- **下载票据**：浏览器原生下载（`<a href>`）带不了自定义头，把令牌放进 URL 又会留在浏览历史里。
  因此用一次带令牌的 POST 换一张**只用于本次下载**的票据：随机、**绑定到具体连接与路径**、
  **有效期 120 秒**（`DEFAULT_TTL = 120.0`）、存内存、进程重启即失效、上限 256 张
  （`app/api/tickets.py:13-43`）。刻意**不设成一次性**——用户在「另存为」里取消后重试不该看到失效错误。
- **主机密钥信任库**：使用**项目自有** `data/known_hosts`，并把 `UserKnownHostsFile` 与 `GlobalKnownHostsFile` **同时**指向它；
  否则用户 `~/.ssh/known_hosts` 里的既有记录会让「首次确认」被跳过。默认策略 `strict`，首次连接必须显式确认指纹
  （决策 D-010，`app/ssh/ssh_launcher.py:124-128`）。
- **输入校验**：连接 id 收窄到 `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`（**禁止 `/` 与 `..`**，
  否则 `/api/connections/<id>/files` 这类路由会被解析成别的资源）、主机名与端口范围校验
  （`app/models/connection.py:29-69`）；远程路径校验见 `app/utils/paths.py` 与 `app/services/filesystem.py`。
- **日志脱敏**：在**日志格式化阶段**统一过一道正则，而不是要求每个调用点自己小心——
  调用点会漏，一条 `logger.debug("ssh 命令：%s", cmd)` 就足以漏出 `-o ProxyCommand=...` 之类的串。
  覆盖 PEM 私钥块、`-i <私钥路径>`、`password=`/`token=`/`secret=` 等键值（`app/utils/redact.py:1-38`）。
- **绑定校验**：默认只监听回环；`security.allow_lan = false` 时启动过程**拒绝**非回环绑定地址（决策 D-009）。
- **写操作受连接级开关约束**：`allow_write`，见 `app/services/filesystem.py:179` `require_write_permission`。
- **密码从不落盘**：配置文件里**没有**密码字段（决策 D-014），密码只存在于内存会话，
  经 `SSH_ASKPASS` 辅助程序交给 ssh 子进程，一次连接用完即弃（决策 D-008）。
  代价是每次重连都要重新输入——这是刻意付出的成本。
- **仓库不含凭据**：`.gitignore` 覆盖 `data/`、`logs/`、`*.pem`、`*.key`、`id_rsa*`、`id_ed25519*`、`known_hosts`、`*.log`
  （`.gitignore:7-25`）。实测 `git ls-files` 在 `data/` 与 `logs/` 下**没有任何被跟踪的文件**。

- **安全测试套件（`tests/security/`，38 项）**：所有 `/api/` 端点（除健康检查）无令牌一律 401；
  错误令牌、跨站 `Sec-Fetch-Site`、外站 `Origin`、伪造 `Host` 一律拒绝；`OPTIONS` 一律 403 且不返回任何
  `Access-Control-*`；静态资源的穿越尝试全部落空且响应体不泄漏源码；安全响应头逐项断言
  （`nosniff`、`no-referrer`、`DENY`、`no-store`、CSP；非 HTML 响应的 CSP 恰为
  `default-src 'none'; frame-ancestors 'none'`）；`frontend/` 全量离线扫描。
- **凭据纪律的两道机器闸门**：`scripts/build.py` 第 5 项扫描 `config/`、`docs/`、`frontend/`、
  `tests/fixtures/` 中填写了值（非占位符）的 `password` 字段与 PEM 私钥头；`tests/security/test_credentials.py`
  用哨兵密码验证它不出现在落盘配置、响应体、`argv`、日志与浏览器存储中。
- **离线闸门**：`scripts/build.py` 第 4 项 + `tests/security` 的 `OfflineFrontendTests` 双重扫描
  `frontend/`，唯一放行 SVG 命名空间 `http://www.w3.org/2000/svg`。
- **错误模型闸门**：`scripts/build.py` 第 6 项拒绝 `app/` 下出现 `http_status=` 关键字写法，
  防止「状态码被当构造参数」这一类缺陷复发。

### 已知限制

**范围限制（规划文档 §3.2）**

- 首版**明确不做**：在线文件编辑器、终端模拟器、远程命令执行面板；用户注册与云端同步、在线账号系统；
  数据库 / 消息队列 / 微服务及前后端分离部署；复杂权限管理平台与多用户协作；
  自动下载依赖、在线更新或任何必须连接互联网的资源。
- 浏览器只调用有限的文件管理 API，**不直接调用 SSH，也不接受任意远程 shell 命令**（规划文档 §4.1 的设计重点）。

**功能缺口**

- **P2 的创建目录 / 重命名 / 删除已在连接层实现，但不通过 HTTP 暴露**。
  以下方法在 `app/ssh/sftp_client.py` 中已实现并在测试床上实测通过，但按规划文档 §3.1 属于 P2，
  **没有**注册进 `ENDPOINTS`（详见 `docs/API.md` §7.2）：
  `SftpClient.mkdir(path, mode=0o755)`（`:267`）、`rmdir(path)`（`:276`）、
  `remove(path)`（`:285`）、`rename(old, new)`（`:294`）。
  补充：`rename` / `remove` 目前在程序内部**只**被上传的「临时名 + 改名」流程使用
  （`app/services/transfer.py:176`、`:183`），不对用户直接开放。本版唯一暴露的写操作是上传。
- **覆盖上传中断会留下被截断的文件**。SFTP v3 的 `RENAME` **不能替换已存在的目标**，
  因此：新建走「临时名 + 改名」，不会留下半成品；而**覆盖只能直接写（`TRUNC`）**——
  覆盖过程中断就会在目标路径上留下一个被截断的文件。这是本版明确接受的取舍。
  覆盖必须由调用方显式声明（`overwrite=True`）并非默认行为，前端需二次确认
  （`app/services/transfer.py:9-18`、`:119`、`:166`）。
- **只能管理 Linux 目标机**：路径语义按 POSIX 处理（`/` 分隔、区分大小写、符号链接）。
  Windows 目标机的路径方言抽象只在**设计上预留**（决策 D-001、D-006），首版不实现。
- **环境前提**：依赖目标机有 SFTP 子系统、宿主机有 OpenSSH 客户端（决策 D-003）——发行文档必须写清。
- 远程**删除、覆盖、编辑**属高风险操作，规划文档 §3.2 要求在只读浏览与传输稳定后**单独设计**，
  并带二次确认、路径检查与操作记录；本版**尚未做这项设计**。
- 文件名含控制字符（含换行符）在**路径校验层被拒绝**，这是首版策略，已在 `docs/SECURITY.md` 登记。

**验证覆盖的缺口（如实记录，不以通过率掩盖）**

- 集成测试跑在 **WSL 非 root sshd 测试床**（`127.0.0.1:2222`）上，其 UID/GID 与真实 CentOS 目标机**不同**，
  且 WSL2 的 localhost 转发是 WSL 特性，**不代表任意目标机可达**。
  规划文档 §7.2 要求的端到端验证仍需在**真实 CentOS 虚拟机**上补做（阶段 05）——**尚未执行**（决策 D-012）。
- 测试床**不含 `sudo`**，因此任何需要 root 的验证（PAM、`UsePAM yes`、特权端口 <1024）
  **不在覆盖范围内，不得据此声称已验证**（决策 D-012）。
- `tests/fixtures/` 仍然**只有 `__init__.py`**：现有夹具都由各层 `support.py` 现场构造
  （临时目录、临时 `known_hosts`、测试床连接配置），没有需要固化的合成数据文件。
- **真实 CentOS 目标机未验证**：集成与端到端全部跑在 WSL Ubuntu 24.04.2 的非 root `sshd` 上，
  规划文档 §7.2 要求的那台虚拟机仍未开机验证（决策 D-012）。
- **系统级断网空载未做**：当前会话无管理员权限，只能给出间接证据（前端零外部 URL、零第三方依赖、
  端到端对外请求为空）。详见 `docs/TEST_REPORT.md` §8。
- **端到端只覆盖 3 条主路径**：下载、编辑/删除连接、预览对话框等界面分支没有端到端用例
  （这些分支由单元层与集成层覆盖）。
- **密码认证只验证到「密码送达服务端」**：非 root `sshd` 读不到 `/etc/shadow`，
  测试床上密码认证永远不可能成功（`tests/integration/test_password_auth.py` 文件头已注明）。

**文档之间的一致性（阶段 06 已同步）**

- `README.md` 已随阶段 03~06 的落地重写：版本行、功能表真实状态、`scripts/` 命令、
  文档索引与 `LICENSE` 引用都对得上当前仓库。
- 决策 D-012 提到的测试床脚本 `scripts/testbed_wsl.sh` 已落地并通过幂等性实测
  （连跑两次 `up`：第二次不重复写配置、不重复加公钥、不重复启动进程）。

### 记录口径的边界（本文刻意留空的部分）

- 不写**性能数字**（吞吐、延迟、并发上限）——目前没有可核实的基准测试记录。
- 不写**长时间稳定性**结论——没有连续运行测试记录。
- 不写**真实 CentOS 目标机上的实测结果**——该验证属阶段 05，尚未执行。
- 不逐条列出 API 变更：`v0.1.0` 是首个版本，没有可比较的前一版本；端点清单以 `docs/API.md` 为准。

### 待补记

- 阶段 03~06 收尾提交的短哈希与便携包校验和：记录在该提交的提交信息与构建产物 `dist/SHA256SUMS.txt` 中。
  二者都**不写进被跟踪文件**——`docs/` 在便携包内，把包哈希写进文档就会改变包内容，形成自引用（`docs/RELEASE.md` 第 4 节有同样的说明）。
- git 标签名、兼容性矩阵、真实 CentOS 目标机与系统级断网的验证记录：补做后在此登记。
- 发布时把标题从「开发中（未发布）」改为实际发布日期。

---

## 参考

- `docs/DECISIONS.md` —— 决策、备选方案、理由与代价（D-001..D-017，以及作废的 D-004 与待决策项 P-001..P-005）
- `docs/REQUIREMENTS.md` —— 功能分级（P0/P1/P2）、非功能需求、验收条件 T-001..T-014、发布门槛
- `docs/API.md` —— 19 个端点的完整定义、错误码全表、版本策略、尚未暴露的写操作
- `docs/ARCHITECTURE.md` —— 分层、数据流、模块职责
- `docs/SECURITY.md` —— 威胁模型、七条安全要求的落实、残余风险
- `docs/DEVELOPMENT.md` —— 代码地图、环境准备、规范、排障
- `docs/USER_GUIDE.md` —— 面向使用者的操作说明
- `docs/TEST_PLAN.md`、`docs/TEST_REPORT.md` —— 测试范围、执行记录与验收项结论
- `docs/RELEASE.md` —— 发行说明、构建步骤、发行包内容与校验和
- `docs/reports/` —— 阶段 01~06 的阶段报告与 `FINAL_REPORT.md`
- `.md` —— 原始规划文档（用户提供，只读输入）
