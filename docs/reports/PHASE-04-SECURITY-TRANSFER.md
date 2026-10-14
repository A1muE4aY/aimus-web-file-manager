# 阶段 04 开发报告：安全控制与文件传输

## 1. 报告信息

| 项目 | 内容 |
|---|---|
| 项目版本 | v0.1.0（开发中） |
| 报告日期 | 2026-10-15 |
| 开发阶段 | 阶段 04 —— 安全控制与文件传输（规划文档 §6.1 第四阶段） |
| 对应 Git 提交或标签 | 无独立提交。阶段 03/04 的产物与阶段 05/06 一并提交；此前的可核实基线是提交 `d2f94e0` |

## 2. 阶段目标

**计划完成事项**

1. 落实规划文档 §10 的七条安全要求：主机密钥验证、密钥与凭据保护、默认只监听回环、
   路径校验、请求保护、日志脱敏、传输限制。
2. 交付上传与下载（含 P0 的目录浏览之外的传输能力），并给出大小、并发、超时、临时文件的限制。
3. 完成主机密钥的**两阶段确认**（未知 → 展示指纹 → 用户确认 → 写入项目自有的信任库）。
4. 产出安全设计与威胁模型文档（`docs/SECURITY.md`）。

**验收标准**

- 浏览器端**不接触任何私钥**；密码不进配置文件、不进日志、不进命令行参数。
- 所有 `/api/` 请求（除健康检查）都必须带会话令牌；跨站来源一律拒绝。
- 主机密钥策略默认 `strict`：首次连接必须显式确认指纹，指纹变化必须报警而不是静默接受。
- 远程路径全部经校验（绝对路径、无 NUL、长度上限），不产生 500。
- 上传/下载按块流式转发，不把整份文件读进内存。

## 3. 实际完成情况

**已完成**

- 请求保护三重校验 + 会话令牌 + Host 头白名单 + `OPTIONS` 一律拒绝（`app/api/security.py`）。
- 下载票据机制（`app/api/tickets.py`）：随机、绑定连接与路径、默认 120 秒、内存态、上限 256 张。
- 主机密钥采集、指纹计算与信任库（`app/ssh/known_hosts.py`）；`UserKnownHostsFile` 与
  `GlobalKnownHostsFile` **同时**指向项目自有文件（`app/ssh/ssh_launcher.py`）。
- 路径校验与规范化（`app/utils/paths.py`）：必须绝对路径、拒绝 NUL、路径 4096 字节上限、名称 255 字节上限。
- 日志脱敏（`app/utils/redact.py`）：在格式化阶段统一处理，覆盖 PEM 私钥块、`-i <私钥路径>`、
  `password=`/`token=`/`secret=` 等键值。
- 传输（`app/services/transfer.py` + `app/ssh/sftp_client.py`）：64 KiB 块流式；上传走「临时名 + 改名」。
- 密码认证通道（`app/ssh/askpass.py` + `app/ssh/ssh_launcher.py`）：一次性秘密文件（`0o600`）+ 包装脚本，
  `SSH_ASKPASS_REQUIRE=force`，认证结束立即销毁；**密码不持久化**（决策 D-014）。
- 写操作受连接级 `allow_write` 开关约束（`app/services/filesystem.py:179`）。
- `docs/SECURITY.md`（威胁模型、七条要求逐条落实、残余风险、明确不做的事）。

**部分完成**

- 并发限制有配置项（`ssh.max_sessions`）与校验，但没有专门的并发压力测试（见本报告 §5 与 §8）。
- 只读浏览之外的写操作**只暴露了上传**；创建目录 / 重命名 / 删除在连接层已实现且实测通过，
  但按规划文档 §3.1 属 P2，未注册进 HTTP 端点（`docs/API.md` §7.2）。

**未完成及原因**

- 真实 CentOS 目标机的安全路径复验：本机无该虚拟机环境，安全用例跑在本机临时 HTTP 服务与
  WSL 测试床上（决策 D-012）。

## 4. 技术实现

**修改/新增的模块**

