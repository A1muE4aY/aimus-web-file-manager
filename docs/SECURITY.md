# AWFM 安全设计与威胁模型

> 本文逐条说明 AWFM v0.1.0 如何落实规划文档 §10 的七条安全要求，并给出威胁模型、代码位置与**残余风险**。安全设计的原则是：不把「离线」当成「安全」，也不把「只监听回环」当成安全边界。
>
> 文档日期 **2026-10-15** · 对应版本 `app/__init__.py:7`（`0.1.0`）· 相关决策 D-003、D-006、D-008、D-009、D-010、D-011、D-014

---

## 1 安全目标与信任边界

**要保护的东西**

| 对象 | 说明 |
|---|---|
| 目标机的文件系统 | 本工具持有目标机某个账号的读写能力，被误用等于该账号的权限被交出 |
| SSH 凭据 | 密码（内存中）、私钥路径与私钥文件（磁盘上，不属于本仓库） |
| 宿主机上的配置与信任库 | `data/config.json`、`data/known_hosts`——信任库被改写等于主机密钥校验失效 |
| 管理接口本身 | 能调用接口就能读目标机文件，因此接口等价于凭据 |

**信任边界**

| 边界 | 两侧 | 跨越方式 | 依靠什么 |
|---|---|---|---|
| 浏览器 ↔ 本地服务 | 不可信页面环境 / 本项目 | HTTP（回环） | 令牌、Host 校验、`Origin`/`Sec-Fetch-Site`、CSP |
| 本地服务 ↔ `ssh` 子进程 | 本项目 / 系统 OpenSSH | argv 列表 + 管道 | 不经 shell；凭据经 `SSH_ASKPASS` |
| `ssh` ↔ 目标机 | 本项目 / 外部主机 | SSH | 主机密钥校验（`strict`）+ 项目自有信任库 |
| 进程 ↔ 宿主机文件系统 | 本项目 / 操作系统 | 普通文件 I/O | 非管理员账户运行；私钥权限由用户自行收紧（§7） |

---

## 2 为什么「只监听 127.0.0.1」不是安全边界

默认只绑定回环（`server.host = "127.0.0.1"`）确实把「局域网里的其它机器」挡在外面，但它**挡不住浏览器**。下面三类攻击都不需要攻击者能连上 32579 端口，因为攻击载荷运行在用户自己的浏览器里，请求从浏览器内部、以「本机」身份发出（`app/api/security.py` 模块 docstring 详细记录了这三类）：

| 攻击 | 怎么发生 | 为什么回环绑定无效 |
|---|---|---|
| CSRF | 用户访问恶意页面，页面用表单提交或「简单请求」`fetch` 打 `http://127.0.0.1:32579/api/…` | 简单请求不触发预检，浏览器会**真的把请求送达并执行**——服务端收到的是一个完全合法的本机请求 |
| DNS 重绑定 | 攻击者把自己的域名解析到 `127.0.0.1`，浏览器认为「同源」，于是允许页面读取响应 | 请求目标仍是回环地址；只要服务端不看 `Host`，它无法区分「用户自己打开的页面」和「攻击者的页面」 |
| 来源伪装 | 攻击者直接构造 `Origin` / `Sec-Fetch-Site` 以外的路径（例如用 `no-cors` 请求、或用不带这些头的旧式客户端） | 这两个头由浏览器填充，服务端**必须校验**，不能假设它们一定正确 |

**本项目的三重对策**（`app/api/security.py:132` `verify_api_request` 固定顺序）：

1. `check_host_header`（`security.py:56`）：`Host` 的主机名必须是 `127.0.0.1` / `localhost` / `::1`（`security.py:44` `ALLOWED_HOSTS`），否则 `invalid_request`（400，「请求的 Host 头不是本机地址，已拒绝。」）。这一条专治 DNS 重绑定——攻击者域名解析到回环后，`Host` 仍然是攻击者的域名。无 `Host` 头（HTTP/1.0）放行，因为浏览器一定会发 `Host`，不存在重绑定空间；`security.allow_lan = true` 时该检查跳过（那时仅靠 Host 已无法表达信任范围）。
2. `check_fetch_metadata`（`security.py:84`）：`Sec-Fetch-Site` 只允许 `none`（地址栏、书签）与 `same-origin`；请求带 `Origin` 时必须是回环来源（`security.py:102` `_is_loopback_origin`）。其它情况一律 `unauthorized`（401，「跨站请求已被拒绝。」）。
3. `check_token`（`security.py:115`）：`X-AWFM-Token` 必须与服务启动时生成的令牌一致（`secrets.compare_digest` 定时安全比较）。未提供 → 「缺少会话令牌，已拒绝。」；不一致 → 「会话令牌不正确，已拒绝。」（`detail` 提示「服务可能已重启，请刷新页面。」）。

