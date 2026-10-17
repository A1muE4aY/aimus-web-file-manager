# PHASE-D：v0.1.3 最终交付报告

| 项目 | 内容 |
|---|---|
| 版本 | 0.1.3（app/__init__.py:7） |
| 报告日期 | 2026-10-17 |
| 依据 | dev_guide/0.1.3_.md（接力任务书 §0~§7） |
| 基线 | v0.1.2（提交 757c951，827 项自动化 + 8 项静态检查） |
| 结论 | 五项需求全部实现并通过自动化与真实桌面验收；四层回归 948 项全通过；静态检查 8/8；发行包重建并双工具复核 |
| 发行包 | dist/AWFM-0.1.3-windows-x64.zip（110 个文件，zip 700,053 字节） |
| SHA-256 | 7ef7ebae885b69892b46cfac61865961198e2b474372287c9735f34ed593312f |

## 1. v0.1.2 遗留问题清单与处理（任务书 §0 第一步）

v0.1.2 的未办事项集中在两份报告，逐条复核后**没有「已确认、影响正常使用」的缺陷**：

| 来源 | 条目 | 性质 | 本轮处理 |
|---|---|---|---|
| PHASE-07-RELEASE-v012.md §6.2 | 6 条：SSH 教程 7 项未实测、平台范围只 Windows x64、未做系统级断网验证、run.sh check 双系统同端口误判（环境重叠）、WSL 看不到 Windows PID（预期行为）、CU 驱动把按键转成大写 | 未验证 / 环境受限 | 原样保留并在本报告 §7 复述；v0.1.3 未扩大平台范围，未追加系统级断网验证 |
| PHASE-06-CU-ACCEPTANCE.md §6.2 | 5 条：均为「本机环境做不了」的补充验证 | 未验证 / 环境受限 | 同上 |

因此 v0.1.3 的第一优先级实际落在任务书 §1/§2/§3 的界面问题与 §4/§5 的新功能上。

v0.1.3 开发期间另有 **2 处自动化失败**（都是本轮新写代码引入的，已修）：

1. tests/security/test_edit_paths.py:105 期望 400，实测 404 session_not_found。根因：delete_entry() 在校验 path 之前就调了 _session()。修法：形状检查前置，并加注释「畸形请求不该因为『没连上』变成 404」（app/api/handlers.py:478）。

2. tests/e2e/test_browser_sidebar.py 断言 .col-perm 的 display 为 table-cell，实测 table-column。根因：选择器先匹配到 colgroup 里的 col.col-perm。修法：改成 #file-table tbody td.col-perm。

## 2. 五项需求的实现与验收对照

| 任务书 | 实现位置 | 自动化用例 | 真实 CU |
|---|---|---|---|
| §1 行内操作区独立容器、固定顺序、等宽不跳动 | .file-actions-box（frontend/assets/css/app.css:917）；ACTION_ORDER / actionCell（frontend/assets/js/files.js:500 / :515），七槽位循环 :584；断点 app.css:1105 / :1120 | tests/unit/test_frontend_layout.py 30 项中 12 项；tests/e2e/test_browser_layout.py 2 项；test_browser_v013.py 3 项 | 项 2、3 |
| §2 文件信息列独立布局（名称弹性、其余受控宽度、表头同列） | colgroup（frontend/index.html:150-158）；列宽与断点 app.css:887、:1110-1142；截断测量 in files.js（markTruncatedNames） | test_frontend_layout.py 中 colgroup/列宽 8 项；test_browser_layout.py 名称右边界断言 | 项 4、5 |
| §3 预览独立框、框内滚动、错误机制不变 | .preview-box（app.css:612，头部 :623/:633/:643，正文 :646）；frontend/assets/js/preview.js:70 | test_browser_v013.py 预览 2 项（长文本滚动、二进制走既有错误路径） | 项 6、7 |
| §4 新建文件/文件夹、多选与批量复制剪切删除压缩解压 | 后端 create_entry（app/services/fileops.py:218）用 SSH_FXF_CREAT 加 SSH_FXF_EXCL；copy_entries:416、move_entries:451、delete_entries:567、extract_entries:1051；前端 fileops.js 的 createEntry:288、copyEntries:359、paste:376、批量 :463/:532/:597；state.js 的 multiSelect:48、clipboard:57 | 单测 CreateTests/CopyTests/MoveTests/BatchTests 共 32 项；集成 18 项；test_frontend_layout.py 多选 10 项；e2e 多选/新建 2 项 | 项 8、9 |
| §5 普通/高级双入口，就绪后自动开浏览器 | run.bat / run.sh（quick）、run-advanced.bat / run-advanced.sh（menu）；scripts/launcher.py 的 cmd_quick:606、open_default_browser:441、pause_before_close:484、cmd_start:516 | test_launcher.py 58 项、test_run_bat.py 17 项、test_launcher_lifecycle.py 18 项 | 项 10~14 |

