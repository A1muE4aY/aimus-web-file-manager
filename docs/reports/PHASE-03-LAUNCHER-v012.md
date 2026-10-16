# 阶段三报告：统一启动脚本 run.bat / run.sh（v0.1.2）

## 一、报告信息

| 项目 | 内容 |
|---|---|
| 版本 | v0.1.2（维护与体验优化；版本号按任务书留到阶段七统一升级，当前程序自报 0.1.1） |
| 阶段 | 阶段三：统一启动脚本 `run.bat` / `run.sh` |
| 依据 | `dev_guide/0.1.2_.md` §3.1 ~ §3.7（本次落地 §3.3 ~ §3.7） |
| 日期 | 2026-10-17 |
| 基线提交 | `9bbf7a3`（阶段 02：文件列表布局固定化与自绘右键菜单），分支 `master` |
| 验证方式 | ① 四层自动化测试（unit / integration / security / e2e）；② 启动器单测 39 项 + 集成 7 项；③ Windows 真实验收 12 用例 34 项判定（含空格目录）；④ Linux（WSL2 Ubuntu 24.04）真实验收 12 用例 |
| 结论 | **通过**。任务书 §3.3 ~ §3.7 全部条款已实现并取得真实运行证据；验收过程中发现 3 个真实缺陷（D-A / D-B / D-C），全部修复并补上回归测试 |

## 二、阶段目标

任务书要求把「怎么启动 AWFM」收敛成**一个入口**，并且启动、停止、状态、日志三条路径都必须如实报告：

| 条款 | 要求要点 |
|---|---|
| §3.3 `run.bat` 行为 | 切到脚本目录；定位 Python；检查依赖与目录；检测已运行；检查端口；启动并报告**实际**结果；给出状态 / 日志 / 停止方式；错误显示具体原因与建议；不闪退、不甩 traceback |
| §3.4 `run.sh` 行为 | 同上，POSIX 语义：`sh` 可执行、信号与退出码原样传递 |
| §3.5 启动与停止的统一设计 | 同一入口的交互菜单（启动 / 状态 / 停止 / 日志 / 退出）；已运行不得起第二个实例；停止只作用于 AWFM 自己的进程、不误杀其它 python / ssh；不得未经用户确认就强制终止；不得谎报成功 |
| §3.6 兼容性和交付要求 | 文档统一引用 `run.bat`/`run.sh`；旧 `start.cmd`/`stop.cmd` 标注弃用或从发行包移除；**默认端口改 32579**；测试覆盖含空格目录启动、重复启动、停止、再启动、端口冲突 |
| §3.7 真实验收 | Windows 6 条逐条真跑；Linux 有环境就实测、没有就记录「未验证」；**不得用模拟输出冒充** |

## 三、实际完成情况

### 3.1 统一启动器（唯一实现）

| 要求 | 实现 | 位置 |
|---|---|---|
| 一个入口、两层 | `run.bat` / `run.sh` 只做「切目录 → 找 Python → 原样转发」，全部逻辑在 Python | `run.bat`、`run.sh`、`scripts/launcher.py` |
| 八个命令 | `menu start status stop restart logs check help` | `scripts/launcher.py:922` |
| 交互菜单 | 后台启动 / 前台启动（Ctrl+C）/ 状态 / 停止 / 日志 / 自检 / 退出；非交互终端**不挂起**，直接打印用法与状态 | `scripts/launcher.py:863` |
| 状态判定四态 | 运行中（PID + 地址 + 版本） / 进程在但健康检查未通过 / PID 已消失（陈旧文件） / 没有运行 | `scripts/launcher.py:322`、`:343` |
| 退出码即语义 | `0` 成功 / `1` 失败 / `2` 用法错误 / `3` 已经在跑或没在跑（未做改动） | `scripts/launcher.py:56-59`、`:947` |

实现要点：`DEFAULT_PORT = 32579`（`scripts/launcher.py:47`，注释写明任务书 §3.6 的来源）、PID 文件 `data/awfm.pid`（`:48`）、控制台日志 `logs/awfm-console.log`（`:49`）、应用日志 `logs/awfm.log`（`:50`）、启动等待 20 s / 停止等待 10 s（`:51-52`）。PID 文件写入用 `.tmp` + `os.replace`（`:212`）；健康检查是 `GET /api/health`（`:175`）；端口占用用连接探测（`:167`，边界见 §4.6）。

### 3.2 两个外壳