另外，`do_OPTIONS`（`app/api/http_server.py:132`）对预检请求**一律返回 403** 且不返回任何 `Access-Control-Allow-*` 头——本项目没有跨源使用的需求，任何跨源预检都是可疑的。

**这三重对策的定位要看清**：它们防的是「浏览器里的另一个页面」借用户的浏览器去打本机服务。它们**不是**对本机其它进程或其它用户的隔离手段——令牌注入在 `frontend/index.html` 里，而静态资源不参与令牌校验（只有 `/api/` 前缀才走 `verify_api_request`），因此一个能在本机打开回环地址的进程可以取到页面、读到令牌，再调用 API。规划文档 §10 的结论与此一致：「离线不等于安全——本机其他进程/用户能访问管理接口即存在风险」。要真正缩小这一范围，需要操作系统级隔离或进程级鉴权，属于规划文档 §10③ 要求「将来单独设计」的范畴（见 §5、§6）。

---

## 3 规划文档 §10 七条要求的落实

### 3.1 要求①：SSH 主机密钥验证

> **要求**：首次连接时提供可信指纹供用户确认；主机密钥变化时不得自动覆盖或忽略警告。
> **实现**（两条路径，都在 `app/services/session.py:156` `_do_connect`）：

| 情形 | 行为 |
|---|---|
| 信任库里已有该主机的记录 | 直接连接，接受与否**完全交给 `ssh` 的 `StrictHostKeyChecking`**；连接失败且 stderr 命中主机密钥问题 → 重新采集（`app/ssh/known_hosts.py:196` `collect_host_keys`）→ 抛 `HostKeyMismatch`，`detail` 写明「本程序不会自动覆盖」，`extra` 里同时给出**信任库指纹**与**当前指纹**两组数据 |
| 信任库里没有记录（且策略不是 `accept-new`） | 采集候选密钥 → 抛 `HostKeyUnknown`（409），`extra.fingerprints` 是待确认的指纹列表；**不写信任库** |

- **没有「一键接受」**：界面只展示指纹并要求人工确认（`frontend/assets/js/connections.js:340` `confirmUnknownHostKey`、`:416` `showHostKeyMismatch`、`:411` `knownHostsHint`），密钥变化时告诉用户去改 `known_hosts_path`（该路径由 `GET /api/session` 返回，`app/api/handlers.py:48` 的注释说明了这个设计意图）。
- **确认即复核**：用户确认后调 `POST …/host-keys/trust`，`ConnectionManager.trust_host_key`（`app/services/connection_manager.py:288`）**重新采集一次**目标机当前密钥，要求它包含用户确认过的指纹；不一致就拒绝写入（「目标机当前提供的主机指纹与用户确认的不一致，已拒绝写入信任库。」）——否则「用户确认」只是走个形式。
- **写入只发生在一个地方**：`append_trusted_key`（`app/ssh/known_hosts.py:159`）明确「调用方必须已在用户层完成确认」，函数本身不做任何确认；写入用原子覆盖（`app/utils/atomic.py`）而不是 append——半行 `known_hosts` 会让 `ssh` 报出与真实原因无关的解析错误。写入时会加一行注释「`# AWFM 于 <UTC 时间> 由用户确认后加入`」。
- **信任库是项目自有的**：`UserKnownHostsFile` 与 `GlobalKnownHostsFile` **都**指向 `data/known_hosts`（`app/ssh/ssh_launcher.py:96` `build_sftp_command`）。否则用户 `~/.ssh/known_hosts` 里的旧记录会让「首次确认」被静默跳过（决策 D-010）。
- **指纹算法与用户能对照的形式一致**：`fingerprint_of`（`app/ssh/known_hosts.py:87`）= 公钥 base64 解码 → SHA-256 → base64 → 去掉尾部 `=` → 前缀 `SHA256:`，与 `ssh-keygen -lf` 的输出逐字符相同。
- **采集方案（待决策 P-005）**：`collect_host_keys` 用「临时 `UserKnownHostsFile` + `StrictHostKeyChecking=no` 连一次，让 `ssh` 自己完成算法协商并把服务端密钥写进临时文件再读回」。之所以不用 `ssh-keyscan`：阶段 01/02 实测本机 OpenSSH_for_Windows_9.5p2 对测试床失败（`choose_kex: unsupported KEX method sntrup761x25519-sha512@openssh.com`，退出码 1，未产出任何密钥行），而 `ssh-keyscan` 不会降级协商（风险项 R-04）。该方案的安全性有三点支撑：① 主机密钥校验发生在**认证之前**，即使没有可用凭据 `ssh` 也已经写完密钥；② 临时文件一次性、`finally` 里 `rmtree`，采集到的密钥在用户确认前**不写入**项目信任库；③ 采集阶段 `BatchMode=yes`，不可能因等待密码输入而挂住。与「静默接受新密钥」的本质区别是：`StrictHostKeyChecking=no` 只作用于那一个临时文件。
- **端口写法**：非 22 端口在 `known_hosts` 里必须写成 `[host]:port`（`host_key_pattern`，`app/ssh/known_hosts.py:105`），写成 `host:port` 会被 `ssh` 当成「主机名里含冒号」而静默忽略整行。

