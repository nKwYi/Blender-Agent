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
  if (name === "proposal") {
    el("vocab-bar").innerHTML = "";
    el("prop-notes").innerHTML = "";
    loadVocab().catch(function (e) {
      setStatus("vocabulary.json 缺失：" + e.message + "（先跑 dev/build_vocabulary.py，再跑 dev/build_data_js.py）");
      var bad = document.createElement("div");
      bad.className = "loaderr";
      bad.textContent = "受限词汇表加载失败：" + e.message +
        " ｜ 修复：python dev/build_vocabulary.py 然后 python dev/build_data_js.py";
      el("vocab-bar").appendChild(bad);
    });
  }
}

function init() {
  var bs = document.querySelectorAll("#views button");
  for (var i = 0; i < bs.length; i++) {
    (function (b) { b.onclick = function () { switchView(b.dataset.view); }; }(bs[i]));
  }
  el("export").onclick = function () {
    var payload = {
      annotations: annotations,
      proposal: proposal
    };
    var blob = new Blob([JSON.stringify(payload, null, 2)],
                        { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "annotations.json";
    a.click();
    setStatus("已导出 annotations.json（含 " +
              Object.keys(annotations).length + " 条标注，" +
              proposal.length + " 条提案）");
  };
  // 顺序有讲究：runDemoHook 必须赶在 loadState 之前读 hash。loadState 会把
  // 未知 hash 归一成状态名并写回 location.hash（"#proposal-all" -> "idle"），
  // 晚一步读就永远是 "idle"，钩子静默不触发。
  runDemoHook(window.location.hash || "");
  bindCanvasDnd();
  loadState(stateFromHash());
}

/* ---------------- 提案视图 ---------------- */

/* 提案画布是整个工作台唯一面向用户做设计决策的地方。核心约定：
   评审提前到落笔那一秒——只有词汇表里的 12 个控件能被摆出来，参数只能在
   allowed_props 里挑；blocked_props 里的（label 的 size/font/color 等）当场
   标违规；想要的效果在词汇表里根本没有的，走「做不到」列表，插入的是
   降级方案而不是原需求。
   注意：主题里没有红也没有绿（constraints.json 的 warn_color / ok_color
   都已确认 native_ok=false），所以「合法 / 违规 / 已降级」一律靠文案、
   边框明度与删除线区分，不靠颜色——与 Blender 侧的能力边界保持一致。 */

var proposal = [];   // [{uid, wkey, label, uiloayout, params, id, note, errors, downgraded, blocker, fallback}]
var vocab = null;

/* 积木身份：每块拿到一个单调递增、永不复用的 uid（b1、b2……）。
   为什么必须是 uid 而不是数组下标：下标是位置。提案视图一旦能删除、能排序，
   第 3 块被删掉之后原来的第 4 块就顶上了它的位置——继续按下标定位，
   用户正在编辑的参数框会莫名其妙跳到隔壁那块上，标注也会贴错块。
   uid 只跟着积木走，位置随便变，身份不变。 */
var uidSeq = 0;

/* 拖拽状态。只在一次拖拽期间非空，任何一条收尾路径都必须把它清掉。 */
var dragState = null;   // {uid: string, fromIdx: int}

/* 最近一次删除，供单步撤销用。null = 没有可撤销的东西。 */
var lastDeleted = null; // {node: object, index: int}

/* 把 fromIdx 处的积木移到 toIdx 处。toIdx 是「先取出源、再插入」的目标位置，
   与 UIList / Array.splice 的常见用法一致，所以向后拖（toIdx > fromIdx）时
   要减一——那个位置上的元素在源被取出后已经往前挪了一位。

   只动数组顺序，绝不重建 uid：uid 是标注不串块的唯一依据，
   一旦在这里调用 nextUid()，用户标注过的积木就集体换了身份。 */
function reorderTo(fromIdx, toIdx) {
  if (fromIdx === toIdx || fromIdx < 0 || fromIdx >= proposal.length) { return; }
  var item = proposal.splice(fromIdx, 1)[0];
  if (!item) { return; }
  var at = toIdx > fromIdx ? toIdx - 1 : toIdx;
  proposal.splice(at, 0, item);
  renderCanvas();
}

/* 指针落在哪一格：返回「插在当前第几块之前」，值域 0..块数。
   越过某块的中线就算落到下一格去——这是列表拖拽的通用手感，
   半高判定对不齐的时候宁可用中线，别让两块之间出现死区。 */
function dropIndexAt(clientY) {
  var boxes = el("canvas").querySelectorAll(".pnode");
  for (var i = 0; i < boxes.length; i++) {
    var r = boxes[i].getBoundingClientRect();
    if (clientY < r.top + r.height / 2) { return i; }
  }
  return boxes.length;
}

/* 把落位指示线挪到第 idx 格。指示线是 #canvas 的直接子元素，不是某块积木的
   子节点——放进 .pnode 的话，它会跟着那一块一起被 renderCanvas 摘掉。 */
function moveDropLine(idx) {
  var host = el("canvas");
  var line = host.querySelector(".drop-line");
  if (!line) {
    line = document.createElement("div");
    line.className = "drop-line";
    line.setAttribute("aria-hidden", "true");
  }
  if (line.parentNode !== host) { host.appendChild(line); }
  var ref = host.querySelectorAll(".pnode")[idx] || null;
  if (ref) { host.insertBefore(line, ref); } else { host.appendChild(line); }
}

/* 拖拽收尾。所有路径（正常落位、按 Esc、丢到画布外面、dragend 迟到）
   都必须调用它，且它必须幂等：漏掉任何一处，画布就会永久卡在拖拽态，
   指示线和半透明的块再也撤不掉。 */
function clearDrag() {
  dragState = null;
  var host = el("canvas");
  var dragging = host.querySelectorAll(".pnode.dragging");
  for (var i = 0; i < dragging.length; i++) { dragging[i].classList.remove("dragging"); }
  var lines = host.querySelectorAll(".drop-line");
  for (var j = 0; j < lines.length; j++) {
    if (lines[j].parentNode) { lines[j].parentNode.removeChild(lines[j]); }
  }
}

/* 原生 HTML5 draggable，零依赖（file:// 下双击直开，不许引任何拖拽库）。
   监听器挂在列容器 #canvas 上而不是每块积木上：画布每次操作都会整体重建，
   挂在具体节点上的监听器第一次重建就失效了。
   dragend 挂在 document 上：源节点一旦被 drop 里的 renderCanvas 摘掉，
   从它身上冒泡的 dragend 就再也到不了 #canvas。 */
function bindCanvasDnd() {
  var canvas = el("canvas");
  canvas.addEventListener("dragstart", function (e) {
    // 在参数框 / 备注框里拖选文本也会冒泡出 dragstart。不挡掉的话，
    // 用户只是在选中一段文字，整个积木却跟着半透明起来，像卡住了。
    if (e.target && e.target.closest && e.target.closest("input, textarea")) { return; }
    var box = e.target && e.target.closest ? e.target.closest(".pnode") : null;
    if (!box) { return; }
    dragState = { uid: box.dataset.uid, fromIdx: idxByUid(box.dataset.uid) };
    box.classList.add("dragging");
    if (e.dataTransfer) {
      e.dataTransfer.effectAllowed = "move";
      try { e.dataTransfer.setData("text/plain", box.dataset.uid); }
      catch (err) { /* 某些浏览器对自定义类型会抛，忽略即可 */ }
    }
  });
  canvas.addEventListener("dragover", function (e) {
    if (!dragState) { return; }
    e.preventDefault();                 // 不 preventDefault 的话 drop 根本不触发
    if (e.dataTransfer) { e.dataTransfer.dropEffect = "move"; }
    moveDropLine(dropIndexAt(e.clientY));
  });
  canvas.addEventListener("drop", function (e) {
    if (!dragState) { return; }
    e.preventDefault();
    var from = dragState.fromIdx;
    var to = dropIndexAt(e.clientY);
    clearDrag();                          // 先收尾再重排：renderCanvas 会清空整列
    reorderTo(from, to);
  });
  document.addEventListener("dragend", clearDrag);
}

function nextUid() {
  uidSeq += 1;
  return "b" + uidSeq;
}

function idxByUid(uid) {
  for (var i = 0; i < proposal.length; i++) {
    if (proposal[i].uid === uid) { return i; }
  }
  return -1;
}

function loadVocab() {
  return getJSON("vocabulary.json").then(function (v) {
    if (!v || !v.widgets || !v.rejected) {
      throw new Error("vocabulary.json 结构不对（缺 widgets / rejected）");
    }
    vocab = v;
    renderVocabBar();
    renderRejected();
    renderUnmapped();
    renderCanvas();
    return v;
  });
}

function renderVocabBar() {
  var host = el("vocab-bar");
  host.innerHTML = "";
  var h = document.createElement("b");
  h.textContent = "可用控件（点一下落到画布最下面，搭好后可拖动换位）：";
  host.appendChild(h);
  vocab.widgets.forEach(function (w) {
    var b = document.createElement("button");
    b.dataset.wkey = w.key;
    b.textContent = w.label;
    b.title = "点一下加到画布最下面；搭好后按住积木左侧的手柄可拖动换位\n" +
      w.uiloayout +
      (w.allowed_props.length ? "\n可用参数：" + w.allowed_props.join(", ") : "\n无参数") +
      (w.blocked_props.length ? "\n被拦参数：" + w.blocked_props.join(", ") : "") +
      (w.note ? "\n" + w.note : "");
    b.onclick = function () { addWidget(w); };
    host.appendChild(b);
  });
  if (vocab.props_scope) {
    var sc = document.createElement("div");
    sc.className = "scope";
    sc.textContent = vocab.props_scope;
    host.appendChild(sc);
  }
  renderUndoBar();
}

/* 单步撤销的按钮。没删过东西时必须 disabled——一个点下去静默无事发生的
   按钮比没有更糟，它会让用户以为撤销坏了。单独抽出来是因为删完一块
   之后必须立刻刷新它的可用状态，而那走的是 delNode 不是 renderVocabBar。 */
function renderUndoBar() {
  var host = el("vocab-bar");
  if (!host) { return; }
  var old = el("undo-del");
  if (old && old.parentNode) { old.parentNode.removeChild(old); }
  var row = document.createElement("div");
  row.className = "rrow";
  var b = document.createElement("button");
  b.id = "undo-del";
  b.dataset.act = "undo";
  b.textContent = "撤销上一次删除";
  b.title = lastDeleted
    ? "把刚删掉的「" + lastDeleted.node.label + "」放回原位（身份不变，只救这一次）"
    : "还没有删过东西";
  b.disabled = !lastDeleted;
  b.onclick = function () { undoDelete(); };
  row.appendChild(b);
  host.appendChild(row);
}

/* 可做、但词汇表还没收录的能力。控件栏没有它、降级栏也不会有它，
   不单列出来就等于在「落笔那一秒」彻底消失——用户只能去约束总表翻。 */
function renderUnmapped() {
  var host = el("prop-notes");
  if (!vocab.unmapped_ok || !vocab.unmapped_ok.length) { return; }
  var h = document.createElement("h3");
  h.textContent = "Blender 做得到、但词汇表尚未收录（落笔时拿不到）：";
  host.appendChild(h);
  var row = document.createElement("div");
  row.className = "rrow";
  vocab.unmapped_ok.forEach(function (u) {
    var s = document.createElement("span");
    s.className = "unmapped";
    s.dataset.ukey = u.key;
    s.textContent = u.label + " " + u.uiloayout;
    s.title = (u.evidence || "") + "\n词汇表里没有对应控件，也没进降级列表——" +
      "要它得先往 dev/build_vocabulary.py 的 WIDGETS 里加一条。";
    row.appendChild(s);
  });
  host.appendChild(row);
}

function renderRejected() {
  var host = el("prop-notes");
  host.innerHTML = "";
  var h = document.createElement("h3");
  h.textContent = "想做但 Blender 做不到的（点按钮插入的是降级方案，不是原需求）";
  host.appendChild(h);
  var row = document.createElement("div");
  row.className = "rrow";
  vocab.rejected.forEach(function (r) {
    var b = document.createElement("button");
    b.dataset.rkey = r.key;
    b.textContent = "插入降级：" + r.label;
    b.title = "做不到：" + r.blocker + "\n降级方案：" + r.fallback;
    b.onclick = function () { addRejected(r); };
    row.appendChild(b);
  });
  host.appendChild(row);
}

function splitParams(raw) {
  return String(raw || "").split(/[,，\s]+/).map(function (s) { return s.trim(); })
    .filter(function (s) { return s.length > 0; });
}

/* 单个参数的判定：返回 null 表示合法，否则返回拦截理由。
   两类拦截要分清，不能只说「不支持」：
     blocked_props —— 这个参数在 Blender 里确实不存在（label 没有 size）
     允许清单之外 —— 这个控件的词汇表里没收录这个参数（怕拼错、怕自造）
   第二类如果不做，用户写 label(size=14) 会被当成 size 被拦，而写
   label(tooltip="x") 这种自造参数就会静默溜过去——那才是真漏。 */
function checkProp(w, p) {
  if (w.blocked_props.indexOf(p) >= 0) {
    return "参数 " + p + " 不被 UILayout 支持（" + w.uiloayout.split("(")[0] + " 没有这个参数）";
  }
  if (w.allowed_props.indexOf(p) < 0) {
    return "参数 " + p + " 不在「" + w.label + "」的允许清单里（可用：" +
      (w.allowed_props.length ? w.allowed_props.join(", ") : "无") + "）";
  }
  return null;
}

function validateWidget(w, params) {
  var errs = [];
  (params || []).forEach(function (p) {
    var msg = checkProp(w, p);
    if (msg) { errs.push({ param: p, msg: msg }); }
  });
  return errs;
}

function addWidget(w) {
  proposal.push({
    uid: nextUid(),
    wkey: w.key,
    label: w.label,
    uiloayout: w.uiloayout,
    allowed_props: w.allowed_props,
    blocked_props: w.blocked_props,
    params: "",
    id: "",
    note: "",
    errors: [],
    downgraded: false
  });
  renderCanvas();
}

function addRejected(r) {
  // 降级项不开放参数输入：它是「这条原需求做不到 + 这样改」的记录，
  // 不是可拼装的控件，硬塞参数进去只会让人以为能落笔。
  proposal.push({
    uid: nextUid(),
    wkey: "__downgraded__",
    label: r.label,
    uiloayout: "(不可用)",
    rkey: r.key,
    blocker: r.blocker,
    fallback: r.fallback,
    params: "",
    id: "",
    note: "",
    errors: [],
    downgraded: true
  });
  renderCanvas();
}

function setParams(n, raw) {
  n.params = raw;
  n.errors = validateWidget(
    { key: n.wkey, label: n.label, uiloayout: n.uiloayout,
      allowed_props: n.allowed_props || [], blocked_props: n.blocked_props || [] },
    splitParams(raw));
  // 参数每敲一个键就要重算 chips 和拦截文案，而重算的代价是整块画布重建。
  // renderCanvas 负责把焦点和光标位置原样还回去，别在这里另想办法。
  renderCanvas();
}

/* 删一块。参数是数组下标（调用方当场就该知道位置），块本身的身份靠 uid 自保——
   剩下的积木不会被重新编号，删中间一块也不会把后面的焦点拽走。
   idx < 0 守卫不能省：idxByUid 未命中时返回 -1，而 proposal.splice(-1, 1)
   在 JS 里是合法的、会把最后一块静默删掉。今天点不出这个路径（闭包节点
   一定还在数组里），但拖拽排序一行就会踩到，所以与 dupNode 一样挡掉。 */
function delNode(idx) {
  if (idx < 0) { return; }
  // 撤销用：整块原样存下来（含 uid），而不是只记个名字。
  // 删除和复制两个按钮紧挨着、点错没有确认，误删的参数和标注就找不回来了。
  lastDeleted = { node: proposal[idx], index: idx };
  proposal.splice(idx, 1);
  renderCanvas();
  renderUndoBar();
}

/* 单步撤销，不是撤销栈：只救最近一次删除，救完就作废。
   放回的是「原来那个对象」，所以 uid 一字不改——它是恢复，不是新建。
   万一原位置已经越界（后面又删过别的），夹到合法区间里即可，
   位置对不上也比数据丢了强。 */
function undoDelete() {
  if (!lastDeleted) { setStatus("没有可撤销的删除"); return; }
  var at = Math.max(0, Math.min(lastDeleted.index, proposal.length));
  proposal.splice(at, 0, lastDeleted.node);
  var label = lastDeleted.node.label;
  lastDeleted = null;
  renderCanvas();
  renderUndoBar();
  setStatus("已撤销删除：「" + label + "」回到第 " + (at + 1) + " 位");
}

/* 复制一块，副本紧跟原块。副本必须领新的 uid：沿用原 uid 的话，焦点保存、
   标注绑定、后续排序都会把两块当成同一块，改一块另一块跟着变。 */
function dupNode(idx) {
  var src = proposal[idx];
  if (!src) { return; }   // uid 对不上（块刚被别的操作删掉）：不崩，什么也不做
  var copy = {};
  for (var k in src) { if (src.hasOwnProperty(k)) { copy[k] = src[k]; } }
  copy.uid = nextUid();
  // 其余字段是浅拷贝：allowed_props / blocked_props 仍与原块共享引用。
  // 这是安全的——这两个字段全文件只读不写（checkProp 里只有 indexOf），
  // errors 才是唯一被改的字段，而 setParams 每次整体重新赋值，
  // 再 slice 一次只是不共享数组，不是在修 bug。真正会打破前提的是
  // 「逐块参数覆盖」那种新功能，不是重排。
  copy.errors = (src.errors || []).slice();
  proposal.splice(idx + 1, 0, copy);
  renderCanvas();
}

/* 记下「谁在编辑哪个字段、光标在哪」，重建完再还回去。
   不这么做的话，用户在被自己 oninput 摘掉的 input 里敲第二个字符时，
   事件已经打到 body 去了：输 scale_y 只会留下 s，全靠粘贴才能输完。
   记的是 uid 不是下标：画布每次都重建，下标会变，uid 不会。 */
function captureFocus(host) {
  var af = document.activeElement;
  if (!af || !af.dataset || af.dataset.field == null) { return null; }
  var box = host.querySelector('.pnode[data-uid="' + af.dataset.uid + '"]');
  var f = box && box.querySelector('[data-field="' + af.dataset.field + '"]');
  if (!f) { return null; }
  return { uid: af.dataset.uid, field: af.dataset.field,
           start: f.selectionStart, end: f.selectionEnd };
}

function restoreFocus(host, keep) {
  if (!keep) { return; }
  var box = host.querySelector('.pnode[data-uid="' + keep.uid + '"]');
  var f = box && box.querySelector('[data-field="' + keep.field + '"]');
  if (!f) { return; }
  f.focus();
  try { f.setSelectionRange(keep.start, keep.end); } catch (e) { /* 不支持就只聚焦 */ }
}

/* 空态引导。原来写的是「从上面挑控件开始拼装」——那是在教人填表单，
   不是在教人怎么搭；用户反馈「还是有点不太会用」，可发现性的问题就在这句。
   这里必须把两条路径都讲清楚：怎么加、怎么改顺序、顺序意味着什么。
   控件架在画布上方（index.html 的结构如此），不是左边，别写错方位。 */
function renderEmptyHint() {
  var p = document.createElement("p");
  p.id = "empty-hint";
  p.className = "hint";
  p.textContent = "点上面的控件，它就落到画布最下面；搭好之后，按住积木左侧的手柄" +
    "可以随时拖动换位，也可以复制一块、或删掉重来。积木从上到下的顺序，" +
    "就是插件里面板从上到下的顺序。挑不到想要的效果时，看下方「做不到」列表——" +
    "点它插入的是降级方案，原需求会被标成做不到。搭好后切回镜像视图，对着真实截图比。";
  return p;
}

function renderCanvas() {
  var host = el("canvas");
  var keep = captureFocus(host);
  host.innerHTML = "";
  if (!proposal.length) {
    host.appendChild(renderEmptyHint());
    return;
  }
  proposal.forEach(function (n, i) {
    var box = document.createElement("div");
    box.className = "note pnode" + (n.downgraded ? " down" : (n.errors.length ? " blocked" : ""));
    box.setAttribute("draggable", "true");   // 必须在 dataset 之前写，否则会插到
                                            // 既有属性中间，打断按顺序匹配的 DOM 断言
    box.dataset.idx = String(i);      // 仅供调试看顺序，任何定位都不许用它
    box.dataset.uid = n.uid;
    box.dataset.wkey = n.wkey;
    box.dataset.downgraded = n.downgraded ? "1" : "0";
    box.dataset.status = n.downgraded ? "downgraded" : (n.errors.length ? "blocked" : "ok");
    box.dataset.errors = String(n.errors.length);
    if (n.rkey) { box.dataset.rkey = n.rkey; }

    var head = document.createElement("div");
    head.className = "phead";
    /* 拖拽手柄。整个 .pnode 都可拖，但手柄是「这里能拖」的视觉承诺——
       没有它，积木看着像个表单卡片，用户不会想到可以换位。 */
    var grip = document.createElement("span");
    grip.className = "drop-handler";
    grip.textContent = "⋮⋮";
    grip.title = "按住这块积木拖动，可以换位置";
    head.appendChild(grip);
    var tag = document.createElement("span");
    tag.className = "ptag";
    tag.textContent = n.downgraded ? "已降级" : (n.errors.length ? "违规 " + n.errors.length + " 项" : "合法");
    head.appendChild(tag);
    var nm = document.createElement("b");
    nm.textContent = n.label;
    head.appendChild(nm);
    var code = document.createElement("code");
    code.textContent = n.uiloayout;
    head.appendChild(code);

    /* 复制 / 删除。
       主题里没有红也没有绿（见文件头），所以「删除」不靠红色表达：
       沿用 .chip.bad——它本来就是「不可用 / 违规」的表达（删除线 + 加深边框），
       与降级块里「原需求做不到」那条删除线是同一套语汇。
       复制沿用普通 .chip。两个按钮都靠 data-uid 找回自己那块，
       不记下标——点了之后画布会重建，下标随时会过期。 */
    var dupB = document.createElement("button");
    dupB.className = "chip";
    dupB.dataset.act = "dup";
    dupB.dataset.uid = n.uid;
    dupB.textContent = "复制";
    dupB.title = "原地复制一块（副本是独立积木，身份独立）";
    dupB.onclick = function () { dupNode(idxByUid(n.uid)); };
    head.appendChild(dupB);

    var delB = document.createElement("button");
    delB.className = "chip bad";
    delB.dataset.act = "del";
    delB.dataset.uid = n.uid;
    delB.textContent = "删除";
    delB.title = "删掉这块积木";
    delB.onclick = function () { delNode(idxByUid(n.uid)); };
    head.appendChild(delB);

    box.appendChild(head);

    if (n.downgraded) {
      var fb = document.createElement("div");
      fb.className = "pfb";
      var req = document.createElement("span");
      req.className = "strike";
      req.textContent = "原需求做不到：" + n.blocker;
      fb.appendChild(req);
      var alt = document.createElement("div");
      alt.textContent = "降级方案：" + n.fallback;
      fb.appendChild(alt);
      box.appendChild(fb);
    } else {
      var chips = document.createElement("div");
      chips.className = "chips";
      var ps = splitParams(n.params);
      ps.forEach(function (p) {
        var c = document.createElement("span");
        var bad = checkProp({ label: n.label, uiloayout: n.uiloayout,
          allowed_props: n.allowed_props || [], blocked_props: n.blocked_props || [] }, p);
        c.className = "chip" + (bad ? " bad" : "");
        c.textContent = p + (bad ? " ✗" : "");
        chips.appendChild(c);
      });
      box.appendChild(chips);

      var pin = document.createElement("input");
      pin.className = "pin pinp";
      pin.dataset.field = "params";
      pin.dataset.uid = n.uid;
      pin.placeholder = "参数，逗号分隔（只认 " +
        ((n.allowed_props || []).join(", ") || "无") + "）";
      pin.value = n.params;
      pin.oninput = function () { setParams(n, pin.value); };
      box.appendChild(pin);
    }

    n.errors.forEach(function (e) {
      var er = document.createElement("div");
      er.className = "perr";
      er.textContent = "✗ 拦截：" + e.msg;
      box.appendChild(er);
    });

    var idIn = document.createElement("input");
    idIn.className = "pin";
    idIn.dataset.field = "id";
    idIn.dataset.uid = n.uid;
    idIn.placeholder = "对应插件元素 ID（可空）";
    idIn.value = n.id;
    idIn.oninput = function () { n.id = idIn.value; };
    box.appendChild(idIn);

    var ta = document.createElement("textarea");
    ta.className = "pnote";
    ta.dataset.field = "note";
    ta.dataset.uid = n.uid;
    ta.placeholder = "想要什么？为什么？";
    ta.value = n.note;
    ta.oninput = function () { n.note = ta.value; };
    box.appendChild(ta);
    host.appendChild(box);
  });
  restoreFocus(host, keep);
}

/* 无头验收钩子：#proposal-all / #proposal-blocked / #proposal-empty / #proposal-typing。
   dev/test_proposal_vocab.py 用 headless Edge --dump-dom 核对「12 个控件点一遍
   全合法」与「label 写了违规参数会被拦」。这里刻意用 bs[i].click() 点真实按钮，
   而不是直接调 addWidget——否则验的就不是用户点的那条路径了。
   #proposal-empty 只切视图不插任何东西，用来核对空画布的初始样子
   （普通 #proposal 走不到提案视图：loadState 会把未知 hash 归一成状态名）。
   #proposal-blocked 会额外给文字（label）塞 size, color, scale, text：
   前三个分别命中 blocked_props、blocked_props、允许清单之外，text 合法。
   #proposal-typing 走逐字符 input 事件，专治「重建画布把焦点弄丢」那类 bug。
   #proposal-del / #proposal-dup 点真实的删除 / 复制按钮，核对块数与 uid 身份。 */
/* 按 wkey 找到数组下标，再拿这块的 uid 去 DOM 里捞输入框——
   两头都靠 uid，数组重排或中间被删掉都不会捞错块。 */
function paramsInputOf(wkey) {
  for (var i = 0; i < proposal.length; i++) {
    if (proposal[i].wkey !== wkey) { continue; }
    return el("canvas").querySelector('.pnode[data-uid="' + proposal[i].uid + '"] [data-field="params"]');
  }
  return null;
}

function uidListOf(nodes) {
  return (nodes || []).map(function (n) { return n.uid; }).join(",");
}

function appendReport(id, attrs) {
  var rep = document.createElement("div");
  rep.id = id;
  Object.keys(attrs).forEach(function (k) { rep.dataset[k] = attrs[k]; });
  el("canvas").appendChild(rep);
}

/* #proposal-del：点画布上真实的删除按钮，核对三件事。
   1) 过期按钮点了不做事——先摘下第一块的删除按钮，真删掉它，再点同一个
      （元素引用还在，闭包还在，但 uid 已经不在数组里，idxByUid 只能给 -1）。
      没有守卫的话 proposal.splice(-1, 1) 会静默删掉最后一块。
   2) 删最后一块，块数必须减一（splice 越界与否在这里现形）。
   3) 删中间一块，其余块的身份必须原封不动，且「渲染出来的 uid」与数组一致。 */
function delReport() {
  var before = uidListOf(proposal);
  var all = el("canvas").querySelectorAll(".pnode");
  var firstUid = proposal[0].uid;

  // 1) 摘下第一块的删除按钮（元素引用脱离文档后依然可点，闭包也还在）
  var staleBtn = all[0].querySelector('[data-act="del"]');
  staleBtn.click();
  var afterFirst = proposal.length;
  var afterFirstUids = uidListOf(proposal);

  // 同一个按钮再点一次：这次它代表的块已经不存在了
  staleBtn.click();
  var afterStale = proposal.length;

  // 2) 删最后一块
  var lastUid = proposal[proposal.length - 1].uid;
  el("canvas").querySelector('.pnode[data-uid="' + lastUid + '"]')
    .querySelector('[data-act="del"]').click();
  var afterLast = proposal.length;

  // 3) 删中间一块
  var midUid = proposal[Math.floor(proposal.length / 2)].uid;
  el("canvas").querySelector('.pnode[data-uid="' + midUid + '"]')
    .querySelector('[data-act="del"]').click();

  // 数组对了还不够——把 DOM 上真实渲染出来的 uid 也报出去，让测试逐位比对。
  // 只报数组的话，「数组删对了但画布上存活积木的 uid 是错的或空的」照样全绿。
  var boxes = el("canvas").querySelectorAll(".pnode[data-uid]");
  var domUids = [];
  for (var i = 0; i < boxes.length; i++) { domUids.push(boxes[i].dataset.uid); }

  appendReport("del-report", {
    before: String(all.length),
    beforeUids: before,
    firstUid: firstUid,
    afterFirst: String(afterFirst),
    afterFirstUids: afterFirstUids,
    afterStale: String(afterStale),
    lastUid: lastUid,
    afterLast: String(afterLast),
    midUid: midUid,
    afterUids: uidListOf(proposal),
    domUids: domUids.join(",")
  });
  setStatus("DEMO del 剩 " + proposal.length + " 块");
}

/* #proposal-dup：复制最后一块，核对块数加一、副本拿到全新 uid，
   并且副本真的以新 uid 渲染进了 DOM（不是只在数组里多了一条记录）。 */
function dupReport() {
  var before = uidListOf(proposal);
  var all = el("canvas").querySelectorAll(".pnode");
  all[all.length - 1].querySelector('[data-act="dup"]').click();

  var boxes = el("canvas").querySelectorAll(".pnode[data-uid]");
  appendReport("dup-report", {
    before: String(all.length),
    beforeUids: before,
    after: String(proposal.length),
    afterUids: uidListOf(proposal),
    domCount: String(boxes.length),
    domLastUid: boxes.length ? boxes[boxes.length - 1].dataset.uid : ""
  });
  setStatus("DEMO dup " + proposal.length + " 块");
}

/* 逐字符敲参数框，派发真的 input 事件——刻意不复用 #proposal-blocked 那条
   直接调 setParams 的捷径，因为那条绕开了用户实际会走的路径。
   这里模拟浏览器的真实行为：只有元素仍然持有焦点，这次按键才会落进去；
   节点一旦被 renderCanvas 摘出文档，后续按键就打到 body 上，字符会丢。
   敲 "scale_ys"（比合法值多一个 s）是为了同时验两件事：字符没丢，
   且最后那一下真的触发了拦截。 */
function typeReport(wkey, text) {
  var lost = 0;
  // 先点一下输入框（用户就是这么开始打字的），否则第一次按键就会「丢失」，
  // 测出来的就不是重建画布的锅，而是没人先把焦点放上去。
  var first = paramsInputOf(wkey);
  if (first) { first.focus(); }
  text.split("").forEach(function (ch) {
    var inp = paramsInputOf(wkey);
    if (!inp || document.activeElement !== inp) { lost++; return; }
    inp.value = inp.value + ch;
    // 光标放在中间而不是末尾：用户会在已有内容中间插入，光标位置也得还原。
    // 全放末尾的话这条断言不可证伪——新建的 input 本来就把光标放在末尾。
    var mid = Math.floor(inp.value.length / 2);
    inp.setSelectionRange(mid, mid);
    inp.dispatchEvent(new Event("input", { bubbles: true }));
  });
  var fin = paramsInputOf(wkey);
  var node = fin && fin.closest ? fin.closest(".pnode") : null;
  var rep = document.createElement("div");
  rep.id = "typing-report";
  rep.dataset.wkey = wkey;
  rep.dataset.lost = String(lost);
  rep.dataset.value = fin ? fin.value : "";
  rep.dataset.focused = String(!!fin && document.activeElement === fin);
  rep.dataset.caret = fin ? String(fin.selectionStart) : "-1";
  rep.dataset.errors = node ? node.dataset.errors : "?";
  rep.dataset.status = node ? node.dataset.status : "?";
  rep.textContent = "逐字符输入 " + text + "：落下 " + (text.length - lost) + "/" +
    text.length + " 字符，焦点" + (rep.dataset.focused === "true" ? "仍在" : "已丢") +
    "，光标在 " + rep.dataset.caret;
  el("canvas").appendChild(rep);
}

function fireDrag(target, type, y, dt) {
  var ev = new DragEvent(type, {
    bubbles: true, cancelable: true, composed: true,
    clientX: 24, clientY: y, dataTransfer: dt
  });
  target.dispatchEvent(ev);
  return ev;
}

/* #proposal-drag：不用真实鼠标，直接派发真的 DragEvent 走一遍拖拽链路。
   无头浏览器没法拖鼠标，但事件本身就是同一条路径——测的是真代码，不是替身。

   两条路径都要走：
     1) 取消：dragstart -> dragover -> dragend（没有 drop）。
        模拟拖到一半按 Esc 或丢在画布外面，这条路上只有 dragend 能收尾，
        漏掉它画布就永久卡在拖拽态（指示线撤不掉、块一直半透明）。
     2) 落位：dragstart -> dragover -> drop（把第 3 块放到第 1 位）。
        drop 里 renderCanvas 会把源节点摘掉，之后的 dragend 未必还冒泡得到，
        所以 drop 自己就必须收干净。 */
function dragReport() {
  var canvas = el("canvas");
  var before = uidListOf(proposal);
  var dt = new DataTransfer();

  // --- 1) 取消 ---
  var b1 = canvas.querySelectorAll(".pnode");
  var src1 = b1[5];
  fireDrag(src1, "dragstart", 0, dt);
  var y1 = b1[3].getBoundingClientRect().top + 4;
  fireDrag(canvas, "dragover", y1, dt);
  var lineSeen = canvas.querySelectorAll(".drop-line").length;
  fireDrag(src1, "dragend", y1, dt);
  var lineAfterCancel = canvas.querySelectorAll(".drop-line").length;
  var draggingAfterCancel = canvas.querySelectorAll(".pnode.dragging").length;
  var stateAfterCancel = String(dragState);
  var orderAfterCancel = uidListOf(proposal);

  // --- 2) 落位：第 3 块 -> 第 1 位 ---
  var b2 = canvas.querySelectorAll(".pnode");
  var src2 = b2[2];
  // 目标 y 取第 1 块顶端上方 2px：肯定在它的中线之上 -> 插入位 = 0，
  // 也就是「放在最前面」，结果顺序应为 [3,1,2,4…]
  var y2 = b2[0].getBoundingClientRect().top + 2;
  fireDrag(src2, "dragstart", 0, dt);
  fireDrag(canvas, "dragover", y2, dt);
  fireDrag(canvas, "drop", y2, dt);
  var lineAfterDrop = canvas.querySelectorAll(".drop-line").length;
  var stateAfterDrop = String(dragState);
  // 浏览器在 drop 之后还会补一个 dragend，从 document 上派发模拟这一下：
  // 此时源节点已经被重建掉了，真实浏览器里这条信号同样未必回得来，
  // 所以 clearDrag 必须幂等。
  fireDrag(document, "dragend", y2, dt);
  var midOrder = uidListOf(proposal);

  // --- 3) 反向落位：第 1 块 -> 第 3 位 ---
  // 只测「往前拖」会漏掉 reorderTo 里 toIdx > fromIdx 那半边：
  // 那一支要减 1（源被取出后，后面的元素已经往前挪了一位），
  // 漏减就会多插一格。只走反向的话，这个 bug 永远测不出来。
  var b3 = canvas.querySelectorAll(".pnode");
  var src3 = b3[0];
  var y3 = b3[3].getBoundingClientRect().top + 2;   // 插在当前第 4 块之前 -> 插入位 = 3
  fireDrag(src3, "dragstart", 0, dt);
  fireDrag(canvas, "dragover", y3, dt);
  fireDrag(canvas, "drop", y3, dt);

  var boxes = canvas.querySelectorAll(".pnode[data-uid]");
  var domUids = [];
  for (var i = 0; i < boxes.length; i++) { domUids.push(boxes[i].dataset.uid); }

  appendReport("drag-report", {
    beforeUids: before,
    lineSeen: String(lineSeen),
    lineAfterCancel: String(lineAfterCancel),
    draggingAfterCancel: String(draggingAfterCancel),
    stateAfterCancel: stateAfterCancel,
    orderAfterCancel: orderAfterCancel,
    lineAfterDrop: String(lineAfterDrop),
    stateAfterDrop: stateAfterDrop,
    afterUids: midOrder,
    afterFwdUids: uidListOf(proposal),
    domUids: domUids.join(",")
  });
  setStatus("DEMO drag 重排后剩 " + proposal.length + " 块");
}

/* #proposal-undo：删中间一块 -> 点画布上真实的撤销按钮 -> 必须原样回到原位。
   报 DOM 上的 uid 序列：只报数组的话，「数组放回去了但画布上还是少一块」照样全绿。 */
function undoReport() {
  var canvas = el("canvas");
  var before = uidListOf(proposal);
  var midIdx = Math.floor(proposal.length / 2);
  var victim = proposal[midIdx].uid;

  canvas.querySelector('.pnode[data-uid="' + victim + '"] [data-act="del"]').click();
  var afterDel = uidListOf(proposal);
  var btnDel = el("undo-del");
  var enabledAfterDel = String(!!btnDel && !btnDel.disabled);

  el("undo-del").click();
  var afterUndo = uidListOf(proposal);
  var btnUndo = el("undo-del");
  var boxes = canvas.querySelectorAll(".pnode[data-uid]");
  var domUids = [];
  for (var i = 0; i < boxes.length; i++) { domUids.push(boxes[i].dataset.uid); }

  appendReport("undo-report", {
    beforeUids: before,
    victimUid: victim,
    victimIdx: String(midIdx),
    afterDelUids: afterDel,
    enabledAfterDel: enabledAfterDel,
    afterUndoUids: afterUndo,
    enabledAfterUndo: String(!!btnUndo && !btnUndo.disabled),
    domUids: domUids.join(",")
  });
  setStatus("DEMO undo 恢复后剩 " + proposal.length + " 块");
}

function runDemoHook(hash) {
  var h = String(hash || "").replace(/^#/, "");
  var kind = (h === "proposal-all") ? "all"
           : (h === "proposal-blocked") ? "blocked"
           : (h === "proposal-typing") ? "typing"
           : (h === "proposal-del") ? "del"
           : (h === "proposal-dup") ? "dup"
           : (h === "proposal-drag") ? "drag"
           : (h === "proposal-undo") ? "undo"
           : (h === "proposal-empty") ? "empty" : null;
  if (!kind) { return; }
  switchView("proposal");
  loadVocab().then(function () {
    el("vocab-bar").innerHTML = "";
    el("prop-notes").innerHTML = "";
    renderVocabBar();
    renderRejected();
    renderUnmapped();
    if (kind === "empty") { setStatus("DEMO empty 控件 0 降级 0"); return; }
    var bs = el("vocab-bar").querySelectorAll("button[data-wkey]");
    for (var i = 0; i < bs.length; i++) { bs[i].click(); }
    if (kind === "typing") { typeReport("scale_y", "scale_ys"); return; }
    if (kind === "blocked") {
      var lab = proposal.filter(function (x) { return x.wkey === "label"; })[0];
      if (lab) { setParams(lab, "size, color, scale, text"); }
    }
    var rb = el("prop-notes").querySelectorAll("button[data-rkey]");
    for (var j = 0; j < rb.length; j++) { rb[j].click(); }
    if (kind === "del") { delReport(); return; }
    if (kind === "dup") { dupReport(); return; }
    if (kind === "drag") { dragReport(); return; }
    if (kind === "undo") { undoReport(); return; }
    var down = proposal.filter(function (x) { return x.downgraded; }).length;
    var blocked = proposal.filter(function (x) { return x.errors.length > 0; }).length;
    setStatus("DEMO " + kind + " 控件 " + (proposal.length - down) +
      " 降级 " + down + " 违规 " + blocked);
  }).catch(function (e) {
    setStatus("DEMO 失败：" + e.message);
  });
}

document.addEventListener("DOMContentLoaded", init);
