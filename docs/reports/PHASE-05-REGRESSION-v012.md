# 阶段五报告：回归测试与安全检查（v0.1.2）

## 一、报告信息

| 项目 | 内容 |
|---|---|
| 版本 | v0.1.2（维护与体验优化；版本号按任务书留到阶段七统一升级，当前程序自报 0.1.1） |
| 阶段 | 阶段五：回归测试与安全检查 |
| 依据 | `dev_guide/0.1.2_.md` §5.1 ~ §5.4（§5.1 文件列表、§5.2 启动脚本、§5.3 SSH 与文件操作、§5.4 自动化测试） |
| 日期 | 2026-10-17 |
| 基线提交 | `13d778a`（阶段 04 收尾：CHANGELOG 记入 v0.1.2 阶段四提交哈希），分支 `master` |
| 验证方式 | ① 把 §5.1 ~ §5.3 的每一条要求先映射到既有用例，找出 5 处缺口再补真实集成用例（`tests/integration/test_launcher_lifecycle.py`，7 → 13 项）；② 四层自动化回归 `python scripts/test.py -v`；③ 静态检查 `python scripts/build.py`（8 项）；④ 发行包检查 `python scripts/package.py`：构建、解开、在独立目录里 `check` / `start` / `GET /` / `status` / `stop` 全程跑通；⑤ WSL2 Ubuntu 24.04 上 `bash -n run.sh` / `sh -n run.sh` 与实际执行 `run.sh` |
| 结论 | **通过**。四层共 817 项全绿（0 失败 / 0 错误 / 1 跳过，1 项跳过为 Windows 平台跳过）；静态检查 8 项全通过；发行包解压后可在独立目录启动、`GET /` 返回 200、可正常停止；**本阶段未改动 `app/` / `frontend/` / `scripts/` 任何一行代码，未发现新的产品缺陷** |

## 二、阶段目标

任务书 §五 把本阶段定义为「回归测试与安全检查」：**不改功能**，而是用既有测试加上新补的用例，证明 v0.1.1 的行为没有被前四个阶段的维护破坏，并把四层数字逐层交代清楚（§5.4 明确要求「不得只报告一个总数」）。

| 条款 | 要求要点 | 落地位置 |
|---|---|---|
| §5.1 文件列表 | 排序与对齐；超长文件名；中文/空格/括号/特殊字符；导航、刷新、预览与编辑入口；按钮位置稳定；不同窗口尺寸不溢出、不遮挡 | 先映射到既有用例（§5.6 表），再用全量回归复验；阶段二的固定布局由 e2e 钉住 |
| §5.2 启动脚本 | Windows 首次/重复/停止/再启动；Linux 语法与实际执行；端口占用、无 Python、无 OpenSSH、配置损坏；路径含空格；不同工作目录；停止是否只影响 AWFM 管理的进程；错误文案；发行包解压后独立运行 | §5.2 的 6 项新用例 + 阶段三真实验收素材 + §5.4 发行包独立运行 + §5.5 WSL 复跑 |
| §5.3 SSH 与文件操作 | 主机指纹确认、密钥认证、SFTP 与目录浏览、搜索/预览/编辑、写权限、冲突检测、上传下载完整性、断开与恢复 | 映射到既有四层用例（§5.6 表），由全量回归复验 |
| §5.4 自动化测试 | 跑 `python scripts/test.py`；同时做静态检查与发行包检查；与上一版本不同须逐层说明新增/通过/失败/跳过及原因 | §5.1 四层数字与差异、§5.3 静态检查、§5.4 发行包检查 |

## 三、实际完成情况

### 3.1 先做覆盖率盘点（映射优先，避免重复造测试）

把 §5.1 ~ §5.3 拆成 26 条可验证要求，逐条找对应用例。结论：**大部分要求已有覆盖**，其中

