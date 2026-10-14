# AWFM 最终开发报告

## 1. 报告信息

| 项目 | 内容 |
|---|---|
| 项目 | Aimu Web File Manager（AWFM）—— 零第三方依赖的本地 Web 远程文件管理器 |
| 项目版本 | v0.1.0 |
| 报告日期 | 2026-10-15 |
| 开发阶段 | 阶段 01~06 全部（规划文档 §6.1） |
| 对应 Git 提交或标签 | `d2f94e0`（阶段 01~02，2026-10-15，13 个文件 / 1534 行）；阶段 03~06 为本次收尾提交，尚未打标签 |

## 2. 阶段目标

按规划文档 `.md` 交付：

1. §3.1 的 **P0 功能全部** + 主要 P1 功能：连接管理、目录浏览、文件预览、上传下载、主机密钥确认、密码/密钥两种认证。
2. §6.1 的六个阶段（环境调查 → 最小链路 → 浏览器界面 → 安全控制 → 文件传输与测试 → 打包与文档）。
3. §7 的测试证据与 §9 的交付文档（设计、需求、API、测试、安全、变更、发行与阶段报告）。
4. §10 的七条安全要求与 §11 的发行形态（开发版 + 便携版）。

总约束：Windows 宿主机 + Linux 目标机、Python 3 标准库后端、原生 HTML/CSS/JS 前端（无框架、无 CDN、无构建步骤）、
system OpenSSH 子进程、**运行时第三方依赖数 = 0**、离线可用、密钥优先并支持密码。

## 3. 实际完成情况

| 阶段 | 目标 | 结论 | 报告 |
|---|---|---|---|
| 01 | 环境调查 | 完成 | `docs/reports/PHASE-01-ENVIRONMENT.md` |
| 02 | 最小链路 | 完成（含技术选型 SPIKE） | `PHASE-02-SPIKE.md`、`PHASE-02-PROTOTYPE.md` |
| 03 | 浏览器界面与核心功能 | 完成 | `PHASE-03-CORE.md` |
| 04 | 安全控制与文件传输 | 完成 | `PHASE-04-SECURITY-TRANSFER.md` |
| 05 | 离线部署与兼容性验证 | 完成（端到端 3 条全绿，发现并修掉 6 处真实缺陷） | `PHASE-05-OFFLINE-DEPLOY.md` |
| 06 | 文档验收与正式发布 | 完成（便携包 + 校验和 + 四层测试全绿） | `PHASE-06-RELEASE.md` |

**规模统计**（文件数 / 行数，本次收尾时统计）

| 范围 | 文件 | 行数 |
|---|---|---|
| `app/` | 33 | 5633 |
| `frontend/` | 14 | 2946 |
| `tests/`（unit / integration / security / e2e + fixtures） | 39 | 4646 |
| `scripts/` | 6 | 1235 |
| `docs/`（不含 `reports/`） | 13 | 3167 |

**未完成及原因**

- 真实 CentOS 目标机验证：本机无该环境，集成与端到端使用 WSL Ubuntu 24.04.2 的非 root `sshd` 测试床。
- 系统级断网空载验证：当前会话无管理员权限，改用三条间接证据（零外部 URL、零第三方依赖、端到端对外请求为空）。
- 端到端只覆盖 3 条主路径，界面的下载、编辑/删除连接、预览对话框分支未做端到端。

## 4. 技术实现

**总体链路**：本机 HTTP 服务（默认 `127.0.0.1`，一次性会话令牌）→ 连接管理器 → 每个连接一个
`ssh -s sftp` 子进程 → **标准库手写 SFTP v3 协议**（`app/ssh/sftp_protocol.py` 编解码、
`app/ssh/sftp_transport.py` 帧收发）→ 目录浏览/预览/上传/下载；前端为纯静态资源，令牌由服务端在
`index.html` 的占位符处注入。

| 关键决策 | 内容 |
|---|---|
| D-002 | 运行时第三方依赖数为 0（只用标准库 + 系统 OpenSSH） |
| D-004 → D-011 | 放弃 `sftp` 批处理与 `ls -l` 解析，改为自实现 SFTP v3 协议（同时也是 T-007 特殊文件名问题的根治） |
| D-006 | 默认配置**不落盘**：读内置默认值启动；显式 `--config` 指向不存在的文件才报错 |
| D-008 / D-014 | 密码不落盘、不经命令行与环境变量，交给一次性 `SSH_ASKPASS` 辅助程序；重连需重输 |
| D-012 | WSL 非 root `sshd` 测试床（`scripts/testbed_wsl.sh`，不使用 `sudo`） |
| D-013 | Windows 上所有文本 I/O 显式 UTF-8（启动脚本设 `PYTHONUTF8=1`） |
| D-015 | 便携版不捆绑 Python、不含 `tests/`；包内 `MANIFEST.json` 逐文件 SHA-256 |
| D-016 | `scripts/build.py` 八项静态校验作为发行门禁（含错误模型回归与凭据纪律） |
| D-017 | 许可证 MIT |

