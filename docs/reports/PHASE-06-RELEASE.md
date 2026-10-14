# 阶段 06 报告：文档验收与正式发布

## 1. 报告信息

| 项目 | 内容 |
|---|---|
| 项目版本 | v0.1.0 |
| 报告日期 | 2026-10-15 |
| 开发阶段 | 阶段 06 —— 文档验收与正式发布（规划文档 §6.1、§11） |
| 对应 Git 提交或标签 | 无（阶段 02 为 `d2f94e0`；阶段 03 及以后均为未提交的工作区状态，见 `docs/CHANGELOG.md`） |

## 2. 阶段目标

计划完成事项：

1. 补齐规划文档 §5 要求的文档体系（`docs/TEST_PLAN.md`、`docs/TEST_REPORT.md`、`docs/RELEASE.md`、根目录 `LICENSE`）。
2. 补齐 `docs/reports/` 的阶段报告与最终报告（按 §9.1 八节模板）。
3. 提供可复现的构建与打包：`scripts/build.*`、`scripts/package.*`，产出**便携版**发行包与 SHA-256 校验和。
4. 通过规划文档 §11 的发行验收清单（8 项）。

验收标准：§11 的八条 —— 干净环境可启动、界面不依赖 CDN/在线字体、正确连接目标并浏览文件、
主机密钥与认证失败处理正确、配置/日志/临时文件位置明确、无互联网可完成核心测试、
用户手册与发行包版本一致、版本号与构建记录与 SHA-256 齐全。

## 3. 实际完成情况

**已完成**

- `scripts/`：`start.py`（启动薄包装）、`test.py`（四层批量运行器）、`build.py`（八项静态校验）、
  `package.py`（便携版打包）、`testbed_wsl.sh`（WSL 测试床）。
- 根目录 `LICENSE`（MIT）与 `README.md` 刷新（功能表、版本、文档索引、系统要求）。
- 文档：`docs/TEST_PLAN.md`、`docs/TEST_REPORT.md`、`docs/RELEASE.md`；
  `docs/reports/` 的 PHASE-02-PROTOTYPE、PHASE-03-CORE、PHASE-04-SECURITY-TRANSFER、PHASE-05-OFFLINE-DEPLOY、
  PHASE-06-RELEASE 与 `FINAL_REPORT.md`；`docs/DECISIONS.md` 补 D-014~D-017 并更新已收敛的待决策项。
- 便携包：`dist/AWFM-0.1.0-windows-x64.zip`（最终为 82 个文件 / 82 个 zip 成员 / 约 300 KB 量级）+ `dist/SHA256SUMS.txt`，
  包内 `MANIFEST.json` 登记每个文件的 SHA-256，包内 `VERSION` 记录版本、构建时间、平台与构建主机 Python。

**部分完成**

- §11 第 3 项「正确连接指定虚拟机并浏览文件」：用 WSL Ubuntu 24.04.2 上的非 root `sshd` 测试床完成，
  **不是**规划文档提到的那台 CentOS 虚拟机。差别在发行版与 `sshd` 权限模型，协议与命令行参数无关，
  但结论的不同写法已在 `docs/TEST_REPORT.md` 与 `docs/TEST_PLAN.md` §9 声明。
- §11 第 6 项「无互联网条件下完成核心测试」：以「前端零外部 URL + 零第三方依赖 + 端到端对外请求为空」
  三条证据完成，未做系统级断网（无管理员权限）。

**未完成及原因**

- 真实 CentOS 目标机验证（本机无该环境）。
- 代码仓库尚无第二笔提交：阶段 03~06 的产物在本次收尾时统一提交，报告如实记为「未提交的工作区状态」。

## 4. 技术实现

1. **发行门禁**：`scripts/package.py` 默认先跑 `scripts/build.py` 的八项检查（Python 版本、语法校验、
   零第三方依赖、前端离线、凭据纪律、错误模型回归、版本一致性、测试包结构），任一失败即中止打包。
   这些检查覆盖的都是「功能测试全绿也照样能违反」的约束（决策 D-016）。
2. **凭据检查的口径而非一刀切**：示例 JSON 里的占位密码（`…`、`...`、`***`、`<...>`、`PASSWORD`、
   `placeholder`、空串）显式放行并计入检查输出，真实密码仍然拦截。首次运行就是被 `docs/API.md:319`
   的占位符命中，处理方式写进了检查本身的输出文本。
3. **打包流程**：暂存（`app/`、`frontend/`、`docs/`、`scripts/start.py`、`README.md`、`LICENSE`、
   `config/config.example.json`）→ 生成 `start.cmd` / `stop.cmd` / `VERSION` / `MANIFEST.json` →
   打 zip（固定时间戳 1980-01-01，`.sh` 成员置 0o755）→ 自检（`testzip()` 查 CRC + 逐个比对清单 SHA-256 +
   必需文件齐全 + 不得有清单外成员）。
4. **不捆绑 Python 的取舍**：零第三方依赖 + 静态资源自带 ⇒「解压即用、不要求在线安装依赖」用
   「一个 Python 3.10+ 解释器 + 本包」满足；`start.cmd` 依次尝试 `py -3` 与 `python`，都找不到时打印
   明确错误并返回 2（决策 D-015）。
