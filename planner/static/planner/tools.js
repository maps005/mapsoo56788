"use strict";
/* Planner tools that CAD / GIS users expect: undo and redo, measure distance and area, find a feature or go to
   coordinates, snapping to poles and equipment, grip editing of cable points, labels, fullscreen, print,
   keyboard shortcuts and user settings. Loaded after app.js and overview.js. */

// ---------------------------------------------------------------------------
// Settings (stored per user in this browser) and auto-design options
// ---------------------------------------------------------------------------
const PREF_DEFAULTS = { snap_m: 8, labels: true, drops: true, cad_dark: true, cad_grid: false, cad_text: 1, cad_off: [],
  cad_map: "off", cad_snap: true, cad_ortho: false };
const PREFS = (() => {
  try { return { ...PREF_DEFAULTS, ...JSON.parse(localStorage.getItem("ftth.prefs") || "{}") }; }
  catch (_) { return { ...PREF_DEFAULTS }; }
})();
function savePrefs() { try { localStorage.setItem("ftth.prefs", JSON.stringify(PREFS)); } catch (_) { /* storage unavailable */ } }

const AD_FIELDS = [  // [option, label, default, min, max, step]
  ["take_rate", "Take rate (share of HPs given a splitter port)", 0.5, 0.05, 1, 0.05],
  ["indoor_fat_ports", "Indoor FAT ports (MDU)", 24, 4, 48, 1],
  ["outdoor_fat_ports", "Outdoor FAT ports (SDU / shops)", 16, 4, 48, 1],
  ["small_premise_max_hp", "Premises up to this many HPs share outdoor FATs", 4, 1, 24, 1],
  ["outdoor_cluster_radius_m", "Outdoor FAT cluster radius (m)", 60, 10, 300, 5],
  ["max_span_m", "Longest aerial span (m)", 65, 20, 150, 1],
  ["new_pole_spacing_m", "New pole spacing (m)", 45, 15, 100, 1],
  ["drop_to_pole_m", "FAT to nearest pole, else new poles (m)", 60, 5, 300, 5],
  ["branch_closure_gap_m", "Extra distance before a branch closure is added (m)", 30, 0, 300, 5],
  ["merge_closures_m", "Share branch closures closer than (m)", 60, 0, 300, 5],
  ["slack_interval_m", "Slack loop on the 48C every (m, 0 = none)", 200, 0, 1000, 10],
  // blank default: taken from the project's design style
  ["coverage_radius_m", "Coverage: premises within (m) of a FAT's pole", null, 20, 1000, 10],
  ["coverage_take_rate", "Coverage: take rate (share of HPs needing a port)", null, 0.005, 1, 0.001],
  ["fat_split", "FAT splitter outputs (8 or 16)", null, 4, 64, 4],
  ["pon_split", "PON splitter outputs (8)", null, 2, 32, 2],
  ["spur_cores", "Distribution cable cores (12 or 24)", null, 6, 96, 6],
];
function autoDesignOptions() {
  try { return JSON.parse(localStorage.getItem("ftth.autodesign") || "{}"); } catch (_) { return {}; }
}

// ---------------------------------------------------------------------------
// Undo / redo: a snapshot of the design after every change (server-controlled approval fields are kept)
// ---------------------------------------------------------------------------
const HIST = { undo: [], redo: [], snap: null, pid: null, max: 100 };
const SERVER_INFO = ["survey_status", "survey_approved_by", "survey_approved_at", "survey_fingerprint", "design_status"];

