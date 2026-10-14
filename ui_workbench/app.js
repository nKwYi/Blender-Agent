/* 工作台逻辑。零依赖、零构建，file:// 双击直开。 */
"use strict";

var STATES = ["idle", "clarify", "options", "running", "done", "partial", "failed"];
var NAMES = {
  idle: "空闲", clarify: "待澄清", options: "规格选项待选",
  running: "执行中", done: "做完", partial: "做到一半", failed: "失败"
};

var cur = "idle";
var tree = null;
var DATA = window.UW_DATA || null;
var lsOK = true;               // file:// 下 Chrome 抛 SecurityError，降级为内存
var annotations = loadAnnotations();

function el(id) { return document.getElementById(id); }

function loadAnnotations() {
  try {
    return JSON.parse(localStorage.getItem("uw_annotations") || "{}");
  } catch (e) {
    lsOK = false;
    return {};
  }
}

function saveAnnotations() {
  // file:// 是不透明源（opaque origin）：localStorage 在 Chrome 里抛 SecurityError
  // （Firefox 正常）。存不了就退回内存，导出按钮仍然可用——不能让一次按键
  // 崩掉整个页面。
  if (!lsOK) { setStatus("（file:// 下无法持久化，标注只存在内存，用「导出标注」保存）"); return; }
  try {
    localStorage.setItem("uw_annotations", JSON.stringify(annotations, null, 2));
  } catch (e) {
    lsOK = false;
    setStatus("（file:// 下无法持久化，标注只存在内存，用「导出标注」保存）");
  }
}

/* file:// 下 XHR / fetch 拉同目录 JSON 会被 CORS 直接拒掉，所以全部数据由
   data/data.js 以 window.UW_DATA 注入，这里只做查表。
   键名规则：去掉 data/ 前缀与 .json 后缀。
   data/layout/idle.json -> "layout/idle"     constraints.json -> "constraints" */