**残余风险**

- 首次确认仍然依赖用户**肉眼比对**指纹。若在第一次连接时就有中间人，用户照抄了他提供的指纹，信任就被建立——这是所有 TOFU（首次使用即信任）方案的共同边界，缓解手段是在界面上展示完整 SHA-256 指纹并提示用另一条渠道核对（例如在目标机上执行 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`）。
- 哈希化的 `known_hosts` 行（`|1|` 开头）无法反推主机名，因此**看不到**这些记录；`looks_like_hashed_hosts`（`app/ssh/known_hosts.py:275`）只用于在界面上解释这一点。
- `_translate_connect_error`（`app/services/session.py:236`）通过匹配英文提示串（`host key verification failed` 等）来增强诊断。这是**有意取舍**：匹配不中只会退化为原始错误，不会产生错误的安全结论；但可能少给用户一组指纹。判定本身始终由 `ssh` 做出。

### 3.2 要求②：密钥与凭据保护

> **要求**：私钥不得经 API 返回浏览器；优先使用 `ssh-agent` 或本地密钥文件；避免明文保存密码。
> **实现**：

| 措施 | 代码位置 |
|---|---|
| 密码**从不**写入配置文件：`Connection` 数据类里没有密码字段，`to_dict()` 只序列化 id/name/host/port/username/auth_method/identity_file/note/allow_write/created_at/updated_at | `app/models/connection.py:120` |
| 私钥内容与私钥路径都不出现在设计上给前端的结构里：`to_public_dict()` 与 `to_dict()` **刻意分成两个方法**，将来加入任何敏感字段只需改一处，所有 API 出口自动安全（若只写一个方法就必须逐个检查每个响应构造点，那是会漏的） | `app/models/connection.py:136`（验收项 T-011） |
| 密码只在 `POST /api/connections/{id}/connect` 的请求体里传入一次，只存在于内存会话对象，断开即丢弃；日志过滤器还会再过一道 | `app/api/handlers.py:84` |
| 密码经 `SSH_ASKPASS` 传递：生成**不含秘密**的包装脚本（`askpass.cmd`，内容恒定）→ 由 `AWFM_ASKPASS_FILE` 环境变量指向的秘密文件提供内容；**密码本身不进环境变量**（Windows 上同用户的其它进程可以读环境变量） | `app/ssh/askpass.py:98` `prepare_askpass`、`ssh_launcher.py:153` `build_environment` |
| 秘密文件用 `newline=""` 写入且不加换行（密码可能合法地以空格结尾），POSIX 上 `chmod 0600`、包装脚本 `0700` | `app/ssh/askpass.py:98` |
| 认证结束后**立即销毁**临时目录（`bundle.cleanup()` 在 `_do_connect` 的 `finally` 里），准备阶段任何异常也会 `rmtree` 后再抛 | `app/services/session.py:156`、`app/ssh/askpass.py:84` |
| `ssh` 参数按认证方式收窄：密钥模式 `BatchMode=yes` + `PreferredAuthentications=publickey`；密码模式 `BatchMode=no` + `NumberOfPasswordPrompts=1` + `PreferredAuthentications=password,keyboard-interactive,publickey` + `SSH_ASKPASS_REQUIRE=force` | `app/ssh/ssh_launcher.py:96`、`ssh_launcher.py:153` |
| 只有用户显式指定 `identity_file` 时才加 `-i`，并同时加 `IdentitiesOnly=yes`——否则 `ssh-agent` 里其它密钥会先被试一遍，在有登录失败次数限制的目标机上可能把账号锁掉 | `app/ssh/ssh_launcher.py:96` |

**两点值得写进文档的取舍**

- `BatchMode=yes` 会**彻底禁用密码认证**——这不是文档说明，而是 OpenSSH 源码 `auth2-passwd.c` 的行为：`userauth_passwd()` 开头就是 `if (options.batch_mode) return 0;`。所以密码模式必须 `BatchMode=no`（决策 D-008）。
- `SSH_ASKPASS` **只接受一个可执行文件路径、不能携带参数**（待决策 P-002），所以要求「包装脚本 + 辅助程序」两层结构；Windows 上没有 `#!/bin/sh`，生成的是 `.cmd`。若某环境上 `.cmd` 不可用，密码认证会明确失败并给出 stderr，而**不会静默降级**成别的认证方式。

