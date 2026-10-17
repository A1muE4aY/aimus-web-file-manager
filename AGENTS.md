# AGENTS.md — `E:\Project\aimus-web-file-manager`

本工作区**本身就是 AWFM 项目根**，不存在「大类 → 编号」两层结构。本文件按全局
`~/.dsh/AGENTS.md` §2.12 钉死本工作区的**顶层白名单与例外**；未列入的顶层条目一律不得新增。

## 1. 权威规格来源

- 规划文档（用户提供，**只读输入，不得改写**）：`E:/Project/aimus-web-file-manager/dev_guide/`
  ——当前接力的版本是 `dev_guide/0.1.2_.md`，历史版本 `0.1.0_.md` `0.1.0_opt1.md` `0.1.1_.md` 同目录留档。
- 本项目的目录结构、功能分级、测试矩阵、文档体系全部以该文件 §3/§5/§7/§9 为准。
- 与之冲突时：**用户当前对话的直接指示 > 本文件 > 规划文档 > 全局 AGENTS.md**。

## 2. 顶层白名单（唯一允许出现在根目录的条目）

| 条目 | 性质 | 说明 |
|---|---|---|
| `app/` | 源码 | 后端应用代码，按 `api/ core/ services/ ssh/ models/ utils/` 分包 |
| `frontend/` | 源码 | 离线可用的原生 HTML/CSS/JS，**禁止任何在线 CDN / 在线字体** |
| `config/` | 配置模板 | 只放 `config.example.json` 与 `config/.gitignore`；**真实配置不得进这里** |
| `tests/` | 测试 | `unit/ integration/ e2e/ security/ fixtures/` |
| `scripts/` | 脚本 | `start.* test.* build.* package.*`，动词开头 |
| `docs/` | 文档 | 设计、需求、API、测试、安全、变更、发行与 `reports/` |
| `data/` | 运行时 | 真实配置与运行数据；**已在 .gitignore**，不提交 |
| `logs/` | 运行时 | 运行日志；**已在 .gitignore**，不提交 |
| `dist/` | 构建产物 | 便携发行包（`AWFM/` 暂存树 + `AWFM-<版本>.zip`，解压根目录固定 `AWFM/`）；**已在 .gitignore**，不提交 |
| `.temp/` | 草稿 | 会话中转；可随时整体清空 |
| `.archive/` | 归档 | 本项目的 `duplicates/ deps/ junk/ misc/`；**只进不出** |
| `README.md` `AGENTS.md` `.gitignore` `.gitattributes` | 根文件 | 允许（`.gitattributes` 钉仓库内行尾为 LF：`scripts/testbed_wsl.sh` 在 WSL 里执行，CRLF 会让 shebang 与续行报 `\r: command not found`） |
| `run.bat` `run.sh` `run-advanced.bat` `run-advanced.sh` | 源码 | 启动入口（v0.1.3 §5）：**启动**入口 `run.bat`/`run.sh` 不带参数即启动（查环境 → 起服务 → 就绪后开浏览器 → 窗口留在前台，按 Ctrl+C 停止服务；直接关窗口则服务继续在后台跑；`run.bat` 用 `start /b` 交棒，避免 cmd 的 `Terminate batch job` 询问）；**菜单**入口 `run-advanced.bat`/`run-advanced.sh` 不带参数进交互菜单。四者都只做「找 Python → 转交 `scripts/launcher.py`」，实现只有一份 |
| `dev_guide/` | 用户输入 | 规划文档与接力任务书，**只读、保持原名原位置不动**（2026-10-17 由用户从根目录 `0.md` `1.md` `2.md` 迁入） |

## 3. 例外与纪律

1. **文档不进子目录**：`docs/` 下的交付文档直接放 `docs/` 根；阶段报告放 `docs/reports/`。
2. **中间产物不得留在根目录**：日志、缓存、`__pycache__`、临时下载 → `data/`、`logs/` 或 `.temp/`。
3. `frontend/` 内禁止出现任何指向外网的 URL（`http(s)://` 除注释与文档链接外）。离线可用是验收项 T-002。
4. **凭据纪律**：私钥、密码、host key 私密文件不得写入 `config/`、`docs/`、`tests/fixtures/` 中会被提交的位置。
5. 运行时目录 `data/` `logs/` `dist/` 由程序或脚本按需创建，**不在仓库里预建空目录**。
6. 新增文件 ≥5 个的目录需要 `_index.md` 登记（文件名 / 用途 / 生成方式）。

## 4. 已知环境事实（阶段 01 实测，2026-10-15）

- 宿主机 Windows 11 家庭版 26300 / AMD64；PowerShell 5.1（**不是 pwsh 7**，脚本勿用 PS7 专属语法）。
- `python` → `E:\Software\Python 3.12\python.exe`（3.12.10）；**无 `python3`**；`py` 启动器存在。
- OpenSSH_for_Windows 9.5p2：`ssh` `sftp` `scp` `ssh-keygen` `ssh-add` 均可用。
- VMware Workstation 26.0.0；VMnet8 `192.168.170.0/24`（NAT），VMnet1 `192.168.11.0/24`（Host-only）。
- 测试虚拟机：`E:\Virtual Machines\CentOS 10\CentOS Stream 10.vmx`（集成测试目标）。
- 本机 **没有** 可用的 SSH 服务端（`localhost:22` 关闭，安装 OpenSSH Server 需要提权且当前会话无审批）。
