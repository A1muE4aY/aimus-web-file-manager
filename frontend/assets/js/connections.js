/**
 * 连接列表、连接表单、主机密钥确认。
 *
 * 关于主机密钥：这是本项目「不静默」原则最要紧的地方。
 * 首次连接某主机时，ssh 自己会拒绝（StrictHostKeyChecking=strict），
 * 后端把采集到的指纹作为结构化错误返回，由用户核对后点「信任」才写入
 * 项目自己的 known_hosts。密钥变化时**不提供**一键接受 ——
 * 那既可能是目标机被重装，也可能是有人在中间转发，只有人能分辨。
 */

import * as api from "./api.js";
import { $, h, clear, formatTime } from "./util.js";
import { toast, toastOk, toastError, toastWarn } from "./toast.js";
import { confirmDialog, openModal, closeModal, infoDialog } from "./modal.js";
import { state, connectionById, isConnected } from "./state.js";

let deps = { onEnter: function () {}, onLeave: function () {} };

export function initConnections(hooks) {
  if (hooks) deps = Object.assign(deps, hooks);
}

const STATE_TEXT = {
  connected: "已连接",
  connecting: "连接中",
  error: "连接出错",
  disconnected: "未连接",
};

export function stateText(name) {
  return STATE_TEXT[name] || name || "未连接";
}

export async function refreshConnections() {
  const data = await api.listConnections();
  // 后端返回的是 {"connections": [...]}，必须取内层数组 —— 直接把外层对象
  // 当数组用会让侧栏永远为空（e2e 首跑就是这么发现的）。
  state.connections = data && Array.isArray(data.connections) ? data.connections : [];
  renderSidebar();
  return state.connections;
}

export function renderSidebar() {
  const list = $("#conn-list");
  clear(list);
  $("#conn-empty").hidden = state.connections.length > 0;
  for (const item of state.connections) list.appendChild(connectionNode(item));
}

function targetLabel(item) {
  const host = item.host || "";
  const port = item.port || 22;
  const user = item.username || "";
  const address = host.indexOf(":") >= 0 ? "[" + host + "]:" + port : host + ":" + port;
  return user ? user + "@" + address : address;
}

function connectionNode(item) {
  const session = item.session || {};
  const connected = Boolean(session.connected);
  const connecting = session.state === "connecting";
  const node = h("li", {
    class: "conn-item",
    "data-id": item.id,
    "data-active": state.activeId === item.id ? "true" : "false",
    "data-state": session.state || "disconnected",
  });

  node.appendChild(
    h(
      "div",
      { class: "conn-item-head" },
      h("span", { class: "conn-name", text: item.name || item.id, title: item.name || item.id }),
      h(
        "span",
        { class: "pill", "data-state": session.state || "disconnected" },
        h("span", { class: "dot" }),
        stateText(session.state)
      )
    )
  );
  node.appendChild(h("div", { class: "conn-target", text: targetLabel(item) }));

  const meta = h("div", { class: "conn-meta" });
  meta.appendChild(
    h("span", { class: "tag", text: item.auth_method === "password" ? "密码认证" : "密钥认证" })
  );
  if (item.allow_write) meta.appendChild(h("span", { class: "tag tag-warn", text: "允许写" }));
  if (connected && session.home) {
    meta.appendChild(h("span", { class: "tag", text: "家目录 " + session.home }));
  }
  node.appendChild(meta);

  if (session.last_error) {
    node.appendChild(h("div", { class: "conn-note broken", text: session.last_error }));
  } else if (item.note) {
    node.appendChild(h("div", { class: "conn-note", text: item.note }));
  }

  const actions = h("div", { class: "conn-actions" });
  if (connected) {
    actions.appendChild(
      h("button", {
        type: "button",
        class: "btn btn-small",
        text: "浏览",
        onClick: function (event) {
          event.stopPropagation();
          openConnection(item.id);
        },
      })
    );
    actions.appendChild(
      h("button", {
        type: "button",
        class: "btn btn-small",
        text: "断开",
        onClick: function (event) {
          event.stopPropagation();
          doDisconnect(item.id);
        },
      })
    );
  } else {
    actions.appendChild(
      h("button", {
        type: "button",
        class: "btn btn-small btn-primary",
        text: connecting ? "连接中…" : "连接",
        disabled: connecting,
        onClick: function (event) {
          event.stopPropagation();
          connectFlow(item.id);
        },
      })
    );
  }
  actions.appendChild(
    h("button", {
      type: "button",
      class: "btn btn-small",
      text: "编辑",
      onClick: function (event) {
        event.stopPropagation();
        openConnectionForm(item);
      },
    })
  );
  actions.appendChild(
    h("button", {
      type: "button",
      class: "btn btn-small btn-danger",
      text: "删除",
      onClick: function (event) {
        event.stopPropagation();
        doDelete(item);
      },
    })
  );
  node.appendChild(actions);

  node.addEventListener("click", function () {
    if (connected) openConnection(item.id);
    else connectFlow(item.id);
  });
  return node;
}

