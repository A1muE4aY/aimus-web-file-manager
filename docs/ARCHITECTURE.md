# AWFM 系统架构

> 本文描述 AWFM（Aimu's Web File Manager）v0.1.0 的四层架构、依赖方向、关键调用链、并发模型与错误模型。文中所有结论都对应 `app/` 与 `frontend/` 中的实际代码，行号以当前工作副本为准；引用形式为 `文件路径:行号`。
>
> 文档日期 **2026-10-15** · 对应版本 `app/__init__.py:7` 的 `__version__ = "0.1.0"` · 主入口 `app/main.py`

---

## 1 架构总览

AWFM 解决的问题是：**在一台 Windows 宿主机上，用浏览器管理另一台（或多台）Linux 目标机上的文件**。整条链路上没有任何组件需要目标机安装额外软件——只要有 SSH 服务与 SFTP 子系统即可。

| 层 | 规划文档 §4 中的名称 | 职责 | 代码位置 | 依赖方向 |
|---|---|---|---|---|
| L1 | 浏览器前端 | 文件列表、路径导航、连接配置、操作反馈 | `frontend/`（`index.html` + 11 个 ES 模块） | 只依赖浏览器，只与本机服务通信 |
| L2 | 本地 Web 服务 | HTTP API、配置管理、输入校验、日志、会话与安全策略 | `app/api/`、`app/services/`、`app/core/`、`app/models/`、`app/utils/` | `api → services → ssh` |
| L3 | SSH·SFTP 连接层 | 主机密钥验证、身份认证、目录查询、文件传输 | `app/ssh/`（6 个模块 + `__init__.py`） | 只依赖 `app/core/`、`app/utils/` |
| L4 | 指定虚拟机 | SSH 服务、SFTP 子系统、远程文件系统 | 不在本仓库内，是外部环境 | 被 L3 以子进程方式调用 |

一次「连接」在实现上等于**一个 `ssh -s sftp` 子进程 + 它在 `stdin/stdout` 上承载的一条 SFTP v3 通道**（决策 D-003、D-011）。这决定了后续所有设计：进程的生命周期就是会话的生命周期，协议帧的读写必须串行化，超时只能靠杀掉进程来打断。

---

## 2 各层职责

### 2.1 浏览器前端层（`frontend/`）

- **职责**：渲染文件列表与路径面包屑、配置连接、发起上传下载、呈现连接状态与错误、用 `<meta>` 中的会话令牌给每个请求签名。
- **关键模块**：入口 `frontend/assets/js/app.js`（由 `frontend/index.html:120` 附近的 `<script type="module" src="/assets/js/app.js">` 加载）；`api.js` 是唯一的网络出口；`files.js` / `connections.js` / `transfer.js` / `preview.js` 是四个功能区；`state.js` 是共享状态；`util.js`、`icons.js`、`toast.js`、`modal.js` 是基础设施。
- **不允许做什么**：
  - 不引入任何在线资源（CDN、在线字体、图标字体）——离线可用是验收项 T-002，也是 `AGENTS.md` §3.3 的硬规则；
  - 不使用构建步骤（没有打包器、没有 `node_modules`），浏览器直接加载 ES 模块；
  - 不接触凭据：私钥路径只是一个字符串，密码只在内存里从输入框传到 `POST …/connect` 请求体；
  - 不实现任何 SSH/SFTP 逻辑，也不解析协议。

### 2.2 本地 Web 服务层（`app/api/`、`app/services/`、`app/core/`、`app/models/`、`app/utils/`）

- **职责**：
  - `app/api/`：HTTP 服务、路由、统一响应信封、请求解析、会话令牌与来源校验、下载票据（`http_server.py`、`router.py`、`request.py`、`responses.py`、`security.py`、`tickets.py`、`handlers.py`）；
  - `app/services/`：连接配置与会话的持有者（`connection_manager.py`）、一条会话的状态机（`session.py`）、目录与元数据语义（`filesystem.py`）、上传下载语义（`transfer.py`）；
  - `app/core/`：配置的加载/校验/原子保存（`config.py`）与错误类型表（`errors.py`）；
  - `app/models/`：对外数据结构（`connection.py`、`entry.py`）；
  - `app/utils/`：路径与名称校验、日志脱敏、日志初始化、原子写入（`paths.py`、`redact.py`、`logging_setup.py`、`atomic.py`）。
- **不允许做什么**：
  - `app/api/` 不 import `app.ssh`：API 层只能经 `ConnectionManager` 拿会话，不能自己建连（`app/api/handlers.py` 的 import 只出现 `app.api.*`、`app.core.errors`、`app.models.connection`、`app.services`）；
  - `app/services/` 不 import `app.api`：服务层不感知 HTTP，错误一律以 `AwfmError` 子类抛出，由 API 层翻译成状态码；
  - 处理函数不依赖「先构造完整响应再发送」的框架结构——下载与上传是流式的，所以 `app/api/handlers.py` 的每个函数自己把响应写出去。

### 2.3 SSH·SFTP 连接层（`app/ssh/`）

