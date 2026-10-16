# 阶段四报告：SSH 配置教程（v0.1.2）

## 一、报告信息

| 项目 | 内容 |
|---|---|
| 版本 | v0.1.2（维护与体验优化；版本号按任务书留到阶段七统一升级，当前程序自报 0.1.1） |
| 阶段 | 阶段四：编写全面的 SSH 配置教程 |
| 依据 | `dev_guide/0.1.2_.md` §4.1 ~ §4.3（§4.1 目标、§4.2 建议章节、§4.3 质量要求） |
| 日期 | 2026-10-17 |
| 基线提交 | `8222f06`（阶段 03 收尾：CHANGELOG 记入 v0.1.2 阶段三提交哈希），分支 `master` |
| 验证方式 | ① 教程关键步骤在 **Windows 11 客户端 + CentOS Stream 10 服务端**上逐条真实执行，命令与输出原文写进教程；② 新增 13 项一致性单测 `tests/unit/test_ssh_guide.py`；③ 四层自动化回归 `python scripts/test.py -v`；④ 教程内容与 `app/ssh/ssh_launcher.py`、`app/core/config.py`、`app/models/connection.py` 逐项对照 |
| 结论 | **通过**。§4.1 ~ §4.3 全部条款落地；J 节 13 类错误中 12 类在本环境复现出真实输出原文；7 项本机无法执行的内容已在教程中逐处标注【未验证】并在附录 B 汇总 |

## 二、阶段目标

任务书 §4.1 要求新增一份面向**两类读者**的 SSH 配置教程，§4.2 给出 A~L 章节建议，§4.3 给出 11 条质量要求并附加一条硬性核验要求。

| 条款 | 要求要点 | 落地位置 |
|---|---|---|
| §4.1 文件与位置 | 在 `docs/` 下新增 SSH 配置教程，文件名 `SSH_SETUP_GUIDE.md` | `docs/SSH_SETUP_GUIDE.md`（1627 行，新建） |
| §4.1 入口 | **在 `docs/USER_GUIDE.md` 中增加清晰的入口链接** | `docs/USER_GUIDE.md:696`（§11.2 排障段末尾）、`:826`（文档依据清单） |
| §4.1 读者 | 既覆盖从零开始的新用户，也帮助有经验的用户排查连接问题 | 前言「这份教程写给谁」`docs/SSH_SETUP_GUIDE.md:6`；零基础路径 = A/B/C/D/E/F/G 节；排障路径 = J/L 节 |
| §4.1 结构 | 循序渐进，并为 Windows、常见 Linux 发行版、不同虚拟化环境提供分支 | D 节 Windows 客户端、E 节 Linux 客户端、C 节服务端（RHEL 系 / Debian 系 / openSUSE）、H 节 VMware 与虚拟机网络 |
| §4.1 命令纪律 | 不得把仅适用于某个操作系统的命令写成通用命令；每条命令说明**执行位置、适用系统、所需权限、预期结果** | 每个代码块都有执行位置与适用系统说明；需要提权的命令标【需管理员】；裸 root/sudo 类命令标【未验证】；预期结果写在命令之后的判读段 |
| §4.2 章节完整性 | A 概念 ~ L 快速排查清单共 12 节，另可补附录 | A ~ L 全部齐备（行号见 §3.1），另加附录 A（AWFM 实际使用的 ssh 选项）与附录 B（验证记录） |
| §4.3 质量要求 | 11 条（准确性、可执行、命令标注、错误信息真实、安全建议、不臆造输出等） | 逐条对照见 §5.4 |
| §4.3 核验要求 | 「教程完成后，**至少在 Windows 客户端与真实 CentOS SSH 服务端环境中核验关键步骤**」 | 实测环境与逐项结果见 §5.3 与教程附录 B |

## 三、实际完成情况

### 3.1 教程正文（1627 行）

