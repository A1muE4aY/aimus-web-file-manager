# 阶段六报告：真实桌面 CU 验收（v0.1.2）

## 一、报告信息

| 项目 | 内容 |
| --- | --- |
| 版本 | v0.1.2（开发中；`app/__init__.py` 仍为 0.1.1，阶段七统一升号） |
| 阶段 | 阶段六 —— 真实桌面 CU 验收（任务书 §6，12 条） |
| 依据 | `dev_guide/0.1.2_.md` §6「真实桌面 CU 验收」（:571-590） |
| 日期 | 2026-10-17 |
| 基线提交 | `a9cae30`（阶段五收尾），分支 `master` |
| 验证方式 | cua_driver 真实桌面操作（Edge InPrivate 访问 `http://127.0.0.1:8790/`）+ 真实终端窗口（cmd、Windows PowerShell、WSL2 Ubuntu）+ 终端辅助命令核对 |
| 结论 | 12 条验收全部完成；发现并修复 1 个用户可见缺陷（`run.bat` 在 GBK 控制台下打印「不是内部或外部命令」假错误）并补回归测试；四层自动化见 §5.1。允许进入阶段七。 |

## 二、阶段目标

任务书 §6（`dev_guide/0.1.2_.md`:571-590）要求在有真实桌面与真实 SSH 服务端的条件下完成 12 条验收，
并给出两条硬约束：

- 允许终端做环境准备、日志查看和结果核对，但**不得用终端命令或直接 HTTP 请求替代本应由 CU 完成的交互**；
- 关键场景要保留截图、日志或操作轨迹，并**区分真实 CU 与辅助命令**。

| 条款 | 要求要点 | 落地位置 |
| --- | --- | --- |
| 1 | 启动 `run.bat`，观察状态提示与访问地址 | §3.2 第 1 条、§3.3（缺陷）、证据 42/43/45/54 |
| 2 | 文件列表中普通文件与超长文件名的显示 | §3.2 第 2 条，证据 05/11 |
| 3 | 操作按钮在不同行保持固定对齐 | §3.2 第 3 条，证据 11-narrow-view |
| 4 | 鼠标与键盘都能看到完整文件名 | §3.2 第 4 条，证据 05/20 |
| 5 | 真实连接 CentOS 主机并浏览目录 | §3.2 第 5 条，证据 01/15/17 |
| 6 | 搜索、预览、编辑入口未失效 | §3.2 第 6 条，证据 21/38/33 |
| 7 | 关闭写权限后编辑保存仍被拒绝 | §3.2 第 7 条，证据 23/27/28/29/33/35/36 |
| 8 | 停止并重启，无重复进程或端口残留 | §3.2 第 8 条，证据 46/47/48/50 |
| 9 | 在适用环境真实运行 `run.sh` | §3.2 第 9 条，证据 51/52 |
| 10 | 按 SSH 教程操作关键配置步骤并核对 | §3.2 第 10 条，证据 53 |
| 11 | 教程错误排查示例与真实错误相符 | §3.2 第 11 条，证据 53 |
| 12 | 启动脚本、教程、发行包三处一致 | §3.2 第 12 条，§4.5 |

## 三、实际完成情况

### 3.1 验收方法：真实 CU 与辅助命令的边界

- **被验对象**：阶段一至三在真实桌面上的可用性 —— 文件列表与操作列布局、搜索/预览/编辑入口、
  写权限开关、统一启动外壳、WSL 侧外壳、SSH 配置教程。
- **真实 CU**：用 `cua_driver_native_*` 系列工具在 2560×1440（缩放 125%）的真实 Windows 桌面上
  操作 Edge InPrivate 窗口与真实终端窗口。点击、双击、键盘、窗口还原、`run.bat` 的启动都走真实输入路径；
  终端窗口由 `launch_app` 以 ShellExecuteEx 打开（与资源管理器双击同一条路径）。
- **辅助命令**：只用于环境准备、日志查看、结果核对（读端口/进程/PID 文件、`python -m unittest`、
  `wsl -d Ubuntu` 取同一脚本的纯文本、PIL 裁图读截图文字），清单见 §5.4。
- **证据组织**：`.temp/cu-v012-stage6/`（本阶段，152 个文件：01~54 号桌面截图、同名 `-view.png` 裁图、crop 脚本）
  与 `.temp/cu-v012/`（阶段一至三的 CU 证据，28 个文件）。`.temp/` 是会话草稿目录，不提交。

