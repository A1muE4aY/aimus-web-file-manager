# 阶段七报告：版本与交付（v0.1.2）

## 一、报告信息

| 项目 | 内容 |
| --- | --- |
| 版本 | v0.1.2（`app/__init__.py:7` = `0.1.2`） |
| 阶段 | 阶段七：版本与交付（v0.1.2 七阶段的最后一个阶段） |
| 依据 | `dev_guide/0.1.2_.md` §7「阶段七：版本与交付」与 §9.1 报告模板（只读输入） |
| 日期 | 2026-10-17 |
| 基线提交 | `8a5e932`（阶段六收尾，分支 `master`） |
| 验证方式 | 静态检查 8 项；打包脚本自检（CRC + 逐文件 SHA-256）；zip 的 SHA-256 两条独立命令复核；解压到**含空格路径**的独立目录后跑真实启动、HTTP、停止流程；`grep` 核对文档版本一致性 |
| 结论 | 版本号、文档、发行包与校验和全部对齐，**允许作为 v0.1.2 交付** |

本报告是 v0.1.2 的**最终报告**，同时承担任务书 §7.4 要求的十项汇总（见 §七 的表）。各阶段的原始记录仍在各自的阶段报告里，本文件不覆盖它们。

## 二、阶段目标

任务书 §7 的四条要求与最终完成标准：

| 条款 | 要求要点 | 落地位置 |
| --- | --- | --- |
| §7.1 | 版本升到 0.1.2；更新变更日志、发布说明、用户指南、报告索引；页面徽标与发行包一致；检查文档是否还把旧启动脚本当默认入口；不覆盖 v0.1.1 的历史证据 | `app/__init__.py:7`、`app/api/http_server.py:117`、`README.md`、`docs/CHANGELOG.md`、`docs/RELEASE.md`、`docs/USER_GUIDE.md:3`、`docs/API.md:5`、`docs/SSH_SETUP_GUIDE.md:3`、`docs/reports/_index.md`；本报告 §三.1 |
| §7.2 | Git：不覆盖未提交修改；每阶段清晰提交；不在未验证状态打发布标签 | 本报告 §七.2（提交记录）、§七.3（标签结论） |
| §7.3 | 重建 Windows 便携包；`run.bat` 存在可执行、文档与脚本匹配、不再要求 `start.cmd`/`stop.cmd`、目录初始化正确、解压到独立目录能启动、SHA-256 已更新并独立复核；Linux 侧同步检查 | `dist/AWFM-0.1.2-windows-x64.zip`、`dist/SHA256SUMS.txt`；本报告 §三.2、§三.3、§五.3、§五.4 |
| §7.4 | 最终报告十项（遗留清单 / 每项状态与根因 / 文件列表布局 / 启动脚本 / SSH 教程 / 自动化统计 / 真实 CU / 未验证项 / Git 记录 / 发行包与哈希） | 本报告 §七.1 的十项对照表 |

**最终完成标准 8 条**（任务书 §7 末）：遗留问题已核实；高优先级缺陷已修或说明阻塞；按钮位置稳定、长文件名可看全；`run.bat` / `run.sh` 提示清晰；教程覆盖常见场景；自动化回归通过；真实 CU 完成且未验证项如实记录；发行包与文档一致可追溯。逐条判定见 §八。

## 三、实际完成情况

### 3.1 版本号与六处文档同步