**残余风险**

- 密码在认证期间以明文形式存在于系统临时目录中的文件里（典型时长不足一秒，认证完成即删除）。防护依赖该临时目录的权限；Windows 上的 `mkdtemp` 目录继承用户配置文件的 ACL，同机**同用户**的进程理论上仍可读。
- 密码在内存中以 Python 字符串形式存在，本版不做内存擦除。
- `identity_file` 的路径由用户填写，本项目不校验其内容或权限；私钥文件本身的保护是用户的责任（§7）。

### 3.3 要求③：本地服务的访问控制

> **要求**：默认绑定 `127.0.0.1`；开放局域网必须单独增加身份验证与 Web 安全防护。
> **实现**：

| 措施 | 代码位置 |
|---|---|
| 默认监听 `127.0.0.1:32579` | `app/core/config.py` `DEFAULTS["server"]` |
| `security.allow_lan = false`（默认）时，非回环绑定**直接拒绝启动**并抛 `ConfigError`，**不静默改回 `127.0.0.1`**——绑错地址的后果是整台机器的文件可被局域网读取，静默纠正会让风险不可见 | `app/core/config.py:178` `validate_binding` |
| 该校验跑**两次**：启动前一次，命令行 `--host`/`--port` 覆盖之后再一次（先用 `--host 0.0.0.0` 把服务开起来、事后再问 `allow_lan` 就太晚了） | `app/main.py:140` `_apply_overrides` 之后 |
| 只监听本机时，访问控制由「令牌 + Host 校验 + 来源校验」共同承担（§2、§3.5） | `app/api/security.py:132` |
| `allow_lan = true` 时 Host 校验按配置跳过，风险必须在配置与文档中说明 | `app/api/security.py:56` |

**残余风险**

- `allow_lan = true` 时**没有任何身份验证**：任何能访问该端口的机器都可以调用全部接口。规划文档 §10③ 要求这一场景「单独增加身份验证与 Web 安全防护」，属于**尚未实现、也不在本版范围内**的功能（§6）。
- 回环地址对**本机所有用户**都是可达的，令牌才是实际屏障；而令牌注入在 `index.html` 中，静态资源不参与令牌校验（§2 结尾、§5）。

### 3.4 要求④：路径校验

> **要求**：禁止 `..` 穿越、绝对路径变体、编码绕过；正确处理符号链接与远程文件系统的路径语义。
> **实现**：

| 措施 | 代码位置 |
|---|---|
| **不做词法 `..` 折叠**（核心决定）：把 `/home/a/link/../x` 折叠成 `/home/a/x` 看似合理但语义错误——若 `link` 是指向 `/etc` 的符号链接，POSIX 的真实解析结果是 `/x`。SFTP v3 的路径由**服务端**按目标机文件系统语义解析，客户端词法折叠会改变语义，属于把安全表演当成安全 | `app/utils/paths.py` 模块 docstring |
| 三条策略：① 只校验形式、不改写语义（`validate_remote_path`）；② 需要规范形态时向服务端要 `REALPATH`；③ 需要目录限制时比较**服务端返回的规范路径** | `app/utils/paths.py:58`、`app/ssh/sftp_client.py:45` |
| 所有远程操作前都先 `REALPATH`：`resolve_path()` 是目录/元数据/预览/传输路径的统一入口 | `app/services/filesystem.py:47` |
| 形式校验（`validate_remote_path`）：必须是字符串、非空、以 `/` 开头（相对路径会让「当前目录」变成隐式状态）、不含 `NUL`、UTF-8 字节数 ≤ 4096（`MAX_PATH_BYTES`，对应 Linux `PATH_MAX`） | `app/utils/paths.py:58` |
| 名称分量校验（`validate_remote_name`，用于上传文件名等单分量场景）：非空、不是 `.`/`..`、不含 `/`、不含 `NUL`、≤255 字节（`MAX_NAME_BYTES`，对应 Linux `NAME_MAX`） | `app/utils/paths.py:80` |
| 长度按 **UTF-8 字节数**而不是字符数计算（`_byte_len`；`中` 是 1 个字符、3 个字节，而目标机的限制是字节） | `app/utils/paths.py:49` |
| 连接 id 收窄字符集（`^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`），**禁止 `/` 与 `..`**——它会成为 URL 路径分量，否则 `/api/connections/<id>/files` 可能被解析成别的资源 | `app/models/connection.py:33` |
| 目录限制工具 `is_within_root()`：**含 `..` 分量的路径一律判 False（fail-closed）**——调用方本应传 `REALPATH` 结果，真出现 `..` 说明规范化被漏掉了，此时按字符串前缀比较会放行 `/home/a/../b` 这类「看起来在 root 内、实际在 root 外」的路径 | `app/utils/paths.py:134` |
| 静态资源路径同样处理：拒绝 `\` 与 `NUL`、拒绝 `.`/`..` 分量，`resolve(strict=True)` 之后必须仍在 `frontend/` 之内（第二道防线，防符号链接逃逸）；不存在的静态路径返回 404 而不是 400 | `app/api/http_server.py:210` `_serve_static`、`:267` `_is_within` |
| 字符集策略：除 `NUL` 外**不拒绝任何字符**（含换行与其它控制字符）。SFTP 用长度前缀字符串传输路径，能原样承载它们；拒掉只会让这些文件永远无法被管理，而没有安全收益。真实风险在**日志注入**与 **HTTP 头注入**，分别在下面两处处理 | `app/utils/paths.py` 模块 docstring |
| 本项目**从不把远程路径交给 shell**：两处子进程调用都是 argv 列表（源码注释 `# noqa: S603 - argv 列表，不经 shell`），没有 `shell=True` | `app/ssh/sftp_transport.py:111`、`app/ssh/known_hosts.py:237` |