### 3.2 十二条验收结果

| # | 结论 | 观察与证据 |
| --- | --- | --- |
| 1 | 通过 | 全新控制台启动 `run.bat` 后菜单干净：目录、`地址 http://127.0.0.1:8760/`、`状态：没有运行` 与 7 个菜单项；选 1) 后打印 `[ OK ] AWFM 已启动（版本 0.1.1）`、地址、`进程: PID 3660`、配置路径、`访问范围: 仅本机（security.allow_lan=false）`、日志路径与 `停止: run.bat stop`（证据 43/45）。修复前的假错误见 §3.3 |
| 2 | 通过 | 进入 `/home/aimu/cu-v012-layout` 后 16 项夹具正常渲染：普通文件（`short.txt`、`zero-bytes.txt`）、符号链接、`big-12MiB.bin`、`.tar.gz` 带额外「解压」按钮、中文与带空格/括号/方括号的名字；窗口 1240×900 时超长名截断为 `a-directory-with-a-rather-...` 与 `这是一个非常长的中文文...`（证据 05/11-narrow-view） |
| 3 | 通过 | 窄窗口下操作列换行成两行，**「重命名」恒在右上、「删除」恒在右下**，带「编辑」「解压」的行只是多占槽位；无横向溢出（证据 11-narrow-view） |
| 4 | 通过 | 鼠标：悬停 `zero-bytes.txt` 弹出完整路径 `/home/aimu/cu-v012-layout/zero-bytes.txt`；键盘：连按 4 次 Tab 后焦点框落在截断单元格，提示完整名 `this-is-a-very-long-english-file-name-that-needs-truncation-in-the-name-column-0123456789.txt`，分两行且完整落在窗口内（证据 05-enter-layout、20-kbd-focus、20-kbd-focus-full） |
| 5 | 通过 | 连接卡显示 `CentOS Stream 10 / 已连接 / aimu@192.168.170.128:22 / 密钥认证 / 允许写 / 家目录 /home/aimu`；双击目录行进入 `cu-v012-layout`，面包屑为 `家目录 /home/aimu / cu-v012-layout`（证据 01-desktop、15-home、17-layout） |
| 6 | 通过 | 搜索 `PERM` 回车 → 「搜索〈PERM〉 已完成 已扫描 2 个目录 · 17 个条目 · 命中 4 条 · 用时 0.0 秒」，每条带「定位」按钮；双击文件名打开预览模态（标题「预览 perm-644.txt」、路径、大小 2 B、修改时间、只读提示、内容、编辑/下载/关闭）；工具栏「编辑」打开编辑器（证据 21-search、38-preview、33-front） |
| 7 | 通过 | 取消勾选「允许写操作」→ toast「已关闭写操作。」、「允许写」徽章消失、行内「编辑」变灰；此时打开编辑器顶部出现琥珀色横幅「这条连接没有开启写权限：可以在这里看内容，但保存会被服务端拒绝。」且编辑区只读、真实按键无效；重新勾选时弹「开启写操作 / 要为「CentOS Stream 10」开启写操作吗？…取消 · 开启」；开启后编辑 → 真实按键写入 → 「4 个字符 · 约 4 B 已修改，尚未保存」→ 点「保存」→ toast「已保存 [perm-644.txt]（4 B）」且列表刷新为 4 B / 2026-10-17 04:41；再把内容改回 2 B 保存成功（证据 23-editor、27-save-refused、28-write-on、29-write-enabled、33-front、35-save-ok、36-restored） |
| 8 | 通过 | 运行中再选 1) → 「[信息] AWFM 已经在运行，本次不会重复启动。」，未起第二个进程；选 3) 显示 `状态：运行中（PID 3660, http://127.0.0.1:8760/, 版本 0.1.1）`、`进程: PID 3660, 映像名 python.exe`、启动时间；选 4) 停止（Windows 拒绝优雅停止，确认后强制终止）；重新选 1) 得到新 PID 3628。辅助核对：端口 8760 监听 **1** 个、`data/awfm.pid` 存在且为 3628、旧 PID 3660 已消失、Python 3.13 进程 **2** 个（菜单外壳 + 唯一服务进程）（证据 46/47/48/50） |
| 9 | 通过 | 真实 WSL2 Ubuntu 终端里跑 `./run.sh`：`start --port 32591 --no-browser` → `[ OK ] AWFM 已启动（版本 0.1.1）`、`进程: PID 12337`、`访问范围 仅本机`，EXIT=0；`status` → `运行中（PID 12337, http://127.0.0.1:32591/, 版本 0.1.1）`、`映像名 python3`，EXIT=0；`stop --force --yes` → `已发送 SIGTERM … AWFM 已停止。`，EXIT=0。`check` 的 9 项前置检查全通过，随后因 Windows 侧 8760 实例占用同一端口而报 `[失败] 端口已被占用：127.0.0.1:8760`（WSL2 mirrored 网络可见宿主监听，属环境重叠，见 §6.2）（证据 51/52） |
| 10 | 通过 | 按 `docs/SSH_SETUP_GUIDE.md` 在真实 PowerShell 窗口核对：`ssh -V` → `OpenSSH_for_Windows_9.5p2, LibreSSL 3.8.2`；`ssh -G` 的 `batchmode no / identitiesonly no / stricthostkeychecking ask / serveraliveinterval 0 / connecttimeout none` 与教程附录 A 一致；密钥登录命令与 AWFM 实际选项形态一致，输出 `AWFM-TUTORIAL-OK / hadoop01 / aimu`，EXIT=0（证据 53） |
| 11 | 通过 | 同一窗口复现教程 J 节的两类错误：J.7 私钥权限过宽 → `Bad permissions. Try removing permissions for user: NT AUTHORITY\Authenticated Users (S-1-5-11) on file …` + `WARNING: UNPROTECTED PRIVATE KEY FILE!` 横幅 + `This private key will be ignored.` + `Permission denied (publickey,gssapi-keyex,gssapi-with-mic,password).`，EXIT=255；端口不通 → `banner exchange: Connection to UNKNOWN port -1: Connection refused`，EXIT=255。两者与教程 J.7/J 节示例逐字相符（证据 53） |
| 12 | 通过 | 启动脚本、教程、发行包三处一致：默认端口 `32579` 在 `scripts/launcher.py:47`、`app/core/config.py:51/:131/:369`、`config/config.example.json:5`、`tests/unit/test_launcher.py:44-46` 四处一致（运行中的 `data/config.json` 用 8760，是用户配置而非出厂默认）；`scripts/package.py:49-51` 的 `STAGE_DIRS/STAGE_SCRIPTS/STAGE_FILES` 与解压包内的实际文件一致；教程与实现的一致性由 `tests/unit/test_ssh_guide.py`（13 项）自动核对（详见 §4.5） |