export function openConnection(id) {
  state.activeId = id;
  renderSidebar();
  deps.onEnter(id);
}

export async function doDisconnect(id) {
  try {
    await api.disconnect(id);
    toastOk("已断开连接。");
  } catch (error) {
    toastError(error);
  }
  if (state.activeId === id) {
    state.activeId = null;
    deps.onLeave();
  }
  await refreshConnections();
}

async function doDelete(item) {
  const ok = await confirmDialog({
    title: "删除连接配置",
    message: "要删除连接「" + (item.name || item.id) + "」吗？",
    detail: "这会从本地配置文件里移除这条记录。远端机器上的文件不会有任何变化。",
    confirmText: "删除",
    danger: true,
  });
  if (!ok) return;
  try {
    await api.deleteConnection(item.id);
    if (state.activeId === item.id) {
      state.activeId = null;
      deps.onLeave();
    }
    await refreshConnections();
    toastOk("已删除连接。");
  } catch (error) {
    toastError(error);
  }
}

/** 需要密码就先问，再连。返回是否连上。 */
export async function connectFlow(id) {
  const item = connectionById(id);
  if (!item) return false;
  let password = "";
  if (item.auth_method === "password") {
    password = await askPassword(item);
    if (password === null) return false;
  }
  return doConnect(id, password);
}

export async function doConnect(id, password) {
  const item = connectionById(id);
  try {
    await api.connect(id, password);
  } catch (error) {
    await refreshConnections();
    if (error.code === "host_key_unknown") {
      const trusted = await confirmUnknownHostKey(id, error, item);
      if (trusted) return doConnect(id, password);
      return false;
    }
    if (error.code === "host_key_mismatch") {
      showHostKeyMismatch(error, item);
      return false;
    }
    if (error.code === "auth_failed" && item && item.auth_method === "password") {
      toastError(error);
      // 密码错一次不值得让用户重新点一遍「连接」。
      const again = await askPassword(item, "认证失败，请重新输入密码。");
      if (again === null) return false;
      return doConnect(id, again);
    }
    toastError(error);
    return false;
  }
  toastOk("已连接到 " + targetLabel(item));
  // 必须先刷新连接列表再进入连接：进入时要用刚连上的 session.home，
  // 顺序反了就会拿旧的空 session 去 loadDirectory，界面落到根目录 "/"。
  await refreshConnections();
  openConnection(id);
  return true;
}

/* ------------------------------------------------------------ 密码对话框 */

function askPassword(item, note) {
  return new Promise(function (resolve) {
    let settled = false;
    function finish(value) {
      if (settled) return;
      settled = true;
      resolve(value);
    }

    const input = h("input", { type: "password", id: "conn-password", autocomplete: "off" });
    const error = h("div", { class: "form-error", hidden: true });
    const body = h(
      "div",
      {},
      h(
        "p",
        {
          class: "hint",
          text:
            (note ? note + " " : "") +
            "密码只用于这一次连接，不会写入配置文件；断开连接后需要重新输入。",
        }
      ),
      h("div", { class: "field" }, h("label", { for: "conn-password", text: "登录密码" }), input),
      error
    );

    function submit() {
      const value = input.value;
      if (!value) {
        error.textContent = "请输入密码。";
        error.hidden = false;
        return;
      }
      finish(value);
      closeModal("submit");
    }

    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        submit();
      }
    });

    const cancel = h("button", {
      type: "button",
      class: "btn",
      text: "取消",
      onClick: function () {
        finish(null);
        closeModal("cancel");
      },
    });
    const ok = h("button", { type: "button", class: "btn btn-primary", text: "连接", onClick: submit });

    openModal({
      title: "输入 " + targetLabel(item) + " 的密码",
      body: body,
      buttons: [cancel, ok],
      onClose: function () {
        finish(null);
      },
    });
    input.focus();
  });
}