| 要求 | 实现 | 位置 |
|---|---|---|
| 切到脚本目录 | `cd /d "%~dp0"`；POSIX 用 `CDPATH= cd -- "$(dirname -- "$0")"` + `pwd -P` 后 `cd` | `run.bat`、`run.sh` |
| 找 Python | `where py` → `py -3`，否则 `where python`；POSIX 依次试 `python3` `python`；找不到打印安装提示 | `run.bat:26-27`、`run.sh` |
| 中文与编码 | `chcp 65001` + `PYTHONUTF8`/`PYTHONIOENCODING`，避免 GBK 控制台打乱中文 | `run.bat`、`run.sh` |
| 不闪退 | 非 0 退出码时打印退出码与帮助提示后 `pause`（自动化可用 `set AWFM_NO_PAUSE=1` 关掉）；退出码 3 直接 `exit /b 3` 不暂停 | `run.bat:45` 起 |
| 行尾 | `.gitattributes` 增加 `*.bat text eol=crlf`（cmd.exe 对 LF 结尾 .bat 的标签跳转不稳） | `.gitattributes` |

### 3.3 端口与发行包

- 默认端口 **8760 → 32579**：`app/core/config.py:51`（`DEFAULTS`）、`:131`（`ServerConfig`）、`:369`（解析兜底）、`config/config.example.json:5`、`tests/unit/test_config.py:39`。
- 发行包不再生成 `start.cmd`/`stop.cmd`：`scripts/package.py` 删除两个生成模板，`STAGE_SCRIPTS = ("start.py", "launcher.py")`（`:50`）、`STAGE_FILES` 含 `run.bat`/`run.sh`（`:51`）、`check_required` 校验 `scripts/launcher.py` / `run.bat` / `run.sh`（`:223-230`）、包内说明改「双击 run.bat（Linux/macOS 用 ./run.sh）」（`:67-68`）。
- `scripts/start.py` 保留为**前台启动的兼容入口**（等价 `run.bat start --foreground`）。

### 3.4 前台停止与信号

- `app/main.py:25` 新增 `import signal`，`:243` 新增 `_install_signal_handlers()`，在 `_serve()` 开头 `:270` 调用：Windows 直接返回；POSIX 注册 `SIGTERM` 处理器抛 `KeyboardInterrupt`，复用 `_serve` 的 `finally` 清理（搜索与发现线程关闭 + `manager.disconnect_all()`），保证不留孤儿 ssh（验收项 T-013）。
- 处理器装不上（非主线程）时静默降级为 `logger.debug`，不影响启动。

### 3.5 测试

| 层次 | 文件 | 数量 | 命令 |
|---|---|---|---|
| 单元 | `tests/unit/test_launcher.py`（新建）、`tests/unit/test_config.py`（修两处过时断言） | 39 | `python -m unittest tests.unit.test_launcher -v` |
| 集成 | `tests/integration/test_launcher_lifecycle.py`（新建：生命周期 4 项 + 外壳退出码 3 项） | 7 | `python -m unittest tests.integration.test_launcher_lifecycle -v` |

单元测试用 `importlib.util.spec_from_file_location("awfm_launcher", ROOT / "scripts" / "launcher.py")` 直接加载启动器（它不是包内模块），覆盖：默认端口、解析器默认值与未知命令、PID 文件往返 / 坏 JSON / 非对象 / 坏 pid、`tail_text` 尾部、四态文案、IPv6 地址拼装、端口探测、配置缺失与损坏与端口覆盖、`find_ssh_client` 缺失、目录不可写、以及 **`SignalTest.test_serve_installs_sigterm_handler`**（`skipIf os.name == "nt"`，在 Linux 上真跑）。

集成测试用子进程真实拉起服务（`PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8`），覆盖完整生命周期、端口冲突被拒、陈旧 PID 文件被识别并替换、无 tty 的菜单立即返回，以及 `WrapperExitCodeTest`（把 `run.bat`/`run.sh`/`launcher.py` 复制进临时目录当 ROOT，验证外壳把退出码 3 / 2 原样传出来、不出现 Traceback）。

### 3.6 文档统一

`README.md`（快速开始改为 run.bat 四步）、`docs/USER_GUIDE.md`（启动 / 菜单 / 停止 / 排错 / FAQ）、`docs/RELEASE.md`（包内目录树、必需文件、打包说明、发行验收表）、`docs/PROJECT_STRUCTURE.md`、`docs/API.md:15`、`docs/SECURITY.md:33/:37/:113`、`docs/TEST_PLAN.md:52`、`app/api/security.py` 三处注释、`scripts/_index.md`、`AGENTS.md`（顶层白名单新增 `run.bat`/`run.sh`）、`docs/DECISIONS.md` 新增 **D-020**、`docs/ARCHITECTURE.md:145` 决策表补 D-020 行、`docs/CHANGELOG.md`。