### 3.3 发现的缺陷：`run.bat` 在 GBK 控制台下打印假错误

**现象**（证据 42-runbat-menu）。在全新控制台（默认代码页 936）里启动 `run.bat`，菜单之前多出两行：

```
'3.10+，当前是' is not recognized as an internal or external command,
operable program or batch file.
'在启动器里，批处理只负责找' is not recognized as an internal or external command,
operable program or batch file.
```

**根因**。`cmd.exe` 按**控制台代码页**逐行读取批处理文件。`run.bat` 是 UTF-8（无 BOM），而原来的 `chcp 65001`
写在第 6 行 —— 读到一半更换代码页后，字节与字符的位置记账错位，含中文的 `rem` 行被从中间截断，
后半截被当成命令执行。截断点落在原第 19、34 行。

**判定实验**（`.temp/runbat-test/`，每个变体都在全新控制台里跑并把输出重定向到日志）：

| 变体 | 处理 | 结果 |
| --- | --- | --- |
| t1 | 原样副本 | 复现（3 行 not recognized） |
| t2 | 只把出问题的两行中文改成 ASCII | 仍剩 1 行报错 |
| t3 | 删掉 `chcp` 行 | 仍然错位（UTF-8 文件被按 GBK 读） |
| t4 | 纯 ASCII 引导段：先 `chcp` 再重跑自己 | **零报错** |

结论：只有「整份文件从一开始就在 UTF-8 下被读取」才是干净的 —— 单独改几行或去掉 `chcp` 都不行。

**修复**。文件开头加入纯 ASCII 引导段（当前 `run.bat`:1-19），中文说明整体移到守卫之后：

