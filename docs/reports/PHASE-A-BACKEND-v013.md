# 阶段 A 报告：后端能力与接口（v0.1.3）

## 1. 报告信息

| 项目 | 内容 |
|---|---|
| 版本 | v0.1.3 |
| 阶段 | A —— 后端能力与接口 |
| 日期 | 2026-10-17 |
| 依据 | `dev_guide/0.1.3_.md` §4「新建文件与文件夹 / 多选」的服务端部分，以及 §1、§3 需要的批量端点支撑 |
| 结论 | 完成。新增 3 个端点、扩展 3 个既有端点；单元测试 `tests/unit/test_fileops.py` 95 项、集成测试 `tests/integration/test_fileops_api.py` 48 项全部通过 |

## 2. 阶段目标

任务书 §4 要求界面能「在当前目录新建文件与文件夹」并「多选后批量复制、剪切、压缩、解压、删除」。这两句话落到后端就是三件事：

1. 有一个**排他**的创建入口，同名条目必须被拒绝而不是静默覆盖，且不能是「先查再建」；
2. 有一个能一次处理多个条目的删除/压缩/解压通道，且中途失败时必须如实报告「已经做成了什么、哪一条失败」；
3. 复制与移动本来就只有单条接口，需要补批量语义与冲突判定。

同时任务书 §4 的安全条款要求「服务端重新验证权限与路径」「前端禁用不等于安全」「失败不得假成功」，所以这一阶段的所有新能力都必须在服务层重新做权限与路径校验，不能只依赖界面把按钮变灰。

## 3. 实际完成情况

| # | 要求 | 实现位置 | 状态 |
|---|---|---|---|
| A-1 | 新建空文件与空目录，排他创建 | `app/services/fileops.py:218` `create_entry()` | 完成 |
| A-2 | 新建前校验名称（空、`.`、`..`、分隔符、NUL、超长） | 复用 `app/core/paths.py` 的 `validate_remote_name()`，在 `create_entry()` 内先调用 | 完成 |
| A-3 | 父目录必须真实存在且是目录 | `app/services/fileops.py:190` `_directory_target()` | 完成 |
| A-4 | 同名条目拒绝且不改动原有内容 | `app/services/fileops.py:209` `_already_exists()` | 完成 |
| A-5 | 批量复制（含目录树、权限位、上限） | `app/services/fileops.py:416` `copy_entries()` + `:336` `_copy_tree()` | 完成 |
| A-6 | 批量移动（不覆盖、逐项记账） | `app/services/fileops.py:451` `move_entries()` | 完成 |
| A-7 | 批量删除（部分失败如实报告） | `app/services/fileops.py:567` `delete_entries()` | 完成 |
| A-8 | 批量压缩（多源打包、可选目标目录） | `app/services/fileops.py:689` `compress_entries()` | 完成 |
| A-9 | 批量解压（单包形状不变、多包汇总） | `app/services/fileops.py:1051` `extract_entries()` | 完成 |
| A-10 | 三个新 HTTP 端点与路由注册 | `app/api/handlers.py:409` / `:432` / `:452`，路由表 `handlers.py:561` | 完成 |
| A-11 | 三个既有端点兼容批量而不破坏旧调用 | `handlers.py:478` delete / `:500` compress / `:526` extract | 完成 |
| A-12 | 接口文档与测试索引同步 | `docs/API.md`（35 个端点）、`tests/unit/_index.md:33`、`tests/integration/_index.md:21` | 完成 |

## 4. 技术实现

### 4.1 为什么新建用 `EXCL` 而不是「先查再建」

最常见的写法是先 `lstat` 看目标是否存在，不存在再 `open` 创建。这在**单用户、无并发**的场景里看起来没问题，但它把一次原子判断拆成了两次系统调用：两次调用之间如果有别的进程（或同一个用户的另一个窗口）抢先建了同名文件，后面的创建就会变成一次**静默覆盖**——原来的内容被截断，而用户看到的是「创建成功」。

所以 `create_entry()` 把判断交给远端一次完成（`app/services/fileops.py:218` 起）：

