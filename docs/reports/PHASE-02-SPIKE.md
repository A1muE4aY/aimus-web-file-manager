# 阶段 02 SPIKE 报告：连接层技术路线验证

## 1. 报告信息

| 项 | 值 |
|---|---|
| 项目 | Aimu's Web File Manager (AWFM) |
| 报告日期 | 2026-10-15 |
| 阶段 | 阶段 02（前置 SPIKE） |
| 目的 | 在写业务代码之前，验证「SSH 连接层到底怎么实现」这一最大不确定项 |
| 结论 | **原定路线（D-004）被推翻，改为原生 SFTP v3 协议（D-011）** |

## 2. SPIKE 目标

规划文档 §12 要求「先验证最小链路」。原设计（`docs/DECISIONS.md` D-003/D-004）
把连接层定为「调 `sftp` CLI + 解析 `ls -l` 文本」。本 SPIKE 要回答三件事：

| 问 | 假设检验 |
|---|---|
| Q1 | `sftp -b -` 的文本输出能否被可靠解析？ |
| Q2 | 是否可能拿到**结构化的**远程文件元数据？ |
| Q3 | 若 Q2 成立，它在本项目的运行环境（Windows 宿主 + OpenSSH 9.5p2 + 密码/密钥认证）中是否可用？ |

## 3. 测试床（因阻塞而先行搭建）

原定的集成目标 CentOS 虚拟机**未开机**，本机 Windows **无 sshd 且无提权**。
为不中断 SPIKE，搭建了一台零提权的本地测试目标：

- **位置**：WSL2 Ubuntu 内，以**普通用户**身份运行的 `sshd`
- **监听**：`127.0.0.1:2222`（WSL2 的 localhost 转发让 Windows 侧直连）
- **安装方式**：从 Ubuntu pool 直接取 `openssh-server_9.6p1-3ubuntu13.20_amd64.deb` 与
  `openssh-sftp-server_9.6p1-3ubuntu13.20_amd64.deb`，用 `dpkg -x` 解包到 `~/.awfm-testbed/root/`
  ——**全程不需要 root**（`apt-get download` 因 lists 陈旧返回 404，故绕过 apt）
- **关键配置**：`StrictModes no`、`UsePAM no`、`PasswordAuthentication yes`、
  `Subsystem sftp <tb>/root/usr/lib/openssh/sftp-server`
- **实测**：`ss -ltn` 确认 `LISTEN 0 128 127.0.0.1:2222`；Windows 侧
  `Test-NetConnection 127.0.0.1 -Port 2222` → `TcpTestSucceeded=True`

**非 root sshd 可行性结论**：可行。`sshd` 在非 root 下会跳过特权分离，
只要端口 ≥1024、且不自建 `/var/empty` 等特权路径即可正常服务。

**该测试床已登记为决策 D-012**，配套脚本 `scripts/testbed_wsl.sh`。

## 4. Q1 的答案：文本解析路线**可用但脆弱**——放弃

### 4.1 实测输出

在测试床上准备含中文、空格、emoji 的目录后，抓取 `sftp -b` 的真实 `ls -l` 输出：

```
drwx******    ? aimu     aimu         4096 Oct 15 00:06 sub
lrwx******    ? aimu     aimu           20 Oct 15 00:06 link 链接
-rw-******    ? aimu     aimu           12 Oct 15 00:06 中文 文件名.txt
-rwx******    ? root     root      2424984 Feb  1  2025 /init
```

### 4.2 五个不可回避的缺陷

| # | 缺陷 | 证据 |
|---|---|---|
| 1 | **权限位被客户端遮蔽** | 只保留文件类型位与属主三位，其余六位是 `*`；nlink 是 `?`。**P1 的「权限与属主展示」信息源本身已丢失** |
| 2 | 时间依赖人类可读格式与本地化 | 半年内 `%b %e %H:%M`、超过半年 `%b %e  %Y`（两个空格）。需 `TZ=UTC`+`LC_ALL=C` 打补丁 |
| 3 | 命令回显混入 stdout | 每条命令回显为 `sftp> <命令>`，末尾还有孤立 `sftp> ` |
| 4 | 批处理遇错即中止 | 一个失败命令会静默吞掉其后所有命令 |
| 5 | 名字含 ` -> ` 时 symlink 行不可解析 | `lrwx... 20 Oct 15 00:06 link 链接 -> ...` |

**判定**：这些缺陷来自「用人类可读界面承载结构化数据」这一**路线选择本身**，不是实现质量问题。
继续走下去只能靠不断加容错分支，且第 1 条**无法通过任何解析手段修复**。

### 4.3 顺带推翻的假设

原 D-004 设想的 `TZ=UTC` + `LC_ALL=C` 补丁**是必要的**（时区与月份缩写确实由客户端本地化决定），
但即便打上补丁也只能解决缺陷 2，解决不了 1、3、4、5。

## 5. Q2 的答案：**可以拿到原生 SFTP v3 协议通道**

