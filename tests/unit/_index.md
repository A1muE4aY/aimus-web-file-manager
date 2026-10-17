# tests/unit/ 索引

纯单元测试：不连网、不起进程、不碰真实 SSH。运行：

```powershell
python -m unittest discover -s tests/unit -t .
```

| 文件 | 覆盖 |
|---|---|
| `test_config.py` | 配置解析与校验、原子保存、默认值（决策 D-006 / D-009）、发现段的取值范围与 `to_dict` 往返（阶段五顺手修掉的 `max_edit_bytes` 丢失也在这里钉住） |
| `test_launcher.py` | 统一启动器 `scripts/launcher.py`（58 项，用 `importlib` 直接加载该脚本；Windows 上跳过 POSIX SIGTERM 那 1 项）：默认端口 32579 与解析器默认值、未知命令退出码 2、映像名判定 `looks_like_python`、PID 文件的读写与坏格式容错、`tail_text` 取尾、四态状态文案、配置加载与 `--port` 覆盖、`build_argv`（阶段三 D-A：配置不存在时不得传 `--config`）、POSIX 的 SIGTERM 处理器；v0.1.3 §5 新增三组：`BrowserLaunchTest`（Windows 走 `os.startfile`/ShellExecute、`OSError` 只报错不抛、POSIX 依次试 `xdg-open`/`gio`/`sensible-browser`、无图形环境时说明缺什么）、`PauseTest`（`AWFM_NO_PAUSE` 与无 TTY 都不等、交互时等回车、EOF 不外泄）、`StartBrowserTest` + `QuickStartTest` + `DispatchTest`（浏览器**只在健康检查通过之后**打开、`--no-browser` 是唯一开关、打不开仍算启动成功且窗口留住、子进程始终带 `--no-browser` 避免弹两次、健康检查超时算失败且不开浏览器、空参数 → `quick` 且按启动超时、裸选项 → `start`） |
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
| `test_fileops.py` | 文件操作（95 项）：重命名、新建（排他打开 EXCL、并发抢占、非法名与断线）、复制（文件/目录树/权限位/符号链接跳过/确认覆盖）、移动（含部分失败记账）、递归删除的预算与深度、批量删除与批量压缩解压、压缩包布局与符号链接以链接本身入包、解压的越界拒绝与覆盖策略 |
| `test_ssh_guide.py` | SSH 教程与实现的「不许各说各话」检查（13 项）：A~L 章节齐全且有序、`build_sftp_command` 实际发出的每个 `-o` 选项键都在教程附录 A 有记录、附录里的 `ConnectTimeout` / `ServerAliveInterval` / `known_hosts` 默认值与 `app/core/config.py` 的 `DEFAULTS` 一致、`AUTH_METHODS` 两种认证方式各有章节、网页端口取自配置且写明「不是 SSH 服务端」、验证状态标记与「不出现私钥材料/模板标记」纪律（决策 D-021） |
| `test_discovery.py` | 在线虚拟机发现（48 项）：五层取材的解析函数用真实格式样本（清单 / `.vmx` / DHCP 租约 / `vmnetdhcp.conf` / 邻居表 / `arp -a`）、探测四态用假 socket、三态融合用临时环境 + 注入探测、注册处的忙 / 取消 / 保留上限 |
| `test_frontend_layout.py` | 前端布局与新建/多选的静态约定（30 项，v0.1.3 §1~§4）：`colgroup` 七列与 `thead` 同序、`rowNode` 逐列构造同序、操作列表头与按钮居中、`ACTION_ORDER` 七个动作与文案顺序、各类型启用条件（编辑仅文件 / 复制不需写权限 / 剪切与重命名与删除与压缩需写权限 / 解压还需压缩包）、禁用时 title 必须给原因、七个槽位在各断点的列数（44/40/38/4+3）、七按钮同一盒高、v0.1.2 的 `row-actions` 五槽位已清除、断点收列顺序（1120 权限 / 1020 类型 / 1000 时间 / 740 大小）、预览独立框与滚动层、新建名校验与「不做先查再建」、创建后按刷新结果区分「已创建」与「列表没刷新」、跨连接粘贴拒绝与覆盖重试、多选复选框与操作条、工具栏四个新入口 |
| `test_run_bat.py` | 四个启动外壳的静态纪律（17 项；阶段六建立，v0.1.3 §5 扩到普通/高级两个入口）：两份 `.bat` 全文件 CRLF 且是合法 UTF-8（含 `.gitattributes` 的 `*.bat text eol=crlf`）；引导段必须纯 ASCII（以首个大于 0x7F 的字节为界）；两份 `.bat` 的引导段五个标记齐全（`if defined AWFM_UTF8_READY goto :awfm_utf8_ready`、`chcp 65001 >nul 2>nul`、`set "AWFM_UTF8_READY=1"`、`"%COMSPEC%" /c ""%~f0" %*"`、`exit /b %ERRORLEVEL%`）且守卫排在重跑之前；`if not defined AWFM_UTF8_READY (` 不得出现（防回退到括号块，退出码会被吃成 0）；`scripts\launcher.py" %*` 原样转发、退出码在括号块外取；`EntryDefaultTests` 钉住默认动作（`run.bat`/`run.sh` 不补参数 → 由 launcher 走 `quick`；`run-advanced.bat`/`run-advanced.sh` 无参数补 `menu`，且判断顺序是「先判空、再给 menu、最后透传」）；`ShellScriptTests` 管两份 `.sh` 的 LF 行尾、shebang、`cd "$SCRIPT_DIR"` 与 `command -v` 找 Python |
