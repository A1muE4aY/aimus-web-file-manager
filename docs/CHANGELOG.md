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
  `v0.1.1` 正在开发中（阶段一~五已完成，见下节），**尚未打包、尚未打标签**。
- **日期**：ISO `YYYY-MM-DD`。
- **维护方式**：**人工维护**，不自动生成。变更发生时同步写，而不是发版前一次性补记。

## [v0.1.1] — 开发中（未发布）

- **版本号**：仍是 `0.1.0`（`app/__init__.py:7`）。阶段六交付时统一改为 `0.1.1` 并重新打包，本轮不提前改号。
- **状态**：阶段一（修复已有缺陷）、阶段二（优化侧边栏）、阶段三（远端文件检索）、阶段四（远端文本编辑与文件操作）、阶段五（在线虚拟机自动发现）已落地并通过测试；阶段六**未开始**。
- **起始日期**：2026-10-16。
- **依据**：工作区根目录的任务书 `2.md`（用户提供的第二轮验收要求）。
- **提交纪律**：阶段一~三的改动共用 `app/api/handlers.py`、`app/core/errors.py` 与前端若干文件，无法拆成互不依赖的提交，因此**合并为一次提交** `6e619f0`（2026-10-16，「阶段 01~03（v0.1.1）：缺陷修复、侧边栏优化、远端文件检索」，43 个文件 / +4768 −60，提交信息里逐阶段列明）；阶段四起每阶段单独提交——阶段四是独立提交 `b2bfc1f`（2026-10-16，「阶段 04（v0.1.1）：远端文本文件编辑与文件操作」，35 个文件 / +6182 −112），随后补了一次收尾提交 `4d69390`；阶段五同样是独立提交 `7a31fe2`（2026-10-16，「阶段 05（v0.1.1）：在线虚拟机自动发现」，32 个文件 / +4901 −64）。
- **行号漂移**：本文 v0.1.0 段引用的 `app/api/handlers.py:259-279`（`ENDPOINTS`）与 `:282`（`build_router()`）**已失效**；阶段三一度是 `:294-317` 与 `:320`，阶段四是 `:434-463` 与 `:466`，阶段五把四个发现端点排到表尾后现为 **`:472-506` 与 `:509`**。历史条目按当时源码保留，不复改；引用这些位置时以函数名为准。

### 阶段进度（依据任务书 2.md 的六阶段）

| 阶段 | 名称 | 状态 | 可核实的产物 |
| --- | --- | --- | --- |
| 一 | 修复已有缺陷 | 已完成 | 写权限热同步、陈旧列表标记与重试入口、新建连接不再打回占位页；测试 `tests/unit/test_permission_sync.py`、`tests/integration/test_write_permission_sync.py`、`tests/security/test_write_permission_paths.py`、`tests/e2e/test_browser_regressions.py` |
| 二 | 优化侧边栏 | 已完成 | `frontend/assets/css/app.css`、`frontend/assets/js/connections.js`；测试 `tests/e2e/test_browser_sidebar.py` |
| 三 | 添加远端文件检索 | 已完成 | `app/services/search.py`、`app/api/handlers.py:161`（三个检索端点）、`frontend/assets/js/search.js`、`frontend/index.html:80`/`:88`；测试 unit 36 项 / integration 15 项 / security 18 项 / e2e 4 项；接口文档 `docs/API.md` §5.20–5.22；手册第 9 章（阶段四插入新第 8 章后顺延，原第 8 章）；阶段报告 `docs/reports/PHASE-03-SEARCH.md` |
| 四 | 远端文本编辑与文件操作 | 已完成 | `app/services/editor.py`、`app/services/fileops.py`、6 个新端点（编号第 23~28，`app/api/handlers.py:434-463`）、配置键 `security.max_edit_bytes`、`EditConflict`（`app/core/errors.py:210`）；前端 `frontend/assets/js/edit.js`/`fileops.js` 与文件列表「操作」列；测试 unit 103 项（本阶段新增：`tests/unit/test_editor.py` 43 + `tests/unit/test_fileops.py` 60，配套内存版 SFTP 假件 `tests/unit/fake_sftp.py`）/ integration 61 项 / security 12 项 / e2e 5 项；四层合计 636 项 0 失败 0 跳过；接口文档 `docs/API.md` §5.23–5.28；手册第 8 章；阶段报告 `docs/reports/PHASE-04-EDIT.md` |
| 五 | 自动发现在线虚拟机 | 已完成 | `app/services/discovery.py`、4 个发现端点（编号第 29~32，`app/api/handlers.py:472-506`）、配置段 `discovery`（9 个键）、`DiscoveryBusy`（`app/core/errors.py:225`）；前端 `frontend/assets/js/discovery.js` 与侧栏「扫描」入口；测试 unit 49 项 / integration 10 项 / security 11 项 / e2e 4 项（本阶段新增 74 项），四层合计 717 项 0 失败 0 跳过；接口文档 `docs/API.md` §5.29–5.32 与 §7.4；手册 §4.4 与 §10.2 的 discovery 段；阶段报告 `docs/reports/PHASE-05-DISCOVERY.md` |
| 六 | 回归、CU 验收与交付 | 未开始 | — |

