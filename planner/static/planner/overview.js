"use strict";
/* Workflow strip, Overview dashboard, LLD CAD view and splicing schematic.
   Loaded after app.js and drawn from the same project data (S.D, S.st) as every deliverable. */

const TAB_STEP = { data: 1, map: 3, materials: 4, lld: 5, schedules: 6, splicing: 6, report: 6, outputs: 6, qa: 7 };
const SVGNS = "http://www.w3.org/2000/svg";
const DRAW_ORDER = { existing: 0, main: 1, spur: 2, drop: 3 };  // thinner spurs on top, so cables sharing a route all show
const byDrawOrder = (cables) => [...cables].sort((a, b) =>
  DRAW_ORDER[a.status === "existing" ? "existing" : a.kind] - DRAW_ORDER[b.status === "existing" ? "existing" : b.kind]);

// ---------------------------------------------------------------------------
// Navigation and downloads
// ---------------------------------------------------------------------------
function showTab(tab, anchor) {
  const b = $(`#tabs [data-tab="${tab}"]`);
  if (b) b.click();
  if (anchor) setTimeout(() => document.getElementById(anchor)?.scrollIntoView({ behavior: "smooth", block: "start" }), 120);
}
$$("#steps > li").forEach((li) => li.addEventListener("click", () => showTab(li.dataset.go, li.dataset.anchor)));
document.addEventListener("click", (e) => {
  const go = e.target.closest("button[data-go]");
  if (go) { showTab(go.dataset.go); return; }
  const a = e.target.closest("a[data-dl]");
  if (a && a.dataset.dl && !a.closest("#outputs")) { e.preventDefault(); download(a.dataset.dl); }
});
async function download(spec) {
  if (!S.pid) return toast("Open a project first");
  await flush();
  window.location = `/api/projects/${S.pid}/export/${spec}`;
  setTimeout(refreshState, 2500);
}

// ---------------------------------------------------------------------------
// Workflow strip: live status of each stage
// ---------------------------------------------------------------------------
function renderSteps() {
  const st = S.st, D = S.D;
  const t = activeTab();
  document.body.classList.toggle("ov", t === "overview");
  $$("#steps > li").forEach((li) => li.classList.toggle("on", +li.dataset.step === TAB_STEP[t]));
  if (!st || !D) return;
  const s = st.summary, c = st.counts;
  const set = (n, text, cls = "") => { const el = $("#st" + n); el.textContent = text; el.className = "sstat " + cls; };
  const surveyErr = st.issues.filter((i) => i.severity === "error" && SURVEY_CODES.includes(i.code)).length;
  const surveyed = D.poles.length + D.homes.length;
  const sec = st.sector, fib = !sec || sec.fibre_tools;  // the step texts in the sector's words
  const w = fib ? { poles: "poles", hps: "HPs", lines: "cables", fats: "FATs" }
    : { poles: sec.support.toLowerCase() + "s", hps: sec.unit, lines: sec.line.toLowerCase() + "s",
        fats: sec.kinds.FAT.split("/")[0].trim().toLowerCase() + "s" };
  set(1, surveyed ? `${s.poles} ${w.poles} · ${s.homes} premises · ${s.homepasses} ${w.hps}` : "No survey data yet", surveyed ? "ok" : "warn");
  set(2, surveyErr ? `${surveyErr} survey error(s) to fix` : D.info.survey_status === "approved" ? "Survey approved ✓"
    : surveyed ? "Clean - ready to approve" : "Waiting for survey data", surveyErr ? "err" : D.info.survey_status === "approved" ? "ok" : "warn");
  const prop = D.cables.filter((x) => x.status === "proposed").length;
  set(3, prop ? `${prop} ${w.lines} · ${s.nodes.FAT} ${w.fats} · ${s.homes_unassigned} unserved` : "No proposed network yet",
    prop ? (s.homes_unassigned ? "warn" : "ok") : "");
  set(4, `${D.materials.length} items · ${s.currency} ${fmt(s.boq_total)}`, D.materials.length ? "ok" : "warn");
  const o = st.outputs || {}, lld = o.lld;
  set(5, !lld?.last ? "DXF / PDF not generated yet" : lld.stale ? "Needs regenerating" : "DXF / PDF up to date",
    !lld?.last ? "" : lld.stale ? "warn" : "ok");
  if (sec?.construction) {  // a building, not a network: the site, the design and its plans
    const b = D.building, walls = b?.walls?.length || 0, plans = o.plans;
    set(1, D.info.boundary.length ? `Plot boundary drawn${b?.origin ? " · building placed" : ""}` : "No plot boundary yet (Site plan)",
      D.info.boundary.length ? "ok" : "warn");
    set(2, c.errors ? `${c.errors} error(s) to fix` : walls ? "Clean" : "Waiting for the design", c.errors ? "err" : walls ? "ok" : "warn");
    set(3, walls ? `${b.levels.length} floor(s) · ${walls} walls · ${b.openings.length} doors & windows` : "No building yet", walls ? "ok" : "");
    set(5, !plans?.last ? "Plans PDF not generated yet" : plans.stale ? "Needs regenerating" : "Plans up to date",
      !plans?.last ? "" : plans.stale ? "warn" : "ok");
  }
  const keys = Object.keys(o), ok = keys.filter((k) => o[k].last && !o[k].stale).length;
  set(6, `${ok} of ${keys.length} deliverables up to date`, ok === keys.length ? "ok" : ok ? "warn" : "");
  const ds = D.info.design_status;
  set(7, ds === "approved" ? "Design approved ✓" : `${ds.replace("_", " ")} · ${c.errors} errors · ${c.warnings} warnings`,
    ds === "approved" ? "ok" : c.errors ? "err" : "warn");
}

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------
// map legend in the project's sector terms (fibre: main cable, FAT...; water: trunk main, meter...)
function legend() {
  const t = S.st?.sector;
  if (!t) return [["main", "Main cable (48C)", ""], ["spur", "Spur cable (12C)", ""], ["drop", "Drop", ""], ["pole", "Pole", "pt"],
    ["home", "Home / MDU", "sq"], ["ENCLOSURE", "Splice enclosure", "sq"], ["JB", "JB", "sq"], ["FAT", "FAT", "sq"], ["PON", "PON", "sq"]];
  return [["main", t.lines.main, ""], ["spur", t.lines.spur, ""], ["drop", t.lines.drop, ""], ["pole", t.support, "pt"],
    ["home", t.premise, "sq"], ["ENCLOSURE", t.kinds.ENCLOSURE, "sq"], ["JB", t.kinds.JB, "sq"], ["FAT", t.kinds.FAT, "sq"],
    ["PON", t.kinds.PON, "sq"]];
}
let ovMap = null, ovLayer = null;

async function renderOverview() {
  if (!S.D) return;
  drawOvMap();
  drawLld($("#ovLld"), false);
  if (typeof renderOvBuilding === "function") renderOvBuilding();
  renderOvReport();
  renderFileIcons();
  $("#ovLegend").innerHTML = legend().map(([k, t, cls]) => `<span><i class="${cls}" style="background:${COL[k]}"></i>${t}</span>`).join("") +
    `<span><i style="background:#9aa5b1"></i>Existing</span>`;
  await flush();
  const [c, sp] = await Promise.all([fresh("ovcalc", () => api(`/api/projects/${S.pid}/calc`)),
                                     fresh("ovsplice", () => api(`/api/projects/${S.pid}/splicing`))]);
  if (c) renderOvTables(c);
  if (sp) spliceSchematic(sp, $("#ovSplice"), $("#ovPon"));
}

function drawOvMap() {
  if (!ovMap) {
    ovMap = L.map("ovMap", { zoomControl: false, scrollWheelZoom: false });
    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      { ...TILE, attribution: "Imagery © Esri" }).addTo(ovMap);
    L.control.zoom({ position: "topright" }).addTo(ovMap);
    ovLayer = L.layerGroup().addTo(ovMap);
  }
  ovMap.invalidateSize();
  ovLayer.clearLayers();
  const D = S.D, fit = [];
  if (D.info.boundary.length) {
    L.polygon(D.info.boundary, { color: "#fff", weight: 1.5, dashArray: "6 4", fill: false, interactive: false }).addTo(ovLayer);
    fit.push(...D.info.boundary);
  }
  for (const c of byDrawOrder(D.cables)) {
    const ll = c.path.map((v) => [v.lat, v.lon]);
    if (ll.length < 2) continue;
    L.polyline(ll, { color: c.status === "existing" ? "#9aa5b1" : COL[c.kind], weight: c.kind === "main" ? 5 : 2.5, opacity: .95,
                     interactive: false }).addTo(ovLayer);
    if (c.status === "proposed") fit.push(...ll);
  }
  for (const p of D.poles) if (okc(p)) L.circleMarker([p.lat, p.lon], { radius: 3, color: "#fff", weight: 1, fillColor: COL.pole, fillOpacity: 1, interactive: false }).addTo(ovLayer);
  for (const h of D.homes) if (okc(h)) { L.marker([h.lat, h.lon], { icon: icon("home", h), interactive: false }).addTo(ovLayer); fit.push([h.lat, h.lon]); }
  for (const n of D.nodes) {
    if (!okc(n)) continue;
    const m = L.marker([n.lat, n.lon], { icon: icon("node", n), interactive: false }).addTo(ovLayer);
    if (n.kind === "POP" || (n.status === "existing" && n.kind !== "SLACK")) m.bindTooltip(esc(n.id), { permanent: true, direction: "right", className: "lbl" });
    fit.push([n.lat, n.lon]);
  }
  if (!fit.length) fit.push(...D.poles.filter(okc).map((p) => [p.lat, p.lon]));
  if (fit.length) ovMap.fitBounds(fit, { padding: [16, 16], maxZoom: 18 });
  else ovMap.setView(map.getCenter(), 15);
}

function tableHtml(head, rows, totalRow, more) {
  return `<table><tr>${head.map((h) => `<th${h.num ? ' class="num"' : ""}>${h.t}</th>`).join("")}</tr>` +
    rows.map((r) => `<tr>${r.map((v, i) => `<td${head[i].num ? ' class="num"' : ""}>${v}</td>`).join("")}</tr>`).join("") +
    (totalRow ? `<tr class="total">${totalRow.map((v, i) => `<td${head[i].num ? ' class="num"' : ""}>${v}</td>`).join("")}</tr>` : "") +
    `</table>` + (more > 0 ? `<div class="more">+ ${more} more - open the full schedule</div>` : "");
}

function renderOvTables(c) {
  const P = c.poles, N = 8, sum = (k) => P.reduce((a, p) => a + (Array.isArray(p[k]) ? p[k].length : p[k]), 0);
  const H = (t, num) => ({ t, num });
  const t = S.st?.sector;
  if (t && !t.fibre_tools) {  // the sector's support schedule: its hardware and equipment columns
    const cols = t.schedule;
    $("#ovPoles").innerHTML = P.length ? tableHtml(
      [H(`${esc(t.support)} ID`), H("Location (Lat, Long)"), H(`${esc(t.line)}s`, 1), ...cols.map(([, h]) => H(esc(h), 1)), H("Notes")],
      P.slice(0, N).map((p) => [esc(p.pole), p.lat != null ? `${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}` : "-", p.cables.length,
                                ...cols.map(([k]) => p[k]), esc(p.notes.join("; "))]),
      ["Total", "", sum("cables"), ...cols.map(([k]) => sum(k)), "-"], P.length - N)
      : `<p class="muted" style="padding:10px">No ${esc(t.support.toLowerCase())}s on the proposed route yet.</p>`;
  } else $("#ovPoles").innerHTML = P.length ? tableHtml(
    [H("Pole ID"), H("Location (Lat, Long)"), H("Cables", 1), H("J-Hook", 1), H("Tension", 1), H("UPB", 1), H("JB", 1), H("Encl.", 1), H("Notes")],
    P.slice(0, N).map((p) => [esc(p.pole), p.lat != null ? `${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}` : "-", p.cables.length, p.jhooks,
                              p.tension, p.upb, p.jb, p.enclosures, esc(p.notes.join("; "))]),
    ["Total", "", sum("cables"), sum("jhooks"), sum("tension"), sum("upb"), sum("jb"), sum("enclosures"), "-"], P.length - N)
    : `<p class="muted" style="padding:10px">No poles on the proposed route yet.</p>`;
  const B = c.bom, NB = 13;
  $("#ovBom").innerHTML = tableHtml([H("Item"), H("Description"), H("Unit"), H("Quantity", 1)],
    B.slice(0, NB).map((l, i) => [i + 1, esc(l.description), esc(l.unit), fmt(l.qty)]), null, B.length - NB);
  $("#ovBoq").innerHTML = tableHtml([H("Description"), H("Unit"), H("Qty", 1), H(`Rate (${esc(c.currency)})`, 1), H(`Total (${esc(c.currency)})`, 1)],
    B.slice(0, 10).map((l) => [esc(l.description), esc(l.unit), fmt(l.qty), l.rate == null ? "n/a" : fmt(l.rate, 2), l.total == null ? "n/a" : fmt(l.total, 2)]),
    ["Total", "", "", "", fmt(c.boq_total, 2)], B.length - 10);
}

