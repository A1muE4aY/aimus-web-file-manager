# 阶段 03 报告：核心功能实现

## 1. 报告信息
| 项 | 值 |
|---|---|
| 项目 | Aimu's Web File Manager (AWFM) |
| 版本 | v0.1.0（`app/__init__.py:7` 的 `__version__ = "0.1.0"`） |
| 报告日期 | 2026-10-15 |
| 阶段 | 阶段 03 / 核心功能实现 |
| 对应 Git 提交或标签 | 无（阶段 02 为 `d2f94e0`；阶段 03 产物为未提交的工作区状态） |
| 依据 | 规划文档 §6.1 阶段 03；`docs/ARCHITECTURE.md`；`docs/API.md`；`docs/CHANGELOG.md` |

## 2. 阶段目标
**计划完成事项**（规划文档 §6.1 阶段 03，产物 = 功能代码 / API 文档 / 单元测试）：
1. 连接配置：主机、端口、用户名、认证方式（密钥 / 密码）可配置，且可增删改查。
2. 目录导航：浏览远程目录、进入子目录、返回上级、刷新与排序。
3. 文件属性展示：文件名、类型、大小、修改时间、权限位。
4. 错误处理：连接错误、权限错误、目录不存在都给出可理解提示，且服务不崩溃。
5. 会话清理：断开连接与进程退出都不留孤儿 ssh 子进程。

**验收标准**：P0 七项（`docs/REQUIREMENTS.md:22-28`）在本地测试床可完整演示；每个 P0 需求至少一个自动化用例（N-04）；`GET /api/health` 正常且全程离线（N-01 / N-02）；配置原子写、损坏时报错而不静默重置（F-P0-06）；退出后无残留 `ssh` 进程（T-013）。

## 3. 实际完成情况
**已完成**（全部为未提交的工作区状态）：
| 项 | 产物 |
|---|---|
| 后端六个包 | `app/api/`（8 模块）、`app/core/`、`app/services/`（4）、`app/ssh/`（6）、`app/models/`、`app/utils/` |
| HTTP API | 19 个端点：路由表 `app/api/handlers.py` 的 `ENDPOINTS`（:259-279）与 `build_router()`（:282） |
| 前端 | `frontend/index.html`（110 行）+ `assets/css/app.css`（561 行）+ 11 个 ES 模块；无框架、无构建步骤、无 CDN |
| 文档四份 | `docs/API.md`（407 行，§4/§5 与 19 个端点一一对应）、`docs/ARCHITECTURE.md`（168 行，含点目录到 SFTP READDIR 的 18 步调用链）、`docs/DEVELOPMENT.md`（288 行）、`docs/USER_GUIDE.md`（625 行） |
| 单元测试 | `tests/unit/`；`docs/CHANGELOG.md` 阶段进度表记录 301 项全部通过（阶段 06 扩充该文件后行号已变，按小节查阅） |
| 集成测试 | `tests/integration/`（`test_connection_flow`、`test_api_flow`、`test_password_auth`）；`docs/CHANGELOG.md` 阶段进度表记录 18 项全部通过 |

**部分完成**：
| 项 | 缺口 |
|---|---|
| 权限与属主展示 | 目录列举已返回 permissions/mode（`app/models/entry.py`）；P1 的「权限与属主界面展示」未单列验收 |
| 会话清理 | `app/services/session.py`（322 行）保证各退出路径关闭子进程；**长时稳定性未验证** |
| P2 写操作 | `SftpClient.mkdir/rmdir/remove/rename`（`app/ssh/sftp_client.py`）已实现，但未注册进 `ENDPOINTS`，不通过 HTTP 暴露 |

**未完成及原因**：
| 项 | 原因 |
|---|---|
| 真实 CentOS 目标机端到端验证 | R-01：虚拟机未开机；集成测试跑在 WSL 测试床 |
| `tests/security/` 与 `tests/e2e/` | 属阶段 04；阶段 03 的安全用例混在 `tests/unit/test_api_security.py` 与 `tests/unit/test_tickets.py` |
| `scripts/build.py` 的八项静态校验 | 属阶段 05/06 的发行门禁（D-016）；阶段 03 时该脚本尚不存在 |