- §5.1 全部 6 条已有覆盖：固定表格布局与五槽位操作区（`frontend/assets/css/app.css:845-890`、`:1023-1052`，阶段二）由 `tests/e2e/test_browser_layout.py`（8 项）与 `tests/e2e/test_browser_sidebar.py`（4 项）钉住；中文/空格/括号/0 字节/12 MiB/权限/旧日期夹具在 `tests/integration/support.py` 的 `layout_fixture`；路径与名称校验在 `tests/unit/test_paths.py`（30 项）与 `tests/security/test_path_traversal.py`；刷新后的陈旧列表在 `tests/e2e/test_browser_regressions.py:122`。
- §5.3 全部 9 条已有覆盖：指纹在 `tests/security/test_host_key.py`（7 项）与 `tests/e2e/test_browser_flow.py`（3 项）；认证与浏览在 `tests/integration/test_connection_flow.py`（10 项）、`test_password_auth.py`、`test_api_flow.py`（8 项）；搜索在 `tests/unit/test_search.py`（36 项）+ `tests/integration/test_search_api.py`（15 项）+ `tests/security/test_search_paths.py`（18 项）+ `tests/e2e/test_browser_search.py`（4 项）；编辑在 `tests/unit/test_editor.py`（43 项）+ `tests/integration/test_edit_api.py`（32 项）+ `tests/security/test_edit_paths.py`（12 项）+ `tests/e2e/test_browser_edit.py`（7 项）；写权限三处、冲突检测（sha256/mtime 409）、上传下载完整性（`support.upload_bytes` / `download_bytes` 走完整 HTTP 往返 + 下载票据 `tests/unit/test_tickets.py`）、断开恢复（D2 回归）各有对应用例。
- §5.2 **找到 5 处缺口**，都集中在「启动脚本的拒绝路径」与「非默认调用方式」：
  1. **OpenSSH 客户端缺失时 `start` 必须拒绝** —— 原先只有函数级单测（`tests/unit/test_launcher.py:301`），没有子进程级证据。
  2. **配置文件损坏时的真实命令行表现** —— 原先只测文案函数，没有断言退出码、没有断言给出 `--init-config` 出路。
  3. **从不同工作目录执行脚本** —— 既有集成用例统一以 `cwd=ROOT` 运行。
  4. **停止只影响 AWFM 管理的进程** —— 单位测试只测了「映像名闸门」的判定函数，没有「旁边真有一个无关 python 进程」的端到端证据。
  5. **脚本路径包含空格** —— 阶段三在 Windows 真机验收过，但没有可重复的自动化用例。

### 3.2 补齐 6 项缺口用例

`tests/integration/test_launcher_lifecycle.py` 由 7 项增至 **13 项**（413 行，新增 6 项）：

| 用例 | 行号 | 断言要点 |
|---|---|---|
| `LauncherLifecycleTest.test_stop_does_not_touch_unrelated_processes` | `:209` | PID 文件里的进程被停止；**同时启动的无关 python 进程必须仍然存活**（decoy 用 `subprocess.Popen([sys.executable, "-c", "import time; time.sleep(180)"])`，finally 里 kill + wait） |
| `LauncherLifecycleTest.test_start_refuses_when_ssh_client_is_missing` | `:242` | 把配置里的 `ssh.ssh_executable` 指向不存在的绝对路径：`start` 退出码 1、文案含「找不到系统 ssh 客户端」、**不写 PID 文件**、端口仍空闲、`check` 仍能正常收尾 |
| `LauncherLifecycleTest.test_corrupt_config_is_refused_with_a_readable_message` | `:274` | 截断的 JSON：`start` 退出码 1 且文案含 `--init-config`；`status` 降级为警告、退出码 3；两者都不出现 Traceback |
| `LauncherLifecycleTest.test_runs_from_a_different_working_directory` | `:303` | 以 `cwd=<临时目录>` 跑 `status` / `check` / `start` / `stop` 全流程仍然正确（PID 文件与日志由参数显式指定） |
| `WrapperExitCodeTest.test_wrapper_runs_from_an_unrelated_working_directory` | `:378` | 以 `cwd=<临时目录>` 调用绝对路径的外壳，仍能转发到同级 `scripts/launcher.py`（`status` 退出码 3） |
| `WrapperExitCodeTest.test_spaces_in_the_script_path` | `:387` | 把 `run.bat` / `run.sh` 与同级 `scripts/` 复制到 `accept space/AWFM test`：外壳仍能找到 `launcher.py`，`status` 退出码 3、`check` 不崩 |

为支持后两项，测试工具函数扩了两个参数：`run_launcher(..., cwd=None)` 与 `_run_wrapper(..., cwd=None, root=None)`，并且**外壳改用绝对路径调用**（原因见 §4.1）。

### 3.3 静态检查与发行包检查

