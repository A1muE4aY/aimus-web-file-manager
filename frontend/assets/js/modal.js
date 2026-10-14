/**
 * 模态对话框。
 *
 * 页面上只有一组模态 DOM（#modal-root），所有对话框复用它 —— 避免出现
 * 两个模态叠在一起、Esc 到底关掉哪一个的混乱。
 */

import { $, clear, h } from "./util.js";

let state = null;

export function isModalOpen() {
  return state !== null;
}

/**
 * 打开对话框。
 *
 * @param {object} options
 * @param {string} options.title
 * @param {Node}   options.body      对话框主体
 * @param {Node[]} options.buttons   底部按钮
 * @param {boolean} options.wide     宽版（大段文本预览用）
 * @param {Function} options.onClose 关闭回调
 */
export function openModal(options) {
  const opts = options || {};
  const root = $("#modal-root");
  const modal = root.querySelector(".modal");
  const body = $("#modal-body");
  const foot = $("#modal-foot");

  clear(body);
  clear(foot);
  $("#modal-title").textContent = opts.title || "";
  if (opts.body) body.appendChild(opts.body);
  const buttons = opts.buttons || [];
  for (const button of buttons) foot.appendChild(button);
  foot.hidden = buttons.length === 0;
  modal.classList.toggle("wide", Boolean(opts.wide));

  root.hidden = false;
  state = { onClose: opts.onClose || null };

  // 焦点给第一个可输入元素；没有就落到关闭按钮，保证 Esc 之外还有出路。
  const first = body.querySelector("input:not([type=hidden]), select, textarea") || body.querySelector("button");
  (first || $("#modal-close")).focus();
  return { close: closeModal };
}

export function closeModal(reason) {
  if (!state) return;
  const onClose = state.onClose;
  state = null;
  const root = $("#modal-root");
  root.hidden = true;
  clear($("#modal-body"));
  clear($("#modal-foot"));
  if (onClose) {
    try {
      onClose(reason);
    } catch (error) {
      // 关闭回调里抛错不应把界面卡在「模态打开了但其实已经关掉」的状态。
      console.error("模态关闭回调出错：", error);
    }
  }
}

/** 焦点留在对话框内：Tab 到边界时绕回来。 */
function trapFocus(event) {
  const root = $("#modal-root");
  if (!state || event.key !== "Tab") return;
  const focusable = root.querySelectorAll(
    'button, [href], input:not([type=hidden]), select, textarea, [tabindex]:not([tabindex="-1"])'
  );
  const visible = [];
  for (const node of focusable) {
    if (!node.disabled && node.offsetParent !== null) visible.push(node);
  }
  if (visible.length === 0) return;
  const first = visible[0];
  const last = visible[visible.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

document.addEventListener("keydown", function (event) {
  if (!state) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeModal("escape");
    return;
  }
  trapFocus(event);
});

document.addEventListener("DOMContentLoaded", function () {
  $("#modal-backdrop").addEventListener("click", function () {
    closeModal("backdrop");
  });
  $("#modal-close").addEventListener("click", function () {
    closeModal("close");
  });
});

/**
 * 确认对话框。
 *
 * 所有破坏性操作（断开连接、删除连接配置、覆盖远端文件）都必须经过它，
 * 这是规划文档 §3.2 对高风险操作的要求。
 */
export function confirmDialog(options) {
  const opts = options || {};
  return new Promise(function (resolve) {
    let settled = false;
    function finish(value) {
      if (settled) return;
      settled = true;
      resolve(value);
    }

    const body = h("div", { class: "confirm-body" });
    body.appendChild(h("p", { text: opts.message || "" }));
    if (opts.detail) body.appendChild(h("p", { class: "hint", text: opts.detail }));

    const cancel = h("button", {
      type: "button",
      class: "btn",
      text: opts.cancelText || "取消",
      onClick: function () {
        finish(false);
        closeModal("cancel");
      },
    });
    const ok = h("button", {
      type: "button",
      class: "btn " + (opts.danger ? "btn-danger" : "btn-primary"),
      text: opts.confirmText || "确定",
      onClick: function () {
        finish(true);
        closeModal("confirm");
      },
    });

    openModal({
      title: opts.title || "请确认",
      body: body,
      buttons: [cancel, ok],
      onClose: function () {
        finish(false);
      },
    });
  });
}

/** 只读信息对话框（「关于」「帮助」用）。 */
export function infoDialog(title, bodyNode, wide) {
  const close = h("button", {
    type: "button",
    class: "btn btn-primary",
    text: "知道了",
    onClick: function () {
      closeModal("ok");
    },
  });
  openModal({ title: title, body: bodyNode, buttons: [close], wide: Boolean(wide) });
}