```bat
@echo off
setlocal enableextensions
rem NOTE: keep everything above the "AWFM_UTF8_READY" block below ASCII-only.
rem cmd.exe reads a batch file line by line using the console code page. ...
if defined AWFM_UTF8_READY goto :awfm_utf8_ready
chcp 65001 >nul 2>nul
set "AWFM_UTF8_READY=1"
"%COMSPEC%" /c ""%~f0" %*"
exit /b %ERRORLEVEL%

:awfm_utf8_ready
```

设计要点（后续修改必须保持）：

1. **引导段内不能出现任何非 ASCII 字节** —— 第一遍就是按旧代码页读它；
2. 用**环境变量**而不是命令行参数做防重入，这样 `%*` 原样转发给 `scripts/launcher.py`，
   不会多出一个 `argparse` 不认识的参数；
3. 子进程退出码用 `exit /b %ERRORLEVEL%` 透传；
4. **不能用 `if (...) ` 括号块**：括号块里的 `%ERRORLEVEL%` 在解析时展开，会把子进程退出码吃成 0。

**二次修复**。第 1 版引导段用的正是括号块，被本阶段新增的集成测试当场抓住
（`WrapperExitCodeTest` 5 项失败，报 `AssertionError: 0 != 3`），随后改成上面的 `goto` 形式。
这属于修复过程中的回归，未进入任何交付版本。

**验证**。修复后用同一命令实测：修复前 `chcp 936` 控制台下退出码 **9009**（半行命令找不到），修复后 **0**
（`.temp/prefix-check/` 放 `git show HEAD:run.bat` 的副本 + `scripts/launcher.py`）；修复后的真实窗口复验见证据
54（`54-runbat-final.png` / `54-runbat-final-crop.png`）。

### 3.4 新增回归测试

| 文件 | 用例 | 断言要点 |
| --- | --- | --- |
| `tests/unit/test_run_bat.py`（新增，9 项） | `RunBatDisciplineTest` 等 | 全文件 CRLF（`.gitattributes` 的 `*.bat text eol=crlf` 也在断言内）；以 `rem AWFM 统一入口（Windows）` 的字节位置为界，**其之前不得出现任何大于 0x7F 的字节**；引导段五个标记齐全（守卫、`chcp 65001 >nul 2>nul`、`set "AWFM_UTF8_READY=1"`、`"%COMSPEC%" /c ""%~f0" %*"`、`exit /b %ERRORLEVEL%`）；守卫必须排在重跑之前；**`if not defined AWFM_UTF8_READY (` 不得出现**（防回退到括号块）；`scripts\launcher.py" %*` 原样转发；中文文案仍在 |
| `tests/integration/test_launcher_lifecycle.py`（+1 项） | `WrapperExitCodeTest.test_gbk_console_does_not_break_the_wrapper` | 在代码页 936 的控制台里执行 `chcp 936 >nul & call run.bat help`：退出码必须为 0，输出含 `AWFM`，且**不含** `not recognized` / `不是内部或外部命令`；用例用 ctypes 的 `GetConsoleOutputCP` / `SetConsoleOutputCP` 在结束后还原控制台代码页（Windows 专用，其他平台跳过） |

## 四、技术实现

### 4.1 `run.bat` 引导段

见 §3.3。当前 `run.bat` 共 **78 行 / 3856 字节 / 77 个 CRLF**，结构为：
ASCII 引导段（:1-19）→ 中文说明与正文（:21 起）→ `set "PYTHONUTF8=1"` / `PYTHONIOENCODING=utf-8`（:32-33）
→ `cd /d "%~dp0"`（:36）→ `py -3` / `python` 解释器探测（:45 起）→ 转交 `scripts\launcher.py` → 透传退出码
→ `if not defined AWFM_NO_PAUSE pause`。

### 4.2 CU 驱动要点（本阶段沉淀的操作规则）

- **每个 run_code 程序都是新的传输会话**：程序开头先 `start_session({})`，否则任何 cua 工具报
  `this session has ended; call start_session explicitly to reuse its label`。
- **Chromium 窗口忽略合成点击**：`click` 默认（background）返回 `route: synthetic_events` 且页面无反应，
  需 `delivery_mode: "foreground"`（`route: global_input`）；`hotkey` 对 `Chrome_WidgetWin_1`
  后台投递会被明确拒绝并要求改用前台投递。
