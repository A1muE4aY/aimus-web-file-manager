# 阶段 04 报告：远端文本编辑与文件操作（v0.1.1）

## 1. 报告信息

| 项目 | 内容 |
|---|---|
| 项目版本 | v0.1.0（v0.1.1 开发中，版本号在阶段六统一提升） |
| 报告日期 | 2026-10-16 |
| 开发阶段 | 阶段 04 —— 添加远端文本文件编辑和文件操作（任务书 `2.md` §五，`2.md:123-150`） |
| 对应 Git 提交或标签 | `b2bfc1f`（2026-10-16，「阶段 04（v0.1.1）：远端文本文件编辑与文件操作」，35 个文件 / +6182 −112）。阶段四单独一次提交 |

## 2. 阶段目标

任务书 §五要求（`2.md:123-150`）：

1. **基本功能**：文件列表或预览界面提供「编辑」入口；为每个条目提供压缩、重命名、解压、删除；独立编辑对话框或编辑页面，保留文件路径与名称；支持读取、修改、保存、取消；保存前有状态提示，保存成功后列表里的大小与修改时间同步更新；文件过大、格式无法识别、编码解码失败时给出清晰提示；预览与编辑有明确区别，不能让人误以为预览会改文件。
2. **数据安全**：默认只允许编辑可识别的文本文件，二进制不得误入编辑器；对文件大小设上限并给提示；正确处理 UTF-8、中文、换行符与末尾换行，无法安全识别的编码要提示、不得静默破坏内容；保存前再次确认有效写权限，前端按钮可用性不能替代服务端校验；加载后远端文件在保存前被改动要检测冲突、不得默认覆盖；保存失败保留用户编辑内容；保存过程中断线不得错误提示成功；不提供任意命令执行或脚本运行。
3. **测试要求**：覆盖正常保存、取消编辑、重命名、删除文件、解压缩、空文件、中文内容、换行符、只读权限、写权限关闭、文件已被删除、保存冲突、断线、超大文件与二进制文件拒绝编辑。

## 3. 实际完成情况

**已完成**

- 服务层两个新模块：`app/services/editor.py`（读文本 / 保存）与 `app/services/fileops.py`（重命名 / 删除 / 压缩 / 解压）。SFTP 适配层 `app/ssh/sftp_client.py` 新增 `open_write` 与 file-like 包装 `ChunkWriter` / `RandomReader`，压缩与解压在本机进程内流式完成。
- 六个 HTTP 端点（`app/api/handlers.py:294` 读文本、`:308` 保存、`:356` 重命名、`:369` 删除、`:386` 压缩、`:402` 解压；路由表 `app/api/handlers.py:434-463` 的第 23~28 项，`build_router()` 在 `:466`）。错误模型新增 `EditConflict`（`edit_conflict`，409，`app/core/errors.py:210`）。
- 配置项 `security.max_edit_bytes`（默认 2097152 = 2 MiB，允许 1024..67108864）：`app/core/config.py` 的 DEFAULTS / `SecurityConfig` / `_SECURITY_KEYS` / `parse_config` 四处加 `config/config.example.json`，并随 `GET /api/session` 返回当前值。
- 前端：`frontend/assets/js/edit.js`（编辑器对话框、Ctrl+S 保存、字数与「已修改」状态、冲突后「重新加载远端内容」、放弃修改前先问一句）、`frontend/assets/js/fileops.js`（重命名 / 压缩 / 解压对话框与删除的两级确认）、`frontend/assets/js/files.js` 的「操作」列（编辑 / 解压 / 重命名 / 压缩 / 删除，写权限关闭时后者置灰）、工具栏「编辑」按钮、`frontend/assets/js/preview.js` 的「编辑」入口与「预览是只读的」说明、`frontend/index.html` 表头与 `frontend/assets/css/app.css` 样式。
- 四层测试：单元 103 项（`tests/unit/test_editor.py` 43 + `tests/unit/test_fileops.py` 60，配套新增 `tests/unit/fake_sftp.py` 内存版 SFTP 假件）、集成 61 项（`tests/integration/test_edit_api.py` 31 + `tests/integration/test_fileops_api.py` 30）、安全 12 项（`tests/security/test_edit_paths.py`）、端到端 5 项（`tests/e2e/test_browser_edit.py`）；另在 `tests/unit/test_errors.py` 登记 `EditConflict`。
- 文档：`docs/API.md`（22 → 28 个端点，新增 §5.23–5.28）、`docs/USER_GUIDE.md`（新增第 8 章「在线编辑与文件操作」，原 8~13 章顺延为 9~14 章）、`docs/CHANGELOG.md`（v0.1.1 段补阶段四）、本报告与各层 `_index.md` 登记。

