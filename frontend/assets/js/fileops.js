/**
 * 条目级文件操作：重命名、删除、压缩、解压。
 *
 * 三条共同的纪律：
 *
 * 1. **写权限只是提示，服务端说了算。** 未开启写权限时这里直接不发起请求
 *    （省一次往返），但即使界面被绕过，后端每个写入口都会重新检查 allow_write。
 * 2. **破坏性操作都要确认。** 删除走 confirmDialog；目录非空时后端会拒绝一次，
 *    这里再补一次「连同里面的内容一起删除」的确认 —— 两级确认不是冗余，
 *    它们防的是不同的失误（点错按钮 vs 没看清是目录）。
 * 3. **状态与失败原因写在对话框里**（opDialog 的状态行），不用 toast 报错误 ——
 *    toast 会自动消失，用户还没来得及读完就没了。
 */

import * as api from "./api.js";
import { h, formatSize, isArchiveName } from "./util.js";
import { openModal, closeModal, confirmDialog } from "./modal.js";
import { toastOk, toastWarn, toastError } from "./toast.js";
import { activeConnection, allowWrite } from "./state.js";

let deps = { onChanged: function () {} };

export function initFileops(hooks) {
  if (hooks) deps = Object.assign(deps, hooks);
}

/** 这个条目看起来能解压吗（真正的判断在后端）。 */
export function canExtract(entry) {
  return Boolean(entry && entry.type === "file" && isArchiveName(entry.name));
}

function guardWrite(conn) {
  if (allowWrite(conn.id)) return true;
  toastWarn("这条连接没有开启写操作，远端不会接受这次修改。请在工具栏打开「允许写操作」。");
  return false;
}

function describe(error) {
  const message = (error && error.message) || "未知错误。";
  const detail = error && error.detail ? "（" + error.detail + "）" : "";
  return message + detail;
}

/** 没有进度可报、又可能耗时几秒的操作，至少要让人看到它在跑。 */
function busyOverlay(text) {
  const node = h("div", { class: "busy-overlay", id: "busy-overlay" }, h("div", { class: "busy-text", text: text }));
  document.body.appendChild(node);
  return {
    close: function () {
      if (node.parentNode) node.parentNode.removeChild(node);
    },
  };
}

/**
 * 统一的操作对话框：一句说明 + 若干字段 + 状态行 + 取消/确定。
 *
 * 抽出来的理由不是省代码，而是让「运行中 / 失败原因」永远出现在同一个位置：
 * 用户不必在每个对话框里重新找状态写在哪。
 */
function opDialog(options) {
  const opts = options || {};
  const status = h("p", { class: "form-status", id: opts.statusId || null, hidden: true });
  const body = h("div", { class: "form-body" });
  body.appendChild(h("p", { text: opts.message || "" }));
  const fields = opts.fields || [];
  for (const field of fields) body.appendChild(field);
  body.appendChild(status);

  const cancel = h("button", {
    type: "button",
    class: "btn",
    text: "取消",
    onClick: function () {
      closeModal("cancel");
    },
  });
  const ok = h("button", {
    type: "button",
    class: "btn btn-primary",
    id: opts.okId || null,
    text: opts.okText || "确定",
    onClick: function () {
      submit();
    },
  });

  openModal({ title: opts.title || "文件操作", body: body, buttons: [cancel, ok] });

  function setStatus(kind, text) {
    status.hidden = false;
    status.setAttribute("data-kind", kind);
    status.textContent = text;
  }

  function busy(on) {
    ok.disabled = on;
    cancel.disabled = on;
  }

  async function submit() {
    if (opts.validate) {
      const problem = opts.validate();
      if (problem) {
        setStatus("error", problem);
        return;
      }
    }
    busy(true);
    setStatus("busy", opts.busyText || "正在处理…");
    try {
      const result = await opts.run();
      closeModal("done");
      if (result && result.toast) toastOk(result.toast);
      if (result && result.warn) toastWarn(result.warn);
      deps.onChanged();
    } catch (error) {
      busy(false);
      setStatus("error", (opts.failureText || "操作失败：") + describe(error));
    }
  }
}

/* ---------------------------------------------------------------- 重命名 */

export async function renameEntry(entry) {
  const conn = activeConnection();
  if (!conn || !guardWrite(conn)) return;
  const input = h("input", {
    type: "text",
    class: "field-input",
    id: "rename-input",
    value: entry.name,
    maxlength: 255,
    "aria-label": "新名称",
  });
  opDialog({
    title: "重命名",
    message: "把「" + entry.name + "」改成：",
    fields: [input, h("p", { class: "hint", text: "只改同一目录里的名字，不做跨目录移动。" })],
    okText: "重命名",
    okId: "btn-rename-ok",
    statusId: "rename-status",
    busyText: "正在重命名…",
    failureText: "重命名失败：",
    validate: function () {
      const name = input.value.trim();
      if (!name) return "名字不能为空。";
      if (name === entry.name) return "新名称与原名相同。";
      if (name.indexOf("/") >= 0) return "名字里不能有斜杠。";
      if (name === "." || name === "..") return "这个名字不能用。";
      return "";
    },
    run: async function () {
      const data = await api.renameEntry(conn.id, entry.path, input.value.trim());
      return { toast: "已重命名为「" + data.entry.new_name + "」。" };
    },
  });
}

/* ---------------------------------------------------------------- 删除 */

