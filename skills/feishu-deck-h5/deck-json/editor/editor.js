// deck-editor frontend · vanilla JS, no framework

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

const state = {
  deck: null,
  deckPath: null,
  selectedIdx: null,
  drag: { fromIdx: null, overRow: null, overSide: null, K: null },
  importSource: null,         // parsed source deck for import modal
  importSourcePath: null,
  importPicked: new Set(),
};

// ---------------------------------------------------------------- network

// Per-launch CSRF token — embedded into the launch URL by deck-editor.py as
// ?token=XXX. Every /api/* call attaches it as X-Editor-Token. Without this
// header, the server returns 403. Reading from `URLSearchParams(location.search)`
// because the token IS in the visible URL (single-user loopback editor — the
// threat model is cross-tab fetch hijack, not URL bar visibility).
const CSRF_TOKEN = (() => {
  const t = new URLSearchParams(location.search).get("token") || "";
  if (!t) {
    console.warn("[deck-editor] no ?token= in URL — API calls will 403");
  }
  return t;
})();

// Asset URLs that need to load *through* the server (preview iframe, etc.)
// must include the token too — they're token-gated server-side. Helper:
function withToken(url) {
  if (!CSRF_TOKEN) return url;
  return url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(CSRF_TOKEN);
}

async function api(path, opts = {}) {
  setStatus("busy", "请求中…");
  try {
    const res = await fetch(path, {
      ...opts,
      headers: {
        "Content-Type":    "application/json",
        "X-Editor-Token":  CSRF_TOKEN,
        ...(opts.headers || {}),
      },
    });
    const data = await res.json();
    if (!data.ok && data.error) {
      setStatus("err", "出错");
      logErr(data.error);
      return data;
    }
    setStatus("ok", "就绪");
    return data;
  } catch (e) {
    setStatus("err", "网络异常");
    logErr(String(e));
    return { ok: false, error: String(e) };
  }
}

async function fetchDeck() {
  const data = await api("/api/deck");
  if (!data.ok) return;
  state.deck = data.deck;
  state.deckPath = data.path;
  renderTopBar();
  renderSlideList();
  if (state.selectedIdx === null && state.deck.slides.length > 0) {
    selectSlide(0);
  } else if (state.selectedIdx !== null) {
    renderInspector();
  }
}

async function runOp(cmd, args, opts = {}) {
  const data = await api("/api/op", {
    method: "POST",
    body: JSON.stringify({ cmd, args }),
  });
  if (!data.ok) return data;
  state.deck = data.deck;
  renderTopBar();
  renderSlideList();
  renderInspector();
  // Defensive: even when we don't reload iframe, re-affirm contentEditable
  // state on wired elements. Some DOM ops + plaintext-only contenteditable
  // combo can clear editability mid-session.
  refreshIframeEditableState();
  // Reload policy:
  //   opts.skipReload  → never reload (in-place edits: contenteditable already
  //                      shows the new text, no need to redraw the iframe)
  //   structural ops   → reload immediately (reorder / insert / delete / clone /
  //                      import / set-variant — DOM structure changed)
  //   set-accent / set-decor → don't reload immediately either; iframe stays
  //                      stale but accurate enough until next structural op
  //                      (user can hit ↻ Render if they need the visual now)
  if (!opts.skipReload) {
    const STRUCTURAL = new Set(["reorder", "move-key", "insert", "delete",
                                "clone", "set-variant"]);
    if (STRUCTURAL.has(cmd)) reloadPreview();
    // else: skip reload (text / attribute changes — iframe stays as-is)
  }
  if (!data.render_ok) {
    log("op 成功但 render 失败:");
    logErr(data.render_log || "");
  } else {
    log(`✓ ${cmd}${args && args.length ? " " + args.join(" ") : ""}`);
  }
  return data;
}

async function importSlide(sourcePath, slideKey) {
  const data = await api("/api/import-slide", {
    method: "POST",
    body: JSON.stringify({ source_path: sourcePath, slide_key: slideKey }),
  });
  if (!data.ok) return data;
  state.deck = data.deck;
  renderTopBar();
  renderSlideList();
  reloadPreview();
  log(`✓ imported '${slideKey}' as '${data.imported_key}' at #${data.position}`);
  return data;
}

// ---------------------------------------------------------------- render UI

function renderTopBar() {
  $("#deckTitle").textContent = state.deck?.deck?.title || "<无标题>";
  $("#slideCount").textContent = `${state.deck?.slides?.length || 0} slides`;
}

function bindListDragHandlers() {
  // Attach once on the <ol> — runs even when the cursor is in inter-row gaps
  // or above/below the row stack. Computes target gap K from mouse Y position
  // relative to all visible rows.
  const list = $("#slideList");
  if (list.__dragBound) return;
  list.__dragBound = true;

  list.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const rows = $$(".slide-row");
    if (rows.length === 0) return;
    // Walk rows; find the first whose vertical center is below the cursor.
    let K = rows.length, targetRow = null, side = "below";
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i].getBoundingClientRect();
      if (e.clientY < r.top + r.height / 2) {
        K = i; targetRow = rows[i]; side = "above"; break;
      }
    }
    if (!targetRow) {
      targetRow = rows[rows.length - 1];
      side = "below";
    }
    if (state.drag.overRow !== targetRow || state.drag.overSide !== side) {
      clearDropIndicators();
      targetRow.classList.add(side === "above" ? "drop-above" : "drop-below");
      state.drag.overRow = targetRow;
      state.drag.overSide = side;
      state.drag.K = K;
    }
  });

  list.addEventListener("drop", async (e) => {
    e.preventDefault();
    const from = state.drag.fromIdx;
    const K = state.drag.K;
    clearDropIndicators();
    if (from === null || K === null) return;
    if (from === K || from === K - 1) return;  // no-op
    const cli_to_pos = from < K ? K : K + 1;
    await runOp("reorder", [from + 1, cli_to_pos]);
  });
}

function getSlideTitle(s) {
  if (!s.data) return s.key;
  if (s.data.title) return s.data.title;
  // Layout-specific fallbacks for slides without a top-level title
  if (s.layout === "quote" && s.data.quote) {
    const q = s.data.quote;
    return [q.lead, q.accent, q.tail].filter(Boolean).join("");
  }
  if (s.layout === "stats" && s.variant === "hero" && s.data.heading) return s.data.heading;
  if (s.layout === "end")     return s.data.contact || "End";
  if (s.layout === "replica") return s.data.page_image || s.key;
  return s.key;
}

function renderSlideList() {
  const list = $("#slideList");
  list.innerHTML = "";
  bindListDragHandlers();
  (state.deck?.slides || []).forEach((s, i) => {
    const li = document.createElement("li");
    li.className = "slide-row";
    li.draggable = true;
    li.dataset.idx = i;
    li.dataset.key = s.key;
    if (i === state.selectedIdx) li.classList.add("is-selected");
    // Single-line title preview (collapse \n / <br> to space for the list row)
    const titlePreview = String(getSlideTitle(s)).replace(/\n|<br>/g, " ");
    li.innerHTML = `
      <div class="idx">${String(i + 1).padStart(2, "0")}</div>
      <div class="meta">
        <div class="title-preview">${escapeHtml(titlePreview)}</div>
      </div>
    `;
    li.addEventListener("click", () => selectSlide(i));

    // Per-row only handles drag-START (dragend / dragover / drop are
    // attached to the LIST itself — see bindListDragHandlers — so empty
    // gaps between rows + list top/bottom also accept drops).
    li.addEventListener("dragstart", (e) => {
      state.drag.fromIdx = i;
      li.classList.add("is-dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", String(i));
    });
    li.addEventListener("dragend", () => {
      li.classList.remove("is-dragging");
      clearDropIndicators();
      state.drag.fromIdx = null;
      state.drag.overRow = null;
      state.drag.overSide = null;
      state.drag.K = null;
    });

    list.appendChild(li);
  });
}

