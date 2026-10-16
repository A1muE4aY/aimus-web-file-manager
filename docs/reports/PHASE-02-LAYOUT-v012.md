# 阶段二报告：文件列表布局与右键菜单（v0.1.2）

## 一、报告信息

| 项目 | 内容 |
|---|---|
| 版本 | v0.1.2（维护与体验优化版本） |
| 阶段 | 阶段二：列表布局与操作区固定、完整名称查看、自定义右键菜单（任务书 `dev_guide/0.1.2_.md` §二） |
| 日期 | 2026-10-17 |
| 基线提交 | `97e68d0`（阶段 01 收尾：CHANGELOG 与文档行号更正），分支 `master` |
| 验证方式 | ① 自动化：`python scripts/test.py -v` 四层 + 新增 `tests/e2e/test_browser_layout.py` 8 项；② **真实桌面 CU**：Edge 无痕窗（pid 4012、window_id 1444516）打开 `http://127.0.0.1:8790/`，后端连真实 CentOS Stream 10（192.168.170.128），改造前后各采一组截图（1.25 显示缩放，页面 100%） |
| 结论 | 2.2 / 2.3 / 2.5 全部落地并留证；窄窗与 150% 缩放按断点阶梯收列，操作按钮不再被推出可视区；截断只发生在显示层，完整名称有悬浮、键盘焦点、右键复制三条路；右键菜单在行/空白/连接卡片三处替换原生菜单，输入框与编辑器仍保留原生文本交互。四层回归全绿。顺带修复一处真实缺陷（复制成功没有反馈） |

---

## 二、阶段目标

任务书 §二 要求本阶段做三件事，并明确「必须真实桌面 CU 前后截图，不得只凭 CSS 测试或 DOM 检查宣称通过」：

1. **2.2 列表布局与操作区固定** —— 同一动作在任何一行都落在同一位置；按钮不因文件名长短、类型、有无图标而移动；操作区用固定或受控宽度、稳定的表格布局或 Grid；按钮不得压住名称/大小/权限/时间；保留键盘操作与可访问性；不要无差别缩小全部文字。
2. **2.3 完整名称查看方式** —— 允许截断，但不能丢失看到完整名字的途径（悬浮提示、可访问组件、复制名称并给出成功/失败反馈）；截断只影响显示，不得改动真实路径、请求参数、上传名与编辑名；中文、英文、空格、括号、长扩展名、特殊字符都要正确。
3. **2.5 自定义右键菜单** —— 用 `contextmenu` 事件拦截原生菜单（不改浏览器/系统设置）；按右键目标与状态给不同操作；位置随鼠标且靠视口边缘自动调整；有层级/悬停/焦点/禁用态；点外部、Escape、切换目录都要关闭；支持键盘；不得影响文本选择、输入框编辑与开发者工具；菜单项只作入口，复用既有业务逻辑与权限校验，服务端独立验证。

---

## 三、实际完成情况

### 3.1 2.2 列宽与操作区（`frontend/assets/css/app.css`）

| 要求 | 实现 | 位置 |
|---|---|---|
| 列宽不再被文件名撑开 | 表格改用固定布局，列宽只由 CSS 决定 | `frontend/assets/css/app.css:845` `#file-table { table-layout: fixed; }` |
| 名字列吸收剩余宽度 | `.col-name { width: auto }`（不用百分比，避免与固定列抢宽度） | `frontend/assets/css/app.css:850` |
| 其余列固定宽度 | 大小 96 / 类型 88 / 权限 104 / 修改时间 148 / 操作 296（px） | `frontend/assets/css/app.css:852-855`、`:861` |
| 操作区固定且按钮不互相挤 | 五个动作钉在五个 Grid 槽位（`grid-column: 1..5`），某行少了「编辑」或多出「解压」只让对应槽位空着 | `frontend/assets/css/app.css:863-885` |
| 按钮不压住名字 | 实测：宽窗 16 行 `重命名` 全部 x=2316；`/home/aimu` 20 行同样 x=2316（目录行没有「编辑」、压缩包行多出「解压」也不影响） | §5.4 |
| 窄窗不横向溢出 | 断点阶梯：1280px 收槽位与操作列 → 1120px 收权限列 → 1020px 收类型列并折成两行 → 820px 收修改时间并收窄大小列 | `frontend/assets/css/app.css:1023-1052`，另见 `:665`（全局 820px 已收权限/类型） |
| 键盘与可访问性 | 名字在截断时才有 `tabindex="0"`；焦点环画在单元格内阴影上（不被 `overflow:hidden` 裁掉） | `frontend/assets/css/app.css:889-890` |
| 不无差别缩小文字 | 只对行内按钮用 11.5px（原本就有），其余字号未动 | `frontend/assets/css/app.css:870-878` |

