# 阶段 B 报告：界面布局、预览框与新建/多选（v0.1.3）

## 1. 报告信息

| 项目 | 内容 |
|---|---|
| 版本 | v0.1.3 |
| 阶段 | B —— 界面布局、预览框、新建与多选 |
| 日期 | 2026-10-17 |
| 依据 | `dev_guide/0.1.3_.md` §1（操作按钮独立容器）、§2（文件信息区独立布局）、§3（预览独立框）、§4（新建文件/文件夹与多选）的前端部分 |
| 结论 | 完成。新增 `tests/unit/test_frontend_layout.py` 30 项静态断言；`tests/e2e/test_browser_layout.py` 布局用例按新结构重写后 2 项通过；新增 `tests/e2e/test_browser_v013.py` 7 项通过 |

## 2. 阶段目标

任务书这四节的共同点是**别再让布局靠内容撑**。v0.1.2 的表格是「把单元格塞满、宽度由内容决定」，于是出现了几类用户能直接看到的问题：行内按钮数量随文件类型变化，短名字的行按钮靠左、长名字的行按钮被挤走；表头与内容各算各的宽度，滚动或窄屏时对不齐；预览框是模态框里的一段 `<pre>`，长文本会把整页撑出滚动条。

所以这一阶段不是「加几个按钮」，而是把三处布局从「内容驱动」改成「容器驱动」，再把新建、复制/剪切、多选这三组交互接上去。

## 3. 实际完成情况

| # | 任务书要求 | 实现位置 | 状态 |
|---|---|---|---|
| B-1 | 行内操作放进独立容器 `file-actions-box` | `frontend/assets/css/app.css:917`；`frontend/assets/js/files.js:515` `actionCell()` | 完成 |
| B-2 | 操作顺序固定：编辑→复制→剪切→重命名→删除→压缩→解压 | `frontend/assets/js/files.js:500` `ACTION_ORDER` | 完成 |
| B-3 | 槽位等宽、按钮文字居中、高度与圆角一致 | `app.css:927`（按钮统一外观）、`:1105` / `:1120` / `:1135`（三档断点的 `grid-template-columns`） | 完成 |
| B-4 | 不适用操作「统一禁用或隐藏但不得引起跳动」 | 七个槽位**永远都在**，只是部分 `disabled`；禁用按钮带 `title` 说明原因（`files.js:584` 起的循环） | 完成 |
| B-5 | 按钮不得覆盖其它列 | 列宽由 `<colgroup>` 固定（`frontend/index.html:150`~`:158`），名称列 `auto` 且 `min-width: 0`，超长优先截断 | 完成 |
| B-6 | 信息区每行独立布局、表头与行同列定义 | 同上，`<colgroup>` 六列（select / name / size / type / perm / time / action 共七项，其中 select 由 `.has-select` 控制显隐，`app.css:905`） | 完成 |
| B-7 | 长名截断且不丢真实路径、完整名可查看 | `files.js:403` 附近的 `.entry-name` 保留 `title` 与 `data-full-name`，`markTruncatedNames()` 实测溢出才加 `data-truncated`，悬浮/聚焦显示完整名 | 完成 |
| B-8 | 预览内容进独立容器，内部滚动 | `frontend/assets/js/preview.js:70`（`.preview-box` + 标题栏 + 正文框）；`app.css:612`~`:661` | 完成 |
| B-9 | 保留换行与缩进、二进制与超限走既有错误路径 | 正文用 `pre.preview-text`（`app.css:661` 注释说明滚动交给外层框），错误分支不新增机制 | 完成 |
| B-10 | 工具栏新增「新建文件」「新建文件夹」「粘贴」「多选」 | `frontend/index.html:77`~`:88`；按钮可用性集中在 `frontend/assets/js/app.js:57`、`:64` | 完成 |
| B-11 | 新建对话框 + 即时校验 + 创建后留在当前目录并刷新 | `frontend/assets/js/fileops.js:288` `createEntry()`（复用 `modal.js`） | 完成 |
| B-12 | 行最左复选框列、多选后批量操作 | `files.js:403` 建单元格、`:627`/`:635` 切 `has-select`、`:687` 更新「已选 N 项」；批量入口 `fileops.js:463`/`:532`/`:597` | 完成 |
| B-13 | 复制/剪切/粘贴：只记路径，粘贴时才动手 | `frontend/assets/js/state.js:57`（`clipboard`）、`fileops.js:359`/`:367`/`:376` | 完成 |

## 4. 技术实现

### 4.1 七槽位为什么用 Grid 而不是「有什么就放什么」

v0.1.2 的 `actionCell()` 是按条件 `push` 按钮的：目录没有「编辑」和「解压」，普通文件没有「解压」，于是同一列里不同行的按钮数量不同，视觉上按钮会「跳」。用户看到的是「点开一个目录，按钮全都往左挪了一格」。