| 章节 | 起始行 | 内容要点 |
|---|---|---|
| 前言 | :6 / :11 / :20 / :33 / :41 | 读者定位；**先分清两个「端口」**（AWFM 服务端口 32579 vs SSH 22）；占位符约定 `<远端主机>` `<用户名>` `<端口>` `<私钥路径>`；状态标记【已实测】【需管理员】【未验证】；全文目录 |
| A. SSH 基本概念 | :60 | A.1~A.7：握手与认证、公钥私钥、known_hosts 与指纹、Sftp 子系统、**AWFM 不是 SSH 服务端**（AWFM 是 SSH 客户端） |
| B. 连接前的检查清单 | :147 | B.1~B.2：网络可达、端口开放、服务运行、账号可用；**虚拟机控制台登录 / Linux 本地登录 / 远程 SSH 三种登录不等价** |
| C. Linux SSH 服务端配置 | :189 | C.1~C.10：是否已安装、安装【需管理员】、服务状态与开机自启、监听端口、日志判读（`Accepted publickey` / `bad ownership or modes`）、关键配置项、改配置的安全流程、防火墙只放行需要的来源、SELinux【未验证】、发行版差异速查（RHEL 系 / Debian 系 / openSUSE） |
| D. Windows SSH 客户端 | :407 | D.1~D.8：检查是否已安装、安装【需管理员】、基础连接测试、`-v` 排查（实测片段）、`.ssh` 目录里有什么、私钥「权限过宽」问题（已实测）、**Windows 没有 `ssh-copy-id`**（改用 PowerShell 追加公钥，已实测）、ssh-agent（已实测） |
| E. Linux 客户端 | :593 | E.1~E.5：先确认客户端是否已安装、基础连接与常用选项、`~/.ssh` 与权限、用 `sftp`/`scp` 验证文件通道、发行版差异与其它客户端（含 macOS 一行，标【未验证】） |
| F. 密码认证 | :672 | F.1~F.7：何时用密码、服务端必须允许密码认证、客户端确认服务端接受哪些认证方式、密码错/账户不存在时的表现、密码使用纪律、AWFM 的密码模式、从密码迁移到密钥 |
| G. 密钥认证 | :771 | G.1~G.9：先找现成密钥、生成密钥对、口令与 ssh-agent、把公钥装到目标账户、**检查远端文件权限**（公钥认证失败的头号原因）、用 `-i` 测试登录、撤销与轮换、AWFM 的密钥模式、常见坑 |
| H. VMware、虚拟机网络与远程连接 | :943 | H.1~H.6：三种网络模式（NAT / 桥接 / Host-only）怎么选、虚拟机内确认自己的地址、宿主机确认「能不能到」、IP 变了怎么办（含改静态 IP 的风险提示）、克隆/重装后的主机密钥变化、控制台能登录而宿主机连不上的常见原因 |
| I. AWFM 连接配置 | :1071 | I.1~I.7：准备参数、首次连接核对主机指纹（不要跳过）、指纹变了怎么办、「允许写操作」是什么意思、连接失败后的排查顺序、**AWFM 实际使用的 ssh 选项**（可核对）、AWFM 支持与不支持（含 `ProxyJump` 对 AWFM 是否生效，标【未验证】） |
| J. 常见错误与诊断流程 | :1184 | J.1~J.16：每类错误固定五段——可能原因 / 检查顺序 / 命令 / 判读 / 安全修复方向；其中 12 类带本机复现的输出原文 |
| K. 安全建议与维护 | :1483 | K.1~K.7：最小权限、禁用 root 直登、密钥口令、known_hosts 维护、日志审计、更新策略 |
| L. 快速排查清单 | :1530 | 8 步顺序排查表（步骤 / 命令与执行位置 / 通过的标志 / 不通时去哪）+ L.1 一页速查（症状 → 先去查 → 一条命令） |
| 附录 A | :1561 | AWFM 实际发出的每一个 `ssh`/`sftp` 选项、取值来源与 askpass 环境变量表 |
| 附录 B | :1588 | 验证记录：环境表、已实测 10 项、未验证 7 项、与 AWFM 版本的对应关系 |

### 3.2 入口链接与索引

- `docs/USER_GUIDE.md:696`：在 §11.2「连不上怎么办」末尾加入教程入口段落，指向 J 节 16 类错误、L 节 8 步清单、状态标记约定与附录 B。
- `docs/USER_GUIDE.md:826`：文末「文档依据」清单补入 `docs/SSH_SETUP_GUIDE.md` 与 `docs/DECISIONS.md` D-021。
- `docs/_index.md:13`：登记 `SSH_SETUP_GUIDE.md`（用途 + 生成方式，注明实测范围与未验证项见附录 B）。

### 3.3 决策、CHANGELOG 与一致性测试

