# AWFM HTTP API 参考

> 本文是 AWFM 本地服务的完整 HTTP 接口说明：统一响应信封、认证与安全机制、`ENDPOINTS` 中注册的**全部 22 个端点**、错误码全表，以及版本策略与「已在连接层实现但首版不通过 HTTP 暴露」的写操作。
>
> 文档日期 **2026-10-16** · 版本 `app/__init__.py:7`（`0.1.0`；v0.1.1 开发中，已新增第 20~22 号检索端点）· 路由注册处 `app/api/handlers.py:294`（`ENDPOINTS`）与 `app/api/handlers.py:320`（`build_router()`）

---

## 1 总览

| 项 | 值 | 依据 |
|---|---|---|
| 基地址 | `http://127.0.0.1:8760`（`server.host`/`server.port` 可改） | `app/core/config.py` 的 `DEFAULTS` |
| 接口前缀 | `/api/` | `app/api/http_server.py:144` `_dispatch` |
| 默认绑定 | 回环地址；非回环绑定必须显式设置 `security.allow_lan = true`（决策 D-009） | `app/core/config.py:178` `validate_binding` |
| 传输编码 | UTF-8；JSON 响应 `application/json; charset=utf-8` | `app/api/responses.py:71` |
| 服务器标识 | `Server: AWFM/0.1.0`（`sys_version` 置空，不泄漏 Python 版本） | `app/api/http_server.py:95` `AwfmRequestHandler` |
| 协议版本 | HTTP/1.1（`protocol_version = "HTTP/1.1"`，因此响应必须给出 `Content-Length` 或 `Connection: close`） | `app/api/http_server.py:95` |
| 认证 | 除 `GET /api/health` 外，所有 `/api/` 请求都必须带 `X-AWFM-Token` 头 | `app/api/security.py:44`、`:48`、`:132` |
| 并发 | `ThreadingHTTPServer`，每请求一线程 | `app/api/http_server.py:81` |
| 端点总数 | 22 | `app/api/handlers.py:294-317` |

端点分成三组：

- **连接级**（不需要已连接的会话，挂在 `/api/connections` 与 `/api/connections/{connection_id}` 之下）：`/api/connections` 的增删改查、`connect`、`disconnect`、`status`、`host-keys`、`host-keys/trust`；
- **会话级**（必须已连接，否则 `404 session_not_found`）：`files`、`stat`、`preview`、`download-ticket`、`download`、`upload`、`upload-check`、`search`；
- **检索级**（只认检索 id，与具体连接解耦）：`GET`/`DELETE /api/searches/{search_id}`。检索是异步的：`POST …/search` 拿 id，之后轮询或中止都走这两个地址。

---

## 2 通用约定

### 2.1 请求解析

| 项 | 规则 | 代码位置 |
|---|---|---|
| 路径与查询串 | `urlsplit` + `unquote(encoding="utf-8", errors="replace")`，`parse_qs(keep_blank_values=True)` | `app/api/request.py:27` |
| 必填查询参数 | `require_query(name)`：参数缺失**或为空串**都抛 `invalid_request`，消息为「缺少必需的查询参数 <name>。」 | `app/api/request.py:47` |
| 布尔查询参数 | `query_bool(name, default)`：`1/true/yes/on` 为真，`0/false/no/off` 为假，其它值抛 `invalid_request` | `app/api/request.py:53` |
| 整数查询参数 | `query_int(name, default)`：非法值抛 `invalid_request` | `app/api/request.py:64` |
| JSON 请求体 | 上限 `MAX_JSON_BODY = 1024 * 1024`（1 MiB），超限抛 `payload_too_large`；空体视为 `{}`；非 UTF-8 或非法 JSON 抛 `invalid_request`（消息里带行号列号）；顶层不是对象也抛 `invalid_request` | `app/api/request.py:21`、`:92` |
| 请求体读取纪律 | 请求体没读完的请求会在响应后强制断开连接，防止 keep-alive 连接上的字节错位 | `app/api/http_server.py:144` 的 `finally` 段 |
| 方法 | `HEAD` 映射到 `GET` 路由；路径存在但方法不符时返回 `invalid_request`（400），`detail` 里列出允许的方法；路径完全不存在返回 `path_not_found`，消息「接口不存在。」 | `app/api/router.py:49`、`app/api/http_server.py:179` |
| 预检 | `OPTIONS` 一律返回 403，且**不返回任何 `Access-Control-Allow-*` 头** | `app/api/http_server.py:132` `do_OPTIONS` |

### 2.2 统一响应信封

**成功**：

```json
{
  "ok": true,
  "data": { }
}
```

- `data` 的形状由具体端点决定；**当 `data` 为 `None` 时该键不出现**（`app/api/responses.py:80`）。`DELETE` 这类端点返回的 `data` 是字典（例如 `{"deleted": {…被删掉的连接…}}`），因此键一定存在。
- 成功状态码默认 200；新建连接与新建上传文件返回 201。
- 序列化用 `json.dumps(payload, ensure_ascii=False, default=str)`，因此中文不被转义。`default=str` 只是最后一道兜底：处理函数一律先转成字典再交给它，**不要把数据对象直接放进响应体** —— 那会得到对象的字符串表示而不是结构化 JSON（2026-10-15 修掉了 §5.5 那一处）。响应体上限 `MAX_JSON_BYTES = 8 MiB`（防御性检查）。

**失败**：

```json
{
  "ok": false,
  "error": {
    "code": "path_not_found",
    "message": "路径不存在。",
    "detail": "远端返回 NO_SUCH_FILE"
  }
}
```

- `error` 的字段来自 `AwfmError.to_dict()`（`app/core/errors.py:59`）：核心字段 `code`/`message` 永远存在，`detail` 为空时该键不出现，`extra` 中的附加字段（例如 `host_key_unknown` 的 `fingerprints`、`connection_not_found` 的 `connection_id`）会被合并进来。
- HTTP 状态码取异常的 `http_status`；若不是合法状态码则回退 500（`app/api/responses.py:88`）。
- `message` 是面向用户的中文说明；`detail` 可能含远端原始串（例如 SFTP 状态文本），用于排查，不保证稳定。

### 2.3 响应头

所有 API 响应都会带上（`app/api/responses.py:32` `security_headers`）：

| 头 | 值 |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `no-referrer` |
| `X-Frame-Options` | `DENY` |
| `Cache-Control` | `no-store` |
| `Content-Security-Policy` | 非 HTML 响应为 `default-src 'none'; frame-ancestors 'none'`；HTML 响应为 `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'` |