function historyRecord() {
  if (!S.D) return;
  const now = JSON.stringify(S.D);
  if (HIST.pid !== S.pid) { Object.assign(HIST, { undo: [], redo: [], pid: S.pid, snap: now }); return undoButtons(); }
  if (HIST.snap && now !== HIST.snap) {
    HIST.undo.push(HIST.snap);
    if (HIST.undo.length > HIST.max) HIST.undo.shift();
    HIST.redo = [];
  }
  HIST.snap = now;
  undoButtons();
}
function restoreSnapshot(json) {
  const keep = Object.fromEntries(SERVER_INFO.map((k) => [k, S.D.info[k]]));
  S.D = JSON.parse(json);
  Object.assign(S.D.info, keep);  // undo never approves or un-approves anything
  HIST.snap = JSON.stringify(S.D);
  S.sel = null; S.draw = [];
  S.dirty = true; clearTimeout(S.timer); S.timer = setTimeout(save, 300);
  renderAll(); undoButtons();
}
function undo() { if (!HIST.undo.length) return toast("Nothing to undo"); HIST.redo.push(HIST.snap); restoreSnapshot(HIST.undo.pop()); toast("Undone"); }
function redo() { if (!HIST.redo.length) return toast("Nothing to redo"); HIST.undo.push(HIST.snap); restoreSnapshot(HIST.redo.pop()); toast("Redone"); }
function undoButtons() {
  const u = $("#btnUndo"), r = $("#btnRedo");
  if (u) { u.disabled = !HIST.undo.length; u.title = `Undo (Ctrl+Z) - ${HIST.undo.length} step(s)`; }
  if (r) { r.disabled = !HIST.redo.length; r.title = `Redo (Ctrl+Y) - ${HIST.redo.length} step(s)`; }
}

// ---------------------------------------------------------------------------
// Snapping: free clicks near a pole or equipment use that feature
// ---------------------------------------------------------------------------
function snapTarget(lat, lon, kinds = ["node", "pole"]) {
  if (!S.D || !PREFS.snap_m) return null;
  let best = null;
  for (const type of kinds) {
    for (const o of type === "node" ? S.D.nodes : S.D.poles) {
      if (!okc(o)) continue;
      const d = hav(lat, lon, o.lat, o.lon);
      if (d <= PREFS.snap_m && (!best || d < best.d - (type === "node" ? 0.5 : 0))) best = { type, obj: o, d };
    }
  }
  return best;
}

// ---------------------------------------------------------------------------
// Measure distance and area (like Google Earth's ruler)
// ---------------------------------------------------------------------------
const MEAS = { pts: [], layer: L.layerGroup().addTo(map) };
function measureClick(lat, lon) { MEAS.pts.push([lat, lon]); drawMeasure(); }
function clearMeasure() { MEAS.pts = []; drawMeasure(); }
function areaM2(pts) {
  const lat0 = pts[0][0] * Math.PI / 180, R = 6371008.8;
  const xy = pts.map(([la, lo]) => [lo * Math.PI / 180 * R * Math.cos(lat0), la * Math.PI / 180 * R]);
  let a = 0;
  for (let i = 0; i < xy.length; i++) { const [x1, y1] = xy[i], [x2, y2] = xy[(i + 1) % xy.length]; a += x1 * y2 - x2 * y1; }
  return Math.abs(a / 2);
}
function drawMeasure() {
  MEAS.layer.clearLayers();
  if (!MEAS.pts.length) return;
  L.polyline(MEAS.pts, { color: "#00e5ff", weight: 3, dashArray: "6 4", interactive: false }).addTo(MEAS.layer);
  let tot = 0;
  MEAS.pts.forEach((p, i) => {
    if (i) tot += hav(MEAS.pts[i - 1][0], MEAS.pts[i - 1][1], p[0], p[1]);
    L.circleMarker(p, { radius: 4, color: "#00e5ff", weight: 2, fillOpacity: 1, interactive: false }).addTo(MEAS.layer)
      .bindTooltip(i ? `${fmt(tot, 1)} m` : "start", { permanent: true, direction: "top", className: "measlbl" });
  });
  const area = MEAS.pts.length >= 3 ? ` · closed area ${fmt(areaM2(MEAS.pts))} m²` : "";
  $("#hint").textContent = `Measured ${fmt(tot, 1)} m over ${MEAS.pts.length - 1} segment(s)${area}. Click to add points; Esc clears.`;
}

