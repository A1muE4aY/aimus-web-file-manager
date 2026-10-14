# tests/integration/ 索引

集成测试：真实 HTTP 服务 + 真实 `ssh` / `sftp` 子进程 + 真实 sshd（WSL 测试床，决策 D-012）。运行：

```powershell
wsl -d Ubuntu bash scripts/testbed_wsl.sh up     # 先起测试床（幂等）
python -m unittest discover -s tests/integration -t .
```

测试床不在时，用例通过 `skipUnless` **跳过而不是失败**；`scripts/test.py` 会把跳过数单独提示出来。

| 文件 | 覆盖 |
|---|---|
| `support.py` | 公共支撑：定位测试床、构造连接配置、起临时 HTTP 服务、统计残留 ssh 进程（验收项 T-013） |
| `test_api_flow.py` | HTTP 主链路：连接 → 列目录 → 预览 → 上传 → 下载 → 断开（T-001 / T-003 / T-006 / T-009） |
| `test_connection_flow.py` | 连接层主链路：真实 `ssh`/`sftp` 子进程、错误路径、进程清理 |
| `test_password_auth.py` | 密码认证链路：断言服务端日志出现 `Failed password for <user>`（非 root 测试床读不到 /etc/shadow，所以只证明密码送达） |
