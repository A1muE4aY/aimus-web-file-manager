# AWFM 开发者指南

**版本**：v0.1.0　**文档日期**：2026-10-15

这份文档给要改 AWFM 代码的人：代码怎么分层、环境怎么准备、规范是什么、加一个功能要动哪几层、出问题怎么查、提交要带什么过程证据。

写文档时遵循一条硬规则：**只描述代码已经做到的事**。凡是尚未实现的部分，本文会明确写「本版没有」而不是省略。

---

## 1 代码地图与分层

### 1.1 分层

| 目录 | 职责 | 说明 |
| --- | --- | --- |
| app/main.py | 进程入口 | 命令行解析、配置加载与覆盖、日志初始化、--init-config、--check、启动 HTTP 服务与优雅停机 |
| app/api/ | HTTP 边界 | 路由表、请求解析、响应编码、会话令牌与跨站校验、下载票据、静态资源、HTTP 服务本体 |
| app/services/ | 业务逻辑 | 连接管理器（增删改查 + 会话上限）、会话状态机、目录与预览、上传下载的预检与语义 |
| app/ssh/ | 协议与子进程 | ssh 命令行构造、known_hosts 与指纹、自实现的 SFTP v3 编解码、传输层与诊断、密码辅助程序 |
| app/models/ | 数据模型 | 连接（connection.py）、目录条目（entry.py）与各自的校验 |
| app/core/ | 配置与错误 | 配置默认值/校验/原子保存（config.py）、错误码与 HTTP 状态映射（errors.py） |
| app/utils/ | 通用工具 | 原子写文件、远程路径处理、日志脱敏、日志初始化 |
| frontend/ | 前端 | 原生 HTML/CSS/JS，11 个 ES 模块，无框架、无构建、无外网资源 |
| tests/ | 测试 | unit / integration / security / fixtures 四个子目录 |

**目录归属与命名不在这里复述**：以规划文档 §5、§5.1 与 docs/PROJECT_STRUCTURE.md 为准（那里有顶层布局、归属判定顺序、各目录纪律表与自检清单）。

### 1.2 依赖方向

请求自上而下流动，依赖只允许向下：

    frontend（浏览器）→ app/api/ → app/services/ → app/ssh/ → 目标机 sshd
                                          ↓
                                app/models/ · app/core/ · app/utils/

- app/ssh/ 只依赖 app/core/errors.py、app/utils/（paths、atomic）与自身包内模块，**不依赖 services 与 api**（实测：对 app/ssh/ 做 import 扫描，命中的只有 app.core.errors、app.utils.atomic、app.utils.paths、app.ssh.*）。这条边界是 SFTP 层能被单独驱动的前提（见 5.4）。
- 业务规则写在 services，不写在 handlers；handlers 只做「取参数 → 调服务 → 编码响应 → 把 AwfmError 翻成 HTTP」。
- 配置只在 app/core/config.py 里解析与校验。别在别处直接读 JSON 文件。

---

## 2 环境准备

### 2.1 必需项

| 项目 | 要求 | 实测/依据 |
| --- | --- | --- |
| Python | 3.12（命令是 python；本机没有 python3） | 阶段 01 实测 3.12.10；见 docs/reports/PHASE-01-ENVIRONMENT.md |
| OpenSSH 客户端 | ssh 可执行文件能被找到 | 实测 OpenSSH_for_Windows_9.5p2，C:\Windows\System32\OpenSSH\ssh.exe |
| 目标机 | Linux + sshd + sftp 子系统 | 需求文档的目标机为 Linux（优先 CentOS Stream 10） |
| 管理员权限 | **不需要** | 程序只读写项目目录下的 data\ 与 logs\ |

### 2.2 不需要装任何依赖

后端运行时第三方依赖数为 0（需求 N-02，决策 D-002）：**没有 pip install 这一步**，仓库里也没有 requirements.txt 之类的依赖清单。系统 OpenSSH 被视为环境前提，不算 Python 依赖。

### 2.3 跑单元测试

在项目根目录执行：

    python -m unittest discover -s tests/unit -t .

tests/unit/ 下现有 9 个用例模块：test_paths.py、test_errors.py、test_entry.py、test_redact.py、test_atomic.py、test_config.py、test_connection_model.py、test_ssh_launcher.py、test_known_hosts.py。**本文刻意不写死用例数**：仓库可能正在被并行修改，用例数会变；看命令自己打印的「Ran N tests」。

