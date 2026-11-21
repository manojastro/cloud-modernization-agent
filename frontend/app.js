/* Cloud Modernization Cockpit - vanilla ES module, zero external dependencies. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const API = "/api/v1";

const state = {
  meta: null,
  portfolio: [],
  assessments: [],
  waves: [],
  selectedApp: "payments-api-gateway",
};

/* ---------------------------------------------------------------- helpers */
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const child of children) {
    if (child == null) continue;
    node.append(child);
  }
  return node;
}

async function api(path, opts = {}) {
  try {
    const resp = await fetch(`${API}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    if (!resp.ok) {
      console.warn(`api ${path} -> ${resp.status}`);
      return { __error: resp.status, ...(await resp.json().catch(() => ({}))) };
    }
    const type = resp.headers.get("content-type") || "";
    return type.includes("json") ? await resp.json() : await resp.text();
  } catch (err) {
    console.warn(`api ${path} failed`, err);
    return { __error: 0 };
  }
}

const ok = (data) => data && !data.__error;

function busy(on, label = "working...") {
  $("#busy").textContent = label;
  $("#busy").classList.toggle("hidden", !on);
}

/* ------------------------------------------------------------ meta / boot */
async function loadMeta() {
  state.meta = await api("/meta");
  const m = state.meta;
  $("#mock-badge").classList.toggle("hidden", !(ok(m) && m.mock_mode));
  if (ok(m)) {
    $("#mock-badge").textContent = m.badge || "MOCK MODE";
    $("#meta-info").textContent =
      `v${m.version} - llm=${m.llm_mode} - apps=${m.application_count}`;
  } else {
    $("#meta-info").textContent = "backend unreachable";
  }
}

/* ------------------------------------------------------------------ boot */
async function refreshAll() {
  await loadMeta();
  const [portfolio, assessments, waves, blocked, graph, opps, risks, events] =
    await Promise.all([
      api("/applications?limit=400"),
      api("/assessments"),
      api("/waves"),
      api("/blocked"),
      api("/graph"),
      api("/opportunities"),
      api("/risks"),
      api("/audit/events?limit=60"),
    ]);

  state.portfolio = ok(portfolio) ? portfolio.items : [];
  state.assessments = ok(assessments) ? assessments : [];
  state.waves = ok(waves) ? waves : [];

  renderPortfolio(portfolio);
  renderMix();
  renderHeatmap();
  renderGraph(ok(graph) ? graph : { nodes: [], edges: [] });
  renderDebt();
  renderAgenticChecklist();
  renderWaves();
  renderBlocked(ok(blocked) ? blocked : []);
  renderProgress();
  renderOpportunities(ok(opps) ? opps : []);
  renderRisks(ok(risks) ? risks : []);
  renderAudit(ok(events) ? events : []);

  const empty = state.portfolio.length === 0;
  $("#portfolio-empty").classList.toggle("hidden", !empty);
  rebuildSelectors();
}

/* ------------------------------------------------------------- portfolio */
async function loadPortfolio() {
  const params = new URLSearchParams();
  const q = $("#f-q").value.trim();
  if (q) params.set("q", q);
  for (const [id, key] of [["f-strategy", "strategy"], ["f-band", "readiness_band"],
                           ["f-runtime", "runtime_id"], ["f-sort", "sort"]]) {
    const v = $(`#${id}`).value;
    if (v) params.set(key, v);
  }
  params.set("limit", "400");
  const data = await api(`/applications?${params}`);
  state.portfolio = ok(data) ? data.items : [];
  renderPortfolio(data);
  renderHeatmap();
}

function chip(text, cls) { return el("span", { class: `chip ${cls}`, text }); }

function renderPortfolio(data) {
  const tbody = $("#portfolio-table tbody");
  tbody.replaceChildren();
  const items = state.portfolio;
  $("#portfolio-count").textContent =
    ok(data) ? `${data.total} shown` : "";
  for (const a of items) {
    tbody.append(el("tr", {
      onclick: () => selectApp(a.id),
    },
      el("td", { text: a.name }),
      el("td", { text: a.domain }),
      el("td", { text: String(a.criticality) }),
      el("td", { text: a.runtime_id }),
      el("td", {}, a.strategy ? chip(a.strategy, `s-${a.strategy}`) : null),
      el("td", { text: a.strategy_confidence != null ? a.strategy_confidence.toFixed(2) : "-" }),
      el("td", {}, a.readiness_band ? chip(a.readiness_band, `b-${a.readiness_band}`) : null),
      el("td", { text: a.agentic_score != null ? `${a.agentic_score}/9` : "-" }),
      el("td", { text: a.debt_index != null ? a.debt_index.toFixed(0) : "-" }),
      el("td", {}, chip(a.placement === "cloud-managed" ? "cloud" : "on-prem",
                        a.placement === "cloud-managed" ? "placement-cloud-managed" : "")),
      el("td", { text: a.usage_per_day.toLocaleString() }),
      el("td", { text: `$${Math.round(a.annual_infra_cost_usd).toLocaleString()}` }),
    ));
  }
}

/* -------------------------------------------------------------- mix donut */
const STRAT_COLORS = {
  REHOST: "#3ba776", REPLATFORM: "#3f7fb5", REFACTOR: "#a06bd4",
  REPURCHASE: "#c99a3c", RELOCATE: "#4fae9b", RETAIN: "#6b7686", RETIRE: "#b55555",
};

function renderMix() {
  const svg = $("#mix-donut");
  const legend = $("#mix-legend");
  legend.replaceChildren();
  svg.replaceChildren();

  const counts = {};
  for (const a of state.portfolio) {
    if (a.strategy) counts[a.strategy] = (counts[a.strategy] || 0) + 1;
  }
  const entries = Object.entries(counts).sort((x, y) => y[1] - x[1]);
  const total = entries.reduce((s, [, n]) => s + n, 0);
  if (!total) return;

  const cx = 100, cy = 100, r = 70, sw = 26;
  let offset = 0;
  for (const [strat, n] of entries) {
    const frac = n / total;
    const dash = frac * 2 * Math.PI * r;
    svg.append(Object.assign(document.createElementNS(
      "http://www.w3.org/2000/svg", "circle"), {
      cx, cy, r, fill: "none",
      stroke: STRAT_COLORS[strat] || "#888",
      "stroke-width": sw,
      "stroke-dasharray": `${dash - 1.5} ${2 * Math.PI * r - dash + 1.5}`,
      "stroke-dashoffset": -offset,
      transform: `rotate(-90 ${cx} ${cy})`,
    }));
    offset += dash;
    legend.append(el("li", {},
      el("i", { style: `background:${STRAT_COLORS[strat] || "#888"}` }),
      el("span", { text: `${strat} (${n})` })));
  }
  const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
  Object.assign(label, { textContent: `${total} classified` });
  Object.entries({ x: cx, y: cy, fill: "#7d8ca0", "font-size": 11,
                   "text-anchor": "middle" }).forEach(([k, v]) =>
    label.setAttribute(k, v));
  svg.append(label);
}

/* ------------------------------------------------------------- heatmap */
function heatColor(score) {
  // 0 -> red-ish, 9 -> green
  const hue = 8 + (score / 9) * 130; // red(8) to green(138)
  return `hsl(${hue}, 55%, 42%)`;
}

function renderHeatmap() {
  const wrap = $("#heatmap");
  wrap.replaceChildren();
  const byApp = new Map(state.assessments.map((a) => [a.application_id, a]));
  const items = state.portfolio.length
    ? state.portfolio.map((p) => ({ id: p.id, name: p.name,
        score: byApp.get(p.id)?.agentic_score }))
    : state.assessments.map((a) => ({ id: a.application_id,
        name: a.application_id, score: a.agentic_score }));
  items.sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
  for (const item of items.slice(0, 400)) {
    wrap.append(el("div", {
      class: "heat-cell",
      title: `${item.name}: agentic ${item.score ?? "?"}/9`,
      style: `background:${item.score == null ? "#333" : heatColor(item.score)}`,
      onclick: () => selectApp(item.id),
    }));
  }
}

/* ---------------------------------------------------------- dependency map */
function renderGraph(graph) {
  const svg = $("#depmap");
  svg.replaceChildren();
  const domain = $("#graph-domain").value;
  const hiddenOnly = $("#graph-hidden-only").checked;

  const apps = graph.nodes.filter((n) => n.kind === "application"
    && (!domain || n.domain === domain));
  const keep = new Set(apps.map((n) => n.id));
  let edges = graph.edges.filter((e) =>
    e.relation !== "APP_DEPENDS_ON_LIBRARY" && e.relation !== "APP_RUNS_BATCH_JOB"
    && e.relation !== "APP_REQUIRES_SERVER");
  if (hiddenOnly) {
    edges = edges.filter((e) => e.discovered_by === "transfer-log-correlation");
    const touched = new Set();
    edges.forEach((e) => { touched.add(e.src); touched.add(e.dst); });
    const filtered = apps.filter((n) => touched.has(n.id));
    keep.clear();
    filtered.forEach((n) => keep.add(n.id));
  }

  const colX = (kind) => (kind === "service" ? 700 : kind === "database" ? 880 : 120);
  const pos = new Map();
  const columns = { application: [], service: [], database: [] };
  for (const n of graph.nodes) {
    if (!keep.has(n.id) && n.kind === "application") continue;
    if (n.kind !== "application" && n.kind !== "service" && n.kind !== "database") continue;
    columns[n.kind].push(n);
  }
  const layoutCol = (list, kind, startY = 20, endY = 540) => {
    list.sort((a, b) => String(a.id).localeCompare(String(b.id)));
    list.forEach((n, i) => pos.set(n.id, {
      x: colX(kind),
      y: list.length > 1 ? startY + (i * (endY - startY)) / (list.length - 1) : (startY + endY) / 2,
      kind,
      node: n,
    }));
  };
  // applications column may hold up to ~140 rows; compress into its band
  const bandEnd = Math.min(540, 40 + columns.application.length * 7);
  layoutCol(columns.service, "service");
  layoutCol(columns.database, "database");
  layoutCol(columns.application, "application", 20, bandEnd);

  const NS = "http://www.w3.org/2000/svg";
  const edgeColor = { APP_CALLS_APP: "#46698f", APP_USES_DATABASE: "#3f7f5f",
                      APP_USES_IDENTITY: "#7a63b5", APP_SENDS_FILE_TO: "#ffb454",
                      APP_USES_FILE_SHARE: "#5f6f85", APP_PUBLISHES_EVENT: "#8a6d3b",
                      APP_CONSUMES_EVENT: "#8a6d3b" };

  let rendered = 0;
  for (const e of edges) {
    if (rendered > 900) break;
    const a = pos.get(e.src);
    const b = pos.get(e.dst);
    if (!a || !b) continue;
    const hidden = e.discovered_by === "transfer-log-correlation";
    const path = document.createElementNS(NS, "path");
    const mx = (a.x + b.x) / 2;
    path.setAttribute("d",
      `M ${a.x} ${a.y} C ${mx} ${a.y}, ${mx} ${b.y}, ${b.x} ${b.y}`);
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", hidden ? "#ffb454" : edgeColor[e.relation] || "#33465e");
    path.setAttribute("stroke-width", hidden ? 2.2 : 0.7);
    if (hidden) path.setAttribute("stroke-dasharray", "5 3");
    path.setAttribute("opacity", hidden ? 0.95 : 0.45);
    const tip = `${e.relation} (${e.discovered_by})`;
    const title = document.createElementNS(NS, "title");
    title.textContent = `${e.src} -> ${e.dst}\n${tip}`;
    path.append(title);
    svg.append(path);
    rendered++;
  }

  for (const [id, p] of pos) {
    const rect = document.createElementNS(NS, "rect");
    const w = p.kind === "application" ? 14 : 18;
    rect.setAttribute("x", p.x - w / 2);
    rect.setAttribute("y", p.y - 5);
    rect.setAttribute("width", w);
    rect.setAttribute("height", 10);
    rect.setAttribute("rx", 3);
    rect.setAttribute("fill",
      p.kind === "service" ? "#b48cff" : p.kind === "database" ? "#3fae6a" : "#35507a");
    const title = document.createElementNS(NS, "title");
    title.textContent = `${p.node.label || id} (${p.kind})`;
    rect.append(title);
    svg.append(rect);
    if (p.kind !== "application" || columns.application.length <= 60) {
      const txt = document.createElementNS(NS, "text");
      txt.setAttribute("x", p.x + (p.kind === "application" ? 12 : 14));
      txt.setAttribute("y", p.y + 4);
      txt.setAttribute("font-size", 8.5);
      txt.setAttribute("fill", "#7d8ca0");
      txt.textContent = (p.node.label || id).slice(0, 34);
      svg.append(txt);
    }
  }
  if (!pos.size) {
    const note = document.createElementNS(NS, "text");
    note.setAttribute("x", 500); note.setAttribute("y", 280);
    note.setAttribute("fill", "#7d8ca0"); note.setAttribute("text-anchor", "middle");
    note.textContent = "no estate yet - seed and run the pipeline";
    svg.append(note);
  }
}

/* ------------------------------------------------------------ debt board */
function renderDebt() {
  const list = $("#debt-list");
  list.replaceChildren();
  const top = [...state.assessments].sort((a, b) => b.debt_index - a.debt_index)
    .slice(0, 10);
  for (const a of top) {
    list.append(el("li", {},
      el("header", {},
        el("b", { text: a.application_id }),
        el("span", { text: `${a.debt_index.toFixed(0)}/100 - complexity ${a.complexity_label}` })),
      el("div", { class: "bar-track" },
        el("div", { class: "bar-fill", style: `width:${Math.min(100, a.debt_index)}%` })),
      el("div", { class: "indicators", text: (a.indicators || []).join(", ") || "clean" }),
    ));
  }
}

/* ------------------------------------------------------ agentic checklist */
async function renderAgenticChecklist() {
  const sel = $("#agentic-app");
  const appId = sel.value || state.selectedApp;
  if (!appId) { $("#agentic-items").replaceChildren(); return; }
  const detail = await api(`/assessments/${appId}`);
  const list = $("#agentic-items");
  list.replaceChildren();
  if (!ok(detail)) {
    list.append(el("li", { class: "fail", text: "assessment unavailable" }));
    return;
  }
  // the checklist endpoint shape: use AgenticReadinessItem rows via detail?detail has summary only
  const summary = $("#agentic-summary");
  summary.textContent =
    `score ${detail.agentic_score}/9 - band ${detail.agentic_band} - ` +
    `complexity ${detail.complexity_score} (${detail.complexity_label}) - ` +
    `debt ${detail.debt_index}`;
}

function renderAgenticItems(items, score, band) {
  const list = $("#agentic-items");
  list.replaceChildren();
  for (const it of items || []) {
    list.append(el("li", {},
      el("span", { class: `mark ${it.passed ? "pass" : "fail"}`,
                   text: it.passed ? "[x]" : "[ ]" }),
      el("div", {},
        el("span", { text: it.label || it.item_key }),
        el("small", { text: it.note || "" })),
    ));
  }
  $("#agentic-summary").textContent =
    items ? `score ${score}/9 - band ${band}` : "";
}

/* ----------------------------------------------------------------- waves */
async function waveAction(path, body, label) {
  busy(true, label);
  const out = await api(path, { method: "POST", body: JSON.stringify(body || {}) });
  busy(false);
  if (!ok(out)) {
    alert(`action failed (${out.__error}): ${out.detail || "see backend logs"}`);
  }
  await refreshAll();
}

function renderWaves() {
  const row = $("#waves-row");
  row.replaceChildren();
  for (const w of state.waves) {
    const card = el("section", { class: "wave-card" });
    card.append(el("header", {},
      el("h3", { text: w.name || `Wave ${w.wave_number}` }),
      el("span", { class: `status-pill status-${w.status}`, text: w.status })));

    const chips = el("div", { class: "member-chips" });
    for (const m of w.memberships || []) {
      chips.append(el("span", {
        class: `m-chip ${m.execution_status}`,
        text: m.member_id,
        title: `${m.member_kind} - ${m.strategy || ""} - ${m.execution_status}`,
      }));
    }
    card.append(chips);

    const actions = el("div", { class: "wave-actions" });
    if (w.status === "AWAITING_APPROVAL" && w.approval_id) {
      actions.append(
        el("button", { class: "btn small approve",
            onclick: () => waveAction(`/approvals/${w.approval_id}/approve`,
              { decided_by: "cockpit", comment: "approved in cockpit" }, "approving..."),
            text: "Approve" }),
        el("button", { class: "btn small reject",
            onclick: () => waveAction(`/approvals/${w.approval_id}/reject`,
              { decided_by: "cockpit", comment: "rejected in cockpit" }, "rejecting..."),
            text: "Reject" }));
    }
    if (w.status === "APPROVED") {
      actions.append(el("button", { class: "btn small primary",
        onclick: () => waveAction(`/waves/${w.wave_number}/execute`,
          { actor: "cockpit" }, "executing wave..."),
        text: "Execute" }));
    }
    if ((w.status === "PLANNED" || w.status === "AWAITING_APPROVAL")) {
      actions.append(el("button", { class: "btn small",
        onclick: () => waveAction(`/waves/${w.wave_number}/preflight`, {},
          "preflighting..."), text: "Preflight" }));
    }
    card.append(actions);
    row.append(card);
  }
}

/* ---------------------------------------------------------------- blocked */
function renderBlocked(blocked) {
  const wrap = $("#blocked-list");
  wrap.replaceChildren();
  if (!blocked.length) {
    wrap.append(el("p", { class: "empty", text: "nothing blocked - every migrating app is scheduled" }));
    return;
  }
  for (const b of blocked) {
    wrap.append(el("div", { class: "blocked-item" },
      el("b", { text: b.application_id }), " ",
      el("code", { text: b.reason_code }),
      el("p", { text: b.reason_detail }),
      el("p", { text: `fix: ${b.suggested_resolution}` })));
  }
}

/* --------------------------------------------------------------- progress */
function renderProgress() {
  const wrap = $("#progress-bars");
  wrap.replaceChildren();
  const counts = {};
  let total = 0;
  for (const w of state.waves) {
    for (const m of w.memberships || []) {
      if (m.member_kind !== "application") continue;
      counts[m.execution_status] = (counts[m.execution_status] || 0) + 1;
      total++;
    }
  }
  const order = ["PENDING", "MIGRATING", "COMPLETED", "BLOCKED", "ROLLED_BACK"];
  for (const key of order) {
    const n = counts[key] || 0;
    if (!total && !n) continue;
    wrap.append(el("div", { class: "pbar-row" },
      el("span", { text: key.toLowerCase() }),
      el("div", { class: "bar-track" },
        el("div", { class: "bar-fill",
          style: `width:${total ? (n / total) * 100 : 0}%;` +
                 `background:${key === "COMPLETED" ? "var(--green)" :
                             key === "ROLLED_BACK" || key === "BLOCKED" ? "var(--red)" :
                             key === "MIGRATING" ? "var(--purple)" : "#3d5878"}`
        })),
      el("span", { text: String(n) })));
  }

  const rolledBack = [];
  for (const w of state.waves) {
    for (const m of w.memberships || []) {
      if (m.execution_status === "ROLLED_BACK") rolledBack.push(m.member_id);
    }
  }
  const callout = $("#rollback-callout");
  callout.classList.toggle("hidden", rolledBack.length === 0);
  callout.replaceChildren();
  for (const id of rolledBack) {
    callout.append(el("div", {},
      el("b", { text: "ROLLED BACK: " }),
      el("span", { text: `${id} - validation failed; placement restored to on-prem` })));
  }
}

/* ------------------------------------------------------- opportunities etc */
function renderOpportunities(opps) {
  const list = $("#opps-list");
  list.replaceChildren();
  for (const o of opps.slice(0, 25)) {
    list.append(el("li", { class: `o-${o.impact}` },
      el("b", { text: o.title }), el("br"),
      el("span", { text: `${o.application_id} - ${o.effort} effort - ${o.description}` })));
  }
  if (!opps.length) list.append(el("li", { text: "no opportunities recorded yet" }));
}

function renderRisks(risks) {
  const list = $("#risks-list");
  list.replaceChildren();
  for (const r of risks.slice(0, 25)) {
    list.append(el("li", { class: r.severity_score >= 3.5 ? "sev-high" : "sev-med" },
      el("b", { text: `[sev ${r.severity_score}] ${r.category}` }), el("br"),
      el("span", { text: `${r.application_id || "portfolio"}${r.wave_number != null ? ` (wave ${r.wave_number})` : ""}: ${r.mitigation}` })));
  }
  if (!risks.length) list.append(el("li", { text: "no risks recorded yet" }));
}

function renderAudit(events) {
  const list = $("#audit-list");
  list.replaceChildren();
  for (const e of events.slice(0, 40)) {
    const ts = (e.ts || "").replace("T", " ").slice(0, 19);
    list.append(el("li", {},
      el("b", { text: e.event_type }), ` ${e.subject} - ${ts}`));
  }
  if (!events.length) list.append(el("li", { text: "audit trail empty" }));
}

/* --------------------------------------------------------- target architecture */
async function loadTargetArch() {
  const appId = $("#ta-app").value;
  const provider = $("#ta-provider").value;
  const wantYaml = $("#ta-yaml").checked;
  const out = $("#ta-output");
  if (!appId) { out.textContent = "// no application selected"; return; }
  const fmt = wantYaml ? "yaml" : "json";
  const data = await api(
    `/target-architecture/${appId}?provider=${provider}&format=${fmt}`);
  if (!ok(data)) {
    out.textContent = `// unavailable (${data.__error}): ${data.detail || ""}`;
    return;
  }
  if (wantYaml) { out.textContent = typeof data === "string" ? data : data.yaml || ""; }
  else out.textContent = JSON.stringify(data.spec ?? data, null, 2);
}

/* ----------------------------------------------------------- app selection */
function selectApp(appId) {
  state.selectedApp = appId;
  $("#agentic-app").value = appId;
  $("#ta-app").value = appId;
  loadTargetArch();
  loadChecklistDetail(appId);
}

async function loadChecklistDetail(appId) {
  // checklist items come from the detail endpoint's readiness rows
  const data = await api(`/applications/${appId}`);
  if (!ok(data)) { renderAgenticItems(null); return; }
  const items = data.agentic_items || [];
  renderAgenticItems(items, items.filter((i) => i.passed).length,
                     data.readiness_band || "");
}

/* --------------------------------------------------------------- selectors */
function rebuildSelectors() {
  // strategy filter options
  const strategies = [...new Set(state.portfolio.map((a) => a.strategy)
                                   .filter(Boolean))].sort();
  const stratSel = $("#f-strategy");
  const currentStrat = stratSel.value;
  stratSel.replaceChildren(el("option", { value: "", text: "strategy: all" }),
    ...strategies.map((s) => el("option", { value: s, text: s })));
  stratSel.value = currentStrat;

  const runtimes = [...new Set(state.portfolio.map((a) => a.runtime_id))
                     .values()].sort();
  const rtSel = $("#f-runtime");
  const currentRt = rtSel.value;
  rtSel.replaceChildren(el("option", { value: "", text: "runtime: all" }),
    ...runtimes.map((r) => el("option", { value: r, text: r })));
  rtSel.value = currentRt;

  const domains = [...new Set(state.portfolio.map((a) => a.domain))].sort();
  $("#graph-domain").replaceChildren(
    el("option", { value: "", text: "domain: all" }),
    ...domains.map((d) => el("option", { value: d, text: d })));

  const names = state.portfolio.map((a) => [a.id, a.name]);
  $("#agentic-app").replaceChildren(...names.map(([id, name]) =>
    el("option", { value: id, text: name })));
  $("#ta-app").replaceChildren(...names.map(([id, name]) =>
    el("option", { value: id, text: `${name}` })));
  $("#agentic-app").value = state.selectedApp;
  $("#ta-app").value = state.selectedApp;
}

/* ------------------------------------------------------------------- wiring */
function wireControls() {
  $("#btn-seed").addEventListener("click", async () => {
    busy(true, "seeding estate...");
    await api("/simulator/seed", { method: "POST", body: JSON.stringify({ size: 120 }) });
    busy(false);
    await refreshAll();
  });

  $("#btn-pipeline").addEventListener("click", async () => {
    busy(true, "running agent pipeline...");
    const out = await api("/pipeline/run", { method: "POST" });
    busy(false);
    if (!ok(out)) alert(`pipeline failed (${out.__error}): ${out.detail || ""}`);
    await refreshAll();
  });

  for (const id of ["f-q", "f-strategy", "f-band", "f-runtime", "f-sort"]) {
    $(`#${id}`).addEventListener(id === "f-q" ? "input" : "change", loadPortfolio);
  }
  $("#graph-domain").addEventListener("change", async () => {
    const g = await api("/graph");
    renderGraph(ok(g) ? g : { nodes: [], edges: [] });
  });
  $("#graph-hidden-only").addEventListener("change", async () => {
    const g = await api("/graph");
    renderGraph(ok(g) ? g : { nodes: [], edges: [] });
  });
  $("#agentic-app").addEventListener("change", (e) => loadChecklistDetail(e.target.value));
  for (const id of ["ta-provider", "ta-yaml"]) {
    $(`#${id}`).addEventListener("change", loadTargetArch);
  }
}

wireControls();
refreshAll().then(loadTargetArch);
