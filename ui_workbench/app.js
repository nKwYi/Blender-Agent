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

/* ---------------- 方案自动保存 ----------------
   用户的原话是「不然我调好了怎么告诉你然后落实呢」——这句话拆开是两件事：
   一是别丢（刷新还在），二是能交出去（导出，见文件末尾的导出段）。
   这一段只管第一件。

   为什么沿用 lsOK 那套降级而不是直接 localStorage.setItem：
   file:// 在 Chrome 里是不透明源，setItem 直接抛 SecurityError。抛在
   renderCanvas 里会让每一次改字都炸掉整个页面——所以照旧：抛了就翻脸
   （lsOK=false）、退回内存、并把这件事顶到页面最上面说清楚。
   「保存失败」最难受的地方不是失败，是静默：不说话的话，用户改了一下午，
   刷新之后才发现全没了。 */

var PLAN_KEY = "uw_plan_v1";

/* 这次启动恢复了多少块。0 = 没恢复（或被夹具 hash 跳过）。
   单独拎出来是因为状态条那句提示要在两个地方用：loadState 收尾时给用户看，
   以及 #proposal-restore 钩子核对「用户看到的到底是不是这句」。 */
var restoredBlocks = 0;

function planPayload() {
  return {
    format: "ui_workbench_plan",
    version: 1,
    saved_at: new Date().toISOString(),
    active_tab: activeTab,
    uid_seq: uidSeq,
    // boards 是三个界面的全部积木，node 对象本身就是内容 + 归属 + 标注的
    // 唯一真身（content / parent / note / id 都在里面），所以整份存进去即可，
    // 不另开一套「存档结构」——两份结构迟早会对不上。
    boards: boards
  };
}

/* 返回 true = 真的落盘了；false = 只在内存里（lsOK 已翻脸）。
   调用方不必处理返回值：翻脸的那一次已经把话说到了页面上。 */
function savePlan() {
  if (!lsOK) { return false; }
  try {
    localStorage.setItem(PLAN_KEY, JSON.stringify(planPayload()));
    return true;
  } catch (e) {
    lsOK = false;
    renderStoreNote();
    return false;
  }
}

function loadPlan() {
  var raw = null;
  try {
    raw = localStorage.getItem(PLAN_KEY);
  } catch (e) {
    // 只有 SecurityError（file:// + Chrome）能证明「这台机器存不了」。
    // 数据损坏那种错不算——那是内容坏了，不是通道坏了，不该连累 lsOK。
    if (e && e.name === "SecurityError") { lsOK = false; renderStoreNote(); }
    return null;
  }
  if (!raw) { return null; }
  try {
    var d = JSON.parse(raw);
    return (d && d.boards) ? d : null;
  } catch (e) {
    return null;
  }
}

/* 把存档里的一块补齐成画布认得的形状。
   为什么需要：将来加字段时，老存档里那块就少几个键。少键不该让整份存档
   作废（用户攒了两小时的东西），所以逐块补默认，而不是整份丢弃。 */
function normalizeNode(raw) {
  var n = raw || {};
  /* 业务块没有 wkey（它不是 UILayout 原语），只有一个 bkey。所以 wkey 的
     默认值只在「不是业务块」时才生效——否则存档里的业务块读回来会变成
     一块 label，界面上看着没丢，导出的代码却换成了别的东西。 */
  var bkey = n.bkey ? String(n.bkey) : null;
  return {
    uid: String(n.uid || nextUid()),
    parent: n.parent || null,
    wkey: bkey ? "" : String(n.wkey || "label"),
    bkey: bkey,
    bvar: String(n.bvar || ""),
    /* 已改过的文案：键是槽的 name，值是用户写的新文案。没改过的槽用
       blocks.json 里的原文——所以存档里不必把每句默认文案都存一份。 */
    btexts: (n.btexts && typeof n.btexts === "object") ? n.btexts : {},
    label: String(n.label || "（存档里的块）"),
    uiloayout: String(n.uiloayout || ""),
    allowed_props: n.allowed_props || [],
    blocked_props: n.blocked_props || [],
    params: String(n.params || ""),
    id: String(n.id || ""),
    note: String(n.note || ""),
    content: (n.content && typeof n.content === "object") ? n.content : {},
    errors: [],
    expanded: !!n.expanded,
    downgraded: !!n.downgraded
  };
}

/* 读回存档。返回恢复出来的块数（0 = 没有可恢复的东西）。

   刻意跳过 #proposal-* 这一类 hash：那些是测试与截图用的夹具，
   每次都自带一套积木（点满 12 个控件、插示例面板……），要是再把上次
   存的方案铺进去，块数就既不是夹具的也不是存档的，测出来的东西没有意义。
   真人打开工作台永远是空 hash 或 #idle，照样恢复。

   #proposal-restore 是唯一的例外，而且它存在的全部意义就是要恢复：
   它跑在「上一趟已经存过盘」的那份浏览器档案里，用的就是真实刷新那条路径。 */
function restorePlan() {
  var h = String(window.location.hash || "");
  if ((h.indexOf("#proposal") === 0 && h !== "#proposal-restore") ||
      h.indexOf("#biz") === 0) { return 0; }  var d = loadPlan();
  if (!d) { return 0; }
  var got = 0;
  TAB_ORDER.forEach(function (k) {
    var list = d.boards[k];
    if (!list || !list.length) { return; }
    boards[k] = list.map(normalizeNode);
    got += list.length;
  });
  if (!got) { return 0; }
  if (TAB_ORDER.indexOf(d.active_tab) >= 0) { activeTab = d.active_tab; }
  // uidSeq 必须跟着涨：不然恢复出来的 b17 之后，下一块新积木又从 b1 开始，
  // 两块撞 uid，标注就会贴到另一块身上。
  if (typeof d.uid_seq === "number" && d.uid_seq > uidSeq) { uidSeq = d.uid_seq; }
  proposal = boards[activeTab];
  restoredBlocks = got;
  return got;
}

/* 页面顶部那句提示 / 导出面板里那行小字。共用一套文案：同一个事实
   不许在页面上有两种说法。lsOK = true 时警告条收起来（不是留着占位）。 */
function storeMsg() {
  return lsOK
    ? "自动保存已开启：三个界面的积木（内容 / 归属 / 标注）每次改动都会写进 "
      + "localStorage，刷新页面不丢。"
    : "自动保存不可用：这个浏览器在 file:// 下禁用了 localStorage"
      + "（Chrome 会抛 SecurityError，Edge 正常）。方案目前只存在内存里，"
      + "刷新或关掉页面就没了——请用下方「下载方案 JSON」把它存到磁盘。";
}

function renderStoreNote() {
  var w = el("store-warn");
  if (w) {
    if (lsOK) { w.hidden = true; w.textContent = ""; }
    else { w.hidden = false; w.textContent = "⚠ " + storeMsg(); }
  }
  var note = el("store-note");
  if (note) { note.textContent = storeMsg(); }
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

/* 恢复提示的唯一出处。放在这里（而不是 init 里直接 setStatus）是因为
   loadState 收尾时会把状态条清空——写在 init 里的那句会被它抹掉，
   用户看到的就只剩一片空白，正好是「到底恢复没恢复」最需要说话的时刻。 */
function restoreNotice() {
  if (!restoredBlocks) { return ""; }
  return "已恢复上次存的方案：" + restoredBlocks + " 块积木（" +
    TAB_ORDER.map(function (k) {
      return TAB_LABELS[k] + " " + boards[k].length;
    }).join(" / ") + "）。继续搭或者直接导出都行。";
}

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
    setStatus(restoreNotice() ||
      (lsOK ? "" : "（file:// 下无法持久化，标注只存在内存，用「导出标注」保存）"));
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
  // 状态胶片条只对镜像视图有意义：那一排 7 个按钮切的是实机状态截图。
  // 提案视图里它挂在控件架正上方，用户会以为「得先选个状态才能提案」——
  // 那是镜像视图的心智模型，套到提案视图上只会挡路。这里是唯一该管它的地方：
  // 切到别的视图一律恢复，免得从提案视图切回来之后胶片条凭空消失。 */
  el("filmstrip").hidden = (name === "proposal");
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
  // 顺序有讲究：restorePlan 必须赶在 runDemoHook 之前跑——它决定 boards 里
  // 现在有什么，而 runDemoHook / loadState 都要在 boards 上作画。放在它们
  // 后面，恢复出来的积木得刷新一次才看得见，那不叫「刷新不丢」。
  // （restorePlan 内部自己跳过 #proposal-* 这类夹具 hash，所以下面的
  //  runDemoHook 拿到的仍是干净的空画布。）
  renderStoreNote();
  restorePlan();
  bindSelection();
  renderExportPanel();
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

/* 一个界面 = 一份独立的积木列表。真实面板（blender_deepseek_agent/ui.py 的
   DEEPSEEK_PT_chat.draw）顶上就是一根横排装着三个页签：对话 / 详情 / 设置，
   点哪个就画哪一份内容。所以工作台这边也必须有三份互不干扰的列表——共用一份的话，
   「搭对话面板搭到一半想看看设置长什么样」就会把半成品混进去。

   boards 是全部三份的真身；proposal 始终指向当前页签的那一份。
   保留 proposal 这个名字、并且让它是个普通变量（不是每次都写 boards[activeTab]），
   是为了让拖拽 / 删除 / 复制 / 撤销 / 各个无头钩子这些既有代码一行都不用改：
   它们读写的都是当前界面，切页签时只换一次指针。 */
var boards = { chat: [], detail: [], settings: [] };
var activeTab = "chat";
var proposal = boards.chat;

var TAB_LABELS = { chat: "对话", detail: "详情", settings: "设置" };
var TAB_ORDER = ["chat", "detail", "settings"];

var vocab = null;
/* 业务块（ui_workbench/blocks.json，dev/build_blocks.py 产出）。
   它是提案视图的第一词汇表：用户先看到的是「这个界面由哪几块东西组成」，
   vocabulary.json 里那 12 个 UILayout 原语退到下面折叠的「高级」区里。
   两种块共用一个画布，但形状不同——见 renderBizNode / renderNode。 */
var blocksDoc = null;

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
   一旦在这里调用 nextUid()，用户标注过的积木就集体换了身份。

   toIdx 一律夹到 [0, 块数]，与 delNode 对称。夹的不是防御性冗余：
   不夹的话 reorderTo(2, -1) 会走到 proposal.splice(-1, 0, item)，
   把积木静默插到最后一个元素之前——正是 delNode 当初要加守卫的那一类。
   今天 UI 走不到（dropIndexAt 只给 0..n），但本函数被明确导出为
   「拖拽与测试共用」的入口，只有兄弟一半的守卫纪律说不过去。 */
/* 同一个父级内重排。拖拽语义只保证「同一父级内换位」：把兄弟积木在
   proposal 数组里的先后对调，再重新渲染。

   为什么不做跨父级拖动（YAGNI）：跨父级要同时改 parent 与落位点，
   一旦算错就会出现「拖进容器里但没进去」或「进去了却在数组里留在外面」，
   而这两种错在界面上都长得像「拖坏了」。归属下拉是主操作路径，够用。

   实现上走「按 uid 定位 + 整段搬移」而不是给 splice 传算出来的下标：
   嵌套之后数组里同父级的兄弟不再连续，下标算错就是静默插错位置。 */
function reorderSibling(uid, targetUid, before) {
  var i = idxByUid(uid);
  if (i < 0) {
    setStatus("这块积木在拖动期间已经不在画布上了，顺序没变");
    return;
  }
  var node = proposal[i];
  if (targetUid && targetUid !== uid) {
    var j = idxByUid(targetUid);
    if (j < 0) {
      setStatus("落点那块积木已经不在画布上了，顺序没变");
      return;
    }
    if ((proposal[j].parent || null) !== (node.parent || null)) {
      // 不同父级：不动。跨父级拖动这一轮明确不做（见上面的说明），
      // 这里必须说话——静默不动会让用户以为拖拽坏了。
      setStatus("只能和同一个容器里的积木换位；换容器请用「归属」下拉");
      return;
    }
  }
  var rest = proposal.filter(function (n) {
    return (n.parent || null) === (node.parent || null) && n.uid !== uid;
  });
  var at = rest.length;
  if (targetUid) {
    for (var k = 0; k < rest.length; k++) {
      if (rest[k].uid === targetUid) { at = before ? k : k + 1; break; }
    }
  }
  var ordered = rest.slice(0, at);
  ordered.push(node);
  ordered = ordered.concat(rest.slice(at));

  // 把算好的顺序写回数组：只在同父级的那些槽位上换，原地不动其他块。
  var slots = [];
  proposal.forEach(function (n, ix) {
    if ((n.parent || null) === (node.parent || null)) { slots.push(ix); }
  });
  for (var s = 0; s < slots.length; s++) { proposal[slots[s]] = ordered[s]; }
  renderCanvas();
}

function reorderTo(fromIdx, toIdx) {
  if (fromIdx === toIdx) { return; }        // 拖回自己的原位：正常无事，不是异常
  if (fromIdx < 0 || fromIdx >= proposal.length) {
    // 拖起和落下之间数组变了（有人先删了东西）。静默弹回去会让用户以为
    // 拖拽坏了——undoDelete 对同类 no-op 会说话，这里也得说。
    setStatus("这块积木在拖动期间已经不在画布上了，顺序没变");
    return;
  }
  var item = proposal.splice(fromIdx, 1)[0];
  if (!item) {
    setStatus("这块积木在拖动期间已经不在画布上了，顺序没变");
    return;
  }
  var at = Math.max(0, Math.min(toIdx > fromIdx ? toIdx - 1 : toIdx, proposal.length));
  proposal.splice(at, 0, item);
  renderCanvas();
}

/* 指针落在哪一格：返回「插在当前兄弟里的第几块之前」，值域 0..兄弟数。
   越过某块的中线就算落到下一格去——这是列表拖拽的通用手感，
   半高判定对不齐的时候宁可用中线，别让两块之间出现死区。

   只看同一个父级里的兄弟：嵌套之后画布上 .pnode 的文档顺序是
   「容器、它的孩子、它的孩子…、下一个容器」，直接数全部 .pnode 会把
   孩子算进指示线的格子里，拖一下就跳位。 */
function dropIndexAt(clientY, parentUid) {
  var boxes = siblingBoxes(parentUid);
  for (var i = 0; i < boxes.length; i++) {
    var r = boxes[i].getBoundingClientRect();
    if (clientY < r.top + r.height / 2) { return i; }
  }
  return boxes.length;
}

/* 同一父级下的兄弟节点，按 DOM 顺序（也就是数组顺序）。 */
function siblingBoxes(parentUid) {
  var host = el("canvas");
  var all = host.querySelectorAll(".pnode[data-uid]");
  var out = [];
  var want = parentUid || "";
  for (var i = 0; i < all.length; i++) {
    if ((all[i].dataset.parent || "") === want) { out.push(all[i]); }
  }
  return out;
}

/* 把落位指示线挪到第 idx 格。指示线挂在那一组兄弟的共同父容器里，
   不是某块积木的子节点——放进 .pnode 的话，它会跟着那一块一起被 renderCanvas 摘掉。 */
function moveDropLine(idx, parentUid) {
  var host = el("canvas");
  var line = host.querySelector(".drop-line");
  if (!line) {
    line = document.createElement("div");
    line.className = "drop-line";
    line.setAttribute("aria-hidden", "true");
  }
  // 指回兄弟之间时要把线放回来：它在「落在容器上」那半程里被收起来了。
  line.hidden = false;
  if (line.parentNode !== host) { host.appendChild(line); }
  var pid = parentUid || "";
  var ref = null;
  var sibs = siblingBoxes(pid);
  if (sibs[idx]) {
    ref = sibs[idx];
  } else if (sibs.length) {
    // 落在最后一块之后：插到这一组兄弟的末尾（容器里就插在它最后一个孩子之后）
    ref = sibs[sibs.length - 1].nextSibling;
  } else if (pid) {
    // 空容器：线要落在那个孩子的框里（.pkids），不是落在容器外面——
    // 落在外面的话，用户看到的是「插在这个容器上面」，与实际落点相反。
    ref = el("canvas").querySelector('.pkids[data-owner="' + pid + '"]')
       || el("canvas").querySelector('.pgroup[data-parent="' + pid + '"]');
  }
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
  /* 「能装进去」的标记与落点高亮也必须一起撤：漏掉任何一处，
     下一次拖起来时画布上会留着一堆上一次的候选框，
     用户会以为那些容器随时在等他拖。 */
  var marks = host.querySelectorAll(".pnode.can-drop, .pnode.drop-target");
  for (var k = 0; k < marks.length; k++) {
    marks[k].classList.remove("can-drop");
    marks[k].classList.remove("drop-target");
  }
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
    // button 同样要挡：这一轮把「整块可拖」放开（不必瞄 ⋮⋮）之后，
    // 从展开 / 复制 / 删除按钮上按下就会变成一次拖拽，点按钮变成点不动。
    if (e.target && e.target.closest &&
        e.target.closest("input, textarea, button")) { return; }
    // select 单独挡：归属下拉也是「按住拖一下换个值」的手势，
    // 被拖拽抢走的话，用户根本没法用下拉选别的容器。
    if (e.target && e.target.closest && e.target.closest("select")) { return; }
    var box = e.target && e.target.closest ? e.target.closest(".pnode") : null;
    if (!box) { return; }
    dragState = { uid: box.dataset.uid, parent: box.dataset.parent || null,
                  fromIdx: siblingIndexOf(box.dataset.uid) };
    box.classList.add("dragging");
    markDropTargets(box.dataset.uid);
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
    /* 指针落在某个容器上：这一轮是「装进去」，不是「换位」。
       指示线在这里必须收掉——线说的是「插在这一格之前」，
       而用户此刻要的是「成为这个容器的子块」，两句话同时出现只会让人犹豫。 */
    var over = containerUnder(e.target);
    if (over) {
      markDropLineHidden(true);
      if (over.ok) { markDropTarget(over.uid, true); }
      return;
    }
    markDropTarget(null, false);
    moveDropLine(dropIndexAt(e.clientY, dragState.parent), dragState.parent);
  });
  canvas.addEventListener("drop", function (e) {
    if (!dragState) { return; }
    e.preventDefault();
    var uid = dragState.uid;
    var parent = dragState.parent;

    /* 落在容器上 = 变成它的子块。跨父级拖动在这一轮做掉了：
       「能装进去的容器」在拖起来时就高亮出来了，用户看得见、点得准，
       不再需要展开积木去翻「归属」下拉。
       同父级内的排序语义一个字没动——那是 dropIndexAt / reorderSibling
       那条既有链路，下面照旧走。 */
    var over = containerUnder(e.target);
    if (over) {
      clearDrag();
      if (over.ok) { reparent(uid, over.uid); return; }
      // 落点是个容器但不能装：必须说话。静默弹回等于「拖拽坏了」。
      setStatus("不能把「" + labelOfUid(uid) + "」放进「" + over.label + "」里："
        + (over.why || "这一块装不了别的积木"));
      return;
    }

    var idx = dropIndexAt(e.clientY, parent);
    var sibs = siblingBoxes(parent);
    // 指示线说的是「插在第 idx 块之前」。把那个块当成锚点，
    // 比反推被拖积木自己原来的下标更不容易错（拖到自己前后都归一到它自己）。
    var anchor = null;
    var self = sibs.filter(function (b) { return b.dataset.uid === uid; })[0];
    var selfPos = -1;
    for (var i = 0; i < sibs.length; i++) { if (sibs[i] === self) { selfPos = i; } }
    if (idx > selfPos) { anchor = idx - 1 < sibs.length ? sibs[idx - 1] : null; }
    else { anchor = sibs[idx] || null; }
    var before = idx <= selfPos;
    var targetUid = anchor ? anchor.dataset.uid : null;
    clearDrag();                          // 先收尾再重排：renderCanvas 会清空整列
    if (targetUid === uid) { return; }
    if (!targetUid) {
      // 落在这一组最后：直接告诉 reorderSibling 移到末尾。
      reorderSibling(uid, null, true);
      return;
    }
    reorderSibling(uid, targetUid, before);
  });
  document.addEventListener("dragend", clearDrag);
}

/* 指针底下是不是一个容器积木。返回 {uid, label, ok, why}，不是容器给 null。

   ok = 能把手里这块装进去。判据与 renderNode 里那两个按钮同一套：
     · 自己不行（装进自己会绕成圈）
     · 自己的子孙不行（同上）
     · 已经在它里面了不行（那不叫「装进去」，等于原地不动）
     · 叶子控件一律不行（Blender 那边写不出来）
   why 带着原因文案：拒绝时必须说清楚为什么，不能只说「不行」。 */
function containerUnder(t) {
  var b = t && t.closest ? t.closest(".pnode") : null;
  if (!b || !b.dataset || !b.dataset.uid) { return null; }
  var n = nodeByUid(b.dataset.uid);
  if (!n || !isContainer(n)) { return null; }
  var ok = b.classList.contains("can-drop");
  var why = "这一块装不了别的积木";
  if (!ok) {
    if (!dragState) { why = "现在没有在拖任何积木"; }
    else if (n.uid === dragState.uid) { why = "不能把自己装进自己"; }
    else if (subtreeUids(dragState.uid).indexOf(n.uid) >= 0) {
      why = "它是自己的子孙，装进去会绕成圈";
    } else if ((dragState.parent || "") === n.uid) {
      why = "它已经在这个容器里了";
    }
  }
  return { uid: n.uid, label: n.label, ok: ok, why: why };
}

/* 拖起来的时候把「能装进去的容器」标出来。
   不标的话用户只能一个个拖过去试：拖不进去的那次没有提示，
   整块积木啪地弹回来，看上去就是坏了。
   主题里没有红也没有绿，所以「能装」靠边框 + 明度差表达，不靠颜色语义。 */
function markDropTargets(uid) {
  var host = el("canvas");
  var boxes = host.querySelectorAll(".pnode[data-uid]");
  var me = nodeByUid(uid);
  var mine = subtreeUids(uid);
  for (var i = 0; i < boxes.length; i++) {
    var n = nodeByUid(boxes[i].dataset.uid);
    if (!n) { continue; }
    var ok = isContainer(n) && n.uid !== uid
      && mine.indexOf(n.uid) < 0
      && (me ? (me.parent || "") !== n.uid : true);
    if (ok) { boxes[i].classList.add("can-drop"); }
  }
}

/* 高亮「就落在这一格」的那一个容器（拖动过程中跟着指针换）。 */
function markDropTarget(uid, on) {
  var host = el("canvas");
  var prev = host.querySelectorAll(".pnode.drop-target");
  for (var i = 0; i < prev.length; i++) { prev[i].classList.remove("drop-target"); }
  if (!uid) { return; }
  var b = host.querySelector('.pnode[data-uid="' + uid + '"]');
  if (b) { b.classList.add("drop-target"); }
}

/* 落在容器上时把落位指示线暂时收掉，拖回兄弟之间再放回来。
   与其删了重建，不如用 hidden 属性留着它——clearDrag 会一并清掉。 */
function markDropLineHidden(hidden) {
  var line = el("canvas").querySelector(".drop-line");
  if (line) { line.hidden = !!hidden; }
}

/* 这块在同父级兄弟里排第几（-1 = 不在画布上）。拖拽起点用它记位置，
   免得 drop 时再去猜「它原来在哪」。 */
