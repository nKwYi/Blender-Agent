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

var proposal = [];   // [{wkey, label, uiloayout, params, id, note, errors, downgraded, blocker, fallback}]
var vocab = null;

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
  h.textContent = "可用控件（落笔即校验）：";
  host.appendChild(h);
  vocab.widgets.forEach(function (w) {
    var b = document.createElement("button");
    b.dataset.wkey = w.key;
    b.textContent = w.label;
    b.title = w.uiloayout +
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

/* 记下「谁在编辑哪个字段、光标在哪」，重建完再还回去。
   不这么做的话，用户在被自己 oninput 摘掉的 input 里敲第二个字符时，
   事件已经打到 body 去了：输 scale_y 只会留下 s，全靠粘贴才能输完。 */
function captureFocus(host) {
  var af = document.activeElement;
  if (!af || !af.dataset || af.dataset.field == null) { return null; }
  var box = host.querySelector('.pnode[data-idx="' + af.dataset.idx + '"]');
  var f = box && box.querySelector('[data-field="' + af.dataset.field + '"]');
  if (!f) { return null; }
  return { idx: af.dataset.idx, field: af.dataset.field,
           start: f.selectionStart, end: f.selectionEnd };
}

function restoreFocus(host, keep) {
  if (!keep) { return; }
  var box = host.querySelector('.pnode[data-idx="' + keep.idx + '"]');
  var f = box && box.querySelector('[data-field="' + keep.field + '"]');
  if (!f) { return; }
  f.focus();
  try { f.setSelectionRange(keep.start, keep.end); } catch (e) { /* 不支持就只聚焦 */ }
}

function renderCanvas() {
  var host = el("canvas");
  var keep = captureFocus(host);
  host.innerHTML = "";
  if (!proposal.length) {
    var p = document.createElement("p");
    p.id = "empty-hint";
    p.className = "hint";
    p.textContent = "从上面挑控件开始拼装。挑不到想要的效果时，看下方「做不到」列表——" +
      "点它插入的是降级方案，原需求会被标成做不到。";
    host.appendChild(p);
    return;
  }
  proposal.forEach(function (n, i) {
    var box = document.createElement("div");
    box.className = "note pnode" + (n.downgraded ? " down" : (n.errors.length ? " blocked" : ""));
    box.dataset.idx = String(i);
    box.dataset.wkey = n.wkey;
    box.dataset.downgraded = n.downgraded ? "1" : "0";
    box.dataset.status = n.downgraded ? "downgraded" : (n.errors.length ? "blocked" : "ok");
    box.dataset.errors = String(n.errors.length);
    if (n.rkey) { box.dataset.rkey = n.rkey; }

    var head = document.createElement("div");
    head.className = "phead";
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
      pin.dataset.idx = String(i);
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
    idIn.dataset.idx = String(i);
    idIn.placeholder = "对应插件元素 ID（可空）";
    idIn.value = n.id;
    idIn.oninput = function () { n.id = idIn.value; };
    box.appendChild(idIn);

    var ta = document.createElement("textarea");
    ta.className = "pnote";
    ta.dataset.field = "note";
    ta.dataset.idx = String(i);
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
   #proposal-typing 走逐字符 input 事件，专治「重建画布把焦点弄丢」那类 bug。 */
/* 逐字符敲参数框，派发真的 input 事件——刻意不复用 #proposal-blocked 那条
   直接调 setParams 的捷径，因为那条绕开了用户实际会走的路径。
   这里模拟浏览器的真实行为：只有元素仍然持有焦点，这次按键才会落进去；
   节点一旦被 renderCanvas 摘出文档，后续按键就打到 body 上，字符会丢。
   敲 "scale_ys"（比合法值多一个 s）是为了同时验两件事：字符没丢，
   且最后那一下真的触发了拦截。 */
function paramsInputOf(wkey) {
  for (var i = 0; i < proposal.length; i++) {
    if (proposal[i].wkey !== wkey) { continue; }
    return el("canvas").querySelector('.pnode[data-idx="' + i + '"] [data-field="params"]');
  }
  return null;
}

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

function runDemoHook(hash) {
  var h = String(hash || "").replace(/^#/, "");
  var kind = (h === "proposal-all") ? "all"
           : (h === "proposal-blocked") ? "blocked"
           : (h === "proposal-typing") ? "typing"
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
    var down = proposal.filter(function (x) { return x.downgraded; }).length;
    var blocked = proposal.filter(function (x) { return x.errors.length > 0; }).length;
    setStatus("DEMO " + kind + " 控件 " + (proposal.length - down) +
      " 降级 " + down + " 违规 " + blocked);
  }).catch(function (e) {
    setStatus("DEMO 失败：" + e.message);
  });
}

document.addEventListener("DOMContentLoaded", init);