// Array fields per (layout, variant). Each array gets its own collapsible
// section in the inspector with per-item add/remove/reorder + field editing.
// Phase 4.b.2 covers flat array-of-objects + simple array-of-strings.
// Polymorphic (body_blocks), 2D (table.rows), and nested-tree (flow/tree,
// content/matrix.quadrants) variants are deferred.
// ---------------------------------------------------------------- block catalog
// Polymorphic body_blocks live in content/3up + content/2col + content/blocks
// + content/story-case. Each block has a `type` discriminator. MVP exposes
// top-level scalar fields per type — complex nested arrays (kpis / rows /
// verdicts) can still be edited in-place inside the preview iframe (each
// inner cell has its own data-text-id) or by editing deck.json directly.
// Source of truth: deck-schema.json $defs/block_*. Field names + enums
// MUST match what the schema accepts (additionalProperties:false), otherwise
// every "add block" op will schema-fail and rollback. Tests in
// deck-json/tests/test_editor_schema_parity.py guard this map against drift.
const BLOCK_TYPES = {
  "pullquote": {
    label: "Pullquote · 引言块",
    defaults: () => ({ type: "pullquote", text: "新的引言文字..." }),
    fields: [
      { key: "text", label: "Text", multi: true },
      { key: "tone", label: "Tone", select: ["default", "orange", "blue", "violet"] },
    ],
  },
  "cta-box": {
    label: "CTA Box · 行动召唤",
    defaults: () => ({ type: "cta-box", heading: "标题", body: "正文..." }),
    fields: [
      { key: "heading",      label: "Heading (标题)" },
      { key: "body",         label: "Body", multi: true },
      { key: "button_label", label: "Button label" },
      { key: "tone",         label: "Tone", select: ["default", "teal"] },
    ],
  },
  "kpi-strip": {
    label: "KPI Strip · 数字条",
    defaults: () => ({ type: "kpi-strip",
                       kpis: [{ value: "0", label: "新指标" },
                              { value: "0", label: "新指标" },
                              { value: "0", label: "新指标" }] }),
    fields: [],
    hint: "kpis[] 内容请在 preview 里双击数字 / 标签编辑,或直接改 deck.json",
  },
  "data-panel": {
    label: "Data Panel · 数据面板",
    defaults: () => ({ type: "data-panel", title: "标题",
                       rows: [{ lbl: "标签 1", val: "0" },
                              { lbl: "标签 2", val: "0" }] }),
    fields: [
      { key: "title", label: "Title" },
      { key: "tone",  label: "Tone", select: ["default", "teal", "violet"] },
    ],
    hint: "rows[] 内容请在 preview 里双击编辑",
  },
  "verdict-grid": {
    label: "Verdict Grid · 判断卡组",
    defaults: () => ({ type: "verdict-grid",
                       cards: [
                         { verdict: "go",          badge: "GO",    title: "标题", body: "正文" },
                         { verdict: "conditional", badge: "条件",  title: "标题", body: "正文" },
                         { verdict: "nogo",        badge: "NO-GO", title: "标题", body: "正文" } ] }),
    fields: [],
    hint: "cards[] (verdict: go/conditional/nogo) 请在 preview 里双击编辑",
  },
  "phone-iframe": {
    label: "Phone iFrame · 手机预览",
    defaults: () => ({ type: "phone-iframe", iframe_src: "assets/phone-screen.html" }),
    fields: [
      { key: "iframe_src", label: "iFrame src (页面路径)" },
      { key: "title",      label: "Title (顶部标题)" },
      { key: "hint",       label: "Hint (底部提示)" },
    ],
  },
  "principle-band": {
    label: "Principle Band · 原则横条",
    defaults: () => ({ type: "principle-band",
                       principles: [
                         { text: "原则 1", color: "teal"  },
                         { text: "原则 2", color: "blue"  },
                         { text: "原则 3", color: "purple" } ] }),
    fields: [],
    hint: "principles[] (text + color: teal/blue/purple) 请在 preview 里双击编辑",
  },
};

const ARRAY_FIELDS = {
  "agenda": {
    items: {
      label: "议程项",
      titleField: "title_zh",
      minItems: 1, maxItems: 8,
      newItem: () => ({ title_zh: "新议程" }),
      fields: [
        { key: "title_zh", label: "标题 (中)" },
        { key: "title_en", label: "副标题 (英 · 可选)" },
      ],
    },
  },
  "section": {
    pills: {
      label: "Pills",
      isStringArray: true,
      minItems: 0, maxItems: 8,
      newItem: () => "新 pill",
    },
  },
  "content:3up": {
    cards: {
      label: "卡片",
      titleField: "title_zh",
      minItems: 3, maxItems: 3,
      newItem: () => ({ num: "0X", title_zh: "新卡片", body: "正文..." }),
      fields: [
        { key: "num", label: "编号" },
        { key: "title_zh", label: "标题" },
        { key: "title_en", label: "英文副标 (可选)" },
        { key: "body", label: "正文", multi: true },
        { key: "footer_label", label: "底部标签" },
      ],
    },
    body_blocks: {
      label: "Body blocks (页面块组件)",
      titleField: "type",
      minItems: 0, maxItems: 4,
      isPolymorphic: true,
    },
  },
  "content:blocks": {
    body_blocks: {
      label: "Body blocks (页面块组件)",
      titleField: "type",
      minItems: 1, maxItems: 6,
      isPolymorphic: true,
    },
  },
  // content/2col: left-text column has lede + feature_list[] + body_blocks[]
  "content:2col": {
    "text.feature_list": {
      label: "Feature list (左列要点)",
      isStringArray: true,
      minItems: 0, maxItems: 6,
      newItem: () => "新要点",
    },
    "text.body_blocks": {
      label: "Body blocks (左列块组件)",
      titleField: "type",
      minItems: 0, maxItems: 4,
      isPolymorphic: true,
    },
  },
  "stats:row": {
    cols: {
      label: "数据列",
      titleField: "label",
      minItems: 3, maxItems: 4,
      newItem: () => ({ num: "0", label: "新指标" }),
      fields: [
        { key: "num",    label: "数字" },
        { key: "unit",   label: "单位" },
        { key: "label",  label: "标签" },
        { key: "trend",  label: "趋势 (↑/↓)" },
        { key: "source", label: "来源" },
      ],
    },
  },
  "stats:waterfall": {
    bars: {
      label: "Bars",
      titleField: "label",
      minItems: 3, maxItems: 8,
      newItem: () => ({ kind: "pos", value: "+0", label: "新柱" }),
      fields: [
        { key: "kind",     label: "类型", select: ["base", "pos", "neg", "end"] },
        { key: "value",    label: "数值" },
        { key: "delta",    label: "Delta" },
        { key: "label",    label: "标签" },
        { key: "sublabel", label: "副标签" },
      ],
    },
  },
  "flow:timeline": {
    nodes: {
      label: "节点",
      titleField: "what",
      minItems: 3, maxItems: 6,
      newItem: () => ({ when: "W?", what: "新节点" }),
      fields: [
        { key: "when", label: "时间" },
        { key: "what", label: "事件" },
        { key: "desc", label: "描述", multi: true },
      ],
    },
  },
  "flow:process": {
    steps: {
      label: "步骤",
      titleField: "title",
      minItems: 3, maxItems: 6,
      newItem: () => ({ title: "新步骤", body: "描述..." }),
      fields: [
        { key: "num",   label: "编号 (可选,自动)" },
        { key: "title", label: "标题" },
        { key: "body",  label: "正文", multi: true },
      ],
    },
  },

  // ── Matrix · 4 个固定象限,每个独立编辑 items[] (Phase 4.b.6) ──
  "content:matrix": {
    "quadrants.tl.items": {
      label: "TL · items",
      isStringArray: true,
      minItems: 2, maxItems: 5,
      newItem: () => "新条目",
    },
    "quadrants.tr.items": {
      label: "TR · items",
      isStringArray: true,
      minItems: 2, maxItems: 5,
      newItem: () => "新条目",
    },
    "quadrants.bl.items": {
      label: "BL · items",
      isStringArray: true,
      minItems: 2, maxItems: 5,
      newItem: () => "新条目",
    },
    "quadrants.br.items": {
      label: "BR · items",
      isStringArray: true,
      minItems: 2, maxItems: 5,
      newItem: () => "新条目",
    },
  },

  // ── flow/tree branches[] with nested leaves[] (Phase 4.b.6) ──
  // branches has 2 special fields: title (string) + leaves[] (string array).
  // We use `subStringArrays` to declare that each item has a nested string
  // array editor under the given key.
  "flow:tree": {
    branches: {
      label: "Branches",
      titleField: "title",
      minItems: 2, maxItems: 4,
      newItem: () => ({ ord: "0X", title: "新分支", leaves: ["叶 1", "叶 2"] }),
      fields: [
        { key: "ord",   label: "Ord (01 / 02 / ...)" },
        { key: "title", label: "Title" },
      ],
      subStringArrays: [
        { key: "leaves", label: "Leaves", minItems: 1, maxItems: 5,
          newItem: () => "新叶子" },
      ],
    },
  },
};