两个实测到的坑：

1. Windows PowerShell 5.1 会把子进程写到 stderr 的内容当成错误记录，直接把输出重定向到文件更可靠：

       python -m unittest discover -s tests/unit -t . > $env:TEMP\awfm-unittest.txt 2>&1
       Get-Content $env:TEMP\awfm-unittest.txt -Tail 5

2. 只要测试文件在跑的同时被别的会话改动，结果就可能一会儿红一会儿绿。**改完代码先跑一遍再下结论**，别拿上一次的输出说事。

写单元测试时的既有约定（可照抄的样板）：协议编解码与已知错误源必须有单测钉死 —— 例如 SFTP 响应包**第一字段是请求 id**、MKDIR/SETSTAT 的**属性字段是完整 ATTRS**（决策 D-011 的「代价」一节明确要求这两点写单测）；配置模板与内置默认值的一致性由 test_config.py 通过 example_config_text() 断言。

### 2.4 集成测试与测试床

**现状（2026-10-15）**：tests/integration/ 里只有 __init__.py，**还没有任何集成用例**。所以下面只是搭建测试床的概述，用例怎么写、覆盖哪些路径，以 **docs/TEST_PLAN.md** 为准 —— 细节见 docs/TEST_PLAN.md。

测试床（决策 D-012）：在 WSL2 Ubuntu 内以**普通用户身份**运行 sshd，监听 127.0.0.1:2222，配置与密钥都在 WSL 的 ~/.awfm-testbed/ 下。Windows 侧用一条连接指向它（现有开发配置里的连接 id 是 wsl-testbed，用户 aimu，密钥 data\testbed\id_ed25519）。选它的理由：零提权（非 root 的 sshd 会跳过特权分离）、WSL2 的 localhost 转发让 Windows 侧直连、脚本化后可随时重建。

必须记住的代价与边界：

- WSL 测试床的 UID/GID 与真实 CentOS 目标机不同，且 WSL2 的 localhost 转发是 WSL 特性 —— **它只是开发期测试床**；规划文档 §7.2 要求的端到端验证要在真实 CentOS 虚拟机上补做（阶段 05）。
- 测试床没有 sudo，任何需要 root 的验证（PAM、UsePAM yes、特权端口）**不在覆盖范围内**，不得据此声称已验证。
- D-012 记录的配套脚本是 scripts/testbed_wsl.sh（WSL 内执行、幂等）。**截至 2026-10-15，仓库里还没有 scripts/ 目录**，当前的测试床搭建脚本是 .temp/ 下的临时脚本（如 .temp\wsl_start_sshd.sh、.temp\wsl_tb.sh）；正式脚本落地后应放到 scripts/ 并更新 D-012 的指向。

### 2.5 安全测试

tests/security/ 目前同样只有 __init__.py，**尚无用例**。该目录要覆盖的是令牌校验、Host 头与跨站校验、票据绑定等边界（对应 app/api/security.py 与 app/api/tickets.py），具体分工见 docs/TEST_PLAN.md。

---

## 3 代码规范

### 3.1 一切文本 I/O 显式钉 UTF-8（决策 D-013）

- 程序启动先调 app/utils/logging_setup.py 的 pin_stdio_encoding()，把 sys.stdout / sys.stderr reconfigure 成 UTF-8（errors="replace"）；
- 所有 open()、日志文件、JSON 读写都显式传 encoding="utf-8"（例如 app/core/config.py:399 读配置、app/utils/atomic.py:27 原子写、app/ssh/askpass.py 的读写都带 newline 与 encoding）；
- subprocess 的文本管道同样显式指定编码；启动脚本设 PYTHONUTF8=1。

**为什么**：Python 在 Windows 上默认 stdout 编码是 GBK，向控制台打印一个 emoji 文件名就会抛 UnicodeEncodeError 并终止程序。文件管理器必然要处理非 ASCII 文件名，这不是边角情况。**新代码不要省这个参数**，省下来的代价是别人机器上的崩溃。

### 3.2 subprocess 只允许出现在 app/ssh/

实测全仓只有两处 import subprocess：app/ssh/known_hosts.py:42（采集主机密钥）与 app/ssh/sftp_transport.py:23（SFTP 通道）。**别在 services 或 api 里另起进程** —— 连接的生命周期、超时与回收都归 ssh 层与会话层管，散落的子进程会直接破坏验收项 T-013（退出时不留下孤儿 ssh 进程）。