function renderOvReport() {
  const i = S.D.info, D = S.D;
  const photo = D.photos[0];
  const secs = S.st?.sector?.construction  // the sections of the building report (ftth/exporters/report.py)
    ? [["Introduction", i.introduction], ["The building", D.building?.walls?.length], ["Bill of quantities", D.building?.walls?.length],
       ["Quality checks & recommendations", i.recommendations]]
    : [["Introduction", i.introduction], ["Survey findings", i.findings], ["Proposed solution", i.proposed_solution],
       ["Cable routing & installation", D.cables.some((c) => c.status === "proposed")], ["Equipment locations", D.nodes.length],
       ["Special requirements", i.special_requirements], ["Conclusion & recommendations", i.recommendations]];
  const title = S.st?.sector && !S.st.sector.fibre_tools ? S.st.sector.report_title : "FTTH Survey Report";
  $("#ovReport").innerHTML = `<h4>${esc(title.toUpperCase())}</h4><div class="sub">${esc(i.area || i.name)}</div>` +
    (photo ? `<img src="/api/projects/${S.pid}/photos/${esc(photo.file)}" alt="${esc(photo.caption)}">` : "") +
    `<ol>${secs.map(([t, v]) => `<li class="${v ? "" : "no"}">${t}</li>`).join("")}</ol>` +
    `<p class="muted">Photos: ${D.photos.length} · Prepared by: ${esc(i.prepared_by || "-")} · Date: ${esc(i.survey_date || "-")}</p>`;
}

const FILES = [["HLD", "KML", "hld.kmz", "#2e7d32", "hld"], ["LLD", "DXF", "lld.dxf", "#1565c0", "lld"],
  ["Pole Summary", "XLS", "pole_summary.xlsx", "#217346", "pole_summary"], ["BOM", "XLS", "bom.xlsx", "#217346", "bom"],
  ["BOQ", "XLS", "boq.xlsx", "#217346", "boq"], ["Splicing Diagram", "PDF", "splicing.pdf", "#c62828", "splicing"],
  ["Survey Report", "DOC", "report.docx", "#2b579a", "report"], ["QA Report", "PDF", "qa.pdf", "#c62828", "qa"]];
function renderFileIcons() {
  const o = S.st?.outputs || {};
  let fresh = 0;
  const t = S.st?.sector;
  const files = t?.construction  // construction: plans instead of the network drawings
    ? [["Plans & Elevations", "PDF", "plans.pdf", "#c62828", "plans"], ...FILES.filter((f) => ["bom", "boq", "report", "qa"].includes(f[4]))]
    : t && !t.fibre_tools  // other sectors: no splicing diagram; the pole summary is their schedule
    ? FILES.filter((f) => f[4] !== "splicing").map((f) => f[4] === "pole_summary" ? [`${t.support} Schedule`, ...f.slice(1)] : f)
    : FILES;
  $("#fileIcons").innerHTML = files.map(([t, tag, spec, col, k]) => {
    const x = o[k], state = !x?.last ? "" : x.stale ? "stale" : "fresh";
    const tip = !x?.last ? "Not generated" : x.stale ? "Needs regenerating" : "Up to date";
    if (state === "fresh") fresh++;
    return `<a class="fileico ${state}" data-dl="${spec}" href="#" title="Download ${esc(t)} (${tag}) - ${tip.toLowerCase()}">
      <span class="doc"><span class="tag" style="background:${col}">${tag}</span></span>
      <span class="fname">${esc(t)}</span><span class="fstate"><span class="dot ${state}"></span>${tip}</span></a>`;
  }).join("");
  $("#fileProgress").textContent = `${fresh} of ${files.length} up to date`;
}
$("#cdbPackage").addEventListener("click", () => $("#btnPackage").click());

// ---------------------------------------------------------------------------
// LLD CAD view: black sheet, CAD colours, legend and title block
// ---------------------------------------------------------------------------
function projector(D) {
  const pts = [...D.poles, ...D.homes, ...D.nodes].filter(okc).map((x) => [x.lat, x.lon])
    .concat(D.cables.filter((c) => c.status === "proposed").flatMap((c) => c.path.map((v) => [v.lat, v.lon])), D.info.boundary);
  if (!pts.length) return null;
  const lat0 = pts.reduce((a, p) => a + p[0], 0) / pts.length, lon0 = pts.reduce((a, p) => a + p[1], 0) / pts.length;
  // metres per degree on the same sphere as hav(), so lengths, measurements and rotations agree with the BOQ
  const m = 6371008.8 * Math.PI / 180, kx = Math.cos(lat0 * Math.PI / 180) * m, ky = m;
  const xy = (lat, lon) => [(lon - lon0) * kx, -(lat - lat0) * ky];
  // drawing extent: the proposed network, premises and boundary (existing cables may run far beyond the project)
  const ext = D.nodes.concat(D.homes).filter(okc).map((x) => xy(x.lat, x.lon))
    .concat(D.cables.filter((c) => c.status === "proposed").flatMap((c) => c.path.map((v) => xy(v.lat, v.lon))), D.info.boundary.map((b) => xy(b[0], b[1])));
  const use = ext.length ? ext : pts.map((p) => xy(p[0], p[1]));
  const xs = use.map((p) => p[0]), ys = use.map((p) => p[1]);
  const box = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  return { xy, box, inverse: (x, y) => [lat0 - y / ky, lon0 + x / kx] };
}

function el(tag, attrs, parent) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}

const CAD_LAYERS = [["boundary", "Project boundary"], ["drops", "Drop links"], ["existing", "Existing cables"], ["main", "48C main cables"],
  ["spur", "12C spur cables"], ["buildings", "Buildings / premises"], ["poles", "Poles"], ["equipment", "Equipment"],
  ["labels", "Equipment labels"], ["tags", "Cable tags"], ["markup", "Drafting (markups)"], ["grid", "Grid"]];
const CAD = { home: null, vb: null, tool: null, meas: [], proj: null, pid: null, feats: { pts: [], lines: [] }, sel: [], op: null };

function drawLld(box, big) {
  const D = S.D;
  const P = typeof PREFS !== "undefined" ? PREFS : { cad_dark: true, cad_grid: false, cad_text: 1, cad_off: [] };
  box.innerHTML = "";
  box.classList.toggle("light", big && !P.cad_dark);
  const pr = projector(D);
  if (!pr) { box.innerHTML = `<p class="muted" style="padding:12px;color:#8b98a8">No mapped features yet.</p>`; return; }
  const { xy } = pr;
  let [x0, y0, x1, y1] = pr.box;
  const span = Math.max(x1 - x0, y1 - y0, 60), pad = span * 0.06;
  x0 -= pad; y0 -= pad; x1 += pad; y1 += pad;
  const svg = el("svg", { xmlns: SVGNS, viewBox: `${x0} ${y0} ${x1 - x0} ${y1 - y0}`, preserveAspectRatio: "xMidYMid meet" }, box);
  const dark = !big || P.cad_dark, fg = dark ? "#e6edf3" : "#111";
  el("rect", { x: x0 - span * 5, y: y0 - span * 5, width: span * 11, height: span * 11, fill: dark ? "#000" : "#fff" }, svg);
  if (big) el("g", { id: "cadBasemap" }, svg);  // map tiles under the drawing (drawBasemap)
  const r = span / (big ? 320 : 200), stroke = (w) => ({ "stroke-width": w, "vector-effect": "non-scaling-stroke", fill: "none" });
  // where each feature is drawn, for picking and snapping in the drawing tab
  const feats = { pts: [], lines: [] };
  const layer = (name) => el("g", { "data-layer": name, ...(big && P.cad_off.includes(name) ? { display: "none" } : {}) }, svg);
  const Lg = Object.fromEntries(CAD_LAYERS.map(([k]) => [k, null]));
  // grid: 10 m / 50 m lines like a CAD model-space grid
  Lg.grid = layer("grid");
  if (big && !P.cad_grid) Lg.grid.setAttribute("display", "none");
  const step = span > 1500 ? 100 : 50;
  for (let gx = Math.floor((x0 - span) / step) * step; gx < x1 + span; gx += step)
    el("line", { x1: gx, y1: y0 - span, x2: gx, y2: y1 + span, stroke: dark ? "#1d2a36" : "#e3e8ee", ...stroke(0.6) }, Lg.grid);
  for (let gy = Math.floor((y0 - span) / step) * step; gy < y1 + span; gy += step)
    el("line", { x1: x0 - span, y1: gy, x2: x1 + span, y2: gy, stroke: dark ? "#1d2a36" : "#e3e8ee", ...stroke(0.6) }, Lg.grid);
  for (const k of ["boundary", "drops", "existing", "main", "spur", "buildings", "poles", "equipment", "markup", "labels", "tags"]) Lg[k] = layer(k);
  if (D.info.boundary.length) el("polygon", { points: D.info.boundary.map((b) => xy(b[0], b[1]).join(",")).join(" "), stroke: dark ? "#cfd8dc" : "#555", "stroke-dasharray": "6 4", ...stroke(1) }, Lg.boundary);
  const fats = Object.fromEntries(D.nodes.filter((n) => n.kind === "FAT").map((n) => [n.id, n]));
  for (const h of D.homes) {
    const f = fats[h.fat];
    if (f && okc(h) && okc(f)) { const a = xy(h.lat, h.lon), b = xy(f.lat, f.lon); el("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], stroke: "#5e6b78", "stroke-dasharray": "3 3", ...stroke(0.8) }, Lg.drops); }
  }
  const lab = labelPlacer(r * 12);
  for (const c of byDrawOrder(D.cables)) {
    if (c.path.length < 2) continue;
    const lay = c.status === "existing" ? Lg.existing : c.kind === "main" ? Lg.main : Lg.spur;
    const pts = c.path.map((v) => xy(v.lat, v.lon));
    el("polyline", { points: pts.map((p) => p.join(",")).join(" "),
      stroke: c.status === "existing" ? "#7d8a96" : c.kind === "main" ? "#ff2a2a" : c.kind === "spur" ? (dark ? "#ffd60a" : "#d4a300") : "#3ddc84",
      ...stroke(c.status === "existing" ? 1.2 : c.kind === "main" ? 3.4 : 1.6) }, lay);
    lab.line(pts, r * 1.5);
    feats.lines.push({ id: c.id, pts });
  }
  for (const h of D.homes) {
    if (!okc(h)) continue;
    const [x, y] = xy(h.lat, h.lon), s = r * (h.kind === "mdu" ? 2.6 : 1.6);
    el("rect", { x: x - s, y: y - s * 0.7, width: 2 * s, height: 1.4 * s, stroke: "#e040fb", ...stroke(1) }, Lg.buildings);
    lab.block(x, y, s);
    feats.pts.push({ type: "home", id: h.id, x, y, rank: 2 });
  }
  for (const p of D.poles) {
    if (!okc(p)) continue;
    const [x, y] = xy(p.lat, p.lon);
    el("circle", { cx: x, cy: y, r: r * 0.9, fill: "#2f80ff", stroke: p.status === "proposed" ? fg : "none", "stroke-width": 1, "vector-effect": "non-scaling-stroke" }, Lg.poles);
    lab.block(x, y, r * 0.9);
    feats.pts.push({ type: "pole", id: p.id, x, y, rank: 1 });
  }
  const ts = r * (big ? 2.4 : 3.2) * (big ? P.cad_text : 1);
  Lg.labels.setAttribute("font-family", "Arial, sans-serif"); Lg.labels.setAttribute("font-size", ts); Lg.labels.setAttribute("fill", fg);
  const placed = [], toLabel = [];
  for (const n of D.nodes) {
    if (!okc(n)) continue;
    const [x0, y0] = xy(n.lat, n.lon), s = r * 2.2;
    let x = x0, y = y0;
    while (placed.some(([px, py]) => Math.abs(px - x) < s * 1.6 && Math.abs(py - y) < s * 1.6)) y += s * 2.3;  // same pole: stack
    if (y !== y0) el("line", { x1: x0, y1: y0, x2: x, y2: y, stroke: fg, ...stroke(0.6) }, Lg.equipment);
    placed.push([x, y]);
    lab.block(x, y, s);
    feats.pts.push({ type: "node", id: n.id, x, y, rank: 0, true: [x0, y0] });
    const col = { FAT: "#ff2a2a", JB: "#c77dff", ENCLOSURE: "#ff9f1c", PR_ENCLOSURE: "#ff9f1c", PON: "#ff4fd8", POP: "#a06cd5", SLACK: "#3ddc84" }[n.kind];
    const g = Lg.equipment;
    if (n.kind === "FAT") el("polygon", { points: `${x},${y - s} ${x + s},${y + s * 0.8} ${x - s},${y + s * 0.8}`, fill: col }, g);
    else if (n.kind === "JB") el("polygon", { points: `${x},${y - s} ${x + s},${y} ${x},${y + s} ${x - s},${y}`, fill: col }, g);
    else if (n.kind === "PON") el("polygon", { points: star(x, y, s * 1.2, s * 0.5), fill: col }, g);
    else if (n.kind === "SLACK") el("circle", { cx: x, cy: y, r: s * 0.8, stroke: col, ...stroke(1.5) }, g);
    else el("rect", { x: x - s * 0.9, y: y - s * 0.9, width: s * 1.8, height: s * 1.8, fill: col }, g);
    if (big || ["POP", "PON", "ENCLOSURE"].includes(n.kind)) toLabel.push([n, x, y, s]);
  }
  feats.marks = drawMarkups(D, xy, Lg.markup, r, lab);
  const text = (layer, pos, attrs, content) => {
    if (pos.leader) { const [a, b, c2, d2] = pos.leader; el("line", { x1: a, y1: b, x2: c2, y2: d2, stroke: attrs.fill || fg, ...stroke(0.5) }, layer); }
    el("text", { x: pos.x, y: pos.y, ...attrs }, layer).textContent = content;
  };
  for (const [n, x, y, s] of toLabel) text(Lg.labels, lab.place(n.id, ts, s, [[x, y]]), {}, n.id);
  if (big) {
    Lg.tags.setAttribute("font-family", "Arial, sans-serif");
    const tsz = r * 2 * P.cad_text;
    for (const c of D.cables) {  // cable tags: the free-most segment midpoint, starting from mid-route
      if (c.status !== "proposed" || c.path.length < 2) continue;
      const pts = c.path.map((v) => xy(v.lat, v.lon));
      const mids = pts.slice(1).map((p, k) => [(p[0] + pts[k][0]) / 2, (p[1] + pts[k][1]) / 2]), m = Math.floor(mids.length / 2);
      const order = mids.map((_, k) => k).sort((a, b) => Math.abs(a - m) - Math.abs(b - m)).map((k) => mids[k]);
      const label = `${c.id} ${c.cores}C`;
      text(Lg.tags, lab.place(label, tsz, r * 0.8, order),
        { fill: c.kind === "main" ? "#ff6b6b" : (dark ? "#ffe680" : "#9a7400"), "font-size": tsz }, label);
    }
  }
  if (big) { el("g", { id: "cadSel" }, svg); el("g", { id: "cadPreview" }, svg); }  // selection and edit previews
  el("g", { id: big ? "cadOverlay" : "", "font-family": "Arial, sans-serif" }, svg);
  // legend and title block stay the same size at any zoom
  const leg = document.createElement("div");
  leg.className = "lldleg";
  const t = S.st?.sector, fibre = !t || t.fibre_tools;
  leg.innerHTML = `<b>LEGEND</b>` + [["#ff2a2a", fibre ? "48C main cable" : t.lines.main, "l"], ["#ffd60a", fibre ? "12C spur cable" : t.lines.spur, "l"],
    ["#7d8a96", fibre ? "Existing cable" : `Existing ${t.line.toLowerCase()}`, "l"],
    ["#2f80ff", fibre ? "Pole" : t.support, "c"], ["#ff2a2a", fibre ? "FAT" : t.kinds.FAT, "t"], ["#c77dff", fibre ? "JB" : t.kinds.JB, "d"],
    ["#ff9f1c", fibre ? "Splice enclosure" : t.kinds.ENCLOSURE, "s"], ["#ff4fd8", fibre ? "PON" : t.kinds.PON, "s"],
    ["#e040fb", fibre ? "Building" : t.premise, "b"]].map(([c, t, k]) => `<div><i class="${k}" style="--c:${c}"></i>${t}</div>`).join("");
  box.appendChild(leg);
  const tb = document.createElement("div");
  tb.className = "lldtb";
  const i = D.info;
  tb.innerHTML = `<b>${fibre ? "FTTH LLD" : "DETAILED DESIGN"}</b><div>${esc((i.area || i.name || "").toUpperCase())}</div><div>${esc(i.company || "")} ${esc(i.drawing_no || "")}</div>
    <div>REV ${S.st?.revision ?? 0} · ${esc(i.design_status.toUpperCase())}</div><div class="cad">AutoCAD · DXF</div>`;
  box.appendChild(tb);
  if (big) {
    CAD.proj = pr; CAD.feats = feats; CAD.r = r;
    const attr = document.createElement("div");
    attr.className = "cadattr";
    attr.id = "cadAttr";
    box.appendChild(attr);
    cadTools(svg);
  }
}

// Label placement for the drawing (same rules as the PDF and DXF, ftth/exporters/labels.py): try around
// the point (right, left, below, above, diagonals), then further out with a leader line; symbols, other labels
// and (less strongly) cable lines are avoided. Units are drawing metres; y grows downwards.
function labelPlacer(cell) {
  const grid = new Map();
  const cells = (b, f) => { for (let i = Math.floor(b[0] / cell); i <= Math.floor(b[2] / cell); i++) for (let j = Math.floor(b[1] / cell); j <= Math.floor(b[3] / cell); j++) f(i + "," + j); };
  const add = (b, wt = 1) => { const o = [b, wt]; cells(b, (k) => { if (!grid.has(k)) grid.set(k, []); grid.get(k).push(o); }); };
  const cost = (b) => {
    let c = 0; const seen = new Set();
    cells(b, (k) => (grid.get(k) || []).forEach((o) => {
      if (seen.has(o)) return; seen.add(o);
      const [q, wt] = o, ix = Math.min(b[2], q[2]) - Math.max(b[0], q[0]), iy = Math.min(b[3], q[3]) - Math.max(b[1], q[1]);
      if (ix > 0 && iy > 0) c += ix * iy * wt;
    }));
    return c;
  };
  const DIRS = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]];
  return {
    block: (x, y, r) => add([x - r, y - r, x + r, y + r]),
    line: (pts, step) => pts.forEach((a, k) => {
      if (!k) return;
      const b = pts[k - 1], n = Math.max(1, Math.floor(Math.hypot(a[0] - b[0], a[1] - b[1]) / step));
      for (let t = 0; t <= n; t++) { const x = b[0] + (a[0] - b[0]) * t / n, y = b[1] + (a[1] - b[1]) * t / n; add([x - step / 4, y - step / 4, x + step / 4, y + step / 4], 0.3); }
    }),
    // returns {x, y (baseline), leader: [x1, y1, x2, y2] | null}
    place(text, size, r, anchors) {
      const w = text.length * size * 0.58, h = size, free = size * size * 0.05;
      let best = null;
      for (let ring = 0; ring < 3 && !(best && best.c < free); ring++) {
        const dist = r + size * 0.25 + ring * (h + size * 0.5);
        for (const [ax, ay] of anchors) {
          for (const [ux, uy] of DIRS) {
            const left = ux > 0 ? ax + dist * ux : ux < 0 ? ax + dist * ux - w : ax - w / 2;
            const top = uy > 0 ? ay + dist * uy : uy < 0 ? ay + dist * uy - h : ay - h / 2;
            const b = [left, top, left + w, top + h], c = cost(b) + ring * 1e-6;
            if (!best || c < best.c) best = { c, b, ring, ax, ay };
          }
          if (best.c < free) break;
        }
      }
      add(best.b);
      const [l, t, rr, bt] = best.b;
      return { x: l, y: bt - h * 0.18, leader: best.ring ? [best.ax, best.ay, Math.min(Math.max(best.ax, l), rr), Math.min(Math.max(best.ay, t), bt)] : null };
    },
  };
}