// Extra editable fields per (layout, variant). Top-level scalar fields.
// EXTRA_FIELDS entries can have:
//   key   : "title"  (top-level scalar)  OR  "hook.lead" (dotted nested path)
//   label : visible label
//   multi : true → textarea instead of input
//   group : optional group header (visually clusters related fields)
const EXTRA_FIELDS = {
  "cover":              [{key: "subtitle",      label: "Subtitle (opt-in 双语)"}],
  "section":            [{key: "lede",          label: "Lede"}],
  "end":                [{key: "contact",       label: "Contact"}],
  "content:3up":        [{key: "lede",          label: "Lede (可选引言)", multi: true}],
  "content:2col":       [
    {key: "text.lede",         label: "Lede (左列引言)", multi: true,  group: "Text 列"},
    {key: "visual.type",       label: "Visual · type",
     select: ["image", "panel", "svg", "placeholder"],                  group: "Visual 列"},
    {key: "visual.image.src",  label: "Visual · image src",             group: "Visual 列 (type=image)"},
    {key: "visual.image.alt",  label: "Visual · image alt",             group: "Visual 列 (type=image)"},
    {key: "visual.min_height", label: "Visual · min-height (CSS)",      group: "Visual 列 (type=image)"},
    {key: "visual.label",      label: "Visual · placeholder label",     group: "Visual 列 (type=placeholder)"},
  ],
  "content:blocks":     [{key: "lede",          label: "Lede", multi: true},
                         {key: "source_footer", label: "Source footer"}],
  "content:story-case": [
    {key: "industry",         label: "行业 (industry-tag)"},
    {key: "brand",            label: "品牌 line"},
    {key: "source",           label: "数据来源 source"},
    {key: "hook.lead",        label: "Lead",          multi: true, group: "Hook · 钩子(开篇引子)"},
    {key: "hook.accent",      label: "Accent (高亮)",              group: "Hook · 钩子(开篇引子)"},
    {key: "hook.tail",        label: "Tail",          multi: true, group: "Hook · 钩子(开篇引子)"},
    {key: "arc.pain",         label: "痛点 pain",     multi: true, group: "Arc · 故事弧"},
    {key: "arc.conflict",     label: "冲突 conflict", multi: true, group: "Arc · 故事弧"},
    {key: "arc.solution",     label: "方案 solution", multi: true, group: "Arc · 故事弧"},
    {key: "arc.value.lead",   label: "Value · lead",               group: "Arc · 故事弧"},
    {key: "arc.value.accent", label: "Value · accent",             group: "Arc · 故事弧"},
    {key: "arc.value.tail",   label: "Value · tail",  multi: true, group: "Arc · 故事弧"},
    {key: "scene.caption",    label: "Scene 说明",                  group: "Scene · 场景图"},
    {key: "quote.lead",       label: "Quote · lead",               group: "Quote · 引言(可选)"},
    {key: "quote.accent",     label: "Quote · accent",             group: "Quote · 引言(可选)"},
    {key: "quote.tail",       label: "Quote · tail",               group: "Quote · 引言(可选)"},
    {key: "stat.number",      label: "Stat · 数字",                group: "Stat · 数据点(可选)"},
    {key: "stat.unit",        label: "Stat · 单位",                group: "Stat · 数据点(可选)"},
    {key: "stat.label",       label: "Stat · 标签",                group: "Stat · 数据点(可选)"},
  ],
  "content:matrix":     [
    {key: "lede",                  label: "Lede (可选引言)", multi: true},
    {key: "axes.y.name",           label: "Y 轴 · 名称",                       group: "坐标轴标签"},
    {key: "axes.y.high_label",     label: "Y 轴 · 上 high label",              group: "坐标轴标签"},
    {key: "axes.y.low_label",      label: "Y 轴 · 下 low label",               group: "坐标轴标签"},
    {key: "axes.x.name",           label: "X 轴 · 名称",                       group: "坐标轴标签"},
    {key: "axes.x.high_label",     label: "X 轴 · 右 high label",              group: "坐标轴标签"},
    {key: "axes.x.low_label",      label: "X 轴 · 左 low label",               group: "坐标轴标签"},
    {key: "quadrants.tl.ord",      label: "TL · ord (01 等)",                  group: "四象限"},
    {key: "quadrants.tl.title",    label: "TL · title",                         group: "四象限"},
    {key: "quadrants.tr.ord",      label: "TR · ord",                           group: "四象限"},
    {key: "quadrants.tr.title",    label: "TR · title",                         group: "四象限"},
    {key: "quadrants.bl.ord",      label: "BL · ord",                           group: "四象限"},
    {key: "quadrants.bl.title",    label: "BL · title",                         group: "四象限"},
    {key: "quadrants.br.ord",      label: "BR · ord",                           group: "四象限"},
    {key: "quadrants.br.title",    label: "BR · title",                         group: "四象限"},
  ],
  "quote":              [{key: "attribution",   label: "Attribution"}],
  "stats:row":          [{key: "footnote",      label: "Footnote"}],
  "stats:hero":         [{key: "eyebrow",       label: "Eyebrow"},
                         {key: "heading",       label: "Heading", multi: true},
                         {key: "body",          label: "Body", multi: true}],
  "stats:waterfall":    [{key: "footnote",      label: "Footnote"}],
  "image-text":         [{key: "lede",          label: "Lede", multi: true}],
  "table":              [{key: "footnote",      label: "Footnote"}],
  "flow:tree":          [
    {key: "root.question", label: "根 · 问题",  multi: true, group: "Tree root"},
    {key: "root.why",      label: "根 · why",    multi: true, group: "Tree root"},
  ],
};

// Dotted-path getter — "hook.lead" → obj.hook?.lead
function getNestedField(obj, dotted) {
  if (!obj) return undefined;
  return dotted.split(".").reduce(
    (acc, k) => (acc == null ? undefined : acc[k]), obj);
}

function renderInspector() {
  const ins = $("#inspector");
  if (state.selectedIdx === null || !state.deck) {
    ins.innerHTML = '<p class="muted">选择左侧 slide 查看 / 编辑</p>';
    return;
  }
  const s = state.deck.slides[state.selectedIdx];
  const slideIdx = state.selectedIdx;
  if (!s) {
    ins.innerHTML = '<p class="muted">选中索引超界</p>';
    return;
  }

  const title  = (s.data && s.data.title) || "";
  const accent = s.accent || "blue";
  const decor  = (s.decor || []).join(", ");
  const notes  = s.notes || "";

  // Variant switcher — only for multi-variant layouts.
  const VARIANTS = {
    content: ["3up", "2col", "story-case", "blocks", "matrix"],
    stats:   ["row", "hero", "waterfall"],
    flow:    ["timeline", "process", "tree"],
  };
  const variants = VARIANTS[s.layout];
  const variantBlock = variants ? `
    <div class="group">
      <div class="label">Variant</div>
      <select class="value-edit" id="ins-variant">
        ${variants.map(v =>
          `<option value="${v}"${v === s.variant ? " selected" : ""}>${v}</option>`).join("")}
      </select>
      <div class="hint" style="margin-top:6px;color:var(--text-40);font-size:11px">
        切 variant 会丢弃不兼容的 data 字段(会弹确认)
      </div>
    </div>` : "";

  // Extra fields per (layout, variant) — supports dotted paths + optional groups
  const lookupKey = s.variant ? `${s.layout}:${s.variant}` : s.layout;
  const extras = EXTRA_FIELDS[lookupKey] || [];
  let prevGroup = null;
  const extrasHtml = extras.map(f => {
    const val = getNestedField(s.data, f.key);
    const valStr = val != null ? String(val) : "";
    // Use a unique id-safe key (dots → dashes) since "." in IDs is fine but
    // querySelector needs escaping; safer to swap.
    const id = `ins-extra-${f.key.replace(/\./g, "-")}`;
    const editor = f.multi
      ? `<textarea class="value-edit" id="${id}" rows="2">${escapeHtml(valStr)}</textarea>`
      : `<input class="value-edit" id="${id}" value="${escapeAttr(valStr)}">`;
    // Insert a group header when group changes
    let groupHeader = "";
    if (f.group && f.group !== prevGroup) {
      groupHeader = `<div class="group-header">${escapeHtml(f.group)}</div>`;
      prevGroup = f.group;
    } else if (!f.group) {
      prevGroup = null;
    }
    return `${groupHeader}
      <div class="group">
        <div class="label">${escapeHtml(f.label)}</div>
        ${editor}
      </div>`;
  }).join("");

  ins.innerHTML = `
    <div class="group">
      <div class="label">Key</div>
      <div class="value"><code>${escapeHtml(s.key)}</code></div>
    </div>
    <div class="group">
      <div class="label">Layout</div>
      <div class="value">${escapeHtml(s.layout)}${variants ? "" : " (single-variant)"}</div>
    </div>
    ${variantBlock}
    <div class="group">
      <div class="label">Screen label</div>
      <input class="value-edit" id="ins-label" value="${escapeAttr(s.screen_label || "")}">
    </div>
    <div class="group">
      <div class="label">Title</div>
      <textarea class="value-edit" id="ins-title" rows="2">${escapeHtml(title)}</textarea>
    </div>
    ${extrasHtml}
    <div class="group">
      <div class="label">Accent</div>
      <select class="value-edit" id="ins-accent">
        ${["blue","teal","violet","purple","orange"].map(c =>
          `<option value="${c}"${c===accent?" selected":""}>${c}</option>`).join("")}
      </select>
    </div>
    <div class="group">
      <div class="label">Decor (comma-sep)</div>
      <input class="value-edit" id="ins-decor" value="${escapeAttr(decor)}">
    </div>
    <div class="group">
      <div class="label">Notes (作者备注 · 不渲染)</div>
      <textarea class="value-edit" id="ins-notes" rows="3">${escapeHtml(notes)}</textarea>
    </div>
    <div class="group">
      <div class="hint" style="color:var(--text-40);font-size:11px;margin-bottom:8px">
        改完移出焦点即自动保存
      </div>
      <div class="row-actions">
        <button class="btn" id="ins-clone">复制此页</button>
        <button class="btn" id="ins-delete">删除</button>
      </div>
    </div>
    ${renderImageField(s, slideIdx)}
    ${renderArraySections(s, slideIdx)}
  `;

  // ── autosave: fire on blur (input/textarea) / change (select) ──
  attachAutoSave("ins-label", () => s.screen_label || "",
    v => ["set", [`slides.${slideIdx}.screen_label`, v]]);
  attachAutoSave("ins-title", () => title,
    v => ["set", [`slides.${slideIdx}.data.title`, v]]);
  attachAutoSave("ins-notes", () => notes,
    v => ["set", [`slides.${slideIdx}.notes`, v]]);
  attachAutoSave("ins-decor", () => decor.replace(/\s+/g, ""),
    v => ["set-decor", [s.key, v.split(",").map(x=>x.trim()).filter(Boolean).join(",")]],
    v => v.split(",").map(x=>x.trim()).filter(Boolean).join(","));
  extras.forEach(f => {
    const oldVal = getNestedField(s.data, f.key);
    const id = `ins-extra-${f.key.replace(/\./g, "-")}`;
    attachAutoSave(id, () => (oldVal != null ? String(oldVal) : ""),
      v => ["set", [`slides.${slideIdx}.data.${f.key}`, v]]);
  });

  // Accent: select uses change event
  $("#ins-accent").addEventListener("change", async (e) => {
    if (e.target.value === (s.accent || "blue")) return;
    await runOp("set-accent", [s.key, e.target.value]);
  });

  // Buttons
  $("#ins-clone").addEventListener("click", cloneCurrentSlide);
  $("#ins-delete").addEventListener("click", deleteCurrentSlide);
  if (variants) {
    $("#ins-variant").addEventListener("change", onVariantChange);
  }
  bindArraySectionListeners(s, slideIdx);
  bindImageFieldListeners();
}