- **职责**：
  - `sftp_transport.py`：**唯一持有子进程的模块**，负责帧读写、request-id 配对、超时、看门狗、stderr 排空，以及把 SFTP `STATUS` 数值码翻译成 `app/core/errors.py` 的异常；
  - `sftp_protocol.py`：SFTP v3 的纯标准库编解码（常量、`Attrs`、`Reader`、`parse_response` 等）；
  - `sftp_client.py`：REALPATH/STAT/OPENDIR/READDIR/OPEN/READ/WRITE/RENAME 等高层操作，句柄与 `close` 严格配对；
  - `ssh_launcher.py`：构造 `ssh` 命令行与子进程环境（`known_hosts`、主机密钥策略、超时、BatchMode、`IdentitiesOnly`）；
  - `known_hosts.py`：信任库读写与主机密钥采集；
  - `askpass.py`：密码认证需要的 `SSH_ASKPASS` 辅助程序。
- **不允许做什么**：
  - 除 `sftp_transport.py`（`subprocess.Popen`）与 `known_hosts.py`（`subprocess.run`）之外，任何模块都不得调用 `subprocess`——`app/ssh/__init__.py:4` 明确写了「本层是唯一允许调用 `subprocess` 的地方」；
  - 不经 `shell`：两处子进程调用都用 argv 列表（源码注释 `# noqa: S603 - argv 列表，不经 shell`），因此远程路径永远不会被 shell 解释；
  - 不理解「文件与目录」的业务语义（是否可下载、是否覆盖、写权限开关都在 `app/services/` 里判断）；
  - 不向上返回原始 stderr：`diagnostics()` 只给最后 6 行脱敏摘要。

### 2.4 目标虚拟机层

- **职责**：提供 SSH 登录与 SFTP 子系统，并按自己的文件系统语义解析路径。
- **对本项目的契约**：
  - 必须启用 SFTP 子系统（决策 D-003 的代价之一）；
  - 路径一律按 POSIX 语义理解（决策 D-001）；`REALPATH` 返回的规范路径是路径正确性的唯一依据（`app/ssh/sftp_client.py:45`）；
  - 本层不在本仓库内，无法用本项目代码保证其正确性；阶段 02 的集成测试床是 WSL Ubuntu 中的非 root `sshd`（`127.0.0.1:2222`，用户 `aimu`，主机密钥指纹 `SHA256:L/T9jS54W2ixc6CSMe7OPVtQRneYZQSVlOleczFarWE`，决策 D-012）。

---

## 3 依赖方向与边界纪律

| 边界 | 规则 | 代码实证 |
|---|---|---|
| L1 → L2 | 前端只发同源 HTTP 请求（`credentials: "same-origin"`、`cache: "no-store"`），每个 `/api/` 请求带 `X-AWFM-Token` | `frontend/assets/js/api.js:47` |
| L2 内部 | `app/api/` 只依赖 `app.services` 与 `app.core`/`app.models`；不 import `app.ssh` | `app/api/handlers.py`、`app/api/http_server.py` 的 import 段 |
| L2 → L3 | 只有 `app/services/` 直接使用 `app.ssh`：`connection_manager.py` 用信任库与 `find_ssh_executable`，`session.py` 组装 transport/client | `app/services/session.py`、`app/services/connection_manager.py` |
| L3 → L2 | 禁止；`app/ssh/` 只 import `app.core.errors`、`app.utils.*` 与同包模块 | 各模块 import 段 |
| L3 → L4 | 只经子进程：`ssh` 可执行文件 + `-s sftp`，argv 列表，`creationflags=CREATE_NO_WINDOW` | `app/ssh/sftp_transport.py:102`、`app/ssh/known_hosts.py:196` |
| 叶子 | `app/utils/`、`app/models/` 被依赖而不反向依赖上层 | 全仓 grep：没有任何模块 import `app.api` |

依赖方向是**单向**的：`api → services → ssh →（protocol / utils）`。唯一一处「跨层」引用是 `app/models/entry.py` 使用 `app/ssh/sftp_protocol.py` 的 `Attrs` 与 `S_IFMT`/`S_IFREG` 常量——它引用的是**协议数据结构**而不是连接能力，因此不构成回环。

---

## 4 关键调用链：浏览器点一下目录 → SFTP READDIR 返回

以「用户点击文件表格中的一行目录」为例，完整链路如下（共 18 步，含失败判定点）。