// The drafting layer (design.markups): lines, polylines, circles, notes, leaders and dimensions in drawing
// metres. Returns their outlines for picking and snapping.
// arc through three points (drawing coordinates): centre, radius and the points along it from a to c;
// the same rules as ftth/exporters/drafting.py arc3 / arc_points
function arc3(a, b, c) {
  const d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]));
  if (Math.abs(d) < 1e-12) return null;
  const s = (p) => p[0] * p[0] + p[1] * p[1];
  const ux = (s(a) * (b[1] - c[1]) + s(b) * (c[1] - a[1]) + s(c) * (a[1] - b[1])) / d;
  const uy = (s(a) * (c[0] - b[0]) + s(b) * (a[0] - c[0]) + s(c) * (b[0] - a[0])) / d;
  const ang = (p) => Math.atan2(p[1] - uy, p[0] - ux), T = 2 * Math.PI, md = (x) => ((x % T) + T) % T;
  const sa = ang(a), sb = ang(b), sc = ang(c), ccw = md(sb - sa) < md(sc - sa);
  const sweep = ccw ? md(sc - sa) : -md(sa - sc);
  return { c: [ux, uy], r: Math.hypot(a[0] - ux, a[1] - uy), start: sa, sweep,
           pts: (n = 32) => Array.from({ length: n + 1 }, (_, k) => [ux + Math.hypot(a[0] - ux, a[1] - uy) * Math.cos(sa + sweep * k / n), uy + Math.hypot(a[0] - ux, a[1] - uy) * Math.sin(sa + sweep * k / n)]) };
}
// dimension lines, text position / angle and value in drawing coordinates (y down); ftth/exporters/drafting.py
function dimGeometry(kind, P, off) {
  const up = (p) => [p[0], -p[1]], ln = (l) => [[l[0], -l[1]], [l[2], -l[3]]];
  const Q = P.map(up);
  let lines = [], t, ang, value;
  const upright = (deg) => { deg = ((deg + 180) % 360 + 360) % 360 - 180; return deg > 90 ? deg - 180 : deg <= -90 ? deg + 180 : deg; };
  if (kind === "radius") {
    const [[cx, cy], [ex, ey]] = Q, a = Math.atan2(ey - cy, ex - cx);
    lines = [[cx, cy, ex, ey]]; value = Math.hypot(ex - cx, ey - cy);
    t = [(cx + ex) / 2 - Math.sin(a) * off * 0.4, (cy + ey) / 2 + Math.cos(a) * off * 0.4]; ang = upright(a * 180 / Math.PI);
  } else if (kind === "angular") {
    const [[ax, ay], [vx, vy], [bx, by]] = Q, T2 = 2 * Math.PI;
    let a1 = Math.atan2(ay - vy, ax - vx), a2 = Math.atan2(by - vy, bx - vx), sw = ((a2 - a1) % T2 + T2) % T2;
    if (sw > Math.PI) { [a1, a2] = [a2, a1]; sw = T2 - sw; }
    const rr = Math.min(Math.hypot(ax - vx, ay - vy), Math.hypot(bx - vx, by - vy)) * 0.6 || off;
    const pts = Array.from({ length: 17 }, (_, k) => [vx + rr * Math.cos(a1 + sw * k / 16), vy + rr * Math.sin(a1 + sw * k / 16)]);
    lines = pts.slice(1).map((p, k) => [pts[k][0], pts[k][1], p[0], p[1]]);
    const mid = a1 + sw / 2;
    t = [vx + (rr + off * 0.5) * Math.cos(mid), vy + (rr + off * 0.5) * Math.sin(mid)]; ang = upright(mid * 180 / Math.PI - 90); value = sw * 180 / Math.PI;
  } else {
    const [[ax, ay], [bx, by]] = Q;
    let d1, d2, a;
    if (kind === "horizontal") { const lv = Math.max(ay, by) + off; d1 = [ax, lv]; d2 = [bx, lv]; value = Math.abs(bx - ax); a = 0; }
    else if (kind === "vertical") { const lv = Math.max(ax, bx) + off; d1 = [lv, ay]; d2 = [lv, by]; value = Math.abs(by - ay); a = 90; }
    else { const r = Math.atan2(by - ay, bx - ax), nx = -Math.sin(r) * off, ny = Math.cos(r) * off; d1 = [ax + nx, ay + ny]; d2 = [bx + nx, by + ny]; value = Math.hypot(bx - ax, by - ay); a = r * 180 / Math.PI; }
    lines = [[ax, ay, d1[0], d1[1]], [bx, by, d2[0], d2[1]], [d1[0], d1[1], d2[0], d2[1]]];
    const tk = (a + 45) * Math.PI / 180, k = off * 0.25;
    for (const [x, y] of [d1, d2]) lines.push([x - k * Math.cos(tk), y - k * Math.sin(tk), x + k * Math.cos(tk), y + k * Math.sin(tk)]);
    const na = (a + 90) * Math.PI / 180;
    t = [(d1[0] + d2[0]) / 2 + Math.cos(na) * off * 0.3, (d1[1] + d2[1]) / 2 + Math.sin(na) * off * 0.3]; ang = upright(a);
  }
  return { lines: lines.map(ln), text: up(t), angle: -ang, value };
}
function dimLabel(m, value) { return m.text || (m.dim === "angular" ? `${value.toFixed(1)}°` : m.dim === "radius" ? `R${value.toFixed(1)} m` : `${value.toFixed(1)} m`); }
function cadLayer(name) { return (S.D.cad_layers || []).find((l) => l.name === name); }
const markupShown = (m) => cadLayer(m.layer || "0")?.visible !== false;
const markupLocked = (m) => !!cadLayer(m.layer || "0")?.locked;

