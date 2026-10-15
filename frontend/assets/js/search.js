/**
 * 远端文件检索：发起搜索、轮询进度、渲染结果、中止与清空。
 *
 * 搜索本身跑在服务端（SFTP 通道只在后端），前端只做两件事：把快照画出来，
 * 以及把「用户想中止」传回去。因此这里**不做任何本地过滤或累计** —— 界面上的
 * 条数一律取后端快照里的 result_count，否则「界面 3 条 / 服务端 5 条」这种
 * 对不上的状态迟早会出现，而且没人说得清哪边对。
 *
 * 轮询用代号（pollToken）作废过期回调：清空或另起一次搜索之后，上一次请求的
 * 响应回来时必须被丢弃，不能覆盖新搜索的状态。
 */

import * as api from "./api.js";
import { $, h, clear, formatSize, formatTime } from "./util.js";
import { entryIcon } from "./icons.js";
import { toastWarn, toastError } from "./toast.js";
import { state, activeConnection, emptySearch } from "./state.js";

const POLL_INTERVAL_MS = 700;
const MAX_QUERY_CHARS = 128;

/** 结果表里的类型文字：图标之外再写一遍，用户不必猜那个小图标是什么意思。 */
const TYPE_LABELS = { directory: "目录", file: "文件", symlink: "符号链接" };

let deps = {
  /** 点「定位」时回调 (所在目录, 名称)，由 app.js 转给 files.locate。 */
  onLocate: function () {},
};

let pollTimer = null;
let pollToken = 0;

export function initSearch(hooks) {
  if (hooks) deps = Object.assign(deps, hooks);
  const form = $("#searchbar");
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    start();
  });
  $("#search-input").addEventListener("keydown", function (event) {
    if (event.key === "Escape") clearSearch();
  });
  $("#btn-search-cancel").addEventListener("click", function () {
    stopSearch();
  });
  $("#btn-search-clear").addEventListener("click", function () {
    clearSearch();
  });
  render();
}

/* ---------------------------------------------------------------- 发起与轮询 */

async function start() {
  const conn = activeConnection();
  if (!conn) {
    toastWarn("先连接一台机器，再搜索。");
    return;
  }
  const input = $("#search-input");
  const query = (input.value || "").trim();
  if (!query) {
    toastWarn("请先输入要搜索的名称。");
    input.focus();
    return;
  }
  if (query.length > MAX_QUERY_CHARS) {
    toastWarn("搜索关键词过长（上限 " + MAX_QUERY_CHARS + " 个字符）。");
    input.focus();
    return;
  }

  // 起点固定成「发起搜索时所在的目录」并显示在面板里：用户点了结果跳到别的
  // 目录之后，仍然看得出来这次搜的是哪里。
  const root = state.path || "/";
  stopPolling();
  state.search = emptySearch();
  state.search.status = "starting";
  state.search.connectionId = conn.id;
  state.search.root = root;
  state.search.query = query;
  render();

  try {
    const data = await api.startSearch(conn.id, root, query);
    apply(data && data.search);
  } catch (error) {
    state.search.status = "failed";
    state.search.error = { message: error.message || "搜索失败。", detail: error.detail || "" };
    render();
    toastError(error);
    return;
  }
  startPolling();
}

