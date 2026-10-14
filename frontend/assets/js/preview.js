/**
 * 文本预览。
 *
 * 只预览文本：后端遇到含 \x00 的文件会直接报错，前端把它当普通失败提示即可。
 * 预览是有上限的（默认 256 KiB），超出部分不会读回来 —— 界面上必须说清楚，
 * 否则用户会以为文件就这么点内容。
 */

import * as api from "./api.js";
import { h, clear, formatSize, formatTime } from "./util.js";
import { openModal, closeModal } from "./modal.js";
import { toast, toastError } from "./toast.js";
import { activeConnection } from "./state.js";

export async function openPreview(entry, onDownload) {
  const conn = activeConnection();
  if (!conn) return;
  let data;
  try {
    data = await api.previewFile(conn.id, entry.path);
  } catch (error) {
    if (error.code === "payload_too_large") {
      toast("这个文件太大，无法在浏览器里预览。可以先下载下来再看。", "warn", 8000);
      return;
    }
    toastError(error);
    return;
  }

  const info = h(
    "dl",
    { class: "kv" },
    h("dt", { text: "路径" }),
    h("dd", { text: data.path }),
    h("dt", { text: "大小" }),
    h("dd", { text: formatSize(data.size) }),
    h("dt", { text: "修改时间" }),
    h("dd", { text: formatTime(entry.mtime) })
  );

  const body = h("div", {});
  body.appendChild(info);
  if (data.truncated) {
    body.appendChild(
      h("p", {
        class: "hint",
        text:
          "文件大于预览上限，下面只显示了前 " +
          formatSize(data.bytes_read) +
          " 的内容（编码按 " +
          data.encoding +
          " 解析）。",
      })
    );
  } else if (data.encoding !== "utf-8") {
    body.appendChild(
      h("p", { class: "hint", text: "这个文件不是 UTF-8 文本，按 " + data.encoding + " 显示。" })
    );
  }
  body.appendChild(h("pre", { class: "preview-text", text: data.text }));

  const download = h("button", {
    type: "button",
    class: "btn",
    text: "下载",
    onClick: function () {
      closeModal("download");
      if (onDownload) onDownload(entry);
    },
  });
  const close = h("button", {
    type: "button",
    class: "btn btn-primary",
    text: "关闭",
    onClick: function () {
      closeModal("close");
    },
  });

  openModal({
    title: "预览 " + entry.name,
    body: body,
    buttons: [download, close],
    wide: true,
  });
}