## 3. 自动化测试统计（四层 + 静态检查）

| 层 | v0.1.2 | v0.1.3 | 差异来源 |
|---|---|---|---|
| 单元 tests/unit | 588 | **680** | 新增 test_frontend_layout.py 30、test_fileops.py +34、test_launcher.py +19、test_run_bat.py 重写 17 |
| 集成 tests/integration | 125 | **147** | test_fileops_api.py +18、test_launcher_lifecycle.py +4 |
| 安全 tests/security | 82 | **82** | 未新增，全部沿用并通过 |
| 端到端 tests/e2e | 32 | **39** | 新增 test_browser_v013.py 7 项 |
| **合计** | 827 | **948** | 0 失败 / 0 错误 / 1 跳过（Windows 平台跳过），用时 **1127.87s** |

静态检查 python scripts/build.py：**8/8 通过**（Python 版本、语法、import 扫描 42 个源文件、前端无外网 URL 19 个文件、凭据纪律 59 个文件、错误模型回归、版本一致性 0.1.3、测试包结构）。

复跑记录：首轮 948 项中 2 项失败（见 §1），修复后第二轮 **948 项全绿**（.temp/regression_v013_run2.log）。

## 4. 真实桌面 CU 14 条（任务书 §6.2）

环境：Windows 11 家庭版 26300 / 2560x1440（缩放 125%）、Microsoft Edge、cua-driver 0.28.0；被测服务以**普通入口**起在 http://127.0.0.1:8760/；目标机 CentOS Stream 10（192.168.170.128，密钥认证、允许写、家目录 /home/aimu），素材在 /home/aimu/cu-v013/（8 项，含中文名、空格+括号名、19.9 KiB / 200 行长文本、1 MiB 二进制、tar.gz、超长英文名）与只读目录 /home/aimu/cu-v013-readonly（chmod 555）。证据目录 .temp/cu-v013/。