### 3.2 2.3 完整名称（`frontend/assets/js/files.js` + `frontend/assets/js/overlay.js`）

- **截断判定**：渲染后逐行量 `clientWidth` 与 `scrollWidth`，只有真的被截断（`scrollWidth > clientWidth + 1`）才标记 `data-truncated="true"` 并给 `tabindex="0"`（`frontend/assets/js/files.js:489`）。
- **三条并行途径**：① 鼠标悬浮 → 自绘提示（`overlay.js:259 showTooltip`）；② 键盘聚焦 → 同一个提示组件；③ 右键菜单「复制名称 / 复制完整路径」（`frontend/assets/js/files.js:568-569`）。名字上同时保留原生 `title` 与 `aria-label`、`data-full-name`。
- **截断只影响显示**：名字文本、`data-name`、请求参数、上传名、编辑名全部用真名；预览/编辑请求里实收完整中文名与完整英文名（§5.2 用例三）。
- **中文/英文/空格括号/长扩展名**：夹具覆盖长英文名（79 字符）、长中文名、`name with spaces (and parens) [and brackets].txt`、`.tar.gz`、符号链接与断链名，全部按真名走。

### 3.3 2.5 右键菜单（`frontend/assets/js/overlay.js` 新增，281 行）

| 要求 | 实现 | 位置 |
|---|---|---|
| 拦截原生菜单 | 在 capture 阶段监听 `contextmenu` 并 `preventDefault`（不改浏览器/系统设置） | `frontend/assets/js/overlay.js:229 installContextMenu`、`:244-245` |
| 输入框/编辑器保留原生交互 | `isNativeTextTarget(node)` 命中 `input / textarea / select / [contenteditable] / .editor-text` 时直接放行 | `frontend/assets/js/overlay.js:236`、`:38` |
| 按目标与状态给不同操作 | 文件行（预览/编辑/下载 …）、目录行（打开目录）、压缩包（多出「解压」）、符号链接（跟随链接）、列表空白（刷新/上一级/上传）、连接卡片（浏览/断开/编辑/删除/复制） | `frontend/assets/js/files.js:516 fileMenuItems`、`:574 containerMenuItems`、`frontend/assets/js/connections.js:45 connectionMenuItems` |
| 位置随鼠标 + 边缘避让 | 先试鼠标右下，放不下翻到另一侧，再夹进 `[EDGE, innerWidth-EDGE-width]`（`EDGE=8`、`GAP=2`） | `frontend/assets/js/overlay.js:80 openMenu`、`:52 placeAt` |
| 视觉层级/悬停/焦点/禁用 | `.overlay-menu`（z-index 55）与 `.overlay-menu-item` 的悬停、`focus-visible`、`is-danger`、`:disabled` 态；禁用项带原因 hint | `frontend/assets/css/app.css:1182-1236` |
| 关闭规则 | 点菜单外（capture mousedown）、Escape、切换目录（`renderTable` 先 `closeOverlays()`）、resize/scroll/wheel、Tab | `frontend/assets/js/overlay.js:135 closeMenu`、`:198-215`；`frontend/assets/js/files.js:271` |
| 键盘可用 | 打开即聚焦首个可用项；Arrow/Home/End 移动，Enter/Space 激活，Escape 关闭并把焦点还给打开者 | `frontend/assets/js/overlay.js:158 onMenuKeydown`、`:130` |
| 只作入口、复用既有逻辑 | 菜单项调用既有 `activate / downloadEntry / openRename / openCompress / confirmDelete / transfer.downloadEntry` 等，不新增功能；写操作仍受「允许写操作」与服务端校验约束 | `frontend/assets/js/files.js:516-572` |