**部分完成**

- 在线编辑**只接受 UTF-8**。任务书要求「对无法安全识别的编码应提示用户，不得静默破坏内容」，AWFM 的做法是明确拒绝并在 `detail` 里给出解码失败的字节偏移，而不是猜测式转码——因此「非 UTF-8 的可编辑」这一条没做，取舍写进 `docs/USER_GUIDE.md` §8.7。
- 换行与 BOM 是**原样保留**（LF / CRLF / CR 与是否带 BOM 都记住），但界面上没有「转换换行风格」的开关。任务书只要求「正确处理换行符及末尾换行」，转换属于额外能力。
- 压缩固定产出 `.tar.gz`；`.zip` 只支持解压（任务书只写「压缩」，未指定格式）。
- 冲突检测基于内容 sha256（首选）或 mtime（回退），不是服务端锁或版本号：检测到变化就拒绝写入，但并发窗口里仍可能出现「刚比对完又被改」，属于文件系统层面的固有竞态。
- 保存过程中断线的行为是「报错并保留编辑器内容」（保存走重新读远端 + 写临时名 + 改名替换，断线时返回 `not_connected`），由集成与单元测试覆盖；真实桌面上的断线演示属阶段六 CU 验收。

**未完成及原因**

- 文件操作不含新建目录、修改权限、复制 / 移动、打包下载、多选批量操作——任务书第四阶段只要求压缩、重命名、解压、删除。
- 没有版本历史、撤销、自动保存。
- 真实桌面 CU 验收（真实 CentOS 上编辑后核对哈希、关掉写权限后不能保存、制造保存冲突）属于任务书阶段六，本阶段证据全部来自自动化测试。
- 版本号仍是 `0.1.0`，未重新打包（阶段六统一处理）。

## 4. 技术实现

- **独立模态对话框，不做页面跳转**：编辑器保留文件列表与当前选中项，取消后不需要重新列目录；对话框里直接显示路径、大小（含上限）、修改时间、编码与换行，避免「编辑的到底是哪个文件」的歧义。预览对话框另外加了一句「这里是只读预览，不会改动远端文件」，并把「编辑」作为独立按钮。
- **保存是四步而不是一次写入**：重读远端比对基线 → 写临时名（`.awfm-part-` + 随机后缀）→ 把原文件改名成备份（`.awfm-bak-`）→ 把临时文件改名成正式名。理由：SFTP v3 的 RENAME 不覆盖已存在目标，而且任何时刻远端要么是旧内容、要么是新内容，不会出现半截文件；第二步之后失败会把备份改回原名，成功后再删备份。
- **冲突检测内容优先、时间戳回退**：读文件时一并返回 sha256；保存时若给了 `base_sha256` 就重新读远端算哈希比对，不等则 409 `edit_conflict` 且**不写入**；只给了 `base_mtime` 时才比较时间戳。理由：mtime 只有秒级精度，远端 touch 与快速保存会撞。
- **换行与 BOM 原样保留**：读的时候记下风格（`lf` / `crlf` / `cr`，并列时偏向 `lf`）与是否带 BOM，文本一律折成 LF 传给浏览器；保存时按原风格编回，只有 `keep_bom` 为真才补 BOM。理由：任务书禁止静默破坏内容，把 CRLF 文件保存成 LF 就是静默破坏；这也是本阶段修掉的一个真实缺陷。
- **二进制判定与编码判定都在服务端**：抽样里有 NUL 或控制字符占比过高即拒绝（「这个文件看起来不是文本文件，不能在线编辑。」），UTF-8 严格解码失败即拒绝并给出偏移。理由：浏览器 `textarea` 没有编码概念，让用户「另存为」比猜编码危险。
- **大小上限 `security.max_edit_bytes` 默认 2 MiB**，远小于上传上限 2 GiB，因为内容要进浏览器内存与 `textarea`；读取前先用 `stat` 看大小，超限直接 413，不读字节。
- **破坏性操作只解析父目录**（`app/services/fileops.py` 的 `_canonical_entry_path`）：删除 / 重命名 / 压缩先对父目录 `realpath`、**最后一段不解析符号链接**。理由：整条 `realpath` 会让「列表里点中的条目」和「远端真正被改的条目」不是同一个——用户点「删除」一个链接时，删掉的必须是链接本身。
- **删除必须先显式声明递归**：服务端对非空目录返回 400 并在 `extra` 里带条目数，前端据此弹第二次确认「连同内容一起删除」，确认后才带 `recursive=true` 重发。界面确认与服务端护栏叠加，避免误删一个装满内容的目录。
- **压缩与解压全在本机进程内完成**：`tarfile` / `zipfile` 加 `ChunkWriter` / `RandomReader` 直接读写 SFTP 句柄，压缩包不落本机磁盘，也**不在远端执行 `tar` / `zip` 命令**（验收项 T-013：不为任何功能在远端执行 Shell）。
- **解压成员的路径逐段校验**：反斜杠先归一成 `/`、去掉开头的 `./`、拒绝 NUL / 绝对路径 / `..` 段，再逐段过 `validate_remote_name`；**越界成员按整包失败**而不是跳过。理由：一个包里出现越界成员说明整包不可信，部分解压等于把不可信内容写进远端。
- **符号链接的两种处理**：压缩时以链接本身入包（`SYMTYPE` + `readlink` 的目标，不跟进去，`bytes` 计 0）；解压时符号链接与硬链接一律跳过并记入 `skipped`（`symlink_skipped`）。理由：链接目标可能在解压范围之外，跟随等于越界写。
- **预算与上限**：压缩 / 解压各 10000 条目与 512 MiB、树深 64 层；删除 10000 条目与 64 层。解压触顶**不报错**，写进响应的 `stopped` 并保留已解出的部分（大包解一半仍然可用），删除触顶则停下并报错（删除不可回滚，需要让人知道发生了什么）。
- **请求体形状检查先于找会话**（六个端点全部如此）：畸形请求的 400 不随连接状态变化，否则「没连接」时 400 会变成 409。这条纪律沿用阶段三。