1. **点击**：表格行的 `click` 处理在 `frontend/assets/js/files.js:176`（`rowNode`）绑定，先经 `files.js:230` `select()` 更新选中态，再走 `files.js:240` `activate()`。`activate` 判断 `entry.type === "directory"` 时才进入下一步。
2. **进入目录**：`frontend/assets/js/files.js:44` `loadDirectory(path)` 更新 `state.path` 与加载状态，调用 `api.listFiles(connectionId, path)`。
3. **发请求**：`frontend/assets/js/api.js:131` `listFiles` → `api.js:47` `request()`，用 `fetch` 发 `GET /api/connections/{id}/files?path=…`，带 `X-AWFM-Token`（令牌来自 `api.js:13` `readMeta("awfm-token")`）。
4. **收到连接**：`app/api/http_server.py:114` `do_GET` → `app/api/http_server.py:144` `_dispatch` 判断路径以 `/api/` 开头，取 `self.ctx`（`app/api/http_server.py:109`，进程内唯一 `AppContext`，在 `create_server` 里用 `new_session_token()` 生成令牌）。
5. **三重校验**：`app/api/security.py:132` `verify_api_request` → `security.py:56` `check_host_header`（Host 必须是本机名）→ `security.py:84` `check_fetch_metadata`（`Sec-Fetch-Site` 只允许 `none`/`same-origin`，`Origin` 必须是回环来源）→ `security.py:115` `check_token`（`secrets.compare_digest` 比对）。`/api/health` 在 `app/api/security.py:48` 的 `OPEN_PATHS` 中，跳过令牌校验。
6. **路由**：`app/api/http_server.py:179` `_dispatch_api` → `app/api/router.py:49` `Router.match` 用 `^pattern$` 匹配 `ENDPOINTS`（`app/api/handlers.py:257` 注册，`handlers.py:280` `build_router()` 装配）。
7. **处理函数**：`app/api/handlers.py:131` `list_files`：`req.require_query("path")`（`app/api/request.py:47`，缺失或空串抛 `invalid_request`）→ `handlers.py:127` `_session(ctx, connection_id)`。
8. **取会话**：`app/services/connection_manager.py:235` `ConnectionManager.session`：取到会话且 `is_connected` 才返回；否则先 `get_connection()` 确认这条连接是否存在（不存在 → `connection_not_found`，HTTP 404，多半是配置刚被删），确认存在后由 `app/services/session.py:330` `require_session` 抛 `SessionNotConnected`（HTTP 404，只是还没连）。
9. **拿客户端**：`app/services/session.py:95` 的 `client` 属性返回 `SftpClient`；未连接时抛 `NotConnected`（HTTP 409）。
10. **服务层语义**：`app/services/filesystem.py:53` `list_directory` → `filesystem.py:47` `resolve_path` → `app/utils/paths.py:58` `validate_remote_path`（只校验形式：必须非空、绝对路径、无 NUL、≤4096 字节；**不做词法 `..` 折叠**）。
11. **路径规范化（第一次往返）**：`app/ssh/sftp_client.py:45` `realpath` → `app/ssh/sftp_transport.py:326` `transact`：在 `_io_lock` 内分配 request-id、`_write_frame`（`sftp_transport.py:224`）写 `SSH_FXP_REALPATH`、循环 `_read_frame`（`sftp_transport.py:288`）直到读到配对 id，交 `app/ssh/sftp_protocol.py:325` `parse_response` 解析。超时由看门狗线程杀进程制造「读返回空」来打断。
12. **确认是目录（第二次往返）**：`app/ssh/sftp_client.py:62` `stat`；若不是目录，`filesystem.py:53` 抛 `ValidationError`「该路径不是一个目录。」（对文件 `OPENDIR` 只会得到语义模糊的失败，所以这里显式先 `STAT`）。
13. **列目录（第三次及以后的往返）**：`app/ssh/sftp_client.py:96` `listdir` → `sftp_client.py:124` `opendir`（`SSH_FXP_OPENDIR` 换 `HANDLE`）→ 循环 `SSH_FXP_READDIR`，每次响应由 `app/ssh/sftp_protocol.py:350` `iter_name_entries` 逐条解析 `filename`/`longname`/`attrs`，直到返回 `SSH_FX_EOF`（`listdir` 用 `accept_status` 把 EOF 当正常结束）；`finally` 里 `close(handle)`（`sftp_client.py:152`）。`.` 与 `..` 被跳过。
14. **建数据结构**：每条 `NameEntry` → `app/models/entry.py:71` `FileEntry.from_attrs` → `entry.py:45` `to_dict`（`atime`/`permissions`/`uid`/`gid`/`link_target` 只在有值时才出现）。`link_target` 只在 `stat_path` 里按需读取，列目录**不解析符号链接目标**（`/usr/bin` 这类目录会有几百个链接，每个 `readlink` 都是一次往返）。
15. **排序与截断**：`app/services/filesystem.py:194` `_sort_key` = (目录→链接→文件, NFC 归一化后的名称 casefold, 原名)，**先排序再截断**到 `MAX_LIST_ENTRIES = 5000`（`filesystem.py:41`）；返回 `{"path", "parent", "entries", "truncated", "total"}`。
16. **写响应**：`app/api/handlers.py:131` → `app/api/responses.py:80` `send_ok` → `responses.py:71` `send_json`（`json.dumps(..., ensure_ascii=False, default=str)`，响应头含 `Cache-Control: no-store`、`X-Content-Type-Options: nosniff`、非 HTML 的 CSP）。
17. **前端拆信封**：`frontend/assets/js/api.js:32` `readBody`：HTTP 非 2xx 或 `payload.ok !== true` 时抛 `ApiError`，否则返回 `payload.data`。
18. **渲染**：`frontend/assets/js/files.js:86` `render` → `files.js:158` `renderTable` → `files.js:176` `rowNode` 用 `frontend/assets/js/util.js:37` `h()` 建 DOM，表头点击排序走 `files.js:26` `bindSortHeaders`。