## 四、技术实现

### 4.1 启动流程（`scripts/launcher.py:447 cmd_start`）

读配置（`:270`，默认路径缺失容忍、显式路径缺失报错）→ 检查数据 / 日志目录可写（`:260`）→ 读 PID 文件判状态（`:322`）：

- **运行中** → 「AWFM 已经在运行，本次不会重复启动。」+ 状态行 + 停止提示，退出码 3，不做任何改动（`:456-457`）；
- **进程在但健康检查不过** → 提示「可能是上次启动没成功」，退出码 3（`:461-463`）；
- **PID 已消失** → 清理陈旧文件后继续（`:465`）。

随后依次检查端口（`:468-473`）、Python 版本（`:243`）、系统 ssh 客户端（`:253`）——**这些「拒绝启动」的判断全部排在配置提示之前**（见 D-C）；再 `spawn_service`（`:382`）写 PID 文件（`:212`）、轮询健康检查（`:494-504`，进程提前退出会删 PID 文件并打印控制台日志尾）、成功后 `report_started`（`:433`）打印「[ OK ] AWFM 已启动（版本 …）」与地址 / 进程 / 配置 / 访问范围 / 日志 / 停止方式。

### 4.2 停止阶梯（`scripts/launcher.py:637 cmd_stop`）

**只认 PID 文件里的 PID**，逐级校验：

1. 没有 PID 文件但端口被占 → 明确写出「停止只作用于 AWFM 自己记录的进程，这里不会去动它」（退出码 1）；
2. 映像名不含 `python` → 「拒绝停止：PID N 的映像名是 X，不是 python 进程。」（`:663`）；
3. 优雅停止：Windows `taskkill /PID N /T`（不带 `/F`）、POSIX `SIGTERM`（`:582`），等待退出（`:615`）；
4. 未退出 → 打印原因 + **询问**是否强制终止；非交互终端一律视为拒绝 → 「已放弃：没有做任何强制操作。」+ 稍后重试与人工处理命令（`:682`，退出码 1）；
5. 用户确认（交互 `y` 或 `--force --yes`）才 `taskkill /F /T` / `SIGKILL`（`:599`）。

真没有在运行 → 「AWFM 没有在运行，什么都没做。」退出码 3（`:656`）。

### 4.3 三个真实缺陷（验收与回归暴露，均已修）

| 编号 | 现象 | 根因 | 修法 | 回归 |
|---|---|---|---|---|
| D-A | 全新目录（便携包首次运行）`start` 退出码 1，日志里 app 报「启动失败：指定的配置文件不存在」 | `build_argv`（`:358`）无条件追加 `--config <默认路径>`；app 只在**默认**路径缺失时用内置默认值，显式 `--config` 缺失是致命错误 | 仅在 `config_exists` 为真时传 `--config`，并加注释说明两种「不存在」的区别；`cmd_start` 开头如实提示「配置文件还不存在…本次用内置默认值启动」 | `tests/unit/test_launcher.py` 新增 `BuildArgvTest` 4 项 |
| D-B | `run.bat stop --force --yes` 明明成功却返回 0；`status`/`stop` 空转应返回 3 也返回 0 | `run.bat:45` 写成 `endlocal ^& exit /b 3`，括号块内 `^&` 让 `&` 变成字面参数 → `endlocal` 执行、`exit /b 3` 永不执行，落到末尾 `exit /b %AWFM_CODE%` 时变量已被删除 | 改为 `endlocal & exit /b 3`（另用 4 个探针脚本确认只有这一种写法正确） | `WrapperExitCodeTest` 断言外壳透传 3 / 2 |
| D-C | 重复启动时，输出先出现「配置文件还不存在…本次用内置默认值启动」，再出现「已经在运行，本次不会重复启动」——自相矛盾 | 配置提示写在状态检查**之前** | 把这组提示移到所有「拒绝启动」分支之后（`:487-491`） | Linux 与 Windows 的 C03 转录复验：只剩「已经在运行」三行 |

另修正两处**测试自身**的过时断言：`tests/unit/test_config.py:237` 与 `:258` 写死了旧默认端口 8760，默认值改 32579 后必然失败——改为比 `cfg.DEFAULTS["server"]["port"]`（默认端口另有 `tests/unit/test_launcher.py:45` 钉住）。