function markupGeometry(m, xy) {
  const P = m.points.map((p) => xy(p[0], p[1]));
  if (m.kind === "arc") {
    const g = arc3(...P), pts = g ? g.pts() : [P[0], P[2]];
    return { P, segs: pts.slice(1).map((p, k) => [pts[k], p]), arc: g, line: pts };
  }
  if (m.kind === "point") return { P, segs: [[P[0], P[0]]] };
  if (m.kind === "circle") {
    const r = Math.hypot(P[1][0] - P[0][0], P[1][1] - P[0][1]);
    return { P, segs: Array.from({ length: 24 }, (_, k) => [0, 1].map((j) => { const a = (k + j) / 24 * 2 * Math.PI; return [P[0][0] + r * Math.cos(a), P[0][1] + r * Math.sin(a)]; })), r };
  }
  const segs = P.slice(1).map((p, k) => [P[k], p]);
  if (m.kind === "polyline" && m.closed && P.length > 2) segs.push([P[P.length - 1], P[0]]);
  if (m.kind === "text") {  // the note's box
    const w = (m.text || "").length * m.size * 0.58, [x, y] = P[0];
    segs.push([[x, y], [x + w, y]], [[x + w, y], [x + w, y - m.size]], [[x + w, y - m.size], [x, y - m.size]], [[x, y - m.size], [x, y]]);
  }
  return { P, segs };
}
function drawMarkups(D, xy, g, r, lab) {
  const out = [];
  const st = (col, w = 1.6) => ({ stroke: col, "stroke-width": w, "vector-effect": "non-scaling-stroke", fill: "none" });
  for (const m of D.markups || []) {
    if (!markupShown(m)) continue;  // hidden drafting layer
    const geo = markupGeometry(m, xy), { P, segs, r: rad } = geo, col = m.colour || "#00e5ff";
    const fill = m.fill ? { fill: m.fill, "fill-opacity": 0.35 } : {};
    out.push({ id: m.id, segs, pts: P, locked: markupLocked(m), kind: m.kind, centre: m.kind === "circle" ? P[0] : geo.arc?.c,
               closed: (m.kind === "polyline" && m.closed) || m.kind === "circle", r: rad ?? geo.arc?.r });
    if (m.kind === "circle") el("circle", { cx: P[0][0], cy: P[0][1], r: rad, ...st(col), ...fill }, g);
    else if (m.kind === "arc") el("polyline", { points: geo.line.map((p) => p.join(",")).join(" "), ...st(col) }, g);
    else if (m.kind === "point") { const k = r * 1.4; el("path", { d: `M${P[0][0] - k} ${P[0][1]}H${P[0][0] + k}M${P[0][0]} ${P[0][1] - k}V${P[0][1] + k}`, ...st(col) }, g); }
    else if (m.kind === "line" || m.kind === "polyline" || m.kind === "leader") {
      el(m.kind === "polyline" && m.closed ? "polygon" : "polyline", { points: P.map((p) => p.join(",")).join(" "), ...st(col), ...(m.closed ? fill : {}) }, g);
      if (m.kind === "leader") {  // arrowhead at the first point
        const [a, b] = P, ang = Math.atan2(b[1] - a[1], b[0] - a[0]), s = r * 2.2;
        el("polygon", { points: [a, [a[0] + s * Math.cos(ang + 0.35), a[1] + s * Math.sin(ang + 0.35)], [a[0] + s * Math.cos(ang - 0.35), a[1] + s * Math.sin(ang - 0.35)]].map((p) => p.join(",")).join(" "), fill: col }, g);
      }
    } else if (m.kind === "dimension") {
      const dg = dimGeometry(m.dim || "aligned", P, m.size * 1.5);
      dg.lines.forEach(([a, b]) => el("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], ...st(col, 1) }, g));
      const t = el("text", { x: 0, y: 0, fill: col, "font-size": m.size, "font-family": "Arial, sans-serif", "text-anchor": "middle",
        transform: `translate(${dg.text[0]} ${dg.text[1]}) rotate(${dg.angle})` }, g);
      t.textContent = dimLabel(m, dg.value);
    }
    if ((m.kind === "text" || m.kind === "leader") && m.text) {
      const [x, y] = P[P.length - 1];
      el("text", { x: x + (m.kind === "leader" ? r : 0), y, fill: col, "font-size": m.size, "font-family": "Arial, sans-serif" }, g).textContent = m.text;
      lab.block(x + m.text.length * m.size * 0.29, y - m.size / 2, Math.max(m.size, m.text.length * m.size * 0.29));
    }
  }
  return out;
}

function star(cx, cy, ro, ri) {
  const p = [];
  for (let k = 0; k < 10; k++) { const a = Math.PI / 5 * k - Math.PI / 2, rr = k % 2 ? ri : ro; p.push(`${cx + rr * Math.cos(a)},${cy + rr * Math.sin(a)}`); }
  return p.join(" ");
}

// ---- CAD tools: zoom / pan / window / measure / coordinates, map underlay and editing ---------------
// Editing works on a selection of poles, equipment, premises, cables and cable vertices
// ({type, id} or {type: "vertex", cable, i}) and goes through the same functions as the map (movePoint,
// deleteFeature, changed), so saving, undo / redo, QA and the properties panel behave the same.
function svgPoint(svg, e) {
  const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
  return pt.matrixTransform(svg.getScreenCTM().inverse());
}
const cadMsg = (t) => { $("#lldMsg").textContent = t; };
function cadPx() {  // drawing metres per screen pixel
  const svg = $("#lldBig svg"), rc = svg?.getBoundingClientRect();
  return rc && rc.width ? Math.max(CAD.vb[2] / rc.width, CAD.vb[3] / rc.height) : 1;
}
const cadKey = (it) => it.type === "vertex" ? `v:${it.cable}:${it.i}` : `${it.type}:${it.id}`;
function segDist(p, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1], l = dx * dx + dy * dy;
  const t = l ? Math.max(0, Math.min(1, ((p.x - a[0]) * dx + (p.y - a[1]) * dy) / l)) : 0;
  return Math.hypot(a[0] + t * dx - p.x, a[1] + t * dy - p.y);
}
function cadCable() {  // the cable whose vertices show grips: one cable, or one of its vertices, selected
  const s = CAD.sel;
  return s.length === 1 ? (s[0].type === "cable" ? s[0].id : s[0].type === "vertex" ? s[0].cable : null) : null;
}

// the feature under the cursor: grips of the selected cable, then equipment, poles, premises, then cables
function cadPick(p) {
  const tol = 8 * cadPx(), F = CAD.feats;
  let best = null;
  const grip = cadCable() && F.lines.find((l) => l.id === cadCable());
  grip?.pts.forEach((q, i) => { const d = Math.hypot(q[0] - p.x, q[1] - p.y); if (d <= tol && (!best || d < best.d)) best = { d, item: { type: "vertex", cable: grip.id, i } }; });
  if (best) return best.item;
  for (const q of F.pts) {
    const d = Math.hypot(q.x - p.x, q.y - p.y) + q.rank * tol * 0.15;
    if (d <= tol * 1.3 && (!best || d < best.d)) best = { d, item: { type: q.type, id: q.id } };
  }
  if (best) return best.item;
  for (const M of (F.marks || []).filter((x) => !x.locked)) for (const [a, b] of M.segs) {  // above cables; locked layers stay put
    const d = segDist(p, a, b);
    if (d <= tol && (!best || d < best.d)) best = { d, item: { type: "markup", id: M.id } };
  }
  if (best) return best.item;
  for (const L of F.lines) for (let k = 1; k < L.pts.length; k++) {
    const d = segDist(p, L.pts[k - 1], L.pts[k]);
    if (d <= tol && (!best || d < best.d)) best = { d, item: { type: "cable", id: L.id } };
  }
  return best ? best.item : null;
}

// object snap (F3; modes in the Osnap list): endpoints and features, midpoints, centres, intersections,
// perpendicular from the previous point, nearest on a line. Things being moved are skipped.
const OSNAP = [["end", "Endpoint / feature"], ["mid", "Midpoint"], ["cen", "Centre"], ["int", "Intersection"],
  ["perp", "Perpendicular"], ["near", "Nearest"]];
function osnapOn(k) { return (PREFS.cad_osnap || { end: 1, mid: 1, cen: 1, int: 1, perp: 1 })[k]; }
function snapFrom() {  // the previous point of the drawing or edit in progress
  return CAD.dpts?.[CAD.dpts.length - 1] || (CAD.op?.base ? [CAD.op.base.x, CAD.op.base.y] : null) || CAD.cmdFrom || null;
}
function segCross(a, b, c, d) {
  const r = [b[0] - a[0], b[1] - a[1]], s = [d[0] - c[0], d[1] - c[1]], den = r[0] * s[1] - r[1] * s[0];
  if (Math.abs(den) < 1e-12) return null;
  const t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den, u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den;
  return t >= -1e-9 && t <= 1 + 1e-9 && u >= -1e-9 && u <= 1 + 1e-9 ? [a[0] + t * r[0], a[1] + t * r[1]] : null;
}
function cadSnap(p, moving) {
  if (!PREFS.cad_snap) return null;
  const tol = 10 * cadPx(), F = CAD.feats;
  let best = null;
  const take = (x, y, item, mode, rank = 0) => {
    if (item && moving.has(cadKey(item))) return;
    const d = Math.hypot(x - p.x, y - p.y);
    if (d <= tol && (!best || d + rank * tol < best.d + best.rank * tol)) best = { x, y, d, item, mode, rank };
  };
  const marks = (F.marks || []).filter((M) => !moving.has(`mpoint:${M.id}`));
  if (osnapOn("end")) {
    F.pts.forEach((q) => take(q.true ? q.true[0] : q.x, q.true ? q.true[1] : q.y, { type: q.type, id: q.id }, "end"));
    F.lines.forEach((L) => L.pts.forEach((q, i) => take(q[0], q[1], { type: "vertex", cable: L.id, i }, "end")));
    marks.forEach((M) => M.pts.forEach((q, k) => { if (M.kind !== "circle" || k === 1) take(q[0], q[1], { type: "mpoint", id: M.id, k }, "end"); }));
  }
  if (osnapOn("cen")) marks.forEach((M) => { if (M.centre) take(M.centre[0], M.centre[1], null, "cen"); });
  // segments near the cursor, for midpoints, intersections, perpendicular and nearest
  const near = [];
  const consider = (a, b) => { if (segDist(p, a, b) <= tol * 3) near.push([a, b]); };
  F.lines.forEach((L) => L.pts.slice(1).forEach((q, k) => consider(L.pts[k], q)));
  marks.forEach((M) => { if (M.kind !== "text" && M.kind !== "point") M.segs.forEach(([a, b]) => consider(a, b)); });
  if (osnapOn("mid")) {
    F.lines.forEach((L) => L.pts.slice(1).forEach((q, k) => take((q[0] + L.pts[k][0]) / 2, (q[1] + L.pts[k][1]) / 2, null, "mid")));
    marks.forEach((M) => { if (["line", "polyline", "leader"].includes(M.kind)) M.segs.forEach(([a, b]) => take((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, null, "mid")); });
  }
  if (osnapOn("int")) for (let i = 0; i < near.length; i++) for (let j = i + 1; j < near.length; j++) {
    const x = segCross(...near[i], ...near[j]);
    if (x) take(x[0], x[1], null, "int");
  }
  const from = snapFrom();
  if (osnapOn("perp") && from) near.forEach(([a, b]) => {
    const dx = b[0] - a[0], dy = b[1] - a[1], l = dx * dx + dy * dy;
    if (!l) return;
    const t = ((from[0] - a[0]) * dx + (from[1] - a[1]) * dy) / l;
    if (t > 0 && t < 1) take(a[0] + t * dx, a[1] + t * dy, null, "perp", 0.3);
  });
  if (osnapOn("near") && !best) near.forEach(([a, b]) => {
    const dx = b[0] - a[0], dy = b[1] - a[1], l = dx * dx + dy * dy, t = l ? Math.max(0, Math.min(1, ((p.x - a[0]) * dx + (p.y - a[1]) * dy) / l)) : 0;
    take(a[0] + t * dx, a[1] + t * dy, null, "near", 0.6);
  });
  return best;
}

// what an edit moves, with its drawing position: poles, premises, equipment (a pole carries its equipment),
// and the free vertices of selected cables (vertices on a pole or equipment move with it)
function cadMovables() {
  const F = CAD.feats, out = [], seen = new Set();
  const selPoles = new Set(CAD.sel.filter((s) => s.type === "pole").map((s) => s.id));
  const add = (k, m) => { if (!seen.has(k)) { seen.add(k); out.push(m); } };
  for (const s of CAD.sel) {
    if (s.type === "pole" || s.type === "home") {
      const q = F.pts.find((x) => x.type === s.type && x.id === s.id);
      if (q) add(cadKey(s), { ...s, x: q.x, y: q.y });
    } else if (s.type === "markup") {  // every point of the drafting moves
      const M = (F.marks || []).find((x) => x.id === s.id);
      M?.pts.forEach((q, k) => add(`mpoint:${s.id}:${k}`, { type: "mpoint", id: s.id, k, x: q[0], y: q[1] }));
    } else if (s.type === "node") {
      const n = find("node", s.id), q = F.pts.find((x) => x.type === "node" && x.id === s.id);
      if (n && q && !(n.pole && selPoles.has(n.pole))) add(cadKey(s), { ...s, x: q.true[0], y: q.true[1] });
    } else {
      const c = find("cable", s.type === "cable" ? s.id : s.cable), L = F.lines.find((l) => l.id === c?.id);
      if (!c || !L) continue;
      const idx = s.type === "cable" ? c.path.map((_, i) => i) : [s.i];
      for (const i of idx) {
        const v = c.path[i];
        if (v && !v.pole && !v.node) add(`v:${c.id}:${i}`, { type: "vertex", cable: c.id, i, x: L.pts[i][0], y: L.pts[i][1] });
      }
    }
  }
  return out;
}

function cadApply(f, snap) {
  const ms = cadMovables();
  if (!ms.length) return toast("Nothing to move: vertices on a pole or equipment move with it - select the pole instead", 6000);
  for (const m of ms) {
    const [x, y] = f(m.x, m.y), [lat, lon] = CAD.proj.inverse(x, y);
    if (m.type === "mpoint") {
      S.D.markups.find((k) => k.id === m.id).points[m.k] = [lat, lon];
    } else if (m.type === "vertex") {
      const v = find("cable", m.cable).path[m.i];
      v.lat = lat; v.lon = lon;
      // a single free vertex dropped on a pole or equipment is attached to it
      if (ms.length === 1 && snap?.item && (snap.item.type === "pole" || snap.item.type === "node")) {
        const n = snap.item.type === "node" ? find("node", snap.item.id) : null;
        v.node = n ? n.id : null; v.pole = n ? n.pole || null : snap.item.id;
        const at = n || find("pole", snap.item.id);
        if (okc(at)) { v.lat = at.lat; v.lon = at.lon; }
      }
    } else {
      const obj = find(m.type, m.id);
      if (m.type === "node" && obj.pole) { obj.pole = null; syncNodePole(obj); }  // taken off its pole
      movePoint(m.type, obj, lat, lon);
    }
  }
  changed();
}

function cadDelete() {
  if (!CAD.sel.length) return toast("Select something to delete");
  const errs = [], verts = {};
  for (const s of CAD.sel) if (s.type === "vertex") (verts[s.cable] ||= []).push(s.i);
  for (const [cid, idx] of Object.entries(verts)) {  // vertices: never a cable's ends
    const c = find("cable", cid);
    for (const i of idx.sort((a, b) => b - a)) {
      if (i === 0 || i === c.path.length - 1 || c.path.length <= 2) errs.push(`${cid}: the ends of a cable cannot be deleted`);
      else c.path.splice(i, 1);
    }
  }
  const marks = new Set(CAD.sel.filter((x) => x.type === "markup").map((x) => x.id));
  if (marks.size) S.D.markups = S.D.markups.filter((m) => !marks.has(m.id));
  const order = { cable: 0, node: 1, home: 2, pole: 3 };  // cables first, so their poles and equipment come free
  for (const s of CAD.sel.filter((x) => x.type in order).sort((a, b) => order[a.type] - order[b.type])) {
    const why = deleteFeature(s.type, s.id);
    if (why) errs.push(why);
  }
  CAD.sel = []; S.sel = null;
  if (errs.length) toast(errs.slice(0, 3).join(" "), 7000);
  changed();
}

function cadSelect(items, add) {
  if (!add) CAD.sel = [];
  for (const it of items) {
    const k = cadKey(it), i = CAD.sel.findIndex((s) => cadKey(s) === k);
    if (i >= 0 && add && items.length === 1) CAD.sel.splice(i, 1); else if (i < 0) CAD.sel.push(it);
  }
  S.sel = CAD.sel.length === 1 && !["vertex", "markup"].includes(CAD.sel[0].type) ? CAD.sel[0] : null;
  drawCadSel(); renderCadProps();
  if (CAD.sel.length) cadMsg(`${CAD.sel.length} selected. Move (M), Rotate (R) or Delete (Del); Esc clears.`);
}

function drawCadSel() {
  const g = $("#cadSel");
  if (!g) return;
  g.innerHTML = "";
  const F = CAD.feats, u = cadPx(), col = "#00e5ff";
  for (const s of CAD.sel) {
    if (s.type === "markup") {
      const M = (F.marks || []).find((x) => x.id === s.id);
      M?.segs.forEach(([a, b]) => el("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], stroke: col, "stroke-width": 4, "stroke-opacity": 0.5, "vector-effect": "non-scaling-stroke" }, g));
      M?.pts.forEach((p) => el("rect", { x: p[0] - 3 * u, y: p[1] - 3 * u, width: 6 * u, height: 6 * u, fill: col }, g));
      continue;
    }
    if (s.type === "cable" || s.type === "vertex") {
      const L = F.lines.find((l) => l.id === (s.type === "cable" ? s.id : s.cable));
      if (L && s.type === "cable") el("polyline", { points: L.pts.map((p) => p.join(",")).join(" "), stroke: col, "stroke-width": 5, "stroke-opacity": 0.55, "vector-effect": "non-scaling-stroke", fill: "none" }, g);
      continue;
    }
    const q = F.pts.find((x) => x.type === s.type && x.id === s.id);
    if (q) el("circle", { cx: q.x, cy: q.y, r: 7 * u, stroke: col, "stroke-width": 2, "vector-effect": "non-scaling-stroke", fill: "none" }, g);
  }
  const cid = cadCable(), L = cid && F.lines.find((l) => l.id === cid), c = cid && find("cable", cid);
  if (L && c) L.pts.forEach((p, i) => {  // grips: filled = free vertex, hollow = on a pole / equipment
    const on = CAD.sel.some((s) => s.type === "vertex" && s.cable === cid && s.i === i), free = !c.path[i].pole && !c.path[i].node;
    el("rect", { x: p[0] - 3.5 * u, y: p[1] - 3.5 * u, width: 7 * u, height: 7 * u, fill: on ? "#ff2a2a" : free ? col : "none", stroke: col, "stroke-width": 1.2, "vector-effect": "non-scaling-stroke" }, g);
  });
}

function renderCadProps() {
  const box = $("#cadProps");
  if (!box) return;
  box.hidden = !CAD.sel.length;
  if (!CAD.sel.length) return;
  if (S.sel) return renderPropsInto(box);
  if (CAD.sel.length === 1 && CAD.sel[0].type === "markup") return markupProps(box, S.D.markups.find((m) => m.id === CAD.sel[0].id));
  if (CAD.sel.length === 1) {  // a cable vertex
    const s = CAD.sel[0], v = find("cable", s.cable)?.path[s.i];
    if (!v) return;
    box.innerHTML = `<h3>Vertex ${s.i + 1} of ${esc(s.cable)}</h3><p>${v.lat.toFixed(6)}, ${v.lon.toFixed(6)}</p>
      <p class="muted">${v.pole || v.node ? `On ${esc(v.node || v.pole)}: it moves with that feature.` : "Free vertex: Move it, or drop it on a pole or equipment (with Snap) to attach it there. Delete removes it from the route."}</p>`;
    return;
  }
  const n = {};
  CAD.sel.forEach((s) => { n[s.type] = (n[s.type] || 0) + 1; });
  box.innerHTML = `<h3>${CAD.sel.length} selected</h3><table>${Object.entries(n).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="num">${v}</td></tr>`).join("")}</table>
    <p class="muted">Move (M) and Rotate (R) act on all of them; vertices on a pole or equipment follow it. Delete (Del) removes them.</p>`;
}

const OP_BUTTON = { move: "#cadMove", rotate: "#cadRotate", copy: "#cadCopy", offset: "#cadOffset" };
function cadStart(kind) {
  if (!CAD.sel.length) return toast(`Select what to ${kind} first (click it, or Select and drag a box)`);
  if (kind === "offset") {
    const m = CAD.sel.length === 1 && CAD.sel[0].type === "markup" && S.D.markups.find((x) => x.id === CAD.sel[0].id);
    if (!m || !["line", "polyline", "circle"].includes(m.kind)) return toast("Offset works on one drafting line, polyline, rectangle or circle");
  }
  if (CAD.tool) setCadTool(CAD.tool);
  CAD.op = { kind, stage: kind === "offset" ? "side" : "base" };
  for (const [k, b] of Object.entries(OP_BUTTON)) $(b).classList.toggle("active", k === kind);
  $("#cadAngle").hidden = kind !== "rotate"; $("#cadAngle").value = "";
  $("#cadDist").hidden = kind !== "offset";
  if (kind === "offset") { $("#cadDist").focus(); return cadMsg("Offset: type the distance (m) in the box, then click the side to offset to. Esc cancels."); }
  cadMsg(`${kind[0].toUpperCase() + kind.slice(1)}: click the base point${PREFS.cad_snap ? " (snaps to features)" : ""}. Esc cancels.`);
}
function cadEnd() {
  CAD.op = null;
  cadMsg("");
  for (const b of Object.values(OP_BUTTON)) $(b).classList.remove("active");
  $("#cadAngle").hidden = true; $("#cadDist").hidden = true;
  const g = $("#cadPreview"); if (g) g.innerHTML = "";
}

// ---- drafting, inquiry, copy and offset --------------------------------------------------------------------
// Draw tools add design.markups (saved with the project, drawn on the LLD / HLD sheets and in the DXF; never
// counted). Inquiry tools only report. Points snap to features and drafting (Snap) and follow Ortho from the
// previous point.
const DRAW = { line: "Line: click two points.", pline: "Polyline: click points; Enter or double-click finishes, C closes it.",
  rect: "Rectangle: click two opposite corners.", circle: "Circle: click the centre, then a point on the edge.",
  text: "Text: type the note in the note box, then click where it goes.",
  leader: "Leader: click the arrow point, then the bend / text points; Enter finishes (text from the note box).",
  dim: "Dimension: click the two points to measure.", area: "Area: click the corners; Enter or double-click finishes.",
  angle: "Angle: click a point on one arm, the vertex, then a point on the other arm.", id: "ID point: click a point." };
CAD.dpts = [];
function drawPoint(p) {
  if (CAD.typed) return { q: [p.x, p.y], sn: null };  // a typed coordinate is exact: no snap, no ortho
  const sn = cadSnap(p, new Set()), last = CAD.dpts[CAD.dpts.length - 1];
  let q = sn ? [sn.x, sn.y] : [p.x, p.y];
  if (last && PREFS.cad_ortho && !sn) q = Math.abs(q[0] - last[0]) >= Math.abs(q[1] - last[1]) ? [q[0], last[1]] : [last[0], q[1]];
  return { q, sn };
}
function nextMarkupId() {
  const ids = new Set((S.D.markups || []).map((m) => m.id));
  let i = 1;
  while (ids.has(`MK${String(i).padStart(3, "0")}`)) i++;
  return `MK${String(i).padStart(3, "0")}`;
}
const toLatLon = (pts) => pts.map(([x, y]) => CAD.proj.inverse(x, y));
function addMarkup(kind, pts, extra = {}) {
  S.D.markups ||= [];
  const m = { id: nextMarkupId(), kind, points: toLatLon(pts), closed: false, text: "", size: Math.min(50, Math.max(0.2, +$("#cadSize").value || 2)),
              colour: $("#cadColour").value || "#00e5ff", layer: CAD.curLayer || "0", fill: "", dim: "aligned", ...extra };
  S.D.markups.push(m);
  CAD.sel = [{ type: "markup", id: m.id }]; S.sel = null;
  changed();
  return m;
}
function polyArea(P) { let a = 0; P.forEach((p, k) => { const q = P[(k + 1) % P.length]; a += p[0] * q[1] - q[0] * p[1]; }); return Math.abs(a) / 2; }
function polyLen(P, closed) { let l = 0; P.forEach((p, k) => { if (k || closed) { const q = P[(k || P.length) - 1]; l += Math.hypot(p[0] - q[0], p[1] - q[1]); } }); return l; }
function showInquiry(P, closed) {  // the measured shape stays on screen until the next tool or Esc
  const g = $("#cadOverlay");
  if (!g) return;
  g.innerHTML = "";
  el(closed ? "polygon" : "polyline", { points: P.map((p) => p.join(",")).join(" "), stroke: "#00e5ff", "stroke-width": 2, "vector-effect": "non-scaling-stroke",
    fill: closed ? "rgba(0,229,255,.15)" : "none", "stroke-dasharray": "6 4" }, g);
}
function drawClick(p) {
  const tool = CAD.tool, { q } = drawPoint(p), pts = CAD.dpts;
  if (tool === "id") {
    const [la, lo] = CAD.proj.inverse(q[0], q[1]), t = `${la.toFixed(6)}, ${lo.toFixed(6)}`;
    cadMsg(`Point: X ${q[0].toFixed(2)} m  Y ${(-q[1]).toFixed(2)} m  ·  ${t} (copied)`);
    navigator.clipboard?.writeText(t).catch(() => {});
    return;
  }
  if (tool === "text") {
    const note = $("#cadNote").value.trim();
    if (!note) { $("#cadNote").focus(); return toast("Type the note in the note box first"); }
    addMarkup("text", [q], { text: note });
    return;
  }
  pts.push(q);
  const n = pts.length;
  if (tool === "line" && n === 2) { const seg = pts.splice(0); addMarkup("line", seg); CAD.dpts = [seg[1]]; }  // next line chains on
  else if (tool === "dim" && n === 2) addMarkup("dimension", pts.splice(0));
  else if (tool === "circle" && n === 2) addMarkup("circle", pts.splice(0));
  else if (tool === "rect" && n === 2) { const [a, b] = pts.splice(0); addMarkup("polyline", [a, [b[0], a[1]], b, [a[0], b[1]]], { closed: true }); }
  else if (tool === "angle" && n === 3) {
    const [a, v, b] = pts.splice(0);
    let d = Math.abs(Math.atan2(a[1] - v[1], a[0] - v[0]) - Math.atan2(b[1] - v[1], b[0] - v[0])) * 180 / Math.PI;
    if (d > 180) d = 360 - d;
    showInquiry([a, v, b], false);
    cadMsg(`Angle: ${d.toFixed(1)}° (and ${(360 - d).toFixed(1)}° the other way round).`);
    return;
  } else cadMsg(DRAW[tool] + (n ? ` ${n} point(s).` : ""));
}
function drawFinish(close) {
  const tool = CAD.tool, pts = CAD.dpts.filter((p, k, a) => !k || Math.hypot(p[0] - a[k - 1][0], p[1] - a[k - 1][1]) > cadPx() * 2);
  CAD.dpts = [];
  if (tool === "pline" && pts.length >= 2) addMarkup("polyline", pts, { closed: !!close && pts.length > 2 });
  else if (tool === "leader" && pts.length >= 2) addMarkup("leader", pts, { text: $("#cadNote").value.trim() });
  else if (tool === "area" && pts.length >= 3) {
    showInquiry(pts, true);
    cadMsg(`Area: ${polyArea(pts).toFixed(1)} m² (${(polyArea(pts) / 10000).toFixed(4)} ha), perimeter ${polyLen(pts, true).toFixed(1)} m.`);
  } else if (pts.length && tool !== "line") toast("Not enough points");
  const g = $("#cadPreview"); if (g) g.innerHTML = "";
}
function drawPreview(g, cur) {
  g.innerHTML = "";
  const tool = CAD.tool, pts = CAD.dpts, col = $("#cadColour").value || "#00e5ff", u = cadPx();
  const st = { stroke: col, "stroke-width": 1.5, "vector-effect": "non-scaling-stroke", fill: "none", "stroke-dasharray": "5 4" };
  if (!pts.length) return;
  const all = [...pts, cur], last = pts[pts.length - 1], len = Math.hypot(cur[0] - last[0], cur[1] - last[1]);
  if (tool === "rect") el("polygon", { points: [pts[0], [cur[0], pts[0][1]], cur, [pts[0][0], cur[1]]].map((p) => p.join(",")).join(" "), ...st }, g);
  else if (tool === "circle") el("circle", { cx: pts[0][0], cy: pts[0][1], r: len, ...st }, g);
  else el(tool === "area" ? "polygon" : "polyline", { points: all.map((p) => p.join(",")).join(" "), ...st, ...(tool === "area" ? { fill: "rgba(0,229,255,.12)" } : {}) }, g);
  const info = tool === "area" && all.length > 2 ? `${polyArea(all).toFixed(1)} m²` : tool === "circle" ? `r ${len.toFixed(1)} m` : `${len.toFixed(1)} m`;
  el("text", { x: cur[0] + 8 * u, y: cur[1] - 8 * u, fill: col, "font-size": 12 * u, "font-family": "Arial, sans-serif" }, g).textContent = info;
}

function markupProps(box, m) {
  if (!m) return;
  const P = m.points.map((p) => CAD.proj.xy(p[0], p[1])), arc = m.kind === "arc" && arc3(...P);
  const info = m.kind === "circle" ? `Radius ${Math.hypot(P[1][0] - P[0][0], P[1][1] - P[0][1]).toFixed(1)} m`
    : m.kind === "polyline" && m.closed ? `Area ${polyArea(P).toFixed(1)} m², perimeter ${polyLen(P, true).toFixed(1)} m`
    : arc ? `Radius ${arc.r.toFixed(1)} m, length ${(Math.abs(arc.sweep) * arc.r).toFixed(1)} m`
    : m.kind === "dimension" ? `Measures ${dimLabel({ ...m, text: "" }, dimGeometry(m.dim || "aligned", P, 1).value)}`
    : ["text", "point"].includes(m.kind) ? "" : `Length ${polyLen(P, false).toFixed(1)} m`;
  const fillable = (m.kind === "polyline" && m.closed) || m.kind === "circle";
  const layers = ["0", ...(S.D.cad_layers || []).map((l) => l.name)];
  box.innerHTML = `<h3>${esc(m.kind[0].toUpperCase() + m.kind.slice(1))} ${esc(m.id)}</h3><p class="muted">Drafting: drawn on the LLD / HLD sheets and in the DXF, never counted.</p>
    <div class="form">${["text", "leader", "dimension"].includes(m.kind) ? `<label>Text${m.kind === "dimension" ? " (empty: the measured value)" : ""}<input data-mk="text" maxlength="300" value="${esc(m.text)}"></label>` : ""}
    ${m.kind === "dimension" && (m.dim || "aligned") !== "radius" && m.dim !== "angular" ? `<label>Dimension<select data-mk="dim">${["aligned", "horizontal", "vertical"].map((k) => `<option ${k === (m.dim || "aligned") ? "selected" : ""}>${k}</option>`).join("")}</select></label>` : ""}
    <label>Layer<select data-mk="layer">${layers.map((l) => `<option ${l === (m.layer || "0") ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>
    <label>Text height (m)<input data-mk="size" type="number" min="0.2" max="50" step="0.1" value="${m.size}"></label>
    <label>Colour<input data-mk="colour" type="color" value="${esc(m.colour)}"></label>
    ${fillable ? `<label class="inline"><input data-mk="hatch" type="checkbox" ${m.fill ? "checked" : ""}> Hatch</label>${m.fill ? `<label>Hatch colour<input data-mk="fill" type="color" value="${esc(m.fill)}"></label>` : ""}` : ""}
    ${m.kind === "polyline" ? `<label class="inline"><input data-mk="closed" type="checkbox" ${m.closed ? "checked" : ""}> Closed</label>` : ""}</div>
    ${info ? `<p>${info}</p>` : ""}`;
  $$("[data-mk]", box).forEach((inp) => inp.addEventListener("change", () => {
    const k = inp.dataset.mk;
    if (k === "hatch") m.fill = inp.checked ? m.colour : "";
    else m[k] = k === "closed" ? inp.checked : k === "size" ? Math.min(50, Math.max(0.2, +inp.value || 2)) : inp.value;
    if (k === "closed" && !m.closed) m.fill = "";
    changed();
  }));
}

// Copy: the selected drafting, poles, premises and equipment, shifted by base point -> second point. Copies are
// proposed and get new IDs; equipment copied with its pole goes on the copy of the pole. Cables are not copied.
function cadCopyApply(f, quiet = false) {  // quiet: return the copies; the caller selects and saves (Array)
  const made = [], poleMap = {};
  const at = (lat, lon) => { const [x, y] = f(...CAD.proj.xy(lat, lon)); return CAD.proj.inverse(x, y); };
  let cables = 0;
  for (const s of CAD.sel) {
    if (s.type === "markup") {
      const m = S.D.markups.find((x) => x.id === s.id), c = { ...JSON.parse(JSON.stringify(m)), id: nextMarkupId() };
      c.points = m.points.map((p) => at(p[0], p[1]));
      S.D.markups.push(c); made.push({ type: "markup", id: c.id });
    } else if (s.type === "pole" || s.type === "home") {
      const o = find(s.type, s.id), c = { ...JSON.parse(JSON.stringify(o)), id: nextId(s.type === "pole" ? "P" : "H") };
      [c.lat, c.lon] = at(o.lat, o.lon);
      if (s.type === "pole") { c.status = "proposed"; poleMap[o.id] = c.id; } else { c.fat = null; c.extra_fats = []; }
      S.D[collOf[s.type]].push(c); made.push({ type: s.type, id: c.id });
    } else if (s.type === "cable" || s.type === "vertex") cables++;
  }
  for (const s of CAD.sel.filter((x) => x.type === "node")) {
    const o = find("node", s.id), c = { ...JSON.parse(JSON.stringify(o)), id: nextId(PREFIX[o.kind], 2), status: "proposed" };
    c.pole = poleMap[o.pole] || null;
    const p = c.pole && find("pole", c.pole);
    [c.lat, c.lon] = p ? [p.lat, p.lon] : at(o.lat, o.lon);
    S.D.nodes.push(c); made.push({ type: "node", id: c.id });
  }
  if (quiet) return { made, cables };
  CAD.sel = made; S.sel = made.length === 1 && made[0].type !== "markup" ? made[0] : null;
  if (made.length) changed();
  toast(`Copied ${made.length}${cables ? `; ${cables} cable(s) not copied (draw new routes between the copies)` : ""}`, 5000);
}

// Offset: a parallel copy of a drafting line, polyline or circle, the typed distance away, on the clicked side
function cadOffsetApply(p) {
  const m = S.D.markups.find((x) => x.id === CAD.sel[0]?.id), d = +$("#cadDist").value;
  if (!m || !(d > 0)) return toast("Type the offset distance (m) first");
  const P = m.points.map((q) => CAD.proj.xy(q[0], q[1]));
  if (m.kind === "circle") {
    const r = Math.hypot(P[1][0] - P[0][0], P[1][1] - P[0][1]), out = Math.hypot(p.x - P[0][0], p.y - P[0][1]) > r, r2 = r + (out ? d : -d);
    if (r2 <= 0) return toast("The offset is larger than the radius");
    return addMarkup("circle", [P[0], [P[0][0] + r2, P[0][1]]], { colour: m.colour, size: m.size });
  }
  const closed = m.kind === "polyline" && m.closed, n = P.length, segs = [];
  for (let k = 0; k < (closed ? n : n - 1); k++) segs.push([P[k], P[(k + 1) % n]]);
  let best = 0, bd = Infinity;  // the side: of the segment nearest the click
  segs.forEach(([a, b], k) => { const dd = segDist(p, a, b); if (dd < bd) { bd = dd; best = k; } });
  const [a0, b0] = segs[best], side = Math.sign((b0[0] - a0[0]) * (p.y - a0[1]) - (b0[1] - a0[1]) * (p.x - a0[0])) || 1;
  const off = segs.map(([a, b]) => {
    const L = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1, nx = -(b[1] - a[1]) / L * d * side, ny = (b[0] - a[0]) / L * d * side;
    return [[a[0] + nx, a[1] + ny], [b[0] + nx, b[1] + ny]];
  });
  const meet = (s1, s2) => {  // where two offset segments' lines cross (or the end of the first when parallel)
    const [[x1, y1], [x2, y2]] = s1, [[x3, y3], [x4, y4]] = s2, den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4);
    if (Math.abs(den) < 1e-9) return s1[1];
    const t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den;
    return [x1 + t * (x2 - x1), y1 + t * (y2 - y1)];
  };
  const Q = closed ? off.map((s, k) => meet(off[(k - 1 + off.length) % off.length], s))
    : [off[0][0], ...off.slice(1).map((s, k) => meet(off[k], s)), off[off.length - 1][1]];
  addMarkup(m.kind === "line" ? "line" : "polyline", Q, { closed, colour: m.colour, size: m.size });
}

// map tiles (OpenStreetMap streets or Esri imagery) under the drawing, at the zoom of the current view
const CAD_TILES = {
  streets: [(z, x, y) => `https://tile.openstreetmap.org/${z}/${x}/${y}.png`, "© OpenStreetMap contributors"],
  satellite: [(z, x, y) => `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${y}/${x}`, "Imagery © Esri"],
};
function drawBasemap() {
  const svg = $("#lldBig svg"), g = svg?.querySelector("#cadBasemap"), attr = $("#cadAttr");
  if (!g || !CAD.proj) return;
  g.innerHTML = "";
  const src = CAD_TILES[PREFS.cad_map];
  if (attr) attr.textContent = src ? src[1] : "";
  if (!src) return;
  const rc = svg.getBoundingClientRect();
  if (!rc.width) return;
  const [vx, vy, vw, vh] = CAD.vb, k = Math.min(rc.width / vw, rc.height / vh);  // viewBox shown with "meet"
  const W = rc.width / k, H = rc.height / k, cx = vx + vw / 2, cy = vy + vh / 2;
  const [latN, lonW] = CAD.proj.inverse(cx - W / 2, cy - H / 2), [latS, lonE] = CAD.proj.inverse(cx + W / 2, cy + H / 2);
  const lat = (latN + latS) / 2, mpp = W / rc.width;
  let z = Math.max(2, Math.min(19, Math.round(Math.log2(156543.03 * Math.cos(lat * Math.PI / 180) / mpp))));
  const n = () => 2 ** z, tx = (lo) => (lo + 180) / 360 * n();
  const ty = (la) => { const r = la * Math.PI / 180; return (1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * n(); };
  const lonOf = (x) => x / n() * 360 - 180, latOf = (y) => 180 / Math.PI * Math.atan(Math.sinh(Math.PI - 2 * Math.PI * y / n()));
  while (z > 2 && (Math.floor(tx(lonE)) - Math.floor(tx(lonW)) + 1) * (Math.floor(ty(latS)) - Math.floor(ty(latN)) + 1) > 150) z--;
  for (let x = Math.floor(tx(lonW)); x <= Math.floor(tx(lonE)); x++) {
    for (let y = Math.max(0, Math.floor(ty(latN))); y <= Math.min(n() - 1, Math.floor(ty(latS))); y++) {
      const [ax, ay] = CAD.proj.xy(latOf(y), lonOf(x)), [bx, by] = CAD.proj.xy(latOf(y + 1), lonOf(x + 1));
      el("image", { href: src[0](z, ((x % n()) + n()) % n(), y), x: ax, y: ay, width: bx - ax, height: by - ay, preserveAspectRatio: "none" }, g);
    }
  }
  // dim the map a little so the drawing stays readable on it
  el("rect", { x: cx - W, y: cy - H, width: 2 * W, height: 2 * H, fill: PREFS.cad_dark ? "#000" : "#fff", "fill-opacity": PREFS.cad_dark ? 0.35 : 0.2 }, g);
}

function cadTools(svg) {
  const home = svg.getAttribute("viewBox").split(" ").map(Number);
  CAD.home = home; CAD.meas = [];
  if (CAD.pid !== S.pid || !CAD.vb) CAD.vb = [...home];  // a redraw after an edit keeps the view
  CAD.pid = S.pid;
  let mapTimer = null;
  const apply = () => {
    svg.setAttribute("viewBox", CAD.vb.join(" "));
    clearTimeout(mapTimer); mapTimer = setTimeout(() => { drawBasemap(); drawCadSel(); }, 120);
  };
  apply();
  const ids = { pole: new Set(S.D.poles.map((x) => x.id)), home: new Set(S.D.homes.map((x) => x.id)),
                node: new Set(S.D.nodes.map((x) => x.id)), cable: new Set(S.D.cables.map((x) => x.id)) };
  ids.markup = new Set((S.D.markups || []).map((x) => x.id));
  CAD.sel = (CAD.sel || []).filter((s) => s.type === "vertex" ? !!find("cable", s.cable)?.path[s.i] : ids[s.type]?.has(s.id));
  if (S.sel && !CAD.sel.includes(S.sel)) S.sel = CAD.sel.length === 1 && CAD.sel[0].type !== "vertex" ? CAD.sel[0] : S.sel;
  renderCadProps();
  const zoomAt = (mx, my, f) => { const v = CAD.vb; CAD.prevVb = [...v]; CAD.vb = [mx - (mx - v[0]) * f, my - (my - v[1]) * f, v[2] * f, v[3] * f]; apply(); };
  const msg = cadMsg;
  const overlay = svg.querySelector("#cadOverlay"), preview = svg.querySelector("#cadPreview");
  const unit = () => Math.max(CAD.vb[2], CAD.vb[3]) / 300;
  const drawMeas = () => {
    overlay.innerHTML = "";
    if (!CAD.meas.length) return;
    el("polyline", { points: CAD.meas.map((p) => `${p.x},${p.y}`).join(" "), stroke: "#00e5ff", "stroke-width": 2, "vector-effect": "non-scaling-stroke", fill: "none", "stroke-dasharray": "6 4" }, overlay);
    let tot = 0;
    CAD.meas.forEach((p, k) => {
      if (k) tot += Math.hypot(p.x - CAD.meas[k - 1].x, p.y - CAD.meas[k - 1].y);
      el("circle", { cx: p.x, cy: p.y, r: unit() * 1.2, fill: "#00e5ff" }, overlay);
      if (k) { const t = el("text", { x: p.x + unit() * 2, y: p.y - unit() * 2, fill: "#00e5ff", "font-size": unit() * 5 }, overlay); t.textContent = `${tot.toFixed(1)} m`; }
    });
    msg(`Measured ${tot.toFixed(1)} m over ${CAD.meas.length - 1} segment(s). Click to add points; Esc or Measure again to stop.`);
  };
  svg.addEventListener("wheel", (e) => { e.preventDefault(); const p = svgPoint(svg, e); zoomAt(p.x, p.y, e.deltaY > 0 ? 1.2 : 1 / 1.2); }, { passive: false });
  let drag = null, rect = null;
  const moving = () => new Set(cadMovables().map((m) => m.type === "vertex" ? `v:${m.cable}:${m.i}` : `${m.type}:${m.id}`));
  // the second point of a move / rotate: snapped to a feature, or kept horizontal / vertical with Ortho
  const target = (p) => {
    if (CAD.typed) return { q: { x: p.x, y: p.y }, sn: null };
    const sn = cadSnap(p, CAD.op?.moving || new Set());
    let q = sn ? { x: sn.x, y: sn.y } : { x: p.x, y: p.y };
    const b = CAD.op?.base;
    if (b && PREFS.cad_ortho && !sn) q = Math.abs(q.x - b.x) >= Math.abs(q.y - b.y) ? { x: q.x, y: b.y } : { x: b.x, y: q.y };
    return { q, sn };
  };
  const opTransform = (q) => {
    const b = CAD.op.base;
    if (CAD.op.kind === "move" || CAD.op.kind === "copy") return { f: (x, y) => [x + q.x - b.x, y + q.y - b.y], text: `${Math.hypot(q.x - b.x, q.y - b.y).toFixed(1)} m` };
    const a = CAD.op.angle ?? Math.atan2(q.y - b.y, q.x - b.x), c = Math.cos(a), s = Math.sin(a);
    return { f: (x, y) => [b.x + (x - b.x) * c - (y - b.y) * s, b.y + (x - b.x) * s + (y - b.y) * c],
             text: `${(-a * 180 / Math.PI).toFixed(1)}°` };
  };
  const snapMark = (sn) => {  // AutoCAD-style marker per snap mode, with its name
    const u = cadPx(), k = 5 * u, x = sn.x, y = sn.y, a = { stroke: "#ffd60a", "stroke-width": 2, "vector-effect": "non-scaling-stroke", fill: "none" };
    const shape = { end: `M${x - k} ${y - k}h${2 * k}v${2 * k}h${-2 * k}z`, mid: `M${x} ${y - k}L${x + k} ${y + k}L${x - k} ${y + k}z`,
      cen: `M${x - k} ${y}a${k} ${k} 0 1 0 ${2 * k} 0a${k} ${k} 0 1 0 ${-2 * k} 0`, int: `M${x - k} ${y - k}L${x + k} ${y + k}M${x + k} ${y - k}L${x - k} ${y + k}`,
      perp: `M${x - k} ${y + k}H${x + k}M${x - k} ${y + k}V${y - k}M${x - k} ${y}H${x}V${y + k}`, near: `M${x - k} ${y - k}L${x + k} ${y + k}H${x - k}L${x + k} ${y - k}z` }[sn.mode || "end"];
    el("path", { d: shape, ...a }, preview);
    el("text", { x: x + 8 * u, y: y + 14 * u, fill: "#ffd60a", "font-size": 10 * u, "font-family": "Arial, sans-serif" }, preview).textContent =
      (OSNAP.find(([m]) => m === sn.mode) || [, "Endpoint"])[1].split(" /")[0];
  };
  CAD.snapMark = snapMark;
  const opPreview = (q, sn) => {
    preview.innerHTML = "";
    const u = cadPx(), col = "#00e5ff";
    if (sn) snapMark(sn);
    if (!CAD.op?.base) return;
    const b = CAD.op.base, { f, text } = opTransform(q);
    el("line", { x1: b.x, y1: b.y, x2: q.x, y2: q.y, stroke: col, "stroke-width": 1, "stroke-dasharray": "5 4", "vector-effect": "non-scaling-stroke" }, preview);
    for (const m of cadMovables()) {
      const [x, y] = f(m.x, m.y);
      el("circle", { cx: x, cy: y, r: 4 * u, fill: col, "fill-opacity": 0.5, stroke: col, "stroke-width": 1, "vector-effect": "non-scaling-stroke" }, preview);
    }
    el("text", { x: q.x + 8 * u, y: q.y - 8 * u, fill: col, "font-size": 12 * u, "font-family": "Arial, sans-serif" }, preview).textContent = text;
  };
  CAD.applyAngle = (deg) => {  // a typed rotation angle (degrees, counter-clockwise)
    if (CAD.op?.kind !== "rotate" || !CAD.op.base) return toast("Rotate: click the base point first");
    CAD.op.angle = -deg * Math.PI / 180;
    const { f } = opTransform(CAD.op.base);
    cadEnd(); cadApply(f, null);
  };
  // a point for the tool in progress, clicked or typed on the command line (cad.js); true when one took it
  const toolPoint = (p) => {
    if (CAD.cmd) { cadCmdPoint(p); return true; }
    if (CAD.tool === "measure") { CAD.meas.push(p); drawMeas(); return true; }
    if (DRAW[CAD.tool]) { drawClick(p); return true; }
    if (CAD.op?.kind === "offset") { cadEnd(); cadOffsetApply(p); return true; }
    if (!CAD.op) return false;
    {  // move / rotate / copy: base point, then second point
      const { q, sn } = target(p);
      if (CAD.op.stage === "base") {
        CAD.op = { ...CAD.op, stage: "second", base: q, moving: CAD.op.kind === "copy" ? new Set() : moving() };
        msg(CAD.op.kind === "rotate" ? "Rotate: click to set the angle, or type it in the angle box and press Enter. Esc cancels."
          : `${CAD.op.kind === "move" ? "Move" : "Copy"}: click the second point (Ortho F8, Snap F3). Esc cancels.`);
        if (CAD.op.kind === "rotate") $("#cadAngle").focus();
      } else {
        const { f } = opTransform(q), kind = CAD.op.kind;
        cadEnd();
        if (kind === "copy") cadCopyApply(f); else cadApply(f, sn);
      }
      return true;
    }
  };
  CAD.toolPoint = toolPoint;
  svg.addEventListener("pointerdown", (e) => {
    const p = svgPoint(svg, e);
    CAD.typed = false;
    if (toolPoint(p)) return;
    svg.setPointerCapture(e.pointerId);
    if (CAD.tool === "window" || CAD.tool === "select" || e.shiftKey && !cadPick(p)) {
      drag = { win: p, select: CAD.tool !== "window", add: e.shiftKey };
      rect = el("rect", { x: p.x, y: p.y, width: 0, height: 0, fill: "rgba(0,229,255,.08)", stroke: "#00e5ff", "stroke-width": 1, "vector-effect": "non-scaling-stroke", "stroke-dasharray": "4 3" }, overlay);
      return;
    }
    const hit = cadPick(p);
    // dragging a selected feature moves the selection (with snap and ortho)
    if (hit && CAD.sel.some((s) => cadKey(s) === cadKey(hit))) {
      const q = hit.type === "vertex" ? CAD.feats.lines.find((l) => l.id === hit.cable).pts[hit.i]
        : (() => { const f = CAD.feats.pts.find((x) => x.type === hit.type && x.id === hit.id); return f ? (f.true || [f.x, f.y]) : [p.x, p.y]; })();
      drag = { move: true, hit, sx: e.clientX, sy: e.clientY };
      CAD.op = { kind: "move", stage: "second", base: { x: q[0], y: q[1] }, moving: moving(), drag: true };
      return;
    }
    drag = { x: e.clientX, y: e.clientY, vx: CAD.vb[0], vy: CAD.vb[1], hit, add: e.shiftKey };
    svg.style.cursor = "grabbing";
  });
  svg.addEventListener("pointermove", (e) => {
    const p = svgPoint(svg, e), pr = CAD.proj;
    if (pr) {  // cursor position in metres and lat / lon (inverse of the local projection)
      const ll = pr.inverse(p.x, p.y);
      $("#lldCoord").textContent = `X ${p.x.toFixed(1)} m  Y ${(-p.y).toFixed(1)} m  ·  ${ll[0].toFixed(6)}, ${ll[1].toFixed(6)}`;
    }
    CAD.cursor = [p.x, p.y];
    if (CAD.cmd) { cadCmdHover(p, preview); return; }
    if (DRAW[CAD.tool]) { const { q, sn } = drawPoint(p); drawPreview(preview, q); if (sn) snapMark(sn); return; }
    if (CAD.op && CAD.op.kind !== "offset") { const { q, sn } = target(p); opPreview(q, sn); if (!drag) return; }
    if (!drag || drag.move) return;
    if (drag.win) {
      const x = Math.min(drag.win.x, p.x), y = Math.min(drag.win.y, p.y);
      rect.setAttribute("x", x); rect.setAttribute("y", y);
      rect.setAttribute("width", Math.abs(p.x - drag.win.x)); rect.setAttribute("height", Math.abs(p.y - drag.win.y));
      return;
    }
    const rc = svg.getBoundingClientRect(), k = Math.max(CAD.vb[2] / rc.width, CAD.vb[3] / rc.height);
    CAD.vb[0] = drag.vx - (e.clientX - drag.x) * k; CAD.vb[1] = drag.vy - (e.clientY - drag.y) * k; apply();
  });
  svg.addEventListener("dblclick", (e) => { if (["pline", "leader", "area"].includes(CAD.tool)) { e.preventDefault(); drawFinish(false); } });
  svg.addEventListener("pointerup", (e) => {
    const p = svgPoint(svg, e);
    if (drag?.move) {  // drag of a selected feature: a real drag moves, a click just keeps the selection
      const far = Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) > 4;
      if (far) { const { q, sn } = target(p), { f } = opTransform(q); cadEnd(); cadApply(f, sn); }
      else { cadEnd(); cadSelect([drag.hit], e.shiftKey); }
    } else if (drag?.win) {
      const w = Math.abs(p.x - drag.win.x), h = Math.abs(p.y - drag.win.y);
      rect.remove(); rect = null;
      const x0 = Math.min(p.x, drag.win.x), y0 = Math.min(p.y, drag.win.y), inside = (x, y) => x >= x0 && x <= x0 + w && y >= y0 && y <= y0 + h;
      if (drag.select) {  // everything wholly inside the box
        const F = CAD.feats;
        cadSelect([...F.pts.filter((q) => inside(q.x, q.y)).map((q) => ({ type: q.type, id: q.id })),
                   ...F.lines.filter((l) => l.pts.every((q) => inside(q[0], q[1]))).map((l) => ({ type: "cable", id: l.id })),
                   ...(F.marks || []).filter((M) => !M.locked && M.pts.every((q) => inside(q[0], q[1]))).map((M) => ({ type: "markup", id: M.id }))], drag.add);
      } else if (w > 1 && h > 1) { CAD.prevVb = [...CAD.vb]; CAD.vb = [x0, y0, w, h]; apply(); setCadTool(null); }
    } else if (drag && Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 4) {  // a click, not a pan
      if (drag.hit) cadSelect([drag.hit], drag.add);
      else if (!drag.add) { cadSelect([], false); msg(""); }
    }
    drag = null; svg.style.cursor = "";
  });
  drawCadSel();
  $("#lldFit").onclick = () => { CAD.prevVb = [...CAD.vb]; CAD.vb = [...CAD.home]; apply(); };
  $("#lldIn").onclick = () => zoomAt(CAD.vb[0] + CAD.vb[2] / 2, CAD.vb[1] + CAD.vb[3] / 2, 1 / 1.4);
  $("#lldOut").onclick = () => zoomAt(CAD.vb[0] + CAD.vb[2] / 2, CAD.vb[1] + CAD.vb[3] / 2, 1.4);
  CAD.clearMeas = () => { CAD.meas = []; drawMeas(); msg(""); };
}
function setCadTool(tool) {
  CAD.tool = CAD.tool === tool ? null : tool;
  if (CAD.tool) cadEnd();
  CAD.dpts = [];
  const g = $("#cadPreview"); if (g) g.innerHTML = "";
  $("#lldWin").classList.toggle("active", CAD.tool === "window");
  $("#lldMeasure").classList.toggle("active", CAD.tool === "measure");
  $("#cadSelect").classList.toggle("active", CAD.tool === "select");
  $$("[data-draw]").forEach((b) => b.classList.toggle("active", b.dataset.draw === CAD.tool));
  if (CAD.tool !== "measure" && CAD.clearMeas) CAD.clearMeas();
  $("#lldMsg").textContent = CAD.tool === "window" ? "Drag a box to zoom to it." : CAD.tool === "measure" ? "Click points to measure; distances are in metres."
    : CAD.tool === "select" ? "Click features (Shift adds) or drag a box: everything wholly inside it is selected."
    : DRAW[CAD.tool] ? `${DRAW[CAD.tool]} Esc stops.` : "";
}

// toolbar and keys of the drawing tab
$("#cadSelect").onclick = () => setCadTool("select");
$("#cadMove").onclick = () => (CAD.op?.kind === "move" ? (cadEnd(), cadMsg("")) : cadStart("move"));
$("#cadRotate").onclick = () => (CAD.op?.kind === "rotate" ? (cadEnd(), cadMsg("")) : cadStart("rotate"));
$("#cadDelete").onclick = () => cadDelete();
$("#cadCopy").onclick = () => (CAD.op?.kind === "copy" ? (cadEnd(), cadMsg("")) : cadStart("copy"));
$("#cadOffset").onclick = () => (CAD.op?.kind === "offset" ? (cadEnd(), cadMsg("")) : cadStart("offset"));
$$("[data-draw]").forEach((b) => { b.onclick = () => setCadTool(b.dataset.draw); });
$("#cadSheetMap").onchange = (e) => { S.D.info.sheet_map = e.target.value; changed(false);
  toast(e.target.value === "off" ? "No map on the PDF sheets and DXF" : "The LLD / HLD PDF sheets and the DXF + map ZIP will have this map"); };
$("#cadUndo").onclick = () => undo();
$("#cadRedo").onclick = () => redo();
const cadToggles = () => { $("#cadSnap").classList.toggle("active", !!PREFS.cad_snap); $("#cadOrtho").classList.toggle("active", !!PREFS.cad_ortho); };
const cadToggle = (k, name) => { PREFS[k] = !PREFS[k]; savePrefs(); cadToggles(); toast(`${name} ${PREFS[k] ? "on" : "off"}`); };
$("#cadSnap").onclick = () => cadToggle("cad_snap", "Snap");
$("#cadOrtho").onclick = () => cadToggle("cad_ortho", "Ortho");
$("#cadMap").onchange = (e) => { PREFS.cad_map = e.target.value; savePrefs(); drawBasemap(); };
$("#cadAngle").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.value !== "") { e.preventDefault(); CAD.applyAngle?.(+e.target.value); }
  if (e.key === "Escape") { cadEnd(); cadMsg(""); }
});
document.addEventListener("keydown", (e) => {
  if (activeTab() !== "lld" || ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName) || e.ctrlKey || e.metaKey) return;
  const k = e.key;
  if (DRAW[CAD.tool]) {  // while drawing: Enter finishes, C closes a polyline, Backspace drops the last point
    if (k === "Enter") { e.preventDefault(); return drawFinish(false); }
    if ((k === "c" || k === "C") && CAD.tool === "pline") return drawFinish(true);
    if (k === "Backspace" && CAD.dpts.length) { e.preventDefault(); CAD.dpts.pop(); return cadMsg(`${DRAW[CAD.tool]} ${CAD.dpts.length} point(s).`); }
  }
  if (k === "Delete" || k === "Backspace") { e.preventDefault(); cadDelete(); }
  else if (k === "Escape") {
    if (CAD.op) cadEnd(); else if (CAD.tool) setCadTool(CAD.tool); else { cadSelect([], false); const o = $("#cadOverlay"); if (o) o.innerHTML = ""; }
    cadMsg("");
  }
  else if (k === "m" || k === "M") cadStart("move");
  else if (k === "r" || k === "R") cadStart("rotate");
  else if (k === "F3") { e.preventDefault(); cadToggle("cad_snap", "Snap"); }
  else if (k === "F8") { e.preventDefault(); cadToggle("cad_ortho", "Ortho"); }
});