- **坐标空间**：`click/double_click/drag` 的 x,y 是 `get_window_state` 截图像素；最大化时截图被缩放
  （2560×1380 → 1568×845，比例 0.6125），窗口还原后与桌面像素一致。harness 预览图经过缩放，
  坐标要用 UIA 的 `frame` 或按「裁图宽 ÷ 预览宽」换算。
- **进入目录必须双击**（`frontend/assets/js/files.js:429`/`:432` 单双击分工是刻意的）；
  `set_window_frame` 对最大化窗口会被拒绝，还原可靠办法是点 Edge 的「还原」按钮。
- 驱动把字母按键投递成大写（搜索框 `perm` 显示为 `PERM`）、Ctrl+S 被浏览器截获为「另存为」，
  都是驱动/环境现象，不是产品行为。

### 4.3 复现手法（教程错误示例，供 item 11）

教程 J 节的错误原文都是本机真实输出，复现手法沿用阶段四报告 §4.1 的记录：J.6 用假公钥写进临时
`known_hosts`、J.16 收窄 `HostKeyAlgorithms`/`KexAlgorithms`、J.14 用 8 把一次性密钥 +
`IdentitiesOnly=no`、J.10 用 `ssh -s <目标> no-such-subsystem`、J.15 用本地假 HTTP 服务、
J.7 用放宽 ACL 的私钥副本（本次 CU 现场复跑的就是 J.7 与端口类错误）。

### 4.4 证据组织

`.temp/cu-v012-stage6/` 命名规则：`NN-主题.png` 为整屏桌面截图，`NN-主题-view.png` 为同一时刻的窗口裁图
（便于读文字），`crop*.py`/`rows*.py` 为裁图脚本。`.temp/cu-v012/` 保存阶段一至三的 01/71~96 号截图与
当时的 `config.json`、`known_hosts`。两处都是草稿目录，不提交；报告以文件名 + 关键文本抄录的方式留证。

### 4.5 三处一致性（item 12）的核对方式

| 对象 | 事实 | 核对方式 |
| --- | --- | --- |
| 默认端口 | `32579`：`scripts/launcher.py:47`、`app/core/config.py:51/:131/:369`、`config/config.example.json:5`、`tests/unit/test_launcher.py:44-46` | 直接读取 + 单测钉常量 |
| 运行配置 | `data/config.json` 用 `8760`（用户配置），`open_browser=false`、`allow_lan=false`、`host_key_policy=strict` | 读取运行配置 |
| 发行包内容 | `scripts/package.py:49-51`：`STAGE_DIRS=("app","frontend","docs")`、`STAGE_SCRIPTS=("start.py","launcher.py")`、`STAGE_FILES=("README.md","LICENSE","config/config.example.json","VERSION","run.bat","run.sh")` | 与 `dist/AWFM-0.1.1-windows-x64/` 解压内容比对：`run.bat`、`run.sh`、`docs/SSH_SETUP_GUIDE.md`、`VERSION`、`config/config.example.json` 均在 |
| 文档一致性 | `docs/` 中 `run.bat` 87 处、`run.sh` 52 处；教程与实现由 `tests/unit/test_ssh_guide.py` 13 项自动核对 | grep + 单测 |

### 4.6 测试侧竞态修正：等待「应用外壳」的表达式

本阶段唯一一处测试代码的健壮性修正，与产品行为无关，但会影响回归结论的可信度：

- 现象：全量回归的 e2e 层报 `tests/e2e/test_browser_edit.py:275` 失败，栈指向 `:216`
  `page.wait_for("!document.getElementById('app').hidden", ...)`，异常为
  `TypeError: Cannot read properties of null (reading 'hidden')`。
- 根因：`tests/e2e/support.py:237-241` 的 `navigate()` 发完 `Page.navigate` 就返回，不等文档加载；
  紧随其后的第一次 `evaluate`（`support.py:214-224`）可能落在新文档尚未解析出 `#app` 的瞬间，
  表达式对 `null` 取 `.hidden` 直接抛出，而 `wait_for`（`support.py:226-235`）遇到异常会立即冒泡、不再轮询。
  本机 CU 环境同时开着多个浏览器窗口、终端与两个 AWFM 实例，页面解析变慢把这条一直存在的竞态暴露了出来。