### 3.4 验收场景对照（任务书 2.4 / 2.5 七条）

| 场景 | 证据 |
|---|---|
| 短名 / 长英文名 / 长中文名 / 空格括号名 | 夹具目录 16 项（`before-01` / `after-01`），e2e 用例二、三、八 |
| 不同文件类型与目录行 | 目录行无「编辑」、压缩包行有「解压」、断链行（`after-02` 行菜单） |
| 0 字节与大文件 | `zero-byte.txt`（0 B）、`big-12MiB.bin`（12.0 MiB） |
| 多种权限字符串 | `perm-000/600/644/755`（`----------`、`-rw-------`、`-rw-r--r--`、`-rwxr-xr-x`） |
| 不同长度日期 | `2020-01-02 03:04`（旧）与 `2026-10-17 01:44`（新） |
| 窗口宽窄 | 1240×900 物理（992 CSS）：`after-09`~`after-12`、`after-13/14`；宽窗 2560 |
| 浏览器缩放 | 150%（`after-15-zoom150.png`），e2e 用例八把视口钉到 661 CSS |
| 悬浮 / 键盘焦点 / 按钮点击 | `after-10`（点击/焦点出提示）、`after-11`（Tab 后消失）、`after-12`（Shift+Tab 回来又出现）；e2e 用例二用真实 `Input.dispatchMouseEvent` 与 `dispatchKeyEvent` |
| ①行上不再出原生菜单 | `before-03-native-context-menu.png`（原生）→ `after-02-row-menu.png`（自绘）；e2e 用例四断言 `defaultPrevented === true` |
| ②识别目标正确 | e2e 用例四逐项断言四种行的菜单项列表；`<tr data-name>` 精确定位，不会误伤相邻行 |
| ③四周不被裁切 | `after-13-blank-menu.png`（下沿上翻）、`after-14-edge-menu.png`（右下角既上翻又左移，菜单 331×242 CSS 全在视口内）；e2e 用例四断言四边不越界 |
| ④点空白/Escape/切换目录关闭 | `after-03-menu-closed.png`；e2e 用例五三条路径全验 |
| ⑤编辑器与输入框仍可复制粘贴 | `after-07-native-in-search.png`（搜索框右键出的是**浏览器原生**菜单：撤销/重做/剪切/复制/粘贴/全选…）、`after-08-native-closed.png`；e2e 用例六 |
| ⑥写权限与服务端校验 | 只读连接上「重命名/压缩/删除/上传」灰掉并写明原因（e2e 用例七）；服务端校验为 v0.1.0 起既有实现，本阶段未放宽 |
| ⑦真实桌面 CU | 见 §5.3，before 7 张 + after 17 张 |

### 3.5 交付清单

| 类型 | 文件 |
|---|---|
| 新增源码 | `frontend/assets/js/overlay.js`（281 行：菜单 + 提示 + 关闭规则） |
| 改动源码 | `frontend/assets/js/files.js`、`frontend/assets/js/connections.js`、`frontend/assets/js/app.js`、`frontend/assets/js/util.js`、`frontend/assets/css/app.css` |
| 新增测试 | `tests/e2e/test_browser_layout.py`（8 项）；`tests/integration/support.py` 增 `layout_fixture()` 与 12 个名字常量 |
| 证据 | `.temp/cu-v012-layout/`（before 7 张、after 17 张） |
| 文档 | 本报告、`docs/CHANGELOG.md`、`docs/reports/_index.md`、`tests/e2e/_index.md`、`tests/integration/_index.md`、`AGENTS.md`（补 `dev_guide/` 白名单与路径更正） |