function renderLld() {
  if (!S.D) return;
  const P = typeof PREFS !== "undefined" ? PREFS : null;
  drawLld($("#lldBig"), true);
  if (P) {
    $("#lldLayers").innerHTML = CAD_LAYERS.filter(([k]) => k !== "grid").map(([k, t]) =>
      `<label><input type="checkbox" data-cl="${k}" ${P.cad_off.includes(k) ? "" : "checked"}> ${t}</label>`).join("");
    $$("#lldLayers [data-cl]").forEach((cb) => cb.addEventListener("change", () => {
      const k = cb.dataset.cl;
      P.cad_off = cb.checked ? P.cad_off.filter((x) => x !== k) : [...new Set([...P.cad_off, k])];
      savePrefs();
      $(`#lldBig [data-layer="${k}"]`)?.setAttribute("display", cb.checked ? "inline" : "none");
    }));
    $("#lldText").value = P.cad_text; $("#lldGrid").checked = P.cad_grid; $("#lldDark").checked = P.cad_dark;
    $("#cadMap").value = P.cad_map || "off"; cadToggles();
    $("#cadSheetMap").value = S.D.info.sheet_map || "off";
  }
}

function lldSvgText() {
  const svg = $("#lldBig svg");
  if (!svg) return null;
  const c = svg.cloneNode(true);
  c.setAttribute("width", 1600); c.setAttribute("height", Math.round(1600 * CAD.vb[3] / CAD.vb[2]));
  // edit aids and map tiles stay out of exports (tiles from other sites would also block the PNG export)
  for (const id of ["#cadOverlay", "#cadSel", "#cadPreview", "#cadBasemap"]) c.querySelector(id)?.remove();
  return new XMLSerializer().serializeToString(c);
}
function saveBlob(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}
function lldFileName(ext) {
  return `${(S.D.info.name || "project").replace(/[^\w-]+/g, "_")}_LLD_view.${ext}`;
}
$("#lldWin").onclick = () => setCadTool("window");
$("#lldMeasure").onclick = () => setCadTool("measure");
$("#lldText").addEventListener("input", (e) => { PREFS.cad_text = +e.target.value; savePrefs(); renderLld(); });
$("#lldGrid").addEventListener("change", (e) => { PREFS.cad_grid = e.target.checked; savePrefs(); $('#lldBig [data-layer="grid"]')?.setAttribute("display", e.target.checked ? "inline" : "none"); });
$("#lldDark").addEventListener("change", (e) => { PREFS.cad_dark = e.target.checked; savePrefs(); renderLld(); });
$("#lldSvg").onclick = () => { const t = lldSvgText(); if (t) saveBlob(new Blob([t], { type: "image/svg+xml" }), lldFileName("svg")); };
$("#lldPng").onclick = () => {
  const t = lldSvgText();
  if (!t) return;
  const img = new Image();
  img.onload = () => {
    const cv = document.createElement("canvas");
    cv.width = img.width || 1600; cv.height = img.height || 1000;
    cv.getContext("2d").drawImage(img, 0, 0);
    cv.toBlob((b) => saveBlob(b, lldFileName("png")), "image/png");
  };
  img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(t);
};
$("#lldPrint").onclick = () => { document.body.classList.add("printlld"); setTimeout(() => window.print(), 200); };