### 新增

- **远端文件检索**（阶段三）：3 个新端点，编号第 20~22（路由表 `app/api/handlers.py:294-317`）——`POST /api/connections/{id}/search`（202 + 快照）、`GET /api/searches/{search_id}`、`DELETE /api/searches/{search_id}`（幂等中止）。
  - 服务层 `app/services/search.py`：后台线程 `awfm-search-<id>` 逐目录列举，**只走既有 SFTP 通道，不在远端执行任何命令**；`scope` 固定 `subtree`；按名称 `casefold` 包含匹配；排序「目录 → 符号链接 → 文件」；结果行带 `parent` 与 `depth`。
  - 四道预算（`SearchLimits`）：`max_results=500`、`max_dirs=2000`、`max_entries=100000`、`time_budget_seconds=45.0`；任一触发即 `truncated=true` 并写入中文 `truncated_reason`；读不到的目录只计入 `skipped_dirs`/`skipped`（明细上限 20 条），连续 10 个目录失败才整体失败；符号链接只报告不跟随（目录环与越界链接都不会被走进去）；同一连接同时只允许一个检索（`search_busy`）。
  - 错误模型新增 `SearchBusy`（`code=search_busy`，HTTP 409，`app/core/errors.py:193`）。
  - 前端：`frontend/assets/js/search.js`（发起 / 700 ms 轮询 / 中止 / 清空 / 结果表 / 区分「没有匹配」与「搜索失败」），搜索栏 `frontend/index.html:80`，结果面板 `frontend/index.html:88`；`frontend/assets/js/files.js` 的 `locate(parent, name)` 跳到所在目录、选中并高亮（`tests/e2e/test_browser_search.py` 断言 `.is-located`）。结果表列出名称 / 类型 / 所在目录 / 大小 / 修改时间。