function siblingIndexOf(uid) {
  var sibs = siblingBoxes(null);
  for (var i = 0; i < sibs.length; i++) { if (sibs[i].dataset.uid === uid) { return i; } }
  return -1;
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

/* ---------------- 积木嵌套 ----------------

   容器类控件（CONTAINER_WKEYS）能装孩子，其余不能。凭什么这么划：只有它们在
   Blender 里真的会收走后面若干个 draw 调用；文字 / 按钮 / 属性行是叶子，
   往里塞东西在 ui.py 里根本写不出来，词汇表也不许这么承诺。

   parent 存的是父积木的 uid，顶层为 null。存 uid 不存下标，理由和 identity
   用 uid 而不是下标是同一条：删掉中间一块、拖动换位之后下标全变，父指针
   一变就整棵树错位。 */
var CONTAINER_WKEYS = ["row", "column", "box", "split", "grid_flow", "panel"];

function isContainer(n) {
  // 业务块一律不是容器：它装不了东西（面板上一整块就是它自己）。
  if (n && n.bkey) { return false; }
  return n && !n.downgraded && CONTAINER_WKEYS.indexOf(n.wkey) >= 0;
}

/* 当前层级的积木：parent 为 null 的按数组顺序；其余按 parent 过滤。
   顺序一律以 proposal 数组里的先后为准——拖拽排序改的也是这个数组，
   两边必须看同一份顺序，否则「拖完顺序没变」这种 bug 会被藏起来。 */
function nodesAtDepth(parentUid) {
  return proposal.filter(function (n) { return (n.parent || null) === (parentUid || null); });
}

function childrenOf(uid) {
  return proposal.filter(function (n) { return n.parent === uid; });
}

/* 按 uid 找块，找不到给 null。工具栏文案与按钮 title 都靠它拿名字，
   拿不到就退化成空串——文案里少个名字远好过整段 JS 报错。 */
function nodeByUid(uid) {
  for (var i = 0; i < proposal.length; i++) {
    if (proposal[i].uid === uid) { return proposal[i]; }
  }
  return null;
}

function labelOfUid(uid) {
  var n = nodeByUid(uid);
  return n ? n.label : "";
}

/* 「上一个容器」= 同一层里、在它前面、最近的那个容器积木（叶子不算）。
   从紧挨着它的那块往前找，而不是只看前一块：前一块是文字时按钮就得
   一直灰着，用户会以为这个功能坏了。

   找不到给 null，调用方据此把按钮置灰。自己的子孙一律排除：
   装进自己的子孙会绕成圈（reparent 还会挡一道，但按钮就不该亮）。 */
function prevContainerUid(uid) {
  var me = nodeByUid(uid);
  if (!me) { return null; }
  var sibs = nodesAtDepth(me.parent);
  var mine = subtreeUids(uid);
  for (var i = sibs.length - 1; i >= 0; i--) {
    var c = sibs[i];
    if (c.uid === uid) { continue; }
    if (!isContainer(c) || mine.indexOf(c.uid) >= 0) { continue; }
    return c.uid;
  }
  return null;
}

/* 整棵子树的 uid 顺序（自己 + 所有后代），按数组顺序。
   删除要拿它、复制要拿它，两处都必须把子孙算进去，否则删掉容器会留下一堆
   指向已不存在 uid 的孤儿（它们 parent 着一个没人认领的 uid，既不显示也删不掉）。 */
function subtreeUids(uid) {
  var out = [];
  var walk = function (u) {
    var n = proposal.filter(function (x) { return x.uid === u; })[0];
    if (!n) { return; }
    out.push(n.uid);
    proposal.forEach(function (c) { if (c.parent === u) { walk(c.uid); } });
  };
  walk(uid);
  return out;
}

/* 环检测：把 uid 挂到 uid2 底下之前必须先确认 uid2 不是自己的子孙，
   否则渲染会无限递归直接把页面卡死。归属下拉只列「别的容器」，
   但数据来自 vocabulary.json 的示例面板，那边写错一个 parent 就会自环，
   所以这里仍然挡一道。 */
function wouldCycle(uid, newParent) {
  if (!newParent) { return false; }
  if (uid === newParent) { return true; }
  return subtreeUids(uid).indexOf(newParent) >= 0;
}

/* 改归属。返回值给状态条用：被环挡住时必须说话，不能静默不动。 */
function reparent(uid, newParent) {
  var i = idxByUid(uid);
  if (i < 0) { setStatus("这块积木已经不在画布上了，归属没变"); return false; }
  if (wouldCycle(uid, newParent)) {
    setStatus("不能把一块积木放进它自己的里面（会绕成圈）");
    return false;
  }
  if (newParent) {
    /* 要检查的是「目的地」，不是「被搬的那块」。
       原先这里查的是 proposal[i]（被搬的块），于是两条路都不通：
       装进别人的时候，因为被搬的多半是文字 / 按钮，被误判成
       「不是容器，装不了别的积木」；移出上一层的时候（newParent 为空）
       又把合法的「放回顶层」一起挡了。 */
    var dest = nodeByUid(newParent);
    if (!dest || !isContainer(dest)) {
      setStatus("「" + ((dest && dest.label) || "那个容器") + "」不是容器，装不了别的积木");
      return false;
    }
  }
  proposal[i].parent = newParent || null;
  /* 挂到别人底下之后，兄弟顺序只由数组顺序决定，所以要把它挪到父容器
     那些孩子的位置上——留在原地的话它会插在父容器自己后面，
     渲染成「父容器里第一个孩子」之外的位置，顺序看着像随机。 */
  var moved = proposal.splice(i, 1)[0];
  moved.parent = newParent || null;
  if (!newParent) { proposal.push(moved); }
  else {
    var kids = proposal.filter(function (n) { return n.parent === newParent; });
    if (!kids.length) { proposal.push(moved); }
    else {
      var lastKid = kids[kids.length - 1];
      proposal.splice(proposal.indexOf(lastKid) + 1, 0, moved);
    }
  }
  renderCanvas();
  setStatus("「" + moved.label + "」已移到「" + (newParent ?
    (proposal.filter(function (n) { return n.uid === newParent; })[0] || {}).label || ""
    : "顶层") + "」");
  return true;
}

/* ---------------- 选中：右栏积木 <-> 左栏预览，双向同步 ----------------
   需求原话：「点右栏任一积木，左边预览里对应的那个渲染区域要用天蓝色描一圈」。

   为什么预览这一侧是重点：右边是零件表，左边才是「拼起来长什么样」。
   零件表上一格一格地点，对不上脑子里那块面板；能指着屏幕说「这一块就是
   这个按钮」才是搭得下去的证据。所以两侧必须同时动。

   三条纪律：
   1) 描边色只许是 --accent（#4772b3，native_api.json 实测 panel_active，
      这张实测色板里唯一的蓝，也是 Blender 里你点东西时看到的那个选中色）。
      语义不靠别的信息承载；但「选中与否」是交互态不是数据，允许用蓝。
   2) 状态写在 data-sel 属性上，不加 class。既有断言按
      `class="note pnode"[^>]*` 与 .pv-row / .pv-grid 这些类名查形状，
      往 className 里塞一个字会把它们整片打瞎。
   3) 不重新渲染。选中只改属性：重画一次画布会顺手把焦点、滚动位置、
      用户刚展开/折起的块全抖一遍，而选中是一个纯粹的视觉反馈。 */
var selUid = null;

function selectBlock(uid) {
  if (uid && !nodeByUid(uid)) { return; }     // 点了已经不在画布上的块：不做声
  selUid = (selUid === uid) ? null : uid;      // 再点一次 = 取消选中
  paintSelection();
  setStatus(selUid
    ? ("已选中「" + nodeByUid(selUid).label + "」：左边预览里那一圈是它占的地方")
    : "已取消选中");
}

function clearSelection() {
  if (!selUid) { return; }
  selUid = null;
  paintSelection();
}

/* 把选中态刷到 DOM 上。只动 data-sel，其它一律不碰。 */
function paintSelection() {
  var c = el("canvas");
  if (c) {
    var boxes = c.querySelectorAll(".pnode[data-uid]");
    var i;
    for (i = 0; i < boxes.length; i++) {
      mark(boxes[i], selUid && boxes[i].dataset.uid === selUid);
    }
    // 容器外面那圈分组框也要跟上：右栏的 .pgroup 才是「这一整块」的边界，
    // 只描标题行的话，选中一个装着五块东西的容器，框出来的却只有一行。
    var grps = c.querySelectorAll(".pgroup[data-owner]");
    for (i = 0; i < grps.length; i++) {
      mark(grps[i], selUid && grps[i].dataset.owner === selUid);
    }
  }
  var p = el("preview");
  if (!p) { return; }
  var pvs = p.querySelectorAll("[data-pvuid]");
  for (var j = 0; j < pvs.length; j++) {
    mark(pvs[j], selUid && pvs[j].dataset.pvuid === selUid);
  }
}

function mark(e, on) {
  if (on) { e.dataset.sel = "1"; }
  else if (e.dataset.sel) { delete e.dataset.sel; }   // 摘干净：取消选中不留残留属性
}

/* 一个委托监听挂在两个栏上：点哪边都只改 selUid 这一个变量，
   两侧的视觉由 paintSelection 统一刷，所以同步是结构上的，不是两处各写一遍。 */
function bindSelection() {
  var canvas = el("canvas");
  if (canvas) {
    canvas.addEventListener("click", function (e) {
      // 按钮和输入框上的点击是它们自己的事（复制 / 删除 / 打字），
      // 顺手改选中会让「我想删这一块」变成「先选中再删」，一步变两步。
      if (e.target.closest("input, textarea, button")) { return; }
      var box = e.target.closest(".pnode[data-uid]");
      selectBlock(box ? box.dataset.uid : null);   // 点空白处 = 取消
    });
  }
  var pv = el("preview");
  if (pv) {
    pv.addEventListener("click", function (e) {
      // closest 认的是最近的祖先：点在某个子块上就选中那个子块，
      // 点在容器自己的空白处才选中容器。预览里容器真的是孩子们的祖先，
      // 所以这个判定同时解释了「整个容器区域含子块都被描边」。
      var n = e.target.closest("[data-pvuid]");
      selectBlock(n ? n.dataset.pvuid : null);
    });
  }
}

/* 业务块。缺了就直接说清楚该跑哪个脚本——沉默地只留 12 个原语，
   用户会以为「工作台就这些」，而真相是数据没生成。 */
function loadBlocks() {
  return getJSON("blocks.json").then(function (b) {
    if (!b || !b.blocks || !b.blocks.length) {
      throw new Error("blocks.json 结构不对（缺 blocks 或 blocks 是空的）");
    }
    blocksDoc = b;
    return b;
  });
}

function loadVocab() {
  return getJSON("vocabulary.json").then(function (v) {
    if (!v || !v.widgets || !v.rejected) {
      throw new Error("vocabulary.json 结构不对（缺 widgets / rejected）");
    }
    vocab = v;
    buildIconList();
    return loadBlocks().then(function () {
      renderVocabBar();
      renderRejected();
      renderElementIdHelp();
      renderUnmapped();
      renderCanvas();
      return v;
    });
  });
}

/* ---------------- 三个界面（对话 / 详情 / 设置）----------------

   真实面板顶上就是一根横排装着三个页签（ui.py 的 active_tab 枚举 +
   DEEPSEEK_PT_chat.draw 里的 layout.row(align=True) + prop(expand=True)），
   点哪个就画哪一份内容。这边照抄这个结构：三个子页签，三份独立积木列表。

   为什么必须是三份独立列表而不是一份加个筛选：一块积木的归属、内容、
   折叠状态都是搭界面时攒下来的半成品。共用一份的话，搭到一半想切到
   「设置」看看会变成什么样，半成品就跟着过去了——用户没法同时对照
   两个界面搭。 */
function renderSubtabs(host) {
  var row = document.createElement("div");
  row.className = "subtabs";
  row.id = "subtabs";
  var cap = document.createElement("b");
  cap.textContent = "要搭哪个界面：";
  row.appendChild(cap);
  TAB_ORDER.forEach(function (k) {
    var b = document.createElement("button");
    b.dataset.tab = k;
    b.textContent = TAB_LABELS[k];
    b.title = "「" + TAB_LABELS[k] + "」界面（" + boards[k].length + " 块积木）";
    b.className = (k === activeTab) ? "on" : "";
    b.onclick = function () { switchTab(k); };
    row.appendChild(b);
  });
  var cnt = document.createElement("span");
  cnt.className = "scope";
  cnt.textContent = "三个界面各有一份积木列表，互不干扰——切过去不会带走这一边的半成品。";
  row.appendChild(cnt);
  host.appendChild(row);
}

/* 切子页签。只换 proposal 指针 + 重画，不碰另外两份列表的内容。 */
function switchTab(name) {
  if (!boards[name]) { return; }
  activeTab = name;
  proposal = boards[name];
  // 换界面就等于换了一份画布，撤销不该跨界面生效。
  lastDeleted = null;
  clearDrag();
  // 选中同理：uid 是全局唯一的，但一份画布里未必真有那一块，
  // 硬留着会在新界面上留一个指向空气的描边。
  if (selUid && !nodeByUid(selUid)) { selUid = null; }
  renderCanvas();
  renderVocabBar();
  renderRejected();
  renderElementIdHelp();
  renderUnmapped();
  setStatus("已切到「" + TAB_LABELS[name] + "」界面（" + proposal.length + " 块积木）");
}

function renderVocabBar() {
  var host = el("vocab-bar");
  host.innerHTML = "";
  renderSubtabs(host);
  /* ---------------- 业务块（第一词汇表）----------------
     放在最上面、默认展开，是因为用户试了很多轮还是说「不会用」：
     根因是拿 UILayout 当词汇表。横排竖排、元素 ID、参数、归属这六个概念
     比它要解决的问题还难。低代码平台不会让你想 flexbox，它给你
     「客户表格」「审批表单」——所以这里给的是业务块，点一下就是插件里
     真实存在的整块代码。 */
  var h = document.createElement("b");
  h.textContent = "界面块（这个面板由哪几块组成 · 点一下加到画布最下面，搭好后可拖动换位）：";
  host.appendChild(h);
  var intro = document.createElement("div");
  intro.className = "scope";
  intro.textContent = (blocksDoc && blocksDoc.what)
    ? blocksDoc.what
    : "块 = 插件界面里真实存在的一整块东西。";
  host.appendChild(intro);
  var bcards = document.createElement("div");
  bcards.className = "wcards";
  bcards.id = "block-cards";
  ((blocksDoc && blocksDoc.blocks) || []).forEach(function (b) {
    bcards.appendChild(blockCard(b));
  });
  host.appendChild(bcards);

  /* ---------------- 高级：UILayout 原语（默认收起）----------------
     原语一块没删：容器能装东西、参数有白名单、降级清单——这些是
     「业务块装不下」时的退路。默认收起是因为大多数界面靠业务块就搭得起来，
     而把 12 张原语卡摆在第一屏正是「不会用」的来源之一。
     用 <details> 而不是 display:none：收起的只是视觉，DOM 里照样在，
     无头验收（--dump-dom）仍然拿得到那 12 个按钮。 */
  var det = document.createElement("details");
  det.id = "adv-primitives";
  det.className = "advanced";
  var sum = document.createElement("summary");
  sum.textContent = "高级：UILayout 原语（业务块搭不出来时用这一层）";
  det.appendChild(sum);
  var advHost = document.createElement("div");
  advHost.id = "adv-host";
  det.appendChild(advHost);
  host.appendChild(det);

  renderPrimitives(advHost);
  renderUndoBar();
}

/* 高级区里的原语控件架。原来 renderVocabBar 的整段搬到这里，逻辑一字未改
   ——12 张卡、示例面板按钮、props_scope 说明都在，只是挂载点从 vocab-bar
   换成了折叠区里的 adv-host。降级清单 / 元素 ID 说明 / 未收录能力仍然挂在
   vocab-bar 上（它们不是「控件」，是别的东西）。 */
function renderPrimitives(host) {
  var h = document.createElement("b");
  h.textContent = "可用控件（点一下落到画布最下面，搭好后可拖动换位）：";
  host.appendChild(h);
  // 每个控件一张卡：上面是迷你图示（看得见长什么样），下面是按钮。
  // 用户原话「横排竖排我还是不太能理解怎么使用」——光看名字看不出区别，
  // 必须先把形状画出来。
  var cards = document.createElement("div");
  cards.className = "wcards";
  vocab.widgets.forEach(function (w) {
    cards.appendChild(widgetCard(w));
  });
  host.appendChild(cards);
  var prow = document.createElement("div");
  prow.className = "rrow";
  var demoB = document.createElement("button");
  demoB.id = "demo-panel-btn";
  demoB.dataset.act = "demo-panel";
  demoB.textContent = "插入「" + TAB_LABELS[activeTab] + "」示例面板";
  demoB.title = "一套能直接抄进 ui.py 的「" + TAB_LABELS[activeTab] + "」界面骨架："
    + "从上到下每块都已填好可用的参数示例和真实元素 ID，容器块里的子积木"
    + "已经缩进装在里面。想先看「一个界面是怎么拼出来的」，点这个；"
    + "看完不满意再一块块删。";
  demoB.onclick = function () { insertExamplePanel(); };
  prow.appendChild(demoB);
  host.appendChild(prow);
  if (vocab.props_scope) {
    var sc = document.createElement("div");
    sc.className = "scope";
    sc.textContent = vocab.props_scope;
    host.appendChild(sc);
  }
}

/* 迷你图示。数据（vocabulary.json 的 demo 字段）只描述形状，这里负责画。
   之所以不把 HTML 字符串写死进数据：重跑 dev/build_vocabulary.py 时图示
   不会和控件定义脱节，而图示恰恰是最容易随控件改动而失真的那部分。
   色值一律走 style.css 的变量——那里已经钉死了「只许用 native_api.json 实测色板」。
   kind 决定形状：row/col/box/split/grid/panel/label/btn/prop/rule/gap。 */
function renderDemo(w) {
  var d = w.demo || {};
  var kind = d.kind || "gap";
  var box = document.createElement("div");
  box.className = "demo d-" + kind;
  box.dataset.dwkey = w.key;
  box.dataset.dkind = kind;
  if (kind === "rule" || kind === "gap") {
    var bar = document.createElement("i");
    bar.className = (kind === "rule") ? "d-rule" : "d-gap";
    box.appendChild(bar);
    return box;
  }
  var items = d.items || [];
  var icons = d.icons || [];
  var bare = d.bare || [];
  var cols = Number(d.cols) > 0 ? Number(d.cols) : 0;
  if (cols) {
    box.dataset.dcols = String(cols);
    /* 网格的列数必须真的由数据决定，所以这一种形状改用 CSS grid：
       flex + 百分比基准量不准（d-it 的 margin 与边框会把最后一个挤到下一行，
       数据写着 4 列、屏幕上却是 2 行），而 grid 的 repeat(n, minmax(0,1fr))
       就是「n 列、一行排得下 n 个」，cols 改成 2 它立刻退回两行。 */
    box.style.display = "grid";
    box.style.gridTemplateColumns = "repeat(" + cols + ", minmax(0, 1fr))";
  }
  if (d.groups) { box.dataset.dgroups = String(d.groups.length); }
  var left = Math.round((Number(d.factor) || 0.5) * 100);
  if (kind === "msgtxt") { return renderMsgBox(box, d, w); }
  if (kind === "composer") { return renderComposer(box, d, icons, left); }
  items.forEach(function (t, i) {
    box.appendChild(demoItem(t, kind, icons[i], left, cols, i, bare.indexOf(i) >= 0));
  });
  /* 双层盒：每组细节自己再一个盒，标题 + 那一串按钮都装在里面。
     外面那个盒已经由 kind 画出来了（这里是 box），所以这里只补里层。
     按钮**字少就横排并排**（详见 demoGroup 的注释），超过 OPT_WRAP_MAX 个
     才退回竖排——预览能量宽度，Blender 那边量不了，所以这个折中由预览替它做。 */
  (d.groups || []).forEach(function (g) {
    var gb = document.createElement("div");
    gb.className = "d-group";
    gb.dataset.dgtitle = g.title || "";
    gb.dataset.dflow = ((g.items || []).length > OPT_WRAP_MAX) ? "col" : "wrap";
    var gt = document.createElement("i");
    gt.className = "d-gtitle";
    if (g.icon) {
      var gi = document.createElement("b");
      gi.className = "d-ic";
      gi.textContent = g.icon;
      gt.appendChild(gi);
    }
    var gtx = document.createElement("span");
    gtx.className = "d-tx";
    gtx.textContent = g.title || "";
    gt.appendChild(gtx);
    gb.appendChild(gt);
    (g.items || []).forEach(function (t, i) {
      gb.appendChild(demoItem(t, "btn", (g.item_icons || [])[i], 0, 0, i));
    });
    box.appendChild(gb);
  });
  if (kind === "panel") {
    var sub = document.createElement("i");
    sub.className = "d-sub";
    sub.textContent = "▾";
    box.appendChild(sub);
  }
  return box;
}

/* ---- 你说的话：一个盒 + 可折叠 ----
   .demo 自己就是那个气泡盒，所以里面**不再套盒子**：文字是一个没有边框的
   .d-msgtext。上一版走 d-box，盒里又出来一个带边框的方块，两层框套着——
   用户点名说「一个盒，到此为止」。

   盒宽 = 预览容器的宽度，文字按盒内宽度折行：不给 .demo 写死宽度、不做
   窄栏、不加左右外边距。把面板拉宽，每一行的字就变多——这正是用户要的
   「文字宽度跟盒宽度一样」。唯一的内边距是盒主题自带的那点 padding。

   形态跟 Blender 侧的原生折叠一致：默认**展开**（折叠是给长提示词用的，
   不是默认藏起来）；收起时只剩一行标题（首句摘要 + 总字数），展开/收起
   按钮在**右下角**（Blender 那边是 layout.panel 的标题行 + 原生箭头）。 */
var FOLD_CHARS = 20;
/* 一组细节里的选项超过这么多个才退回一个一行。选项字通常很短
   （「选择：经典直筒微收口（推荐）」这种），一个占满一整行会把面板拉长；
   但数量一多就并排不下了，所以留这道闸。
   插件那边（ui.py 的 too_wide）用的是「>3 个或标签总字数 >22 就竖排」——
   它量不到像素只能估，这里量得到，所以只看个数。真要两边完全一致，
   把这个数改成 3 就与 ui.py 对齐了。 */
var OPT_WRAP_MAX = 3;

/* 收起时留在标题行里的摘要：首句 + 总字数。没有句号就切不出首句，
   这时退回「前 FOLD_CHARS 个字 + 省略号」。两种情况都带总字数——
   后面的正文是被藏起来了，所以那个省略号不是修辞，是实话。 */
function foldSummary(full) {
  var m = full.match(/^[^。！？]*[。！？]/);
  var head = m ? m[0] : (full.length > FOLD_CHARS ? full.slice(0, FOLD_CHARS) : full);
  return head + "…（共 " + full.length + " 字）";
}

function renderMsgBox(box, d, w) {
  var full = String((d.items || [])[0] || "");
  /* 默认展开：只有明确存了 false 才折着。写反了（!!msgOpen）的话，
     新插入的气泡一律是折着的，用户看到的第一眼就是一行摘要。 */
  var open = !(w.node && w.node.msgOpen === false);
  var txt = document.createElement("i");
  txt.className = "d-msgtext" + (open ? "" : " folded");
  txt.dataset.dmsglen = String(full.length);
  txt.textContent = open ? full : foldSummary(full);
  box.appendChild(txt);
  if (full.length <= FOLD_CHARS) { return box; }
  var tg = document.createElement("i");
  tg.className = "d-msgfold" + (open ? " open" : "");
  tg.dataset.dmsgfold = open ? "1" : "0";
  tg.textContent = open ? "▾ 收起" : "展开全文 ▸";
  /* 状态存在积木上（node.msgOpen），不是存在这个元素上：重画一次就没了，
     导出时也要跟着它走（见 pyBizLines 的 open_default）。 */
  tg.addEventListener("click", function (ev) {
    ev.stopPropagation();
    if (!w.node) { return; }
    w.node.msgOpen = !w.node.msgOpen;
    renderCanvas();
  });
  box.appendChild(tg);
  return box;
}

/* ---- 对话输入区：标签与输入框合成一处 ----
   上一版是「标签 + 高度滑块」一行、输入框下一行。那个「高度 3」的滑块已经
   按用户要求删掉（高度由输入框自己的多行决定），标签于是直接压在输入框上面，
   两者同属一个盒、输入框摊满盒宽——不再有那条只为放数字而存在的行。 */
function renderComposer(box, d, icons, left) {
  (d.items || []).forEach(function (t, i) {
    box.appendChild(demoItem(t, "prop", icons[i], left, 0, i, true));
  });
  var tb = document.createElement("div");
  tb.className = "d-textbox";
  tb.dataset.dtextbox = "1";
  tb.textContent = d.textbox || "";
  box.appendChild(tb);
  return box;
}

/* 一个条目方块。图标名照样照印（离线没有图标资源），而且**永远在**——
   面板窄的时候 Blender 那边只剩图标，文字那边藏起来（style.css 的容器查询）。
   文字自己包一层 .d-tx：窄面板要 display:none 的是**文字**，图标得留着。

   bare 为真时这一格不是控件，而是**盒里的正文**（「正在做什么」那句、
   「输入建模指令:」那个标签）：不画边框也不画底色，直接躺在盒里。
   画成带边框的小方块就是「盒里又套了一个盒」——用户点名要拿掉的那一层。
   这里用 data-dbare 而不是加一个 class：dev/test_proposal_blocks.py 的
   dom_biz_demo_items 是按字面串 'class="d-it"' 数方块数的，多一个类名就数不到。 */
function demoItem(t, kind, icon, left, cols, i, bare) {
  var it = document.createElement("i");
  it.className = "d-it";
  if (bare) { it.dataset.dbare = "1"; }
  if (icon) {
    var ic = document.createElement("b");
    ic.className = "d-ic";
    ic.textContent = icon;
    it.appendChild(ic);
  }
  var tx = document.createElement("span");
  tx.className = "d-tx";
  tx.textContent = t;
  it.appendChild(tx);
  // 分栏与网格靠内联宽度画出来：比例是数据给的，代码只负责把它变成宽度。
  // 这里不写颜色，色值由 style.css 的变量统一管。
  if (kind === "split") {
    it.style.flex = "0 0 " + (i === 0 ? left : (100 - left)) + "%";
  } else if (kind === "grid") {
    /* 网格交给容器（上面那段 grid-template-columns）分列，方块本身不再自带
       基准宽度：带基准的那套 flex 量出来会差几像素而折行。 */
    it.style.minWidth = "0";
    it.dataset.dcell = String(i);
  }
  return it;
}

/* ---------------- 业务块 ----------------
   一张业务块卡 = 一张图示 + 一个名字 + 一句话「它是什么、什么时候出现」
   +（有多样式时）一个变体下拉 + 一个「加进去」按钮。

   为什么卡片上还带变体下拉：状态提示条有四种样子（忙碌 / 待批准 /
   做到一半 / 失败），它们在 ui.py 里就是四段不同的代码。用户要的
   「失败那一条长什么样」不是改文案能改出来的，所以这是一个选择，不是一个输入框。 */
function blockByKey(k) {
  var bs = (blocksDoc && blocksDoc.blocks) || [];
  for (var i = 0; i < bs.length; i++) {
    if (bs[i].key === k) { return bs[i]; }
  }
  return null;
}

function variantOf(b, vkey) {
  var vs = (b && b.variants) || [];
  for (var i = 0; i < vs.length; i++) {
    if (vs[i].key === vkey) { return vs[i]; }
  }
  return (b && b.variants && b.variants[0]) ? b.variants[0] : null;
}

function blockCard(b) {
  var card = document.createElement("div");
  card.className = "wcard bcard";
  card.dataset.bcardFor = b.key;
  card.dataset.tab = b.tab;
  // 图示复用原语那套渲染器：形状语言只有一套（row/col/box/grid/prop…），
  // 两处各画一套只会让用户以为它们是两回事。
  card.appendChild(renderDemo({ key: b.key, demo: b.demo }));
  var btx = document.createElement("button");
  btx.dataset.bkey = b.key;
  btx.textContent = b.label;
  btx.title = "点一下加到画布最下面；搭好后按住积木上的空白处可拖动换位\n" +
    b.what + "\n（这个界面块对应的代码就是插件 ui.py 里现成的那一段，"
    + "导出时原样带走，不会被重新翻译）";
  btx.onclick = function () { addBizBlock(b); };
  card.appendChild(btx);
  var tab = document.createElement("span");
  tab.className = "btab";
  tab.textContent = TAB_LABELS[b.tab] || b.tab;
  card.appendChild(tab);
  var what = document.createElement("div");
  what.className = "wnote";
  what.textContent = b.what;
  card.appendChild(what);
  if ((b.variants || []).length > 1) {
    var sel = document.createElement("select");
    sel.className = "pvar";
    sel.dataset.bvar = b.key;
    sel.title = "这一块有几种样子。选中的那种决定导出哪一段代码——"
      + "它们在插件里本来就是不同的代码。";
    b.variants.forEach(function (v) {
      var o = document.createElement("option");
      o.value = v.key;
      o.textContent = v.label;
      sel.appendChild(o);
    });
    sel.value = b.default_variant;
    /* 换下拉就换掉这张卡的图示与说明：卡片得先让人看清「选中的那款长什么样」，
       否则这段 UI 只是让人先插一块再回头改。 */
    var vw = document.createElement("div");
    vw.className = "wnote";
    sel.onchange = function () {
      var vv = variantOf(b, sel.value);
      if (!vv) { return; }
      var old = card.querySelector(".demo");
      if (old) { card.replaceChild(renderDemo({ key: b.key, demo: vv.demo }), old); }
      vw.textContent = vv.what;
    };
    vw.textContent = variantOf(b, b.default_variant).what;
    card.appendChild(sel);
    card.appendChild(vw);
    /* 插入按钮读下拉当前值。放在 select 之后，所以「选失败 → 加一块」
       就是连着两下，不用先去别处改这块的设置。 */
    btx.onclick = function () { addBizBlock(b, sel.value); };
  }
  return card;
}

/* 插入一块业务块。它只有五样东西可改：变体、几处文案、一个备注名（元素 ID）、
   自己的注解——外加通用的拖动排序 / 复制 / 删除。
   没有参数框、没有归属、没有子块：这一块在插件里就是完整的一段，
   让用户「往里再塞点东西」只会导出 Blender 那边写不出来的代码。 */
function addBizBlock(b, vkey) {
  var v = variantOf(b, vkey || b.default_variant);
  proposal.push({
    uid: nextUid(),
    parent: null,
    wkey: "",
    bkey: b.key,
    bvar: v ? v.key : (b.default_variant || ""),
    btexts: {},
    label: b.label,
    uiloayout: "",
    allowed_props: [],
    blocked_props: [],
    params: "",
    /* 元素 ID 变成可选的「备注名」，默认按序号自动生成。不填照样能导出——
       它只影响导出的注释，不影响代码。 */
    id: autoNoteName(b.label),
    note: "",
    content: {},
    errors: [],
    expanded: false,
    downgraded: false
  });
  renderCanvas();
}

/* 自动备注名：同一块插第几块就叫什么（块1 / 块2 / 块3…）。
   用户不填也能导出，所以这个名字只是「别忘了这块叫什么」的兜底。 */
function autoNoteName(label) {
  var n = proposal.filter(function (x) { return x.label === label; }).length + 1;
  return label + n;
}

/* 画布上的一块业务块。和 renderNode 的差别就是「变简单」那几处：
   没有参数框、没有归属下拉、没有移入/移出、没有子块区；
   多出来的是变体下拉与这一块能改的那几处文案。 */
function renderBizNode(n) {
  var b = blockByKey(n.bkey);
  var box = document.createElement("div");
  box.className = "note pnode bnode";
  box.setAttribute("draggable", "true");
  box.dataset.parent = "";
  box.dataset.idx = String(idxByUid(n.uid));
  box.dataset.uid = n.uid;
  box.dataset.bkey = n.bkey;
  box.dataset.bvar = n.bvar || "";
  box.dataset.downgraded = "0";
  box.dataset.status = "ok";
  box.dataset.errors = "0";
  box.dataset.expanded = n.expanded ? "1" : "0";

  var head = document.createElement("div");
  head.className = "phead";
  var grip = document.createElement("span");
  grip.className = "drop-handler";
  grip.textContent = "⋮⋮";
  grip.title = "按住这块积木的空白处拖动，可以换位置";
  head.appendChild(grip);
  var tag = document.createElement("span");
  tag.className = "ptag";
  tag.textContent = b ? (TAB_LABELS[b.tab] || b.tab) + " · 界面块" : "界面块";
  head.appendChild(tag);
  var nm = document.createElement("b");
  nm.textContent = n.label;
  head.appendChild(nm);
  var code = document.createElement("code");
  code.textContent = b ? (b.variants.length + " 种样式") : "";
  head.appendChild(code);
  head.appendChild(bizChip("fold", n.uid, n.expanded ? "收起" : "展开",
    n.expanded ? "把改文案 / 备注名这两样折起来" : "展开这一块，改文案与备注名",
    function () { n.expanded = !n.expanded; renderCanvas(); }));
  head.appendChild(bizChip("dup", n.uid, "复制", "原地复制一块（副本身份独立）",
    function () { dupNode(idxByUid(n.uid)); }));
  head.appendChild(bizChip("del", n.uid, "删除", "删掉这块积木", function () {
    delNode(idxByUid(n.uid));
  }, "chip bad"));
  box.appendChild(head);

  if (!n.expanded) { return box; }

  // 变体下拉：放在最上面，因为换变体会换掉下面所有可改文案的位置。
  if (b && (b.variants || []).length > 1) {
    var row = document.createElement("div");
    row.className = "crow";
    var lab = document.createElement("span");
    lab.className = "clab";
    lab.textContent = "样式";
    row.appendChild(lab);
    var sel = document.createElement("select");
    sel.className = "pin psel";
    sel.dataset.field = "bvar";
    sel.dataset.uid = n.uid;
    b.variants.forEach(function (v) {
      var o = document.createElement("option");
      o.value = v.key;
      o.textContent = v.label;
      sel.appendChild(o);
    });
    sel.value = n.bvar;
    sel.onchange = function () {
      n.bvar = sel.value;
      // 换变体就把已改文案清掉：那些文案是针对旧变体里那句话的，
      // 带过去会让导出的代码里出现「两段各改了一半」的句子。
      n.btexts = {};
      renderCanvas();
    };
    row.appendChild(sel);
    var vw = document.createElement("div");
    vw.className = "wnote";
    var vv = variantOf(b, n.bvar);
    vw.textContent = vv ? vv.what : "";
    row.appendChild(vw);
    box.appendChild(row);
  }

  // 可改文案：只给当前变体里真的出现的那些槽（busy 里没有「已经做了：」）。
  var v = b ? variantOf(b, n.bvar) : null;
  var src = v ? String(v.ui_py) : "";
  (b && b.slots || []).forEach(function (s) {
    if (src.indexOf(s.literal) < 0) { return; }
    var wrap = document.createElement("div");
    wrap.className = "crow";
    var l2 = document.createElement("span");
    l2.className = "clab";
    l2.textContent = s.label;
    wrap.appendChild(l2);
    var inp = document.createElement("input");
    inp.className = "pin";
    inp.dataset.field = "btext";
    inp.dataset.uid = n.uid;
    inp.dataset.slot = s.name;
    inp.placeholder = "改这里只会改代码里那一句文案";
    inp.value = (n.btexts && n.btexts[s.name] != null) ? n.btexts[s.name] : s.text;
    inp.oninput = function () {
      n.btexts = n.btexts || {};
      if (inp.value === s.text) { delete n.btexts[s.name]; }
      else { n.btexts[s.name] = inp.value; }
      savePlan();
      renderPyOut();
    };
    wrap.appendChild(inp);
    box.appendChild(wrap);
  });

  var idIn = document.createElement("input");
  idIn.className = "pin";
  idIn.dataset.field = "id";
  idIn.dataset.uid = n.uid;
  idIn.placeholder = "备注名（可空，不填也能导出）";
  idIn.title = "只是导出里那行注释里写的名字，方便你回头对上代码。\n"
    + "不填不影响导出——这一块本来就是插件里现成的一段。";
  idIn.value = n.id;
  idIn.oninput = function () { n.id = idIn.value; savePlan(); renderPyOut(); };
  box.appendChild(idIn);

  var ta = document.createElement("textarea");
  ta.className = "pnote";
  ta.dataset.field = "note";
  ta.dataset.uid = n.uid;
  ta.placeholder = "这块要做什么？为什么？";
  ta.value = n.note;
  ta.oninput = function () { n.note = ta.value; savePlan(); renderPyOut(); };
  box.appendChild(ta);
  return box;
}

function bizChip(act, uid, text, title, fn, cls) {
  var b = document.createElement("button");
  b.className = cls || "chip";
  b.dataset.act = act;
  b.dataset.uid = uid;
  b.textContent = text;
  b.title = title;
  b.onclick = fn;
  return b;
}

function widgetCard(w) {
  var card = document.createElement("div");
  card.className = "wcard";
  card.dataset.cardFor = w.key;
  card.appendChild(renderDemo(w));
  var b = document.createElement("button");
  // data-wkey 必须是第一个属性：既有断言按 `<button data-wkey="..." title="...">`
  // 的形状匹配按钮标题，插在前面就会把它们全打瞎。
  b.dataset.wkey = w.key;
  b.title = "点一下加到画布最下面；搭好后按住积木上的空白处可拖动换位\n" +
    w.uiloayout +
    (w.allowed_props.length ? "\n可用参数：" + w.allowed_props.join(", ") : "\n无参数") +
    (w.props_example ? "\n参数示例（可原样粘进参数框）：" + w.props_example : "") +
    (w.props_hint ? "\n照着写：" + w.props_hint : "") +
    (w.blocked_props.length ? "\n被拦参数：" + w.blocked_props.join(", ") : "") +
    (w.note ? "\n" + w.note : "");
  b.textContent = w.label;
  b.onclick = function () { addWidget(w); };
  card.appendChild(b);
  if (w.note) {
    var nt = document.createElement("div");
    nt.className = "wnote";
    nt.textContent = w.note;
    card.appendChild(nt);
  }
  return card;
}

/* 图标候选表：一个 <datalist>，喂给内容输入框里的图标框。
   名册来自 vocabulary.json 的 icons（dev/build_vocabulary.py 从
   native_api.json 的实测枚举里抄下来的 1033 个），不是图标库、不是图片——
   离线双击直开，什么外部资源都不许引。建一次就够，后面复用同一个节点。 */
function buildIconList() {
  var old = document.getElementById("pv-icon-list");
  if (old && old.parentNode) { old.parentNode.removeChild(old); }
  var dl = document.createElement("datalist");
  dl.id = "pv-icon-list";
  dl.dataset.iconcount = String(((vocab && vocab.icons) || []).length);
  (vocab.icons || []).forEach(function (name) {
    var o = document.createElement("option");
    o.value = name;
    dl.appendChild(o);
  });
  document.body.appendChild(dl);
}

function widgetByKey(k) {
  var ws = (vocab && vocab.widgets) || [];
  for (var i = 0; i < ws.length; i++) {
    if (ws[i].key === k) { return ws[i]; }
  }
  return null;
}

/* 一键插入一套能直接抄的面板。数据在 vocabulary.json 的 example_panels 里
   （对话 / 详情 / 设置各一套），每块都带真实的参数示例与元素 ID——
   用户点开任一块，看到的就是成品，而不是一堆空输入框。

   按当前子页签取对应那套：对话沿用原来那 8 块，详情与设置是另两套，
   内容各自照着真实面板（ui.py 的 draw_detail_content / draw_settings_content）
   的结构写的，不是把对话那套换个名字。

   嵌套关系在 vocabulary.json 的 example_panel_parents 里，是一张
   「块下标 -> 父块下标」的表（父下标为 "-1" 或缺省 = 顶层）。按下标而不是
   按 wkey 指父：一套面板里常有多个同 wkey 的容器（对话面板有根竖排 chat.stream，
   也有 chat.options 那个竖排），按 wkey 找会挂到最靠后的那个上去——
   挂错容器在预览里几乎看不出来，只会觉得「排版怪怪的」。
   必须两遍：先把块全插进去拿到 uid，再按下标挂 parent——一遍做完的话，
   挂的时候父块的 uid 还不存在。 */
function insertExamplePanel() {
  var all = (vocab && vocab.example_panels) || {};
  var p = all[activeTab] || (vocab && vocab.example_panel);
  if (!p || !p.blocks || !p.blocks.length) {
    setStatus("vocabulary.json 里没有「" + (TAB_LABELS[activeTab] || activeTab) +
      "」的示例面板，先重跑 dev/build_vocabulary.py");
    return;
  }
  var parentMap = (vocab && vocab.example_panel_parents &&
                   vocab.example_panel_parents[activeTab]) || {};
  var n = 0;
  var made = [];
  p.blocks.forEach(function (b, i) {
    var node = addExampleBlock(b);
    if (!node) { return; }
    n++;
    made.push({ spec: b, node: node, idx: i });
  });
  made.forEach(function (m) {
    var pi = parentMap[String(m.idx)];
    var host = (pi === undefined || pi === null || pi === "" || Number(pi) < 0)
      ? null : (made[Number(pi)] ? made[Number(pi)].node : null);
    m.node.parent = host ? host.uid : null;
  });
  renderCanvas();
  var nested = made.filter(function (m) { return !!m.node.parent; }).length;
  setStatus("已插入示例面板「" + (p.title || "") + "」" + n + " 块（其中 " + nested +
    " 块装在容器里）：" + (p.caption || ""));
}

function addExampleBlock(b) {
  var w = widgetByKey(b.wkey);
  if (!w) { return null; }   // 词汇表里没有这个控件：不插，也不让整批示例崩掉
  var n = {
    uid: nextUid(),
    parent: null,
    wkey: w.key,
    label: w.label,
    uiloayout: w.uiloayout,
    allowed_props: w.allowed_props,
    blocked_props: w.blocked_props,
    params: b.params || "",
    id: b.element_id || "",
    note: b.note || "",
    // 示例面板自带内容（否则插进来是一片空壳，预览看不出这是个界面）；
    // 万一数据里漏了，回落到起手内容，不留空。
    content: b.content || starterContent(w.key),
    errors: [],
    expanded: false,
    downgraded: false
  };
  // 走一次真判定：示例参数要是自己违规了，画布上立刻会标「违规」，
  // 而不是让人以为「示例都能用」是工作台在骗人。
  n.errors = validateWidget(w, splitParams(n.params));
  proposal.push(n);
  return n;
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
  b.title = lastDeleted && lastDeleted.nodes && lastDeleted.nodes.length
    ? "把刚删掉的「" + lastDeleted.nodes[0].label + "」" +
      (lastDeleted.nodes.length > 1 ? ("连同它里面的 " + (lastDeleted.nodes.length - 1) + " 块") : "") +
      "放回画布" +
      "（位置会尽量靠近删除处；要是删除之后又拖动过别的积木，就不一定还在原位）"
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

/* 「对应插件元素 ID」到底填什么。这个字段以前只有一个 (可选) 占位符，
   用户完全无从下手——它是提案里唯一需要用户自己发明名字的地方。
   一次说清三件事：它是什么、怎么命名、能不能留空。 */
function renderElementIdHelp() {
  var hlp = vocab && vocab.element_id_help;
  if (!hlp) { return; }
  var host = el("prop-notes");
  var wrap = document.createElement("div");
  wrap.id = "element-id-help";
  wrap.className = "note";
  var t = document.createElement("div");
  t.className = "pfb";
  t.textContent = hlp.title;
  wrap.appendChild(t);
  [hlp.what, hlp.naming, hlp.optional].forEach(function (line) {
    if (!line) { return; }
    var d = document.createElement("div");
    // 刻意不用 .perr：那是对着用户喊「✗ 拦截」的样式，而且既有断言按
    // class="perr" 的出现次数核对拦截条数——说明文字蹭这个类会把
    // 「有几条拦截」数错，让不相干的断言替说明文案背锅。
    d.className = "idline";
    d.textContent = line;
    wrap.appendChild(d);
  });
  if (hlp.examples && hlp.examples.length) {
    var ex = document.createElement("div");
    ex.className = "chips";
    ex.dataset.examples = hlp.examples.join(",");
    hlp.examples.forEach(function (e) {
      var c = document.createElement("span");
      c.className = "chip";
      c.textContent = e;
      ex.appendChild(c);
    });
    wrap.appendChild(ex);
  }
  host.appendChild(wrap);
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
    parent: null,
    wkey: w.key,
    label: w.label,
    uiloayout: w.uiloayout,
    allowed_props: w.allowed_props,
    blocked_props: w.blocked_props,
    props_example: w.props_example || "",
    props_hint: w.props_hint || "",
    params: "",
    id: "",
    note: "",
    // 起手内容：空按钮定不了形，第一块就写上能看懂的话（发送指令 / 输入建模指令…）。
    content: starterContent(w.key),
    errors: [],
    expanded: false,   // 默认折叠：三块输入框不在 DOM 里，积木只占一行
    downgraded: false
  });
  renderCanvas();
}