**残余风险**

- 按设计，本项目**不做根目录限制**：用户可以浏览、读取该 SSH 账号在目标机上能访问的任何路径。这是文件管理器的功能目标，不是漏洞；能力的边界是目标机账号的权限，而不是本项目的路径检查。
- `is_within_root()` 当前是留给需要「限制在某个根目录内」的场景的工具（例如将来的 P2 写操作），本版的浏览流程不使用它。
- 服务端 `REALPATH` 的结果遵循目标机的符号链接语义。客户端**刻意**不二次判断「最终位置是否还在预期目录内」——如果要做，必须由未来的写操作显式设计根目录策略。

### 3.5 要求⑤：请求保护

> **要求**：校验方法、参数、来源与会话权限；使用 Cookie 会话时要考虑 CSRF。
> **实现**：

| 措施 | 代码位置 |
|---|---|
| 会话凭证是**自定义请求头** `X-AWFM-Token`，不是 Cookie——因此浏览器不会自动携带它，天然没有 CSRF 的会话状态可被借用 | `app/api/security.py:115` |
| 令牌每次启动重新生成（`secrets.token_urlsafe(32)`），只存内存 | `app/api/security.py:51` |
| 来源校验（`Sec-Fetch-Site`、`Origin`）与 Host 校验，顺序固定且对 `/api/health` 也生效 | `app/api/security.py:132` |
| 预检一律 403，不发任何 CORS 允许头 | `app/api/http_server.py:132` |
| 方法校验：路由器按 `^pattern$` 匹配，命中路径但方法不符时返回 `invalid_request`（400）并在 `detail` 里列出允许的方法 | `app/api/router.py:49`、`app/api/http_server.py:179` |
| 参数校验：`require_query`（缺失或空串都拒绝）、`query_bool`（只接受固定取值）、`query_int` | `app/api/request.py:47`、`:53`、`:64` |
| 请求体限额：JSON 体默认 1 MiB（`MAX_JSON_BODY`），超限 `payload_too_large`；保存在线编辑按 `security.max_edit_bytes` 放宽（`text_body_limit()`），其余接口不动 | `app/api/request.py:24`、`:34`、`:92` |
| 会话权限：所有文件端点都经 `ConnectionManager.session()` 取**已连接**的会话；连接不存在 → `connection_not_found`（404），存在但未连接 → `session_not_found`（404），两种都不会绕过会话直接读远端 | `app/services/connection_manager.py:235` |
| 写权限：连接级开关 `allow_write`，默认关闭；上传前由 `require_write_permission` 把门，未开启抛 `unauthorized`（「该连接未开启写权限，无法上传文件。」）——这是最内层的一道门禁，即使上层漏判也写不动 | `app/services/filesystem.py:179` |
| 连接纪律：请求体没读完的请求，响应后强制断开连接，避免 keep-alive 连接上的字节错位；回错误前先排空请求体（超时 5 秒） | `app/api/http_server.py:144` 的 `finally` 段、`:217` `_discard_request_body` |
| 下载另走短时票据（120 秒、绑定连接与路径、仅内存），避免把长期令牌放进 URL（URL 会留在浏览器历史里，而且令牌能调用全部接口） | `app/api/tickets.py`、`app/api/security.py:132` |

**残余风险**

- 令牌注入在 `index.html` 里，而静态资源不校验令牌：能访问回环端口本机进程可以取到令牌。这是本版接受的边界（§2 结尾）。
- 令牌在整个进程生命周期内有效（默认 `security.session_token_ttl_seconds = 43200`，12 小时，作为配置项存在）；服务重启即失效。本版**没有**逐请求的会话过期与吊销机制。

