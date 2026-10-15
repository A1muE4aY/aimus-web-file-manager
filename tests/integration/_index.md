# tests/integration/ 索引

集成测试：真实 HTTP 服务 + 真实 `ssh` / `sftp` 子进程 + 真实 sshd（WSL 测试床，决策 D-012）。运行：

```powershell
wsl -d Ubuntu bash scripts/testbed_wsl.sh up     # 先起测试床（幂等）
python -m unittest discover -s tests/integration -t .
```

测试床不在时，用例通过 `skipUnless` **跳过而不是失败**；`scripts/test.py` 会把跳过数单独提示出来。

| 文件 | 覆盖 |
|---|---|
| `support.py` | 公共支撑：定位测试床、构造连接配置、起临时 HTTP 服务、统计残留 ssh 进程（验收项 T-013）、`testbed_command` 造景、`search_fixture` 检索树（中文名 / 无权限目录 / 符号链接 / 目录环 / 大量文件）、`edit_fixture` / `ops_fixture` 编辑与文件操作夹具、`upload_bytes` / `download_bytes` 走完整 HTTP 往返取字节、`Client.put`、发现扫描的发起与等待（`start_discovery_scan` / `wait_discovery_scan` / `scan_and_wait`） |
| `test_api_flow.py` | HTTP 主链路：连接 → 列目录 → 预览 → 上传 → 下载 → 断开（T-001 / T-003 / T-006 / T-009） |
| `test_connection_flow.py` | 连接层主链路：真实 `ssh`/`sftp` 子进程、错误路径、进程清理 |
| `test_password_auth.py` | 密码认证链路：断言服务端日志出现 `Failed password for <user>`（非 root 测试床读不到 /etc/shadow，所以只证明密码送达） |
| `test_write_permission_sync.py` | 写权限同步（阶段一缺陷①）：全程只从 HTTP API 进入，覆盖「改配置 → 活动会话立刻生效」 |
| `test_edit_api.py` | 在线编辑 API（31 项）：读文本元数据与换行/BOM、保存后字节回到远端、内容与 mtime 冲突 409、只读文件 403、写权限关闭 401、`security.max_edit_bytes` 生效（413） |
| `test_fileops_api.py` | 文件操作 API（30 项）：重命名 / 删除（含递归与两类符号链接回归）/ 压缩成 .tar.gz 并核验成员 / 解压（zip 与 tar、重复解压跳过、覆盖）/ 越界归档整包拒绝 / 只读连接四个写入口 401 / 压缩解压不新增 ssh 进程 |
| `test_discovery_api.py` | 在线虚拟机发现的四个端点（10 项）：环境概览的六个来源与权限说明、扫描结束后计数自洽、被探测的地址必须落在读出来的网段内且只探 22、本机网卡与网关既不列出也不探测、并发扫描 409、中止之后槽位真的空出来。**不依赖 WSL 测试床**（读的是宿主机自己的 VMware 状态），没装 VMware 的机器整类跳过 |