| # | 验收项 | 结论 | 证据与关键文字 |
|---|---|---|---|
| 1 | 版本显示正确 | 通过 | 01-ordinary-launch.png：右上状态条「本地服务正常 · AWFM 0.1.3」；02-console-output.png：「[ OK ] AWFM 已启动（版本 0.1.3）」 |
| 2 | 操作按钮顺序固定、文字居中、位置不跳 | 通过 | 03-crop-actions2.png（放大 2×）、03-crop-list.png：8 行七个按钮 left/width 完全一致，顺序为 编辑→复制→剪切→重命名→删除→压缩→解压；「操作」表头正好位于按钮块上方居中 |
| 3 | 不同文件类型操作区一致 | 通过 | 同两张图；UIA 明细：目录行 编辑/解压 置灰但占位不变，普通文件 解压 置灰，sample-pack.tar.gz 行七个全亮 |
| 4 | 信息列与表头对齐 | 通过 | 03-crop-list.png：UIA frame 实测 名称 x=426 w=928 / 大小 x=1353 w=145 / 类型 x=1497 w=133 / 修改时间 x=1784 w=223，全部 y=339 h=45；行 y 逐行 +46，列不重叠 |
| 5 | 长名截断且能查看完整名 | 通过 | 06-truncation.png、06-crop-trunc.png：180 字符探针文件以省略号截断、不侵入「大小」列；07-crop-menu.png：右键菜单「复制完整路径」带完整路径；复制后剪贴板长度 **220**（19 前缀 + 201 名字，Get-Clipboard 与驱动 clipboard_read 一致） |
| 6 | 文本预览独立框且框内滚动 | 通过 | 04-crop-preview.png：标题「预览 long-preview.txt」+ 元信息（路径/大小/修改时间）+ 正文框自带表头「UTF-8 · 19.9 KiB · 只读」与自己的滚动条，第 001~023 行换行缩进原样；关掉后再开 short.txt → 10-crop-preview-short.png（43 B，同一框结构） |
| 7 | 二进制提示明确 | 通过 | 05-crop-toast2.png：「该文件看起来是二进制文件，无法作为文本预览。」详情「/home/aimu/cu-v013/binary-1MiB.bin（前 262144 字节内含 NUL 字节）」 |
| 8 | 创建空文件，远端一致 | 通过 | 08-crop-list.png（新行 cu-probe-empty.txt 0 B / -rw-r--r-- / 13:31）、08-crop-toast.png（绿条「已创建空文件「cu-probe-empty.txt」。」）、状态文本同句；远端 stat 实测 **0 bytes 644 /home/aimu/cu-v013/cu-probe-empty.txt** |
| 9 | 无写权限时服务端拒绝创建 | 通过 | 09-crop-dialog.png：对话框保持打开并显示「创建失败：打开文件 /home/aimu/cu-v013-readonly/should-fail.txt：远端拒绝访问。（远端返回 PERMISSION_DENIED：Permission denied）」；列表仍 0 项；远端 ls -la 确认目录仍只有 . 与 .. |
| 10 | 普通脚本启动自动开浏览器 | 通过 | 01-ordinary-launch.png（Edge 自动新开标签并显示 AWFM 页面）+ 02-console-output.png（「浏览器：已用系统默认浏览器打开地址」） |
| 11 | 高级脚本启动也自动开浏览器 | 通过 | 13-crop-console.png：run-advanced.bat start → 「[ OK ] AWFM 已启动（版本 0.1.3）」…「浏览器：已用系统默认浏览器打开地址」，随即回到提示符（带参数不进菜单）；13-advanced-launch.png：新标签已打开；Edge 标题「和另外 4 个页面」→「和另外 5 个页面」 |
| 12 | 启动失败给出明确错误 | 通过 | 16-crop-busy.png：先用占用 8760 的假监听，再 run.bat → 「[失败] 启动失败：127.0.0.1:8760 已经被占用。」+「占用者不是 AWFM（没有对应的 PID 文件）。请用 --port 换一个端口…」+「[提示] 本次没有成功完成，退出码 1。」，不闪退、不空等 |
| 13 | 重复启动处理 | 通过 | 14-crop-dup.png：服务已在跑时 run.bat → 「[信息] AWFM 已经在运行，本次不会再启动第二个实例。」+ 地址 + 停止方法；未起第二个进程 |
| 14 | 停止后无残留、可再启动 | 通过 | 11-crop-stop.png（停止提示与确认）、12-crop-stop-done.png（「已强制终止（taskkill /F，含子进程）」「[ OK ] AWFM 已停止（强制终止）。」）；停止后 8760 无监听、Get-Process -Id 19748 为空；再次 run.bat → 新 PID 24412、data/awfm.pid 里 version 为 0.1.3、GET /api/health 200 且 version 0.1.3（17-restart.png） |

CU 期间还留了两张对照图：03-list-cu-v013.png（进入目录后的整屏）、14-duplicate-start.png（重复启动整屏）。

CU 驱动本身的限制（**只影响取证方式，不影响产品结论**）：后台注入的鼠标事件到不了 Chromium 页面（按钮必须用前台 SendInput）、press_key / hotkey 在 Chrome_WidgetWin_1 上必须前台、最大化窗口不允许 set_window_frame（改用「造超长文件名」触发截断），驱动偶尔把键入字母转成大写。

## 5. 启动脚本行为与兼容性

| 行为 | 普通 run.bat / run.sh | 高级 run-advanced.bat / run-advanced.sh |
|---|---|---|
| 不带参数 | scripts/launcher.py quick：查环境 → 起服务 → 等 /api/health → 开浏览器 → 打印地址/日志/停止方法 → 等回车关窗 | menu：交互菜单（启动/状态/停止/日志/自检） |
| 带参数 | 原样透传给 launcher（start/stop/status/logs/check/--port …） | 同左，两者行为一致 |
| 自动开浏览器 | 默认开；--no-browser 关闭（唯一开关，配置里 open_browser 与旧选项 --open-browser 自 v0.1.3 起不起作用） | start 同样默认开 |
| 就绪判断 | 轮询 /api/health（DEFAULT_START_TIMEOUT=20s），超时给控制台日志尾部与手动命令，不只看 PID | 同左 |
| 浏览器打不开 | 只打印地址并提示手动打开，退出码仍为 0 | 同左 |
| 重复启动 | 打印「已经在运行」+ 地址 + 停止方法，不启第二个实例 | start 同样拒绝重复实例 |
| 停止 | run.bat stop：先 taskkill /T（不带 /F），Windows 上层拒绝后**询问**是否强制终止；非交互终端用 --force --yes | 同左 |