- **唯一来源升号**：`app/__init__.py:7` 由 `0.1.1` 改为 `0.1.2`；`scripts/build.py` 第 7 项（`check_version_consistency`）要求同一版本号同时出现在 `README.md` 与 `docs/CHANGELOG.md`，因此这三处必须一起改，否则静态检查直接失败。
- **HTTP 响应头**：`app/api/http_server.py:117` 的注释里写的是 `AWFM/0.1.1` 字面量，实际代码用 `server_version = f"AWFM/{__version__}"` 生成，注释同步改为 `0.1.2`；解压验收里 `GET /` 与 `run.bat status` 都显示 0.1.2。
- **`README.md` 六处**：当前版本（改为 v0.1.2 并列出七阶段维护内容）、测试状态（单元 588 / 集成 125 / 安全 82 / 端到端 32 = 827 项）、发行包名（`dist/AWFM-0.1.2-windows-x64.zip`）、决策范围（D-001 ~ D-021）、阶段报告范围（v0.1.2 为 01~07）、规划文档链接（由 `.md` 改为 `dev_guide/`）；已知限制改为「自动化跑在 WSL 测试床，真实 CentOS Stream 10 由各阶段人工 CU 覆盖；未做系统级断网验证」。
- **`docs/USER_GUIDE.md:3`**：改为 `版本：v0.1.2　文档日期：2026-10-17（手册主体写于 v0.1.0/v0.1.1，v0.1.2 增补了 SSH 教程入口与启动方式）`。
- **`docs/API.md:5`**：文档日期 2026-10-17、版本 `0.1.2`、端点总数 32（20~22 检索、23~28 在线编辑与文件操作、29~32 在线虚拟机发现，均为 v0.1.1 引入，**v0.1.2 未增删任何端点**）。
- **`docs/SSH_SETUP_GUIDE.md:3`**：适用版本「**AWFM v0.1.2**（2026-10-17 发布；启动横幅与 `run.bat status` 显示同一个版本号）」，去掉了阶段四写作时的「开发中」表述。
- **`docs/CHANGELOG.md`**：标题由 `## [v0.1.2] — 未发布` 改为 `## [v0.1.2] — 2026-10-17`；版本号行去掉「尚未改号」的说法；状态行由「开发中」改为「已完成（阶段一~七，2026-10-17）」并追加阶段七段落；「版本标识」段补 v0.1.2 的产物与「仓库至今没有任何 git 标签」的说明；阶段进度表「七」行由「未开始」改为已完成（含发行包路径与验收结论）。
- **`docs/RELEASE.md`** 全面改写为 v0.1.2（见 §四.5）。
- **旧启动脚本**：任务书 §7.1 要求检查「文档是否还把旧启动脚本当默认入口」。仓库内 `start.cmd` / `stop.cmd` 只在**历史记录**里出现（v0.1.2 阶段三把二者从发行包移除，`docs/reports/PHASE-03-LAUNCHER-v012.md` 与 v0.1.1 的历史报告保留了这件事的来龙去脉）；所有面向用户的入口说明都已是 `run.bat` / `run.sh`。
- **历史证据不被覆盖**：v0.1.0 / v0.1.1 的发行包（`dist/AWFM-0.1.0-windows-x64.zip`、`dist/AWFM-0.1.1-windows-x64.zip`）、旧报告 `docs/reports/PHASE-0*-*.md`、`docs/TEST_REPORT.md`、v0.1.0/v0.1.1 的 CHANGELOG 段落全部原样保留。

### 3.2 发行包重建

- 命令：`python -X utf8 scripts/package.py`；先跑 `scripts/build.py` 的 8 项静态校验（全部通过），再暂存白名单文件 → 生成 `VERSION` 与 `MANIFEST.json` → 以固定时间戳（1980-01-01）压缩 → `testzip()` 校验 CRC → 逐文件比对清单哈希 → 检查有没有清单外的成员。
- 产物：`dist/AWFM-0.1.2-windows-x64/`（104 个文件、1,519,434 字节）、`dist/AWFM-0.1.2-windows-x64.zip`（104 个成员、631,659 字节 = 616.9 KB）、`dist/SHA256SUMS.txt`。
- 顶层条目：`app, config, docs, frontend, scripts, LICENSE, MANIFEST.json, README.md, run.bat, run.sh, VERSION`——**没有 `tests/`**、没有 `data/` 与 `logs/`、**没有 `start.cmd` / `stop.cmd`**；`run.bat` 与 `run.sh` 都在，`docs/SSH_SETUP_GUIDE.md` 已随包分发。
- `MANIFEST.json`：`file_count = 103`（清单不登记自身），加自身正好 104；`VERSION` 内容为 `AWFM 0.1.2` / 构建时间 `2026-10-17T05:21:39` / 平台 `windows-x64` / 构建主机 Python `3.12.10`。
- 与 v0.1.1 的 95 个文件 / 588.8 KB 相比，增量来自 v0.1.2 新增的 `scripts/launcher.py`、`run.bat`、`run.sh`、`docs/SSH_SETUP_GUIDE.md`（1627 行）与七份阶段报告。

### 3.3 校验和与独立复核

`dist/SHA256SUMS.txt` 记录**本次构建**的 zip 与 `MANIFEST.json` 两个哈希。为避免「自己写自己」的循环，zip 的哈希用两条互相独立的命令复核：

