/**
 * 通用小工具：DOM 构造与人类可读格式化。
 *
 * 两条纪律：
 *
 * 1. **一律用 textContent，绝不拼 innerHTML。** 文件名来自远端机器，
 *    里面完全可能包含 `<script>` 或属性注入片段；把它们当 HTML 处理就是
 *    一个远程可控的 XSS。这里的 h() 只支持 text，没有 html 选项。
 * 2. **不做时区/语言的猜测。** 后端把 epoch 秒原样给我们，按用户本机时区
 *    渲染是浏览器的事。
 */

/**
 * 取元素。入参是 CSS 选择器（全站统一写 $("#某 id")）。
 * 选择器写错时立刻抛错，比后面某个 undefined 报错好定位。
 */
export function $(selector) {
  const node = document.querySelector(selector);
  if (!node) throw new Error("页面缺少元素 " + selector + "，前端资源与 index.html 不匹配。");
  return node;
}

/** 同上，但允许找不到（可选元素）。 */
export function maybe(selector) {
  return document.querySelector(selector);
}

function appendChildren(node, children) {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    if (Array.isArray(child)) appendChildren(node, child);
    else if (child instanceof Node) node.appendChild(child);
    else node.appendChild(document.createTextNode(String(child)));
  }
}

/**
 * 建元素。attrs 里：class / text / 事件(onClick) / 布尔属性 / 其余走 setAttribute。
 * 返回的节点永不包含未转义的 HTML。
 */
export function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const key of Object.keys(attrs)) {
      const value = attrs[key];
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key === "value") node.value = value;
      else if (key === "checked" || key === "disabled" || key === "hidden" || key === "selected") node[key] = Boolean(value);
      else if (key.length > 2 && key.slice(0, 2) === "on" && typeof value === "function") {
        node.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (value === true) node.setAttribute(key, "");
      else node.setAttribute(key, String(value));
    }
  }
  appendChildren(node, children);
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

/**
 * 复制一段文本到剪贴板，返回是否成功。
 *
 * 为什么要返回布尔值：复制失败时界面必须说一声。默默什么都不发生的话，用户
 * 会以为复制好了，粘贴出来却是上一次的内容。navigator.clipboard 只在安全
 * 上下文里存在（127.0.0.1 算，局域网地址不算），所以保留 execCommand 兜底。
 */
export async function copyToClipboard(text) {
  const value = String(text === null || text === undefined ? "" : text);
  if (!value) return false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch (error) {
    // 落到下面的兜底路径。
  }
  try {
    const area = document.createElement("textarea");
    area.value = value;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "-1000px";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return Boolean(ok);
  } catch (error) {
    return false;
  }
}

/** 元素里已有的文本（用于 aria-label 之类）。 */
export function setText(node, text) {
  node.textContent = text;
}

/* ---------------------------------------------------------------- 格式化 */

const SIZE_UNITS = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];

/** 字节数 → 人类可读。1 KiB = 1024 B（与 ls -h 一致，不做十进制混用）。 */
export function formatSize(bytes) {
  if (bytes === null || bytes === undefined) return "—";
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1024) return bytes + " B";
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < SIZE_UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = value >= 100 ? 0 : 1;
  return value.toFixed(digits) + " " + SIZE_UNITS[unit];
}

function pad2(n) {
  return n < 10 ? "0" + n : String(n);
}

/** epoch 秒 → 本机时区的 YYYY-MM-DD HH:MM。 */
export function formatTime(epochSeconds) {
  if (!epochSeconds && epochSeconds !== 0) return "—";
  const date = new Date(epochSeconds * 1000);
  if (Number.isNaN(date.getTime())) return "—";
  return (
    date.getFullYear() +
    "-" +
    pad2(date.getMonth() + 1) +
    "-" +
    pad2(date.getDate()) +
    " " +
    pad2(date.getHours()) +
    ":" +
    pad2(date.getMinutes())
  );
}

/** 相对时间，用在详情面板里。 */
export function formatRelative(epochSeconds) {
  if (!epochSeconds && epochSeconds !== 0) return "";
  const seconds = Math.floor(Date.now() / 1000) - epochSeconds;
  if (seconds < 0) return "（时间在未来）";
  if (seconds < 60) return seconds + " 秒前";
  if (seconds < 3600) return Math.floor(seconds / 60) + " 分钟前";
  if (seconds < 86400) return Math.floor(seconds / 3600) + " 小时前";
  if (seconds < 86400 * 30) return Math.floor(seconds / 86400) + " 天前";
  return "";
}

export const TYPE_LABELS = {
  file: "文件",
  directory: "目录",
  symlink: "符号链接",
  socket: "套接字",
  fifo: "命名管道",
  block: "块设备",
  char: "字符设备",
  unknown: "未知",
};

/**
 * 名字像不像压缩包。
 *
 * 与后端 app/services/fileops.py 的 ARCHIVE_SUFFIXES 保持一致：前端只用它决定
 * 「解压」按钮出不出现，真正能不能解压由后端说了算（后缀不对就拒绝）。
 */
const ARCHIVE_SUFFIXES = [".tar.gz", ".tgz", ".tar", ".zip"];

export function isArchiveName(name) {
  const text = String(name || "").toLowerCase();
  for (const suffix of ARCHIVE_SUFFIXES) {
    if (text.length > suffix.length && text.slice(-suffix.length) === suffix) return true;
  }
  return false;
}

export function typeLabel(type) {
  return TYPE_LABELS[type] || type || "未知";
}

const TYPE_CHARS = {
  file: "-",
  directory: "d",
  symlink: "l",
  socket: "s",
  fifo: "p",
  block: "b",
  char: "c",
};

function rwx(mode, shift) {
  const bits = (mode >> shift) & 0o7;
  return (bits & 0o4 ? "r" : "-") + (bits & 0o2 ? "w" : "-") + (bits & 0o1 ? "x" : "-");
}

/**
 * 权限位 → `-rw-r--r--` 形式。
 *
 * 后端保留了完整的 mode（选原生 SFTP 协议的直接收益），所以这里能画出
 * 真实权限位；setuid/setgid/sticky 也要画出来，否则 4755 与 0755 看起来一样。
 */
export function formatPermissions(entry) {
  const perms = entry && typeof entry.permissions === "number" ? entry.permissions : null;
  if (perms === null) return "—";
  const mode = perms & 0o7777;
  const prefix = TYPE_CHARS[entry.type] || "?";
  const chars = (prefix + rwx(mode, 6) + rwx(mode, 3) + rwx(mode, 0)).split("");
  if (mode & 0o4000) chars[3] = mode & 0o100 ? "s" : "S";
  if (mode & 0o2000) chars[6] = mode & 0o010 ? "s" : "S";
  if (mode & 0o1000) chars[9] = mode & 0o001 ? "t" : "T";
  return chars.join("");
}

/** 把分片路径显示成面包屑，末段返回 null 让调用方决定要不要省略。 */
export function unknownErrorMessage(error) {
  if (error && error.name === "AbortError") return "已取消。";
  return (error && error.message) || "发生了未知错误。";
}
