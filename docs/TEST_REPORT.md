# AWFM 测试报告

- 项目版本：v0.1.0
- 报告日期：2026-10-15
- 对应测试计划：`docs/TEST_PLAN.md`（本报告是唯一结果出口，只记录**实际执行过**的东西）
- 结论一句话：**四层自动化测试合计 363 项全部通过，0 失败 0 错误 0 跳过；静态校验 8 项全过；
  便携版解压冒烟通过。** 未执行项见 §8。

## 1. 测试环境

| 项目 | 实测值 |
|---|---|
| 操作系统 | Windows 11 家庭版 26300（AMD64），当前会话**非管理员** |
| 终端 | Windows PowerShell 5.1（不是 pwsh 7）；`unittest` 的进度点会走 stderr，需 `2>&1 | Select-String` 过滤 |
| Python | 3.12.10，`E:\Software\Python 3.12\python.exe`（本机无 `python3`） |
| SSH 客户端 | OpenSSH_for_Windows 9.5p2（`ssh` / `sftp` / `scp` / `ssh-keygen` 均可用；**无 `ssh-keyscan`**） |
| 目标机测试床 | WSL Ubuntu 24.04.2 LTS 上的非 root `sshd`，监听 `127.0.0.1:2222`，用户 `aimu`，家目录 `/home/aimu` |
| 浏览器（端到端） | Microsoft Edge 155.0.4283.45（`--headless=new --inprivate`，CDP over WebSocket） |
| 网络 | 全程不需要外网 |

## 2. 测试范围与分层

| 层 | 位置 | 本次执行数 | 依赖 |
|---|---|---|---|
| 语法校验 | `python -W error::SyntaxWarning -m compileall -q app tests scripts` | 全部源文件 | 无 |
| 单元 | `tests/unit` | 304 | 无 |
| 集成 | `tests/integration` | 18 | WSL 测试床（`127.0.0.1:2222` + `data/testbed/id_ed25519`） |
| 安全 | `tests/security` | 38 | 本机临时 HTTP 服务；主机密钥用例需要 `ssh`/`ssh-keygen` |
| 端到端 | `tests/e2e` | 3 | Edge + 本机服务；其中 2 条另需测试床 |
| 静态校验 | `python scripts/build.py` | 8 项检查 | 无 |
| 打包自检 | `python scripts/package.py` | 清单逐文件 SHA-256 + 必需文件 + 冒烟 | 无 |

## 3. 执行结果

### 3.1 四层 + 语法校验（`python scripts/test.py`）

| 层 | 用例 | 失败 | 错误 | 跳过 | 耗时 | 结果 |
|---|---|---|---|---|---|---|
| unit | 304 | 0 | 0 | 0 | 2.96s | OK |
| integration | 18 | 0 | 0 | 0 | 12.28s | OK |
| security | 38 | 0 | 0 | 0 | 8.95s | OK |
| e2e | 3 | 0 | 0 | 0 | 13.49s | OK |
| **合计** | **363** | **0** | **0** | **0** | **37.69s** | **全部通过** |

语法校验：通过（`SyntaxWarning` 视为错误）。端到端证据截图：`tests/e2e/artifacts/browser-journey-ef1aeb02.png`。

### 3.2 静态校验（`python scripts/build.py`）—— 8/8 通过

| # | 检查 | 结论 |
|---|---|---|
| 1 | Python 版本 >= 3.10 | 通过（3.12.10） |
| 2 | 语法校验 | 通过 |
| 3 | 零第三方依赖（`ast` 扫描顶层导入） | 通过（`app/`、`scripts/` 只导入标准库与项目内模块） |
| 4 | 前端离线（`frontend/` 内不得有外部 URL） | 通过（唯一放行 SVG 命名空间 `http://www.w3.org/2000/svg`） |
| 5 | 凭据纪律 | 通过（放行 1 处文档示例占位符，见 §6 测试缺陷 5） |
| 6 | 错误模型回归（`app/` 不得出现 `http_status=`） | 通过 |
| 7 | 版本一致性（`app/__init__.py` 的版本出现在 `README.md` 与 `docs/CHANGELOG.md`） | 通过（0.1.0） |
| 8 | 测试包结构（四层各有 `__init__.py`） | 通过 |

