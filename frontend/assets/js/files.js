/**
 * 文件列表：路径导航、排序、选中。
 *
 * 这一层只负责「把条目画出来」和「用户点了什么」，不直接发起下载/上传 ——
 * 那些动作由 app.js 接到回调后交给 transfer.js，避免模块之间互相 import
 * 形成环。
 */

import * as api from "./api.js";
import {
  $,
  h,
  clear,
  copyToClipboard,
  formatSize,
  formatTime,
  formatPermissions,
  typeLabel,
  isArchiveName,
} from "./util.js";
import { entryIcon } from "./icons.js";
import { installContextMenu, showTooltip, hideTooltip, closeOverlays } from "./overlay.js";
import { toast, toastOk, toastError, toastWarn } from "./toast.js";
import { state, activeConnection, allowWrite, isConnected } from "./state.js";

let deps = {
  onSelectionChange: function () {},
  onOpenFile: function () {},
  // 下载与上传由 app.js 接到 transfer.js。这一层不直接 import 传输模块，
  // 免得两个模块互相引用形成环。
  onDownload: function () {},
  onUpload: function () {},
  onPathChange: function () {},
  onEdit: function () {},
  onRename: function () {},
  onDelete: function () {},
  onCompress: function () {},
  onExtract: function () {},
  // 连接断了以后要重新连上时调用（id, 想回到的目录），返回是否连上。
  onReconnect: function () {
    return Promise.resolve(false);
  },
  // 发现通道已经断了时调用，用来马上把连接卡片与工具栏刷成实际状态。
  onConnectionLost: function () {},
};

export function initFiles(hooks) {
  if (hooks) deps = Object.assign(deps, hooks);
  bindSortHeaders();
  bindRetry();
  bindContextMenus();
}

/**
 * 右键菜单的接线（v0.1.2 阶段二 2.5）。
 *
 * 两个安装点各管一件事：行上给「这条目能做什么」，空白处给「列表本身能做什么」。
 * 祖先节点先收到事件，所以空白处那一个遇到行内的右键要放行，交给行菜单处理。
 */
function bindContextMenus() {
  installContextMenu($("#file-body"), function (event) {
    const row = event.target.closest ? event.target.closest("tr[data-name]") : null;
    if (!row) return null;
    const name = row.getAttribute("data-name");
    const entry = state.entries.filter(function (item) {
      return item.name === name;
    })[0];
    return entry ? fileMenuItems(entry) : null;
  }, { label: "文件操作" });
  installContextMenu($(".table-wrap"), function (event) {
    if (event.target.closest && event.target.closest("tr[data-name]")) return null;
    return containerMenuItems();
  }, { label: "列表操作" });
}

/** 列表过期时横幅上的「重试」，重试的是当前路径本身。 */
function bindRetry() {
  const retry = $("#btn-retry-list");
  if (!retry) return;
  retry.addEventListener("click", function () {
    retryLoad();
  });
}

/** 服务端回的「连接已经断了」这类错误码。 */
function isLostCode(code) {
  return code === "not_connected" || code === "session_not_found";
}

/** 现在这条连接是不是已经不能用了：会话断了，或上一次请求就是这么失败的。 */
function connectionLost() {
  const conn = activeConnection();
  if (!conn) return false;
  if (!isConnected(conn.id)) return true;
  return Boolean(state.listError && isLostCode(state.listError.code));
}

/**
 * 「重试」：连接还活着就重发一次请求；连接已经断了就先重新连上再回到原目录。
 *
 * 对着一个已经死掉的会话反复重发是没用的 —— 服务端那边通道早没了，用户只会
 * 看到列表一直挂着「已过期」（v0.1.2 缺陷 D2）。重连走的是正常连接流程，
 * 密码与主机指纹该确认的仍然要确认。
 */
async function retryLoad() {
  const conn = activeConnection();
  if (!conn) return;
  if (connectionLost()) {
    await deps.onReconnect(conn.id, state.path);
    return;
  }
  await refresh();
  // 这一趟才发现通道断了：接着重连，别让用户再点一次。
  if (connectionLost()) await deps.onReconnect(conn.id, state.path);
}