- `python scripts/build.py` → **8 项全通过**（明细见 §5.3）。
- `python scripts/package.py` → 退出码 0：构建 `dist/AWFM-0.1.1-windows-x64/`（101 个文件，1.37 MB）、`dist/AWFM-0.1.1-windows-x64.zip`（102 条目，588.8 KB）、`dist/SHA256SUMS.txt`；逐文件 SHA-256 与 MANIFEST 自检通过。
- 把 zip 解到**独立目录** `.temp/pkg-run/AWFM-0.1.1-windows-x64` 后完整跑一遍（明细见 §5.4）。

### 3.4 四层回归

`python scripts/test.py -v` 跑完整四层，数字与逐层差异见 §5.1。

## 四、技术实现

### 4.1 写测试时被真实输出纠正的三处假设

这三处都不是产品缺陷，而是**测试侧对产品行为的假设写错了**，报告如实记录：

1. **坏配置下 `status` 不是退出码 1，而是「降级警告 + 退出码 3」**。第一版断言按 `start` 的行为写成「两边都退出码 1」，实跑得到：[警告] 读不到配置，无法显示预期地址：配置文件无法使用：配置文件不是合法的 JSON，已停止启动。，退出码 3。查 `scripts/launcher.py:565-585` `cmd_status` 确认这是有意设计（`status` 在没有运行实例时仍应报告状态，读不到配置只降级为警告），断言改为按真实设计写。
2. **`cmd /c run.bat` 依赖当前目录解析**。从无关目录调用时得到 `'run.bat' is not recognized as an internal or external command`。这不是产品问题：`run.bat:11` 有 `cd /d "%~dp0"`，双击与相对调用都正确；是测试自己的调用方式错了。改为**绝对路径** `["cmd", "/c", str(shell_root / "run.bat"), *args]`，从任意 `cwd` 调用都成立。
3. **`test_stop_does_not_touch_unrelated_processes` 的 decoy 必须在 finally 里清理**。首版漏了，用例失败时会把一个 `time.sleep(180)` 的 python 留在机器上；改为 `finally` 中 `kill()` + `wait()`。

### 4.2 用例怎么保证「只动该动的进程」

`scripts/launcher.py` 的停止纪律是两道闸门：① 只认 `data/awfm.pid` 里的 PID；② 该 PID 的映像名必须含 `python`（`tests/unit/test_launcher.py:77-95` 用 `looks_like_python` 矩阵钉住判定）。新用例补的是端到端证据：PID 文件指向 AWFM，旁边另起一个同为 python 的无关进程，停止后必须只有前者消失。

### 4.3 一次性脚本与素材（不提交）

阶段三留下的真实验收素材仍在 `.temp/launcher-accept/`（`run-accept.ps1` Windows C01~C12、`wsl-accept.sh` Linux 侧、`wsl-unit.sh` 让被跳过的 `SignalTest` 在 Linux 真跑）。本阶段新增的一次性素材：`.temp/pkg-run-check.ps1`（发行包独立运行验收脚本，UTF-8 with BOM）与 `.temp/pkg-run/evidence.txt`（102 行证据）。这些都在 `.temp/` 下，不进仓库。

## 五、测试结果

### 5.1 四层自动化测试

| 层 | 数量 | 结果 | 耗时 |
|---|---|---|---|
| unit | 579 | OK（1 项按平台跳过：`SignalTest` 在 Windows 上跳过，在 Linux（WSL2 Ubuntu 24.04）上真跑通过——阶段三已核验） | 4.073 s |
| integration | 124 | OK | 320.651 s |
| security | 82 | OK | 467.275 s |
| e2e | 32 | OK | 189.529 s |
| 合计 | 817 | 0 失败 / 0 错误 / 1 跳过 | 981.53 s |

`python scripts/test.py -v` 退出码 0，末行「全部通过。」。全文日志：`.temp/full-test-v012-p5.log`。

**与上一版本（阶段四，811 项）的逐层差异**（任务书 §5.4 要求「不得只报告一个总数」）：