实测证据：02-console-output.png（普通启动全流程输出）、13-crop-console.png（高级 start）、11-crop-stop.png 与 12-crop-stop-done.png（停止确认）、14-crop-dup.png（重复启动）、16-crop-busy.png（端口占用失败）。

兼容性：四份外壳只做「切脚本目录 → 找 Python → 转交 scripts/launcher.py」；run.bat / run-advanced.bat 开头的纯 ASCII UTF-8 引导段保证 GBK(936) 控制台下不乱码（test_run_bat.py 10 项静态纪律 + 1 项 chcp 936 集成用例）。run.sh / run-advanced.sh 是 POSIX #!/bin/sh，**本机未实测**（§7）。

## 6. 创建文件的权限与安全验证

- **排他创建**：文件用 client.open(target, SSH_FXF_WRITE 加 SSH_FXF_CREAT 加 SSH_FXF_EXCL, 0644)，目录用 client.mkdir(target, 0755)；**不做「先 stat 再创建」**——两次系统调用之间被抢占会退化成静默覆盖。同名由远端以 SSH_FX_FAILURE 拒绝，再 lstat 翻译成「同名条目已经存在。」（extra 里带 path / exists / type）。

- **服务端重新校验**：require_write_permission(session, 新建文件) + validate_remote_name（拒绝空、点、双点、含斜杠或 NUL、超长）+ _directory_target 的 realpath/stat 必须是目录；前端禁用只是提示，不是安全边界。

- **实证**：只读目录（chmod 555）里创建 → PERMISSION_DENIED，文件夹内仍为空（CU 项 9）；同名重复创建 → 「同名条目已经存在。」（单测 test_create_refuses_an_existing_name）；并发抢占用 mock.patch.object(client, open, racing_open) 模拟，判为同名而不是覆盖（test_creation_uses_an_exclusive_open）。

- **刷新失败与创建成功分开报**：创建成功但列表没刷出来时给出可重试提示；CU 里 10 项计数与远端 stat 一致。

- **批量上限**：MAX_COPY_ENTRIES=10000、MAX_COPY_BYTES=512 MiB、MAX_TREE_DEPTH；符号链接复制时跳过并记 code symlink_skipped（不跟随、不造假文件）；移动逐项 rename，目标已存在一律拒绝（SFTP v3 RENAME 不覆盖，先复制再删会把原子改名退化成两步）。

- 名称实测覆盖中文、空格、括号、方括号与超长名（CU 素材 4 个）；空名、点、双点、含分隔符、300 字符名均被拒（单测 11 项 + 集成 8 项）。

## 7. 未验证项与限制（如实记录）

- **Linux / macOS 未实测**：run.sh / run-advanced.sh 只有静态纪律与（Windows 下的）桩 launcher 转发用例；xdg-open / gio / open 分支由单测 mock 覆盖，没有真机验证。平台范围仍是 Windows x64（沿用 v0.1.2 的结论）。

- **浏览器自动打开在无图形环境下未实测**（无 DISPLAY 的 Linux、Server Core）；代码路径为「找不到打开命令 → 只提示地址、退出码 0」，由单测覆盖。

- **Windows 停止需要一次确认**：后台服务以 DETACHED_PROCESS 启动、没有窗口，taskkill /T（不带 /F）无法送达 WM_CLOSE，于是 stop 先花 10 秒等待、再提示「是否强制终止」。这是 v0.1.2 起就存在的平台行为，v0.1.3 未改；非交互场景用 run.bat stop --force --yes（--yes 时同样会等满 10 秒）。

- **未做系统级断网验证**（沿用 v0.1.2）：只有静态零外链、零第三方依赖与端到端「对外请求为空」的间接证据。

- **SSH 教程 7 项未在本机实测**（sudo / SELinux / firewalld / macOS 等），仍标注在 docs/SSH_SETUP_GUIDE.md 附录 B。

- **批量操作没有逐文件进度条**：以整体遮罩呈现；中途失败保留已完成部分，并在错误里报 done / failed。

