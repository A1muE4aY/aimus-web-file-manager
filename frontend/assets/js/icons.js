/**
 * 内联 SVG 图标。
 *
 * 不引图标字体、不引图标库 —— 规划文档 §2.1 要求前端零在线资源，
 * 而几个十几像素的图形不值得为它增加一个资源类型。
 * 颜色一律用 `currentColor`，由 CSS 类决定，这样两个主题都自动适配。
 */

const NS = "http://www.w3.org/2000/svg";

function svg(className) {
  const node = document.createElementNS(NS, "svg");
  node.setAttribute("class", className);
  node.setAttribute("viewBox", "0 0 16 16");
  node.setAttribute("width", "16");
  node.setAttribute("height", "16");
  node.setAttribute("aria-hidden", "true");
  node.setAttribute("focusable", "false");
  return node;
}

function shape(parent, d, extra) {
  const path = document.createElementNS(NS, "path");
  path.setAttribute("d", d);
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", "1.3");
  path.setAttribute("stroke-linecap", "round");
  path.setAttribute("stroke-linejoin", "round");
  if (extra) {
    for (const key of Object.keys(extra)) path.setAttribute(key, extra[key]);
  }
  parent.appendChild(path);
  return path;
}

const FOLDER = "M1.7 4.3a1.1 1.1 0 0 1 1.1-1.1h2.9l1.3 1.5h5.2a1.1 1.1 0 0 1 1.1 1.1v6.2a1.1 1.1 0 0 1-1.1 1.1H2.8a1.1 1.1 0 0 1-1.1-1.1z";
const FILE = "M4.2 1.9h4.6l3 3v9.2H4.2z";
const FILE_FOLD = "M8.8 1.9v3h3";
const LINK = "M6.6 9.4 9.4 6.6M6.2 4.6l1.1-1.1a2.6 2.6 0 0 1 3.7 3.7l-1.1 1.1M9.8 11.4l-1.1 1.1a2.6 2.6 0 0 1-3.7-3.7l1.1-1.1";
const DEVICE = "M3.5 4.5h9v7h-9zM3.5 8.5h9";
const FIFO = "M3.5 8h9";

/** 按条目类型给图标。断链单独加一个类，让 CSS 能把整行染红。 */
export function entryIcon(type, broken) {
  let className = "entry-icon";
  const node = svg(className);
  if (type === "directory") {
    node.setAttribute("class", "entry-icon is-dir");
    shape(node, FOLDER);
  } else if (type === "symlink") {
    node.setAttribute("class", "entry-icon is-link" + (broken ? " is-broken" : ""));
    shape(node, LINK);
  } else if (type === "socket" || type === "block" || type === "char") {
    shape(node, DEVICE);
  } else if (type === "fifo") {
    shape(node, FIFO);
  } else {
    shape(node, FILE);
    shape(node, FILE_FOLD);
  }
  return node;
}