现在的做法是两个常量对齐：`ACTION_ORDER`（`frontend/assets/js/files.js:500`）固定七个键的顺序，`app.css:1105`/`:1120` 的 `grid-template-columns: repeat(7, 40px)` / `repeat(7, 38px)` 固定七个等宽槽位，渲染循环（`files.js:584`）**总是**遍历 `ACTION_ORDER`，只是对当前条目不适用的键设 `disabled`。槽位恒定 ⇒ 按钮位置恒定 ⇒ 切换文件类型时不会有任何跳动。

为了让「灰掉」不是「说不清为什么灰」，禁用按钮都带 `title`（例如「需要先打开『允许写操作』」「目录不能预览」「只有压缩包可以解压」），单元测试 `test_disabled_buttons_still_explain_themselves` 断言的是「禁用的那些按钮必须有说明」，不是「有多少个禁用」。

### 4.2 列宽由 `<colgroup>` 一处决定

`frontend/index.html:150`~`:158` 新增 `<colgroup>`：`col-select`（宽度由 `.has-select` 决定显示或 `display: none`）、`col-name`（`auto`，可截断）、`col-size` / `col-type` / `col-perm` / `col-time`（受控宽度）、`col-action`（固定，容得下七槽位）。表头与每一行的 `<td>` 顺序完全一致，宽度只由 `<colgroup>` 决定，与文件名长短、有没有图标无关。

`app.css:887` 的注释写明了这条规矩：「每列宽度只由 `<colgroup>` 决定」。这样一来「表头与行对齐」不再是需要每次都检查的事——它们是同一套列定义。

多选列的做法值得一提：单元格一开始就在 DOM 里，切多选只是给 `<table>` 加/去 `has-select` 类（`files.js:304`、`:627`），`app.css:905` 的 `#file-table:not(.has-select) .col-select { display: none }` 负责隐藏。好处是**切模式不重绘列表**，滚动位置、选中高亮、悬浮状态都不丢；坏处是 DOM 里始终多一列空单元格，可以忽略。

### 4.3 预览框：把滚动关进框里

`frontend/assets/js/preview.js:70` 起构造三层结构：`.preview-box`（统一边框、圆角、背景，深色主题下跟随变量）→ `.preview-box-head`（标题写文件名、状态写大小/编码/是否截断、右侧操作按钮）→ `.preview-box-body`（`overflow: auto`，`max-height` 由视口高度推导）。正文 `pre.preview-text` 只负责保留换行与缩进（`white-space: pre-wrap`）。

这样长文本的行数与整页滚动彻底解耦：内容再长也只在框内滚，模态框高度不随内容变化。二进制与超限两条错误路径**没有新增机制**——`previewFile()` 抛的错误照旧走 `toastError`，`payload_too_large` 照旧弹「文件太大」，这一点由 `tests/e2e/test_browser_v013.py::test_preview_of_a_big_file_uses_the_normal_error_path` 钉住。

### 4.4 新建：前端只做即时反馈，判定仍在服务端

`fileops.js:288` 的 `createEntry(kind)` 打开一个只含「名称」一个输入框的模态框，输入时即时校验（空、`.`、`..`、含 `/`、含 NUL、超过 255 字符），给了明确提示就禁用「创建」按钮。提交后调 `api.js:213` `createEntry()`（POST `…/create`），成功则**留在当前目录**刷新列表。

这里刻意没有做「先查重名再建」：重名判定交给服务端的排他创建（见阶段 A 报告 §4.1），前端只在收到 `exists: true` 的错误时把提示落在名称输入框下方。任务书要求「前端禁用不等于安全」，这条实现正好把安全边界放在服务端。

刷新失败与创建成功被分开报（`fileops.js:288` 起的成功分支）：先提示「已创建 xxx」，再单独尝试刷新，刷新失败时提示「创建成功，但列表没刷新，点刷新重试」——而不是让用户以为创建失败又建一遍。

### 4.5 复制/剪切/粘贴与多选

剪贴板存在 `state.clipboard`（`frontend/assets/js/state.js:57`）：`{ mode: "copy" | "cut", connectionId, paths }`。它只记路径与来源连接，**不动远端任何东西**，粘贴时才真正调用 `/copy` 或 `/move`（`fileops.js:376`）。这样做的原因很直接：如果剪切时立刻移动，用户改主意就没有退路；而只记路径时「取消粘贴」等于什么都不做。

粘贴前检查两件事：来源连接必须与当前连接一致（`state.js:57` 起存了 `connectionId`，跨连接粘贴直接拒绝并说明原因），目标目录不能是源自己或源的子目录（这条服务端也会再拒一次）。