下载响应额外带 `Content-Disposition` 与 `X-AWFM-Path`（见 §5.17）。

---

## 3 认证与安全

### 3.1 会话令牌：`X-AWFM-Token`

- 服务每次启动生成一个新令牌：`secrets.token_urlsafe(32)`（`app/api/security.py:51` `new_session_token`），存在 `AppContext` 里，不写磁盘。
- 令牌通过 `frontend/index.html` 中的占位符 `<!--AWFM_TOKEN-->` 注入成 `<meta name="awfm-token" content="…">`（同时注入 `<meta name="awfm-version">`）；若模板里找不到占位符，服务只打一条 warning「前端将拿不到会话令牌」。
- 前端每次请求都带上该头（`frontend/assets/js/api.js:47`），取值来自 `api.js:13` `readMeta("awfm-token")`。
- 校验失败的消息：未提供 → 「缺少会话令牌，已拒绝。」；不匹配 → 「会话令牌不正确，已拒绝。」（`detail`：「服务可能已重启，请刷新页面。」）。比较用 `secrets.compare_digest`（`app/api/security.py:115`）。
- **唯一例外**：`GET /api/health`（`app/api/security.py:48` `OPEN_PATHS`）。它仍然要过 Host 与来源校验，只是跳过令牌。

### 3.2 Host 头校验

`check_host_header`（`app/api/security.py:56`）要求 `Host` 的主机名属于 `{127.0.0.1, localhost, ::1, [::1]}`（`app/api/security.py:44` `ALLOWED_HOSTS`），否则抛 `invalid_request`：「请求的 Host 头不是本机地址，已拒绝。」（`extra.host` 回显收到的值）。无 `Host` 头（HTTP/1.0 老客户端）直接放行——浏览器必定会发 `Host`，所以不存在 DNS 重绑定空间。当 `security.allow_lan = true` 时该校验直接跳过。

### 3.3 Origin / `Sec-Fetch-Site` 校验

`check_fetch_metadata`（`app/api/security.py:84`）：`Sec-Fetch-Site` 只允许 `none`（地址栏、书签）与 `same-origin`，其它值抛 `unauthorized`「跨站请求已被拒绝。」；若请求带 `Origin`，则 `_is_loopback_origin`（`app/api/security.py:102`）必须为真（`null`、非 `http(s)://`、或主机名不是回环地址都拒绝）。

### 3.4 下载票据：`POST …/download-ticket`

**为什么存在**：下载必须由浏览器自己发起（`<a href>` 或 `window.location`）才能有原生进度条与「另存为」；用 `fetch` + `Blob` 会把整个文件读进浏览器内存（4 GB 镜像走不通，违背决策 D-007）。而浏览器发起的导航请求带不了自定义头，把长期令牌放进 URL 又会留在浏览器历史里、且能调用全部接口。票据是这两者之间的折中（`app/api/tickets.py` 模块 docstring）。

| 性质 | 值 |
|---|---|
| 生成 | `secrets.token_urlsafe(24)` 随机串 |
| 绑定 | 具体连接 id + 具体远程路径（`issue(connection_id, path)`） |
| TTL | `DEFAULT_TTL = 120.0` 秒，基于 `time.monotonic()` |
| 存储 | 只在进程内存；进程重启全部失效 |
| 数量上限 | `MAX_TICKETS = 256`，超过时回收最早一张并打 warning |
| 可重复使用 | **是**（见下） |

**为什么不设成一次性**：票据在真正开始传数据时才被消费。若标成一次性，用户在「另存为」对话框点取消、或浏览器重试一次 URL，票据就失效了，用户看到的是无法解释的错误。代价是 120 秒内可以重复使用，而它本来也只能下那一个文件——取舍划算（`app/api/tickets.py` 模块 docstring）。

请求与响应：

```http
POST /api/connections/vm1/download-ticket
X-AWFM-Token: …
Content-Type: application/json

{"path": "/var/log/app.log"}
```

```json
{
  "ok": true,
  "data": {
    "ticket": "Rk3s…",
    "url": "/api/connections/vm1/download?ticket=Rk3s…&path=%2Fvar%2Flog%2Fapp.log",
    "expires_in": 120
  }
}
```

校验发生在处理函数里：`download_file` 取出 `ticket` 查询参数后调 `DownloadTickets.verify(ticket, connection_id, path)`（`app/api/tickets.py:67`），连接或路径不符都会拒绝并记 warning。路由层只用 `peek()`（`app/api/tickets.py:86`）判断「这次请求是否跳过令牌校验」，因为路由匹配时还不知道 URL 里的 `connection_id` 与 `path` 是否与票据一致（`app/api/http_server.py:152`、`TICKET_PATH_RE` 在 `app/api/http_server.py:63`）。

### 3.5 认证与安全的分层顺序

`verify_api_request`（`app/api/security.py:132`）固定顺序：`check_host_header` → `check_fetch_metadata` → 若路径在 `OPEN_PATHS` 或带有效票据则返回 → `check_token`。也就是说**令牌是最后一道**，前三道对 `/api/health` 同样生效。

---

## 4 端点总表

