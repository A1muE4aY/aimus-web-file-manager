# 阶段 05 报告：离线部署与兼容性验证

## 1. 报告信息

| 项目 | 内容 |
|---|---|
| 项目版本 | v0.1.0 |
| 报告日期 | 2026-10-15 |
| 开发阶段 | 阶段 05 —— 离线部署与兼容性验证（规划文档 §6.1） |
| 对应 Git 提交或标签 | 无（阶段 02 为 `d2f94e0`；阶段 03 及以后均为未提交的工作区状态，见 `docs/CHANGELOG.md`） |

## 2. 阶段目标

计划完成事项：

1. 在不依赖外网的条件下证明前端可用：静态扫描 + **真实浏览器**端到端验证（规划文档 §7.2 要求浏览器端到端，且不得引入在线依赖）。
2. 提供可复现的 Linux 目标机测试床，并让集成测试能在 Windows 宿主上一键跑完。
3. 把「离线可用 / 零第三方运行时依赖」变成可重复执行的检查，而不是一句声明。

验收标准：T-002（本地页面离线加载）、T-012（离线部署）、N-01（离线可用）、N-02（轻依赖），
外加端到端路径要覆盖 §7.2 的连接、浏览、主机密钥确认、密码提示与失败提示。

## 3. 实际完成情况

**已完成**

- `tests/e2e/`：3 条端到端用例，用**标准库手写 CDP 客户端**驱动真实 Microsoft Edge（headless + 无痕），
  覆盖「连接 → 浏览 → 上传两个文件 → 进入目录 → 两级返回」的完整旅程、首次连接的主机密钥确认、密码提示与失败提示。
- `scripts/testbed_wsl.sh`：幂等的 WSL 测试床启停脚本（`up` / `status` / `stop`），不使用 `sudo`。
- 前端离线检查落地两处：`tests/security/test_web_security.py` 的 `OfflineFrontendTests` 与
  `scripts/build.py` 的 `check_frontend_offline`（前者是测试，后者是发行门禁）。
- 零依赖检查落地：`scripts/build.py` 的 `check_stdlib_only`（`ast` 扫描顶层导入）。
- 本阶段**发现并修复 6 处真实缺陷**（其中 3 处前端、1 处错误模型、2 处 HTTP 层），详见 §6。

**部分完成**

- 端到端只覆盖了 3 条主路径（连接/浏览/上传、主机密钥确认、密码失败），没有覆盖下载、编辑连接、删除连接等分支。

**未完成及原因**

- **真实 CentOS 目标机验证**：本机没有可用的 CentOS 环境（规划文档提到的那台虚拟机未启动/未接入），
  集成与端到端全部跑在 WSL Ubuntu 24.04.2 上。已如实记入 `docs/TEST_PLAN.md` §9 与 `docs/TEST_REPORT.md`。
- **断网空载的系统级验证**：当前会话无管理员权限，无法安全断开网络栈；改为提供三条间接证据
  （前端零外部 URL、零第三方依赖、端到端内对外 http(s) 请求列表为空）。

## 4. 技术实现

**关键实现方案**

1. **不引入 Selenium / Playwright**。需求 N-02 要求运行时依赖数为 0，因此 `tests/e2e/support.py` 用
   `socket` + `http.client` 手写 CDP over WebSocket：握手要求 `101`、客户端帧加掩码、支持 126/127 长度、
   `ping` 回 `pong`、按 `id` 匹配响应，其余事件收进 `self.events`（`Page`/`Network`/`Runtime` 三个域）。
2. **浏览器按需启动、用完即收**：`browser_session()` 以
   `--headless=new --inprivate --disable-gpu --no-first-run --no-default-browser-check --disable-background-networking
   --disable-component-update --disable-sync --disable-extensions --window-size=W,H --remote-debugging-port=<空闲端口>
   --user-data-dir=<临时目录>` 启动 Edge，用 `/json/list` 轮询到 `type=page` 的调试目标，退出时用
   `taskkill /F /T /PID` 收掉整棵进程树；找不到 Edge 则 `SkipTest`（跳过，不是失败）。
3. **测试床与测试解耦**：`scripts/testbed_wsl.sh` 用 `apt-get download` + `dpkg -x` 把 `openssh-server`
   解到 `~/.awfm-testbed/` 下，以非 root 用户跑一个只监听 `127.0.0.1:2222` 的 `sshd`；
   日志固定写到 `~/.awfm-testbed/sshd/var/sshd.log`（与 `tests/integration/test_password_auth.py:42` 的硬编码一致）。
   脚本只操作自己的目录，不写系统路径，重复执行不产生副作用。
4. **离线是「扫出来的」而不是「说出来的」**：`frontend/` 下所有文本文件（`.html/.css/.js/.svg/.json`）中，
   除 SVG 命名空间 `http://www.w3.org/2000/svg` 外不允许出现任何 `http(s)://`；端到端用例另外断言
   页面的 `Network.requestWillBeSent` 里没有任何外部域请求，且本机请求不为空（证明断言本身有效）。

**与原设计的差异**

- 原计划用 Selenium 做端到端（规划文档允许），实际改为手写 CDP：代价是要自己维护约 370 行 WebSocket 客户端，
  收益是运行时依赖数保持 0、CI 与用户机器都不需要额外安装任何东西。
- 阶段 05 原定只做「离线验证」，实际还承担了「第一次真正在浏览器里执行前端代码」的职责 —— 因此暴露出的
  缺陷数量超出预期（见 §6）。