| 复核方式 | 命令 | 结果 |
| --- | --- | --- |
| PowerShell 哈希提供程序 | `Get-FileHash -Algorithm SHA256 dist\AWFM-0.1.2-windows-x64.zip` | `5026A45AD5CCC9904EFD15AB432C0B171CC5D977047F045E2EBF4FCCC05AAC3A` |
| 系统证书工具 | `certutil -hashfile dist\AWFM-0.1.2-windows-x64.zip SHA256` | `5026a45ad5ccc9904efd15ab432c0b171cc5d977047f045e2ebf4fccc05aac3a` |
| 打包脚本自报 | `scripts/package.py` 末行 | `5026a45ad5ccc9904efd15ab432c0b171cc5d977047f045e2ebf4fccc05aac3a` |

三者一致（大小写不同，值相同）。包内另有 `MANIFEST.json` 的**逐文件**哈希，用于校验解压后的内容是否被改动。

> 说明：zip 自身的哈希**刻意不写进包内文档**（`docs/` 属于包内容，写进去会立刻改变包内容使哈希失效），所以 `docs/RELEASE.md` 只解释校验方式、不记录该值；哈希只存在于 `dist/SHA256SUMS.txt`（不在包内）与本报告。

### 3.4 解压到独立目录后的独立运行

解压目标刻意选在**含空格的路径**下：`.temp/pkg-run-012/AWFM test dir/`（任务书 §7.3 要求「解压到独立目录能启动」；含空格路径同时在回归 v0.1.2 阶段三发现的「路径带空格」场景）。

| 步骤 | 命令 | 结果 |
| --- | --- | --- |
| 1 | `run.bat check` | 退出码 0；9 项自检通过 + 1 项警告（`data/known_hosts` 尚未建立，首次确认指纹后创建） |
| 2 | `run.bat start --no-browser --port 32611` | 退出码 0；`[ OK ] AWFM 已启动（版本 0.1.2）`，PID 38976，配置不存在时提示「本次用内置默认值启动」 |
| 3 | `GET http://127.0.0.1:32611/` | HTTP 200，7399 字节，标题含 `AWFM`，页面内外网 URL 数 **0** |
| 4 | `GET /api/health` | HTTP 200，`{"ok": true, "data": {"status": "ok", "version": "0.1.2", "connections": 0}}` |
| 5 | `run.bat status` | 退出码 0；`状态：运行中（PID 38976，http://127.0.0.1:32611/，版本 0.1.2）` |
| 6 | `run.bat stop --force --yes` | 退出码 0；Windows 拒绝优雅停止 → `taskkill /F`，`[ OK ] AWFM 已停止（强制终止）。` |
| 7 | 残留检查 | 端口 32611 监听数 **0**；`data/awfm.pid` 已删除；包内 `data/`、`logs/` 自动生成（`logs/` 内有 `awfm.log`、`awfm-console.log`） |
| 8 | 从无关工作目录调用 `<包路径>\run.bat status` | 退出码 3；`状态：没有运行 / 端口：空闲`（外壳不依赖当前工作目录） |

原始输出见 `.temp/pkg-run-012/evidence.txt`（§五.4 摘录了判定性行）。

### 3.5 Linux 侧同步检查

便携包的 Linux 外壳 `run.sh` 在 v0.1.2 阶段五已做过 `bash -n` / `sh -n` 语法检查与真跑（WSL2 Ubuntu 24.04，`WrapperExitCodeTest` 6 项通过），阶段六又在真实终端里跑完整链路并留下证据（`.temp/cu-v012-stage6/51-wsl-runsh.png`）。本阶段重新打包后，包内 `run.sh` 与仓库同源（打包脚本按白名单复制，`MANIFEST.json` 的逐文件哈希可证），因此不需要重跑；`bash -n run.sh` 在本阶段再次执行仍为通过。

## 四、技术实现

### 4.1 版本唯一来源与三处校验

版本号的唯一来源是 `app/__init__.py:7`；`app/api/http_server.py:117` 附近用 `f"AWFM/{__version__}"` 生成 `Server` 头（注释是给人看的字面量，容易忘记同步，本次一并改掉）。`scripts/build.py` 的第 7 项 `check_version_consistency()`（`:222`）同时检查 `app/__init__.py` 的 `__version__`、`README.md` 与 `docs/CHANGELOG.md` 三处是否一致；`scripts/package.py` 把它作为打包前的第 1 步，所以「文档忘改」会直接导致打包失败，而不是产出一个版本号自相矛盾的包。

