"use strict";
/* ArchPlanner UI. The design document (D) is edited locally and autosaved;
   the server returns validation issues, summaries and output freshness. */

const S = { pid: null, D: null, st: null, dirty: false, timer: null, saving: null,
            mode: "select", sel: null, draw: [], fitted: false };
const CORES = [2, 4, 6, 8, 12, 24, 48, 72, 96, 144];
const COL = { main: "#e01b24", spur: "#f5c211", drop: "#2ec27e", POP: "#9141ac", ENCLOSURE: "#ff7800",
  PR_ENCLOSURE: "#c64600", JB: "#a347ba", PON: "#e66100", FAT: "#e01b24", SLACK: "#57e389", pole: "#1c71d8", home: "#33d17a" };
const NODE_KINDS = ["POP", "ENCLOSURE", "PR_ENCLOSURE", "JB", "PON", "FAT", "SLACK"];
const PREFIX = { POP: "POP", ENCLOSURE: "SE", PR_ENCLOSURE: "PR", JB: "JB", PON: "PON", FAT: "FAT", SLACK: "SL" };
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n, d = 0) => (n == null || isNaN(n) ? "" : Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d }));

function toast(msg, ms = 3500) {
  const t = $("#toast"); t.textContent = msg; t.style.display = "block";
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.style.display = "none"), ms);
}

function csrf() { const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ""; }
function withCsrf(opts = {}) {
  if ((opts.method || "GET").toUpperCase() !== "GET") opts.headers = { ...(opts.headers || {}), "X-CSRFToken": csrf() };
  return opts;
}
function signedOut() { window.location = "/accounts/login/?next=/"; throw new Error("Signed out"); }

async function api(path, opts = {}) {
  const r = await fetch(path, withCsrf(opts));
  if (r.status === 401) signedOut();
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch (_) {}
    throw new Error(msg);
  }
  return r.json();
}
const jsonBody = (o) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(o) });

// ---------------------------------------------------------------------------
// Projects, saving, state
// ---------------------------------------------------------------------------
async function loadProjects(selectId) {
  const list = await api("/api/projects");
  const sel = $("#projectSelect");
  sel.innerHTML = list.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("") ||
    `<option value="">(no projects)</option>`;
  const want = new URLSearchParams(location.search);
  const id = selectId || want.get("project") || localStorage.getItem("ftth.pid");
  if (id && list.some((p) => p.id === id)) sel.value = id;
  if (sel.value) await openProject(sel.value);
}

async function openProject(pid) {
  await flush();
  S.pid = pid; S.sel = null; S.fitted = false;
  try { localStorage.setItem("ftth.pid", pid); } catch (_) {}
  applyState(await api(`/api/projects/${pid}`), true);
}

function applyState(st, replaceDesign) {
  S.st = st;
  if (replaceDesign || !S.D) S.D = st.design;
  historyRecord();  // server operations (auto-design, allocate...) can be undone too
  renderAll();
}

function changed(rerenderMap = true) {
  historyRecord();
  S.dirty = true; renderHeader();
  clearTimeout(S.timer); S.timer = setTimeout(save, 600);
  if (rerenderMap) renderMap();
  renderProps();
  if (activeTab() === "lld" && typeof renderLld === "function") renderLld();  // edits made in the drawing tab
  if (activeTab() === "building" && typeof renderBuilding === "function") renderBuilding(false);
}

async function save() {
  clearTimeout(S.timer); S.timer = null;
  while (S.saving) await S.saving;  // one save at a time: the next one must carry the new version hash
  if (!S.pid || !S.dirty) return;
  S.dirty = false; renderHeader("saving");
  const body = JSON.stringify(S.D);
  // X-Base-Hash lets the server refuse the save if someone else changed the project meanwhile
  S.saving = fetch(`/api/projects/${S.pid}`, withCsrf({ method: "PUT", body,
      headers: { "Content-Type": "application/json", "X-Base-Hash": S.st?.hash || "" } }))
    .then(async (r) => {
      if (r.status === 401) signedOut();
      if (r.ok) return r.json();
      const j = await r.json().catch(() => ({}));
      if (j.conflict) S.conflict = true;
      throw new Error(typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail || r.statusText));
    })
    .then((st) => {
      S.st = st;
      const si = st.design.info, li = S.D.info;
      if (li.design_status !== si.design_status) {
        li.design_status = si.design_status;
        toast("Design changed after approval: status returned to draft");
      }
      if (li.survey_status !== si.survey_status) toast("Survey data changed after approval: survey returned to draft");
      for (const k of ["survey_status", "survey_approved_by", "survey_approved_at", "survey_fingerprint"]) li[k] = si[k];
      renderHeader(); renderActiveTab(false);
    })
    .catch((e) => {
      if (S.conflict) {
        S.conflict = false; S.dirty = false; renderHeader();
        if (confirm(e.message + "\n\nReload the latest version now? Your unsaved change will be discarded.")) openProject(S.pid);
        else toast("Not saved. Reload the project before making further changes.", 8000);
        return;
      }
      S.dirty = true; renderHeader(); toast("Save failed: " + e.message, 6000);
    })
    .finally(() => (S.saving = null));
  return S.saving;
}

async function flush() {
  if (S.timer || S.dirty) await save();
  if (S.saving) await S.saving;
}

async function serverOp(path, opts) {
  await flush();
  const st = await api(path, opts || { method: "POST" });
  applyState(st, true);
  return st;
}