- 新增决策 **D-021**（`docs/DECISIONS.md:342`）：教程中未在本机实测的命令必须显式标注验证状态；备选方案与代价一并记录。`docs/ARCHITECTURE.md:146` 决策表补入该行。
- `docs/CHANGELOG.md`：:24 版本状态行、:40 阶段表拆出「四」为已完成、:43 起「新增」小节记录教程、证据、D-021 与 13 项单测。
- 新增 `tests/unit/test_ssh_guide.py`（13 项）并在 `tests/unit/_index.md:34` 登记，断言清单见 §5.2。

## 四、技术实现

### 4.1 关键难点：教程里的输出必须是真实跑出来的

任务书 §4.3 明确要求错误信息不得臆造。J 节要讲的十几类错误里，很多在「一切正常」的验证环境里不会自然出现。采取的办法是**制造一次性、可回收的失败条件**，让 ssh 自己吐出报错原文，然后原样抄进教程。所有一次性素材放在会话草稿目录 `.temp/j-errors/`，不提交。

| 教程小节 | 要复现的错误 | 复现手法 | 结果（原文已写入教程） |
|---|---|---|---|
| J.6 | 主机指纹变化 | 用一次性密钥对生成的假公钥（`dummy1.pub`）与真实 host key 混排，写进临时 `known_hosts_changed`（105 B），以 `UserKnownHostsFile` + `StrictHostKeyChecking=yes` 连接 | 完整 `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!` 横幅、`IT IS POSSIBLE THAT SOMEONE IS DOING SOMETHING NASTY!`、`The fingerprint for the ED25519 key sent by the remote host is SHA256:DqCdx8fTqzkkNm7wByDOmaYooNWJF5geaBL0n1WXTzQ.`、`Offending ED25519 key in <kh>:1`、`Host key verification failed.`（退出码 255） |
| J.16 | 算法协商失败 | 用 `-o HostKeyAlgorithms=` / `-o KexAlgorithms=` 把客户端算法强行收窄到服务端不支持的集合 | `Unable to negotiate with 192.168.170.128 port 22: no matching host key type found. Their offer: rsa-sha2-512,rsa-sha2-256,ecdsa-sha2-nistp256,ssh-ed25519`；以及 `no matching key exchange method found` 一例（含服务端完整 offer 列表） |
| J.14 | 认证尝试次数过多 | 一次连接挂 8 把一次性私钥（`-i` ×8 + `IdentitiesOnly=no`） | `Received disconnect from 192.168.170.128 port 22:2: Too many authentication failures` + `Disconnected from 192.168.170.128 port 22`（退出码 255） |
| J.10 | SFTP 子系统缺失/不可用 | `ssh -s <目标> no-such-subsystem` | `subsystem request failed on channel 0`（退出码 255，与 `sftp` 不可用时的报错形态一致） |
| J.15 | 连到了非 SSH 服务 | 本地起 `http-listen.py`（313 B）在 127.0.0.1:32587 上发一个 HTTP 响应再关闭，然后 ssh 连它 | `Connection closed by 127.0.0.1 port 32587`（退出码 255） |
| J.7 | 私钥权限过于开放 | Linux 侧把私钥改成 0644；Windows 侧放宽 ACL | Linux：`Permissions 0644 for '…' are too open.` + `This private key will be ignored.` + `Load key "…": bad permissions` + `Permission denied (publickey,gssapi-keyex,gssapi-with-mic,password).`；Windows：`Bad permissions. Try removing permissions for user: NT AUTHORITY\Authenticated Users (S-1-5-11) on file …`；修复 `icacls … /inheritance:r` + `icacls … /grant:r "$($env:USERNAME):F"` 后登录成功 |
| G.5（现象体现在 C.5 的服务端日志） | `authorized_keys` 权限违规 | 把远端 `authorized_keys` 权限改坏 | 客户端 `Permission denied (publickey…)`，服务端日志 `Authentication refused: bad ownership or modes for file …` |

补充经验（写在教程 D 节与 I 节）：PowerShell 里调用 `ssh` 时，参数必须用数组透传（`& ssh @argsArr`），否则引号、空格与逗号会被 PowerShell 先解释一遍；ssh 的错误走 stderr，在 PowerShell 里显示为 `NativeCommandError` 红字，**这是显示现象，不是命令失败**——退出码才是判据。

### 4.2 三种状态标记与占位符约定（D-021）