- **剪贴板不持久化**：复制/剪切只存在页面内存，刷新或切连接即丢失。

- **CU 证据目录 .temp/cu-v013/ 属会话中转**，按项目纪律不进仓库、不进发行包；本报告用文件名引用它们。

## 8. 发行包位置与 SHA-256

| 项 | 值 |
|---|---|
| 便携包 | dist/AWFM-0.1.3-windows-x64.zip（v0.1.0 / v0.1.1 / v0.1.2 的 zip 保留未覆盖；v0.1.3 的 zip 在「发布后界面微调」两轮之后重新构建，本节数字来自**产出这份 zip 的最终构建**，2026-10-17 15:18） |
| 解压后目录 | dist/AWFM-0.1.3-windows-x64/（111 个文件 / 1,740,808 字节，含 MANIFEST.json；清单 file_count=110） |
| zip 大小 | 719,611 字节（702.7 KB），成员 111 个，成员名统一带 AWFM-0.1.3-windows-x64/ 前缀 |
| **SHA-256** | ca235f4922b7f5afee3534d71962971b05cd60bb68d1eab2b4cd1ae031730641 |
| 双工具复核 | Get-FileHash -Algorithm SHA256 → CA235F49…30641；certutil -hashfile … SHA256 → ca235f49…730641，一致 |
| 校验清单 | dist/SHA256SUMS.txt（不在包内）：zip 哈希 + MANIFEST.json 哈希（73335f14ad03da63551a61e654f81bcc85e1964ef0da210281930c5d53463ee6） |

**独立目录验收**（路径含空格：.temp/pkg-test/AWFM 0.1.3 四次验收/，用 `Expand-Archive` 解压的就是上表这份 zip）：

- run.bat check → 退出码 0（8 项自检通过：Python / 依赖 / 端口空闲 / 前端资源 / 日志目录可写 / 配置 / 主机密钥策略 / 自检 --check）
- run.bat start --port 8794 --no-browser → 退出码 0，版本 0.1.3，PID 9092，启动时间 2026-10-17T15:19:27+08:00
- GET / → 200，9371 字节
- GET /api/health → 200，status ok、version 0.1.3、connections 0；响应头 Server: AWFM/0.1.3
- run.bat status → 退出码 0，显示 PID 9092 / 端口 8794 / 启动时间 / 版本 0.1.3
- run.bat stop --force --yes → 退出码 0（`已强制终止（taskkill /F，含子进程）`），端口 8794 监听数归 0

包内 VERSION：AWFM 0.1.3 / 构建时间 2026-10-17T15:18:44 / 目标平台 windows-x64 / 构建主机 Python 3.12.10；便携说明已改为「双击 run.bat 即普通启动、就绪后自动开浏览器；菜单用 run-advanced.bat」。

**与中间构建的差异**：本交付里 zips 先后重建过四次，前三次的目录树分别含 110、111、111 个文件。那两次多出来的 1 个文件是留在 `dist/AWFM-0.1.3-windows-x64/` 里运行的端到端遗留进程写下的 `logs/awfm-console.log`。它同时也是重打包失败的原因：只要还有进程的当前目录在那个暂存目录里，`shutil.rmtree` 就报 `PermissionError: [WinError 32] 另一个程序正在使用此文件`（本轮先后两次撞上，第二次的占用者是遗留的 `cmd.exe → run.bat` 与 `app/main.py`）。最终构建前先把遗留的 `run.bat` / `app/main.py` 进程清掉，暂存目录里不再有 `logs/`，文件数回到 110（+ `MANIFEST.json` = 111）。

**自引用说明**：`docs/` 在包里，而本节要记录包自身的字节数与哈希，两者无法与自身完全闭合——上表记录的是产出这份 zip 的那次构建，如果之后又改过 `docs/`，以包外的 `dist/SHA256SUMS.txt` 为准。

## 9. Git 记录