- 文件：`client.open(target, SSH_FXF_WRITE | SSH_FXF_CREAT | SSH_FXF_EXCL, 0o644)` 然后立刻 `close()`，得到一个 0 字节、权限 0644 的空文件；
- 目录：`client.mkdir(target, 0o755)` —— `MKDIR` 本身在协议层就是排他的，目标已存在会返回失败。

`EXCL` 失败时不再依赖错误文本，而是补一次 `lstat`：目标确实存在就用 `_already_exists()` 翻译成「同名条目已经存在。」（带 `extra` 里的 `path`、`type`、`exists: true`），否则把原始错误原样抛出。这样既保住了排他语义，又能给用户一句能看懂的话。单测 `test_creation_uses_an_exclusive_open` 直接断言打开文件时 `pflags` 含 `SSH_FXF_EXCL` 且**不含** `SSH_FXF_TRUNC`——防止以后有人「顺手」加上 `TRUNC` 把语义改回覆盖。

### 4.2 批量的统一记账方式

四个批量函数（`copy_entries` / `move_entries` / `delete_entries` / `extract_entries`）共用同一套约定：

1. 先做**整批**的前置校验（列表非空、每项是字符串、条目数不超上限、源必须存在、目标目录必须是目录），任何一条不合法就在动手之前抛出，不留半成品；
2. 再逐项执行，成功项累积进结果；
3. 中途失败时把已经完成的项塞进异常对象的 `extra`：`exc.extra = dict(exc.extra or {}, done=[...], failed=<当前项>)`，然后原样 re-raise。前端据此显示「已完成 N 项，第 M 项失败」。

这条约定带来一个直接好处：界面上不需要自己猜「到底做成了几个」，服务端报的就是真实做成的数量（`tests/unit/test_fileops.py` 的 `test_a_failed_move_reports_what_already_moved` 与 `test_a_failed_batch_extract_reports_what_already_unpacked` 两项专门钉住它）。

### 4.3 复制与移动：两件不同的事

复制是**读数据再写数据**，所以要考虑字节预算与目录递归：

- 上限：单批 ≤ `MAX_COPY_ENTRIES`（10000，`fileops.py:87`）、累计 ≤ `MAX_COPY_BYTES`（512 MiB，`:90`）、递归深度 ≤ `MAX_TREE_DEPTH`（64，`:84`）；
- 目录树递归复制，权限位取源的 `permissions & 0o777`；
- **符号链接一律跳过**（记进 `skipped`，`code: "symlink_skipped"`），不跟随、不伪造一个普通文件。理由是跟随符号链接会把远端目录树之外的内容悄悄拷进来，而伪造副本会掩盖「这里本来是个链接」这个事实；
- 走 `client.download_chunks()` → `client.upload_stream()` 流式搬运，不把整个文件读进内存。

移动是**改名**，所以只调用 `client.rename()`，并且目标已存在时**一律拒绝**：SFTP v3 的 `RENAME` 本身不覆盖，而「先复制再删」会把一次原子改名退化成两个半成品状态（复制成功、删除失败时源和目标同时存在）。任务书没有要求移动覆盖，所以这里选了更保守也更诚实的语义。

### 4.4 既有端点的兼容扩展

`delete`、`compress`、`extract` 三个端点从 v0.1.2 起就存在，界面和其它调用方都在用。扩展方式是「加字段而不是改字段」：

- 请求体仍接受单条 `path`；新增可选 `paths` 数组（`handlers.py:396` `_payload_paths()`），给了 `paths` 就走批量；
- `compress` 新增 `into`（目标目录，必须是已存在的目录，留空放第一个源所在目录）；响应里 `source` 保留为第一项，另加 `sources` 数组；
- `extract` 单个压缩包时**原样返回** `extract_entry()` 的结果（形状与 v0.1.2 完全一致），多个时才返回 `{archives, count, entries, files, directories, bytes, stopped}`。

这样 v0.1.2 的调用方和测试无需改动，新增能力只是多了几种合法入参。

## 5. 测试结果