5. **停止脚本防误杀**：`stop.cmd` 先按端口找出 LISTENING 的 PID，**再用 `tasklist` 确认该 PID 是 python
   进程**才执行 `taskkill /PID /T /F`；否则打印警告并返回 1。
6. **校验和的自引用处理**：`docs/` 随包分发，因此不把压缩包自身的 SHA-256 写进包内文档；
   校验和只放在 `dist/SHA256SUMS.txt` 与 git 提交信息里（决策 D-015）。

**与原设计的差异**：规划文档 §5 把 `pyproject.toml` / `requirements.txt` 列为「采用包管理或有第三方依赖时」
才需要 —— 本项目零依赖，故不创建；根目录也没有新增这两个文件。

## 5. 测试结果

| | 内容 |
|---|---|
| 测试环境 | Windows 11 家庭版 26300 / Python 3.12.10 / OpenSSH_for_Windows 9.5p2 / Edge 155.0.4283.45 / WSL Ubuntu 24.04.2 |
| 执行命令 | `python scripts/test.py`、`python scripts/build.py`、`python scripts/package.py` |
| 全量测试 | 单元 304 / 集成 18 / 安全 38 / 端到端 3，合计 **363 项，0 失败、0 错误、0 跳过** |
| 静态校验 | 八项全部通过（36 个源文件 / 30 个顶层模块全部标准库；`frontend/` 14 个文件无外部 URL；凭据扫描 28 个文件，放行 1 处示例占位符） |
| 打包自检 | 清单 81 项（不登记清单自身）+ `MANIFEST.json` = 包内 82 个文件，zip 成员 82 个；自检「压缩包完整，且包内每个文件与 MANIFEST.json 的 SHA-256 一致」 |
| 便携版冒烟 | 解压到临时目录 → `start.cmd --port 8899 --no-browser` → `/api/health` 返回 200 且版本 0.1.0 → 首页 200（4467 字节，令牌占位符已替换）→ `/assets/js/api.js` 200（6449 字节）→ 运行时目录 `data/`、`logs/awfm.log` 自动创建 → `stop.cmd` 输出「AWFM stopped.」后端口不再响应 |
| 关键测试证据 | `tests/e2e/artifacts/browser-journey-<RUN_TAG>.png`、`dist/SHA256SUMS.txt`、`dist/MANIFEST.json` |

## 6. 问题与风险

| # | 问题 | 处理 |
|---|---|---|
| 1 | 凭据检查把文档示例占位符 `{"password": "…"}` 判为真凭据 | 在检查内显式放行占位符写法并计入输出文本，而不是关闭检查（决策 D-016） |
| 2 | `tests/integration/support.py` 统计 `ssh.exe` 的 PowerShell 脚本在**只剩一个**子进程时返回 0（标量的 `.Count` 为空），导致 T-013 的断言在真正只有一个子进程时失败 | 用 `@(...)` 把管道结果包成数组；这条测试缺陷此前被环境里残留的多个 `ssh` 进程掩盖（假绿） |
| 3 | 打包脚本重复运行时哈希会变 | 已在 `dist/SHA256SUMS.txt` 说明：`VERSION` 含构建时间，重打包必然产生新哈希 |

**尚存风险**

- 包内不含 `tests/`，用户无法用包自证；发行质量由 `docs/TEST_REPORT.md` 与仓库承担（决策 D-015）。
- 用户需自备 Python 3.10+；`start.cmd` 能明确报错，但不能替用户安装。
- MIT 许可不含专利与商标条款（决策 D-017）。
- 未验证真实 CentOS 目标机与系统级断网。

## 7. 文档与交付物

- 文档：`README.md`、`LICENSE`、`docs/TEST_PLAN.md`、`docs/TEST_REPORT.md`、`docs/RELEASE.md`、
  `docs/reports/`（阶段 02~06 报告与 `FINAL_REPORT.md`）、`docs/DECISIONS.md`（D-014~D-017）、
  `docs/CHANGELOG.md`、`docs/_index.md`、`docs/PROJECT_STRUCTURE.md`。
- 构建产物：`dist/AWFM-0.1.0-windows-x64.zip`、`dist/AWFM-0.1.0-windows-x64/`（暂存目录）、
  `dist/SHA256SUMS.txt`；`dist/` 已在 `.gitignore` 中，不进仓库。
- 依赖与运行要求：Windows 10/11 + Python 3.10+ + 系统 OpenSSH 客户端；无第三方 Python 包；无外网要求。

## 8. 阶段结论

- **是否达到验收条件**：达到 §11 发行验收清单的 8 项，其中第 3、6 项按 §3 的写法降级表述（测试床替代
  CentOS 虚拟机、间接证据替代系统级断网），未用「通过」掩盖差异。
- **是否允许进入下一阶段**：无下一阶段 —— v0.1.0 按规划文档的六阶段到此结束。
- **后续任务**：真实 CentOS 目标机与断网空载验证；端到端覆盖扩展到下载与连接管理分支；
  为 `v0.1.1` 起启用 git 标签（`CHANGELOG.md` 已预留格式）。