/* -------------------------------------------------------- 主机密钥确认 */

function fingerprintList(keys, className) {
  const box = h("div", {});
  for (const key of keys || []) {
    box.appendChild(
      h(
        "div",
        { class: "fingerprint " + (className || "") },
        h("span", { class: "fp-type", text: key.key_type || "未知类型" }),
        h("span", { class: "fp-value", text: key.fingerprint || "" })
      )
    );
  }
  if (!keys || keys.length === 0) box.appendChild(h("p", { class: "hint", text: "（没有采集到指纹）" }));
  return box;
}

function confirmUnknownHostKey(id, error, item) {
  const keys = error.extra && Array.isArray(error.extra.fingerprints) ? error.extra.fingerprints : [];
  return new Promise(function (resolve) {
    let settled = false;
    function finish(value) {
      if (settled) return;
      settled = true;
      resolve(value);
    }

    const body = h(
      "div",
      {},
      h("p", {
        text:
          "这是第一次连接 " +
          targetLabel(item) +
          "。SSH 用主机密钥确认「你连上的确实是那台机器」，而不是中间转发的人。",
      }),
      h("p", {
        class: "hint",
        text: "请核对下面的指纹与目标机上的输出是否一致（在目标机上执行）：",
      }),
      h("p", { class: "hint" }, h("code", { text: "ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub" })),
      fingerprintList(keys),
      h("p", {
        class: "hint",
        text: "如果指纹对不上，说明中间可能有其他人，请选「取消」。",
      })
    );

    const cancel = h("button", {
      type: "button",
      class: "btn",
      text: "取消",
      onClick: function () {
        finish(false);
        closeModal("cancel");
      },
    });
    const trust = h("button", {
      type: "button",
      class: "btn btn-primary",
      text: "指纹一致，信任并继续",
      onClick: async function () {
        trust.disabled = true;
        try {
          if (keys.length === 0) throw new Error("没有可信任的指纹。");
          // 只信任 ssh 自己首选的第一个密钥：真正建连时它会用同一把。
          await api.trustHostKey(id, keys[0].key_type, keys[0].fingerprint);
          toastOk("已记录主机密钥。");
          finish(true);
          closeModal("trust");
        } catch (err) {
          toastError(err);
          trust.disabled = false;
        }
      },
    });

    openModal({
      title: "首次连接，请核对主机指纹",
      body: body,
      buttons: [cancel, trust],
      onClose: function () {
        finish(false);
      },
    });
  });
}

function knownHostsHint() {
  const path = state.session && state.session.known_hosts_path ? state.session.known_hosts_path : "data/known_hosts";
  return path;
}

function showHostKeyMismatch(error, item) {
  const extra = error.extra || {};
  const body = h(
    "div",
    {},
    h("p", {
      text:
        "目标机 " + targetLabel(item) + " 提供的主机密钥与本地记录的不一致。",
    }),
    h("p", { class: "hint", text: "本地已记录的指纹：" }),
    fingerprintList(extra.trusted_fingerprints),
    h("p", { class: "hint", text: "目标机现在提供的指纹：" }),
    fingerprintList(extra.current_fingerprints, "is-warn"),
    h("p", {
      text: "目标机被重装或换过密钥会出现这种情况；有人在中间转发也会。",
    }),
    h("p", {
      class: "hint",
      text:
        "本工具不会自动接受新密钥，也不会替你删除旧记录。确认目标机确实换过密钥后，" +
        "请手工编辑 " +
        knownHostsHint() +
        "，删掉该主机对应的行，再重新连接。",
    })
  );
  infoDialog("主机密钥发生变化", body);
}

/* ------------------------------------------------------------ 连接表单 */

