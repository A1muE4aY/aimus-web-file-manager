/**
 * 在线虚拟机发现（v0.1.1 阶段五）。
 *
 * 这个模块只做三件事：把「本机能看见什么」画出来、把「用户要扫描 / 要中止」传回去、
 * 以及在用户挑中一台机器时把地址交给「新增连接」表单。最后一件是通过 app.js 注入的
 * 回调完成的 —— 模块之间不互相 import，这是本项目前端既定的分工。
 *
 * 三条纪律，来自决策 D-018 与 app/services/discovery.py：
 *
 * 1. **扫描结果只是候选。** 界面从不说「可以连」，只说「探测到了什么」；这里不自动
 *    创建连接，也不代替用户确认主机指纹。
 * 2. **三种状态分开说。** 「发现了虚拟机」「地址在线」「SSH 可用」是三件不同的事，
 *    混成一句话就会出现「列表说在线，点下去连不上」。
 * 3. **不做本地加减。** 条数、状态、进度一律取后端快照里的值；后端说「没探测」就显示
 *    「没探测」，不写成「离线」—— 探测超时也可能只是防火墙丢包。
 */

import * as api from "./api.js";
import { $, h, clear, formatTime } from "./util.js";
import { openModal, closeModal } from "./modal.js";
import { toastError, toastWarn } from "./toast.js";

const POLL_INTERVAL_MS = 600;

/** 阶段名取自后端 collect() 里的 stage() 调用，一个不多一个不少。 */
const STAGE_LABELS = {
  starting: "准备中",
  inventory: "读 VMware 清单",
  running: "问运行状态",
  vmx: "读虚拟机配置",
  leases: "读 DHCP 租约",
  neighbors: "查系统邻居表",
  probe: "探测地址",
  done: "已完成",
};

const STATUS_LABELS = {
  starting: "正在启动…",
  running: "扫描中…",
  done: "已完成",
  cancelled: "已中止",
  failed: "失败",
};

/** 来源的可用性（后端 sources[].state）。 */
const SOURCE_STATE_LABELS = {
  ok: "可用",
  empty: "没有内容",
  missing: "找不到文件",
  unavailable: "不可用",
  denied: "需要管理员权限",
  error: "读取出错",
};

/** 整台机器的汇总结论（后端 vms[].answer_state）。 */
const ANSWER_LABELS = {
  unknown_address: "没有地址",
  not_probed: "地址未探测",
  ssh_open: "SSH 可用",
  online: "地址在线",
  no_answer: "探测无响应",
};

/** 单个地址的探测原始结论（后端 addresses[].ssh_state）。与上面那张表不是一回事。 */
const SSH_STATE_LABELS = {
  open: "SSH 可用",
  refused: "在线，但没有 SSH",
  timeout: "无响应",
  unreachable: "不可达",
  not_probed: "未探测",
  error: "探测出错",
};

const SOURCE_LABELS = {
  guest: "客户机自报",
  neighbor: "系统邻居表",
  lease: "DHCP 租约",
  arp: "ARP 表",
  vmnet: "虚拟网段配置",
};

let deps = {
  /** 「创建连接」回调 (草稿)，由 app.js 转给 connections.openConnectionForm。 */
  onCreateConnection: function () {},
};

let environment = null; // GET /api/discovery 的结果
let envError = ""; // 读环境失败时的原因
let scan = null; // 最近一次扫描的后端快照（界面只认它）
let nodes = null; // 模态里那批节点的引用
let pollTimer = null;
let pollToken = 0;
let envToken = 0;

export function initDiscovery(hooks) {
  if (hooks) deps = Object.assign(deps, hooks);
  // 入口按钮由本模块自己绑：它只属于发现功能，不必让 app.js 转发。
  $("#btn-scan-vms").addEventListener("click", open);
}

/* -------------------------------------------------------------- 打开与关闭 */

export function open() {
  nodes = buildModal();
  openModal({
    title: "扫描本机虚拟机",
    body: nodes.body,
    buttons: [closeButton()],
    wide: true,
    onClose: handleClosed,
  });
  // 上一次的结果留在屏幕上（关掉再打开不该白扫一次），有环境信息就先画出来。
  if (scan) renderScan();
  else renderIdle();
  loadEnvironment();
  if (scan && scan.running) startPolling();
}