**一次请求穿过的层（同一链路的分层视图）**

| 层 | 参与的模块 | 该层的失败会变成 |
|---|---|---|
| L1 | `files.js` → `api.js` | `ApiError` → `toast.js` 里的错误提示 |
| L2 | `http_server.py` → `security.py` → `router.py` → `handlers.py` → `filesystem.py` | `AwfmError` 子类 → JSON 错误信封 + HTTP 状态码 |
| L3 | `session.py` → `sftp_client.py` → `sftp_transport.py` → `sftp_protocol.py` | SFTP `STATUS` → `map_status_error()` → `AwfmError` |
| L4 | 远端 `sftp-server` | 只以 `STATUS` 码与 stderr 文本回来 |

---

## 5 关键设计决策与理由

编号沿用 `docs/DECISIONS.md`；这里只补「该决策约束了架构的哪一部分」。

| 编号 | 决策 | 理由（完整版见 DECISIONS.md） | 对架构的约束 |
|---|---|---|---|
| D-001 | Windows 宿主机 + Linux 目标机 | 宿主机是日常环境，目标机以 Linux/VMware 为主；先打通一条确定路径再谈兼容 | 远程路径按 POSIX 语义处理；路径方言抽象预留但不实现 |
| D-002 | 后端只用 Python 3 标准库，零第三方运行时依赖 | 便携版要在没有网络的机器上直接跑，不能依赖 `pip install`；也避免把供应链风险引进一个「能读整台机器文件」的工具 | HTTP 服务、并发、SFTP 编解码都由本项目实现（`app/api/http_server.py`、`app/ssh/sftp_protocol.py`）；系统 OpenSSH 视为环境前提（`docs/REQUIREMENTS.md` N-02） |
| D-003 | SSH 用系统 OpenSSH 子进程 | 自带 `known_hosts` 校验、`ssh-agent`、密钥格式与算法协商——这三件事正是第三方库要自己维护的部分 | 会话 = 子进程；密码认证必须借助 `SSH_ASKPASS`（D-008）；放弃 `sshpass`（密码会出现在进程命令行里） |
| D-004 | **已作废**（实现层不得再引用） | 原方案「`sftp` 批处理 + 解析 `ls -l`」在阶段 02 SPIKE 被推翻：`ls -l` 把权限位遮蔽成 `-rw-******`、输出受本地化影响、错误只能靠匹配英文串、文件名转义会丢、且不是真流式 | 实现层不得再引用该方案，全部改走 D-011 |
| D-005 | 前端原生 HTML/CSS/JS，无框架、无 CDN、无构建 | 离线可用是验收项 T-002，任何 CDN 或在线字体都会让离线页面变成空白 | 路由、状态、渲染、模块边界全部自己写（11 个 ES 模块）；`frontend/` 内禁止外网 URL |
| D-006 | 配置 JSON 原子写入，绝不静默重置 | 崩在半路留下被截断的 JSON，下次启动就会因「配置损坏」拒绝服务，而用户什么都没做错 | 一切写入走 `app/utils/atomic.py`（同目录 temp + fsync + `os.replace`）；读到损坏配置只能报 `config_error` 让用户处理 |
| D-007 | 传输按 64 KiB 块流式进行 | 传大文件时内存占用必须与文件大小无关（8 GB 镜像不能读进内存） | `DEFAULT_CHUNK_SIZE`、`MAX_READ_CHUNK` 都是 64 KiB；下载用生成器 `download_chunks`，上传边读请求体边写；代价是必须自己处理部分失败与回读校验 |
| D-008 | 密码认证走 `SSH_ASKPASS` + `SSH_ASKPASS_REQUIRE=force` | `ssh` 从终端读密码，而它被当子进程跑（没有终端）；`SSH_ASKPASS_REQUIRE=force` 是因为 OpenSSH 8.4+ 在有终端时会忽略 `SSH_ASKPASS` | `app/ssh/askpass.py` 生成两层辅助程序（`.cmd` 包装 + Python helper），密码经临时文件传递；`SSH_ASKPASS` 只接受可执行文件路径、不能带参数（待决策 P-002） |
| D-009 | 默认只监听回环；`security.allow_lan=false` 时拒绝非回环绑定 | 管理接口等价于对目标机的文件访问权限，默认暴露到局域网的风险远大于跨机访问的便利；**拒绝启动而不是静默改回 `127.0.0.1`**——绑错地址的后果是整台机器文件可被局域网读取，静默纠正会让风险不可见 | `app/core/config.py:178` `validate_binding` 在启动前与命令行覆盖后各跑一次；绑定地址还会决定 Host 校验是否放宽（`app/api/security.py:56`） |
| D-010 | 主机密钥策略 `strict` + 项目自有 `data/known_hosts` + 首次必须用户确认 | 用户 `~/.ssh/known_hosts` 里的旧记录会让「首次确认」被静默跳过，所以 `UserKnownHostsFile` 与 `GlobalKnownHostsFile` 都指向项目自有文件；信任库放在项目内便于审计与迁移 | 未知主机 → `HostKeyUnknown`（409，带指纹）；不匹配 → `HostKeyMismatch`（409，新旧指纹并列，**不提供一键接受**）；写入信任库前必须重新采集并核对指纹（`app/services/connection_manager.py:288`） |
| D-011 | 连接层 = 原生 SFTP v3 协议，经 `ssh -s sftp` | 五点：① 信息完整性——`flags=15` 的完整 `ATTRS` 带真实权限位，不被客户端遮蔽；② 无本地化依赖；③ 结构化 `STATUS` 码，不必匹配英文错误串；④ 文件名保真（长度前缀字符串）；⑤ 真流式。前提：Windows `ssh.exe` 管道二进制安全已实测 | 需要自己实现编解码；两个高频错误源已钉死在文档与代码注释里：**响应包第一个字段是请求 id**、**MKDIR/SETSTAT 的属性字段是完整 `ATTRS` 结构** |
| D-012 | 用 WSL Ubuntu 的非 root `sshd` 作集成测试床（`127.0.0.1:2222`，用户 `aimu`） | 零提权、随时可用、可复现；比在一台真虚拟机上反复重装快得多 | 测试床只覆盖非特权路径：不含 `sudo`，PAM 与特权端口（<1024）不在覆盖范围；UID/GID 与 CentOS 不同；WSL 的 localhost 转发不代表真实网络可达性 |
| D-013 | Windows 上一切文本 I/O 显式钉 UTF-8 | 控制台默认 GBK，中文日志会抛 `UnicodeEncodeError`；隐式编码还会让配置文件在不同区域设置下互不兼容 | `pin_stdio_encoding()` 在 `main()` 最前面调用；`open`/`write_text` 一律显式 `encoding="utf-8"` |
| D-019 | 单次 SFTP WRITE 最多 64 KiB，超出由 `SftpClient.write_chunk` 拆帧 | OpenSSH 的 `sftp-server` 拒收整包超过 256 KiB 的消息并**直接结束连接**，客户端只会看到「写入远端失败：连接已断开」，会把「大文件保存不了」误判成网络问题 | `MAX_WRITE_CHUNK` / `OPENSSH_MAX_PACKET_BYTES` 在 `app/ssh/sftp_protocol.py`；拆分在 `app/ssh/sftp_client.py` `write_chunk`（上传、覆盖写、在线编辑保存、压缩打包共用这一条路）；实测 261120 字节可、262144 字节断；回归 `tests/unit/test_sftp_client.py` |
| D-014 | 密码从不持久化 | 把密码写进本地 JSON，其安全性完全依赖该文件的 ACL，而本项目默认以非管理员账户运行、无法保证 ACL 正确；与其提供一个「看起来安全」的选项，不如不提供 | 配置文件里**没有**密码字段（`app/models/connection.py` 模块 docstring）；密码只在 `POST …/connect` 请求体里传入、只存在于内存会话；代价是每次重连都要重新输入 |

