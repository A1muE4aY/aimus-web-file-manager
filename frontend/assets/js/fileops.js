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
import { state, activeConnection, allowWrite } from "./state.js";

let deps = {
  // 列表/视图已经变化（成功之后统一走这里刷新）。
  onChanged: function () {},
  // 剪贴板内容变了（工具栏的「粘贴」按钮要跟着亮/灰）。
  onClipboardChange: function () {},
  // 等列表刷新完成（新建之后要据此区分「创建成功」与「创建成功但列表没刷新」）。
  refreshList: function () {
    return Promise.resolve();
  },
};

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

/**
 * 拆掉响应外面那层信封（后端把结果包成 {"entry": ...} / {"deleted": ...} 这样的形状）。
 *
 * 这里刻意在缺键时抛错而不是返回 undefined：界面上显示「已删除「undefined」」
 * 比直接报错更难查 —— 端到端用例会因此立刻变红。
 */
function unwrap(data, key) {
  if (!data || typeof data !== "object" || !(key in data)) {
    throw new Error("接口响应里缺少 " + key + " 字段，界面无法显示这次操作的结果。");
  }
  return data[key];
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
      // silent：这一次的 run() 自己已经把列表刷新过了（新建就是这种），再刷一次
      // 只会让刚出现的行闪一下。其它情况仍然交给 onChanged 统一刷新。
      if (!(result && result.silent)) await deps.onChanged();
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
      const renamed = unwrap(
        await api.renameEntry(conn.id, entry.path, input.value.trim()),
        "entry"
      );
      return { toast: "已重命名为「" + renamed.new_name + "」。" };
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
    const deleted = unwrap(await api.deleteEntry(conn.id, entry.path, false), "deleted");
    overlay.close();
    reportDeleted(deleted);
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
        const deleted = unwrap(await api.deleteEntry(conn.id, entry.path, true), "deleted");
        overlay.close();
        reportDeleted(deleted);
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

export function compressEntry(entry) {
  // 单行按钮与批量操作共用一套对话框：两种入口的默认值不同（单个时用条目名），
  // 但校验、请求与结果文案必须完全一致，否则同一件事会有两套说法。
  return compressEntries([entry]);
}

/* ---------------------------------------------------------------- 解压 */

export function extractEntry(entry) {
  // 同上：单个与批量走同一套对话框，响应形状的差异由 extractResult 统一处理。
  return extractEntries([entry]);
}

/* ---------------------------------------------------------------- 新建 */

/**
 * 名字校验：与后端 validate_remote_name 同一套规则。
 *
 * 前端先查一遍只是为了让提示出现在对话框里（服务端仍然会再查一次，绕不过去）。
 */
function nameProblem(raw) {
  const name = String(raw === null || raw === undefined ? "" : raw);
  if (name === "") return "名称不能为空。";
  if (name === "." || name === "..") return "名称不能是 . 或 ..。";
  if (name.indexOf("/") >= 0) return "名称里不能有 /：它必须是一个单独的名字，不能是路径。";
  if (name.indexOf(String.fromCharCode(0)) >= 0) return "名称里不能有空字符。";
  if (name.length > 255) return "名称太长（最多 255 个字符）。";
  return "";
}

/**
 * 新建文件 / 文件夹（v0.1.3 §4）。
 *
 * 两处刻意：
 * - **不做「先查有没有再建」**：那是一次多余往返，而且查完到建之间被抢占就会
 *   变成静默覆盖。这里直接建，同名交给服务端的排他创建去拒绝。
 * - **「建好了」与「列表刷新到了」分开报**：远端已经落地的事实不能因为一次刷新
 *   失败就说成「创建失败」，那会让人再建一次、得到同名的第二份。
 */
export async function createEntry(kind) {
  const conn = activeConnection();
  if (!conn || !guardWrite(conn)) return;
  const isDir = kind === "directory";
  const label = isDir ? "文件夹" : "文件";
  const directory = state.path;
  const input = h("input", {
    type: "text",
    class: "field-input",
    id: "create-name",
    value: "",
    maxlength: 255,
    placeholder: isDir ? "例如 notes" : "例如 notes.txt",
    "aria-label": "名称",
  });
  opDialog({
    title: "新建" + label,
    message: "在「" + directory + "」里新建" + label + "。",
    fields: [
      input,
      h("p", {
        class: "hint",
        text: isDir
          ? "创建后停在这个目录里，不会自动跳进去。同名条目会被拒绝，不会覆盖。"
          : "创建出来是一个 0 字节的空文件，可以马上用「编辑」写内容。同名条目会被拒绝，不会覆盖。",
      }),
    ],
    okText: "创建",
    okId: "btn-create-ok",
    statusId: "create-status",
    busyText: "正在创建…",
    failureText: "创建失败：",
    validate: function () {
      return nameProblem(input.value);
    },
    run: async function () {
      const entry = unwrap(await api.createEntry(conn.id, directory, input.value, kind), "entry");
      const done = "已创建" + (isDir ? "文件夹" : "空文件") + "「" + entry.name + "」。";
      try {
        await deps.refreshList();
      } catch (error) {
        return { silent: true, toast: done, warn: "列表没能刷新：" + describe(error) + " 请点「刷新」确认一下。" };
      }
      const listed = (state.entries || []).some(function (item) {
        return item.path === entry.path;
      });
      if (!listed) return { silent: true, toast: done, warn: "刷新后的列表里没找到它，请点「刷新」再确认一次。" };
      return { silent: true, toast: done };
    },
  });
}

/* ---------------------------------------------------------------- 复制 / 剪切 / 粘贴 */

/**
 * 复制与剪切都只是**在本地记下路径**：真正的字节搬运发生在粘贴时。
 *
 * 记 connectionId 是为了拦住跨连接粘贴 —— 那等于要求服务端在两台主机之间直接
 * 搬运，而现在的实现是「下载再上传」，跨连接不是一条请求能做的事。
 */
function rememberClipboard(mode, conn, list) {
  state.clipboard = {
    mode: mode,
    connectionId: conn.id,
    directory: parentOf(list[0].path),
    paths: list.map(function (entry) { return entry.path; }),
    names: list.map(function (entry) { return entry.name; }),
  };
  deps.onClipboardChange();
}

export function copyEntries(entries) {
  const conn = activeConnection();
  const list = (entries || []).filter(Boolean);
  if (!conn || !list.length) return;
  rememberClipboard("copy", conn, list);
  toastOk("已复制 " + list.length + " 项。进入目标目录后点「粘贴」。");
}

export function cutEntries(entries) {
  const conn = activeConnection();
  const list = (entries || []).filter(Boolean);
  if (!conn || !list.length || !guardWrite(conn)) return;
  rememberClipboard("cut", conn, list);
  toastOk("已剪切 " + list.length + " 项。进入目标目录后点「粘贴」即可移动。");
}

/** 复制/剪切的落地点：把剪贴板里的路径搬到当前目录。 */
export async function paste() {
  const conn = activeConnection();
  const clip = state.clipboard;
  if (!conn) {
    toastWarn("先连接一台远端主机，再粘贴。");
    return;
  }
  if (!clip) {
    toastWarn("剪贴板是空的：先在行上点「复制」或「剪切」。");
    return;
  }
  if (clip.connectionId !== conn.id) {
    toastWarn("这些条目来自另一条连接，不能跨连接粘贴。请切回那条连接，或先把文件下载下来。");
    return;
  }
  if (!guardWrite(conn)) return;
  const into = state.path;
  if (clip.mode === "cut" && into === clip.directory) {
    toastWarn("剪切的条目已经在这个目录里：先进入目标目录，再粘贴。");
    return;
  }
  const moving = clip.mode === "cut";
  const overlay = busyOverlay((moving ? "正在移动 " : "正在复制 ") + clip.paths.length + " 项…");
  try {
    if (moving) {
      const moved = unwrap(await api.moveEntries(conn.id, clip.paths, into), "move");
      state.clipboard = null;
      deps.onClipboardChange();
      overlay.close();
      toastOk("已移动 " + moved.count + " 项到「" + moved.destination + "」。");
      await deps.onChanged();
      return;
    }
    let copied;
    try {
      copied = unwrap(await api.copyEntries(conn.id, clip.paths, into, false), "copy");
    } catch (error) {
      const conflicts = (error && error.extra && error.extra.conflicts) || [];
      if (!error || error.code !== "invalid_request" || !conflicts.length) throw error;
      overlay.close();
      const names = conflicts
        .slice(0, 6)
        .map(function (item) {
          return String(item.source || item.target || "").split("/").pop();
        })
        .join("、");
      const more = conflicts.length > 6 ? " 等 " + conflicts.length + " 项" : "";
      const ok = await confirmDialog({
        title: "目标位置已经有同名条目",
        message: "「" + into + "」里已经有：" + names + more + "。要覆盖它们吗？",
        detail: "覆盖会用源条目的内容替换远端已有的同名文件或目录，无法撤销。",
        confirmText: "覆盖",
        danger: true,
      });
      if (!ok) return;
      copied = unwrap(await api.copyEntries(conn.id, clip.paths, into, true), "copy");
    }
    overlay.close();
    const skipped = (copied.skipped || []).length;
    let text =
      "已复制 " + copied.copied.length + " 项到「" + copied.destination + "」（" +
      copied.files + " 个文件、" + formatSize(copied.bytes) + "）";
    if (skipped) text += "，跳过 " + skipped + " 个符号链接";
    toastOk(text + "。");
    await deps.onChanged();
  } catch (error) {
    overlay.close();
    toastError(error);
  }
}

/* ---------------------------------------------------------------- 批量删除 / 压缩 / 解压 */

/** 批量动作中途失败时，先把「已经做成了什么」说清楚，再说失败原因。 */
function reportFailure(error, label) {
  const extra = (error && error.extra) || {};
  const done = Array.isArray(extra.done) ? extra.done : [];
  if (done.length) {
    toastWarn(
      label + "只完成了一部分：已处理 " + done.length + " 项，失败的路径是 " +
      extra.failed + "。" + describe(error)
    );
    return;
  }
  toastError(error);
}

export async function deleteEntries(entries) {
  const conn = activeConnection();
  const list = (entries || []).filter(Boolean);
  if (!conn || !list.length || !guardWrite(conn)) return;
  const paths = list.map(function (entry) { return entry.path; });
  const what = list.length === 1 ? "「" + list[0].name + "」" : list.length + " 个条目";
  const ok = await confirmDialog({
    title: "删除",
    message: "确定删除" + what + "吗？",
    detail: "远端没有回收站，删掉就找不回来了。目录会连同里面的内容一起删除。",
    confirmText: "删除",
    danger: true,
  });
  if (!ok) return;
  await runDeleteMany(conn, paths);
}

/** 两级确认里的第二级：目录非空时后端会先拒绝一次，这里再问一次。 */
async function runDeleteMany(conn, paths) {
  let overlay = busyOverlay("正在删除 " + paths.length + " 项…");
  try {
    const deleted = unwrap(await api.deleteEntry(conn.id, paths, false), "deleted");
    overlay.close();
    toastOk(deletedText(deleted));
    await deps.onChanged();
    return;
  } catch (error) {
    overlay.close();
    const extra = (error && error.extra) || {};
    if (!error || error.code !== "invalid_request" || !extra.entries) {
      reportFailure(error, "删除");
      return;
    }
    const done = Array.isArray(extra.done) ? extra.done : [];
    const again = await confirmDialog({
      title: "目录不是空的",
      message: "其中有目录里还留着 " + extra.entries + " 个条目。要连同里面的内容一起删除吗？",
      detail: (done.length ? "已经有 " + done.length + " 项删掉了。" : "") + "这一步之后无法撤销。",
      confirmText: "连同内容一起删除",
      danger: true,
    });
    if (!again) return;
    // 只重试还没删掉的：已成功的路径再删一次会变成「路径不存在」的假失败。
    const rest = paths.filter(function (path) { return done.indexOf(path) < 0; });
    const overlay2 = busyOverlay("正在删除 " + rest.length + " 项…");
    try {
      const deleted = unwrap(await api.deleteEntry(conn.id, rest, true), "deleted");
      overlay2.close();
      toastOk(deletedText(deleted));
      await deps.onChanged();
    } catch (error2) {
      overlay2.close();
      reportFailure(error2, "删除");
    }
  }
}

function deletedText(data) {
  let text = "已删除 " + data.count + " 项";
  if (data.directories) text += "（文件 " + data.files + " 个，目录 " + data.directories + " 个）";
  return text + "。";
}

/**
 * 批量压缩：一个压缩包装下所有选中的条目（后端就是这样实现的）。
 *
 * 放在哪、叫什么都要能改 —— 批量时默认名 archive.tar.gz 只是省一次输入，
 * 不是规则。
 */
export function compressEntries(entries) {
  const conn = activeConnection();
  const list = (entries || []).filter(Boolean);
  if (!conn || !list.length || !guardWrite(conn)) return;
  const single = list.length === 1;
  const paths = list.map(function (entry) { return entry.path; });
  const nameInput = h("input", {
    type: "text",
    class: "field-input",
    id: "compress-name",
    value: single ? list[0].name + ".tar.gz" : "archive.tar.gz",
    maxlength: 255,
    "aria-label": "压缩包名称",
  });
  const intoInput = h("input", {
    type: "text",
    class: "field-input",
    id: "compress-into",
    value: state.path,
    "aria-label": "压缩包放在哪个目录",
  });
  opDialog({
    title: "压缩",
    message: single
      ? "把「" + list[0].name + "」打包成 .tar.gz："
      : "把选中的 " + list.length + " 项一起打包成一个 .tar.gz：",
    fields: [
      h("p", { class: "field-label", text: "压缩包名称" }),
      nameInput,
      h("p", { class: "field-label", text: "放在哪个目录" }),
      intoInput,
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
      const problem = nameProblem(nameInput.value);
      if (problem) return problem;
      const into = intoInput.value.trim();
      if (!into) return "压缩包放在哪个目录不能为空。";
      if (into.charAt(0) !== "/") return "目录要写成绝对路径（以 / 开头）。";
      return "";
    },
    run: async function () {
      const archive = unwrap(
        await api.compressEntry(conn.id, paths, nameInput.value, intoInput.value.trim()),
        "archive"
      );
      const skipped = (archive.skipped || []).length;
      let text =
        "已生成「" + archive.name + "」（" + archive.entries + " 个条目，" + formatSize(archive.size) + "）";
      if ((archive.sources || []).length > 1) text += "，来源 " + archive.sources.length + " 项";
      if (skipped) text += "，跳过 " + skipped + " 个不支持的条目";
      return { toast: text + "。" };
    },
  });
}

/** 批量解压：只处理压缩包，混着普通文件时明确说「只解这几个」。 */
export async function extractEntries(entries) {
  const conn = activeConnection();
  const list = (entries || []).filter(Boolean);
  if (!conn || !list.length || !guardWrite(conn)) return;
  const archives = list.filter(canExtract);
  if (!archives.length) {
    toastWarn("选中的条目里没有压缩包（支持 .tar.gz / .tgz / .tar）。");
    return;
  }
  if (archives.length < list.length) {
    toastWarn("只解压其中的 " + archives.length + " 个压缩包，其它 " + (list.length - archives.length) + " 个条目会被忽略。");
  }
  const paths = archives.map(function (entry) { return entry.path; });
  const into = h("input", {
    type: "text",
    class: "field-input",
    id: "extract-into",
    value: archives.length === 1 ? parentOf(archives[0].path) : state.path,
    "aria-label": "解压到",
  });
  const overwrite = h("input", { type: "checkbox", id: "extract-overwrite" });
  opDialog({
    title: "解压",
    message:
      archives.length === 1
        ? "把「" + archives[0].name + "」解压到："
        : "把这 " + archives.length + " 个压缩包都解压到：",
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
      const result = unwrap(
        await api.extractEntry(conn.id, paths, into.value.trim(), overwrite.checked),
        "extract"
      );
      return extractResult(result);
    },
  });
}