function bindSortHeaders() {
  const headers = document.querySelectorAll("#file-table thead th[data-sort]");
  for (const th of headers) {
    th.addEventListener("click", function () {
      const key = th.getAttribute("data-sort");
      if (state.sort.key === key) {
        state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
      } else {
        state.sort.key = key;
        state.sort.dir = key === "size" || key === "mtime" ? "desc" : "asc";
      }
      renderTable();
    });
  }
}

/* ---------------------------------------------------------------- 加载 */

export async function loadDirectory(path) {
  const conn = activeConnection();
  if (!conn) return;
  setNotice(null);
  state.loading = true;
  state.listStatus = "loading";
  state.pendingPath = path;
  // 换目录时旧条目还留在屏幕上，先如实标记「这不是目标目录的内容」，
  // 免得加载过程中用户以为看到的就是新目录。
  if (path !== state.path) state.stale = true;
  render();
  try {
    const data = await api.listFiles(conn.id, path);
    state.path = data.path || path;
    state.parent = data.parent === undefined ? null : data.parent;
    state.entries = Array.isArray(data.entries) ? data.entries : [];
    state.truncated = Boolean(data.truncated);
    state.total = typeof data.total === "number" ? data.total : state.entries.length;
    state.selected = null;
    state.stale = false;
    state.listError = null;
    state.listStatus = state.entries.length === 0 ? "empty" : "ok";
    deps.onSelectionChange(null);
    deps.onPathChange(state.path);
    if (state.truncated) {
      setNotice(
        "warn",
        "这个目录的条目太多，只显示前 " + state.entries.length + " 项（共 " + state.total + " 项）。"
      );
    }
  } catch (error) {
    // 失败不等于「目录是空的」。保留 path / parent / entries 与连接状态，只把列表
    // 标记为过期并在列表上方说明原因：用户还能看到上次的内容，也能点「重试」。
    // 绝不能把上一次的结果当成最新列表继续显示（2.md 阶段一缺陷②）。
    state.stale = true;
    state.listStatus = "error";
    state.listError = {
      message: error.message || "加载失败。",
      detail: error.detail || "",
      code: error.code || "",
    };
    setNotice("error", error.message + (error.detail ? "（" + error.detail + "）" : ""));
    toastError(error);
    // 通道断了：立刻让连接卡片与工具栏反映实际状态，不必等下一次轮询。
    if (isLostCode(state.listError.code)) deps.onConnectionLost(error);
  } finally {
    state.loading = false;
    state.pendingPath = null;
    render();
  }
}

export function refresh() {
  if (activeConnection()) return loadDirectory(state.path);
  return Promise.resolve();
}

export function goUp() {
  if (state.parent) return loadDirectory(state.parent);
  return Promise.resolve();
}

/* ---------------------------------------------------------------- 渲染 */

export function render() {
  renderCrumbs();
  renderTable();
  $("#btn-up").disabled = !state.parent;
}

function renderCrumbs() {
  const nav = $("#crumbs");
  clear(nav);
  nav.appendChild(
    h("button", {
      type: "button",
      class: "crumb",
      text: "/",
      title: "/",
      onClick: function () {
        loadDirectory("/");
      },
    })
  );
  const parts = state.path.split("/").filter(Boolean);
  let accumulated = "";
  for (const part of parts) {
    accumulated += "/" + part;
    const target = accumulated;
    nav.appendChild(h("span", { class: "crumb-sep", text: "›" }));
    nav.appendChild(
      h("button", {
        type: "button",
        class: "crumb",
        text: part,
        title: target,
        onClick: function () {
          loadDirectory(target);
        },
      })
    );
  }
}