| D-020 | 统一启动入口 = `run.bat` / `run.sh`（只做「切到脚本目录 + 找 Python + 原样转发」）+ `scripts/launcher.py`（唯一实现）；默认端口 8760 → 32579；停止只在「PID 文件里的 PID」且「映像名含 python」两个条件同时成立时动作，未经确认绝不强制终止 | v0.1.1 的 `start.cmd` / `stop.cmd` 是两份互不相干的批处理：重复启动、端口冲突、停止失败都只能靠用户自己看窗口，且无法被测试覆盖。逻辑放进 Python 后，单测 39 项 + 集成 4 项 + 外壳退出码测试都可自动化；外壳只剩转发，行为由退出码 0/1/2/3 表达 | `run.bat`、`run.sh`、`scripts/launcher.py`（八命令 menu/start/status/stop/restart/logs/check/help）；发行白名单 `scripts/package.py:50-51`（不再生成 `start.cmd`/`stop.cmd`）；`app/main.py:243` 的 SIGTERM 处理器让 POSIX `stop` 走优雅退出；决策全文、备选与代价见 `docs/DECISIONS.md` D-020 |
| D-021 | 教程中未在本机实测的命令必须显式标注验证状态（【已实测】/【需管理员】/【未验证】），附录 B 汇总未验证范围 | 教程的使用场景正是「照着做却结果不同」，读者必须能分辨哪一步被验证过；未验证清单同时是后续补验证的入口 | 教程正文与 `tests/unit/test_ssh_guide.py` 绑定：标记缺失、未验证清单被删都会让测试失败；「教程里写的 ssh 选项 / 默认值 / 认证方式」与 `app/ssh/ssh_launcher.py`、`app/core/config.py`、`app/models/connection.py` 的一致性由该测试守护 |