- **远端文本在线编辑**（阶段四）：`GET|PUT /api/connections/{id}/text`（第 23~24 号端点）。
  - 服务层 `app/services/editor.py`：只接受**普通文件**且必须是可识别的 UTF-8 文本——目录、二进制（含 NUL 或控制字符密度过高）、非 UTF-8、超过 `security.max_edit_bytes`（默认 2097152 字节 = 2 MiB）一律结构化拒绝；读取时剥掉 BOM、把 CRLF 与 CR 折成 LF，并记录换行风格（`lf`/`crlf`/`cr`）、是否混合换行、是否有末尾换行、`sha256` 与 `mtime` 作为保存基线；保存时先 `require_write_permission("保存文件")`，再核对基线（`base_sha256` 或 `base_mtime`），不一致抛 `EditConflict`；内容先写成 `<名字>.awfm-part-<随机>` 临时文件并校验字节数，再把原文件改名成 `<名字>.awfm-bak-<随机>` 备份、新文件改名顶替，任一步失败都会回滚；默认**沿用文件原有的换行风格**，`keep_bom` 决定是否写回 BOM。
  - 新增配置键 `security.max_edit_bytes`（`app/core/config.py` 的 `DEFAULTS` / `SecurityConfig` / `_SECURITY_KEYS` / `parse_config` 四处，以及 `config/config.example.json`；允许 1024..67108864），当前值随 `GET /api/session` 返回。
  - 错误模型新增 `EditConflict`（`code=edit_conflict`，HTTP 409，`app/core/errors.py:210`）：宁可让用户重来，也不覆盖别人的修改。
  - 前端 `frontend/assets/js/edit.js`：独立编辑对话框（路径 / 大小含上限 / 修改时间 / 编码 / 换行 / 字符计数 / 「已修改，尚未保存」状态），**Ctrl+S** 保存；冲突时显示「重新加载远端内容」并保留用户输入；取消时若有改动先内联确认（不开第二个模态，因为模态 DOM 只有一组）。
- **文件操作**（阶段四）：4 个新端点（第 25~28 号）——`POST …/rename`、`POST …/delete`、`POST …/compress`（201）、`POST …/extract`（201）。
  - 服务层 `app/services/fileops.py`：重命名（同名 / 目标已存在 / 非法名 / 根目录都拒绝）、删除（非空目录必须显式 `recursive=true`，递归受 10000 条目与 64 层深度上限约束）、压缩成 **.tar.gz**（GNU tar + gzip，保留权限与 mtime，**符号链接以链接本身入包**，条目上限 10000、原始字节上限 512 MiB）、解压（支持 `.tar.gz` / `.tgz` / `.tar` / `.zip`，目标目录不存在时只创建最后一级；远端已存在同名文件默认跳过并列出，`overwrite=true` 才覆盖；条目数或解出字节数触顶时停止并记入 `stopped`，已解出的部分保留）。
  - 压缩与解压**全部在本机进程内流式完成**（标准库 tarfile / gzip / zipfile + SFTP 读写），远端不执行任何命令。
  - 前端 `frontend/assets/js/fileops.js`（重命名 / 删除 / 压缩 / 解压四个对话框，删除对非空目录会二次确认）、文件列表新增「操作」列（`frontend/assets/js/files.js` 的 `actionCell`）、工具栏「编辑」按钮、`frontend/index.html` 与 `frontend/assets/css/app.css`；预览窗口增加「编辑」入口并标明预览只读。