/** 排序：目录始终在最前，其余按所选列。 */
function sortEntries(entries) {
  const key = state.sort.key;
  const dir = state.sort.dir === "desc" ? -1 : 1;
  const rank = function (entry) {
    if (entry.type === "directory") return 0;
    if (entry.type === "symlink") return 1;
    return 2;
  };
  const copy = entries.slice();
  copy.sort(function (a, b) {
    const rankDiff = rank(a) - rank(b);
    if (rankDiff !== 0) return rankDiff;
    let result = 0;
    if (key === "size") result = (a.size || 0) - (b.size || 0);
    else if (key === "mtime") result = (a.mtime || 0) - (b.mtime || 0);
    else if (key === "type") {
      result = String(a.type).localeCompare(String(b.type)) || nameCompare(a, b);
    } else result = nameCompare(a, b);
    if (result === 0) result = nameCompare(a, b);
    return result * dir;
  });
  return copy;
}

function nameCompare(a, b) {
  return String(a.name).localeCompare(String(b.name), undefined, {
    numeric: true,
    sensitivity: "base",
  });
}

function renderTable() {
  const body = $("#file-body");
  // 重绘会把行整批换掉：挂在旧行上的菜单与提示必须先收掉（阶段二 2.5）。
  closeOverlays();
  clear(body);
  const entries = sortEntries(state.entries);
  for (const entry of entries) body.appendChild(rowNode(entry));
  markTruncatedNames();
  renderListStatus();
  renderEmptyHint();
  $("#entry-count").textContent = countText();

  const headers = document.querySelectorAll("#file-table thead th[data-sort]");
  for (const th of headers) {
    if (th.getAttribute("data-sort") === state.sort.key) th.setAttribute("data-dir", state.sort.dir);
    else th.removeAttribute("data-dir");
  }
}

/**
 * 列表状态提示。四种状态要能被用户一眼分开：加载中 / 成功 / 空目录 / 失败，
 * 外加「显示的条目已过期」。过期时表格整体压暗，并在顶部给出原因与重试入口。
 */
function renderListStatus() {
  const wrap = document.querySelector(".table-wrap");
  if (wrap) {
    wrap.setAttribute("data-stale", state.stale ? "true" : "false");
    wrap.setAttribute("data-loading", state.loading ? "true" : "false");
  }
  const banner = $("#list-stale");
  const text = $("#list-stale-text");
  if (!banner) return;
  if (!state.stale) {
    banner.hidden = true;
    return;
  }
  banner.hidden = false;
  // 连接断了时，横幅上那个按钮做的是「重新连接」而不是「重试」：
  // 让人知道点下去会发生什么（v0.1.2 缺陷 D2）。
  const retry = $("#btn-retry-list");
  if (retry) retry.textContent = connectionLost() ? "重新连接" : "重试";
  if (text) {
    if (state.listError) {
      text.textContent =
        "这份列表可能已经过期：最近一次加载失败 —— " +
        state.listError.message +
        (state.listError.detail ? "（" + state.listError.detail + "）" : "");
    } else {
      text.textContent =
        "正在加载 " + (state.pendingPath || state.path) + "，下面显示的还是上一个目录的内容。";
    }
  }
}

/** 空目录与加载失败必须给出不同的文案，不能让失败看起来像「这个目录是空的」。 */
function renderEmptyHint() {
  const empty = $("#dir-empty");
  if (!empty) return;
  if (state.entries.length > 0) {
    empty.hidden = true;
    return;
  }
  if (state.listStatus === "loading") {
    empty.textContent = "正在加载…";
  } else if (state.listStatus === "error") {
    empty.textContent = "加载失败，无法显示这个目录的内容。";
  } else if (state.listStatus === "empty") {
    empty.textContent = "这个目录是空的。";
  } else {
    empty.hidden = true;
    return;
  }
  empty.hidden = false;
}

function countText() {
  const count = state.entries.length;
  if (count > 0) {
    if (state.listStatus === "loading") return count + " 项（正在加载…）";
    if (state.stale) return count + " 项（已过期）";
    return count + " 项" + (state.truncated ? "（已截断，共 " + state.total + " 项）" : "");
  }
  if (state.listStatus === "loading") return "加载中…";
  if (state.listStatus === "error") return "加载失败";
  return "0 项";
}