---

## 四、技术实现

### 4.1 为什么是固定布局 + 多断点，而不是「让列宽自适应」

改造前的真实截图（`before-01-layout-dir.png`）显示：表格用自动布局，列宽由内容撑开 —— 出现 79 字符的英文名后，`权限` 列被挤到只剩几个字符，操作列整体右移；`before-04-narrow.png`（1240×900 物理）里表格出现横向滚动条、`修改时间` 与 `操作` 整列在视口外；`before-05-zoom150.png`（页面 150%）里 `修改时间` 被裁、操作列按钮被右边缘切掉。所以问题不是「某个列宽不够」，而是**布局根本不确定**。

因此本阶段把列宽从内容手里收回：固定布局 + 固定列宽 + 操作区 Grid 槽位。代价是窄窗口需要主动决定「先收哪一列」，于是按实测加了断点阶梯（`app.css:1023-1052`）：1280 → 1120 → 1020 → 820。阶梯的取舍顺序是：**先收最不影响判断的元信息**（权限 → 类型 → 修改时间），最后才动操作区；操作区收到极限时改折成两行，而不是继续缩按钮。

### 4.2 五个固定槽位

`actionCell`（`frontend/assets/js/files.js:447`）按行生成动作对象数组（`{key,label,cls,enabled,run}`），每项带 `data-action`；CSS 用 `grid-column` 把 `btn-edit-entry / btn-extract-entry / btn-rename-entry / btn-compress-entry / btn-delete-entry` 钉死在 1~5 列。于是「有没有这个按钮」不再影响「别的按钮在哪」——这是 2.2「同一列按钮位置一致」的实现方式，也是 e2e 用例一的断言对象（同一动作在所有行上的 `left/width` 唯一）。

### 4.3 截断检测放在渲染之后

`markTruncatedNames()`（`frontend/assets/js/files.js:489`）在 `renderTable()` 末尾执行，用 `clientWidth > 0 && scrollWidth > clientWidth + 1` 判定。放在渲染后而不是渲染前，是因为只有真正排版完才知道有没有溢出；用 `+1` 是给子像素四舍五入留余量，避免把「刚好放下」误判成截断。只有被判定为截断的名字才拿 `tabindex="0"`——不截断的名字不该多出一个键盘焦点。

### 4.4 overlay.js

`overlay.js` 只做三件事：造菜单、造提示、决定什么时候关。它不认识文件、连接或权限，菜单内容由调用方通过 `build(event)` 回调提供（`frontend/assets/js/overlay.js:229`）；`build` 返回 `null` 或空数组时**不拦截**，原生菜单照旧出现——这就是「列表空白处由祖先容器接管、行内由行接管」不打架的原因。`closeOverlays()`（`:293`）供 `renderTable()` 在重绘前调用：菜单与提示挂在 `document.body` 上，而它们指向的行会被整批换掉，不主动收会留下「指向已不存在行的菜单」。

### 4.5 顺带修复：复制成功没有反馈

`frontend/assets/js/files.js` 的 `copyText()`（`:504`）成功分支调用 `toastOk`，但该文件的 import 只引入了 `{ toast, toastError, toastWarn }`（`:23`）——**`toastOk` 未定义**。这条路径在 `navigator.clipboard.writeText()` 成功时抛 `ReferenceError`，界面什么都不显示，正是任务书 2.3 明确点名要避免的「复制了却不知道成没成」。新增的 e2e 用例五在第一次运行时就撞上它（超时等待提示），修复为在 import 里补 `toastOk`（`frontend/assets/js/files.js:23`）。修好后成功/失败两条路都有提示且都带文本内容。

---

## 五、测试结果

### 5.1 全量四层（`python scripts/test.py -v`）