| 方向 | 模块 | 关键实现 |
|---|---|---|
| 请求保护 | `app/api/security.py` | 令牌 `secrets.compare_digest` 比较；`OPEN_PATHS` 只放 `GET /api/health`；`ALLOWED_HOSTS` 只收字面量 `127.0.0.1`/`localhost`/`[::1]`；`Sec-Fetch-Site` 只允许 `none`/`same-origin`；带 `Origin` 时必须回环 |
| 传输票据 | `app/api/tickets.py` | `DEFAULT_TTL = 120.0`、`MAX_TICKETS = 256`；票据绑定连接 id 与路径，换路径即 401 |
| 主机密钥 | `app/ssh/known_hosts.py`、`app/ssh/ssh_launcher.py` | 采集：临时 `UserKnownHostsFile` + `StrictHostKeyChecking=no` **只用于取回密钥**（`known_hosts.py:221`），随后由项目策略判定；连接期策略名映射 `{"strict": "yes", "accept-new": "accept-new"}` |
| 密码通道 | `app/ssh/askpass.py` | 秘密文件 `os.chmod(secret_path, 0o600)`（`askpass.py:122`）；包装脚本导出环境变量后删除自身；`SSH_ASKPASS_REQUIRE=force`（`ssh_launcher.py:177`）；密钥路径下清理 `SSH_ASKPASS`（`ssh_launcher.py:184-185`） |
| 路径校验 | `app/utils/paths.py` | 必须绝对路径；`MAX_PATH_BYTES = 4096`；`MAX_NAME_BYTES = 255`；相对路径直接 400 |
| 日志 | `app/utils/redact.py`、`app/utils/logging_setup.py` | 格式化阶段脱敏，占位符 `***已脱敏***`；日志轮转 `MAX_BYTES = 2 MiB` |
| 传输 | `app/services/transfer.py`、`app/ssh/sftp_client.py` | `DEFAULT_CHUNK_SIZE = 64 * 1024`；上传预检 `declared` 长度与 `max_upload_bytes`（`transfer.py:136`）、下载预检文件大小与 `max_download_bytes`（`transfer.py:71`）；上传「临时名 + 改名」（`transfer.py:9-18`） |
| 边界限制 | `app/api/request.py`、`app/api/responses.py`、`app/services/filesystem.py`、`app/ssh/sftp_protocol.py` | 请求体 `MAX_JSON_BODY = 1 MiB`；响应 `MAX_JSON_BYTES = 8 MiB`；目录列举 `MAX_LIST_ENTRIES = 5000`（超出置 `truncated`）；SFTP `MAX_READ_CHUNK = 64 KiB`、`MAX_FRAME_BYTES = 4 MiB` |

**与原设计的差异**

- 原计划（D-004）用 `sftp` 批处理 + 文本解析，阶段 02 的 SPIKE 用实测输出推翻，改自实现 SFTP v3（D-011）。
  对安全侧的直接影响是：权限位、`uid`/`gid`、字节大小、时间戳都来自二进制协议帧而不是人类可读文本，
  文本解析被伪造/歧义的风险一并消失。
- 下载票据**刻意不做成一次性**：用户在「另存为」对话框里取消后重试不该看到「票据失效」。
  代价是同一张票据在 120 秒内可被重复使用，安全性由「绑定连接 + 绑定路径 + 短有效期 + 内存态」共同保证。

## 5. 测试结果

| 项目 | 内容 |
|---|---|
| 测试环境 | Windows 11 家庭版 26300 / Python 3.12.10 / OpenSSH_for_Windows 9.5p2 / WSL Ubuntu 24.04.2 非 root `sshd`（`127.0.0.1:2222`） |
| 执行命令 | `python scripts/test.py`（四层）；`python scripts/build.py`（八项静态校验） |
| 测试总数 | 安全层 **38 项**；相关单元层模块（`test_api_security` 等）与集成层 18 项同批执行；全部四层合计 363 项 |
| 通过 / 失败 / 错误 / 未执行 | 363 通过 / 0 失败 / 0 错误 / 0 跳过 |
| 关键测试证据 | `tests/security/test_web_security.py`（18 个端点无令牌一律 401；Host 头与跨站来源拒绝；静态资源穿越清单；响应头策略；离线扫描）、`test_credentials.py`（哨兵密码不出现在落盘配置、8 个 GET 端点响应、`argv`、日志与浏览器存储；`AskpassBundle` 的秘密文件内容与 `env`）、`test_path_traversal.py`、`test_host_key.py` |

**如实说明**：`tests/security/` 的 38 项用例是在**阶段 05/06 的安全加固**中建立的，不是阶段 04 当时的产物——
阶段 04 当时的验证手段是单元层与集成层。按「测试计划要求每条验收项至少一条用例」的口径，
这里给出的是**当前仓库状态**下这些安全要求的证据，而不是阶段 04 结束时刻的快照。
四个安全验收项的逐条结论见 `docs/TEST_REPORT.md` §4（T-005、T-008、T-011 等）。