function rowNode(entry) {
  const selected = state.selected && state.selected.path === entry.path;
  const row = h("tr", {
    "data-type": entry.type,
    "data-name": entry.name,
    "data-selected": selected ? "true" : "false",
    title: entry.path,
  });
  if (entry.type === "directory") row.className = "is-dir";

  const nameCell = h("td", { class: "col-name" });
  const wrap = h("div", { class: "name-cell" }, entryIcon(entry.type, entry.link_broken));
  // 名字列会被截断，所以完整名字在这里留三份：title（鼠标悬浮的原生提示）、
  // aria-label（读屏）、data-full-name（自绘的完整名称浮层）。能不能聚焦由渲染
  // 之后的测量决定 —— 名字没被截断的行不该多出一个 Tab 停留点。
  const name = h("span", {
    class: "entry-name" + (entry.type === "symlink" ? " link" : ""),
    text: entry.name,
    title: entry.name,
    "data-full-name": entry.name,
    "aria-label": entry.name,
  });
  name.addEventListener("keydown", function (event) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      event.stopPropagation();
      activate(entry);
    }
  });
  name.addEventListener("mouseenter", function () {
    if (name.getAttribute("data-truncated") === "true") showTooltip(entry.name, name);
  });
  name.addEventListener("mouseleave", function () {
    hideTooltip(name);
  });
  name.addEventListener("focus", function () {
    if (name.getAttribute("data-truncated") === "true") showTooltip(entry.name, name);
  });
  name.addEventListener("blur", function () {
    hideTooltip(name);
  });
  wrap.appendChild(name);
  if (entry.link_target) {
    wrap.appendChild(
      h("span", {
        class: "entry-target" + (entry.link_broken ? " broken" : ""),
        text: "→ " + entry.link_target + (entry.link_broken ? "（断链）" : ""),
      })
    );
  }
  nameCell.appendChild(wrap);
  row.appendChild(nameCell);

  row.appendChild(
    h("td", {
      class: "col-size",
      text: entry.type === "directory" ? "—" : formatSize(entry.size),
    })
  );
  row.appendChild(h("td", { class: "col-type", text: typeLabel(entry.type) }));
  row.appendChild(h("td", { class: "col-perm", text: formatPermissions(entry) }));
  row.appendChild(
    h("td", {
      class: "col-time",
      text: formatTime(entry.mtime),
      title: entry.mtime ? new Date(entry.mtime * 1000).toString() : "",
    })
  );

  row.appendChild(actionCell(entry));

  row.addEventListener("click", function () {
    select(entry);
  });
  row.addEventListener("dblclick", function () {
    activate(entry);
  });
  return row;
}

/**
 * 「操作」列：把条目级动作放在行内。
 *
 * 两个细节都是刻意的：
 * - 写操作按钮在连接未开写权限时直接禁用：省一次注定被拒的往返。真正的把关在
 *   服务端 —— 每个写入口都会重新检查 allow_write，界面禁用只是提示。
 * - 每个按钮都 stopPropagation：否则点按钮会先触发整行的选中，删除这种动作
 *   会连带把选中项换掉，让人以为自己删的是别的条目。
 */
function actionCell(entry) {
  const conn = activeConnection();
  const writable = Boolean(conn && allowWrite(conn.id));
  const box = h("div", { class: "row-actions" });
  // 五个动作用五个固定槽位：按钮由 CSS 按动作钉在自己的列上（grid-column），
  // 于是「重命名」在任何一行、任何文件类型下都落在同一个横坐标，行与行之间
  // 不会因为少了「编辑」或多出「解压」而错位（v0.1.2 阶段二 2.2）。
  const actions = [];
  if (entry.type === "file") {
    actions.push({ key: "edit", label: "编辑", cls: "btn-edit-entry", enabled: true, run: function () { deps.onEdit(entry); } });
  }
  if (entry.type === "file" && isArchiveName(entry.name)) {
    actions.push({ key: "extract", label: "解压", cls: "btn-extract-entry", enabled: writable, run: function () { deps.onExtract(entry); } });
  }
  actions.push({ key: "rename", label: "重命名", cls: "btn-rename-entry", enabled: writable, run: function () { deps.onRename(entry); } });
  actions.push({ key: "compress", label: "压缩", cls: "btn-compress-entry", enabled: writable, run: function () { deps.onCompress(entry); } });
  actions.push({ key: "delete", label: "删除", cls: "btn-delete-entry", enabled: writable, run: function () { deps.onDelete(entry); } });
  for (const action of actions) {
    box.appendChild(
      h("button", {
        type: "button",
        class: "btn btn-small " + action.cls,
        "data-action": action.key,
        text: action.label,
        disabled: !action.enabled,
        title: action.enabled ? action.label : "需要先打开「允许写操作」",
        onClick: function (event) {
          event.stopPropagation();
          action.run();
        },
      })
    );
  }
  const cell = h("td", { class: "col-action" });
  cell.appendChild(box);
  return cell;
}