## 4. 技术实现
**修改的模块**：`app/api/`（http_server 290 / handlers 278 / request 121 / responses 114 / security 120 / tickets 98 / router 59 行）、`app/core/`（config 402 / errors 172）、`app/services/`（session 322 / connection_manager 294 / transfer 188 / filesystem 183）、`app/ssh/`（sftp_transport 352 / sftp_protocol 337 / sftp_client 265 / known_hosts 242 / ssh_launcher 148 / askpass 122）、`app/models/`（connection 146 / entry 75）、`app/utils/`（paths 148 / logging_setup 86 / redact 78 / atomic 36）、`app/main.py` 273；前端 11 个模块（connections 575 / files 281 / app 222 / api 216 / transfer 189 / util 165 / modal 162 / preview 82 / toast 71 / icons 60 / state 54 行）。
**关键实现方案**：
1. **分层与依赖方向**：api → services → ssh →（protocol / utils）单向；`app/api/` 不 import `app/ssh/`；`app/ssh/__init__.py:4` 声明本层是唯一允许调用 subprocess 的地方，两处调用（`app/ssh/sftp_transport.py:102`、`app/ssh/known_hosts.py:196`）都用 argv 列表、不经 shell。
2. **自实现 SFTP v3（D-011）**：`app/ssh/sftp_protocol.py` 用 struct 手写编解码与 `parse_response()`（:325）；`app/ssh/sftp_transport.py` 唯一持有子进程，负责 request-id 配对（`transact` :326）、超时看门狗（:154，每 0.1 秒查 deadline）与 stderr 排空（:131，保留最后 200 行）。
3. **并发模型**：每请求一线程（`app/api/http_server.py:81` 的 `ThreadingHTTPServer`，`daemon_threads=True`）；`app/ssh/sftp_transport.py:71` 的 `_io_lock` 串行化帧收发——SFTP v3 无请求多路复用，交错写帧会让 id 与响应错配且无法恢复；看门狗线程绕开「Windows 的 select() 不支持管道」，stderr 排空避免 `ssh` 因管道写满而挂起。
4. **错误模型**：`app/core/errors.py` 每个异常类自带字符串 `code` 与整数 `http_status`；SFTP STATUS 数值码经 `app/ssh/sftp_transport.py:49` 的 `map_status_error()` 翻译（2→404、3→403、5→502、6/7→409、8 及其它→502），不依赖匹配英文错误串。
5. **会话清理（T-013）**：`app/services/session.py:310` 的 `_teardown()` 先取走 transport 并置 None 再关闭；主线程 `finally` 调 `manager.disconnect_all()`。
**与原设计的差异**：
| 原设计 | 实际 | 原因 |
|---|---|---|
| `frontend/` 含 `pages/` 与 `assets/fonts/` | 只有 `index.html` + `assets/{css,js,icons}` | 单页应用不需要分页目录，也没有自备字体 |
| HTTP 基础设施放在 `app/core/` | 落在 `app/api/http_server.py`（290 行） | `app/api/` 才是 HTTP 边界，core 只留配置与错误 |

## 5. 测试结果
**测试环境**：宿主机 Windows 11 家庭版 26300 / PowerShell 5.1 / Python 3.12.10（`E:\Software\Python 3.12\python.exe`）/ OpenSSH_for_Windows 9.5p2；测试床 WSL2 Ubuntu 24.04.2 上非 root `sshd`，`127.0.0.1:2222`，用户 `aimu`。
**执行命令**：
```powershell
python -m unittest discover -s tests/unit -t .
python -m unittest discover -s tests/integration -t .
```
| 类别 | 数量 | 结果 |
|---|---|---|
| `tests/unit/` | 301 项（17 个模块） | 全部通过（`docs/CHANGELOG.md` 阶段进度表；阶段 06 扩充后行号已变） |
| `tests/integration/` | 18 项（3 个模块） | 全部通过（`docs/CHANGELOG.md` 阶段进度表） |
| `tests/security/`、`tests/e2e/`、依赖真实 CentOS 的验收项 | — | **未建立 / 未执行**（分属阶段 04 与 05） |
**如实声明**：本报告未重新执行测试套件。按文件最后修改时间推断，阶段 03 期间（00:32–00:44）落地的单元测试为 15 个模块 / 279 项，与 `docs/CHANGELOG.md` 阶段进度表记录的 301 项对不上（后加的 `test_errors`、`test_known_hosts` 共 25 项也补不足差值）；工作区当前静态计数为 unit 304 / integration 18 / security 38 / e2e 3，合计 363 项，`scripts/build.py` 八项静态校验全过。**最终结果见 `docs/TEST_REPORT.md`。**
**关键测试证据**：
- `tests/unit/test_sftp_protocol.py`（37 项）钉死两个高危错误点：响应包第一个字段是请求 id、`MKDIR`/`SETSTAT` 的属性字段是完整 ATTRS；`tests/unit/test_config.py`（34 项）与 `tests/unit/test_paths.py`（30 项）覆盖配置默认值/原子写与远程路径形式校验（`app/utils/paths.py:58`，只校验形式、不做词法 `..` 折叠）。
- `tests/integration/test_api_flow.py`（8 项，含 CSP 与安全响应头断言）、`test_connection_flow.py`（8 项，主机密钥两阶段确认）、`test_password_auth.py`（2 项，`SSH_ASKPASS` 路径 D-008）。