/** 关闭界面时把还在跑的扫描停掉。
 *
 * 后端同一时刻只允许一个扫描，留一个在后台跑会让下次「开始扫描」直接吃到 409，
 * 而用户看不见也停不掉它。这里不等结果：关窗不该卡住。
 */
function handleClosed() {
  stopPolling();
  if (scan && scan.running) {
    api.cancelDiscovery(scan.id).catch(function () {});
  }
}

function closeButton() {
  return h("button", {
    type: "button",
    class: "btn",
    text: "关闭",
    onClick: function () {
      closeModal("close");
    },
  });
}

/* ------------------------------------------------------------------ 骨架 */

function buildModal() {
  const start = h("button", {
    type: "button",
    class: "btn btn-small btn-primary",
    id: "btn-discovery-start",
    text: "开始扫描",
    onClick: startScan,
  });
  const cancel = h("button", {
    type: "button",
    class: "btn btn-small",
    id: "btn-discovery-cancel",
    text: "中止",
    hidden: true,
    onClick: stopScan,
  });
  const status = h("span", { class: "discovery-status", id: "discovery-status", "data-state": "idle", text: "还没有扫描" });
  const progress = h("span", { class: "discovery-progress", id: "discovery-progress" });
  const hint = h("p", { class: "discovery-hint", id: "discovery-hint", hidden: true });

  const envBody = h("div", { class: "discovery-env-body", id: "discovery-env-body" });
  const env = h(
    "details",
    { class: "discovery-env", id: "discovery-env" },
    h("summary", { text: "本机能读到的信息" }),
    envBody
  );

  const vmBody = h("tbody", { id: "discovery-vm-body" });
  const vms = h(
    "section",
    { class: "discovery-rows", id: "discovery-vms" },
    h("h3", { id: "discovery-vms-title", text: "发现的虚拟机" }),
    h(
      "div",
      { class: "discovery-table-wrap" },
      h(
        "table",
        { class: "file-table discovery-table" },
        h(
          "thead",
          {},
          h(
            "tr",
            {},
            h("th", { class: "col-name", scope: "col", text: "名称" }),
            h("th", { scope: "col", text: "状态" }),
            h("th", { scope: "col", text: "地址" }),
            h("th", { scope: "col", text: "能不能连" }),
            h("th", { class: "col-action", scope: "col", text: "操作" })
          )
        ),
        vmBody
      )
    ),
    h("p", { class: "discovery-empty", id: "discovery-vms-empty", hidden: true })
  );

  const onlineBody = h("tbody", { id: "discovery-online-body" });
  const online = otherSection("discovery-online", "另外在线的地址（没有 SSH）", onlineBody);

  const sshBody = h("tbody", { id: "discovery-ssh-body" });
  const ssh = otherSection("discovery-ssh", "另外可连 SSH 的地址", sshBody);

  const body = h(
    "div",
    { class: "discovery-body" },
    h("div", { class: "discovery-head" }, status, progress, h("span", { class: "discovery-head-right" }, start, cancel)),
    hint,
    env,
    vms,
    online,
    ssh,
    h("p", {
      class: "discovery-foot",
      text:
        "扫描只读本机 VMware 留下的信息，并对已知虚拟网段里的少量地址各做一次 SSH 端口探测；" +
        "它不会创建连接、不会记住主机指纹，也不会改动系统网络配置。结果只是候选地址。",
    })
  );

  return { body, start, cancel, status, progress, hint, env, envBody, vms, vmBody, online, onlineBody, ssh, sshBody };
}

/** 两张「其它地址」表结构相同，只有标题不同。 */
function otherSection(id, title, body) {
  const section = h(
    "section",
    { class: "discovery-rows", id: id, hidden: true },
    h("h3", { text: title }),
    h(
      "div",
      { class: "discovery-table-wrap" },
      h(
        "table",
        { class: "file-table discovery-table" },
        h(
          "thead",
          {},
          h(
            "tr",
            {},
            h("th", { class: "col-ip", scope: "col", text: "地址" }),
            h("th", { scope: "col", text: "来源" }),
            h("th", { scope: "col", text: "结论" }),
            h("th", { class: "col-action", scope: "col", text: "操作" })
          )
        ),
        body
      )
    )
  );
  return section;
}

/* -------------------------------------------------------------- 发起与轮询 */

