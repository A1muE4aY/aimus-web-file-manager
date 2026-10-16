# AWFM 测试计划

- 适用版本：v0.1.0（开发版与便携版同一份代码）
- 制定日期：2026-10-15
- 对应需求：规划文档 §3.1（功能分级）、§7（测试与证据）、§10（安全要求）与
  `docs/REQUIREMENTS.md` 的 T-001~T-014、N-01~N-07
- 结果出口：`docs/TEST_REPORT.md`（本计划只规定「测什么、怎么测、什么算通过」）

## 1. 目的与范围

| | 内容 |
|---|---|
| 纳入 | 后端全部模块、前端全部脚本、SSH/SFTP 真实链路、安全控制、便携版打包与启动 |
| 纳入 | 规划文档 §10 的七条安全要求（主机密钥验证、密钥保护、默认只听回环、路径校验、请求保护、日志脱敏、传输限制） |
| 不纳入 | 真实 CentOS 物理/虚拟机目标机的验证（本机无该环境，见 §9 与 `docs/TEST_REPORT.md` 的「未执行」） |
| 不纳入 | 断网空载下的系统级验证（非管理员权限下无法安全地断开网络栈） |
| 不纳入 | 多用户并发压测、超过 `max_sessions` 的压力场景 |

## 2. 测试分层

| 层 | 位置 | 用例数 | 依赖 | 命令 |
|---|---|---|---|---|
| 静态校验 | `scripts/build.py` | 8 项检查 | 无 | `python scripts/build.py` |
| 单元 | `tests/unit` | 304 | 无 | `python -m unittest discover -s tests/unit -t .` |
| 集成 | `tests/integration` | 18 | WSL 测试床（`127.0.0.1:2222` + `data/testbed/id_ed25519`） | `python -m unittest discover -s tests/integration -t .` |
| 安全 | `tests/security` | 38 | 仅主机密钥用例需要 `ssh`/`ssh-keygen`；其余用本机临时 HTTP 服务与 discard 端口 | `python -m unittest discover -s tests/security -t .` |
| 端到端 | `tests/e2e` | 3 | Microsoft Edge + 本机 HTTP 服务；其中 2 条另需测试床 | `python -m unittest discover -s tests/e2e -t .` |
| 打包自检 | `scripts/package.py` | 清单逐文件 SHA-256 + 必需文件齐全 | 无 | `python scripts/package.py` |

依赖缺失时的行为：集成与端到端层用 `skipUnless`/`SKIP` 跳过（测试床不在、Edge 未安装），**跳过不算通过**，必须在 `docs/TEST_REPORT.md` 里逐条说明。

## 3. 运行方式

| 目的 | 命令 |
|---|---|
| 四层全跑 + 语法校验 | `python scripts/test.py` |
| 只跑快的两层（单元 + 安全） | `python scripts/test.py --fast` |
| 测试结束自动跑构建校验 | `python scripts/test.py --build` |
| 单层 | `python -m unittest discover -s tests/<层> -t .` |
| 语法校验（`SyntaxWarning` 视为错误） | `python -W error::SyntaxWarning -m compileall -q app tests scripts` |
| 打包（默认先跑八项校验） | `python scripts/package.py` |

`scripts/test.py` 的退出码：0 全过 / 1 有层未通过 / 2 用法错误或语法校验失败。它会打印一张汇总表，**并把「跳过」单列**——跳过的用例没有验证任何东西。

PowerShell 下看输出：`unittest` 把进度点写到 stderr，Windows PowerShell 5.1 会把它渲染成 `NativeCommandError`。用
`... 2>&1 | Select-String -Pattern '^(ERROR|FAIL): |^Ran |^OK|^FAILED'` 过滤即可，这不是测试失败。

## 4. 环境要求