### 3.6 要求⑥：日志脱敏

> **要求**：不记录密码、私钥内容、认证令牌、完整敏感配置。
> **实现**：

| 措施 | 代码位置 |
|---|---|
| 脱敏在**日志格式化阶段统一执行**，而不是要求每个调用点自己小心——调用点会漏，一条 `logger.debug("ssh 命令：%s", cmd)` 就足以把敏感串漏出去，而漏掉的日志没人会回头检查 | `app/utils/redact.py` 模块 docstring |
| `RedactingFilter` 同时挂在文件处理器与 stderr 处理器上 | `app/utils/logging_setup.py:30` `setup_logging` |
| 三类正则：PEM 私钥块整段替换；命令行里的 `-i <私钥路径>`；`password=…`/`passwd:…`/`token=…`/`secret=…`/`api_key=…` 等键值对 | `app/utils/redact.py:42` `redact` |
| **参数先按键名脱敏**（`%(password)s` 这类记录的唯一救回点——格式化之后键名就消失了，光看值 `hunter2` 无从判断它是不是密码）；字典按**键名**匹配，因此给日志传参优先用字典风格 | `app/utils/redact.py:89` `_redact_args` |
| 替换后**清空 `record.args`**：消息已是成品，若留着 `args` 而模板里的 `%s` 已被吃掉，格式化器会再插值一次并抛 `TypeError: not all arguments converted during string formatting`——脱敏反倒把日志弄坏 | `app/utils/redact.py:69` `filter` |
| 过滤器永不抛异常、始终放行记录 | `app/utils/redact.py:69` |
| 占位符统一为 `***已脱敏***` | `app/utils/redact.py:39` `PLACEHOLDER` |
| 远端字符串（文件名、主机标签）进日志前过 `safe_for_log()`：攻击场景是「远程文件名 `evil\n2026-01-01 ERROR 认证成功`」——直接插进日志会**伪造出一条不存在的日志行**；这里把控制字符转义成 `\xNN` 并截断（超长加 `...(+N)`） | `app/utils/paths.py:154` |
| 连接失败时给用户的诊断只取最后 6 行并逐行脱敏，**不返回完整 stderr**（可能含主机名、用户名等） | `app/ssh/sftp_transport.py:308` `diagnostics` |
| 日志轮转：单文件 2 MiB、保留 3 个备份（程序可能连续跑几个月，不轮转会把磁盘写满而用户不会想到清它）；日志写 `logs/`，不写 `data/` | `app/utils/logging_setup.py:30` |

**残余风险**

- 脱敏是启发式正则：未知格式的秘密（例如用户把密码写进连接的 `note` 字段、再被某条日志打印）不会被识别。**不要把秘密写进任何配置字段**。
- 日志文件是明文且不加密，同机可读；它记录的是连接标识与操作路径，不记录文件内容（下载/上传只记字节数与路径）。

### 3.7 要求⑦：传输安全（大小、并发、超时、临时文件设限）

> **要求**：对文件大小、并发连接数、超时与临时文件设置上限。
> **实现**：