| 层 | 阶段四 | 阶段五 | 新增 | 通过 | 失败 | 错误 | 跳过 | 差异原因 |
|---|---|---|---|---|---|---|---|---|
| unit | 579 | 579 | 0 | 579 | 0 | 0 | 1（平台跳过） | 本阶段未改动单测 |
| integration | 118 | **124** | **+6** | 124 | 0 | 0 | 0 | 新增 6 项启动脚本缺口用例（§3.2、§5.2） |
| security | 82 | 82 | 0 | 82 | 0 | 0 | 0 | 本阶段未改动安全用例（耗时 466.72 → 467.275 s） |
| e2e | 32 | 32 | 0 | 32 | 0 | 0 | 0 | 本阶段未改动端到端用例（耗时 187.12 → 189.529 s） |
| 合计 | 811 | **817** | **+6** | 817 | 0 | 0 | 1 | 唯一的数量变化来自新增的 6 项集成用例 |

跳过的 1 项是 `tests/unit/test_launcher.py` 的 `SignalTest`（Windows 上没有 POSIX 信号，按平台跳过），阶段三已在 WSL2 Ubuntu 24.04 上真跑通过；本阶段没有新增跳过项。

### 5.2 新增 6 项集成用例

新增 6 项都在 `tests/integration/test_launcher_lifecycle.py`（413 行，7 → 13 项），逐条断言见 §3.2。显式指定这 6 个用例复跑一遍：

`python -m unittest -v <6 个用例名>` → **`Ran 6 tests in 40.793s / OK`**，退出码 0，日志 `.temp/stage5-new-cases.log`。

| 用例（行号） | 用例自己声明的任务书条款 | 结果 |
|---|---|---|
| `test_stop_does_not_touch_unrelated_processes`（`:209`） | §5.2「停止操作是否只影响 AWFM 管理的进程」 | ok |
| `test_start_refuses_when_ssh_client_is_missing`（`:242`） | §5.2「OpenSSH 不存在」：缺 ssh 客户端时只能拒绝启动 | ok |
| `test_corrupt_config_is_refused_with_a_readable_message`（`:274`） | §5.2「配置文件损坏」：给人话 + 出路，不给 traceback | ok |
| `test_runs_from_a_different_working_directory`（`:303`） | §5.2「从不同工作目录执行脚本」：路径不能锚在 cwd 上 | ok |
| `test_wrapper_runs_from_an_unrelated_working_directory`（`:378`） | 外壳从无关目录调用仍能转发到同级 `scripts/launcher.py` | ok |
| `test_spaces_in_the_script_path`（`:387`） | §5.2「脚本路径包含空格」 | ok |

这 6 项同时也随四层回归的 integration 层（124 项）跑过一遍（§5.1）。

### 5.3 静态检查（`python scripts/build.py`，8 项全通过）

| 检查 | 结论 | 输出要点 |
|---|---|---|
| Python 版本 | 通过 | 当前 3.12.10（`E:\Software\Python 3.12\python.exe`） |
| 语法校验（SyntaxWarning 视为错误） | 通过 | `app/` `tests/` `scripts/` 编译通过 |
| 零第三方依赖（import 扫描） | 通过 | 扫描 42 个源文件，导入 42 个顶层模块，全部来自标准库 |
| 前端离线（无 CDN / 在线字体） | 通过 | 扫描 19 个前端文件，未发现任何外部 URL（SVG 命名空间除外） |
| 凭据纪律（无私钥 / 无明文密码） | 通过 | 扫描 53 个可能被提交的文件，未发现私钥内容或明文密码（3 处示例占位符已放行：`docs/API.md:338`、`docs/DECISIONS.md:236`、`docs/reports/PHASE-06-RELEASE.md:90`） |
| 错误模型回归（`http_status` 不是构造参数） | 通过 | `app/` 下没有把 `http_status` 当构造参数传的写法 |
| 版本一致性 | 通过 | `__version__ = 0.1.1`，`README.md` 与 `docs/CHANGELOG.md` 均已提到该版本 |
| 测试包结构 | 通过 | `tests/` 四层都有 `__init__.py`：unit / integration / security / e2e |

末行「全部 8 项通过。」，退出码 0。日志：`.temp/build-check-v012.log`。

### 5.4 发行包检查与解压后的独立运行

构建：`python scripts/package.py` 退出码 0（日志 `.temp/package-v012.log`）。产物与自检：