// ---------------------------------------------------------------------------
// Grip editing of a selected cable: drag points (snap to poles / equipment), drag "+" to insert, right-click to remove
// ---------------------------------------------------------------------------
const gripLayer = L.layerGroup().addTo(map);
const gripIcon = (cls, txt = "") => L.divIcon({ className: "", html: `<div class="grip ${cls}">${txt}</div>`, iconSize: [14, 14], iconAnchor: [7, 7] });
function vertexAt(lat, lon) {
  const sn = snapTarget(lat, lon);
  if (!sn) return { lat, lon, pole: null, node: null, crossing: false };
  const o = sn.obj;
  return { lat: o.lat, lon: o.lon, pole: sn.type === "pole" ? o.id : (o.pole || null), node: sn.type === "node" ? o.id : null, crossing: false };
}
function drawOverlays() {
  gripLayer.clearLayers();
  drawMeasure();
  document.body.classList.toggle("nolabels", !PREFS.labels);
  if (!PREFS.drops && typeof G !== "undefined") G.drops.clearLayers();
  if (!S.D || S.mode !== "select" || S.sel?.type !== "cable") return;
  const c = S.D.cables.find((x) => x.id === S.sel.id);
  if (!c) return;
  const ends = () => { c.from_node = c.path[0].node || null; c.to_node = c.path[c.path.length - 1].node || null; };
  c.path.forEach((v, i) => {
    const m = L.marker([v.lat, v.lon], { draggable: true, icon: gripIcon(v.pole || v.node ? "on" : ""), zIndexOffset: 2000 }).addTo(gripLayer);
    m.bindTooltip(`Point ${i + 1}${v.pole ? " · pole " + esc(v.pole) : ""}${v.node ? " · " + esc(v.node) : ""}<br>Drag to move (snaps to poles), right-click to remove`, { direction: "top" });
    m.on("click", (e) => L.DomEvent.stopPropagation(e));
    m.on("dragend", () => {
      const { lat, lng } = m.getLatLng();
      Object.assign(v, vertexAt(lat, lng), { crossing: v.crossing });
      ends(); changed();
    });
    m.on("contextmenu", (e) => {
      L.DomEvent.stopPropagation(e); L.DomEvent.preventDefault(e);
      if (c.path.length <= 2) return toast("A cable needs at least 2 points");
      c.path.splice(i, 1); ends(); changed();
    });
  });
  for (let i = 1; i < c.path.length; i++) {
    const a = c.path[i - 1], b = c.path[i];
    const m = L.marker([(a.lat + b.lat) / 2, (a.lon + b.lon) / 2], { draggable: true, icon: gripIcon("mid", "+"), zIndexOffset: 1900 }).addTo(gripLayer);
    m.bindTooltip("Drag to add a point here (snaps to poles)", { direction: "top" });
    m.on("click", (e) => L.DomEvent.stopPropagation(e));
    m.on("dragend", () => { const { lat, lng } = m.getLatLng(); c.path.splice(i, 0, vertexAt(lat, lng)); changed(); });
  }
}

// ---------------------------------------------------------------------------
// Find a feature or go to coordinates; cursor coordinates and scale bar
// ---------------------------------------------------------------------------
L.control.scale({ imperial: false, position: "bottomleft" }).addTo(map);
const CoordBox = L.Control.extend({
  onAdd() { const d = L.DomUtil.create("div", "coordbox"); d.textContent = "-"; return d; },
});
const coordBox = new CoordBox({ position: "bottomleft" }).addTo(map);
map.on("mousemove", (e) => { coordBox.getContainer().textContent = `${e.latlng.lat.toFixed(6)}, ${e.latlng.lng.toFixed(6)}`; });

let gotoMarker = null;
function findFeature(q) {
  q = (q || "").trim();
  if (!q || !S.D) return;
  const m = q.match(/^\s*(-?\d+(?:\.\d+)?)\s*[,; ]\s*(-?\d+(?:\.\d+)?)\s*$/);
  if (m) {
    let lat = +m[1], lon = +m[2];
    if (Math.abs(lat) > 90 && Math.abs(lon) <= 90) [lat, lon] = [lon, lat];
    if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return toast("Not valid coordinates");
    showTab("map");
    setTimeout(() => {
      map.setView([lat, lon], Math.max(map.getZoom(), 18));
      if (gotoMarker) gotoMarker.remove();
      gotoMarker = L.marker([lat, lon]).addTo(map).bindTooltip(`${lat.toFixed(6)}, ${lon.toFixed(6)}`, { permanent: true }).openTooltip();
    }, 80);
    return;
  }
  const lc = q.toLowerCase();
  const all = ["poles", "homes", "nodes", "cables"].flatMap((c) => S.D[c].map((x) => ({ id: x.id, name: x.name || "" })));
  const hit = all.find((x) => x.id.toLowerCase() === lc) || all.find((x) => x.id.toLowerCase().includes(lc) || x.name.toLowerCase().includes(lc));
  if (!hit) return toast(`Nothing called "${q}"`);
  goTo(hit.id);
}
function refreshFindList() {
  const dl = $("#findList");
  if (!dl || !S.D) return;
  dl.innerHTML = ["poles", "homes", "nodes", "cables"].flatMap((c) => S.D[c].map((x) =>
    `<option value="${esc(x.id)}">${esc(x.name || c.slice(0, -1))}</option>`)).join("");
}