// ---------------------------------------------------------------------------
// Helpers on the design
// ---------------------------------------------------------------------------
const collOf = { pole: "poles", home: "homes", node: "nodes", cable: "cables" };
function find(type, id) { return S.D[collOf[type]].find((x) => x.id === id); }
function allIds() { return new Set(["poles", "homes", "nodes", "cables", "splitters"].flatMap((c) => S.D[c].map((x) => x.id))); }
function nextId(prefix, width = 3) {
  const ids = allIds(); let i = 1;
  while (ids.has(prefix + String(i).padStart(width, "0"))) i++;
  return prefix + String(i).padStart(width, "0");
}
function hav(a, b, c, d) {
  const R = 6371008.8, r = Math.PI / 180;
  const x = Math.sin(((c - a) * r) / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin(((d - b) * r) / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}
const okc = (o) => o && o.lat != null && o.lon != null;

function renameRef(oldId, newId) {
  for (const c of S.D.cables) {
    for (const v of c.path) { if (v.pole === oldId) v.pole = newId; if (v.node === oldId) v.node = newId; }
    if (c.from_node === oldId) c.from_node = newId;
    if (c.to_node === oldId) c.to_node = newId;
  }
  for (const h of S.D.homes) if (h.fat === oldId) h.fat = newId;
  for (const n of S.D.nodes) if (n.pole === oldId) n.pole = newId;
  for (const s of S.D.splitters) if (s.node === oldId) s.node = newId;
  for (const x of S.D.connections) {
    if (x.node === oldId) x.node = newId;
    for (const e of [x.a, x.b]) if ((e.kind === "cable" || e.kind === "olt") && e.ref === oldId) e.ref = newId;
  }
}

function movePoint(type, obj, lat, lon) {
  obj.lat = lat; obj.lon = lon;
  if (type === "pole") {
    for (const n of S.D.nodes) if (n.pole === obj.id) { n.lat = lat; n.lon = lon; }
  }
  const ids = new Set([obj.id, ...(type === "pole" ? S.D.nodes.filter((n) => n.pole === obj.id).map((n) => n.id) : [])]);
  for (const c of S.D.cables) for (const v of c.path) {
    if ((type === "pole" && (v.pole === obj.id || ids.has(v.node))) || (type === "node" && v.node === obj.id)) {
      v.lat = lat; v.lon = lon;
    }
  }
  if (type === "node") syncNodePole(obj);
}

function syncNodePole(node) {
  for (const c of S.D.cables) for (const v of c.path) if (v.node === node.id) v.pole = node.pole || null;
}

// Remove one feature and what belongs to it; returns why it cannot be removed, or null when it was
function deleteFeature(type, id) {
  if (type === "pole") {
    const users = S.D.cables.filter((c) => c.path.some((v) => v.pole === id)).map((c) => c.id);
    const nodes = S.D.nodes.filter((n) => n.pole === id).map((n) => n.id);
    if (users.length || nodes.length) return `Pole ${id} is used by ${[...users, ...nodes].join(", ")}. Remove those first.`;
  }
  if (type === "node") {
    const users = S.D.cables.filter((c) => c.from_node === id || c.to_node === id || c.path.some((v) => v.node === id)).map((c) => c.id);
    if (users.length) return `${id} is connected to cables ${users.join(", ")}. Delete those first.`;
    const spl = S.D.splitters.filter((s) => s.node === id).map((s) => s.id);
    S.D.splitters = S.D.splitters.filter((s) => s.node !== id);
    S.D.connections = S.D.connections.filter((c) => c.node !== id && ![c.a, c.b].some((e) => spl.includes(e.ref)));
    for (const h of S.D.homes) if (h.fat === id) h.fat = null;
  }
  if (type === "cable") S.D.connections = S.D.connections.filter((x) => ![x.a, x.b].some((e) => e.kind === "cable" && e.ref === id));
  S.D[collOf[type]] = S.D[collOf[type]].filter((x) => x.id !== id);
  return null;
}

function deleteSelected() {
  if (!S.sel) return toast("Nothing selected");
  const why = deleteFeature(S.sel.type, S.sel.id);
  if (why) return toast(why, 6000);
  S.sel = null; changed();
}

// ---------------------------------------------------------------------------
// Map
// ---------------------------------------------------------------------------
const map = L.map("map", { doubleClickZoom: false, zoomControl: true }).setView([-1.312, 36.823], 16);
// Tile requests send only this site's origin as Referer: OpenStreetMap refuses tiles without one.
const TILE = { maxZoom: 20, maxNativeZoom: 19, referrerPolicy: "strict-origin-when-cross-origin" };
const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  { ...TILE, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' });
const carto = L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
  { ...TILE, maxNativeZoom: 20, subdomains: "abcd", attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>' });
const sat = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", { ...TILE, attribution: "Imagery © Esri" });
const BASE = { "Streets (OpenStreetMap)": osm, "Streets (CARTO)": carto, Satellite: sat };
let streets = osm;
try { streets = BASE[localStorage.getItem("ftth.basemap")] || osm; } catch (e) { /* storage unavailable */ }
if (streets === sat) streets = osm;
streets.addTo(map);
let osmErrors = 0;  // OpenStreetMap down or refusing this server: fall back to the CARTO street map
osm.on("tileerror", () => {
  if (++osmErrors === 4 && map.hasLayer(osm)) {
    map.removeLayer(osm); carto.addTo(map); streets = carto;
    toast("OpenStreetMap tiles could not be loaded - switched to the CARTO street map", 6000);
  }
});
const G = { boundary: L.layerGroup().addTo(map), drops: L.layerGroup().addTo(map), cables: L.layerGroup().addTo(map),
            homes: L.layerGroup().addTo(map), poles: L.layerGroup().addTo(map), nodes: L.layerGroup().addTo(map),
            draw: L.layerGroup().addTo(map) };
L.control.layers(BASE,
  { Boundary: G.boundary, "Drop links": G.drops, Cables: G.cables, Homes: G.homes, Poles: G.poles, Equipment: G.nodes }).addTo(map);
map.on("baselayerchange", (e) => {
  $("#satellite").checked = e.layer === sat;
  if (e.layer !== sat) streets = e.layer;
  try { localStorage.setItem("ftth.basemap", e.name); } catch (err) { /* storage unavailable */ }
});
$("#satellite").onchange = (e) => { if (e.target.checked) { map.removeLayer(streets); sat.addTo(map); } else { map.removeLayer(sat); streets.addTo(map); } };

function icon(type, obj, selected) {
  let size = 12, style = "", html = "";
  const sel = selected ? " sel" : "";
  if (type === "pole") {
    size = 12; style = `background:${COL.pole};border-radius:50%;${obj.status === "proposed" ? "border-style:dashed;" : ""}`;
  } else if (type === "home") {
    size = obj.kind === "mdu" ? 14 : 10; style = `background:${COL.home};border-radius:2px;`;
  } else {
    size = 18;
    if (obj.kind === "FAT") html = `<svg width="18" height="18" viewBox="0 0 18 18"><polygon points="9,1 17,17 1,17" fill="${COL.FAT}" stroke="#fff" stroke-width="2"/></svg>`;
    else style = `background:${COL[obj.kind]};border-radius:3px;`;
  }
  const inner = html ? `<div class="${sel.trim()}" style="width:${size}px;height:${size}px">${html}</div>`
    : `<div class="mk${sel}" style="width:${size}px;height:${size}px;${style}"></div>`;
  return L.divIcon({ className: "", html: inner, iconSize: [size, size], iconAnchor: [size / 2, size / 2] });
}

function renderMap() {
  if (!S.D) return;
  Object.values(G).forEach((g) => g.clearLayers());
  const D = S.D, isSel = (t, id) => S.sel && S.sel.type === t && S.sel.id === id;
  const drag = S.mode === "select";
  if (D.info.boundary.length) L.polygon(D.info.boundary, { color: "#555", weight: 2, dashArray: "6 4", fill: false, interactive: false }).addTo(G.boundary);

  const fats = Object.fromEntries(D.nodes.filter((n) => n.kind === "FAT").map((n) => [n.id, n]));
  for (const h of D.homes) {
    for (const fid of [h.fat, ...(h.extra_fats || [])]) {
      const f = fats[fid];
      if (f && okc(h) && okc(f)) L.polyline([[h.lat, h.lon], [f.lat, f.lon]], { color: "#77767b", weight: 1, dashArray: "3 4", interactive: false }).addTo(G.drops);
    }
  }
  for (const x of D.ducts || []) {
    if (x.path.length < 2) continue;
    L.polyline(x.path.map((v) => [v.lat, v.lon]), { color: "#3584e4", weight: 3, dashArray: "2 5" })
      .bindTooltip(esc(`${x.id} · ${x.kind}`), { sticky: true }).addTo(G.cables);
  }
  for (const c of D.cables) {
    if (c.path.length < 2) continue;
    const line = L.polyline(c.path.map((v) => [v.lat, v.lon]), {
      color: COL[c.kind], weight: (c.kind === "main" ? 5 : c.kind === "spur" ? 4 : 2) + (isSel("cable", c.id) ? 3 : 0),
      opacity: isSel("cable", c.id) ? 1 : 0.85, dashArray: c.install === "underground" ? "8 6" : null,
    }).addTo(G.cables);
    line.bindTooltip(esc(`${c.id} · ${c.cores}C ${c.kind}`), { sticky: true });
    line.on("click", (e) => { L.DomEvent.stopPropagation(e); featureClick("cable", c, e); });
  }
  const addMarker = (type, obj, group, label) => {
    if (!okc(obj)) return;
    const m = L.marker([obj.lat, obj.lon], { icon: icon(type, obj, isSel(type, obj.id)), draggable: drag, zIndexOffset: type === "node" ? 500 : 0 }).addTo(group);
    m.bindTooltip(esc(label), { permanent: type === "node", direction: "right", offset: [8, 0], className: type === "node" ? "lbl" : "" });
    m.on("click", (e) => { L.DomEvent.stopPropagation(e); featureClick(type, obj, e); });
    m.on("dragend", () => {
      let { lat, lng } = m.getLatLng();
      if (type === "node") {
        const p = D.poles.find((p) => okc(p) && hav(lat, lng, p.lat, p.lon) < 4);
        obj.pole = p ? p.id : null;
        if (p) { lat = p.lat; lng = p.lon; }
      }
      movePoint(type, obj, lat, lng); S.sel = { type, id: obj.id }; changed();
    });
  };
  D.homes.forEach((h) => addMarker("home", h, G.homes, `${h.id}${h.units > 1 ? ` (${h.units} units)` : ""}${h.fat ? " → " + h.fat : ""}`));
  D.poles.forEach((p) => addMarker("pole", p, G.poles, `${p.id} (${p.status})`));
  D.nodes.forEach((n) => addMarker("node", n, G.nodes, n.id));

  (D.info.extend_to || []).forEach((pt, i) => {
    const m = L.marker(pt, { icon: L.divIcon({ className: "", html: '<div style="font-size:20px;color:#9141ac;text-shadow:0 0 2px #fff">&#9733;</div>', iconSize: [20, 20], iconAnchor: [10, 10] }) })
      .bindTooltip("Backbone end (48C extends here)").addTo(G.nodes);
    m.on("click", (e) => { L.DomEvent.stopPropagation(e); if (S.mode === "extend") { D.info.extend_to.splice(i, 1); changed(); } });
  });
  if (S.draw.length) {
    const pts = S.draw.map((v) => [v.lat, v.lon]);
    if (S.mode === "boundary") L.polygon(pts, { color: "#00b7ff", dashArray: "4 4", interactive: false }).addTo(G.draw);
    else L.polyline(pts, { color: COL[$("#cableKind").value], weight: 4, dashArray: "6 6", interactive: false }).addTo(G.draw);
    pts.forEach((p) => L.circleMarker(p, { radius: 4, color: "#00b7ff", interactive: false }).addTo(G.draw));
  }
  drawOverlays();
  const site = typeof buildingOnMap === "function" ? buildingOnMap(G.boundary) : [];  // construction: the building's footprint
  if (!S.fitted && map.getContainer().offsetWidth) {  // fit once the map is visible
    const pts = [...D.poles, ...D.homes, ...D.nodes].filter(okc).map((x) => [x.lat, x.lon]).concat(D.info.boundary, site);
    if (pts.length) map.fitBounds(pts, { padding: [30, 30], maxZoom: 18 });
    S.fitted = true;
  }
}

function setMode(mode) {
  if (S.draw.length && mode !== S.mode) S.draw = [];
  S.mode = mode;
  $$("#toolbar [data-mode]").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  const hints = {
    select: "Click a feature to edit it. Drag points to move them; connected cables follow.",
    pole: "Click the map to add poles.", home: "Click the map to add homes. Change to MDU and set units in the panel.",
    node: "Click a pole to mount equipment on it, or click the map to place it freely.",
    cable: "Click the start equipment, then poles, equipment and points along the route. Finish with Enter, a double-click or by clicking the last point again; Esc cancels.",
    boundary: "Click the boundary corners. Double-click or Enter to finish.",
    extend: "Click where the 48C backbone must reach (e.g. a future phase). Click a backbone-end star to remove it.",
    measure: "Click points to measure distance (and area with 3+ points). Esc clears.",
  };
  if (mode !== "measure" && typeof clearMeasure === "function") clearMeasure();  // tools.js loads after this file
  $("#hint").textContent = hints[mode] || "";
  renderMap();
}

function featureClick(type, obj, e) {
  if (S.mode === "measure") return okc(obj) ? measureClick(obj.lat, obj.lon) : measureClick(e.latlng.lat, e.latlng.lng);
  if (S.mode === "cable" && type !== "cable" && type !== "home") {
    const v = { lat: obj.lat, lon: obj.lon, pole: null, node: null, crossing: false };
    if (type === "pole") v.pole = obj.id; else { v.node = obj.id; v.pole = obj.pole || null; }
    const last = S.draw[S.draw.length - 1];  // clicking the last point again finishes the cable
    if (last && S.draw.length > 1 &&
        ((v.node && last.node === v.node) || (!v.node && v.pole && last.pole === v.pole && !last.node))) return finishDraw();
    S.draw.push(v);
    return renderMap();
  }
  if (S.mode === "node" && type === "pole") {
    const kind = $("#nodeKind").value;
    const n = { id: nextId(PREFIX[kind], 2), kind, lat: obj.lat, lon: obj.lon, pole: obj.id, status: "proposed",
                ports: defaultPorts(kind), notes: "" };
    S.D.nodes.push(n); S.sel = { type: "node", id: n.id }; return changed();
  }
  if (S.mode !== "select" && S.mode !== "node" && S.mode !== "cable") return mapClick(e);
  S.sel = { type, id: obj.id }; renderMap(); renderProps();
}

function mapClick(e) {
  const { lat, lng: lon } = e.latlng;
  const D = S.D;
  if (S.mode === "measure") return measureClick(lat, lon);
  // snapping: a click close to a pole / equipment uses it (routes stay pole to pole)
  const sn = ["cable", "node"].includes(S.mode) ? snapTarget(lat, lon, S.mode === "node" ? ["pole"] : ["node", "pole"]) : null;
  if (sn) return featureClick(sn.type, sn.obj, e);
  if (S.mode === "pole") {
    const p = { id: nextId("P"), lat, lon, type: "wood", height_m: null, condition: "", status: "proposed", notes: "" };
    D.poles.push(p); S.sel = { type: "pole", id: p.id }; return changed();
  }
  if (S.mode === "home") {
    const h = { id: nextId("H"), lat, lon, kind: "home", units: 1, name: "", address: "", fat: null, access_notes: "", notes: "" };
    D.homes.push(h); S.sel = { type: "home", id: h.id }; return changed();
  }
  if (S.mode === "node") {
    const kind = $("#nodeKind").value;
    const n = { id: nextId(PREFIX[kind], 2), kind, lat, lon, pole: null, status: "proposed",
                ports: defaultPorts(kind), notes: "" };
    D.nodes.push(n); S.sel = { type: "node", id: n.id }; return changed();
  }
  if (S.mode === "cable" || S.mode === "boundary") {
    S.draw.push({ lat, lon, pole: null, node: null, crossing: false }); return renderMap();
  }
  if (S.mode === "extend") { D.info.extend_to.push([lat, lon]); return changed(); }
  if (S.mode === "place" && typeof placeBuilding === "function") return placeBuilding(lat, lon);
  S.sel = null; renderMap(); renderProps();
}

function finishDraw() {
  // a double-click also delivers two clicks: drop repeated points
  const pts = S.draw.filter((p, i, a) => i === 0 || hav(a[i - 1].lat, a[i - 1].lon, p.lat, p.lon) > 0.5 || p.node !== a[i - 1].node);
  S.draw = [];
  if (S.mode === "boundary") {
    if (pts.length >= 3) { S.D.info.boundary = pts.map((p) => [p.lat, p.lon]); changed(); toast("Boundary saved"); }
    return renderMap();
  }
  if (pts.length < 2) { toast("A cable needs at least 2 points"); return renderMap(); }
  const cores = +$("#cableCores").value, kind = $("#cableKind").value, t = S.st?.sector;
  const c = { id: nextId("C"), kind, cores, from_node: pts[0].node, to_node: pts[pts.length - 1].node,
              install: t?.install || "aerial", status: "proposed", path: pts, reserved: [], notes: "" };
  S.D.cables.push(c); S.sel = { type: "cable", id: c.id };
  toast(t && !t.fibre_tools ? `${t.line} ${c.id} created (${sizeText(cores)} ${t.lines[kind] || kind})`
    : `Cable ${c.id} created (${cores}C ${kind})`);
  changed();
}

map.on("click", (e) => mapClick(e));
map.on("dblclick", () => { if (S.mode === "cable" || S.mode === "boundary") finishDraw(); });
document.addEventListener("keydown", (e) => {
  if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
  if (activeTab() === "lld") return;  // the drawing tab has its own keys (cadKeys in overview.js)
  if (e.key === "Enter" && S.draw.length) finishDraw();
  if (e.key === "Escape") { S.draw = []; renderMap(); }
  if (e.key === "Delete" && S.sel) deleteSelected();
});

// ---------------------------------------------------------------------------
// Properties panel
// ---------------------------------------------------------------------------
const FIELDS = {
  pole: [["id", "text"], ["type", "text"], ["height_m", "number"], ["condition", "text"], ["status", ["existing", "proposed"]], ["notes", "textarea"], ["lat", "number"], ["lon", "number"]],
  home: [["id", "text"], ["kind", ["home", "mdu", "business"]], ["units", "int"], ["name", "text"], ["address", "text"], ["fat", "fat"], ["extra_fats", "fatlist"], ["acquired", "bool"], ["access_notes", "text"], ["notes", "textarea"], ["lat", "number"], ["lon", "number"]],
  node: [["id", "text"], ["kind", NODE_KINDS], ["status", ["existing", "proposed"]], ["pole", "pole"], ["ports", "int"], ["notes", "textarea"], ["lat", "number"], ["lon", "number"]],
  cable: [["id", "text"], ["kind", ["main", "spur", "drop"]], ["cores", CORES], ["install", ["aerial", "underground"]], ["status", ["existing", "proposed"]], ["reserved", "list"], ["notes", "textarea"]],
};

function input(field, kind, value) {
  const v = value ?? "";
  if (Array.isArray(kind)) return `<select data-f="${field}">${kind.map((o) => {  // o: value, or [value, label]
    const [val, label] = Array.isArray(o) ? o : [o, o];
    return `<option value="${esc(val)}" ${String(val) === String(v) ? "selected" : ""}>${esc(label)}</option>`;
  }).join("")}</select>`;
  if (kind === "textarea") return `<textarea data-f="${field}">${esc(v)}</textarea>`;
  if (kind === "fat" || kind === "pole") {
    const opts = kind === "fat" ? S.D.nodes.filter((n) => n.kind === "FAT").map((n) => n.id) : S.D.poles.map((p) => p.id);
    return `<select data-f="${field}"><option value="">(none)</option>${opts.map((o) => `<option ${o === v ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
  }
  if (kind === "list") return `<input data-f="${field}" value="${esc((value || []).join(", "))}" placeholder="e.g. 11, 12">`;
  if (kind === "fatlist") return `<input data-f="${field}" value="${esc((value || []).join(", "))}" placeholder="further FATs for a large MDU, e.g. FAT-02, FAT-03">`;
  if (kind === "bool") return `<select data-f="${field}"><option value="false" ${!value ? "selected" : ""}>no</option><option value="true" ${value ? "selected" : ""}>yes</option></select>`;
  return `<input data-f="${field}" type="${kind === "text" ? "text" : "number"}" step="${kind === "int" ? 1 : "any"}" value="${esc(v)}">`;
}

// sector: line sizes in its unit (48C, DN160, 50 mm²) and equipment ratings (transformer kVA)
function sizeText(n) {
  const u = S.st?.sector?.size_unit || "C";
  return u === "C" ? `${n}C` : u === "mm" ? `DN${n}` : `${n} ${u}`;
}
function defaultPorts(kind) {
  const t = S.st?.sector;
  if (t && !t.fibre_tools) return t.port_defaults?.[kind] ?? null;
  return kind === "FAT" ? S.D.rules.default_fat_ports : null;
}

// the fields of a feature in the project's sector: fibre keeps FIELDS; other sectors rename them, offer their
// sizes and ratings, and leave out fibre-only fields (core reservations, FAT load sharing)
function sectorFields(type, obj) {
  const t = S.st?.sector;
  const named = (f) => f.replace("_", " ");
  if (!t || t.fibre_tools) return FIELDS[type].map(([f, k]) => [f, k, named(f)]);
  const out = [];
  for (const [f, k] of FIELDS[type]) {
    if (f === "reserved" || f === "extra_fats") continue;
    if (f === "ports") {
      const label = t.ports?.[obj.kind];
      if (label) out.push([f, t.port_sizes?.[obj.kind] || k, label]);
      continue;
    }
    if (f === "cores") { out.push([f, t.sizes, `${t.size} (${t.size_unit})`]); continue; }
    if (f === "kind" && type === "node") { out.push([f, k.map((x) => [x, t.kinds[x] || x]), "kind"]); continue; }
    if (f === "kind" && type === "cable") { out.push([f, k.map((x) => [x, t.lines[x] || x]), "kind"]); continue; }
    const label = { fat: t.kinds.FAT, units: t.unit, type: `${t.support.toLowerCase()} type`,
                    height_m: "height (m)", install: "installation" }[f];
    out.push([f, k, label || named(f)]);
  }
  return out;
}

function detailInput(d, value) {
  const v = value ?? "";
  if (Array.isArray(d.kind)) return `<select data-d="${d.key}"><option value="">-</option>${d.kind.map((o) => `<option ${String(o) === String(v) ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
  if (d.kind === "number" || d.kind === "int") return `<input data-d="${d.key}" type="number" step="${d.kind === "int" ? 1 : "any"}" value="${esc(v)}">`;
  return `<input data-d="${d.key}" type="text" maxlength="300" value="${esc(v)}">`;
}

function renderProps() {
  renderPropsInto($("#props"));
  if (activeTab() === "lld" && typeof renderCadProps === "function") renderCadProps();  // the drawing tab's panel
}

function renderPropsInto(el) {
  if (!S.D || !S.sel) { el.innerHTML = `<p class="muted">Select a feature to edit it.</p>${summaryHtml()}`; return; }
  const { type, id } = S.sel, obj = find(type, id);
  if (!obj) { S.sel = null; return renderPropsInto(el); }
  const t = S.st?.sector, fibre = !t || t.fibre_tools;
  const issues = (S.st?.issues || []).filter((i) => i.ref === id);
  const title = fibre ? (type === "node" ? obj.kind : type[0].toUpperCase() + type.slice(1))
    : type === "node" ? t.kinds[obj.kind] || obj.kind
    : { pole: t.support, home: t.premise.split("/")[0].trim(), cable: t.lines[obj.kind] || t.line }[type];
  let html = `<h3>${esc(title)} ${esc(id)}</h3><div class="form">` +
    sectorFields(type, obj).map(([f, k, label]) => `<label>${esc(label)}${input(f, k, obj[f])}</label>`).join("") + `</div>`;
  const dets = fibre ? [] : t.details?.[type] || [];
  if (dets.length) {
    html += `<h4>${esc(t.label)} details</h4><div class="form">` + dets.map((d) =>
      `<label>${esc(d.label)}${d.unit ? ` (${esc(d.unit)})` : ""}${detailInput(d, (obj.details || {})[d.key])}</label>`).join("") + `</div>`;
  }
  if (type === "node" && fibre) {
    const sp = S.D.splitters.filter((s) => s.node === id);
    html += `<p class="muted">Splitters: ${sp.map((s) => `${esc(s.id)} 1x${s.outputs}`).join(", ") || "none"} — edit in the Splicing tab.</p>`;
    if (obj.kind === "FAT") {
      const load = (S.st?.summary?.fat_load || {})[id] || 0;  // as of the last save
      html += `<p>Load: <b>${load}</b> / ${obj.ports || S.D.rules.default_fat_ports} ports</p>`;
    }
  }
  if (type === "cable") {
    let len = 0;
    obj.path.forEach((v, i) => { if (i) len += hav(obj.path[i - 1].lat, obj.path[i - 1].lon, v.lat, v.lon); });
    html += `<p>Route length: <b>${fmt(len, 1)} m</b> (design length${fibre ? " with slack" : ""} is in the Schedules tab)</p>
      <p>From <b>${esc(obj.from_node || "-")}</b> to <b>${esc(obj.to_node || "-")}</b></p>
      <table><tr><th>#</th><th>Vertex</th><th title="The span after this point crosses a road">Road X</th></tr>` +
      obj.path.map((v, i) => `<tr><td>${i + 1}</td><td>${esc(v.node || v.pole || `${v.lat.toFixed(5)}, ${v.lon.toFixed(5)}`)}</td>
        <td>${i < obj.path.length - 1 ? `<input type="checkbox" data-x="${i}" ${v.crossing ? "checked" : ""}>` : ""}</td></tr>`).join("") + `</table>`;
  }
  if (issues.length) html += `<h4>Issues</h4>` + issues.map((i) => `<div class="issue ${i.severity}">${esc(i.message)}</div>`).join("");
  const focused = el.contains(document.activeElement) ? document.activeElement.dataset.f : null;
  el.innerHTML = html;
  if (focused) $(`[data-f="${focused}"]`, el)?.focus();
  $$("[data-f]", el).forEach((inp) => inp.addEventListener("change", () => setField(type, obj, inp.dataset.f, inp.value)));
  $$("[data-d]", el).forEach((inp) => inp.addEventListener("change", () => setDetail(obj, dets.find((d) => d.key === inp.dataset.d), inp.value)));
  $$("[data-x]", el).forEach((cb) => cb.addEventListener("change", () => { obj.path[+cb.dataset.x].crossing = cb.checked; changed(); }));
}

function setDetail(obj, d, raw) {
  obj.details = obj.details || {};
  let v = raw.trim();
  if (v && (d.kind === "number" || d.kind === "int")) {
    v = d.kind === "int" ? parseInt(v, 10) : +v;
    if (isNaN(v)) { toast(`${d.label} must be a number`); return renderProps(); }
  }
  if (v === "") delete obj.details[d.key]; else obj.details[d.key] = v;
  changed();
}

function setField(type, obj, f, raw) {
  const kind = FIELDS[type].find((x) => x[0] === f)[1];
  let v = raw;
  if (kind === "number") v = raw === "" ? null : +raw;
  if (kind === "int") v = raw === "" ? null : parseInt(raw, 10);
  if (f === "cores") v = +raw;
  if (kind === "fat" || kind === "pole") v = raw || null;
  if (kind === "list") v = raw.split(/[,\s]+/).filter(Boolean).map(Number).filter((n) => !isNaN(n));
  if (kind === "fatlist") v = raw.split(",").map((x) => x.trim()).filter(Boolean);
  if (kind === "bool") v = raw === "true";
  if (f === "units" && (v === null || v < 0)) { toast("Units must be 0 or more (0 = not counted)"); return renderProps(); }
  if (f === "id") {
    v = raw.trim();
    if (!v || (v !== obj.id && allIds().has(v))) { toast(`ID "${v}" is empty or already used`); return renderProps(); }
    renameRef(obj.id, v); obj.id = v; S.sel.id = v;
  } else if (f === "lat" || f === "lon") {
    const lat = f === "lat" ? v : obj.lat, lon = f === "lon" ? v : obj.lon;
    if (lat != null && lon != null) movePoint(type, obj, lat, lon); else obj[f] = v;
  } else if (type === "node" && f === "pole") {
    obj.pole = v;
    syncNodePole(obj);
    const p = v && find("pole", v);
    if (p && okc(p)) movePoint("node", obj, p.lat, p.lon);
  } else {
    obj[f] = v;
    if (type === "home" && f === "kind" && v === "mdu" && obj.units < 2) obj.units = 2;
  }
  changed();
}

function summaryHtml() {
  const s = S.st?.summary; if (!s) return "";
  const t = S.st?.sector, fibre = !t || t.fibre_tools;
  if (t?.construction) {  // the building, not a network
    const b = S.D.building;
    return `<h4>Project summary</h4><table>
      <tr><td>Floors</td><td class="num">${b?.levels?.length || 0}</td></tr>
      <tr><td>Walls / doors & windows</td><td class="num">${b?.walls?.length || 0} / ${b?.openings?.length || 0}</td></tr>
      <tr><td>Placed on the site plan</td><td class="num">${b?.origin ? "yes" : "no"}</td></tr>
      <tr><td><b>BOQ total</b></td><td class="num"><b>${esc(s.currency)} ${fmt(s.boq_total, 2)}</b></td></tr></table>`;
  }
  return `<h4>Project summary</h4><table>
    <tr><td>${fibre ? "Poles" : esc(t.support) + "s"}</td><td class="num">${s.poles} (${s.poles_new} new)</td></tr>
    <tr><td>Premises / ${fibre ? "homepasses" : esc(t.unit)}</td><td class="num">${s.homes} / ${s.homepasses}</td></tr>
    <tr><td>Unserved premises</td><td class="num">${s.homes_unassigned}</td></tr>
    ${Object.entries(s.nodes).filter(([, v]) => v).map(([k, v]) => `<tr><td>${esc(fibre ? k : t.kinds[k] || k)}</td><td class="num">${v}</td></tr>`).join("")}
    ${Object.entries(s.cable_m).map(([k, v]) => `<tr><td>${k}</td><td class="num">${fmt(v)} m</td></tr>`).join("")}
    <tr><td><b>BOQ total</b></td><td class="num"><b>${esc(s.currency)} ${fmt(s.boq_total, 2)}</b></td></tr></table>`;
}

// ---------------------------------------------------------------------------
// Header & tabs
// ---------------------------------------------------------------------------
function renderHeader(saving) {
  const st = S.st;
  $("#saveState").textContent = saving ? "Saving..." : S.dirty ? "Unsaved changes" : "Saved";
  if (!st) return;
  const c = st.counts;
  const b = $("#issueBadge");
  b.textContent = `${c.errors} errors · ${c.warnings} warnings`;
  b.title = `Validation issues${c.notes ? ` (plus ${c.notes} note${c.notes > 1 ? "s" : ""} for information)` : ""}`;
  b.className = "pill " + (c.errors ? "err" : c.warnings ? "warn" : "ok");
  $("#revBadge").textContent = `Rev ${st.revision} · ${S.D.info.design_status}`;
  $("#revBadge").title = `Owner ${st.owner}; last saved by ${st.updated_by || "-"}`;
  renderSteps();
  renderAccess();
}

function activeTab() { return $("#tabs button.active").dataset.tab; }
$$("#tabs button").forEach((b) => b.addEventListener("click", async () => {
  $$("#tabs button").forEach((x) => x.classList.toggle("active", x === b));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + b.dataset.tab));
  if (b.dataset.tab === "map") setTimeout(() => { map.invalidateSize(); if (!S.fitted) renderMap(); }, 50);
  renderSteps();
  await renderActiveTab(true);
}));

function renderAll() { if (typeof applySector === "function") applySector(); renderHeader(); renderMap(); renderProps(); renderActiveTab(true); }

async function renderActiveTab(full) {
  const t = activeTab();
  if (!S.D) return;
  if (t === "data") renderData();
  if (t === "materials" && full) renderMaterials();
  if (t === "overview") await renderOverview();
  if (t === "settings" && full) renderSettings();
  if (t === "lld" && full) renderLld();
  if (t === "building" && typeof renderBuilding === "function") renderBuilding(full);
  if (t === "splicing") { await renderSplicing(); await renderSplicingSchematic(); }
  if (t === "schedules") await renderSchedules();
  if (t === "report" && full) renderReport();
  if (t === "qa") await renderQA();
  if (t === "outputs") renderOutputs();
  if (t === "map") renderProps();
}

function goTo(ref) {
  const type = ["poles", "homes", "nodes", "cables"].map((c) => [c, S.D[c].find((x) => x.id === ref)]).find(([, x]) => x);
  if (!type) return;
  const t = { poles: "pole", homes: "home", nodes: "node", cables: "cable" }[type[0]];
  S.sel = { type: t, id: ref };
  $('#tabs [data-tab="map"]').click();
  const o = type[1];
  if (t === "cable" && o.path.length) map.fitBounds(o.path.map((v) => [v.lat, v.lon]), { maxZoom: 18, padding: [40, 40] });
  else if (okc(o)) map.setView([o.lat, o.lon], Math.max(map.getZoom(), 18));
  renderMap();
}

const RANK = { error: 0, warning: 1, info: 2 };  // notes (info) are shown but never counted as problems
function issuesHtml(issues) {
  if (!issues.length) return `<p class="muted">No issues.</p>`;
  return issues.map((i) => `<div class="issue ${i.severity}" data-ref="${esc(i.ref || "")}">${i.severity === "error" ? "✖" : i.severity === "info" ? "ℹ" : "⚠"} ${esc(i.message)}</div>`).join("");
}
function bindIssues(el) { $$(".issue[data-ref]", el).forEach((d) => d.addEventListener("click", () => d.dataset.ref && goTo(d.dataset.ref))); }

// ---------------------------------------------------------------------------
// Survey data tab
// ---------------------------------------------------------------------------
const SURVEY_CODES = ["id_missing", "id_duplicate", "id_whitespace", "coord_missing", "coord_invalid", "location_duplicate", "units_invalid", "mdu_units"];
const DATA_COLS = {
  poles: ["id", "lat", "lon", "type", "height_m", "condition", "status", "notes"],
  homes: ["id", "lat", "lon", "kind", "units", "name", "address", "fat", "notes"],
  nodes: ["id", "kind", "lat", "lon", "pole", "status", "ports", "notes"],
  cables: ["id", "kind", "cores", "from_node", "to_node", "install", "status"],
};
function renderData() {
  const issues = (S.st.issues || []).filter((i) => SURVEY_CODES.includes(i.code));
  $("#dataIssues").innerHTML = issuesHtml(issues); bindIssues($("#dataIssues"));
  const ss = S.D.info.survey_status;
  $("#surveyStatus").textContent = "Survey: " + ss + (ss === "approved" && S.D.info.survey_approved_by
    ? ` by ${S.D.info.survey_approved_by} (${(S.D.info.survey_approved_at || "").slice(0, 16).replace("T", " ")})` : ""); $("#surveyStatus").className = "pill " + (ss === "approved" ? "ok" : "warn");
  const coll = $("#dataColl").value, q = $("#dataFilter").value.toLowerCase(), cols = DATA_COLS[coll];
  const bad = new Set(issues.map((i) => i.ref));
  const rows = S.D[coll].filter((x) => !q || cols.some((c) => String(x[c] ?? "").toLowerCase().includes(q)));
  $("#dataTable").innerHTML = `<table><tr>${cols.map((c) => `<th>${c}</th>`).join("")}</tr>` +
    rows.map((x) => `<tr class="click" data-id="${esc(x.id)}" style="${bad.has(x.id) ? "background:#fdecec" : ""}">${cols.map((c) => `<td>${esc(typeof x[c] === "number" && (c === "lat" || c === "lon") ? x[c].toFixed(6) : x[c])}</td>`).join("")}</tr>`).join("") +
    `</table><p class="muted">${rows.length} of ${S.D[coll].length} rows. Click a row to edit it on the map.</p>`;
  $$("#dataTable tr[data-id]").forEach((tr) => tr.addEventListener("click", () => goTo(tr.dataset.id)));
}
async function approveSurvey() {
  await flush();
  S.D.info.survey_status = "approved"; S.dirty = true;
  await save();
  const server = S.st.design.info.survey_status;
  if (server !== "approved") { S.D.info.survey_status = server; S.dirty = false; renderHeader(); }
  else toast("Survey dataset approved");
  renderData();
}
$("#dataColl").onchange = renderData; $("#dataFilter").oninput = renderData;
$("#importForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!S.pid) return toast("Create or open a project first");
  try {
    const st = await serverOp(`/api/projects/${S.pid}/import`, { method: "POST", body: new FormData(e.target) });
    const r = st.import;
    $("#importReport").textContent = `Added ${r.added}, updated ${r.updated}.\n` + r.problems.join("\n");
    S.fitted = false; renderMap(); renderData();
  } catch (err) { toast(err.message, 6000); }
});
$("#approveSurvey").onclick = () => {
  const errs = (S.st.issues || []).filter((i) => SURVEY_CODES.includes(i.code) && i.severity === "error");
  if (errs.length) return toast(`Fix ${errs.length} survey error(s) before approving`);
  approveSurvey();
};

// ---------------------------------------------------------------------------
// Materials & rules
// ---------------------------------------------------------------------------
function renderMaterials() {
  const D = S.D;
  $("#materialsTable").innerHTML = `<table><tr><th>Code</th><th>Description</th><th>Unit</th><th>Rate (${esc(D.info.currency)})</th><th>Category</th><th></th></tr>` +
    D.materials.map((m, i) => `<tr>${["code", "description", "unit", "rate", "category"].map((f) =>
      `<td><input data-m="${i}" data-f="${f}" ${f === "rate" ? 'type="number" step="any"' : ""} value="${esc(m[f])}"></td>`).join("")}
      <td><button data-del="${i}" class="danger">✕</button></td></tr>`).join("") + `</table>`;
  $$("#materialsTable input").forEach((inp) => inp.addEventListener("change", () => {
    const m = D.materials[+inp.dataset.m]; m[inp.dataset.f] = inp.dataset.f === "rate" ? +inp.value : inp.value; changed(false);
  }));
  $$("#materialsTable [data-del]").forEach((b) => b.addEventListener("click", () => { D.materials.splice(+b.dataset.del, 1); changed(false); renderMaterials(); }));

  const r = D.rules;
  $("#rulesForm").innerHTML = Object.entries(r).map(([k, v]) => {
    const label = k.replace(/_/g, " ");
    if (Array.isArray(v) && v.some((x) => typeof x === "object"))
      return `<label>${label} (JSON)<textarea data-r="${k}" data-t="json">${esc(JSON.stringify(v, null, 1))}</textarea></label>`;
    if (Array.isArray(v)) return `<label>${label} (comma separated)<input data-r="${k}" data-t="list" value="${esc(v.join(", "))}"></label>`;
    if (RULE_CHOICES[k]) return `<label>${label}<select data-r="${k}">${RULE_CHOICES[k].map((o) =>
      `<option ${o === v ? "selected" : ""}>${o}</option>`).join("")}</select></label>`;
    if (typeof v === "boolean") return `<label class="inline"><input type="checkbox" data-r="${k}" data-t="bool" ${v ? "checked" : ""}> ${label}</label>`;
    if (typeof v === "object") return Object.entries(v).map(([kk, vv]) =>
      `<label>${label}: ${esc(kk)}<input data-r="${k}" data-k="${esc(kk)}" value="${esc(vv)}"></label>`).join("");
    return `<label>${label}<input data-r="${k}" ${typeof v === "number" ? 'type="number" step="any"' : ""} value="${esc(v)}"></label>`;
  }).join("");
  $$("#rulesForm [data-r]").forEach((inp) => inp.addEventListener("change", () => {
    const k = inp.dataset.r, t = inp.dataset.t;
    if (inp.dataset.k) r[k][inp.dataset.k] = inp.value;
    else if (t === "bool") r[k] = inp.checked;
    else if (t === "list") r[k] = inp.value.split(",").map((x) => x.trim()).filter(Boolean);
    else if (t === "json") { try { r[k] = JSON.parse(inp.value); } catch (e) { return toast("Invalid JSON: " + e.message); } }
    else if (typeof r[k] === "number") {
      const n = RULE_INTS.has(k) ? parseInt(inp.value, 10) : parseFloat(inp.value);
      if (inp.value === "" || isNaN(n) || n < 0) { toast(`${k.replace(/_/g, " ")} must be a number of 0 or more`); inp.value = r[k]; return; }
      r[k] = n; inp.value = n;
    } else r[k] = inp.value;
    changed(false);
  }));

  $("#adjTable").innerHTML = `<table><tr><th>Material</th><th>Quantity change</th><th>Reason</th><th>By</th><th></th></tr>` +
    D.adjustments.map((a, i) => `<tr><td><select data-a="${i}" data-f="code">${D.materials.map((m) => `<option ${m.code === a.code ? "selected" : ""}>${esc(m.code)}</option>`).join("")}</select></td>
      <td><input data-a="${i}" data-f="qty" type="number" step="any" value="${a.qty}"></td>
      <td><input data-a="${i}" data-f="reason" value="${esc(a.reason)}"></td><td><input data-a="${i}" data-f="by" value="${esc(a.by)}"></td>
      <td><button data-adel="${i}" class="danger">✕</button></td></tr>`).join("") + `</table>`;
  $$("#adjTable [data-a]").forEach((inp) => inp.addEventListener("change", () => {
    const a = D.adjustments[+inp.dataset.a]; a[inp.dataset.f] = inp.dataset.f === "qty" ? +inp.value : inp.value; changed(false);
  }));
  $$("#adjTable [data-adel]").forEach((b) => b.addEventListener("click", () => { D.adjustments.splice(+b.dataset.adel, 1); changed(false); renderMaterials(); }));
}
const RULE_CHOICES = { tension_pole_passing: ["jhook", "none", "tension"] };
const RULE_INTS = new Set(["jhook_per_straight_cable", "tension_per_cable_end", "tension_per_cable_corner",
  "max_suspension_poles", "upb_tension_per_bracket", "upb_per_equipment", "default_pon_split", "default_fat_split",
  "default_fat_ports"]);
async function loadDefaults(what) {
  if (!confirm(`Replace this project's ${what === "rules" ? "construction rules" : "material catalogue"} with the company defaults?`)) return;
  const def = await api("/api/defaults");
  if (what === "rules") S.D.rules = def.rules; else S.D.materials = def.materials;
  changed(false); renderMaterials(); toast("Company defaults loaded");
}
$("#resetRules").onclick = () => loadDefaults("rules");
$("#priceFile").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  e.target.value = "";
  if (!f || !S.pid) return;
  const fd = new FormData(); fd.append("file", f);
  try {
    const st = await serverOp(`/api/projects/${S.pid}/prices`, { method: "POST", body: fd });
    const r = st.prices;
    $("#priceReport").textContent = `${f.name}: ${r.updated.length} rate(s) changed, ${r.added.length} item(s) added, ${r.unchanged} unchanged.\n` +
      [...r.updated, ...r.added.map((a) => "added " + a), ...r.problems].join("\n");
    renderMaterials();
  } catch (err) { toast(err.message, 6000); }
});
$("#resetMaterials").onclick = () => loadDefaults("materials");
$("#addMaterial").onclick = () => { S.D.materials.push({ code: "NEW-ITEM", description: "", unit: "ea", rate: 0, category: "General" }); changed(false); renderMaterials(); };
$("#addAdj").onclick = () => { S.D.adjustments.push({ code: S.D.materials[0]?.code || "", qty: 0, reason: "", by: "" }); changed(false); renderMaterials(); };

// ---------------------------------------------------------------------------
// Splicing
// ---------------------------------------------------------------------------
function coreDot(hex) { return `<span class="core" style="background:${hex}"></span>`; }
const latest = {};  // per-panel request counter: ignore responses superseded by a newer refresh
async function fresh(panel, fn) {
  const n = (latest[panel] = (latest[panel] || 0) + 1);
  const r = await fn();
  return n === latest[panel] ? r : null;
}

async function renderSplicing() {
  await flush();
  const sel = $("#spNode"), cur = sel.value;
  sel.innerHTML = S.D.nodes.map((n) => `<option value="${esc(n.id)}">${esc(n.id)} (${n.kind})</option>`).join("");
  if (cur && S.D.nodes.some((n) => n.id === cur)) sel.value = cur;
  const node = sel.value;
  const sp = await fresh("splicing", () => api(`/api/projects/${S.pid}/splicing${node ? `?node=${encodeURIComponent(node)}` : ""}`));
  if (!sp) return;
  const info = sp.nodes[0];
  const D = S.D;
  if (info) {
    $("#spSplitters").innerHTML = (info.splitters.length ? `<table><tr><th>ID</th><th>Stage</th><th>Ratio</th><th></th></tr>` +
      info.splitters.map((s) => `<tr><td>${esc(s.id)}</td><td>${s.stage}</td><td><select data-sp="${esc(s.id)}">${[2, 4, 8, 16, 32, 64].map((o) => `<option value="${o}" ${o === s.outputs ? "selected" : ""}>1x${o}</option>`).join("")}</select></td>
      <td><button class="danger" data-spdel="${esc(s.id)}">✕</button></td></tr>`).join("") + `</table>` : `<p class="muted">No splitters.</p>`) +
      `<div class="row"><select id="spStage"><option value="1">Stage 1</option><option value="2">Stage 2</option></select><button id="spAddSplit">Add splitter</button></div>`;
    $$("[data-sp]").forEach((s) => s.addEventListener("change", () => { D.splitters.find((x) => x.id === s.dataset.sp).outputs = +s.value; changed(false); }));
    $$("[data-spdel]").forEach((b) => b.addEventListener("click", async () => {
      const id = b.dataset.spdel;
      D.splitters = D.splitters.filter((x) => x.id !== id);
      D.connections = D.connections.filter((c) => ![c.a, c.b].some((e) => e.kind.startsWith("splitter") && e.ref === id));
      changed(false); await renderSplicing();
    }));
    $("#spAddSplit").onclick = async () => {
      const stage = +$("#spStage").value; let id = `S${stage}-${node}`, k = 2;
      while (D.splitters.some((s) => s.id === id)) id = `S${stage}-${node}-${k++}`;
      D.splitters.push({ id, node, stage, outputs: stage === 1 ? D.rules.default_pon_split : D.rules.default_fat_split });
      changed(false); await renderSplicing();
    };

    $("#spConnections").innerHTML = info.connections.length ? info.connections.map((c) =>
      `<div class="conn"><span class="muted">${esc(c.id)}${c.auto ? "" : "*"}</span>
        <span class="chip">${c.a_hex ? coreDot(c.a_hex) : ""}${esc(c.a_label)}</span>
        <span class="wire" style="background:${c.a_hex || c.b_hex || "#555"}"></span>
        <span class="chip">${c.b_hex ? coreDot(c.b_hex) : ""}${esc(c.b_label)}</span>
        <button class="danger" data-cdel="${esc(c.id)}">✕</button></div>`).join("") + `<p class="muted">* manual connection</p>`
      : `<p class="muted">No connections at this node.</p>`;
    $$("[data-cdel]").forEach((b) => b.addEventListener("click", async () => {
      D.connections = D.connections.filter((c) => c.id !== b.dataset.cdel); changed(false); await renderSplicing();
    }));

    const nodeObj = D.nodes.find((n) => n.id === node);
    const refs = { cable: info.cables, splitter_in: info.splitters.map((s) => s.id), splitter_out: info.splitters.map((s) => s.id),
                   olt: nodeObj?.kind === "POP" ? [node] : [] };
    const endForm = (p) => `<div class="row"><b>${p.toUpperCase()}</b>
      <select id="sp${p}k">${Object.keys(refs).map((k) => `<option>${k}</option>`).join("")}</select>
      <select id="sp${p}r"></select><input id="sp${p}n" type="number" min="1" value="1" style="width:70px" title="core / port"></div>`;
    $("#spAdd").innerHTML = endForm("a") + endForm("b") + `<button id="spAddConn">Add connection</button>`;
    for (const p of ["a", "b"]) {
      const fill = () => { $(`#sp${p}r`).innerHTML = refs[$(`#sp${p}k`).value].map((r) => `<option>${esc(r)}</option>`).join(""); };
      $(`#sp${p}k`).onchange = fill; fill();
    }
    $("#spAddConn").onclick = async () => {
      const end = (p) => ({ kind: $(`#sp${p}k`).value, ref: $(`#sp${p}r`).value, n: +$(`#sp${p}n`).value || 1 });
      const a = end("a"), b = end("b");
      if (!a.ref || !b.ref) return toast("Choose both ends");
      let i = 1; const ids = new Set(D.connections.map((c) => c.id));
      while (ids.has("M" + String(i).padStart(4, "0"))) i++;
      D.connections.push({ id: "M" + String(i).padStart(4, "0"), node, a, b, auto: false, note: "" });
      changed(false); await renderSplicing();
      const errs = (S.st.issues || []).filter((x) => ["core_duplicate", "port_duplicate", "core_range", "core_reserved", "port_range", "cable_absent"].includes(x.code));
      if (errs.length) toast(errs[0].message, 6000);
    };
  } else {
    ["#spSplitters", "#spConnections", "#spAdd"].forEach((s) => ($(s).innerHTML = `<p class="muted">Add equipment on the map first.</p>`));
  }
  $("#spTraces").innerHTML = Object.entries(sp.traces).map(([fat, t]) =>
    `<div class="trace ${t.ok ? "" : "bad"}"><b>${esc(fat)}</b>: ${t.ok ? "fed from " + esc(t.olt) : "NOT FED – " + esc(t.reason)}<br>
     <span class="muted">${t.steps.map((s) => `${esc(s.node)}: ${esc(s.from)} → ${esc(s.to)}`).join("<br>")}</span></div>`).join("") || `<p class="muted">No FAT splitters yet.</p>`;
  $("#spCores").innerHTML = sp.cores.map((c) => `<div style="margin-bottom:8px"><b>${esc(c.cable)}</b> ${c.cores}C ${c.kind} —
    used ${c.used}, reserved ${c.reserved}, spare ${c.spare}<br>${c.core_list.map((k) =>
      `<span class="corecell ${k.status}" title="${esc(k.uses.join(" | ") || k.status)}">${coreDot(k.fibre_hex)}${k.n}</span>`).join("")}</div>`).join("");
}
$("#spNode").onchange = renderSplicing;
$("#btnAllocate").onclick = async () => {
  try {
    const st = await serverOp(`/api/projects/${S.pid}/allocate`);
    const r = st.result;
    toast(`Allocated ${r.connections} connections, created ${r.splitters} splitters` + (r.issues.length ? ` — ${r.issues.length} problem(s): ${r.issues[0]}` : ""), 7000);
    await renderSplicing();
  } catch (e) { toast(e.message); }
};

// ---------------------------------------------------------------------------
// Schedules
// ---------------------------------------------------------------------------
async function renderSchedules() {
  await flush();
  const c = await fresh("calc", () => api(`/api/projects/${S.pid}/calc`));
  if (!c) return;
  const t = S.st?.sector;
  if (t && !t.fibre_tools) renderSectorSchedules(c, t); else renderFibreSchedules(c);
  $$("#schPoles tr[data-id]").forEach((tr) => tr.addEventListener("click", () => goTo(tr.dataset.id)));
  $("#schBom").innerHTML = `<table><tr><th>Code</th><th>Description</th><th>Unit</th><th class="num">Calc.</th><th class="num">Adj.</th><th class="num">Qty</th></tr>` +
    c.bom.map((l) => `<tr><td>${esc(l.code)}</td><td>${esc(l.description)}</td><td>${esc(l.unit)}</td><td class="num">${fmt(l.calculated)}</td><td class="num">${l.adjustment ? fmt(l.adjustment) : ""}</td><td class="num"><b>${fmt(l.qty)}</b></td></tr>`).join("") + `</table>`;
  renderBoqAfterSchedules(c);
}

// other sectors: lines in the sector's sizes (no slack loops), and the support schedule (manholes, marker posts,
// poles, lighting columns) with the sector's hardware, equipment and recorded details
function renderSectorSchedules(c, t) {
  const overhead = t.install === "aerial";
  $("#schCables").innerHTML = `<p class="muted">Proposed ${esc(t.line.toLowerCase())}s only. Length = measured + extra %${overhead ? " + end allowance + sag per point" : ""}, rounded up.</p>
    <table><tr><th>${esc(t.line)}</th><th>Type</th><th>${esc(t.size)}</th><th class="num">Measured m</th><th class="num">Extra m</th>${overhead ? `<th class="num">End m</th><th class="num">Sag m</th>` : ""}<th class="num">Total m</th><th class="num">Road X</th></tr>` +
    c.cables.map((x) => `<tr><td>${esc(x.cable)}</td><td>${esc(t.lines[x.kind] || x.kind)}</td><td>${sizeText(x.cores)}</td><td class="num">${fmt(x.route_m, 1)}</td><td class="num">${fmt(x.extra_m, 1)}</td>${overhead ? `<td class="num">${fmt(x.end_m)}</td><td class="num">${fmt(x.sag_m, 1)}</td>` : ""}<td class="num"><b>${fmt(x.total_m)}</b></td><td class="num">${x.crossings}</td></tr>`).join("") + `</table>`;
  const P = c.poles, cols = t.schedule, sum = (k) => P.reduce((a, p) => a + (typeof p[k] === "number" ? p[k] : p[k].length), 0);
  const fields = t.details?.pole || [];
  const det = (id) => { const d = (find("pole", id) || {}).details || {};
    return fields.filter((f) => d[f.key] != null).map((f) => `${f.label}: ${d[f.key]}${f.unit ? " " + f.unit : ""}`).join("; "); };
  $("#schPoles").innerHTML = `<table><tr><th>${esc(t.support)} ID</th><th>Location (Lat, Long)</th><th class="num">${esc(t.line)}s</th>${cols.map(([, h]) => `<th class="num">${esc(h)}</th>`).join("")}${fields.length ? "<th>Details</th>" : ""}<th>Notes</th></tr>` +
    P.map((p) => `<tr class="click" data-id="${esc(p.pole)}"><td>${esc(p.pole)}</td><td>${p.lat != null ? p.lat.toFixed(5) + ", " + p.lon.toFixed(5) : "-"}</td><td class="num">${p.cables.length}</td>${cols.map(([k]) => `<td class="num">${p[k]}</td>`).join("")}${fields.length ? `<td>${esc(det(p.pole))}</td>` : ""}<td>${esc(p.notes.join("; "))}</td></tr>`).join("") +
    `<tr class="total"><td>Total</td><td></td><td class="num">${sum("cables")}</td>${cols.map(([k]) => `<td class="num">${sum(k)}</td>`).join("")}${fields.length ? "<td></td>" : ""}<td></td></tr></table>`;
}

function renderFibreSchedules(c) {
  $("#schCables").innerHTML = `<p class="muted">Proposed cables only. Length = measured + extra % + end allowance + sag per point (+ risers), rounded up; then slack loops at equipment.</p>
    <table><tr><th>Cable</th><th>Type</th><th>Cores</th><th class="num">Measured m</th><th class="num">Extra m</th><th class="num">End m</th><th class="num">Sag m</th><th class="num">Rounded m</th><th class="num">Slack loops</th><th class="num">Slack m</th><th class="num">Total m</th><th class="num">Road X</th></tr>` +
    c.cables.map((x) => `<tr><td>${esc(x.cable)}</td><td>${x.kind}</td><td>${x.cores}</td><td class="num">${fmt(x.route_m, 1)}</td><td class="num">${fmt(x.extra_m, 1)}</td><td class="num">${fmt(x.end_m)}</td><td class="num">${fmt(x.sag_m, 1)}</td><td class="num">${fmt(x.rounded_m)}</td><td class="num">${x.slack_loops}</td><td class="num">${fmt(x.slack_m)}</td><td class="num"><b>${fmt(x.total_m)}</b></td><td class="num">${x.crossings}</td></tr>`).join("") + `</table>`;
  const P = c.poles, sum = (k) => P.reduce((a, p) => a + (typeof p[k] === "number" ? p[k] : p[k].length), 0);
  $("#schPoles").innerHTML = `<table><tr><th>Pole ID</th><th>Location (Lat, Long)</th><th class="num">Cables</th><th class="num">Tension Clamps</th><th class="num">UPB</th><th class="num">J-Hooks</th><th class="num">Ext. Arm</th><th class="num">JB</th><th class="num">Enclosure</th><th class="num">FAT</th><th>Notes</th></tr>` +
    P.map((p) => `<tr class="click" data-id="${esc(p.pole)}"><td>${esc(p.pole)}</td><td>${p.lat != null ? p.lat.toFixed(5) + ", " + p.lon.toFixed(5) : "-"}</td><td class="num">${p.cables.length}</td><td class="num">${p.tension}</td><td class="num">${p.upb}</td><td class="num">${p.jhooks}</td><td class="num">${p.ext_arms}</td><td class="num">${p.jb}</td><td class="num">${p.enclosures}</td><td class="num">${p.fats}</td><td>${esc(p.notes.join("; "))}</td></tr>`).join("") +
    `<tr class="total"><td>Total</td><td></td><td class="num">${sum("cables")}</td><td class="num">${sum("tension")}</td><td class="num">${sum("upb")}</td><td class="num">${sum("jhooks")}</td><td class="num">${sum("ext_arms")}</td><td class="num">${sum("jb")}</td><td class="num">${sum("enclosures")}</td><td class="num">${sum("fats")}</td><td></td></tr></table>`;
}

function renderBoqAfterSchedules(c) {
  $("#schBoq").innerHTML = `<table><tr><th>Description</th><th>Unit</th><th class="num">Qty</th><th class="num">Rate</th><th class="num">Total (${esc(c.currency)})</th></tr>` +
    c.bom.map((l) => `<tr><td>${esc(l.description)}</td><td>${esc(l.unit)}</td><td class="num">${fmt(l.qty)}</td><td class="num">${l.rate == null ? "n/a" : fmt(l.rate, 2)}</td><td class="num">${l.total == null ? "n/a" : fmt(l.total, 2)}</td></tr>`).join("") +
    `<tr class="total"><td>Total</td><td></td><td></td><td></td><td class="num">${fmt(c.boq_total, 2)}</td></tr></table>`;
}

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------
const INFO = [["name", "text"], ["area", "text"], ["client", "text"], ["prepared_by", "text"], ["survey_date", "date"], ["currency", "text"],
  ["region", "text"], ["zone", "text"], ["cluster", "text"], ["surveyors", "text"],
  ["olt_name", "text"], ["olt_ports_available", "text"], ["interception", "text"], ["feeder_cores_available", "text"],
  ["interception_node", "text"], ["interception_nodes", "list"], ["company", "text"], ["drawing_no", "text"], ["lead_planner", "text"], ["planned_by", "text"], ["drawn_by", "text"],
  ["checked_by", "text"], ["approved_by", "text"],
  ["introduction", "textarea"], ["findings", "textarea"], ["proposed_solution", "textarea"], ["special_requirements", "textarea"], ["recommendations", "textarea"]];
function renderReport() {
  const info = S.D.info;
  $("#infoForm").innerHTML = INFO.map(([f, k]) => `<label>${f.replace(/_/g, " ")}${k === "textarea" ? `<textarea data-i="${f}">${esc(info[f])}</textarea>` : `<input data-i="${f}" data-kind="${k}" type="${k === "list" ? "text" : k}" value="${esc(k === "list" ? (info[f] || []).join(", ") : info[f])}">`}</label>`).join("");
  $$("#infoForm [data-i]").forEach((inp) => inp.addEventListener("change", () => {
    info[inp.dataset.i] = inp.dataset.kind === "list" ? inp.value.split(",").map((x) => x.trim()).filter(Boolean) : inp.value;
    changed(false);
    if (inp.dataset.i === "name") { const o = $(`#projectSelect option[value="${S.pid}"]`); if (o) o.textContent = inp.value; }
  }));
  $("#photos").innerHTML = S.D.photos.map((p, i) => `<figure><img src="/api/projects/${S.pid}/photos/${esc(p.file)}" alt="">
    <input data-ph="${i}" value="${esc(p.caption)}" placeholder="Caption"><button class="danger" data-phdel="${i}">Remove</button></figure>`).join("");
  $$("[data-ph]").forEach((inp) => inp.addEventListener("change", () => { S.D.photos[+inp.dataset.ph].caption = inp.value; changed(false); }));
  $$("[data-phdel]").forEach((b) => b.addEventListener("click", () => { S.D.photos.splice(+b.dataset.phdel, 1); changed(false); renderReport(); }));
  renderPhotoAi();
}
$("#photoForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { await serverOp(`/api/projects/${S.pid}/photos`, { method: "POST", body: new FormData(e.target) }); e.target.reset(); renderReport(); }
  catch (err) { toast(err.message); }
});