/**
 * 名字没被截断的行不该多出 Tab 停留点，所以渲染完量一次：真截断了才给它
 * tabindex 与 data-truncated，键盘用户按 Tab 就能停在名字上看到完整名字。
 */
function markTruncatedNames() {
  const names = document.querySelectorAll("#file-body .entry-name");
  for (const node of names) {
    const truncated = node.clientWidth > 0 && node.scrollWidth > node.clientWidth + 1;
    if (truncated) {
      node.setAttribute("data-truncated", "true");
      node.setAttribute("tabindex", "0");
    } else {
      node.removeAttribute("data-truncated");
      node.removeAttribute("tabindex");
    }
  }
}

/** 复制名称 / 复制路径：成功失败都要给反馈，不能默默什么都不发生。 */
async function copyText(text, what) {
  const ok = await copyToClipboard(text);
  if (ok) toastOk("已复制" + what + "：" + text);
  else toastWarn("浏览器不允许自动复制，请手动选中后复制：" + text);
}

/**
 * 文件行上的右键菜单。
 *
 * 只放「这个条目现在真能做的事」：目录没有预览/编辑/下载，非压缩包没有解压；
 * 需要写权限的动作在只读连接下灰掉并说明原因（而不是藏起来，让人以为工具没做）。
 */
function fileMenuItems(entry) {
  const conn = activeConnection();
  const connected = Boolean(conn && isConnected(conn.id));
  const writable = Boolean(conn && allowWrite(conn.id));
  const writeHint = writable ? "" : "需要先打开「允许写操作」";
  const isFile = entry.type === "file";
  const items = [];
  if (!connected) return items;
  if (entry.type === "directory") {
    items.push({ label: "打开目录", hint: "进入这个目录", onSelect: function () { activate(entry); } });
  } else if (isFile) {
    items.push({ label: "预览", hint: "只读地看一眼内容", onSelect: function () { deps.onOpenFile(entry); } });
    items.push({
      label: "编辑",
      hint: "在线修改并保存",
      onSelect: function () { deps.onEdit(entry); },
    });
  } else {
    items.push({ label: "打开（跟随符号链接）", hint: entry.link_target || "", onSelect: function () { activate(entry); } });
  }
  if (isFile) {
    items.push({ label: "下载", hint: "保存到本机", onSelect: function () { deps.onDownload(entry); } });
  }
  if (isFile && isArchiveName(entry.name)) {
    items.push({
      label: "解压",
      hint: writable ? "解压到当前目录" : writeHint,
      disabled: !writable,
      onSelect: function () { deps.onExtract(entry); },
    });
  }
  items.push({ separator: true });
  items.push({
    label: "重命名",
    hint: writable ? "" : writeHint,
    disabled: !writable,
    onSelect: function () { deps.onRename(entry); },
  });
  items.push({
    label: "压缩成 .tar.gz",
    hint: writable ? "" : writeHint,
    disabled: !writable,
    onSelect: function () { deps.onCompress(entry); },
  });
  items.push({
    label: "删除",
    danger: true,
    hint: writable ? "删除前还会再确认一次" : writeHint,
    disabled: !writable,
    onSelect: function () { deps.onDelete(entry); },
  });
  items.push({ separator: true });
  items.push({ label: "复制名称", hint: "只复制文件名", onSelect: function () { copyText(entry.name, "名称"); } });
  items.push({ label: "复制完整路径", hint: entry.path, onSelect: function () { copyText(entry.path, "路径"); } });
  return items;
}