| # | 方法 | 路径 | 处理函数 | 说明 |
|---|---|---|---|---|
| 1 | GET | `/api/health` | `health`（`handlers.py:26`） | 健康检查，免令牌 |
| 2 | GET | `/api/session` | `session_info`（`:38`） | 服务与安全策略摘要 |
| 3 | GET | `/api/connections` | `list_connections`（`:57`） | 连接配置列表 + 会话状态 |
| 4 | POST | `/api/connections` | `create_connection`（`:65`） | 新增连接（201） |
| 5 | GET | `/api/connections/{connection_id}` | `get_connection`（`:61`） | 单条连接配置 |
| 6 | PATCH | `/api/connections/{connection_id}` | `update_connection`（`:73`） | 局部更新 |
| 7 | DELETE | `/api/connections/{connection_id}` | `delete_connection`（`:79`） | 删除并先断开 |
| 8 | POST | `/api/connections/{connection_id}/connect` | `connect`（`:84`） | 建立（或重建）会话 |
| 9 | POST | `/api/connections/{connection_id}/disconnect` | `disconnect`（`:98`） | 断开（幂等） |
| 10 | GET | `/api/connections/{connection_id}/status` | `connection_status`（`:103`） | 会话状态 |
| 11 | GET | `/api/connections/{connection_id}/host-keys` | `list_host_keys`（`:107`） | 信任库中该主机的指纹 |
| 12 | POST | `/api/connections/{connection_id}/host-keys/trust` | `trust_host_key`（`:112`） | 用户确认后写入信任库 |
| 13 | GET | `/api/connections/{connection_id}/files` | `list_files`（`:131`） | 列目录 |
| 14 | GET | `/api/connections/{connection_id}/stat` | `stat_file`（`:137`） | 单个路径的元数据 |
| 15 | GET | `/api/connections/{connection_id}/preview` | `preview_file`（`:144`） | 文本预览（只读、有上限） |
| 16 | POST | `/api/connections/{connection_id}/download-ticket` | `download_ticket`（`:155`） | 换取下载票据 |
| 17 | GET | `/api/connections/{connection_id}/download` | `download_file`（`:178`） | 二进制流下载 |
| 18 | POST | `/api/connections/{connection_id}/upload` | `upload_file`（`:224`） | 上传（201 新建 / 200 覆盖） |
| 19 | GET | `/api/connections/{connection_id}/upload-check` | `check_upload`（`:278`） | 上传前的覆盖预检 |
| 20 | POST | `/api/connections/{connection_id}/search` | `start_search`（`:161`） | 启动检索（**202**，后台线程里跑） |
| 21 | GET | `/api/searches/{search_id}` | `search_status`（`:181`） | 轮询检索进度 / 取结果 |
| 22 | DELETE | `/api/searches/{search_id}` | `cancel_search`（`:185`） | 请求中止（幂等） |

以下所有示例都省略了请求头 `X-AWFM-Token`（除健康检查外都必须有），`connection_id` 一律用 `vm1`。

---

## 5 端点详解

### 5.1 GET /api/health

免令牌（仍在 `OPEN_PATHS`），便于用 `curl` 确认服务活着。不返回任何敏感信息。

- 参数：无。
- 成功（200）：

```json
{ "ok": true, "data": { "status": "ok", "version": "0.1.0", "connections": 1 } }
```

- `connections` 是配置里连接配置的条数（不是活动会话数）。
- 可能的错误：`invalid_request`（400，Host 头不是本机地址）。

### 5.2 GET /api/session

返回前端启动时需要的服务摘要（`frontend/assets/js/app.js:182` `boot()` 第一个调用）。

- 成功（200）：

```json
{
  "ok": true,
  "data": {
    "version": "0.1.0",
    "host_key_policy": "strict",
    "max_upload_bytes": 2147483648,
    "max_download_bytes": 0,
    "allow_lan": false,
    "known_hosts_path": "E:/Project/aimus-web-file-manager/data/known_hosts"
  }
}
```

- `max_download_bytes = 0` 表示不限；`known_hosts_path` 给界面用——主机密钥变化时要明确告诉用户去改哪个文件（`app/api/handlers.py:48` 注释，本服务**不提供一键接受**）。
- 可能的错误：`unauthorized`（401）。

### 5.3 GET /api/connections

- 成功（200）：`data.connections` 是数组，每项 = 连接配置的公开字段 + `session` 状态：

```json
{
  "ok": true,
  "data": {
    "connections": [
      {
        "id": "vm1",
        "name": "开发虚拟机",
        "host": "192.168.170.128",
        "port": 22,
        "username": "aimu",
        "auth_method": "key",
        "identity_file": "",
        "note": "",
        "allow_write": false,
        "created_at": "2026-10-15T02:10:00Z",
        "updated_at": "2026-10-15T02:10:00Z",
        "session": {
          "connection_id": "vm1",
          "state": "disconnected",
          "connected": false,
          "connected_at": null,
          "duration_seconds": null,
          "home": "/",
          "server_version": null,
          "last_error": null
        }
      }
    ]
  }
}
```

- 没有会话时不查远端，直接给一份 `state = "disconnected"` 的默认状态（`app/services/connection_manager.py:85`）。
- 可能的错误：`unauthorized`（401）。

### 5.4 POST /api/connections

- 请求体：`Connection` 的字段；`id` 可省略（省略时按 `name` 或 `host` 生成，形如 `dev-vm-a1b2c3`）。必须是非空 JSON 对象，否则 `invalid_request`（「请求体必须是一个 JSON 对象。」）。
- 字段约束（`app/models/connection.py`）：`id` 匹配 `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`（**禁止 `/` 与 `..`**）；`host` 非空且 ≤255 字符、不含空白/斜杠/控制字符；`port` 1..65535；`username` 非空、≤128、不含 `NUL`/`CR`/`LF`；`auth_method` 只能是 `key` 或 `password`；未知字段会被拒绝；`allow_write` 默认 `false`。
- 请求示例：

```json
{ "id": "vm1", "name": "开发虚拟机", "host": "192.168.170.128", "username": "aimu", "auth_method": "key" }
```

- 成功（**201**）：`data.connection` 是新建后的公开字段（不含任何凭据）。
- 可能的错误：`invalid_request`（400：id 非法或已存在、字段非法、请求体不是对象）、`config_error`（500：写配置文件失败）、`unauthorized`（401）。

### 5.5 GET /api/connections/{connection_id}

- 成功（200）：`data.connection` = 该连接的公开字段 **加上** `session`（会话状态），与 `GET /api/connections` 列表里的每一项同形。实现走 `ConnectionManager.connection_detail()`（`app/services/connection_manager.py:106`）。

```json
{
  "ok": true,
  "data": {
    "connection": {
      "id": "vm1", "name": "开发虚拟机", "host": "192.168.170.128", "port": 22,
      "username": "aimu", "auth_method": "key", "identity_file": "", "note": "",
      "allow_write": false, "created_at": "2026-10-15T02:10:00Z", "updated_at": "2026-10-15T02:10:00Z",
      "session": { "connection_id": "vm1", "state": "disconnected", "connected": false,
                   "connected_at": null, "duration_seconds": null, "home": null,
                   "server_version": null, "last_error": null }
    }
  }
}
```

响应不含凭据 —— `Connection` 里没有密码字段（决策 D-014），也没有私钥内容。当前前端（`frontend/assets/js/api.js`）没有调用这个端点。
- 可能的错误：`connection_not_found`（404）、`invalid_request`（400：id 字符合法性）、`unauthorized`（401）。

### 5.6 PATCH /api/connections/{connection_id}

