# tests/security 目录索引

安全测试层（规划文档 §7.2）。这些用例**验证的是防线本身**，与功能测试分开：
失败时的含义是「安全约束被破坏」，不是「功能没做出来」。

| 文件 | 覆盖 | 需要测试床 |
| --- | --- | --- |
| support.py | 不依赖测试床的真实 HTTP 服务句柄（临时 known_hosts + 可配置连接表） | 否 |
| test_web_security.py | 未授权调用、CSRF / DNS 重绑定、静态资源穿越、响应头策略、前端无在线地址 | 否 |
| test_credentials.py | 密码不进配置文件、不回显、不进日志、不进 ssh 命令行 | 否 |
| test_path_traversal.py | 远端路径语义（.. 由服务端 REALPATH 解析、只解码一次、NUL/超长拒绝、上传名不得穿越） | 是 |
| test_host_key.py | 首次连接必须人工确认（T-005）、密钥变化是硬失败且不自动覆盖、accept-new 才写库 | 是 |

需要测试床的用例在 data/testbed/id_ed25519 或 127.0.0.1:2222 不存在时
**跳过（skip）而不是失败**，见 tests/integration/support.py 的 require_testbed。