| 组件 | 要求 | 本项目实测 |
|---|---|---|
| Python | >= 3.10（`scripts/launcher.py`、`scripts/start.py` 与 `scripts/build.py` 都会拦） | 3.12.10（`E:\Software\Python 3.12\python.exe`，本机无 `python3`） |
| 操作系统 | Windows 10/11 | Windows 11 家庭版 26300（非管理员会话） |
| SSH 客户端 | 任意 OpenSSH（`ssh`/`ssh-keygen` 在 PATH 或配置里给全路径） | OpenSSH_for_Windows 9.5p2 |
| 目标机测试床 | 任意 Linux + sshd（非 root 亦可） | WSL Ubuntu 24.04.2 的非 root sshd，`127.0.0.1:2222`，用户 `aimu`，家目录 `/home/aimu` |
| 测试床启停脚本 | — | `wsl -d Ubuntu bash scripts/testbed_wsl.sh [up|status|stop]`（幂等、不使用 `sudo`、不碰系统目录） |
| 浏览器（端到端） | Chromium 系（用 CDP 驱动） | Microsoft Edge 155.0.4283.45（headless + 无痕） |
| 网络 | **不需要外网**（T-002/N-01） | 前端零外部 URL，运行时零第三方依赖 |

## 5. 用例设计原则

1. **不打桩**：真实 HTTP 服务（本机回环端口）、真实 `ssh`/`sftp` 子进程、真实 `sshd`、真实浏览器（CDP over WebSocket，标准库手写）。
2. **异常路径优先**：认证失败、主机密钥未知/不匹配、相对路径与 `..`、NUL 字节、超长路径、票据伪造与换路径、上传越权、连接被重置。正常路径只是基线。
3. **每条验收项至少一条用例**（映射见 §7）。
4. **断言可核实**：状态码、错误码、响应头、落盘字节、远端文件内容、进程数量。
5. **不碰真实用户环境**：临时目录、临时 `known_hosts`、回环端口、必然连不上的 discard 端口（`127.0.0.1:9`）；测试不读写用户的真实 `~/.ssh`。
6. **测试自身的缺陷也算缺陷**：断言写错、对代理对象形状的错误假设都要修，并记进 `docs/TEST_REPORT.md`（否则测试会给出假绿）。

## 6. 进入与退出准则

- **进入**：`python -W error::SyntaxWarning -m compileall -q app tests scripts` 通过。
- **退出**：四层全绿，且跳过用例为 0 或已逐条说明；`scripts/build.py` 八项全过；便携版解压冒烟（启动、访问、停止）通过；`docs/TEST_REPORT.md` 已按最终数字更新。
- **不通过的定义**：出现 1 条失败或错误即不通过；出现「未执行」的验收项即在结论里明写，不得用跳过充当通过。

## 7. 验收项到用例的映射