### 4.2 打包流程与可复现性

`scripts/package.py` 的 `STAGE_DIRS = ("app", "frontend", "docs")`、`STAGE_SCRIPTS = ("start.py", "launcher.py")`、`STAGE_FILES = ("README.md", "LICENSE", "config/config.example.json", "VERSION", "run.bat", "run.sh")`（`:49-51`）决定包内容；必需文件清单里已经包含 `run.bat` / `run.sh` / `scripts/launcher.py`，缺失即判定打包失败。压缩使用**固定时间戳（1980-01-01）**，所以同样输入产出同样的字节；只有 `VERSION` 里的构建时间会变，因此**同一版本重新打包得到的哈希不同是刻意的**（哈希用于校验这一份拷贝，不是标识这一个版本）。

### 4.3 独立复核为什么要两条命令

打包脚本自己会算哈希，但「用同一段代码算出来的哈希」不能证明文件没坏——它只能证明「脚本认为它算出来的值等于它自己写的值」。所以复核用两条**互不共享代码**的系统命令：PowerShell 的 `Get-FileHash` 与 Windows 自带的 `certutil -hashfile`，只有两者与 `SHA256SUMS.txt` 三方一致才算通过。

### 4.4 解压验收为什么放在含空格的路径

含空格路径是 v0.1.2 阶段三的真实缺陷现场（`run.bat` 早期版本在 `%~dp0` 带空格时找不到同级 `scripts/launcher.py`）。把独立运行验收固定放在 `.temp/pkg-run-012/AWFM test dir/`，等于每次打包都顺带回归这条路径；验收脚本里也设了 `AWFM_NO_PAUSE=1`，用于让菜单外壳在非交互环境下不阻塞。

### 4.5 `docs/RELEASE.md` 的改写范围

| 小节 | 改动 |
| --- | --- |
| §1 发行概览 | 版本 0.1.2、发行日期 2026-10-17、产物名 `dist/AWFM-0.1.2-windows-x64.zip`，并说明 v0.1.0/v0.1.1 的包仍保留 |
| §2 便携包内容 | 目录树说明含 `run.bat` / `run.sh` / `scripts/launcher.py`；必需文件清单含三者 |
| §3 构建与打包步骤 | 数字口径换成 v0.1.2 的 104 个文件 / 1,519,434 字节 / zip 631,659 字节 |
| §4 校验和 | 文件名与命令示例换成 v0.1.2；保留「为什么不把包自身哈希写进包内文档」的说明 |
| §5 安装与运行 | 默认端口 32579、含空格路径已验收、停止走同一入口 |
| §6 版本与构建记录 | `app/__init__.py:7` 的值改为 `0.1.2` |
| §8 发行验收 8 项 | 第 1、7、8 项换成 v0.1.2 的实测证据（解压验收、包内文档版本一致、VERSION/MANIFEST/SHA256SUMS 三者齐全 + 双工具复核） |
| §9 已知限制 | 补三条：Windows 后台服务无温和停止（平台行为）、`run.bat` 的 GBK 缺陷已修、教程 7 项未实测步骤已标注 |

## 五、测试结果

### 5.1 四层自动化（最终数字）

`python scripts/test.py -v`（阶段六修复 e2e 竞态后复跑，日志 `.temp/full-test-v012-p6.log` 与 `.temp/e2e-v012-p6.log`）：

| 层 | 数量 | 结果 | 耗时 |
| --- | --- | --- | --- |
| unit（单元） | 588 | OK（skipped=1） | 4.26 s |
| integration（集成） | 125 | OK | 331.56 s |
| security（安全） | 82 | OK | 473.10 s |
| e2e（端到端） | 32 | OK | 220.39 s |
| **合计** | **827** | **0 失败 / 0 错误 / 1 跳过** | 1029.31 s（层耗时相加） |

与**上一版本**（阶段五基线的 817 = 579 / 124 / 82 / 32）的差异说明（任务书 §5.4 要求逐项说明，不得只报总数）：