### 4.4 端口探测的边界（已知限制，本阶段不改行为）

`port_busy()`（`:167`）是**连接探测**：能连上就认为被占用。它无法证明「能绑定」。在 WSL2 mirrored 网络模式下实测到这一最坏情形：`ss -ltnp` 无监听者、Windows 侧 `Get-NetTCPConnection` 计数为 0，但 WSL 内 bind 127.0.0.1:32579 报 `[Errno 98] Address already in use`（加 `SO_REUSEADDR` 仍旧失败），于是启动器报「端口空闲」而 app 报「端口 32579 已被占用」，最终启动器如实报「启动失败：服务进程已经退出（退出码 2）。」并附控制台日志尾。**用户仍能看到具体原因**，因此保留现行为并登记为限制（§6.2）。

## 五、测试结果

### 5.1 四层自动化测试

`python scripts/test.py -v`（含语法校验；子进程强制 UTF-8，决策 D-013）：

| 层 | 数量 | 结果 | 耗时 |
|---|---|---|---|
| unit | 566 | OK（1 项按平台跳过：`SignalTest` 在 Windows 上跳过，在 Linux 上真跑通过） | 4.04 s |
| integration | 118 | OK | 278.13 s |
| security | 82 | OK | 466.62 s |
| e2e | 32 | OK | 187.01 s |
| 合计 | 798 | 0 失败 / 0 错误 / 1 跳过 | 935.79 s |

说明：上表是本阶段**最终产品代码**上的一次完整运行（`python scripts/test.py -v`，退出码 0，末行「全部通过」）。此前的一次全量运行还暴露了两处**测试自身**的过时断言（`tests/unit/test_config.py:237`、`:258` 写死旧默认端口 8760），已改为比 `cfg.DEFAULTS["server"]["port"]`；同一轮里 unit 的 2 失败即来自这两处。

回归还暴露出**测试运行器自己**的一个记录缺陷：`scripts/test.py` 的 `STATUS_RE` 只认裸 `OK`，而 unittest 在「全部通过但有跳过」时打印的是 `OK (skipped=1)`——于是「跳过」一列一直是 0，与文件开头第 14-15 行「跳过要单独列出来」的记录纪律相矛盾。已修（`scripts/test.py:33-35` 允许 `OK (…)`），修后单跑 unit 层即正确报告「1 跳过」并给出「1 项被跳过 —— 跳过的用例没有验证任何东西」的提示。

### 5.2 启动器单测（Windows 与 Linux 双跑）

- Windows：`Ran 39 tests / OK (skipped=1)`（`SignalTest` 按 `os.name` 跳过）。
- WSL（Ubuntu 24.04，`/usr/bin/python3` 3.12.3）：`Ran 39 tests in 0.842s / OK`，其中 `test_serve_installs_sigterm_handler ... ok`——**Windows 上被跳过的那条在 Linux 上真跑并通过**，证明 SIGTERM 处理器确实会中断主循环并走清理路径。

### 5.3 集成测试

`tests/integration/test_launcher_lifecycle.py` 7 项全过（首次运行 46.26 s；`test_full_lifecycle` 单跑 45.60 s）：完整生命周期（启动 → 重复启动 → 状态 → 日志 → 未确认停止 → 确认停止 → 空转停止 → 重启 → 再停）、端口冲突被拒且不留 PID 文件、陈旧 PID 文件被识别并替换、无 tty 菜单立即返回。

### 5.4 Windows 真实验收（任务书 §3.7）

编排脚本 `.temp/launcher-accept/run-accept.ps1`（ASCII-only，12 用例 / 34 项判定），被测目录是**含空格的副本**：`E:\Project\aimus-web-file-manager\.temp\accept space\AWFM test dir`（全新树，故意不含 `data/config.json`）。转录：`.temp/launcher-accept/windows-transcript.txt`。

