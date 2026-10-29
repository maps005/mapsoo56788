"use strict";
// AutoCAD-style commands for the drawing tab: the command line (aliases, typed coordinates), more draw tools
// (arc, polygon, point, hatch, linear / radius / angular dimensions), modify tools (scale, mirror, array, trim,
// extend, fillet, join, explode, break, match properties) and the drafting layer manager.
// Builds on overview.js (CAD state, snap, selection, addMarkup, cadApply, cadCopyApply) so edits save, undo and
// export like everything else. Drawing coordinates are metres, y down; typed coordinates are X east, Y north.

const LINE_KINDS = ["line", "polyline"];
const markupById = (id) => (S.D.markups || []).find((m) => m.id === id);
const geomOf = (m) => markupGeometry(m, CAD.proj.xy);
const xyOf = (m) => m.points.map((p) => CAD.proj.xy(p[0], p[1]));
const ptsLatLon = (P) => P.map(([x, y]) => CAD.proj.inverse(x, y));
const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
const len = (v) => Math.hypot(v[0], v[1]);

// ---- commands ---------------------------------------------------------------------------------------------
// each command: prompt(step) -> message; point(p) -> handle a point; value(text) -> typed number / option;
// enter() -> finish; hover(p, g) -> preview. CAD.cmd = {name, step, data}
const CMDS = {
  arc: {
    label: "Arc", prompt: (c) => ["Arc: click the start point.", "Arc: click a point on the arc.", "Arc: click the end point."][c.step],
    point(c, q) { c.data.pts.push(q); if (c.data.pts.length === 3) { addMarkup("arc", c.data.pts.splice(0)); return "again"; } },
    hover(c, q, g) { const P = [...c.data.pts, q]; if (P.length === 3) { const a = arc3(...P); if (a) previewLine(g, a.pts()); } else if (P.length > 1) previewLine(g, P); },
  },
  polygon: {
    label: "Polygon", prompt: (c) => c.step ? `Polygon (${c.data.sides} sides): click a corner.` : `Polygon: type the number of sides (now ${c.data.sides}) or click the centre.`,
    start: (c) => { c.data.sides = CAD.polySides || 6; },
    value(c, t) { const n = parseInt(t, 10); if (n >= 3 && n <= 64) { c.data.sides = CAD.polySides = n; return "prompt"; } return toast("Sides: a whole number from 3 to 64"); },
    point(c, q) {
      if (!c.step) { c.data.centre = q; c.step = 1; return "prompt"; }
      addMarkup("polyline", polygonPts(c.data.centre, q, c.data.sides), { closed: true }); return "again";
    },
    hover(c, q, g) { if (c.step) previewLine(g, [...polygonPts(c.data.centre, q, c.data.sides), polygonPts(c.data.centre, q, c.data.sides)[0]]); },
  },
  point: { label: "Point", prompt: () => "Point: click where it goes.", point(c, q) { addMarkup("point", [q]); } },
  hatch: {
    label: "Hatch", prompt: () => "Hatch: click inside (or on) a closed drafting shape to fill it with the current colour; again to clear.",
    point(c, q) {
      const hit = closedAt(q);
      if (!hit) return toast("No closed polyline, rectangle, polygon or circle there");
      hit.fill = hit.fill ? "" : ($("#cadColour").value || "#00e5ff");
      changed();
    },
  },
  dimlinear: {
    label: "Linear dimension", prompt: (c) => c.step ? "Linear dimension: click the second point (horizontal or vertical, whichever is longer)." : "Linear dimension: click the first point.",
    point(c, q) {
      if (!c.step) { c.data.a = q; c.step = 1; return "prompt"; }
      const a = c.data.a, dim = Math.abs(q[0] - a[0]) >= Math.abs(q[1] - a[1]) ? "horizontal" : "vertical";
      addMarkup("dimension", [a, q], { dim }); return "again";
    },
    hover(c, q, g) { if (c.step) previewLine(g, [c.data.a, q]); },
  },
  dimradius: {
    label: "Radius dimension", prompt: () => "Radius dimension: click a drafting circle or arc where the radius line should point.",
    point(c, q) {
      const M = (CAD.feats.marks || []).filter((x) => x.centre && !x.locked).sort((a, b) => Math.abs(len(sub(q, a.centre)) - a.r) - Math.abs(len(sub(q, b.centre)) - b.r))[0];
      if (!M || Math.abs(len(sub(q, M.centre)) - M.r) > 12 * cadPx()) return toast("Click on a drafting circle or arc");
      const d = sub(q, M.centre), k = M.r / (len(d) || 1);
      addMarkup("dimension", [M.centre, [M.centre[0] + d[0] * k, M.centre[1] + d[1] * k]], { dim: "radius" });
    },
  },
  dimangular: {
    label: "Angular dimension", prompt: (c) => ["Angular dimension: click a point on the first arm.", "Angular dimension: click the vertex.", "Angular dimension: click a point on the second arm."][c.step],
    point(c, q) { c.data.pts.push(q); c.step++; if (c.data.pts.length === 3) { addMarkup("dimension", c.data.pts.splice(0), { dim: "angular" }); return "again"; } return "prompt"; },
    hover(c, q, g) { if (c.data.pts.length) previewLine(g, [...c.data.pts, q]); },
  },
  scale: {
    label: "Scale", needsSel: true,
    prompt: (c) => c.step ? "Scale: type the factor (e.g. 2 or 0.5) and press Enter." : "Scale: click the base point.",
    point(c, q) { if (!c.step) { c.data.base = q; c.step = 1; return "prompt"; } },
    value(c, t) {
      const k = +t;
      if (!c.step || !(k > 0)) return toast(c.step ? "Scale factor: a number above 0" : "Click the base point first");
      const b = c.data.base;
      cadApply((x, y) => [b[0] + (x - b[0]) * k, b[1] + (y - b[1]) * k], null);
      for (const s of CAD.sel) if (s.type === "markup") { const m = markupById(s.id); if (m) m.size = Math.min(50, Math.max(0.2, m.size * k)); }
      return "done";
    },
  },
  mirror: {
    label: "Mirror", needsSel: true,
    prompt: (c) => c.step ? "Mirror: click the second point of the mirror line." : "Mirror: click the first point of the mirror line (the originals stay; delete them if needed).",
    point(c, q) {
      if (!c.step) { c.data.a = q; c.step = 1; return "prompt"; }
      const a = c.data.a, d = sub(q, a), l2 = d[0] * d[0] + d[1] * d[1];
      if (!l2) return toast("The mirror line needs two different points");
      const f = (x, y) => { const t = ((x - a[0]) * d[0] + (y - a[1]) * d[1]) / l2, px = a[0] + t * d[0], py = a[1] + t * d[1]; return [2 * px - x, 2 * py - y]; };
      const { made, cables } = cadCopyApply(f, true);
      CAD.sel = made; S.sel = null; changed();
      toast(`Mirrored ${made.length}${cables ? `; ${cables} cable(s) not copied` : ""}`);
      return "done";
    },
    hover(c, q, g) { if (c.step) previewLine(g, [c.data.a, q]); },
  },
  array: {
    label: "Array", needsSel: true,
    prompt: () => "Array: type rows columns row-spacing column-spacing in metres (e.g. 1 5 0 10) and press Enter.",
    value(c, t) {
      const [rows, cols, dy, dx] = t.split(/[\s,]+/).map(Number);
      if (!(rows >= 1 && cols >= 1) || rows * cols > 200 || [dy, dx].some((v) => !isFinite(v))) return toast("Array: rows columns row-spacing column-spacing (at most 200 items)");
      const sel = [...CAD.sel], all = [];
      for (let r = 0; r < rows; r++) for (let k = 0; k < cols; k++) {
        if (!r && !k) continue;
        CAD.sel = sel;
        all.push(...cadCopyApply((x, y) => [x + k * dx, y - r * dy], true).made);  // rows go north (up)
      }
      CAD.sel = [...sel, ...all]; S.sel = null; changed();
      toast(`Array: ${all.length} copies`);
      return "done";
    },
  },
  arraypolar: {
    label: "Polar array", needsSel: true,
    prompt: (c) => c.step ? "Polar array: type the number of items and the angle to fill (e.g. 6 360) and press Enter." : "Polar array: click the centre.",
    point(c, q) { if (!c.step) { c.data.c = q; c.step = 1; return "prompt"; } },
    value(c, t) {
      const [n, fill = 360] = t.split(/[\s,]+/).map(Number);
      if (!c.step || !(n >= 2 && n <= 200)) return toast(c.step ? "Polar array: items (2-200) and angle" : "Click the centre first");
      const step = (fill >= 360 ? 360 / n : fill / (n - 1)) * Math.PI / 180, ctr = c.data.c, sel = [...CAD.sel], all = [];
      for (let i = 1; i < n; i++) {
        const a = -step * i, cs = Math.cos(a), sn = Math.sin(a);  // counter-clockwise on screen
        CAD.sel = sel;
        all.push(...cadCopyApply((x, y) => [ctr[0] + (x - ctr[0]) * cs - (y - ctr[1]) * sn, ctr[1] + (x - ctr[0]) * sn + (y - ctr[1]) * cs], true).made);
      }
      CAD.sel = [...sel, ...all]; S.sel = null; changed();
      toast(`Polar array: ${all.length} copies`);
      return "done";
    },
  },
  trim: {
    label: "Trim", prompt: () => "Trim: click the part of a drafting line or polyline to cut away (at its crossings with other lines). Esc ends.",
    point(c, q) { trimAt(q); },
  },
  extend: {
    label: "Extend", prompt: () => "Extend: click near the end of a drafting line or polyline to extend it to the next line it meets. Esc ends.",
    point(c, q) { extendAt(q); },
  },
  fillet: {
    label: "Fillet", prompt: (c) => c.step ? "Fillet: click the second line." : `Fillet (radius ${c.data.r} m; type a radius to change): click the first drafting line.`,
    start: (c) => { c.data.r = CAD.filletR || 0; },
    value(c, t) { const r = +t; if (!(r >= 0)) return toast("Radius: 0 or more"); c.data.r = CAD.filletR = r; return "prompt"; },
    point(c, q) {
      const m = lineAt(q, ["line"]);
      if (!m) return toast("Click a drafting line (lines from L or exploded shapes)");
      if (!c.step) { c.data.first = { m, q }; c.step = 1; return "prompt"; }
      if (m.id === c.data.first.m.id) return toast("Click a different line");
      filletLines(c.data.first, { m, q }, c.data.r);
      return "again";
    },
  },
  join: { label: "Join", needsSel: true, run() { joinSelection(); } },
  explode: { label: "Explode", needsSel: true, run() { explodeSelection(); } },
  break: {
    label: "Break", prompt: (c) => c.step ? "Break: click the second point (or type @ to split at the first point)." : "Break: click the first point on a drafting line or polyline.",
    point(c, q) {
      if (!c.step) { const m = lineAt(q, LINE_KINDS); if (!m) return toast("Click on a drafting line or polyline"); c.data = { m, a: q }; c.step = 1; return "prompt"; }
      breakBetween(c.data.m, c.data.a, q); return "done";
    },
    value(c, t) { if (c.step && t.trim() === "@") { breakBetween(c.data.m, c.data.a, c.data.a); return "done"; } return toast("Type @ to split at the first point"); },
  },
  matchprop: {
    label: "Match properties", prompt: (c) => c.step ? "Match properties: click the drafting to change (Esc ends)." : "Match properties: click the source drafting.",
    point(c, q) {
      const m = lineAt(q, null);
      if (!m) return toast("Click on drafting");
      if (!c.step) { c.data.src = m; c.step = 1; return "prompt"; }
      const s = c.data.src;
      Object.assign(m, { colour: s.colour, layer: s.layer, size: s.size, ...(m.kind === "polyline" && m.closed || m.kind === "circle" ? { fill: s.fill } : {}) });
      changed(); return "prompt";
    },
  },
};
const ALIASES = {
  L: ["draw", "line"], LINE: ["draw", "line"], PL: ["draw", "pline"], PLINE: ["draw", "pline"], REC: ["draw", "rect"], RECTANG: ["draw", "rect"],
  C: ["draw", "circle"], CIRCLE: ["draw", "circle"], T: ["draw", "text"], DT: ["draw", "text"], MT: ["draw", "text"], TEXT: ["draw", "text"],
  LE: ["draw", "leader"], LEADER: ["draw", "leader"], DAL: ["draw", "dim"], DIM: ["draw", "dim"], DIMALIGNED: ["draw", "dim"],
  AA: ["draw", "area"], AREA: ["draw", "area"], ID: ["draw", "id"], DI: ["tool", "measure"], DIST: ["tool", "measure"],
  A: ["cmd", "arc"], ARC: ["cmd", "arc"], POL: ["cmd", "polygon"], POLYGON: ["cmd", "polygon"], PO: ["cmd", "point"], POINT: ["cmd", "point"],
  H: ["cmd", "hatch"], HATCH: ["cmd", "hatch"], DLI: ["cmd", "dimlinear"], DIMLINEAR: ["cmd", "dimlinear"], DRA: ["cmd", "dimradius"],
  DIMRADIUS: ["cmd", "dimradius"], DAN: ["cmd", "dimangular"], DIMANGULAR: ["cmd", "dimangular"],
  SC: ["cmd", "scale"], SCALE: ["cmd", "scale"], MI: ["cmd", "mirror"], MIRROR: ["cmd", "mirror"], AR: ["cmd", "array"], ARRAY: ["cmd", "array"],
  ARRAYRECT: ["cmd", "array"], ARRAYPOLAR: ["cmd", "arraypolar"], ARP: ["cmd", "arraypolar"], TR: ["cmd", "trim"], TRIM: ["cmd", "trim"],
  EX: ["cmd", "extend"], EXTEND: ["cmd", "extend"], F: ["cmd", "fillet"], FILLET: ["cmd", "fillet"], J: ["cmd", "join"], JOIN: ["cmd", "join"],
  X: ["cmd", "explode"], EXPLODE: ["cmd", "explode"], BR: ["cmd", "break"], BREAK: ["cmd", "break"], MA: ["cmd", "matchprop"], MATCHPROP: ["cmd", "matchprop"],
  M: ["op", "move"], MOVE: ["op", "move"], CO: ["op", "copy"], CP: ["op", "copy"], COPY: ["op", "copy"], RO: ["op", "rotate"], ROTATE: ["op", "rotate"],
  O: ["op", "offset"], OFFSET: ["op", "offset"], E: ["do", "erase"], ERASE: ["do", "erase"], DEL: ["do", "erase"], U: ["do", "undo"], UNDO: ["do", "undo"],
  REDO: ["do", "redo"], LA: ["do", "layers"], LAYER: ["do", "layers"], Z: ["zoom"], ZOOM: ["zoom"], OS: ["do", "osnap"], OSNAP: ["do", "osnap"],
  ORTHO: ["do", "ortho"], SNAP: ["do", "snap"], SELECT: ["tool", "select"], W: ["tool", "window"], HELP: ["do", "help"], "?": ["do", "help"],
};