- **在线虚拟机自动发现**（阶段五）：4 个新端点，编号第 29~32（`app/api/handlers.py:472-506`）——`GET /api/discovery`（环境概览：能读到什么、上限是多少，不读大文件也不探测）、`POST /api/discovery/scan`（**202** + 快照，后台线程里跑）、`GET /api/discovery/scans/{scan_id}`（轮询进度与结果）、`DELETE` 同路径（幂等中止）。发现端点**不挂在任何连接之下**，也不需要已连接。
  - 服务层 `app/services/discovery.py`：**五层取材**——VMware 清单（`inventory.vmls`）、`vmrun list`（运行状态，是**可选依赖**：缺了只把状态标成「未知」，而不是当成「已关机」）、虚拟机的 `.vmx`（名称 / 客户机类型 / 网卡 MAC）、`vmnetdhcp.conf` 与 `vmnetdhcp.leases`（虚拟网段与地址历史）、系统邻居表（`Get-NetNeighbor`，失败时回退 `arp -a`）；装了 VMware Tools 时还会用 `vmrun getGuestIPAddress` 问客户机自报的地址（实测 487 ms，超时 5 秒）。
  - **三种状态分开建模**：发现虚拟机（清单与 `.vmx` 里有的台数）/ 地址在线（`answer_state` 为 `online` 或 `ssh_open`）/ SSH 可用（`ssh_open`）。虚拟机级的 `ssh_open` 是布尔值或 `null`——`null` 表示「一个地址都没探测过」，**不是**「确定连不上」；地址级 `ssh_state` 保留探测的原始结论（`open` / `refused` / `timeout` / `unreachable` / `not_probed` / `error`）。
  - **有上限的探测**：只探 `vmnetdhcp.conf` 声明过的虚拟网段、只探 22 端口、每个地址一次 TCP 连接（默认 1 秒）、每网段不超过 `max_addresses_per_subnet`、整轮不超过 `max_probes`、总时长不超过 `time_budget_seconds`；碰到上限记 `truncated` 与 `truncated_reason`，用户中止记 `interrupted`（两者可能同时为真）。
  - **结果只是候选**：不写连接表、不自动信任主机指纹、不建立 SSH 会话（「SSH 可用」是直接对 22 端口试出来的，没有登录）、不执行任何远端命令，也不修改 VMware 的任何文件（安全层逐字节比对）。
  - 新增配置段 `discovery`（9 个键：`enabled` / `probe_ssh` / `probe_timeout_seconds` / `max_probe_workers` / `max_addresses_per_subnet` / `max_probes` / `time_budget_seconds` / `vmware_root` / `vmware_data_dir`，见 `app/core/config.py` 的 `DEFAULTS` / `DiscoveryConfig` / `_DISCOVERY_KEYS` / `parse_config` 四处，以及 `config/config.example.json`）。
  - 错误模型新增 `DiscoveryBusy`（`code=discovery_busy`，HTTP 409，`app/core/errors.py:225`）：同一时刻只允许一个扫描，第二次请求返回 409 并提示先等它结束或点「中止」。
  - 前端：`frontend/assets/js/discovery.js`（侧栏「扫描」入口、六个来源的状态表、阶段与进度、中止、结果表按三态分列、每行「创建连接」）、`frontend/assets/js/api.js` 新增四个方法、`frontend/index.html` 的 `#btn-scan-vms` 与 `frontend/assets/css/app.css` 的新样式；`frontend/assets/js/connections.js` 的 `openConnectionForm(existing, options)` 支持「草稿预填 + 提示语」，因此从结果里点「创建连接」走的是**新增**分支而不是编辑分支。
  - 本机实测（VMware Workstation 26 + CentOS Stream 10）：3 台虚拟机（其中 1 台正在运行）、探测 3/3 个地址、1 个地址 SSH 可用，整轮 4.2~5.1 秒。


### 变更

