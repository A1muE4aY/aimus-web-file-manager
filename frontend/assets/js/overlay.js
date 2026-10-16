/**
 * 浮层：自定义右键菜单与「完整名称」提示。
 *
 * 两件事放在一个模块里，是因为它们共用同一套定位、避让与关闭逻辑：都要贴着
 * 鼠标或元素出现、都要躲开视口边缘、都要能被 Escape 与点击外部关掉。
 *
 * 三条纪律：
 *
 * 1. **只拦我们自己的区域。** 安装点是文件列表与连接卡片；输入框、文本域、
 *    可编辑区域一律放行，浏览器原生的复制粘贴、拼写检查不能被破坏。
 * 2. **菜单只是入口。** 每一项都调用既有业务函数，写权限、二次确认、错误提示
 *    都在那条链路上；菜单自己不碰远端，也不因为「界面上没显示」就当成了权限。
 * 3. **键盘能用。** 上下键、Home/End、回车、Escape 都要工作；菜单关掉以后
 *    焦点要还给打开它的那个元素。
 */

import { h } from "./util.js";

/** 浮层与视口边缘至少留出的距离。 */
const EDGE = 8;
/** 菜单相对鼠标位置的偏移，别让光标压住第一项文字。 */
const GAP = 2;

/** 这些地方保留浏览器原生右键菜单（复制、粘贴、拼写检查都靠它）。 */
const NATIVE_TEXT_SELECTOR = "input, textarea, select, [contenteditable]:not([contenteditable='false']), .editor-text";

let menu = null;
let menuItems = [];
let menuReturnFocus = null;
let tooltip = null;
let tooltipAnchor = null;
const attached = new Set();

export function isMenuOpen() {
  return Boolean(menu);
}

/** true = 这个节点位于需要原生右键菜单的区域里。 */
export function isNativeTextTarget(node) {
  if (!node || typeof node.closest !== "function") return false;
  return Boolean(node.closest(NATIVE_TEXT_SELECTOR));
}

function placeAt(node, x, y) {
  node.style.left = "0px";
  node.style.top = "0px";
  const size = node.getBoundingClientRect();
  const maxLeft = window.innerWidth - EDGE - size.width;
  const maxTop = window.innerHeight - EDGE - size.height;
  // 视口右侧/下侧放不下时，先试着往回收，再不行就翻到鼠标的另一侧。
  let left = x + GAP;
  if (left > maxLeft) left = x - GAP - size.width;
  left = Math.max(EDGE, Math.min(left, Math.max(EDGE, maxLeft)));
  let top = y + GAP;
  if (top > maxTop) top = y - GAP - size.height;
  top = Math.max(EDGE, Math.min(top, Math.max(EDGE, maxTop)));
  node.style.left = Math.round(left) + "px";
  node.style.top = Math.round(top) + "px";
}

function normalizeItems(items) {
  const out = [];
  for (const item of items || []) {
    if (!item) continue;
    if (item.separator) {
      if (out.length && !out[out.length - 1].separator) out.push({ separator: true });
      continue;
    }
    if (typeof item.onSelect !== "function") continue;
    out.push(item);
  }
  while (out.length && out[out.length - 1].separator) out.pop();
  return out;
}

/**
 * 打开菜单。items 里每项形如：
 * { label, hint, disabled, danger, onSelect }，或 { separator: true } 画一条分隔线。
 */
export function openMenu(options) {
  closeMenu("reopen");
  const items = normalizeItems(options.items);
  if (!items.length) return null;

  const node = h("div", {
    class: "overlay-menu",
    role: "menu",
    tabindex: "-1",
    "aria-label": options.label || "操作菜单",
  });

  for (const item of items) {
    if (item.separator) {
      node.appendChild(h("div", { class: "overlay-menu-sep", role: "separator" }));
      continue;
    }
    const button = h("button", {
      type: "button",
      class: "overlay-menu-item" + (item.danger ? " is-danger" : ""),
      role: "menuitem",
      disabled: Boolean(item.disabled),
      title: item.hint || item.label,
      // 禁用项也要让人知道为什么不能点，但不去抢键盘焦点。
      tabindex: item.disabled ? "-1" : "0",
      onClick: function (event) {
        event.stopPropagation();
        const action = item.onSelect;
        closeMenu("select");
        action();
      },
    });
    button.appendChild(h("span", { class: "overlay-menu-label", text: item.label }));
    if (item.hint) button.appendChild(h("span", { class: "overlay-menu-hint", text: item.hint }));
    node.appendChild(button);
  }

  menuReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  document.body.appendChild(node);
  placeAt(node, options.x, options.y);
  menu = node;
  menuItems = Array.prototype.slice.call(node.querySelectorAll(".overlay-menu-item:not([disabled])"));
  node.addEventListener("keydown", onMenuKeydown);
  document.addEventListener("mousedown", onDocumentMouseDown, true);
  document.addEventListener("contextmenu", onDocumentContextMenu, true);
  document.addEventListener("keydown", onDocumentKeydown, true);
  window.addEventListener("resize", onViewportChange, true);
  window.addEventListener("scroll", onViewportChange, true);
  window.addEventListener("wheel", onViewportChange, true);
  // 焦点进菜单：键盘用户按右键（Shift+F10 / 菜单键）后可以立刻上下选。
  if (menuItems.length) menuItems[0].focus();
  else node.focus();
  return node;
}