// ---------------------------------------------------------------------------
// Splicing schematic: main cable -> enclosure -> PON (1st stage) -> FATs (2nd stage) -> homes
// ---------------------------------------------------------------------------
function ponNodes() {
  const ids = new Set(S.D.splitters.filter((s) => s.stage === 1).map((s) => s.node));
  S.D.nodes.filter((n) => n.kind === "PON").forEach((n) => ids.add(n.id));
  return [...ids];
}

function spliceSchematic(sp, box, select) {
  const D = S.D, pons = ponNodes();
  const cur = select.value;
  select.innerHTML = pons.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join("");
  if (cur && pons.includes(cur)) select.value = cur;
  select.onchange = () => spliceSchematic(sp, box, select);
  if (!pons.length) { box.innerHTML = `<p class="muted">No PON / first-stage splitter yet. Place a PON or run Auto-design, then Auto-allocate fibres.</p>`; return; }
  const pon = select.value;
  // FATs whose fibre trace to the OLT passes through this PON
  const fed = [];
  for (const [label, tr] of Object.entries(sp.traces)) {
    if (!tr.steps.some((s) => s.node === pon)) continue;
    const fat = tr.steps[0]?.node;
    const cable = (tr.steps[0]?.to || "").replace(/\s*\(.*\)$/, "");
    const spl = (tr.steps[0]?.from || "").replace(/ IN$/, "");
    fed.push({ fat, spl, label, cable, ok: tr.ok });
  }
  const unfed = Object.entries(sp.traces).filter(([, tr]) => !tr.ok).length;
  const s1 = D.splitters.find((s) => s.node === pon && s.stage === 1);
  const feeders = D.cables.filter((c) => c.status === "proposed" && (c.from_node === pon || c.to_node === pon || c.path.some((v) => v.node === pon)));
  const main = feeders.find((c) => c.kind === "main") || feeders[0];
  const root = D.info.interception_node || D.nodes.find((n) => n.status === "existing" && ["POP", "ENCLOSURE"].includes(n.kind))?.id || "Feed";
  const hp = (fid) => D.homes.filter((h) => h.fat === fid || (h.extra_fats || []).includes(fid)).reduce((a, h) => a + h.units, 0);
  const rows = Math.max(fed.length, 2), H = rows * 58 + 70, W = 760;
  const yc = 30 + rows * 29;
  const colours = sp.colours.map((c) => c[1]);
  let out = `<svg xmlns="${SVGNS}" width="100%" style="max-width:${W}px;min-width:520px" viewBox="0 0 ${W} ${H}" font-family="Arial, sans-serif" font-size="11">
    <defs><marker id="arw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10z" fill="#c2185b"/></marker></defs>`;
  // main cable as a bundle of coloured fibres
  out += `<text x="10" y="${yc - 30}" font-weight="700">Main cable</text><text x="10" y="${yc - 17}">${esc(main ? `${main.id} ${main.cores}C` : "-")}</text>`;
  colours.slice(0, 8).forEach((c, k) => { out += `<rect x="10" y="${yc - 10 + k * 3}" width="84" height="3" fill="${c}"/>`; });
  out += `<line x1="96" y1="${yc}" x2="140" y2="${yc}" stroke="#7b1fa2" stroke-width="2" marker-end="url(#arw)"/>`;
  out += `<rect x="142" y="${yc - 16}" width="96" height="32" rx="5" fill="#455a64"/><text x="190" y="${yc - 22}" text-anchor="middle" font-weight="700">Splice enclosure</text>
    <text x="190" y="${yc + 4}" text-anchor="middle" fill="#fff">${esc(root)}</text>`;
  out += `<line x1="238" y1="${yc}" x2="290" y2="${yc}" stroke="#7b1fa2" stroke-width="2" marker-end="url(#arw)"/>`;
  out += `<rect x="292" y="${yc - 22}" width="80" height="44" rx="5" fill="#1e88e5"/><text x="332" y="${yc + 6}" text-anchor="middle" fill="#fff" font-size="17" font-weight="700">${esc(s1 ? `1x${s1.outputs}` : "1x8")}</text>
    <text x="332" y="${yc - 28}" text-anchor="middle" font-weight="700">${esc(pon)}</text><text x="332" y="${yc + 36}" text-anchor="middle" fill="#555">1st stage splitter</text>`;
  fed.forEach((f, k) => {
    const y = 30 + k * 58 + 29;
    const s2 = D.splitters.find((s) => s.id === f.spl) || D.splitters.find((s) => s.node === f.fat && s.stage === 2);
    const twin = fed.filter((x) => x.fat === f.fat).length > 1;
    out += `<path d="M372,${yc} C420,${yc} 430,${y} 488,${y}" stroke="#e53935" stroke-width="2" fill="none" marker-end="url(#arw)"/>`;
    out += `<text x="430" y="${y - 6}" fill="#666" font-size="9.5">${esc(f.cable)}</text>`;
    out += `<rect x="490" y="${y - 15}" width="66" height="30" rx="4" fill="#43a047"/><text x="523" y="${y + 5}" text-anchor="middle" fill="#fff" font-size="14" font-weight="700">${esc(s2 ? `1x${s2.outputs}` : "-")}</text>`;
    out += `<text x="523" y="${y - 20}" text-anchor="middle" font-weight="700">${esc(f.fat)}${twin ? ` · ${esc(f.spl)}` : ""}</text>`;
    out += `<line x1="556" y1="${y}" x2="600" y2="${y}" stroke="#333" stroke-width="1.5" marker-end="url(#arw)"/><text x="604" y="${y + 4}">To MDUs / homes (${hp(f.fat)} HPs)</text>`;
  });
  if (!fed.length) out += `<text x="400" y="${yc + 4}" fill="#c62828">No FAT is fed through ${esc(pon)} yet - run Auto-allocate fibres.</text>`;
  out += `<text x="10" y="${H - 22}" font-weight="700">Fibre core colours</text>`;
  colours.forEach((c, k) => { out += `<circle cx="${130 + k * 34}" cy="${H - 26}" r="5" fill="${c}" stroke="#333"/><text x="${138 + k * 34}" y="${H - 22}" font-size="9.5">${k + 1}</text>`; });
  if (unfed) out += `<text x="${W - 10}" y="${H - 6}" text-anchor="end" fill="#c62828" font-size="10">${unfed} FAT splitter(s) in the project are not fed</text>`;
  box.innerHTML = out + `</svg>`;
}

async function renderSplicingSchematic() {
  const sp = await fresh("spschem", () => api(`/api/projects/${S.pid}/splicing`));
  if (sp) spliceSchematic(sp, $("#spSchematic"), $("#spPon"));
}

renderSteps();
