/**
 * 下载与上传。
 *
 * 下载走「票据 + 浏览器自己的导航」：只有浏览器自己发起的下载才有原生进度、
 * 断点提示和「另存为」对话框，而这类请求带不了自定义头，所以先用一次带令牌
 * 的 POST 换一张只能下这一个文件的短票据。（详见 app/api/tickets.py）
 *
 * 上传走 XMLHttpRequest：fetch 至今没有可用的上传进度事件，而大文件没有进度
 * 就无法判断是慢还是卡住了。取消用 AbortController 接进 XHR 的 abort。
 */

import * as api from "./api.js";
import { $, h, formatSize } from "./util.js";
import { toast, toastOk, toastError, toastWarn } from "./toast.js";
import { confirmDialog, openModal, closeModal } from "./modal.js";
import { state, activeConnection, allowWrite } from "./state.js";

let deps = { onChanged: function () {} };

export function initTransfer(hooks) {
  if (hooks) deps = Object.assign(deps, hooks);
}

export function setTransferStatus(text) {
  $("#transfer-status").textContent = text || "";
}

/* ---------------------------------------------------------------- 下载 */

export async function downloadEntry(entry) {
  const conn = activeConnection();
  if (!conn) return;
  try {
    const info = await api.downloadTicket(conn.id, entry.path);
    const link = document.createElement("a");
    link.href = info.url;
    link.rel = "noopener";
    link.download = entry.name;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTransferStatus("正在下载 " + entry.name + " …（进度见浏览器下载栏）");
    toastOk("已开始下载 " + entry.name);
    // 浏览器接管了传输，我们无法知道它何时结束，几秒后把状态清掉即可。
    setTimeout(function () {
      setTransferStatus("");
    }, 8000);
  } catch (error) {
    toastError(error);
  }
}

/* ---------------------------------------------------------------- 上传 */

export async function uploadFiles(fileList) {
  const conn = activeConnection();
  if (!conn) return;
  if (!allowWrite(conn.id)) {
    toastError(new Error("这条连接没有开启写权限，无法上传。"));
    return;
  }
  const files = Array.from(fileList || []);
  if (files.length === 0) return;

  let done = 0;
  let skipped = 0;
  let failed = 0;
  for (const file of files) {
    const result = await uploadOne(conn, file);
    if (result === "abort") break;
    if (result === "ok") done += 1;
    else if (result === "skip") skipped += 1;
    else failed += 1;
  }

  setTransferStatus("");
  if (done > 0) {
    deps.onChanged();
    toastOk("上传完成：" + done + " 个文件" + (skipped ? "，跳过 " + skipped + " 个" : "") + "。");
  } else if (failed === 0 && skipped > 0) {
    toast("已跳过全部文件。", "warn");
  }
  if (failed > 0) toast(failed + " 个文件上传失败，详情见上方提示。", "error", 8000);
}

async function uploadOne(conn, file) {
  // 1) 先问后端这个位置有没有同名文件 —— 覆盖是不可撤销的，必须让用户先确认。
  let overwrite = false;
  try {
    const info = await api.uploadCheck(conn.id, state.path, file.name);
    if (info && info.exists) {
      if (info.type === "directory") {
        toastError(new Error("「" + file.name + "」在远端是一个目录，无法用文件覆盖。"));
        return "fail";
      }
      const ok = await confirmDialog({
        title: "覆盖远端文件",
        message: "「" + file.name + "」在远端已存在，要用本次上传覆盖它吗？",
        detail:
          "远端现有文件：" +
          formatSize(info.size) +
          "，最后修改 " +
          (info.mtime ? new Date(info.mtime * 1000).toLocaleString() : "时间未知") +
          "。覆盖后旧内容无法恢复。",
        confirmText: "覆盖",
        danger: true,
      });
      if (!ok) return "skip";
      overwrite = true;
    }
  } catch (error) {
    if (error.code !== "path_not_found") {
      toastError(error);
      return "fail";
    }
  }

  // 2) 带进度与取消的上传。
  const dialog = progressDialog(file);
  setTransferStatus("正在上传 " + file.name);
  try {
    await api.uploadFile(conn.id, state.path, file, {
      overwrite: overwrite,
      signal: dialog.controller.signal,
      onProgress: function (loaded, total) {
        dialog.update(loaded, total);
      },
    });
    dialog.finish();
    return "ok";
  } catch (error) {
    dialog.finish();
    if (error.name === "AbortError") {
      toast("已取消上传 " + file.name + "。", "warn");
      return "abort";
    }
    toastError(error);
    return "fail";
  }
}

function progressDialog(file) {
  const barInner = h("div", {});
  const bar = h("div", { class: "progress" }, barInner);
  const info = h("p", {
    class: "hint",
    text: "正在上传 " + file.name + "（" + formatSize(file.size) + "）",
  });
  const body = h("div", {}, info, bar);
  const controller = new AbortController();
  let closed = false;

  const cancelButton = h("button", {
    type: "button",
    class: "btn btn-danger",
    text: "取消上传",
    onClick: function () {
      cancelButton.disabled = true;
      cancelButton.textContent = "正在取消…";
      controller.abort();
    },
  });

  openModal({
    title: "上传文件",
    body: body,
    buttons: [cancelButton],
    onClose: function () {
      // 用户按 Esc 或点背景关掉对话框，等同于取消这次上传 ——
      // 否则后台还在传，而界面上那条进度条已经不见了。
      if (!closed) controller.abort();
      closed = true;
    },
  });

  return {
    controller: controller,
    update: function (loaded, total) {
      const percent = total > 0 ? Math.round((loaded / total) * 100) : 0;
      barInner.style.width = percent + "%";
      info.textContent =
        "正在上传 " +
        file.name +
        "：" +
        percent +
        "%（" +
        formatSize(loaded) +
        " / " +
        formatSize(total) +
        "）";
    },
    finish: function () {
      closed = true;
      closeModal("done");
      setTransferStatus("");
    },
  };
}
