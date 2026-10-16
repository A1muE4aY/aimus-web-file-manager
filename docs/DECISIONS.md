# AWFM 技术选型与决策记录

每条记录包含：决策、备选方案、理由、代价。**决策理由是该条最不可省略的部分**——
没有理由的决策在下一次评审时无法被检验。

---

## D-001 宿主机 = Windows 本机，目标机 = Linux

- **决策**：服务运行在 Windows 宿主机；首版只保证管理 Linux 目标机。
- **备选**：Linux 宿主机；Windows/Linux 双向支持。
- **理由**：项目面向 VMware Workstation 场景（规划文档 §1.2），宿主机实际就是 Windows 11；
  引入跨平台适配层会显著增加首版工作量，而首版的价值在于把 SSH 链路做可靠。
- **代价**：路径语义按 POSIX 处理（`/` 分隔、区分大小写、符号链接）。若将来支持
  Windows 目标机，需要在 `app/utils/` 增加路径方言抽象。**该抽象已在设计上预留**
  （见 D-006），但首版不实现。

## D-002 后端 = Python 3 标准库，零第三方运行时依赖

- **决策**：后端只用 Python 3 标准库（`http.server`、`json`、`subprocess`、`logging` 等）。
- **备选**：Flask/FastAPI + Paramiko；Node.js + ssh2。
- **理由**：规划文档 §2.1 与 N-02 要求「尽可能少的依赖」「离线可用」。
  Python 3.12 已装在宿主机；任何 pip 依赖都会让便携版必须携带 wheel 或联网安装，
  直接违背 §11 的开箱即用门槛。
- **代价**：`http.server` 功能有限，需要自己实现路由、请求体限长、错误映射与静态文件服务。
  这些是可控的一次性成本，且换来「解压即用」。
- **放弃的方案**：`socketserver` 裸写协议层——`http.server` 已提供正确的 HTTP 解析，没必要重造。

## D-003 SSH = 系统 OpenSSH 子进程，不引入 SSH 协议库

- **决策**：通过 `subprocess` 调用 Windows 自带的 `ssh.exe` / `sftp.exe`。
- **备选**：Paramiko（纯 Python SSH）；`plink`（PuTTY）；自己实现 SSH 协议。
- **理由**：
  1. 规划文档 §2.1 的首选路线。
  2. 系统 OpenSSH 自带 `known_hosts` 校验、`ssh-agent` 集成、密钥格式兼容与算法协商，
     这些用 Paramiko 重新实现一遍是纯粹的风险转移。
  3. 零第三方依赖（D-002）。
- **代价（必须如实记录）**：
  1. **依赖目标机有 SFTP 子系统**，且依赖宿主机有 OpenSSH 客户端——发行文档必须写清。
  2. ~~需要解析 `sftp` 的文本输出~~ —— **该风险已被 D-011 消除**：改用
     `ssh -s <host> sftp` 取得裸 SFTP v3 二进制协议通道，不再解析任何人类可读输出。
  3. 密码认证需要 `SSH_ASKPASS` 机制（见 D-008）。
- **放弃的方案**：`sshpass`——Windows 上没有，且它同样是把密码塞进环境/命令行。

## D-004 目录列举：`sftp` 批处理模式 + 固定时区/语言环境 —— **已被 D-011 取代**

> **状态：作废（2026-10-15）**。本决策建立在「只能解析 `sftp` CLI 文本输出」这一错误前提上。
> 阶段 02 SPIKE 实测证明可以拿到裸 SFTP 协议通道（D-011），文本解析的全部脆弱点随之消失。
> 下方内容保留作为**决策演进记录**，实现层**不得**再引用本决策。

- **决策**：目录列举走 `sftp -b -` 批处理模式执行 `ls -l`，并对子进程强制
  `TZ=UTC`（使 `localtime()` 等价于 UTC）与 `LC_ALL=C`（使月份缩写固定为英文）。
- **理由**：`sftp` 的 `ls -l` 由**客户端**格式化，时间戳来自服务端的 `mtime`（epoch 秒），
  经客户端 `localtime()` 转换。若不定死时区与语言，同一台目标机在不同宿主机上
  会解析出不同的时间甚至不同的月份字符串。**定死这两个变量后，解析结果可复现。**
- **代价**：解析器必须容忍 OpenSSH 的两套日期格式：
  半年内为 `%b %e %H:%M`（无年份），超过半年为 `%b %e  %Y`（两个空格）。
  解析逻辑必须有单元测试覆盖，并用真实抓取到的输出做夹具。
