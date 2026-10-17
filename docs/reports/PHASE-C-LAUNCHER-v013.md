# 阶段 C 报告：普通与高级启动脚本（v0.1.3）

## 1. 报告信息

| 项目 | 内容 |
|---|---|
| 版本 | v0.1.3 |
| 阶段 | C —— 启动脚本拆普通与高级、就绪后自动打开浏览器 |
| 日期 | 2026-10-17 |
| 依据 | `dev_guide/0.1.3_.md` §5 全部条款（普通入口、高级入口、浏览器打开、进程识别、失败提示） |
| 结论 | 完成。普通入口 `run.bat` / `run.sh`，高级入口 `run-advanced.bat` / `run-advanced.sh`；实现仍只有 `scripts/launcher.py` 一份。单元 `tests/unit/test_launcher.py` 58 项、`tests/unit/test_run_bat.py` 17 项、集成 `tests/integration/test_launcher_lifecycle.py` 18 项全部通过 |

## 2. 阶段目标

任务书 §5 的问题描述得很具体：双击启动脚本的用户想要的是「起来、浏览器打开、能用」，而 v0.1.2 的 `run.bat` 打开的是一个交互菜单，要再按一次数字；启动之后还得自己记住地址、自己复制到浏览器。同时另一类用户（要换端口、要看状态、要停、要重启、要排障）需要菜单和参数。

把一个入口硬拆成两套逻辑是最容易出错的方案（两份实现必然漂移），所以这一阶段的做法是：**外壳分两个，实现只有一份**。差异只允许出现在「不带参数时的默认动作」这一处，并且必须由测试钉住。

## 3. 实际完成情况

| # | 任务书要求 | 实现位置 | 状态 |
|---|---|---|---|
| C-1 | 保留现有能力作为「高级」入口 | `run-advanced.bat`（85 行，新增）、`run-advanced.sh`（42 行，新增） | 完成 |
| C-2 | 新增「普通」入口 | `run.bat` / `run.sh` 不带参数即普通启动（等价 `quick`） | 完成 |
| C-3 | 普通入口：查环境、默认配置、防重复启动 | `scripts/launcher.py:606` `cmd_quick()` → `check_python()` / `load_settings()` / `current_state()` | 完成 |
| C-4 | **服务真正就绪后**才打开浏览器 | `cmd_start()`（`launcher.py:516` 起）先 `spawn_service()` 再轮询 `http_health()`（`:180`），通过后才调用 `open_default_browser()`（`:441`） | 完成 |
| C-5 | 用系统默认浏览器，不硬编码 | Windows `os.startfile(url)`（ShellExecute）；macOS `open`；Linux 依次 `xdg-open` / `gio open` / `sensible-browser` | 完成 |
| C-6 | 打开失败只显示地址，不得误报为启动失败 | `open_default_browser()` 返回 `(bool, 说明)`；失败时打印「没能自动打开浏览器（…）。请手动在浏览器里打开：<URL>」，退出码仍为 `EXIT_OK` | 完成 |
| C-7 | 显示地址、结果、日志位置、停止方法 | `cmd_quick()` 成功分支打印地址 / 日志（`console_log` 与 `DEFAULT_APP_LOG`）/ 「停止：… run.bat stop」 | 完成 |
| C-8 | 出错时窗口可读、不闪退 | `pause_before_close()`（`:484`）在普通入口的**所有**退出路径上调用；`AWFM_NO_PAUSE=1` 或非 TTY 直接跳过 | 完成 |
| C-9 | 高级入口默认也要开浏览器 | `cmd_start()` 是两个入口共用的启动路径，`--no-browser` 是唯一关闭开关 | 完成 |
| C-10 | 不得无限等待，超时给诊断 | `--timeout` 默认 `DEFAULT_START_TIMEOUT`（20 秒，`:56`）；超时打印控制台日志尾部（`print_console_tail()`，`:427`）并返回 `EXIT_FAILED` | 完成 |
| C-11 | 不得重复弹标签页 | 启动子进程时强制附加 `--no-browser`（子进程自己不再开浏览器），只由启动器开一次 | 完成 |
| C-12 | 已在运行时给清晰提示与地址 | `cmd_quick()` 的「已在运行」分支打印地址与停止方法，并打开浏览器，一律 `EXIT_OK` | 完成 |
| C-13 | 准确识别自己的进程，不无差别杀 python/ssh | 沿用 v0.1.2 的 PID 文件 + `process_image_name()`（`launcher.py:112`）校验，未改动 | 完成 |

## 4. 技术实现

### 4.1 一份实现、两个外壳

四个外壳的分工被压到最小：

```
run.bat            → "%AWFM_PY%" "scripts\launcher.py" %*          （不带参数时 launcher 自己补 quick）
run-advanced.bat   → 不带参数：launcher.py menu；带参数：launcher.py %*
```