function startPolling() {
  stopPolling();
  const token = ++pollToken;
  pollTimer = window.setInterval(function () {
    pollStatus(token);
  }, POLL_INTERVAL_MS);
  pollStatus(token);
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function pollStatus(token) {
  const search = state.search;
  if (token !== pollToken || !search.id) return;
  let data = null;
  try {
    data = await api.searchStatus(search.id);
  } catch (error) {
    if (token !== pollToken) return;
    stopPolling();
    search.status = "failed";
    search.error = {
      message: error.message || "无法获取搜索进度。",
      detail: error.detail || "",
    };
    render();
    return;
  }
  if (token !== pollToken) return;
  apply(data && data.search);
}

/** 把后端快照搬进前端状态。字段名一次映射完，别在渲染层再散着取。 */
function apply(snapshot) {
  if (!snapshot) return;
  const search = state.search;
  search.id = snapshot.id || search.id;
  search.connectionId = snapshot.connection_id || search.connectionId;
  search.root = snapshot.root || search.root;
  search.query = snapshot.query || search.query;
  search.status = snapshot.status || search.status;
  search.running = Boolean(snapshot.running);
  search.results = Array.isArray(snapshot.results) ? snapshot.results : [];
  search.resultCount =
    typeof snapshot.result_count === "number" ? snapshot.result_count : search.results.length;
  search.scannedDirs = snapshot.scanned_dirs || 0;
  search.scannedEntries = snapshot.scanned_entries || 0;
  search.skippedDirs = snapshot.skipped_dirs || 0;
  search.truncated = Boolean(snapshot.truncated);
  search.truncatedReason = snapshot.truncated_reason || "";
  search.durationSeconds =
    typeof snapshot.duration_seconds === "number" ? snapshot.duration_seconds : null;
  search.error = snapshot.error || null;
  if (!search.running) stopPolling();
  render();
}

/** 用户点「中止」：只是请求，状态要等后端下一次快照才算数。 */
async function stopSearch() {
  const search = state.search;
  if (!search.id || !search.running) return;
  try {
    await api.cancelSearch(search.id);
  } catch (error) {
    // 中止失败通常意味着搜索刚好结束了（404 之类），如实提示即可，
    // 不必把整个面板打成失败态 —— 结果还在，用户仍然能用。
    toastWarn(error.message || "中止搜索失败。");
    return;
  }
  pollStatus(pollToken);
}

/** 清空面板与状态，回到「没搜过」的样子。 */
export function clearSearch() {
  stopPolling();
  pollToken += 1;
  state.search = emptySearch();
  const input = $("#search-input");
  if (input) input.value = "";
  render();
}

/** 切换/断开连接时调用：上一个连接的结果不能留在屏幕上。 */
export function resetSearch() {
  clearSearch();
}

/* -------------------------------------------------------------------- 渲染 */

export function render() {
  const panel = $("#search-panel");
  if (!panel) return;
  const search = state.search;
  const connected = Boolean(activeConnection());
  const idle = search.status === "idle";

  const input = $("#search-input");
  input.disabled = !connected;
  $("#btn-search").disabled = !connected || search.running;
  $("#search-scope").textContent =
    connected && !idle && search.root
      ? "范围：" + search.root + " 及其子目录"
      : connected
        ? "范围：当前目录及其子目录"
        : "";

  const rows = $("#search-rows");
  const body = $("#search-body");
  clear(body);
  // 未搜索/已清空时连表头一起收起来：只剩一个空表头的表格看起来像加载失败。
  rows.hidden = true;
  panel.hidden = idle;
  if (idle) return;

  $("#search-title").textContent = "搜索「" + search.query + "」";
  $("#search-status").textContent = statusText(search);
  $("#search-status").setAttribute("data-state", search.status);
  $("#search-progress").textContent = progressText(search);
  $("#btn-search-cancel").hidden = !search.running;
  $("#btn-search-clear").hidden = false;

  const hint = hintFor(search);
  const hintNode = $("#search-hint");
  hintNode.hidden = !hint;
  if (hint) {
    hintNode.textContent = hint.text;
    hintNode.setAttribute("data-kind", hint.kind);
  }

  for (const item of search.results) body.appendChild(rowNode(item));
  // 没有结果时连表头一起收起来：只剩一个空表头的表格看起来像加载失败。
  rows.hidden = search.results.length === 0;
}

function statusText(search) {
  if (search.status === "starting") return "正在启动…";
  if (search.status === "running") return "搜索中…";
  if (search.status === "done") return "已完成";
  if (search.status === "cancelled") return "已中止";
  return "失败";
}

function progressText(search) {
  if (search.status === "starting") return "";
  const parts = [
    "已扫描 " + search.scannedDirs + " 个目录",
    search.scannedEntries + " 个条目",
    "命中 " + search.resultCount + " 条",
  ];
  if (typeof search.durationSeconds === "number") {
    parts.push("用时 " + search.durationSeconds.toFixed(1) + " 秒");
  }
  return parts.join(" · ");
}

/**
 * 面板里的一句话说明。
 *
 * 这里刻意区分四种情况：搜索失败 / 没有匹配 / 结果被截断 / 有目录读不到。
 * 把它们混成一句「没有结果」会让用户以为文件不存在，而实际上可能是没权限。
 */
function hintFor(search) {
  if (search.status === "failed") {
    const error = search.error || {};
    return {
      kind: "error",
      text:
        "搜索失败：" +
        (error.message || "未知原因") +
        (error.detail ? "（" + error.detail + "）" : ""),
    };
  }
  const notes = [];
  if (search.truncated && search.truncatedReason) notes.push(search.truncatedReason);
  if (search.skippedDirs > 0) {
    notes.push("有 " + search.skippedDirs + " 个目录读不到（权限不足或已被删除），已跳过。");
  }
  if (search.resultCount === 0) {
    if (search.status === "running") return null;
    const prefix = search.status === "cancelled" ? "已中止，没有找到匹配的文件。" : "没有匹配的文件。";
    return { kind: "warn", text: prefix + (notes.length ? " " + notes.join(" ") : "") };
  }
  if (notes.length) return { kind: "warn", text: notes.join(" ") };
  return null;
}

function rowNode(item) {
  const row = h("tr", { "data-type": item.type, "data-name": item.name, title: item.path });
  if (item.type === "directory") row.className = "is-dir";

  const nameCell = h("td", { class: "col-name" });
  const wrap = h("div", { class: "name-cell" }, entryIcon(item.type, item.link_broken));
  wrap.appendChild(
    h("span", {
      class: "entry-name" + (item.type === "symlink" ? " link" : ""),
      text: item.name,
    })
  );
  nameCell.appendChild(wrap);
  row.appendChild(nameCell);

  row.appendChild(
    h("td", { class: "col-type", text: TYPE_LABELS[item.type] || "其他" })
  );
  row.appendChild(h("td", { class: "col-dir", text: item.parent || "", title: item.parent || "" }));
  row.appendChild(
    h("td", { class: "col-size", text: item.type === "directory" ? "—" : formatSize(item.size) })
  );
  row.appendChild(
    h("td", {
      class: "col-time",
      text: formatTime(item.mtime),
      title: item.mtime ? new Date(item.mtime * 1000).toString() : "",
    })
  );

  const action = h("td", { class: "col-action" });
  const button = h("button", { type: "button", class: "btn btn-small", text: "定位" });
  button.addEventListener("click", function (event) {
    event.stopPropagation();
    locate(item);
  });
  action.appendChild(button);
  row.appendChild(action);

  row.addEventListener("dblclick", function () {
    locate(item);
  });
  return row;
}

/** 「定位」：跳到结果所在的目录并选中它；面板不关，方便接着点下一条。 */
function locate(item) {
  deps.onLocate(item.parent || "/", item.name);
}
