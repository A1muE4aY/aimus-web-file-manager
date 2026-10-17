# 阶段报告索引

规划文档 §9 要求每个阶段产出一份开发报告，最终汇总为 `FINAL_REPORT.md`。
报告模板见规划文档 §9.1（八节结构：报告信息 / 阶段目标 / 实际完成情况 / 技术实现 /
测试结果 / 问题与风险 / 文档与交付物 / 阶段结论）。

| 文件 | 阶段 | 日期 | 结论 |
|---|---|---|---|
| `PHASE-01-ENVIRONMENT.md` | 阶段 01 需求分析与环境调查 | 2026-10-15 | 环境满足技术路线；四问已确认；目标虚拟机需开机 |
| `PHASE-02-SPIKE.md` | 阶段 02 前置 SPIKE：连接层路线验证 | 2026-10-15 | 原生 SFTP v3 协议全项实测通过；D-004 作废，新增 D-011 |
| `PHASE-02-PROTOTYPE.md` | 阶段 02 最小原型 | 2026-10-15 | 见报告 |
| `PHASE-03-CORE.md` | 阶段 03 核心功能实现 | 2026-10-15 | 见报告 |
| `PHASE-04-SECURITY-TRANSFER.md` | 阶段 04 安全控制与文件传输 | 2026-10-15 | §10 七条要求逐条有实现与代码位置；允许进入阶段 05 |
| `PHASE-05-OFFLINE-DEPLOY.md` | 阶段 05 离线部署与兼容性验证 | 2026-10-15 | 端到端 3 条全绿；发现并修掉 6 处真实缺陷；允许进入阶段 06 |
| `PHASE-06-RELEASE.md` | 阶段 06 文档验收与正式发布 | 2026-10-15 | §11 发行验收 8 项通过（第 3、6 项降级表述） |
| `FINAL_REPORT.md` | 最终总结（由上述报告汇总） | 2026-10-15 | 四层 363 项全绿；T-001~T-014 全部通过；建议发布 v0.1.0 |
| `PHASE-03-SEARCH.md` | 阶段 03 添加远端文件检索（v0.1.1） | 2026-10-16 | 后端 36 项单测 + 15 项集成 + 18 项安全 + 4 项端到端全绿；四层合计 455 项 0 失败 0 跳过；允许进入阶段四 |
| `PHASE-04-EDIT.md` | 阶段 04 添加远端文本文件编辑和文件操作（v0.1.1） | 2026-10-16 | 单元 103 项 + 集成 61 项 + 安全 12 项 + 端到端 5 项全绿；四层合计 636 项 0 失败 0 跳过；允许进入阶段五 |
| `PHASE-05-DISCOVERY.md` | 阶段 05 自动发现在线虚拟机（v0.1.1） | 2026-10-16 | 单元 49 项 + 集成 10 项 + 安全 11 项 + 端到端 4 项全绿；四层合计 717 项 0 失败 0 跳过；三个场景只有模拟覆盖已标记未验证；允许进入阶段六 |
| `PHASE-06-CU-ACCEPTANCE.md` | 阶段 06 真实桌面 CU 验收（v0.1.1） | 2026-10-16 | 任务书 §七九项全部执行；①②③④⑤⑥⑦⑧ 通过、⑨为记录性条目；CU 期间发现 3 处前端缺陷与 1 处服务端缺陷并全部修复；未验证项与人工介入点已登记 |
| `PHASE-06-REGRESSION.md` | 阶段 06 回归、CU 验收与交付（v0.1.1） | 2026-10-16 | 四层合计 719 项 0 失败 0 跳过（`python scripts/test.py`）；修复检索剪枝的顺序缺陷并加强用例；便携包 `dist/AWFM-0.1.1-windows-x64.zip` 与校验和已重建并独立复核 |
| `PHASE-02-LAYOUT-v012.md` | 阶段 02 文件列表布局与右键菜单（v0.1.2） | 2026-10-17 | 七项验收要求（2.1~2.7）逐条落地并各有 e2e 断言；新增 8 项布局 e2e 全绿，四层合计 752 项 0 失败 0 跳过；真实桌面 CU 前后证据 24 张；修复 2 处前端缺陷（复制无反馈、菜单未随重绘关闭）；允许进入阶段三 |
| `PHASE-03-LAUNCHER-v012.md` | 阶段 03 统一启动脚本 run.bat / run.sh（v0.1.2） | 2026-10-17 | 任务书 §3.3~§3.7 全部条款落地：`scripts/launcher.py` 八命令与交互菜单、两个外壳、退出码语义 0/1/2/3、只认自己 PID 的停止阶梯、默认端口 32579；四层合计 798 项 0 失败 0 错误（跳过 1）；Windows 真实验收 34 项判定全过、Linux（WSL2 Ubuntu 24.04）12 用例全过；验收暴露并修复 3 个真实缺陷（D-A/D-B/D-C）；允许进入阶段四 |
| `PHASE-04-SSH-GUIDE-v012.md` | 阶段 04 SSH 配置教程（v0.1.2） | 2026-10-17 | 任务书 §4.1~§4.3 全部条款落地：新增 `docs/SSH_SETUP_GUIDE.md`（1627 行，A~L + 两个附录），并在 `docs/USER_GUIDE.md` 增加入口；关键步骤在 Windows 11 客户端 + CentOS Stream 10 服务端真实核验（J 节 13 类错误中 12 类有复现输出原文）；7 项无法在本机执行的内容逐处标注【未验证】并汇总于附录 B（决策 D-021）；新增 13 项一致性单测钉住教程与 `ssh_launcher`/默认配置的一致性；允许进入阶段五 |
| `PHASE-01-LEGACY-v012.md` | 阶段 01 遗留问题复核与基线检查（v0.1.2） | 2026-10-17 | 六项遗留全部复核（①④⑤检测⑥通过、②部分、③确认缺陷 D1、⑤确认缺陷 D2）；D1 两层与 D2 已修并新增 25 项回归；四层合计 744 项 0 失败 0 跳过；真实桌面 CU 复验通过；允许进入阶段二 |
| `PHASE-05-REGRESSION-v012.md` | 阶段 05 回归测试与安全检查（v0.1.2） | 2026-10-17 | 任务书 §5.1~§5.4 逐条对照：§5.1~§5.3 的 26 条可验证要求先逐条映射到既有自动化（报告 §5.6），再补 6 项启动脚本缺口用例（`tests/integration/test_launcher_lifecycle.py` 7 → 13 项）；四层合计 817 项 0 失败 0 错误（跳过 1，Windows 平台跳过、WSL 上真跑）；静态检查 8 项全通过；发行包解压到独立目录后独立运行（`check` / `start` / `GET /` 返回 200 / `status` / `stop`）；WSL2 Ubuntu 24.04 上 `bash -n` / `sh -n` 与外壳实跑通过；未改动 `app/` / `frontend/` / `scripts/`，未发现新的产品缺陷；允许进入阶段六 |
| `PHASE-06-CU-ACCEPTANCE-v012.md` | 阶段 06 真实桌面 CU 验收（v0.1.2） | 2026-10-17 | 任务书 §6 的 12 条验收全部执行并取证（Edge InPrivate 真机操作 + 真实 cmd / PowerShell / WSL2 终端，证据 01~54 号截图与裁图）；CU 期间发现并修复 1 个用户可见缺陷（`run.bat` 在 GBK 控制台下的两行假错误，改为纯 ASCII 引导段 + `goto` 守卫）并补 9 项单测 + 1 项集成用例；四层自动化全绿、静态检查 8 项通过；遗留限制项均有环境解释；允许进入阶段七 |
| `PHASE-A-BACKEND-v013.md` | 阶段 A 后端能力与接口（v0.1.3） | 2026-10-17 | 新增 `/create` `/copy` `/move` 三个端点（`app/api/handlers.py:409`/`:432`/`:452`），`delete`/`compress`/`extract` 兼容批量 `paths` 与 `compress.into`；新建用 `SSH_FXF_CREAT\|EXCL` + `MKDIR` 排他创建、不做「先查再建」（`app/services/fileops.py:218`）；复制带 10000 条目 / 512 MiB / 深度 64 上限、符号链接跳过并报告；移动逐项 `rename`、目标已存在一律拒绝；单元 `tests/unit/test_fileops.py` **95 项**、集成 `tests/integration/test_fileops_api.py` **48 项**全部通过（集成在真实 SFTP 测试床上用真实字节核对）；允许进入阶段 B |
| `PHASE-B-UI-v013.md` | 阶段 B 界面布局、预览框与新建/多选（v0.1.3） | 2026-10-17 | 行内操作区独立容器 `.file-actions-box` 七槽位固定顺序（`frontend/assets/js/files.js:500` `ACTION_ORDER`、`frontend/assets/css/app.css:917`/`:1105`）、`<colgroup>` 列定义（`frontend/index.html:150`）、`.preview-box` 预览独立框（`frontend/assets/js/preview.js:70`、`app.css:612`）、新建/复制剪切/多选三组交互；新增 `tests/unit/test_frontend_layout.py` **30 项**静态断言、`tests/e2e/test_browser_v013.py` **7 项**、`tests/e2e/test_browser_layout.py` 断言按新结构重写；允许进入阶段 C |
| `PHASE-C-LAUNCHER-v013.md` | 阶段 C 普通与高级启动脚本（v0.1.3） | 2026-10-17 | `run.bat`/`run.sh` 不带参数即普通启动（`scripts/launcher.py:606` `cmd_quick()`），新增 `run-advanced.bat`/`run-advanced.sh` 无参数进菜单；`open_default_browser()`（`:441`）用系统默认浏览器、打不开只提示地址且不算启动失败，`pause_before_close()`（`:484`）防闪退，「就绪后才开浏览器」由 `http_health()` 轮询（`:180`）保证、子进程强制 `--no-browser` 防重复弹页；单元 `test_launcher.py` **58 项**、`test_run_bat.py` **17 项**、集成 `test_launcher_lifecycle.py` **18 项**全部通过；允许进入阶段 D |
| `PHASE-D-RELEASE-v013.md` | 阶段 D 回归、真实 CU 验收与交付（v0.1.3，最终报告） | 2026-10-17 | v0.1.2 两份报告共 11 条遗留逐条复核，**无「已确认、影响正常使用」的缺陷**（全部为环境受限/未验证），并记录本轮修掉的 2 处新引入失败（`tests/security/test_edit_paths.py:105` 期望 400 实测 404，改为形状检查前置 `app/api/handlers.py:478`；`tests/e2e/test_browser_sidebar.py` 选择器命中 `colgroup` 改为 `#file-table tbody td.col-perm`）；五项需求→实现位置→用例→CU 逐条对照；四层 **948** 项 0 失败 0 错误（1 跳过，用时 1127.87s）、静态检查 8/8；真实桌面 CU **14 条**全部执行并取证（`.temp/cu-v013/`，含长名截断、只读目录拒绝、端口占用、重复启动、停止后重启）；发行包 `dist/AWFM-0.1.3-windows-x64.zip`（110 个文件 / 700,053 字节），SHA-256 `7ef7ebae…312f` 由 `Get-FileHash` 与 `certutil` 双工具复核，含空格独立目录跑通 check/start/health/status/stop；未验证项与平台行为（Windows 停止需一次确认）如实登记；**允许作为 v0.1.3 交付** |
| `PHASE-07-RELEASE-v012.md` | 阶段 07 版本与交付（v0.1.2，最终报告） | 2026-10-17 | 版本号统一升到 0.1.2（`app/__init__.py:7`；静态检查第 7 项同时钉住 README 与 CHANGELOG）；六处用户文档版本与日期对齐，历史报告与旧包未被覆盖；重建便携包 `dist/AWFM-0.1.2-windows-x64.zip`（104 个文件 / 616.9 KB，不再含 `start.cmd`/`stop.cmd`、不含 `tests/`），zip 的 SHA-256 由 `Get-FileHash` 与 `certutil` 两条独立命令复核一致；解压到**含空格路径**的独立目录后 `check` / `start`（版本 0.1.2）/ `GET /` 200 / `/api/health` 200 `{"version":"0.1.2"}` / `status` / `stop` 全程跑通、端口与 PID 无残留；四层自动化 **827** 项 0 失败 0 错误（1 跳过）、静态检查 8 项通过；含任务书 §7.4 十项对照、七阶段提交记录与「本次不打 git 标签」的结论；**允许作为 v0.1.2 交付** |