命令 `python scripts/test.py -v`（unit → integration → security → e2e 四层依次执行，前端语法校验含在其中），本阶段收尾时完整跑过一遍：

| 层 | 用例 | 失败 | 错误 | 跳过 | 耗时 | 结果 |
|---|---|---|---|---|---|---|
| unit | 527 | 0 | 0 | 0 | 3.48s | OK |
| integration | 111 | 0 | 0 | 0 | 219.21s | OK |
| security | 82 | 0 | 0 | 0 | 469.17s | OK |
| e2e | 32 | 0 | 0 | 0 | 196.04s | OK |
| **合计** | **752** | **0** | **0** | **0** | **887.90s** | **全部通过** |

与阶段一收尾时的 744 项相比净增 8 项，正好是本阶段新增的 8 项布局 e2e 用例（`tests/e2e/test_browser_layout.py`）；原有 744 项无一改动、无一退化。e2e 层单跑时 8 项耗时 `Ran 8 tests in 29.568s`。

### 5.2 新增 e2e 8 项（`tests/e2e/test_browser_layout.py`）

| 用例 | 断言要点 |
|---|---|
| 一 固定槽位 | 同一动作跨 16 行的 `left/width` 唯一；目录行无「编辑」、压缩包行有「解压」；`edit < extract < rename < compress < delete`；名字右边界 ≤ 按钮组左边界；表格无横向溢出 |
| 二 截断与完整名 | 992 CSS 视口下长名带 `data-truncated` + `title` + `aria-label` + `data-full-name`（均等于真名），短名没有 `tabindex`；鼠标悬浮与键盘聚焦各出一条 `.overlay-tooltip[role=tooltip]` 且不越界，移开/失焦即消失 |
| 三 截断不改真名 | 预览请求 URL 含 `quote(长中文名)`；编辑请求含 `quote(长英文名)` 且编辑器内容为夹具真文本；菜单触发的重命名对话框预填完整真名 |
| 四 菜单替换原生并认目标 | 四种行（普通文件/压缩包/目录/断链）菜单项列表逐项相等；`contextmenu` 事件的 `defaultPrevented === true`；`role=menu` + `aria-label="文件操作"`；四边不越界且贴近鼠标；Escape 关闭；空白菜单含「刷新列表」不含「复制名称」 |
| 五 三条关闭路径 + 键盘 | Escape；点列表外（不导航、不弹框）；`End`+`Enter` 触发「复制完整路径」且提示里带真实路径；换目录后菜单与提示计数为 0 |
| 六 原生菜单放行 | 搜索框与编辑器里 `defaultPrevented === false`、无自绘菜单、焦点仍在输入框 |
| 七 只读连接 | 可读项不灰、写项（重命名/压缩/删除/上传）灰掉且 hint 为「需要先打开「允许写操作」」；删除项带 `is-danger`；点禁用项菜单不关、不弹确认框 |
| 八 窄窗与 150% 缩放 | 992 CSS：权限/类型列 `display:none`、删除折到第二行且与「解压」左对齐、按钮不出视口、无横向溢出；661 CSS：修改时间列收起、大小列 64px、名字列仍是最宽的数据列且长名仍被截断 |

鼠标与键盘都是**真实输入**（`Input.dispatchMouseEvent` / `Input.dispatchKeyEvent`，走 CDP），不是 `element.click()`；窄窗与缩放用 `Emulation.setDeviceMetricsOverride` 改变视口。

### 5.3 真实桌面 CU 证据

**改造前（`before-*.png`，7 张）**

| 截图 | 说明 |
|---|---|
| `before-00-home-directories.png` | 基线：`/home/aimu` 正常目录列表 |
| `before-01-layout-dir.png` | 夹具目录：长英文/中文名把 `权限` 挤没、操作列右移 |
| `before-02-hover-tooltip.png` / `before-02b-hover-pixel.png` | 鼠标悬浮在**被截断**的名字上：什么提示都没有（两张字节数相同）——这就是 2.3 要解决的问题 |
| `before-03-native-context-menu.png` | 行上右键出的是浏览器原生菜单（返回/重新加载/另存为/打印/检查…） |
| `before-04-narrow.png` | 1240×900：出现横向滚动条、`修改时间`/`操作` 整列在视口外 |
| `before-05-zoom150.png` | 页面 150%：`修改时间` 被裁、操作按钮被右边缘切掉 |