## 5. 测试结果

命令（工作目录 `E:/Project/aimus-web-file-manager`）：

```
python scripts/test.py          # 四层批量运行器：unit -> integration -> security -> e2e
```

实际输出（2026-10-16，测试床 127.0.0.1:2222 在线，Edge 可用）：

```
== 语法校验：python -W error::SyntaxWarning -m compileall -q app tests scripts ==
通过（0.28s）

== 汇总 ==
unit           449 用例    0 失败    0 错误    0 跳过    2.73s  OK
integration     98 用例    0 失败    0 错误    0 跳过   24.49s  OK
security        71 用例    0 失败    0 错误    0 跳过   14.85s  OK
e2e             18 用例    0 失败    0 错误    0 跳过   92.34s  OK
合计             636 用例    0 失败    0 错误    0 跳过  134.41s

全部通过。
```

本阶段相关用例分布：

| 层 | 文件 | 用例数 | 覆盖点 |
|---|---|---|---|
| 单元 | `tests/unit/test_editor.py` | 43 | 元数据与 sha256、中文与空文件、CRLF / 单独 CR / 混合换行 / 无末尾换行、BOM 剥离、二进制与非 UTF-8 拒绝、上限先于读取、保存后字节与权限保持、内容与 mtime 冲突、备份改名失败与替换失败都回滚且无残留、只读文件 403、断连不改动远端、默认与显式换行风格 |
| 单元 | `tests/unit/test_fileops.py` | 60 | 重命名（含只改链接名）、删除计数与递归预算与深度上限、非空目录必须 recursive、压缩包成员布局与权限 mtime、符号链接以链接本身入包、解压越界成员整包失败、已存在项跳过与覆盖、条目与字节上限写进 stopped |
| 集成 | `tests/integration/test_edit_api.py` | 31 | 读接口字段与换行/BOM、保存后 `download` 取回的字节一致、CRLF 默认保持、冲突 409 且不覆盖他人改动、只读文件 403、写权限关闭 401、`max_edit_bytes` 生效（413）、参数形状七连 400 |
| 集成 | `tests/integration/test_fileops_api.py` | 30 | 重命名与元数据、删除三类结果与符号链接回归、压缩后下载并用 `tarfile` 核验成员、解压（tar.gz 与 zip、重复解压跳过、覆盖）、越界成员整包拒绝且目标目录外无文件、只读连接四个写入口 401、压缩解压前后 ssh 进程数不变（T-013） |
| 安全 | `tests/security/test_edit_paths.py` | 12 | 六个端点无令牌 401、20 条畸形请求体在死连接上也只有 400（形状检查先于找会话）、未知连接 404、撤权连接上五个写入口全 401 且远端无新增文件、四类越界归档（`../`、`a/../../`、绝对路径、反斜杠）整包拒绝、拒绝之后正常归档仍能解压 |
| 端到端 | `tests/e2e/test_browser_edit.py` | 5 | 操作列「编辑」→ 改内容 → 保存（远端字节与界面大小列同步）、冲突提示且不覆盖、可重新加载远端内容、取消前先问「放弃修改」、重命名 / 压缩 / 解压 / 删除走对话框、只读连接上编辑可用而重命名 / 压缩 / 删除置灰 |