两条硬规则：

1. 只用 argv 列表传参，**从不 shell=True**（app/utils/paths.py 的模块 docstring 把这条写成了设计前提：因为不做 shell 解析，路径里除 NUL 外的任何字符都不必拒绝）；
2. 命令行的构造集中在 app/ssh/ssh_launcher.py，别在调用点手拼字符串 —— 主机密钥策略、BatchMode、身份文件等选项之间有耦合（例如密码认证必须 BatchMode=no，因为 OpenSSH 的 userauth_passwd() 在 batch mode 下直接返回失败）。

### 3.3 类型注解

公开函数与方法都写完整注解，返回值用具体结构（dict 也要在 docstring 里写清键），构造参数里的可选开关用关键字参数声明。可参照的既有写法：app/services/connection_manager.py:129 的 def create_connection(self, payload: dict) -> dict:。

### 3.4 docstring 写「为什么」，不写「做什么」

函数名已经说明了做什么，docstring 的价值在于记录**当时为什么这样选、代价是什么**。仓库里现成的样板：

- app/utils/paths.py 的模块 docstring 解释**为什么不折叠 `..`**：若 link 指向 /etc，/home/a/link/../x 的真实 POSIX 语义是 /x 而非 /home/a/x，按字面折叠会改变语义；因此它只做形式校验，需要规范形态就向服务端要 REALPATH。
- app/ssh/ssh_launcher.py 的 build_sftp_command docstring 写明为什么密码模式必须 BatchMode=no、为什么 GlobalKnownHostsFile 也要指向项目文件（否则用户 ~/.ssh/known_hosts 里的旧记录会让首次确认被跳过）。
- app/api/handlers.py 里关于主机密钥变化的注释写明：界面要明确告诉用户去改哪个文件，**不提供一键接受**。

注释与 docstring 用中文，和现有代码保持一致。

### 3.5 前端：h() + textContent，绝不拼 HTML

frontend/assets/js/util.js 开头两条纪律（原文）：**一律用 textContent，绝不拼 innerHTML** —— 文件名来自远端机器，里面完全可能包含 script 标签或属性注入片段，把它们当 HTML 处理就是一个远程可控的 XSS；h() 只支持 text，没有 html 选项。

实测证据：整个 frontend/ 目录里 **innerHTML / insertAdjacentHTML / outerHTML 零命中，模板字符串（美元加大括号）也零命中**。这不是风格洁癖，而是把注入面直接砍掉：所有节点都由 util.js:37 的 h(tag, attrs, ...children) 用 createElement / createTextNode 构造，字符串子节点走 createTextNode。

**新增界面代码请沿用这个模式**：要插一段可变文本就传 text 属性或子节点，不要为了排版方便去拼 HTML 字符串，也不要用模板字符串拼节点。

### 3.6 错误与文案

- 业务错误一律抛 AwfmError 的子类（app/core/errors.py），由 API 层统一翻译成响应；错误码与 HTTP 状态的映射**是 API 契约，改它必须同步 docs/API.md**（该文件已在仓库里）。
- 用户可见文案（message / detail）写中文、写清下一步动作。同一件事不要在两层写两套说法：能在 handlers 里给出「请回到界面重新点击下载」这种指引的，就别让底层抛英文。
- 敏感内容不入日志：默认 redact_secrets=true 时 logging_setup 会挂上 RedactingFilter；新增日志语句时不要把凭据类内容拼进消息。

---

## 4 新增一条连接：完整调用链

以界面上点「+ 新增」→ 填表 → 提交为例，一次改动要碰的层：

| 步骤 | 位置 | 做什么 |
| --- | --- | --- |
| 1 | frontend/assets/js/connections.js（openConnectionForm 与提交处理） | 收集表单字段，payload 字段名固定为 name / host / port / username / auth_method / identity_file / note / allow_write |
| 2 | frontend/assets/js/api.js:95 createConnection(payload) | 调 request()（api.js:47），带 X-AWFM-Token 头，POST /api/connections |
| 3 | app/api/handlers.py:65 create_connection | 解析请求体、校验形状，调连接管理器 |
| 4 | app/services/connection_manager.py:129 create_connection | 生成 id（由 name/host 派生 + uuid 片段），组装 Connection |
| 5 | app/models/connection.py | 逐字段校验（id 正则、host 字符集、port 范围、username 长度等）；name 为空时回填「用户名@主机」 |
| 6 | app/services/connection_manager.py:141 | 调 app/core/config.py 的 save_config → app/utils/atomic.py 原子写回 data\config.json；接口返回后前端 refreshConnections 重绘侧栏 |

