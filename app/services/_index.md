# app/services/ 索引

用例层：把连接层的原语编排成 API 层要的操作，并持有进程内的会话状态。

| 文件 | 用途 |
|---|---|
| `connection_manager.py` | 连接配置的增删改查 + 会话注册表；删除连接前先断开；活动会话达到 `ssh.max_sessions` 时回收最早的一条 |
| `session.py` | 一条远程会话：状态机（idle/connecting/connected/error）、时长、最近错误、SFTP 客户端句柄 |
| `filesystem.py` | 目录浏览与文件元数据：排序、截断、符号链接标记、预览读取、写入门禁（`allow_write`） |
| `transfer.py` | 上传与下载：流式收发、大小上限、临时文件 + 原子改名（决策 D-007） |