// ---------------------------------------------------------------- image upload

function renderImageField(slide, slideIdx) {
  // Detect which layouts have a top-level image field worth a dropzone
  let path, current;
  if (slide.layout === "image-text") {
    path = `slides.${slideIdx}.data.image.src`;
    current = (slide.data && slide.data.image && slide.data.image.src) || "";
  } else if (slide.layout === "content" && slide.variant === "story-case") {
    path = `slides.${slideIdx}.data.scene.image`;
    current = (slide.data && slide.data.scene && slide.data.scene.image) || "";
  } else if (slide.layout === "content" && slide.variant === "2col") {
    // Only show dropzone when visual is configured as image
    const vtype = (slide.data && slide.data.visual && slide.data.visual.type);
    if (vtype !== "image") return "";
    path = `slides.${slideIdx}.data.visual.image.src`;
    current = (slide.data && slide.data.visual && slide.data.visual.image && slide.data.visual.image.src) || "";
  } else if (slide.layout === "replica") {
    path = `slides.${slideIdx}.data.page_image`;
    current = (slide.data && slide.data.page_image) || "";
  } else {
    return "";
  }
  const display = current
    ? `<div class="image-current"><code>${escapeHtml(current)}</code></div>`
    : `<div class="image-empty">没有图</div>`;
  return `
    <div class="group">
      <div class="label">Image</div>
      <div class="image-dropzone" data-set-path="${escapeAttr(path)}">
        ${display}
        <div class="image-hint">拖图到这里 · 或点击选文件</div>
        <input type="file" accept="image/*" class="image-file-input" style="display:none">
      </div>
    </div>
  `;
}

function bindImageFieldListeners() {
  $$(".image-dropzone").forEach((zone) => {
    const input = zone.querySelector(".image-file-input");
    const path  = zone.dataset.setPath;
    zone.addEventListener("click", (e) => {
      if (e.target !== input) input.click();
    });
    input.addEventListener("change", async () => {
      if (input.files[0]) await uploadImage(input.files[0], path);
    });
    zone.addEventListener("dragover", (e) => {
      e.preventDefault();
      zone.classList.add("is-dragover");
    });
    zone.addEventListener("dragleave", () => zone.classList.remove("is-dragover"));
    zone.addEventListener("drop", async (e) => {
      e.preventDefault();
      zone.classList.remove("is-dragover");
      const f = e.dataTransfer.files[0];
      if (f) await uploadImage(f, path);
    });
  });
}

async function importPdf(file) {
  if (!file.type.includes("pdf") && !file.name.toLowerCase().endsWith(".pdf")) {
    log("✗ 不是 PDF 文件");
    return;
  }
  setStatus("busy", "切页中…");
  log(`→ 正在转换 ${file.name} (${(file.size / 1024 / 1024).toFixed(1)} MB)…`);
  const b64 = await fileToBase64(file);
  const data = await api("/api/import-pdf", {
    method: "POST",
    body: JSON.stringify({ filename: file.name, base64_content: b64 }),
  });
  if (!data.ok) return;
  state.deck = data.deck;
  renderTopBar();
  renderSlideList();
  reloadPreview();
  log(`✓ imported ${data.n_pages} pages from ${file.name}: ${data.added_keys.join(", ")}`);
}

async function uploadImage(file, path) {
  if (!file.type.startsWith("image/")) {
    log("✗ 不是图片文件: " + file.type);
    return;
  }
  const b64 = await fileToBase64(file);
  const up = await api("/api/upload-image", {
    method: "POST",
    body: JSON.stringify({ filename: file.name, base64_content: b64 }),
  });
  if (!up.ok) return;
  // Set the src field — runOp with default reload so iframe shows new image
  await runOp("set", [path, up.src]);
  reloadPreview();
  log(`✓ uploaded ${file.name} (${(up.size / 1024).toFixed(1)} KB) → ${up.src}`);
}

// ---------------------------------------------------------------- array editor

function renderArraySections(slide, slideIdx) {
  const lookupKey = slide.variant ? `${slide.layout}:${slide.variant}` : slide.layout;
  const cfg = ARRAY_FIELDS[lookupKey];
  if (!cfg) return "";
  let html = "";
  for (const [fieldName, fieldCfg] of Object.entries(cfg)) {
    // fieldName may be dotted (e.g. "quadrants.tl.items")
    const items = getNestedField(slide.data, fieldName) || [];
    html += renderArraySection(slide, slideIdx, fieldName, fieldCfg, items);
  }
  return html;
}

function renderArraySection(slide, slideIdx, fieldName, cfg, items) {
  const count = items.length;
  const maxStr = cfg.maxItems != null ? ` / 最多 ${cfg.maxItems}` : "";
  const canAdd = cfg.maxItems == null || count < cfg.maxItems;
  const itemsHtml = items
    .map((item, i) => renderArrayItem(slide, slideIdx, fieldName, cfg, i, item, count))
    .join("");

  // Polymorphic add: dropdown of types
  let addControl;
  if (!canAdd) {
    addControl = `<div class="hint" style="color:var(--text-40);font-size:11px;padding:4px 0">已到上限 (${cfg.maxItems})</div>`;
  } else if (cfg.isPolymorphic) {
    addControl = `
      <div class="poly-add-row">
        <select class="value-edit poly-add-type">
          ${Object.entries(BLOCK_TYPES).map(([t, c]) =>
            `<option value="${escapeAttr(t)}">${escapeHtml(c.label)}</option>`).join("")}
        </select>
        <button class="btn btn-ghost poly-add-btn" data-field-name="${escapeAttr(fieldName)}">+ 添加</button>
      </div>`;
  } else {
    addControl = `<button class="btn btn-ghost array-add-btn" data-field-name="${escapeAttr(fieldName)}">+ 添加</button>`;
  }

  return `
    <div class="group array-section" data-field-name="${escapeAttr(fieldName)}">
      <div class="label">
        ${escapeHtml(cfg.label)} <span style="color:var(--text-40);font-weight:500">${count}${maxStr}</span>
      </div>
      <div class="array-items">${itemsHtml}</div>
      ${addControl}
    </div>
  `;
}