- 请求体：任意子集；未出现的字段保持不变。**不允许改 `id`**（`app/services/connection_manager.py:145`，改 id 等于换一条连接，应表现为「删除 + 新建」，否则会留下指向旧 id 的悬挂会话）→ `invalid_request`（「连接 id 不可修改。」）。
- 请求示例：`{"allow_write": true, "name": "开发虚拟机（可写）"}`
- 成功（200）：`data.connection` = 更新后的公开字段。
- 可能的错误：`invalid_request`（400）、`connection_not_found`（404）、`config_error`（500）、`unauthorized`（401）。

### 5.7 DELETE /api/connections/{connection_id}

- 行为：**先断开该连接的会话**再删除配置（`app/services/connection_manager.py:168`），随后原子写回配置文件。
- 成功（200）：`data.deleted` = 被删掉的那条连接的公开字段（不含 `session`）。

```json
{ "ok": true, "data": { "deleted": { "id": "vm1", "name": "开发虚拟机", "host": "192.168.170.128", "port": 22, "username": "aimu", "auth_method": "key", "identity_file": "", "note": "", "allow_write": false, "created_at": "2026-10-15T02:10:00Z", "updated_at": "2026-10-15T02:10:00Z" } } }
```

（返回被删掉的内容而不是 `null`：界面可以据此提示「已删除 vm1」，也便于调用方确认删的确实是它。）
- 可能的错误：`connection_not_found`（404）、`invalid_request`（400）、`config_error`（500）、`unauthorized`（401）。

### 5.8 POST /api/connections/{connection_id}/connect

- 请求体：`{"password": "…"}`。`password` 可省略或为 `null`（都当作空串）；非字符串 → `invalid_request`（「password 必须是字符串。」）。密钥认证时提交的密码会被忽略（只记 debug）——界面上切换认证方式可能残留密码框内容。
- 语义：重复调用会先断开旧会话再建新的（`app/services/connection_manager.py:199`：`ssh` 子进程绑定的是进程内管道，复用已退出进程的管道只会得到「看起来连着但什么都读不到」的假会话）。活动会话数达到 `ssh.max_sessions`（默认 4）时会**回收连接时间最早的那条**，而不是拒绝本次连接。
- 成功后 `data.connection` 是会话状态：

```json
{
  "ok": true,
  "data": {
    "connection": {
      "connection_id": "vm1",
      "state": "connected",
      "connected": true,
      "connected_at": 1792000000.123,
      "duration_seconds": 0.0,
      "home": "/home/aimu",
      "server_version": 3,
      "last_error": null
    }
  }
}
```

- `state` 取值：`disconnected` / `connecting` / `connected` / `error`（`error` 与 `disconnected` 分开，是因为前者要带上「为什么失败」给界面显示）。
- `home` 是登录后的起始目录（服务端 `REALPATH` 的结果），失败时为 `/`；`server_version` 是 SFTP 协议版本（协商结果，`app/ssh/sftp_protocol.py` 的 `SSH_FXP_VERSION`）。
- 可能的错误：`invalid_request`（400：密码认证但未提供密码）、`auth_failed`（401）、`host_key_unknown`（409，`error.fingerprints` 里是待确认的指纹列表）、`host_key_mismatch`（409，`extra` 里同时带信任库指纹与当前指纹）、`not_connected`（409）、`timeout`（504）、`config_error`（500：找不到 `ssh` 客户端）、`connection_not_found`（404）、`unauthorized`（401：令牌）。

### 5.9 POST /api/connections/{connection_id}/disconnect

- 参数：无请求体。
- 语义：幂等——断开一个本来就没连的连接**不是错误**（对重试友好），此时返回一份 `disconnected` 状态。
- 成功（200）：`data.connection` = 会话状态（字段同 §5.8）。
- 可能的错误：`connection_not_found`（404）、`invalid_request`（400）、`unauthorized`（401）。

### 5.10 GET /api/connections/{connection_id}/status

- 成功（200）：`data.connection` = 会话状态（字段同 §5.8；没有会话时返回 `disconnected` 默认状态）。
- 前端每 20 秒轮询一次（`frontend/assets/js/app.js:172` `pollStatus`，页面隐藏时跳过）。
- 可能的错误：`connection_not_found`（404）、`unauthorized`（401）。

### 5.11 GET /api/connections/{connection_id}/host-keys

- 成功（200）：

```json
{
  "ok": true,
  "data": {
    "keys": [ { "key_type": "ssh-ed25519", "fingerprint": "SHA256:L/T9jS54W2ixc6CSMe7OPVtQRneYZQSVlOleczFarWE" } ],
    "policy": "strict"
  }
}
```

- `keys` 是项目信任库（`data/known_hosts`）里该主机（按 `host`/`port` 匹配，端口非 22 时写成 `[host]:port`）的全部密钥。返回列表而不是单条：同一主机可以同时有 `ssh-ed25519` 与 `ssh-rsa` 两把钥匙，只保留一把会让另一条合法连接被误判成「密钥变化」。
- 哈希化的 `known_hosts` 行（`|1|` 开头）无法反推主机名，会被跳过；`app/ssh/known_hosts.py:275` `looks_like_hashed_hosts` 用于在界面上解释「为什么看不到某些主机」。
- 可能的错误：`connection_not_found`（404）、`unauthorized`（401）。

### 5.12 POST /api/connections/{connection_id}/host-keys/trust

- 请求体：`{"key_type": "ssh-ed25519", "fingerprint": "SHA256:…"}`。缺任一项 → `invalid_request`（「缺少 key_type。」/「缺少 fingerprint。」）。
- 语义（`app/services/connection_manager.py:288`）：**重新采集一次**目标机当前的主机密钥，并要求它包含用户确认过的指纹；两次采集之间密钥变了就拒绝写入——否则「用户确认」只是走个形式。已存在同样的 `key_type` + `fingerprint` 时返回 `added: false`（不重复写）。
- 成功（200）：

```json
{ "ok": true, "data": { "added": true, "fingerprint": "SHA256:L/T9jS54W2ixc6CSMe7OPVtQRneYZQSVlOleczFarWE", "key_type": "ssh-ed25519" } }
```

- 可能的错误：`invalid_request`（400：缺字段、或「目标机当前提供的主机指纹与用户确认的不一致，已拒绝写入信任库。」）、`connection_not_found`（404）、`config_error`（500）、`unauthorized`（401）。

### 5.13 GET /api/connections/{connection_id}/files