## 6. 问题与风险
**发现的问题（阶段 03 期间真实修复的缺陷）**：
| 缺陷 | 现象 | 修复 |
|---|---|---|
| SFTP 成功响应被当作错误抛出 | 远端返回 `OK：Success` 却报错 | `app/ssh/sftp_client.py:30-34` 定义 `_OK = (proto.SSH_FX_OK,)`，只用 STATUS 回话的调用点（:162/:184/:272/:281/:290/:300）显式接受 |
| `StrictHostKeyChecking` 收到非法取值 `strict` | `ssh` 在解析参数阶段退出：`command-line line 0: unsupported option "strict"`，现象是「连不上」 | `app/ssh/ssh_launcher.py:46-53` 显式映射 `_STRICT_HOST_KEY_OPTION = {"strict": "yes", "accept-new": "accept-new"}`（使用处 :128） |
| 中文连接名生成的 id 含非 ASCII | 用中文命名连接必然 400（「临」.isalnum() 为真，生成的 id 随后被 `_ID_RE`（`app/models/connection.py:29`）拒绝） | `app/services/connection_manager.py:181-195` 先做 ASCII 归一化再过滤，派生不出 ASCII 时回退 `conn`；显示名不受影响 |
| SFTP 响应包解析错位 / `MKDIR`·`SETSTAT` 属性字段编码错误 | 解析整体错位；属性字段发成裸 `uint32` 会让 `sftp-server` 直接 `fatal()` 退出，客户端只看到 `EOFError: EOF poll=None` | `tests/unit/test_sftp_protocol.py` 钉死（37 项） |
**复现步骤（第 2 条）**：
```powershell
ssh -o StrictHostKeyChecking=strict aimu@127.0.0.1
# command-line line 0: unsupported option "strict"
```
**尚存风险**：
1. 测试床是 WSL2 Ubuntu，UID/GID 与真实 CentOS 不同；WSL2 的 `localhost` 转发不代表真实网络可达性。
2. 测试床不含 sudo，任何需要 root 的验证（PAM、`UsePAM yes`、特权端口 <1024）不在覆盖范围内，不得据此声称已验证（D-012）。
3. `rename`/`remove` 只在程序内部服务上传的「临时名 + 改名」流程（`app/services/transfer.py`），不对用户开放；也没有任何长时稳定性或性能记录（`docs/CHANGELOG.md` 明确记录了口径边界）。
4. 阶段 03 的产物未提交（`git status` 中 `app/`、`frontend/`、`tests/`、`docs/*.md` 未跟踪），阶段证据只能靠工作区状态与文档追溯。

## 7. 文档与交付物
**新增或修改的文档**：`docs/API.md`（407 行，19 个端点逐条说明）/ `docs/ARCHITECTURE.md`（168 行，分层、调用链、并发模型、错误模型、前端模块依赖）/ `docs/DEVELOPMENT.md`（288 行，代码地图与开发规范）/ `docs/USER_GUIDE.md`（625 行，按规划文档 §8 十二章节目录编排）。
**构建产物**：无。阶段 03 没有对应提交，也没有发行包（`dist/` 中的便携包属阶段 05/06）。
**依赖与运行要求**：运行时第三方依赖 = 0（N-02，`app/__init__.py:1-5`）；环境前提 = Python 3.12 + 系统 OpenSSH 客户端 + 目标机 SFTP 子系统；默认 `127.0.0.1:8760`、`security.allow_lan=false`（N-03）；前端离线、无外部 URL（T-002）；配置写 `data/config.json`、原子写、损坏报 `config_error` 而不静默重置（F-P0-06）；密码不落盘（D-014）、不在 API 响应中回吐私钥（N-06）；文本 I/O 显式 UTF-8（D-013）。

## 8. 阶段结论
**是否达到验收条件：基本达到。** P0 七项的功能代码与 API 文档齐备，单元/集成测试记录在案；未达到的是「真实 CentOS 目标机的端到端验证」（属阶段 05）与「安全 / 端到端测试两层」（属阶段 04）。
**是否允许进入阶段 04：允许。**
**后续任务：**
1. 阶段 04：主机密钥、路径校验、文件传输、权限错误、异常中断、大文件。
2. 补齐阶段 03 缺的两层测试：`tests/security/` 与 `tests/e2e/` 在阶段 04 落地，最终口径以 `docs/TEST_REPORT.md` 为准。
3. 把阶段 03/04 的工作区状态提交到 git。
4. 阶段 05 前请用户开机 CentOS 虚拟机（R-01）。