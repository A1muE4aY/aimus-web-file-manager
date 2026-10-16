# AWFM SSH 配置教程

> 适用版本：**AWFM v0.1.2**（2026-10-17 发布；启动横幅与 `run.bat status` 显示同一个版本号）。
> 本文写于 2026-10-17，验证环境：Windows 11 客户端 + CentOS Stream 10 服务端（见文末「附录 B 验证记录」）。

## 这份教程写给谁

- **从零开始**：刚装好一台 Linux 机器（物理机、虚拟机或云主机），想让 AWFM 连上去管理文件。
- **已经用过 SSH**：终端里能连，但 AWFM 连不上或行为不符合预期，需要按现象定位。

## 先分清两个「端口」，不要混淆

| 端口 | 默认值 | 谁在监听 | 说明 |
|---|---|---|---|
| **AWFM 网页端口** | `32579` | 本机的 AWFM 服务（Python） | 浏览器访问 `http://127.0.0.1:32579/`；只在你自己这台机器上监听 |
| **SSH 端口** | `22` | **远端**主机的 sshd | AWFM 作为客户端去连它；本文绝大部分内容都在讲这个端口 |

本教程中出现的 `32579` 都指网页端口，出现的 `22` 都指 SSH 端口。两者的排错方式完全不同：网页打不开要查本机要不要重启 AWFM，SSH 连不上要查远端主机。

## 占位符约定

本文用尖括号表示「你要替换成自己环境里的值」。示例里的真实值（`192.168.170.128`、`aimu`、`hadoop01`、指纹 `SHA256:…`）只是本次验证用的机器，**不是**你的环境，也**不会**是固定值：

| 占位符 | 含义 | 例子 |
|---|---|---|
| `<远端主机>` | 远端 IP 或域名 | `192.168.170.128`、`vm.example.lan` |
| `<用户名>` | 远端登录账户 | `aimu`、`deploy` |
| `<端口>` | 远端 SSH 端口，未改动过就是 `22` | `22`、`2222` |
| `<私钥路径>` | 本机上私钥文件的完整路径 | Windows：`C:\Users\you\.ssh\id_ed25519`；Linux：`~/.ssh/id_ed25519` |

命令里的提示符：`$` 表示**远端 Linux 上的普通用户**，`#` 表示**远端 root**（或 `sudo`），`PS>` 表示**本机 Windows PowerShell**，`cmd>` 表示 **Windows 命令提示符**。命令块右上角会注明执行位置。

## 状态标记

教程中每条关键命令后面都可能有这三种标记之一：

- **【已实测】**：本文作者在 Windows 11 + CentOS Stream 10 上真实执行过，输出见正文或附录 B。
- **【需管理员】**：需要 `root` / `sudo` / Windows 管理员权限。本次验证环境里普通用户没有免密 sudo，**这类命令未逐条实测**，已按通用发行版行为写明，请以 `man` 与你的发行版文档为准。
- **【未验证】**：本次环境不具备条件（例如 SELinux 处于 Disabled、firewalld 未运行、macOS 缺失），只给出方向，不当成已验证结论。

## 目录