## 5. 测试结果

| | 内容 |
|---|---|
| 测试环境 | Windows 11 家庭版 26300 / Python 3.12.10 / OpenSSH_for_Windows 9.5p2 / Microsoft Edge 155.0.4283.45 / WSL Ubuntu 24.04.2 非 root `sshd`（`127.0.0.1:2222`） |
| 执行命令 | `python -m unittest discover -s tests/e2e -t .`；全量 `python scripts/test.py` |
| 端到端结果 | 3 项，全部通过（12.68s），0 跳过 |
| 关键测试证据 | `tests/e2e/artifacts/browser-journey-<RUN_TAG>.png`（每次运行一张，界面真实渲染）；端到端断言「对外 http(s) 请求列表为空」 |
| 该阶段其它层 | 单元 304 项、集成 18 项、安全 38 项（最终汇总见 `docs/TEST_REPORT.md`） |

## 6. 问题与风险

本阶段的主要产出其实是缺陷清单 —— 前端的 JS **在此之前从未在浏览器里被执行过**，三层后端测试都看不见这些问题。

| # | 现象 | 根因 | 修复 |
|---|---|---|---|
| 1 | 页面永远空白，`#app` 一直 `hidden`，无 toast 无报错 | `frontend/assets/js/util.js` 的 `$` 原本是 `document.getElementById` 的包装，而全站 45 处调用都写成 `$("#id")` 的 CSS 选择器形式；任何一处执行即抛错 | `util.js:13-25` 改为 `document.querySelector(selector)`，失败时抛出指明选择器的错误 |
| 2 | 连接列表恒为空（`#conn-empty` 不隐藏），端到端三条用例全部超时 | `GET /api/connections` 返回 `{"connections":[...]}`，而 `connections.js` 把返回值当数组（`Array.isArray(list)`） | `connections.js:35-40` 改为取 `data.connections`；新增连接的守卫同步改为 `created.connection.id` |
| 3 | 信任主机密钥后进入的是根目录 `/` 而不是家目录 | `connections.js` 原顺序是先 `openConnection(id)` 再 `refreshConnections()`，进入会话时用的还是旧数据（`session.home` 为空） | 改为先刷新列表再进入连接，并在源码里写下原因注释 |
| 4 | 连接一个必然失败的端口（`127.0.0.1:9`）报 500 `internal_error` | `app/core/errors.py` 的 `http_status` 是**类属性**，但 4 处调用点把它当构造参数传 —— `TypeError` 掩盖了真实错误 | 4 处改用对应错误子类（`OperationTimeout` 504 / `RemoteError` 502 / `ConfigError` 500）；新增两条回归测试与构建检查 `check_error_model` |
| 5 | 响应头 `Server: AWFM/0.1.0 `（尾随空格） | `BaseHTTPRequestHandler.version_string()` 会拼 `server_version + " " + sys_version` | `app/api/http_server.py:100-106` 覆盖 `version_string()` |
| 6 | 浏览器关页面后服务端刷 `ConnectionResetError: [WinError 10054]` 的整段 traceback | keep-alive 连接被重置，`rfile.readline` 直接抛异常到 `socketserver` | `AwfmRequestHandler.handle_one_request` 捕获 `ConnectionResetError`/`BrokenPipeError`/`ConnectionAbortedError` 并置 `close_connection = True` |

**尚存风险**

- 端到端依赖 CDP：Edge 大版本升级可能改变行为（当前 155.0.4283.45）；用例失败时应先看截图再判定是产品问题还是浏览器问题。
- 三条用例只覆盖主路径；界面分支（下载、编辑/删除连接、预览对话框）仍只有单元与集成层覆盖。
- 真实 CentOS 目标机与断网空载仍未验证（见 §3）。

**复现步骤（以缺陷 4 为例）**：`python scripts/test.py --fast` 全绿时也可能存在该缺陷 —— 它由端到端的
`tests/e2e/test_browser_flow.py` 第 3 条（discard 端口连接）首次暴露；单独复现可调用
`app/ssh/known_hosts.py` 的 `collect_host_keys(ssh_executable=..., host="127.0.0.1", port=9)`。

## 7. 文档与交付物

- 新增代码：`tests/e2e/__init__.py`、`tests/e2e/support.py`、`tests/e2e/test_browser_flow.py`、`tests/e2e/_index.md`、`scripts/testbed_wsl.sh`
- 新增文档：`docs/TEST_PLAN.md`（本阶段起制定）、`docs/TEST_REPORT.md`（结果出口）
- 修改代码：`frontend/assets/js/util.js`、`frontend/assets/js/connections.js`、`app/api/http_server.py`、
  `app/ssh/known_hosts.py`、`app/ssh/sftp_transport.py`、`tests/integration/support.py`
- 构建产物：本阶段不产出发行包（阶段 06）
- 依赖与运行要求：Python >= 3.10、系统 OpenSSH；端到端额外需要 Edge；集成与端到端需要测试床

## 8. 阶段结论

- **是否达到验收条件**：达到。T-002、T-012、N-01、N-02 均有可重复执行的证据，端到端三条用例全绿。
- **是否允许进入下一阶段**：允许（阶段 06 文档验收与正式发布）。
- **后续任务**：便携版打包与校验和（阶段 06）；补真实 CentOS 目标机验证；把端到端覆盖扩展到下载与连接管理分支。