- 查询参数：`path`（必填，绝对路径，如 `/var/log`）。
- 成功（200）：

```json
{
  "ok": true,
  "data": {
    "path": "/var/log",
    "parent": "/var",
    "entries": [
      {
        "name": "app.log",
        "path": "/var/log/app.log",
        "type": "file",
        "size": 4096,
        "mtime": 1792000000,
        "mode": "0644",
        "atime": 1792000000,
        "permissions": 33188,
        "uid": 1000,
        "gid": 1000
      }
    ],
    "truncated": false,
    "total": 1
  }
}
```

- `path` 是服务端 `REALPATH` 给出的规范路径（不是请求里那串）；`parent` 是它的父目录，根目录时为 `null`。
- `entries[]` 是 `FileEntry.to_dict()`：`name`/`type`/`size`/`mtime`/`mode` 必有，`atime`/`permissions`/`uid`/`gid` 只在有值时才出现，`link_target` 出现时会附带 `link_broken`。`type` 取值：`directory`/`symlink`/`file`/`socket`/`fifo`/`block`/`char`/`unknown`。
- 排序与截断：先按 (目录 → 符号链接 → 文件, Unicode NFC 归一化后的名称, 原名) 排序，再截断到 `MAX_LIST_ENTRIES = 5000` 条；`total` 是截断前的条目数，`truncated` 表示是否发生了截断。`.` 与 `..` 不出现。
- 列目录**不解析符号链接目标**（每个 `readlink` 都是一次往返，会拖慢大目录）。
- 可能的错误：`invalid_request`（400：缺 `path`、路径非法、或「该路径不是一个目录。」）、`session_not_found`（404：尚未连接）、`path_not_found`（404）、`permission_denied`（403）、`not_connected`（409）、`protocol_error`/`remote_error`（502）、`timeout`（504）、`unauthorized`（401）。

### 5.14 GET /api/connections/{connection_id}/stat

- 查询参数：`path`（必填）；`follow`（可选布尔，默认 `true`）。
- `follow=true`：解析符号链接后取属性；`follow=false`：`lstat`，若目标是链接则额外尝试 `readlink` 填 `link_target`，并用一次 `stat` 判断 `link_broken`（断链在 `/etc`、`/usr/lib` 很常见，文件管理器必须能表达）。
- 成功（200）：**`data` 直接就是 FileEntry 对象本身**（不是包一层 `entry`）：

```json
{
  "ok": true,
  "data": {
    "name": "nginx.conf",
    "path": "/etc/nginx/nginx.conf",
    "type": "symlink",
    "size": 22,
    "mtime": 1792000000,
    "mode": "0777",
    "link_target": "/etc/nginx/nginx.conf.real",
    "link_broken": false
  }
}
```

- 可能的错误：同 §5.13（`invalid_request`/`session_not_found`/`path_not_found`/`permission_denied`/`not_connected`/`protocol_error`/`remote_error`/`timeout`/`unauthorized`）。

### 5.15 GET /api/connections/{connection_id}/preview

- 查询参数：`path`（必填）；`max_bytes`（可选整数，默认 `DEFAULT_PREVIEW_BYTES = 262144`，会被夹到 `[1, 262144]`）。
- 这是**只读预览**，不是编辑器（规划文档 §3.2 明确首版不做在线编辑器）。
- 成功（200）：

```json
{
  "ok": true,
  "data": {
    "path": "/etc/hostname",
    "text": "awfm-test\n",
    "encoding": "utf-8",
    "truncated": false,
    "bytes_read": 10,
    "size": 10
  }
}
```

- 编码判定：先按 UTF-8 解码，失败则回退 `latin-1`（**不用** `errors="replace"`：大量替换字符会让用户以为文件坏了，`latin-1` 至少是双射的）。`encoding` 字段回显实际用的编码。
- 前若干字节里含 `NUL` 时抛 `invalid_request`（「该文件看起来是二进制文件，无法作为文本预览。」）。
- 可能的错误：`invalid_request`（400：缺 `path`、目录、二进制文件、路径非法）、`session_not_found`（404）、`path_not_found`（404）、`permission_denied`（403）、`not_connected`（409）、`remote_error`/`protocol_error`（502）、`timeout`（504）、`unauthorized`（401）。

### 5.16 POST /api/connections/{connection_id}/download-ticket

- 请求体：`{"path": "/绝对/路径"}`（非字符串或空 → `invalid_request`「缺少 path。」）。连接必须存在（不存在直接 `connection_not_found`）。
- 成功（200）：见 §3.4 的示例（`ticket`、`url`、`expires_in: 120`）。`url` 里的三段都用 `quote(..., safe="")` 做了百分号编码。
- 注意：这里**不检查文件是否存在**——真正的检查在下载时由 `prepare_download` 做。
- 可能的错误：`invalid_request`（400）、`connection_not_found`（404）、`unauthorized`（401）。

### 5.17 GET /api/connections/{connection_id}/download

- 查询参数：`ticket`（票据，路由层用它跳过令牌校验）、`path`（必填，必须与票据绑定的路径一致）。
- 成功（200）：**响应体是原始二进制流**，不是 JSON 信封。响应头：

| 头 | 值 |
|---|---|
| `Content-Type` | `application/octet-stream` |
| `Content-Length` | 文件当前大小的字节数 |
| `Content-Disposition` | `attachment; filename="<ASCII 回退名>"; filename*=UTF-8''<百分号编码名>` |
| `X-AWFM-Path` | 远程路径的百分号编码形式（`quote(value, safe="/")`，HTTP 头只能是 latin-1 字节） |

- 参数校验顺序：先验票据（`Unauthorized`「下载票据无效、已过期，或与请求的文件不匹配。」），再取会话，再检查路径：目录 → `invalid_request`（「目录不能直接下载。」，`detail` 提示「如需打包下载，请使用压缩功能（P2）」）；符号链接或非普通文件 → `invalid_request`（「只有普通文件可以被下载。」）；超过 `security.max_download_bytes`（非 0 时）→ `payload_too_large`（413）。
- 传输行为：按 64 KiB 块流式发送。客户端中断（`BrokenPipeError`/`ConnectionResetError`）只记 info「下载被客户端中断」并断开连接；若正常结束时发送字节数与 `stat` 结果不一致（目标机文件在传输中被改小），记 warning 并断开连接——让浏览器知道这次下载不完整，而不是安静地交出一个被截断的文件。
- 可能的错误：`unauthorized`（401）、`invalid_request`（400）、`payload_too_large`（413）、`session_not_found`（404）、`path_not_found`（404）、`permission_denied`（403）、`not_connected`（409）、`remote_error`/`protocol_error`（502）、`timeout`（504）。