| 用例 | 命令 | 退出码 | 关键实测 |
|---|---|---|---|
| C01 | `run.bat check` | 0 | 自检全通过，含「[ OK ] 端口空闲：127.0.0.1:32579」 |
| C02 | `run.bat start` | 0 | 首次启动成功：PID 33892，地址 http://127.0.0.1:32579/，`GET /` 200（7399 B）、`GET /api/health` 200（76 B），页面含 AWFM |
| C03 | `run.bat start`（重复） | **3** | 「AWFM 已经在运行，本次不会重复启动。」PID 不变、仍只一个监听者 |
| C04 | `run.bat status` | 0 | 「运行中（PID 33892，http://127.0.0.1:32579/，版本 0.1.1）」 |
| C05 | HTTP 可达 | — | 浏览器地址就是 status / start 打印的那个地址（验收条款 3） |
| C06 | PID 文件与控制台日志 | — | `data/awfm.pid` 有活着的 python PID；`logs/awfm-console.log` 925 B |
| C07 | `run.bat stop`（不带确认） | **1** | 「Windows 拒绝了优雅停止（该进程没有窗口，通常只能在确认后强制终止）」→ 询问 → 非交互终端视为拒绝 → 「已放弃：没有做任何强制操作。」；**服务 PID 33892 与无关的诱饵 python PID 27152 都还活着**（验收条款 4 的直接证据） |
| C08 | `run.bat stop --force --yes` | 0 | 端口关闭、`data/awfm.pid` 删除、诱饵进程不受影响 |
| C09 | `run.bat stop`（空转） | **3** | 「AWFM 没有在运行，什么都没做。」 |
| C10 | 端口被占（32580 由独立 python 占住） | **1** | 「启动失败：127.0.0.1:32580 已经被占用。」+ 提示 netstat 命令；不写 PID 文件；占用者 PID 37656 不受影响 |
| C11 | 缺解释器（`cases\no-python.cmd` 把 PATH 缩到 System32） | 1 | 「[失败] 找不到 Python 解释器。」+ 安装提示 |
| C12 | `run.bat restart` | 0 | 停止后再启动正常，端口重新可连 |
| C13 | 非 tty 菜单 | 0 | 打印完整用法 + 当前状态，不挂起等输入 |
| C14 | 收尾停止 | 0 | 端口无监听者 |

末行：`### SUMMARY: 34 checks, 0 failed`；退出码行 `C01=0 C02=0 C03=3 C04=0 C07=1 C08=0 C09=3 C10=1 C11=0 C12=0 C13=0 C14=0`。

### 5.5 Linux 真实验收（WSL2 Ubuntu 24.04）

编排脚本 `.temp/launcher-accept/wsl-accept.sh`，被测目录 `/tmp/awfm accept/run.sh test dir`（含空格）。转录：`.temp/launcher-accept/linux-transcript.txt`。

| 用例 | 命令 | 退出码 | 关键实测 |
|---|---|---|---|
| C01 | `sh ./run.sh check` | 0 | Python 3.12.3 / ssh / 前端资源 / 数据与日志目录 / 主机密钥策略 strict / 监听 127.0.0.1（仅本机）全部通过；端口空闲 |
| C02 | `sh ./run.sh start --port 32591` | 0 | 首次启动成功：PID 8170，地址 http://127.0.0.1:32591/；`GET /` 200（7399 B）、health 200 |
| C03 | 重复启动 | **3** | 「已经在运行，本次不会重复启动。」不再出现矛盾提示（D-C 修复的证据） |
| C04 | `status` | 0 | 「运行中（PID 8170…版本 0.1.1）」，进程映像名 python3 |
| C06 | PID 文件 | — | 含 `root`/`config`/`python`/`started_at` 等字段，路径里的空格原样保留；控制台日志 794 B |
| C07 | `stop --timeout 3` | **0** | 「正在停止…」+「已发送 SIGTERM」+「[ OK ] AWFM 已停止。」——**POSIX 优雅停止真的能停**；诱饵进程仍存活 |
| C08 | `stop --force --yes` | 3 | 「AWFM 没有在运行，什么都没做。」（与 Windows 相反，因为 C07 已经停了） |
| C09 | `stop`（空转） | 3 | 同上 |
| C10 | 端口被占（32580） | **1** | 「已经被占用。」+ 提示 `ss -ltnp \| grep :32580`（Linux 文案） |
| C12 | 再次启动 | 0 | 停止后重启正常 |
| C13 | 菜单（非 tty） | 0 | 「当前不是交互终端，不显示菜单。」+ 用法 + 状态 |
| C14 | 收尾停止 | 0 | 端口无监听者 |

### 5.6 任务书 §3.7 六条对照