- 活动会话不再持有建连时的 `Connection` 快照，改为持有可热更新的引用，写权限开关改了立刻生效（阶段一缺陷①）。
- 侧边栏加宽并重排卡片（名称 / 用户名+主机+端口 / 认证方式 / 远端家目录 / 状态），长名称与长路径换行且不重叠（阶段二）。
- `docs/API.md` 扩到 22 个端点并新增 §5.20–5.22；`docs/USER_GUIDE.md` 新增第 8 章「文件检索」，原第 8~12 章顺延为 9~13 章。
- `tests/e2e/artifacts/*.png` 加入 `.gitignore`：截图按随机 `RUN_TAG` 每次运行生成，不逐张入库（v0.1.0 已入库的 6 张保留）。
- 仓库清理：v0.1.0 某脚本按字面量创建的 `%SystemDrive%` 目录（内含 `ProgramData/Microsoft/Windows/Caches/*.db`，0.94 MB）移入 `.archive/junk/percent-systemdrive-2026-10-16/`。
- `docs/API.md` 扩到 **28 个端点**并新增 §5.23–5.28（读 / 写文本、重命名、删除、压缩、解压），同时重核了全文引用的源码行号，并声明「行号按本文日期的工作树核对，v0.1.1 插端点会让旧行号漂移，引用时以函数名为准」；`docs/USER_GUIDE.md` 新增第 8 章「在线编辑与文件操作」，原第 8~13 章顺延为第 9~14 章（`docs/USER_GUIDE.md:388` 起）。
- 上传接口的既有语义**保持不变**：仍然只有「上传 / 覆盖」，覆盖仍然直接截断写入（见「已知限制」）。
- `docs/API.md` 扩到 **32 个端点**并新增 §5.29–5.32（发现的环境概览 / 发起扫描 / 轮询 / 幂等中止）与 §7.4（发现读什么、不读什么）；错误码表补 `discovery_busy` 一行，并修正被 `DiscoveryBusy` 插入顶下去的两个行号（`internal_error` → `errors.py:241`、`timeout` → `errors.py:236`）。`docs/USER_GUIDE.md` 新增 §4.4「不填地址：让工具去虚拟机网络里找一台」与 §10.2 的 discovery 段字段表（**不新开一章**，避免第 9~14 章整体顺延）。
- 四个发现端点排在 `ENDPOINTS` 表的**最后**（发现级与具体连接无关），让 API 文档的端点编号保持「只增不改」：20~22 检索、23~28 编辑与文件操作、29~32 发现。已入库文档里按编号引用的 6 处因此无需改动。
- 扫描结束（含用户中止）时把 `stage` 明确收成 `done`，避免「阶段」这一列在扫描结束后停在上一个动作上像是卡住了；失败时保留当时那一步，好看出卡在哪里（`app/services/discovery.py` 的 `Discovery._run`）。
- `config/config.example.json` 删掉了 `$schema` 一行，使模板与 `DEFAULTS` 逐字段相等（原因见「修复」第一条）。

### 修复