| 层 | 上一版 | 本版 | 新增 | 通过 | 失败 | 跳过 | 差异原因 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| unit | 579 | 588 | **+9** | 588 | 0 | 1 | 新增 `tests/unit/test_run_bat.py` 9 项（`run.bat` 的 CRLF 纪律、引导段纯 ASCII、五个标记与顺序、不得回退到括号块、`%*` 原样转发、中文文案仍在） |
| integration | 124 | 125 | **+1** | 125 | 0 | 0 | `WrapperExitCodeTest` 新增「在代码页 936 的控制台里 `call run.bat help`」1 项，断言退出码 0、输出含 `AWFM`、不含 `not recognized` / `不是内部或外部命令` |
| security | 82 | 82 | 0 | 82 | 0 | 0 | 本阶段未改动安全相关代码 |
| e2e | 32 | 32 | 0 | 32 | 0 | 0 | 用例数不变；阶段六首跑有 1 项失败（`tests/e2e/test_browser_edit.py:275` 撞上等待表达式竞态），修 9 处表达式后整层复跑全绿（见 §六.1） |

唯一跳过项是 `tests/unit/test_launcher.py` 的 `SignalTest`（Windows 没有 POSIX 信号，按平台跳过；v0.1.2 阶段三与阶段五在 WSL2 Ubuntu 24.04 里真跑通过）。

### 5.2 静态检查（8 项）

`python -X utf8 scripts/build.py`（打包脚本会自动先跑一遍，两处输出一致）：

| # | 检查 | 结果 |
| --- | --- | --- |
| 1 | Python 版本（≥3.10） | 通过（3.12.10） |
| 2 | 语法校验（SyntaxWarning 视为错误） | 通过（`app/` `tests/` `scripts/`） |
| 3 | 零第三方依赖（import 扫描） | 通过（42 个源文件，全部标准库） |
| 4 | 前端离线（无 CDN / 在线字体） | 通过（19 个前端文件，无外部 URL） |
| 5 | 凭据纪律（无私钥 / 无明文密码） | 通过（扫描 **56** 个可能被提交的文件——比阶段五的 54 个多出阶段六、七新增的报告与 `tests/unit/test_run_bat.py`；3 处示例占位符放行：`docs/API.md:338`、`docs/DECISIONS.md:236`、`docs/reports/PHASE-06-RELEASE.md:90`） |
| 6 | 错误模型回归（`http_status` 不是构造参数） | 通过 |
| 7 | 版本一致性（`__version__` = README = CHANGELOG） | 通过（`0.1.2`） |
| 8 | 测试包结构（四层都有 `__init__.py`） | 通过 |

### 5.3 发行包自检

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| CRC 完整性 | `zipfile.testzip()` | 通过 |
| 逐文件哈希 | 与 `MANIFEST.json` 比对 | 103 项全部一致 |
| 清单外成员 | 目录成员集合比对 | 无 |
| 双工具复核 | `Get-FileHash` + `certutil` | 一致（§三.3） |

### 5.4 解压独立运行（判定性摘录）

```
===== 1 run.bat check =====               EXIT=0   （9 项通过 + 1 警告）
===== 2 run.bat start --port 32611 =====   EXIT=0   [ OK ] AWFM 已启动（版本 0.1.2）  PID 38976
===== 3 GET / =====                       HTTP 200 ; bytes=7399 ; title ok: True ; external url count: 0
                                          health HTTP 200 : {"status": "ok", "version": "0.1.2", ...}
===== 4 run.bat status =====               EXIT=0   运行中（PID 38976，http://127.0.0.1:32611/，版本 0.1.2）
===== 5 run.bat stop --force --yes =====   EXIT=0   AWFM 已停止（强制终止）
===== 6 residuals =====                    listeners on 32611: 0 ; pid file exists: False ; logs: awfm.log, awfm-console.log
===== 7 status from unrelated cwd =====    EXIT=3   状态：没有运行 / 端口：空闲
```

## 六、问题与风险

### 6.1 本阶段（含阶段六遗留）解决的问题

