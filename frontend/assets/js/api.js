/**
 * 后端 API 客户端。
 *
 * 所有请求都带 `X-AWFM-Token`（会话令牌由后端注入到 index.html 的 meta 里）。
 * 这个头同时是我们最主要的 CSRF 防线：攻击者的页面既读不到我们的 HTML，
 * 也就拿不到令牌值；而它一旦想自定义这个头，浏览器就会先发预检，
 * 而后端的 OPTIONS 一律拒绝（见 app/api/security.py 的注释）。
 */

export const TOKEN = readMeta("awfm-token");
export const SERVER_VERSION = readMeta("awfm-version") || "unknown";

function readMeta(name) {
  const node = document.querySelector('meta[name="' + name + '"]');
  return node ? node.getAttribute("content") || "" : "";
}

/** 后端把错误统一成 {ok:false, error:{code,message,detail}}，这里还原成异常。 */
export class ApiError extends Error {
  constructor(code, message, detail, status, extra) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.detail = detail || "";
    this.status = status || 0;
    // 后端错误对象里的附加字段原样保留：主机密钥未知时，待确认的指纹
    // 就在 error.fingerprints 里，前端要拿它来显示给用户。
    this.extra = extra || {};
  }
}

async function readBody(response) {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new ApiError(
      "bad_response",
      "后端返回的不是合法 JSON（HTTP " + response.status + "）。",
      text.slice(0, 500),
      response.status
    );
  }
}

async function request(method, path, options) {
  const opts = options || {};
  const headers = {};
  if (TOKEN) headers["X-AWFM-Token"] = TOKEN;
  let body;
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    // 循环引用之类的问题在 JSON.stringify 时就暴露，不要等到 fetch 报网络错。
    body = JSON.stringify(opts.body);
  }
  const response = await fetch(path, {
    method: method,
    headers: headers,
    body: body,
    signal: opts.signal,
    credentials: "same-origin",
    cache: "no-store",
  });
  const payload = await readBody(response);
  if (!response.ok || !payload || payload.ok !== true) {
    const err = (payload && payload.error) || {};
    throw new ApiError(
      err.code || "http_" + response.status,
      err.message || "请求失败（HTTP " + response.status + "）。",
      err.detail,
      response.status,
      err
    );
  }
  return payload.data;
}

function qs(value) {
  return encodeURIComponent(value);
}

export function health() {
  return request("GET", "/api/health");
}

export function sessionInfo() {
  return request("GET", "/api/session");
}

export function listConnections() {
  return request("GET", "/api/connections");
}

export function createConnection(payload) {
  return request("POST", "/api/connections", { body: payload });
}

export function updateConnection(id, payload) {
  return request("PATCH", "/api/connections/" + qs(id), { body: payload });
}

export function deleteConnection(id) {
  return request("DELETE", "/api/connections/" + qs(id));
}

export function connect(id, password) {
  const body = {};
  if (password) body.password = password;
  return request("POST", "/api/connections/" + qs(id) + "/connect", { body: body });
}

export function disconnect(id) {
  return request("POST", "/api/connections/" + qs(id) + "/disconnect");
}

export function status(id) {
  return request("GET", "/api/connections/" + qs(id) + "/status");
}

export function hostKeys(id) {
  return request("GET", "/api/connections/" + qs(id) + "/host-keys");
}

export function trustHostKey(id, keyType, fingerprint) {
  return request("POST", "/api/connections/" + qs(id) + "/host-keys/trust", {
    body: { key_type: keyType, fingerprint: fingerprint },
  });
}

export function listFiles(id, path) {
  return request("GET", "/api/connections/" + qs(id) + "/files?path=" + qs(path));
}

export function statFile(id, path, follow) {
  const suffix = follow === false ? "&follow=0" : "";
  return request("GET", "/api/connections/" + qs(id) + "/stat?path=" + qs(path) + suffix);
}

export function previewFile(id, path, maxBytes) {
  let url = "/api/connections/" + qs(id) + "/preview?path=" + qs(path);
  if (maxBytes) url += "&max_bytes=" + qs(String(maxBytes));
  return request("GET", url);
}

/**
 * 发起一次远端检索。
 *
 * 搜索在服务端跑（SFTP 连接只在后端），这里拿到的是**初始快照**，之后按
 * /api/searches/<id> 轮询进度。后端用 202 表示「已受理」，所以不能把它当成
 * 「已经搜完」。
 */
export function startSearch(id, path, query) {
  return request("POST", "/api/connections/" + qs(id) + "/search", {
    body: { path: path, query: query },
  });
}

export function searchStatus(searchId) {
  return request("GET", "/api/searches/" + qs(searchId));
}

export function cancelSearch(searchId) {
  return request("DELETE", "/api/searches/" + qs(searchId));
}

/* ------------------------------------------- 在线编辑与文件操作（v0.1.1 阶段四） */