function getJSON(path) {
  if (!DATA) {
    return Promise.reject(new Error("data/data.js 没加载，先跑 python dev\\build_data_js.py"));
  }
  var key = path.replace(/^data\//, "").replace(/\.json$/, "");
  var v = DATA[key];
  if (v === undefined) {
    return Promise.reject(new Error(path + " 不在 data/data.js 里，重新生成"));
  }
  return Promise.resolve(v);
}

function setStatus(msg) { el("status").textContent = msg || ""; }

function stateFromHash() {
  var h = (window.location.hash || "").replace(/^#/, "");
  return STATES.indexOf(h) >= 0 ? h : "idle";
}

function renderFilmstrip() {
  var bar = el("filmstrip");
  bar.innerHTML = "";
  STATES.forEach(function (s) {
    var b = document.createElement("button");
    b.textContent = NAMES[s] + " (" + s + ")";
    if (s === cur) { b.className = "on"; }
    b.onclick = function () { loadState(s); };
    bar.appendChild(b);
  });
}

function loadState(name) {
  cur = name;
  if (window.location.hash.replace(/^#/, "") !== name) {
    window.location.hash = name;   // 便于逐状态截图核对
  }
  renderFilmstrip();
  el("shot").src = "data/shots/" + name + ".png";
  el("shot-cap").textContent = "实机截图 · " + NAMES[name];
  setStatus("加载 " + name + " …");
  getJSON("data/layout/" + name + ".json").then(function (t) {
    tree = t;
    renderTree();
    renderAnnot();
    setStatus(lsOK ? "" : "（file:// 下无法持久化，标注只存在内存，用「导出标注」保存）");
  }).catch(function (e) {
    setStatus("布局树缺失：" + e.message + "（先跑 dev/capture_layout.py）");
    el("tree").innerHTML = "";
  });
}

function renderTree() {
  var host = el("tree");
  host.innerHTML = "";
  if (!tree) { return; }
  // 根节点不保证是消息流：Task 4 的导出以 chat.stream 为根、chat.tabbar 是它
  // 的第一个子节点，所以这里只做通用递归，不对根做特殊假设。
  host.appendChild(node(tree, 0, "0"));
}

/* 标注键 = 状态 | element_id | DFS 路径。
   路径是必须的：树里同一 element_id 会重复（options 有 3 个 chat.options），
   而没有 element_id 的节点更多（options 24 个节点里 16 个没有 ID）——只按 ID
   计数会让所有无名节点塌缩到同一个 "state|?"，互相覆盖标注。
   路径形如 0 / 0.2 / 0.2.1，是这个节点在本次 DFS 里的下标路径，唯一且不依赖 ID。
   第 n 次出现（nth）只用于树上显示 #2 / #3，不参与定键。 */
function akey(eid, path) {
  return cur + "|" + (eid || "?") + "@" + path;
}

function node(n, depth, path, seen) {
  seen = seen || {};
  var d = document.createElement("div");
  d.className = "node";
  d.style.paddingLeft = (depth * 16 + 8) + "px";
  if (n.alert) { d.className += " alert"; }
  if (n.enabled === false) { d.className += " disabled"; }

  var eid = n.element_id || "";
  var nth = eid ? (seen[eid] = (seen[eid] || 0) + 1) : 0;
  var key = akey(eid, path);
  d.dataset.eid = eid;
  d.dataset.akey = key;
  d.dataset.path = path;
  d.dataset.nth = String(nth);
  if ((annotations[key] || {}).want) { d.className += " noted"; }

  var kind = document.createElement("span");
  kind.className = "kind";
  kind.textContent = n.kind;
  d.appendChild(kind);

  if (eid) {
    var i = document.createElement("span");
    i.className = "id";
    i.textContent = eid + (nth > 1 ? " #" + nth : "") + " ";
    d.appendChild(i);
  } else {
    // 无名节点在树上标出路径，否则十几个 "box" / "row" 长得一模一样，
    // 标注挂在谁身上全靠猜。
    var a2 = document.createElement("span");
    a2.className = "id";
    a2.textContent = "?" + "@" + path + " ";
    d.appendChild(a2);
  }
  (n.texts || []).forEach(function (t) {
    var s = document.createElement("span");
    s.className = "txt";
    s.textContent = t + " ";
    d.appendChild(s);
  });
  (n.ops || []).forEach(function (o) {
    var s = document.createElement("span");
    s.className = "id";
    s.textContent = "[" + o.id + (o.text ? ":" + o.text : "") + "] ";
    d.appendChild(s);
  });
  (n.props || []).forEach(function (p) {
    var s = document.createElement("span");
    s.className = "kind";
    s.textContent = (p.prop || "?") + (p.is_textbox ? "(textbox)" : "") + " ";
    d.appendChild(s);
  });
  if (n.alert) {
    var a = document.createElement("span");
    a.className = "kind";
    a.textContent = "⚠ alert";
    d.appendChild(a);
  }
  if (n.enabled === false) {
    var e = document.createElement("span");
    e.className = "kind";
    e.textContent = "禁用";
    d.appendChild(e);
  }

  d.onclick = function (e) {
    // 子节点嵌在父 .node 里，必须阻断冒泡，否则同一次点击会把祖先也标成选中，
    // 最终选中的变成根节点。
    e.stopPropagation();
    var all = document.querySelectorAll("#tree .node");
    for (var i2 = 0; i2 < all.length; i2++) {
      all[i2].className = all[i2].className.replace(/\s*sel\b/g, "");
    }
    d.className += " sel";
    renderAnnot();
  };
  (n.children || []).forEach(function (c, ci) {
    d.appendChild(node(c, depth + 1, path + "." + ci, seen));
  });
  return d;
}

/* 树里同一 ID 会出现多次、无名节点还有十几个，靠 data-akey 精确定位 */
function selectedNode() { return document.querySelector("#tree .node.sel"); }

function renderAnnot() {
  var host = el("annot");
  var sel = selectedNode();
  var key = sel ? sel.dataset.akey : "";
  host.innerHTML = "";

  var h = document.createElement("h3");
  h.textContent = sel
    ? "标注 · " + (sel.dataset.eid || "（无 ID " + sel.dataset.path + "）") +
      (Number(sel.dataset.nth) > 1 ? " 第 " + sel.dataset.nth + " 处" : "") +
      "  [" + key + "]"
    : "标注 · （先在右侧点一个元素）";
  host.appendChild(h);

  var note = document.createElement("div");
  note.className = "note";
  var ta = document.createElement("textarea");
  ta.placeholder = sel ? "想要什么？为什么？" : "先点一个元素再写";
  ta.disabled = !sel;
  ta.value = (annotations[key] || {}).want || "";
  ta.oninput = function () {
    annotations[key] = annotations[key] || {};
    annotations[key].want = ta.value;
    saveAnnotations();
  };
  note.appendChild(ta);
  host.appendChild(note);
}

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderConstraints() {
  getJSON("constraints.json").then(function (reg) {
    var host = el("constraints");
    var rows = "";
    (reg.entries || []).forEach(function (e) {
      rows += "<tr><td>" + esc(e.title) + "<br><small>" + esc(e.key) + "</small></td>"
        + "<td><span class='badge " + (e.native_ok ? "ok" : "no") + "'>"
        + (e.native_ok ? "可做" : "做不到") + "</span></td>"
        + "<td>" + esc(e.native_ok ? (e.uiloayout || "") : e.blocker) + "</td>"
        + "<td>" + esc(e.native_ok ? "—" : e.fallback) + "</td></tr>";
    });
    host.innerHTML = "<table><tr><th>能力</th><th>判定</th><th>阻断原因 / API</th>"
      + "<th>降级方案</th></tr>" + rows + "</table>";
  }).catch(function (e) {
    el("constraints").textContent = "constraints.json 缺失：" + e.message;
  });
}

function switchView(name) {
  ["mirror", "proposal", "constraints"].forEach(function (v) {
    el("view-" + v).hidden = (v !== name);
  });
  var bs = document.querySelectorAll("#views button");
  for (var i = 0; i < bs.length; i++) {
    bs[i].className = (bs[i].dataset.view === name) ? "on" : "";
  }
  if (name === "constraints") { renderConstraints(); }
}

function init() {
  var bs = document.querySelectorAll("#views button");
  for (var i = 0; i < bs.length; i++) {
    (function (b) { b.onclick = function () { switchView(b.dataset.view); }; }(bs[i]));
  }
  el("export").onclick = function () {
    var blob = new Blob([JSON.stringify(annotations, null, 2)],
                        { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "annotations.json";
    a.click();
    setStatus("已导出 annotations.json");
  };
  loadState(stateFromHash());
}

document.addEventListener("DOMContentLoaded", init);
