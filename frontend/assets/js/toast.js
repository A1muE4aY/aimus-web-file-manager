/**
 * 右下角的轻量提示。
 *
 * 只用来报告「刚刚发生了什么」，不承载需要用户确认的信息 ——
 * 需要确认的一律走 modal.js 的对话框，因为 toast 会自动消失。
 */

import { $, h } from "./util.js";

const DEFAULT_TIMEOUT = 5000;

export function toast(message, kind, timeout) {
  const options = kind || {};
  const text = typeof kind === "string" ? message : kind.message;
  const level = typeof kind === "string" ? kind : kind.kind || "info";
  const seconds = typeof timeout === "number" ? timeout : options.timeout || DEFAULT_TIMEOUT;

  const node = h(
    "div",
    { class: "toast", "data-kind": level, role: "status" },
    h("span", { class: "toast-text", text: text })
  );
  const close = h("button", {
    type: "button",
    class: "toast-close",
    "aria-label": "关闭提示",
    text: "×",
    onClick: function () {
      remove();
    },
  });
  node.appendChild(close);

  // 长消息给用户更多时间读完；短消息也别一闪而过。
  const lifetime = Math.max(seconds, Math.min(15000, 2000 + text.length * 60));
  let timer = null;
  let removed = false;

  function remove() {
    if (removed) return;
    removed = true;
    if (timer) clearTimeout(timer);
    if (node.parentNode) node.parentNode.removeChild(node);
  }

  node.addEventListener("mouseenter", function () {
    if (timer) clearTimeout(timer);
  });
  node.addEventListener("mouseleave", function () {
    timer = setTimeout(remove, 2000);
  });

  $("#toasts").appendChild(node);
  timer = setTimeout(remove, lifetime);
  return remove;
}

export function toastError(error) {
  const message = (error && error.message) || "发生了未知错误。";
  const detail = error && error.detail ? String(error.detail) : "";
  const node = toast(message, "error", 8000);
  if (detail) {
    // 细节（远端原始信息）单独放一行，便于用户复制给我们排查。
    const box = $("#toasts").lastElementChild;
    if (box) box.appendChild(h("div", { class: "toast-detail", text: detail }));
  }
  return node;
}

export function toastOk(message) {
  return toast(message, "ok", 3500);
}

export function toastWarn(message) {
  return toast(message, "warn", 6500);
}