function addRejected(r) {
  // 降级项不开放参数输入：它是「这条原需求做不到 + 这样改」的记录，
  // 不是可拼装的控件，硬塞参数进去只会让人以为能落笔。
  proposal.push({
    uid: nextUid(),
    parent: null,
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
    expanded: false,
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
  /* 拦截时自动展开，把违规摊开给用户看。
     注意是「把状态置为展开」，不是在渲染时拿 errors.length 强行盖掉显示状态：
     后者会让「一有错就弹开」变成不可逆的——用户收起之后，下一次 renderCanvas
     又给它弹回去，没人能把它折上。写成状态赋值就只是「第一次拦到时帮他打开」，
     之后点「收起」是真的收得起来。 */
  if (n.errors.length) { n.expanded = true; }
  // 参数每敲一个键就要重算 chips 和拦截文案，而重算的代价是整块画布重建。
  // renderCanvas 负责把焦点和光标位置原样还回去，别在这里另想办法。
  renderCanvas();
}

/* 删一块。参数是数组下标（调用方当场就该知道位置），块本身的身份靠 uid 自保——
   剩下的积木不会被重新编号，删中间一块也不会把后面的焦点拽走。
   idx < 0 守卫不能省：idxByUid 未命中时返回 -1，而 proposal.splice(-1, 1)
   在 JS 里是合法的、会把最后一块静默删掉。今天点不出这个路径（闭包节点
   一定还在数组里），但拖拽排序一行就会踩到，所以与 dupNode 一样挡掉。

   删容器时连带删掉整棵子树（选项 A，不做「提升到顶层」）。理由：把子积木
   提升到顶层会让面板凭空多出一堆没人认领的控件——原来它们是「这段里的
   三行」，删掉这段之后它们就没有位置依据了。连带删 + 单步撤销一起做，
   子树是可逆的，所以这个选择不会造成不可恢复的数据损失。 */
function delNode(idx) {
  if (idx < 0) { return; }
  var victim = proposal[idx];
  if (!victim) { return; }
  // 撤销用：整棵子树原样存下来（含各自 uid 与 parent），而不是只记个名字。
  // 删除和复制两个按钮紧挨着、点错没有确认，误删的参数和标注就找不回来了。
  var uids = subtreeUids(victim.uid);
  var nodes = [];
  for (var k = 0; k < uids.length; k++) {
    var nn = proposal.filter(function (x) { return x.uid === uids[k]; })[0];
    if (nn) { nodes.push(nn); }
  }
  lastDeleted = { nodes: nodes, index: idx, parent: victim.parent || null };
  for (var i = nodes.length - 1; i >= 0; i--) {
    var at = idxByUid(nodes[i].uid);
    if (at >= 0) { proposal.splice(at, 1); }
  }
  renderCanvas();
  renderUndoBar();
  if (nodes.length > 1) {
    setStatus("已删除「" + victim.label + "」连同它里面的 " + (nodes.length - 1) + " 块");
  }
}

/* 单步撤销，不是撤销栈：只救最近一次删除，救完就作废。
   放回的是「原来那个对象」，所以 uid 一字不改——它是恢复，不是新建。
   子树按原顺序一并放回；万一原位置已经越界（后面又删过别的），夹到合法
   区间里即可，位置对不上也比数据丢了强。 */
function undoDelete() {
  if (!lastDeleted) { setStatus("没有可撤销的删除"); return; }
  var nodes = lastDeleted.nodes || [];
  var at = Math.max(0, Math.min(lastDeleted.index, proposal.length));
  for (var i = 0; i < nodes.length; i++) { proposal.splice(at + i, 0, nodes[i]); }
  var label = nodes.length ? nodes[0].label : "";
  lastDeleted = null;
  renderCanvas();
  renderUndoBar();
  setStatus("已撤销删除：「" + label + "」" + (nodes.length > 1 ?
    ("连同它里面的 " + (nodes.length - 1) + " 块") : "") + "回到第 " + (at + 1) + " 位");
}

/* 复制一块，副本紧跟原块。副本必须领新的 uid：沿用原 uid 的话，焦点保存、
   标注绑定、后续排序都会把两块当成同一块，改一块另一块跟着变。
   容器连同整棵子树一起复制，且子孙的 parent 改指到副本的新 uid——
   否则副本里的孩子还挂在原件底下，改一块动两处。 */
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
  /* expanded 走浅拷贝，即「复制当前这块的样子」——原块折着、副本也折着，
     原块开着、副本也开着。之所以不强制复位：复制的意义是「再来一块一样的」，
     折叠态也是这块的一部分。强制 copy.expanded = false 的话，复制一块配好的
     积木会把刚抄过来的参数又藏回折叠态（用户得多点一次才看得见自己复制了什么），
     而复制一块刚建、还没配置的积木反倒会弹开——两头的直觉都是反的。 */
  var insertAt = idx + 1;

  var uids = subtreeUids(src.uid);
  var uidMap = {};
  var clones = [];
  for (var c = 0; c < uids.length; c++) {
    var node = proposal.filter(function (x) { return x.uid === uids[c]; })[0];
    if (!node) { continue; }
    var cl = {};
    for (var f in node) { if (node.hasOwnProperty(f)) { cl[f] = node[f]; } }
    cl.uid = nextUid();
    cl.errors = (node.errors || []).slice();
    uidMap[node.uid] = cl.uid;
    clones.push(cl);
  }
  // 第二遍统一改写 parent：必须等 uidMap 齐了才能改，
  // 否则孙块的 parent 会被指向一个还没定下来的 uid。
  clones.forEach(function (cl) {
    cl.parent = (cl.parent && uidMap[cl.parent]) ? uidMap[cl.parent] : (cl.parent || null);
  });
  for (var j = 0; j < clones.length; j++) { proposal.splice(insertAt + j, 0, clones[j]); }
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
  p.textContent = "点上面的界面块，它就落到画布最下面；搭好之后，按住积木上" +
    "按钮以外的空白处可以随时拖动换位，也可以复制一块、或删掉重来。" +
    "积木默认是折起来的，点「展开」才出现改文案与备注名。" +
    "积木从上到下的顺序，"+
    "就是插件里面板从上到下的顺序。挑不到想要的效果时，把下面折叠的" +
    "「高级：UILayout 原语」展开——做不到的东西都列在那儿，点它插入的是" +
    "降级方案，原需求会被标成做不到。搭好后切回镜像视图，对着真实截图比。";
  return p;
}

/* 画布按树递归渲染。顶层积木各自一块；容器积木额外带一个 .pgroup，
   它的孩子缩进画在那个分组框里——用户要能一眼看出「这几行是装在这个容器里的」，
   而不是左缩进几格就完事（光靠缩进，看不出边界在哪、拖起来也不知道能拖到哪）。

   为什么递归而不是先把树拍平成带 depth 的列表：拍平会让 .pnode 的文档顺序
   与数组顺序不一致，而既有断言逐位比对 DOM 里的 uid 顺序，嵌套一上来就全红。
   递归渲染时，兄弟的文档顺序仍等于数组顺序，只有跨层级时才出现父子关系。 */
function renderCanvas() {
  var host = el("canvas");
  var keep = captureFocus(host);
  host.innerHTML = "";
  renderPreview();
  if (!proposal.length) {
    host.appendChild(renderEmptyHint());
  } else {
    renderLevel(host, null);
  }
  restoreFocus(host, keep);
  // 两条都挂在重画之后：重画会把 DOM 全换一遍，先前打上的选中标记一律失效，
  // 不补这一笔就会「点一下选中，再改个字标记就没了」。
  paintSelection();
  savePlan();
  // 那段 ui.py 是从 proposal 推出来的，所以跟着画布一起重算：
  // 右边改一个字，下面那份草稿得当场跟着变，否则用户会照着一份过期的代码抄。
  renderPyOut();
}

/* 渲染一整层：parent 为 null 就是顶层，否则是那个容器里的孩子。

   容器这一层分两截，是为了让「树」这件事在界面上成立：
     .pgroup —— 整个分组框（带边框），装着容器自己的标题行 + 下面的 .pkids
     .pkids —— 只装孩子，左边一条竖线，每个孩子一条短横线接回竖线
   竖线从容器标题行下方开始，而不是从分组框最顶上：一根线从上贯到底，
   会被读成「这个容器自己也是别人的孩子」。

   为什么把 children 多包一层 div：树线要有个只属于「孩子区」的元素，
   才能把竖线画在标题行下面。写在 .pgroup 自己身上做不到——
   它的上边缘就是容器顶边。 */
function renderLevel(host, parentUid) {
  nodesAtDepth(parentUid).forEach(function (n) {
    var pair = renderNode(n);
    if (isContainer(n)) {
      var grp = document.createElement("div");
      grp.className = "pgroup";
      grp.dataset.parent = parentUid || "";
      // 数据属性写在 className 之后、其余属性之前：既有断言按
      // class -> draggable -> data-idx -> data-uid -> data-wkey 的顺序做正则匹配。
      grp.dataset.owner = n.uid;
      grp.appendChild(pair);
      var kids = document.createElement("div");
      kids.className = "pkids";
      kids.dataset.owner = n.uid;
      renderLevel(kids, n.uid);
      grp.appendChild(kids);
      host.appendChild(grp);
      return;
    }
    host.appendChild(pair);
  });
}

/* 渲染一块积木（不含它的孩子）。返回那个 .pnode 元素。
   抽成独立函数是因为树递归之后「画一块」这件事要能被单独调用——
   容器那层自己套一个 .pgroup 把孩子装进去。 */
function renderNode(n) {
  /* 业务块有自己的画法（renderBizNode）：它没有参数、没有归属、没有子块。
     这一句分派是两种块唯一的汇合点——往下所有既有代码都可以假定
     「拿到的是一块 UILayout 原语」。 */
  if (n.bkey) { return renderBizNode(n); }
  var i = idxByUid(n.uid);   // 仅供调试看顺序，任何定位都不许用它
  var box = document.createElement("div");
    box.className = "note pnode" + (n.downgraded ? " down" : (n.errors.length ? " blocked" : ""));
    box.setAttribute("draggable", "true");   // 必须在 dataset 之前写，否则会插到
                                            // 既有属性中间，打断按顺序匹配的 DOM 断言
    // data-parent 插在 data-uid 之前：既有断言里 data-uid -> data-wkey ->
    // data-downgraded -> data-status -> data-errors -> data-rkey 是一串连续的
    // 正则（dom_all_widgets_ok / dom_all_downgraded 都这么写），插在中间会全打瞎。
    // 放在 data-uid 之前是安全的：那些正则都以 `class="note pnode"[^>]*` 起头，
    // 中间多几个属性不影响匹配。
    box.dataset.parent = n.parent || "";
    box.dataset.idx = String(i);
    box.dataset.uid = n.uid;
    box.dataset.wkey = n.wkey;
    box.dataset.downgraded = n.downgraded ? "1" : "0";
    box.dataset.status = n.downgraded ? "downgraded" : (n.errors.length ? "blocked" : "ok");
    box.dataset.errors = String(n.errors.length);
    if (n.rkey) { box.dataset.rkey = n.rkey; }
    // data-expanded 必须写在最后：既有断言按 data-errors（末尾）或
    // data-errors -> data-rkey 的顺序做正则匹配，插在中间会把它们打断。
    box.dataset.expanded = n.expanded ? "1" : "0";

    var head = document.createElement("div");
    head.className = "phead";
    /* 拖拽手柄。整个 .pnode 都可拖（按钮和输入框上按下除外），
       手柄只是「这里能拖」的视觉承诺——没有它，积木看着像个表单卡片，
       用户不会想到可以换位。 */
    var grip = document.createElement("span");
    grip.className = "drop-handler";
    grip.textContent = "⋮⋮";
    grip.title = "按住这块积木的空白处拖动，可以换位置";
    head.appendChild(grip);
    var tag = document.createElement("span");
    tag.className = "ptag";
    tag.textContent = n.downgraded ? "已降级" : (n.errors.length ? "违规 " + n.errors.length + " 项" : "合法");
    head.appendChild(tag);
    var nm = document.createElement("b");
    nm.textContent = n.label;
    head.appendChild(nm);
    /* 容器标题上标子块数。0 也照样标：空容器和「没渲染出来」长得一模一样，
       只标非 0 的话，空容器在画布上看起来就像一个装不下东西的死块。
       数字直接取 childrenOf（按 parent 过滤真数组），不是拿 DOM 数一遍。 */
    if (isContainer(n)) {
      var kidsN = childrenOf(n.uid).length;
      var cnt = document.createElement("span");
      cnt.className = "pcount";
      cnt.dataset.kids = String(kidsN);
      cnt.textContent = "· " + kidsN;
      cnt.title = kidsN
        ? ("这个容器里装着 " + kidsN + " 块：画在下面那个框里")
        : "空容器：还没有子块。拖一块进来，或点「移入上一个容器」把它挂进去";
      head.appendChild(cnt);
    }
    var code = document.createElement("code");
    code.textContent = n.uiloayout;
    head.appendChild(code);

    /* 移入上一个容器 / 移出上一层。
       原来只有展开态里的「归属」下拉能换父级，而那要先把积木展开、
       再找到那一行、点开下拉——三下。改父级是搭界面的高频动作，
       埋在下面等于没有，所以直接摆到标题行上，一点就生效。

       没有可移入 / 可移出时是 disabled（压暗），不是消失：
       一个会忽然不见的按钮看起来像界面坏了，而「此刻没东西可移」是常态。 */
    var upUid = prevContainerUid(n.uid);
    var inB = document.createElement("button");
    inB.className = "chip pmove";
    inB.dataset.act = "in";
    inB.dataset.uid = n.uid;
    inB.textContent = "移入上一个容器";
    inB.disabled = !upUid;
    inB.title = upUid
      ? ("把这一块装进上面最近的容器「" + labelOfUid(upUid) + "」里")
      : "上面没有能装它的容器（叶子控件装不了东西，容器才装得了）";
    inB.onclick = function () { reparent(n.uid, upUid); };
    head.appendChild(inB);

    var outB = document.createElement("button");
    outB.className = "chip pmove";
    outB.dataset.act = "out";
    outB.dataset.uid = n.uid;
    outB.textContent = "移出上一层";
    outB.disabled = !n.parent;
    outB.title = n.parent
      ? ("把这一块从「" + labelOfUid(n.parent) + "」里拿出来，放回顶层")
      : "这一块已经在顶层了，没有上一层可退";
    outB.onclick = function () { reparent(n.uid, null); };
    head.appendChild(outB);

    /* 展开 / 收起。折叠时那三个输入框根本不进 DOM，画布才从「一张大表单」
       变回「一列积木」；细节点开才展开。
       按钮直接翻转 n.expanded——它和「被拦截所以自动展开」是两条独立的路：
       setParams 只会把它置成 true，不会替用户再按回去。 */
    var foldB = document.createElement("button");
    foldB.className = "chip";
    foldB.dataset.act = "fold";
    foldB.dataset.uid = n.uid;
    foldB.textContent = n.expanded ? "收起" : "展开";
    foldB.title = n.expanded
      ? "把参数 / 元素 ID / 备注这三个输入框折起来"
      : "展开这一块，改参数、对应插件元素 ID、想做什么";
    foldB.onclick = function () { n.expanded = !n.expanded; renderCanvas(); };
    head.appendChild(foldB);

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

    /* 降级块的理由两行不随折叠藏起来：它是「这条原需求做不到 + 这样改」的
       记录，不是待填的输入，藏起来等于让用户以为这块还没搭。 */
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
    }

    /* 以下全部只在展开时渲染。折叠态还留着标题行那个「违规 N 项」徽标，
       所以收起之后用户依然看得出这块被拦了，只是被拦的理由不占地方。 */
    if (!n.expanded) {
      return box;
    }

    if (!n.downgraded) {
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
      /* placeholder 里直接给可粘的示例。用户只看到一串允许的参数名时，
         无从判断「该写成什么样」；示例给错了比不给更糟，所以这一串是逐个
         在 native_api.json 与白名单上核过的（测试 dom_examples_no_intercept
         会把它真的敲进参数框验一遍）。 */
      pin.placeholder = "示例（可原样粘）：" +
        (n.props_example || "无参数") +
        "　｜只认 " + ((n.allowed_props || []).join(", ") || "无") +
        (n.props_hint ? "　｜照着写：" + n.props_hint : "");
      pin.title = n.props_hint
        ? "照着写成：" + n.props_hint + "\n只认：" +
          ((n.allowed_props || []).join(", ") || "无")
        : "本控件没有可用参数";
      pin.value = n.params;
      pin.oninput = function () { setParams(n, pin.value); };
      box.appendChild(pin);

      /* 积木的内容。与 params 分开：params 是「Blender 调用长什么样」，
         content 是「这块里写什么字」——预览只认后者。容器类控件
         （row/column/box/split/grid_flow/panel/separator/scale_y）没有内容，
         它们只分组或占位，所以这段对它们整段跳过。 */
      var spec = contentSpec(n.wkey);
      if (spec && spec.length) {
        var cwrap = document.createElement("div");
        cwrap.className = "pcontent";
        var ctit = document.createElement("div");
        ctit.className = "pfb";
        ctit.textContent = "这块里写什么（左边预览就照着画）：";
        cwrap.appendChild(ctit);
        spec.forEach(function (f) { cwrap.appendChild(contentInput(n, f)); });
        box.appendChild(cwrap);
      }
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
    var eh = (vocab && vocab.element_id_help) || {};
    idIn.placeholder = "对应插件元素 ID，可空" +
      (eh.examples && eh.examples.length ? "（例：" + eh.examples.join(" / ") + "）" : "");
    idIn.title = (eh.what || "") + "\n" + (eh.naming || "") + "\n" + (eh.optional || "");
    idIn.value = n.id;
    // 这里不重画画布（会把这个输入框本身换掉、光标跳走），但必须存盘：
    // 元素 ID 是标注与导出的挂钩，刷新丢了就等于用户白填。
    idIn.oninput = function () { n.id = idIn.value; savePlan(); };
    box.appendChild(idIn);

    var ta = document.createElement("textarea");
    ta.className = "pnote";
    ta.dataset.field = "note";
    ta.dataset.uid = n.uid;
    ta.placeholder = "想要什么？为什么？";
    ta.value = n.note;
    ta.oninput = function () { n.note = ta.value; savePlan(); renderPyOut(); };
    box.appendChild(ta);

    /* 归属下拉。这是换容器的主操作路径：拖拽只管同父级内换位，
       把一块搬进另一个容器得靠这里。放在展开态里、跟参数框排在一起——
       折叠时它不占地方，展开时它就在「这块是谁」旁边，一眼看懂。

       选项只有「（顶层）」和别的容器积木：叶子控件装不了东西，
       容器也不能选自己或自己的子孙（那会绕成圈，reparent 会挡）。 */
    var sel = document.createElement("select");
    sel.className = "pin psel";
    sel.dataset.field = "parent";
    sel.dataset.uid = n.uid;
    sel.title = "把这一块放进哪个容器里。拖拽只能和同一个容器里的积木换位，"
      + "换容器请用这里。";
    var topOpt = document.createElement("option");
    topOpt.value = "";
    topOpt.textContent = "（顶层）";
    sel.appendChild(topOpt);
    var myUids = subtreeUids(n.uid);
    proposal.forEach(function (c) {
      if (!isContainer(c) || myUids.indexOf(c.uid) >= 0) { return; }
      var o = document.createElement("option");
      o.value = c.uid;
      o.textContent = c.label + (c.parent ? "（在「" +
        ((proposal.filter(function (x) { return x.uid === c.parent; })[0] || {}).label || "")
        + "」里）" : "");
      sel.appendChild(o);
    });
    sel.value = n.parent || "";
    sel.onchange = function () { reparent(n.uid, sel.value || null); };
    var selWrap = document.createElement("div");
    selWrap.className = "crow";
    var selLab = document.createElement("span");
    selLab.className = "clab";
    selLab.textContent = "归属";
    selWrap.appendChild(selLab);
    selWrap.appendChild(sel);
    box.appendChild(selWrap);

    return box;
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
   #proposal-del / #proposal-dup 点真实的删除 / 复制按钮，核对块数与 uid 身份。
   #proposal-fold 点真实的展开按钮，走一遍「默认折叠 -> 展开 -> 收起 ->
   拦截自动展开 -> 还能再收起」，专治「一有错就永久弹开」。
   #proposal-examples 把 12 个控件的参数示例逐个敲进参数框，一条拦截都不许有。
   #proposal-panel 点真实的「插入示例面板」按钮，核对块数、uid 与参数合法性。 */
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
function foldButtonOf(wkey) {
  for (var i = 0; i < proposal.length; i++) {
    if (proposal[i].wkey !== wkey) { continue; }
    return el("canvas").querySelector('.pnode[data-uid="' + proposal[i].uid + '"] [data-act="fold"]');
  }
  return null;
}

function typeReport(wkey, text) {
  var lost = 0;
  // 积木默认折叠，参数框不在 DOM 里——先点「展开」再打字，走的就是
  // 用户自己要点的那一下，不走后门。
  if (!paramsInputOf(wkey)) {
    var fb = foldButtonOf(wkey);
    if (fb) { fb.click(); }
  }
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

  // --- 0) 按钮上按下不许触发拖拽 ---
  // 整块可拖是这一轮才放开的（不必瞄 ⋮⋮）。放开的前提就是把按钮排除掉：
  // 否则「复制」和「删除」点下去会变成一次拖拽，按钮等于废掉。
  var dupBtn = canvas.querySelector('.pnode [data-act="dup"]');
  fireDrag(dupBtn, "dragstart", 0, dt);
  var stateAfterBtn = String(dragState);
  var draggingAfterBtn = canvas.querySelectorAll(".pnode.dragging").length;
  clearDrag();

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

  var fwdOrder = uidListOf(proposal);
  var boxes = canvas.querySelectorAll(".pnode[data-uid]");
  var domUids = [];
  for (var i = 0; i < boxes.length; i++) { domUids.push(boxes[i].dataset.uid); }

  /* --- 4) reorderTo 自己的守卫：负的 toIdx ---
     拖拽路径上 dropIndexAt 只给 0..n，UI 永远走不到负数，所以这条路只能
     直接调 reorderTo 验——它本来就被明确导出为「拖拽与测试共用」的入口。
     不夹紧的话 splice(-1, 0, item) 会把最后一块静默插回倒数第二位，
     也就是「看起来什么都没动」——比报错更难发现。 */
  var guardBefore = uidListOf(proposal);
  var guardMoved = proposal[proposal.length - 1].uid;
  reorderTo(proposal.length - 1, -1);
  var guardAfter = uidListOf(proposal);
  var gBoxes = canvas.querySelectorAll(".pnode[data-uid]");
  var guardDom = [];
  for (var j = 0; j < gBoxes.length; j++) { guardDom.push(gBoxes[j].dataset.uid); }

  appendReport("drag-report", {
    beforeUids: before,
    stateAfterBtn: stateAfterBtn,
    draggingAfterBtn: String(draggingAfterBtn),
    lineSeen: String(lineSeen),
    lineAfterCancel: String(lineAfterCancel),
    draggingAfterCancel: String(draggingAfterCancel),
    stateAfterCancel: stateAfterCancel,
    orderAfterCancel: orderAfterCancel,
    lineAfterDrop: String(lineAfterDrop),
    stateAfterDrop: stateAfterDrop,
    afterUids: midOrder,
    afterFwdUids: fwdOrder,
    guardBeforeUids: guardBefore,
    guardMovedUid: guardMoved,
    guardAfterUids: guardAfter,
    guardDomUids: guardDom.join(","),
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

/* #proposal-fold：折叠 / 展开 / 拦截自动展开这三条规则一次跑完。
   每一步都用画布上真实的「展开」按钮点，并把「这块里到底有没有那几个输入框」
   连同 data-expanded 一起报出去——只报数组字段的话，「状态对了但 DOM 里
   根本没渲染输入框」照样全绿。
   取 label 是因为它有明确的 blocked 参数（size），造得出拦截。 */
function countFields(uid) {
  var box = el("canvas").querySelector('.pnode[data-uid="' + uid + '"]');
  if (!box) { return "?"; }
  return [box.querySelectorAll('[data-field="params"]').length,
          box.querySelectorAll('[data-field="id"]').length,
          box.querySelectorAll('[data-field="note"]').length,
          box.querySelectorAll(".perr").length,
          box.dataset.expanded].join("/");
}

function foldReport() {
  var canvas = el("canvas");
  var target = proposal.filter(function (x) { return x.wkey === "label"; })[0];
  if (!target) { setStatus("DEMO fold 没找到 label"); return; }
  var uid = target.uid;
  var foldBtn = canvas.querySelector('.pnode[data-uid="' + uid + '"] [data-act="fold"]');

  var before = countFields(uid);            // 默认折叠
  foldBtn.click();
  var opened = countFields(uid);            // 手动展开
  foldBtn.click();
  var recollapsed = countFields(uid);        // 手动收起
  setParams(target, "size");                // 拦截 -> 自动展开
  var afterBlock = countFields(uid);
  foldBtn.click();                          // 还能再收起来吗
  var afterCollapse = countFields(uid);

  appendReport("fold-report", {
    uid: uid,
    before: before,
    opened: opened,
    recollapsed: recollapsed,
    afterBlock: afterBlock,
    afterCollapse: afterCollapse,
    errorCount: String(target.errors.length),
    expandedNodes: String(canvas.querySelectorAll(".pnode[data-expanded='1']").length)
  });
  setStatus("DEMO fold 剩 " + proposal.length + " 块");
}

/* #proposal-examples：把每个控件的参数示例真的敲进参数框，核对一条拦截都不产生。
   走的是和用户一样的路径——点控件按钮 → 点「展开」→ 派发真的 input 事件，
   唯一没走的是逐字符（逐字符那条由 #proposal-typing 单独盯）。
   「示例给错了比不给更糟」：示例一旦违规，用户一粘贴就被拦，工作台等于在骗人。 */
function examplesReport() {
  var rows = [];
  var values = [];
  var covered = [];
  var bs = el("vocab-bar").querySelectorAll("button[data-wkey]");
  for (var i = 0; i < bs.length; i++) {
    var wkey = bs[i].dataset.wkey;
    var w = widgetByKey(wkey);
    if (!w) { rows.push(wkey + ":nowidget"); continue; }
    bs[i].click();
    var blk = null;
    for (var k = 0; k < proposal.length; k++) {
      if (proposal[k].wkey === wkey) { blk = proposal[k]; }
    }
    if (!blk) { rows.push(wkey + ":noblock"); continue; }
    if (!paramsInputOf(wkey)) { foldButtonOf(wkey).click(); }
    var inp = paramsInputOf(wkey);
    if (!inp) { rows.push(wkey + ":noinput"); continue; }
    var ex = w.props_example || "";
    inp.value = ex;
    inp.dispatchEvent(new Event("input", { bubbles: true }));
    /* 重渲染之后必须重新从文档里捞这块。
       inp 这时已经被 renderCanvas 摘下来了，读它身上的 dataset 只会拿到
       「改参数之前」的旧值——错误数永远是 0，示例给错了也照样全绿。
       那个被摘下来的节点上连 dataset.errors 都停留在上一次渲染。 */
    var live = el("canvas").querySelector('.pnode[data-uid="' + blk.uid + '"]');
    var liveInp = live ? live.querySelector('[data-field="params"]') : null;
    rows.push(wkey + ":" + (live ? live.dataset.errors : "?") + ":" +
      (live ? live.dataset.status : "?"));
    values.push(wkey + "=" + (liveInp ? liveInp.value : "?"));
    covered.push(wkey);
  }
  var boxes = el("canvas").querySelectorAll(".pnode[data-uid]");
  var uids = [];
  for (var j = 0; j < boxes.length; j++) { uids.push(boxes[j].dataset.uid); }
  appendReport("examples-report", {
    rows: rows.join("|"),
    values: values.join("|"),
    covered: covered.join(","),
    total: String(proposal.length),
    uids: uids.join(",")
  });
  var bad = rows.filter(function (r) { return !/:0:ok$/.test(r); });
  setStatus("DEMO examples " + rows.length + " 个示例，" + bad.length + " 个被拦");
}

/* #proposal-panel：点真实的「插入示例面板」按钮，核对块数、uid 身份、
   每块参数是否合法，以及有多少块带真实元素 ID。 */
function panelReport() {
  var btn = el("demo-panel-btn");
  var before = proposal.length;
  if (btn) { btn.click(); }
  var boxes = el("canvas").querySelectorAll(".pnode[data-uid]");
  var rows = [];
  var ids = [];
  proposal.forEach(function (n) {
    rows.push(n.wkey + ":" + n.errors.length + ":" + (n.params || "-"));
    if (n.id) { ids.push(n.id); }
  });
  var domUids = [];
  for (var i = 0; i < boxes.length; i++) { domUids.push(boxes[i].dataset.uid); }
  appendReport("panel-report", {
    before: String(before),
    after: String(proposal.length),
    domCount: String(boxes.length),
    domUids: domUids.join(","),
    rows: rows.join("|"),
    ids: ids.join(","),
    blockedNodes: String(el("canvas").querySelectorAll(".pnode.blocked").length)
  });
  setStatus("DEMO panel 插入 " + proposal.length + " 块");
}

/* ---------------- 界面预览（左栏） ----------------
   用户原话「左侧映射出来界面，右侧是积木」：右侧是零件表，左边必须把零件
   拼起来之后真正长什么样画出来——不画出来就永远搭不出一个界面。

   两条纪律：
   1) 从数据渲染，不拼 HTML 字符串。写死模板的话，积木数据一改预览就悄悄
      过期（迷你图示那条教训）。所以这里只有 createElement + className。
   2) 诚实。只画 Blender 真画得出来的东西，颜色只用 style.css 里那 23 个
      实测值。主题里没有红也没有绿，所以「有拦截 / 做不到」一律靠底色明度、
      边框、删除线表达，不靠颜色。 */

/* 每种控件的内容字段。容器类控件（只分组或占位）不在表里。 */
var CONTENT_SPEC = {
  row:      [{ field: "heading", label: "标题文字" }],
  column:   [{ field: "heading", label: "标题文字" }],
  label:    [{ field: "text", label: "文字" }, { field: "icon", label: "图标" }],
  operator: [{ field: "text", label: "按钮文字" }, { field: "icon", label: "图标" }],
  prop:     [{ field: "label", label: "属性名" }, { field: "value", label: "当前值" }],
  textbox:  [{ field: "placeholder", label: "占位提示" }, { field: "lines", label: "可见行数" }]
};

function contentSpec(wkey) { return CONTENT_SPEC[wkey] || null; }

/* 新积木的起手内容：空按钮没法定形，起手给一句能直接看懂的。
   文案来自 vocabulary.json 的 starter_content（数据在这里，界面只负责画）。 */
function starterContent(wkey) {
  var s = (vocab && vocab.starter_content) || {};
  var v = s[wkey];
  return v ? JSON.parse(JSON.stringify(v)) : {};
}

function contentInput(n, f) {
  var row = document.createElement("div");
  row.className = "crow";
  var lab = document.createElement("span");
  lab.className = "clab";
  lab.textContent = f.label;
  row.appendChild(lab);
  var inp = document.createElement("input");
  inp.className = "pin";
  // data-field 用 "c:" 前缀与 params / id / note 区分开：焦点保持是靠它找回来的，
  // 撞名会让用户改参数时焦点跳到内容框。
  inp.dataset.field = "c:" + f.field;
  inp.dataset.uid = n.uid;
  var v = (n.content || {})[f.field];
  inp.value = (v == null) ? "" : String(v);
  if (f.field === "icon") {
    inp.setAttribute("list", "pv-icon-list");
    inp.placeholder = "图标名（如 PLAY）";
    inp.title = "图标只能从 Blender 实测的 " +
      (((vocab && vocab.icons) || []).length || "?") + " 个图标名里挑：";
  } else if (f.field === "lines") {
    inp.placeholder = "3";
    inp.title = "Blender 里 textbox 的 initial_visible_lines，预览按它算高度";
  } else {
    inp.placeholder = f.label;
  }
  inp.oninput = function () { setContent(n, f.field, inp.value); };
  row.appendChild(inp);
  return row;
}

function setContent(n, field, raw) {
  n.content = n.content || {};
  if (field === "lines") {
    var v = parseInt(raw, 10);
    // 留空 / 敲错都当「没填」：预览回落到占位形状，而不是画出一个 0 高的框。
    n.content.lines = isNaN(v) || v < 1 ? 0 : v;
  } else {
    n.content[field] = raw;
  }
  renderCanvas();   // 连带重画预览：右边改一个字，左边当场变
}

/* 参数框按白名单只收参数名（columns=2 会被当自造参数拦下），所以取值解析
   必须容错：写了 =值 就用，没写就用该控件的惯用缺省值。 */
function paramValue(n, key, dflt) {
  var toks = splitParams(n.params);
  for (var i = 0; i < toks.length; i++) {
    if (toks[i] === key) { return dflt; }
    if (toks[i].indexOf(key + "=") === 0) { return toks[i].slice(key.length + 1); }
  }
  return null;
}

function hasParam(n, key) { return splitParams(n.params).indexOf(key) >= 0; }

function numParam(n, key, dflt) {
  var raw = paramValue(n, key, null);
  if (raw === null) { return dflt; }
  var v = parseFloat(raw);
  return isNaN(v) ? dflt : v;
}

/* 一个预览节点。pvEl 只做「建元素 + 挂 data-pv」，形状一律由 className 决定。 */
function pvEl(cls, kind) {
  var e = document.createElement("div");
  e.className = cls;
  e.dataset.pv = kind;
  return e;
}

/* 空内容不许留白：画一个压暗的占位形状，让人看得出这块在这儿、是什么形状。
   data-empty="1" 是给测试看的——「没填」必须是一种可见状态，不是缺席。 */
function pvSlot(txt) {
  var s = pvEl("pv-slot pv-empty", "slot");
  s.dataset.empty = "1";
  s.textContent = txt || "（空容器 · 控件放这里）";
  return s;
}

function pvText(e, txt, ph) {
  if (txt) {
    e.appendChild(document.createTextNode(txt));
  } else {
    e.className += " pv-empty";
    e.dataset.empty = "1";
    e.textContent = ph;
  }
  return e;
}

function pvIconSpan(c) {
  /* 图标只用字符：离线没有图标资源，也不许引图片。预览画的是「这一块要用
     哪个图标」这个事实——把图标名原样印出来，而不是伪造一张长得像的图。 */
  var s = pvEl("pv-ico", "icon");
  s.textContent = c.icon;
  return s;
}

function renderPreview() {
  var host = el("preview");
  if (!host) { return; }
  host.innerHTML = "";
  var panel = pvEl("bpv", "panel-root");
  panel.dataset.pvcount = String(proposal.length);
  if (!proposal.length) {
    var hint = document.createElement("p");
    hint.className = "pv-hint";
    hint.textContent = "左边这块空白就是 Blender 侧看到的面板。往右边加积木，"
      + "它会从上到下长出来：横排并排、竖排堆叠、框和输入框都长面板里的样子。";
    panel.appendChild(hint);
  }
  // 顶层积木就地遍历（也就是「当前这份列表里 parent 为空的那几块」）；
  // 再往下的层级交给 pvLevel 递归——容器要把孩子放进自己肚子里，
  // 所以每块都得知道自己被谁装着，没法一次 forEach 拍平。
  proposal.forEach(function (n) {
    if (n.parent) { return; }
    panel.appendChild(pvNode(n));
  });
  host.appendChild(panel);
}

/* 预览按树递归渲染：容器自己成为一个 flex/grid 容器，
   它的孩子真的放进去（不再是那个空占位格子）。
   这就是「横排里装着按钮」能出现在截图里的原因——容器渲染成
   layout.row() 那个 flex，子积木渲染成它里面的按钮。 */
function pvLevel(host, parentUid) {
  nodesAtDepth(parentUid).forEach(function (n) {
    host.appendChild(pvNode(n));
  });
}

function pvNode(n) {
  var d;
  if (n.downgraded) {
    /* 降级块是「这条原需求做不到 + 这样改」的记录，Blender 里根本没有这块东西。
       预览照样给它一个位置，但画成压暗 + 删除线的一条说明：谎称它会出现，
       预览就不诚实了。 */
    d = pvEl("pv-down pv-empty", "downgraded");
    d.dataset.empty = "1";
    d.textContent = "✗ 做不到：" + n.label + "（只是记录，Blender 里不画）";
    d.dataset.pvuid = n.uid;
    return d;
  }
  if (n.bkey) {
    d = pvBiz(n);
    d.dataset.pvuid = n.uid;
    return d;
  }
  d = pvWidget(n);
  d.dataset.pvuid = n.uid;
  return d;
}

/* 业务块的预览：直接照 blocks.json 里这块的 demo 画。
   为什么不给业务块另发明一套预览形状——它的形状就是它在插件里的形状，
   照抄 demo 最诚实；而且这样「卡片上的图示」和「左边预览」必然是同一套画法，
   两边不会各画各的。 */
function pvBiz(n) {
  var b = blockByKey(n.bkey);
  var v = b ? variantOf(b, n.bvar) : null;
  var demo = (v && v.demo) || (b && b.demo) || { kind: "box", items: [] };
  var wrap = pvEl("pv-biz", "biz");
  wrap.dataset.pvk = demo.kind || "box";
  /* 名字单独一个元素：pvText 是「就地改并返回同一个元素」，拿它的返回值
     当子节点会把外层的 className 一起改掉（上一版就是这么把 .pv-biz
     变成 .pv-bizname 的，样式跟着丢）。 */
  var head = pvEl("pv-bizname", "bizname");
  head.textContent = n.label;
  wrap.appendChild(head);
  wrap.appendChild(renderDemo({ key: n.bkey, demo: demo, node: n }));
  return wrap;
}

/* 往一个容器节点里放它的孩子。

   没有孩子时才画占位格子，而且只在「这个容器一眼看不出该放什么」时画：
   row / column 带了 heading（页签条、分组标题就是它）就不再画占位——
   Blender 里 layout.row(align=True, heading="AI 对话") 底下没东西时就只画那个标题，
   多画一个虚线格子反而会让预览比真实面板多出一行，看着像排版出了错。 */
function pvFill(d, n) {
  if (childrenOf(n.uid).length) { pvLevel(d, n.uid); return; }
  if (n.wkey === "row" || n.wkey === "column") {
    var h = (n.content || {}).heading || paramValue(n, "heading", null);
    if (h) { return; }
  }
  d.appendChild(pvSlot());
}

function pvWidget(n) {
  var k = n.wkey;
  var c = n.content || {};
  var d;
  if (k === "row" || k === "column") {
    d = pvEl(k === "row" ? "pv-row" : "pv-col", k);
    /* 标题优先取内容（heading=... 这种带取值的写法参数框收不了，
       页签条 / 分组标题只能靠内容），没有内容再退回参数里的裸 heading。 */
    var head = c.heading || paramValue(n, "heading", null);
    if (head) { d.appendChild(pvEl("pv-head", "heading")).textContent = head; }
    pvFill(d, n);
    return d;
  }
  if (k === "box") {
    d = pvEl("pv-box" + (hasParam(n, "alert") ? " alert" : ""), "box");
    pvFill(d, n);
    return d;
  }
  if (k === "split") {
    d = pvEl("pv-split", "split");
    var f = Math.max(0.05, Math.min(0.95, numParam(n, "factor", 0.3)));
    var l = pvEl("pv-half", "split-left");
    l.style.flex = "0 0 " + Math.round(f * 100) + "%";
    var r = pvEl("pv-half", "split-right");
    r.style.flex = "1 1 auto";
    /* 分栏的两个孩子分头放：没有孩子就各留一个占位格子。
       真面板里的左右分栏本来就是「一边的控件」和「另一边的控件」，
       全部堆在左栏会让预览跟真实面板长得不一样。 */
    var kids = childrenOf(n.uid);
    if (kids.length) {
      l.appendChild(pvNode(kids[0]));
      if (kids.length > 1) {
        for (var q = 1; q < kids.length; q++) { r.appendChild(pvNode(kids[q])); }
      } else { r.appendChild(pvSlot("右")); }
    } else {
      l.appendChild(pvSlot("左"));
      r.appendChild(pvSlot("右"));
    }
    d.appendChild(l);
    d.appendChild(r);
    return d;
  }
  if (k === "grid_flow") {
    d = pvEl("pv-grid", "grid_flow");
    var cols = Math.max(1, Math.min(4, Math.round(numParam(n, "columns", 2))));
    d.style.gridTemplateColumns = "repeat(" + cols + ", 1fr)";
    var gk = childrenOf(n.uid);
    if (gk.length) {
      gk.forEach(function (g) { d.appendChild(pvNode(g)); });
    } else {
      for (var i = 0; i < cols; i++) { d.appendChild(pvSlot()); }
    }
    return d;
  }
  if (k === "panel") {
    d = pvEl("pv-panel", "panel");
    var closed = hasParam(n, "default_closed");
    var hd = pvEl("pv-head", "panel-head");
    hd.textContent = (closed ? "▸ " : "▾ ") +
      (paramValue(n, "idname", null) || n.id || "子面板");
    d.appendChild(hd);
    /* 折叠态面板不画内容区：Blender 里 closed 的 panel 本来就只剩标题条。 */
    var body = pvEl("pv-body" + (closed ? " pv-empty" : ""), "panel-body");
    if (closed) { body.dataset.empty = "1"; }
    else { pvFill(body, n); }
    d.appendChild(body);
    return d;
  }
  if (k === "label") {
    d = pvEl("pv-label", "label");
    if (c.icon) { d.appendChild(pvIconSpan(c)); }
    return pvText(d, c.text, "（未填文字）");
  }
  if (k === "operator") {
    d = pvEl("pv-btn", "operator");
    if (c.icon) { d.appendChild(pvIconSpan(c)); }
    return pvText(d, c.text, "（未填按钮文字）");
  }
  if (k === "prop") {
    d = pvEl("pv-prop" + (hasParam(n, "use_property_split") ? " split" : ""), "prop");
    var kv = pvEl("pv-k", "prop-label");
    pvText(kv, c.label, "（未填属性名）");
    var vv = pvEl("pv-v", "prop-value");
    pvText(vv, c.value, "—");
    d.appendChild(kv);
    d.appendChild(vv);
    return d;
  }
  if (k === "textbox") {
    d = pvEl("pv-textbox", "textbox");
    var lines = Number(c.lines) > 0 ? Math.min(10, Number(c.lines)) : 3;
    d.style.height = (lines * 16 + 8) + "px";
    d.appendChild(pvText(pvEl("pv-tx", "textbox-text"),
                         c.placeholder, "（未填占位提示）"));
    return d;
  }
  if (k === "separator") {
    d = document.createElement("hr");
    d.className = "pv-sep";
    d.dataset.pv = "separator";
    return d;
  }
  if (k === "scale_y") {
    d = pvEl("pv-gap", "scale_y");
    d.style.height = Math.max(6, numParam(n, "scale_y", 1) * 18) + "px";
    d.title = "留白，不画任何东西";
    return d;
  }
  /* 词汇表之外的控件（理论上到不了）：画一个诚实的「不认识」，
     而不是悄悄画成空白。 */
  d = pvEl("pv-slot pv-empty", "unknown");
  d.dataset.empty = "1";
  d.textContent = "未知控件：" + k;
  return d;
}

/* #proposal-preview：界面预览的验收钩子。
   报的不是 class 名（那只能证明「我写了这个 class」），而是浏览器算出来的
   样式与几何——flex 方向、grid 列数、grid 子元素宽高、hr 的标签名。
   把 .pv-row 改成竖排、把 grid 改回普通流、把 scale_y 的高度抹掉，
   这里都会当场变，Python 侧的红也就落在这些行上。 */
function pvOf(uid) {
  return el("preview").querySelector('[data-pvuid="' + uid + '"]');
}

/* 展开一块并拿到它的某个内容输入框，和 paramsInputOf 同一个路子：按 wkey 找
   块、按 uid 找输入框，两头都不靠下标。 */
function contentInputOf(wkey, field) {
  for (var i = 0; i < proposal.length; i++) {
    if (proposal[i].wkey !== wkey) { continue; }
    var box = el("canvas").querySelector('.pnode[data-uid="' + proposal[i].uid + '"]');
    if (!box) { continue; }
    return box.querySelector('[data-field="c:' + field + '"]');
  }
  return null;
}

function previewShape(n, e) {
  var cs = getComputedStyle(e);
  var s = e.tagName.toLowerCase() + "/" + cs.display + "/" + cs.flexDirection;
  if (n.wkey === "grid_flow") {
    s += "/" + cs.gridTemplateColumns.split(" ").filter(function (x) { return x; }).length;
  }
  if (n.wkey === "scale_y") { s += "/" + e.offsetHeight; }
  if (n.wkey === "split") {
    var l = e.firstElementChild;
    s += "/" + (l ? Math.round(l.getBoundingClientRect().width) : -1);
  }
  if (n.wkey === "textbox") { s += "/" + e.offsetHeight; }
  if (n.wkey === "panel") {
    s += "/" + (e.querySelector(".pv-head") ? "head" : "nohead") +
         "/" + (e.querySelector(".pv-body") ? "body" : "nobody");
  }
  if (n.wkey === "prop") { s += "/" + e.children.length; }
  if (n.wkey === "label" || n.wkey === "operator") {
    s += "/" + (e.textContent || "").length;
  }
  return n.wkey + "=" + s;
}

function previewReport() {
  var shapes = [];
  var missing = 0;
  proposal.forEach(function (n) {
    var e = pvOf(n.uid);
    if (!e) { missing++; shapes.push(n.wkey + "=MISSING"); return; }
    shapes.push(previewShape(n, e));
  });
  var nodes = el("preview").querySelectorAll("[data-pvuid]").length;

  /* 改内容 -> 预览跟着变。走真的 input 事件 + 真的输入框：
     直接改 proposal[0].content 再读预览，只能证明「赋值和读取互相认识」。 */
  var lab = proposal.filter(function (x) { return x.wkey === "label"; })[0];
  var typed = "";
  if (lab) {
    if (!contentInputOf("label", "text")) {
      el("canvas").querySelector('.pnode[data-uid="' + lab.uid + '"] [data-act="fold"]').click();
    }
    var inp = contentInputOf("label", "text");
    if (inp) {
      inp.value = "正在改你的场景 · 第 2 步";
      inp.dispatchEvent(new Event("input", { bubbles: true }));
      typed = (pvOf(lab.uid) || {}).textContent || "";
    }
  }

  /* 清空 -> 占位形状，不是空白。 */
  var cleared = "?";
  if (lab) {
    var inp2 = contentInputOf("label", "text");
    if (inp2) {
      inp2.value = "";
      inp2.dispatchEvent(new Event("input", { bubbles: true }));
      var pe = pvOf(lab.uid);
      cleared = pe ? (pe.dataset.empty === "1" && /pv-empty/.test(pe.className)
        ? "empty" : "filled") : "missing";
    }
  }

  /* 折叠态面板：参数里写了 default_closed 就该只剩一条标题条。 */
  var closedHead = "?";
  var pan = proposal.filter(function (x) { return x.wkey === "panel"; })[0];
  if (pan) {
    setParams(pan, "default_closed");
    var pe2 = pvOf(pan.uid);
    var hd2 = pe2 && pe2.querySelector(".pv-head");
    closedHead = hd2 ? (hd2.textContent || "?").slice(0, 1) : "?";
  }

  appendReport("preview-report", {
    count: String(nodes),
    proposal: String(proposal.length),
    missing: String(missing),
    shapes: shapes.join("|"),
    "typedText": typed,
    cleared: cleared,
    "closedHead": closedHead,
    "iconList": (document.getElementById("pv-icon-list") || { dataset: {} }).dataset
      .iconcount || "0",
    // 两栏：两个挂载点必须挂在同一个 .canvas-split 下，而不是「都在页面上」。
    "twoPane": (el("preview") && el("canvas") &&
                el("preview").closest(".canvas-split") &&
                el("preview").closest(".canvas-split") ===
                  el("canvas").closest(".canvas-split")) ? "1" : "0"
  });
  setStatus("DEMO preview 预览 " + nodes + " 节点");
}

/* #proposal-nest：把嵌套相关的几条路径各真跑一遍，然后把读数报出来。
   存在的理由：这一轮新增的行为（归属下拉 / 子树复制 / 子树删除 / 三界面独立）
   都没有既成的无头钩子覆盖。少一个钩子，这些行为就只剩「代码看着对」。

   报的每一项都是浏览器真算出来的东西或真点过的按钮的结果，不是数组自证：
     tree —— 「容器uid>孩子uid」拼成的层级串，用来核对树结构本身
     dupTree / dupCount —— 复制一个容器后，副本是不是连子树一起复制了
     delCount —— 删掉一个容器后，孙块是不是也跟着没了
     tabs —— 三个子页签各自的块数，用来核对三份列表互不干扰
     selOptions —— 归属下拉里的选项数（含「（顶层）」） */
function nestReport() {
  var btn = el("demo-panel-btn");
  if (btn) { btn.click(); }

  var stream = proposal.filter(function (n) { return n.id === "chat.stream"; })[0];
  /* 删容器：整棵子树一起走，单独留下一个块数。
     挑规格竖排（chat.options）而不是页签条：它里面套着「细节横排 -> 三个
     勾选选项」，删它一次能连着验掉三层（孙块也得跟着走，孤儿不许剩）。 */
  var opts = proposal.filter(function (n) { return n.id === "chat.options"; })[0];

  var tree = proposal.map(function (n) {
    return (n.parent ? n.parent : "-") + ">" + n.uid;
  }).join("|");

  /* 复制容器：副本必须带整棵子树，且子孙的 parent 改指副本的新 uid。 */
  var dupTree = "";
  var dupCount = -1;
  if (stream) {
    var before = proposal.length;
    dupNode(idxByUid(stream.uid));
    dupCount = proposal.length - before;
    var copy = proposal.filter(function (n) { return n.id === "chat.stream"; })[1];
    dupTree = copy ? copy.uid + ":" + childrenOf(copy.uid).length : "nocopy";
  }

  /* 删容器：整棵子树一起走，单独留下一个块数。 */
  var delCount = -1;
  /* 删完之后不许剩孤儿：还挂在已删容器底下的块既不显示也删不掉，
     用户会以为「删了没用」。这里数的是真数组，不是渲染结果。 */
  var orphans = -1;
  if (opts) {
    var b2 = proposal.length;
    var gone = subtreeUids(opts.uid);
    delNode(idxByUid(opts.uid));
    delCount = b2 - proposal.length;
    orphans = proposal.filter(function (n) {
      return n.parent && gone.indexOf(n.parent) >= 0;
    }).length;
  }

  /* 三个界面各自的块数：切过去记个数，切回来再记一次。
     对话这一份刚才被增删过，详情与设置应当仍是 0。 */
  var tabs = [];
  TAB_ORDER.forEach(function (k) {
    switchTab(k);
    tabs.push(k + "=" + proposal.length);
  });
  switchTab("chat");

  /* 归属下拉只画在展开态里（折叠时它不占地方），所以先展开一块再数选项。 */
  var probe = proposal.filter(function (n) { return n.id === "chat.stream"; })[0];
  if (probe && !probe.expanded) { probe.expanded = true; renderCanvas(); }
  var sel = el("canvas").querySelector('.pnode[data-uid="' +
    (probe ? probe.uid : "") + '"] [data-field="parent"]');
  /* 选项里必须只有容器积木 + （顶层）：叶子控件和「自己 / 自己的子孙」
     都列进去的话，用户点一下就会把积木挂到非法位置。 */
  var optTexts = [];
  if (sel) {
    for (var q = 0; q < sel.options.length; q++) { optTexts.push(sel.options[q].textContent); }
  }
  /* 预览是不是真的树：数每个预览节点在 DOM 里套着几层别的预览节点。
     这是浏览器算出来的父子关系，不是我们自己写的 class 名——
     把 pvFill 改成永远画占位（容器不装孩子）的话，这里的 maxDepth 会掉到 1。 */
  var maxDepth = 0;
  var pvs = el("preview").querySelectorAll("[data-pvuid]");
  for (var i = 0; i < pvs.length; i++) {
    var d = 0;
    var up = pvs[i].parentElement;
    while (up) {
      if (up.dataset && up.dataset.pvuid) { d++; }
      up = up.parentElement;
    }
    if (d > maxDepth) { maxDepth = d; }
  }

  appendReport("nest-report", {
    tree: tree,
    dupTree: dupTree,
    dupCount: String(dupCount),
    delCount: String(delCount),
    delOrphans: String(orphans),
    tabs: tabs.join(","),
    selOptions: String(sel ? sel.options.length : 0),
    selTexts: optTexts.join("|"),
    groups: String(el("canvas").querySelectorAll(".pgroup").length),
    pvMaxDepth: String(maxDepth),
    pvCount: String(pvs.length),
    blocks: String(proposal.length)
  });
  setStatus("DEMO nest 树 " + proposal.length + " 块 / 分组 " +
    el("canvas").querySelectorAll(".pgroup").length);
}

/* #proposal-move：换父级的三条路径各走一遍，外加「树到底画出来没有」。
   报的每一条都来自浏览器里真点过的按钮 / 真派发过的 DragEvent：
     kidzones    —— .pkids 孩子区（树线那一截）有几个
     kidzone-kids—— 孩子区里装着的积木数
     counts      —— 容器标题上标的「· N」，N = 该容器真有几个子块
     in-* / out-*—— 两个快捷按钮的个数与其中被置灰的个数
     out-parent  —— 点「移出上一层」之后这一块的 parent 变成什么
     in-parent   —— 再点「移入上一个容器」之后变成什么
     drag-cands  —— 拖起来时被标成「能装进去」的容器数
     drag-parent —— 落在那个容器上之后 parent 变成什么
     deny-status —— 把容器拖进它自己的子孙里，状态条说了什么 */
function moveReport() {
  var btn = el("demo-panel-btn");
  if (btn) { btn.click(); }
  var canvas = el("canvas");
  var dt = new DataTransfer();

  /* --- 树画出来没有：孩子区 + 子块数 --- */
  var zones = canvas.querySelectorAll(".pkids");
  var zoneKids = 0;
  for (var z = 0; z < zones.length; z++) {
    zoneKids += zones[z].querySelectorAll(".pnode[data-uid]").length;
  }
  /* 容器标题上的「· N」逐个对账：标签上的 N 与真孩子数必须一致，
     且至少有一个空容器标着「· 0」（空容器要看得见是空的）。 */
  var counts = [];
  var countBad = 0;
  var emptyMarked = 0;
  var badges = canvas.querySelectorAll(".pnode .pcount");
  for (var b = 0; b < badges.length; b++) {
    var box = badges[b].closest(".pnode");
    counts.push(badges[b].textContent);
    var real = childrenOf(box.dataset.uid).length;
    if (badges[b].dataset.kids !== String(real)) { countBad++; }
    if (real === 0) { emptyMarked++; }
  }

  /* --- 两个快捷按钮：每块都有，没得移的必须置灰（不是消失） --- */
  var inAll = canvas.querySelectorAll('.pnode [data-act="in"]');
  var outAll = canvas.querySelectorAll('.pnode [data-act="out"]');
  var inOff = 0, outOff = 0;
  for (var i1 = 0; i1 < inAll.length; i1++) { if (inAll[i1].disabled) { inOff++; } }
  for (var o1 = 0; o1 < outAll.length; o1++) { if (outAll[o1].disabled) { outOff++; } }

  /* --- 点「移出上一层」再点「移入上一个容器」 --- */
  var target = proposal.filter(function (n) { return n.wkey === "label"; })[0];
  var blocksBefore = proposal.length;
  var outParent = "?";
  var inParent = "?";
  var inParentWkey = "?";
  var inDisabled = "?";
  var inStatus = "";
  if (target) {
    target.expanded = false;
    renderCanvas();
    var tbox = canvas.querySelector('.pnode[data-uid="' + target.uid + '"]');
    tbox.querySelector('[data-act="out"]').click();
    outParent = String(nodeByUid(target.uid).parent || "");
    var tbox2 = canvas.querySelector('.pnode[data-uid="' + target.uid + '"]');
    var inBtn2 = tbox2.querySelector('[data-act="in"]');
    inDisabled = String(inBtn2.disabled);
    inBtn2.click();
    inStatus = el("status").textContent || "";
    var pnode = nodeByUid(target.uid);
    inParent = String((pnode && pnode.parent) || "");
    inParentWkey = pnode && pnode.parent && nodeByUid(pnode.parent)
      ? nodeByUid(pnode.parent).wkey : (inParent ? "?" : "");
  }

  /* --- 拖进容器：拖起来先数「能装进去的容器」，再落到其中一个身上 --- */
  var dragCands = -1;
  var dragParent = "?";
  var dragParentWkey = "?";
  var victim = proposal.filter(function (n) { return n.wkey === "box"; })[0];
  var boxNode = victim ? canvas.querySelector('.pnode[data-uid="' + victim.uid + '"]') : null;
  var optionsNode = proposal.filter(function (n) { return n.id === "chat.options"; })[0];
  var optBox = optionsNode
    ? canvas.querySelector('.pnode[data-uid="' + optionsNode.uid + '"]') : null;
  /* 落点 uid 与落点前原来的 parent 一起报出去：只报「落完之后的 parent 是
     个容器」的话，压根没落成（被拒了 / 分支没走）也照样绿——被拖的那块本来
     就装在 chat.stream 里。这两样报上来，断言才能钉住「真的从 A 挪到了 B」。 */
  var dragTargetUid = optBox ? (optBox.dataset.uid || "") : "";
  var dragFrom = victim ? String((nodeByUid(victim.uid) || {}).parent || "") : "";
  if (boxNode && optBox) {
    fireDrag(boxNode, "dragstart", 0, dt);
    dragCands = canvas.querySelectorAll(".pnode.can-drop").length;
    fireDrag(optBox, "dragover", 0, dt);
    fireDrag(optBox, "drop", 0, dt);
    var vp = nodeByUid(victim.uid);
    dragParent = String((vp && vp.parent) || "");
    dragParentWkey = vp && vp.parent && nodeByUid(vp.parent)
      ? nodeByUid(vp.parent).wkey : "";
  }
  clearDrag();

  /* --- 拒绝时必须说话：把容器拖进它自己的子孙里 --- */
  var denyStatus = "";
  var denyParent = "?";
  var stream = proposal.filter(function (n) { return n.id === "chat.stream"; })[0];
  var deep = proposal.filter(function (n) { return n.wkey === "row" && n.id !== "chat.tabbar"; })[0];
  var deepBox = deep ? canvas.querySelector('.pnode[data-uid="' + deep.uid + '"]') : null;
  var streamBox = stream ? canvas.querySelector('.pnode[data-uid="' + stream.uid + '"]') : null;
  if (streamBox && deepBox) {
    fireDrag(streamBox, "dragstart", 0, dt);
    fireDrag(deepBox, "dragover", 0, dt);
    fireDrag(deepBox, "drop", 0, dt);
    denyStatus = el("status").textContent || "";
    denyParent = String((nodeByUid(stream.uid) && nodeByUid(stream.uid).parent) || "");
  }
  clearDrag();

  appendReport("move-report", {
    blocks: String(proposal.length),
    blocksBefore: String(blocksBefore),
    kidzones: String(zones.length),
    zoneKids: String(zoneKids),
    counts: counts.join("|"),
    countBad: String(countBad),
    emptyMarked: String(emptyMarked),
    inAll: String(inAll.length),
    inOff: String(inOff),
    outAll: String(outAll.length),
    outOff: String(outOff),
    outParent: outParent,
    inParent: inParent,
    inParentWkey: inParentWkey,
    inDisabled: inDisabled,
    inStatus: inStatus,
    dragCands: String(dragCands),
    dragParent: dragParent,
    dragParentWkey: dragParentWkey,
    dragTargetUid: dragTargetUid,
    dragFrom: dragFrom,
    denyStatus: denyStatus,
    denyParent: denyParent
  });
  setStatus("DEMO move 树线 " + zones.length + " 组 / 候选 " + dragCands +
    " / 拖进容器 -> " + dragParent);
}

/* ---------------- 导出：把这一版交出去 ----------------
   需求原话：「不然我调好了怎么告诉你然后落实呢」。
   「告诉你」和「落实」是两条路，所以出口也分两条：

     ui.py（代码）      —— 落实。照 blender_deepseek_agent/ui.py 里
                          draw_chat_content() 的写法，把积木树翻成
                          layout.row / box / label / operator / prop …
     方案说明（Markdown）—— 告诉你。一份人能读、AI 也能直接读成实施计划的文档。
     方案 JSON          —— 存档。三个界面全在里面，以后接着改。
     自动保存           —— 别丢。见文件开头那段。

   三条纪律：
   1) 这份 ui.py 是**草稿**，从没在真实 Blender 里跑过。文件头和每一块的
      注释里都必须写明这句话——不写就成了「看起来能跑的代码」，那比不给更糟。
   2) 翻译不出来的东西不许假装翻译了：算子名 / 属性名缺了就发 TODO，
      并汇总进文末的「必须人工补」清单。
   3) 降级块（Blender 里做不到的）不生成代码，只生成注释记录。 */

var UNVERIFIED_NOTICE =
  "工具生成 · 未经验证：这段代码由 UI Workbench 从积木树自动导出，"
  + "从没在真实 Blender 里跑过。是草稿，不是能直接粘贴就用的成品。";

/* 各控件的默认参数（取自 vocabulary.json 的 uiloayout，界面只负责排版）。 */
var PY_DEFAULT_KW = {
  row: "align=True",
  column: "align=True",
  box: "",
  split: "factor=0.3",
  grid_flow: "columns=2, even_columns=True",
  panel: ""
};

/* 这些是「赋值给容器」而不是「传进调用」的参数，照样写成属性赋值行。 */
var PY_ATTRS = ["alert", "scale_y", "use_property_split"];

/* 光写名字不带取值的参数 = 「打开这个开关」。
   必须补成 =True：照原样吐出去会生成 layout.row(align, ...)，
   那在 Python 里就是语法错误——一份连 ast.parse 都过不去的「草稿」
   连草稿都算不上。（Blender 这几个开关的默认值就是 True，所以补 True
   与用户「打开它」的意思一致。） */
var PY_TRUE_FLAGS = ["align", "even_columns", "even_rows", "row_major",
                     "default_closed", "use_property_split", "translate"];

function pyStr(s) {
  return '"' + String(s == null ? "" : s)
    .replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n") + '"';
}

/* 业务块改文案时用：原句是 f-string 就保住 f 前缀。
   丢掉它，「选择: {lbl}」会变成字面上的花括号——插件里那个按钮
   就永远显示「选择: {lbl}」这几个字符，而不是那个选项的名字。 */
function pyStrF(s, keepF) {
  var q = pyStr(s);
  return keepF ? ("f" + q) : q;
}

/* True / False / None / 数字照抄，其余一律当字符串加引号。
   不判断的话 align=False 会被写成 align="False"——那在 Blender 里是
   一个非空的字符串，真值，参数等于反过来生效。 */
function pyScalar(v) {
  var t = String(v == null ? "" : v).trim();
  if (/^(True|False|None)$/.test(t) || /^-?[0-9]+(\.[0-9]+)?$/.test(t)) { return t; }
  return pyStr(t);
}

function pyIndent(depth) { return new Array(depth + 1).join("    "); }

function pyVarName(base, used) {
  used[base] = (used[base] || 0) + 1;
  return used[base] === 1 ? base : (base + used[base]);
}

/* 参数表：词汇表给的默认值打底，用户写的同名键覆盖它。
   注意覆盖而不是拼接——align=True 后面再来一个 align=False，
   拼起来就成了 layout.row(align=True, align=False)，那在 Python 里
   直接是语法错误。

   光写名字没写取值的参数 = 「打开这个开关」，必须补成 =True：
   照原样吐出去会生成 layout.row(align, ...)，一份连 ast.parse 都过不去的
   「草稿」连草稿都算不上。补 True 与用户「打开它」的意思一致
   （Blender 这几个开关的默认值就是 True），而不在清单里的裸参数
   另记一条，让人自己核对。 */
function pyKw(n, todo) {
  var vals = {};
  var defaults = {};
  var order = [];
  function add(t, dflt) {
    var i = t.indexOf("=");
    var k = (i < 0 ? t : t.slice(0, i)).trim();
    if (!(k in vals)) { order.push(k); }
    // defaults 只记第一次（也就是词汇表给的那个）。用户后写的裸 tokens
    // 如果把这里也覆盖成 ""，columns 就会从 2 变成 None——网格静默塌成一列。
    if (!(k in defaults)) { defaults[k] = dflt; }
    vals[k] = (i < 0 ? "" : t.slice(i + 1).trim());
  }
  splitParams(PY_DEFAULT_KW[n.wkey] || "").forEach(function (t) { add(t, t); });
  splitParams(n.params).forEach(function (t) {
    var k = t.split("=")[0].trim();
    if (PY_ATTRS.indexOf(k) >= 0) { return; }
    add(t, "");
  });
  return order.map(function (k) {
    if (vals[k] !== "") { return k + "=" + pyScalar(vals[k]); }
    /* 裸参数有两种意思，得分开处理，混起来会静默改坏面板：
       - 它是个开关（align / even_columns）：补 =True，与「打开它」一致；
       - 它是个取值没写完（columns、factor）：保留词汇表给的默认值，
         另记一条。写成 columns=True 会让网格真的只剩一列，而且不报错。 */
    if (PY_TRUE_FLAGS.indexOf(k) >= 0) { return k + "=True"; }
    if (todo) {
      todo.push("「" + n.label + "」的参数 " + k + " 没写取值，已保留词汇表给的默认"
        + (defaults[k] ? ("（" + defaults[k] + "）") : "（没有默认，已写 None）")
        + "——请补上你想要的取值");
    }
    return defaults[k] ? (k + "=" + pyScalar(defaults[k].split("=")[1]))
      : (k + "=None");
  }).join(", ");
}

function pyAttrLines(n, varName, ind) {
  var out = [];
  splitParams(n.params).forEach(function (t) {
    var i = t.indexOf("=");
    var k = (i < 0 ? t : t.slice(0, i)).trim();
    if (PY_ATTRS.indexOf(k) < 0 || n.wkey === "scale_y") { return; }
    out.push(ind + varName + "." + k + " = " +
      (i < 0 ? "True" : pyScalar(t.slice(i + 1))));
  });
  return out;
}

/* 占位名字一律写成「一眼认得出不是真的」的样子：deepseek.TODO_算子名待定
   而不是 deepseek.TODO_填算子名——扫代码的人先看到「待定」两个字，
   不会以为那只是个人类可读的后缀就照抄进 ui.py。 */
function pyOperatorId(n, todo) {
  var id = String(n.id || "").trim();
  if (id.indexOf("deepseek.") === 0) { return id; }
  if (id) {
    todo.push("算子「" + n.label + "」的元素 ID 是「" + id +
      "」，不是 deepseek.* 开头，已补成 deepseek." + id + "——请核对真实算子名");
    return "deepseek." + id;
  }
  todo.push("算子「" + n.label + "」还没填元素 ID，代码里留的是 TODO 占位——请填真实算子名");
  return "deepseek.TODO_算子名待定";
}

/* 元素 ID 与 Property 名是两回事。元素 ID 是工作台里定位这块积木用的，
   state.prop() 要的是 state 上真有的属性名。把 "chat.composer" 原样塞进
   state.prop(state, "chat.composer") 看着能抄、真跑起来是 AttributeError——
   这种「看着对其实对不上」的代码最费时间，所以只有下表核对过的才照抄，
   其余一律在行首标 TODO。
   下表抄自 blender_deepseek_agent/ui.py:953 的 draw_chat_content：
     cbox.textbox(state, "prompt", initial_visible_lines=state.prompt_lines, ...) */
var PY_PROP_NAMES = {
  "chat.composer": "prompt"
};

function pyPropName(n, todo) {
  var id = String(n.id || "").trim();
  if (PY_PROP_NAMES[id]) { return PY_PROP_NAMES[id]; }
  if (id) {
    /* 有元素 ID 但没核对过：照填可以（用户多半知道自己写的是什么），
       但必须在这一块前面留一行行首 # TODO，见 pyLevel 里 pyFlag.todo 的用法。
       宁好多一句提醒，也不要给一段看着能跑、实际对不上的代码。 */
    todo.push("「" + n.label + "」的元素 ID 是「" + id +
      "」，它未必就是 state 上的 Property 名，已照原样填上——请核对真实属性名");
    pyFlag.todo = true;
    return id;
  }
  todo.push("「" + n.label + "」还没填元素 ID，属性名留的是 TODO 占位——请填真实的 Property 名字");
  return "TODO_属性名待定";
}

/* 业务块往导出里写的那几行：出处说明 + 那段原样的 ui_py。
   写在 pyLevel 里（而不是另开一个导出器）是为了让 pyCols / pyStats
   这两本账自动包含业务块——导出面板上「共几块」的统计才不会少算。 */
function pyBizLines(out, todo, n, ind) {
  var b = blockByKey(n.bkey);
  var v = b ? variantOf(b, n.bvar) : null;
  if (!v) {
    // blocks.json 里查不到这块：多半是数据换了版本而存档还是旧的。
    // 宁可明说，也不生成一段来路不明的代码。
    out.push(ind + "# ⚠ blocks.json 里没有「" + n.bkey + "」这一块，无法生成代码（请重跑 dev/build_blocks.py）");
    todo.push("界面块「" + n.bkey + "」在 blocks.json 里不存在，请重跑 dev/build_blocks.py");
    return;
  }
  out.push(ind + "#   出处：blender_deepseek_agent/ui.py 里「" + v.label +
    "」这一段，原样抄来（不是翻译出来的）");
  var src = applyBizTexts(String(v.ui_py), b, n);
  /* 展开/收起的状态存在积木上（node.msgOpen），导出时**不许丢**：用户在
     工作台里把这条长消息点开了，导出的 default_closed 就得跟着变成 False，
     否则预览里展开着、Blender 里一装上还是折着的，两边讲两个版本的故事。 */
  if (n.msgOpen) {
    src = src.replace("open_default=False", "open_default=True");
  }
  var lines = src.split("\n");
  for (var i = 0; i < lines.length; i++) {
    out.push(lines[i].length ? (ind + lines[i]) : "");
  }
  var rw = v.rewrites || [];
  if (rw.length) {
    out.push(ind + "#   为独立成块改绑过 " + rw.length + " 处（局部变量改绑 layout），"
      + "改的理由见 blocks.json 的 rewrites");
  }
}

/* 把用户改过的文案套回那段 ui_py。

   只替换**字符串字面量**：逐字找出 blocks.json 里登记的那句原文，换成
   重新转义过的新句。绝不整行重写——所以用户写什么都改不坏结构，
   引号、反斜杠、换行都由 pyStr 负责。

   原文在代码里出现两次以上时不替换（blocks.json 生成期已经禁止这种槽），
   宁可留着默认文案，也不能猜用户想改哪一处。 */
function applyBizTexts(src, b, n) {
  var texts = n.btexts || {};
  (b.slots || []).forEach(function (s) {
    var val = texts[s.name];
    if (val == null || val === s.text) { return; }
    var cnt = src.split(s.literal).length - 1;
    if (cnt !== 1) {
      pyStats.textSkipped = (pyStats.textSkipped || 0) + 1;
      return;
    }
    src = src.replace(s.literal, pyStrF(val, s.literal.indexOf("f\"") === 0));
  });
  return src;
}

function pyNoteLines(n, ind) {
  var out = [ind + "#   想做什么 · 为什么：" +
    (n.note ? n.note : "（这块没写标注）")];
  if (n.downgraded) {
    out.push(ind + "#   拦路：" + (n.blocker || "（没记）"));
    out.push(ind + "#   改成：" + (n.fallback || "（没记）"));
  }
  /* 被拦下的参数不在这里逐条抄一遍：那些话已经写在积木上了，
     再抄一遍只会让这份代码和画布长得像两套东西。改在文末汇总成一条，
     让人知道「有几块还没过参数这一关」，具体哪几块看方案说明。 */
  if (n.errors && n.errors.length) {
    out.push(ind + "#   ⚠ 这块有 " + n.errors.length + " 个参数被工作台拦下了（见文末清单）");
  }
  return out;
}

/* buildPy 一次运行里记的两本账。导出面板上那行统计、测试报告里的缩进表，
   读的都是它们——同一份数，不许两处各算一遍（各算一遍就迟早对不上）。 */
var pyCols = {};
var pyStats = { total: 0, todo: 0 };
/* pyPropName 遇到「有元素 ID 但没核对过」时置位：这一块生成的代码看着能跑，
   实际未必对得上，行首必须留一行 # TODO 提醒。 */
var pyFlag = { todo: false };

/* 占位标记写在行首：grep '# TODO' 一把抓得到，扫一眼代码的人也不会把
   deepseek.TODO_算子名待定 当成真算子名抄走。 */
function pyTodoComment(n, ind) {
  return ind + "# TODO: 「" + n.label + "」还没填真实取值（元素 ID / Property 名 / "
    + "算子名），下面这行是占位，不能直接用。";
}

/* 递归翻译一层。host = 生成出来的代码里「这些东西该往哪放」的变量名。
   depth 只用于 pyCols 的记账，不再决定缩进——原因见下面那三行。 */
function pyLevel(out, todo, used, parentUid, host, depth) {
  /* 缩进是这个生成器最要紧的形状，而它的正确答案只有一个：全部同列。
     Blender 的 UILayout 不是上下文管理器——row = layout.row() 之后紧跟的
     row.label() 必须和这一行同列；嵌套只能靠变量名表达（col / col2 / col3 /
     grid），真实的 ui.py 里 draw_chat_content 也正是这么写的。
     往下多缩一格在 Python 里不是「更深」，是 IndentationError：函数体里
     第一个定格的块之后，同一层没有 for/if/while 去开一个 suite，那行直接
     unexpected indent。递归里为子块加一级深度，就是当年那个 bug。
     ast.parse 是这件事唯一的判据，dev/test_proposal_vocab.py 每次都跑。 */
  var ind = pyIndent(1);
  nodesAtDepth(parentUid).forEach(function (n, i) {
    var idx = proposal.indexOf(n);
    pyCols[idx] = ind.length;
    pyStats.total++;
    var c = n.content || {};
    var head = ind + "# ── " + (i + 1) + ") " +
      (n.id || "（没填元素 ID）") + " · " + n.label;
    out.push(head + "  —— 工作台自动生成，未经验证");
    pyNoteLines(n, ind).forEach(function (l) { out.push(l); });

    if (n.downgraded) {
      // 降级块在 Blender 里根本没有对应东西：生成代码就是谎称它会出现。
      out.push(ind + "# ✗ 做不到，所以这里不生成代码（只是这条需求的记录）");
      return;
    }

    /* 业务块不做翻译：它带的那段 ui_py 就是插件 ui.py 里现成的代码，
       原样贴出去。翻译过的代码「看起来对但画不出来」是最坏的一种错，
       而业务块这条路从设计上就不经过任何翻译。
       文案改动只落在字符串字面量上，所以替换用的是「逐字找出那个字面量、
       换成重新转义过的新字面量」，不会碰到任何结构。 */
    if (n.bkey) {
      pyBizLines(out, todo, n, ind);
      return;
    }

    if (n.wkey === "separator") {
      out.push(ind + host + ".separator()");
      return;
    }
    if (n.wkey === "scale_y") {
      var sy = paramValue(n, "scale_y", null);
      out.push(ind + host + ".scale_y = " + (sy === null ? "1.0" : pyScalar(sy)));
      return;
    }

    /* 只有容器才需要 pyKw：叶子的 text / icon / columns / prop 这些写在参数框里，
       它们描述的是「这块叫什么」，已经由 pyLeaf 按各自的调用形式发出去了。
       再让 pyKw 走一遍，叶子的每一个参数都会被当成「开关名没写取值」报一遍，
       文末清单立刻被无意义的条目淹没——清单一旦嘈杂就等于没有清单。 */
    var kw = (CONTAINER_WKEYS.indexOf(n.wkey) >= 0) ? pyKw(n, todo) : "";
    var base = null;
    var stmt = null;
    pyFlag.todo = false;
    if (n.wkey === "row" || n.wkey === "column") {
      var kwc = kw;
      var head2 = c.heading || paramValue(n, "heading", null);
      if (head2 && !/heading=/.test(kwc)) {
        kwc = kwc ? (kwc + ", heading=" + pyStr(head2)) : ("heading=" + pyStr(head2));
      }
      base = (n.wkey === "row") ? "row" : "col";
      stmt = host + "." + n.wkey + "(" + kwc + ")";
    } else if (n.wkey === "box") {
      base = "box";
      stmt = host + ".box(" + kw + ")";
    } else if (n.wkey === "split") {
      base = "split";
      stmt = host + ".split(" + kw + ")";
    } else if (n.wkey === "grid_flow") {
      base = "grid";
      stmt = host + ".grid_flow(" + kw + ")";
    } else if (n.wkey === "panel") {
      base = "panel";
      var idn = paramValue(n, "idname", null) || n.id;
      if (!idn) {
        todo.push("子面板「" + n.label + "」还没填元素 ID，panel 的 idname 留的是 TODO 占位");
      }
      stmt = host + ".panel(" + (idn ? pyStr(idn) : "TODO_子面板ID") +
        (hasParam(n, "default_closed") ? ", default_closed=True" : "") + ")";
    } else {
      stmt = pyLeaf(n, host, todo);
    }

    /* 这块要不要先喊一声 TODO：语句里自带占位名字（deepseek.TODO_算子名待定），
       或者 pyPropName 说「这个属性名没核对过」。两种都必须在行首留标记，
       否则用户扫过去只会以为那段是能直接用的。 */
    if (pyFlag.todo || /TODO/.test(String(stmt))) {
      pyStats.todo++;
      out.push(pyTodoComment(n, ind));
    }

    if (base) {
      var vn = pyVarName(base, used);
      out.push(ind + vn + " = " + stmt);
      pyAttrLines(n, vn, ind).forEach(function (l) { out.push(l); });
      // 容器自己那些「非参数」的设置：heading 是 row/column 的分组标题，
      // 在 Blender 里它就是行内的一块子面板标题，必须跟着这行一起出现。
      if ((n.wkey === "row" || n.wkey === "column") && head2) {
        out.push(ind + "# 上面这行的 heading 就是这一段的分组标题");
      }
      pyLevel(out, todo, used, n.uid, vn, depth + 1);
    } else {
      out.push(ind + stmt);
      pyAttrLines(n, host, ind).forEach(function (l) { out.push(l); });
    }
  });
}

function pyLeaf(n, host, todo) {
  var c = n.content || {};
  /* 图标用单引号，跟 ui.py 里的写法一致（'PLAY' 而不是 "PLAY"）。
     两边都对，但抄改的人习惯在既有文件里看到的那一种。 */
  var icon = c.icon ? (", icon='" + String(c.icon).replace(/'/g, "") + "'") : "";
  if (n.wkey === "label") {
    return host + ".label(text=" + pyStr(c.text || "TODO_文字") + icon + ")";
  }
  if (n.wkey === "operator") {
    return host + ".operator(" + pyStr(pyOperatorId(n, todo)) +
      ", text=" + pyStr(c.text || "TODO_按钮文字") + icon + ")";
  }
  if (n.wkey === "prop") {
    return host + ".prop(state, " + pyStr(pyPropName(n, todo)) +
      (c.label ? (", text=" + pyStr(c.label)) : "") + ")";
  }
  if (n.wkey === "textbox") {
    var ln = Number(c.lines) > 0 ? Math.min(10, Number(c.lines)) : 3;
    return host + ".textbox(state, " + pyStr(pyPropName(n, todo)) +
      (c.placeholder ? (", text=" + pyStr(c.placeholder)) : "") +
      ", initial_visible_lines=" + ln + ")";
  }
  todo.push("app.js 认识的控件「" + n.wkey + "」没有对应的代码翻译，人工补");
  return "# ⚠ 未知控件 " + n.wkey + "：app.js 与这份导出不同步，请人工补这一行";
}

function buildPy() {
  var out = [];
  var todo = [];
  var used = {};
  pyCols = {};
  pyStats = { total: 0, todo: 0, textSkipped: 0 };
  pyFlag = { todo: false };
  var now = new Date().toISOString().replace("T", " ").slice(0, 19);
  out.push("# -*- coding: utf-8 -*-");
  out.push("#");
  out.push("# ⚠ " + UNVERIFIED_NOTICE);
  out.push("#");
  out.push("# 由 UI Workbench 从「" + TAB_LABELS[activeTab] + "」界面的积木树导出，生成时间 "
    + now + "，共 " + proposal.length + " 块。");
  out.push("# 积木的先后顺序 = 面板从上到下的顺序；容器积木 = 一层 layout 容器，");
  out.push("# 容器里的子积木就画在它下面那几行。");
  out.push("");
  out.push("");
  out.push("def draw_" + activeTab + "_content(layout, state):");
  out.push('    """「' + TAB_LABELS[activeTab] + '」界面。' + UNVERIFIED_NOTICE + '"""');
  /* 响应式图标、长消息折叠这两小段：它们是 blocks.json 里 py_preamble /
     py_helper 登记的新增代码，ui.py 里没有（所以它们不像别的行那样
     「原样抄来」）。少发其中一段，用户在 Blender 里就没有那个可行写法可抄。 */
  var pre = (blocksDoc && blocksDoc.py_preamble) || null;
  var helper = (blocksDoc && blocksDoc.py_helper) || null;
  if (pre && proposal.length) {
    /* why 按句号断行导出：它是一整段中文，塞成一行会顶穿一屏代码，
       而「这是 ui.py 之外的新增代码」这句话必须跟着代码走。 */
    String(pre.why || "").split("。").forEach(function (s) {
      var t = s.trim();
      if (t) { out.push("    # " + t + "。"); }
    });
    (pre.snippet || []).forEach(function (ln) {
      out.push(ln.trim() ? ("    " + ln) : "");
    });
  }
  if (helper && proposal.length) {
    out.push("");
    String(helper.why || "").split("。").forEach(function (s) {
      var t2 = s.trim();
      if (t2) { out.push("    # " + t2 + "。"); }
    });
    (helper.snippet || []).forEach(function (ln) {
      out.push(ln.trim() ? ("    " + ln) : "");
    });
  }
  if (!proposal.length) {
    out.push("    # 这一份还没有积木：Blender 侧这里也应该是空的。");
  } else {
    pyLevel(out, todo, used, null, "layout", 1);
  }
  out.push("");
  out.push("");
  out.push("# ---- 落笔前必须人工处理的 " + todo.length + " 处 ----");
  if (!todo.length) {
    out.push("# （没有发现缺算子名 / 缺属性名的地方。但这段代码仍然没在 Blender 里跑过，");
    out.push("#   至少要先把整段贴进 Blender 看一眼渲染结果，再合进 ui.py。）");
  } else {
    todo.forEach(function (t, i) { out.push("# " + (i + 1) + ". " + t); });
  }
  return out.join("\n");
}

/* ---------------- 方案说明（Markdown）----------------
   这是「告诉你」的主渠道，所以格式必须干净：只讲搭了什么、你想了什么、
   哪里降级了、哪些还没验证。一行调试信息都不塞。 */
/* 业务块在方案说明里的那几行。它没有「代码形态 / 参数 / 归属」那些栏——
   那些栏说的都是 UILayout 原语的事，硬套到业务块上会写出「参数：（空）」
   这种让人以为漏填了的假字段。业务块该说的是：它是哪一块、什么样式、
   改了哪几句文案。 */
function mdBizBlock(n, depth) {
  var ind = mdIndent(depth);
  var b = blockByKey(n.bkey);
  var v = b ? variantOf(b, n.bvar) : null;
  var lines = [ind + "- **" + n.label + "**（界面块 · " +
    (b ? (TAB_LABELS[b.tab] || b.tab) : "未知界面") + "）"];
  if (v) { lines.push(ind + "  - 样式：" + v.label + " —— " + v.what); }
  lines.push(ind + "  - 备注名：" + (n.id ? ("`" + n.id + "`") : "（没填，不影响导出）"));
  lines.push(ind + "  - 代码出处：blender_deepseek_agent/ui.py 里「" +
    (v ? v.label : n.bkey) + "」那一段，原样抄来");
  var edits = [];
  (b && b.slots || []).forEach(function (s) {
    var val = (n.btexts || {})[s.name];
    if (val != null && val !== s.text) { edits.push(s.label + " = " + val); }
  });
  if (edits.length) { lines.push(ind + "  - 改了文案：" + edits.join("；")); }
  return lines;
}

function mdIndent(depth) { return new Array(depth + 1).join("  "); }

function mdBlock(n, depth) {
  var ind = mdIndent(depth);
  var c = n.content || {};
  if (n.bkey) { return mdBizBlock(n, depth); }
  var head = ind + "- **" + n.label + "**（" + n.wkey + "）";
  if (n.downgraded) {
    return [head + " —— 降级项，Blender 里做不到，不生成代码",
      ind + "  - 原需求：" + n.label,
      ind + "  - 拦路：" + (n.blocker || "（没记）"),
      ind + "  - 改成：" + (n.fallback || "（没记）")];
  }
  var lines = [head];
  lines.push(ind + "  - 元素 ID：" + (n.id ? ("`" + n.id + "`") : "（没填）"));
  lines.push(ind + "  - 代码形态：" + n.uiloayout);
  if (n.params) { lines.push(ind + "  - 参数：" + n.params); }
  var bits = [];
  var spec = contentSpec(n.wkey);
  if (spec) {
    spec.forEach(function (f) {
      var v = c[f.field];
      if (v !== undefined && v !== null && v !== "") {
        bits.push(f.label + " = " + v);
      }
    });
  }
  if (bits.length) { lines.push(ind + "  - 内容：" + bits.join("；")); }
  if (n.errors && n.errors.length) {
    n.errors.forEach(function (e) {
      lines.push(ind + "  - ⚠ 参数被拦：" + e.msg);
    });
  }
  var kids = childrenOf(n.uid);
  if (kids.length) {
    lines.push(ind + "  - 归属：容器，装了 " + kids.length + " 块子积木");
    kids.forEach(function (k) {
      lines.push.apply(lines, mdBlock(k, depth + 2));
    });
  } else if (n.parent) {
    lines.push(ind + "  - 归属：装在「" +
      ((nodeByUid(n.parent) || {}).label || n.parent) + "」里");
  } else {
    lines.push(ind + "  - 归属：顶层");
  }
  return lines;
}

/* 一个界面的树形清单。序号打在每个顶层块的第一行上，不另起一行——
   拆成「1.」+「- …」两行的话，Markdown 里会渲染成两个列表项。 */
function mdTab(k, startNo) {
  var list = boards[k];
  var out = ["### " + TAB_LABELS[k] + "界面（" + list.length + " 块）"];
  if (!list.length) {
    out.push("");
    out.push("还没搭任何积木。");
    return out;
  }
  var i = startNo || 0;
  list.forEach(function (n) {
    if (n.parent) { return; }
    var lines = mdBlock(n, 0);
    i++;
    lines[0] = lines[0].replace(/^- \*\*/, i + ". **");
    out.push("");
    out.push.apply(out, lines);
  });
  return out;
}

function buildMarkdown() {
  var out = [];
  var now = new Date().toISOString().replace("T", " ").slice(0, 19);
  var noted = [];
  var downs = [];
  TAB_ORDER.forEach(function (k) {
    boards[k].forEach(function (n) {
      if (n.downgraded) { downs.push({ tab: TAB_LABELS[k], n: n }); }
      if (n.note) {
        noted.push("- **" + TAB_LABELS[k] + "** / " + n.label +
          (n.id ? ("（`" + n.id + "`）") : "（没填元素 ID）") + "：" + n.note);
      }
    });
  });

  out.push("# 界面方案说明（UI Workbench 导出）");
  out.push("");
  out.push("导出时间：" + now + "　当前界面：**" + TAB_LABELS[activeTab] + "**");
  out.push("");
  out.push("> **这版还没有在真实 Blender 里验证过。**");
  out.push("> 它是在工作台里用积木搭出来的草稿：控件、参数、内容都对着 Blender 实测过的");
  out.push("> 能力边界填，但没有真的 render 过、真的点过。下面附的 ui.py 只是把积木树");
  out.push("> 直译成代码，**不要直接粘进 ui.py 就当完成**——先在 Blender 里跑一遍看效果。");
  out.push("");
  out.push("## 一、当前搭了什么");
  out.push("");
  // 三个界面连续编号：编号只在「一」这一节里有意义，分头从 1 开始会撞号。
  var seq = 0;
  TAB_ORDER.forEach(function (k) {
    out.push.apply(out, mdTab(k, seq));
    seq += boards[k].filter(function (n) { return !n.parent; }).length;
    out.push("");
  });
  out.push("## 二、你的标注原文");
  out.push("");
  if (!noted.length) {
    out.push("（还没有任何标注。选中一块积木、展开它，在「我为什么这么摆」里写一句，");
    out.push("这里就会逐条列出，并标明它挂在哪一块上。）");
  } else {
    out.push("以下是你写的每一条标注，原文照抄，括号里是它挂在哪块上：");
    out.push("");
    out.push.apply(out, noted);
  }
  out.push("");
  out.push("## 三、降级方案（Blender 里做不到的）");
  out.push("");
  if (!downs.length) {
    out.push("（没有降级项。）");
  } else {
    out.push("下面这些是「这条原需求做不到」的记录。代码里不生成对应内容——");
    out.push("谎称它们会出现，预览和 ui.py 就都不诚实了。");
    out.push("");
    downs.forEach(function (d) {
      out.push("- **" + d.n.label + "**（" + d.tab + "界面）");
      out.push("  - 拦路：" + (d.n.blocker || "（没记）"));
      out.push("  - 改成：" + (d.n.fallback || "（没记）"));
    });
  }
  out.push("");
  out.push("## 四、这版还没验证过");
  out.push("");
  out.push("- 没有在真实 Blender 里 render 过，控件的实际尺寸 / 对齐 / 分栏比例都可能要调。");
  out.push("- ui.py 里凡是标着 TODO 的地方（缺算子名、缺属性名）都还没填。");
  out.push("- 参数只对着实测过的允许清单填了，Blender 版本一变就该重测。");
  out.push("");
  return out.join("\n");
}

function buildJSON() {
  return {
    format: "ui_workbench_plan",
    version: 1,
    generated_at: new Date().toISOString(),
    verified_in_blender: false,
    notice: UNVERIFIED_NOTICE,
    // annotations / proposal 这两个键原样留着：既有断言按
    // `var payload = { ... }` 里的这两个字段核对导出内容，不能改名。
    annotations: annotations,
    proposal: proposal,
    active_tab: activeTab,
    boards: boards,
    ui_py: buildPy(),
    markdown: buildMarkdown()
  };
}

/* ---------------- 拿文件：下载 + 复制（两条都有降级）---------------- */

function downloadText(name, text, mime) {
  var blob = new Blob([text], { type: mime || "text/plain;charset=utf-8" });
  var a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  // Blob URL 不 revoke 的话会一直挂在文档的 URL 表上，导个十几次就攒一堆。
  setTimeout(function () { URL.revokeObjectURL(a.href); }, 30000);
  return name;
}

/* 剪贴板三级降级：
     1) navigator.clipboard.writeText —— file:// 下多半没有，或直接被拒；
     2) textarea + execCommand("copy") —— 老办法，Chrome/Edge 的 file:// 通常可行；
     3) 选中文本留在页面上，让人自己 Ctrl+C —— 页面里那份 <pre> 本来就选得中。
   任何一级都不许抛到外面：拿不到剪贴板是一次「没复制上」，不是页面崩了。 */
function copyText(text, done) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        done("clipboard", "已复制到剪贴板");
      }, function () { legacy(); });
      return;
    }
  } catch (e) { /* 走到下面那一级去 */ }
  legacy();

  function legacy() {
    var ta = document.createElement("textarea");
    ta.className = "clipboard-fallback";
    ta.setAttribute("readonly", "readonly");
    ta.value = text;
    // 必须真的挂在文档里：脱离文档的 textarea 选不中，execCommand 直接空转。
    var host = el("py-out") && el("py-out").parentNode;
    (host || document.body).appendChild(ta);
    ta.focus();
    ta.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    if (ok) {
      if (ta.parentNode) { ta.parentNode.removeChild(ta); }
      done("exec-command", "已复制到剪贴板（降级路径）");
    } else {
      ta.dataset.pick = "1";
      done("select-only",
        "这个浏览器不让脚本写剪贴板：代码已经全选在页面上了，按 Ctrl+C 复制");
    }
  }
}

function renderExportPanel() {
  var host = el("export-btns");
  if (!host) { return; }
  host.innerHTML = "";
  function btn(id, text, title, fn) {
    var b = document.createElement("button");
    b.id = id;
    b.textContent = text;
    b.title = title;
    b.onclick = fn;
    host.appendChild(b);
  }
  btn("x-py-copy", "复制 ui.py 代码",
    "把生成的 Python 片段放进剪贴板。剪贴板不可用时会自动降级："
    + "先把代码全选在页面上，你按 Ctrl+C 一样能拿走。",
    function () {
      copyText(buildPy(), function (how, msg) {
        setStatus(msg + "（" + how + "）");
        el("py-out").dataset.copied = how;
      });
    });
  btn("x-py-dl", "下载 ui.py",
    "存成 .py 文件。和上面那一份内容完全一样，只是路径不同。",
    function () {
      var n = downloadText("ui_plan_" + activeTab + ".py", buildPy(),
                           "text/x-python;charset=utf-8");
      setStatus("已下载 " + n + "（草稿，未在 Blender 里验证过）");
    });
  btn("x-md-dl", "下载方案说明（Markdown）",
    "一份人能读、也能据此写实施计划的文档：搭了什么、你的标注原文、"
    + "哪些降级了、哪些还没验证。",
    function () {
      var n = downloadText("ui_plan_" + activeTab + ".md", buildMarkdown(),
                           "text/markdown;charset=utf-8");
      setStatus("已下载 " + n);
    });
  btn("x-json-dl", "下载方案文件（JSON）",
    "三个界面的完整存档（含内容 / 归属 / 标注 / 生成的那份 ui.py），"
    + "以后接着改就靠它。取代了原来那个「导出标注」按钮——那是同一份数据的旧壳。",
    function () {
      var n = downloadText("ui_plan.json",
                           JSON.stringify(buildJSON(), null, 2),
                           "application/json");
      setStatus("已下载 " + n + "（三个界面 " +
        TAB_ORDER.map(function (k) { return TAB_LABELS[k] + " " + boards[k].length; }).join(" / ") +
        "）");
    });
  renderPyOut();
}

function renderPyOut() {
  var pre = el("py-out");
  if (pre) { pre.textContent = buildPy(); }
  /* 统计行紧贴代码上方：导出看着像「完事了」，其实一半的块还是占位。
     不靠红黄绿表达状态（实测主题里没有红也没有绿），靠文字 + 明度差：
     数字用亮色，说明用暗色。 */
  var st = el("py-stat");
  if (!st) { return; }
  st.innerHTML = "";
  var okN = pyStats.total - pyStats.todo;
  var a = document.createElement("span");
  a.className = "code-stat-num";
  a.textContent = "共 " + pyStats.total + " 块 · 其中 " + pyStats.todo +
    " 块带 TODO 占位 · " + okN + " 块已完整";
  var b = document.createElement("span");
  b.className = "code-stat-hint";
  b.textContent = (pyStats.todo > 0)
    ? ("——带占位的 " + pyStats.todo + " 块不能直接粘进 ui.py，先按行首的 # TODO 逐条填真值；"
       + "已完整的那 " + okN + " 块同样还没在真实 Blender 里跑过。")
    : "——每一块都还没在真实 Blender 里跑过，贴进 ui.py 后先看渲染结果。";
  st.appendChild(a);
  st.appendChild(b);
  st.dataset.total = String(pyStats.total);
  st.dataset.todo = String(pyStats.todo);
  st.dataset.ok = String(okN);
}

/* #proposal-select：从右栏点 <-> 从左栏点，两个方向各走一遍真 click。
   存在理由：这一轮新增的双向选中同步没有任何既成钩子覆盖，
   少一个钩子它就只剩「代码看着对」。

   报的每一条都是浏览器真算出来的东西：
     pvSel / pnodeSel  —— 两侧各标了几块（真点一次之后的 DOM 状态）
     outline*          —— getComputedStyle 读出来的描边，不是我们写的类名。
                          把 --accent 换成任何别的色值，这三条立刻红。
     covered / inside  —— 被描边的容器区域里，装着几块子积木、其中几块
                          真的落在那道描边围出来的矩形之内（几何判定）。
                          只描标题行的话 inside 会掉到 0。
     pgroupSel         —— 右栏那个容器的分组框是不是也跟上了 */
function selectReport(fromPreview) {
  var btn = el("demo-panel-btn");
  if (btn) { btn.click(); }
  /* 挑 chat.options（规格竖排）：它是容器，里面还套着「细节横排 -> 三个勾选
     选项」，选中它一次能同时验掉「容器区域含子块都被描边」和「只描标题行不算」。 */
  var target = proposal.filter(function (n) { return n.id === "chat.options"; })[0]
            || proposal.filter(function (n) { return isContainer(n); })[0];

  var attrs = {};
  if (target) {
    var box = el("canvas").querySelector('.pnode[data-uid="' + target.uid + '"]');
    if (fromPreview) {
      var pv = pvOf(target.uid);
      if (pv) {
        pv.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      }
    } else if (box) {
      box.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    }
  }

  var sel = selUid ? pvOf(selUid) : null;
  var cs = sel ? getComputedStyle(sel) : null;
  var covered = 0;
  var inside = 0;
  if (sel) {
    var kids = sel.querySelectorAll("[data-pvuid]");
    covered = kids.length;
    var sr = sel.getBoundingClientRect();
    for (var i = 0; i < kids.length; i++) {
      var kr = kids[i].getBoundingClientRect();
      // 判定用矩形包含而不是 DOM 包含：DOM 包含证明不了「描边真的圈住了它」，
      // 而圈不住正是「只描了标题行」那种做法的症状。
      if (kr.left >= sr.left - 2 && kr.right <= sr.right + 2 &&
          kr.top >= sr.top - 2 && kr.bottom <= sr.bottom + 2) {
        inside++;
      }
    }
  }
  attrs.selUid = String(selUid || "");
  attrs.targetId = target ? target.id : "";
  attrs.pvSel = String(el("preview").querySelectorAll('[data-pvuid][data-sel="1"]').length);
  attrs.pnodeSel = String(el("canvas").querySelectorAll('.pnode[data-sel="1"]').length);
  attrs.pgroupSel = String(el("canvas").querySelectorAll('.pgroup[data-sel="1"]').length);
  attrs.outlineColor = cs ? cs.outlineColor : "";
  attrs.outlineWidth = cs ? cs.outlineWidth : "";
  attrs.outlineStyle = cs ? cs.outlineStyle : "";
  attrs.covered = String(covered);
  attrs.inside = String(inside);
  attrs.status = el("status").textContent || "";

  /* 再点一次 = 取消。量的是点完之后两侧各剩几个标记。 */
  var box2 = el("canvas").querySelector('.pnode[data-uid="' + (selUid || "") + '"]');
  if (box2) { box2.dispatchEvent(new MouseEvent("click", { bubbles: true })); }
  attrs.togglePv = String(el("preview").querySelectorAll('[data-pvuid][data-sel="1"]').length);
  attrs.togglePnode = String(el("canvas").querySelectorAll('.pnode[data-sel="1"]').length);
  attrs.toggleStatus = el("status").textContent || "";

  /* 点空白：点在预览根上（它自己没有 data-pvuid，closest 认不到块）。
     已经取消过了，所以这一步单独量的是「点空白不会凭空把谁选中」。 */
  el("preview").dispatchEvent(new MouseEvent("click", { bubbles: true }));
  attrs.blankPv = String(el("preview").querySelectorAll('[data-pvuid][data-sel="1"]').length);
  attrs.blankSelUid = String(selUid || "");

  /* 反向：这次从预览点，量右栏是不是跟着选中（上面那次量的是预览）。
     留一个真的选中态在页面上，给那张截图用。 */
  if (target) {
    var pv2 = pvOf(target.uid);
    if (pv2) { pv2.dispatchEvent(new MouseEvent("click", { bubbles: true })); }
  }
  attrs.backPvSel = String(el("preview").querySelectorAll('[data-pvuid][data-sel="1"]').length);
  attrs.backPnodeSel = String(el("canvas").querySelectorAll('.pnode[data-sel="1"]').length);

  appendReport("select-report", attrs);
  setStatus("DEMO select 描边 " + attrs.pvSel + " / 容器内 " +
    inside + "/" + covered + " 子块在框内");
}

/* #proposal-select-leaf：从预览点一个**叶子**块（多行输入框）。
   和 #proposal-select 分开是因为叶子没有子块，量的是另一件事：
   描边应当只圈住它自己那一格，不牵连容器里的别的块。
   也给「点预览里的区域」那张截图用——容器那张与 #proposal-select 长得一样。 */
function selectLeafReport() {
  var btn = el("demo-panel-btn");
  if (btn) { btn.click(); }
  var target = proposal.filter(function (n) { return n.wkey === "textbox"; })[0];
  if (target) {
    var pv = pvOf(target.uid);
    if (pv) { pv.dispatchEvent(new MouseEvent("click", { bubbles: true })); }
  }
  var sel = selUid ? pvOf(selUid) : null;
  var cs = sel ? getComputedStyle(sel) : null;
  appendReport("select-leaf-report", {
    targetWkey: target ? target.wkey : "",
    selUid: String(selUid || ""),
    pvSel: String(el("preview").querySelectorAll('[data-pvuid][data-sel="1"]').length),
    pnodeSel: String(el("canvas").querySelectorAll('.pnode[data-sel="1"]').length),
    covered: String(sel ? sel.querySelectorAll("[data-pvuid]").length : -1),
    outlineColor: cs ? cs.outlineColor : "",
    outlineWidth: cs ? cs.outlineWidth : "",
    status: el("status").textContent || ""
  });
  setStatus("DEMO select-leaf 从预览点中一个叶子块");
}

/* #proposal-save：把方案写进 localStorage，再原样读回来逐字核对。
   核对的是「读回来的东西」而不是「写的时候没抛异常」——JSON.stringify
   对着一个带环的对象会安静地抛 TypeError，对着一个少字段的对象会安静地
   写出去，两种都得在这里现形。 */
function saveReport() {
  var btn = el("demo-panel-btn");
  if (btn) { btn.click(); }
  /* 真敲一次标注进去：只存内容的存盘，标注丢了照样全绿，
     而标注恰恰是「告诉你」这件事里唯一不可替代的部分。 */
  var target = proposal.filter(function (n) { return n.id === "chat.stream"; })[0];
  var noteBox = null;
  if (target) {
    target.expanded = true;
    renderCanvas();
    var tbox = el("canvas").querySelector('.pnode[data-uid="' + target.uid + '"]');
    noteBox = tbox ? tbox.querySelector('[data-field="note"]') : null;
  }
  if (noteBox) {
    noteBox.value = "这句注解必须在刷新之后还在";
    noteBox.dispatchEvent(new Event("input", { bubbles: true }));
  }
  var blocks = proposal.length;
  var wrote = savePlan();

  var back = null;
  try {
    back = JSON.parse(localStorage.getItem(PLAN_KEY) || "null");
  } catch (e) {
    back = null;
  }
  var got = back && back.boards && back.boards.chat ? back.boards.chat : [];
  var rt = got.filter(function (n) { return n.id === "chat.stream"; })[0];
  var nested = got.filter(function (n) { return n.parent; }).length;

  appendReport("save-report", {
    lsOK: lsOK ? "1" : "0",
    wrote: wrote ? "1" : "0",
    blocks: String(blocks),
    stored: String(got.length),
    nested: String(nested),
    note: rt ? (rt.note || "") : "",
    content: rt && rt.content ? JSON.stringify(rt.content) : "",
    parent: rt ? String(rt.parent || "") : "",
    uidSeq: String(back && back.uid_seq >= 0 ? back.uid_seq : -1),
    banner: el("store-warn").hidden ? "" : "shown"
  });
  setStatus("DEMO save 存了 " + got.length + " / " + blocks + " 块");
}

/* #proposal-restore：另一个页面（同一份浏览器档案，所以 localStorage 是通的）
   冷启动时把存档读回来。跑在两个不同的 --dump-dom 里，与真实刷新同一条路径。 */
function restoreReport() {
  var back = loadPlan();
  var got = back && back.boards && back.boards.chat ? back.boards.chat : [];
  var rt = got.filter(function (n) { return n.id === "chat.stream"; })[0];
  /* 报用户实际会看到的那句，而不是钩子自己编的一句：
     loadState 收尾时会用它改写状态条，所以它就是真正的出口。 */
  var notice = restoreNotice();
  setStatus(notice);
  appendReport("restore-report", {
    lsOK: lsOK ? "1" : "0",
    restored: String(proposal.length),
    blocks: String(boards.chat.length),
    detail: String(boards.detail.length),
    settings: String(boards.settings.length),
    note: rt ? (rt.note || "") : "",
    nested: String(got.filter(function (n) { return n.parent; }).length),
    uidSeq: String(uidSeq),
    status: notice
  });
  setStatus(notice || ("DEMO restore 恢复 " + proposal.length + " 块"));
}

/* #proposal-export：把三种导出各真跑一遍，把产物报出来。
   报的必须是「生成出来的字符串」，不是「有没有点过按钮」——
   生成器本身写错了（少一层缩进、把 note 吞了）的话，点一百次也是错的。 */
function exportReport() {
  var btn = el("demo-panel-btn");
  if (btn) { btn.click(); }
  /* 示例面板里没有分隔线，所以顺手真点一个上来：
     翻译器里 separator / scale_y 那两条分支，光靠示例数据永远走不到，
     「代码看着对」就又变成了唯一证据。 */
  var vb = el("vocab-bar").querySelector('button[data-wkey="separator"]');
  if (vb) { vb.click(); }
  /* 先把面板刷新一次：上面刚点进来的分隔线得进 <pre>，也得出现在统计行里。
     不刷的话下面量到的 pyStats 与用户眼前那行数字对不上。 */
  renderPyOut();
  var py = buildPy();
  var md = buildMarkdown();
  var js = buildJSON();
  /* 标注那一条必须对着真数据核对：随便找一条带标注的积木，
     检查它的原文真的进了 Markdown。写死一句示例文案的话，
     生成器把 note 整个吞掉也照样绿。 */
  var noted = proposal.filter(function (n) { return !!n.note; })[0];
  var lines = py.split("\n");
  /* 缩进是这个生成器最要紧的形状：Blender 的 UILayout 不是上下文管理器，
     row = layout.row() 后面那几行必须和它自己同列，多一格贴进 ui.py 就是
     IndentationError。
     量的不是「容器行的下一行差几列」——没有子块的容器后面那行是它的兄弟，
     差 0 是碰巧，不是证据（上一版就是这么挑错了行）。这里按树去找：
     每个容器的第一块子积木 vs 容器自己，差必须是 0。 */
  var COLS = pyCols;
  var deltas = [];
  for (var ci = 0; ci < proposal.length; ci++) {
    var node = proposal[ci];
    if (CONTAINER_WKEYS.indexOf(node.wkey) < 0) { continue; }
    var kids = childrenOf(node.uid);
    if (!kids.length) { continue; }
    deltas.push(COLS[proposal.indexOf(kids[0])] - COLS[ci]);
  }
  var mapKeys = [];
  for (var ki = 0; ki < proposal.length; ki++) {
    if (COLS[ki] === undefined) { continue; }
    mapKeys.push(ki);
  }
  var pyLines = lines.length;
  /* 数的是「哪种调用出现了几次」，不是「有几行字里写着 layout.」：
     子积木画在容器变量上（row.operator(...)），不是全都挂在 layout 上，
     按 layout.operator( 数会一个都数不到——这条断言就是这么写错过一次的。 */
  var sepLines = lines.filter(function (l) {
    return /\.separator\(\)/.test(l);
  }).length;
  var opLines = lines.filter(function (l) {
    return /\.operator\(/.test(l);
  }).length;
  /* TODO 只数「代码里那些占位语句」，不算注释、更不算文末清单里复述它们
     的那几行：清单条目本身也写着 TODO_算子名待定，一并数进去就翻倍了。
     判据是「非注释行里出现 TODO」——正好是用户扫代码时会看见的那些行。 */
  var cut = lines.findIndex(function (l) {
    return /落笔前必须人工处理的/.test(l);
  });
  var codePart = lines.slice(0, cut < 0 ? lines.length : cut);
  var todoStmts = codePart.filter(function (l) {
    var t = l.trim();
    return t.indexOf("#") !== 0 && /TODO/.test(t);
  });
  var todoFlags = codePart.filter(function (l) {
    return /^\s*#\s*TODO:/.test(l);
  });
  appendReport("export-report", {
    pyLines: String(pyLines),
    pyHead: lines.slice(0, 4).join(" / ").slice(0, 200),
    pyHasFunc: /def draw_chat_content\(layout, state\):/.test(py) ? "1" : "0",
    pyChildDeltas: deltas.join(","),
    pyChildDeltaN: String(deltas.length),
    pyIndentMap: mapKeys.map(function (i) { return i + ":" + COLS[i]; }).join(" "),
    pyBlockKeys: mapKeys.map(function (i) {
      return proposal[i].wkey + "|" + (proposal[i].id || "");
    }).join(" "),
    pyStatTotal: String(pyStats.total),
    pyStatTodo: String(pyStats.todo),
    pyStatOk: String(pyStats.total - pyStats.todo),
    pyStatShown: String(((el("py-stat") || {}).textContent || "").length),
    pyTodoFlagged: String(todoFlags.length),
    pyHasNote: noted && py.indexOf(noted.note) >= 0 ? "1" : "0",
    pyHasUnverified: (py.match(/未经验证/g) || []).length,
    pyHasSep: String(sepLines),
    pyHasOp: String(opLines),
    pyTodo: String(todoStmts.length),
    pyChecks: (py.match(/必须人工处理的 (\d+) 处/) || [0, "?"])[1],
    mdLines: String(md.split("\n").length),
    mdHasTree: /## 一、当前搭了什么/.test(md) ? "1" : "0",
    mdHasNotes: /## 二、你的标注原文/.test(md) ? "1" : "0",
    mdHasDown: /## 三、降级方案/.test(md) ? "1" : "0",
    mdHasUnverified: /还没有在真实 Blender 里验证过/.test(md) ? "1" : "0",
    mdHasNoteText: noted && md.indexOf(noted.note) >= 0 ? "1" : "0",
    mdNoteId: noted ? (noted.id || "") : "",
    jsonKeys: Object.keys(js).sort().join(","),
    jsonBoards: String(Object.keys(js.boards || {}).length),
    jsonPy: js.ui_py === py ? "1" : "0",
    jsonVerified: js.verified_in_blender === false ? "1" : "0",
    pre: (el("py-out").textContent || "").length
  });
  setStatus("DEMO export ui.py " + pyLines + " 行 / 说明 " +
    md.split("\n").length + " 行");
}

/* #proposal-demo-<tab> 里的 <tab>：子页签名，结尾可以缀一个 "-open"
   （全部展开，给「要看清树线」的那张截图用）。这里只做切分，
   switchTab 仍然只接受 boards 里真有的名字——写错页签名照样什么都不做。 */
function demoTabSpec(rest) {
  var s = String(rest || "");
  return s.slice(-5) === "-open" ? s.slice(0, -5) + "|open" : s;
}

function runDemoHook(hash) {
  var h = String(hash || "").replace(/^#/, "");
  /* 业务块钩子（#biz-*）在进 runDemoHook 之前就被接走了：它们测的是
     界面块那一层（无嵌套 / 无参数框 / 导出原样带走 ui.py），
     与底下那套 UILayout 原语的钩子互不相干。 */
  if (h.indexOf("biz-") === 0) { runBizHook(h); return; }
  var kind = (h === "proposal-all") ? "all"
           : (h === "proposal-blocked") ? "blocked"
           : (h === "proposal-typing") ? "typing"
           : (h === "proposal-del") ? "del"
           : (h === "proposal-dup") ? "dup"
           : (h === "proposal-drag") ? "drag"
           : (h === "proposal-undo") ? "undo"
           : (h === "proposal-fold") ? "fold"
           : (h === "proposal-examples") ? "examples"
           : (h === "proposal-panel") ? "panel"
           : (h === "proposal-preview") ? "preview"
           : (h === "proposal-nest") ? "nest"
           : (h === "proposal-move") ? "move"
           : (h === "proposal-select") ? "select"
           : (h === "proposal-select-back") ? "select-back"
           : (h === "proposal-select-leaf") ? "select-leaf"
           : (h === "proposal-save") ? "save"
           : (h === "proposal-restore") ? "restore"
           : (h === "proposal-export") ? "export"
           : (h.indexOf("proposal-demo-") === 0) ? "demo-" + demoTabSpec(h.slice("proposal-demo-".length))
           : (h === "proposal-empty") ? "empty" : null;
  if (!kind) { return; }
  switchView("proposal");
  loadVocab().then(function () {
    el("vocab-bar").innerHTML = "";
    el("prop-notes").innerHTML = "";
    renderVocabBar();
    renderRejected();
    renderElementIdHelp();
    renderUnmapped();
    if (kind === "empty") { setStatus("DEMO empty 控件 0 降级 0"); return; }
    if (kind === "examples") { examplesReport(); return; }
    if (kind === "panel") { panelReport(); return; }
    if (kind === "nest") { nestReport(); return; }
    if (kind === "move") { moveReport(); return; }
    if (kind === "select") { selectReport(false); return; }
    if (kind === "select-back") { selectReport(true); return; }
    if (kind === "select-leaf") { selectLeafReport(); return; }
    if (kind === "save") { saveReport(); return; }
    if (kind === "restore") { restoreReport(); return; }
    if (kind === "export") { exportReport(); return; }
    /* #proposal-demo-<tab>：切到那个子页签并插入它自己的示例面板。
       给无头截图用——人眼要看的就是「切到详情之后，右边是不是详情那套积木」，
       而这件事只有走真实的 switchTab + 真实的示例面板按钮才说得清。
       截图是给人看的，所以这里只把画布摆好，不往 DOM 里塞验收报告。
       结尾再缀一个 "-open" 就把每块都展开：折叠态看不出树线与分组框，
       展开态才看得出「哪几块装在谁里面」。 */
    if (kind.indexOf("demo-") === 0) {
      var parts = kind.slice(5).split("|");
      switchTab(parts[0]);
      var btn = el("demo-panel-btn");
      if (btn) { btn.click(); }
      if (parts[1] === "open") {
        proposal.forEach(function (n) { n.expanded = true; });
        renderCanvas();
      }
      return;
    }
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
    if (kind === "fold") { foldReport(); return; }
    if (kind === "preview") { previewReport(); return; }
    var down = proposal.filter(function (x) { return x.downgraded; }).length;
    var blocked = proposal.filter(function (x) { return x.errors.length > 0; }).length;
    setStatus("DEMO " + kind + " 控件 " + (proposal.length - down) +
      " 降级 " + down + " 违规 " + blocked);
  }).catch(function (e) {
    setStatus("DEMO 失败：" + e.message);
  });
}

/* ---------------- 业务块的验收钩子（#biz-*）----------------
   这些 hash 只给无头 Edge 用（dev/test_proposal_blocks.py）与截图用，
   真人打开工作台永远是空 hash 或 #idle。它们刻意只点**真实按钮**、
   只读**浏览器算出来的东西**，不直接调内部函数——否则验的就不是
   用户点的那条路了。

     #biz-empty   只切视图，什么都不插（看空态与控件架）
     #biz-all     把 16 块全点一遍
     #biz-demo    插一个 6 块的对话界面（截图 2 用）
     #biz-report  插完跑一遍读数并报出来：块数 / 有没有嵌套 /
                  有没有参数框 / 变体下拉 / 拖动重排 / 文案改动是否落到导出
     #biz-export  报出导出的 ui.py 全文（验它能被 ast.parse） */
function runBizHook(hash) {
  var h = String(hash || "").replace(/^#/, "");
  var kind = h.indexOf("biz-") === 0 ? h.slice(4) : null;
  /* 结尾缀 -narrow：把左边那块预览压到 280px。
     这是「响应式图标」那一条的真实验证入口——不是把 class 换掉就宣布
     图标没了，而是压窄之后由浏览器自己重新算一遍样式，再把算出来的
     display 报出来（见 bizIconReport）。
     -wide 则反过来把面板拉到 560px：用来证明「盒宽 = 面板宽」——把面板
     拉宽，同一段文字每行的字就变多。 */
  var narrow = false;
  if (kind && kind.slice(-7) === "-narrow") {
    narrow = true;
    kind = kind.slice(0, -7);
  }
  var wide = false;
  if (kind && kind.slice(-5) === "-wide") {
    wide = true;
    kind = kind.slice(0, -5);
  }
  /* all-detail / all-settings：先把画布切到那个界面再点满它那一层的块。
     控件架上的卡片本来就按界面过滤，留在对话页点按钮只会点中对话那 7 张。 */
  var tab = null;
  var tm = /^taball-(chat|detail|settings)$/.exec(kind || "");
  if (tm) { kind = "taball"; tab = tm[1]; }
  if (kind === "taball-detail" || kind === "taball-settings") {
    tab = kind.slice("taball-".length);
    kind = "taball";
  }
  if (!kind) { return; }
  switchView("proposal");
  loadVocab().then(function () {
    if (narrow) { setNarrowPanel(true); }
    if (wide) { document.body.classList.add("uw-panel-560"); renderCanvas(); }
    if (tab) { switchTab(tab); }
    if (kind === "empty") {
      setStatus("BIZ empty 块 0" + (narrow ? "（面板已压窄）" : ""));
      return;
    }
    if (kind === "taball") {
      /* 只点**当前界面**那几块：控件架把三个界面的卡片都放在 DOM 里，
         一把 querySelectorAll 会把 16 块全插进对话这份画布，
         截图上就是「对话页里混着详情和设置的块」。#biz-all 仍然是
         三个界面全点一遍（dev/test_proposal_blocks.py 的 dom_all_* 用它）。 */
      var bs = el("vocab-bar").querySelectorAll("button[data-bkey]");
      var n = 0;
      for (var i = 0; i < bs.length; i++) {
        var cd = bs[i].closest ? bs[i].closest(".bcard") : null;
        if (cd && cd.dataset.tab && cd.dataset.tab !== activeTab) { continue; }
        bs[i].click();
        n++;
      }
      /* 截图模式：控件架收掉、页面回到最上面，不然无头 --screenshot 只截
         视口，截到的是一屏卡片，看不见用户真正要看的那块界面预览。
         真人打开工作台永远不会带上这个 class（只有 #biz-taball 会加）。 */
      document.body.classList.add("uw-shot-canvas");
      if (window.scrollTo) { window.scrollTo(0, 0); }
      setStatus("BIZ taball " + activeTab + " 块 " + proposal.length +
                "（点了 " + n + " 张卡）");
      return;
    }
    if (kind === "all") {
      var all = el("vocab-bar").querySelectorAll("button[data-bkey]");
      for (var i2 = 0; i2 < all.length; i2++) { all[i2].click(); }
      setStatus("BIZ all 块 " + proposal.length);
      return;
    }
    if (kind === "icons") { insertBizDemo(); bizIconReport(narrow); return; }
    if (kind === "msg") { insertBizDemo(); bizMsgReport(null); return; }
    if (kind === "wrap") { insertBizDemo(); bizWrapReport(); return; }
    if (kind === "msg-folded") { insertBizDemo(); bizMsgReport(false); return; }
    if (kind === "msg-open") { insertBizDemo(); bizMsgReport(true); return; }
    if (kind === "demo") { insertBizDemo(); return; }
    if (kind === "report") { insertBizDemo(); bizReport(); return; }
    if (kind === "export") { insertBizDemo(); bizExportReport(); return; }
    setStatus("BIZ 未知钩子：" + kind);
  }).catch(function (e) {
    setStatus("BIZ 失败：" + e.message);
  });
}

/* 把预览面板压窄 / 放回默认宽度。压窄这件事只有截图与无头验收用得着，
   所以走 body 上的一个 class，而不是去改 style.css 的行内宽度。 */
function setNarrowPanel(on) {
  document.body.classList.toggle("uw-narrow-panel", !!on);
  renderCanvas();
}

/* 响应式图标的无头验收：报两遍——默认（宽）面板下图标角标的 display，
   以及压窄到 280px 之后浏览器重新算出来的 display。
   量的是 getComputedStyle，不是「class 有没有设」，所以这条断言坏掉时
   只可能是真的坏了：要么 CSS 写错了，要么响应式根本没生效。 */
function bizIconReport(narrow) {
  if (narrow) { setNarrowPanel(true); }
  var host = el("preview");
  function readState() {
    function visible(sel) {
      var xs = host.querySelectorAll(sel);
      var shown = 0;
      for (var i = 0; i < xs.length; i++) {
        var cs = host.ownerDocument.defaultView.getComputedStyle(xs[i]);
        if (cs.display !== "none" && cs.visibility !== "hidden") { shown++; }
      }
      return { total: xs.length, shown: shown };
    }
    return {
      ico: visible(".d-ic"), tx: visible(".d-tx"),
      panel: Math.round(host.getBoundingClientRect().width)
    };
  }
  var wide = readState();
  /* 压窄 → 同一批元素重新算样式 → 再读一遍。两读都必须来自真实布局，
     所以中间不能只改一个 class 就立刻读：renderCanvas 已经同步重画。 */
  setNarrowPanel(!narrow);
  var thin = readState();
  setNarrowPanel(!!narrow);
  /* dataset 的键不许带横线：写 "wide-total" 会直接抛 TypeError
     （DOMStringMap 不是普通对象），整条钩子就哑了。落到 DOM 上是
     data-wide-ico-total，Python 那边按横线读回来。 */
  appendReport("biz-icons", {
    "wideIcoTotal": String(wide.ico.total),
    "wideIcoShown": String(wide.ico.shown),
    "wideTextTotal": String(wide.tx.total),
    "wideTextShown": String(wide.tx.shown),
    "widePanel": String(wide.panel),
    "narrowIcoTotal": String(thin.ico.total),
    "narrowIcoShown": String(thin.ico.shown),
    "narrowTextTotal": String(thin.tx.total),
    "narrowTextShown": String(thin.tx.shown),
    "narrowPanel": String(thin.panel),
    "tabs": tabsReading(),
    "status": statusReading(),
    "pills": pillsReading(),
    "qs": qsReading(),
    "composer": composerReading(),
    "msg": msgShapeReading()
  });
}

/* 对话输入区：标签与输入框**合成一处**——标签是这个盒的直接孩子（不是
   另一个 .d-crow 里的），输入框同样是这个盒的直接孩子、摊满盒宽、排在标签
   下面。最后一格报「盒里还有没有『高度 3』那类滑块」：只查有没有
   .d-textbox 是不够的，滑块删没删它照样成立。 */
function composerReading() {
  var card = document.querySelector('.bcard[data-bcard-for="chat_composer"] .demo');
  if (!card) { return ""; }
  var box = card.querySelector(".d-textbox");
  var its = card.querySelectorAll(".d-it");
  var lab = its.length ? its[0] : null;
  var txt = (card.textContent || "");
  if (!box || !lab) {
    return [card.dataset.dkind, String(its.length), box ? "1" : "0",
            "none", "none", "0"].join(":");
  }
  var br = box.getBoundingClientRect();
  var lr = lab.getBoundingClientRect();
  var sibling = (box.parentNode === card && lab.parentNode === card);
  var span = (br.width >= lr.width - 1);
  var below = (br.top >= lr.bottom - 1);
  return [card.dataset.dkind, String(its.length), "1",
          sibling ? "sibling" : "split",
          (span && below) ? "merged" : "loose",
          (txt.indexOf("高度") >= 0) ? "1" : "0"].join(":");
}

/* 状态提示条卡片：「正在做什么」那一格是**盒里的正文**，不是又一个控件。
   判据是浏览器算出来的边框宽度——数据里写了 bare、渲染器也可能照抄，
   但只要 CSS 还给它画了边框，盒里就还是两层框。 */
function statusReading() {
  var card = document.querySelector('.bcard[data-bcard-for="chat_status"] .demo');
  if (!card) { return ""; }
  var its = card.querySelectorAll(".d-it");
  if (!its.length) { return ""; }
  var cs = hostCs(its[0]);
  var bcs = hostCs(card);
  return [card.dataset.dkind, String(its.length),
          (cs.borderTopWidth === "0px") ? "bare" : "boxed",
          (bcs.borderTopWidth !== "0px") ? "boxed" : "bare"].join(":");
}

/* 你说的话：一个盒，到此为止。量的是浏览器算出来的边框宽度——
   外层气泡盒有边框，里面那段文字没有边框。有没有第二个带边框的盒子，
   不看 DOM 结构（.d-msgtext 本来就只有一个），看它自己画没画边框。
   后三格是盒宽那条：盒子的宽度（应等于容器宽，不许写死）、文字占多宽、
   以及一个固定的行高——「把面板拉宽，每行的字变多」就是拿
   宽面板的每行字数 减去 窄面板的每行字数 来验的。 */
var MSG_LINE_H = 16;
/* 这一段文字**真的**排成几行：拿 Range 把内容框住，数它自己的行盒有几个
   不同的 top。用 clientHeight / 行高去估是不行的——.d-msgtext 在盒里是
   flex 项、会被拉满盒高，折与不折量出来都是同一个数。 */
function lineCount(t) {
  if (!t) { return 0; }
  var r = t.ownerDocument.createRange();
  r.selectNodeContents(t);
  var tops = {};
  var rs = r.getClientRects();
  for (var i = 0; i < rs.length; i++) {
    if (rs[i].height > 0) { tops[String(Math.round(rs[i].top))] = "1"; }
  }
  return Object.keys(tops).length;
}

function msgShapeReading() {
  var demo = el("preview").querySelector(".demo.d-msgtxt");
  if (!demo) { return ""; }
  var cs = hostCs(demo);
  var txt = demo.querySelector(".d-msgtext");
  var ts = txt ? hostCs(txt) : null;
  var tr = txt ? txt.getBoundingClientRect() : null;
  return [demo.dataset.dkind,
          (cs.borderTopWidth !== "0px") ? "boxed" : "bare",
          (ts && ts.borderTopWidth === "0px") ? "plain" : "boxed",
          String(demo.querySelectorAll(".d-group").length),
          tr ? String(Math.round(tr.width)) : "0",
          String(Math.round((tr ? tr.width : 0) / MSG_LINE_H))].join(":");
}

/* 「文字宽度跟盒宽度一样」：同一个气泡在宽面板与窄面板下各量一次每行字数。
   宽的必须明显更多——不多就说明盒宽被写死了、或者文字被塞进了窄栏里。
   这一格只有预览能量得到（Blender 那边量不到像素），所以它就是这条的判据。 */
function msgWrapReading() {
  if (!el("preview").querySelector(".demo.d-msgtxt")) { return ""; }
  /* 每次量完都要重新取节点：setNarrowPanel 会 renderCanvas()，重画之后
     手里那个 .d-msgtext 已经不在文档里了，拿旧引用量宽度会永远量到同一个值。 */
  function perLine() {
    var txt = el("preview").querySelector(".demo.d-msgtxt .d-msgtext");
    if (!txt) { return { px: 0, cpl: 0, lines: 0 }; }
    var w = Math.round(txt.getBoundingClientRect().width);
    var lines = Math.max(1, lineCount(txt));
    return { px: w, cpl: Math.ceil(Number(txt.dataset.dmsglen || 0) / lines),
             lines: lines };
  }
  setNarrowPanel(true);
  var th = perLine();
  setNarrowPanel(false);
  var wd = perLine();
  return [String(th.lines), String(th.cpl), String(wd.lines), String(wd.cpl),
          String(wd.px), String(th.px)].join(":");
}

function hostCs(e) {
  return e.ownerDocument.defaultView.getComputedStyle(e);
}

/* 页签条那个卡片：三个页签到底写着什么。这条只量文字本身，
   「有没有 AI 那两个字」是一次改名就会漂的事，写死不如现场读。 */
function tabsReading() {
  var card = document.querySelector('.bcard[data-bcard-for="chat_tabbar"] .demo');
  if (!card) { return ""; }
  var out = [];
  card.querySelectorAll(":scope > .d-it").forEach(function (it) {
    /* 只读文字本身：textContent 会把图标角标那个名字一起读进来，
       断言就会去比「COMMUNITY对话」这种没人写的串。 */
    out.push(it.lastChild ? it.lastChild.textContent : "");
  });
  return out.join("|");
}

/* 快捷指令网格那个卡片：四个方块是不是真的排在同一行。
   量的是浏览器算出来的 top 与宽度，不是数据里的 cols——数据写 4 而 CSS
   没跟上，这里就会量出两个不同的 top。 */
function pillsReading() {
  var card = document.querySelector('.bcard[data-bcard-for="chat_pills"] .demo');
  if (!card) { return ""; }
  var its = card.querySelectorAll(".d-it");
  var tops = {};
  var ws = [];
  its.forEach(function (it) {
    var r = it.getBoundingClientRect();
    tops[String(Math.round(r.top))] = "1";
    ws.push(String(Math.round(r.width)));
  });
  return its.length + ":" + Object.keys(tops).length + ":" + ws.join(",") +
    ":" + card.querySelectorAll(".d-ic").length;
}

/* 规格选项组那个卡片：外层一个盒装下引子 + 三组细节，每组细节自己一个盒。
   「引子是不是这个盒的直接孩子」这条是第 2 条的全部：文字与按钮同盒，
   文字就是盒里的第一个直接孩子，按钮在盒里的分组中。 */
function qsReading() {
  /* 排版必须在**预览**里量，不是在控件架那张卡上：卡只有 210px 宽，
     量出来的是「这么窄排不下三行」——而用户真正看的是左边那块预览。
     预览里带分组的 demo 只有规格选项组这一个，所以按 data-dgroups 找。 */
  var card = el("preview").querySelector(".demo[data-dgroups]") ||
             document.querySelector('.bcard[data-bcard-for="chat_questions"] .demo');
  if (!card) { return ""; }
  var intro = card.querySelector(':scope > .d-it');
  var gs = card.querySelectorAll(".d-group");
  var per = [];
  var rows = [];
  var flows = [];
  gs.forEach(function (g) {
    var is = g.querySelectorAll(".d-it");
    per.push(is.length);
    /* 每组细节里的选项真的排成几行：数浏览器算出来的不同 top。
       「字少就横排」这一条就是这个数——3 个选项挤在一行才是横排，
       数 DOM 层级（有几个 .d-it）永远量不出排版。 */
    var tops = {};
    for (var i = 0; i < is.length; i++) {
      tops[String(Math.round(is[i].getBoundingClientRect().top))] = "1";
    }
    rows.push(Object.keys(tops).length);
    flows.push(g.dataset.dflow || "?");
  });
  var titles = [];
  gs.forEach(function (g) {
    titles.push((g.dataset.dgtitle || ""));
  });
  return [card.dataset.dkind, intro ? intro.textContent : "", gs.length,
          per.join("/"), titles.join("|"),
          /* 那个盒里除了引子还装不装按钮：第 2 条的全部就是这一格。
             只报「外层是 box、引子是它的直接孩子」是不够的——把里层整层
             删掉，前两句照样成立，于是「文字和按钮同盒」没人验。 */
          card.querySelector(".d-group") ? "same" : "bare",
          card.querySelectorAll(".d-ic").length,
          rows.join("/"), flows.join("/")].join(":");
}

/* 一套 6 块的对话界面。挑法：页签条 / 状态提示条 / 消息气泡 /
   对话输入区 / 底部操作行 / 规格选项组——正好是插件对话面板里从上到下
   真实存在的那几块（ui.py 的 draw_chat_content）。 */
function insertBizDemo() {
  var want = ["chat_tabbar", "chat_status", "chat_bubble", "chat_questions",
              "chat_composer", "chat_actions"];
  want.forEach(function (k) {
    var b = blockByKey(k);
    if (b) { addBizBlock(b); }
  });
  setStatus("BIZ 已插入 " + proposal.length + " 块（对话面板）");
}

/* 长消息折叠的无头验收 + 截图入口。

   先折着读一遍、再展开读一遍，两遍都读**浏览器算出来的东西**：
   折叠态要看得见省略号、也要看得见展开指示（不是一个光看不知道什么意思的
   小三角）；展开态要真的多出全文。导出那一遍同时验「状态存在积木上、
   导出时没丢」——用户在预览里点开了，导出里的 open_default 就得是 True。

   shotState 为 null 时只读数（测试用）；true / false 时把画布停在那个状态
   并收起控件架，供无头截图用。 */
function bizMsgReport(shotState) {
  var node = proposal.filter(function (n) { return n.bkey === "chat_bubble"; })[0];
  if (!node) { setStatus("BIZ msg 没插进 chat_bubble"); return; }
  node.msgOpen = false;
  renderCanvas();
  var folded = msgProbe();
  var pyClosed = buildPy();
  node.msgOpen = true;
  renderCanvas();
  var open = msgProbe();
  var pyOpen = buildPy();
  appendReport("biz-msg", {
    "foldedText": folded.text,
    "foldedDots": folded.dots,
    "foldedTrunc": folded.trunc,
    "foldedToggle": folded.toggle,
    "foldedLines": folded.lines,
    "foldedPos": folded.pos,
    "openText": open.text,
    "openDots": open.dots,
    "openTrunc": open.trunc,
    "openToggle": open.toggle,
    "openPos": open.pos,
    "shape": msgShapeReading(),
    "pyClosed": (pyClosed.indexOf("open_default=False") >= 0) ? "1" : "0",
    "pyOpen": (pyOpen.indexOf("open_default=True") >= 0) ? "1" : "0",
    "pyHasPanel": (pyOpen.indexOf("layout.panel") >= 0) ? "1" : "0",
    "pyHasDefaultClosed": (pyOpen.indexOf("default_closed") >= 0) ? "1" : "0",
    "pyLines": String(pyOpen.split("\n").length)
  });
  if (shotState !== null) {
    node.msgOpen = !!shotState;
    renderCanvas();
    document.body.classList.add("uw-shot-canvas");
    if (window.scrollTo) { window.scrollTo(0, 0); }
    setStatus("BIZ msg " + (shotState ? "展开态" : "折叠态"));
    return;
  }
  setStatus("BIZ msg 折叠/展开两态都读完了");
}

/* 折叠态长什么样：text 是显示出来的那段，dots 是有没有省略号，
   trunc 是「原文比显示的长」（也就是确实被折了），toggle 是展开指示的文字。
   trunc 比 dots 强：省略号可以由别处带来，trunc 比的是原文长度。 */
function msgProbe() {
  var demo = el("preview").querySelector(".demo.d-msgtxt");
  if (!demo) {
    return { text: "", dots: "0", trunc: "0", toggle: "", lines: "0", pos: "none" };
  }
  var t = demo.querySelector(".d-msgtext");
  var g = demo.querySelector(".d-msgfold");
  var txt = t ? t.textContent : "";
  var full = t ? Number(t.dataset.dmsglen || 0) : 0;
  /* 按钮在不在右下角：拿浏览器算出来的几何位置对**盒子内容区**的右下角，
     不看 CSS 里写没写 align-self——写了但被别处的规则盖掉、或者干脆是
     行尾而不是角上时，这里都要红。 */
  var pos = "none";
  if (g) {
    var hr = demo.getBoundingClientRect();
    var gr = g.getBoundingClientRect();
    var pcs = hostCs(demo);
    var ir = hr.right - (parseFloat(pcs.paddingRight) || 0);
    var ib = hr.bottom - (parseFloat(pcs.paddingBottom) || 0);
    pos = (gr.right >= ir - 2 && gr.bottom >= ib - 2) ? "br" : "elsewhere";
  }
  return {
    text: txt,
    dots: (txt.indexOf("…") >= 0) ? "1" : "0",
    trunc: (full > txt.length) ? "1" : "0",
    toggle: g ? g.textContent : "",
    lines: String(lineCount(t)),
    pos: pos
  };
}

function bizReport() {
  var canvas = el("canvas");
  /* 插完那一刻的块序（还没拖动）：页签条必须排在状态提示条上面。
     报出来的是 bkey 序列，测试那边按头两个比——只报「块数」的话，
     顺序反了根本看不出来。 */
  var order0 = proposal.map(function (n) { return n.bkey; }).join(",");
  /* 拖动重排：把第 1 块挪到最后。派发真的 DragEvent 走一遍真链路，
     不直接调 reorderTo——要验的就是「用户拖一下会怎样」。 */
  var before = uidListOf(proposal);
  var boxes = canvas.querySelectorAll('.bnode[data-uid]');
  if (boxes.length > 1) {
    fireDrag(boxes[0], "dragstart", 0, null);
    var last = boxes[boxes.length - 1];
    var r = last.getBoundingClientRect();
    fireDrag(last, "dragover", r.bottom - 2, null);
    fireDrag(last, "drop", r.bottom - 2, null);
  }
  clearDrag();
  var after = uidListOf(proposal);

  /* 文案改动：把状态提示条（busy 变体）那个「终止任务」改成别的，
     看它有没有真的落到导出的代码里。

     用「改前 / 改后各数一遍出现次数」而不是「改完就全文不该有这句」：
     插件里「终止任务」这四个字不止一处（对话输入区的 else 分支也有），
     按全文找会得到一个恒假的断言。真正要证明的是**这一处**被换掉了。 */
  var status = proposal.filter(function (n) { return n.bkey === "chat_status"; })[0];
  var slotName = "";
  var before2 = buildPy();
  var oldCount = 0;
  if (status) {
    var b = blockByKey(status.bkey);
    var v = variantOf(b, status.bvar);
    var s = (b.slots || []).filter(function (x) {
      return String(v.ui_py).indexOf(x.literal) >= 0;
    })[0];
    if (s) {
      slotName = s.name;
      oldCount = before2.split(s.literal).length - 1;
      status.btexts = {};
      status.btexts[s.name] = "立刻停下";
    }
  }
  var py = buildPy();
  var edited = slotName ? (py.indexOf("立刻停下") >= 0) : false;
  var newCount = slotName
    ? (py.split("\"" + "终止任务\"").length - 1) : 0;

  /* 展开全部：改文案 / 备注名 / 样式下拉这三样输入框只在展开态进 DOM，
     不展开就量不到，等于让「折叠时渲染错误」这类 bug 逃过去。 */
  proposal.forEach(function (n) { n.expanded = true; });
  renderCanvas();
  var canvas = el("canvas");
  /* dataset 的键必须是驼峰：写 "biz-nodes" 会在赋值时直接抛
     TypeError（DOMStringMap 不接受带横线的属性名），整条钩子就哑了。
     落到 DOM 上是 data-biz-nodes，测试那边按横线读回来。 */
  appendReport("biz-report", {
    "blocks": String(proposal.length),
    "bizNodes": String(canvas.querySelectorAll(".bnode").length),
    /* 「业务块不可再嵌套」：画布上不许出现 .pgroup（容器分组框），
       也不许出现任何带 data-parent 的业务块。 */
    "pgroups": String(canvas.querySelectorAll(".pgroup").length),
    "nested": String(canvas.querySelectorAll(".bnode[data-parent]:not([data-parent=''])").length),
    /* 「业务块没有参数框」：data-field="params" 一个都不该有。 */
    "paramBoxes": String(canvas.querySelectorAll('[data-field="params"]').length),
    "parentSelects": String(canvas.querySelectorAll('[data-field="parent"]').length),
    "moveBtns": String(canvas.querySelectorAll(".pmove").length),
    "textBoxes": String(canvas.querySelectorAll('[data-field="btext"]').length),
    "idBoxes": String(canvas.querySelectorAll('[data-field="id"]').length),
    "variantSelects": String(canvas.querySelectorAll('[data-field="bvar"]').length),
    "shelfCards": String(document.querySelectorAll(".bcard").length),
    "order": order0,
    "shelfButtons": String(document.querySelectorAll("button[data-bkey]").length),
    "advDetails": String(document.querySelectorAll("details#adv-primitives").length),
    "pvBiz": String(canvas.ownerDocument.querySelectorAll(".pv-biz").length),
    "dragChanged": (before !== after) ? "1" : "0",
    "dragFirstWasFirst":
      (before.split(",")[0] !== after.split(",")[0]) ? "1" : "0",
    "editedInPy": edited ? "1" : "0",
    "oldCount": String(oldCount),
    "newCount": String(newCount),
    "slot": slotName,
    "pyLines": String(py.split("\n").length)
  });
}

/* 「盒宽 = 面板宽」的无头验收入口（#biz-wrap）：把预览分别量成宽、窄、
   560px 三档，量的是同一个气泡的文字宽度与每行字数。宽的那档每行字数
   必须明显更多——不多就说明盒宽被写死了，或者文字被塞进了某个窄栏里。
   截图也走这里（#biz-taball-chat-wide / -narrow）。 */
function bizWrapReport() {
  appendReport("biz-wrap", {
    "shape": msgShapeReading(),
    "wrap": msgWrapReading(),
    "narrow": msgWrapNarrowOnly()
  });
  document.body.classList.add("uw-shot-canvas");
  if (window.scrollTo) { window.scrollTo(0, 0); }
  setStatus("BIZ wrap 宽/窄/560 三档都读完了");
}

/* 560px 那一档：msgWrapReading 只量宽与窄两档（宽 = 面板默认宽），
   这里单独量「面板宽 560」时的文字宽度与每行字数。 */
function msgWrapNarrowOnly() {
  document.body.classList.add("uw-panel-560");
  renderCanvas();
  var txt = el("preview").querySelector(".demo.d-msgtxt .d-msgtext");
  var w = txt ? Math.round(txt.getBoundingClientRect().width) : 0;
  var lines = Math.max(1, lineCount(txt));
  var cpl = txt ? Math.ceil(Number(txt.dataset.dmsglen || 0) / lines) : 0;
  document.body.classList.remove("uw-panel-560");
  renderCanvas();
  return [String(w), String(cpl), String(lines)].join(":");
}

function bizExportReport() {
  var py = buildPy();
  appendReport("biz-export", {
    "pyLines": String(py.split("\n").length),
    "py": py
  });
  /* 截图要看的就是这段代码，而它在页面最底下。前面还有一屏控件架加一屏
     画布，无头 --screenshot 只截视口，滚过去也只滚到导出面板的标题。
     所以给 body 挂一个只给截图用的 class，由 style.css 把控件架与画布收掉。
     真人打开工作台永远不会带上这个 class（只有 #biz-export 这条钩子会加）。 */
  document.body.classList.add("uw-shot-export");
  var panel = el("export-panel");
  if (panel && panel.scrollIntoView) {
    panel.scrollIntoView({ block: "start" });
  }
}

document.addEventListener("DOMContentLoaded", init);