// ---------------------------------------------------------------------------
// QA & revisions
// ---------------------------------------------------------------------------
async function renderQA() {
  await flush();
  const issues = S.st.issues;
  $("#qaIssues").innerHTML = issuesHtml([...issues].sort((a, b) => (RANK[a.severity] ?? 3) - (RANK[b.severity] ?? 3)));
  bindIssues($("#qaIssues"));
  renderComments();
  const ds = S.D.info.design_status;
  $("#designStatus").textContent = ds; $("#designStatus").className = "pill " + (ds === "approved" ? "ok" : ds === "in_review" ? "warn" : "");
  const revs = await fresh("revisions", () => api(`/api/projects/${S.pid}/revisions`));
  if (!revs) return;
  $("#revisions").innerHTML = `<table><tr><th>Rev</th><th>Date</th><th>Author</th><th>Status</th><th>Note</th><th>Data</th><th></th></tr>` +
    revs.map((r) => `<tr><td>${r.version}</td><td>${esc(r.created.replace("T", " ").slice(0, 16))}</td><td>${esc(r.author)}</td><td>${esc(r.status)}</td><td>${esc(r.note)}</td><td>${esc(r.hash)}</td>
      <td><button data-restore="${r.version}">Restore</button></td></tr>`).join("") + `</table>` + (revs.length ? "" : `<p class="muted">No revisions saved yet.</p>`);
  $$("[data-restore]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm(`Restore revision ${b.dataset.restore}? Current unsaved work will be replaced (save a revision first if needed).`)) return;
    await serverOp(`/api/projects/${S.pid}/revisions/${b.dataset.restore}/restore`); toast("Revision restored");
  }));
}
$$("[data-rev]").forEach((b) => b.addEventListener("click", async () => {
  const note = $("#revNote").value.trim();
  if (!note && !b.dataset.rev) return toast("Enter a revision note");
  try {
    await serverOp(`/api/projects/${S.pid}/revisions`, jsonBody({ note: note || `Status: ${b.dataset.rev}`, design_status: b.dataset.rev || null }));
    $("#revNote").value = ""; toast("Revision saved"); renderQA();
  } catch (e) { toast(e.message, 6000); }
}));

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
const FORMAT_LABEL = { zip: "CSV (zip)", xlsx: "Excel", docx: "Word", "lld.zip": "DXF + map (zip)" };
function renderOutputs() {
  const outs = S.st.outputs;
  $("#outputs").innerHTML = Object.entries(outs).map(([k, o]) => `<div class="outrow"><span class="name">${esc(o.title)}</span>
    ${o.formats.map((f) => `<a href="/api/projects/${S.pid}/export/${k}.${f}" data-dl><button>${FORMAT_LABEL[`${k}.${f}`] || FORMAT_LABEL[f] || f.toUpperCase()}</button></a>`).join("")}
    <span class="spacer"></span>${!o.last ? `<span class="muted">not generated yet</span>` : o.stale ? `<span class="stale">Needs regenerating (design changed since last generated from data ${esc(o.last.hash)})</span>` : `<span class="fresh">Up to date (${esc(o.last.created.slice(0, 16).replace("T", " "))})</span>`}</div>`).join("");
  $$("#outputs [data-dl]").forEach((a) => a.addEventListener("click", async (e) => {
    if (S.dirty || S.timer) { e.preventDefault(); await flush(); window.location = a.href; }
    setTimeout(refreshState, 2500);
  }));
}
async function refreshState() { await flush(); S.st = await api(`/api/projects/${S.pid}`); renderHeader(); renderActiveTab(false); }
$("#btnPackage").onclick = async () => {
  await flush();
  let url = `/api/projects/${S.pid}/package.zip`;
  const r = await fetch(url);
  if (r.status === 409) {
    const j = await r.json();
    if (!confirm(j.detail + "\n\nDownload the package anyway (marked with open issues in MANIFEST.json)?")) return;
    url += "?force=true";
  } else if (!r.ok) return toast("Package failed: " + r.statusText);
  window.location = url;
  setTimeout(refreshState, 4000);
};