**与原设计的差异**：不创建 `pyproject.toml` / `requirements.txt`（零依赖，规划文档只在其为必要时要求）；
端到端从「用 Selenium」改为标准库手写 CDP 客户端（保持依赖数为 0）。

## 5. 测试结果

| | 内容 |
|---|---|
| 测试环境 | Windows 11 家庭版 26300 / Python 3.12.10 / OpenSSH_for_Windows 9.5p2 / Microsoft Edge 155.0.4283.45 / WSL Ubuntu 24.04.2 非 root `sshd` |
| 执行命令 | `python scripts/test.py`（四层 + 语法校验）、`python scripts/build.py`、`python scripts/package.py` |
| 测试总数 | **363 项**：单元 304、集成 18、安全 38、端到端 3 |
| 通过 / 失败 / 错误 / 未执行 | 363 通过 / 0 失败 / 0 错误 / 0 跳过；另有 8 项静态校验全过 |
| 关键测试证据 | `tests/e2e/artifacts/browser-journey-<RUN_TAG>.png`（真实浏览器截图）、`dist/SHA256SUMS.txt`、`dist/MANIFEST.json`、便携版解压冒烟记录（`docs/TEST_REPORT.md` §3） |
| 未执行 | 真实 CentOS 目标机验证；系统级断网空载验证 |

验收项结论：**T-001~T-014 全部通过**（逐项证据见 `docs/TEST_REPORT.md` §4）；
非功能项 **N-01~N-07 全部满足**（同文件 §5）。

## 6. 问题与风险

开发期间发现并修复的**真实缺陷 6 处**（其中 3 处只有真实浏览器才能发现）：

| # | 一句话 | 修复位置 |
|---|---|---|
| 1 | 前端 `$` 的语义与全站 45 处调用不匹配，页面永远空白 | `frontend/assets/js/util.js:13-25` |
| 2 | 连接列表把 `{"connections":[...]}` 当数组，列表恒空 | `frontend/assets/js/connections.js:35-40` |
| 3 | 信任主机密钥后进入根目录而非家目录（进入连接时用的还是旧数据） | `frontend/assets/js/connections.js` 的 `doConnect` |
| 4 | `AwfmError` 的 `http_status` 是类属性，4 处调用点却当关键字参数传 → `TypeError` 被 500 掩盖 | `app/ssh/known_hosts.py` 3 处、`app/ssh/sftp_transport.py` 1 处 |
| 5 | `Server` 响应头带尾随空格 | `app/api/http_server.py:100-106` |
| 6 | 连接被重置时服务端刷整段 traceback | `app/api/http_server.py` 的 `handle_one_request` |

测试自身的缺陷也一并修正（否则会给出假绿）：`AskpassBundle.payload` 是字典而非路径、
`known_hosts` 文件在首次连接前可能不存在、集成测试的配置对象只存在于内存、
过滤 `/connect` 响应时不能用子串（`/api/connections` 也含 `/connect`）、
PowerShell 标量的 `.Count` 返回空导致进程计数恒为 0（已改用 `@(...)` 包裹）。

**尚存风险**：端到端依赖 CDP，浏览器大版本升级可能影响用例；包内无测试，用户侧质量依赖发行报告；
未在 CentOS 与真实断网环境下验证；MIT 不含专利与商标条款。

## 7. 文档与交付物

- 需求与设计：`docs/REQUIREMENTS.md`、`docs/ARCHITECTURE.md`、`docs/PROJECT_STRUCTURE.md`、`docs/DECISIONS.md`
- 接口与安全：`docs/API.md`（19 个端点）、`docs/SECURITY.md`
- 测试：`docs/TEST_PLAN.md`、`docs/TEST_REPORT.md`
- 使用与发行：`docs/USER_GUIDE.md`、`docs/DEVELOPMENT.md`、`docs/RELEASE.md`、`README.md`、`LICENSE`
- 变更与报告：`docs/CHANGELOG.md`、`docs/reports/`（阶段 01~06 + 本报告）
- 构建产物：`dist/AWFM-0.1.0-windows-x64.zip` + `dist/SHA256SUMS.txt`（`dist/` 不提交）
- 运行要求：Windows 10/11 + Python 3.10+ + 系统 OpenSSH 客户端；无第三方 Python 包；不需要外网

## 8. 阶段结论

- **是否达到验收条件**：达到。§3.1 的 P0 功能全部交付，§10 安全要求逐条有测试或检查兜底，
  §11 发行验收 8 项通过（第 3、6 项按本报告 §3 的说明降级表述），四层测试 363 项全绿且无跳过。
- **是否允许发布**：允许发布 v0.1.0（便携版与开发版同源）。
- **后续任务**：
  1. 在真实 CentOS 目标机上复跑集成与端到端；
  2. 在有管理员权限的机器上做系统级断网验证；
  3. 把端到端覆盖扩展到下载、编辑/删除连接与预览分支；
  4. 为 v0.1.1 起启用 git 标签，并把每阶段产物按阶段分别提交（本次为一次性收尾提交）。