- **未决**：文件名含换行符时 `ls -l` 输出不可解析。首版策略是**在路径校验层拒绝控制字符**，
  并在 `docs/SECURITY.md` 登记为已知限制。

### 实测结果（推翻本决策的证据）

在 WSL 非 root sshd 测试床上执行 `sftp -b -`，抓到真实输出：

```
drwx******    ? aimu     aimu         4096 Oct 15 00:06 sub
-rw-******    ? aimu     aimu           12 Oct 15 00:06 中文 文件名.txt
```

1. **权限位被客户端遮蔽成 `*`**：只保留文件类型位与属主三位，其余六位全是 `*`，nlink 字段是 `?`。
   → P1 的「权限/属主展示」在文本路线上**信息已经丢失**，无法实现。
2. 日期依赖**人类可读格式**，半年内为 `%b %e %H:%M`、超过半年为 `%b %e  %Y`（两个空格）。
   → 需要为格式差异写容错解析，且丢失时区之外的精度信息。
3. 批处理模式**仍会把每条命令回显成 `sftp> <命令>`** 混入 stdout，末尾还有孤立 `sftp> `。
4. 批处理**遇错即中止**，一个失败命令会静默吞掉后续命令。
5. 名字含 ` -> ` 时 symlink 行不可解析。

**这些代价全部来自「用文本界面承载结构化数据」这一路线选择本身**，而非实现质量。
原生协议一次性消除全部五项（见 D-011）。

## D-005 前端 = 原生 HTML/CSS/JS，无框架、无 CDN

- **决策**：不使用任何前端框架、构建工具或在线资源。
- **理由**：规划文档 §2.1 + 验收项 T-002（离线加载全部必要资源）。引入 CDN 会直接
  让离线场景失败；引入打包工具会引入 Node 构建链，与「轻依赖」冲突。
- **代价**：需要手写 DOM 渲染、事件委托与状态管理。规模可控（单页文件管理器）。

## D-006 配置存储 = JSON 文件，不引入数据库

- **决策**：`data/config.json`，原子写入（临时文件 + `os.replace`）。
- **理由**：配置可读、可备份、可追踪（规划文档 §2.1）。连接数量是个位数，数据库是纯负担。
- **代价**：并发写需要自己加锁；文件损坏需要显式报错而不是静默重置——
  **静默重置会丢失用户配置，属于不可接受的行为**。

## D-007 传输 = 流式，不整份读入内存

- **决策**：下载/上传走子进程 stdin/stdout 管道，以固定大小块转发（默认 64 KiB）。
- **理由**：规划文档 §4.2 明确要求；避免大文件把服务进程内存打满。
- **代价**：需要处理「客户端中途断开」与「子进程退出码」的组合，并保证文件句柄与子进程
  在异常路径上都被回收（验收项 T-013）。

## D-008 密码认证 = `SSH_ASKPASS` + 强制模式

- **决策**：密码认证时设置 `SSH_ASKPASS` 与 `SSH_ASKPASS_REQUIRE=force`，
  由辅助程序把密码写到 stdout 交给 `ssh`/`sftp`。
- **备选**：`sshpass`（Windows 不可用）；PuTTY `plink -pw`（引入第三方二进制）。
- **理由**：这是 OpenSSH 官方支持的非交互密码注入机制，Ansible、VS Code Remote 等
  均使用同一机制。
- **代价与已知风险**：密码需要从父进程传给辅助程序。传递通道、以及它在进程环境/命令行中的
  可见性，**必须在 `docs/SECURITY.md` 中明确登记**，并优先引导用户使用密钥认证。
  具体通道在阶段 02 的 SPIKE 中实测确定（见 `docs/reports/PHASE-02-SPIKE.md`）。

## D-009 服务默认只监听回环地址

- **决策**：`server.host` 默认 `127.0.0.1`；`security.allow_lan=false` 时，
  启动过程会**拒绝**非回环绑定地址。
- **理由**：规划文档 §10.3。离线不等于安全——本机其他进程同样能访问管理接口。
- **代价**：想从别的机器访问必须显式改配置并阅读安全文档。

## D-010 主机密钥策略默认 strict

- **决策**：`security.host_key_policy = "strict"`。使用**项目自有的 `data/known_hosts`**，
  而非用户 `~/.ssh/known_hosts`；首次连接必须由用户显式确认并导入指纹。