### 3.3 便携版打包与冒烟（`python scripts/package.py`）

| 步骤 | 结果 |
|---|---|
| 打包前校验 | 8 项静态检查全过 |
| 打包 | `python scripts/package.py` → `dist/AWFM-0.1.0-windows-x64.zip`（82 个 zip 成员；清单 `file_count` = 81，不含 `MANIFEST.json` 自身） |
| 自检 | `testzip()` CRC 通过；包内每个文件与 `MANIFEST.json` 的 SHA-256 一致；无清单外成员；11 个必需文件齐全 |
| 校验和 | `dist/SHA256SUMS.txt`（压缩包哈希 + 清单哈希 + 校验方式） |
| 冒烟：启动 | 解压到临时目录后 `start.cmd --port 8899 --no-browser` → `GET /api/health` = **200**，`{"status":"ok","version":"0.1.0","connections":0}` |
| 冒烟：页面 | `/` = 200，4467 字节，`name="awfm-token"` 已注入真令牌（43 字符，占位符 `<!--AWFM_TOKEN-->` 已消失）；`/assets/js/api.js` = 200，6449 字节 |
| 冒烟：运行时目录 | 首次运行自动创建 `data/`（默认配置不落盘，决策 D-006）与 `logs/awfm.log`，日志首行：`2026-10-15 01:27:12 INFO    [awfm] AWFM 0.1.0 已启动：http://127.0.0.1:8899/` |
| 冒烟：停止 | `stop.cmd` 输出 `[INFO] Stopping AWFM (PID 26536, port 8899) ...` 与 `[ OK ] AWFM stopped.`，随后 `GET /api/health` 无响应，进程自行退出（未触发兜底强杀） |

> 上表是**最终包**（文档补齐后重新打包，82 个成员）上的实测；此前 67 文件版本的冒烟结论相同。
> 冒烟在项目 `.temp/pkgcheck2/` 下解压执行，未使用管理员权限，也未改动系统任何位置（§11 验收第 1 项）。

## 4. 验收项结论

| 验收项 | 结论 | 主要证据 |
|---|---|---|
| T-001 服务启动 | 通过 | 单元 `test_config.py`；集成 `test_api_flow.py` 的 `/api/health`；便携版冒烟 |
| T-002 本地页面离线加载 | 通过 | `tests/security` 的 `OfflineFrontendTests`（`frontend/` 全部文本文件零外部 URL）；端到端断言「对外 http(s) 请求为空、本机请求非空」；`scripts/build.py` 第 4 项 |
| T-003 SSH 正常连接 | 通过 | 集成 `test_connection_flow.py`（家目录 `/home/aimu`、SFTP 协议版本 3）；端到端第 1 条 |
| T-004 认证失败 | 通过 | 集成 `test_password_auth.py`（服务端日志出现新的 `Failed password`）；端到端第 3 条（`127.0.0.1:9` → 502/504 且界面弹提示、不落盘） |
| T-005 主机密钥变化 | 通过 | `tests/security/test_host_key.py`（未知 → 409 且不写信任库；伪造指纹 → 拒绝且文件不变；信任库被替换 → 409 `host_key_mismatch`）；端到端第 2 条（真模态、点「指纹一致，信任并继续」后连接成功） |
| T-006 目录浏览 | 通过 | 集成真实 `/etc` 列表（目录/符号链接/文件排序）；单元 `test_filesystem.py`；端到端行渲染与面包屑 |
| T-007 特殊文件名 | 通过 | 带空格与中文的文件名 `样本 文件.txt`、emoji 内容往返（集成）；端到端 `标记 名称 <RUN_TAG>.txt`；单元 `test_entry.py` |
| T-008 权限与路径 | 通过 | 单元 `test_paths.py`；`tests/security/test_path_traversal.py`（相对路径 400、`..` 由服务端 REALPATH 解析、百分号只解一次、NUL/超长路径 400、反斜杠是字面字符、NUL 与命令注入字样不产生 500） |
| T-009 上传下载 | 通过 | 单元 `test_sftp_protocol.py`；集成 mkdir/upload/download/rename/remove 往返（含 `mode` 0700 校验）；安全层票据篡改与换路径 → 401 |
| T-010 网络中断 | 通过 | discard 端口（`127.0.0.1:9`）连接失败路径（集成与端到端）；单元 `test_known_hosts.py` 的死端口用例；`app/api/http_server.py` 的连接重置处理（修复后 e2e 日志不再出现该类噪声栈） |
| T-011 敏感信息 | 通过 | 单元 `test_redact.py`、`test_logging_setup.py`；`tests/security/test_credentials.py`（哨兵密码不出现在落盘配置、8 个 GET 端点响应、`argv`、日志与端到端浏览器存储中） |
| T-012 离线部署 | 通过 | 离线扫描 + `scripts/build.py` + 便携版解压冒烟（§3.3） |
| T-013 资源释放 | 通过 | 集成 `test_disconnect_releases_the_child_process`（PowerShell 统计 `ssh.exe -p 2222`，断开后回到原值）；单元 `test_askpass.py`（一次性秘密文件与包装脚本被销毁） |
| T-014 目录结构 | 通过 | `scripts/build.py` 第 8 项；各目录 `_index.md`；`docs/PROJECT_STRUCTURE.md` |