多选模式（`files.js:627`/`:635`）：勾选状态存在 `state.multiSelect` 与行上的复选框，操作条显示「已选 N 项」与全选/复制/剪切/删除/压缩/解压/清空。批量调用直接复用阶段 A 的 `paths` 数组；失败时按服务端返回的 `extra.done` / `extra.failed` 报告「已完成 N 项，第 M 项失败」，不做「全部成功」的假象。

## 5. 测试结果

| 层 | 文件 | 数量 | 结果 |
|---|---|---|---|
| 单元 | `tests/unit/test_frontend_layout.py`（新增） | 30 项 | `Ran 30 tests, OK` |
| 端到端 | `tests/e2e/test_browser_layout.py`（按新结构重写断言） | 2 项布局用例 | 通过（证据 `.temp`/`tests/e2e/artifacts/browser-layout-*.png`） |
| 端到端 | `tests/e2e/test_browser_v013.py`（新增） | 7 项 | `Ran 7 tests in 38.773s, OK` |

`test_frontend_layout.py` 不启动浏览器，直接读 `index.html` / `files.js` / `app.css` 做静态断言：`<colgroup>` 的列与表头一一对应、每行 `td` 顺序一致、表头带全选复选框、「操作」表头居中、`ACTION_ORDER` 与任务书要求的顺序一致、按钮由该数组驱动、每个动作在正确类型上启用、禁用按钮有说明、三档断点都保留七个槽位、七个按钮同处一个容器。这些断言存在的意义是：布局的「规矩」如果被后续改动破坏，不用等浏览器跑到才暴露。

`test_browser_v013.py` 覆盖七件事：新建空文件与文件夹并确认远端真的落地、创建拒绝重名与非法名、多选显示复选框并正确计数、复制后粘贴把文件放到用户看着的目录、长文本预览在框内滚动、大文件走普通错误路径、只读连接下创建按钮禁用。

## 6. 问题与风险

| # | 问题 | 处理 |
|---|---|---|
| 1 | 布局 e2e 最初拿**跨行的绝对 `top`** 比较，17 个值当然不相等 | 改为逐行比较（每行七个按钮同 `top`）；窄窗折行只比「相对本行 edit 的偏移」 |
| 2 | `#file-table { min-width: 340px }` 在 661 CSS 视口下比 `.table-wrap`（334px）大 6px，强行多出横向滚动 | 改成 `min-width: 300px`（`app.css:891` 附近），并在注释里写明「兜底值不能大于最窄视口下的容器宽度」 |
| 3 | e2e 里 `"已选 %d 项" % total` 没在 Python 侧替换，浏览器抛 `ReferenceError: total is not defined` | 先在 Python 里拼好字符串，再用 `js()` 转义后注入 |
| 4 | 七槽位在 661 视口折成 4+3 两行 | 这是任务书允许的「挤不下先调弹性列」的结果，不是缺陷；断言改为「第二行从『删除』起」并记录折行形态 |
| 5 | 预览超限与二进制两条错误在界面上给的是同一个 toast 位置、不同文案 | 按任务书「二进制用现有错误机制」保持现状，e2e 断言同时接受两种文案（`二进制` 或 `太大`） |

## 7. 文档与交付物

- 代码：`frontend/index.html`（+33 行）、`frontend/assets/css/app.css`（+211 行改动）、`frontend/assets/js/files.js`（+290 行）、`fileops.js`（+386 行）、`app.js`（+75 行）、`api.js`（+62 行）、`state.js`（+57 行）、`preview.js`（+23 行）。
- 测试：`tests/unit/test_frontend_layout.py`（新增，342 行 / 30 项）、`tests/e2e/test_browser_layout.py`（断言重写）、`tests/e2e/test_browser_v013.py`（新增，572 行 / 7 项）。
- 文档：`docs/USER_GUIDE.md` §6 两条（每行显示与预览）改写、§8.5 开头补固定顺序说明、新增 §8.8 新建、§8.9 复制剪切粘贴、§8.10 多选与批量；`docs/CHANGELOG.md` 的 v0.1.3「新增」段逐条列出前端能力。

## 8. 阶段结论

阶段 B 完成，允许进入阶段 C。判断依据：

1. 任务书 §1/§2/§3 的布局要求都有「容器驱动」的实现，而不是靠内容凑——列宽由 `<colgroup>` 一处决定、按钮槽位由 `ACTION_ORDER` 一处决定、预览滚动由 `.preview-box-body` 一处决定；
2. 新建/复制剪切/多选三组交互在真实浏览器里跑通（e2e 7 项），并且安全判定留在服务端；
3. 布局纪律有 30 项静态断言，后续改动破坏「规矩」会立刻在单元层报错。

未覆盖的部分（如实记录）：只测了 Chromium（无头 Edge）与 992 / 661 两档断点，没有在 Firefox / Safari 上验证；深色主题的对比度只做了肉眼核对，没有做自动化的对比度计算。
