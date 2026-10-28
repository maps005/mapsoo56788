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
  const secs = [["Introduction", i.introduction], ["Survey findings", i.findings], ["Proposed solution", i.proposed_solution],
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
  const files = t && !t.fibre_tools  // other sectors: no splicing diagram; the pole summary is their schedule
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
  const kx = Math.cos(lat0 * Math.PI / 180) * 111320, ky = 110540;
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
  ["labels", "Equipment labels"], ["tags", "Cable tags"], ["grid", "Grid"]];
const CAD = { home: null, vb: null, tool: null, meas: [], proj: null };

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
  const r = span / (big ? 320 : 200), stroke = (w) => ({ "stroke-width": w, "vector-effect": "non-scaling-stroke", fill: "none" });
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
  for (const k of ["boundary", "drops", "existing", "main", "spur", "buildings", "poles", "equipment", "labels", "tags"]) Lg[k] = layer(k);
  if (D.info.boundary.length) el("polygon", { points: D.info.boundary.map((b) => xy(b[0], b[1]).join(",")).join(" "), stroke: dark ? "#cfd8dc" : "#555", "stroke-dasharray": "6 4", ...stroke(1) }, Lg.boundary);
  const fats = Object.fromEntries(D.nodes.filter((n) => n.kind === "FAT").map((n) => [n.id, n]));
  for (const h of D.homes) {
    const f = fats[h.fat];
    if (f && okc(h) && okc(f)) { const a = xy(h.lat, h.lon), b = xy(f.lat, f.lon); el("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], stroke: "#5e6b78", "stroke-dasharray": "3 3", ...stroke(0.8) }, Lg.drops); }
  }
  for (const c of byDrawOrder(D.cables)) {
    if (c.path.length < 2) continue;
    const lay = c.status === "existing" ? Lg.existing : c.kind === "main" ? Lg.main : Lg.spur;
    el("polyline", { points: c.path.map((v) => xy(v.lat, v.lon).join(",")).join(" "),
      stroke: c.status === "existing" ? "#7d8a96" : c.kind === "main" ? "#ff2a2a" : c.kind === "spur" ? (dark ? "#ffd60a" : "#d4a300") : "#3ddc84",
      ...stroke(c.status === "existing" ? 1.2 : c.kind === "main" ? 3.4 : 1.6) }, lay);
  }
  for (const h of D.homes) {
    if (!okc(h)) continue;
    const [x, y] = xy(h.lat, h.lon), s = r * (h.kind === "mdu" ? 2.6 : 1.6);
    el("rect", { x: x - s, y: y - s * 0.7, width: 2 * s, height: 1.4 * s, stroke: "#e040fb", ...stroke(1) }, Lg.buildings);
  }
  for (const p of D.poles) {
    if (!okc(p)) continue;
    const [x, y] = xy(p.lat, p.lon);
    el("circle", { cx: x, cy: y, r: r * 0.9, fill: "#2f80ff", stroke: p.status === "proposed" ? fg : "none", "stroke-width": 1, "vector-effect": "non-scaling-stroke" }, Lg.poles);
  }
  const ts = r * (big ? 2.4 : 3.2) * (big ? P.cad_text : 1);
  Lg.labels.setAttribute("font-family", "Arial, sans-serif"); Lg.labels.setAttribute("font-size", ts); Lg.labels.setAttribute("fill", fg);
  for (const n of D.nodes) {
    if (!okc(n)) continue;
    const [x, y] = xy(n.lat, n.lon), s = r * 2.2;
    const col = { FAT: "#ff2a2a", JB: "#c77dff", ENCLOSURE: "#ff9f1c", PR_ENCLOSURE: "#ff9f1c", PON: "#ff4fd8", POP: "#a06cd5", SLACK: "#3ddc84" }[n.kind];
    const g = Lg.equipment;
    if (n.kind === "FAT") el("polygon", { points: `${x},${y - s} ${x + s},${y + s * 0.8} ${x - s},${y + s * 0.8}`, fill: col }, g);
    else if (n.kind === "JB") el("polygon", { points: `${x},${y - s} ${x + s},${y} ${x},${y + s} ${x - s},${y}`, fill: col }, g);
    else if (n.kind === "PON") el("polygon", { points: star(x, y, s * 1.2, s * 0.5), fill: col }, g);
    else if (n.kind === "SLACK") el("circle", { cx: x, cy: y, r: s * 0.8, stroke: col, ...stroke(1.5) }, g);
    else el("rect", { x: x - s * 0.9, y: y - s * 0.9, width: s * 1.8, height: s * 1.8, fill: col }, g);
    if (big || ["POP", "PON", "ENCLOSURE"].includes(n.kind)) { const t = el("text", { x: x + s * 1.3, y: y - s * 0.4 }, Lg.labels); t.textContent = n.id; }
  }
  if (big) {
    Lg.tags.setAttribute("font-family", "Arial, sans-serif");
    for (const c of D.cables) {  // cable tags at mid-route
      if (c.status !== "proposed" || c.path.length < 2) continue;
      const v = c.path[Math.floor(c.path.length / 2)], [x, y] = xy(v.lat, v.lon);
      const t = el("text", { x: x + r, y: y + r * 3, fill: c.kind === "main" ? "#ff6b6b" : (dark ? "#ffe680" : "#9a7400"), "font-size": r * 2 * P.cad_text }, Lg.tags);
      t.textContent = `${c.id} ${c.cores}C`;
    }
  }
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
  if (big) { CAD.proj = pr; cadTools(svg); }
}

function star(cx, cy, ro, ri) {
  const p = [];
  for (let k = 0; k < 10; k++) { const a = Math.PI / 5 * k - Math.PI / 2, rr = k % 2 ? ri : ro; p.push(`${cx + rr * Math.cos(a)},${cy + rr * Math.sin(a)}`); }
  return p.join(" ");
}

// ---- CAD tools: zoom / pan / window / measure / coordinates ---------------
function svgPoint(svg, e) {
  const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
  return pt.matrixTransform(svg.getScreenCTM().inverse());
}
function cadTools(svg) {
  const home = svg.getAttribute("viewBox").split(" ").map(Number);
  CAD.home = home; CAD.vb = [...home]; CAD.meas = [];
  const apply = () => svg.setAttribute("viewBox", CAD.vb.join(" "));
  const zoomAt = (mx, my, f) => { const v = CAD.vb; CAD.vb = [mx - (mx - v[0]) * f, my - (my - v[1]) * f, v[2] * f, v[3] * f]; apply(); };
  const msg = (t) => { $("#lldMsg").textContent = t; };
  const overlay = svg.querySelector("#cadOverlay");
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
  svg.addEventListener("pointerdown", (e) => {
    const p = svgPoint(svg, e);
    if (CAD.tool === "measure") { CAD.meas.push(p); drawMeas(); return; }
    svg.setPointerCapture(e.pointerId);
    if (CAD.tool === "window") {
      drag = { win: p };
      rect = el("rect", { x: p.x, y: p.y, width: 0, height: 0, fill: "rgba(0,229,255,.08)", stroke: "#00e5ff", "stroke-width": 1, "vector-effect": "non-scaling-stroke", "stroke-dasharray": "4 3" }, overlay);
      return;
    }
    drag = { x: e.clientX, y: e.clientY, vx: CAD.vb[0], vy: CAD.vb[1] };
    svg.style.cursor = "grabbing";
  });
  svg.addEventListener("pointermove", (e) => {
    const p = svgPoint(svg, e), pr = CAD.proj;
    if (pr) {  // cursor position in metres and lat / lon (inverse of the local projection)
      const ll = pr.inverse(p.x, p.y);
      $("#lldCoord").textContent = `X ${p.x.toFixed(1)} m  Y ${(-p.y).toFixed(1)} m  ·  ${ll[0].toFixed(6)}, ${ll[1].toFixed(6)}`;
    }
    if (!drag) return;
    if (drag.win) {
      const x = Math.min(drag.win.x, p.x), y = Math.min(drag.win.y, p.y);
      rect.setAttribute("x", x); rect.setAttribute("y", y);
      rect.setAttribute("width", Math.abs(p.x - drag.win.x)); rect.setAttribute("height", Math.abs(p.y - drag.win.y));
      return;
    }
    const rc = svg.getBoundingClientRect(), k = Math.max(CAD.vb[2] / rc.width, CAD.vb[3] / rc.height);
    CAD.vb[0] = drag.vx - (e.clientX - drag.x) * k; CAD.vb[1] = drag.vy - (e.clientY - drag.y) * k; apply();
  });
  svg.addEventListener("pointerup", (e) => {
    if (drag?.win) {
      const p = svgPoint(svg, e), w = Math.abs(p.x - drag.win.x), h = Math.abs(p.y - drag.win.y);
      rect.remove(); rect = null;
      if (w > 1 && h > 1) { CAD.vb = [Math.min(p.x, drag.win.x), Math.min(p.y, drag.win.y), w, h]; apply(); }
      setCadTool(null);
    }
    drag = null; svg.style.cursor = "";
  });
  $("#lldFit").onclick = () => { CAD.vb = [...CAD.home]; apply(); };
  $("#lldIn").onclick = () => zoomAt(CAD.vb[0] + CAD.vb[2] / 2, CAD.vb[1] + CAD.vb[3] / 2, 1 / 1.4);
  $("#lldOut").onclick = () => zoomAt(CAD.vb[0] + CAD.vb[2] / 2, CAD.vb[1] + CAD.vb[3] / 2, 1.4);
  CAD.clearMeas = () => { CAD.meas = []; drawMeas(); msg(""); };
}
function setCadTool(tool) {
  CAD.tool = CAD.tool === tool ? null : tool;
  $("#lldWin").classList.toggle("active", CAD.tool === "window");
  $("#lldMeasure").classList.toggle("active", CAD.tool === "measure");
  if (CAD.tool !== "measure" && CAD.clearMeas) CAD.clearMeas();
  $("#lldMsg").textContent = CAD.tool === "window" ? "Drag a box to zoom to it." : CAD.tool === "measure" ? "Click points to measure; distances are in metres." : "";
}

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
  }
}

function lldSvgText() {
  const svg = $("#lldBig svg");
  if (!svg) return null;
  const c = svg.cloneNode(true);
  c.setAttribute("width", 1600); c.setAttribute("height", Math.round(1600 * CAD.vb[3] / CAD.vb[2]));
  c.querySelector("#cadOverlay")?.remove();
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
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && activeTab() === "lld" && CAD.tool) setCadTool(null); });


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
