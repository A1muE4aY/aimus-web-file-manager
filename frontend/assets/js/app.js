/**
 * 前端入口：把各个模块接到 DOM 上。
 *
 * 分工：connections 管侧栏与连接，files 管列表与导航，transfer 管传输，
 * preview 管预览；互相之间不 import，副作用都从这里出发，谁调用了什么一目了然。
 */

import * as api from "./api.js";
import { $ } from "./util.js";
import { toast, toastOk, toastError, toastWarn } from "./toast.js";
import { confirmDialog, infoDialog } from "./modal.js";
import * as connections from "./connections.js";
import * as files from "./files.js";
import * as transfer from "./transfer.js";
import * as search from "./search.js";
import * as edit from "./edit.js";
import * as fileops from "./fileops.js";
import * as discovery from "./discovery.js";
import { openPreview } from "./preview.js";
import { state, activeConnection, allowWrite, isConnected, connectionById } from "./state.js";

const POLL_INTERVAL_MS = 20000;

function setServerStatus(name, text) {
  $("#server-status").setAttribute("data-state", name);
  $("#server-status-text").textContent = text;
}

function hostInfo(conn) {
  const session = conn.session || {};
  const address = (conn.username ? conn.username + "@" : "") + conn.host + ":" + conn.port;
  return session.home ? address + " · 家目录 " + session.home : address;
}

/** 按当前状态刷新整条工具栏。所有按钮的可用性只在这里决定。 */
function updateToolbar() {
  const conn = activeConnection();
  const connected = Boolean(conn && isConnected(conn.id));
  // 会话被判成「已经断了」时，主区继续留着上一次的列表：列表上方的横幅会写清
  // 原因，按钮也变成「重新连接」。直接把列表换成占位提示会让用户丢掉上下文，
  // 还以为是自己点错了（v0.1.2 缺陷 D2）。
  const broken = Boolean(conn && !connected && (conn.session || {}).state === "error");
  const selected = state.selected;
  const selectable = Boolean(selected && (selected.type === "file" || selected.type === "symlink"));

  $("#content").hidden = !connected && !broken;
  $("#placeholder").hidden = connected || broken;
  $("#write-toggle-wrap").hidden = !connected;
  $("#host-info").textContent = connected ? hostInfo(conn) : "";
  $("#btn-up").disabled = !connected || !state.parent;
  $("#btn-preview").disabled = !(connected && selectable);
  $("#btn-edit").disabled = !(connected && edit.canEdit(selected));
  $("#btn-download").disabled = !(connected && selectable);
  $("#btn-upload").disabled = !(connected && allowWrite(conn.id));
  $("#chk-allow-write").checked = Boolean(connected && allowWrite(conn.id));
  // 搜索栏的可用性与范围文案也随连接状态走，统一在这里刷新。
  search.render();
}

/**
 * 进入一条连接（path 省略时进登录家目录）。
 *
 * path 用在「掉线后重新连接」上：用户刚才看的就是那个目录，连上后应当回到
 * 那里，而不是跳回家目录（v0.1.2 缺陷 D2）。
 */
async function enterConnection(id, path) {
  const conn = connectionById(id);
  if (!conn) return;
  // 换连接时先清掉上一次的检索结果：那些路径属于另一台机器，留着只会误导。
  search.resetSearch();
  state.activeId = id;
  connections.renderSidebar();
  updateToolbar();
  const session = conn.session || {};
  await files.loadDirectory(path || session.home || "/");
  updateToolbar();
}

function leaveConnection() {
  state.activeId = null;
  search.resetSearch();
  files.resetView();
  updateToolbar();
}

/** 检索结果里的「定位」：交给文件列表跳目录并选中，检索面板保持打开。 */
function handleLocate(parent, name) {
  files.locate(parent, name);
}

function handleOpenFile(entry) {
  openPreview(
    entry,
    function (target) {
      transfer.downloadEntry(target);
    },
    function (target) {
      edit.openEditor(target);
    }
  );
}