## 6. 问题与风险

**发现的问题与修复方式**（阶段 03/04 期间，均已在代码中留痕）

| # | 问题 | 修复 |
|---|---|---|
| 1 | `StrictHostKeyChecking` 收到内部策略名 `strict` 导致 ssh 在**参数解析阶段**就退出（`command-line line 0: unsupported option "strict"`），现象是「连不上」，根因埋在参数拼装里 | 显式映射表 `{"strict": "yes", "accept-new": "accept-new"}`（`app/ssh/ssh_launcher.py:46-53`，使用处 `:128`） |
| 2 | 中文连接名生成的 id 含非 ASCII 字符（`"临".isalnum()` 为真）后被自家校验拒绝 | 先做 ASCII 归一化再过滤，派生不出 ASCII 时回退 `conn`，显示名不受影响（`app/services/connection_manager.py:181-195`） |
| 3 | SFTP 成功响应的 `STATUS` 码 `0` 被当作错误抛出（远端返回 `OK：Success` 却报错） | 只以 `STATUS` 回话的请求（`WRITE`/`CLOSE`/`MKDIR`/`RMDIR`/`REMOVE`/`RENAME`）显式带 `_OK = (proto.SSH_FX_OK,)`（`app/ssh/sftp_client.py:30-34` 及各调用点） |
| 4 | 响应包漏读「请求 id」字段导致后续解析全部错位；`MKDIR`/`SETSTAT` 的属性字段编码错误会让 `sftp-server` 直接 `fatal()` | 两者都用单元测试钉死（`tests/unit/test_sftp_protocol.py`） |
| 5 | Windows 控制台默认 GBK，打印 emoji 文件名直接 `UnicodeEncodeError` 并终止程序 | 启动强制 UTF-8（决策 D-013） |

**尚存风险**（详见 `docs/SECURITY.md` §5）

- 密码认证依赖 `SSH_ASKPASS`，密码在极短时间内存在于一次性文件与辅助进程内存中；
  本机其他进程若能读该临时目录仍有可能截获——因此**优先引导密钥认证**。
- 服务只监听回环**不是**安全边界：本机其他用户/进程仍可能访问，令牌是这一层的实际防线。
- 非 root `sshd` 测试床读不到 `/etc/shadow`，密码认证在测试床上**永远不可能成功**，
  已验证的是「密码确实送达服务端」而不是「认证成功后的行为」。
- 覆盖上传中断会在目标路径留下被截断的文件（SFTP v3 的 `RENAME` 不能替换已存在目标），本版明确接受。

**复现步骤**（安全问题的最小复现）

```powershell
# 无令牌访问受保护端点 → 401
curl.exe -i http://127.0.0.1:8760/api/connections
# 伪造 Host → 400
curl.exe -i -H "Host: evil.example" http://127.0.0.1:8760/api/health
# 相对路径 → 400
curl.exe -i -H "X-AWFM-Token: <token>" "http://127.0.0.1:8760/api/connections/<id>/files?path=../.."
```

## 7. 文档与交付物

- 新增文档：`docs/SECURITY.md`（威胁模型、七条要求落实、残余风险、明确不做的事、私钥权限运维）。
- 修改文档：`docs/API.md`（传输与主机密钥端点）、`docs/ARCHITECTURE.md`（安全层与传输层）、
  `docs/DECISIONS.md`（新增 D-014）。
- 新增源码：`app/api/security.py`、`app/api/tickets.py`、`app/utils/redact.py`、`app/ssh/askpass.py`。
- 构建产物：无（阶段 06 才产出便携包）。
- 依赖与运行要求：无第三方运行时依赖；需要系统 OpenSSH 客户端（含 SFTP 子系统）。

## 8. 阶段结论

- **是否达到验收条件**：达到。§10 七条要求逐条有实现与可核实的代码位置，浏览器端不接触私钥，
  密码不落盘、不进日志与命令行，主机密钥默认 `strict` 且变化时报警，路径校验不产生 500，
  传输按块流式转发。
- **是否允许进入下一阶段**：允许进入阶段 05（离线部署与兼容性验证）。
- **后续任务**：
  1. 建立 `tests/security/` 独立安全用例集（已于阶段 05/06 完成，38 项）；
  2. 在真实 CentOS 目标机上复验安全路径；
  3. 为「远程删除/覆盖/编辑」单独设计二次确认与操作记录（规划文档 §3.2）；
  4. 补并发上限的压力验证。