// ---------------------------------------------------------------------------
// Toolbar buttons, fullscreen, print, shortcuts
// ---------------------------------------------------------------------------
function toggleFullscreen(force) {
  const on = document.body.classList.toggle("mapfull", force);
  $("#btnFull").classList.toggle("active", on);
  setTimeout(() => map.invalidateSize(), 60);
}
function printMap() {
  showTab("map");
  document.body.classList.add("printmap");
  setTimeout(() => { map.invalidateSize(); window.print(); }, 300);
}
window.addEventListener("afterprint", () => { document.body.classList.remove("printmap", "printlld"); setTimeout(() => map.invalidateSize(), 60); });

$("#btnUndo").onclick = undo;
$("#btnRedo").onclick = redo;
$("#btnLabels").onclick = () => { PREFS.labels = !PREFS.labels; savePrefs(); $("#btnLabels").classList.toggle("active", PREFS.labels); drawOverlays(); };
$("#btnLabels").classList.toggle("active", PREFS.labels);
$("#btnFull").onclick = () => toggleFullscreen();
$("#btnPrint").onclick = printMap;
$("#btnHelp").onclick = () => $("#helpDlg").showModal();
$("#helpClose").onclick = () => $("#helpDlg").close();
$("#setKeys").onclick = () => $("#helpDlg").showModal();
$("#findBox").addEventListener("change", (e) => findFeature(e.target.value));
$("#findBox").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); findFeature(e.target.value); } });
$("#findBox").addEventListener("focus", refreshFindList);

const KEY_MODES = { s: "select", p: "pole", h: "home", e: "node", c: "cable", b: "boundary", m: "measure" };
document.addEventListener("keydown", (e) => {
  const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName);
  const mod = e.ctrlKey || e.metaKey;
  if (mod && !typing && e.key.toLowerCase() === "z") { e.preventDefault(); return e.shiftKey ? redo() : undo(); }
  if (mod && !typing && e.key.toLowerCase() === "y") { e.preventDefault(); return redo(); }
  if (typing || mod || e.altKey) return;
  if (e.key === "Escape") { clearMeasure(); if (document.body.classList.contains("mapfull")) toggleFullscreen(false); }
  if (e.key === "?") return $("#helpDlg").showModal();
  if (activeTab() !== "map") return;
  const k = e.key.toLowerCase();
  if (KEY_MODES[k]) return setMode(KEY_MODES[k]);
  if (k === "/") { e.preventDefault(); return $("#findBox").focus(); }
  if (k === "l") return $("#btnLabels").click();
  if (k === "f") return toggleFullscreen();
});

// ---------------------------------------------------------------------------
// Settings tab
// ---------------------------------------------------------------------------
const TITLE_FIELDS = [["name", "Project name"], ["client", "Client"], ["company", "Company (title block)"], ["drawing_no", "Drawing no."],
  ["area", "Area"], ["region", "Region"], ["zone", "Zone"], ["cluster", "Cluster"], ["currency", "Currency"],
  ["lead_planner", "Lead planner"], ["planned_by", "Planned by"], ["drawn_by", "Drawn by"], ["checked_by", "Checked by"],
  ["approved_by", "Approved by (title block)"]];