测试基建：

- `tests/unit/fake_sftp.py`（新增）是内存版 SFTP，不是单纯的 mock：它真跑 tar / zip 字节流，权限位是真的（读无读位文件、列无读位目录、写只读文件都会失败），`rename` 不覆盖已存在目标（服务层依赖这一点），离线后所有调用抛 `NotConnected`。
- `tests/integration/support.py` 新增 `edit_fixture`（普通 / CRLF / 空 / 无末尾换行 / BOM / 只读 / 二进制 / 8 KiB / 符号链接 / 子目录）与 `ops_fixture`（树、空目录、目标目录、两组符号链接），以及 `upload_bytes` / `download_bytes`（走完整的上传与票据下载往返取字节）与 `Client.put`。
- 端到端夹具在 `$HOME/awfm-e2e-edit-<RUN_TAG>` 下由 `testbed_command` 现摆现清，并用两个连接（一个 `allow_write=False`）验证按钮与提示的差异。

端到端截图证据（每次运行重新生成，`tests/e2e/artifacts/` 已加入 `.gitignore`）：
`browser-edit-saved-c992a576.png`、`browser-edit-conflict-c992a576.png`、`browser-edit-cancel-c992a576.png`、`browser-edit-ops-c992a576.png`、`browser-edit-readonly-c992a576.png`。

## 6. 问题与风险

本阶段发现并修掉 6 处真实缺陷：

1. **破坏性操作跟着符号链接走**（`app/services/fileops.py`）：删除 / 重命名 / 压缩原先都走 `filesystem.resolve_path`（整条 `realpath`），于是列表里对一个指向 `/home/aimu/real.txt` 的 `link.txt` 点「删除」，实际删掉的是 `real.txt`，链接还留着。改为新增 `_canonical_entry_path`（只对父目录 `realpath`、最后一段不解析），并补三条回归：删除链接保留目标文件、删除指向目录的链接保留目录内容、压缩符号链接时包里是链接本身。
2. **在线编辑保存会把 CRLF 静默写成 LF**（`app/services/editor.py`）：`save_text_file` 的 `newline` 默认值曾是 `"lf"`，任何 CRLF 文件保存一次就被改掉换行风格。改为默认空串＝沿用文件原有风格，并新增 `_peek()`（只读开头一小段探测风格，不因文件更大而报错）。
3. **解压目标目录不存在时直接报错**：用户说「解压到这里」而该目录还没建时，原先 `client.stat` 抛 `path_not_found` 就失败。改为只创建最后一级目录（多级路径写错仍然报错，不默默造一串空目录）。
4. **`gzip_open` 未定义**（`app/services/fileops.py`）：压缩路径写了 `with gzip_open(writer)`，真机冒烟一跑就 `NameError`。改为 `gzip.GzipFile(fileobj=writer, mode="wb", mtime=0)`（`mtime=0` 让同样的输入产出可复现的包）。
5. **覆盖落位用了不存在的 `overwrite_target`**（`app/services/fileops.py`）：解压覆盖分支写了 `if overwrite_target(...)`。改为「先 `lstat` 判断，目标存在且不是目录就 `client.remove`，再 `rename`」——因为 SFTP v3 的 RENAME 不覆盖已存在目标。
6. **文件操作的成功提示显示 undefined**（§BT§frontend/assets/js/fileops.js§BT§）：这条**不在本阶段提交里**——它是提交之后做 e2e 截图核对时才看出来的。后端把结果包成 §BT§{"entry": …}§BT§ / §BT§{"deleted": …}§BT§ / §BT§{"archive": …}§BT§ / §BT§{"extract": …}§BT§ 这样的信封，而前端除重命名外都直接读顶层字段，于是屏幕上出现「已删除「undefined」」——远端状态是对的，只有提示是错的（e2e 断言原本只核对远端，所以漏掉了）。修复为统一的 §BT§unwrap(data, key)§BT§：缺键时抛错而不是返回 undefined，§BT§tests/e2e/test_browser_edit.py§BT§ 新增 §BT§wait_for_toast§BT§，断言提示文案里不含 §BT§undefined§BT§。教训：**端到端用例要连界面说了什么一起核对**，只核对远端状态会放过这一类缺陷。