| 提交 | 内容 | 归类 |
|---|---|---|
| 50ba713 | 阶段 A：后端新建/复制/移动与批量能力（9 个文件，+1602 −58） | 接口能力 |
| e78dd44 | 阶段 B：操作区七槽位、列布局、预览框、新建与多选（12 个文件，+2043 −178） | 界面与交互 |
| ec3df14 | 阶段 C：启动脚本拆普通/高级 + 自动开浏览器（9 个文件，+761 −55） | 启动脚本 |
| 48951f3 | 阶段 D：版本升 0.1.3、文档同步、阶段报告 A~D、打包白名单、发行包与最终报告（12 个文件，+764 −57） | 最终交付 |
| 本行所在提交 | 收尾：把阶段 D 的提交哈希回写进 CHANGELOG 与本报告 §9 | 收尾 |
| 发布后修正提交 | 表格表头对齐、列宽改 px、宽屏加宽档、断点重排、单测断言，以及 CHANGELOG / RELEASE / 本报告的同步（版本号仍 0.1.3，不升 0.1.4） | 交付后修正（见 §10） |

**为什么没有把「界面优化」和「新建/多选」拆成两个提交**：两者落在同一批文件（frontend/index.html、app.css、files.js、app.js、fileops.js、state.js、api.js）的相邻 hunk 里，拆分需要 hunk 级 staging 且无法在本机复跑中间态，因此合并为一个「界面与交互」提交并在本表如实标注，符合任务书 §7「拆不开就合并并说明」的要求。

阶段报告：docs/reports/PHASE-A-BACKEND-v013.md、PHASE-B-UI-v013.md、PHASE-C-LAUNCHER-v013.md、本报告（PHASE-D-RELEASE-v013.md），均已在 docs/reports/_index.md 登记。

仓库至今**没有任何 git 标签**（v0.1.2 的结论延续），v0.1.3 同样未打标签、未对外发布。

## 10. 发布后界面微调：表格对齐与信息列宽度（v0.1.3，不升版本号）

交付之后用户报告：文件列表「对不准、非居中」，并希望信息列（大小 / 类型 / 权限 / 修改时间）多给一些宽度。按用户要求**版本号保持 0.1.3**，不引入 0.1.4。（本节记的是第一轮；第二轮的三处修正见 §11，权限列宽度在那里又收窄了一档，两节按时间顺序读。）

### 10.1 两条根因（都是实测出来的，不是猜的）

1. **表头被统一左对齐。** `.file-table thead th { text-align: left }`（`frontend/assets/css/app.css:413`）对 `th` 的声明压过 `.col-size { text-align: right }`，于是「大小」表头靠左、数值贴右边界——同一列里表头和数字不在同一条边线上，看上去就是没对齐。实测改动前 `th.col-size` 的计算样式是 `left`、`td.col-size` 是 `right`。
2. **列宽被按比例放大。** 通用规则里 `.col-name { width: 44% }` 与 `col-size: 96px` 这类 px 列宽混在一起，而文件表是 `table-layout: fixed`（`frontend/assets/css/app.css:899`）。固定布局下百分比与 px 混用会把 px 当**权重**按比例分配：表宽 1498 时写 96px 实际渲染 102.2px（×1.066），表宽 1996 时 ×1.418。同一列的宽度于是随窗口漂移，表头与数值、按钮与「操作」表头的相对位置一起漂。

### 10.2 改动（`frontend/assets/css/app.css` 与一份单测）

- 百分比只留给**没有 colgroup** 的搜索结果表：`.search-table .col-name/.col-size/...`（`app.css:454` 起），并在代码里写明「不要在这里给文件列表列宽」。
- 文件列表的列宽统一留在 `#file-table` 的 col 规则里，名称列改 `width: auto` 吃掉剩余宽度（`app.css:906`）；基准列宽 大小 96 / 类型 88 / 权限 104 / 修改时间 148 / 操作 352 / 复选 36。
- 新增 `#file-table thead th.col-size { text-align: right; }`（`app.css:923`），表头跟着数值走。
- 新增 `@media (min-width: 1600px)` 加宽档（`app.css:1171`）：大小 120 / 类型 108 / 权限 136 / 修改时间 190 / 操作 380，按钮槽位 `repeat(7, 48px)`；窄窗口的收列节奏不受影响。
- 断点重排：权限列 1240、类型列 1120、修改时间 1000、大小 740、七槽折两行 880（`app.css:1128` / `:1134` / `:1144` / `:1160` / `:1154`）。原因：信息列加宽后 1121~1239 CSS 视口（表格约 760~880px）同时放「名称 + 四个信息列 + 七个按钮」已放不下，实测名称列被压到 0 并出现横向滚动；820~879 七槽一行虽塞得下，名称列却只剩 40px 左右，不如折成 4+3。
- `tests/unit/test_frontend_layout.py` 新增两条断言：`#file-table thead th.col-size` 必须右对齐；≥1600px 加宽档必须存在且逐列给出 120/108/136/190。断点断言同步到新门槛，槽位断言同步到 44 / 40 / 38 / 52px 四档。