function handleEdit(entry) {
  edit.openEditor(entry);
}

/**
 * 扫描结果里的「创建连接」：只把地址填进表单，不保存也不连接。
 *
 * 发现出来的地址是候选，所以表单里要明说一遍来源；保存之后仍然要用户点「连接」、
 * 并且先核对主机指纹 —— 这条链路上没有任何一步是自动的。
 */
function handleCreateConnection(draft) {
  connections.openConnectionForm(draft, {
    notice:
      "以下内容来自「扫描本机虚拟机」的结果，只是候选地址：请核对后再保存；" +
      "保存后点「连接」时仍会先让你确认主机指纹。",
  });
}

function handleRename(entry) {
  fileops.renameEntry(entry);
}

function handleDelete(entry) {
  fileops.deleteEntry(entry);
}

function handleCompress(entry) {
  fileops.compressEntry(entry);
}

function handleExtract(entry) {
  fileops.extractEntry(entry);
}

/** 写操作改动了远端，列表里的大小与修改时间必须跟着更新，否则像是没生效。 */
function handleSaved() {
  files.refresh();
}

async function toggleWrite(event) {
  const conn = activeConnection();
  if (!conn) return;
  const want = event.target.checked;
  if (want) {
    const ok = await confirmDialog({
      title: "开启写操作",
      message: "要为「" + (conn.name || conn.id) + "」开启写操作吗？",
      detail:
        "开启后这条连接可以上传并覆盖远端文件。默认关闭，是为了先确认只读浏览足够稳定。",
      confirmText: "开启",
      danger: true,
    });
    if (!ok) {
      event.target.checked = false;
      return;
    }
  }
  try {
    await api.updateConnection(conn.id, { allow_write: want });
    await connections.refreshConnections();
    toastOk(want ? "已开启写操作。" : "已关闭写操作。");
  } catch (error) {
    event.target.checked = !want;
    toastError(error);
  }
  updateToolbar();
  // 「操作」列的按钮（重命名 / 压缩 / 删除）也要跟着变灰或恢复：工具栏走 updateToolbar，
  // 行内按钮只在列表重渲染时更新，不补这一句就要等下一次刷新才生效。
  files.render();
}

function showHelp() {
  const body = document.createElement("div");
  function block(title, lines) {
    const section = document.createElement("section");
    const heading = document.createElement("h3");
    heading.textContent = title;
    section.appendChild(heading);
    const list = document.createElement("ul");
    for (const line of lines) {
      const item = document.createElement("li");
      item.textContent = line;
      list.appendChild(item);
    }
    section.appendChild(list);
    return section;
  }
  body.appendChild(
    block("怎么用", [
      "在左侧「+ 新增」里填目标机的地址与登录方式，然后点「连接」。",
      "双击目录进入，双击文件预览（预览是只读的，不会改动远端文件）；也可以用上方按钮下载。",
      "选中文本文件后点「编辑」可以在线修改并保存；保存前会核对文件有没有被别人改过，有冲突时不会覆盖别人的内容。",
      "「操作」列里可以重命名、压缩成 .tar.gz、解压与删除条目；这些按钮要先打开「允许写操作」。",
      "在搜索框里输入名称回车，会在当前目录及其子目录里递归找文件名；结果里点「定位」直接跳到那个目录。",
      "侧栏的「扫描」会读本机 VMware 的清单、虚拟机配置、DHCP 租约与系统邻居表，再对已知虚拟网段里的一小批地址各做一次 SSH 端口探测；结果里的「创建连接」只是把地址填进表单，连不连由你决定。",
      "顶部路径条可以点任意一级直接跳回去。",
      "「允许写操作」默认关闭；打开后才可以上传与覆盖远端文件。",
    ])
  );
  body.appendChild(
    block("关于安全", [
      "浏览器只与本机服务通信，SSH 连接由后端建立，私钥与密码不会发送到浏览器。",
      "密码不会写入配置文件，断开连接后即丢弃，重连时需要重新输入。",
      "首次连接某台机器时会让你核对主机指纹；指纹变化时本工具不会自动接受。",
      "服务默认只监听 127.0.0.1，局域网内其它机器访问不到。",
      "关闭本工具后 SSH 连接立即断开，不会在后台保留会话。",
    ])
  );
  infoDialog("使用说明", body);
}