- 修法：把这 9 处表达式改成空值安全的形式，DOM 未就绪时返回假值继续轮询，语义与超时都不变：

  ```javascript
  !!document.getElementById('app') && !document.getElementById('app').hidden
  ```

- 改动位置：`tests/e2e/test_browser_discovery.py:135`、`test_browser_edit.py:216`、
  `test_browser_flow.py:106/:187/:229`、`test_browser_layout.py:330`、
  `test_browser_regressions.py:110`、`test_browser_search.py:148`、`test_browser_sidebar.py:169`（共 9 处）。
- 验证：e2e 整层复跑 32 项全绿（`.temp/e2e-v012-p6.log`，220.39 s，`EXIT=0`）。
- 附带收益：若应用外壳真的没渲染出来，报错从「表达式抛错 TypeError」变成等待超时并带上原来那句
  「页面外壳没有显示出来」，排查信息更直白。

## 五、测试结果

### 5.1 四层自动化

`python scripts/test.py -v`（日志 `.temp/full-test-v012-p6.log`）：

`python scripts/test.py -v`（全量日志 `.temp/full-test-v012-p6.log`）：

| 层 | 数量 | 结果 | 耗时 |
| --- | --- | --- | --- |
| unit | 588 | OK (skipped=1) | 4.26 s |
| integration | 125 | OK | 331.56 s |
| security | 82 | OK | 473.10 s |
| e2e | 32 | OK | 220.39 s |
| 合计 | 827 | 0 失败 / 0 错误 / 1 跳过 | 1029.31 s |

- e2e 一行的数字来自**修正等待表达式之后**的整层复跑（`.temp/e2e-v012-p6.log`，`EXIT=0`）。第一次全量跑在 e2e 层出现 1 项失败（`tests/e2e/test_browser_edit.py:275``test_editor_saves_an_edited_file`，页面尚未解析到 `#app` 时等待表达式抛 `TypeError`）；按 §6.1 第一行修正后复跑，32 项全绿。
- 唯一跳过项仍是 `tests/unit/test_launcher.py` 的 `SignalTest`（Windows 没有 POSIX 信号；WSL2 Ubuntu 上真跑通过，见 §5.4）。

与阶段五（817 项：579 / 124 / 82 / 32）的逐层差异（任务书 §5.4 要求说明新增、通过、失败、跳过与实际原因）：

| 层 | 阶段五 | 阶段六 | 新增 | 原因 |
| --- | --- | --- | --- | --- |
| unit | 579 | 588 | +9 | 新增 `tests/unit/test_run_bat.py`（`run.bat` 静态纪律，§3.4） |
| integration | 124 | 125 | +1 | 新增 `WrapperExitCodeTest.test_gbk_console_does_not_break_the_wrapper`（GBK 控制台不再出现假错误） |
| security | 82 | 82 | 0 | 本阶段未改动安全相关代码与用例 |
| e2e | 32 | 32 | 0 | 未新增用例；只把 9 处「等待应用外壳」表达式改成空值安全（§6.1） |
| 合计 | 817 | 827 | +10 | 通过 827、失败 0、错误 0、跳过 1（与阶段五同为 `SignalTest` 一项） |

### 5.2 本阶段新增测试

| 命令 | 结果 |
| --- | --- |
| `python -m unittest tests.unit.test_run_bat -v` | Ran 9 tests in 0.005s — OK |
| `python -m unittest tests.integration.test_launcher_lifecycle.WrapperExitCodeTest -v` | Ran 6 tests in 6.675s — OK |
| 修复前/后对照（`chcp 936` 控制台下 `run.bat help`） | 9009 → 0 |

### 5.3 真实桌面 CU 验收证据清单