## 5. 非功能项结论

| 项 | 结论 | 证据 |
|---|---|---|
| N-01 离线可用 | 满足 | 前端零外部 URL；端到端对外请求为空；运行时零第三方依赖 |
| N-02 轻依赖（运行时依赖数 = 0） | 满足 | `scripts/build.py` 第 3 项：`app/` 与 `scripts/` 的顶层导入全部落在 `sys.stdlib_module_names` 或项目内模块；端到端用标准库手写 CDP，未引入 Selenium/Playwright |
| N-03 默认安全 | 满足 | 默认配置 `server.host = 127.0.0.1`；Host 头白名单（`127.0.0.1:<port>`、`localhost:<port>`）；外站 Host 与跨站 `Sec-Fetch-Site` 一律拒绝 |
| N-04 可测试 | 满足 | 四层可独立运行；每层有 `__init__.py` 与 `_index.md`；`scripts/test.py` 一次跑完并汇总 |
| N-05 资源受控 | 满足 | `max_upload_bytes` / `max_download_bytes` / `max_sessions` / 请求体上限与超时的配置校验与用例（`test_config.py`、`test_transfer` 相关用例） |
| N-06 日志脱敏 | 满足 | 三种写法（`password=%s`、`{"api_key": "%s"}`、`ssh -i <路径>`）在日志里都变成 `***已脱敏***` |
| N-07 可移植 | 满足 | `--config` 指定配置文件；数据目录与日志目录由配置路径推导（`app/core/config.py:162-170`），启动自检打印实际位置（`app/main.py:207`） |

## 6. 缺陷记录

### 6.1 产品缺陷（6 处，全部已修并留回归）

| # | 现象 | 根因 | 修复与回归 |
|---|---|---|---|
| 1 | 页面永远空白：`#app` 一直 `hidden`，无 toast、无可见报错 | `frontend/assets/js/util.js` 的 `$` 是 `document.getElementById` 包装，而全站 45 处按 `$("#id")` 调用 | `util.js:13-25` 改为 `document.querySelector`；端到端第 1 条覆盖 |
| 2 | 连接列表恒为空（`#conn-empty` 不隐藏） | `GET /api/connections` 返回 `{"connections":[...]}`，前端当数组用 | `connections.js:35-40` 取 `data.connections`；端到端三条用例都会先经过列表渲染 |
| 3 | 信任主机密钥后落到根目录 `/` 而不是家目录 | 先 `openConnection` 后 `refreshConnections`，进入会话时 `session.home` 还是空的 | 调换顺序并写注释；端到端第 2 条断言家目录下才有夹具目录 |
| 4 | 连接必然失败的端口报 500 `internal_error` | `AwfmError.http_status` 是类属性，4 处调用点当关键字参数传 → `TypeError` | 改用 `OperationTimeout` / `RemoteError` / `ConfigError`；`tests/unit/test_errors.py` 新增两条（构造函数拒绝该关键字 + 静态扫描 `app/`）+ `test_known_hosts.py` 死端口用例 + `scripts/build.py` 第 6 项 |
| 5 | `Server` 响应头带尾随空格 | `BaseHTTPRequestHandler.version_string()` 会拼 `sys_version` | `http_server.py:100-106` 覆盖 `version_string()`；安全层响应头用例 |
| 6 | 浏览器关闭页面后服务端刷 `ConnectionResetError: [WinError 10054]` 整段 traceback | keep-alive 连接被重置，`rfile.readline` 抛到 `socketserver` | `AwfmRequestHandler.handle_one_request` 捕获 `ConnectionResetError`/`BrokenPipeError`/`ConnectionAbortedError`；修复后 e2e 输出不再出现该类噪声 |

