# frontend/assets/js/ 索引

原生 ES 模块，**零框架、零 CDN、无构建步骤**（验收项 T-002）。所有 DOM 通过 `util.js` 的 `$` 取，选择器必须与 `frontend/index.html` 一致。

| 文件 | 用途 |
|---|---|
| `util.js` | `$` / `maybe` 选择器、HTML 转义、大小与时间格式化 |
| `api.js` | 后端 API 封装：统一带 `X-AWFM-Token`、解析 `{ok, data, error}` 信封、把错误转成异常 |
| `state.js` | 前端状态：连接列表、当前会话、当前目录与条目、选中项 |
| `app.js` | 应用引导与外壳：注入令牌、启动自检、进入/退出连接、状态栏与面包屑 |
| `connections.js` | 连接侧栏：新增/编辑/删除、连接与断开、密码输入、主机密钥核对与信任 |
| `files.js` | 文件列表：渲染、排序、双击进入目录、向上、选择、写入门禁开关 |
| `transfer.js` | 上传与下载：进度、重名确认、校验、下载票据 |
| `search.js` | 远端文件检索：发起搜索、轮询进度、结果表、「定位」跳转、中止与清空 |
| `edit.js` | 在线编辑（v0.1.1）：只读预览、编辑、保存时的冲突提示与覆盖确认 |
| `fileops.js` | 文件操作（v0.1.1）：重命名、删除、压缩、解压，以及各操作的确认与结果提示 |
| `discovery.js` | 在线虚拟机发现（v0.1.1 阶段五）：侧栏「扫描」入口、环境与来源状态、扫描进度与中止、结果表分「发现虚拟机 / 地址在线 / SSH 可用」三态、从某一行「创建连接」时预填既有表单（只是候选，保存与指纹确认仍走原路） |
| `preview.js` | 文本预览：编码与截断提示 |
| `overlay.js` | 自绘浮层（v0.1.2 阶段二）：右键菜单（`openMenu`/`closeMenu`/`installContextMenu`，capture 阶段拦截 `contextmenu`，视口边自动翻边）与完整名称提示（`showTooltip`/`hideTooltip`）。输入框、文本域、`[contenteditable]`、`.editor-text` 命中 `isNativeTextTarget` 时放行原生菜单 |
| `modal.js` | 模态框：标题/正文/按钮，焦点与 Esc 关闭 |
| `toast.js` | 轻提示：成功/失败/信息，自动消失 |
| `icons.js` | 内联 SVG 图标（离线，不引外部图标库） |

## 已知坑（真实踩过，见 docs/reports/PHASE-05）

* `api.js` 的 `request()` 返回的是 `payload.data`，调用方要自己取内层键（例如 `data.connections`）。
* 打开目录要 `dblclick`，单击只是选中。
* `overlay.js` 的菜单与提示挂在 `document.body` 上，不会随表格重绘消失：`renderTable()` 必须在重绘前调用 `closeOverlays()`（`files.js:271`），否则会留下指向已不存在行的菜单。
* `installContextMenu` 的 `build(event)` 返回 `null` 或空数组时**不拦截**原生菜单——这是「输入框里仍要能粘贴」的实现方式，不要改成无条件 `preventDefault`。