/** 列表空白处的右键菜单：只放列表本身的操作，不冒充某个条目。 */
function containerMenuItems() {
  const conn = activeConnection();
  if (!conn || !isConnected(conn.id)) return [];
  const writable = allowWrite(conn.id);
  const items = [
    { label: "刷新列表", hint: "重新读取当前目录", onSelect: function () { refresh(); } },
  ];
  if (state.parent) {
    items.push({ label: "返回上一级", hint: state.parent, onSelect: function () { goUp(); } });
  }
  items.push({
    label: "上传文件…",
    hint: writable ? "选择本机文件上传到当前目录" : "需要先打开「允许写操作」",
    disabled: !writable,
    onSelect: function () { deps.onUpload(); },
  });
  return items;
}

function select(entry) {
  state.selected = entry;
  const body = $("#file-body");
  for (const row of body.children) {
    row.setAttribute("data-selected", row.getAttribute("data-name") === entry.name ? "true" : "false");
  }
  deps.onSelectionChange(entry);
}

/** 双击的行为：目录进去，文件交给上层决定（预览）。 */
export async function activate(entry) {
  if (entry.type === "directory") return loadDirectory(entry.path);
  if (entry.type === "symlink") {
    // 列表里刻意不解析链接目标（/usr/bin 那种目录会慢到秒级），
    // 所以只有真要打开时才问服务端一次。
    try {
      const info = await api.statFile(activeConnection().id, entry.path, true);
      if (info.type === "directory") return loadDirectory(info.path);
      deps.onOpenFile(info);
      return undefined;
    } catch (error) {
      toastError(error);
      return undefined;
    }
  }
  if (entry.type === "file") {
    deps.onOpenFile(entry);
    return undefined;
  }
  toast("这种类型的条目不能打开。", "warn");
  return undefined;
}

/**
 * 跳到某个检索结果所在的目录并选中它。
 *
 * 结果里的路径可能是任意深度的，直接 loadDirectory 到它的父目录即可；选中用
 * **名字**而不是完整路径 —— 列表本来就来自这个目录，同一个目录里不会出现两条
 * 同名条目，而 search 结果与列表条目的路径拼法（末尾斜杠之类）不必强求一致。
 */
export async function locate(parent, name) {
  if (!activeConnection()) return;
  await loadDirectory(parent || "/");
  let target = null;
  for (const entry of state.entries) {
    if (entry.name === name) {
      target = entry;
      break;
    }
  }
  if (!target) {
    // 搜索期间目录被改动过是正常的，如实说明，别假装选中了。
    toastWarn("已切到「" + (parent || "/") + "」，但列表里没有「" + name + "」，它可能刚被改动过。");
    return;
  }
  select(target);
  for (const row of $("#file-body").children) {
    if (row.getAttribute("data-name") !== name) continue;
    if (row.scrollIntoView) row.scrollIntoView({ block: "center" });
    // 短暂高亮一下：只靠选中态的话，光标在搜索结果上面时用户不容易注意到
    // 下面的列表已经跳过去了。
    row.classList.add("is-located");
    window.setTimeout(function () {
      row.classList.remove("is-located");
    }, 1600);
  }
}

export function setNotice(kind, text) {
  const node = $("#notice");
  if (!kind || !text) {
    node.hidden = true;
    node.textContent = "";
    return;
  }
  node.hidden = false;
  node.setAttribute("data-kind", kind);
  node.textContent = text;
}

/** 切换连接时清空视图，避免上一条连接的目录残留在屏幕上。 */
export function resetView() {
  state.path = "/";
  state.parent = null;
  state.entries = [];
  state.selected = null;
  state.truncated = false;
  state.total = 0;
  state.stale = false;
  state.listStatus = "idle";
  state.listError = null;
  state.pendingPath = null;
  setNotice(null);
  render();
  deps.onSelectionChange(null);
}