- **理由**：验收项 T-005 要求「不得静默接受未经确认的新主机密钥」。
  使用自有 known_hosts 可避免污染用户既有 SSH 信任库，也让「首次确认」这件事在
  应用里可被明确表达，而不是藏在 ssh 的交互提示里。
- **代价**：用户首次连接多一步确认。这是刻意设计的成本。

---

## D-011 连接层 = 原生 SFTP v3 协议，经 `ssh -s sftp` 子进程

- **决策**：连接层不走 `sftp` CLI 文本界面，而是执行
  `ssh <options> <user>@<host> -s sftp`，与远端 `sftp-server` 直接交换
  **SFTP v3 二进制协议帧**。协议编解码用 `struct` 手写，仍是零第三方依赖。
- **备选**：
  1. `sftp -b -` 批处理 + 解析 `ls -l` 文本（原 D-004，已作废）；
  2. Paramiko（违背 D-002 零依赖）；
  3. `ssh -- sh -c 'cat -- "$1"' sh '<path>'` 取文件流（只解决传输，不解决元数据）。
- **理由（全部有实测证据，见 `docs/reports/PHASE-02-SPIKE.md`）**：
  1. **信息完整性**：`STAT`/`READDIR` 返回 `flags=15` 的完整 ATTRS ——
     权限位 `0o100644` / `0o120777` **原样未被遮蔽**（CLI 界面里是 `-rw-******`），
     uid/gid、字节大小、`atime`/`mtime` 均为 epoch 整数。P1 的权限与属主展示因此**可实现**。
  2. **无本地化依赖**：时间戳是整数，不再需要 `TZ=UTC`/`LC_ALL=C` 这类环境变量补丁，
     也不再有「两套日期格式」的解析分支。
  3. **结构化错误**：失败返回 `STATUS` 包与数值码（`2`=No such file、`3`=Permission denied、
     `4`=Failure、`8`=OP_UNSUPPORTED），可直接映射为 API 错误码，不必匹配英文错误串。
  4. **文件名保真**：协议长度前缀字符串，含空格、中文、emoji、` -> ` 的名字**原样往返**。
  5. **真流式**：`READ`/`WRITE` 以 offset+length 分块，64 KiB 块上传 256000 字节实测字节数一致。
- **前提（已实测）**：Windows 的 `ssh.exe` 管道是**二进制安全**的 ——
  1024 字节含 `0x00`-`0xFF` 的载荷经 `ssh ... cat` 往返**逐字节相同**，无 CRLF 转换。
- **代价（如实记录）**：
  1. 需要自己实现协议编解码。**已实测到两个高频错误源**：服务端响应包**第一字段是请求 id**
     （漏读会导致全部解析错位）；`MKDIR`/`SETSTAT` 的属性字段是**完整 ATTRS 结构**
     （`uint32 flags` + 按 flags 出现的字段），不是裸 `uint32` ——
     发错会让 `sftp-server` 直接 `fatal()` 退出并表现为「EOF poll=None」。
     两者都必须写单元测试钉死。
  2. 需要自己做请求-响应配对与超时（协议无内置超时）。
  3. 需要与 `known_hosts` 校验、密码认证等 ssh 层选项正确组合。

## D-012 本地开发/集成测试用「WSL 非 root sshd」测试床

- **决策**：集成测试目标为 WSL2 Ubuntu 内以**普通用户身份**运行的
  `sshd`，监听 `127.0.0.1:2222`，配置与密钥全部位于 `~/.awfm-testbed/`。
- **备选**：启动 VMware CentOS 虚拟机（规划文档首选，但需人工开机、IP 依赖 DHCP，
  且无法在无人值守下复现）；安装 Windows OpenSSH Server（**需管理员权限，当前不可行**）。
- **理由**：
  1. **零提权**：`sshd` 在非 root 下会跳过特权分离，用 `dpkg -x` 解包的二进制即可直接运行。
  2. **可用**：WSL2 的 localhost 转发让 Windows 侧 `127.0.0.1:2222` 直连，无需改网络。
  3. **可复现**：脚本化后可随时重建，不依赖任何虚拟机状态。
- **代价**：WSL sshd 的 UID/GID 与真实 CentOS 目标机不同；WSL2 的 `localhost` 转发
  是 WSL 特性，不代表任意目标机可达。**因此它只作为开发期测试床**，
  规划文档 §7.2 要求的端到端验证仍需在真实 CentOS 虚拟机上补做（阶段 05）。