> 上表 `PHASE-01`~`FINAL_REPORT` 为 v0.1.0 的报告（2026-10-15，均按 §9.1 八节模板撰写）；
> v0.1.1 的报告：`PHASE-03-SEARCH.md`、`PHASE-04-EDIT.md`、`PHASE-05-DISCOVERY.md`、
> `PHASE-06-CU-ACCEPTANCE.md`（九项真实桌面 CU 验收）与 `PHASE-06-REGRESSION.md`（回归与交付）；
> `PHASE-03-SEARCH.md` 与 `PHASE-04-EDIT.md` 属 v0.1.1 开发过程，文件名按 v0.1.1 自己的阶段编号（阶段三 = 远端文件检索，阶段四 = 远端文本编辑与文件操作）；
> v0.1.1 的阶段四报告叫 `PHASE-04-EDIT.md`，与 v0.1.0 的 `PHASE-04-SECURITY-TRANSFER.md` 不是同一份。
> v0.1.2 的报告统一加 `-v012` 后缀（如 `PHASE-01-LEGACY-v012.md` = 阶段一「遗留问题复核与基线检查」），以便与 v0.1.0 / v0.1.1 的同阶段报告区分。
> v0.1.3 的报告统一加 `-v013` 后缀，阶段编号按接力任务书 `dev_guide/0.1.3_.md` 的 A~D（A 后端、B 界面、C 启动脚本、D 回归与交付），与 v0.1.2 的数字阶段号不是同一套编号。
> 阶段 02~06 的报告与 `FINAL_REPORT.md` 均按 §9.1 八节模板撰写；
> 报告只写可核实的内容（能指到源码就写 `路径:行号`，能指到实测就写命令与输出）。
