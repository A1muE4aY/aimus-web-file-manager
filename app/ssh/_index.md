# app/ssh/ 索引

连接层：一切与 `ssh` / `sftp` 子进程打交道的东西都在这里。私钥与密码**从不离开本进程**，更不到浏览器。

| 文件 | 用途 |
|---|---|
| `ssh_launcher.py` | 构造 `ssh` 命令行与运行环境（`BatchMode`、`StrictHostKeyChecking`、`UserKnownHostsFile`、keepalive…） |
| `askpass.py` | `SSH_ASKPASS` 辅助程序：密码只落到临时文件，认证结束立即销毁（决策 D-008） |
| `known_hosts.py` | 主机密钥采集、指纹计算、信任库读写与比对（安全关键：首次连接要用户核对指纹，变更要拒绝） |
| `sftp_protocol.py` | SFTP v3 协议编解码：纯标准库实现，逐字段对应 RFC/草案 |
| `sftp_transport.py` | `ssh -s sftp` 子进程与协议帧收发、超时、进程清理 |
| `sftp_client.py` | 面向文件系统的高层操作：列目录、stat、读块、写块、mkdir、rename、remove |