### 10.3 实测（无头 Edge 打开真实运行实例，`/api/health` 为 `{"ok":true,"data":{"status":"ok","version":"0.1.3","connections":2}}`）

| CSS 视口 | 表格宽 | 名称列 | `th.col-size`（align / 右边界 / 宽） | `td.col-size` | 「操作」表头中心 | 按钮块中心 | 可见列 |
|---|---|---|---|---|---|---|---|
| 2048 | 1679 | 745 | right / 1202 / 120 | right / 1202 / 120 | 1826 | 1826 | 名称 大小 类型 权限 修改时间 操作 |
| 1600 | 1231 | 297 | right / 754 / 120 | right / 754 / 120 | 1378 | 1378 | 同上 |
| 1500 | 1131 | 343 | right / 776 / 96 | right / 776 / 96 | 1292 | 1292 | 同上 |
| 1200 | 831 | 175 | right / 608 / 96 | right / 608 / 96 | 1006 | 1006 | 名称 大小 类型 修改时间 操作（权限列已按 1240 断点收起） |

- 四档都满足：表头与数值同一条右边界；按钮块中心与「操作」表头中心逐像素相等；七个按钮无一被 `text-overflow` 截断（`scrollWidth <= clientWidth`）；表格无横向滚动（`scrollWidth == clientWidth`）。
- 另一张复刻真实标记的探针页（视口 − 360px 模拟侧栏）扫了 16 档宽度（2048 → 660），对齐与居中结论一致；660 档的 26px 溢出是探针模拟宽度造成的，真实页面在 740 断点以上无横向滚动。
- 证据截图：`.temp/cu-layout/live-2048.png`（2048×1100 的真实实例渲染）。

### 10.4 回归范围与如实说明

- `python -m unittest discover -s tests/unit -t .` → **682 项 OK**（1 项 Windows 平台跳过）。
- `python -m unittest tests.e2e.test_browser_layout tests.e2e.test_browser_sidebar tests.e2e.test_browser_v013` → **19 项 OK**（85.8s）。
- `python scripts/build.py` 静态检查 **8 项通过**；`python scripts/package.py` 退出码 0，重建后的包已在含空格的独立目录重跑 §8 的六步验收。
- **未重跑的部分**：集成层、安全层与其余端到端模块本轮没有重跑（改动只落在 CSS 与一份布局单测上，接口、服务端与启动脚本没有动）。§3 的 948 项统计仍是阶段 D 那次全量回归的结果，本节不重述。
- **静态资源缓存**：静态响应已经带 `Cache-Control: no-store`（`app/api/responses.py:37` 由 `security_headers()` 统一发出，实测 `/assets/css/app.css` 响应头确实有它），所以升级后刷新一次页面就能拿到新样式，不涉及缓存头改动。实测该响应体 45,072 字节、与工作区里的 `frontend/assets/css/app.css` 一致，说明服务端发的就是新文件。
- **未做**：把静态资源改成带版本查询串（`?v=…`）留给下一个版本评估；本轮不改 URL 形式。

## 11. 发布后界面微调（第二轮）：按钮居中、类型列间距、权限改八进制（v0.1.3，不升版本号）

§10 的对齐修正交付后，用户又报了三处：操作列的按钮文字在按钮里不居中、大小与类型贴得太近、权限要改成数字（字符形式光标移上去再看）。仍按用户要求保持 0.1.3。

### 11.1 三处根因（实测，不是猜的）

1. **按钮文字左偏 11.5px。** `.btn` 是 `inline-flex`（`frontend/assets/css/app.css:483`），按钮里只有一段文字，于是它成了**匿名 flex 项**；`text-align: center` 管不动 flex 项的位置，项默认从 `flex-start` 排起。实测 48px 槽位（内容区 46px）里 23px 的两个字，文字包围盒中心比内容区中心偏左 11.5px = (46−23)/2；「重命名」34.5px 偏左 5.8px。判定依据是 `getComputedStyle(btn).justifyContent === "normal"`。
2. **大小与类型贴在一起。** 大小列右对齐、类型列左对齐，两列各自的内边距（10px + 10px）全压在同一条列边界上，视觉上只剩 20px；而类型列本身有大片空余（「文件」两字 23px，列宽 88/108px）。
3. **权限列是十位字符。** `drwxr-xr-x` 占满 104/136px 的列宽，而扫列表时真正要判断的只有「读得、写得、别人能不能进」三件事。

