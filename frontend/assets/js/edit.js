/**
 * 在线文本编辑。
 *
 * 与预览的区别是刻意的：预览只读、有上限、可能只显示前一段；编辑是把整份文件读进来、
 * 改完再整份写回，所以这里只接受能安全往返的文本（UTF-8、非二进制、不超过
 * security.max_edit_bytes）。
 *
 * 保存从来不是「把界面上的字发过去就行」：
 *
 * - 写权限由**服务端**重新确认。这条连接没开写权限时后端直接拒绝，界面上按钮是否
 *   可用只是提示，不作数。
 * - 打开时拿到的 sha256 作为基线一起发回去；远端在编辑期间被改过就拒绝写入
 *   （409 edit_conflict），由用户决定重新加载还是继续编辑 —— 绝不默认覆盖别人的修改。
 * - 保存失败（冲突、断线、权限）时对话框保持打开，内容原样留在 textarea 里。
 *
 * 页面上只有一组模态 DOM，所以「放弃修改」「冲突确认」这类追问做成对话框**内部**的
 * 内联条（#editor-ask / #editor-notice），而不是再开一个确认框 —— 那样会把编辑器
 * 自己的 DOM 冲掉。
 */

import * as api from "./api.js";
import { h, formatSize, formatTime } from "./util.js";
import { openModal, closeModal } from "./modal.js";
import { toast, toastOk, toastError, toastWarn } from "./toast.js";
import { activeConnection, allowWrite } from "./state.js";

const NEWLINE_LABELS = {
  lf: "LF（Unix 换行）",
  crlf: "CRLF（Windows 换行）",
  cr: "CR（旧 Mac 换行）",
  none: "没有换行符",
};

const ROWS = 22;

let deps = { onSaved: function () {} };

export function initEdit(hooks) {
  if (hooks) deps = Object.assign(deps, hooks);
}

/** 只有普通文件能进文本编辑：目录、设备、套接字都不行。 */
export function canEdit(entry) {
  return Boolean(entry && entry.type === "file");
}

/**
 * 打开编辑器。
 *
 * 先把远端内容读回来，读不回来就不开对话框 —— 打开一个空白编辑器让用户以为
 * 文件本来就是空的，是最坏的一种「成功」。
 */
export async function openEditor(entry) {
  const conn = activeConnection();
  if (!conn) return;
  if (!canEdit(entry)) {
    toastWarn("只有普通文件可以在线编辑。");
    return;
  }
  let payload;
  try {
    payload = await api.readText(conn.id, entry.path);
  } catch (error) {
    reportReadFailure(error);
    return;
  }
  showEditor(conn, entry, payload.file, payload.limits || {});
}

/** 把后端对「不能编辑」的解释如实转达，不要笼统地说一句失败。 */
function reportReadFailure(error) {
  const code = error && error.code;
  if (code === "payload_too_large") {
    toast("这个文件太大，不能在线编辑。可以先预览前一段，或下载下来用别的工具改。", "warn", 9000);
    return;
  }
  if (code === "invalid_request") {
    toast("这个文件无法在线编辑：" + (error.message || ""), "warn", 9000);
    return;
  }
  toastError(error);
}

