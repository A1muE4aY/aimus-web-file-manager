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
  /** 列表状态：idle（还没加载过）| loading | ok | empty | error。 */
  listStatus: "idle",
  /**
   * 表格里显示的条目是否已经不保证是最新的。
   *
   * 两种情况会置位：正在切换到另一个目录（屏幕上还是旧目录的条目），以及最近一次
   * 加载/刷新失败（远端可能已经变了）。它只影响提示文案，**不清空 entries** ——
   * 用户在看的路径和连接状态都不该因为一次失败就被抹掉。
   */
  stale: false,
  /** 最近一次列表失败的原因，加载成功后清空。形如 { message, detail }。 */
  listError: null,
  /** 正在请求的目录路径（过期提示里用它说明目标）。 */
  pendingPath: null,
};

/**
 * 检索状态的初始值。
 *
 * 用工厂函数而不是共享同一个对象字面量：清空搜索时若复用同一个引用，上一次
 * 的结果数组会跟着回来（前端最容易犯的这类别名错误）。
 */
export function emptySearch() {
  return {
    /** 后端搜索 id；null 表示当前没有搜索。 */
    id: null,
    /** 发起搜索的连接 id，用于判断结果是不是已经换了机器。 */
    connectionId: null,
    /** 搜索起点（发起时的当前目录）。 */
    root: null,
    query: "",
    /** idle | starting | running | done | failed | cancelled。 */
    status: "idle",
    running: false,
    /** 后端快照里的结果数组（已按目录优先 + 名称排好序）。 */
    results: [],
    resultCount: 0,
    scannedDirs: 0,
    scannedEntries: 0,
    /** 读不到而跳过的目录数（无权限、已删除等）。 */
    skippedDirs: 0,
    /** 是否因为达到上限而提前结束。 */
    truncated: false,
    truncatedReason: "",
    durationSeconds: null,
    /** 形如 { code, message, detail }。 */
    error: null,
  };
}

/** 检索相关的状态；界面上的结果表完全由它驱动。 */
state.search = emptySearch();

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