- **配套脚本**：`scripts/testbed_wsl.sh`（WSL 内执行，幂等）。
- **注意**：测试床不含 `sudo`，任何需要 root 的验证（PAM、`UsePAM yes`、特权端口 <1024）
  **不在测试床覆盖范围内**，不得据此声称已验证。

## D-013 Windows 上一切文本 I/O 显式钉 UTF-8

- **决策**：程序启动时对 `sys.stdout`/`sys.stderr` 调用
  `reconfigure(encoding="utf-8")`；所有日志文件、JSON 读写、`subprocess` 文本管道
  **显式传 `encoding="utf-8"`**；启动脚本设 `PYTHONUTF8=1`。
- **理由（实测故障）**：Python 在 Windows 上默认 stdout 编码是 **GBK**。向控制台
  打印一个 emoji 文件名（`🎉` U+1F389）直接抛
  `UnicodeEncodeError: 'gbk' codec can't encode character '\U0001f389'` 并终止程序。
  文件管理器**必然**要处理非 ASCII 文件名，这不是边角情况。
- **代价**：几乎为零。若用户控制台代码页不是 UTF-8，个别字符可能显示问号，
  但**数据本身不丢失**（JSON 响应与日志文件都是 UTF-8 字节流）。

## D-014 密码从不持久化

- **决策**：配置文件里**没有**密码字段（`app/models/connection.py` 的字段清单里没有它）；密码只在
  `POST /api/connections/{id}/connect` 的请求体里出现一次，交给一次性的 `SSH_ASKPASS` 辅助程序
  喂给 `ssh` 子进程，认证结束立即销毁（与 D-008 配套）。密码**不经过命令行参数、也不经过环境变量**。
- **备选**：把密码写进 `config.json`；或写进系统凭据库（Windows Credential Manager / libsecret）。
- **理由**：把密码写进本地 JSON，其安全性完全依赖该文件的 ACL；而本项目按 D-001/§1.2 的定位是
  「普通用户在自己机器上运行」，默认非管理员账户，无法保证 ACL 正确配置。与其提供一个「看起来安全」
  的选项，不如不提供——用户看不见的风险比多输一次密码更贵。写进系统凭据库则需要引入平台相关依赖，
  与 D-002 冲突。
- **代价**：每次重连都要重新输入；界面上从密码切到密钥时密码框可能有残留（已在 `docs/API.md` 5.8 注明）。
  另一个代价是**无法「后台自动重连」**——这被明确接受：需要的场合应当改用密钥认证。
- **可核实依据**：`app/models/connection.py`（模块 docstring）、`app/ssh/askpass.py`、
  `tests/unit/test_connection_model.py:88`、`tests/security/test_credentials.py`（哨兵密码不出现在落盘配置、
  响应、日志与 `argv` 中）。

## D-015 便携版打包口径：不捆绑 Python，不含 tests/ —— **包内启动脚本清单已由 D-020 更新**

- **决策**：`scripts/package.py` 产出的便携包 = 仓库的可运行子集
  （`app/`、`frontend/`、`docs/`、`scripts/start.py`、`README.md`、`LICENSE`、
  `config/config.example.json`、`scripts/launcher.py`、`run.bat`、`run.sh`，加上自己生成的 `VERSION`、`MANIFEST.json`；**v0.1.2 阶段三起不再生成 `start.cmd`/`stop.cmd`**，见 D-020）；
  **不捆绑 Python 运行时，也不把 `tests/` 打进去**。包内每个文件在 `MANIFEST.json` 里登记 SHA-256，
  压缩包整体哈希写进 `dist/SHA256SUMS.txt`。
- **备选**：PyInstaller / Nuitka 打单文件 exe；把 Python 解释器嵌入包内；把 `tests/` 一并分发。
- **理由**：项目零第三方依赖（D-002）且静态资源全部自带（验收项 T-002），因此规划文档 §11
  要求的「解压后运行启动脚本、不要求在线安装依赖」用**一个 Python 3.10+ 解释器 + 本包**即可满足。
  打包器会带来体积、杀软误报与构建复杂度，而它要解决的唯一问题（解释器）并不比「让用户装一次 Python」
  更省事，也不符合本项目「可复核」的取向——包里的东西应当一眼看得懂。`tests/` 属于开发版（即仓库本身），
  进包只会让发行包对最终用户更吵。
- **代价**：用户须自备 Python 3.10+（`run.bat`/`run.sh` 找不到解释器时明确报错并指向 README 的「系统要求」）；
  包内不含测试，所以「用户手上这份包能不能跑通测试」不能自证，只能由发行时的
  `docs/TEST_REPORT.md` 与仓库里的四层测试承担。