| 项目 | 值 |
|---|---|
| 目录 | `dist/AWFM-0.1.1-windows-x64/`，101 个文件，1.37 MB |
| 压缩包 | `dist/AWFM-0.1.1-windows-x64.zip`，102 条目，588.8 KB，SHA-256 `3e7be58a16d3f5c110f88c9c1effd09bb85b0f8962020fc55fbd5e585eb4d767` |
| 校验 | `dist/SHA256SUMS.txt`；逐文件 SHA-256 与 `MANIFEST.json` 一致 |
| 顶层内容 | `app` `config` `docs` `frontend` `scripts` `LICENSE` `MANIFEST.json` `README.md` `run.bat` `run.sh` `VERSION`；**不含 `tests/`** |

解压到独立目录后（证据 `.temp/pkg-run/evidence.txt`，102 行）：

| 步骤 | 命令 | 结果 |
|---|---|---|
| 自检 | `run.bat check` | 退出码 0；解释器 Python 3.13.16（`run.bat` 优先 `py -3`）；ssh = `C:\Windows\System32\OpenSSH\ssh.EXE`；主机密钥策略 strict；端口 127.0.0.1:32579 空闲；已配置连接 0 个 |
| 启动 | `run.bat start --no-browser --port 1500` | 退出码 0，PID 24164，日志写入包内 `logs/` |
| 网页 | `GET http://127.0.0.1:1500/` | **HTTP 200**，7399 字节，标题 `AWFM · 远程文件管理器`，页面内外部 URL 数 0（离线可用） |
| 状态 | `run.bat status` | 运行中（PID 24164，版本 0.1.1，启动时间 2026-10-17T04:10:33+08:00） |
| 停止 | `run.bat stop --force --yes` | 退出码 0；Windows 拒绝优雅停止（该进程没有窗口）→ 强制终止；端口 1500 释放；`data/` `logs/` 在包内自动生成 |
| 跨目录 | `cmd /c <包绝对路径>\run.bat status` | 退出码 3，显示「没有运行」「地址 http://127.0.0.1:32579/（按当前配置，未在运行）」「端口：空闲」 |

### 5.5 WSL2 上的 Linux 脚本检查（§5.2「Linux 脚本的语法和实际执行」）

| 项目 | 命令 | 结果 |
|---|---|---|
| Bash 语法 | `bash -n run.sh` | `SYNTAX OK` |
| POSIX 语法 | `sh -n run.sh` | `POSIX SYNTAX OK` |
| 实际执行 | `python3 -m unittest tests.integration.test_launcher_lifecycle.WrapperExitCodeTest -v` | `Ran 5 tests in 0.758s / OK`——`run.sh` 真跑：`status` / `stop` 空闲退出码 3、参数转发与用法错误、从无关目录调用、**带空格路径** |

环境：WSL2 Ubuntu（`wsl -d Ubuntu`）。日志：`.temp/wsl-runsh-v012.log`。

### 5.6 任务书条款逐条对照