function cadCommand(name) {
  const spec = CMDS[name];
  if (!spec) return;
  if (spec.needsSel && !CAD.sel.length) return toast(`${spec.label}: select what to ${spec.label.toLowerCase()} first`);
  if (CAD.tool) setCadTool(CAD.tool);
  cadEnd();
  if (spec.run) { spec.run(); CAD.lastCmd = name; return; }
  CAD.cmd = { name, step: 0, data: { pts: [] } };
  spec.start?.(CAD.cmd);
  CAD.lastCmd = name;
  cmdPrompt();
}
function cmdPrompt() { const c = CAD.cmd; if (c) cadMsg(`${CMDS[c.name].prompt(c)}`); }
function cmdEnd() {
  CAD.cmd = null; CAD.cmdFrom = null;
  const g = $("#cadPreview"); if (g) g.innerHTML = "";
  cadMsg("");
}
function cmdResult(r) {
  if (r === "done") return cmdEnd();
  if (r === "again") { const n = CAD.cmd?.name; CAD.cmd = { name: n, step: 0, data: { pts: [], ...(CAD.cmd?.data.sides ? { sides: CAD.cmd.data.sides } : {}), ...(CAD.cmd?.data.r !== undefined ? { r: CAD.cmd.data.r } : {}) } }; }
  cmdPrompt();
}