function renderArrayItem(slide, slideIdx, fieldName, cfg, idx, item, total) {
  // For polymorphic items, switch to block-type's fields
  let effectiveFields = cfg.fields;
  let typeLabel = "";
  if (cfg.isPolymorphic) {
    const t = (item && item.type) || "?";
    const blockCfg = BLOCK_TYPES[t];
    effectiveFields = blockCfg ? blockCfg.fields : [];
    typeLabel = blockCfg ? blockCfg.label : `unknown: ${t}`;
  }

  // Collapsed header text
  let header;
  if (cfg.isStringArray) {
    header = String(item);
  } else if (cfg.isPolymorphic) {
    header = typeLabel;
  } else if (cfg.titleField && item[cfg.titleField]) {
    header = String(item[cfg.titleField]);
  } else {
    header = `#${idx + 1}`;
  }
  header = header.replace(/\n|<br>/g, " ").slice(0, 50) || `(空白)`;

  const upDisabled     = idx === 0          ? " disabled" : "";
  const downDisabled   = idx === total - 1  ? " disabled" : "";
  const removeDisabled = total <= (cfg.minItems || 0) ? " disabled" : "";

  // Body — fields editor
  let body;
  if (cfg.isStringArray) {
    const path = `slides.${slideIdx}.data.${fieldName}.${idx}`;
    const val = String(item);
    body = `<input class="value-edit array-field"
              data-set-path="${escapeAttr(path)}"
              data-orig="${escapeAttr(val)}"
              value="${escapeAttr(val)}">`;
  } else {
    body = (effectiveFields || []).map((f) => {
      // f.key may be dotted for polymorphic blocks (e.g. "left.title")
      const val = getNestedField(item, f.key);
      const valStr = val != null ? String(val) : "";
      const path = `slides.${slideIdx}.data.${fieldName}.${idx}.${f.key}`;
      let editor;
      if (f.select) {
        editor = `<select class="value-edit array-field"
                    data-set-path="${escapeAttr(path)}"
                    data-orig="${escapeAttr(valStr)}">
                    ${f.select.map(opt =>
                      `<option value="${escapeAttr(opt)}"${opt === valStr ? " selected" : ""}>${escapeHtml(opt)}</option>`).join("")}
                  </select>`;
      } else if (f.multi) {
        editor = `<textarea class="value-edit array-field"
                    data-set-path="${escapeAttr(path)}"
                    data-orig="${escapeAttr(valStr)}"
                    rows="2">${escapeHtml(valStr)}</textarea>`;
      } else {
        editor = `<input class="value-edit array-field"
                    data-set-path="${escapeAttr(path)}"
                    data-orig="${escapeAttr(valStr)}"
                    value="${escapeAttr(valStr)}">`;
      }
      return `
        <div class="array-sub-field">
          <span class="array-sub-label">${escapeHtml(f.label)}</span>
          ${editor}
        </div>`;
    }).join("");

    // Polymorphic block hint (e.g. "kpis[] 内容请在 preview 里编辑")
    if (cfg.isPolymorphic) {
      const blockCfg = BLOCK_TYPES[(item && item.type) || ""];
      if (blockCfg && blockCfg.hint) {
        body += `<div class="block-hint">${escapeHtml(blockCfg.hint)}</div>`;
      }
      if (!blockCfg) {
        body += `<div class="block-hint" style="color:var(--warn)">未知 block type: ${escapeHtml((item && item.type) || "?")}</div>`;
      }
    }

    // Nested string sub-arrays inside each item (e.g. branch.leaves[])
    (cfg.subStringArrays || []).forEach((sub) => {
      const subItems = item[sub.key] || [];
      const subPath  = `${fieldName}.${idx}.${sub.key}`;  // for mutateArray
      const canAdd = sub.maxItems == null || subItems.length < sub.maxItems;
      const itemsHtml = subItems.map((s, j) => {
        const p = `slides.${slideIdx}.data.${subPath}.${j}`;
        const v = String(s);
        const upDis  = j === 0                  ? " disabled" : "";
        const dnDis  = j === subItems.length-1  ? " disabled" : "";
        const rmDis  = subItems.length <= (sub.minItems || 0) ? " disabled" : "";
        return `
          <div class="sub-string-row">
            <input class="value-edit array-field"
                   data-set-path="${escapeAttr(p)}" data-orig="${escapeAttr(v)}" value="${escapeAttr(v)}">
            <button class="btn-mini" data-sub-action="up"     data-sub-path="${escapeAttr(subPath)}" data-sub-idx="${j}"${upDis}>↑</button>
            <button class="btn-mini" data-sub-action="down"   data-sub-path="${escapeAttr(subPath)}" data-sub-idx="${j}"${dnDis}>↓</button>
            <button class="btn-mini" data-sub-action="remove" data-sub-path="${escapeAttr(subPath)}" data-sub-idx="${j}"${rmDis}>✕</button>
          </div>`;
      }).join("");
      body += `
        <div class="array-sub-field sub-string-array">
          <span class="array-sub-label">${escapeHtml(sub.label)} <span style="color:var(--text-40);font-weight:400">${subItems.length}${sub.maxItems != null ? ` / 最多 ${sub.maxItems}` : ""}</span></span>
          ${itemsHtml}
          ${canAdd
            ? `<button class="btn btn-ghost sub-string-add" data-sub-path="${escapeAttr(subPath)}">+ 添加</button>`
            : ""}
        </div>`;
    });
  }

  return `
    <details class="array-item" data-idx="${idx}">
      <summary>
        <span class="array-item-idx">#${idx + 1}</span>
        <span class="array-item-title">${escapeHtml(header)}</span>
        <span class="array-item-actions">
          <button class="btn-mini" data-action="up"     title="上移"${upDisabled}>↑</button>
          <button class="btn-mini" data-action="down"   title="下移"${downDisabled}>↓</button>
          <button class="btn-mini" data-action="remove" title="删除"${removeDisabled}>✕</button>
        </span>
      </summary>
      <div class="array-item-body">${body}</div>
    </details>
  `;
}

async function bindArraySectionListeners(slide, slideIdx) {
  // Per-field autosave (blur for input/textarea, change for select)
  $$(".array-field").forEach((el) => {
    const evt = el.tagName === "SELECT" ? "change" : "blur";
    el.addEventListener(evt, async () => {
      const orig = el.dataset.orig;
      const path = el.dataset.setPath;
      if (el.value === orig) return;
      // skipReload — iframe shows stale text but inspector form is correct;
      // user can hit ↻ Render or do a structural op to refresh
      await runOp("set", [path, el.value], { skipReload: true });
    });
  });

  // Per-item up/down/remove
  $$(".array-section").forEach((section) => {
    const fieldName = section.dataset.fieldName;
    section.querySelectorAll(".array-item-actions .btn-mini").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (btn.disabled) return;
        const action = btn.dataset.action;
        const itemEl = btn.closest(".array-item");
        const idx = parseInt(itemEl.dataset.idx, 10);
        await mutateArray(slideIdx, fieldName, (arr) => {
          if (action === "up"     && idx > 0)               [arr[idx-1], arr[idx]] = [arr[idx], arr[idx-1]];
          else if (action === "down" && idx < arr.length-1) [arr[idx], arr[idx+1]] = [arr[idx+1], arr[idx]];
          else if (action === "remove")                      arr.splice(idx, 1);
          return arr;
        });
      });
    });
  });

  // Add buttons (non-polymorphic)
  $$(".array-add-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const fieldName = btn.dataset.fieldName;
      const lookupKey = slide.variant ? `${slide.layout}:${slide.variant}` : slide.layout;
      const cfg = ARRAY_FIELDS[lookupKey][fieldName];
      await mutateArray(slideIdx, fieldName, (arr) => {
        arr.push(cfg.newItem());
        return arr;
      });
    });
  });

  // Polymorphic add (block type picker)
  $$(".poly-add-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const fieldName = btn.dataset.fieldName;
      const section = btn.closest(".array-section");
      const sel = section.querySelector(".poly-add-type");
      const blockType = sel.value;
      const blockCfg = BLOCK_TYPES[blockType];
      if (!blockCfg) return;
      await mutateArray(slideIdx, fieldName, (arr) => {
        arr.push(blockCfg.defaults());
        return arr;
      });
    });
  });

  // Nested string sub-array buttons (e.g. branch.leaves)
  $$(".btn-mini[data-sub-action]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.preventDefault(); e.stopPropagation();
      if (btn.disabled) return;
      const subPath = btn.dataset.subPath;
      const subIdx  = parseInt(btn.dataset.subIdx, 10);
      const action  = btn.dataset.subAction;
      await mutateArray(slideIdx, subPath, (arr) => {
        if (action === "up"     && subIdx > 0)               [arr[subIdx-1], arr[subIdx]] = [arr[subIdx], arr[subIdx-1]];
        else if (action === "down" && subIdx < arr.length-1) [arr[subIdx], arr[subIdx+1]] = [arr[subIdx+1], arr[subIdx]];
        else if (action === "remove")                         arr.splice(subIdx, 1);
        return arr;
      });
    });
  });
  $$(".sub-string-add").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      const subPath = btn.dataset.subPath;
      // Look up the sub-array config from current cfg by parsing the path
      // subPath shape: "<fieldName>.<idx>.<sub.key>"  — find the cfg
      const m = subPath.match(/^([^.]+(?:\.[^.0-9][^.]*)*)\.(\d+)\.([^.]+)$/);
      // simpler: just match last path segment as sub.key
      const parts = subPath.split(".");
      const subKey = parts[parts.length - 1];
      const fieldName = parts.slice(0, -2).join(".");
      const lookupKey = slide.variant ? `${slide.layout}:${slide.variant}` : slide.layout;
      const cfg = ARRAY_FIELDS[lookupKey] && ARRAY_FIELDS[lookupKey][fieldName];
      const subCfg = cfg && (cfg.subStringArrays || []).find(s => s.key === subKey);
      if (!subCfg) return;
      await mutateArray(slideIdx, subPath, (arr) => {
        arr.push(subCfg.newItem());
        return arr;
      });
    });
  });
}