| 条款 | 判定 | 证据 |
|---|---|---|
| §5.1 排序和对齐 | ✅ | 固定表格布局（`frontend/assets/css/app.css:845-890`）+ `tests/e2e/test_browser_layout.py`；排序规则 `tests/unit/test_filesystem.py`（26 项） |
| §5.1 超长文件名显示 | ✅ | `frontend/assets/js/files.js:489` 截断检测 + `overlay.js` 完整名称提示；e2e 布局 8 项覆盖悬浮与键盘焦点 |
| §5.1 中文/空格/括号/特殊字符 | ✅ | `tests/integration/support.py` 的 `layout_fixture`；`tests/unit/test_paths.py`（30 项）；`tests/security/test_path_traversal.py` |
| §5.1 目录导航、刷新、预览、编辑入口 | ✅ | `tests/e2e/test_browser_flow.py`、`test_browser_edit.py`（7 项）、`test_browser_regressions.py:122`（远端删除后刷新标灰）、工具栏 `btn-refresh` |
| §5.1 操作按钮位置稳定 | ✅ | 五个动作钉在五个 Grid 槽位（`frontend/assets/css/app.css:863-885`）；e2e 布局断言按钮不位移 |
| §5.1 不溢出、不遮挡 | ✅ | `tests/e2e/test_browser_layout.py`：992 px 窄窗与 150% 缩放（661 px）下不出视口、无横向滚动；`tests/e2e/test_browser_sidebar.py`：三种宽度侧栏 |
| §5.2 Windows 首次/重复/停止/再启动 | ✅ | `tests/integration/test_launcher_lifecycle.py:103` `test_full_lifecycle`；阶段三真实验收 C01~C12；本节 §5.4 发行包内再跑一遍 |
| §5.2 Linux 语法与实际执行 | ✅ | §5.5（`bash -n` / `sh -n` + `run.sh` 真跑 5 项） |
| §5.2 端口占用 | ✅ | `test_port_conflict_is_refused`:167；`tests/unit/test_launcher.py` 端口判定 |
| §5.2 Python 不存在 | ✅ | 阶段三真实验收用例 `.temp/launcher-accept/cases/no-python.cmd`（`check_python()` 给出安装指引） |
| §5.2 OpenSSH 不存在 | ✅ | `test_start_refuses_when_ssh_client_is_missing`:242（新） |
| §5.2 配置文件损坏 | ✅ | `test_corrupt_config_is_refused_with_a_readable_message`:274（新）；`tests/unit/test_launcher.py:224` 文案 |
| §5.2 脚本路径包含空格 | ✅ | `test_spaces_in_the_script_path`:387（新）；WSL 侧同一用例通过（§5.5） |
| §5.2 从不同工作目录执行脚本 | ✅ | `test_runs_from_a_different_working_directory`:303（新）、`test_wrapper_runs_from_an_unrelated_working_directory`:378（新）；§5.4 跨目录调用 |
| §5.2 停止是否只影响 AWFM 管理的进程 | ✅ | `test_stop_does_not_touch_unrelated_processes`:209（新）；`tests/unit/test_launcher.py:77-95` 映像名闸门 |
| §5.2 错误信息是否清晰 | ✅ | 上述用例断言的人话文案：坏配置给出 `--init-config` 出路、缺 ssh 给出按平台安装指引、重复启动与端口占用给出下一步 |
| §5.2 发行包解压后能否独立运行 | ✅ | §5.4：解压到独立目录后 `check` / `start` / `GET /` / `status` / `stop` 全通 |
| §5.3 主机指纹确认流程 | ✅ | `tests/security/test_host_key.py`（7 项）、`tests/e2e/test_browser_flow.py`（3 项） |
| §5.3 密钥认证 | ✅ | `tests/integration/test_connection_flow.py`（10 项）；`test_password_auth.py` 覆盖密码模式 |
| §5.3 SFTP 连接与目录浏览 | ✅ | `tests/integration/test_api_flow.py`（8 项） |
| §5.3 文件搜索 | ✅ | unit 36 项 + integration 15 项 + security 18 项 + e2e 4 项 |
| §5.3 预览、编辑 | ✅ | `tests/unit/test_editor.py`（43 项）+ `tests/integration/test_edit_api.py`（32 项）+ `tests/security/test_edit_paths.py`（12 项）+ `tests/e2e/test_browser_edit.py`（7 项） |
| §5.3 写权限控制 | ✅ | `tests/unit/test_permission_sync.py`（6 项）+ `tests/integration/test_write_permission_sync.py`（4 项）+ `tests/security/test_write_permission_paths.py`（3 项） |
| §5.3 文件冲突检测 | ✅ | sha256 / mtime 不一致返回 409（`tests/integration/test_edit_api.py`） |
| §5.3 上传、下载及内容完整性 | ✅ | `support.upload_bytes` / `download_bytes` 走完整 HTTP 往返比对字节；下载票据 `tests/unit/test_tickets.py`（11 项） |
| §5.3 连接断开与恢复 | ✅ | `tests/integration/test_connection_flow.py` 的错误路径与进程清理；e2e 对缺陷 D2 的回归 |
| §5.4 运行 `python scripts/test.py` | ✅ | §5.1，退出码 0 |
| §5.4 静态检查与发行包检查 | ✅ | §5.3（8 项）、§5.4（构建 + 独立运行） |
| §5.4 差异必须逐层说明 | ✅ | §5.1 的「与阶段四的差异」段：新增 5 项、通过数、失败 0、跳过 1 及原因 |

## 六、问题与风险

### 6.1 过程中解决与处理的问题