- **缺陷①写权限状态不同步**：界面打开「允许写操作」后立刻上传仍被拒，必须断开重连。修复后写操作每次都以当前配置为准（`tests/security/test_write_permission_paths.py` 反向验证：撤权后旧会话引用写不进去，远端不落一个字节，连 `<名字>.awfm-part-*` 都不出现）。
- **缺陷②远端目录刷新后的陈旧列表**：目录被删后点「刷新」，页面报错却把上一次的列表留在屏幕上。修复后旧列表被明确标注「已过期」并给出重试入口（`tests/e2e/test_browser_regressions.py`）。
- **缺陷③新建连接后的文件区状态**：已有活动连接时新建连接会把文件区打回占位页。修复后新建不影响正在浏览的连接（同上）。
- 阶段三实现中修掉的界面缺陷：清空检索后结果表仍留着隐藏的旧行（`frontend/assets/js/search.js` 的 `render()` 先清空再判 `idle`）；空闲态与搜索后的范围文案不一致（「范围：当前目录及其子目录」→「范围：<root> 及其子目录」）。
- 参数形状检查前移：`start_search`（`app/api/handlers.py:161`）先校验 `path`/`query` 再找会话，避免「没连接」时把 400 变成 409（`tests/security/test_search_paths.py` 的 `test_malformed_body_is_rejected_without_a_live_session` 钉住；阶段四把同一条纪律扩展到全部六个新端点）。
- **破坏性操作会跟着符号链接走**（阶段四写单元测试时发现，属真实缺陷）：原先删除 / 重命名 / 压缩都先把路径整条 `realpath`，于是「删除一个指向 `/home/aimu/real.txt` 的链接」实际删掉了 `real.txt`。修复为只对**父目录**做 `realpath`、最后一段不解析（`app/services/fileops.py` 的 `_canonical_entry_path`），并补了三条回归：改链接名不动目标、删链接保留目标、`链接以链接身份进包`。
- 在线编辑保存曾经默认用 LF 写回，会把 CRLF 文件悄悄改成 LF；改为**默认沿用文件原有的换行风格**（`app/services/editor.py` 的 `save_text_file`，并新增只读头部的 `_peek` 用于探测风格）。
- 解压目标目录不存在时原先直接报错，改为**创建最后一级**（只建一级；多级路径写错仍然报错，不静默造出一串空目录）。
- **文件操作与保存后的成功提示显示 undefined**（阶段四收尾做 e2e 截图核对时发现，属真实缺陷）：后端把结果包成 `{"entry": …}` / `{"deleted": …}` / `{"archive": …}` / `{"extract": …}` 这样的信封，而 `frontend/assets/js/fileops.js` 里除重命名外都直接读顶层字段，于是屏幕上出现「已删除「undefined」」——远端状态是对的，只有提示是错的（e2e 原本只核对远端，所以漏掉了）。修复为统一的 `unwrap(data, key)`：缺键时**抛错**而不是返回 undefined，`tests/e2e/test_browser_edit.py` 新增 `wait_for_toast` 断言提示文案里不含 `undefined`。
- **随包发布的配置模板根本加载不了**（阶段五写配置测试时发现，属真实缺陷）：`config/config.example.json` 第 2 行写着 `"$schema": "./config.schema.json"`，而 `config/` 下**没有**这个文件、全仓库也没有第二处引用；`parse_config` 又会因未知根字段直接抛 `ConfigError`（「配置里含无法识别的字段」），于是「照抄随包模板」的结果是程序启动不了。修复为删掉该行（模板现与 `DEFAULTS` 逐字段相等），并把 `example_config_text()` 由 `json.dumps(DEFAULTS)` 改为**真的读磁盘模板**（`app/core/config.py`）；同时新增两条单元测试：模板能被 `parse_config` 加载、模板与 `DEFAULTS` 相等。原先那条断言比的是「自己刚生成的字符串」，模板少一整段也照样通过，属于自证。
- **用户自定义的 `security.max_edit_bytes` 会被静默丢掉**（阶段五补 `discovery` 段时发现，属真实缺陷）：`AppConfig.to_dict()` 的 `security` 段漏了这个键，而连接管理每次增删改连接都会 `save_config()`，于是用户把它调大之后，只要在界面上动一次连接，设置就被写回默认的 2 MiB。修复为在 `to_dict()` 里补上（`app/core/config.py`），并加了一条 `parse_config(to_dict())` 的往返用例（自定义值 123456 与 `discovery.max_probes=64` 都不丢）。
- **本机虚拟网卡与网关地址既是候选又永远不会被探测**（阶段五读代码时发现，属真实缺陷）：`app/services/discovery.py` 的 `targets` 已经排除了它们，但「其它地址」列表没有排除，于是 `192.168.170.1`/`.2` 这类地址会出现在结果里永远标着「未探测」；而那句解释「本机虚拟网卡与网关地址不做探测。」写在 `if host_addresses & set(targets)` 里——这个条件恒为假，**是一句永远不会出现的死代码**。修复为在「其它地址」循环里就跳过并单独计数，让说明真的会出现在 `notes` 里（「邻居表里有 N 条是本机虚拟网卡或网关的地址，已跳过（它们不是待连接的机器）。」；本机实测 N=1，与既有的「过滤 172 条」相加仍是 173，没有重复计数）。

### 安全