**加一个字段时不要只改一端**，至少要动这几处（否则会出现「界面填了但重启就丢」或「配置文件里多出未知字段被拒」）：

1. app/models/connection.py 的字段定义、校验与已知字段列表（未知字段会被显式拒绝，不是静默忽略）；
2. config/config.example.json 模板与 app/core/config.py 的 DEFAULTS（test_config.py 会断言两者一致）；
3. app/core/config.py 的 to_dict / parse_config（配置的读写是对称的）；
4. 前端表单、payload 与展示（connections.js）；
5. docs/API.md（接口契约变了）。

---

## 5 调试技巧

### 5.1 先跑自检

    python app\main.py --check

输出逐项列出 Python 版本、ssh 可执行文件、前端资源、数据/日志目录可写性、信任库、主机密钥策略、监听地址与已配置连接数，任一失败会以退出码 1 结束。用户手册第 3.1 节有逐行解释，这里只强调一点：**它是发行验收清单里的第一条命令**（T-012），改完环境相关代码先跑它。

### 5.2 日志

- 文件：logs\awfm.log（同时输出到 stderr），格式 `时间 级别 [logger 名] 消息`；
- 滚动：单文件 2 MiB，保留 3 个备份；日志目录建不出来只警告不阻止启动；
- 级别：改配置里的 security.log_level，或临时用 python app\main.py --log-level DEBUG；
- 脱敏：security.redact_secrets 为 true 时挂 RedactingFilter；
- 排查连接问题时把级别开到 DEBUG，日志里能看到状态机与会话回收（例如「活动会话数达到上限 N，回收最早的会话 x」）。

### 5.3 SFTP 层的诊断信息

app/ssh/sftp_transport.py 提供：

- stderr_text()（第 298 行）：返回 ssh 子进程的 stderr 文本，主机密钥校验失败的判定就靠它；
- diagnostics()（第 308 行）：取 stderr 最后 6 行，拼上「ssh 退出码=<code>」，用「；」连接；没有内容时返回「ssh 未输出诊断信息」。**它刻意不返回完整 stderr**，因为里面可能含主机名与用户名；
- transact()（第 326 行）：发一个请求并等响应，超时与错误路径普遍把 diagnostics() 拼进 detail —— 所以你在界面/日志里看到的错误详情，多半就是这里带出来的。

### 5.4 单独驱动连接层（.temp\probe_ops.py 那种写法）

有些能力（写操作属规划文档 §3.1 的 P2）**还没有通过 HTTP 暴露**，这时不要为了调试去改 handlers，直接驱动连接层。现成样板是 .temp\probe_ops.py，核心就几行：

    import sys
    sys.path.insert(0, ".")

    from app.core.config import load_config, DEFAULT_CONFIG_PATH
    from app.services.connection_manager import ConnectionManager
    from app.utils.logging_setup import pin_stdio_encoding

    pin_stdio_encoding()
    config = load_config(DEFAULT_CONFIG_PATH)     # 相对路径以项目根为基准，不受 cwd 影响
    manager = ConnectionManager(config)
    manager.connect("wsl-testbed")                # 配置里的连接 id
    client = manager.session("wsl-testbed").client
    # 之后直接调 client.listdir / stat / mkdir / upload_stream / download_chunks / rename / remove / rmdir

要点：

- 先 sys.path.insert(0, ".")，并在**项目根目录**执行，否则 import app 会失败；
- 一定先 pin_stdio_encoding()，否则带非 ASCII 文件名的输出会在 Windows 控制台上炸；
- 探针脚本写 .temp\ 下，用「打印 PASS/FAIL + 收集失败项」的 self-check 风格（probe_ops.py 的 check() 就是），跑完把结论抄进报告；
- 这类脚本**不要提交**：.temp/ 是可随时清空的会话中转目录。

### 5.5 对照真实 ssh 命令行

怀疑是 ssh 选项组合的问题时，用 app/ssh/ssh_launcher.py 的 build_sftp_command 构造出与程序一致的命令行，和手工执行的 ssh 做对照；只读探测（能连上吗、指纹对不对）也可以用系统 ssh 手工复现：

    ssh -p 2222 aimu@127.0.0.1

---