function cmdSnapPoint(p) {  // snapped (unless typed), with Ortho from the previous point
  if (CAD.typed) return [p.x, p.y];
  const sn = cadSnap(p, new Set());
  let q = sn ? [sn.x, sn.y] : [p.x, p.y];
  const from = snapFrom();
  if (from && PREFS.cad_ortho && !sn) q = Math.abs(q[0] - from[0]) >= Math.abs(q[1] - from[1]) ? [q[0], from[1]] : [from[0], q[1]];
  return q;
}
// called by overview.js for clicks and typed points while a command runs
function cadCmdPoint(p) {
  const c = CAD.cmd, spec = CMDS[c.name];
  if (!spec.point) return toast(`${spec.label}: type the value and press Enter`);
  const q = cmdSnapPoint(p);
  CAD.cmdFrom = q;
  cmdResult(spec.point(c, q));
}
function cadCmdHover(p, g) {
  g.innerHTML = "";
  const c = CAD.cmd, spec = CMDS[c.name];
  if (!CAD.typed && PREFS.cad_snap) { const sn = cadSnap(p, new Set()); if (sn) CAD.snapMark?.(sn); }
  spec.hover?.(c, cmdSnapPoint(p), g);
}
function previewLine(g, P) {
  el("polyline", { points: P.map((q) => q.join(",")).join(" "), stroke: $("#cadColour").value || "#00e5ff", "stroke-width": 1.5,
    "stroke-dasharray": "5 4", "vector-effect": "non-scaling-stroke", fill: "none" }, g);
}
function polygonPts(c, corner, n) {
  const r = len(sub(corner, c)), a0 = Math.atan2(corner[1] - c[1], corner[0] - c[0]);
  return Array.from({ length: n }, (_, k) => [c[0] + r * Math.cos(a0 + 2 * Math.PI * k / n), c[1] + r * Math.sin(a0 + 2 * Math.PI * k / n)]);
}
function inPoly(q, P) {
  let inside = false;
  for (let i = 0, j = P.length - 1; i < P.length; j = i++) {
    if ((P[i][1] > q[1]) !== (P[j][1] > q[1]) && q[0] < (P[j][0] - P[i][0]) * (q[1] - P[i][1]) / (P[j][1] - P[i][1]) + P[i][0]) inside = !inside;
  }
  return inside;
}
function closedAt(q) {  // the smallest closed drafting shape containing (or touching) the point
  const hits = [];
  for (const M of CAD.feats.marks || []) {
    if (M.locked || !M.closed) continue;
    const m = markupById(M.id);
    const inside = M.kind === "circle" ? len(sub(q, M.centre)) <= M.r : inPoly(q, M.pts);
    const on = M.segs.some(([a, b]) => segDist({ x: q[0], y: q[1] }, a, b) <= 8 * cadPx());
    if (inside || on) hits.push([M.kind === "circle" ? Math.PI * M.r * M.r : polyArea(M.pts), m]);
  }
  hits.sort((a, b) => a[0] - b[0]);
  return hits[0]?.[1] || null;
}
function lineAt(q, kinds) {  // the nearest drafting of these kinds at the point (network features are not in the way)
  const tol = 8 * cadPx(), P = { x: q[0], y: q[1] };
  let best = null;
  for (const M of CAD.feats.marks || []) {
    if (M.locked || (kinds && !kinds.includes(M.kind))) continue;
    for (const [a, b] of M.segs) { const d = segDist(P, a, b); if (d <= tol && (!best || d < best.d)) best = { d, id: M.id }; }
  }
  return best ? markupById(best.id) : null;
}