export async function deleteEntry(entry) {
  const conn = activeConnection();
  if (!conn || !guardWrite(conn)) return;
  const isDir = entry.type === "directory";
  const ok = await confirmDialog({
    title: "删除" + (isDir ? "目录" : "条目"),
    message: "确定删除「" + entry.name + "」吗？",
    detail: isDir
      ? "目录会连同里面的内容一起删除。远端没有回收站，删掉就找不回来了。"
      : "远端没有回收站，删掉就找不回来了。",
    confirmText: "删除",
    danger: true,
  });
  if (!ok) return;

  let overlay = busyOverlay("正在删除「" + entry.name + "」…");
  try {
    const data = await api.deleteEntry(conn.id, entry.path, false);
    overlay.close();
    reportDeleted(data);
    return;
  } catch (error) {
    overlay.close();
    const extra = (error && error.extra) || {};
    if (error && error.code === "invalid_request" && extra.entries) {
      // 后端要求显式递归：这里把「里面有多少东西」摆到用户面前再问一次。
      const again = await confirmDialog({
        title: "目录不是空的",
        message: "「" + entry.name + "」里有 " + extra.entries + " 个条目，要连同里面的内容一起删除吗？",
        detail: "这一步之后无法撤销。",
        confirmText: "连同内容一起删除",
        danger: true,
      });
      if (!again) return;
      overlay = busyOverlay("正在删除「" + entry.name + "」…");
      try {
        const data = await api.deleteEntry(conn.id, entry.path, true);
        overlay.close();
        reportDeleted(data);
      } catch (error2) {
        overlay.close();
        toastError(error2);
      }
      return;
    }
    toastError(error);
  }
}

function reportDeleted(data) {
  const removed = data.removed || { files: 0, directories: 0 };
  let text = "已删除「" + data.name + "」";
  if (removed.directories) text += "（文件 " + removed.files + " 个，目录 " + removed.directories + " 个）";
  toastOk(text + "。");
  deps.onChanged();
}

/* ---------------------------------------------------------------- 压缩 */

export async function compressEntry(entry) {
  const conn = activeConnection();
  if (!conn || !guardWrite(conn)) return;
  const input = h("input", {
    type: "text",
    class: "field-input",
    id: "compress-name",
    value: entry.name + ".tar.gz",
    maxlength: 255,
    "aria-label": "压缩包名称",
  });
  opDialog({
    title: "压缩",
    message: "把「" + entry.name + "」打包成 .tar.gz，放在它旁边：",
    fields: [
      input,
      h("p", {
        class: "hint",
        text: "打包在 AWFM 本机完成、字节流经 SFTP 写回，不会在远端执行 tar 命令。符号链接只记录链接本身，不跟进去。",
      }),
    ],
    okText: "压缩",
    okId: "btn-compress-ok",
    statusId: "compress-status",
    busyText: "正在压缩…（条目多的时候要一会儿）",
    failureText: "压缩失败：",
    validate: function () {
      const name = input.value.trim();
      if (!name) return "压缩包名称不能为空。";
      if (name.indexOf("/") >= 0) return "名称里不能有斜杠。";
      return "";
    },
    run: async function () {
      const data = await api.compressEntry(conn.id, entry.path, input.value.trim());
      const skipped = (data.skipped || []).length;
      let text =
        "已生成「" + data.name + "」（" + data.entries + " 个条目，" + formatSize(data.size) + "）";
      if (skipped) text += "，跳过 " + skipped + " 个不支持的条目";
      return { toast: text + "。" };
    },
  });
}

/* ---------------------------------------------------------------- 解压 */

export async function extractEntry(entry) {
  const conn = activeConnection();
  if (!conn || !guardWrite(conn)) return;
  const into = h("input", {
    type: "text",
    class: "field-input",
    id: "extract-into",
    value: parentOf(entry.path),
    "aria-label": "解压到",
  });
  const overwrite = h("input", { type: "checkbox", id: "extract-overwrite" });
  opDialog({
    title: "解压",
    message: "把「" + entry.name + "」解压到：",
    fields: [
      into,
      h("label", { class: "check" }, overwrite, h("span", { text: "覆盖已经存在的同名文件" })),
      h("p", {
        class: "hint",
        text: "默认不覆盖：同名的条目会被跳过并在结果里说明。压缩包里的符号链接与特殊文件不会被解压出来。",
      }),
    ],
    okText: "解压",
    okId: "btn-extract-ok",
    statusId: "extract-status",
    busyText: "正在解压…",
    failureText: "解压失败：",
    validate: function () {
      const target = into.value.trim();
      if (!target) return "解压目标不能为空。";
      if (target.charAt(0) !== "/") return "解压目标要写成绝对路径（以 / 开头）。";
      return "";
    },
    run: async function () {
      const data = await api.extractEntry(conn.id, entry.path, into.value.trim(), overwrite.checked);
      let text = "已解压 " + data.files + " 个文件";
      if (data.directories) text += "、建立 " + data.directories + " 个目录";
      if ((data.existing || []).length) text += "；跳过 " + data.existing.length + " 个已存在的条目";
      if ((data.skipped || []).length) text += "；跳过 " + data.skipped.length + " 个不支持或不安全的条目";
      text += "（目标 " + data.destination + "）。";
      if (data.stopped) return { warn: text + " 解压被上限中断：" + data.stopped };
      return { toast: text };
    },
  });
}

/** /home/aimu/a.tar.gz → /home/aimu；已经在根下的条目回落到 /。 */
function parentOf(path) {
  const trimmed = String(path || "").replace(/\/+$/, "");
  const index = trimmed.lastIndexOf("/");
  return index <= 0 ? "/" : trimmed.slice(0, index);
}
