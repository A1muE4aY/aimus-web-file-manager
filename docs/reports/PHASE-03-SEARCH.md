# 阶段 03 报告：远端文件检索（v0.1.1）

## 1. 报告信息

| 项目 | 内容 |
|---|---|
| 项目版本 | v0.1.0（v0.1.1 开发中，版本号在阶段六统一提升） |
| 报告日期 | 2026-10-16 |
| 开发阶段 | 阶段 03 —— 添加远端文件检索（任务书 `2.md` §四，`2.md:94-122`） |
| 对应 Git 提交或标签 | `6e619f0`（2026-10-16）。阶段一~三的改动共用 `app/api/handlers.py` 等文件，合并为一次提交，提交信息里逐阶段列明 |

## 2. 阶段目标

任务书 §四要求（`2.md:94-122`）：

1. **基本功能**：文件区提供搜索入口；按文件名或目录名匹配；默认搜索当前目录及子目录（若只搜当前目录必须明确标注范围）；大小写不敏感；结果显示名称 / 路径 / 类型 / 大小 / 修改时间；点击结果可定位或打开；可清空、可取消、无结果有提示；有进度或状态反馈且允许中止。
2. **性能与可靠性**：不得一次性加载整个文件系统；逐目录限制并发与资源，不耗尽 SSH；处理无权限目录、符号链接、断连、远端目录消失、网络中断；符号链接要有明确策略防止循环；不跨出授权范围、不允许 `..` 越权；必须走既有 SFTP 机制，**不为检索在远端执行任意 Shell**；明确区分「搜索失败」与「没有匹配」。
3. **测试要求**：覆盖普通文件、中文名、大小写、嵌套目录、空结果、无权限目录、符号链接、远端断开、大量文件。

## 3. 实际完成情况

**已完成**

- 服务层 `app/services/search.py`：后台线程逐目录列举（只调用既有的 SFTP `listdir`），四道预算与截断、跳过读不到的目录并上报、符号链接只报不跟随、随时可中止、同一连接同时只允许一个检索。
- 三个 HTTP 端点（`app/api/handlers.py:161` 起，路由表 `app/api/handlers.py:294-317` 的第 20~22 项）：`POST /api/connections/{id}/search`（202 + 快照）、`GET /api/searches/{search_id}`、`DELETE /api/searches/{search_id}`（幂等中止）。错误模型新增 `SearchBusy`（`search_busy`，409，`app/core/errors.py:193`）。
- 前端：搜索栏与结果面板（`frontend/index.html:80` / `:88`）、模块 `frontend/assets/js/search.js`（发起 / 轮询 / 中止 / 清空 / 结果表 / 把「没有匹配」与「搜索失败」分开提示）、`frontend/assets/js/files.js` 的 `locate(parent, name)`（跳到所在目录、选中并高亮）。结果表列出名称 / 类型 / 所在目录 / 大小 / 修改时间。
- 四层测试：单元 36 项（`tests/unit/test_search.py`）、集成 15 项（`tests/integration/test_search_api.py`）、安全 18 项（`tests/security/test_search_paths.py`）、端到端 4 项（`tests/e2e/test_browser_search.py`），另加错误模型全量覆盖测试补登 `SearchBusy`（`tests/unit/test_errors.py`）。
- 文档：`docs/API.md`（22 个端点，新增 §5.20–5.22）、`docs/USER_GUIDE.md`（新增第 8 章「文件检索」，后续章节顺延为 9~13 章）、`docs/CHANGELOG.md`（v0.1.1 段）、本报告与各层 `_index.md` 登记。

**部分完成**

- 符号链接采取**明确策略：只报告、不跟随**。任务书只要求「策略明确 + 防循环」，因此目录环（`循环目录/回环 -> 搜索根`）与指向根外的链接都不会被走进去；代价是链接指向的内容不在结果里，这一取舍写进了 `docs/USER_GUIDE.md` §8.3 与 §8.4。
- 断连场景的断言是 `status ∈ {failed, cancelled}`：远端消失时列举会立刻抛 `not_connected`（`status=failed`），但若断连恰好发生在取消路径上则为 `cancelled`，这是固有竞态，测试按实际情况二选一断言（`tests/integration/test_search_api.py`）。
- 检索上限（500 命中 / 2000 目录 / 100000 条目 / 45 秒）是模块常量，暂不可配置。