function showEditor(conn, entry, file, limits) {
  let baseline = file; // 保存时当作基线的快照；冲突后「重新加载」会替换它
  let original = file.text; // 用来判断有没有改过

  const area = h("textarea", {
    class: "editor-text",
    id: "editor-text",
    rows: ROWS,
    spellcheck: "false",
    "aria-label": "文件内容",
  });
  area.value = original;

  const info = h(
    "dl",
    { class: "kv editor-kv" },
    h("dt", { text: "路径" }),
    h("dd", { text: file.path }),
    h("dt", { text: "大小" }),
    h("dd", { text: formatSize(file.size) + "（上限 " + formatSize(file.limit || limits.max_edit_bytes || 0) + "）" }),
    h("dt", { text: "修改时间" }),
    h("dd", { text: formatTime(file.mtime) }),
    h("dt", { text: "编码" }),
    h("dd", { text: file.encoding + (file.bom ? "（带 BOM，保存时保留）" : "") }),
    h("dt", { text: "换行" }),
    h("dd", { text: newlineLabel(file) })
  );

  const notice = h("p", { class: "editor-notice", id: "editor-notice", hidden: true });
  const counts = h("span", { class: "editor-counts", id: "editor-counts" });
  const dirty = h("span", { class: "editor-dirty", id: "editor-dirty" });

  const save = h("button", {
    type: "button",
    class: "btn btn-primary",
    id: "btn-editor-save",
    text: "保存",
    onClick: function () {
      saveNow();
    },
  });
  const reload = h("button", {
    type: "button",
    class: "btn btn-small",
    id: "btn-editor-reload",
    text: "重新加载远端内容",
    hidden: true,
    onClick: function () {
      reloadRemote();
    },
  });
  const cancel = h("button", {
    type: "button",
    class: "btn",
    id: "btn-editor-cancel",
    text: "取消",
    onClick: function () {
      cancelNow();
    },
  });

  const ask = h("div", { class: "editor-ask", id: "editor-ask", hidden: true });
  const askText = h("p", { class: "editor-ask-text", id: "editor-ask-text" });
  const askYes = h("button", { type: "button", class: "btn btn-danger btn-small", id: "editor-ask-yes" });
  const askNo = h("button", {
    type: "button",
    class: "btn btn-small",
    id: "editor-ask-no",
    text: "继续编辑",
    onClick: function () {
      hideAsk();
    },
  });
  ask.appendChild(askText);
  ask.appendChild(h("span", { class: "editor-ask-actions" }, askYes, askNo));

  const body = h("div", { class: "editor-body" }, info, notice, area, ask);
  const foot = h(
    "div",
    { class: "editor-foot" },
    counts,
    dirty,
    h("span", { class: "editor-foot-right" }, reload, cancel, save)
  );

  openModal({
    title: "编辑 " + file.name,
    body: body,
    buttons: [foot],
    wide: true,
    // Esc、点空白处、右上角 × 与「取消」按钮一样要检查未保存的修改：真实 CU 里
    // 在对话框外面点了一下，刚写的几行就被悄悄丢掉了，前后不一致。
    onRequestClose: function () {
      cancelNow();
      return false;
    },
  });

  const writable = allowWrite(conn.id);
  if (!writable) {
    setNotice("warn", "这条连接没有开启写权限：可以在这里看内容，但保存会被服务端拒绝。");
  }

  let askHandler = null;
  askYes.addEventListener("click", function () {
    const fn = askHandler;
    hideAsk();
    if (fn) fn();
  });

  area.addEventListener("input", refreshStatus);
  area.addEventListener("keydown", function (event) {
    if (event.key === "s" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      saveNow();
    }
  });

  refreshStatus();
  area.focus();

  /* ------------------------------------------------------------ 对话框内部 */

  function isDirty() {
    return area.value !== original;
  }

  function refreshStatus() {
    const bytes = utf8Bytes(area.value);
    counts.textContent = area.value.length + " 个字符 · 约 " + formatSize(bytes);
    const changed = isDirty();
    dirty.textContent = changed ? "已修改，尚未保存" : "与打开时一致";
    dirty.setAttribute("data-dirty", changed ? "true" : "false");
    save.disabled = !writable || !changed;
  }

  function setNotice(kind, text) {
    notice.hidden = false;
    notice.setAttribute("data-kind", kind);
    notice.textContent = text;
  }

  function askFor(text, yesText, onYes) {
    askText.textContent = text;
    askYes.textContent = yesText;
    askHandler = onYes;
    ask.hidden = false;
  }

  function hideAsk() {
    ask.hidden = true;
    askHandler = null;
  }

  function cancelNow() {
    if (!isDirty()) {
      closeModal("cancel");
      return;
    }
    askFor("有未保存的修改，确定放弃吗？", "放弃修改并关闭", function () {
      closeModal("discard");
    });
  }

  async function saveNow() {
    if (!writable) {
      setNotice("warn", "这条连接没有开启写权限，保存被拒绝。请在工具栏打开「允许写操作」后重试。");
      return;
    }
    if (!isDirty()) {
      setNotice("info", "内容和打开时一样，没有需要保存的改动。");
      return;
    }
    hideAsk();
    save.disabled = true;
    setNotice("busy", "正在保存…");
    try {
      const result = await api.saveText(conn.id, baseline.path, area.value, {
        baseSha256: baseline.sha256,
        baseMtime: baseline.mtime,
        // 空串 = 沿用文件当前的换行风格，别把 CRLF 文件悄悄改成 LF。
        newline: "",
        keepBom: Boolean(baseline.bom),
      });
      const saved = result.file;
      closeModal("saved");
      toastOk("已保存「" + saved.name + "」（" + formatSize(saved.size) + "）。");
      deps.onSaved();
    } catch (error) {
      handleSaveFailure(error);
    }
  }

  function handleSaveFailure(error) {
    const code = error && error.code;
    if (code === "edit_conflict") {
      reload.hidden = false;
      setNotice(
        "warn",
        (error.message || "远端文件已被改动。") +
          " 为了不覆盖别人的修改，AWFM 没有写入。你可以点「重新加载远端内容」看现在的版本，或继续编辑后再决定。"
      );
    } else if (code === "unauthorized") {
      setNotice(
        "error",
        error.message + "（这是服务端拒绝的，界面上的按钮状态不作数。）"
      );
    } else {
      setNotice(
        "error",
        "保存失败：" +
          ((error && error.message) || "未知错误。") +
          (error && error.detail ? "（" + error.detail + "）" : "") +
          " 内容还在编辑器里，可以重试或先复制出去。"
      );
    }
    save.disabled = false;
  }

  async function reloadRemote() {
    reload.disabled = true;
    setNotice("busy", "正在重新加载远端内容…");
    try {
      const payload = await api.readText(conn.id, baseline.path);
      baseline = payload.file;
      original = payload.file.text;
      area.value = original;
      reload.hidden = true;
      setNotice("info", "已重新加载远端内容（你刚才的修改已放弃）。");
      refreshStatus();
    } catch (error) {
      setNotice("error", "重新加载失败：" + ((error && error.message) || "未知错误。"));
    } finally {
      reload.disabled = false;
    }
  }
}

function newlineLabel(file) {
  const parts = [NEWLINE_LABELS[file.newline] || "未知（保存时按原样处理）"];
  if (file.mixed_newlines) parts.push("文件里混用了多种换行，保存时按最常见的一种写回");
  if (!file.final_newline) parts.push("末尾没有换行");
  return parts.join("；");
}

/** 粗略估 UTF-8 字节数（真正的上限由服务端把关，这里只是给用户一个量感）。 */
function utf8Bytes(text) {
  let bytes = 0;
  for (const ch of text) {
    const code = ch.codePointAt(0);
    if (code < 0x80) bytes += 1;
    else if (code < 0x800) bytes += 2;
    else if (code < 0x10000) bytes += 3;
    else bytes += 4;
  }
  return bytes;
}