- **自引用问题**：`docs/` 随包分发，所以**不把压缩包自身的 SHA-256 写进包内文档**（写了就自相矛盾：
  改文档 → 哈希变 → 文档又过期）。校验和只放在 `dist/SHA256SUMS.txt` 与 git 提交信息里。

## D-016 构建前静态校验（`scripts/build.py` 八项）作为发行门禁

- **决策**：`scripts/package.py` 默认先跑 `scripts/build.py` 的八项检查，任一失败即中止打包
  （`--skip-checks` 可以跳过，但那是给人手动补救用的，不是常规路径）。
  八项为：Python 版本、语法校验（`SyntaxWarning` 视为错误）、零第三方依赖（ast 扫描 import）、
  前端离线（frontend 内不得有外部 URL）、凭据纪律、错误模型回归、版本一致性、测试包结构。
- **理由**：其中五项（依赖数、前端 URL、凭据、版本一致性、测试包结构）属于
  **「一旦回退也不会被功能测试发现」**的约束——功能全绿照样能违反它们。把它们做成一条可重复执行的
  本地命令，比写在文档里指望人记住更可靠；这也是规划文档 §11「构建过程可复现」的落点。
- **代价**：静态检查一定会误报，因此必须允许**写明口径的例外**，而不是随手关掉检查。第一次运行就遇到：
  `docs/API.md:319` 的示例 JSON 写作 `{"password": "…"}`（占位符），被「填了值的 password 字段」
  规则命中。处理方式是在检查里显式放行占位符写法（`…`、`...`、`***`、`<...>`、`PASSWORD`、
  `placeholder`、空串），并把它计入检查输出文本（会打印「1 处示例占位符已放行」）。
- **防复发**：「错误模型回归」这一项就是 2026-10-15 真实缺陷的闸门——四处代码把类属性 `http_status`
  当构造参数传（`TypeError` → 500 掩盖真实错误），见 `docs/reports/PHASE-05-OFFLINE-DEPLOY.md`。

## D-017 许可证 = MIT

- **决策**：根目录 `LICENSE` 采用 MIT 许可，版权行 `Copyright (c) 2026 Aimu`。
- **备选**：Apache-2.0；GPL-3.0；不提供许可（保留全部权利）。
- **理由**：规划文档 §5 的目录树把 `LICENSE` 列在根目录，属于必须交付的文件；用户未指定许可证，
  因此选最短、最常见、对个人工具负担最小的宽松许可。它同时满足「可分发便携版」这一形态对使用者
  的最低要求（明确可以复制、修改、再分发）。
- **代价**：MIT 不含专利授权与商标条款；若将来要面向更严格的分发环境，需要重新评估并替换
  `LICENSE` 与 `README.md` 的「许可」一节。更换成本很低，这是选择它的另一个原因。

## D-018 虚拟机发现 = 本地 VMware 信息 + 限定网段的 TCP 探测

