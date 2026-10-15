# tests/e2e 目录索引

端到端测试：真实浏览器（无头 Edge + 无痕 + 全新临时配置目录）驱动完整链路
「浏览器 → 本机 HTTP 服务 → SSH/SFTP → 远程文件系统」。

| 文件 | 作用 | 需要 WSL 测试床 |
| --- | --- | --- |
| support.py | 标准库实现的 CDP over WebSocket 客户端与 Edge 启动器；页面辅助函数 | 否 |
| test_browser_flow.py | 浏览器里的连接、目录浏览、主机密钥确认、密码提示与失败上报 | 前两个类需要 |
| test_browser_regressions.py | 阶段一缺陷②③的浏览器回归：远端目录消失后的「已过期」列表与重试入口；已有活动连接时新建连接不得把文件区打回占位页 | 是 |
| test_browser_sidebar.py | 阶段二侧边栏：窄/常规/宽三种宽度下的布局、长名称换行不重叠、四种连接状态一眼可分 | 是 |
| test_browser_search.py | 阶段三检索界面（4 项）：搜索 → 结果表（名称/类型/所在目录/大小/修改时间）→ 定位跳转并高亮 → 大小写不敏感与无匹配提示 → 清空 → 中止并释放连接 | 是 |
| artifacts/ | 运行时截图产物（不入库，可随时删除） | - |

运行方式：

    python -m unittest discover -s tests/e2e -t .

没有装 Edge 或没有测试床时相关用例自动跳过（不是失败）。
