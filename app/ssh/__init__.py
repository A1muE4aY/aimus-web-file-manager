"""连接层：SSH 子进程启动器、SFTP v3 协议编解码、known_hosts 校验。

设计依据见 docs/DECISIONS.md D-011（原生 SFTP v3 协议）与 D-012（测试床）。
本层是唯一允许调用 `subprocess` 的地方。
"""
