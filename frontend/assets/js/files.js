/**
 * 文件列表：路径导航、排序、选中。
 *
 * 这一层只负责「把条目画出来」和「用户点了什么」，不直接发起下载/上传 ——
 * 那些动作由 app.js 接到回调后交给 transfer.js，避免模块之间互相 import
 * 形成环。
 */

import * as api from "./api.js";
import { $, h, clear, formatSize, formatTime, formatPermissions, typeLabel } from "./util.js";
import { entryIcon } from "./icons.js";
import { toast, toastError, toastWarn } from "./toast.js";
import { state, activeConnection } from "./state.js";

let deps = {
  onSelectionChange: function () {},
  onOpenFile: function () {},
  onPathChange: function () {},
};

export function initFiles(hooks) {
  if (hooks) deps = Object.assign(deps, hooks);
  bindSortHeaders();
  bindRetry();
}

/** 列表过期时横幅上的「重试」，重试的是当前路径本身。 */
function bindRetry() {
  const retry = $("#btn-retry-list");
  if (!retry) return;
  retry.addEventListener("click", function () {
    refresh();
  });
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
    state.listError = { message: error.message || "加载失败。", detail: error.detail || "" };
    setNotice("error", error.message + (error.detail ? "（" + error.detail + "）" : ""));
    toastError(error);
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
  clear(body);
  const entries = sortEntries(state.entries);
  for (const entry of entries) body.appendChild(rowNode(entry));
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
  wrap.appendChild(
    h("span", {
      class: "entry-name" + (entry.type === "symlink" ? " link" : ""),
      text: entry.name,
    })
  );
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

  row.addEventListener("click", function () {
    select(entry);
  });
  row.addEventListener("dblclick", function () {
    activate(entry);
  });
  return row;
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