**仍未决的相关项**：P-002（`SSH_ASKPASS` 能否携带参数，阶段 03 实测）；P-005（取主机指纹的方案已改为「临时 `UserKnownHostsFile` + `StrictHostKeyChecking=no` 连一次读回 host key」，因为 `ssh-keyscan` 在 Windows OpenSSH 9.5p2 上对本测试床失败，风险项 R-04）。

---

## 6 并发模型

### 6.1 线程清单

| 线程 | 创建处 | 数量 | 职责 |
|---|---|---|---|
| HTTP 请求线程 | `app/api/http_server.py:81` `AwfmHTTPServer`（继承 `ThreadingHTTPServer`，`daemon_threads=True`） | 每请求一个 | 执行 `router` → `handler`，直到响应写完（下载期间一直占用） |
| ssh 看门狗线程 | `app/ssh/sftp_transport.py:154` `_start_watchdog` | 每个会话一个 | 每 `_WATCHDOG_INTERVAL = 0.1` 秒检查 deadline，超时即杀子进程 |
| ssh stderr 排空线程 | `app/ssh/sftp_transport.py:131` `_start_stderr_drain` | 每个会话一个 | 持续读走子进程的 stderr，保留最后 `_STDERR_HISTORY = 200` 行 |
| 浏览器延时线程 | `app/main.py` 的 `_serve` 中 `threading.Timer` | 启动时一个 | 0.4 秒后调 `webbrowser.open`，避免与监听启动竞争 |

主线程只做 `serve_forever(poll_interval=0.5)`；`finally` 里 `server.shutdown()`、`server_close()`、`manager.disconnect_all()`（验收项 T-013：退出不留孤儿 `ssh` 进程）。

### 6.2 为什么每个都必须存在

- **每请求一线程（而不是单线程）**：下载一个 4 GB 文件时该请求线程会持续 `wfile.write`，单线程服务器在这段时间里连「刷新目录」和「查询状态」都无法响应——界面会像死掉一样。`daemon_threads=True` 让这些线程不会阻止进程退出。
- **`SftpTransport` 的可重入锁（`app/ssh/sftp_transport.py:71`，`_io_lock`）**：SFTP v3 没有请求多路复用，响应里只有 request-id 可以配对。两个线程交错写帧会让 id 与响应错配，且**无法恢复**（协议已错位）。因此 `transact()`（`sftp_transport.py:326`）把「分配 id → 写帧 → 读到配对响应」整个放在同一把 `RLock` 里。Web 服务是多线程的，这把锁不是可选项。副作用：同一条会话上的长下载会串行化该会话的其它 SFTP 操作——`ssh.max_sessions` 的上限与回收策略（`app/services/connection_manager.py:267`）就是为多连接场景准备的。
- **看门狗线程**：Windows 的 `select()` 不支持管道，没法给阻塞的 `proc.stdout.read()` 加超时；用「带超时的读线程 + 队列」又会引入「怎么杀掉一个卡住的线程」的问题（Python 没有安全的线程取消）。选第三种做法：一个看门狗线程盯着共享 deadline，超时直接终止子进程，被阻塞的 `read()` 随即返回空字节，调用方据此抛 `OperationTimeout`（HTTP 504）。副作用是「超时即断连」，对 SFTP 可以接受，而且比留下一个半死不活的通道更安全。
- **stderr 排空线程**：`ssh` 在握手阶段可能输出超过管道缓冲区（通常 64 KiB）的内容；写不进去就会**阻塞 `ssh` 自身**，表现为无法解释的挂起。必须持续排空而不是「需要时再读」。保留上限 200 行是因为 `ssh -v` 类输出可能刷很多，无上限保留等于给自己制造内存泄漏。
- **两把服务层锁**：`ConnectionManager._lock`（`app/services/connection_manager.py:65`）保护 `_sessions` 与配置列表的一致性；`RemoteSession._lock`（`app/services/session.py:67`）保护状态机字段（`_transport`/`_client`/`_state`/`_last_error`）。二者都是 `RLock`，因为 `_teardown()` 这类内部动作会在已持锁的路径上再次进入。
- **票据锁**：`DownloadTickets._lock`（`app/api/tickets.py:50`）保护票据表，`issue`/`verify`/`peek`/`clear`/`_purge` 都在锁内。

### 6.3 锁的边界纪律

- **锁内不做阻塞 I/O**：`ConnectionManager.connect`（`connection_manager.py:199`）在锁内只完成「校验 + 选会话 + 必要时回收别的会话」，真正的 `session.connect(...)` 在锁外调用（`connection_manager.py:223`）——否则一次 15 秒的连接超时会冻结所有其它 API 请求。
- **清理必须可重入**：`RemoteSession._teardown()`（`app/services/session.py:310`）先取走 `transport` 并置 `None`，再关闭；关闭失败只记 debug（关闭失败不该掩盖原始错误）。
- **生成器负责句柄**：`download_chunks`（`app/ssh/sftp_client.py:199`）是生成器，客户端中断时 `GeneratorExit` 会让 `finally` 中的 `close(handle)` 正常执行——句柄不会因为 HTTP 层提前退出而泄漏。