function renderSettings() {
  if (!S.D) return;
  const i = S.D.info;
  $("#setTitle").innerHTML = TITLE_FIELDS.map(([f, t]) =>
    `<label>${t}<input data-si="${f}" value="${esc(i[f])}"></label>`).join("");
  $$("#setTitle [data-si]").forEach((inp) => inp.addEventListener("change", () => {
    i[inp.dataset.si] = inp.value; changed(false);
    if (inp.dataset.si === "name") { const o = $(`#projectSelect option[value="${S.pid}"]`); if (o) o.textContent = inp.value; }
  }));
  const ad = autoDesignOptions();
  renderStandards();
  const style = S.D.info.design_style || "per_premise";
  $("#setAuto").innerHTML = `<label>Design style (saved with the project)<select id="adStyle">
      <option value="per_premise" ${style === "per_premise" ? "selected" : ""}>Per premise: every homepass gets a FAT port, 12C spurs, 1x8 splitters (Infinity)</option>
      <option value="coverage" ${style === "coverage" ? "selected" : ""}>Coverage: outdoor FATs on poles at a take rate, 24C distribution, 1x16 splitters (Kabiria)</option>
    </select></label>
    <label>Other interception points (existing closures / POPs, comma separated)<input id="adRoots" value="${esc((S.D.info.interception_nodes || []).join(", "))}" placeholder="e.g. EX ENC 02"></label>` +
    AD_FIELDS.map(([k, t, def, min, max, step]) =>
      `<label>${t}<input type="number" data-ad="${k}" min="${min}" max="${max}" step="${step}" value="${ad[k] ?? def ?? ""}" placeholder="from the design style"></label>`).join("");
  $("#adStyle").addEventListener("change", (e) => { S.D.info.design_style = e.target.value; changed(false); toast("Design style saved with the project"); });
  $("#adRoots").addEventListener("change", (e) => {
    const ids = e.target.value.split(",").map((x) => x.trim()).filter(Boolean);
    const bad = ids.filter((x) => !S.D.nodes.some((n) => n.id === x));
    if (bad.length) toast(`Not found in this project: ${bad.join(", ")}`, 6000);
    S.D.info.interception_nodes = ids.filter((x) => !bad.includes(x)); changed(false);
  });
  const p = PREFS;
  $("#setPrefs").innerHTML = `
    <label>Snap to poles / equipment within (m, 0 = off)<input type="number" id="pSnap" min="0" max="50" step="1" value="${p.snap_m}"></label>
    <label class="inline"><input type="checkbox" id="pLabels" ${p.labels ? "checked" : ""}> Show equipment labels on the map</label>
    <label class="inline"><input type="checkbox" id="pDrops" ${p.drops ? "checked" : ""}> Show drop links (home → FAT)</label>
    <label class="inline"><input type="checkbox" id="pDark" ${p.cad_dark ? "checked" : ""}> CAD view: black background (AutoCAD model space)</label>
    <label class="inline"><input type="checkbox" id="pGrid" ${p.cad_grid ? "checked" : ""}> CAD view: show grid</label>
    <label>CAD view text size<input type="range" id="pText" min="0.5" max="2.5" step="0.1" value="${p.cad_text}"></label>`;
  const bind = (id, key, conv) => $(id).addEventListener("change", (e) => { PREFS[key] = conv(e.target); savePrefs(); renderMap(); });
  bind("#pSnap", "snap_m", (t) => Math.max(0, +t.value || 0));
  bind("#pLabels", "labels", (t) => t.checked);
  bind("#pDrops", "drops", (t) => t.checked);
  bind("#pDark", "cad_dark", (t) => t.checked);
  bind("#pGrid", "cad_grid", (t) => t.checked);
  bind("#pText", "cad_text", (t) => +t.value);
}
$("#saveAuto").onclick = () => {
  const out = {};
  for (const [k, , def, min, max] of AD_FIELDS) {
    const raw = $(`#setAuto [data-ad="${k}"]`).value;
    if (raw === "" && def === null) continue;  // blank: use the design style's value
    const v = +raw;
    if (!Number.isFinite(v) || v < min || v > max) return toast(`${k.replace(/_/g, " ")} must be between ${min} and ${max}`);
    if (v !== def) out[k] = v;
  }
  try { localStorage.setItem("ftth.autodesign", JSON.stringify(out)); } catch (_) { /* storage unavailable */ }
  toast(Object.keys(out).length ? `Auto-design will use: ${Object.entries(out).map(([k, v]) => `${k} ${v}`).join(", ")}` : "Auto-design will use the company defaults");
};
let STANDARDS = null;
async function renderStandards() {
  try { STANDARDS = STANDARDS || await api("/api/standards"); } catch (_) { return; }
  const pick = (S.st && S.st.company && S.st.company.design_standard) || "system";
  $("#stdSel").innerHTML = STANDARDS.map((s) => `<option value="${esc(s.key)}" ${s.key === pick ? "selected" : ""}>${esc(s.label)}${s.key === pick ? " (company)" : ""}</option>`).join("");
}
$("#stdApply").onclick = async () => {
  const key = $("#stdSel").value;
  if (!confirm("Reset this project's construction rules and design style to the selected standard?")) return;
  try {
    const st = await serverOp(`/api/projects/${S.pid}/apply-standard`, jsonBody({ standard: key }));
    toast(`Rules set to ${st.result.label}`); renderSettings();
  } catch (e) { toast(e.message, 7000); }
};
$("#resetAuto").onclick = () => { try { localStorage.removeItem("ftth.autodesign"); } catch (_) { /* */ } renderSettings(); toast("Auto-design options reset to the company defaults"); };

