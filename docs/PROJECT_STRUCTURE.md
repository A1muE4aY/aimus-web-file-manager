# AWFM 目录结构与文件归属

> 本文是**开发验收标准**之一（规划文档 §5.1）。新增文件前先在这里找到它的归属；
> 找不到归属就先放进 `.temp/`，并回来补规则，而不是随手扔在根目录。

## 1. 顶层布局

```
aimus-web-file-manager/
├── app/                 应用主代码（Python 3 标准库，零第三方依赖）
│   ├── __init__.py      版本号与包元信息
│   ├── main.py          服务入口：参数解析、配置装载、HTTP 服务启动
│   ├── api/             HTTP API 路由与请求处理
│   ├── core/            配置装载与校验、错误模型与 HTTP 状态映射
│   ├── services/        连接管理、会话状态机、文件业务逻辑、传输语义
│   ├── ssh/             SSH/SFTP 适配层：ssh 子进程、SFTP v3 协议、主机密钥、askpass
│   ├── models/          领域数据模型（连接、目录条目）
│   └── utils/           无业务依赖的通用工具：路径校验、日志脱敏、原子写、日志配置
├── frontend/            前端资源（原生 HTML/CSS/JS，无构建步骤）
│   ├── index.html
│   └── assets/
│       ├── css/
│       ├── js/          （11 个 ES 模块，见 assets/js/_index.md）
│       └── icons/
├── config/              配置模板与默认配置
│   ├── config.example.json
│   └── .gitignore
├── tests/               自动化测试
│   ├── unit/            无外部依赖；路径规范化、解析、校验、错误映射
│   ├── integration/     对真实 SFTP 服务端；默认标记为需要环境
│   ├── e2e/             浏览器端到端（Edge InPrivate）
│   ├── security/        路径穿越、未授权调用、凭据泄漏、主机密钥
│   └── fixtures/        测试夹具（合成数据，**不含真实凭据**）
├── scripts/             开发、测试、启动与打包脚本（动词开头）
│   ├── launcher.py      统一启动器：启动/状态/停止/重启/日志/自检（run.bat 与 run.sh 的实现）
│   ├── start.py         前台启动的兼容入口（等价 run.bat start --foreground）
│   ├── test.py          四层测试批量运行器（unit/integration/security/e2e + 语法校验）
│   ├── build.py         构建前静态校验（8 项，发行门禁）
│   ├── package.py       便携版打包、清单校验与自检
│   └── testbed_wsl.sh   WSL 非 root sshd 测试床（up / status / stop，幂等）
├── docs/                设计与交付文档（本层根目录，不再分包子目录）
│   └── reports/         阶段报告、故障分析、部署记录、最终总结
├── data/                运行时配置与数据（.gitignore）
├── logs/                运行日志（.gitignore）
├── dist/                发行包产物（.gitignore）
├── run.bat              Windows 统一入口（双击进交互菜单，参数原样转给 scripts/launcher.py）
├── run.sh               Linux/macOS 统一入口（exec 转发，退出码与信号原样传递）
├── LICENSE              MIT 许可证
├── README.md            项目入口说明
├── AGENTS.md            本工作区白名单与纪律（唯一权威的顶层条目表）
├── .gitignore           忽略运行数据、日志与构建产物
├── .gitattributes       仓库内统一 LF 行尾（scripts/testbed_wsl.sh 要在 WSL 里执行）
├── .temp/               会话草稿，可整体清空
└── .archive/            本项目归档：duplicates/ deps/ junk/ misc/
```

## 2. 归属判定顺序（第一个命中即停）

1. 是**应用源码** → `app/<最贴近的分包>/`
2. 是**页面/样式/脚本/图标/字体** → `frontend/assets/<类别>/`
3. 是**测试** → `tests/<层级>/`；测试数据 → `tests/fixtures/`
4. 是**文档** → `docs/`（阶段报告 → `docs/reports/`）
5. 是**可重复执行的开发/构建动作** → `scripts/`
6. 是**运行时产生的**（配置、日志、缓存、临时下载）→ `data/` 或 `logs/`
7. 拿不准 / 一次性 → `.temp/`
8. 是重复件、可重建依赖、锁文件、杂物 → `.archive/<对应子目录>/`

## 3. 各目录纪律

| 目录 | 放什么 | 明确不放 |
|---|---|---|
| `app/` | 应用源代码 | 测试、运行日志、用户数据、临时脚本 |
| `frontend/` | 离线可用的页面、脚本、样式、本地资源 | 任何在线 CDN、在线字体、外链 JS/CSS |
| `config/` | 默认配置与模板 | 真实密码、私钥、可用的个人 SSH 配置 |
| `tests/` | 可独立执行的测试 | 依赖真实虚拟机的用例**必须**单独标记，不得混进 `unit/` |
| `scripts/` | 启动、测试、构建、打包 | 业务逻辑（业务逻辑属于 `app/`） |
| `docs/` | 设计决策、开发过程、测试报告、用户文档 | 生成物、渲染产物、日志 |
| `data/` `logs/` | 运行时产物 | 任何会被提交的内容 |
| `dist/` | 可交付构建结果 | 源代码修改入口 |

## 4. 命名规范

| 对象 | 规则 | 禁止 |
|---|---|---|
| Python 模块 | 小写 + 下划线：`host_keys.py` | `Test.py`、`tmp.py`、`a.py` |
| Python 测试 | `test_<被测模块>.py` | `tests.py` |
| 脚本 | 动词开头 + 小写下划线：`build_portable.py` | `test.bat`、`run.py` |
| 前端资源 | 小写 + 连字符：`file-list.js` | `fileList.js`、`new.js` |
| 文档 | 大写下划线：`TEST_REPORT.md`；报告 `PHASE-03-CORE.md` | `新建文档.md` |
| 发行包 | `AWFM-<版本>.zip`；解压根目录固定 `AWFM/` | `-windows-x64` 等平台后缀、带版本号的根目录 |
| 截图 | `截图<两位序号>-<内容>.png` | UUID 名、系统默认名 |
| 目录 | 英文小写 + 连字符 | 中文目录名、`新建文件夹`、`temp` |

## 5. 例外情况

1. **`.md`（根目录）**：用户提供的原始规划文档，保持原名与原位置，不重命名、不移动、不改写。
2. **`.git`、`.dsh`**：工具目录，不计入散件。
3. **`data/` `logs/` `dist/`**：由程序或脚本按需创建，**不在仓库里预建空目录**。
4. **测试夹具中的密钥**：只能使用一次性生成的测试密钥对，且必须能明确区分于真实凭据。

## 6. 自检清单（每次会话结束前）

1. 根目录有没有新增计划外的散件？
2. `docs/` 里有没有同一份交付物的两个副本？
3. `__pycache__` / `node_modules` / `*.log` 有没有混进源码或文档目录？
4. 新增文件 ≥ 5 个的目录，`_index.md` 有没有更新？