export function openConnectionForm(existing) {
  const editing = Boolean(existing);
  const item = existing || {
    name: "",
    host: "",
    port: 22,
    username: "",
    auth_method: "key",
    identity_file: "",
    note: "",
    allow_write: false,
  };

  function field(label, input, hint, required) {
    return h(
      "div",
      { class: "field" },
      h("label", {}, label, required ? h("span", { class: "req", text: " *" }) : null),
      input,
      hint ? h("div", { class: "hint", text: hint }) : null
    );
  }

  const inputName = h("input", { type: "text", value: item.name || "", maxlength: "80" });
  const inputHost = h("input", { type: "text", value: item.host || "", required: "required", autocomplete: "off" });
  const inputPort = h("input", { type: "number", value: String(item.port || 22), min: "1", max: "65535" });
  const inputUser = h("input", { type: "text", value: item.username || "", autocomplete: "off" });
  const selectAuth = h(
    "select",
    {},
    h("option", { value: "key", text: "密钥（推荐）", selected: item.auth_method !== "password" }),
    h("option", { value: "password", text: "密码", selected: item.auth_method === "password" })
  );
  const inputKey = h("input", {
    type: "text",
    value: item.identity_file || "",
    autocomplete: "off",
    placeholder: "留空表示用 ssh-agent 或默认密钥",
  });
  const keyField = field(
    "私钥文件",
    inputKey,
    "可留空：留空时用 ssh-agent 里已加载的密钥，或 ~/.ssh 下的默认密钥。私钥始终只在本机使用，不会发送到浏览器。"
  );
  const inputNote = h("input", { type: "text", value: item.note || "", maxlength: "200" });
  const checkWrite = h("input", { type: "checkbox", checked: Boolean(item.allow_write) });
  const error = h("div", { class: "form-error", hidden: true });

  function syncAuth() {
    keyField.hidden = selectAuth.value !== "key";
  }
  selectAuth.addEventListener("change", syncAuth);
  syncAuth();

  const body = h(
    "div",
    {},
    error,
    field("名称", inputName, "留空则自动用「用户名@主机」作为名称。"),
    h(
      "div",
      { class: "field-row" },
      field("主机", inputHost, "IP 或域名。", true),
      h("div", { class: "field grow-0" }, h("label", {}, "端口"), inputPort)
    ),
    field("用户名", inputUser, "留空表示用当前本机用户名（一般在 Windows 上你不会想留空）。"),
    field("认证方式", selectAuth, "密码不会写入配置文件，每次连接时输入。"),
    keyField,
    field("备注", inputNote),
    h(
      "div",
      { class: "field" },
      h(
        "label",
        { class: "check" },
        checkWrite,
        h("span", { text: "允许对该连接执行写操作（上传 / 覆盖）" })
      ),
      h("div", {
        class: "hint",
        text: "默认关闭。关闭时后端会拒绝一切写请求，界面上也不会给出写入入口。",
      })
    )
  );

  async function submit() {
    error.hidden = true;
    const payload = {
      name: inputName.value.trim(),
      host: inputHost.value.trim(),
      port: Number(inputPort.value || 22),
      username: inputUser.value.trim(),
      auth_method: selectAuth.value,
      identity_file: inputKey.value.trim(),
      note: inputNote.value.trim(),
      allow_write: checkWrite.checked,
    };
    if (!payload.host) {
      error.textContent = "请填写主机地址。";
      error.hidden = false;
      return;
    }
    try {
      if (editing) {
        await api.updateConnection(existing.id, payload);
        toastOk("已保存连接配置。");
      } else {
        const created = await api.createConnection(payload);
        toastOk("已新增连接。");
        if (created && created.connection && created.connection.id) state.activeId = null;
      }
      closeModal("saved");
      await refreshConnections();
    } catch (err) {
      error.textContent = err.message + (err.detail ? "（" + err.detail + "）" : "");
      error.hidden = false;
    }
  }

  const cancel = h("button", {
    type: "button",
    class: "btn",
    text: "取消",
    onClick: function () {
      closeModal("cancel");
    },
  });
  const save = h("button", { type: "button", class: "btn btn-primary", text: editing ? "保存" : "新增", onClick: submit });

  openModal({
    title: editing ? "编辑连接" : "新增连接",
    body: body,
    buttons: [cancel, save],
  });
  inputHost.focus();
}