undoButtons();

// ---------------------------------------------------------------------------
// Photo AI: suggestions from a vision model for survey photos (sent only when the planner presses Analyse)
// ---------------------------------------------------------------------------
let PHOTO_AI = null;
async function photoAiStatus() {
  if (PHOTO_AI) return PHOTO_AI;
  try { PHOTO_AI = await api("/api/photo-ai"); } catch (_) { PHOTO_AI = { enabled: false }; }
  return PHOTO_AI;
}
const normId = (s) => String(s || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
async function renderPhotoAi() {
  const st = await photoAiStatus();
  $$("#photos figure").forEach((fig, i) => {
    const ph = S.D.photos[i];
    if (!ph) return;
    const img = fig.querySelector("img");
    if (img && !img.parentElement.classList.contains("boxwrap")) {
      const w = document.createElement("div"); w.className = "boxwrap"; img.replaceWith(w); w.appendChild(img);
    }
    const a = ph.analysis || {};
    fig.querySelectorAll(".aibox").forEach((x) => x.remove());
    (a.objects || []).filter((o) => o.box).slice(0, 12).forEach((o) => {
      const b = document.createElement("div");
      b.className = "aibox";
      Object.assign(b.style, { left: `${o.box[0] * 100}%`, top: `${o.box[1] * 100}%`, width: `${o.box[2] * 100}%`, height: `${o.box[3] * 100}%` });
      b.innerHTML = `<span>${esc(o.label)}</span>`;
      img.parentElement.appendChild(b);
    });
    let box = fig.querySelector(".ai");
    if (!box) { box = document.createElement("div"); box.className = "ai"; fig.appendChild(box); }
    const pole = (a.pole_labels || []).map((t) => S.D.poles.find((p) => normId(p.id) === normId(t))).find(Boolean);
    box.innerHTML = (a.objects ? `
      <div>${a.objects.slice(0, 10).map((o) => `<span class="chip">${esc(o.label)}${o.confidence != null ? ` ${Math.round(o.confidence * 100)}%` : ""}</span>`).join("") || "<span class='muted'>nothing detected</span>"}</div>
      ${(a.pole_labels || []).map((t) => `<span class="chip tag">tag: ${esc(t)}</span>`).join("")}
      ${(a.issues || []).map((t) => `<span class="chip issue">${esc(t)}</span>`).join("")}
      ${a.summary ? `<div class="muted">${esc(a.summary)}</div>` : ""}
      <div class="row">${a.summary ? `<button data-aicap="${i}">Add to caption</button>` : ""}
        ${pole && ph.feature !== pole.id ? `<button data-aipole="${i}" data-pole="${esc(pole.id)}">Link to pole ${esc(pole.id)}</button>` : ""}</div>
      <div class="muted">${esc(a.provider || "")} · ${esc((a.at || "").replace("T", " "))} · suggestions only, check before use</div>` : "") +
      (st.enabled ? `<div class="row"><button data-aigo="${i}" title="Sends this photo to ${esc(st.provider)}">${a.objects ? "Analyse again" : "Analyse (AI)"}</button></div>`
        : (a.objects ? "" : `<div class="muted">Photo AI is not set up on this server.</div>`));
  });
  $$("[data-aigo]").forEach((b) => b.addEventListener("click", async () => {
    const ph = S.D.photos[+b.dataset.aigo];
    b.disabled = true; b.textContent = "Analysing...";
    try {
      await serverOp(`/api/projects/${S.pid}/photos/${encodeURIComponent(ph.file)}/analyse`);
      toast("Photo analysed - review the suggestions");
    } catch (e) { toast(e.message, 7000); }
    renderReport();
  }));
  $$("[data-aicap]").forEach((b) => b.addEventListener("click", () => {
    const ph = S.D.photos[+b.dataset.aicap];
    ph.caption = [ph.caption, ph.analysis.summary].filter(Boolean).join(" - ").slice(0, 500); changed(false); renderReport();
  }));
  $$("[data-aipole]").forEach((b) => b.addEventListener("click", () => {
    S.D.photos[+b.dataset.aipole].feature = b.dataset.pole; changed(false); renderReport(); toast(`Photo linked to pole ${b.dataset.pole}`);
  }));
}


// ---------------------------------------------------------------------------
// Company logo, access (view-only for company viewers, approve button), review comments
// ---------------------------------------------------------------------------
function renderAccess() {
  const st = S.st;
  if (!st) return;
  const appr = $('[data-rev="approved"]');
  if (appr) { appr.disabled = !st.can_approve; appr.title = st.can_approve ? "" : "Approving needs the approver role in this project's company"; }
  let bar = $("#readonly");
  if (!st.can_edit) {
    if (!bar) { bar = document.createElement("div"); bar.id = "readonly"; document.querySelector("header").after(bar); }
    bar.textContent = "View only: you can read this project and leave review comments, but not change it (company viewer).";
  } else if (bar) bar.remove();
}

async function renderComments() {
  if (!S.pid) return;
  const list = await fresh("comments", () => api(`/api/projects/${S.pid}/comments`));
  if (!list) return;
  drawComments(list);
}
function drawComments(list) {
  const open = list.filter((c) => !c.resolved).length;
  $("#cmtCount").textContent = open ? `${open} open` : "none open";
  $("#cmtCount").className = "pill " + (open ? "warn" : "ok");
  $("#cmtList").innerHTML = list.map((c) => `<div class="cmt ${c.resolved ? "done" : ""}">
      <div class="cmeta"><b>${esc(c.author || "-")}</b> · ${esc(c.created.slice(0, 16).replace("T", " "))}${c.revision ? ` · rev ${c.revision}` : ""}
        ${c.ref ? ` · <a data-cref="${esc(c.ref)}">${esc(c.ref)}</a>` : ""}${c.resolved ? ` · resolved by ${esc(c.resolved_by)}` : ""}</div>
      <div>${esc(c.text).replace(/\n/g, "<br>")}</div>
      <button class="sm" data-cres="${c.id}" data-reopen="${c.resolved ? 1 : ""}">${c.resolved ? "Reopen" : "Mark resolved"}</button></div>`).join("")
    || `<p class="muted">No comments yet. Reviewers' comments appear here and on the Review page.</p>`;
  $$("[data-cref]").forEach((a) => a.addEventListener("click", () => goTo(a.dataset.cref)));
  $$("[data-cres]").forEach((b) => b.addEventListener("click", async () => {
    try { drawComments(await api(`/api/projects/${S.pid}/comments/${b.dataset.cres}/resolve`, jsonBody({ reopen: !!b.dataset.reopen }))); }
    catch (e) { toast(e.message); }
  }));
}
$("#cmtAdd").onclick = async () => {
  const text = $("#cmtText").value.trim();
  if (!text) return toast("Write a comment first");
  const ref = $("#cmtRef").value.trim() || (S.sel ? S.sel.id : "");
  try {
    drawComments(await api(`/api/projects/${S.pid}/comments`, jsonBody({ text, ref })));
    $("#cmtText").value = ""; $("#cmtRef").value = "";
    toast("Comment added");
  } catch (e) { toast(e.message); }
};
// links from the Review page: /?project=ID&feature=ID opens the project on that feature
(() => {
  const f = new URLSearchParams(location.search).get("feature");
  if (!f) return;
  const t = setInterval(() => { if (S.D) { clearInterval(t); goTo(f); } }, 300);
  setTimeout(() => clearInterval(t), 15000);
})();
