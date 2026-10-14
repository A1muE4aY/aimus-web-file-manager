# app/api/ 索引

HTTP 边界层：把请求变成参数、把异常变成响应。**这一层不做业务判断**，业务在 app/services/ 与 app/ssh/。

| 文件 | 用途 |
|---|---|
| `http_server.py` | `ThreadingHTTPServer` + `AwfmRequestHandler`：只绑回环、覆盖 `version_string()`（Server 头不带尾随空格与 Python 版本）、吞掉连接被重置的噪声异常 |
| `router.py` | 极简正则路由表：路径模板 → 处理函数，零依赖 |
| `request.py` | 请求包装：百分号解码、查询参数、JSON 请求体解析与大小限制 |
| `handlers.py` | 全部 API 处理函数（health / session / connections / connect / files / stat / preview / upload / download-ticket / host-keys …） |
| `responses.py` | 响应构造：`{ok, data}` 与 `{ok: false, error}` 两种信封、统一响应头与 CSP |
| `security.py` | 请求侧校验：令牌、Host、Sec-Fetch-Site / Origin、方法白名单 |
| `tickets.py` | 下载票据：浏览器原生下载带不了自定义头，用短命一次性票据换令牌 |

## 错误到状态码

异常一律是 `app/core/errors.py` 里的子类，状态码来自**类属性** `http_status`（不是构造参数）。
新增错误类型时只覆盖类属性，`scripts/build.py` 会拦住「把 http_status 当关键字参数传」的写法。