**未完成及原因**

- 不搜文件内容、不支持通配符与正则——任务书只要求按名称匹配，未要求内容检索，留待后续版本。
- 真实桌面 CU 验收（含真实 CentOS 检索）属于任务书阶段六，本阶段不做；本阶段证据全部来自自动化测试。

## 4. 技术实现

- **异步两段式**：`POST …/search` 立即返回 202 与快照，扫描在后台线程 `awfm-search-<id>` 里跑，进度由 `GET /api/searches/{id}` 轮询（前端 700 ms 一次）。理由：远端目录列举可能持续几十秒，同步接口会占住连接并让「中止」无法生效。
NaN
- **排序**：目录 → 符号链接 → 文件 → 其他，组内按名称 `casefold` 再按路径，保证同名大小写稳定。
- **预算检查在「发现处」也在「条目循环内」**：`max_dirs` 在目录入队时检查，`max_entries` / `max_results` 每处理一个条目检查一次。理由：单个目录里几千个条目是在同一层走完的，只在最外层检查等于没有上限。
- **取消**：`threading.Event` 在每个条目与每个目录处各检查一次，因此点「中止」后几乎立刻停下；中止不算截断（`truncated` 保持 `false`）、不算失败（`error` 为 `None`），连接槽位立刻释放。
- **跳过而不是失败**：读不到的目录只计入 `skipped_dirs` / `skipped`（明细最多 20 条），连续 10 个目录失败才整体失败；真断连仍按 `not_connected` 上报。
- **参数形状检查先于找会话**（`app/api/handlers.py:161`）：`path` / `query` 的类型与空值先校验，再取会话。理由：畸形请求的错误不该随连接状态变化，否则「没连接」时 400 会变成 409。
- **路径安全**：复用 `app/utils/paths.py` 的 `validate_remote_path`（拒绝非绝对路径、NUL、超过 4096 字节），`..` 交给服务端 `realpath` 解析后再判定，调用方不做词法折叠。
- **注册表**：`SearchRegistry` 只保留最近 20 条**已结束**的记录（`_prune_locked`），超出后 `GET`/`DELETE` 返回 404「搜索不存在或已过期。」；断连时 `cancel_for_connection` 停掉该连接的全部检索。

## 5. 测试结果

命令（工作目录 `E:/Project/aimus-web-file-manager`）：

```
python scripts/test.py          # 四层批量运行器：unit -> integration -> security -> e2e
```

实际输出（2026-10-16，测试床 127.0.0.1:2222 在线，Edge 可用）：

```
== 语法校验：python -W error::SyntaxWarning -m compileall -q app tests scripts ==
通过（0.28s）

unit           346 用例    0 失败    0 错误    0 跳过    2.69s  OK
integration     37 用例    0 失败    0 错误    0 跳过   13.89s  OK
security        59 用例    0 失败    0 错误    0 跳过   12.41s  OK
e2e             13 用例    0 失败    0 错误    0 跳过   74.15s  OK
合计             455 用例    0 失败    0 错误    0 跳过  103.15s

全部通过。
```

本阶段相关用例分布：

| 层 | 文件 | 用例数 | 覆盖点 |
|---|---|---|---|
| 单元 | `tests/unit/test_search.py` | 36 | 匹配与排序、`depth` 语义、四道预算与截断原因、跳过与取消、单连接并发 |
| 集成 | `tests/integration/test_search_api.py` | 15 | 中文名各层命中、大小写、目录优先、路径与深度字段、空结果非错误、无权限目录被跳过并上报、符号链接不跟随且不越界（根外 `only-here.txt`）、取消、中止后槽位释放、并发 409、检索期间列目录不受影响、断连原因 |
| 安全 | `tests/security/test_search_paths.py` | 18 | 无令牌 401、未知/非小写十六进制 id 404、畸形 body 400（形状检查先于会话）、相对路径 / NUL / 超长 / 指向文件 400、关键词校验（含放行制表符）、被拒后不占槽位、**检索前后 ssh 进程数不变**（T-013）、检索不改动远端目录 |
| 端到端 | `tests/e2e/test_browser_search.py` | 4 | 搜索 → 结果表（含类型列）→ 「定位」跳转并高亮 → 面板不关；大小写不敏感与无匹配提示；清空回到空闲；中止并释放连接后再搜一次成功 |