### 6.2 测试自身缺陷（6 处，已修）

| # | 问题 | 处理 |
|---|---|---|
| 1 | 假设 `AskpassBundle.payload` 是路径，实际是字典（`payload[ASKPASS_FILE_ENV]`） | 按真实形状断言秘密文件内容与 `env` |
| 2 | 假设 `config.known_hosts_path` 指向的文件一定存在（首次连接前不存在） | 读取封装为「不存在则返回空列表」 |
| 3 | 断言集成测试的 `config.json` 落盘，实际配置只存在于内存 | 改为递归扫描临时目录的所有文本文件 |
| 4 | 用子串 `"/connect"` 过滤连接响应，误命中 `/api/connections` | 改为 `url.endswith("/connect")` |
| 5 | 凭据检查把文档示例占位符判为真凭据 | 显式放行占位符写法（`…`、`...`、`***`、`<...>`、`PASSWORD`、`placeholder`、空串）并计入检查输出 |
| 6 | `tests/integration/support.py` 统计 `ssh.exe` 时，只剩一个进程的标量 `.Count` 返回空 → 计数恒为 0（T-013 断言在真正只有一个子进程时失败） | 用 `@(...)` 包裹管道结果；此前被环境里残留的多个 `ssh` 进程掩盖，属于假绿 |

## 7. 证据文件清单

| 证据 | 位置 |
|---|---|
| 端到端截图 | `tests/e2e/artifacts/browser-journey-ef1aeb02.png`（本次运行） |
| 四层汇总 | 本报告 §3.1（源命令 `python scripts/test.py`） |
| 静态校验 | `python scripts/build.py`（可用 `--json PATH` 留档） |
| 包清单与校验和 | `dist/MANIFEST.json`、`dist/SHA256SUMS.txt` |
| 便携版冒烟 | 本报告 §3.3 |

## 8. 未执行与限制（不得当作通过）

1. **真实 CentOS 目标机未验证**：集成与端到端全部跑在 WSL Ubuntu 24.04.2 的非 root `sshd` 上。
2. **密码认证只验证到「密码送达服务端」**：非 root `sshd` 读不到 `/etc/shadow`（`tests/integration/test_password_auth.py` 文件头已注明），断言的是服务端日志出现新的 `Failed password`。
3. **系统级断网空载未做**：当前会话非管理员，无法安全断开网络栈；只提供间接证据（零外部 URL、零第三方依赖、端到端对外请求为空）。
4. **端到端覆盖 3 条主路径**：未覆盖下载、编辑/删除连接、预览对话框等界面分支（这些分支由单元与集成层覆盖）。

## 9. 结论

- 四层自动化测试 **363 项全部通过，0 失败、0 错误、0 跳过**；静态校验 8 项全过；便携版打包与冒烟通过。
- 验收项 T-001~T-014 全部通过，非功能项 N-01~N-07 全部满足；第 8 节列出的 4 条限制**不影响**上述结论的成立范围，
  但也不被这些结论覆盖。
- 建议：发布 v0.1.0；下一轮把第 8 节的第 1、3 项补齐，并把端到端扩展到下载与连接管理分支。