| 类别 | 限制 | 默认值 | 代码位置 |
|---|---|---|---|
| 上传大小 | `security.max_upload_bytes` | 2147483648（2 GiB） | `app/core/config.py` `DEFAULTS`；校验在 `app/services/transfer.py:102` |
| 下载大小 | `security.max_download_bytes`（`0` = 不限） | 0 | `app/services/transfer.py:44` `prepare_download` |
| 文本预览 | `DEFAULT_PREVIEW_BYTES`，且接口层再夹一次 `[1, 262144]` | 262144（256 KiB） | `app/services/filesystem.py:38`、`app/api/handlers.py:147-148` |
| 单次列目录条目 | `MAX_LIST_ENTRIES`（先排序再截断） | 5000 | `app/services/filesystem.py:41` |
| JSON 请求体 / 响应体 | `MAX_JSON_BODY` / `MAX_JSON_BYTES`（文本保存按 `security.max_edit_bytes` 放宽） | 1 MiB / 8 MiB | `app/api/request.py:24`、`:34`、`app/api/responses.py:29` |
| 单个 SFTP 帧 | `MAX_FRAME_BYTES`（同时让「把 ASCII 当长度」立刻暴露，而不是试图分配几个 GB） | 4 MiB | `app/ssh/sftp_protocol.py:135` |
| 单次读写块 | `MAX_READ_CHUNK` / `DEFAULT_CHUNK_SIZE` | 64 KiB（D-007） | `app/ssh/sftp_protocol.py:130`、`app/ssh/sftp_client.py` |
| 单次 WRITE 帧 | `MAX_WRITE_CHUNK`（超过就拆帧；服务端整包上限 `OPENSSH_MAX_PACKET_BYTES` = 256 KiB，超限会被 sftp-server 掐断连接） | 64 KiB（D-007、D-019） | `app/ssh/sftp_protocol.py`、`app/ssh/sftp_client.py` `write_chunk` |
| 并发会话 | `ssh.max_sessions`，达到上限时**回收连接时间最早的那条**（而不是拒绝新连接） | 4 | `app/services/connection_manager.py:267` |
| 连接超时 | `ssh.connect_timeout_seconds`（同时用于 `ConnectTimeout` 与采集主机密钥） | 15 秒 | `app/core/config.py`、`app/ssh/ssh_launcher.py:96` |
| 操作超时 | `ssh.command_timeout_seconds` 作为 `SftpTransport` 的 `operation_timeout`；超时由看门狗线程杀进程打断 | 60 秒 | `app/ssh/sftp_transport.py:326` `transact`、`:154` `_start_watchdog` |
| 保活 | `ServerAliveInterval` + `ServerAliveCountMax=3` | 30 秒 × 3 | `app/ssh/ssh_launcher.py:96` |
| 下载票据 | `DEFAULT_TTL` / `MAX_TICKETS` | 120 秒 / 256 张 | `app/api/tickets.py:39`、`:43` |
| 临时文件：上传 | `<目标名>.awfm-part-<8 位随机十六进制>`，写完 `RENAME` 到目标；失败即删（删不掉只记 warning，因为名字带随机后缀不会与用户文件混淆）；文件名里出现该保留串会被拒绝，防止用户上传一个「临时文件」去干扰别人的上传 | — | `app/services/transfer.py:41`、`:102`、`:171` |
| 临时文件：密码 | `awfm-askpass-` 目录，认证结束立即销毁 | — | `app/ssh/askpass.py:98` |
| 临时文件：主机密钥采集 | `awfm-hostkey-` 目录，`finally` 中 `rmtree` | — | `app/ssh/known_hosts.py:196` |
| 临时文件：配置写入 | 同目录 `.awfm-tmp-*`，`fsync` 后 `os.replace`，任何异常都先删除临时文件 | — | `app/utils/atomic.py:21` |
| 进程退出清理 | 关闭全部会话与 `ssh` 子进程（验收项 T-013） | — | `app/main.py` `_serve` 的 `finally`、`app/services/connection_manager.py:256` `disconnect_all` |

**残余风险**

- 默认上限偏宽松（上传 2 GiB、下载不限）：这是为了能传镜像文件；需要更严格的机器应在 `data/config.json` 里收紧。
- 覆盖已存在文件时只能直接截断写入（SFTP v3 的 `RENAME` 不能替换已存在目标），因此**覆盖中断会留下被截断的文件**——本版接受的取舍；新建文件走「临时名 + 改名」不受此影响。
- 「远端只写了一半却返回 OK」这类问题靠写完后**回读 `STAT` 校验字节数**兜底（`app/ssh/sftp_client.py:214` `upload_stream`），但仍无法发现「写对了大小、内容却不同」的情况（协议不提供校验和）。

---

## 4 响应头与内容安全策略

`security_headers()`（`app/api/responses.py:32`）给每个响应加上：

| 头 | 值 | 作用 |
|---|---|---|
| `X-Content-Type-Options` | `nosniff` | 禁止浏览器按内容猜类型 |
| `Referrer-Policy` | `no-referrer` | 不把本机地址泄漏给外部站点 |
| `X-Frame-Options` | `DENY` | 禁止被任何页面嵌套（防点击劫持） |
| `Cache-Control` | `no-store` | 目录列表与错误信息不留在浏览器缓存里 |
| `Content-Security-Policy` | 见下 | 把「前端不含在线资源」从约定变成浏览器强制 |

- HTML 响应：`default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'`
- 其它响应：`default-src 'none'; frame-ancestors 'none'`

CSP 的价值在于**它不依赖代码自律**：只要有人在 `frontend/` 里加了一个 CDN 脚本、在线字体或外链图片，浏览器会直接拒绝加载并报错——离线可用（验收项 T-002）与「不向外部泄漏访问行为」两件事同时得到了强制保证。`form-action 'none'` 还额外堵住了「页面里出现表单并提交到外部」的路径。

---

## 5 残余风险汇总