`run.bat` 一行都不改就是把默认动作交给 Python 侧（`launcher.py:1073` 的 `main()`：`if not raw: raw = ["quick"]`）。好处是「普通启动」的全部行为（就绪判断、浏览器、暂停、提示文案）都在能被单元测试覆盖的 Python 代码里，而不是散在批处理的 `echo` 里；坏处是批处理的可读性差一点——但 `run.bat` 本来就只做「找 Python + 转交参数」。

`run-advanced.bat` 必须显式传 `menu`，因为 launcher 的 argparse 默认值仍是 `menu`（`tests/unit/test_launcher.py:48` 断言 `parse_args([]).command == "menu"`，这是 v0.1.2 的既有契约，不能为了新需求推翻）。它用 `goto` 而不是 `if () else ()` 分支，原因是批处理在括号块里读 `%ERRORLEVEL%` 会拿到**进入块之前**的值（v0.1.2 在 GBK 控制台下踩过这个坑），所以退出码在 `:awfm_take_code` 标签处、块外读取。

### 4.2 「就绪」到底怎么判断

任务书写得很直白：不能只看 PID。`cmd_start()` 的顺序是：

1. `spawn_service()` 起子进程，子进程附加 `--no-browser`（`:390`）；
2. 轮询 `http_health(host, port)`（`:180`，`GET /api/health`，每次 1.5 秒超时）直到返回 `{"status": "ok"}` 或超时；
3. 只有第 2 步通过，才 `open_default_browser()` 并打印「已用系统默认浏览器打开地址」；
4. 超时则打印控制台日志尾部、给出诊断（端口被占 / 配置错误 / Python 太旧等），返回 `EXIT_FAILED`，**不开浏览器**。

单测 `test_http_health_fails_before_browser` 用一个永远返回空字典的 `http_health` 桩 + 0.3 秒超时，断言事件序列里没有 browser 事件、退出码是 `EXIT_FAILED`。

### 4.3 浏览器打不开不算失败

`open_default_browser()`（`launcher.py:441`）的返回值是 `(是否成功, 说明)`：

- Windows：`os.startfile(url)` 成功即成功；`OSError`（没有关联程序）返回 `(False, "没有关联的浏览器…")`；
- macOS：`open <url>`；
- Linux：依次尝试 `xdg-open` / `gio open` / `sensible-browser`，都找不到且有 `DISPLAY` 时才退回 `webbrowser.open`（没有图形环境就别试了）；
- 任何分支都不抛异常。

`cmd_start()` 拿到 `False` 时打印一条 `warn` 与手动打开的地址，然后**照常**报启动成功、退出码 `EXIT_OK`。这条语义由 `StartBrowserTest` 的三个用例钉住（浏览器失败仍 `EXIT_OK`、输出含「没能自动打开浏览器」与 URL、子进程 `extra_args` 必须含 `--no-browser`）。

### 4.4 窗口别一闪而过

`pause_before_close()`（`launcher.py:484`）：

```python
def pause_before_close() -> None:
    """出错或需要用户读完地址时，别让窗口一闪而过（run.bat 里也有同样的等待）。

    自动化脚本里设 AWFM_NO_PAUSE=1 跳过；非交互（没有 TTY）时也不会挂住。
    """
    if os.environ.get("AWFM_NO_PAUSE"):
        return
    try:
        if not (sys.stdin and sys.stdin.isatty()):
            return
    except (AttributeError, ValueError):
        return
    try:
        input("  按回车键关闭这个窗口……")
    except (EOFError, KeyboardInterrupt):
        say("")
```

两个判断都必要：`AWFM_NO_PAUSE=1` 让自动化测试与脚本调用不被挂住；`isatty()` 为假时（重定向、管道、服务方式调用）不该等输入。`cmd_quick()` 的**所有**出口（已在运行、启动失败、启动成功）都会调用它——最初只在两个失败分支调用，自查时发现「成功时窗口一闪而过、用户看不到地址」，于是改成无条件调用。

## 5. 测试结果

| 层 | 文件 | 数量 | 结果 |
|---|---|---|---|
| 单元 | `tests/unit/test_launcher.py` | 58 项（原 39，新增 19） | `OK (skipped=1)` |
| 单元 | `tests/unit/test_run_bat.py` | 17 项（整份重写，覆盖四个外壳） | `Ran 17 tests, OK` |
| 集成 | `tests/integration/test_launcher_lifecycle.py` | 18 项（原 14，新增 4） | 新增用例 `Ran 4 tests, OK` |