### 11.2 改动

| 位置 | 改法 |
|---|---|
| `frontend/assets/css/app.css` 的 `#file-table .file-actions-box .btn` | 加 `justify-content: center`，并在注释里写明「匿名 flex 项，text-align 管不动」这条根因 |
| `frontend/assets/css/app.css` 新增 `#file-table th.col-type, #file-table td.col-type` | `padding-left: 20px`（表头与数值一起挪，仍同一左边界） |
| `frontend/assets/css/app.css` 的 `#file-table col.col-perm` | 基准 104 → 92，宽屏档（≥1600px）136 → 104 |
| `frontend/assets/js/util.js` | 新增并导出 `formatPermissionOctal(entry)`：`(perms & 0o7777).toString(8)`，不足三位补零，特殊位有值时才显示第四位（与 `stat -c %a` 一致） |
| `frontend/assets/js/files.js` | 权限单元格改成 `formatPermissionOctal(entry)`；`permissionHint(cell, entry)` 用 `showTooltip`/`hideTooltip` 挂字符形式，并写入 `aria-label` |
| `tests/unit/test_frontend_layout.py` | 新增三条断言（按钮 `justify-content: center`、类型列 20px 左内边距、权限列八进制 + 悬浮字符形式），宽屏档权限列宽度断言 136 → 104 |

为什么提示用自绘浮层而不是原生 `title`：原生 title 要悬停约一秒才出、样式与界面不一致；自绘提示与名称列的「完整名称」提示共用 `overlay.js` 同一套浮层，进出即显。

### 11.3 实测（无头 Edge 打开真实实例 `http://127.0.0.1:8760/`，测的是真实 DOM 的包围盒与元素宽度）

| CSS 视口 | 表格宽 | 名称列 | 七枚按钮文字偏移 | 大小 → 类型 间距 | 权限（值 / 宽） | 被截断按钮 | 横向滚动 |
|---|---|---|---|---|---|---|---|
| 2048 | 1679 | 777 | 全 0 | 30px | 700 / 104 | 0 | 无 |
| 1600 | 1231 | 329 | 全 0 | 30px | 700 / 104 | 0 | 无 |
| 1500 | 1131 | 355 | 全 0 | 30px | 700 / 92 | 0 | 无 |
| 1400 | 1031 | 255 | 全 0 | 30px | 700 / 92 | 0 | 无 |
| 1240 | 871 | 215 | 全 0 | 30px | 权限列收起 | 0 | 无 |
| 1120 | 751 | 197 | 全 0 | 类型列收起 | — | 0 | 无 |
| 992 | 623 | 217 | 全 0 | — | — | 0 | 无 |
| 880 | 511 | 175 | 全 0 | — | — | 0 | 无 |

- 改前对照：七枚按钮偏移 −11.5 / −11.5 / −11.5 / −5.8 / −11.5 / −11.5 / −11.5，大小 → 类型 20px。
- 权限数字与远端一致：目录 700 / 755、只读目录 555、文件 600 / 644（与 `ls -l` 对照）；悬浮提示实测返回 `drwx------`。
- 名称列因权限列收窄而变宽：2048 视口 745 → 777，1600 视口 297 → 329。
- 证据截图：`.temp/cu-layout/after-v2.png`（2048 视口）、`.temp/cu-layout/after-crop-info.png`（权限 + 按钮）、`.temp/cu-layout/after-crop-gap.png`（大小 → 类型间距）。

### 11.4 回归范围与如实说明

- `python -m unittest discover -s tests/unit -t .` → **685 项 OK**（1 项 Windows 平台跳过；本轮新增 3 条）。
- `python -m unittest tests.e2e.test_browser_layout tests.e2e.test_browser_sidebar tests.e2e.test_browser_v013` → **19 项 OK**（80.1s）。
- 集成层、安全层与其余端到端模块本轮没有重跑（改动只落在 CSS、两个前端模块与一份布局单测上，接口、服务端与启动脚本没有动）。
- 静态资源仍由 `app/api/responses.py:37` 的 `Cache-Control: no-store` 兜住，升级后刷新一次即生效，不涉及缓存头改动。