- 【已实测】：在本次验证环境里真实执行过，教程给出的是真实输出。
- 【需管理员】：命令本身正确，但需要提权；教程给出应看到的结果，不伪造终端输出。
- 【未验证】：本机没有对应环境（无 sudo、SELinux 关闭、firewalld 未运行、无 macOS、未搭跳板机、未改虚拟机网络），命令来自官方文档或通用做法，**不得当作结论**。
- 占位符：正文示例一律用 `<远端主机>` `<用户名>` `<端口>` `<私钥路径>`；只有附录 B 与 J 节的「真实输出原文」保留验证环境的实际 IP 与指纹（作为可核对的历史记录）。

### 4.3 一致性单测怎么钉住文档

`tests/unit/test_ssh_guide.py` 不做文本比对，而是**从代码里取事实、到教程里找对应**：

- 用 `ssh_launcher.build_sftp_command` 在密码模式与密钥模式下真实构造命令，解析出所有 `-o` 键名与 `-i`，逐个断言其出现在附录 A；反过来附录 A 记录的 `BatchMode` / `NumberOfPasswordPrompts` 两种模式都必须说明。
- 附录 A 里的 `ConnectTimeout` / `ServerAliveInterval` 数值必须等于 `app/core/config.py` 的 `DEFAULTS["ssh"]`，known_hosts 默认路径一致，默认端口必须等于 `DEFAULTS["server"]["port"]`。
- `app/models/connection.py` 的 `AUTH_METHODS` 必须与 F（密码）、G（密钥）两节的存在对应。
- 纪律断言：必须含【已实测】【未验证】标记；不得出现任何私钥正文、`TODO`/`TBD`/`FIXME`/`待补`、未渲染的 HTML 注释。

这样，只要 ssh 选项名、默认值、认证方式或端口在代码里变了而教程没跟上，单测就会失败。

### 4.4 关于一次性脚本

复现实验用的临时脚本与密钥（`.temp/j-errors/` 下的 `dummy1`~`dummy8` 及其 `.pub`、`http-listen.py`、`known_hosts_changed`）是会话草稿，**不提交**；教程正文不依赖它们——每条命令都是读者可以照抄的完整命令。

## 五、测试结果

### 5.1 四层自动化测试

| 层 | 数量 | 结果 | 耗时 |
|---|---|---|---|
| unit | 579 | OK（1 项按平台跳过：`SignalTest` 在 Windows 上跳过，在 Linux（WSL2 Ubuntu 24.04）上真跑通过——阶段三已核验） | 4.11 s |
| integration | 118 | OK | 278.38 s |
| security | 82 | OK | 466.72 s |
| e2e | 32 | OK | 187.12 s |
| 合计 | 811 | 0 失败 / 0 错误 / 1 跳过 | 936.33 s |

`python scripts/test.py -v` 退出码 0，末行「全部通过」。unit 由阶段三的 566 增至 **579**（新增 `tests/unit/test_ssh_guide.py` 13 项）；integration / security / e2e 的数量与阶段三一致（118 / 82 / 32）。本阶段**未改动** `app/`、`frontend/`、`scripts/` 任何一行代码，因此后三层的作用是确认「只加文档与一个单测」没有意外影响既有行为。

### 5.2 教程一致性单测（13 项）

`python -m unittest tests.unit.test_ssh_guide -v` → `Ran 13 tests / OK`（0.013 s）：

| 测试类 | 断言的要点 |
|---|---|
| `GuidePresenceTests` | 教程存在且 > 800 行；A~L 12 个章节标题齐全且顺序正确；两个附录存在 |
| `GuideMatchesImplementationTests` | `build_sftp_command` 发出的每个 `-o` 键都在附录 A；密码/密钥两种模式的差异选项都已记录；`ConnectTimeout`/`ServerAliveInterval` 数值 = 代码默认值；known_hosts 默认路径一致；`AUTH_METHODS` = {key, password} 且 F/G 两节存在；默认端口 32579 出现在教程中；教程明确写了「AWFM 不是 SSH 服务端」 |
| `GuideDisciplineTests` | 含【已实测】【未验证】标记；附录 B 必须提到 sudo / SELinux / firewalld / macOS 四类未验证环境；不得出现私钥正文或 `TODO`/`TBD`/`FIXME`/`待补`、HTML 注释 |

### 5.3 教程关键步骤的真实核验（§4.3 最后一条）

核验环境（教程附录 B 同）：Windows 11 家庭版 AMD64 + `OpenSSH_for_Windows_9.5p2`；服务端 CentOS Stream 10（`hadoop01`）+ `OpenSSH_9.9p1`（`openssh-server-9.9p1-32.el10.x86_64`）；VMware NAT `192.168.170.0/24`（虚拟机 `192.168.170.128`，宿主 VMnet8 `192.168.170.1`）。