## 6 提交与过程证据

### 6.1 规划文档 §6.2 要求的过程证据

| 变更类型 | 必须留存的证据 |
| --- | --- |
| 需求变更 | docs/CHANGELOG.md |
| 技术选型 | docs/DECISIONS.md |
| 代码变更 | Git 提交 |
| 自动化测试 | 测试脚本与运行日志 |
| 手工测试 | 测试记录与截图 |
| 问题追踪 | docs/reports/ 下的报告 |
| 构建过程 | scripts/build.* |
| 发布验证 | 校验和与版本清单 |

### 6.2 本项目怎么执行

- **阶段化提交**：按规划文档 §6.1 的阶段推进，一个阶段内的改动整理成清晰的若干次提交（改了协议就单独一次，别把「顺手重构」和「修协议 bug」塞进同一次），提交信息里写清「为什么改」。
- **DECISIONS.md 在选型发生的那一刻写**：决策要记备选方案、理由与代价三段（现有 D-001~D-014 都是这个格式）。被推翻的决策不要删，标成「作废」并写被谁取代（例如 D-004 作废、由 D-011 取代）。
- **CHANGELOG.md 在用户可见行为变化时写**：新增能力、错误文案改变、配置字段增删、兼容性变化都要记。
- **报告放 docs/reports/**：阶段报告按 docs/reports/ 现有模板写（PHASE-01、PHASE-02 就是样板：实测命令、实测输出、风险编号 R-xx、结论与遗留）。

**现状（2026-10-15）**：docs/CHANGELOG.md 与 scripts/ 目录**尚未创建**（README 已把它们列为计划项）。在它们落地之前，需求与构建类证据只能先记在阶段报告里，不要假装文件已存在。

### 6.3 提交前自检

    python app\main.py --check
    python -m unittest discover -s tests/unit -t .

外加三条纪律（来自 AGENTS.md）：

1. data\、logs\、dist\ 已在 .gitignore，**不要把运行期文件提交上去**；
2. 私钥、密码、host key 私密文件不得出现在 config\、docs\、tests\fixtures\ 中会被提交的位置；
3. frontend/ 内禁止出现任何指向外网的 URL（验收项 T-002，离线可用）。

---

## 参考

源码（相对项目根，正斜杠）：

- app/main.py —— 入口、CLI 参数、--init-config、--check、启动与停机
- app/__init__.py —— 版本号与「只用标准库」的说明
- app/api/handlers.py、app/api/security.py、app/api/tickets.py、app/api/http_server.py、app/api/request.py、app/api/responses.py、app/api/router.py
- app/core/config.py、app/core/errors.py
- app/models/connection.py、app/models/entry.py
- app/services/connection_manager.py、app/services/session.py、app/services/filesystem.py、app/services/transfer.py
- app/ssh/ssh_launcher.py、app/ssh/known_hosts.py、app/ssh/sftp_transport.py、app/ssh/sftp_protocol.py、app/ssh/sftp_client.py、app/ssh/askpass.py
- app/utils/atomic.py、app/utils/paths.py、app/utils/redact.py、app/utils/logging_setup.py
- frontend/assets/js/util.js、frontend/assets/js/api.js、frontend/assets/js/connections.js 等 11 个 ES 模块
- config/config.example.json
- tests/unit/ 下的 9 个用例模块（test_config.py 含模板与默认值同步断言）
- .temp/probe_ops.py —— 单独驱动连接层的探针写法样板

文档依据：

- .md（规划文档）—— §3.1 功能分级、§5/§5.1 目录规则、§6.1 阶段划分、§6.2 过程证据、§7.2 测试层级
- docs/PROJECT_STRUCTURE.md —— 目录归属判定与各目录纪律
- docs/REQUIREMENTS.md —— 功能与非功能需求（N-02 运行时依赖数为 0）
- docs/DECISIONS.md —— D-002、D-006、D-009~D-014（尤其 D-011 SFTP 自实现、D-012 测试床、D-013 UTF-8）
- docs/API.md —— 接口契约（错误码与路径改动需同步）
- docs/reports/PHASE-01-ENVIRONMENT.md —— 环境实测
- docs/reports/PHASE-02-SPIKE.md —— SFTP 协议实测与两个高频错误源
- docs/TEST_PLAN.md —— 测试分层与测试床细节（用例部分以它为准）
- AGENTS.md —— 顶层白名单、目录纪律、凭据纪律
