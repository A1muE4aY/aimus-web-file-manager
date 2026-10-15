# tests/unit/ 索引

纯单元测试：不连网、不起进程、不碰真实 SSH。运行：

```powershell
python -m unittest discover -s tests/unit -t .
```

| 文件 | 覆盖 |
|---|---|
| `test_config.py` | 配置解析与校验、原子保存、默认值（决策 D-006 / D-009）、发现段的取值范围与 `to_dict` 往返（阶段五顺手修掉的 `max_edit_bytes` 丢失也在这里钉住） |
| `test_errors.py` | 错误模型：状态码来自类属性；构造函数拒绝 `http_status=` 关键字；静态扫描 app/ 防复发 |
| `test_paths.py` | 远程路径与名称校验（验收项 T-008） |
| `test_redact.py` | 日志脱敏（验收项 T-011） |
| `test_logging_setup.py` | 日志轮转、UTF-8、格式化阶段脱敏 |
| `test_atomic.py` | 原子写入不留半截文件 |
| `test_connection_model.py` | 连接模型校验与「密码从不持久化」 |
| `test_entry.py` | 文件条目元数据与不跟随符号链接 |
| `test_filesystem.py` | 排序、截断、预览、写入门禁 |
| `test_known_hosts.py` | 信任库解析、指纹格式、写入，以及采集失败必须是结构化错误 |
| `test_askpass.py` | `SSH_ASKPASS` 辅助程序的生命周期与清理（决策 D-008） |
| `test_ssh_launcher.py` | `ssh` 命令行构造，每条选项对应一次真实故障 |
| `test_sftp_protocol.py` | SFTP v3 编解码，每个断言对应一次真实踩坑 |
| `test_request.py` | 请求包装：百分号解码、查询参数、JSON 体 |
| `test_router.py` | 正则路由器 |
| `test_tickets.py` | 下载票据 |
| `test_api_security.py` | API 层安全校验（令牌、Host、来源、方法） |
| `test_permission_sync.py` | 写权限同步（阶段一缺陷①）：活动会话持有的连接必须可热更新，而不是建连时的快照 |
| `test_search.py` | 检索服务（36 项）：匹配与排序、depth 语义、四道预算与截断、跳过与取消、单连接并发限制 |
| `fake_sftp.py` | 内存版 SFTP 假件（不是 mock）：真跑 tar/zip 字节流与权限语义、rename 不覆盖、offline 抛 NotConnected，供在线编辑与文件操作单测使用 |
| `test_editor.py` | 在线编辑（43 项）：文本识别与二进制/非 UTF-8 拒绝、换行与 BOM 记忆、sha256/mtime 冲突、备份改名与回滚、无残留临时文件 |
| `test_fileops.py` | 文件操作（60 项）：重命名、递归删除的预算与深度、压缩包布局与符号链接以链接本身入包、解压的越界拒绝与覆盖策略 |
| `test_discovery.py` | 在线虚拟机发现（48 项）：五层取材的解析函数用真实格式样本（清单 / `.vmx` / DHCP 租约 / `vmnetdhcp.conf` / 邻居表 / `arp -a`）、探测四态用假 socket、三态融合用临时环境 + 注入探测、注册处的忙 / 取消 / 保留上限 |