| 核验项 | 对应小节 | 结果 |
|---|---|---|
| 客户端版本与路径 | D.1 | `ssh -V` 与 `Get-Command ssh` 输出与教程一致 |
| 服务端状态与监听 | C.3 / C.4 | `active` / `enabled`；监听 `0.0.0.0:22` 与 `[::]:22` |
| 服务端日志判读 | C.5 | 捕获 `Accepted publickey …`、`Authentication refused: bad ownership or modes …` |
| 主机指纹双端一致 | I.2 | RSA / ECDSA / ED25519 三种主机密钥在双端算出同一 `SHA256:` 串 |
| 密钥认证端到端 | G.2 / G.4 / G.6 | 生成密钥 → 追加公钥 → `ssh -i` 登录成功；撤销后同一把私钥立即失效 |
| Windows 侧安装公钥 | D.7 | `Get-Content … \| ssh … "cat >> …"` 成功且登录成功 |
| 私钥权限两种形态与修复 | J.7 | Linux 0644 与 Windows ACL 放宽两种报错均复现；Windows 修复命令实测有效 |
| `authorized_keys` 权限违规 | G.5 / C.5 | 客户端拒绝，服务端日志给出 `bad ownership or modes` |
| `sftp` 子系统可用 | E.4 | `pwd` / `ls` 可用，退出码 0 |
| 13 类错误文本 | J 节 | 12 类在本环境复现；`No route to host` 未复现（已在教程中标注） |

### 5.4 任务书条款逐条对照

| 条款 | 判定 | 证据 |
|---|---|---|
| §4.1 文件名与位置 | ✅ | `docs/SSH_SETUP_GUIDE.md`，1627 行 |
| §4.1 `docs/USER_GUIDE.md` 入口链接 | ✅ | `docs/USER_GUIDE.md:696`、`:826` |
| §4.1 覆盖零基础与排障两类读者 | ✅ | 前言读者定位 + A/B/C/D/E/F/G 入门路径 + J/L 排障路径 |
| §4.1 循序渐进、含系统与虚拟化分支 | ✅ | D/E/C 三组系统分支 + H 节 VMware 三种网络模式 + 快照/IP 变化分支 |
| §4.1 命令不得跨系统混用、四要素说明 | ✅ | 每个代码块标注执行位置与适用系统；【需管理员】标记；预期结果写入判读段 |
| §4.2 A~L 章节完整 | ✅ | §3.1 行号表（A :60 … L :1530），另加两个附录 |
| §4.3 质量要求 11 条 | ✅ | 不臆造输出（§4.1 的复现表）、安全建议（K 节）、可执行命令、错误原文、状态标记（D-021）等逐条落地 |
| §4.3 在 Windows 客户端 + 真实 CentOS 服务端核验关键步骤 | ✅ | §5.3 十项核验；附录 B 记录环境与逐项结果 |

## 六、问题与风险

### 6.1 过程中解决与处理的问题

1. **「教程里的输出必须真实」与「不能拿验证机冒险」的冲突**：J.6 指纹变化如果直接改真实 `known_hosts`，会破坏后续所有验证。改为用一次性 `UserKnownHostsFile` 指向临时文件，报错一样、环境不受影响。
2. **普通账户没有免密 sudo**：所有安装、启动服务、改配置、`sshd -T`、防火墙放行类命令一律不臆造输出，标【需管理员】/【未验证】，只写「执行后应看到什么」。
3. **J.16 算法协商在本机默认配置下不会失败**：现代客户端与服务端算法集重叠，直接连永远成功。改为用 `HostKeyAlgorithms` / `KexAlgorithms` 强行收窄到服务端不支持的算法，得到真实的 `no matching … Their offer: …` 报错。
4. **教程与代码漂移**：教程附录 A 与 I 节描述的是 AWFM 的实际行为，代码一改教程就会过期。用 13 项一致性单测把选项名、默认值、认证方式、端口钉住（§4.3），其余靠 D-021 的维护约定。
5. **PowerShell 调用 ssh 的两个坑**：参数引号被 PowerShell 先解释（改用 `&` + 数组透传）；ssh 的错误输出在 PowerShell 里显示为 `NativeCommandError` 红字（用退出码判据）。两点都已写进教程 D 节。