另有一处**测试基建**缺陷（不是应用缺陷）：内存版 SFTP 假件（`tests/unit/fake_sftp.py`）的 `remove` / `rmdir` 原先会解析符号链接，导致「删除链接」在单测里表现得像删了目标；按 POSIX 语义改为作用于条目本身（`rmdir` 对链接报「不是目录」）。

风险与已知限制：

- 上限是常量（只有 `security.max_edit_bytes` 可配）：压缩 / 解压 10000 条目与 512 MiB、删除 10000 条目、树深 64 层。**删除触顶会留下部分删除**（已删的条目不回滚），响应里带已删计数。
- 在线编辑只支持 UTF-8 且 ≤ 2 MiB；不支持二进制、不提供换行风格切换。
- 冲突检测基于 sha256 / mtime，不是服务端锁；两个人在同一秒内先后保存仍可能后写覆盖前写（但会先被哈希比对拦下）。
- 覆盖上传（阶段二的能力）在取消时仍可能留下半截文件：上传路径没有改成「临时名 + 改名」，在线编辑保存改了，这是已知的不对称，记在 `docs/CHANGELOG.md` 的已知限制里。
- 压缩包超限时包被丢弃（临时文件清理），但已经传输的字节不可回收；远端磁盘写满的错误会以 `remote_error` 502 上报。
- 端到端依赖本机 Edge 与在线测试床，缺任一项该层即跳过——本项目纪律是**跳过不算通过**，运行器会单独列出跳过数（本次 0 跳过）。
- 多人同时编辑同一文件不在本轮设计目标内。

## 7. 文档与交付物

- 代码：`app/services/editor.py`（新增）、`app/services/fileops.py`（新增）、`app/ssh/sftp_client.py`、`app/api/handlers.py`、`app/core/config.py`、`app/core/errors.py`、`config/config.example.json`、`frontend/assets/js/edit.js`（新增）、`frontend/assets/js/fileops.js`（新增）、`frontend/assets/js/api.js`、`frontend/assets/js/util.js`、`frontend/assets/js/files.js`、`frontend/assets/js/preview.js`、`frontend/assets/js/app.js`、`frontend/index.html`、`frontend/assets/css/app.css`。
- 测试：上表 6 个文件，另加 `tests/unit/fake_sftp.py`（新增假件）、`tests/integration/support.py`（造景基建）、`tests/unit/test_errors.py`（登记 `EditConflict`）、`tests/e2e/artifacts/` 截图。
- 文档：`docs/API.md`（28 个端点与 §5.23–5.28）、`docs/USER_GUIDE.md`（第 8 章与章节顺延）、`docs/CHANGELOG.md`（v0.1.1 段）、本报告、`app/services/_index.md` 与 `tests/{unit,integration,security,e2e}/_index.md` 登记。
- 未产出：打包产物与校验和仍是 v0.1.0 的那一份（任务书阶段六要求重新构建）。

## 8. 阶段结论

阶段四（远端文本编辑与文件操作）**功能与测试已完成**：在线编辑器、重命名 / 删除 / 压缩 / 解压四个文件操作、六个 HTTP 端点、配置与错误模型、前端入口与「操作」列全部落地，四层 636 项测试全绿（本阶段新增 181 项），任务书 §五的三组要求逐条有实现与测试证据。

允许进入阶段五（自动发现在线虚拟机）。遗留事项：真实桌面 CU 验收、版本号提升与重新打包属阶段六；新建目录 / 修改权限 / 复制移动 / 打包下载、非 UTF-8 编码、可配置上限留待后续版本。