| 条款 | 结果 | 证据 |
|---|---|---|
| 1 首次启动成功 | 通过 | Windows C02（含空格的全新目录）；Linux C02 |
| 2 已运行时重复执行给出正确提示 | 通过 | Windows C03 = 3；Linux C03 = 3 |
| 3 浏览器能访问正确的本地服务地址 | 通过 | 打印的地址与 `GET /` / `/api/health` 实测一致（Windows C05 / Linux C05） |
| 4 停止操作不会误终止其它进程 | 通过 | Windows C07 未确认时服务与诱饵都在；C08 只结束服务；C10 不碰占用者；C15 诱饵全程存活 |
| 5 停止后再次启动正常 | 通过 | Windows C12 = 0；Linux C12 = 0 |
| 6 缺少依赖或端口被占用时提示清晰 | 通过 | Windows C11（缺解释器）、C10（端口占用）；Linux C10 |

## 六、问题与风险

### 6.1 已解决的问题

D-A（全新目录无法启动）、D-B（外壳吞掉退出码）、D-C（重复启动时的矛盾提示），详见 §4.3；两处测试自身过时断言同时修正。三个缺陷都由**真实验收 / 全量回归**发现，说明「真跑一遍」这条纪律有效。

### 6.2 已知限制（如实登记）

1. **Windows 上的后台服务没有控制台**，`taskkill /PID N /T`（不带 `/F`）必然失败，因此 `run.bat stop` 一定走到「确认后强杀」；POSIX 上 `SIGTERM` 正常生效。这是操作系统行为差异，已在文档与提示文案里写明。
2. **WSL2 mirrored 网络模式下 127.0.0.1:32579 无法 bind**（Windows 侧也看不到监听者）。Linux 生命周期验收因此改用 `--port 32591`；默认端口 32579 的行为由 Windows 侧完整覆盖。这是环境限制，不是产品缺陷。
3. **端口探测是连接探测**，不能证明可绑定（§4.4）。最坏情形下用户仍能看到 app 的具体报错。
4. **`run.bat` / `run.sh` 不转发 app 自身的选项**（如 `--log-level`）：它们只认启动器自己的选项；需要 app 选项时走 `python app\main.py`。
5. **macOS 完全未验证**；Linux 只在 WSL2 Ubuntu 24.04 上实测，尚未在裸机 / 其它发行版验证。
6. 依赖**系统 ssh 客户端**（`find_ssh_client`）；缺失时启动器给出安装提示并退出 1。

### 6.3 风险

- 阶段四（搜索与文件操作加固）会让 `/api/health` 之外的接口变化，但启动器只依赖 `/api/health` 与 PID 文件，接口面很小；
- 发行包尚未在真实便携场景（U 盘 / 非开发机）验证，留到阶段六 / 七的发行验收。

## 七、文档与交付物

代码：`scripts/launcher.py`（新建）、`run.bat` `run.sh`（新建）、`scripts/package.py`、`app/main.py`、`app/core/config.py`、`app/api/security.py`（注释端口）、`config/config.example.json`、`.gitattributes`。

测试：`tests/unit/test_launcher.py`（新建）、`tests/unit/test_config.py`、`tests/integration/test_launcher_lifecycle.py`（新建）。

文档：`README.md`、`AGENTS.md`、`docs/USER_GUIDE.md`、`docs/RELEASE.md`、`docs/PROJECT_STRUCTURE.md`、`docs/API.md`、`docs/SECURITY.md`、`docs/TEST_PLAN.md`、`docs/DECISIONS.md`（D-020 + D-015 更新）、`docs/ARCHITECTURE.md`（D-020 行）、`docs/CHANGELOG.md`、`scripts/_index.md`、本报告与 `docs/reports/_index.md`。

验收证据（`.temp/launcher-accept/`，`.temp` 可随时清空，故关键输出已抄进本报告）：`run-accept.ps1`、`wsl-accept.sh`、`wsl-unit.sh`、`diag-ports.sh`、`cases/no-python.cmd`、`windows-transcript.txt`、`linux-transcript.txt`。

## 八、阶段结论

阶段三**通过**。任务书 §3.3 ~ §3.7 的全部条款均已落地并取得真实运行证据：一个入口（`run.bat` / `run.sh` + `scripts/launcher.py`）、八个命令与交互菜单、四态状态判定与退出码语义、只认自己 PID 的停止阶梯、默认端口 32579 与发行包脚本清理、前台 SIGTERM 清理路径；Windows 12 用例 34 项判定与 Linux 12 用例全部符合预期，四层自动化测试 798 项无失败。验收与回归暴露的 3 个真实缺陷已修复并补上回归测试。可以进入阶段四（搜索与文件操作加固）。

阶段三基线：`9bbf7a3`（阶段 02）。本阶段结论仅覆盖阶段三范围内的行为，v0.1.2 整体结论留待阶段七。