`test_launcher.py` 新增的五组：`BrowserLaunchTest`（4 项：Windows 走 `os.startfile`、`OSError` 变 `(False, …)`、Linux 无命令且无 `DISPLAY` 时失败、Linux 优先 `xdg-open`）、`PauseTest`（4 项：`AWFM_NO_PAUSE`、非 TTY、正常调用、`EOFError`）、`StartBrowserTest`（5 项：事件序列 `spawn → health → browser`、`--no-browser` 无 browser 事件、浏览器失败仍成功、子进程带 `--no-browser`、健康检查不通过不失败地开浏览器）、`QuickStartTest`（4 项：已在运行 / 已在运行且浏览器失败 / 启动失败 / 启动成功）、`DispatchTest`（2 项：`main([])` 走 quick、`--port` 归 start）。

`WrapperDefaultActionTest` 的做法是把 `scripts/launcher.py` 替换成一个只打印 `json.dumps(sys.argv[1:])` 的桩，然后把四个外壳一起复制到临时目录里执行：`run.bat` / `run.sh` 无参数必须打印 `[]`（quick 由 launcher 自己补）、`run-advanced.*` 无参数必须打印 `["menu"]`、两者带参数必须原样透传。这样测的是**外壳真的交给了 launcher 什么**，而不是「文件里有没有某行字」。

`test_run_bat.py` 的 17 项守的是静态纪律：两个 `.bat` 都是 CRLF、合法 UTF-8、引导段纯 ASCII、五个关键标记齐全、守卫在重跑之前、`chcp` 在首个中文之前、两个 `.sh` 无 CR 且有 shebang 与 `cd "$SCRIPT_DIR"`、`.gitattributes` 覆盖。

## 6. 问题与风险

| # | 问题 | 处理 |
|---|---|---|
| 1 | 普通启动成功后窗口立刻关闭，用户看不到地址与停止方法 | `cmd_quick()` 改成**总是** `pause_before_close()`，并补打印日志位置与停止命令 |
| 2 | 批处理括号块内读 `%ERRORLEVEL%` 拿到旧值 | `run-advanced.bat` 用 `goto` 分支，退出码在块外 `:awfm_take_code` 读取 |
| 3 | 两个入口若各自维护一套启动逻辑必然漂移 | 只允许「不带参数时的默认动作」不同，其余共用 `cmd_start()`；差异由 `WrapperDefaultActionTest` 与 `test_run_bat.py` 双向钉住 |
| 4 | 无图形环境时 `xdg-open` 不存在 | 依次尝试三个命令，都失败才返回 `(False, …)`；不抛异常、不影响启动 |
| 5 | `--open-browser` 与配置项 `open_browser` 在 v0.1.3 后不再生效 | 保留解析只为兼容旧命令行，`print_usage()` 明确标注「v0.1.2 的旧选项，现在默认就会打开，保留只为兼容」，`--no-browser` 是唯一关闭开关 |

## 7. 文档与交付物

- 代码：`scripts/launcher.py`（+169 行：`quick` 命令、`open_default_browser()`、`pause_before_close()`、`cmd_quick()`、用法与解析器调整）；`run.bat` / `run.sh`（只改注释与提示文案）；新增 `run-advanced.bat` / `run-advanced.sh`。
- `AGENTS.md` 顶层白名单加入两个新外壳，并把四个入口的分工写进那一行。
- `docs/USER_GUIDE.md`：步骤 3 整段改写（普通启动真实输出 + 四条行为）、新增「步骤 3.1 高级启动」、参数表更新；`docs/RELEASE.md` §1 增加「启动入口」行、§2 目录树与必需文件清单加入两个新外壳、§5 安装与运行按新入口重写。
- 测试：`tests/unit/test_launcher.py`、`tests/unit/test_run_bat.py`、`tests/integration/test_launcher_lifecycle.py`；索引 `tests/unit/_index.md:12`、`:37` 与 `tests/integration/_index.md:15` 同步。

## 8. 阶段结论

阶段 C 完成，允许进入阶段 D。判断依据：

1. 任务书 §5 的每一条都有对应实现（见 §3 的 13 行对照表），且「就绪后才开浏览器」「打不开不算失败」「不得重复弹标签页」三条都有单元测试直接钉住；
2. 两个入口的行为差异被限制在一处，并有真实执行外壳的集成测试证明 argv 正确；
3. 普通入口的每条退出路径都不会闪退（`pause_before_close()` 无条件调用），自动化下也不会被挂住（`AWFM_NO_PAUSE`）。

未覆盖的部分（如实记录）：**真实双击**的体验只在阶段 D 的 CU 里验证（自动化只能验证 argv 与事件顺序）；Linux 侧的 `xdg-open` 分支只有单元测试（桩），没有在真实桌面 Linux 上点过；`gio open` / `sensible-browser` 两个后备命令从未被真实调用过。