---

## 7 错误模型

错误类型集中在 `app/core/errors.py`：每个类自带字符串 `code` 与整数 `http_status`，因此新增错误类型不需要改任何路由代码。`to_dict()`（`app/core/errors.py:59`）的字段顺序是「先合并 `extra`、再用核心字段覆盖」——`extra` 常来自底层异常或远端返回，若允许它盖掉 `code`/`message`，一个构造失误就能让前端收到伪造的错误码。

| 异常类（`app/core/errors.py`） | `code` | HTTP | 触发场景 |
|---|---|---|---|
| `ValidationError`（:79） | `invalid_request` | 400 | 请求参数不合法（路径、主机名、端口、JSON 结构） |
| `PayloadTooLarge`（:86） | `payload_too_large` | 413 | 请求体或文件超过 `max_upload_bytes`（验收项 N-07 传输限额） |
| `ConfigError`（:93） | `config_error` | 500 | 配置文件损坏或不可读；D-006 绝不静默重置 |
| `Unauthorized`（:103） | `unauthorized` | 401 | 会话令牌缺失/不正确，或下载票据无效 |
| `ConnectionNotFound`（:114） | `connection_not_found` | 404 | 配置里没有这个连接 id |
| `SessionNotConnected`（:119） | `session_not_found` | 404 | 会话不存在或尚未建立 |
| `NotConnected`（:126） | `not_connected` | 409 | 会话存在但底层 SFTP 通道已断开（网络中断、远端重启） |
| `AuthFailed`（:133） | `auth_failed` | 401 | SSH 认证失败：用户名/密钥/密码不被接受 |
| `HostKeyUnknown`（:140） | `host_key_unknown` | 409 | 首次连接，主机密钥未经用户确认（T-005）；`extra.fingerprints` 是公钥指纹，非敏感信息 |
| `HostKeyMismatch`（:151） | `host_key_mismatch` | 409 | 主机密钥与信任库记录不符（T-005）；必须人工介入，程序不得自动覆盖 |
| `PathNotFound`（:165） | `path_not_found` | 404 | 远程路径不存在（SFTP `STATUS` 2） |
| `PermissionDenied`（:172） | `permission_denied` | 403 | 远端拒绝访问（SFTP `STATUS` 3） |
| `RemoteError`（:179） | `remote_error` | 502 | 远端返回其它错误（SFTP `STATUS` 4 或未映射码） |
| `ProtocolError`（:186） | `protocol_error` | 502 | SFTP 协议层异常：帧不合法、序列错位、通道在请求未完成时关闭 |
| `OperationTimeout`（:193） | `timeout` | 504 | 操作超时 |
| `InternalError`（:198） | `internal_error` | 500 | 未预期的内部异常 |

**SFTP `STATUS` → 异常 → HTTP 的三段式翻译**（`app/ssh/sftp_transport.py:49` `map_status_error`）：

| SFTP `STATUS` | 异常 | HTTP |
|---|---|---|
| 2 `NO_SUCH_FILE` | `PathNotFound` | 404 |
| 3 `PERMISSION_DENIED` | `PermissionDenied` | 403 |
| 5 `BAD_MESSAGE` | `ProtocolError` | 502 |
| 6 `NO_CONNECTION` / 7 `CONNECTION_LOST` | `NotConnected` | 409 |
| 8 `OP_UNSUPPORTED` | `RemoteError` | 502 |
| 其它（含 4 `FAILURE`） | `RemoteError` | 502 |

选原生协议的直接收益就在这里：判定依据是**数值码**，不必匹配 `sftp` 客户端输出的英文串——那些串在不同 OpenSSH 版本与不同 `LC_*` 下都会变（D-011 理由 ③）。

---

## 8 前端模块依赖图

`frontend/assets/js/` 共 11 个 ES 模块，全部由浏览器直接加载，没有打包步骤。依赖关系如下（箭头 = `import`）。

```
index.html
  └─ app.js                    （唯一的入口，只被 index.html 的 script 标签加载）
       ├─ api.js               （唯一的网络出口：fetch / XMLHttpRequest）
       ├─ util.js              （DOM 与格式化工具）
       ├─ state.js             （共享状态对象）
       ├─ icons.js             （内联 SVG）
       ├─ toast.js ─── util.js
       ├─ modal.js ─── util.js
       ├─ connections.js ── api.js, util.js, toast.js, modal.js, state.js
       ├─ files.js ──────── api.js, util.js, icons.js, toast.js, state.js
       ├─ transfer.js ───── api.js, util.js, toast.js, modal.js, state.js
       └─ preview.js ────── api.js, util.js, modal.js, toast.js, state.js
```