async function mutateArray(slideIdx, fieldName, mutator) {
  // fieldName may be dotted ("quadrants.tl.items", "branches.0.leaves").
  const cur = getNestedField(state.deck.slides[slideIdx].data, fieldName) || [];
  const next = mutator([...cur]);
  const path = `slides.${slideIdx}.data.${fieldName}`;
  // For structural array changes (add/remove/move), DO reload preview so user
  // sees the new card / removed bar / reordered nodes.
  await runOp("set", [path, JSON.stringify(next)]);
  reloadPreview();
}

function attachAutoSave(id, getOldValue, makeOpArgs, normalize) {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener("blur", async () => {
    let v = el.value;
    if (normalize) v = normalize(v);
    if (v === getOldValue()) return;
    const [cmd, args] = makeOpArgs(v);
    await runOp(cmd, args);
  });
}

async function onVariantChange(e) {
  const s = state.deck.slides[state.selectedIdx];
  if (!s) return;
  const newVariant = e.target.value;
  if (newVariant === s.variant) return;
  // deck-cli set-variant warns about field drops + prompts; --yes bypasses.
  // For safety in the UI: confirm here ourselves.
  if (!confirm(
    `切换 variant: ${s.variant} → ${newVariant}\n\n` +
    `所有不属于新 variant 的 data 字段会被丢弃(deck-cli 自动 backup)。\n继续?`
  )) {
    e.target.value = s.variant;
    return;
  }
  await runOp("set-variant", [s.key, newVariant]);
}

async function cloneCurrentSlide() {
  const s = state.deck.slides[state.selectedIdx];
  if (!s) return;
  // Auto-generate non-colliding key: -copy, -copy-2, -copy-3 ...
  const existing = new Set(state.deck.slides.map(x => x.key));
  let newKey = `${s.key}-copy`;
  let n = 2;
  while (existing.has(newKey)) {
    newKey = `${s.key}-copy-${n++}`;
  }
  const data = await runOp("clone", [s.key, newKey]);
  if (!data || !data.ok) return;
  // Select the cloned slide (right after the original by default)
  const newIdx = state.deck.slides.findIndex(x => x.key === newKey);
  if (newIdx >= 0) selectSlide(newIdx);
  log(`✓ cloned as '${newKey}'`);
}

async function deleteCurrentSlide() {
  const s = state.deck.slides[state.selectedIdx];
  if (!s) return;
  if (!confirm(`真要删除 slide '${s.key}'? (会自动备份)`)) return;
  const oldIdx = state.selectedIdx;
  await runOp("delete", [s.key]);
  // After delete, slides[oldIdx] is now what was slides[oldIdx+1].
  // Clamp to last valid index; or null if deck is empty.
  const n = state.deck.slides.length;
  if (n === 0) {
    state.selectedIdx = null;
  } else {
    state.selectedIdx = Math.min(oldIdx, n - 1);
    selectSlide(state.selectedIdx);
  }
  renderInspector();
}

function selectSlide(i) {
  state.selectedIdx = i;
  $$(".slide-row").forEach((el, j) =>
    el.classList.toggle("is-selected", j === i)
  );
  renderInspector();
  scrollPreviewTo(i);
}

function scrollPreviewTo(i) {
  const iframe = $("#previewIframe");
  if (!iframe || !iframe.contentWindow) return;
  // feishu-deck.js syncs current slide via window location hash like #02-key.
  // We post to iframe by reloading with #N or via postMessage.
  try {
    const num = String(i + 1).padStart(2, "0");
    // Try hash navigation first — feishu-deck.js listens for hashchange
    iframe.contentWindow.location.hash = `#${num}`;
  } catch (e) { /* cross-origin or not ready */ }
}

// ---------------------------------------------------------------- switch deck

async function openSwitchDeckModal() {
  const data = await api("/api/decks");
  const list = $("#deckList");
  if (!data.ok) {
    list.innerHTML = `<li class="muted">load failed</li>`;
  } else {
    list.innerHTML = data.decks.map((d) => `
      <li class="deck-row ${d.is_current ? "is-current" : ""}" data-path="${escapeAttr(d.path)}">
        <div class="deck-title">${escapeHtml(d.title)}</div>
        <div class="deck-meta">
          <span class="badge">${d.n_slides} slides</span>
          <code>${escapeHtml(d.path)}</code>
        </div>
      </li>`).join("") || `<li class="muted">没有找到 deck.json (跑过的 runs/&lt;ts&gt;/output/ 都没有)</li>`;
    list.querySelectorAll(".deck-row").forEach((li) => {
      li.addEventListener("click", () => switchDeck(li.dataset.path));
    });
  }
  $("#switchModal").classList.remove("hidden");
}