| # | 问题 | 根因 | 处理 |
| --- | --- | --- | --- |
| 1 | e2e 首次全量跑出现 1 项失败（`tests/e2e/test_browser_edit.py:275`） | `tests/e2e/support.py` 的 `navigate()` 发完 `Page.navigate` 就返回、不等加载；紧随其后的 `!document.getElementById('app').hidden` 遇到尚未解析的 DOM 抛 `TypeError`，而 `wait_for()` 遇异常冒泡、不再轮询 | 9 处调用点统一改成空值安全表达式 `!!document.getElementById('app') && !document.getElementById('app').hidden`；整层复跑 32 项全绿（详见 `docs/reports/PHASE-06-CU-ACCEPTANCE-v012.md` §4.6） |
| 2 | `run.bat` 在 GBK（936）控制台里打印两行假错误 | `cmd.exe` 按控制台代码页逐行读取批处理文件，UTF-8 文件在中途执行 `chcp 65001` 会导致字节/字符记账错位，中文 `rem` 行被截断后当成命令执行 | 文件开头改为纯 ASCII 引导段（`chcp` → 置环境变量 → 用子进程重跑自身 → `exit /b %ERRORLEVEL%`），中文说明整体后移；补 9 项静态单测 + 1 项 `chcp 936` 集成用例（详见 `docs/reports/PHASE-06-CU-ACCEPTANCE-v012.md` §3.3） |
| 3 | 阶段七重建包时若 `PYTHONUTF8` 环境变量拼错会误报语法校验失败 | 命令写法问题（`set PYTHONUTF8=1 && …` 会把尾随空格带进变量值，Python 报 `invalid PYTHONUTF8 environment variable value`） | 改用 `python -X utf8` 显式指定，不依赖环境变量；这是操作陷阱、不是产品缺陷，记录在此以免复现 |

本阶段**没有发现新的产品缺陷**：`app/` 只改了版本号与一行注释，`frontend/` 一行未动，`scripts/` 一行未动。

### 6.2 未验证项与已知限制（如实登记）

1. **SSH 教程的 7 项未在本机实测**（阶段四登记，本阶段复核后仍然成立）：sudo/root 类命令（本机无免密 sudo）、SELinux 相关命令（测试机 SELinux 为 Disabled）、firewalld 相关命令（未运行 firewalld）、Windows 安装 OpenSSH 客户端与 ssh-agent 服务、macOS 与 `ssh-add --apple-use-keychain`、静态 IP / DHCP 保留步骤、`ProxyJump` 对 AWFM 是否生效（无跳板机）。教程内逐处标了【未验证】，附录 B 有完整清单。
2. **平台范围**：便携版只验了 Windows x64 宿主机；Linux / macOS 只在 WSL2 Ubuntu 24.04 里验了外壳与启动器，没有第二台原生 Linux 宿主机，macOS 完全未验证。
3. **未做系统级断网验证**：只有静态扫描（零外部 URL、零第三方依赖）与端到端「对外请求为空」的间接证据。
4. **`run.sh check` 在双系统同端口时会被误判为失败**：Windows 侧 8760 实例在跑时，WSL2（mirrored 网络）能看到宿主监听，于是 `check` 报「端口已被占用」、退出码 1；这是环境重叠，不是缺陷（`docs/reports/PHASE-06-CU-ACCEPTANCE-v012.md` §6.2）。
5. **跨系统的 PID 可见性**：在 WSL 里读 Windows 写的 `data/awfm.pid` 会得到「PID 已经不存在」，属预期。
6. **CU 驱动的按键被转成大写**：真实桌面 CU 里键盘输入落到页面时是大写（驱动侧现象），因此写文件类验收以 2 B 内容往返为准，不能据此判断产品行为。

### 6.3 风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 同一版本重新打包得到不同哈希 | 用户按哈希比对时可能困惑 | `docs/RELEASE.md` §4 明确说明：哈希用于校验「这一份拷贝」，`VERSION` 里的构建时间必然变化 |
| 用户误把旧包（0.1.1）当新包 | 界面显示 0.1.1，功能缺失 | 三个包并存但目录名/压缩包名带版本号；`VERSION`、界面徽标、`run.bat status` 三处一致可自查 |
| 未打 git 标签导致无法按标签回溯 | 只能按提交哈希回溯 | 本报告 §七.2 记录七阶段全部提交哈希；标签策略见 §七.3 |
| 教程的未实测步骤被当作已验证 | 用户按错误预期操作 | 教程内【未验证】标记 + 附录 B + 决策 D-021 + `tests/unit/test_ssh_guide.py` 的纪律断言 |

## 七、文档与交付物

### 7.1 任务书 §7.4 十项对照