**改造后（`after-*.png`，17 张）**

| 截图 | 说明 |
|---|---|
| `after-00-reload.png` | Ctrl+R 重载后仍连着（会话与列表都能恢复） |
| `after-01-layout-dir.png` | 同一目录：列宽固定，长名不再挤压别的列 |
| `after-02-row-menu.png` | 压缩包行右键：预览/编辑/下载/解压/重命名/压缩成 .tar.gz/删除/复制名称/复制完整路径 |
| `after-03-menu-closed.png` | Escape 关闭（菜单消失、行仍选中） |
| `after-04-blank-menu.png` | 列表空白处右键：刷新列表/返回上一级/上传文件… |
| `after-05-conn-menu.png` | 连接卡片右键：浏览文件/断开/编辑配置/删除连接/复制名称/复制地址 |
| `after-06-native-in-input.png` | **作废**（右键落到了表头行，得到的是「列表操作」菜单），保留以说明过程 |
| `after-07-native-in-search.png` / `after-08-native-closed.png` | 搜索框与编辑器里右键出的是**浏览器原生**菜单（撤销/重做/剪切/复制/粘贴/全选…），Escape 后消失 |
| `after-09-narrow.png` | 1240×900：无横向滚动条，权限/类型列收起，操作列折成两行固定槽位 |
| `after-10-narrow-fullname-click.png` | 点在截断的名字上：自绘提示显示完整 79 字符英文名（分两行） |
| `after-11-narrow-after-tab.png` | Tab 后提示消失 |
| `after-12-narrow-focus-back.png` | Shift+Tab 焦点回到名字后提示重新出现（键盘可达性） |
| `after-13-blank-menu.png` | 光标在列表下方：菜单整体上翻，底边贴视口下沿 |
| `after-14-edge-menu.png` | 光标在右下角：菜单同时上翻 + 左移，四边都在视口内 |
| `after-15-zoom150.png` | 页面 150%：只剩名称/大小/操作三列，名字列反而变宽，按钮不裁切 |

**采集方法的两个坑（供后续阶段复用）**

- Chromium 的**原生右键菜单是独立顶层窗口**，不会出现在窗口截图里；要看它必须用整屏截图（`get_desktop_state`，2560×1440）。`after-07` 就是这么拿到的。
- Windows CU 驱动没有独立的 hover 原语（`drag` 也是按下拖动），所以「悬浮提示」的证据由**点击/键盘焦点**路径呈现（`after-10`~`after-12`）；悬浮与焦点在实现上共用 `showTooltip`，e2e 用例二另用真实鼠标事件补了悬浮路径。

### 5.4 量化测量

| 项目 | 测量 |
|---|---|
| 屏幕 | 2560×1440，显示缩放 1.25（页面缩放 100%，即 1 CSS px = 1.25 物理 px） |
| 宽窗固定槽位 | 夹具目录 16 行的 `重命名` 全部 x=2316（物理）；`/home/aimu` 20 行同样 x=2316 |
| 窄窗（1240×900 物理 / 992 CSS） | 行高 79 物理（操作列折两行）；`重命名` 全部 x=1125 物理（=900 CSS），行宽 768 物理，右边界在窗口内 → 无横向溢出 |
| 行高对比 | 100% 时 79 物理，150% 时 115 物理 |
| 边缘菜单盒 | 331×242 CSS（`after-14` 右下角，四边均在视口内） |
| 150% 缩放（661 CSS 视口） | 名字列 104.4 CSS、大小列 64 CSS、修改时间列收起；名字列仍是最宽的数据列 |

---

## 六、问题与风险

