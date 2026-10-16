# 阶段一报告：遗留问题复核与基线检查（v0.1.2）

## 一、报告信息

| 项目 | 内容 |
|---|---|
| 版本 | v0.1.2（维护与体验优化版本） |
| 阶段 | 阶段一：检查遗留问题与当前基线（任务书 \`dev_guide/0.1.2_.md\` §一） |
| 日期 | 2026-10-17 |
| 基线版本 | v0.1.1（\`python -c "import app; print(app.__version__)"\` → \`0.1.1\`） |
| 基线提交 | \`252d799fd3fbb43e60cd80330a7541b0c870e46f\`（\`252d799 阶段 06（v0.1.1）：回归、真实桌面 CU 验收与交付\`），分支 \`master\` |
| 验证方式 | ① 自动化：\`python scripts/test.py -v\` 四层；② 真实桌面 CU：Edge 无痕窗（pid 4012、window_id 1444516）打开 \`http://127.0.0.1:8790/\`，后端为改造后的 AWFM；③ 真实目标机：CentOS Stream 10（192.168.170.128）与 WSL 集成测试床（127.0.0.1:2222） |
| 结论 | 六项遗留全部复核完毕；确认并修复两个高优先级缺陷 D1、D2，各补回归测试；四层 744 项全绿（0 失败 / 0 错误 / 0 跳过）。允许进入阶段二 |

---

## 二、阶段目标

任务书 §一 要求本阶段只做三件事，不做新功能：

1. **1.1 检查项目状态** —— 在动手前把仓库真实状态（顶层结构、脚本、发行包、测试基线）核清楚，避免在不知情的前提下改动。
2. **1.2 遗留事项分类** —— 把 v0.1.1 留下的六项遗留逐项复核，分类为「已确认缺陷 / 未验证风险 / 已知限制 / 体验改进」，每项都要有可核实的结论而不是推测。
3. **1.3 修复门槛** —— 先修完全部已确认的高优先级缺陷并为每个缺陷补回归测试，才允许进入体验优化；**不得删测试、弱化断言或跳过失败项来制造全绿**。

六项遗留：① VM 运行中但 SSH 不可达；② IP 变化 / 重复发现 / 扫描取消；③ 接近编辑器上限的大文件；④ 非 UTF-8 文件提示；⑤ 被动掉线；⑥ 发行包在独立目录启动。

---

## 三、实际完成情况

### 3.1 项目状态检查（1.1）

| 检查项 | 结果 |
|---|---|
| 仓库顶层 | \`.archive .git .temp app config data dev_guide dist docs frontend logs scripts tests\` + \`.gitattributes .gitignore AGENTS.md LICENSE README.md\`，无散件、无根级规划文档 |
| 启动/构建脚本 | \`scripts/\` = \`build.py package.py start.py test.py testbed_wsl.sh _index.md\`；**没有 stop 脚本**，发行包里的 \`stop.cmd\` 由 \`scripts/package.py\` 生成 |
| 版本与发行包 | \`dist/\` 含 \`AWFM-0.1.0-windows-x64\`、\`AWFM-0.1.1-windows-x64\` 两个目录与压缩包 + \`SHA256SUMS.txt\` |
| 校验和复核 | \`AWFM-0.1.1-windows-x64.zip\` = \`13fdd5e616ab1f775acccfebeb893224a901058dddc1833a39841a30095e7350\`（与 \`SHA256SUMS.txt\` 一致）；\`AWFM-0.1.0-windows-x64.zip\` = \`f65d64287e45092d94b36af42c483868c4f8404187a0c6d2a9a091fc795b2ccc\` |
| 用户既有未提交改动 | \`0.md\` \`1.md\` \`2.md\` 的暂存删除（-823 行）与未跟踪的 \`dev_guide/\` —— **本阶段全程未触碰**（任务书 §7.2「不覆盖未提交修改」） |
| 测试基线 | 阶段一开工前与收尾各跑一次 \`python scripts/test.py -v\`；收尾结果见 §五 |

### 3.2 六项遗留逐项复核（1.2）

| 编号 | 遗留项 | 分类结论 | 复核方式（真实证据） | 处理结果 |
|---|---|---|---|---|
| ① | VM 运行中但 SSH 不可达 | 未验证风险 → **已消除** | \`vmrun -T ws pause "E:/Virtual Machines/Ubuntu x64/Ubuntu x64.vmx"\`，\`vmrun list\` 仍显示 Total running VMs: 2，而 192.168.170.129:22 探测不通；随后在界面点「扫描」→「开始扫描」 | **通过**：结果表该行显示「运行中 · 来源：vmrun」「探测无响应 探测没连上 SSH，也可以新建连接再试一次。」并提供「创建连接」按钮；汇总「虚拟机 3 台（运行中 2） · 探测 3/3 个地址，其中 1 个能连 SSH · 用时 6.5 秒」（截图 \`90-discovery-result.png\`） |
| ② | IP 变化 / 重复发现 / 扫描取消 | **部分消除** | 扫描进行中点「中止」；旧租约线索；一次扫描多条同 IP 未遇到 | **通过（取消）**：界面「已中止」+「探测 0/3 个地址…用时 4.7 秒」+「扫描已中止，下面是中止前已经拿到的部分。」（截图 \`91-scan-aborted.png\`）。旧租约线索真实出现：「租约地址 192.168.170.130 已过期，只能当作线索。」。**剩余**：重复发现与扫描期间 IP 变化未能在真机复现 → 记入 §6.3 |
| ③ | 接近编辑器上限的大文件 | **已确认缺陷 D1（高优先级）** | 真实界面打开 1.9 MiB 文件 → 改 → 保存；集成回归 \`tests/integration/test_edit_api.py:378\` | **缺陷确认并修复**（两层根因，见 §4.1 / §4.2）；真实界面复验通过（§5.4） |
| ④ | 非 UTF-8 文件提示 | 未验证风险 → **已消除** | 真实界面点 \`gbk-encoded.txt\`（GBK，58 B）的「编辑」 | **通过**：提示为「这个文件无法在线编辑：这个文件的编码不是 UTF-8，无法安全地在线上编辑。」（截图 \`77-gbk-edit-click.png\`） |
| ⑤ | 被动掉线 | **已确认缺陷 D2（高优先级）**：检测合格、恢复路径不合格 | 在 CentOS 上 \`pkill -f sftp-server\` 杀掉 AWFM 的 SFTP 子进程，再点界面「刷新」 | **检测通过，恢复路径缺陷确认并修复**（见 §4.3）；真实界面复验通过（§5.4） |
| ⑥ | 发行包在独立目录启动 | 未验证风险 → **部分消除** | 把 \`dist/AWFM-0.1.1-windows-x64.zip\` 解到含空格的独立目录 \`.temp/pkg-check/独立 目录/\`，用 \`cmd start.cmd --port 8799\` 启动 | **通过（同机）**：\`GET /api/health\` 200 \`{"ok": true, "data": {"status": "ok", "version": "0.1.1", "connections": 0}}\`，\`logs/awfm.log\` 有「AWFM 0.1.1 已启动：http://127.0.0.1:8799/」与「主机密钥策略 strict」。**局限**：没有第二台无依赖的干净机器 → 记入 §6.3 |

### 3.3 修复门槛执行情况（1.3）

- 两个「已确认缺陷」都**先修后进入体验优化**：D1（两层：HTTP 传输上限不一致 + SFTP 单帧超限）、D2（被动掉线后无法恢复）。
- 每个缺陷都补了回归测试，共 **25 项**新用例（清单见 §4.4）；**没有删除任何测试、没有弱化任何断言、没有跳过任何失败项**。
- 其余四项属未验证风险 / 已知限制，逐项给出复核结论与剩余风险，不做「假装通过」的处理。
- 阶段二起的体验改进（文件列表布局、右键菜单、启动脚本、教程）在本阶段**未动**，符合任务书 §0「禁止先开发新功能、最后才处理遗留问题」。

---

## 四、技术实现

### 4.1 D1 第一层：HTTP 请求体上限与「可编辑大小」不一致

**根因**

- \`app/api/request.py:24\` \`MAX_JSON_BODY = 1024 * 1024\`（1 MiB）是写死的传输层上限。
- 「能打开多大文件」用的是 \`app/core/config.py:61\` / \`:145\` 的 \`max_edit_bytes\`，默认 \`2097152\`（2 MiB），\`:405-407\` 允许 \`security.max_edit_bytes\` 取 1024 ~ 64 MiB。
- 两者不一致 → **1 MiB ~ 2 MiB 的文件「打得开、存不回去」**：保存时服务端在读 body 之前就回 413，\`app/api/http_server.py\` 的 \`finally\` 分支发现 body 没读完便直接关连接，浏览器上传还没结束就断，前端只看到「保存失败：Failed to fetch 内容还在编辑器里，可以重试或先复制出去。」（文案见 \`frontend/assets/js/edit.js:277\`、\`:291-298\`）

**修法**

| 位置 | 改动 |
|---|---|
| \`app/api/request.py:34\` | 新增 \`def text_body_limit(max_edit_bytes: int) -> int:\`，把「文本保存」的传输上限与编辑器上限对齐，并保留 \`JSON_TEXT_SLACK\` 余量；下限不低于 \`MAX_JSON_BODY\` |
| \`app/api/request.py:136\` | \`def json(self, *, max_bytes: int | None = None)\`：不传参时仍是 1 MiB 通用上限，只有明确知道自己在收文本的路径才放宽 |
| \`app/api/request.py:114\` | 新增 \`def discard(self, limit: int) -> bool:\`：按上限排空（或拒绝排空）请求体，返回值表示「读完了 / 没读完」 |
| \`app/api/http_server.py:217\` | 新增 \`_discard_request_body(self, req)\`：回错误响应前先把 body 排空，避免「错误响应还没送达连接就被关掉」 |
| \`app/api/http_server.py:230\` | \`sock.settimeout(DRAIN_TIMEOUT_SECONDS)\`（\`:68\` \`DRAIN_TIMEOUT_SECONDS = 5.0\`），排空不允许无限期挂住连接 |
| \`app/api/http_server.py:244\` | \`_dispatch_api\` 里对 \`PUT …/text\` 用 \`text_body_limit(max_edit_bytes)\`，其余接口继续用通用上限 |

### 4.2 D1 第二层：单次 SFTP WRITE 超过服务端整包上限，连接被掐断

**现象**：第一层修好后，集成回归 \`tests/integration/test_edit_api.py:378\`（上传 1,900,001 字节 → 编辑 → 保存）拿到 \`409 not_connected\`「写入远端失败：与远端的连接已断开。」，同一会话后续请求全部 \`404 session_not_found\`，整个 \`EditApiTests\` 类连带失败。

**根因（实测确认）**

- OpenSSH 的 \`sftp-server\` 用 \`SFTP_MAX_MSG_LENGTH\`（256 KiB）限制**整包**长度（长度字段 = 类型 + request-id + 负载），超限就打印 bad message 并**结束连接**；客户端收不到任何 \`STATUS\`，只看到管道断开 → 本项目表现为 \`NotConnected\`。
- 边界实测（WSL 测试床 OpenSSH_9.6p1 Ubuntu-3ubuntu13.20）：一次 WRITE 携带 **261120 字节成功、262144 字节即断连**。既有的 \`MAX_FRAME_BYTES\`（4 MiB）只管**入站**帧，管不到这个上限。
- 触发点：\`app/services/editor.py:342\` \`written = client.upload_stream(temp, [data], expected_size=len(data), mode=mode)\` —— 把在线编辑的整份文本当**一个**块写出去，所以 256 KiB 以上的文件「能打开、保存必失败」。
- 其它写入路径审计：\`app/services/transfer.py\` 的上传走 \`_read_exact(rfile, content_length)\`（默认 65536 一块），本就安全；\`app/ssh/sftp_client.py\` 的 \`ChunkWriter.write\`（压缩打包路径）经 \`write_chunk\`，被下面的修复一并覆盖。

**修法**

| 位置 | 改动 |
|---|---|
| \`app/ssh/sftp_protocol.py:137\` | \`OPENSSH_MAX_PACKET_BYTES = 256 * 1024\`：记录「这是服务端实现行为，不是协议」，并写入实测边界 |
| \`app/ssh/sftp_protocol.py:143\` | \`MAX_WRITE_CHUNK = 64 * 1024\`：与读取块（D-007）一致，给帧头留余量 |
| \`app/ssh/sftp_client.py:179\` | \`def write_chunk(self, handle: bytes, offset: int, data: bytes) -> None:\` 改为**自动拆帧**：\`while sent < len(view)\` 逐块 \`transact(SSH_FXP_WRITE, encode_string(handle) + encode_uint64(offset + sent) + encode_string(piece), …)\`。选这里是因为它是所有写入路径的唯一收口（\`upload_stream\`、\`ChunkWriter\`） |
| \`docs/DECISIONS.md\` | 新增 **D-019**「单次 SFTP WRITE = 最多 64 KiB，超过就拆帧」，含备选方案（只让调用方分块 / 在 \`transact\` 里拒绝超长帧）与代价（1.9 MiB 从 1 帧变 30 帧，实测仍在 1 秒量级） |
| \`docs/SECURITY.md\` | 资源上限表增加「单次 WRITE 帧」一行 |
| \`docs/ARCHITECTURE.md\` | 决策表增加 D-019 行 |

### 4.3 D2：被动掉线后「重试」是死路、卡片状态不跟随

**根因**：传输层抛出的 \`NotConnected\` 只作为**本次请求**的错误返回，没有任何地方把会话标死 → ① 侧栏卡片仍显示绿色「已连接」；② 横幅按钮是「重试」，点下去只是对着同一个已死会话重发请求（CentOS 上也没有新的 \`sftp-server\` 进程），界面永远停在「19 项（已过期）」。

**修法**

| 位置 | 改动 |
|---|---|
| \`app/services/session.py:339\` | 新增 \`def mark_broken(self, message: str) -> dict:\`：状态转 \`error\`、保留 \`last_error\`、之后 \`session.client\` 抛 \`NotConnected\`（HTTP 409，带 \`connection_id\`），\`disconnect()\` 仍能清空 |
| \`app/services/connection_manager.py:285\` | 新增 \`def mark_broken(self, connection_id: str \| None, error: AwfmError) -> None:\`：把会话状态同步进连接列表（未知 / 空 id 忽略） |
| \`app/api/http_server.py:261\` | \`except NotConnected as exc:\` 统一收口 —— 请求因通道断开失败时把该会话标死并回 \`not_connected\`（409） |
| \`frontend/assets/js/files.js:57\` \`:62\` \`:66\` | \`isLostCode(code)\` / \`connectionLost()\`：识别「连接丢了」这一类错误 |
| \`frontend/assets/js/files.js:76\` | \`retryLoad()\`：连接已丢时走重连而不是原地重发 |
| \`frontend/assets/js/files.js:150\` | 列表加载失败且属掉线类错误时回调 \`deps.onConnectionLost(error)\` |
| \`frontend/assets/js/files.js:276-279\` | 横幅按钮文案：\`retry.textContent = connectionLost() ? "重新连接" : "重试"\` |
| \`frontend/assets/js/app.js:42\` | \`const broken = Boolean(conn && !connected && (conn.session \|\| {}).state === "error");\` —— 工具栏与卡片按真实会话状态渲染 |
| \`frontend/assets/js/app.js:276\` \`:279\` | 接线 \`onReconnect(connectionId, path)\` / \`onConnectionLost()\`：重连成功后回到原目录 |
| \`frontend/assets/js/connections.js:204\` \`:252\` \`:263\` | \`openConnection(id, options)\` / \`connectFlow\` / \`doConnect\` 支持带 \`path\` 重连（\`options.path\`） |

### 4.4 新增回归测试（25 项）

| 文件 | 新增 | 用例 |
|---|---|---|
| \`tests/unit/test_request.py\`（现 32 项） | 10 | \`TextBodyLimitTests\` 3（默认编辑上限给足余量 / 1.9 MiB 正文可解析 / 不小于通用上限）、\`JsonLimitTests\` 3（不传参仍按 1 MiB / 自定义上限可收 / 自定义上限被强制执行且 detail 含「上限 100 字节」）、\`DiscardTests\` 4（空体无事 / 限内读完 / 超限一个字节都不读 / 截断报失败） |
| \`tests/unit/test_broken_session.py\`（**新文件**，7 项） | 7 | \`SessionMarkBrokenTests\`（状态与 \`last_error\`、第一次原因胜出、\`client\` 抛 409 + \`connection_id\`、\`disconnect()\` 清空）、\`ManagerMarkBrokenTests\`（\`session_status\`/\`list_connections\` 同步、未知 / 空 id 忽略、标记后取会话抛 404） |
| \`tests/unit/test_sftp_client.py\`（**新文件**，5 项） | 5 | 小写入单帧且偏移保留 / 空写入不发帧 / 大写入按 64 KiB 拆帧且偏移正确 / 每帧含帧头仍小于 256 KiB / **实测失败尺寸 262144 字节不再写死连接** |
| \`tests/integration/test_connection_flow.py\`（现 10 项） | 2 | \`:151\` \`class BrokenChannelTests\`：\`:187\` 杀掉通道后请求 409 \`not_connected\`、\`/status\` 与 \`/api/connections\` 里 \`state=error\`、\`POST /connect\` 可恢复；\`:213\` 通道丢失后第二次请求被拒（404）而不是重试 |
| \`tests/integration/test_edit_api.py\`（现 32 项） | 1 | \`:378\` \`test_file_between_the_transport_ceiling_and_the_edit_limit_saves\`：1,900,001 字节（> 1 MiB 且 < 2 MiB）上传 → 编辑 → 保存成功，同时压住 D1 的两层 |

---

## 五、测试结果

### 5.1 全量四层（\`python scripts/test.py -v\`，日志 \`.temp/full-test-v012.log\`）

| 层 | 用例 | 失败 | 错误 | 跳过 | 用时 | 结果 |
|---|---|---|---|---|---|---|
| unit | 527 | 0 | 0 | 0 | 3.94 s | OK（\`Ran 527 tests in 3.943s\`） |
| integration | 111 | 0 | 0 | 0 | 219.38 s | OK（\`Ran 111 tests in 219.383s\`） |
| security | 82 | 0 | 0 | 0 | 469.33 s | OK（\`Ran 82 tests in 469.331s\`） |
| e2e | 24 | 0 | 0 | 0 | 165.38 s | OK（\`Ran 24 tests in 165.379s\`） |
| **合计** | **744** | **0** | **0** | **0** | **858.04 s** | **全部通过** |

e2e 层证据截图：\`tests/e2e/artifacts/browser-journey-e0d2f46e.png\`。

### 5.2 针对缺陷的定向验证

| 命令 / 场景 | 结果 |
|---|---|
| \`python -m unittest tests.unit.test_request tests.unit.test_broken_session -v\` | Ran 39 tests … OK |
| \`python -m unittest tests.unit.test_sftp_client -v\` | Ran 5 tests … OK |
| \`python -m unittest tests.integration.test_edit_api -v\` | **修复前**：14 失败 + 1 错误（首个失败即 409 vs 200）→ **修复后**：Ran 32 tests in 81.525 s，OK |
| 探针 \`.temp/probe_big_save.py\`（分块写 + 单帧尺寸扫描） | **修复前** 65536 / 131072 / 204800 / 261120 OK，**262144 起全部 FAIL \`NotConnected\`**（1048576 时 ssh 子进程已退出）；**修复后** 65536 … 1048576 … **1900000 全部 OK** |

### 5.3 真实桌面 CU 复验（D1 / D2）

| 步骤 | 观察到的真实界面 |
|---|---|
| D1-1 重载页面 → 点卡片「连接」→ 双击 \`cu-v012\` → 点 \`big-1.9MiB.txt\` 的「编辑」 | 编辑器：\`/home/aimu/cu-v012/big-1.9MiB.txt\`、「1.8 MiB（上限 2.0 MiB）」「utf-8」「LF（Unix 换行）；末尾没有换行」「1900000 个字符 · 约 1.8 MiB」「与打开时一致」，保存按钮为禁用（不在 a11y 树里） |
| D1-2 正文 \`Ctrl+End\` → 输入 \`ZZ-D1FIX-END\` | 「1900012 个字符 · 约 1.8 MiB」「已修改，尚未保存」，「保存」按钮出现 |
| D1-3 点「保存」 | 对话框正常关闭、**无「保存失败」提示**，列表自动刷新，修改时间由 00:50 变 **01:36**；远端独立核对 \`stat -c %s\` = **1900012**、末尾 20 字节 \`FM v0.1.ZZ-D1FIX-END\` |
| D2-1 CentOS 上 \`pkill -f sftp-server\` → 点工具栏「刷新」 | 卡片变「**连接失败**」+ 原因行「写入远端失败：连接已断开。」+ 按钮变回「连接」；主区横幅「写入远端失败：连接已断开。（[Errno 22] Invalid argument; ssh 退出码=4294967295）」与「这份列表可能已经过期：最近一次加载失败 —— …」；计数「5 项（已过期）」；**横幅按钮文案「重新连接」** |
| D2-2 点「重新连接」 | 6 秒后卡片回到「已连接」，面包屑仍在 \`/ › home › aimu › cu-v012\`，列表恢复 **5 项（不再标记已过期）**，无错误横幅 |

截图（\`.temp/cu-v012/\`）：\`92-d1-editor-open.png\`、\`93-d1-editor-dirty.png\`、\`94-d1-saved.png\`、\`95-d2-detected.png\`、\`96-d2-recovered.png\`；遗留项复核另有 \`77\`、\`78\`~\`91\` 号截图。

---

## 六、问题与风险

### 6.1 本阶段新发现并已修复

1. **D1 第一层**（HTTP 1 MiB 硬上限 vs 编辑器 2 MiB 上限）——「能打开、存不回去」，且错误被 \`Failed to fetch\` 掩盖。
2. **D1 第二层**（单次 WRITE 整包 > 256 KiB 被 \`sftp-server\` 掐断连接）——这是**遗留项③真正的根因**；它的危险之处在于表现成「网络断了」而不是「参数超限」，因此已固化为决策 **D-019**（含实测边界 261120 / 262144）。
3. **D2**（被动掉线后无恢复路径、卡片状态不跟随）——检测侧本来是对的，问题在恢复侧。

### 6.2 \`docs/reports/PHASE-06-CU-ACCEPTANCE.md\` §5「已知限制与未验证项」的逐条复核结论

| 序号 | v0.1.1 原文要点 | 本阶段结论 |
|---|---|---|
| ① | 发现功能「运行但 SSH 不可达」「扫描期间 IP 变化」「扫描失败」当时只有模拟覆盖 | **部分消除**：真实制造了「VM 运行中 + SSH 不可达」（vmrun pause）并在界面验证；（扫描失败 / IP 变化）仍未见真机样本 |
| ② | 非 VMware 平台发现未验证 | **仍未验证**（本机只有 VMware Workstation 26） |
| ③ | 多台虚拟机同时在线、一次扫描出现多条同 IP 未遇到 | **仍未遇到**（本次扫描为 3 台虚拟机，无重复 IP） |
| ④ | 断线恢复只测了「主动断开 → 重连」，被动掉线未在真机制造 | **已消除**：真机 \`pkill -f sftp-server\` 制造被动掉线，并修好恢复路径（D2），真实界面复验通过 |
| ⑤ | 接近 2 MiB 上限的大文件编辑与保存未在真机跑 | **已消除**：1.9 MiB 真机编辑并保存成功（1900000 → 1900012 字节，远端核对一致） |
| ⑥ | 非 UTF-8 文件被拒的提示未截图 | **已消除**：真实界面提示已截图（\`77-gbk-edit-click.png\`） |

### 6.3 剩余风险与已知限制

1. **没有第二台无依赖的干净机器**：遗留⑥的「独立目录 + 含空格路径」只能同机验证（同一台 Windows、同一套 Python/OpenSSH）。
2. **非 VMware 平台（VirtualBox / Hyper-V / KVM）的发现能力仍未验证**。
3. **一次扫描出现多条同 IP、扫描期间 IP 变化**仍无真机样本；租约过期线索（「192.168.170.130 已过期，只能当作线索。」）已在真实数据中出现。
4. **CU 输入由驱动投递**（\`delivery_mode:"foreground"\` 的全局输入），不是人手操作；页面级交互（键盘、鼠标轨迹）与人手仍有差异，但界面反馈、日志与远端文件内容都已独立核对。
5. v0.1.1 §5.3 记录的「点结果区『搜索』按钮偶发不触发，改回车必定触发」在本阶段多轮复验中**未再复现**，暂不作为缺陷跟踪。

### 6.4 与后续阶段的关系

阶段二~七（文件列表布局与右键菜单、统一启动脚本、SSH 教程、回归与安全检查、真实桌面 CU 验收、版本与交付）在本阶段未动，全部留给后续阶段执行。

---

## 七、文档与交付物

| 类别 | 内容 |
|---|---|
| 新增报告 | \`docs/reports/PHASE-01-LEGACY-v012.md\`（本文件）；\`docs/reports/_index.md\` 增加本报告一行，并补一句「v0.1.2 的报告统一加 \`-v012\` 后缀」的命名约定 |
| 设计文档 | \`docs/DECISIONS.md\`（新增 D-019）、\`docs/ARCHITECTURE.md\`（决策表 D-019 行）、\`docs/SECURITY.md\`（资源上限表新增「单次 WRITE 帧」） |
| 代码 | \`app/api/request.py\`、\`app/api/http_server.py\`、\`app/api/handlers.py\`、\`app/services/session.py\`、\`app/services/connection_manager.py\`、\`app/ssh/sftp_client.py\`、\`app/ssh/sftp_protocol.py\`、\`frontend/assets/js/app.js\`、\`frontend/assets/js/connections.js\`、\`frontend/assets/js/files.js\` |
| 测试 | \`tests/unit/test_request.py\`、\`tests/unit/test_broken_session.py\`（新）、\`tests/unit/test_sftp_client.py\`（新）、\`tests/integration/test_connection_flow.py\`、\`tests/integration/test_edit_api.py\` |
| 证据（会话中转，可清空） | \`.temp/cu-v012/\` 截图与配置（\`config.json\`、\`known_hosts\`）、\`.temp/probe_big_save.py\`、\`.temp/probe_big_save*.log\`、\`.temp/full-test-v012.log\`、\`.temp/it-edit.log\` |
| 改动规模 | \`git diff --stat\`：19 files changed, 459 insertions(+), 856 deletions(-)（其中 -823 行为用户既有的 \`0.md\`/\`1.md\`/\`2.md\` 暂存删除，与本阶段无关） |
| 提交 | 阶段一独立提交 `24fd0b2`（2026-10-17，「阶段 01（v0.1.2）：遗留问题复核、D1/D2 缺陷修复与回归」，20 个文件 / +889 −33）；用户的 `0.md`/`1.md`/`2.md` 暂存删除与未跟踪的 `dev_guide/` **未被该提交包含**，原样留在工作区 |

---

## 八、阶段结论

阶段一的三项要求全部完成，且满足进入下一阶段的门槛：

1. **项目状态已核清**并留档（顶层结构、脚本清单、发行包校验和、用户既有未提交改动、测试基线）。
2. **六项遗留全部复核**，逐项给出「已确认缺陷 / 未验证风险 / 已知限制」分类与真实证据；其中 ③（D1）与 ⑤（D2）升级为高优先级缺陷。
3. **修复门槛已满足**：D1、D2 均先修后优化，各带回归测试（新增 25 项），全量四层 **744 项 0 失败 / 0 错误 / 0 跳过**，并在真实桌面 CU 上对两个缺陷做了端到端复验。
4. 遗留项 ①④⑥ 复核通过（⑥为同机部分验证），②部分通过；剩余未验证项与非 VMware 平台限制已如实登记在 §6.3。

**允许进入阶段二：文件列表布局优化与自定义右键菜单。**