- 检索的路径与关键词校验与浏览同源（`app/utils/paths.py` 的 `validate_remote_path`）：非绝对路径、含 NUL、超过 4096 字节一律 400；`..` 交给服务端 `realpath` 解析后再判定，不做调用方折叠；`query` 上限 128 字符，除制表符外的控制字符拒绝（`tests/security/test_search_paths.py`）。
- 检索不为任何请求在远端执行 shell 命令：断言检索前后命令行含 `-p 2222` 的 `ssh.exe` 进程数不变（验收项 T-013），并断言检索不改动远端目录（`tests/security/test_search_paths.py` 的 `SearchCommandDisciplineTests`）。
- 写权限门禁的对抗性验证：绕过界面直接打服务层写入口，撤权后依旧全部被拒（`tests/security/test_write_permission_paths.py`）。
- 阶段四的六个新写入口（保存 / 重命名 / 删除 / 压缩 / 解压）每一个都在服务层第一句查写权限，**界面按钮状态不作数**：`tests/security/test_edit_paths.py` 在撤权连接上打这 5 个入口，全部 401，事后核对远端没有新增任何文件。
- 解压的成员路径校验（`app/services/fileops.py` 的 `_member_target`）：绝对路径、`..` 段、NUL、以反斜杠充当分隔符的写法一律**整包拒绝**（不是悄悄跳过）；符号链接与硬链接条目跳过并计入 `skipped`。集成与安全两层都用真实构造的越界 tar/zip 验证过：拒绝后 /tmp 与夹具根都没有 `evil.txt`，且随后一个正常归档仍能解压。
- 在线编辑不做「猜测式解码」：编码不是 UTF-8 就直接拒绝，并在 `detail` 里给出解码失败的字节偏移，**不静默改写用户内容**。
- 阶段五的发现端点做了对抗性验证（`tests/security/test_discovery_paths.py`，11 项）：四个端点无令牌一律 401；畸形扫描 id 一律 404；探测只落在已知虚拟网段内、且只探 **22 端口**；本机虚拟网卡与网关地址既不进候选也不被探测；`discovery.probe_ssh=false` 时一个包都不发；`max_probes=1` 是真上限；扫描前后 VMware 的清单、`vmnetdhcp.conf`、`vmnetdhcp.leases` **内容逐字节不变**（只允许 VMware 自己的 DHCP 服务往租约文件追加，判据是旧内容是新内容的前缀）；扫描前后 `ssh.exe` 进程数不变（验收项 T-013 的同类要求）；扫描不往连接表里加任何东西——结果只是候选。

### 已知限制

- 阶段六未开始：CU 验收与 v0.1.1 打包**尚未执行**（阶段五的在线虚拟机发现已落地，见上）。
- 文件操作**仍然没有**：新建目录、修改权限、复制 / 移动、打包下载、多选批量操作；压缩格式固定 `.tar.gz`（解压额外支持 `.tgz` / `.tar` / `.zip`）。
- 在线编辑只支持 **UTF-8** 文本（含或不含 BOM），单文件上限 `security.max_edit_bytes`（默认 2 MiB）；不做编码转换，不提供十六进制视图或行尾转换开关。
- 没有版本历史与撤销：删除、覆盖上传、保存都不可回退（远端回收站不在本项目范围内）；编辑器内容只在浏览器内存里，刷新页面即丢。
- 检索上限与压缩 / 解压上限都是常量，暂不可配置；检索不跟随符号链接、不搜文件内容、不支持通配符与正则。
- 覆盖上传中途取消仍会留下不完整的文件（SFTP v3 的 RENAME 不能替换已存在目标），在线编辑保存则走「临时名 + 改名 + 备份回滚」，不受此影响。
- 版本号仍是 `0.1.0`，便携发行包与校验和仍是 v0.1.0 的那一份，未重新构建。
- 在线虚拟机发现只认**本机装好的 VMware Workstation**（清单、`vmrun`、`vmnetdhcp.*`）：不认 VirtualBox、Hyper-V，也不认远程 ESXi。邻居表只有 Windows 读得到（其它平台该来源标 `unavailable`，地址只能来自租约与清单）；非管理员读不到 VMware 进程的命令行，运行状态由 `vmrun` 决定，`vmrun` 也读不到时虚拟机状态是「未知」而**不是**「已关机」。它只判断 22 端口通不通，不识别机器上跑了别的什么服务，也不区分「机器没开」与「防火墙拦了」。
- 阶段六要求的真实桌面 CU 验收**尚未执行**：阶段一~五的证据来自单元 / 集成 / 安全 / 无头 Edge e2e 测试，都不等同于 CU 验收。

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