### 6.1 本阶段新发现并已修复

| 编号 | 问题 | 发现方式 | 处理 |
|---|---|---|---|
| L1 | 复制成功时界面无任何反馈 | 新增 e2e 用例五等待「复制完整路径」提示超时 | `frontend/assets/js/files.js:23` 补 `toastOk` 导入（§4.5） |
| L2 | 切换目录后菜单/提示可能指向已被替换的行 | 实现 `renderTable()` 时发现没有关闭调用点 | 新增 `closeOverlays()`（`frontend/assets/js/overlay.js:293`），`renderTable()` 重绘前调用（`frontend/assets/js/files.js:271`） |
| L3 | 只读连接下菜单项只灰不禁用点击 | 设计菜单时确定 | 禁用项带 `disabled` + `tabindex="-1"` + 原因 hint，点击不关菜单（e2e 用例七） |

### 6.2 已知限制

- **悬浮证据以点击/键盘路径呈现**（§5.3 说明）：CU 驱动缺少独立 hover 原语，真实悬浮只由 e2e 的 `Input.dispatchMouseEvent` 覆盖。
- **窄窗收列顺序是取舍，不是通用结论**：断点阈值来自 2560×1440 / 1.25 缩放 + 1240×900 窗口两组实测；其它分辨率或系统缩放下的观感可能不同，但「先收元信息、最后动操作区」的规则是稳定的。
- **菜单只接既有操作**：本阶段没有为菜单新增任何功能（任务书要求）；因此菜单里看不到「新建文件夹 / 批量选择」之类尚未设计的能力。
- **服务端校验未改动**：菜单项的权限控制仍走既有服务端校验；前端禁用只是体验层，不能当作安全边界（任务书 2.5 ⑥ 的要求本来就是「服务端必须独立验证」，该实现自 v0.1.0 起就在）。

### 6.3 与后续阶段的关系

- 阶段三（统一启动脚本）会替换 `scripts/start.py` 的启动方式，与本阶段的前端改动无耦合。
- 断点阶梯与 `overlay.js` 是后续「SSH 配置教程」页面可以复用的组件（教程页同样需要窄窗可读与自绘浮层）。

---

## 七、文档与交付物

| 文件 | 变更 |
|---|---|
| `docs/reports/PHASE-02-LAYOUT-v012.md` | 本报告（新增） |
| `docs/reports/_index.md` | 登记本报告 |
| `docs/CHANGELOG.md` | v0.1.2 段：状态、阶段进度表、修复（L1/L2）、变更、已知限制 |
| `tests/e2e/_index.md` | 登记 `test_browser_layout.py`（8 项，需要测试床与 Edge） |
| `tests/integration/_index.md` | `support.py` 行补 `layout_fixture()` 说明 |
| `frontend/assets/js/_index.md` | 登记 `overlay.js`，并补两条已知坑（重绘前必须 `closeOverlays()`；`build` 返回空时不拦截原生菜单） |
| `AGENTS.md` | 顶层白名单的 `.md` 行换成 `dev_guide/`；权威规格来源由根目录 `.md` 更正为 `dev_guide/`（当前接力版 `dev_guide/0.1.2_.md`） |
| `.temp/cu-v012-layout/` | CU 前后证据 24 张（会话中转目录，不入库） |

---

## 八、阶段结论

阶段二的 2.2 / 2.3 / 2.5 三项要求全部落地，并在**真实桌面**上留下改造前/后各一组截图：改造前长名挤压列宽、窄窗出横向滚动条、150% 缩放下按钮被裁、右键只有原生菜单、截断的名字没有任何查看途径；改造后列宽与按钮位置固定、窄窗按断点收列、截断的名字有三条途径看全并带成功/失败反馈、右键菜单在三处替换原生菜单而输入框与编辑器仍保留原生文本交互。四层回归全绿，新增 8 项 e2e 全部通过，并在过程中发现并修复一处真实缺陷（复制成功没有反馈）。允许进入阶段三。