async function startScan() {
  nodes.start.disabled = true;
  nodes.cancel.hidden = false;
  try {
    const data = await api.startDiscovery();
    apply(data && data.scan);
  } catch (error) {
    // 409（已经有一个在扫）之类的答复如实转达：这说明另一个页面或上一次没停干净，
    // 自己编一句话解释不如把后端的话原样给用户看。
    if (error && error.code === "discovery_busy") toastWarn(error.message);
    else toastError(error);
    if (scan) renderScan();
    else renderIdle();
    return;
  }
  startPolling();
}

function startPolling() {
  stopPolling();
  const token = ++pollToken;
  pollTimer = window.setInterval(function () {
    pollStatus(token);
  }, POLL_INTERVAL_MS);
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function pollStatus(token) {
  if (token !== pollToken || !scan || !scan.id) return;
  let data = null;
  try {
    data = await api.discoveryStatus(scan.id);
  } catch (error) {
    if (token !== pollToken) return;
    stopPolling();
    scan.status = "failed";
    scan.error = { message: error.message || "无法获取扫描进度。", detail: error.detail || "" };
    renderScan();
    return;
  }
  if (token !== pollToken) return;
  apply(data && data.scan);
}

/** 用户点「中止」：只是请求，状态要等后端下一次快照才算数。 */
async function stopScan() {
  if (!scan || !scan.id || !scan.running) return;
  try {
    await api.cancelDiscovery(scan.id);
  } catch (error) {
    toastWarn(error.message || "中止扫描失败。");
    return;
  }
  pollStatus(pollToken);
}

/** 把后端快照搬进前端状态。字段名一次映射完，别在渲染层再散着取。 */
function apply(snapshot) {
  if (!snapshot) return;
  scan = {
    id: snapshot.id || "",
    status: snapshot.status || "running",
    running: Boolean(snapshot.running),
    stage: snapshot.stage || "",
    startedAt: snapshot.started_at || null,
    durationSeconds: typeof snapshot.duration_seconds === "number" ? snapshot.duration_seconds : null,
    error: snapshot.error || null,
    vms: Array.isArray(snapshot.vms) ? snapshot.vms : [],
    addresses: Array.isArray(snapshot.addresses) ? snapshot.addresses : [],
    counts: snapshot.counts || {},
    probes: snapshot.probes || {},
    notes: Array.isArray(snapshot.notes) ? snapshot.notes : [],
    interrupted: Boolean(snapshot.interrupted),
    truncated: Boolean(snapshot.truncated),
    truncatedReason: snapshot.truncated_reason || "",
    limits: snapshot.limits || {},
  };
  if (!scan.running) stopPolling();
  renderScan();
}

/* ------------------------------------------------------------ 环境与来源 */

async function loadEnvironment() {
  const token = ++envToken;
  envError = "";
  renderEnvironment();
  try {
    const data = await api.discoveryEnvironment();
    if (token !== envToken) return;
    environment = (data && data.environment) || null;
  } catch (error) {
    if (token !== envToken) return;
    environment = null;
    envError = error.message || "读取失败。";
  }
  renderEnvironment();
  if (scan) renderScan();
  else renderIdle();
}

function renderEnvironment() {
  if (!nodes) return;
  const box = nodes.envBody;
  clear(box);
  if (envError) {
    box.appendChild(h("p", { class: "discovery-sub is-warn", text: "读取本机环境失败：" + envError }));
    return;
  }
  if (!environment) {
    box.appendChild(h("p", { class: "discovery-sub", text: "正在读取…" }));
    return;
  }

  const rows = [];
  for (const source of environment.sources || []) {
    rows.push(
      h(
        "tr",
        {},
        h("td", { text: source.label || source.name || "" }),
        h("td", { class: stateClass(source.state), text: SOURCE_STATE_LABELS[source.state] || source.state || "" }),
        h("td", { text: source.detail || "" })
      )
    );
  }
  box.appendChild(
    h(
      "table",
      { class: "discovery-sources" },
      h(
        "thead",
        {},
        h("tr", {}, h("th", { text: "来源" }), h("th", { text: "状态" }), h("th", { text: "说明" }))
      ),
      h("tbody", {}, rows)
    )
  );

  const limits = environment.limits || {};
  const limitBits = [
    "单地址超时 " + limits.probe_timeout_seconds + " 秒",
    "每网段最多 " + limits.max_addresses_per_subnet + " 个地址",
    "总共最多 " + limits.max_probes + " 个地址",
    "并发 " + limits.max_probe_workers,
    "总时限 " + limits.time_budget_seconds + " 秒",
  ];
  box.appendChild(h("p", { class: "discovery-sub", text: "探测上限：" + limitBits.join(" · ") }));
  if (limits.probe_ssh === false) {
    box.appendChild(h("p", { class: "discovery-sub is-warn", text: "配置里关掉了 SSH 端口探测，只会报告地址来自哪里。" }));
  }
  for (const note of environment.notes || []) {
    box.appendChild(h("p", { class: "discovery-sub is-warn", text: note }));
  }
}

function stateClass(state) {
  if (state === "ok" || state === "empty") return "is-ok";
  if (state === "unavailable" || state === "denied" || state === "error") return "is-warn";
  return "is-dim";
}

/* ------------------------------------------------------------------ 渲染 */

function renderIdle() {
  if (!nodes) return;
  setStatus("idle", "还没有扫描");
  nodes.progress.textContent = "";
  nodes.start.disabled = Boolean(environment && environment.enabled === false);
  nodes.start.textContent = "开始扫描";
  nodes.cancel.hidden = true;
  showHint(
    environment && environment.enabled === false ? "warn" : "info",
    environment && environment.enabled === false
      ? "在线虚拟机发现在配置里是关闭的（discovery.enabled）。把配置改成 true 并重启程序后再来。"
      : "点「开始扫描」：工具会读本机 VMware 的清单、虚拟机配置、DHCP 租约与系统邻居表，" +
        "再对已知虚拟网段里的一小批地址各做一次 SSH 端口探测。"
  );
  nodes.vms.hidden = true;
  nodes.online.hidden = true;
  nodes.ssh.hidden = true;
}

function renderScan() {
  if (!nodes || !scan) return;
  const running = scan.running;
  nodes.start.disabled = running || Boolean(environment && environment.enabled === false);
  nodes.start.textContent = running ? "扫描中…" : "重新扫描";
  nodes.cancel.hidden = !running;
  setStatus(scan.status, STATUS_LABELS[scan.status] || scan.status);
  nodes.progress.textContent = progressText();

  const hint = hintFor();
  if (hint) showHint(hint.kind, hint.text);
  else nodes.hint.hidden = true;

  renderVms();
  renderOthers();
}

function setStatus(state, text) {
  nodes.status.setAttribute("data-state", state);
  nodes.status.textContent = text;
}

function showHint(kind, text) {
  nodes.hint.hidden = false;
  nodes.hint.setAttribute("data-kind", kind);
  nodes.hint.textContent = text;
}

function progressText() {
  const parts = [];
  if (scan.running) {
    parts.push("阶段：" + (STAGE_LABELS[scan.stage] || scan.stage || "准备中"));
    if (scan.startedAt) parts.push("开始于 " + formatTime(scan.startedAt));
    return parts.join(" · ");
  }
  const counts = scan.counts || {};
  if (typeof counts.vms === "number") {
    parts.push("虚拟机 " + counts.vms + " 台（运行中 " + (counts.running || 0) + "）");
  }
  const probes = scan.probes || {};
  if (probes.planned) {
    parts.push("探测 " + (probes.done || 0) + "/" + probes.planned + " 个地址，其中 " + (probes.open || 0) + " 个能连 SSH");
  }
  if (typeof scan.durationSeconds === "number") parts.push("用时 " + scan.durationSeconds.toFixed(1) + " 秒");
  return parts.join(" · ");
}

/**
 * 顶上那一段说明。
 *
 * 失败、被中止、没有发现、被上限截断是四种不同情况，混成一句「没有结果」会让用户
 * 以为机器不存在，而实际上可能只是没探测到或被取消。
 */
function hintFor() {
  if (scan.status === "failed") {
    const error = scan.error || {};
    return {
      kind: "error",
      text: "扫描失败：" + (error.message || "未知原因") + (error.detail ? "（" + error.detail + "）" : ""),
    };
  }
  if (scan.running) return null;

  const notes = (scan.notes || []).slice();
  if (scan.truncated && scan.truncatedReason && notes.indexOf(scan.truncatedReason) < 0) {
    notes.push(scan.truncatedReason);
  }
  const counts = scan.counts || {};
  const others = scan.addresses || [];
  const probedOthers = others.filter(function (item) {
    return item.probed && !item.responded;
  }).length;
  if (probedOthers > 0) {
    notes.push("另有 " + probedOthers + " 个已知网段里的地址探测无响应 —— 这不代表那台机器关机。");
  }

  if (scan.status === "cancelled" || scan.interrupted) {
    return {
      kind: "warn",
      text: "扫描已中止，下面是中止前已经拿到的部分。" + (notes.length ? " " + notes.join(" ") : ""),
    };
  }
  if (!counts.vms && !others.length) {
    return {
      kind: "warn",
      text:
        "没有从 VMware 的清单里找到虚拟机，也没有发现其它在线地址。" +
        (notes.length ? " " + notes.join(" ") : "") +
        " 请确认这台机器上确实装了 VMware 并至少建过一台虚拟机。",
    };
  }
  if (notes.length) return { kind: "warn", text: notes.join(" ") };
  return null;
}

function renderVms() {
  const body = nodes.vmBody;
  clear(body);
  const vms = scan.vms || [];
  nodes.vms.hidden = false;
  nodes.vms.querySelector("h3").textContent = "发现的虚拟机（" + vms.length + " 台）";
  const empty = nodes.vms.querySelector(".discovery-empty");
  empty.hidden = vms.length > 0;
  if (!vms.length) {
    empty.textContent = "没有从 VMware 的清单里找到虚拟机。";
    return;
  }
  for (const vm of vms) body.appendChild(vmRow(vm));
}

function vmRow(vm) {
  const row = h("tr", { "data-vm": vm.name || "" });

  // 名称：下面挂一行次要信息，以及后端给出的每台机器的说明（例如配置文件不在磁盘上）。
  const nameCell = h("td", { class: "col-name" });
  nameCell.appendChild(h("div", { class: "discovery-name", text: vm.name || "（没有名字）" }));
  const bits = [];
  if (vm.guest_os) bits.push(vm.guest_os);
  if (vm.cpus) bits.push(vm.cpus + " 核");
  if (vm.memory_mb) bits.push(Math.round(vm.memory_mb / 1024) + " GiB 内存");
  if (bits.length) nameCell.appendChild(h("div", { class: "discovery-sub", text: bits.join(" · ") }));
  for (const note of vm.notes || []) {
    nameCell.appendChild(h("div", { class: "discovery-sub is-warn", text: note }));
  }
  row.appendChild(nameCell);

  // 运行状态：vmrun 说不出话时是「未知」，不能写成「已关机」。
  const stateCell = h("td", {});
  stateCell.appendChild(h("div", { text: runStateLabel(vm.state) }));
  if (vm.state === "unknown") {
    stateCell.appendChild(h("div", { class: "discovery-sub", text: "读不到运行状态" }));
  } else if (vm.running_source) {
    stateCell.appendChild(h("div", { class: "discovery-sub", text: "来源：" + vm.running_source }));
  }
  row.appendChild(stateCell);

  // 地址：主地址 + 其它线索地址（例如同 MAC 的过期租约）。
  const addrCell = h("td", { class: "col-ip" });
  if (vm.ip) {
    addrCell.appendChild(h("div", { class: "discovery-ip", text: vm.ip + (vm.ssh_port ? ":" + vm.ssh_port : "") }));
    addrCell.appendChild(h("div", { class: "discovery-sub", text: "来源：" + sourceLabel(vm.ip_source) }));
  } else {
    addrCell.appendChild(h("div", { class: "discovery-sub", text: "没有地址" }));
  }
  const others = (vm.addresses || []).filter(function (item) {
    return item.ip !== vm.ip;
  });
  if (others.length) {
    addrCell.appendChild(
      h("div", {
        class: "discovery-sub",
        text:
          "其它线索：" +
          others
            .map(function (item) {
              return item.ip + "（" + (SSH_STATE_LABELS[item.ssh_state] || item.ssh_state) + "）";
            })
            .join("、"),
      })
    );
  }
  row.appendChild(addrCell);

  // 能不能连：说结论，也说结论是怎么来的。
  const answerCell = h("td", {});
  answerCell.appendChild(
    h("span", {
      class: "discovery-answer",
      "data-state": vm.answer_state || "",
      text: ANSWER_LABELS[vm.answer_state] || vm.answer_state || "—",
    })
  );
  if (vm.ssh_open === false) {
    answerCell.appendChild(h("div", { class: "discovery-sub", text: "探测没连上 SSH，也可以新建连接再试一次。" }));
  } else if (vm.ssh_open === null || vm.ssh_open === undefined) {
    answerCell.appendChild(h("div", { class: "discovery-sub", text: "这个地址没有被探测过。" }));
  }
  row.appendChild(answerCell);

  const action = h("td", { class: "col-action" });
  if (vm.ip) {
    action.appendChild(
      createButton({ ip: vm.ip, port: vm.ssh_port || 22, name: vm.name || "", source: vm.ip_source || "" })
    );
  }
  row.appendChild(action);
  return row;
}

function runStateLabel(state) {
  if (state === "running") return "运行中";
  if (state === "stopped") return "已关机";
  return "未知";
}

function renderOthers() {
  // 两张表互斥：一张是「活着但没有 SSH」，另一张是「能连 SSH」，不会同一条出现两次。
  const others = scan.addresses || [];
  const online = others.filter(function (item) {
    return item.responded === true && item.ssh_open !== true;
  });
  const ssh = others.filter(function (item) {
    return item.ssh_open === true;
  });
  fillOtherSection(nodes.online, nodes.onlineBody, online, "另外在线的地址（没有 SSH）");
  fillOtherSection(nodes.ssh, nodes.sshBody, ssh, "另外可连 SSH 的地址");
}

function fillOtherSection(section, body, list, title) {
  clear(body);
  section.hidden = list.length === 0;
  if (!list.length) return;
  section.querySelector("h3").textContent = title + "（" + list.length + " 个）";
  for (const item of list) body.appendChild(otherAddressRow(item));
}

function otherAddressRow(entry) {
  const row = h("tr", { "data-ip": entry.ip });

  const ipCell = h("td", { class: "col-ip" });
  ipCell.appendChild(h("div", { class: "discovery-ip", text: entry.ip + (entry.port ? ":" + entry.port : "") }));
  if (entry.mac) ipCell.appendChild(h("div", { class: "discovery-sub", text: entry.mac }));
  row.appendChild(ipCell);

  const sourceCell = h("td", {});
  sourceCell.appendChild(h("div", { text: sourceLabel(entry.source) }));
  if (entry.subnet) sourceCell.appendChild(h("div", { class: "discovery-sub", text: entry.subnet }));
  row.appendChild(sourceCell);

  const stateCell = h("td", {});
  stateCell.appendChild(h("div", { text: SSH_STATE_LABELS[entry.ssh_state] || entry.ssh_state || "—" }));
  if (typeof entry.elapsed_ms === "number") {
    stateCell.appendChild(h("div", { class: "discovery-sub", text: entry.elapsed_ms + " ms" }));
  }
  row.appendChild(stateCell);

  const action = h("td", { class: "col-action" });
  action.appendChild(createButton({ ip: entry.ip, port: entry.port || 22, name: "", source: entry.source || "" }));
  row.appendChild(action);
  return row;
}

/* ---------------------------------------------------------- 创建连接（候选） */

/** 「创建连接」只把地址填进表单 —— 不保存、不连接、不信任指纹，最后一步永远由用户点。 */
function createButton(item) {
  const button = h("button", { type: "button", class: "btn btn-small", text: "创建连接", "data-ip": item.ip });
  button.addEventListener("click", function () {
    const draft = {
      name: item.name || item.ip,
      host: item.ip,
      port: item.port || 22,
      username: "",
      auth_method: "key",
      identity_file: "",
      note: noteFor(item),
      allow_write: false,
    };
    closeModal("create-connection");
    deps.onCreateConnection(draft);
  });
  return button;
}

function noteFor(item) {
  const where = item.name ? "虚拟机「" + item.name + "」" : "扫描结果里的地址";
  const source = sourceLabel(item.source);
  return (
    "由「扫描本机虚拟机」发现（" + where + (source ? "，" + source : "") + "）。连接前请核对主机指纹。"
  ).slice(0, 200);
}

function sourceLabel(source) {
  return SOURCE_LABELS[source] || source || "来源不详";
}