| # | 要求 | 位置 |
| --- | --- | --- |
| 1 | 开发前的遗留问题清单 | `docs/reports/PHASE-01-LEGACY-v012.md` §2~§3（六项遗留：①④⑤⑥ 通过、② 部分、③ 确认缺陷 D1、⑤ 确认缺陷 D2）；原始清单来自 v0.1.1 的 `docs/reports/PHASE-06-CU-ACCEPTANCE.md` |
| 2 | 每项遗留的状态、根因与处理 | 同上 §3~§6：D1（切换目录后残留菜单/提示）、D2（目录扫描与请求体上限）已修并补 25 项回归；未消除项在该报告 §6.2 逐条写明 |
| 3 | 文件列表布局改动与验收 | `docs/reports/PHASE-02-LAYOUT-v012.md`（固定列宽与五槽位操作区、断点阶梯、完整名称三条途径、三处自绘菜单；8 项 e2e + 真实桌面 CU 前后证据） |
| 4 | 启动脚本的设计、行为与兼容性 | `docs/reports/PHASE-03-LAUNCHER-v012.md`（`run.bat` / `run.sh` + `scripts/launcher.py`，八命令与菜单、退出码 0/1/2/3、停止只动自己记录的 PID、默认端口 32579、Windows 34 项 + Linux 12 项真实验收）；决策 D-020 |
| 5 | SSH 教程的目录结构与验证范围 | `docs/SSH_SETUP_GUIDE.md`（1627 行，A~L 十二节 + 附录 A 选项表 / 附录 B 验证记录）；`docs/reports/PHASE-04-SSH-GUIDE-v012.md` §5~§6；决策 D-021 |
| 6 | 自动化测试统计与实际命令 | 本报告 §5.1（827 项）与 §5.2（静态检查 8 项）；命令 `python scripts/test.py -v`、`python -X utf8 scripts/build.py` |
| 7 | 真实桌面 CU 验收记录 | `docs/reports/PHASE-06-CU-ACCEPTANCE-v012.md`（任务书 §6 十二条逐条执行，证据 `.temp/cu-v012-stage6/` 01~54 号截图 + 裁图）；阶段一~三的 CU 证据在 `.temp/cu-v012/` |
| 8 | 未验证项、已知限制与剩余风险 | 本报告 §6.2 与 §6.3；各阶段报告的「未验证清单」小节；`docs/CHANGELOG.md` v0.1.2 的「已知限制」段 |
| 9 | Git 提交记录 | 本报告 §7.2 |
| 10 | 发行包路径与 SHA-256 | 本报告 §3.2、§3.3；`dist/AWFM-0.1.2-windows-x64.zip`（`5026a45ad5ccc9904efd15ab432c0b171cc5d977047f045e2ebf4fccc05aac3a`）、`dist/SHA256SUMS.txt` |

### 7.2 Git 提交记录（v0.1.2 七阶段）

| 阶段 | 提交 | 说明 |
| --- | --- | --- |
| 一 | `24fd0b2` + 收尾 `97e68d0` | 遗留问题复核、D1/D2 缺陷修复与回归（20 个文件 / +889 −33） |
| — | `0728358` | 规划文档迁入 `dev_guide/`（5 个文件；三个重命名 + 一个新文件） |
| 二 | `9bbf7a3` + 收尾 `ae6165d` | 文件列表布局固定化与自绘右键菜单（14 个文件） |
| 三 | `9b5abe1` + 收尾 `8222f06` | 统一启动脚本 `run.bat` / `run.sh`（29 个文件 / +2119 −123） |
| 四 | `2e75ef1` + 收尾 `13d778a` | SSH 配置教程与入口、决策 D-021、13 项一致性单测（10 个文件 / +2032 −2） |
| 五 | `6225c4b` + 收尾 `a9cae30` | 回归测试与安全检查，补 6 项启动脚本缺口用例、静态检查与发行包独立运行验收（5 个文件 / +413 −10） |
| 六 | `fbf0e74` + 收尾 `8a5e932` | 真实桌面 CU 验收 12 条，修复 `run.bat` 在 GBK 控制台下的假错误并补 10 项回归测试（16 个文件 / +515 −15） |
| 七 | `ef411c4` + 收尾提交 | 版本与交付（升号、文档同步、重建发行包与校验和、解压验收、本报告；10 个文件 / +327 −33） |

每个阶段独立成一个提交，收尾提交只做一件事：把该阶段的提交哈希记进 `docs/CHANGELOG.md` 的提交纪律列表。任务书 §7.2 要求的「不覆盖用户未提交修改」在阶段一就已遵守：用户既有的 `0.md` / `1.md` / `2.md` 删除与未跟踪的 `dev_guide/` 没有被任何提交包含。