| 证据文件（`.temp/cu-v012-stage6/`） | 对应条款 | 关键内容 |
| --- | --- | --- |
| `01-desktop.png` | 5 | 桌面起始状态：Edge InPrivate 打开 `127.0.0.1:8790`，连接卡与 /home/aimu 列表 |
| `05-enter-layout.png` | 2、4 | 双击进入 `cu-v012-layout`；16 项夹具；悬停显示完整路径 |
| `11-narrow-window.png`、`11-narrow-view.png` | 2、3 | 1240×900 下长名截断、操作列换行且按钮位置固定、无横向溢出 |
| `20-kbd-focus.png`、`20-kbd-focus-full.png` | 4 | Tab 焦点落在截断单元格后弹出完整文件名 |
| `15-home.png`、`17-layout.png` | 5 | 真实 CentOS 主机上浏览家目录与测试目录 |
| `21-search.png`、`21-search-view.png` | 6 | 搜索命中 4 条并给出扫描统计与「定位」入口 |
| `38-preview.png`、`38-preview-view.png` | 6 | 预览模态（只读提示 + 编辑/下载/关闭） |
| `23-editor-view.png`、`27-save-refused-view.png` | 7 | 关写权限时编辑器只读 + 顶部拒绝保存横幅 |
| `28-write-on-view.png`、`29-write-enabled-view.png` | 7 | 开启写操作的确认对话框与恢复后的「允许写」徽章 |
| `33-front-view.png`、`35-save-ok-view.png`、`36-restored-view.png` | 7 | 真实按键编辑 → 保存成功（4 B → 2 B）与提示文案 |
| `42-runbat-menu-view.png` | 1 | **缺陷证据**：修复前菜单上方的两行假错误 |
| `43-runbat-fixed-view.png`、`45-menu-start-view.png` | 1 | 修复后干净菜单、地址与启动成功提示 |
| `46-dup-start-view.png`、`47-status-view.png`、`48-stop-prompt-view.png`、`50-restarted-view.png` | 8 | 重复启动被拒、状态详情、停止提示、重启后新 PID |
| `51-wsl-runsh.png`(+crop) | 9 | WSL2 终端里 `run.sh` start/status/stop 全流程 EXIT=0 |
| `52-wsl-check.png`(+crop) | 9 | `run.sh check` 9 项通过后因端口被 Windows 侧实例占用而失败 |
| `53-ssh-guide.png`(+crop) | 10、11 | 真实 PowerShell：`ssh -V`、`ssh -G`、密钥登录成功、J.7 与端口错误原文 |
| `54-runbat-final.png`(+crop) | 1 | 二次修复后复验：菜单干净、中文正常、状态行显示运行中的 PID 与地址 |

### 5.4 辅助命令清单（与真实 CU 的区分）

以下命令只用于环境准备与结果核对，**不替代**任何 CU 交互：

| 用途 | 命令 |
| --- | --- |
| item 8 残留核对 | `Get-NetTCPConnection -LocalPort 8760 -State Listen`、`Get-Content data/awfm.pid`、`Get-Process python \| Where-Object { $_.Path -like '*Python 3.13*' }` |
| item 9 的 WSL 侧执行 | `wsl -d Ubuntu -- bash <脚本>`（窗口本身由 `launch_app` 打开的真实 Windows Terminal 承载） |
| item 10/11 的命令文本 | `.temp/ssh-guide-check.ps1`（在真实 PowerShell 窗口内执行，结果由截图 53 承载） |
| 回归与静态检查 | `python scripts/test.py -v`、`python scripts/build.py` |
| 读截图文字 | Pillow 裁图脚本（`crop*.py`） |

### 5.5 静态检查与发行包

`python scripts/build.py` 8 项全部通过（Python 版本 / 语法校验 / 零第三方依赖 42 个源文件 /
前端离线 19 个文件 / 凭据纪律 54 个可能被提交的文件 / 错误模型回归 / 版本一致性 / 测试包结构）。
发行包检查在阶段五已完成（`dist/AWFM-0.1.1-windows-x64` 解压后独立运行、`GET /` HTTP 200 与 7399 字节、
零外链），本阶段改动 `run.bat` 后未重新打包 —— 打包与哈希在阶段七随版本号一并重做。

## 六、问题与风险

### 6.1 过程中发现并解决的问题

| 问题 | 性质 | 处理 |
| --- | --- | --- |
| `run.bat` 在 GBK 控制台下打印两行 `is not recognized ...` | **产品缺陷（用户可见）** | 加纯 ASCII 引导段 + `chcp` 后重跑自身；补 9 项单测 + 1 项集成用例（§3.3、§3.4） |
| 第 1 版修复用括号块吞掉退出码 | 修复引入的回归 | 新增的集成测试当场抓住（`0 != 3`），改 `goto` 形式后复跑全绿 |
| 测试侧：`run.bat` 用相对路径调用时依赖 cwd | 测试假设错误 | 集成测试改用绝对路径 `cmd /c <root>/run.bat`，并新增「从无关工作目录执行」用例 |
| 环境：`chcp` 改写控制台代码页会污染后续命令 | 测试隔离问题 | 集成测试用 ctypes 读取并还原控制台代码页 |
| 测试侧：e2e 首次全量跑在 `tests/e2e/test_browser_edit.py:216` 撞上竞态 | **测试健壮性问题（不是产品缺陷）** | 9 处「等待应用外壳」表达式改为空值安全后整层复跑全绿（§5.1、4.6） |