| 层 | 文件 | 数量 | 结果 |
|---|---|---|---|
| 单元 | `tests/unit/test_fileops.py` | 95 项（原 61 + 新增 34） | `Ran 95 tests, OK` |
| 集成 | `tests/integration/test_fileops_api.py` | 48 项（原 30 + 新增 18） | `Ran 48 tests in 156.511s, OK` |

新增单元测试按四个类组织（`tests/unit/test_fileops.py`）：`CreateTests`（11 项：空文件 0 字节与 0644、建目录 0755 且可继续放入、`EXCL` 断言、同名拒绝且原字节不变、并发抢占、非法名 7 种、未知 `kind`、目录不存在、父是文件、无写权限、断线）、`CopyTests`（9 项）、`MoveTests`（5 项）、`BatchTests`（7 项，含两项部分失败记账）。

集成测试在真实 SFTP 测试床上跑（`tests/integration/support.py` 的测试床）：新建 8 项、复制 5 项、移动 2 项、批量 3 项。核对字节一律用 `download_bytes()` 取回真实内容比对，而不是只看接口返回值——这一点直接回应任务书「不许只查静态代码就宣称完成」。

测试替身也补了能力：`tests/unit/fake_sftp.py` 的 `open()` 增加了 `SSH_FXF_EXCL` 语义（目标已存在就 `raise RemoteError`），并新增 `download_chunks()` 生成器供复制路径使用。没有这两处，`EXCL` 与复制都无法在单元层验证。

## 6. 问题与风险

| # | 问题 | 处理 |
|---|---|---|
| 1 | 集成测试里想用 `stat -c "%s %a"` 核对尺寸与权限，`%a` 被 Python 的 `%` 格式化吃掉 | 改为读 `GET …/files` 返回的 `entries` 核对 `size` / `type`，不再拼 shell 格式化串 |
| 2 | 集成测试整层耗时远超 `run_code` 默认 120 秒截止 | 一律以后台作业跑，日志用 `Tee-Object` 落盘后 `Get-Content -Tail` 查看；纯 shell 文件数统计改用工具而非 `wc`（本机无 `wc`） |
| 3 | 符号链接复制语义有取舍 | 明确选择「跳过并报告」而不是跟随或伪造，理由见 §4.3；已写进 `docs/API.md` §5.26 与用户手册 §8.9 |
| 4 | 移动不支持覆盖 | 有意为之（见 §4.3）。如果以后要支持，应实现为「先写临时名 → `rename` 覆盖」而不是复制后删除 |
| 5 | 复制没有并发 | 逐文件串行搬运；512 MiB / 10000 条目是硬上限而非性能目标。真实大目录拷贝会慢，这一点写进 `docs/RELEASE.md` §9 |

## 7. 文档与交付物

- 代码：`app/services/fileops.py`（+461 行）、`app/api/handlers.py`（+114 行，含 `_payload_paths`）、`tests/unit/fake_sftp.py`、`tests/unit/test_fileops.py`（+334 行）、`tests/integration/test_fileops_api.py`（+219 行）。
- `docs/API.md`：端点总表从 32 个改为 **35 个**，新增 §5.25 create / §5.26 copy / §5.27 move，后续小节整体顺延；§5.29 delete / §5.30 compress / §5.31 extract 各补一段「v0.1.3 起也接受批量」；§7.2 的写入口与 SFTP 原语清单同步（`open` 进清单，`mkdir` 现有两个调用者），并新增一条说明为什么用 `EXCL` 而不是先查再建。
- `tests/unit/_index.md:33`、`tests/integration/_index.md:21` 的项数与覆盖点同步。

## 8. 阶段结论

阶段 A 完成，允许进入阶段 B。三条判断依据：

1. 任务书 §4 的安全条款（排他创建、服务端重新校验、失败不假成功）在服务层有实现也有用例；
2. 既有端点向后兼容，v0.1.2 的调用方与测试未做修改即通过；
3. 集成测试在真实测试床上用真实字节核对，不是只跑桩。

未覆盖的部分（如实记录）：复制大目录的**性能**没有基准测试；符号链接的「跳过」只在单元层与集成层验证过，没有在真实桌面 CU 里点过（CU 验收项里没有这一条，任务书 §6.2 的 14 条也不涉及）。