### 5.18 POST /api/connections/{connection_id}/upload

- 查询参数（**注意参数名是 `name`，不是 `filename`**）：

| 参数 | 必填 | 说明 |
|---|---|---|
| `path` | 是 | 目标**目录**的绝对路径 |
| `name` | 是 | 目标**文件名**（单个分量，不能含 `/`，不能是 `.`/`..`，≤255 字节，且不能包含保留串 `.awfm-part-`） |
| `overwrite` | 否 | 布尔，默认 `false` |

- 请求体：**原始文件字节**，必须带 `Content-Length`（服务不支持分块传输编码；缺失或为 0 → `invalid_request`：「上传需要 Content-Length，且不能为 0。」）。超过 `security.max_upload_bytes`（默认 2 GiB）→ `payload_too_large`。
- 需要连接开启写权限：`allow_write = false` 时抛 `unauthorized`（「该连接未开启写权限，无法上传文件。」`detail`：「请在连接配置中显式勾选「允许写操作」后重试。」）——这是最内层的一道门禁。
- 覆盖规则：目标已存在且 `overwrite` 为假 → `invalid_request`（「目标位置已存在同名文件。」）；同名**目录**存在 → `invalid_request`（「同名目录已存在，无法上传文件。」）。前端在覆盖前会先调 `upload-check` 并弹二次确认（`frontend/assets/js/transfer.js:86`）。
- 写入策略：新建文件先写「临时名 + 改名」（`<目标名>.awfm-part-<8 位随机>`，写完再 `RENAME` 到目标名，失败则删除临时文件）——直接写目标名时中途断线会留下一个与真文件没有区别的半截文件；覆盖是另一条路径（SFTP v3 的 `RENAME` 不能替换已存在目标，只能直接截断写入），代价是覆盖中断会留下被截断的文件，这是本版接受的取舍。写完后会**回读 `STAT` 校验字节数**。
- 成功：`data` 是上传结果，状态码区分新建与覆盖：

| 情况 | 状态码 |
|---|---|
| 目标原本不存在 | **201** |
| 目标已存在且 `overwrite=true` | **200** |

```json
{ "ok": true, "data": { "path": "/home/aimu/notes.txt", "name": "notes.txt", "size": 1024, "overwritten": false } }
```

- 可能的错误：`invalid_request`（400）、`payload_too_large`（413）、`unauthorized`（401：令牌或写权限）、`session_not_found`（404）、`path_not_found`（404：目标目录不存在）、`permission_denied`（403）、`not_connected`（409）、`remote_error`/`protocol_error`（502）、`timeout`（504）。

### 5.19 GET /api/connections/{connection_id}/upload-check

- 查询参数：`path`（目录，必填）、`name`（文件名，必填）。
- 用途：上传前的预检，界面用它决定要不要弹「确认覆盖」对话框。
- 成功（200）：

```json
{
  "ok": true,
  "data": { "path": "/home/aimu/notes.txt", "exists": true, "type": "file", "size": 1024, "mtime": 1792000000 }
}
```

目标不存在时返回 `exists: false`，其余字段为 `null`。
- 可能的错误：`invalid_request`（400）、`session_not_found`（404）、`path_not_found`（404：目录不存在时由路径解析抛出）、`permission_denied`（403）、`not_connected`（409）、`unauthorized`（401）。

---

### 5.20 POST /api/connections/{connection_id}/search

启动一次远端文件名检索。请求体是 JSON：

```json
{ "path": "/home/aimu", "query": "报告" }
```

- `path`（必填，字符串）：搜索根，必须是**目录**的绝对路径；`..` 不由调用方折叠，服务端用真实路径（`realpath`）解析后再校验，与 `/files` 同一套规则（`app/utils/paths.py` 的 `validate_remote_path`）。
- `query`（必填，字符串）：关键词，按名称做**大小写不敏感**的包含匹配（`casefold`）。上限 128 个字符；除 `\t` 以外的控制字符一律拒绝。
- 搜索范围固定是**该目录及其全部子目录**，快照里的 `scope` 因此恒为 `"subtree"`。

成功返回 **202**（已受理、尚未完成），响应体是**发起瞬间**的快照，通常 `status` 为 `"running"`、`results` 为空数组：

```json
{
  "ok": true,
  "data": {
    "search": {
      "id": "9f2c1b0a4e5d6c7b",
      "connection_id": "vm1",
      "root": "/home/aimu",
      "query": "报告",
      "scope": "subtree",
      "status": "running",
      "running": true,
      "started_at": 1792000000.123,
      "finished_at": null,
      "duration_seconds": 0.0,
      "scanned_dirs": 0,
      "scanned_entries": 0,
      "skipped_dirs": 0,
      "skipped_names": 0,
      "skipped": [],
      "result_count": 0,
      "truncated": false,
      "truncated_reason": "",
      "limits": { "max_results": 500, "max_dirs": 2000, "max_entries": 100000, "time_budget_seconds": 45.0 },
      "error": null,
      "results": []
    }
  }
}
```

为什么是 202 而不是 200：检索跑在服务端后台线程里（线程名 `awfm-search-<id>`，见 `app/services/search.py`），HTTP 处理器只负责受理并立刻把 id 交出去，进度与结果都靠 `GET /api/searches/{search_id}` 轮询。这样长时间搜索不会把一个 HTTP 请求挂住，也随时能中止。

**同一连接同一时刻只允许一个检索**：已有在跑的检索时返回 `409 search_busy`（消息「这条连接上已经有一个正在进行的搜索。」，`detail` 为「请等它结束，或在结果区点「中止」。」）。连接断开或删除时，它上面还在跑的检索会被自动请求中止（`SearchRegistry.cancel_for_connection`），因此不会留下永久占用的槽位。