### 7.3 发布标签的结论

仓库至今**没有任何 git 标签**（`git tag` 输出为空），v0.1.1 的 CHANGELOG 标题本身就是「`## [v0.1.1] — 2026-10-16（未打标签）`」，历史报告里「为 v0.1.1 起启用 git 标签」是**建议**而非既成事实。任务书 §7.2 只禁止「在未验证状态创建发布标签」，并未要求必须打标签。

本阶段的决定：**不打标签，并把这个结论写进记录**。理由有三：① 版本溯源已由「`app/__init__.py:7` 的唯一来源 + 逐阶段提交哈希 + 发行包哈希」三件事覆盖；② 仓库没有远端、没有发布流程，标签在当前使用方式下没有承载额外信息；③ 打一个不同于 v0.1.1 处理方式的新约定，应该由用户决定而不是由维护者顺手引入。如果用户希望启用标签，建议从 v0.1.2 起补打 `v0.1.2`，并同步更新 `docs/CHANGELOG.md` 的版本标识段。

### 7.4 交付文件

| 文件 | 说明 |
| --- | --- |
| `dist/AWFM-0.1.2-windows-x64.zip` | Windows x64 便携包（104 个文件、616.9 KB） |
| `dist/AWFM-0.1.2-windows-x64/` | 便携包解压目录（1,519,434 字节） |
| `dist/SHA256SUMS.txt` | 本次构建的 zip 与 `MANIFEST.json` 的 SHA-256 |
| `docs/RELEASE.md` | 发行说明（v0.1.2） |
| `docs/CHANGELOG.md` | 变更记录（v0.1.2 = 2026-10-17） |
| `README.md`、`docs/USER_GUIDE.md`、`docs/API.md`、`docs/SSH_SETUP_GUIDE.md` | 版本与日期已对齐的面向用户文档 |
| `docs/reports/PHASE-0{1..7}-*-v012.md` | 七个阶段报告（本文件是第七份） |

**不提交的内容**：`dist/`、`data/`、`logs/` 都在 `.gitignore` 里；CU 证据目录 `.temp/cu-v012/`（阶段一~三）与 `.temp/cu-v012-stage6/`（阶段六）以及 `.temp/pkg-run-012/`（本阶段）都是会话草稿，按 `AGENTS.md` 不进仓库。

## 八、阶段结论

阶段七完成：版本号统一升到 0.1.2，六处文档与页面徽标一致；Windows 便携包重建并**两种独立方式复核** SHA-256 一致；解压到含空格的独立目录后 `check` / `start` / `GET /` / `/api/health` / `status` / `stop` 全程跑通且无残留；四层自动化 827 项 0 失败 0 错误（1 项按平台跳过），静态检查 8 项通过。**允许作为 v0.1.2 交付。**

任务书 §7 的**最终完成标准 8 条**逐条判定：

| # | 标准 | 判定 | 依据 |
| --- | --- | --- | --- |
| 1 | 开发前的遗留问题已核实 | 通过 | 阶段一六项遗留逐条复核（`PHASE-01-LEGACY-v012.md` §3） |
| 2 | 高优先级缺陷已修或说明阻塞 | 通过 | D1、D2 已修并补 25 项回归；未消除项在报告 §6.2 逐条写明 |
| 3 | 操作按钮位置稳定、长文件名可看全 | 通过 | 阶段二固定五槽位 + 断点阶梯，8 项 e2e + 真实桌面 CU 前后证据 |
| 4 | `run.bat` / `run.sh` 提示清晰 | 通过 | 阶段三真实验收；阶段六修复 GBK 假错误后新控制台菜单干净 |
| 5 | 教程覆盖常见场景 | 通过（7 项未实测已标注） | `docs/SSH_SETUP_GUIDE.md` A~L + 16 类错误；附录 B 与决策 D-021 |
| 6 | 自动化回归通过 | 通过 | 827 项 0 失败 0 错误 1 跳过；静态检查 8 项 |
| 7 | 真实 CU 完成、未验证项如实记录 | 通过 | `PHASE-06-CU-ACCEPTANCE-v012.md` 十二条 + 本报告 §6.2 |
| 8 | 发行包与文档一致、可追溯 | 通过 | 版本三处一致（静态检查第 7 项）+ 包内文档同源 + `SHA256SUMS.txt` 与双工具复核 + 七阶段提交哈希 |
