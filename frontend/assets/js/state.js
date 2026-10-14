/**
 * 前端共享状态。
 *
 * 刻意做成一个普通对象而不是散在各模块里的闭包变量：界面上的「当前连接 /
 * 当前目录 / 选中项」会影响好几个模块（侧栏、文件表、工具栏按钮），
 * 集中放一处才看得清谁改了它。
 */

export const state = {
  /** /api/session 的返回，启动时取一次。 */
  session: null,
  /** 连接列表（后端返回的原始结构，含 session 状态）。 */
  connections: [],
  /** 当前正在浏览的连接 id，没在浏览时为 null。 */
  activeId: null,
  /** 当前目录的绝对路径。 */
  path: "/",
  /** 当前目录的条目（后端顺序，前端排序后使用）。 */
  entries: [],
  /** 排序状态。 */
  sort: { key: "name", dir: "asc" },
  /** 当前选中的条目。 */
  selected: null,
  /** 列表是否被截断。 */
  truncated: false,
  /** 目录总条目数（截断前）。 */
  total: 0,
  /** 正在加载目录。 */
  loading: false,
};

export function connectionById(id) {
  for (const item of state.connections) {
    if (item.id === id) return item;
  }
  return null;
}

export function activeConnection() {
  return state.activeId ? connectionById(state.activeId) : null;
}

export function sessionOf(id) {
  const item = connectionById(id);
  return item && item.session ? item.session : null;
}

export function isConnected(id) {
  const session = sessionOf(id);
  return Boolean(session && session.connected);
}

export function allowWrite(id) {
  const item = connectionById(id);
  return Boolean(item && item.allow_write);
}