export function closeMenu(reason) {
  if (!menu) return;
  const node = menu;
  const buttons = menuItems;
  const returnFocus = menuReturnFocus;
  menu = null;
  menuItems = [];
  menuReturnFocus = null;
  node.removeEventListener("keydown", onMenuKeydown);
  document.removeEventListener("mousedown", onDocumentMouseDown, true);
  document.removeEventListener("contextmenu", onDocumentContextMenu, true);
  document.removeEventListener("keydown", onDocumentKeydown, true);
  window.removeEventListener("resize", onViewportChange, true);
  window.removeEventListener("scroll", onViewportChange, true);
  window.removeEventListener("wheel", onViewportChange, true);
  node.remove();
  const focused = document.activeElement;
  const focusWasInside = Boolean(focused && (node === focused || node.contains(focused))) || buttons.indexOf(focused) >= 0;
  if (returnFocus && focusWasInside && document.contains(returnFocus) && reason !== "outside") {
    returnFocus.focus();
  }
}

function onMenuKeydown(event) {
  if (!menu) return;
  const key = event.key;
  if (key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    closeMenu("escape");
    return;
  }
  if (key === "Tab") {
    // 让 Tab 继续在页面里走，只是把菜单收掉，不吞掉这次按键。
    closeMenu("tab");
    return;
  }
  if (!menuItems.length) return;
  const current = menuItems.indexOf(document.activeElement);
  let next = null;
  if (key === "ArrowDown") next = current + 1;
  else if (key === "ArrowUp") next = current <= 0 ? menuItems.length - 1 : current - 1;
  else if (key === "Home") next = 0;
  else if (key === "End") next = menuItems.length - 1;
  else if (key === "Enter" || key === " ") {
    // 按钮的默认行为会派发 click，这里只保证焦点在菜单里时按键确实落在按钮上。
    if (current < 0) {
      event.preventDefault();
      menuItems[0].click();
    }
    return;
  } else if (key === "ArrowRight" || key === "ArrowLeft") {
    return;
  } else {
    return;
  }
  event.preventDefault();
  event.stopPropagation();
  if (next < 0) next = menuItems.length - 1;
  if (next >= menuItems.length) next = 0;
  menuItems[next].focus();
}

function onDocumentMouseDown(event) {
  if (!menu) return;
  if (menu.contains(event.target)) return;
  // 点在菜单外：先关菜单。点在别处的那一下该干嘛干嘛，不阻止默认行为。
  closeMenu("outside");
}

function onDocumentContextMenu(event) {
  if (!menu) return;
  if (menu.contains(event.target)) return;
  closeMenu("outside");
}

function onDocumentKeydown(event) {
  if (event.key === "Escape" && menu) {
    closeMenu("escape");
  }
}

function onViewportChange() {
  if (menu) closeMenu("viewport");
  if (tooltip) hideTooltip();
}

/**
 * 装一个右键菜单入口。build(event) 返回菜单项数组；返回 null / 空数组表示
 * 「这里没有合适的操作」，此时不拦截原生菜单，也不会弹出一个空菜单。
 *
 * options.label 只是给读屏软件听的名字（「文件操作」「连接操作」），菜单项
 * 本身由调用方按当前对象与状态决定，这里不做通用猜测。
 */
export function installContextMenu(root, build, options) {
  if (!root || attached.has(root)) return;
  attached.add(root);
  const label = (options && options.label) || "操作菜单";
  root.addEventListener(
    "contextmenu",
    function (event) {
      if (isNativeTextTarget(event.target)) return;
      let items = null;
      try {
        items = build(event);
      } catch (error) {
        items = null;
      }
      if (!items || !items.length) return;
      event.preventDefault();
      event.stopPropagation();
      openMenu({ x: event.clientX, y: event.clientY, items: items, label: label });
    },
    true
  );
}

/* ------------------------------------------------------- 完整名称提示 */

/**
 * 鼠标悬浮或键盘聚焦时，在条目旁边显示完整的名字。
 *
 * 截断只发生在显示层：这里显示的文本就是条目的真实名称，不改路径、不改请求参数。
 */
export function showTooltip(text, anchor) {
  if (!text || !anchor) return;
  hideTooltip();
  const node = h("div", { class: "overlay-tooltip", role: "tooltip", text: text });
  document.body.appendChild(node);
  const rect = anchor.getBoundingClientRect();
  node.style.left = "0px";
  node.style.top = "0px";
  const size = node.getBoundingClientRect();
  const maxLeft = window.innerWidth - EDGE - size.width;
  let left = rect.left;
  if (left > maxLeft) left = Math.max(EDGE, maxLeft);
  let top = rect.bottom + 6;
  if (top + size.height > window.innerHeight - EDGE) top = Math.max(EDGE, rect.top - size.height - 6);
  node.style.left = Math.round(Math.max(EDGE, left)) + "px";
  node.style.top = Math.round(top) + "px";
  tooltip = node;
  tooltipAnchor = anchor;
}

export function hideTooltip(anchor) {
  if (!tooltip) return;
  if (anchor && tooltipAnchor !== anchor) return;
  tooltip.remove();
  tooltip = null;
  tooltipAnchor = null;
}

/**
 * 把两个浮层一起收掉：列表重绘、目录切换、连接状态变化时调用。
 *
 * 菜单与提示都挂在 body 上，而它们指向的条目会被重绘整批换掉。不主动收的话，
 * 一个菜单会指着已经不在屏幕上的那一行继续留着（v0.1.2 阶段二 2.5：切换目录要关闭）。
 */
export function closeOverlays() {
  closeMenu("viewport");
  hideTooltip();
}