// ---------------------------------------------------------------------------
// Toolbar & startup
// ---------------------------------------------------------------------------
$("#cableCores").innerHTML = CORES.map((c) => `<option value="${c}" ${c === 12 ? "selected" : ""}>${c}C</option>`).join("");
$("#cableKind").onchange = () => { $("#cableCores").value = { main: 48, spur: 12, drop: 2 }[$("#cableKind").value]; };
$$("#toolbar [data-mode]").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
$("#btnDelete").onclick = deleteSelected;
$("#btnAutoDesign").onclick = async () => {
  const existing = S.D.nodes.filter((n) => n.status === "existing" && ["POP", "ENCLOSURE", "PR_ENCLOSURE"].includes(n.kind));
  if (!existing.length) return toast("Add the existing closure or POP the network starts from (status: existing) first", 7000);
  let root = S.D.info.interception_node;
  if (!root || !existing.some((n) => n.id === root)) {
    root = prompt("Interception point - ID of the existing closure / POP the network starts from:\n" +
      existing.map((n) => n.id).join(", "), existing[0].id);
    if (!root) return;
    if (!existing.some((n) => n.id === root.trim())) return toast("No existing closure / POP with that ID");
    S.D.info.interception_node = root.trim(); changed(false);
  }
  const proposed = S.D.cables.filter((c) => c.status === "proposed").length + S.D.nodes.filter((n) => n.status === "proposed").length;
  if (proposed && !confirm(`Replace the current proposed design (${proposed} cables/equipment) with an automatic design from ${root}?
Save a revision first if you want to keep it.`)) return;
  try {
    const st = await serverOp(`/api/projects/${S.pid}/auto-design`, jsonBody(autoDesignOptions()));
    const r = st.result;
    toast(r.log.join(" · ") + (r.allocation_issues.length ? ` — ${r.allocation_issues.length} allocation issue(s)` : ""), 9000);
    S.fitted = false; renderMap();
  } catch (e) { toast(e.message, 7000); }
};
$("#btnAssign").onclick = async () => {
  try { const st = await serverOp(`/api/projects/${S.pid}/assign-homes`); toast(`Assigned ${st.result.assigned} premises; ${st.result.unassigned.length} still unserved`); }
  catch (e) { toast(e.message); }
};
$("#projectSelect").onchange = (e) => e.target.value && openProject(e.target.value);
$("#newProject").onclick = async () => {
  // left empty, the server names it after the company's sector ("New water supply project")
  const name = prompt("Project name (leave empty for a default name)", ""); if (name === null) return;
  await flush(); const st = await api("/api/projects", jsonBody({ name })); await loadProjects(st.id);
};
$("#newSample").onclick = async () => { await flush(); const st = await api("/api/projects", jsonBody({ sample: true })); await loadProjects(st.id); };
window.addEventListener("beforeunload", (e) => { if (S.dirty || S.timer) { save(); e.preventDefault(); } });

setMode("select");
loadProjects().catch((e) => toast("Could not load projects: " + e.message, 8000));