测试床造景（`tests/integration/support.py` 的 `search_fixture`）：中文名、大小写、嵌套、`chmod 000` 的无权限目录、符号链接、目录环、根外目录、4500 文件的批量树；摆整棵树约 0.61 s，扫完 151 目录 / 4650 条目约 0.56 s。端到端夹具另在 `$HOME` 下摆 1500 个空目录，让「运行中」状态可观测。

端到端截图证据（每次运行重新生成，`tests/e2e/artifacts/` 已加入 `.gitignore`）：
`browser-search-locate-d79ac4ae.png`、`browser-search-no-match-d79ac4ae.png`、`browser-search-cancelled-d79ac4ae.png`。

## 6. 问题与风险

本阶段发现并修掉 5 处真实缺陷：

1. 清空检索后结果表仍留着隐藏的旧行（`frontend/assets/js/search.js` 的 `render()` 先清空再判 `idle`）——端到端用例断言 `#search-body` 行数为 0 时暴露。
2. 空闲态与搜索后的范围文案不一致（「范围：当前目录及其子目录」与「范围：<root> 及其子目录」）——按任务书「必须明确标注范围」修正并在用例里钉住。
3. 畸形请求的 400 会随连接状态变成 409——把形状检查挪到找会话之前（`app/api/handlers.py:161`）。
4. 单个目录的条目数不受预算约束（只在最外层检查）——预算检查移入条目循环。
5. 新增 `SearchBusy` 后错误模型的全量覆盖测试未同步登记，全量回归报 `test_all_subclasses_are_covered_by_this_test` 失败——补登后四层 455 项全绿（`tests/unit/test_errors.py`）。

风险与已知限制：

- 扫描耗时取决于远端磁盘与目录规模：实测 500 目录约 1.42 s，平铺 2000 个以上子目录会立刻触发 `max_dirs` 截断（因此「可观测的运行中状态」需要把目录数压在 2000 以下）。
- 断连与取消之间存在固有竞态，测试只能二选一断言（见 §3）。
- 上限是常量；符号链接不跟随意味着链接指向的内容搜不到；不搜文件内容。
- 端到端依赖本机 Edge 与在线测试床，缺少任一条件时该层会被跳过——按本项目记录纪律，**跳过不算通过**，运行器会单独列出跳过数。

## 7. 文档与交付物

- 代码：`app/services/search.py`（新增）、`app/api/handlers.py`、`app/core/errors.py`、`frontend/assets/js/search.js`（新增）、`frontend/assets/js/files.js`、`frontend/assets/js/api.js`、`frontend/assets/js/state.js`、`frontend/assets/js/app.js`、`frontend/index.html`、`frontend/assets/css/app.css`。
- 测试：上表 4 个文件，另加 `tests/unit/test_errors.py` 与 `tests/integration/support.py`（造景基建）、`tests/e2e/artifacts/` 截图。
- 文档：`docs/API.md`（§5.20–5.22、错误码表、§7.1 版本说明）、`docs/USER_GUIDE.md`（第 8 章与章节顺延）、`docs/CHANGELOG.md`（v0.1.1 段）、本报告、`app/services/_index.md` 与 `tests/{unit,integration,security,e2e}/_index.md` 登记。
- 未产出：打包产物与校验和仍是 v0.1.0 的那一份（任务书阶段六要求重新构建）。

## 8. 阶段结论

阶段三（远端文件检索）**功能与测试已完成**：后端检索服务、三个端点、前端搜索界面与「定位」跳转全部落地，四层共 455 项测试全绿（其中本阶段新增 73 项 + 1 项登记修正），任务书 §四的三组要求逐条有实现与测试证据。

允许进入阶段四（远端文本文件编辑与文件操作）。遗留事项：CU 验收、版本号提升与重新打包属阶段六；内容检索、可配置上限、跟随符号链接的选项留待后续版本。