### 6.2 未验证清单（教程附录 B 原文，逐处已标注【未验证】）

| 内容 | 原因 |
|---|---|
| 所有 `sudo` / `root` 类命令（安装、启动服务、改配置、`sshd -T`、防火墙放行） | 验证环境的普通账户没有免密 `sudo` |
| SELinux 开启时的端口标签与文件上下文 | 该虚拟机 SELinux 为 `Disabled` |
| firewalld 运行中的放行规则 | 该虚拟机 firewalld 未运行 |
| Windows 安装 OpenSSH 客户端、启动 ssh-agent 服务 | 需要管理员权限 |
| macOS 客户端与 `ssh-add --apple-use-keychain` | 无 macOS 环境 |
| 静态 IP / DHCP 保留的具体操作步骤 | 需要改动虚拟机网络配置（高风险，未执行） |
| `~/.ssh/config` 里的 `ProxyJump` 对 AWFM 是否生效（I.7） | 未搭跳板机环境 |

### 6.3 风险与缓解

1. **发行版分支只对一个发行版做过端到端实测**：C 节的 RHEL 系在 CentOS Stream 10 上真跑过，Debian 系与 openSUSE 的命令来自官方文档，未实测 → 已在 C 节逐条标注；属于环境缺失而非能力缺失。
2. **验证环境相关的事实会随机器变化**：IP、网段、指纹只出现在附录 B 与 J 的「真实输出原文」中，正文示例统一用占位符，读者照抄不会踩到别人的环境。
3. **SELinux / firewalld / macOS / sudo 四类内容与验证环境不同**：若读者环境与验证环境不同，教程给出的可能是「应然」而非「实然」→ 已标【未验证】，阶段五的安全检查会复核 K 节安全建议与这两处的命令。
4. **文档过期**：`tests/unit/test_ssh_guide.py` 只能钉住结构化事实（选项、默认值、认证方式、端口），J 节的错误文本与 I 节的界面描述仍可能过期 → 依赖 D-021 的约定：改 `app/ssh/ssh_launcher.py` 或连接表单时同步核对教程 I 节与附录 A。

## 七、文档与交付物

| 文件 | 变更 | 说明 |
|---|---|---|
| `docs/SSH_SETUP_GUIDE.md` | 新增 1627 行 | 本阶段主交付物：A~L 12 节 + 附录 A/B |
| `docs/USER_GUIDE.md` | :696、:826 | 教程入口链接与文档依据（任务书 §4.1 明确要求） |
| `docs/_index.md` | :13 | 登记教程文件（用途 + 生成方式 + 实测范围） |
| `docs/DECISIONS.md` | :342 | 新增 D-021（未实测命令必须标注验证状态） |
| `docs/ARCHITECTURE.md` | :146 | 决策表补 D-021 行 |
| `docs/CHANGELOG.md` | :24、:40、:43 | v0.1.2 状态行、阶段表「四」置为已完成、「新增」小节 |
| `tests/unit/test_ssh_guide.py` | 新增 13 项 | 教程与实现的一致性测试 |
| `tests/unit/_index.md` | :34 | 登记新测试文件 |
| `docs/reports/PHASE-04-SSH-GUIDE-v012.md` | 新增 | 本报告 |
| `docs/reports/_index.md` | 追加一行 | 阶段报告索引登记 |

不提交：`.temp/j-errors/`（一次性复现素材与临时密钥）；阶段四**未改动** `app/`、`frontend/`、`scripts/` 任何一行代码。

## 八、阶段结论

- 任务书 §4.1 ~ §4.3 的全部条款已落地并各有可核对的位置（§5.4 逐条对照）。
- 教程的质量关键点在于**错误信息是真的**：J 节 16 类错误中 12 类带本机复现的输出原文，读者排障时可以直接对照字符串；剩下 4 类（`No route to host` 与三类需特定环境的前置条件）已明确标注。
- 7 项未验证内容集中在权限与异构环境（sudo、SELinux、firewalld、Windows 管理员操作、macOS、虚拟机网络改动、跳板机），是环境缺失而非结论缺失，已在教程中逐处标注并在附录 B 汇总（决策 D-021）。
- 本阶段不改代码，四层回归的作用是确认文档与测试的新增没有意外影响既有功能；结果见 §5.1。
- **允许进入阶段五（回归测试与安全检查）**：阶段五将覆盖全量四层回归、安全自查，并复核本阶段标注的 SELinux / firewalld 相关内容。