快照字段（`data.search`，同时也是 `GET`/`DELETE` 的返回体）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 检索 id，小写十六进制（路由只接受 `[0-9a-f]+`） |
| `connection_id` / `root` / `query` / `scope` | string | 发起时冻结的连接、搜索根、关键词；`scope` 恒为 `subtree` |
| `status` | string | `running` / `done` / `failed` / `cancelled` |
| `running` | bool | `status == "running"` 的便捷字段 |
| `started_at` / `finished_at` / `duration_seconds` | number | Unix 秒；未结束时 `finished_at` 为 `null`，`duration_seconds` 按当前时刻算，保留三位小数 |
| `scanned_dirs` / `scanned_entries` | int | 已列举的目录数、已检查的条目数 |
| `skipped_dirs` / `skipped_names` | int | 读不到的目录数、被跳过的非法条目名（`.`/`..`/含斜杠）数 |
| `skipped` | array | 读不到的目录明细，**最多 20 条**：`{"path", "code", "message"}` |
| `result_count` | int | 命中条数，等于 `results` 的长度（快照里两者同源） |
| `truncated` / `truncated_reason` | bool / string | 命中上限、目录上限、条目上限或时长预算触发时置 `true`，并给出中文原因 |
| `limits` | object | 本次生效的上限：`max_results`(500)、`max_dirs`(2000)、`max_entries`(100000)、`time_budget_seconds`(45.0) |
| `error` | object\|null | 失败时的 `{code, message, detail}`；**「没有匹配」不是失败**，此时为 `null` |
| `results` | array | 命中行（见下） |

结果行的字段：`name`、`type`（`directory` / `file` / `symlink` / `other`）、`size`、`mtime`、`mode`、`path`（绝对路径）、`parent`（所在目录）、`depth`（相对搜索根的层数，根的直接子项为 **1**）。排序固定为**目录 → 符号链接 → 文件**，同类型内按名称 `casefold` 升序、再按路径兜底。

**符号链接策略：报告但不跟随。** 条目类型是链接时会被列进结果（`type: "symlink"`），但**不会**被当作目录下钻。因此指向目录的链接、指到搜索根之外的链接、以及自指的目录环都不会把搜索带出去或让它转圈。

- 可能的错误：`invalid_request`（400：缺字段、`path` 不是绝对路径或超过 4096 字节、`query` 为空或过长或含控制字符）、`unauthorized`（401）、`connection_not_found`（404）、`session_not_found`（404）、`path_not_found`（404：搜索根不存在）、`permission_denied`（403：搜索根本身读不到）、`not_connected`（409）、`search_busy`（409）、`timeout`（504）。
- 参数形状检查发生在**找会话之前**：连接不存在时收到畸形请求，返回的是 400 而不是 404/409（`app/api/handlers.py:161` 的注释写明了这个取舍）。

### 5.21 GET /api/searches/{search_id}

轮询进度与取结果。`search_id` 只接受**小写**十六进制串；其它形状的地址不匹配路由，按 `404 path_not_found`（接口路径不存在）返回。

成功（200），完成态示例（命中 2 条）：

```json
{
  "ok": true,
  "data": {
    "search": {
      "id": "9f2c1b0a4e5d6c7b",
      "connection_id": "vm1",
      "root": "/home/aimu",
      "query": "报告",
      "scope": "subtree",
      "status": "done",
      "running": false,
      "started_at": 1792000000.123,
      "finished_at": 1792000000.987,
      "duration_seconds": 0.864,
      "scanned_dirs": 37,
      "scanned_entries": 412,
      "skipped_dirs": 1,
      "skipped_names": 0,
      "skipped": [ { "path": "/home/aimu/locked", "code": "permission_denied", "message": "远端拒绝访问。" } ],
      "result_count": 2,
      "truncated": false,
      "truncated_reason": "",
      "limits": { "max_results": 500, "max_dirs": 2000, "max_entries": 100000, "time_budget_seconds": 45.0 },
      "error": null,
      "results": [
        { "name": "报告.txt", "type": "file", "size": 19, "mtime": 1791999000, "mode": 33188,
          "path": "/home/aimu/报告.txt", "parent": "/home/aimu", "depth": 1 },
        { "name": "报告-草稿.txt", "type": "file", "size": 6, "mtime": 1791999050, "mode": 33188,
          "path": "/home/aimu/报告-草稿.txt", "parent": "/home/aimu", "depth": 1 }
      ]
    }
  }
}
```

行为要点：

- **读不到的目录不会让整次检索失败**：只体现在 `skipped_dirs` / `skipped` 里并继续搜；只有**连续 10 个**目录都失败时才整体置为 `failed`（`app/services/search.py` 的 `MAX_CONSECUTIVE_FAILURES`）。
- **断连**：`status` 变 `failed`，`error.code` 为 `not_connected`，消息说明连接已断开——这与「没有匹配」是两回事。
- **保留窗口**：检索记录只保留最近 20 条**已结束**的（`_prune_locked`），更早的会被回收，再查返回 `404 path_not_found`（消息「搜索不存在或已过期。」，`detail` 提示重新发起）。
- 可能的错误：`unauthorized`（401）、`path_not_found`（404：id 未知/已过期，或接口路径本身不存在）。

### 5.22 DELETE /api/searches/{search_id}

请求中止当前检索，响应 200，返回**收到请求那一刻**的快照。

- 中止是**幂等**的：已经结束的检索再 DELETE 不报错，返回它当前的终态快照（`done` / `failed` 原样返回，不会被改写成 `cancelled`）。
- 响应里的 `status` **可能仍是 `running`**：处理器只是把取消标志交给工作线程，线程要到下一个检查点才收尾（每个条目检查一次，因此延迟很短）。判定中止完成请以轮询到的 `cancelled` 为准。
- 中止**不算截断、也不算失败**：终态里 `truncated` 保持 `false`、`truncated_reason` 为空、`error` 为 `null`；已经找到的结果留在 `results` 里。
- 中止后活动槽立刻释放，同一条连接可以马上发起下一次检索。
- 可能的错误：`unauthorized`（401）、`path_not_found`（404）。

---

## 6 错误码全表

错误类型定义在 `app/core/errors.py`，每个类自带 `code` 与 `http_status`。