/**
 * 读取一个远端文本文件，连同保存时用的基线（sha256 / mtime）。
 *
 * 后端会拒绝二进制、非 UTF-8、超大与目录，并在错误里说清是哪种情况，
 * 前端把 message 原样转达即可，不要自己猜。
 */
export function readText(id, path) {
  return request("GET", "/api/connections/" + qs(id) + "/text?path=" + qs(path));
}

/**
 * 写回内容。
 *
 * baseSha256 / baseMtime 是打开时服务端给的基线：文件在你编辑期间被改过，
 * 后端会拒绝写入（409 edit_conflict）而不是覆盖别人的修改。
 * newline 留空 = 沿用文件当前的换行风格，这是常态。
 */
export function saveText(id, path, text, options) {
  const opts = options || {};
  return request("PUT", "/api/connections/" + qs(id) + "/text", {
    body: {
      path: path,
      text: text,
      base_sha256: opts.baseSha256 || "",
      base_mtime: typeof opts.baseMtime === "number" ? opts.baseMtime : null,
      newline: opts.newline || "",
      keep_bom: Boolean(opts.keepBom),
    },
  });
}

/** 响应形如 {"entry": {...}} —— 调用方要先拆掉这层信封（见 fileops.js 的 unwrap）。 */
export function renameEntry(id, path, newName) {
  return request("POST", "/api/connections/" + qs(id) + "/rename", {
    body: { path: path, new_name: newName },
  });
}

/** 响应形如 {"deleted": {...}}：removed 里有文件与目录的计数。 */
export function deleteEntry(id, path, recursive) {
  return request("POST", "/api/connections/" + qs(id) + "/delete", {
    body: { path: path, recursive: Boolean(recursive) },
  });
}

/** 响应形如 {"archive": {...}}：entries / size / bytes / skipped 都在里面。 */
export function compressEntry(id, path, name) {
  return request("POST", "/api/connections/" + qs(id) + "/compress", {
    body: { path: path, name: name || "" },
  });
}

/** 响应形如 {"extract": {...}}：files / directories / existing / skipped / stopped 都在里面。 */
export function extractEntry(id, path, into, overwrite) {
  return request("POST", "/api/connections/" + qs(id) + "/extract", {
    body: { path: path, into: into || "", overwrite: Boolean(overwrite) },
  });
}

export function uploadCheck(id, directory, filename) {
  return request(
    "GET",
    "/api/connections/" + qs(id) + "/upload-check?path=" + qs(directory) + "&name=" + qs(filename)
  );
}

/**
 * 换一张下载票据。
 *
 * 下载必须由浏览器自己发起（<a href> / location.assign）才有原生进度条与
 * 「另存为」对话框；而浏览器自己发起的导航请求带不了自定义头，所以先用
 * 一次带令牌的 POST 换一张只能下这一个文件的票据，再把票据放进 URL。
 */
export function downloadTicket(id, path) {
  return request("POST", "/api/connections/" + qs(id) + "/download-ticket", {
    body: { path: path },
  });
}

/**
 * 上传一个文件。
 *
 * 这里用 XMLHttpRequest 而不是 fetch，唯一原因是上传进度：
 * fetch 至今没有可用的上传进度事件（duplex 流在浏览器端支持极差），
 * 而大文件没有进度条就无法判断是不是卡住了。
 */
export function uploadFile(id, directory, file, options) {
  const opts = options || {};
  return new Promise(function (resolve, reject) {
    const url =
      "/api/connections/" +
      qs(id) +
      "/upload?path=" +
      qs(directory) +
      "&name=" +
      qs(file.name) +
      (opts.overwrite ? "&overwrite=1" : "");
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url, true);
    if (TOKEN) xhr.setRequestHeader("X-AWFM-Token", TOKEN);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    if (opts.onProgress) {
      xhr.upload.addEventListener("progress", function (event) {
        if (event.lengthComputable) opts.onProgress(event.loaded, event.total);
      });
    }
    if (opts.signal) {
      opts.signal.addEventListener("abort", function () {
        xhr.abort();
      });
    }
    xhr.addEventListener("load", function () {
      let payload = null;
      try {
        payload = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch (error) {
        reject(new ApiError("bad_response", "上传响应不是合法 JSON。", xhr.responseText.slice(0, 500), xhr.status));
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300 && payload && payload.ok === true) {
        resolve(payload.data);
        return;
      }
      const err = (payload && payload.error) || {};
      reject(
        new ApiError(
          err.code || "upload_failed",
          err.message || "上传失败（HTTP " + xhr.status + "）。",
          err.detail,
          xhr.status
        )
      );
    });
    xhr.addEventListener("error", function () {
      reject(new ApiError("network_error", "上传过程中网络中断。", "", 0));
    });
    xhr.addEventListener("abort", function () {
      const error = new Error("已取消上传。");
      error.name = "AbortError";
      reject(error);
    });
    xhr.send(file);
  });
}