/** 单包与多包的响应形状不同（多包多一层 archives 汇总），分开成文。 */
function extractResult(result) {
  if (result && Array.isArray(result.archives)) {
    let text = "已解压 " + result.count + " 个压缩包（" + result.files + " 个文件";
    if (result.directories) text += "、" + result.directories + " 个目录";
    text += "）。";
    if (result.stopped) return { warn: text + " 解压被上限中断：" + result.stopped };
    return { toast: text };
  }
  let text = "已解压 " + result.files + " 个文件";
  if (result.directories) text += "、建立 " + result.directories + " 个目录";
  if ((result.existing || []).length) text += "；跳过 " + result.existing.length + " 个已存在的条目";
  if ((result.skipped || []).length) text += "；跳过 " + result.skipped.length + " 个不支持或不安全的条目";
  text += "（目标 " + result.destination + "）。";
  if (result.stopped) return { warn: text + " 解压被上限中断：" + result.stopped };
  return { toast: text };
}

/** /home/aimu/a.tar.gz → /home/aimu；已经在根下的条目回落到 /。 */
function parentOf(path) {
  const trimmed = String(path || "").replace(/\/+$/, "");
  const index = trimmed.lastIndexOf("/");
  return index <= 0 ? "/" : trimmed.slice(0, index);
}