| 验收项 | 主要证据 |
|---|---|
| T-001 服务启动 | `tests/unit/test_config.py`、`tests/integration/test_api_flow.py`（`/api/health`）、`app/main.py --check` |
| T-002 本地页面离线加载 | `tests/security/test_web_security.py` 的 `OfflineFrontendTests`、`scripts/build.py` 的前端离线检查、`tests/e2e` 的对外请求为空断言 |
| T-003 SSH 正常连接 | `tests/integration/test_connection_flow.py`、`tests/e2e/test_browser_flow.py` 第 1 条 |
| T-004 认证失败 | `tests/integration/test_password_auth.py`、`tests/e2e/test_browser_flow.py` 第 3 条（503/504 与提示文案） |
| T-005 主机密钥变化 | `tests/security/test_host_key.py`（未知/伪造/不一致三种）、`tests/e2e/test_browser_flow.py` 第 2 条 |
| T-006 目录浏览 | `tests/integration/test_connection_flow.py`（真实 `/etc`）、`tests/unit/test_filesystem.py`、`tests/e2e` 的行渲染断言 |
| T-007 特殊文件名 | `tests/unit/test_entry.py`、`tests/integration`（`样本 文件.txt`、emoji 内容）、`tests/e2e`（带空格的 `标记 名称 <RUN_TAG>.txt`） |
| T-008 权限与路径 | `tests/unit/test_paths.py`、`tests/security/test_path_traversal.py` |
| T-009 上传下载 | `tests/unit/test_sftp_protocol.py`、`tests/integration` 的 mkdir/upload/download/rename/remove 往返、`tests/security` 的票据篡改用例 |
| T-010 网络中断 | `tests/security/support.py` 的 discard 端口连接、`tests/unit/test_known_hosts.py` 的死端口用例、`app/api/http_server.py` 的连接重置处理 |
| T-011 敏感信息 | `tests/unit/test_redact.py`、`tests/unit/test_logging_setup.py`、`tests/security/test_credentials.py`（哨兵密码不出现在响应/落盘/日志/命令行） |
| T-012 离线部署 | `tests/security` 的离线扫描、`scripts/build.py`、`scripts/package.py` + 便携版解压冒烟 |
| T-013 资源释放 | `tests/integration/test_connection_flow.py` 的 `test_disconnect_releases_the_child_process`（统计 `ssh.exe -p 2222`）、`tests/unit/test_askpass.py`（临时秘密文件销毁） |
| T-014 目录结构 | `scripts/build.py` 的测试包结构检查、各目录 `_index.md` |
| N-01 离线可用 | 前端离线检查 + 端到端「对外 http(s) 请求列表为空」 |
| N-02 轻依赖（运行时依赖数 = 0） | `scripts/build.py` 的 `ast` 导入扫描（只允许标准库与项目内模块） |
| N-03 默认安全（只绑 127.0.0.1） | `tests/unit/test_config.py` 的默认值与 `allow_lan` 校验、`app/main.py --check` |
| N-04 可测试 | 四层测试可独立运行；`tests/*/` 各自有 `__init__.py` 与 `_index.md` |
| N-05 资源受控 | `max_upload_bytes`/`max_download_bytes`/`max_sessions` 的配置校验与传输限额用例 |
| N-06 日志脱敏 | `tests/unit/test_redact.py`、`tests/security/test_credentials.py` 的 `LoggingRedactionTests` |
| N-07 可移植 | `--config` 指定配置文件；数据目录与日志目录由配置路径推导（`app/core/config.py:162-170`），启动自检会打印实际位置（`app/main.py:207`） |

## 8. 证据与产物

| 产物 | 位置 | 说明 |
|---|---|---|
| 端到端截图 | `tests/e2e/artifacts/browser-journey-<RUN_TAG>.png` | 每次运行一条，作为「界面真的跑起来」的视觉证据 |
| 四层汇总表 | `docs/TEST_REPORT.md` | 用例数/失败/错误/跳过/耗时，按最终一次运行填写 |
| 静态校验结果 | `python scripts/build.py --json <path>` | 机器可读，用于发行时留档 |
| 包清单与校验和 | `dist/MANIFEST.json`、`dist/SHA256SUMS.txt` | 逐个文件 SHA-256 + 压缩包哈希 |
| 构建记录 | 包内 `VERSION` | 版本、构建时间、平台、构建主机 Python |

## 9. 已知不覆盖（如实记录，不用「通过」掩盖）

1. **真实 CentOS 目标机未验证**：本机没有可用的 CentOS 环境，集成与端到端全部跑在 WSL Ubuntu 24.04.2 的非 root `sshd` 上。协议层与命令行参数与发行版无关，但这不等于在 CentOS 上验证过。
2. **密码认证在测试床上只能证明「密码送达服务端」**：非 root `sshd` 读不到 `/etc/shadow`（`tests/integration/test_password_auth.py` 文件头已注明），所以该用例断言的是服务端日志出现新的 `Failed password`，不是登录成功。
3. **断网空载未做系统级验证**：非管理员会话无法安全断开网络栈；只用「前端零外部 URL 静态扫描 + 运行时零第三方依赖 + 端到端对外请求为空」三条间接证据。

## 10. 维护约定

- 新增测试文件要登记到该层的 `_index.md`；目录内文件数达到 5 个必须有 `_index.md`（`AGENTS.md` §3.6）。
- 改动 `app/` 或 `frontend/` 时，同一提交内更新受影响的测试层。
- 版本号变更必须同时出现在 `README.md` 与 `docs/CHANGELOG.md`（`scripts/build.py` 的版本一致性检查会拦）。
- 每次发行前重跑 `scripts/test.py` 与 `scripts/package.py`，并把结果写进 `docs/TEST_REPORT.md`。