### 5.1 前提验证：Windows `ssh.exe` 管道是否二进制安全

**这一步是整条路线的成败关键**——若 Windows 上存在 CRLF 转换或编码转换，协议帧会被破坏。

```python
subprocess.run(['ssh', ..., 'cat'], input=bytes(range(256)) * 4, capture_output=True)
# → 回程 1024 字节，与输入逐字节相同（IDENTICAL）
```

**结论：二进制安全，无任何转换。** 路线成立。

### 5.2 取得协议通道的方式

```
ssh -p <port> -i <key> -o UserKnownHostsFile=<kh> -o StrictHostKeyChecking=yes \
    -o BatchMode=yes -o LogLevel=ERROR <user>@<host> -s sftp
```

`-s sftp` 让 ssh 请求远端的 `sftp` 子系统，随后 stdin/stdout 即成为**裸 SFTP 协议双向流**，
与远端 `sftp-server` 进程直接对话，中间**没有任何客户端解析层**。

### 5.3 协议要点（实现必须钉死的部分）

**帧格式**：`uint32 长度` + `byte 类型` + 负载。长度**含**类型字节，**不含**长度字段自身。

**★ 最高频错误源 1：服务端响应包的第一个字段是请求 id。**
初版实现漏读 id，导致 `REALPATH`/`STAT` 全部解析错位。正确布局：

| 包 | 布局 |
|---|---|
| `SSH_FXP_NAME(104)` | `id + count + count×[filename(string), longname(string), ATTRS]` |
| `SSH_FXP_STATUS(101)` | `id + code(uint32) + message(string) + lang(string)` |
| `SSH_FXP_HANDLE(102)` | `id + handle(string)` |
| `SSH_FXP_DATA(103)` | `id + data(string)` |
| `SSH_FXP_ATTRS(105)` | `id + ATTRS` |

**`ATTRS` 结构**：`uint32 flags` + 按 flags 位出现的字段
（`1`=SIZE(uint64)、`2`=UIDGID(uint32,uint32)、`4`=PERMISSIONS(uint32)、
`8`=ACMODTIME(atime,mtime)、`0x80000000`=EXTENDED）。

**★ 最高频错误源 2：`MKDIR`/`SETSTAT` 的属性字段是完整 ATTRS，不是裸 `uint32`。**
初版直接发 `struct.pack(">I", 0o755)`，`sftp-server` 解析失败后直接 `fatal()` 退出，
客户端观察到的是 `EOFError: EOF poll=None` —— **错误现象与真实原因相距极远**。
正确写法：`struct.pack(">II", 4, 0o755)`（flags=PERMISSIONS + 模式）。

**本 SPIKE 用到的操作码**：INIT(1)/VERSION(2)、OPEN(3)、CLOSE(4)、READ(5)、WRITE(6)、
LSTAT(7)、SETSTAT(9)、OPENDIR(11)、READDIR(12)、REMOVE(13)、MKDIR(14)、RMDIR(15)、
REALPATH(16)、STAT(17)、RENAME(18)、READLINK(19)、SYMLINK(20)。

**STATUS 码**：0 OK / 1 EOF / 2 NO_SUCH_FILE / 3 PERMISSION_DENIED / 4 FAILURE /
5 BAD_MESSAGE / 6 NO_CONNECTION / 7 CONNECTION_LOST / 8 OP_UNSUPPORTED / 9 INVALID_HANDLE。

**OPEN 的 pflags**：READ=0x1、WRITE=0x2、APPEND=0x4、CREAT=0x8、TRUNC=0x10、EXCL=0x20。

### 5.4 实测结果（全部通过）

| 验证项 | 结果 |
|---|---|
| `INIT` 协商 | 服务端回 `VERSION`，version=3 |
| `REALPATH(".")` | `/home/aimu` |
| `REALPATH` 含 `..` | `/home/aimu/awfm test dir/../awfm test dir` → `/home/aimu/awfm test dir`（服务端折叠） |
| `STAT` 普通文件 | `flags=15`，`perm=33188(0o100644)`、`size=12`、`uid=1000`、`gid=1000`、`atime/mtime` 为 **epoch 整数** |
| **权限位是否遮蔽** | **未遮蔽** —— 拿到完整 `0o100644`。CLI 的 `******` 纯属客户端显示行为 |
| `STAT` 大文件 | `size=58435601`（58 MB）准确 |
| `LSTAT` 符号链接 | `perm=41471(0o120777)`、`size=20`（链接目标长度） |
| `STAT` 同一符号链接 | 跟随到目标：`perm=0o100644`、`size=12` |
| `STAT` 不存在路径 | `STATUS code=2 "No such file"` |
| `OPENDIR`/`READDIR` | 返回 `.`、`..` 与全部条目，终点为 `STATUS code=1 "End of file"` |
| **文件名保真** | `'中文 文件名.txt'`、`'link 链接'`、`'emoji🎉'` 全部原样正确 |
| `READ` 流式 | 内容逐字节正确（`b'hello awfm\\n'`） |
| `MKDIR` | `STATUS 0 Success`；父目录不存在 → `STATUS 2` |
| `RENAME` / `RMDIR` / `REMOVE` | 均 `STATUS 0` |
| **`WRITE` 流式上传** | `OPEN(0x1a) + WRITE(64 KiB 分块) + CLOSE` 上传 **256000 字节**，随后 `STAT` 校验 `size=256000` **完全一致** |