async function switchDeck(path) {
  const data = await api("/api/switch-deck", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
  if (!data.ok) return;
  // Re-fetch deck + reset state + reload preview
  state.selectedIdx = null;
  await fetchDeck();
  reloadPreview();
  $("#switchModal").classList.add("hidden");
  log(`✓ switched to ${path}`);
}

// ---------------------------------------------------------------- fullscreen preview
// Hide both side panes so preview takes the full editor window. Toggle via
// button or Esc. (For browser-level fullscreen of the iframe itself, use
// the iframe's own bottom-bar ⛶ button or press F.)
function toggleFullscreenPreview() {
  const layout = $(".layout");
  const inFull = layout.classList.contains("no-slides");
  if (inFull) {
    layout.classList.remove("no-slides", "no-inspector");
    $("#btnFullscreen").textContent = "⛶ 全屏";
  } else {
    layout.classList.add("no-slides", "no-inspector");
    $("#btnFullscreen").textContent = "✕ 退出全屏";
  }
  // After layout shift, force iframe to re-scale (its inner ResizeObserver
  // may not fire if iframe element resize doesn't propagate to inner doc).
  setTimeout(() => {
    const iframe = $("#previewIframe");
    if (iframe && iframe.contentWindow) {
      iframe.contentWindow.dispatchEvent(new Event("resize"));
    }
  }, 60);
}

function reloadPreview() {
  const iframe = $("#previewIframe");
  if (!iframe) return;
  let hash = "";
  try {
    hash = iframe.contentWindow ? iframe.contentWindow.location.hash : "";
  } catch (e) { /* cross-origin or not loaded */ }
  // /preview/* is not token-gated (relative URLs in preview HTML can't
  // carry tokens, see deck-editor.py do_GET) — Same-Origin Policy + no
  // CORS allow-origin already blocks cross-origin reads.
  iframe.src = `/preview/index.html?mode=present&t=${Date.now()}${hash}`;
  iframe.addEventListener("load", setupPreviewInPlaceEdit, { once: true });
}

// ---------------------------------------------------------------- in-place edit

// Translate a data-text-id like "slide-04.title" or "slide-02.item-03" into
// the JSON path relative to the deck (e.g. "data.title", "data.items.2.title_zh").
// Mirrors the data-text-id formats emitted by render-deck.py enrichers.
function textIdToSlidePath(textId) {
  const m = textId.match(/^slide-\d+\.(.+)$/);
  if (!m) return null;
  let field = m[1];

  // text-id naming → schema field naming (dashes vs underscores)
  field = field
    .replace(/^chapter-num$/,    "chapter_num")
    .replace(/^source-footer$/,  "source_footer");

  const dec = (s) => String(parseInt(s, 10) - 1);

  // Two-level array structures (handle first so single-level regex doesn't eat them)
  let mm;
  if ((mm = field.match(/^branch-(\d+)\.leaf-(\d+)$/))) {
    return `data.branches.${dec(mm[1])}.leaves.${dec(mm[2])}`;
  }
  if ((mm = field.match(/^row-(\d+)\.cell-(\d+)$/))) {
    return `data.rows.${dec(mm[1])}.${dec(mm[2])}`;
  }
  if ((mm = field.match(/^(tl|tr|bl|br)\.item-(\d+)$/))) {
    return `data.quadrants.${mm[1]}.items.${dec(mm[2])}`;
  }

  // Single-array structures. Most are a simple "name-NN.<X>" → "names.<NN-1>.<X>".
  // card-NN.title is a naming alias: id says "title", schema says "title_zh".
  const ITEM_TRANSFORMS = [
    [/^card-(\d+)\.title$/,          (m) => `cards.${dec(m[1])}.title_zh`],
    [/^card-(\d+)\.(.+)$/,           (m) => `cards.${dec(m[1])}.${m[2]}`],
    [/^col-(\d+)\.(.+)$/,            (m) => `cols.${dec(m[1])}.${m[2]}`],
    [/^node-(\d+)\.(.+)$/,           (m) => `nodes.${dec(m[1])}.${m[2]}`],
    [/^step-(\d+)\.(.+)$/,           (m) => `steps.${dec(m[1])}.${m[2]}`],
    [/^bar-(\d+)\.(.+)$/,            (m) => `bars.${dec(m[1])}.${m[2]}`],
    [/^branch-(\d+)\.(.+)$/,         (m) => `branches.${dec(m[1])}.${m[2]}`],
    [/^head-(\d+)$/,                 (m) => `headers.${dec(m[1])}`],
    [/^item-(\d+)$/,                 (m) => `items.${dec(m[1])}.title_zh`],   // agenda
    [/^pill-(\d+)$/,                 (m) => `pills.${dec(m[1])}`],            // section
    [/^(tl|tr|bl|br)\.(.+)$/,        (m) => `quadrants.${m[1]}.${m[2]}`],     // matrix
    [/^text\.feature-(\d+)$/,        (m) => `text.feature_list.${dec(m[1])}`], // content/2col bullets
  ];
  for (const [re, fn] of ITEM_TRANSFORMS) {
    const mm = field.match(re);
    if (mm) return `data.${fn(mm)}`;
  }

  // Top-level / dot-path (title, lede, hook.lead, arc.value.accent, etc.)
  return `data.${field}`;
}

// Find this element's slide-key by walking up to .slide[data-slide-key].
function findSlideKeyFor(el) {
  let cur = el;
  while (cur && cur !== cur.ownerDocument.body) {
    if (cur.dataset && cur.dataset.slideKey) return cur.dataset.slideKey;
    cur = cur.parentElement;
  }
  return null;
}

const INPLACE_STYLE_ID = "fs-inplace-style";
const INPLACE_STYLE = `
  /* ── editor-only override: ALWAYS fill the iframe viewport ──
     feishu-deck.js auto-switches to scroll mode on <900px viewports +
     scroll-mode .deck has max-width:1280px+margin:auto + padding:12px —
     those reasonable production defaults make the deck shrink to a small
     centered card in the editor's preview pane. We force present-style
     fill here so the deck always occupies the entire iframe regardless
     of mode classification. */
  html, body { margin: 0 !important; padding: 0 !important; height: 100% !important;
               background: #000 !important; overflow: hidden !important; }
  .deck { position: fixed !important; inset: 0 !important;
          width: 100vw !important; height: 100vh !important;
          max-width: none !important; padding: 0 !important; margin: 0 !important;
          display: block !important; gap: 0 !important; }
  .deck .slide-frame { position: absolute !important; inset: 0 !important;
                       aspect-ratio: auto !important;
                       opacity: 0; pointer-events: none;
                       transition: opacity .2s ease;
                       border: 0 !important; border-radius: 0 !important;
                       box-shadow: none !important; }
  .deck .slide-frame.is-current { opacity: 1 !important; pointer-events: auto !important; }

  /* In-place edit visual hooks */
  [data-text-id][data-fs-editable] {
    cursor: text;
    outline: 1px dashed rgba(60, 127, 255, 0);
    outline-offset: 4px;
    transition: outline-color 0.15s, background-color 0.15s;
    border-radius: 4px;
  }
  [data-text-id][data-fs-editable]:hover {
    outline-color: rgba(60, 127, 255, 0.55);
    background-color: rgba(60, 127, 255, 0.06);
  }
  [data-text-id][data-fs-editable]:focus {
    outline: 2px solid var(--fs-blue, #3C7FFF);
    outline-offset: 4px;
    background-color: rgba(60, 127, 255, 0.10);
  }
`;

// Re-affirm contentEditable on already-wired elements. Cheap, idempotent.
// Called after every runOp so a stale browser state (e.g. contentEditable
// silently reset by some DOM op) gets restored without re-attaching
// duplicate listeners.
function refreshIframeEditableState() {
  const iframe = $("#previewIframe");
  if (!iframe || !iframe.contentDocument) return;
  const doc = iframe.contentDocument;
  let fixed = 0;
  doc.querySelectorAll("[data-fs-editable]").forEach((el) => {
    if (el.contentEditable !== "plaintext-only") {
      el.contentEditable = "plaintext-only";
      fixed++;
    }
  });
  if (fixed > 0) {
    console.log("[fs-edit] refreshIframeEditableState restored", fixed, "elements");
  }
}

function setupPreviewInPlaceEdit() {
  const iframe = $("#previewIframe");
  if (!iframe || !iframe.contentDocument) return;
  const doc = iframe.contentDocument;

  // Force present mode + trigger scale recompute. feishu-deck.js auto-switches
  // to scroll mode on viewports < 900px wide — and the editor's preview pane
  // can easily be <900px on a 1280-1366px window. This guarantees the iframe
  // stays in present mode regardless of pane width.
  const deck = doc.querySelector(".deck");
  if (deck && deck.dataset.mode !== "present") {
    deck.dataset.mode = "present";
  }
  // Kick a resize so scaleFrame re-runs with the latest viewport.
  const cw = iframe.contentWindow;
  if (cw) cw.dispatchEvent(new Event("resize"));

  // Inject hover/focus styling once
  if (!doc.getElementById(INPLACE_STYLE_ID)) {
    const styleEl = doc.createElement("style");
    styleEl.id = INPLACE_STYLE_ID;
    styleEl.textContent = INPLACE_STYLE;
    doc.head.appendChild(styleEl);
  }

  // Walk every text-id leaf. Make editable only when:
  //   (a) it has no child elements (pure text leaf, safe to edit)
  //   (b) data-text-id maps to a supported scalar JSON path
  doc.querySelectorAll("[data-text-id]").forEach((el) => {
    // Skip mixed-content elements (e.g. blockquote with multiple spans, each
    // its own leaf). EXCEPTION: <br> children are fine — they're just layout
    // artifacts from \n → <br> normalization (e.g. cover title with line
    // breaks). textContent transparently converts them back to \n on read.
    const hasComplexChildren = [...el.children].some(c => c.tagName !== "BR");
    if (hasComplexChildren) return;
    if (el.dataset.fsEditable) return;       // already wired

    const path = textIdToSlidePath(el.dataset.textId);
    if (!path) return;                       // deep array item — Phase 4.b.2

    el.dataset.fsEditable = "1";
    el.contentEditable = "plaintext-only";
    el.spellcheck = false;
    // Heading-class tags are single-line; <p>/<blockquote> are multi-line.
    // (Newlines in titles still work via Shift+Enter or Cmd+Enter commit.)
    const SINGLE_LINE_TAGS = new Set(["H1", "H2", "H3", "H4", "H5", "H6", "SPAN", "LABEL"]);
    const isSingleLine = SINGLE_LINE_TAGS.has(el.tagName);
    el.title = isSingleLine
      ? `编辑 · Enter 保存 · Shift+Enter 换行 · Esc 取消`
      : `编辑 · Cmd/Ctrl+Enter 保存 · Esc 取消 · ${path}`;

    let snapshot = el.textContent;

    el.addEventListener("focus", () => {
      snapshot = el.textContent;
    });

    el.addEventListener("blur", async () => {
      const newVal = el.textContent;
      if (newVal === snapshot) return;
      const slideKey = findSlideKeyFor(el);
      if (!slideKey) {
        log(`in-place edit: no slide-key for ${el.dataset.textId}`);
        return;
      }
      const idx = state.deck.slides.findIndex((s) => s.key === slideKey);
      if (idx < 0) {
        log(`in-place edit: slide '${slideKey}' not in state`);
        return;
      }
      const fullPath = `slides.${idx}.${path}`;
      await runOp("set", [fullPath, newVal], { skipReload: true });
      // skipReload=true: contenteditable already shows the new text, no need
      // to redraw iframe. Trade-off: \n → <br> conversion (which only happens
      // server-side on render) won't be reflected until next structural op
      // or manual ↻ Render — but the user sees their typed newlines in the
      // contenteditable view, so visually it's coherent.
    });

    el.addEventListener("keydown", (e) => {
      // STOP keys from bubbling to iframe document — feishu-deck.js binds
      // Space / ArrowLeft / ArrowRight / PageUp / PageDown / Home / End to
      // slide navigation in present mode, which fires whenever the user types
      // while focused in a contenteditable inside the deck.
      e.stopPropagation();

      if (e.key === "Escape") {
        e.preventDefault();
        el.textContent = snapshot;
        el.blur();
        return;
      }
      if (e.key === "Enter") {
        // Single-line: Enter commits, Shift+Enter inserts newline
        // Multi-line: Enter inserts newline (default), Cmd/Ctrl+Enter commits
        if (isSingleLine && !e.shiftKey) {
          e.preventDefault();
          el.blur();
        } else if (!isSingleLine && (e.metaKey || e.ctrlKey)) {
          e.preventDefault();
          el.blur();
        }
      }
    });
  });
}

// ---------------------------------------------------------------- import modal

async function openImportModal() {
  $("#importFile").value = "";
  $("#importListWrap").classList.add("hidden");
  $("#importList").innerHTML = "";
  state.importSource = null;
  state.importSourcePath = null;
  state.importPicked.clear();
  $("#importDo").disabled = true;
  $("#importModal").classList.remove("hidden");
}

function closeImportModal() {
  $("#importModal").classList.add("hidden");
}

async function onImportFile(e) {
  const file = e.target.files[0];
  if (!file) return;
  try {
    // Read as base64 — server doesn't need an absolute path.
    const b64 = await fileToBase64(file);
    state.importBase64 = b64;
    state.importFilename = file.name;

    // First round-trip: server parses + returns slide list for the picker.
    const data = await api("/api/import-upload", {
      method: "POST",
      body: JSON.stringify({ filename: file.name, base64_content: b64 }),
    });
    if (!data.ok) {
      alert(`读取文件失败: ${data.error || "unknown"}`);
      return;
    }
    state.importSource = { slides: data.slides };
    state.importPicked.clear();
    renderImportList();
    $("#importListWrap").classList.remove("hidden");
    $("#importDo").disabled = true;
  } catch (err) {
    alert(`读取文件失败: ${err.message}`);
  }
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload  = () => {
      // dataURL: "data:application/json;base64,..."
      const dataUrl = reader.result;
      const comma = dataUrl.indexOf(",");
      resolve(dataUrl.slice(comma + 1));
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function renderImportList() {
  const list = $("#importList");
  list.innerHTML = "";
  state.importSource.slides.forEach((s, i) => {
    const li = document.createElement("li");
    li.dataset.key = s.key;
    if (state.importPicked.has(s.key)) li.classList.add("is-picked");
    li.innerHTML = `
      <input type="checkbox" ${state.importPicked.has(s.key) ? "checked" : ""}>
      <span class="idx">${String(i + 1).padStart(2, "0")}</span>
      <span class="key">${escapeHtml(s.key)}</span>
      <span class="layout-tag">${escapeHtml(s.layout)}${s.variant ? "/" + s.variant : ""}</span>
    `;
    li.addEventListener("click", (e) => {
      if (e.target.tagName !== "INPUT") {
        const cb = li.querySelector("input");
        cb.checked = !cb.checked;
      }
      if (li.querySelector("input").checked) state.importPicked.add(s.key);
      else state.importPicked.delete(s.key);
      li.classList.toggle("is-picked", state.importPicked.has(s.key));
      $("#importDo").disabled = state.importPicked.size === 0;
    });
    list.appendChild(li);
  });
}

async function doImport() {
  closeImportModal();
  // Server already has the parsed JSON in memory? No — Phase 4.a server is
  // stateless on uploads. We re-send the base64 once per slide. Cheap (file
  // is in memory; ~KB-range JSON).
  for (const slideKey of state.importPicked) {
    const data = await api("/api/import-upload", {
      method: "POST",
      body: JSON.stringify({
        filename:       state.importFilename,
        base64_content: state.importBase64,
        slide_key:      slideKey,
      }),
    });
    if (data.ok) {
      state.deck = data.deck;
      log(`✓ imported '${slideKey}' as '${data.imported_key}' at #${data.position}`);
    } else {
      logErr(data.error || "import failed");
      break;
    }
  }
  renderTopBar();
  renderSlideList();
  reloadPreview();
}

// ---------------------------------------------------------------- utils

function setStatus(kind, text) {
  const pill = $("#statusPill");
  pill.className = `status-pill status-${kind}`;
  pill.textContent = text;
}

function log(msg) {
  const lb = $("#logbar");
  lb.classList.remove("is-err");
  lb.textContent = msg;
}

function logErr(msg) {
  const lb = $("#logbar");
  lb.classList.add("is-err");
  lb.textContent = msg.split("\n")[0].slice(0, 200);
  console.error(msg);
}

function clearDropIndicators() {
  $$(".slide-row.drop-above, .slide-row.drop-below").forEach((el) => {
    el.classList.remove("drop-above");
    el.classList.remove("drop-below");
  });
}

function escapeHtml(s) {
  if (s === null || s === undefined) return "";
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
function escapeAttr(s) { return escapeHtml(s); }

// ---------------------------------------------------------------- boot

document.addEventListener("DOMContentLoaded", () => {
  $("#btnRender").addEventListener("click", async () => {
    setStatus("busy", "渲染中…");
    const data = await api("/api/render", { method: "POST" });
    if (data.ok) {
      reloadPreview();
      log("✓ 已重新渲染");
    } else {
      logErr(data.log || data.error || "render 失败");
    }
  });
  $("#btnReload").addEventListener("click", fetchDeck);
  $("#btnImport").addEventListener("click", openImportModal);
  $("#btnSwitchDeck").addEventListener("click", openSwitchDeckModal);
  $("#btnImportPDF").addEventListener("click", () => $("#pdfFile").click());
  $("#pdfFile").addEventListener("change", async (e) => {
    if (e.target.files[0]) await importPdf(e.target.files[0]);
    e.target.value = "";
  });
  $("#switchClose").addEventListener("click", () => $("#switchModal").classList.add("hidden"));
  $("#btnFullscreen").addEventListener("click", toggleFullscreenPreview);
  $("#importCancel").addEventListener("click", closeImportModal);
  $("#helpClose").addEventListener("click", () => $("#helpModal").classList.add("hidden"));
  $("#importCancel2").addEventListener("click", closeImportModal);
  $("#importFile").addEventListener("change", onImportFile);
  $("#importDo").addEventListener("click", doImport);

  // Wire in-place edit for the initial iframe load too (not just reloads).
  // Also: set initial src here (not in HTML) so the CSRF token can be
  // attached — the iframe src goes through the token-gated /preview/* route.
  const initialFrame = $("#previewIframe");
  if (initialFrame) {
    initialFrame.addEventListener("load", setupPreviewInPlaceEdit, { once: true });
    initialFrame.src = "/preview/index.html?mode=present";
  }

  // Global keyboard shortcuts. Skip when typing in input/textarea/select
  // (avoid eating Backspace etc.).
  document.addEventListener("keydown", (e) => {
    // ESC always closes any open modal
    if (e.key === "Escape" && !$("#importModal").classList.contains("hidden")) {
      closeImportModal();
      return;
    }
    if (e.key === "Escape" && !$("#helpModal").classList.contains("hidden")) {
      $("#helpModal").classList.add("hidden");
      return;
    }
    // ESC also exits fullscreen preview
    if (e.key === "Escape" && $(".layout").classList.contains("no-slides")) {
      toggleFullscreenPreview();
      return;
    }
    // ? → open keyboard cheatsheet
    if (e.key === "?" && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      $("#helpModal").classList.remove("hidden");
      return;
    }
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select") return;

    // Cmd/Ctrl + S → render
    if ((e.metaKey || e.ctrlKey) && (e.key === "s" || e.key === "S")) {
      e.preventDefault();
      $("#btnRender").click();
      return;
    }

    // Need a selected slide for the rest
    if (state.selectedIdx === null || !state.deck) return;
    const n = state.deck.slides.length;

    // Arrow up/down → navigate slide selection
    if (e.key === "ArrowDown" && state.selectedIdx < n - 1) {
      e.preventDefault();
      selectSlide(state.selectedIdx + 1);
      return;
    }
    if (e.key === "ArrowUp" && state.selectedIdx > 0) {
      e.preventDefault();
      selectSlide(state.selectedIdx - 1);
      return;
    }

    // Delete / Backspace → delete selected slide (confirm)
    if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      deleteCurrentSlide();
      return;
    }
  });

  fetchDeck();
});