| 风险 | 现状 | 可能的改进方向（未实现） |
|---|---|---|
| `security.allow_lan = true` 时无身份验证 | 任何能访问该端口的机器都能调用全部接口 | 规划文档 §10③ 要求单独设计（TLS、认证、CSRF 防护、访问日志） |
| 本机其它进程/用户可访问管理接口 | 令牌注入在 `index.html`，静态资源不校验令牌；能打开回环端口的进程可取到令牌 | 进程级鉴权、操作系统级隔离，或只允许指定浏览器实例 |
| 首次确认依赖用户肉眼比对指纹 | TOFU 方案的固有边界 | 提供指纹二维码 / 与目标机输出的自动比对 |
| 哈希化的 `known_hosts` 记录无法匹配 | 只提示、不处理 | 支持解析哈希行需要主机名候选集，收益有限 |
| 密码在认证期间短暂落盘于系统临时目录 | 生命周期约为一次认证（通常 <1 秒），结束即删 | 用管道/命名管道代替文件传递 |
| 用户名与主机名会出现在日志与错误信息中 | 已按需脱敏，但连接标识本身需要可读 | 可配置的日志级别与字段裁剪 |
| 覆盖中断会留下被截断的目标文件 | 已知取舍（见 §3.7） | 先写临时文件再 `RENAME`——但 SFTP v3 不支持替换式改名，需改用其它策略 |
| 传输没有端到端校验和 | 只校验字节数 | 传输后比对摘要（协议不提供，需要额外往返） |

---

## 6 明确不做的事

- **不做账户体系与多用户**：本版是「一个进程、一个用户、一个令牌」的本地工具。
- **不做 TLS**：服务默认只在回环上监听；`allow_lan = true` 时不提供加密，这是**已知且未解决**的问题，不要用它跨越不可信网络。
- **不做配置加密**：配置文件里本来就没有秘密（决策 D-014）；私钥不进项目目录（`AGENTS.md` §3.4）。
- **不做操作审计与会话历史**：规划文档把「操作审计与会话历史」列为 P2；本版只有运行日志。
- **不做文件内容检查**：上传/下载按字节搬运，不做病毒扫描或类型白名单。
- **不做自动更新与在线依赖下载**：便携版不引入任何在线供应链（规划文档 §3.2）。

---

## 7 运维实操：收紧私钥权限（Windows）

Windows 上的 OpenSSH 会检查私钥文件的 ACL；权限过宽时会**拒绝使用**并报：

```
UNPROTECTED PRIVATE KEY FILE
Permissions for 'C:\Users\<你>\.ssh\id_ed25519' are too open.
```

用下面的命令关掉权限继承，只保留当前用户的读权限（在当前用户的 PowerShell 中执行）：

```powershell
icacls <key> /inheritance:r /grant:r "$($env:USERNAME):(R)"
```

把 `<key>` 换成私钥文件的完整路径。建议同时遵循阶段 02 报告 R-05 的教训：

- **逐文件设置权限，不要对私钥所在目录做整目录继承**——目录级的宽松 ACL 会被新文件继承，等于悄悄把权限放大回来；
- 私钥优先用 Windows 自带的 `ssh-keygen` 生成（格式与 `ssh.exe` 完全一致），只把 `.pub` 公钥内容交给目标机；
- 私钥**不要**放进项目目录（`config/`、`docs/`、`tests/fixtures/` 都在提交范围内，禁止存放凭据）；
- 连接配置里的 `identity_file` 填私钥的完整路径即可，本项目不会读取或复制私钥内容。

---

## 参考

本文依据以下源码与文档（路径相对项目根，正斜杠）：

- 规划文档：`.md`（§10 安全要求七条、§10.1 主机密钥、§10.2 凭据、§10.4 路径校验、§10.6 日志脱敏）
- `docs/DECISIONS.md`（D-003、D-006、D-008、D-009、D-010、D-011、D-014）、`docs/REQUIREMENTS.md`（T-005、T-011、T-013、N-02、N-07）
- `docs/reports/PHASE-01-ENVIRONMENT.md`、`docs/reports/PHASE-02-SPIKE.md`（R-04 `ssh-keyscan` 不可用、R-05 私钥权限教训）
- 安全实现：`app/api/security.py`、`app/api/tickets.py`、`app/api/http_server.py`、`app/api/responses.py`、`app/api/request.py`
- 凭据与主机密钥：`app/ssh/askpass.py`、`app/ssh/known_hosts.py`、`app/ssh/ssh_launcher.py`、`app/services/session.py`、`app/services/connection_manager.py`、`app/models/connection.py`
- 路径与日志：`app/utils/paths.py`、`app/utils/redact.py`、`app/utils/logging_setup.py`、`app/utils/atomic.py`
- 传输限制：`app/services/transfer.py`、`app/services/filesystem.py`、`app/ssh/sftp_protocol.py`、`app/ssh/sftp_transport.py`、`app/ssh/sftp_client.py`、`app/core/config.py`
- 前端安全相关行为：`frontend/assets/js/api.js`（`X-AWFM-Token`）、`frontend/assets/js/connections.js`（指纹确认界面）、`frontend/assets/js/app.js`（写权限开关的二次确认）、`frontend/index.html`（令牌注入点）