### 6.2 未验证或受限的项

1. **`run.sh check` 在 WSL 里因端口冲突失败**：WSL2 mirrored 网络能看到 Windows 宿主正在监听的 8760，
   而当前配置恰好用 8760。9 项前置检查全部通过，冲突属环境重叠而非缺陷；换用独立端口即可通过（阶段三
   Linux 验收用的就是 32591）。
2. **跨系统的 PID 可见性**：WSL 里 `run.sh status` 读到 Windows 侧写入的 PID 文件时，会报
   「PID 文件里的 PID 已经不存在」（WSL 看不到 Windows 进程）。属预期行为，已在教程/文档中说明。
3. **CU 按键被驱动转成大写**：item 7 的写入内容与原始夹具只差大小写（远端 `perm-644.txt` 现为 2 B 的
   「X + 换行」，与原始的「x + 换行」等价），保存与拒绝保存的结论不受影响。
4. **未覆盖的交互**：鼠标滚轮滚动到底、拖拽排序、多标签页并发等不在任务书 §6 的 12 条范围内，未逐项演示。
5. **平台范围**：CU 验收只在 Windows 11 + Edge（Chromium）上做；Linux/macOS 桌面未做 CU，
   布局类断言由 8 项 `tests/e2e/test_browser_layout.py` 与 4 项 `test_browser_sidebar.py` 在无头 Chromium 下回归。

### 6.3 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 布局与提示只在单一浏览器/分辨率下人工看过 | e2e 层用 3 种窗口宽度 + 150% 缩放（661px / 992px / 1440px）自动断言不出视口、无横向滚动 |
| CU 证据保存在 `.temp/`（不提交） | 报告逐条记录证据文件名 + 关键文本抄录；关键错误原文同时进了教程与测试断言 |
| `run.bat` 引导段将来被误改回括号块 | `tests/unit/test_run_bat.py` 显式断言 `if not defined AWFM_UTF8_READY (` 不存在 |
| 发行包尚未按新 `run.bat` 重新构建 | 阶段七统一升号、重新打包并复核 SHA-256 |

## 七、文档与交付物

| 交付物 | 说明 |
| --- | --- |
| `run.bat` | 修复 GBK 控制台假错误（78 行 / 3856 字节，ASCII 引导段 + `goto` 守卫） |
| `tests/unit/test_run_bat.py` | 新增 9 项静态纪律测试 |
| `tests/integration/test_launcher_lifecycle.py` | 新增 1 项 GBK 控制台集成用例 + 2 个控制台代码页助手 |
| `tests/e2e/*.py`（7 个文件 / 9 处） | 等待「应用外壳」的表达式改成空值安全，消除页面未解析时的假失败（§4.6） |
| `tests/unit/_index.md`、`tests/integration/_index.md` | 登记新增用例 |
| 本报告 + `docs/reports/_index.md` | 阶段六记录 |
| `docs/CHANGELOG.md` | v0.1.2 的「修复」段记入本次缺陷、进度表更新阶段六 |
| `.temp/cu-v012-stage6/` | 验收证据（草稿目录，不提交） |

## 八、阶段结论

- 任务书 §6 的 12 条验收**全部完成**，其中 11 条为真实桌面/真实终端操作取证，第 12 条为三处一致性核对；
- 发现并修复 1 个用户可见缺陷（`run.bat` 在 GBK 控制台下的假错误），并补上 10 项回归测试；
- 全量回归首跑暴露的 e2e 等待表达式竞态（测试侧）已修正并复跑全绿（§4.6、§5.1）；
- 四层自动化与静态检查全绿（§5.1、§5.5），本次改动未破坏既有功能；
- 遗留的限制项（§6.2）均有明确的环境解释或替代覆盖，不阻塞后续阶段。

**允许进入阶段七（版本与交付）。**