- [A. SSH 基本概念](#a-ssh-基本概念)
- [B. 连接前的检查清单](#b-连接前的检查清单)
- [C. Linux SSH 服务端配置](#c-linux-ssh-服务端配置)
- [D. Windows SSH 客户端](#d-windows-ssh-客户端)
- [E. Linux SSH 客户端](#e-linux-ssh-客户端)
- [F. 密码认证](#f-密码认证)
- [G. 密钥认证](#g-密钥认证)
- [H. VMware、虚拟机网络与远程连接](#h-vmware虚拟机网络与远程连接)
- [I. AWFM 连接配置](#i-awfm-连接配置)
- [J. 常见错误与诊断流程](#j-常见错误与诊断流程)
- [K. 安全建议与维护](#k-安全建议与维护)
- [L. 快速排查清单](#l-快速排查清单)
- [附录 A：AWFM 实际使用的 ssh 选项](#附录-aawfm-实际使用的-ssh-选项)
- [附录 B：验证记录](#附录-b验证记录)

---

## A. SSH 基本概念

### A.1 客户端与服务端是两个程序

SSH 是「一端发起、一端等待」的协议：

| 角色 | 程序 | 在哪 | 干什么 |
|---|---|---|---|
| **服务端**（sshd） | `sshd` | **远端**主机上，通常开机自启、监听 22 端口 | 接受连接、验证身份、提供 shell 与 SFTP 子系统 |
| **客户端** | `ssh`、`sftp`、`scp` | **你操作的这台机器**上 | 发起连接、把命令或文件操作送到对端 |

AWFM 用的是**系统自带的 OpenSSH 客户端**（决策 D-003/D-011：不引入第三方 SSH 库）。它自己不是服务端，见 A.7。

### A.2 主机名、IP、端口、用户名、认证方式

一次连接由这五样东西描述，缺一不可：

| 概念 | 含义 | 常见误解 |
|---|---|---|
| **主机名 / IP** | 你要连的机器在哪 | 「虚拟机能开机」不等于「这个 IP 是它」——NAT 下 IP 由 DHCP 分配，会变（见 H.6） |
| **端口** | 服务端 sshd 在哪个端口等待 | 改了 `Port` 之后，`ssh <用户名>@<远端主机>` 会连到 22 而失败，必须加 `-p` |
| **用户名** | 用**远端**的哪个账户登录 | 不是本机 Windows 账户名；留空时 ssh 会用本机当前用户名去试 |
| **认证方式** | 用密码，还是用密钥 | 服务端可能只允许其中一种 |
| **主机密钥** | 服务端的身份凭证，用来确认「你连的确实是它」 | 与「你的登录凭证」是两回事，见 A.4 |

### A.3 公钥与私钥

密钥认证用的是一对数学上配对的密钥：

- **私钥**：只存在**客户端**，是你的身份证明，等价于密码，绝不外传、绝不写进配置文件或聊天记录。
- **公钥**：可以随便传播，它被追加到**远端** `~/.ssh/authorized_keys` 里，表示「持有对应私钥的人可以登录」。

登录时的过程是「挑战—应答」：服务端发一个只有对应私钥才能正确回答的挑战，客户端用私钥回答。**私钥本身从不发送给服务端**。

### A.4 主机指纹

第一次连接某台机器时，服务端会先出示它的**主机公钥**。客户端把这个公钥的哈希（指纹）算出来给你看：

```
256 SHA256:DqCdx8fTqzkkNm7wByDOmaYooNWJF5geaBL0n1WXTzQ no comment (ED25519)
```

你确认之后，这个公钥被记进 `known_hosts` 文件。以后每次连接都会比对：

- 指纹**一致** → 静默通过。
- 指纹**变了** → 说明对端换了密钥（重装系统、换机器）**或者**有人在中间冒充（中间人攻击）。此时必须停下来查清原因，**不要**为了「先连上」而直接信任新指纹。

AWFM 默认策略是 `strict`：只接受已经记录在案的主机密钥；首次连接必须在界面里人工核对，指纹变化时不自动接受（见 I.2、I.3）。

### A.5 AWFM 如何通过系统 OpenSSH 工作

AWFM 的后端把连接配置翻译成一条 `ssh` 命令，并为每个连接启动一个子进程，用它承载 **SFTP 子系统**：

```
ssh -p 22 -o UserKnownHostsFile=<项目 data/known_hosts> … <用户名>@<远端主机> -s sftp
```

要点：

- 信任库用的是**项目自己的** `data/known_hosts`，不是你的 `%USERPROFILE%\.ssh\known_hosts`，所以 AWFM 的「首次确认」不会被你终端里的旧记录绕过。
- 密钥模式下加 `-i <私钥路径>` 与 `IdentitiesOnly=yes`：只试你指定的那把私钥，不会拿 agent 里其它密钥去撞（避免触发对端的失败次数限制）。
- 密码模式下密码通过 `SSH_ASKPASS` 辅助程序、经一个临时文件交给 `ssh` 子进程，**不进命令行、不进环境变量**，用完即删。

完整选项表见 [附录 A](#附录-aawfm-实际使用的-ssh-选项)。

### A.6 「SSH 端口是通的」不等于「能登录」

这是最容易误判的一条。下面三件事是**依次**发生的，任何一步失败，最终看到的都是「连不上」：

1. **网络可达**：包能到那台机器。
2. **端口可达**：sshd 正在 22 端口监听，且防火墙放行。
3. **认证成功**：用户名存在、认证方式被允许、凭证正确、权限合规。

实测（本次验证环境）：`AWFM 服务端`端口 22 可达，但把 AWFM 的私钥路径指向一个不存在的文件时，服务端回复的是认证失败而不是连接失败——**端口通与认证过是两件事**。

### A.7 AWFM 不是 SSH 服务端

明确边界，避免误解：

- AWFM **不会**替你安装、启动或配置远端的 `sshd`。
- AWFM **不会**修改远端 `sshd_config`、**不会**动远端防火墙。
- AWFM **不会**替你生成或上传私钥；密钥的生成与安装由你在终端里完成（本文 G 节），AWFM 只负责**使用**已经可用的密钥或密码。

换句话说：**先在终端里把 SSH 调通，再回到 AWFM 里填配置**。这是最短的路径。

---

## B. 连接前的检查清单

按顺序确认下面 7 项。任意一项「不确定」就先把它弄清楚，不要跳过。

| # | 要确认的事 | 怎么确认（在哪执行） | 通过的标准 |
|---|---|---|---|
| 1 | 远端主机正在运行 | 虚拟机窗口 / 云控制台（本机） | 能看到登录提示符或系统在跑 |
| 2 | 知道正确的 IP 或主机名 | 远端执行 `hostname -I`、`ip -4 addr`（远端） | 得到一个能 ping 通的地址 |
| 3 | 知道目标登录用户名 | 远端执行 `whoami`、`id`（远端） | 有一个存在的账户名 |
| 4 | SSH 服务端已安装并运行 | 远端执行 `systemctl is-active sshd`（远端） | 输出 `active` |
| 5 | 防火墙与路由允许访问 SSH 端口 | 远端 `ss -ltn`，本机 `Test-NetConnection -Port 22` | 端口可达（见 C.4、H.4） |
| 6 | 客户端有可用的 SSH 工具 | 本机 `ssh -V`、`where ssh`（本机） | 打印版本号与路径 |
| 7 | 决定用密码还是密钥 | 与远端管理员确认（或远端 `sshd -T`，需 root） | 至少一种方式可用 |

### B.1 三种「登录」不能默认等价

排错时最常见的误会是把下面三件事当成一件事：

| 登录方式 | 走什么通道 | 能证明什么 |
|---|---|---|
| **虚拟机控制台登录**（VMware 窗口里敲用户名密码） | 虚拟显示器 / 键盘，与网络无关 | 证明系统在运行、账户存在。**完全不能**证明 SSH 可用 |
| **Linux 本地账户登录**（已登录的终端里 `su - <用户名>`） | 本机 PAM | 证明账户与密码在本机可用。**不能**证明 sshd 允许该账户远程登录 |
| **远程 SSH 登录** | 网络 → sshd → 认证 → 会话 | 这才是 AWFM 要走的路 |

一台机器可以「控制台登录正常、SSH 完全连不上」——例如 sshd 没启动，或者 sshd 只监听内网地址，或者防火墙只放行了别的端口。

### B.2 最短路径建议

在终端里先跑通这一条，再去 AWFM 里填：

```bash
# 远端 Linux 上确认 sshd 状态
systemctl is-active sshd
```

```powershell
# 本机 Windows PowerShell：先直接连一次
ssh -p <端口> <用户名>@<远端主机>
```

能进到 shell，说明网络、端口、认证三关都过了，只是 AWFM 里的配置还没填对；AWFM 连不上而这条能连上，问题一定在 AWFM 的配置项（见 I.5）。

## C. Linux SSH 服务端配置

> 这一节的命令都在**远端 Linux** 上执行。带 `#` 提示符或标注【需管理员】的必须用 `root` 或 `sudo`。

### C.1 先确认 sshd 是否已安装

```bash
$ rpm -q openssh-server          # RHEL / CentOS / Fedora / Rocky / AlmaLinux
openssh-server-9.9p1-32.el10.x86_64        # ← 已安装时会打印版本
$ dpkg -l | grep -i openssh-server         # Ubuntu / Debian
$ pacman -Q openssh                        # Arch
$ apk info -e openssh                      # Alpine
$ command -v sshd                          # 通用：能打印路径就是装了
/usr/sbin/sshd
```

【已实测】CentOS Stream 10 上 `rpm -q openssh-server` 输出 `openssh-server-9.9p1-32.el10.x86_64`，`command -v sshd` 输出 `/usr/sbin/sshd`。

如果包不存在，说明系统里没有 SSH 服务端——**这正是「虚拟机控制台能登录、但远程连不上」的最常见原因**。

### C.2 安装（【需管理员】，本环境未以 root 实测）

```bash
# RHEL 系
sudo dnf install -y openssh-server
# Debian / Ubuntu
sudo apt update && sudo apt install -y openssh-server
# Arch
sudo pacman -S --noconfirm openssh
# Alpine
sudo apk add openssh openssh-server
```

安装后服务通常不会自动启动（Debian 系的 `openssh-server` 包会尝试启动），按 C.3 确认。

### C.3 服务状态、启动与开机自启

```bash
$ systemctl is-active sshd        # active
$ systemctl is-enabled sshd       # enabled
$ systemctl status sshd --no-pager | head -10
● sshd.service - OpenSSH server daemon
     Loaded: loaded (/usr/lib/systemd/system/sshd.service; enabled; preset: enabled)
     Active: active (running) since Sat 2026-10-17 00:49:44 CST; 2h 52min ago
   Main PID: 1152 (sshd)
       Docs: man:sshd(8)
```

【已实测】上面四行是 CentOS Stream 10 的真实输出（`active` / `enabled`）。

**单位名不一样**：RHEL 系是 `sshd`，**Debian / Ubuntu 是 `ssh`**（`systemctl status ssh`）。写脚本时别写死。

启动并设为开机自启（【需管理员】）：

```bash
sudo systemctl enable --now sshd      # Debian/Ubuntu 用 ssh
```

没有 systemd 的环境（容器、老发行版、某些 WSL）：`sudo service sshd start`，或直接前台跑 `/usr/sbin/sshd -D -e` 看实时日志。

### C.4 检查监听端口

```bash
$ ss -ltn | grep :22
LISTEN 0      128          0.0.0.0:22        0.0.0.0:*
LISTEN 0      128             [::]:22           [::]:*
$ ss -ltnp | grep :22              # 加 p 能看到进程名，通常要权限
```

【已实测】上面两行是 CentOS Stream 10 的真实输出。判读方法：

| 看到的 | 含义 | 远端能不能连 |
|---|---|---|
| `0.0.0.0:22` 和 `[::]:22` | 所有网卡、IPv4+IPv6 | 能 |
| 只有 `127.0.0.1:22` | 只监听回环（`ListenAddress 127.0.0.1`） | **不能**，需要改回 `0.0.0.0` 或加一条 `ListenAddress` |
| 只有 `[::]:22` | 只监听 IPv6 | 看客户端；很多环境会回退失败 |
| `:2222` 之类 | 端口被改过 | 连接时必须 `-p 2222` |

老系统没有 `ss`：`netstat -ltn | grep :22`（包名 `net-tools`）。

### C.5 查看服务端日志

```bash
$ journalctl -u sshd -n 5 --no-pager
10月 17 03:40:14 hadoop01 sshd-session[4159]: Accepted publickey for aimu from 192.168.170.1 port 8742 ssh2: ED25519 SHA256:wmNiZ5RHmCgCe7Jp88VAezA9X28sVpi69yQXtysiSQg
10月 17 03:41:33 hadoop01 sshd-session[4483]: Authentication refused: bad ownership or modes for file /home/aimu/.ssh/authorized_keys
10月 17 03:41:33 hadoop01 sshd-session[4483]: Connection closed by authenticating user aimu 127.0.0.1 port 50484 [preauth]
```

【已实测】以上三条都是本次验证中真实产生的日志。关键词对照：

| 关键词 | 含义 |
|---|---|
| `Accepted publickey for …` | 公钥认证成功。**后面那个 SHA256 是你客户端公钥的指纹**，可与本机 `ssh-keygen -lf <公钥>` 对照 |
| `Accepted password for …` | 密码认证成功 |
| `Failed password for …` | 密码错、账户不存在，或该账户被禁止登录 |
| `Authentication refused: bad ownership or modes for file …` | 文件权限/属主不满足 `StrictModes`，sshd 直接拒绝使用该文件（见 G.5） |
| `Connection closed by authenticating user … [preauth]` | 认证尚未完成连接就断了：客户端放弃、方法不匹配、或网络中断 |
| `Connection reset by peer` | 链路被中断（NAT 掉线、防火墙重置） |

注意：**OpenSSH 9.9 起每连接的进程名是 `sshd-session`**（不再统一叫 `sshd`），所以 `grep sshd` 反而更容易漏；`journalctl -u sshd` 按服务过滤最稳。

没有 journald 的系统【需管理员】：`sudo tail -n 50 /var/log/secure`（RHEL 系）或 `sudo tail -n 50 /var/log/auth.log`（Debian 系）。

### C.6 查看关键配置项（【需管理员】）

```bash
$ ls -l /etc/ssh/sshd_config
-rw-------. 1 root root 3674  9月18日 08:00 /etc/ssh/sshd_config
$ sudo sshd -T | grep -E '^(port|listenaddress|passwordauthentication|pubkeyauthentication|permitrootlogin|subsystem)'
```

【已实测的部分】CentOS Stream 10 上 `/etc/ssh/sshd_config` 是 `-rw------- root root`，**普通用户读不到**（会报 `权限不够`）；`/etc/ssh/sshd_config.d/` 同样不可读。也就是说「随手 cat 一下配置」在非 root 下做不到，必须用受控的管理渠道。

`sshd -T`（需 root）打印的是**最终生效值**，比看文件更可靠——因为 `sshd_config.d/*.conf` 与 `Match` 块会覆盖主文件里的行。

| 配置项 | 作用 | 常见值 / 注意 |
|---|---|---|
| `Port` | 监听端口 | `22`；改过之后客户端必须 `-p` |
| `ListenAddress` | 监听地址 | `0.0.0.0` / `::` / 具体地址；写 `127.0.0.1` 会让远端连不上 |
| `PasswordAuthentication` | 是否允许密码认证 | `yes` / `no` |
| `PubkeyAuthentication` | 是否允许公钥认证 | 默认 `yes` |
| `KbdInteractiveAuthentication` | 键盘交互（PAM）认证 | 与密码认证是**两回事**，AWFM 的密码模式两者都允许 |
| `PermitRootLogin` | 是否允许 root 直接登录 | 建议 `prohibit-password` 或 `no` |
| `AllowUsers` / `DenyUsers` | 账户白名单/黑名单 | 名单外的人连密码正确也会失败 |
| `Subsystem sftp …` | SFTP 子系统命令 | **AWFM 依赖它**；缺了会「能登录但列不出目录」 |
| `StrictModes` | 是否检查家目录/authorized_keys 权限 | 默认 `yes`，建议保持 |

### C.7 改配置的安全流程（【需管理员】）

改 SSH 很容易把自己锁在门外，按这 6 步走：

1. **先保住退路**：不要关掉当前可用的终端或 VMware 控制台窗口。
2. **备份**：

   ```bash
   sudo cp -a /etc/ssh/sshd_config /etc/ssh/sshd_config.bak-$(date +%F)
   ```

3. **只改需要的那一两行**。不要用别处抄来的整份配置**覆盖**：不同发行版的默认值差别很大，覆盖会连带改掉 `Subsystem`、`KexAlgorithms`、`Include` 等，症状往往离你原本想改的东西很远。
4. **语法检查**：

   ```bash
   sudo sshd -t          # 没有任何输出 = 通过
   ```

5. **平滑重载**（不会掐断已建立的会话）：

   ```bash
   sudo systemctl reload sshd      # Debian/Ubuntu 用 ssh
   ```

6. **立刻验证**：新开一个终端登录一次。失败就还原备份并再次 reload：

   ```bash
   sudo cp -a /etc/ssh/sshd_config.bak-<日期> /etc/ssh/sshd_config && sudo systemctl reload sshd
   ```

改端口、改认证方式、改登录策略**都属于高风险改动**：先在隔离环境验证，或者确保你能通过 VMware 控制台/云厂商 VNC 进去救回来。

### C.8 防火墙：只放行需要的端口和来源

先看状态：

```bash
$ sudo firewall-cmd --state          # RHEL 系；实测本机输出「not running」
$ sudo ufw status verbose            # Ubuntu / Debian
$ sudo nft list ruleset | head -20   # 底层规则（需 root；非 root 会报 Operation not permitted）
```

放行 SSH（示例给的是**限定来源网段**的写法，按需替换）：

```bash
# RHEL 系 / firewalld
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="192.168.170.0/24" service name="ssh" accept'
sudo firewall-cmd --reload

# Ubuntu / Debian / ufw
sudo ufw allow from 192.168.170.0/24 to any port 22 proto tcp
sudo ufw status numbered
```

判读：`sudo firewall-cmd --list-all` 能看到你加的富规则；`sudo ufw status` 里能看到 `22/tcp ALLOW 192.168.170.0/24`。

**不要**把「关掉防火墙」当成通用解法：

- `sudo systemctl stop firewalld` / `sudo ufw disable` 会把整台机器暴露在网络上；
- 只在完全隔离的实验网段、且明确知道后果时才可临时关闭，并**必须**记录恢复命令；
- 正确的方向是「开放**这一个端口**给**这一个网段**」。

【已实测的部分】本环境 firewalld 处于 `not running`、SELinux 为 `Disabled`，所以上面这些改动类命令**没有逐条执行**；状态查询类命令的输出见上。

### C.9 SELinux（本环境 Disabled，【未验证】）

```bash
$ getenforce        # 实测本机：Disabled
```

开启（`Enforcing`）的机器上，两类操作会被拦：

- **非标准端口**：`sudo semanage port -a -t ssh_port_t -p tcp <端口>`；
- **非默认位置的家目录 / 密钥目录**：用 `semanage fcontext` 定义标签后 `restorecon -Rv <目录>`。

**不要**用 `setenforce 0` 或改 `/etc/selinux/config` 作为解决办法——那是把整机安全策略关掉，代价远大于你要解决的问题。

### C.10 发行版差异速查

| | RHEL / CentOS / Fedora / Rocky | Debian / Ubuntu | Arch | Alpine |
|---|---|---|---|---|
| 安装 | `dnf install openssh-server` | `apt install openssh-server` | `pacman -S openssh` | `apk add openssh` |
| 服务名 | `sshd` | **`ssh`** | `sshd` | `sshd` |
| 主配置 | `/etc/ssh/sshd_config`（+ `sshd_config.d/`） | 同左 | 同左 | 同左 |
| 日志 | `journalctl -u sshd` / `/var/log/secure` | `journalctl -u ssh` / `/var/log/auth.log` | `journalctl -u sshd` | `logread` |
| 防火墙 | firewalld | ufw | iptables/nftables | iptables |
| SELinux/AppArmor | SELinux | AppArmor | 视配置 | 无 |

---

## D. Windows SSH 客户端

> 这一节的命令都在**本机 Windows** 上执行。`PS>` 是 PowerShell，`cmd>` 是命令提示符。

### D.1 检查是否已安装

```powershell
PS> ssh -V
OpenSSH_for_Windows_9.5p2, LibreSSL 3.8.2
PS> (Get-Command ssh).Source
C:\Windows\System32\OpenSSH\ssh.exe
```

```bat
cmd> where ssh
```

【已实测】本机输出就是上面三行（版本 9.5p2，路径 `C:\Windows\System32\OpenSSH\ssh.exe`）。

**注意**：`ssh -V` 把版本号写到 **stderr**（不是 stdout），所以 PowerShell 里可能显示成一行红字 `NativeCommandError`。那是 PowerShell 的显示习惯，不代表命令失败——看到版本号就是成功。

### D.2 没装怎么装（【需管理员】，未实测）

推荐用系统自带的可选功能（来源可信、随系统更新）：

```powershell
# 管理员 PowerShell
Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
```

图形界面路径：**设置 → 系统 → 可选功能 → 添加可选功能 → 搜索「OpenSSH 客户端」→ 安装**。

也可以从微软官方渠道装更新版本（例如 `winget install Microsoft.OpenSSH.Beta`）。**不要**到不知名网站下载 `ssh.exe` 或第三方 SSH 客户端：它是你全部凭证的必经之路，被替换的客户端可以把私钥和密码直接送走。

### D.3 基础连接测试

```powershell
PS> ssh <用户名>@<远端主机>                 # 默认端口 22
PS> ssh -p <端口> <用户名>@<远端主机>        # 端口不是 22 时
PS> ssh -i C:\Users\<你>\.ssh\id_ed25519 <用户名>@<远端主机>   # 指定私钥
```

首次连接会看到：

```
The authenticity of host '<远端主机> (<IP>)' can't be established.
ED25519 key fingerprint is SHA256:……
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

**先核对指纹再输 `yes`**：在远端机器上执行 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`，两边一致才继续（见 A.4、I.2）。

### D.4 用 `-v` 排查（实测片段）

```powershell
PS> ssh -v -i <私钥路径> <用户名>@<远端主机> "echo ok"
debug1: Connecting to 192.168.170.128 [192.168.170.128] port 22.
debug1: Local version string SSH-2.0-OpenSSH_for_Windows_9.5
debug1: Remote protocol version 2.0, remote software version OpenSSH_9.9
debug1: Authenticating to 192.168.170.128:22 as 'aimu'
debug1: Next authentication method: publickey
debug1: Offering public key: C:/Users/Aimu2/.ssh/id_ed25519 ED25519 SHA256:wmNiZ5RH…
debug1: Server accepts key: C:/Users/Aimu2/.ssh/id_ed25519 ED25519 SHA256:wmNiZ5RH…
debug1: Entering interactive session.
```

【已实测】以上是本次验证捕获的真实输出（指纹串已截断）。按顺序读这几行就能定位卡在哪一步：

| 最后停在 | 说明问题在 |
|---|---|
| `Connecting to …` 之后没有下文 | 网络/路由/主机不在线（见 J.2） |
| 有 `port 22` 但报 `Connection refused` | 端口没有人监听或防火墙拒绝（见 J.1） |
| `Authenticating to … as 'user'` 后失败 | 用户名或认证方式（见 J.4） |
| `Offering public key` 有、`Server accepts key` 没有 | 服务端不接受这把公钥（多半是公钥没装到目标账户，见 G.4） |
| 完全没有 `Offering public key` | 私钥路径不对/权限过宽被忽略（见 D.6、J.7） |

更详细用 `-vv`；要长期保存就先重定向：

```powershell
PS> ssh -vv <用户名>@<远端主机> 2> ssh-debug.log
```

把日志贴给别人之前先看一眼：里面有主机名、用户名和**公钥指纹**（不是私钥），但也可能带出内网结构信息。

### D.5 `%USERPROFILE%\.ssh` 目录里有什么

```powershell
PS> Get-ChildItem $env:USERPROFILE\.ssh -Force | Select-Object Name,Length
Name              Length
----              ------
id_ed25519           411          ← 私钥：没有扩展名，绝不外传
id_ed25519.pub       104          ← 公钥：可自由传播，装到远端 authorized_keys
known_hosts         1868          ← 你终端里连过的机器的主机密钥
known_hosts.old     1021          ← 上一个版本的备份（OpenSSH 自动维护）
```

【已实测】上面是本机真实目录内容。两点说明：

- 私钥**没有扩展名**；`.pub` 那个是公钥，内容以 `ssh-ed25519 AAAA…` 开头，可以随便看、随便发。
- 这里的 `known_hosts` 是**你终端**的信任库；AWFM 用的是项目目录下的 `data/known_hosts`，两者互不影响（这正是为了让 AWFM 的「首次确认」不被旧记录绕过）。

### D.6 Windows 上私钥的「权限过宽」问题（已实测）

OpenSSH 检查私钥文件的 ACL。**正确的 ACL**（本机实测，可正常登录）：

```powershell
PS> icacls C:\Users\<你>\.ssh\id_ed25519
C:\Users\<你>\.ssh\id_ed25519 BUILTIN\Administrators:(F)
                              NT AUTHORITY\SYSTEM:(F)
                              <本机名>\<你>:(M)
```

把私钥复制到一个继承权限较宽的目录（例如普通文件夹，带 `NT AUTHORITY\Authenticated Users:(I)(RX)`）后再用 `-i` 指定它，**实测报错**：

```
Bad permissions. Try removing permissions for user: NT AUTHORITY\Authenticated Users (S-1-5-11) on file …\awfm-open-key.
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@         WARNING: UNPROTECTED PRIVATE KEY FILE!          @
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
Permissions for '…' are too open.
It is required that your private key files are NOT accessible by others.
This private key will be ignored.
Load key "…": bad permissions
<用户名>@<远端主机>: Permission denied (publickey,gssapi-keyex,gssapi-with-mic,password).
```

**修复方式（实测有效）**：

```powershell
PS> icacls <私钥路径> /inheritance:r
PS> icacls <私钥路径> /grant:r "$($env:USERNAME):F"
PS> icacls <私钥路径>
<私钥路径> <本机名>\<你>:(F)
```

【已实测】按上面两条命令处理后，同一个私钥再次 `ssh -i` 登录成功（输出 `acl-fixed-login-ok`，退出码 0）。

要点：这个检查**只在用 `-i` 明确指定私钥时才会触发**。所以典型症状是「AWFM 里用这把密钥连不上，但把它放到 `~/.ssh` 下却好像没问题」——因为默认位置的文件往往是之前用 `ssh-keygen` 直接生成的，ACL 天然是收紧的。

### D.7 Windows **没有** `ssh-copy-id`（已实测）

```powershell
PS> (Get-Command ssh-copy-id -ErrorAction SilentlyContinue)
# 无输出 → 本机 OpenSSH 客户端不提供该脚本
```

【已实测】本机 `C:\Windows\System32\OpenSSH\` 下有 `ssh`、`sftp`、`scp`、`ssh-keygen`、`ssh-keyscan`、`ssh-add`，**没有** `ssh-copy-id`。用下面这条等价命令代替（**实测通过**）：

```powershell
PS> Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub | ssh <用户名>@<远端主机> "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && wc -l ~/.ssh/authorized_keys"
2 /home/aimu/.ssh/authorized_keys
```

随后用生成的私钥登录，实测成功输出 `windows-installed-key-login-ok`。

cmd.exe 里等价写法：

```bat
cmd> type "%USERPROFILE%\.ssh\id_ed25519.pub" | ssh <用户名>@<远端主机> "cat >> ~/.ssh/authorized_keys"
```

注意 `>>` 是**追加**：同一把公钥重复执行会写入多行（不影响登录，但会让文件变乱），清理见 G.7。

### D.8 ssh-agent（Windows 上默认没开，已实测）

```powershell
PS> Get-Service ssh-agent | Select-Object Status,StartType
Status  StartType
------  ---------
Stopped Disabled
PS> ssh-add -l
Error connecting to agent: No such file or directory
```

【已实测】本机 ssh-agent 服务处于 `Stopped / Disabled`，因此 `ssh-add -l` 直接报错（退出码 2）。**带口令的私钥**想免每次输入，需要开启它（【需管理员】，未实测）：

```powershell
# 管理员 PowerShell
Set-Service ssh-agent -StartupType Automatic
Start-Service ssh-agent
ssh-add $env:USERPROFILE\.ssh\id_ed25519
ssh-add -l
```

AWFM 里「私钥文件」留空时，就会走 agent 或 `~/.ssh` 下的默认密钥（界面提示原文：「可留空：留空时用 ssh-agent 里已加载的密钥，或 ~/.ssh 下的默认密钥。」）。

## E. Linux SSH 客户端

> 这一节的命令在**发起连接的 Linux 机器**上执行（可能是你的工作站，也可能是另一台服务器）。

### E.1 先确认客户端装没装

```bash
$ rpm -q openssh-clients          # RHEL / CentOS / Fedora / Rocky / AlmaLinux
openssh-clients-9.9p1-32.el10.x86_64
$ dpkg -l | grep -i openssh-client     # Ubuntu / Debian
$ command -v ssh sftp scp ssh-keygen ssh-copy-id ssh-keyscan ssh-add
/usr/bin/ssh
/usr/bin/sftp
/usr/bin/scp
/usr/bin/ssh-keygen
/usr/bin/ssh-copy-id
/usr/bin/ssh-keyscan
/usr/bin/ssh-add
```

【已实测】上面这份清单来自本环境的 CentOS Stream 10（`openssh-clients-9.9p1-32.el10.x86_64`）：**七个命令都存在，包含 `ssh-copy-id`**。这一点和 Windows 客户端不同（Windows 没有 `ssh-copy-id`，见 D.7）。

缺客户端时的安装命令（【需管理员】，未实测）：`sudo dnf install -y openssh-clients` / `sudo apt install -y openssh-client` / `sudo pacman -S openssh` / `sudo apk add openssh-client`。

### E.2 基础连接与常用选项

```bash
$ ssh <用户名>@<远端主机>                      # 默认 22 端口
$ ssh -p <端口> <用户名>@<远端主机>             # 非默认端口
$ ssh -i ~/.ssh/id_ed25519 <用户名>@<远端主机>  # 指定私钥
$ ssh -v <用户名>@<远端主机>                    # 打印连接过程（排障）
$ ssh -o ConnectTimeout=5 <用户名>@<远端主机>   # 明确超时，避免脚本里长时间挂住
```

Linux 客户端与 Windows 客户端是**同一套 OpenSSH**，选项、错误文本、`known_hosts` 机制都一致；差异只在路径（`~/.ssh` 而不是 `%USERPROFILE%\.ssh`）和权限模型（POSIX 位而不是 ACL）。

【已实测】本环境用 Linux 客户端做过完整的密钥登录（`ssh -i` + `BatchMode=yes` + `IdentitiesOnly=yes`），成功输出 `demo-login-ok` / `aimu` / `/home/aimu`。

### E.3 `~/.ssh` 与权限

```bash
$ ls -ld ~/.ssh ~/.ssh/authorized_keys
drwx------. 2 aimu aimu  71 10月 17 03:12 /home/aimu/.ssh
-rw-------. 1 aimu aimu 103 10月 17 03:41 /home/aimu/.ssh/authorized_keys
$ ls -ld ~
drwx------. 19 aimu aimu 4096 10月 17 03:11 /home/aimu
```

【已实测】以上是目标机上的真实权限：家目录 `700`、`.ssh` `700`、`authorized_keys` `600`，属主都是登录用户本人。这三项是公钥认证能成立的**前提**，被放宽任何一项都会失败（见 G.5）。

### E.4 用 `sftp` / `scp` 验证文件通道

能登录 ≠ 能传文件。AWFM 用的是 SFTP 子系统，所以要单独验一次：

```bash
$ sftp -i ~/.ssh/id_ed25519 <用户名>@<远端主机>      # 进入交互式 sftp
sftp> pwd
Remote working directory: /home/aimu
sftp> ls -l
sftp> bye

$ scp -i ~/.ssh/id_ed25519 ./local.txt <用户名>@<远端主机>:/tmp/    # 单向拷贝
```

【已实测】本环境用批处理方式跑过（`sftp -b -` 从标准输入读命令），真实输出：`sftp> pwd` → `Remote working directory: /home/aimu`，目录列表正常列出，退出码 0。

如果 `ssh` 能登录而 `sftp` 报错，问题在**服务端 `Subsystem sftp`**（C.6 的表格里那一行），不是认证。

### E.5 发行版差异与其它客户端

| 场景 | 说明 |
|---|---|
| 发行版差异 | 只有包名和默认算法版本不同，命令与选项一致 |
| Shell | bash / zsh / sh 下命令写法相同；`~` 由 shell 展开，脚本里引用路径建议写 `$HOME` |
| macOS | 自带 OpenSSH 客户端，路径同为 `~/.ssh`；`ssh-add` 有 `--apple-use-keychain` 选项可把口令存进钥匙串【未验证】 |
| Git Bash / MSYS2（Windows） | 提供类 POSIX 环境与 `ssh-copy-id` 脚本，路径仍是 Windows 侧的 `%USERPROFILE%\.ssh`【未验证】 |

---

## F. 密码认证

### F.1 什么时候用密码、什么时候别用

| 场景 | 建议 |
|---|---|
| 临时试用、快速验证「这台机器到底能不能登」 | 可以先用密码确认链路，再换密钥 |
| 长期连接、自动化、AWFM 里保存的连接 | **优先密钥**（见 G） |
| 服务器暴露在公网 | 尽量关闭密码认证，只用密钥 + 限制来源 |
| 密码是别人给你的、或你在猜测 | **不要试**（见 F.5） |

密码认证本身不是「不安全的技术」，它的问题在于：密码可被猜测、被复用、被记录在脚本和聊天记录里，而密钥不会离开你的机器。

### F.2 服务端必须允许密码认证

服务端相关的项（【需管理员】，本环境未以 root 实测）：

```bash
sudo sshd -T | grep -i -E 'passwordauthentication|kbdinteractiveauthentication|permitemptypasswords'
```

| 项 | 含义 |
|---|---|
| `PasswordAuthentication yes` | 允许直接提交密码 |
| `KbdInteractiveAuthentication yes` | 允许键盘交互（PAM）认证，很多发行版默认走这条路 |
| `PermitEmptyPasswords no` | 禁止空密码（默认值，保持 `no`） |

**两者是两回事**：有些服务器关了 `PasswordAuthentication` 但留了 `KbdInteractiveAuthentication`，仍然能用密码登录；反之亦然。这也是 AWFM 的密码模式同时允许 `password` 与 `keyboard-interactive` 两种方式的原因。

另外，账户本身要有可用密码。目标机上可以查（【需管理员】）：

```bash
sudo passwd -S <用户名>      # 第二列是 P（有密码）/ L（锁定）/ NP（无密码）
```

### F.3 在客户端确认服务端接受哪些认证方式

不需要读服务端配置，也能从客户端的失败信息里读出「服务端接受什么」：

```
Permission denied (publickey,gssapi-keyex,gssapi-with-mic,password).
```

括号里的列表就是服务端**愿意接受**的认证方式，按顺序尝试。判读：

| 括号里有没有 | 结论 |
|---|---|
| 有 `password` 或 `keyboard-interactive` | 服务端允许密码；此时再失败通常是密码错、账户被锁、或 `AllowUsers` 不含你 |
| 只有 `publickey` | 服务端**已关闭密码认证**，只能改用密钥 |
| 出现 `gssapi-*` | 是 Kerberos/GSSAPI 相关方式，普通环境会跳过，不用管 |

【已实测】本次故意把私钥权限放宽后登录失败，客户端真实输出就是上面那一行（含 4 种方式）；同时服务端日志给出的是权限问题，而不是「认证方式不允许」。

### F.4 密码错、账户不存在时的表现

服务端日志（C.5 讲过位置）：

```
sshd-session[4483]: Failed password for aimu from 192.168.170.1 port 8742 ssh2
```

客户端看到的**始终是同一句** `Permission denied (…,password).`。这是有意设计：不告诉试探者「这个账户存在但密码错」还是「这个账户根本不存在」。所以**不要**从客户端提示里推测账户是否存在，去服务端日志看。

### F.5 密码使用的安全纪律（重要）

**禁止**：

- 猜测密码、用字典或脚本批量尝试不同账户/密码——这属于未授权访问尝试，无论动机是什么；
- 把密码写进脚本、配置文件、命令行参数、Git 提交、聊天记录或截图；
- 在别人的机器上把密码交给第三方工具「代记」；
- 复用你在别处使用的重要密码。

**AWFM 的密码处理方式**（可以据此判断它是否可信）：

- 密码**不写入配置文件**：连接记录里根本没有密码字段（决策 D-014）；
- 密码**只在本机内存**中存在，通过系统 OpenSSH 的 `SSH_ASKPASS` 机制交给 `ssh` 进程，**不走命令行参数、不走环境变量**；
- 每次连接都要重新输入（界面提示原文：「密码不会写入配置文件，每次连接时输入。」）；
- 只允许尝试一次（`NumberOfPasswordPrompts=1`），不会反复索要、不会自动换方式试探；
- 浏览器与后端之间只传「连接参数」，密码由后端在本机向 `ssh` 提交（`app.js:204`：「浏览器只与本机服务通信，SSH 连接由后端建立，私钥与密码不会发送到浏览器。」）。

### F.6 在 AWFM 里使用密码模式

1. 「+ 新增」或选中连接 → 「编辑」；
2. 「认证方式」选**密码**；
3. 「私钥文件」留空即可（密码模式不使用它）；
4. 保存后点「浏览文件」，在弹出的输入框里填写密码（每次连接都填）。

密码模式的命令行形态（AWFM 内部）：`BatchMode=no` + `PreferredAuthentications=password,keyboard-interactive,publickey` + `NumberOfPasswordPrompts=1`。

如果你要连接的是**自动化场景**（定时任务、无人值守），密码模式并不合适：没有人输入密码就登录不了。这种情况请改用密钥（G），并在目标账户上限制这把密钥的权限。

### F.7 从密码迁移到密钥

推荐顺序：先用密码确认能登录 → 生成密钥（G.2）→ 把公钥装到目标账户（G.4）→ 用 `ssh -i` 验证密钥能登录（G.6）→ 在 AWFM 里把认证方式改成密钥（G.8）→ 确认无误后再考虑在服务端关闭密码认证（【需管理员】，高风险，务必留着控制台退路）。

**先确认密钥可用，再关密码**，顺序反过来会把自己锁在门外。

---

## G. 密钥认证

密钥认证解决的是「不传密码也能证明我是我」。一次生成、长期使用、可以随时撤销，是 AWFM 推荐的认证方式。

### G.1 先看有没有现成的密钥

```bash
# Linux / macOS
$ ls -l ~/.ssh
# Windows PowerShell
PS> Get-ChildItem $env:USERPROFILE\.ssh -Force
```

看到 `id_ed25519` + `id_ed25519.pub`（或 `id_rsa` + `id_rsa.pub`）就已经有密钥对了，可以直接跳到 G.4。

【已实测】本机 Windows 的 `%USERPROFILE%\.ssh` 里已有 `id_ed25519`（411 字节）+ `id_ed25519.pub`（104 字节），本次全部验证都是用它完成的。

### G.2 生成密钥对

```bash
$ ssh-keygen -t ed25519 -C "awfm-guide" -f ~/.ssh/awfm_key
Generating public/private ed25519 key pair.
Enter passphrase (empty for no passphrase):
Enter same passphrase again:
Your identification has been saved in /home/aimu/.ssh/awfm_key
Your public key has been saved in /home/aimu/.ssh/awfm_key.pub
The key fingerprint is:
SHA256:v+8Jn3VyuOF0sLuALGWPhkO5Y6AHXBqYyItTQkQA+M8 awfm-guide
```

要点：

- `-t ed25519` 是当前推荐算法；需要兼容很老的服务端时用 `-t rsa -b 3072`；`ecdsa` 一般不必选；
- `-C` 只是备注（写进公钥尾部，方便你日后认出这把钥匙），不影响功能；
- `-f` 指定文件名，不写则默认 `~/.ssh/id_ed25519`；文件名**不要**用 `.pub` 结尾；
- 口令（passphrase）**建议设置**：私钥文件被偷走时，没有口令就用不了。留空则不设口令（方便，但风险更高）；设置了口令后想免输入就用 ssh-agent（D.8 / G.3）；
- Windows 上如果要在一条命令里写完，`-N ""` 的空字符串引号容易被 PowerShell 吃掉，**直接交互式回车留空更省事**。

【已实测】本次用 `ssh-keygen -q -t ed25519 -N "" -C awfm-guide-demo -f <路径>` 生成，产出：私钥 411 字节、权限 `0600`，公钥 97 字节、权限 `0644`；指纹 `SHA256:v+8Jn3VyuOF0sLuALGWPhkO5Y6AHXBqYyItTQkQA+M8`。

### G.3 口令与 ssh-agent

```bash
# Linux / macOS：启动 agent 并加载（每次登录会话都要做一次，或在 shell 配置里做）
$ eval "$(ssh-agent -s)"
$ ssh-add ~/.ssh/awfm_key
Enter passphrase for /home/aimu/.ssh/awfm_key:
$ ssh-add -l
256 SHA256:v+8Jn3VyuOF0sLuALGWPhkO5Y6AHXBqYyItTQkQA+M8 /home/aimu/.ssh/awfm_key (ED25519)
```

```powershell
# Windows：先启用服务（需管理员），再加载
PS> Set-Service ssh-agent -StartupType Automatic; Start-Service ssh-agent
PS> ssh-add $env:USERPROFILE\.ssh\id_ed25519
PS> ssh-add -l
```

【已实测】本机 Windows 的 ssh-agent 默认是 `Stopped / Disabled`，直接 `ssh-add -l` 会报 `Error connecting to agent: No such file or directory`（退出码 2）—— 这是「没开服务」，不是密钥有问题。

### G.4 把公钥装到目标账户

**公钥**（`.pub`）装到远端 `~/.ssh/authorized_keys`；**私钥**永远留在本机。

方式一：`ssh-copy-id`（Linux/macOS 客户端，最简单）

```bash
$ ssh-copy-id -i ~/.ssh/awfm_key.pub <用户名>@<远端主机>
$ ssh-copy-id -i ~/.ssh/awfm_key.pub -p <端口> <用户名>@<远端主机>
```

【已实测】目标机 `/usr/bin/ssh-copy-id` 存在（`-h` 显示用法与 `-i/-p/-o` 选项）。**Windows 客户端没有这个脚本**，用方式二。

方式二：手工追加（任何客户端都能用；Windows 上的实测命令见 D.7）

```bash
$ cat ~/.ssh/awfm_key.pub | ssh <用户名>@<远端主机> "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && wc -l ~/.ssh/authorized_keys"
2 /home/aimu/.ssh/authorized_keys
```

【已实测】本次从 Windows 用等价命令追加，返回 `2`（追加后共 2 行），随后用对应私钥登录成功。

追加后**务必核对行数**：`wc -l ~/.ssh/authorized_keys`。`>>` 是追加，重复执行会写入重复行。

方式三：把公钥内容贴给管理员，由管理员代为加入（公钥可以公开，私钥不行）。

### G.5 检查远端文件权限（公钥认证失败的头号原因）

要求（`StrictModes` 打开时逐项检查）：

| 对象 | 要求 | 修复命令 |
|---|---|---|
| 家目录 | 属主是本人，**组和其他人不可写**（常见 `700` 或 `755`） | `chmod 700 ~`（谨慎）/ 调整属主 `chown <用户>:<组> ~` |
| `~/.ssh` | `700` | `chmod 700 ~/.ssh` |
| `~/.ssh/authorized_keys` | `600` | `chmod 600 ~/.ssh/authorized_keys` |
| 以上三者 | 属主必须是登录用户本人 | `chown -R <用户>:<用户组> ~/.ssh` |

【已实测】故意把 `authorized_keys` 改成 `666` 后：客户端得到 `Permission denied (publickey,gssapi-keyex,gssapi-with-mic,password).`，而**服务端日志直接点明原因**：

```
sshd-session[4483]: Authentication refused: bad ownership or modes for file /home/aimu/.ssh/authorized_keys
```

恢复 `600` 后同一把私钥立刻可以登录（`diff` 校验文件内容完全未变）。**这条日志是判断「权限问题」还是「公钥没装上」的关键分界**：有 `Authentication refused: bad ownership or modes` 就是权限，没有这句才是公钥/账户问题。

### G.6 用 `-i` 测试密钥登录

```bash
$ ssh -i ~/.ssh/awfm_key -o IdentitiesOnly=yes <用户名>@<远端主机> "echo login-ok; whoami; pwd"
login-ok
aimu
/home/aimu
```

要点：

- `-i` 指定私钥；`-o IdentitiesOnly=yes` 表示**只试这一把**（否则客户端还会把 agent 里、`~/.ssh` 下的其它钥匙也递上去，容易误判「到底哪把生效了」）；AWFM 在指定私钥时正是这么做的；
- 想看过程加 `-v`：`Offering public key:` 说明试了这把，`Server accepts key:` 说明服务端接受了它；
- 这一步成功，才说明「公钥装对了 + 权限对了 + 服务端允许公钥」三件事同时成立。

【已实测】本次新生成的密钥对该目标机登录成功，输出 `demo-login-ok` / `aimu` / `/home/aimu`，退出码 0。

### G.7 撤销与轮换密钥

**撤销 = 从目标账户的 `authorized_keys` 里删掉那一行**，不需要动客户端、也不需要重启 sshd。

```bash
$ grep -n "awfm-guide-demo" ~/.ssh/authorized_keys     # 先看清是第几行（按公钥尾部备注找最容易）
$ sed -i '/awfm-guide-demo/d' ~/.ssh/authorized_keys      # 删除匹配行（执行前先备份）
$ wc -l ~/.ssh/authorized_keys
```

【已实测】删除那一行后，同一把私钥（同一个客户端、同一条命令）立刻变成 `Permission denied (publickey,gssapi-keyex,gssapi-with-mic,password).` —— 撤销是**立即生效**的。

轮换（例如怀疑私钥泄露）推荐顺序：

1. 在客户端生成**新**密钥对（G.2）；
2. 把新公钥追加进目标账户（G.4），验证新私钥能登录（G.6）；
3. 确认无误后，再删掉旧公钥那一行（本节的命令）；
4. 在 AWFM 里把该连接的「私钥文件」改成新私钥路径；
5. 旧私钥文件在本机删除（`shred -u` / 安全删除），并检查有没有别处（备份、云盘、聊天记录）还留着它。

如果怀疑的是**主机**被换过（不是你的密钥泄露），那是主机密钥的问题：见 I.2 与 J.8。

### G.8 在 AWFM 里使用密钥

1. 「认证方式」选**密钥（推荐）**；
2. 「私钥文件」填**私钥**的绝对路径——**不要**填 `.pub`；
   - Windows 示例：`C:\Users\<你>\.ssh\id_ed25519`
   - Linux 示例：`/home/<你>/.ssh/awfm_key`
3. 「私钥文件」留空：AWFM 就不加 `-i`，由 `ssh` 自己去找 agent 里的密钥或 `~/.ssh` 下的默认密钥（界面提示原文：「可留空：留空时用 ssh-agent 里已加载的密钥，或 ~/.ssh 下的默认密钥。私钥始终只在本机使用，不会发送到浏览器。」）；
4. 保存后点「浏览文件」测试；首次连接会弹出**主机指纹核对**对话框，核对方法见 I.2。

AWFM 在指定私钥时会加 `-i <路径>` 与 `IdentitiesOnly=yes`：前者保证用的就是这把钥匙，后者避免误用其它钥匙。所以**在命令行里先用同样方式测通**（G.6），AWFM 里就大概率能通；反过来「命令行能连、AWFM 连不上」时，第一件事是比较两边用的私钥路径是否一致。

### G.9 密钥认证的常见坑

| 现象 / 报错 | 原因 | 处理 |
|---|---|---|
| `UNPROTECTED PRIVATE KEY FILE!` + `Permissions 0644 for '…' are too open.` + `This private key will be ignored.` | 私钥权限过宽（Linux 上实测） | `chmod 600 <私钥>`；Windows 上的对应报错与修法见 D.6 |
| `Permissions for '…' are too open.`（Windows） | ACL 允许了 `Authenticated Users` 等 | `icacls <私钥> /inheritance:r` + `icacls <私钥> /grant:r "$($env:USERNAME):F"`（实测有效） |
| `Load key "…": bad permissions` | 同上，密钥已被跳过 | 同上；注意这条出现后客户端会**继续尝试别的方式**，最终报 `Permission denied` |
| 登录失败但 `authorized_keys` 里确实有这把公钥 | 权限不合规（G.5） | 看服务端日志有没有 `Authentication refused: bad ownership or modes` |
| `-i` 指向 `.pub` 文件 | 指定错了文件 | `-i` 永远指私钥（不带 `.pub`） |
| 把私钥内容当公钥贴进 `authorized_keys` | 贴反了 | `authorized_keys` 里每行必须以 `ssh-ed25519 AAAAC3…` 这类**公钥**开头 |
| 每次连接都问口令 | 没开 agent | G.3 / D.8 |
| 换了新密钥但用旧连接仍是旧的 | AWFM 连接里仍写着旧私钥路径 | 编辑该连接，更新「私钥文件」 |

**绝不要把私钥内容粘贴到任何配置文件、聊天窗口、工单或截图里**（包括本教程的读者）。公钥可以，私钥不行。

---

## H. VMware、虚拟机网络与远程连接

### H.1 先分清 VMware 的三种网络模式

| 模式 | 虚拟机拿到什么地址 | 谁能连它 | 典型用途 |
|---|---|---|---|
| **桥接（Bridged）** | 和宿主机同一个物理网段的地址（由公司/家里的路由器分配） | 同一局域网里的任何机器 | 想让别人也能访问这台虚拟机 |
| **NAT** | VMware 虚拟网段的地址（默认 `192.168.x.0/24`），出口经宿主机做地址转换 | 宿主机可以直连；外部机器不能直接连进来（除非做端口转发） | 只在本机用、不想影响局域网 |
| **仅主机（Host-only）** | 另一个虚拟网段的地址 | 只有宿主机能连 | 完全隔离的实验环境 |

【已实测】本机上 VMware 建了两个虚拟网络：`VMware Network Adapter VMnet8 = 192.168.170.1`（NAT）与 `VMware Network Adapter VMnet1 = 192.168.11.1`（仅主机）；虚拟机在 NAT 网段里拿到 `192.168.170.128`，默认网关 `192.168.170.2`。因此**宿主机与虚拟机互通，而局域网里其它机器连不到这台虚拟机**——这正是 NAT 模式的预期行为。

排查时先问一句：**我的客户端和这台虚拟机在不在同一个可互通的网段里？** 不在，就得先解决网络，而不是折腾 SSH 配置。

### H.2 在虚拟机里确认自己的地址

```bash
$ hostname -I
192.168.170.128
$ ip -4 -o addr show
1: lo    inet 127.0.0.1/8 scope host lo
2: ens33 inet 192.168.170.128/24 brd 192.168.170.255 scope global dynamic noprefixroute ens33
$ ip -4 route | head -3
default via 192.168.170.2 dev ens33 proto static metric 100
192.168.170.0/24 dev ens33 proto kernel scope link src 192.168.170.128 metric 100
$ nmcli -t -f NAME,DEVICE,STATE con show --active
ens33:ens33:activated
lo:lo:activated
```

【已实测】以上是目标机上的真实输出。要点：

- 看到的是**哪个网卡**（这里 `ens33`）和**哪个网段**（`192.168.170.0/24`）；不同机器的网卡名可能是 `eth0`、`ens160`、`ens192`；
- 地址带 `dynamic` 就说明是 DHCP 分配的，**会变**（见 H.5）；
- `noprefixroute` 只是地址添加方式，不影响连接。

### H.3 从宿主机确认「能不能到」

```powershell
PS> ping <虚拟机IP>
PS> Test-NetConnection <虚拟机IP> -Port 22 | Select-Object TcpTestSucceeded
PS> ssh -v -p <端口> <用户名>@<虚拟机IP>
```

| 现象 | 结论 | 下一步 |
|---|---|---|
| `ping` 通、22 端口不通 | 网络到得了，sshd 或防火墙有问题 | 虚拟机里按 C.3 / C.4 查 sshd 与监听端口 |
| `ping` 不通 | 网络层就不通：网段不同、虚拟机没联网、网卡没起来 | 回 H.1/H.2 核对网段与网卡 |
| 端口通、`ssh` 仍失败 | 认证阶段的问题 | 看 J 节，先确认用户名与认证方式 |

【已实测】本环境是用 `ssh` 直接验证的：命令成功返回并执行了远端命令（退出码 0）。`ping` 与 `Test-NetConnection` 是同类判断中更快的两条，本次未逐条记录输出【未逐条实测】。注意部分环境会禁 ICMP，`ping` 不通不代表 TCP 不通，**以端口测试为准**。

### H.4 虚拟机 IP 变了怎么办

DHCP 的租约到期或重启后，虚拟机可能换一个地址；AWFM 里保存的连接就会连不上（症状通常是 `Connection timed out`）。三种确认新地址的办法：

1. **在虚拟机里查**（最直接）：`hostname -I`、`ip -4 addr`；
2. **在宿主机查 VMware 的 DHCP 租约文件**：

   ```powershell
   PS> Get-Content C:\ProgramData\VMware\vmnetdhcp.leases | Select-String '192.168.170'
   lease 192.168.170.128 {
   ```

   【已实测】该文件在本机存在且包含虚拟机的租约记录（`lease 192.168.170.128 {`），可以用来交叉验证虚拟机自报的地址。

3. **用 AWFM 的「扫描」功能**：它会读取本机的 VMware 配置/租约等来源并按网段探测 22 端口，列出候选地址（探测范围仅限读出来的虚拟网段，不会扫别的网络）。

想彻底避免地址漂移，可以让地址固定下来【需管理员/未验证】：

- 在 VMware 的「虚拟网络编辑器」里为这台虚拟机的 MAC 做 **DHCP 保留**（推荐，改动最小）；
- 或者在虚拟机里把该网卡改成**静态 IP**（要同时设置网关与 DNS，配错会让虚拟机失去网络）；
- 或者给虚拟机加**第二个网卡**专门用于管理（进阶，容易把路由搞乱）。

### H.5 克隆、重装后的主机密钥变化

把虚拟机克隆一份、或者重装系统，主机会得到**新的主机密钥**。此时客户端会拒绝连接并给出这段文字（下面是从本环境真实复现的输出）：

```
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
IT IS POSSIBLE THAT SOMEONE IS DOING SOMETHING NASTY!
Someone could be eavesdropping on you right now (man-in-the-middle attack)!
It is also possible that a host key has just been changed.
The fingerprint for the ED25519 key sent by the remote host is
SHA256:DqCdx8fTqzkkNm7wByDOmaYooNWJF5geaBL0n1WXTzQ.
Please contact your system administrator.
Add correct host key in <known_hosts 路径> to get rid of this message.
Offending ED25519 key in <known_hosts 路径>:1
Host key for 192.168.170.128 has changed and you have requested strict checking.
Host key verification failed.
```

**正确处理**（不要照着提示里的字面意思直接盖章通过）：

1. **停下来想清楚**：这台机器最近重装/克隆过吗？如果不是你干的，就要按安全事件对待（可能有人在中间）。
2. 通过**可信渠道**（VMware 控制台、云控制台、机房 KVM）在目标机上核对新指纹：

   ```bash
   $ ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
   256 SHA256:DqCdx8fTqzkkNm7wByDOmaYooNWJF5geaBL0n1WXTzQ no comment (ED25519)
   ```

3. 确认是「换机器」而不是「被中间人」之后，才更新客户端记录：

   ```bash
   $ ssh-keygen -R <主机>            # 删除旧记录（会同时备份为 known_hosts.old）
   ```

   然后重新连接、核对指纹、再确认。AWFM 里对应的操作见 I.3。

4. 如果指纹**说不清来源**，那就先别连：换网络、换时间再查，或直接重建这台虚拟机。宁可多花半小时，也不要把凭证交给一台身份不明的机器。

### H.6 「控制台能登录，宿主机却连不上」的常见原因

| 原因 | 在虚拟机里怎么确认 | 处理 |
|---|---|---|
| sshd 没装 | `rpm -q openssh-server` / `command -v sshd` | 装（C.2） |
| sshd 没启动 | `systemctl is-active sshd` | `sudo systemctl enable --now sshd`（C.3） |
| sshd 只监听回环 | `ss -ltn \| grep :22` 只有 `127.0.0.1:22` | 改 `ListenAddress`（C.6） |
| 防火墙拦了 22 | `sudo firewall-cmd --list-all` / `sudo ufw status` | 放行 22（C.8） |
| 网卡没起来 / 没地址 | `ip -4 addr`、`nmcli device status` | 起网卡、修 DHCP |
| 在 NAT 网段但客户端不在同一网段 | 对比两端地址（H.1） | 换桥接或做端口转发 |
| 用了错误的 IP（旧地址） | `hostname -I`、租约文件（H.4） | 更新 AWFM 里的主机地址 |

---

## I. AWFM 连接配置

### I.1 准备这些参数

点「+ 新增」打开连接表单，逐项含义如下（括注是界面上的提示原文）：

| 字段 | 填什么 | 注意 |
|---|---|---|
| **名称** | 给这条连接起的名字 | 留空则自动用「用户名@主机」 |
| **主机** | 远端 IP 或域名（必填） | 就是 H.2 里查到的地址 |
| **端口** | SSH 端口，默认 `22` | 改过端口才需要动它；**不是** AWFM 网页端口 32579 |
| **用户名** | **远端**登录账户 | 留空会用本机当前用户名去试；Windows 上一般不要留空 |
| **认证方式** | 「密钥（推荐）」或「密码」 | 密码模式见 F.6 |
| **私钥文件** | 私钥的绝对路径，仅密钥模式显示 | 「可留空：留空时用 ssh-agent 里已加载的密钥，或 ~/.ssh 下的默认密钥。私钥始终只在本机使用，不会发送到浏览器。」 |
| **备注** | 给自己看的说明 | 例如「实验室虚拟机」「生产跳板机」 |
| **允许写操作** | 是否允许上传/覆盖/重命名/删除等写操作 | 默认**关闭**；打开后才有写操作（I.4） |

填完保存，然后点「浏览文件」开始连接。

### I.2 首次连接：核对主机指纹（不要跳过）

第一次连一台机器时，AWFM 会停下来让你核对指纹，对话框内容如下（界面原文）：

> **首次连接，请核对主机指纹**
> 这是第一次连接 <用户名>@<主机>:<端口>。SSH 用主机密钥确认「你连上的确实是那台机器」，而不是中间转发的人。
> 请核对下面的指纹与目标机上的输出是否一致（在目标机上执行）：
> `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`
> （指纹列表：密钥类型 + 指纹）
> 如果指纹对不上，说明中间可能有其他人，请选「取消」。

正确做法：**在目标机上**（VMware 控制台、或另一个可信终端）执行对话框里给出的那条命令，把输出与本机界面上的指纹逐字符比对（`SHA256:` 后面那串大小写敏感），一致才点「指纹一致，信任并继续」。

【已实测】目标机上该命令的真实输出：

```
$ ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
256 SHA256:DqCdx8fTqzkkNm7wByDOmaYooNWJF5geaBL0n1WXTzQ no comment (ED25519)
```

它与客户端侧独立取得的指纹完全一致（本次用 `ssh-keyscan 192.168.170.128 | ssh-keygen -lf -` 交叉核对，三种密钥类型 RSA/ECDSA/ED25519 全部一致）。这说明**指纹是可以并且应该被核对的**：两边算出同一串字符，才证明你连的是那台机器。

确认之后，AWFM 把这个主机公钥写入项目的信任库 `data/known_hosts`（**不是**你 `%USERPROFILE%\.ssh\known_hosts`），提示「已记录主机密钥。」。

### I.3 指纹变了怎么办

如果目标机重装或换了机器，AWFM 会明确报错并把「本地已记录的指纹」与「目标机现在提供的指纹」并列展示；默认策略 `strict` 下**不会自动接受新指纹**。此时：

1. 先当成安全事件对待：确认这台机器是不是你（或同事）重装/克隆过；
2. 通过可信渠道核对新指纹（同 I.2，用 `ssh-keygen -lf` 在目标机上取）；
3. 确认无误后，在界面上明确选择信任新指纹（或在命令行 `ssh-keygen -R <主机>` 清掉旧记录后再走一次首次连接流程）；
4. 如果对不上来源，**不要**为了「先连上」而信任——先把机器查清楚。

### I.4 「允许写操作」是什么意思

AWFM 把「看」和「改」分开：

| 状态 | 能做什么 |
|---|---|
| 未打开（默认） | 浏览目录、预览、下载、搜索；写操作按钮不可用 |
| 已打开 | 上传/覆盖、在线编辑保存、重命名、压缩为 `.tar.gz`、解压、删除 |

建议：日常浏览就保持关闭；确实要上传或改文件时再临时打开，用完关掉。这条开关是**客户端侧的意图声明**，不能替代服务端的权限控制——真正的边界由远端的文件属主与权限位决定。

### I.5 连接失败后的排查顺序

按这个顺序做，通常两三轮就能定位：

1. **看 AWFM 的报错原文**（它把 ssh 的错误带出来了）：是连接类（`Connection refused` / `Connection timed out`）还是认证类（`Permission denied` / `Host key verification failed`）？
2. **在命令行里复现同一条连接**：

   ```powershell
   PS> ssh -v -p <端口> -i <私钥路径> <用户名>@<主机>
   ```

3. **对比两边用的私钥路径**：AWFM 里填的路径与命令行 `-i` 的路径必须**指向同一个文件**（Windows 上要写完整路径，例如 `C:\Users\<你>\.ssh\id_ed25519`）；
4. **对比认证方式**：AWFM 选「密码」而服务端禁用了密码，会直接失败；选「密钥」而没填私钥、agent 里又没密钥，也会失败；
5. **对比主机指纹**：`Host key verification failed` / 指纹变化 → 按 I.2、I.3 处理；
6. **单独验证 SFTP**：命令行 `sftp` 能列出目录而 AWFM 不能 → 看服务端 `Subsystem sftp`（C.6）；
7. **仍然不通**：把 AWFM 的报错与命令行同一时刻的 `ssh -vv` 输出放在一起看，逐行对照 `debug1:` 停在哪一步（D.4 的判读表）。

### I.6 AWFM 实际使用的 ssh 选项（可核对）

AWFM 不是「另写一套 SSH 实现」，而是把参数翻译成系统 `ssh` 的命令行。它固定使用这些选项：

| 选项 | 值 | 作用 |
|---|---|---|
| `-p` | 连接里填的端口 | 目标端口 |
| `UserKnownHostsFile` / `GlobalKnownHostsFile` | 项目 `data/known_hosts` | 信任库独立于用户目录，防止「首次确认」被旧记录绕过 |
| `StrictHostKeyChecking` | `yes`（默认）/ `accept-new` | 主机密钥策略；默认只接受已记录的 |
| `ConnectTimeout` / `ServerAliveInterval` / `ServerAliveCountMax` | 配置值（默认 15 / 30 / 3） | 连不上时快速失败；NAT 掉线能被发现 |
| `LogLevel=ERROR` | — | 正常路径下 stderr 保持干净，便于诊断 |
| `BatchMode` | 密钥模式 `yes`，密码模式 `no` | 密钥模式禁止交互挂起；**密码模式必须为 `no`**，否则密码认证会被跳过 |
| `PreferredAuthentications` | 密钥：`publickey`；密码：`password,keyboard-interactive,publickey` | 限定认证尝试顺序 |
| `-i` + `IdentitiesOnly=yes` | 填了私钥时 | 只尝试这一把私钥，避免拿 agent 里其它密钥反复尝试（可能触发对端失败次数限制） |
| `-s sftp` | — | 走 SFTP 子系统传文件 |

完整清单与理由见 [附录 A](#附录-aawfm-实际使用的-ssh-选项)。

### I.7 AWFM 支持与不支持（以当前实现为准）

| 能力 | 现状 |
|---|---|
| 认证方式 | 只支持**密钥**与**密码**两种；不支持 Kerberos/GSSAPI、双因素交互式登录 |
| 密码保存 | **不支持保存密码**（每次连接输入），这是刻意的安全取舍 |
| ssh-agent | 可以使用（「私钥文件」留空时走 agent 或默认密钥），但 AWFM 不管理 agent |
| 跳板机 / ProxyJump | 没有专门的配置项；AWFM 调用系统 `ssh`，因此写在你 `~/.ssh/config` 里的 `ProxyJump` 等配置**可能**仍会生效【未验证】 |
| 端口转发 / SOCKS | 不支持 |
| SFTP 子系统 | 强依赖；服务端没有 `Subsystem sftp` 时无法浏览文件 |
| 主机指纹 | 首次人工确认、变化不自动接受（默认 `strict`） |
| 写操作 | 由每条连接的「允许写操作」+ 远端文件权限共同决定 |

---

## J. 常见错误与诊断流程

先看这张总表定位方向，再跳到对应小节。**不要把所有错误都归因于防火墙**——下面 16 类里只有前三类与网络/防火墙直接相关。

| 错误 / 现象 | 出问题的层次 | 小节 |
|---|---|---|
| `Connection refused` | 端口没人监听 / 被拒绝 | J.1 |
| `Connection timed out` | 网络不可达 / 被静默丢弃 | J.2 |
| `No route to host` | 路由 / 链路 | J.3 |
| `Permission denied (publickey,password)` | 认证 | J.4 |
| `Host key verification failed` | 主机密钥（未知主机） | J.5 |
| `REMOTE HOST IDENTIFICATION HAS CHANGED!` | 主机密钥（变化） | J.6 |
| `UNPROTECTED PRIVATE KEY FILE!` / `Permissions ... are too open` | 本机私钥权限 | J.7 |
| sshd 未启动 / 监听在别的端口 | 服务端 | J.8 |
| 用户名写错 / 账户不允许登录 | 认证 | J.9 |
| `subsystem request failed on channel 0` | SFTP 子系统 | J.10 |
| 能登录但列不出目录 | 权限 / 家目录 | J.11 |
| 上传/保存/删除被拒绝 | 写权限 | J.12 |
| `Connection reset by peer` / 会话突然失效 | 链路中断 | J.13 |
| `Too many authentication failures` | 认证尝试次数 | J.14 |
| `Connection closed by ...` / 协议错乱 | 连到了非 SSH 服务 | J.15 |
| `Unable to negotiate ...  no matching ... found` | 算法协商 | J.16 |

### J.1 `Connection refused`

**可能原因**：sshd 没在监听该端口；端口写错；目标地址不是这台机器；防火墙主动拒绝（`REJECT`）。

**检查顺序与命令**：

```bash
# 服务端：有没有监听、监听的哪个端口
$ ss -ltn | grep -E ':22|:2222'
$ systemctl is-active sshd
```

```powershell
# 客户端：换个端口试试、确认地址
PS> ssh -p 22 <用户名>@<主机>
```

**判读**：服务端 `ss` 里看不到 22 → 服务没起来或改了端口；客户端报错里带 `port 2222` 而服务端只在 22 监听 → 端口填错。

【已实测】把一个没有服务监听的端口当作 SSH 端口时的真实输出（Windows 客户端）：

```
banner exchange: Connection to UNKNOWN port -1: Connection refused
```

另一台机器上可能显示更常见的形态 `ssh: connect to host <主机> port 2222: Connection refused`——含义相同。

**安全修复方向**：启动 sshd（C.3），或把连接配置里的端口改成实际端口；防火墙规则应针对**该端口**放行（C.8），不要整体关闭防火墙。

### J.2 `Connection timed out`

**可能原因**：IP 不可达（认错了地址/虚拟机没开机）；跨网段路由不通；防火墙 `DROP`（静默丢弃，表现为超时而不是拒绝）；NAT 未做端口映射。

**检查顺序与命令**：

```powershell
PS> ping <主机>                                  # 先看能不能到
PS> Test-NetConnection <主机> -Port <端口>        # 再看端口
PS> ssh -o ConnectTimeout=5 <用户名>@<主机>
```

```bash
# 服务端：确认自己的地址与路由
$ hostname -I; ip -4 route | head -3
```

**判读**：`ping` 通但端口超时 → 防火墙大概率在丢包（或 sshd 不在该端口）；`ping` 也不通 → 网络层问题，先解决网络（H 节）。

【已实测】真实输出：

```
ssh: connect to host 192.168.170.199 port 22: Connection timed out
```

**安全修复方向**：把连接配置的主机改成正确地址；在**两端**核对网段是否互通；需要跨网段时用受限的端口转发或跳板机，不要为了方便把服务暴露到公网。

### J.3 `No route to host`

**可能原因**：链路/路由中断（网卡掉线、交换机端口关闭、路由表缺失），或防火墙用 ICMP 明确拒绝。

**检查顺序与命令**：

```bash
$ ip -4 route            # 有没有默认路由
$ ip -4 addr show        # 网卡有没有地址、是不是 DOWN
$ nmcli device status    # 网卡状态
```

```powershell
PS> ipconfig | Select-String 'VMnet|以太网|IPv4'
```

**判读**：客户端与虚拟机不在同一网段时，宿主机必须有自己的虚拟网卡地址（H.1）；虚拟机网卡 `DOWN` 时先在虚拟机里把它起来。

**安全修复方向**：恢复链路与路由；不要用「关掉防火墙」来绕过，先确认是路由问题还是策略拒绝。

### J.4 `Permission denied (publickey,password)`

**这是认证失败，不是网络失败**——连接已经建立、服务端已经回话。

| 可能原因 | 怎么确认 |
|---|---|
| 用户名写错 / 账户不存在 | 服务端日志有没有 `Failed password for <你写的用户名>`；或核对 `id <用户名>` |
| 密码错 | 服务端日志 `Failed password for ...` |
| 服务端不需要密码（只允许密钥） | 括号列表里没有 `password` / `keyboard-interactive`（F.3） |
| 公钥没装到目标账户 | 命令行 `-v` 里有 `Offering public key` 但没有 `Server accepts key`（G.4） |
| `authorized_keys` 权限不合规 | 服务端日志 `Authentication refused: bad ownership or modes for file ...`（G.5） |
| 私钥权限过宽被客户端忽略 | 报错里有 `UNPROTECTED PRIVATE KEY FILE!`（J.7） |

**检查顺序**：先读括号里的方法列表 → 再看服务端日志 → 再核对公钥是否真的在 `authorized_keys` 里（`grep <备注> ~/.ssh/authorized_keys`）。

【已实测】本环境故意放宽权限后得到的就是这一行：

```
Permission denied (publickey,gssapi-keyex,gssapi-with-mic,password).
```

**安全修复方向**：不要重复试密码（会触发锁定或封禁），先把原因查清；优先改用密钥（G）。

### J.5 `Host key verification failed`（未知主机）

**可能原因**：这台机器的主机密钥还没被记录过（首次连接），而客户端策略要求严格校验。

【已实测】用一个空的信任库 + `StrictHostKeyChecking=yes` 复现的真实输出：

```
No ED25519 host key is known for 192.168.170.128 and you have requested strict checking.
Host key verification failed.
```

**正确做法**：不要改成 `StrictHostKeyChecking=no` 了事。先通过可信渠道取得目标机的指纹（`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`），核对一致后再记录（命令行按提示输入 `yes`；AWFM 里走 I.2 的对话框）。

### J.6 主机指纹变化（`REMOTE HOST IDENTIFICATION HAS CHANGED!`）

完整原文与正确处理见 **H.5**。要点重复一次：

- 这是**安全告警**，不是配置错误；
- 只有在你确认目标机确实被重装/克隆过之后，才更新本地记录；
- AWFM 的默认策略不会自动接受新指纹；
- 命令行上处理：`ssh-keygen -R <主机>` 删除旧记录后重新连接并核对。

### J.7 私钥无法读取 / 权限过宽

两种形态，修复方式不同：

**Linux / macOS（POSIX 权限位）**——【已实测】真实输出：

```
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@         WARNING: UNPROTECTED PRIVATE KEY FILE!          @
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
Permissions 0644 for '/tmp/awfm-guide-keys/demo_key' are too open.
It is required that your private key files are NOT accessible by others.
This private key will be ignored.
Load key "/tmp/awfm-guide-keys/demo_key": bad permissions
<用户名>@<主机>: Permission denied (publickey,gssapi-keyex,gssapi-with-mic,password).
```

修复：`chmod 600 <私钥>`。

**Windows（ACL）**——【已实测】真实输出与修复见 **D.6**：

```
Bad permissions. Try removing permissions for user: NT AUTHORITY\Authenticated Users (S-1-5-11) on file …
Permissions for '…' are too open.
This private key will be ignored.
```

修复：

```powershell
PS> icacls <私钥路径> /inheritance:r
PS> icacls <私钥路径> /grant:r "$($env:USERNAME):F"
```

**判读要点**：这两种报错的共同后果是**这把私钥被跳过**，于是客户端继续尝试别的方式，最终仍然报 `Permission denied`。所以看到 `Permission denied` 时，往上翻几行，先确认有没有这两段警告。

### J.8 sshd 未启动 / 监听在错误端口

```bash
$ systemctl is-active sshd          # inactive / failed
$ sudo systemctl enable --now sshd  # 启动并设为自启（需管理员）
$ ss -ltn | grep :22                # 确认监听
```

如果 `ss` 显示的是 `127.0.0.1:22`，说明只监听回环：远端连不上（C.4）。如果显示 `:2222`，连接配置里的端口要改成 2222。

**安全修复方向**：改 `Port` 之前先想清楚有没有别的系统依赖 22 端口；改完用 `sudo sshd -t` 检查语法、`sudo systemctl reload sshd` 平滑生效，并**保留一个已登录的会话**作为退路（C.7）。

### J.9 远端用户名错误

**现象**：密码确定正确，仍然 `Permission denied`；服务端日志出现 `Failed password for <错的用户名>` 或 `Invalid user <错的用户名>`。

**检查**：

```bash
$ whoami; id            # 在虚拟机的控制台里执行，确认真实账户名
$ getent passwd <用户名>  # 该账户是否存在
```

容易混淆的几种：Windows 账户名 ≠ Linux 账户名；`root` 往往被 `PermitRootLogin` 禁止；`ubuntu`/`centos`/`ec2-user` 这类云镜像默认户名各不相同。

### J.10 `subsystem request failed on channel 0`（SFTP 不可用）

**现象**：`ssh` 能登录，但 AWFM 或 `sftp` 一列目录就失败。

【已实测】请求一个不存在的子系统时，客户端真实输出：

```
subsystem request failed on channel 0
```

SFTP 的对应报错形态与此完全一致——它说明**服务端没有提供该子系统**。检查服务端配置里有没有这一行（C.6）：

```
Subsystem sftp /usr/libexec/openssh/sftp-server     # 路径随发行版不同
```

**修复方向**：由管理员在 `sshd_config` 中补回该行并 reload（C.7）。注意有些加固脚本会顺手删掉它，此时 `ssh` 一切正常，只有文件传输失败。

### J.11 能登录，但列不出目录 / 家目录不可访问

**可能原因**：家目录属主或权限不对（例如 `root` 拥有、`700` 无执行位）；家目录在自动挂载（autofs）上尚未挂载；SELinux 上下文错误（C.9）。

```bash
$ ls -ld /home/<用户名> /home/<用户名>/.ssh
$ df -h /home/<用户名>
```

**判读**：家目录缺少 `x`（进入）或 `r`（列目录）权限，`sftp` 会直接报权限拒绝；`chmod 700 /home/<用户名>` 与 `chown <用户名>:<用户组> /home/<用户名>` 是常规修法（改属主/权限前先确认没有更合适的组策略）。

### J.12 上传 / 保存 / 删除被拒绝

两种来源，先分清是哪一种：

| 现象 | 来源 | 处理 |
|---|---|---|
| 界面按钮不可用 / 提示需要先打开写操作 | AWFM 的「允许写操作」未打开 | I.4 |
| 服务端返回权限拒绝（`Permission denied`） | 远端文件属主/权限位、目录不可写、磁盘只读 | 在服务端核对 `ls -l`、`df -h`、挂载选项 |
| 保存时报内容冲突 | 文件在别处被改过（AWFM 的冲突检测） | 重新加载远端内容后再合并保存 |

**安全修复方向**：优先调整**具体目录**的属主/权限或把文件放到用户可写位置，而不是 `chmod 777` 或改 `sudo` 白名单。

### J.13 连接成功但会话突然失效（`Connection reset by peer`）

**可能原因**：NAT/防火墙的连接表超时；网络切换（笔记本休眠、Wi-Fi 切换）；服务端重启或 `sshd` 被重载；长时间无操作。

**检查**：

```bash
$ journalctl -u sshd -n 20 --no-pager | tail -20    # 服务端：连接是怎么结束的
```

**缓解**：AWFM 已经启用 `ServerAliveInterval=30`、`ServerAliveCountMax=3`（附录 A），能让 NAT 掉线更早被发现；掉线后 AWFM 会把该连接标为「已断开」，重新连接即可（会回到原来的目录）。

### J.14 `Too many authentication failures`

**可能原因**：客户端一次性递了太多把公钥（agent 里存了很多），服务端 `MaxAuthTries`（默认 6）用完后直接断开。

【已实测】用 8 把无关密钥尝试登录（`-i` 指定 8 次、`IdentitiesOnly=no`）时的真实输出：

```
Received disconnect from 192.168.170.128 port 22:2: Too many authentication failures
Disconnected from 192.168.170.128 port 22
```

**修复**：明确指定要用的那一把，并加 `-o IdentitiesOnly=yes`；AWFM 在填了「私钥文件」时**自动**这么做，这正是它避免该问题的原因（I.6）。

### J.15 连到了非 SSH 服务（`Connection closed by ...`）

**可能原因**：端口写成了 HTTP、数据库等别的服务；中间的负载均衡/代理拦了连接。

【已实测】把 SSH 客户端指向一个发 HTTP 响应的端口，真实输出：

```
Connection closed by 127.0.0.1 port 32587
```

**判读**：这类报错里**不会**出现 `Permission denied`，也不会出现 `port 22` 以外的成功协商；结合 `ssh -v` 看有没有 `Remote protocol version`，没有就说明对端根本不是 SSH。

### J.16 算法协商失败

**可能原因**：客户端或服务端过老/被加固过，双方没有共同支持的算法。

【已实测】两条真实输出（强制使用服务端不支持的老算法）：

```
Unable to negotiate with 192.168.170.128 port 22: no matching key exchange method found. Their offer: mlkem768x25519-sha256,mlkem768nistp256-sha256,mlkem1024nistp384-sha384,curve25519-sha256,curve25519-sha256@libssh.org,ecdh-sha2-nistp256,ecdh-sha2-nistp384,ecdh-sha2-nistp521,diffie-hellman-group-exchange-sha256,diffie-hellman-group14-sha256,diffie-hellman-group16-sha512,diffie-hellman-group18-sha512,ext-info-s,kex-strict-s-v00@openssh.com

Unable to negotiate with 192.168.170.128 port 22: no matching host key type found. Their offer: rsa-sha2-512,rsa-sha2-256,ecdsa-sha2-nistp256,ssh-ed25519
```

**判读**：`Their offer:` 后面是**对端支持什么**。正确方向是升级较老的一端，或在明确知道风险的前提下**最小化**地放开某一个算法；不要整体回退到 `ssh-rsa`/`diffie-hellman-group1-sha1` 这类已被淘汰的算法。

---

## K. 安全建议与维护

### K.1 私钥保管

- 私钥只放在本机自己的用户目录（Windows `%USERPROFILE%\.ssh`、Linux `~/.ssh`），权限收紧（Linux `600`、Windows 只留本人 + Administrators + SYSTEM）；
- 设置口令（passphrase），配合 ssh-agent 使用（G.3 / D.8）；
- 不要放云盘、不要放进 Git 仓库、不要贴到聊天工具或工单里；
- 一台设备一把密钥、一个用途一把密钥，便于单独撤销（G.7）；
- 怀疑泄露就立刻轮换：先装新公钥、验证、再删旧公钥行。

### K.2 主机指纹核验

- 首次连接**必须**核对（I.2）；
- 指纹变化**必须**先调查（H.5 / I.3）；
- 不要把 `StrictHostKeyChecking=no`、`/dev/null` 当 known_hosts 之类的写法留在日常配置里——那等于每次连接都无条件信任对端。

### K.3 最小权限原则

- 用普通账户登录，需要 root 权限时再用 `sudo`；不要开放 `PermitRootLogin yes`；
- 写操作按需打开，用完关掉（I.4）；
- 远端只给必要的目录权限，不要用 `chmod -R 777` 解决问题；
- 在服务端可以用 `AllowUsers`/`Match` 限制谁能从哪些来源登录（C.6）。

### K.4 合理设置访问范围

- sshd 监听地址按需收窄（只监听管理网段的网卡）；
- 防火墙只放行必要来源（C.8）；
- 不要把 SSH 直接暴露到公网；需要远程访问时优先用 VPN 或跳板机。

### K.5 备份与变更

- 改 SSH 配置前先备份（C.7），并保留一个已登录会话或控制台退路；
- 主机密钥属于「这台机器的身份」，随机器一起备份/迁移时要意识到：迁移后指纹**不变**才符合预期，变了就当事件处理；
- 记录每次改动的时间与原因，便于回溯。

### K.6 更新与日志

- 定期更新系统与 OpenSSH（安全修复的主要来源）；
- 关注服务端日志（C.5）里的异常：大量 `Failed password`、来源异常的 `Accepted`、`bad ownership or modes`；
- AWFM 侧只记录连接标识与错误，不记录密码；日志脱敏是既定要求（`security.redact_secrets`）。

### K.7 不要用来源不明的脚本

网上流传的「一键配置 SSH」「一键免密登录」脚本经常做这几件事：把 `PasswordAuthentication` 改成 `no`、把 `PermitRootLogin` 改成 `yes`、往 `authorized_keys` 里塞一把来路不明的公钥、或把私钥写到临时目录。**只手工执行你读得懂的每一条命令**；别人给的公钥在装之前先看一下它的备注与指纹。

---

## L. 快速排查清单

按顺序走，每一步都先看**这一步的结论**，不要跳步。

| 步骤 | 命令（在哪执行） | 通过的标志 | 不通时去哪 |
|---|---|---|---|
| 1. 网络可达 | `ping <主机>`（本机） | 有回包 | H 节 |
| 2. SSH 端口可达 | `Test-NetConnection <主机> -Port <端口>`（本机）；`ss -ltn \| grep :<端口>`（远端） | 端口开放、服务端在监听 | J.1 / J.2 / J.8 |
| 3. 服务端正常 | `systemctl is-active sshd`（远端） | `active` | C.3 |
| 4. 用户名正确 | `id <用户名>`（远端控制台） | 账户存在 | J.9 |
| 5. 认证成功 | `ssh -v [-i <私钥>] <用户名>@<主机>`（本机） | 出现 `Server accepts key` 或密码通过；能进 shell | F / G / J.4 / J.7 |
| 6. 主机指纹可信 | `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`（远端）+ 与客户端显示比对 | 两边完全一致 | I.2 / I.3 / J.5 / J.6 |
| 7. SFTP 可用 | `sftp [-i <私钥>] <用户名>@<主机>` 后 `pwd` / `ls`（本机） | 能列出目录 | J.10 |
| 8. 目录权限正确 | `ls -ld ~ ~/.ssh`（远端） | 属主是自己、权限合理 | J.11 / J.12 |

### L.1 一页速查（把这张表贴在手边）

| 你看到的 | 先去查 | 一条命令 |
|---|---|---|
| `Connection refused` | sshd 是否在监听 | 远端 `ss -ltn \| grep :22` |
| `Connection timed out` | 网络与防火墙 | 本机 `Test-NetConnection <主机> -Port 22` |
| `Permission denied (…)` | 认证方式与凭证 | 服务端 `journalctl -u sshd -n 20` |
| `Host key verification failed` | 指纹未记录 | 远端 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` |
| `REMOTE HOST IDENTIFICATION HAS CHANGED!` | 机器是否被重装 | 同上，并读 H.5 |
| `UNPROTECTED PRIVATE KEY FILE!` | 私钥权限 | Linux `chmod 600 <私钥>` / Windows `icacls` 见 D.6 |
| `subsystem request failed` | SFTP 子系统 | 远端 `sudo sshd -T \| grep -i subsystem` |
| `Too many authentication failures` | 递上去的密钥太多 | 加 `-o IdentitiesOnly=yes -i <私钥>` |
| 能登录但列不出目录 | 家目录权限 / SELinux | 远端 `ls -ld ~` |

---

## 附录 A：AWFM 实际使用的 ssh 选项

以下选项由 AWFM 在建立每条连接时固定追加（源码：`app/ssh/ssh_launcher.py`，便于核对「AWFM 到底做了什么」）。

| 选项 | 值 | 为什么这么定 |
|---|---|---|
| `-p` | 连接配置里的端口 | 支持非 22 端口 |
| `-o UserKnownHostsFile=<项目 data/known_hosts>` | 项目自有信任库 | 不污染用户 `~/.ssh`，且让「首次确认」在应用内可表达 |
| `-o GlobalKnownHostsFile=<同一个文件>` | 同上 | 否则用户既有记录会让首次确认被静默跳过 |
| `-o StrictHostKeyChecking=yes` | 默认（策略 `strict`） | 只接受已记录的主机密钥；可配置为 `accept-new`（接受新主机但拒绝变化） |
| `-o ConnectTimeout=<配置值>` | 默认 15 秒 | 目标机不在线时快速失败，不无限挂起 |
| `-o ServerAliveInterval=<配置值>` / `ServerAliveCountMax=3` | 默认 30 秒 | 让 NAT 掉线能被周期性探测到 |
| `-o LogLevel=ERROR` | — | 正常路径 stderr 为空，错误诊断不被噪音淹没 |
| `-o BatchMode=yes`（密钥模式） | — | 禁止交互式提示导致的挂起 |
| `-o BatchMode=no` `-o NumberOfPasswordPrompts=1`（密码模式） | — | `BatchMode=yes` 会**彻底禁用**密码认证（OpenSSH 的 `userauth_passwd()` 直接返回 0），所以密码模式必须为 `no`；再用一次尝试上限避免反复索要 |
| `-o PreferredAuthentications=publickey`（密钥）/ `password,keyboard-interactive,publickey`（密码） | — | 限定尝试顺序，行为可预期 |
| `-i <私钥路径>` `-o IdentitiesOnly=yes`（填了私钥时） | — | 只试指定的这一把，避免 agent 里其它密钥被逐个递出（J.14） |
| `-s sftp` | — | 通过 SFTP 子系统传文件 |

密码模式下额外的环境变量（只传「用什么程序读密码」和「从哪里读」，**密码本身不进命令行、不进环境变量**）：

| 变量 | 值 | 作用 |
|---|---|---|
| `SSH_ASKPASS` | 本机辅助程序路径 | 由它把密码交给 ssh |
| `SSH_ASKPASS_REQUIRE` | `force` | 无条件使用 askpass（OpenSSH 8.4+），否则有终端时会被忽略 |
| `DISPLAY` | 原值或 `awfm-local` | 部分版本要求该变量非空 |

## 附录 B：验证记录

**验证环境（2026-10-17）**

| 项 | 值 |
|---|---|
| 客户端 | Windows 11 家庭版（AMD64） |
| 客户端 OpenSSH | `OpenSSH_for_Windows_9.5p2, LibreSSL 3.8.2`（`C:\Windows\System32\OpenSSH\ssh.exe`） |
| 服务端 | CentOS Stream 10（Coughlan），hostname `hadoop01` |
| 服务端 OpenSSH | `OpenSSH_9.9p1, OpenSSL 3.5.8`（包 `openssh-server-9.9p1-32.el10.x86_64`） |
| 网络 | VMware NAT：虚拟机 `192.168.170.128/24`，网关 `192.168.170.2`，宿主机 VMnet8 `192.168.170.1` |

**已实测（关键步骤逐条真实执行过）**

| 内容 | 结果 |
|---|---|
| 客户端版本与路径（D.1） | `ssh -V` 与 `Get-Command ssh` 输出如上 |
| 服务端状态与监听（C.3 / C.4） | `active` / `enabled`；`0.0.0.0:22` 与 `[::]:22` |
| 服务端日志判读（C.5） | 捕获 `Accepted publickey …`、`Authentication refused: bad ownership or modes …` |
| 主机指纹双端一致（I.2） | RSA / ECDSA / ED25519 三种密钥双端算出同一 `SHA256:` 串 |
| 密钥认证端到端（G.2 / G.4 / G.6） | 生成 → 追加公钥 → `ssh -i` 登录成功；撤销后同一把私钥立即失效 |
| Windows 安装公钥路径（D.7） | `Get-Content … \| ssh … "cat >> …"` 成功并登录成功 |
| 私钥权限（Linux 0644 / Windows ACL 放宽） | 两种报错均真实复现；Windows 修复命令实测有效 |
| `authorized_keys` 权限违规（G.5） | 客户端 `Permission denied`，服务端日志 `Authentication refused: bad ownership or modes for file …` |
| `sftp` 子系统可用（E.4） | 能 `pwd` / `ls`，退出码 0 |
| 13 类错误文本（J 节） | 其中 12 类在本环境真实复现（见各小节标注）；`No route to host` 未复现 |

**未验证（本文中已逐处标注，不要当成结论）**

| 内容 | 原因 |
|---|---|
| 所有 `sudo` / `root` 类命令（安装、启动服务、改配置、`sshd -T`、防火墙放行） | 验证环境的普通账户没有免密 `sudo` |
| SELinux 开启时的端口标签与文件上下文 | 该虚拟机 SELinux 为 `Disabled` |
| firewalld 运行中的放行规则 | 该虚拟机 firewalld 未运行 |
| Windows 安装 OpenSSH 客户端、启动 ssh-agent 服务 | 需要管理员权限 |
| macOS 客户端与 `ssh-add --apple-use-keychain` | 无 macOS 环境 |
| 静态 IP / DHCP 保留的具体操作步骤 | 需要改动虚拟机网络配置（高风险，未执行） |
| `~/.ssh/config` 里的 `ProxyJump` 对 AWFM 是否生效（I.7） | 未搭跳板机环境 |

**本文与 AWFM 版本的关系**：教程描述的行为对应 AWFM v0.1.2 的实现（`app/ssh/ssh_launcher.py` 的命令行构造、`frontend/assets/js/connections.js` 的表单与指纹对话框）。程序行为变化时，这两处是最先需要同步核对的地方。