| `code` | HTTP | 触发场景 | 定义处 |
|---|---|---|---|
| `invalid_request` | 400 | 请求参数不合法（路径、名称、主机名、端口、JSON 结构、缺字段、方法不符） | `errors.py:79` |
| `unauthorized` | 401 | 令牌缺失/不正确、下载票据无效、连接未开启写权限、跨站来源 | `errors.py:103` |
| `auth_failed` | 401 | SSH 认证失败（用户名/密钥/密码不被接受） | `errors.py:133` |
| `permission_denied` | 403 | 远端拒绝访问（SFTP `STATUS` 3） | `errors.py:172` |
| `connection_not_found` | 404 | 配置里没有这个连接 id | `errors.py:114` |
| `session_not_found` | 404 | 会话不存在或尚未建立（请先点「连接」） | `errors.py:119` |
| `path_not_found` | 404 | 远程路径不存在（SFTP `STATUS` 2）；静态资源不存在；接口路径不存在 | `errors.py:165` |
| `not_connected` | 409 | 会话存在但通道已断开（SFTP `STATUS` 6/7） | `errors.py:126` |
| `host_key_unknown` | 409 | 首次连接，主机密钥未经用户确认（`extra.fingerprints`） | `errors.py:140` |
| `host_key_mismatch` | 409 | 主机密钥与信任库记录不符，必须人工介入 | `errors.py:151` |
| `search_busy` | 409 | 同一条连接上已有正在进行的检索（`app/services/search.py` 的 `SearchRegistry.start`） | `errors.py:193` |
| `payload_too_large` | 413 | 请求体超过 1 MiB，或文件超过 `max_upload_bytes` / `max_download_bytes` | `errors.py:86` |
| `internal_error` | 500 | 未预期的内部异常；端口被占用、绑定地址不可用 | `errors.py:198` |
| `config_error` | 500 | 配置文件损坏/不可读/写失败；找不到 `ssh` 客户端 | `errors.py:93` |
| `remote_error` | 502 | 远端返回其它错误（SFTP `STATUS` 4 或未映射码） | `errors.py:179` |
| `protocol_error` | 502 | SFTP 协议层异常：帧不合法、序列错位、通道提前关闭 | `errors.py:186` |
| `timeout` | 504 | 操作超时（看门狗杀掉 `ssh` 子进程） | `errors.py:193` |

---

## 7 版本策略与尚未暴露的写操作

### 7.1 版本

- 应用版本在 `app/__init__.py:7`（当前 `0.1.0`），通过 `Server` 响应头与 `GET /api/health`、`GET /api/session` 暴露。API 路径**不带版本前缀**——这是本地单用户服务，前后端同版本发布、同一次启动一起加载（前端资源由同一个进程提供），因此不需要 URL 版本协商。
- 配置文件有自己的版本号：`CONFIG_VERSION = 1`（`app/core/config.py` 的 `DEFAULTS["config_version"]`）。读到**更高版本**的配置文件会拒绝启动，而不是猜测字段含义；配置损坏时同样报 `config_error`，**绝不静默重置**（决策 D-006）。
- 前端在启动时先调 `GET /api/session`，可以据此判断服务能力（例如 `max_upload_bytes`、`max_download_bytes`、`host_key_policy`），比硬编码版本号更稳。
- **v0.1.1 开发中**：本版本在 v0.1.0 之上增加了远端文件检索（第 20~22 号端点）。`app/__init__.py` 里的版本号目前仍是 `0.1.0`，待阶段六交付时统一改为 `0.1.1` 并重新打包；端点路径、响应信封与既有端点的行为都不变（纯新增）。

### 7.2 已在连接层实现、首版不通过 HTTP 暴露的写操作

以下方法在 `app/ssh/sftp_client.py` 中已实现并在阶段 02 的测试床上实测通过，但按规划文档 §3.1 属于 **P2**（远程创建目录/重命名/删除），首版**没有**注册到 `ENDPOINTS` 中：

| 方法 | 代码位置 | 对应 SFTP 请求 |
|---|---|---|
| `SftpClient.mkdir(path, mode=0o755)` | `app/ssh/sftp_client.py:267` | `SSH_FXP_MKDIR` |
| `SftpClient.rmdir(path)` | `app/ssh/sftp_client.py:276` | `SSH_FXP_RMDIR` |
| `SftpClient.remove(path)` | `app/ssh/sftp_client.py:285` | `SSH_FXP_REMOVE` |
| `SftpClient.rename(old, new)` | `app/ssh/sftp_client.py:294` | `SSH_FXP_RENAME` |

代码注释写的是「仅在稳定性验证后启用」。规划文档 §3.2 同时要求：远程删除、覆盖、编辑属于高风险操作，必须在只读浏览稳定之后单独设计，并带二次确认、路径检查与操作记录。因此本版唯一暴露的写操作是上传，且受连接级 `allow_write` 开关约束（`app/services/filesystem.py:179` `require_write_permission`）。

### 7.3 静态资源

非 `/api/` 路径由静态处理器提供（`app/api/http_server.py:210`）：`/` 映射到 `frontend/index.html`；只允许 `GET` 与 `HEAD`；拒绝 `\` 与 `NUL`、拒绝 `.`/`..` 分量，解析后的真实路径必须仍在 `frontend/` 之内（`app/api/http_server.py:267` `_is_within`）。未知后缀抛 `invalid_request`。`index.html` 响应时会注入令牌与版本 meta（见 §3.1）。

---

## 参考

本文依据以下源码（路径相对项目根，正斜杠）：

- 路由与处理函数：`app/api/handlers.py`、`app/api/router.py`
- 请求解析与响应：`app/api/request.py`、`app/api/responses.py`
- 服务与安全：`app/api/http_server.py`、`app/api/security.py`、`app/api/tickets.py`
- 错误模型：`app/core/errors.py`；配置与默认值：`app/core/config.py`
- 服务层：`app/services/connection_manager.py`、`app/services/session.py`、`app/services/filesystem.py`、`app/services/transfer.py`、`app/services/search.py`（检索的后台线程、预算与截断、跳过目录、中止）
- 连接层：`app/ssh/sftp_client.py`、`app/ssh/sftp_transport.py`、`app/ssh/sftp_protocol.py`、`app/ssh/known_hosts.py`、`app/ssh/askpass.py`、`app/ssh/ssh_launcher.py`
- 数据模型与工具：`app/models/connection.py`、`app/models/entry.py`、`app/utils/paths.py`
- 前端调用方：`frontend/assets/js/api.js`、`frontend/assets/js/app.js`、`frontend/assets/js/transfer.js`、`frontend/assets/js/search.js`（检索面板：发起、轮询、中止、清空、定位）、`frontend/index.html`
- 相关文档：`.md`（§3.1 功能分级、§3.2 首版不做、§4.2 API 草案、§10 安全要求）、`docs/DECISIONS.md`（D-006/D-007/D-009/D-010/D-014）、`docs/ARCHITECTURE.md`、`docs/SECURITY.md`