**READDIR 的顺序不保证**，客户端必须自行排序。

### 5.5 附带发现的 Windows 陷阱

Python 在 Windows 上默认 stdout 编码是 **GBK**。向控制台打印含 emoji 的文件名
（`🎉` U+1F389）会抛 `UnicodeEncodeError: 'gbk' codec can't encode character '\U0001f389'`
并终止程序。文件管理器必然要处理非 ASCII 文件名，因此**已登记为决策 D-013**：
显式将 stdout/stderr `reconfigure(encoding="utf-8")`，日志与 JSON 一律显式 UTF-8。

## 6. Q3 的答案：在目标环境中可用

| 前提 | 实测 |
|---|---|
| Windows 有 `ssh.exe` | 是（`OpenSSH_for_Windows_9.5p2`） |
| 管道二进制安全 | 是（§5.1，1024 字节逐字节相同） |
| 目标机有 SFTP 子系统 | 是（Ubuntu `sftp-server`；CentOS 的 `openssh-server` 同样自带） |
| 密钥认证可组合 | 是（`-i` + `UserKnownHostsFile` + `StrictHostKeyChecking=yes` 实测连通） |
| 与已知 `known_hosts` 机制兼容 | 是 |

## 7. 发现的问题

### 7.1 R-04：Windows 的 `ssh-keyscan` 不可用（**未解决，已给出方案**）

```powershell
ssh-keyscan -p 2222 -t ed25519 127.0.0.1
# # 127.0.0.1:2222 SSH-2.0-OpenSSH_9.6p1 Ubuntu-3ubuntu13.20
# debug1: kex: algorithm: sntrup761x25519-sha512@openssh.com
# choose_kex: unsupported KEX method sntrup761x25519-sha512@openssh.com
# 退出码 1，无任何 host key 行
```

同一台机器上 `ssh -Q kex` 列出的算法**不含 `sntrup761x25519-sha512@openssh.com`**，
而该算法恰是现代 OpenSSH 服务端的**首选 KEX**。`ssh-keyscan` 未能降级协商，直接失败。

**影响**：规划文档 §10.1 要求「首次连接提供可信指纹确认」，原计划用 `ssh-keyscan` 取指纹。

**替代方案（登记为 P-005，阶段 03 实现）**：
不调用 `ssh-keyscan`，而是用一个**临时 `UserKnownHostsFile`** 加
`-o StrictHostKeyChecking=no` 连一次，让 `ssh` 自己把服务端 host key 写进该临时文件，
再从文件里读出指纹呈现给用户确认。若用户接受，才写入项目自有的 `data/known_hosts`。
此方案**与 OpenSSH 版本无关**，且复用 ssh 自身的算法协商。

**安全说明**：`StrictHostKeyChecking=no` 在此**仅用于向临时文件收集候选密钥**，
收集到的密钥在用户确认之前**不得**写入 `data/known_hosts`，也不得用于任何实际的文件操作；
这与「静默接受新密钥」（验收项 T-005 禁止）有本质区别。

### 7.2 R-05：`icacls` 继承设置导致文件不可读（已解决）

对目录执行 `icacls <dir> /inheritance:r /grant:r "$env:USERNAME:(R)"` 后，
该目录内的文件出现 `Get-Content ... 访问被拒绝 (UnauthorizedAccessException)`。

**修法**：`icacls <dir> /reset /T /C`。
**教训**：私钥权限**逐文件**设置（`icacls <file> /inheritance:r /grant:r "<完整主体名>:(R)"`），
不要对整个目录去继承。更稳妥的做法是私钥一律用 Windows `ssh-keygen` 在 Windows 侧生成，
只把公钥交给目标机。

## 8. SPIKE 结论

1. **Q1 答案**：可行但脆弱，且**权限位信息源已丢失**——放弃。
2. **Q2 答案**：**可以**，`ssh -s sftp` 提供原生二进制协议通道，Windows 管道二进制安全。
3. **Q3 答案**：在目标环境中**可用**。
4. **决策变更**：新增 **D-011**（连接层 = 原生 SFTP v3 协议），
   **D-004 作废**，**P-001/P-003/P-004 作废**（问题本身消失），新增 **P-005**（取指纹方案）。
5. **能力升级**：P1 的「权限与属主展示」由**不可能**变为**可实现**；
   结构化 `STATUS` 码让错误映射不再依赖匹配英文错误串。

**允许进入阶段 03。** 连接层基线已确定且经端到端实测，
协议实现所需的两个高危错误点（响应包 id 前缀、ATTRS 属性字段）已在本文档中记录，
将在单元测试中钉死。