function bindHandlers() {
  $("#btn-new-connection").addEventListener("click", function () {
    connections.openConnectionForm(null);
  });
  $("#btn-help").addEventListener("click", showHelp);

  $("#btn-refresh").addEventListener("click", function () {
    files.refresh();
  });
  $("#btn-up").addEventListener("click", function () {
    files.goUp();
  });
  $("#btn-preview").addEventListener("click", function () {
    if (state.selected) handleOpenFile(state.selected);
  });
  $("#btn-edit").addEventListener("click", function () {
    if (state.selected) edit.openEditor(state.selected);
  });
  $("#btn-download").addEventListener("click", function () {
    if (state.selected) transfer.downloadEntry(state.selected);
  });
  $("#btn-upload").addEventListener("click", function () {
    $("#file-input").click();
  });
  $("#file-input").addEventListener("change", async function (event) {
    const input = event.target;
    const chosen = input.files;
    try {
      await transfer.uploadFiles(chosen);
    } finally {
      // 清空，保证连续选同一个文件也能再次触发 change。
      input.value = "";
    }
  });
  $("#chk-allow-write").addEventListener("change", toggleWrite);
}

/** 只刷新状态，不动用户正在看的目录 —— 后台 ssh 掉线要能自己显示出来。 */
async function pollStatus() {
  if (document.hidden) return;
  try {
    await connections.refreshConnections();
    updateToolbar();
  } catch (error) {
    if (error.name === "ApiError" && error.status === 0) return;
  }
}

async function boot() {
  $("#app").hidden = false;
  bindHandlers();
  connections.initConnections({ onEnter: enterConnection, onLeave: leaveConnection });
  discovery.initDiscovery({ onCreateConnection: handleCreateConnection });
  files.initFiles({
    onSelectionChange: updateToolbar,
    onOpenFile: handleOpenFile,
    // 右键菜单里的「下载」「上传文件…」走的还是工具栏那两个入口，
    // 菜单只是把已经存在的能力放到鼠标底下（v0.1.2 阶段二 2.5）。
    onDownload: function (entry) {
      transfer.downloadEntry(entry);
    },
    onUpload: function () {
      $("#file-input").click();
    },
    onPathChange: updateToolbar,
    onEdit: handleEdit,
    onRename: handleRename,
    onDelete: handleDelete,
    onCompress: handleCompress,
    onExtract: handleExtract,
    onReconnect: function (connectionId, path) {
      return connections.connectFlow(connectionId, { path: path });
    },
    onConnectionLost: function () {
      // 刷新连接卡片后重画一次列表：横幅上的按钮要跟着从「重试」变成「重新连接」。
      return connections.refreshConnections().then(function () {
        updateToolbar();
        files.render();
      });
    },
  });
  search.initSearch({ onLocate: handleLocate });
  edit.initEdit({ onSaved: handleSaved });
  fileops.initFileops({ onChanged: handleSaved });
  transfer.initTransfer({
    onChanged: function () {
      files.refresh();
    },
  });
  updateToolbar();

  try {
    state.session = await api.sessionInfo();
    setServerStatus("connected", "本地服务正常 · AWFM " + state.session.version);
  } catch (error) {
    setServerStatus("error", "本地服务不可用");
    toastError(error);
  }

  try {
    await connections.refreshConnections();
    // 页面刷新后后端可能仍然连着某条连接，直接回到它，别让用户重新点一遍。
    const live = state.connections.filter(function (item) {
      return item.session && item.session.connected;
    })[0];
    if (live) await enterConnection(live.id);
  } catch (error) {
    toastError(error);
  }
  updateToolbar();

  setInterval(pollStatus, POLL_INTERVAL_MS);
  window.addEventListener("focus", pollStatus);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