| 模块 | 行数 | 依赖（import 行号） | 被谁依赖 |
|---|---|---|---|
| `app.js` | 226 | api、util、toast、modal、connections、files、transfer、preview、state（`:8-16`） | 无（入口） |
| `api.js` | 230 | 无 `app` 内部依赖 | app、connections、files、transfer、preview |
| `state.js` | 56 | 无 | app、connections、files、transfer、preview |
| `util.js` | 175 | 无 | app、connections、files、transfer、preview、toast、modal |
| `icons.js` | 63 | 无 | files |
| `toast.js` | 76 | util（`:8`） | app、connections、files、transfer、preview |
| `modal.js` | 172 | util（`:8`） | app、connections、transfer、preview |
| `connections.js` | 581 | api、util、toast、modal、state（`:11-15`） | app |
| `files.js` | 286 | api、util、icons、toast、state（`:9-13`） | app |
| `transfer.js` | 198 | api、util、toast、modal、state（`:12-16`） | app |
| `preview.js` | 86 | api、util、modal、toast、state（`:9-13`） | app |

**没有循环依赖**：`api.js`、`state.js`、`util.js`、`icons.js` 不 import 任何本包模块，依赖图是一个以 `app.js` 为根的树。四个功能区模块之间**互不 import**——它们需要通知彼此的地方由 `app.js` 注入回调（`app.js:185-195`）：

- `connections.initConnections({ onEnter, onLeave })`：连接建立/断开后，由 `app.js:49` `enterConnection` 与 `app.js:60` `leaveConnection` 决定刷新文件列表、重置视图；
- `files.initFiles({ onSelectionChange, onOpenFile, onPathChange })`：选中项变化、双击文件、路径变化时统一由 `app.js:32` `updateToolbar` 决定按钮可用性（这是全部按钮可用性的**唯一决定处**）；
- `transfer.initTransfer({ onChanged })`：上传完成后回调 `files.refresh()`，避免 `transfer.js` 直接依赖 `files.js`。

这样的好处是「谁调用了什么」全部收敛在入口文件里；代价是每个功能区模块都要有一个 `init` 入口来接收依赖（`files.js:21`、`connections.js:19`、`transfer.js:20`）。

---

## 9 已知边界与首版不做的事

- **写操作只在连接层实现，未通过 HTTP 暴露**：`SftpClient` 已实现 `mkdir`（`app/ssh/sftp_client.py:267`）、`rmdir`（`:276`）、`remove`（`:285`）、`rename`（`:294`），但按规划文档 §3.1 它们属于 P2，首版不出现在 `ENDPOINTS` 里。唯一被暴露的写操作是**上传**（`POST …/upload`），且受连接级开关 `allow_write` 约束（`app/services/filesystem.py:179` `require_write_permission`）。
- **不做在线编辑器**：`GET …/preview` 是只读预览，有硬上限 `DEFAULT_PREVIEW_BYTES = 256 KiB`（`app/services/filesystem.py:38`），二进制文件直接拒绝。
- **不做终端、不做远程命令**：整个连接层只有一条 SFTP 通道（`ssh -s sftp`），没有 `exec` 通道。
- **不做多用户**：只有一个进程内令牌（每次启动换新），没有账户体系；`security.allow_lan=true` 时没有身份验证，规划文档 §10③ 要求将来单独设计。
- **不做打包与依赖下载**：便携版只是「Python + 源码 + 配置模板」的组合，不引入任何在线更新机制（规划文档 §3.2）。

---

## 参考

本文依据以下源码与文档（路径相对项目根，正斜杠）：

- 规划文档：`.md`（§3.1 功能分级、§4 四层架构、§4.1 核心运行流程、§10 安全要求）
- `docs/DECISIONS.md`（D-001..D-014）、`docs/REQUIREMENTS.md`、`docs/PROJECT_STRUCTURE.md`
- `docs/reports/PHASE-01-ENVIRONMENT.md`、`docs/reports/PHASE-02-SPIKE.md`
- `app/__init__.py`、`app/main.py`、`app/core/config.py`、`app/core/errors.py`
- `app/models/connection.py`、`app/models/entry.py`
- `app/services/connection_manager.py`、`app/services/session.py`、`app/services/filesystem.py`、`app/services/transfer.py`
- `app/ssh/__init__.py`、`app/ssh/ssh_launcher.py`、`app/ssh/sftp_transport.py`、`app/ssh/sftp_protocol.py`、`app/ssh/sftp_client.py`、`app/ssh/known_hosts.py`、`app/ssh/askpass.py`
- `app/api/http_server.py`、`app/api/router.py`、`app/api/request.py`、`app/api/responses.py`、`app/api/security.py`、`app/api/tickets.py`、`app/api/handlers.py`
- `app/utils/paths.py`、`app/utils/redact.py`、`app/utils/logging_setup.py`、`app/utils/atomic.py`
- `frontend/index.html`、`frontend/assets/js/app.js`、`frontend/assets/js/api.js`、`frontend/assets/js/files.js`、`frontend/assets/js/connections.js`、`frontend/assets/js/transfer.js`、`frontend/assets/js/preview.js`、`frontend/assets/js/state.js`、`frontend/assets/js/util.js`、`frontend/assets/js/icons.js`、`frontend/assets/js/toast.js`、`frontend/assets/js/modal.js`