// ---- trim / extend / break: drafting lines and polylines, cut at their crossings with other lines -------------
function pathOf(m) { const P = xyOf(m); return m.kind === "polyline" && m.closed ? [...P, P[0]] : P; }
function along(P, q) {  // distance along a path of the point on it nearest q
  let best = Infinity, at = 0, s = 0;
  for (let k = 1; k < P.length; k++) {
    const a = P[k - 1], b = P[k], d = sub(b, a), L = len(d) || 1e-9;
    const t = Math.max(0, Math.min(1, ((q[0] - a[0]) * d[0] + (q[1] - a[1]) * d[1]) / (L * L)));
    const dd = len(sub(q, [a[0] + t * d[0], a[1] + t * d[1]]));
    if (dd < best) { best = dd; at = s + t * L; }
    s += L;
  }
  return at;
}
function pathLength(P) { let s = 0; for (let k = 1; k < P.length; k++) s += len(sub(P[k], P[k - 1])); return s; }
function cutPath(P, s0, s1) {  // the part of a path between distances s0 and s1
  const out = [];
  let s = 0;
  for (let k = 1; k < P.length; k++) {
    const a = P[k - 1], b = P[k], L = len(sub(b, a));
    const at = (t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
    if (s + L >= s0 && s <= s1 && L > 0) {
      if (!out.length) out.push(at(Math.max(0, (s0 - s) / L)));
      out.push(at(Math.min(1, (s1 - s) / L)));
    }
    s += L;
  }
  return out.filter((p, i, A) => !i || len(sub(p, A[i - 1])) > 1e-6);
}
function crossings(m, P) {  // distances along the path where other drafting and the cables cross it
  const edges = [];
  for (const M of CAD.feats.marks || []) if (M.id !== m.id && M.kind !== "text" && M.kind !== "point") edges.push(...M.segs);
  for (const L of CAD.feats.lines) L.pts.slice(1).forEach((q, k) => edges.push([L.pts[k], q]));
  const out = [];
  let s = 0;
  for (let k = 1; k < P.length; k++) {
    const a = P[k - 1], b = P[k], L = len(sub(b, a));
    for (const [c, d] of edges) { const x = segCross(a, b, c, d); if (x) out.push(s + len(sub(x, a))); }
    s += L;
  }
  return out.sort((x, y) => x - y);
}
function replaceMarkup(m, parts) {  // parts: point lists in drawing coordinates; the first keeps the id
  const i = S.D.markups.indexOf(m);
  const made = parts.filter((P) => P.length >= 2).map((P) => ({
    ...JSON.parse(JSON.stringify(m)), closed: false, kind: P.length === 2 && m.kind === "line" ? "line" : "polyline", points: ptsLatLon(P) }));
  S.D.markups.splice(i, 1);
  made.forEach((x, k) => { x.id = k ? nextMarkupId() : m.id; S.D.markups.push(x); });  // the first keeps the id
  CAD.sel = []; S.sel = null;
  changed();
}
function trimAt(q) {
  const m = lineAt(q, LINE_KINDS);
  if (!m) return toast("Click the part of a drafting line or polyline to cut away");
  const P = pathOf(m), L = pathLength(P), s0 = along(P, q), xs = crossings(m, P).filter((s) => s > 1e-6 && s < L - 1e-6);
  const closed = m.kind === "polyline" && m.closed;
  const lo = Math.max(0, ...xs.filter((s) => s < s0)), hi = Math.min(L, ...xs.filter((s) => s > s0));
  if (closed) {
    if (xs.length < 2) return toast("A closed shape needs two crossings to trim between");
    const a = xs.filter((s) => s < s0).pop() ?? xs[xs.length - 1], b = xs.find((s) => s > s0) ?? xs[0];
    const keep = b > a ? [...cutPath(P, b, L), ...cutPath(P, 0, a).slice(1)] : cutPath(P, b, a);
    return replaceMarkup(m, [keep]);
  }
  if (!xs.length) return toast("Nothing crosses this line: delete it instead (Del)");
  replaceMarkup(m, [lo > 1e-6 ? cutPath(P, 0, lo) : [], hi < L - 1e-6 ? cutPath(P, hi, L) : []]);
}
function extendAt(q) {
  const m = lineAt(q, LINE_KINDS);
  if (!m || (m.kind === "polyline" && m.closed)) return toast("Click near the end of an open drafting line or polyline");
  const P = xyOf(m), atStart = len(sub(q, P[0])) < len(sub(q, P[P.length - 1]));
  const end = atStart ? P[0] : P[P.length - 1], prev = atStart ? P[1] : P[P.length - 2];
  const dir = sub(end, prev), dl = len(dir);
  if (!dl) return;
  const far = [end[0] + dir[0] / dl * 1e5, end[1] + dir[1] / dl * 1e5];
  let best = null;
  const edges = [];
  for (const M of CAD.feats.marks || []) if (M.id !== m.id && M.kind !== "text" && M.kind !== "point") edges.push(...M.segs);
  for (const L of CAD.feats.lines) L.pts.slice(1).forEach((p, k) => edges.push([L.pts[k], p]));
  for (const [c, d] of edges) { const x = segCross(end, far, c, d); if (x && len(sub(x, end)) > 1e-6 && (!best || len(sub(x, end)) < len(sub(best, end)))) best = x; }
  if (!best) return toast("No line to extend to in that direction");
  P[atStart ? 0 : P.length - 1] = best;
  m.points = ptsLatLon(P);
  changed();
}
function breakBetween(m, a, b) {
  const P = pathOf(m), L = pathLength(P);
  let s0 = along(P, a), s1 = along(P, b);
  if (s0 > s1) [s0, s1] = [s1, s0];
  if (m.kind === "polyline" && m.closed) return replaceMarkup(m, [[...cutPath(P, s1, L), ...cutPath(P, 0, s0).slice(1)]]);
  replaceMarkup(m, [cutPath(P, 0, s0), cutPath(P, s1, L)]);
}

// ---- fillet / join / explode -----------------------------------------------------------------------------
function filletLines(A, B, r) {
  const [a1, a2] = xyOf(A.m), [b1, b2] = xyOf(B.m);
  const d1 = sub(a2, a1), d2 = sub(b2, b1), den = d1[0] * d2[1] - d1[1] * d2[0];
  if (Math.abs(den) < 1e-12) return toast("The lines are parallel");
  const t = ((b1[0] - a1[0]) * d2[1] - (b1[1] - a1[1]) * d2[0]) / den, X = [a1[0] + t * d1[0], a1[1] + t * d1[1]];
  // each line keeps the end on the side of the corner that was clicked
  const keepA = dot(sub(A.q, X), sub(a1, X)) > 0 ? a1 : a2;
  const keepB = dot(sub(B.q, X), sub(b1, X)) > 0 ? b1 : b2;
  const ua = unit(sub(keepA, X)), ub = unit(sub(keepB, X));
  if (r <= 0) {
    A.m.points = ptsLatLon([keepA, X]); B.m.points = ptsLatLon([X, keepB]);
    return changed();
  }
  const half = Math.acos(Math.max(-1, Math.min(1, dot(ua, ub)))) / 2, dist = r / Math.tan(half);
  if (dist > len(sub(keepA, X)) || dist > len(sub(keepB, X))) return toast("The radius is too large for these lines");
  const ta = [X[0] + ua[0] * dist, X[1] + ua[1] * dist], tb = [X[0] + ub[0] * dist, X[1] + ub[1] * dist];
  const bis = unit([ua[0] + ub[0], ua[1] + ub[1]]), cd = r / Math.sin(half), ctr = [X[0] + bis[0] * cd, X[1] + bis[1] * cd];
  const mid = [ctr[0] - bis[0] * r, ctr[1] - bis[1] * r];
  A.m.points = ptsLatLon([keepA, ta]); B.m.points = ptsLatLon([tb, keepB]);
  addMarkup("arc", [ta, mid, tb], { colour: A.m.colour, layer: A.m.layer });
}
const dot = (a, b) => a[0] * b[0] + a[1] * b[1];
const unit = (v) => { const l = len(v) || 1; return [v[0] / l, v[1] / l]; };
function joinSelection() {
  const ms = CAD.sel.filter((s) => s.type === "markup").map((s) => markupById(s.id)).filter((m) => m && LINE_KINDS.includes(m.kind) && !(m.kind === "polyline" && m.closed));
  if (ms.length < 2) return toast("Join: select two or more open drafting lines or polylines that meet end to end");
  const tol = Math.max(0.05, 3 * cadPx());
  let chain = xyOf(ms[0]);
  const rest = ms.slice(1).map((m) => ({ m, P: xyOf(m) }));
  let grew = true;
  while (grew && rest.length) {
    grew = false;
    for (let i = 0; i < rest.length; i++) {
      const P = rest[i].P, s = chain[0], e = chain[chain.length - 1];
      let add = null;
      if (len(sub(P[0], e)) <= tol) add = () => { chain = [...chain, ...P.slice(1)]; };
      else if (len(sub(P[P.length - 1], e)) <= tol) add = () => { chain = [...chain, ...P.slice(0, -1).reverse()]; };
      else if (len(sub(P[P.length - 1], s)) <= tol) add = () => { chain = [...P.slice(0, -1), ...chain]; };
      else if (len(sub(P[0], s)) <= tol) add = () => { chain = [...P.slice(1).reverse(), ...chain]; };
      if (add) { add(); rest.splice(i, 1); grew = true; break; }
    }
  }
  const closed = len(sub(chain[0], chain[chain.length - 1])) <= tol && chain.length > 3;
  if (closed) chain.pop();
  const joined = new Set(ms.filter((m) => !rest.some((r) => r.m === m)).map((m) => m.id));
  const first = ms[0];
  S.D.markups = S.D.markups.filter((m) => m === first || !joined.has(m.id));
  Object.assign(first, { kind: "polyline", closed, points: ptsLatLon(chain) });
  CAD.sel = [{ type: "markup", id: first.id }]; S.sel = null;
  changed();
  toast(`Joined ${joined.size}${rest.length ? `; ${rest.length} did not touch the chain` : ""}`);
}
function explodeSelection() {
  const ms = CAD.sel.filter((s) => s.type === "markup").map((s) => markupById(s.id)).filter(Boolean);
  let n = 0;
  for (const m of ms) {
    const P = xyOf(m), base = JSON.parse(JSON.stringify(m)), parts = [];
    if (m.kind === "polyline") { const Q = m.closed ? [...P, P[0]] : P; for (let k = 1; k < Q.length; k++) parts.push({ kind: "line", pts: [Q[k - 1], Q[k]] }); }
    else if (m.kind === "leader") { for (let k = 1; k < P.length; k++) parts.push({ kind: "line", pts: [P[k - 1], P[k]] }); if (m.text) parts.push({ kind: "text", pts: [P[P.length - 1]], text: m.text }); }
    else if (m.kind === "dimension") {
      const dg = dimGeometry(m.dim || "aligned", P, m.size * 1.5);
      dg.lines.forEach(([a, b]) => parts.push({ kind: "line", pts: [a, b] }));
      parts.push({ kind: "text", pts: [dg.text], text: dimLabel(m, dg.value) });
    } else continue;
    S.D.markups = S.D.markups.filter((x) => x !== m);
    for (const p of parts) S.D.markups.push({ ...base, id: nextMarkupId(), kind: p.kind, points: ptsLatLon(p.pts), closed: false, fill: "", text: p.text || "", dim: "aligned" });
    n++;
  }
  if (!n) return toast("Explode works on drafting polylines, rectangles, polygons, leaders and dimensions");
  CAD.sel = []; S.sel = null;
  changed();
  toast(`Exploded ${n}`);
}

// ---- layer manager --------------------------------------------------------------------------------------
function renderLayers() {
  const box = $("#cadProps");
  box.hidden = false;
  const L = (S.D.cad_layers ||= []), cur = CAD.curLayer || "0";
  const count = (name) => (S.D.markups || []).filter((m) => (m.layer || "0") === name).length;
  box.innerHTML = `<h3>Drafting layers</h3><table class="cadlayers"><tr><th>Current</th><th>Name</th><th></th><th title="Visible">On</th><th title="Locked">Lock</th><th class="num">Items</th><th></th></tr>
    <tr><td><input type="radio" name="curlay" value="0" ${cur === "0" ? "checked" : ""}></td><td>0</td><td></td><td></td><td></td><td class="num">${count("0")}</td><td></td></tr>` +
    L.map((l, i) => `<tr><td><input type="radio" name="curlay" value="${esc(l.name)}" ${cur === l.name ? "checked" : ""}></td>
      <td><input data-ln="${i}" value="${esc(l.name)}" maxlength="40"></td><td><input data-lc="${i}" type="color" value="${esc(l.colour)}"></td>
      <td><input data-lv="${i}" type="checkbox" ${l.visible ? "checked" : ""}></td><td><input data-ll="${i}" type="checkbox" ${l.locked ? "checked" : ""}></td>
      <td class="num">${count(l.name)}</td><td><button data-ld="${i}" title="Delete the layer (its drafting moves to 0)">&times;</button></td></tr>`).join("") +
    `</table><div class="row"><input id="newLayer" maxlength="40" placeholder="new layer name"><button id="addLayer">Add</button><span class="spacer"></span><button id="closeLayers">Close</button></div>
    <p class="muted">New drafting goes on the current layer in its colour. Hidden layers are left out of the drawing, PDF and DXF; locked ones cannot be picked. In the DXF each is a layer of its own.</p>`;
  const save = () => { changed(); renderLayers(); };
  $$("[name=curlay]", box).forEach((r) => r.addEventListener("change", () => {
    CAD.curLayer = r.value;
    const l = cadLayer(r.value); if (l) $("#cadColour").value = l.colour;
    toast(`Current layer: ${r.value}`);
  }));
  $$("[data-ln]", box).forEach((inp) => inp.addEventListener("change", () => {
    const l = L[+inp.dataset.ln], v = inp.value.trim();
    if (!v || v === "0" || L.some((x) => x !== l && x.name === v)) { toast("Layer names must be unique and not 0"); return renderLayers(); }
    (S.D.markups || []).forEach((m) => { if (m.layer === l.name) m.layer = v; });
    if (CAD.curLayer === l.name) CAD.curLayer = v;
    l.name = v; save();
  }));
  $$("[data-lc]", box).forEach((inp) => inp.addEventListener("change", () => { L[+inp.dataset.lc].colour = inp.value; save(); }));
  $$("[data-lv]", box).forEach((inp) => inp.addEventListener("change", () => { L[+inp.dataset.lv].visible = inp.checked; save(); }));
  $$("[data-ll]", box).forEach((inp) => inp.addEventListener("change", () => { L[+inp.dataset.ll].locked = inp.checked; save(); }));
  $$("[data-ld]", box).forEach((b) => b.addEventListener("click", () => {
    const l = L[+b.dataset.ld];
    (S.D.markups || []).forEach((m) => { if (m.layer === l.name) m.layer = "0"; });
    if (CAD.curLayer === l.name) CAD.curLayer = "0";
    L.splice(+b.dataset.ld, 1); save();
  }));
  $("#addLayer", box).onclick = () => {
    const v = $("#newLayer", box).value.trim();
    if (!v || v === "0" || L.some((x) => x.name === v)) return toast("Type a new, unique layer name");
    L.push({ name: v, colour: $("#cadColour").value || "#00e5ff", visible: true, locked: false });
    CAD.curLayer = v; save();
  };
  $("#closeLayers", box).onclick = () => { box.hidden = !CAD.sel.length; renderCadProps(); };
}

// ---- command line -----------------------------------------------------------------------------------------
function parsePoint(t) {
  // "x,y" or "dist<angle" from the drawing origin (metres, Y north, angles counter-clockwise from east);
  // with @ in front, from the previous point
  const rel = t.startsWith("@"), s = rel ? t.slice(1) : t;
  let m = s.match(/^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$/), v = null;
  if (m) v = [+m[1], -+m[2]];
  else if ((m = s.match(/^(\d+(?:\.\d+)?)\s*<\s*(-?\d+(?:\.\d+)?)$/))) { const a = +m[2] * Math.PI / 180; v = [+m[1] * Math.cos(a), -+m[1] * Math.sin(a)]; }
  if (!v) return null;
  if (!rel) return v;
  const from = snapFrom();
  if (!from) { toast("No previous point for @: click or type the first point"); return null; }
  return [from[0] + v[0], from[1] + v[1]];
}
function feedPoint(q) {
  CAD.typed = true;
  try { if (!CAD.toolPoint?.({ x: q[0], y: q[1] })) toast("Start a command first (type L, PL, C, M...)"); }
  finally { CAD.typed = false; }
}
function runCommandLine(raw) {
  const t = raw.trim(), T = t.toUpperCase();
  if (!t) {  // Enter: finish the command in progress, or repeat the last one
    if (CAD.cmd) { const s = CMDS[CAD.cmd.name]; return s.enter ? cmdResult(s.enter(CAD.cmd)) : cmdEnd(); }
    if (DRAW[CAD.tool]) return drawFinish(false);
    return CAD.lastCmd ? cadCommand(CAD.lastCmd) : null;
  }
  if (/[,<]/.test(t) || (t.startsWith("@") && t.length > 1)) {
    const pt = parsePoint(t);
    return pt ? feedPoint(pt) : CAD.cmd || CAD.op || DRAW[CAD.tool] ? null : toast(`Not a point: ${t}`);
  }
  if (CAD.cmd && CMDS[CAD.cmd.name].value && !ALIASES[T]) return cmdResult(CMDS[CAD.cmd.name].value(CAD.cmd, t));
  if (/^-?\d+(\.\d+)?$/.test(t)) {  // a number: angle, offset, or a distance along the cursor from the previous point
    if (CAD.op?.kind === "rotate" && CAD.op.base) return CAD.applyAngle(+t);
    if (CAD.op?.kind === "offset") { $("#cadDist").value = t; return cadMsg("Offset: now click the side to offset to."); }
    const from = snapFrom(), cur = CAD.cursor;
    if (from && cur) { const u = unit(sub(cur, from)); return feedPoint([from[0] + u[0] * +t, from[1] + u[1] * +t]); }
    return toast("Type a command, or a point as x,y");
  }
  const a = ALIASES[T] || (T.startsWith("Z ") || T.startsWith("ZOOM ") ? ["zoom"] : null);
  if (!a) return toast(`Unknown command "${t}" (type ? for the list)`);
  if (CAD.cmd) cmdEnd();
  if (a[0] === "draw" || a[0] === "tool") { if (CAD.tool !== a[1]) setCadTool(a[1]); return; }
  if (a[0] === "cmd") return cadCommand(a[1]);
  if (a[0] === "op") return cadStart(a[1]);
  if (a[0] === "zoom") {
    const o = T.split(/\s+/)[1] || "E";
    if (o === "E" || o === "A") return $("#lldFit").click();
    if (o === "W") return setCadTool("window");
    if (o === "P" && CAD.prevVb) { [CAD.vb, CAD.prevVb] = [CAD.prevVb, [...CAD.vb]]; return renderLld(); }
    return toast("Zoom: Z E (extents), Z W (window), Z P (previous)");
  }
  ({ erase: cadDelete, undo, redo, layers: renderLayers, ortho: () => $("#cadOrtho").click(), snap: () => $("#cadSnap").click(),
     osnap: () => { const d = $("#cadOsnap"); if (d) d.open = !d.open; },
     help: () => cadMsg("Draw: L PL REC POL C A PO T LE H · Dim: DAL DLI DRA DAN · Modify: M CO RO SC MI AR ARP O TR EX F J X BR MA E · " +
       "Inquiry: DI AREA ID · LA layers · Z E/W/P · U REDO · points: x,y  @dx,dy  @dist<angle  or a distance") })[a[1]]?.();
}

const cmdInput = $("#cadCmd");
cmdInput?.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" && e.key !== "Escape") return;
  e.preventDefault(); e.stopPropagation();  // the drawing's own Enter / Esc shortcuts must not run as well
  if (e.key === "Enter") { const v = cmdInput.value; cmdInput.value = ""; runCommandLine(v); }
  else { cmdInput.value = ""; if (CAD.cmd) cmdEnd(); else if (CAD.op) cadEnd(); else if (CAD.tool) setCadTool(CAD.tool); }
});
// typing in the drawing tab goes to the command line, as in AutoCAD
document.addEventListener("keydown", (e) => {
  if (activeTab() !== "lld" || e.ctrlKey || e.metaKey || e.altKey || !cmdInput) return;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
  if (e.key === "Escape" && CAD.cmd) { cmdEnd(); return; }
  if (e.key === "Enter" && CAD.cmd) { e.preventDefault(); return runCommandLine(""); }
  if (e.key.length === 1 && /[A-Za-z0-9@.,<\-?]/.test(e.key) && !(DRAW[CAD.tool] && /[cC]/.test(e.key) && CAD.tool === "pline")) {
    if (!CAD.cmd && !CAD.op && !DRAW[CAD.tool] && /^[mMrR]$/.test(e.key)) return;  // M and R keep starting Move / Rotate
    cmdInput.focus();
  }
}, true);

// buttons for the new tools and the Osnap list
$$("[data-cmd]").forEach((b) => { b.onclick = () => cadCommand(b.dataset.cmd); });
$("#cadLayers")?.addEventListener("click", renderLayers);
function renderOsnap() {
  const box = $("#cadOsnapList");
  if (!box) return;
  const cur = PREFS.cad_osnap || { end: 1, mid: 1, cen: 1, int: 1, perp: 1 };
  box.innerHTML = OSNAP.map(([k, t]) => `<label><input type="checkbox" data-os="${k}" ${cur[k] ? "checked" : ""}> ${t}</label>`).join("");
  $$("[data-os]", box).forEach((cb) => cb.addEventListener("change", () => {
    PREFS.cad_osnap = { ...cur, [cb.dataset.os]: cb.checked ? 1 : 0 }; savePrefs(); renderOsnap();
  }));
}
renderOsnap();