- **决策**：发现只使用宿主机本地已有的信息与有限探测，按可靠性分层：
  1. `%APPDATA%\VMware\inventory.vmls` —— 虚拟机清单（配置路径、显示名、UUID）。普通用户可读。
  2. VMware 的 `vmrun.exe list`（路径由注册表 `HKLM\SOFTWARE\VMware, Inc.\VMware Workstation` 的 `InstallPath` 与常见位置探测得到）—— **运行状态的权威来源**；不可用时只把运行状态标为「未知」并写明原因，不让整次扫描失败。
  3. `.vmx` 文件 —— 显示名、`guestOS`、`ethernet0.generatedAddress`（MAC）、`uuid.bios`、网络类型。
  4. `vmnetdhcp.conf` 与 `vmnetdhcp.leases`（`C:\ProgramData\VMware\`）—— 虚拟网段与 **IP 历史**（IP、起止时间、MAC、客户端主机名）。
  5. 系统邻居表 + **只对已知虚拟网段内的候选地址**做 TCP 22 探测 —— 当前可达性，以及「这个地址是否提供 SSH」。
  6. 三种状态分开建模、不合并：**发现虚拟机**（清单/文件层）／**地址在线**（邻居表或探测确认）／**SSH 可用**（TCP 22 握手成功）；每个字段都带来源与采集时间，未知就显示未知。
  7. 发现结果只是候选：创建连接仍走既有「新增连接」表单（用户可改主机、端口、用户名、认证方式），主机指纹仍走既有首次确认流程，**不自动创建可信连接、不自动信任指纹**。
- **备选**：
  - A. 只读清单文件、不做任何网络探测 —— 更简单，但回答不了「这台虚拟机现在能不能连」，也区分不出「关闭」与「在线」。
  - B. 走 `vmrest.exe` 的 REST API（TCP 8697）—— **实测该端口未监听**，要额外启动并维护一个常驻服务，还多一个需要认证的本地 HTTP 面，不划算。
  - C. 读 `vmware-vmx.exe` 进程的命令行/路径来判运行状态 —— **实测被否决**：非管理员会话下 `Win32_Process.CommandLine`、`ExecutablePath`、`Get-Process.Path` 全为空。
  - D. 对整个 `192.168.170.0/24` 做端口扫描 —— 越界、慢，且 NAT 网段里可能还有非本项目的设备；任务书明确禁止无边界全网扫描。
- **理由**：
  1. 任务书要求「优先使用本机已有的虚拟化管理信息与有限范围网络发现」「不要求管理员权限」；第 1~5 项全部是本地文件读取与本地 TCP 连接，实测在**非管理员** shell 下都可用。
  2. 唯一能给出权威运行状态的是 VMware 自己的 `vmrun`（实测退出码 0，输出 `Total running VMs: 1` 与在跑虚拟机的 vmx 路径）。把它做成**可选依赖**：有则拿到最可靠的信息，没有也不至于整功能不可用。
  3. 「零第三方运行时依赖」（D-002）约束的是**库**：调用已安装的 VMware 命令行工具与读本地文件都不违反它。
- **代价与已实测的坑**：
  1. 发现能力绑定 VMware Workstation。其他虚拟化平台只做「检测到并明确说明未支持」，不实现（任务书禁止擅自扩展）。
  2. **租约文件是历史而不是现状**：实测 4 条租约的 `ends` 全部已过期，不能单独当作「在线」证据，必须与邻居表/TCP 探测交叉验证。
  3. **`.vmx.lck` 目录不可靠**：实测 `Ubuntu x64` 已关机却仍有 `.vmx.lck`，而 `vmrun list` 只报 1 台在跑。锁目录只能作为弱提示，**绝不**作为「正在运行」的依据。
  4. 邻居表里存在大量 `Unreachable` 历史条目（同一网段实测 80 条以上），必须按状态过滤，否则会把并不存在的主机报成「发现」。
  5. 清单可能指向已被删除的虚拟机：实测 `inventory.vmls` 里的 `CentOS version 5 and earlier 64-bit.vmx` 在磁盘上已不存在。这类条目要显示为「文件缺失/未知」，不能猜。
  6. 探测必须有上限：每个已知网段最多探测 254 个地址、并发受限、单地址超时不超过 1 秒；只探测网段内的候选地址，不做端口扫描。

### 实测证据（2026-10-16，非管理员 shell）

| 事实 | 实测值 |
|---|---|
| VMware Workstation | 注册表 `InstallPath` = `E:\VMware Workstation Pro\`（`vmrun.exe` 与 `vmrest.exe` 都在这里） |
| `vmrun list` | 退出码 0；`Total running VMs: 1`；`E:\Virtual Machines\CentOS 10\CentOS Stream 10.vmx` |
| 虚拟机清单 | `C:\Users\Aimu2\AppData\Roaming\VMware\inventory.vmls`（1951 字节，3 条 vmlist，其中 1 条指向已不存在的 vmx） |
| 虚拟网段 | VMnet8 `192.168.170.0/24`（DHCP 池 .128–.254，网关 .2）；VMnet1 `192.168.11.0/24`（池 .128–.254） |
| 租约文件 | `C:\ProgramData\VMware\vmnetdhcp.leases`（1220 字节，4 条租约，`ends` 全部已过期） |
| 邻居表 | `192.168.170.128 → 00-0C-29-58-7B-2A`（state=Stale）；同网段 80 条以上 `Unreachable` |
| 在跑的虚拟机 | CentOS Stream 10：MAC `00:0c:29:58:7b:2a` ↔ 当前 `192.168.170.128`（同一 MAC 的历史租约曾是 `.130`，可用于「IP 变化」用例） |
| SSH 探测 | `192.168.170.128:22` 16 ms 内连上；`192.168.170.2`（NAT 网关）ping 通但 22 不通 —— 现成的「地址在线但没有 SSH」实例 |
| 非管理员可读 | 清单、`preferences.ini`、`vmnetdhcp.conf`/`leases`、邻居表、`vmrun` |
| 非管理员读不到 | `vmware-vmx.exe` 的命令行与路径（要更高权限）—— 「跳过并解释原因」的真实样本 |

## D-019 单次 SFTP WRITE = 最多 64 KiB，超过就拆帧（服务端整包上限 256 KiB）

- **决策**：`SftpClient.write_chunk` 把超过 `MAX_WRITE_CHUNK`（64 KiB）的数据拆成多个 `SSH_FXP_WRITE` 帧依次发送，每帧带自己的偏移；两个常量（`MAX_WRITE_CHUNK`、服务端整包上限 `OPENSSH_MAX_PACKET_BYTES` = 256 KiB）钉在 `app/ssh/sftp_protocol.py`。
- **备选**：
  - A. 只让调用方自己分块（在线编辑保存时按 64 KiB 切）—— 只修好一条路径；`upload_stream`、`ChunkWriter`（压缩打包）与将来的调用方仍可能再犯，而犯错的代价是「整条通道被服务端掐断」，不是一次可恢复的报错。
  - B. 在 `SftpTransport.transact` 里拒绝超长请求帧 —— 报错位置更靠底层，但只是把「写死连接」换成「一直报错」，大文件依旧写不进去。
- **理由**：
  1. `write_chunk` 是所有写入路径的唯一收口（`upload_stream`、`ChunkWriter.write`），在这里拆帧一次性覆盖上传、覆盖写、在线编辑保存、压缩打包。
  2. 拆分对上层完全透明：偏移、帧序、写完后的回读校验（`upload_stream` 用 `STAT` 比对字节数）都不变。
  3. 64 KiB 与读取块保持一致（D-007），并且给帧头（长度字段、类型、request-id、handle、偏移、数据长度字段）留足余量。
- **代价与已实测的坑**：
  1. 1.9 MiB 的保存从 1 帧变成 30 帧，多出 29 次往返；实测一次 1.9 MB 写入仍在 1 秒量级，可接受。
  2. **这个上限不是协议的一部分，而是服务端实现的行为**：OpenSSH 的 `sftp-server` 用 `SFTP_MAX_MSG_LENGTH`（256 KiB）判**整包**长度，超限时打印 `bad message from ...` 并**结束连接**。客户端收不到任何 STATUS，只看到管道断开 —— 在本项目里表现为 `NotConnected`：「写入远端失败：连接已断开。」，极易被误判成网络问题。
  3. 实测边界（WSL 测试床 OpenSSH_9.6p1 Ubuntu-3ubuntu13.20）：一次 WRITE 携带 261120 字节成功，262144 字节即断连；`MAX_FRAME_BYTES`（4 MiB）管的是**入站**帧，管不到这个上限。
  4. 对应的真实缺陷（v0.1.2 阶段一 D1 第二层）：`app/services/editor.py:342` 用 `upload_stream(temp, [data])` 把在线编辑的整份文本当**一个**块写出去，于是 256 KiB 以上的文件「能打开、保存必失败」。回归测试：`tests/unit/test_sftp_client.py`（5 项，含实测失败尺寸 262144）与 `tests/integration/test_edit_api.py` 的 `test_file_between_the_transport_ceiling_and_the_edit_limit_saves`。


## D-020 统一启动入口 = `run.bat` / `run.sh` + `scripts/launcher.py`（v0.1.2 阶段三）

- **决策**：对外只留一个入口——Windows 双击 `run.bat`、Linux/macOS 执行 `./run.sh`；两个外壳只做三件事
  （切到脚本所在目录、找 Python 解释器、把参数原样转交给 `scripts/launcher.py`），**逻辑只有一份 Python 实现**
  （`scripts/launcher.py`，命令 `menu`/`start`/`status`/`stop`/`restart`/`logs`/`check`/`help`，不带命令时进入交互菜单）。
  默认端口从 8760 改为 **32579**。
- **备选**：
  - A. 把 `start.cmd` 直接改名成 `run.bat`、`stop.cmd` 改名成 `run.sh` —— 正是任务书 §3.3 明确禁止的做法：两个平台各写一套外壳，逻辑立刻分叉。
  - B. 只提供 `python scripts/launcher.py`，不做外壳 —— 用户得先会开命令行、还得知道 Python 装在哪；「双击就能用」是这次改造的起点。
  - C. 在外壳里写 PowerShell / bash 的启动逻辑 —— 进程存活判断、PID 文件、健康检查在两个平台上无法共用，测试也要写两遍。
- **理由**：
  1. 一个入口少一类支持问题：用户不用先判断「我该运行哪一个」。
  2. 逻辑集中在可单元测试的 Python 里：`tests/unit/test_launcher.py`（39 项）直接调用 `launcher.py` 的函数，外壳只剩转发；
     `tests/integration/test_launcher_lifecycle.py`（7 项：生命周期 4 + 外壳退出码 3）用子进程跑真实生命周期（启动 → 重复启动 → 状态 → 日志 → 停止 → 再启动），
     `WrapperExitCodeTest` 再验一遍外壳的退出码传递（Windows 走 `cmd /c run.bat`，POSIX 走 `/bin/sh run.sh`）。
  3. 退出码就是「状态与请求是否一致」：`start` 发现已经在运行返回 3 且不改动任何东西；`stop` 发现没在运行也返回 3；
     `check`/`start` 失败返回 1；用法错误返回 2。脚本与人都能据此判断，不需要解析输出文本。
- **停止纪律（验收条款 4）**：`stop` 只认 `data/awfm.pid` 里记的 PID，并要求该 PID 的映像名含 `python`
  （否则打印「拒绝停止：PID N 的映像名是 X，不是 python 进程。」）；**没有 PID 文件时绝不去动占用端口的程序**，
  只报告「AWFM 没有在运行（没有 PID 文件），但 127.0.0.1:32579 上有别的程序在监听。停止只作用于 AWFM 自己记录的进程，这里不会去动它。」。
  Windows 上后台进程收不到温和信号，先温和 `taskkill /PID N /T`，没退再**征求确认**才 `taskkill /F /T`；
  非交互终端一律当作拒绝并返回 1（自动化用 `stop --force --yes`）。
- **代价**：
  1. 链路多了一层（`run.bat` → `launcher.py` → `app/main.py`），排查时要知道是哪一层报的错；因此每层错误都带 `[失败]` 前缀、具体原因与建议命令。
  2. `run.bat` 不转发 app 自身的选项（`--log-level`、`--init-config`、`--check` 等），那些仍走 `python app\main.py`；帮助文本与用户指南都写明了这一点。
  3. 真实缺陷（本阶段 Windows 验收发现，已修并补回归）：`scripts/launcher.py:358` 曾把「默认配置路径不存在」当成显式 `--config` 传下去，
     在全新目录里启动必失败（`app/main.py` 对显式 `--config` 缺失报错 exit 2）；`run.bat` 的 `endlocal ^& exit /b 3` 在括号块里把 `&` 变成字面参数，
     退出码 3 被吞成 0。两条分别由 `BuildArgvTest`（4 项）与 `WrapperExitCodeTest` 守住。

---

## 已收敛的待决策项

| 编号 | 原问题 | 结论 |
|---|---|---|
| P-001 | `sftp` 批处理对含空格路径的引用规则 | **作废** —— 不再使用批处理模式（D-011） |
| P-002 | `SSH_ASKPASS` 能否携带参数 | **已解决**：不用参数，改用「环境变量指向一个一次性秘密文件」的方案（决策 D-008）。实现 `app/ssh/askpass.py`；测试 `tests/unit/test_askpass.py`、`tests/security/test_credentials.py`、`tests/integration/test_password_auth.py` |
| P-003 | 是否改用 `ssh cat` 取真流式 | **作废** —— 协议层 `READ`/`WRITE` 已提供真流式（D-011） |
| P-004 | `ls -l` 解析失败的降级策略 | **作废** —— 不再有 `ls -l` 解析（D-011） |
| P-005 | 「首次连接取主机指纹」的实现方式 | **已实现**：`ssh-keyscan` 在 Windows OpenSSH 9.5p2 上**不可用**（见 `docs/reports/PHASE-02-SPIKE.md`），改为「临时 `UserKnownHostsFile` + `StrictHostKeyChecking=no` 连一次，读回 ssh 自己写入的 host key」（`app/ssh/known_hosts.py:221`；这里用 `no` 只是因为采集用的是一张**临时** known_hosts，与「静默接受新密钥」不是一回事，见 `known_hosts.py:22` 与 `:31` 的说明；用户可见的策略取值 `strict`/`accept-new` 由配置项 `host_key_policy` 决定）。实现 `app/ssh/known_hosts.py`（`collect_host_keys`）；测试 `tests/security/test_host_key.py`、`tests/unit/test_known_hosts.py` |