1. **测试侧三处假设写错**（详见 §4.1）：坏配置下 `status` 的退出码、外壳的相对路径调用、decoy 进程未清理。都在本阶段内改正，未改动产品代码。
2. **5 处覆盖缺口**（详见 §3.1）已由 6 项新用例补齐（「从不同工作目录执行」在启动器与外壳两处各一项）；其中「缺 ssh 客户端」与「坏配置」两项原先只有函数级证据，现在有了子进程级、带退出码与副作用断言的证据。
3. **测试并发与端口**：新增用例沿用 `support.free_port()` 先探后用的方式；`test_stop_does_not_touch_unrelated_processes` 与 `test_spaces_in_the_script_path` 单独跑一遍（`Ran 2 tests in 17.368s / OK`）后再纳入全量回归。

### 6.2 未覆盖与未验证清单（如实记录）

| 项 | 现状 | 说明 |
|---|---|---|
| 发行包在 Linux/macOS 上解压运行 | 未验证 | 本阶段只对 Windows 包做了独立运行验收；Linux 侧只验了 `run.sh` 的语法与实际执行（§5.5） |
| Python 3.13 下跑完整四层回归 | 未验证 | 发行包内自检用的是 `py -3`（3.13.16），只跑了 `check` / `start` / `status` / `stop`；仓库回归始终用 3.12.10 |
| §5.2「Python 不存在」的真实重跑 | 未重跑 | 阶段三已用 `.temp/launcher-accept/cases/no-python.cmd` 真实验收，素材仍在，本阶段以既有证据引用 |
| §5.3 的 SSH 项在真实 CentOS 目标上重跑 | 未重跑 | 四层测试用本地替身/假 sftp 服务覆盖；真实环境用于阶段四教程核验，端到端 CU 验收在阶段六 |
| 真实桌面 CU 交互（任务书 §六 的 12 条） | 不属于本阶段 | 阶段六执行 |

### 6.3 风险与缓解

| 风险 | 缓解 |
|---|---|
| 停止操作误伤无关进程 | 两道闸门（只认 PID 文件 + 映像名必须含 `python`）且有端到端用例；没有 PID 文件时绝不去动占用端口的程序 |
| 端口先探后用存在竞态（TOCTOU） | 测试统一用 `support.free_port()`；四层 800+ 项历史上无端口相关 flake；真实使用时端口冲突会由 `start` 明确拒绝并给出提示 |
| Windows 上无窗口进程无法优雅停止 | `stop` 需要 `--force` 时明确提示并强制终止（包内验收已实测），不会留下 PID 文件 |
| 发行包只在 Windows 验证过 | 由 `scripts/build.py` 的 import 扫描（零第三方依赖）与 `run.sh` 的 WSL 实跑共同保证可移植性；阶段七打包时会再走一遍 |

## 七、文档与交付物

| 文件 | 说明 |
|---|---|
| `tests/integration/test_launcher_lifecycle.py` | 7 → 13 项（413 行）；新增 5 项缺口用例，工具函数支持 `cwd` 与自定义 `root` |
| `tests/integration/_index.md:15` | 登记 13 项与新增 5 项的覆盖点 |
| `docs/reports/PHASE-05-REGRESSION-v012.md` | 本报告 |
| `docs/reports/_index.md` | 报告索引新增一行 |
| `docs/CHANGELOG.md` | v0.1.2 段：状态行、提交纪律（阶段五哈希）、阶段进度表拆行、新增/变更条目 |

不提交的证据（`.temp/`）：`.temp/full-test-v012-p5.log`（四层回归全文）、`.temp/build-check-v012.log`（静态检查）、`.temp/package-v012.log`（打包）、`.temp/pkg-run/evidence.txt`（发行包独立运行 102 行）、`.temp/wsl-runsh-v012.log`（WSL）。

## 八、阶段结论

1. 任务书 §5.1 ~ §5.4 全部条款有对应证据（§5.6 逐条对照），**无未落地条款**。
2. 四层回归全绿（§5.1）；与阶段四相比只有 integration 层数量变化（新增 5 项用例），失败 0、错误 0、跳过 1（Windows 平台跳过的 `SignalTest`，在 WSL2 Ubuntu 上真跑通过）。
3. 静态检查 8 项通过；发行包可在独立目录解开、启动、访问、停止，且跨目录调用仍然正确。
4. **本次维护未破坏既有功能**：`app/` / `frontend/` / `scripts/` 在本阶段一行未改，回归结论可作为阶段六真实桌面验收的基线。
